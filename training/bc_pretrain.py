#!/usr/bin/env python
"""bc_pretrain.py — behavioral-cloning pretraining from FUMBBL .bbp pairs.

Supervised warm-start for PPO: streams the (obs, mask, action) records that
`bb_lockstep --dump-pairs` extracted from real FUMBBL replays
(validation/extract_pairs.py; format documented in tools/bb_lockstep.c and
validation/README.md), builds THE SAME policy the trainer uses, and trains
masked cross-entropy on the three action heads (type 30 | arg 33 | sq 391).

Policy construction mirrors pufferlib.torch_pufferl.load_policy exactly —
the classes come from pufferlib.models and the hyperparameters from the
[policy]/[torch] sections of config/bloodbowl.ini layered over PufferLib's
default.ini, so the checkpoint state_dict is key-for-key what
PuffeRL.save_weights writes and `puffer train bloodbowl --load-model-path
<bc.bin>` warm-starts from it directly. The save->load round-trip through
the real pufferlib.torch_pufferl.PuffeRL.load_weights is verified after
every save.

DATA PATH: shard headers and embedded replay IDs are validated up front, but
record bodies remain file-backed. Training copies only one sampled mini-batch
to the accelerator; validation walks held-out shards batchwise. A bounded LRU
limits simultaneously open memmaps. The default sampler chooses a replay
uniformly, then a record within it, preventing long/easy-to-map replays from
dominating solely because they produced more pairs. Use
``--sampling record-weighted`` for the historical uniform-record objective.
The legacy ``load_shards`` function remains as an explicitly in-memory API for
small tools and tests.

Loss: per head, logits are masked with the record's stored 454-bit legality
mask (additive -1e9 on illegal entries) before softmax; the three CE terms
are summed. Reported: per-head accuracy (masked argmax == target) and top-1
legal-action match (all three heads correct at once).

BACKEND NOTE: this matches the TORCH backend's checkpoint layout
(PuffeRL.save_weights == torch.save(state_dict)); `puffer train ... --slowly
--load-model-path bc.bin` (and any CPU-only _C build, where load_policy
reads it at create time) warm-starts directly. The CUDA backend's
save/load_weights (src/bindings.cu) is a raw flat-fp32 master_weights blob
in CUDA parameter order — convert with training/convert_checkpoint.py
(`--to-cuda bc.bin -o bc_cuda.bin`) and warm-start the native backend via
the local load_model_path patch in pufferl.py. Note the CUDA layers carry
no bias terms, so the converter drops the torch biases (warned).

v0 LIMITATION — iid samples, zero recurrent state: each record is treated
as an independent sample and the MinGRU state is zeroed, so the network
only learns the zero-state map obs->action. Sequence-BC (replay-ordered
windows carrying recurrent state, matching PPO's rollout treatment) is v1;
it needs the same shards, just grouped by (replay_id, agent) and sorted by
cmd — the fields are already in the records.

Run with the PufferLib venv (torch):
  vendor/PufferLib/.venv/bin/python training/bc_pretrain.py
  vendor/PufferLib/.venv/bin/python training/bc_pretrain.py \\
      --replay-ids validation/bb2025-replay-ids.txt \\
      --steps 500 --batch-size 256 --device cuda \\
      --out training/checkpoints/bc.bin
"""

import argparse
import ast
import configparser
import glob
import hashlib
import os
import struct
import sys
import types
from collections import OrderedDict
from dataclasses import dataclass

import numpy as np
import torch
import torch.nn.functional as F

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "vendor", "PufferLib"))

# Mirrors ACT_SIZES in puffer/bloodbowl/binding.c (asserted against the .bbp
# header's mask_size below — the shards only pin the sum).
ACT_SIZES = (30, 33, 391)
MAGIC = b"BBP1"
KNOWN_VERSIONS = (1, 2, 3)  # BBP v3 is the semantic obs-v5 marker. Historical
                            # v2/2782 is obs-v4 and must not mix with v3/2782.
HEADER_LEN = 16
REPLAY_ID_SCAN_BATCH = 65_536


def rec_dtype(obs_size, mask_size):
    """Return the header-driven BBP record layout.

    Legacy shards remain readable, but an index rejects mixed header versions
    or shapes. Version is load-bearing because BBP v2/2782 is obs-v4 while
    BBP v3/2782 is same-shape obs-v5.
    """
    return np.dtype([
        ("replay", "<u4"), ("cmd", "<u4"), ("agent", "u1"), ("pad", "u1", (3,)),
        ("obs", "u1", (obs_size,)), ("mask", "u1", (mask_size,)),
        ("type", "u1"), ("arg", "u1"), ("sq", "<u2"),
    ])


@dataclass(frozen=True)
class ShardInfo:
    replay_id: int
    path: str
    version: int
    obs_size: int
    mask_size: int
    record_count: int
    record_size: int

    @property
    def body_bytes(self):
        return self.record_count * self.record_size


def _selected_shard_paths(pair_dir, replay_ids=None):
    """Discover numeric shards and apply an exact replay-ID allowlist."""
    pair_dir = os.fspath(pair_dir)
    paths = sorted(glob.glob(os.path.join(pair_dir, "*.bbp")))
    if not paths:
        raise SystemExit(f"no .bbp shards in {pair_dir} — "
                         "run validation/extract_pairs.py first")
    by_id = {}
    for path in paths:
        try:
            replay_id = int(os.path.splitext(os.path.basename(path))[0])
        except ValueError as exc:
            raise SystemExit(
                f"{path}: .bbp shard filename must be a numeric replay ID") from exc
        if replay_id in by_id:
            raise SystemExit(f"duplicate .bbp shard for replay {replay_id}")
        by_id[replay_id] = path

    if replay_ids is None:
        selected = sorted(by_id)
    else:
        requested = frozenset(int(replay_id) for replay_id in replay_ids)
        if not requested:
            raise SystemExit("replay-ID allowlist is empty")
        missing = sorted(requested - set(by_id))
        if missing:
            preview = ", ".join(str(x) for x in missing[:8])
            suffix = " ..." if len(missing) > 8 else ""
            raise SystemExit(
                f"missing {len(missing)} requested replay shard(s) in "
                f"{pair_dir}: {preview}{suffix}")
        selected = sorted(requested)
    return [(replay_id, by_id[replay_id]) for replay_id in selected]


def _close_memmap(array):
    mmap = getattr(array, "_mmap", None)
    if mmap is not None:
        mmap.close()


def _read_shard_info(path, replay_id):
    """Validate one shard without retaining or reading its body wholesale."""
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            header = f.read(HEADER_LEN)
    except OSError as exc:
        raise SystemExit(f"cannot read .bbp shard {path}: {exc}") from exc
    if len(header) != HEADER_LEN:
        raise SystemExit(f"{path}: truncated .bbp header")
    magic, version, obs_size, mask_size = struct.unpack("<4sIII", header)
    if magic != MAGIC or version not in KNOWN_VERSIONS:
        raise SystemExit(f"{path}: bad header {magic} v{version}")
    if obs_size == 0:
        raise SystemExit(f"{path}: observation size must be positive")
    if mask_size != sum(ACT_SIZES):
        raise SystemExit(
            f"{path}: mask size {mask_size} != action size {sum(ACT_SIZES)}")
    dtype = rec_dtype(obs_size, mask_size)
    body_bytes = size - HEADER_LEN
    if body_bytes < 0 or body_bytes % dtype.itemsize:
        raise SystemExit(
            f"{path}: body size {max(body_bytes, 0)} is not a whole number "
            f"of {dtype.itemsize}-byte records")
    record_count = body_bytes // dtype.itemsize

    # Validate embedded replay IDs in bounded chunks. A memmap reserves address
    # space only; it does not copy the multi-GB corpus into process memory.
    if record_count:
        shard = np.memmap(path, dtype=dtype, mode="r", offset=HEADER_LEN,
                          shape=(record_count,))
        try:
            for start in range(0, record_count, REPLAY_ID_SCAN_BATCH):
                stop = min(start + REPLAY_ID_SCAN_BATCH, record_count)
                if not np.all(shard["replay"][start:stop] == replay_id):
                    raise SystemExit(
                        f"{path}: record replay IDs do not match shard "
                        f"filename {replay_id}")
        finally:
            _close_memmap(shard)
    return ShardInfo(
        replay_id=replay_id,
        path=path,
        version=version,
        obs_size=obs_size,
        mask_size=mask_size,
        record_count=record_count,
        record_size=dtype.itemsize,
    )


class ShardIndex:
    """Metadata-only corpus index with a bounded LRU of read-only memmaps."""

    def __init__(self, shards, cache_size=8):
        if int(cache_size) < 1:
            raise ValueError("cache_size must be at least 1")
        self.shards = tuple(shards)
        self.cache_size = int(cache_size)
        self._by_id = {shard.replay_id: shard for shard in self.shards}
        self._cache = OrderedDict()
        self.max_cache_entries = 0

        if not self.shards:
            raise SystemExit("selected .bbp corpus contains no shards")
        self.obs_size = self.shards[0].obs_size
        self.mask_size = self.shards[0].mask_size
        self.total_records = sum(s.record_count for s in self.shards)
        if self.total_records == 0:
            parent = os.path.dirname(self.shards[0].path)
            raise SystemExit(f"selected .bbp corpus in {parent} has zero records")

    @classmethod
    def from_directory(cls, pair_dir, replay_ids=None, cache_size=8):
        shards = []
        lineage = None
        for replay_id, path in _selected_shard_paths(pair_dir, replay_ids):
            info = _read_shard_info(path, replay_id)
            current = (info.version, info.obs_size, info.mask_size)
            if lineage is None:
                lineage = current
            elif current != lineage:
                raise SystemExit(
                    f"{path}: header mismatch across shards — "
                    f"v{info.version}/{info.obs_size}/{info.mask_size} vs "
                    f"v{lineage[0]}/{lineage[1]}/{lineage[2]}; never mix obs lineages "
                    "in one corpus")
            shards.append(info)
        return cls(shards, cache_size=cache_size)

    @property
    def replay_ids(self):
        return tuple(shard.replay_id for shard in self.shards)

    @property
    def nonempty_replay_ids(self):
        return tuple(
            shard.replay_id for shard in self.shards if shard.record_count)

    @property
    def cache_entries(self):
        return len(self._cache)

    @property
    def cached_memmaps(self):
        return tuple(self._cache.values())

    def info(self, replay_id):
        try:
            return self._by_id[int(replay_id)]
        except KeyError as exc:
            raise KeyError(f"replay {replay_id} is not in this shard index") from exc

    def open_shard(self, replay_id):
        replay_id = int(replay_id)
        if replay_id in self._cache:
            shard = self._cache.pop(replay_id)
            self._cache[replay_id] = shard
            return shard
        info = self.info(replay_id)
        if info.record_count == 0:
            return np.empty(0, dtype=rec_dtype(info.obs_size, info.mask_size))
        # Evict before opening so even transiently the process never owns more
        # mappings than the configured bound.
        while len(self._cache) >= self.cache_size:
            _old_id, old = self._cache.popitem(last=False)
            _close_memmap(old)
        shard = np.memmap(
            info.path,
            dtype=rec_dtype(info.obs_size, info.mask_size),
            mode="r",
            offset=HEADER_LEN,
            shape=(info.record_count,),
        )
        self._cache[replay_id] = shard
        self.max_cache_entries = max(self.max_cache_entries, len(self._cache))
        return shard

    def read_records(self, replay_id, selection):
        """Return an owning batch copy, safe after cache eviction."""
        return np.array(self.open_shard(replay_id)[selection], copy=True)

    def close(self):
        while self._cache:
            _replay_id, shard = self._cache.popitem(last=False)
            _close_memmap(shard)

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _tb):
        self.close()


def split_replay_ids(replay_ids, val_frac, seed):
    """Deterministically split replay IDs; no replay crosses the boundary."""
    ids = np.asarray(sorted(set(int(x) for x in replay_ids)), dtype=np.int64)
    if len(ids) < 2:
        raise SystemExit("replay-disjoint split requires at least two nonempty replays")
    if not 0.0 < float(val_frac) < 1.0:
        raise SystemExit("--val-frac must be strictly between 0 and 1")
    rng = np.random.default_rng(seed)
    rng.shuffle(ids)
    n_val = max(1, round(float(val_frac) * len(ids)))
    n_val = min(n_val, len(ids) - 1)
    val_ids = tuple(sorted(int(x) for x in ids[:n_val]))
    val_set = set(val_ids)
    train_ids = tuple(sorted(int(x) for x in ids if int(x) not in val_set))
    return train_ids, val_ids


class LazyReplayDataset:
    """Replay-disjoint lazy view supporting two deterministic IID samplers."""

    def __init__(self, index, replay_ids):
        self.index = index
        self.replay_ids = tuple(sorted(set(int(x) for x in replay_ids)))
        self.shards = tuple(index.info(replay_id) for replay_id in self.replay_ids)
        if any(shard.record_count == 0 for shard in self.shards):
            raise ValueError("LazyReplayDataset cannot sample zero-record shards")
        if not self.shards:
            raise ValueError("LazyReplayDataset requires at least one shard")
        self.counts = np.asarray(
            [shard.record_count for shard in self.shards], dtype=np.int64)
        self.cumulative_counts = np.cumsum(self.counts)
        self.total_records = int(self.cumulative_counts[-1])
        self.dtype = rec_dtype(index.obs_size, index.mask_size)

    def __len__(self):
        return self.total_records

    def sample_records(self, batch_size, rng, mode="replay"):
        """Sample an owning batch, uniformly by replay or by record."""
        batch_size = int(batch_size)
        if batch_size < 1:
            raise ValueError("batch_size must be at least 1")
        if mode == "replay":
            shard_indices = rng.integers(0, len(self.shards), size=batch_size)
            local_indices = np.empty(batch_size, dtype=np.int64)
            for shard_index in np.unique(shard_indices):
                positions = np.flatnonzero(shard_indices == shard_index)
                local_indices[positions] = rng.integers(
                    0, self.counts[shard_index], size=len(positions))
        elif mode == "record":
            global_indices = rng.integers(
                0, self.total_records, size=batch_size)
            shard_indices = np.searchsorted(
                self.cumulative_counts, global_indices, side="right")
            starts = np.where(
                shard_indices == 0, 0,
                self.cumulative_counts[np.maximum(shard_indices - 1, 0)])
            local_indices = global_indices - starts
        else:
            raise ValueError("sampling mode must be 'replay' or 'record'")

        out = np.empty(batch_size, dtype=self.dtype)
        for shard_index in np.unique(shard_indices):
            positions = np.flatnonzero(shard_indices == shard_index)
            shard = self.shards[int(shard_index)]
            out[positions] = self.index.open_shard(shard.replay_id)[
                local_indices[positions]]
        return out

    def iter_record_batches(self, batch_size=2048):
        """Visit every record once in stable replay/file order."""
        batch_size = int(batch_size)
        if batch_size < 1:
            raise ValueError("batch_size must be at least 1")
        for shard in self.shards:
            for start in range(0, shard.record_count, batch_size):
                stop = min(start + batch_size, shard.record_count)
                yield self.index.read_records(
                    shard.replay_id, slice(start, stop))


def load_replay_ids(path):
    """Load an exact replay-ID allowlist (one integer per line).

    The FUMBBL corpus contains overlapping BB2020 and BB2025 games, so dates
    cannot safely select an edition.  ``tools/replay_corpus_audit.py`` writes
    this format from each replay's embedded ``rulesVersion`` field.
    """
    ids = set()
    try:
        with open(path, encoding="utf-8") as f:
            for lineno, raw in enumerate(f, 1):
                value = raw.split("#", 1)[0].strip()
                if not value:
                    continue
                try:
                    replay_id = int(value)
                except ValueError as exc:
                    raise SystemExit(
                        f"{path}:{lineno}: invalid replay ID {value!r}") from exc
                if replay_id < 0:
                    raise SystemExit(
                        f"{path}:{lineno}: replay ID must be non-negative")
                ids.add(replay_id)
    except OSError as exc:
        raise SystemExit(f"cannot read replay-ID allowlist {path}: {exc}") from exc
    if not ids:
        raise SystemExit(f"replay-ID allowlist {path} is empty")
    return frozenset(ids)


def replay_ids_sha256(replay_ids):
    payload = "".join(f"{int(replay_id)}\n" for replay_id in sorted(replay_ids))
    return hashlib.sha256(payload.encode("ascii")).hexdigest()


def resolve_device(requested):
    """Resolve auto to CUDA first, then Apple MPS, then CPU."""
    if requested != "auto":
        return requested
    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def load_shards(pair_dir, replay_ids=None):
    """Compatibility loader for small callers; the CLI uses ShardIndex.

    Unlike the historical implementation this allocates one final array and
    fills it batchwise, avoiding the additional list-of-bodies + concatenate
    copy. It is still intentionally an in-memory API.
    """
    with ShardIndex.from_directory(
            pair_dir, replay_ids=replay_ids, cache_size=2) as index:
        data = LazyReplayDataset(index, index.nonempty_replay_ids)
        records = np.empty(index.total_records,
                           dtype=rec_dtype(index.obs_size, index.mask_size))
        offset = 0
        for batch in data.iter_record_batches(REPLAY_ID_SCAN_BATCH):
            records[offset:offset + len(batch)] = batch
            offset += len(batch)
        assert offset == len(records)
        return records, index.obs_size, index.mask_size


def load_policy_like_trainer(config_path, obs_size):
    """pufferlib.torch_pufferl.load_policy minus the vec (sizes from .bbp)."""
    import pufferlib
    import pufferlib.models

    default_ini = os.path.join(os.path.dirname(os.path.dirname(
        os.path.realpath(pufferlib.__file__))), "config", "default.ini")
    p = configparser.ConfigParser()
    read = p.read([default_ini, config_path])
    if len(read) != 2:
        raise SystemExit(f"config read failed: wanted {default_ini} + "
                         f"{config_path}, got {read}")

    def section(name):
        out = {}
        for k, v in p[name].items():
            try:
                out[k] = ast.literal_eval(v)
            except (ValueError, SyntaxError):
                out[k] = v
        return out

    policy_kwargs = section("policy")
    torch_cfg = section("torch")
    network_cls = getattr(pufferlib.models, torch_cfg["network"])
    encoder_cls = getattr(pufferlib.models, torch_cfg["encoder"])
    decoder_cls = getattr(pufferlib.models, torch_cfg["decoder"])
    network = network_cls(**policy_kwargs)
    encoder = encoder_cls(obs_size, policy_kwargs["hidden_size"])
    decoder = decoder_cls(ACT_SIZES, policy_kwargs["hidden_size"])
    policy = pufferlib.models.Policy(encoder, decoder, network)
    desc = (f"{torch_cfg['encoder']} -> {torch_cfg['network']}"
            f"(hidden={policy_kwargs['hidden_size']}, "
            f"layers={policy_kwargs.get('num_layers')}) -> "
            f"{torch_cfg['decoder']}{ACT_SIZES}")
    return policy, desc


def split_by_replay(recs, val_frac, seed):
    train_ids, val_ids = split_replay_ids(
        np.unique(recs["replay"]), val_frac, seed)
    val_m = np.isin(recs["replay"], val_ids)
    return recs[~val_m], recs[val_m], list(val_ids)


def to_tensors(recs, device):
    # Owning copies detach tensors from evictable memmaps. Only this batch is
    # transferred to the accelerator.
    obs = torch.from_numpy(np.array(
        recs["obs"], copy=True, order="C")).to(device)
    mask = torch.from_numpy(np.array(
        recs["mask"], copy=True, order="C")).to(device).bool()
    tgt = torch.stack([
        torch.from_numpy(recs["type"].astype(np.int64)),
        torch.from_numpy(recs["arg"].astype(np.int64)),
        torch.from_numpy(recs["sq"].astype(np.int64)),
    ], dim=1).to(device)
    return obs, mask, tgt


def forward_heads(policy, obs, device):
    """iid forward at zero recurrent state (the v0 limitation above)."""
    state = policy.initial_state(obs.shape[0], device=device)
    logits, _values, _state = policy.forward_eval(obs, state)
    return logits  # tuple of (B,30), (B,33), (B,391)


def masked_losses(logits, mask, tgt):
    """Per-head CE over mask-restricted logits; returns (loss, head_hits)."""
    off, losses, hits = 0, [], []
    for h, n in enumerate(ACT_SIZES):
        m = mask[:, off:off + n]
        off += n
        lg = logits[h].masked_fill(~m, -1e9)
        losses.append(F.cross_entropy(lg, tgt[:, h]))
        hits.append(lg.argmax(dim=1) == tgt[:, h])
    return sum(losses), hits


@torch.no_grad()
def evaluate(policy, obs, mask, tgt, device, batch=2048):
    policy.eval()
    tot, loss_sum = 0, 0.0
    head_hit = [0, 0, 0]
    exact_hit = 0
    for i in range(0, obs.shape[0], batch):
        o, m, t = obs[i:i + batch], mask[i:i + batch], tgt[i:i + batch]
        logits = forward_heads(policy, o, device)
        loss, hits = masked_losses(logits, m, t)
        loss_sum += loss.item() * o.shape[0]
        exact = torch.ones_like(hits[0])
        for h in range(3):
            head_hit[h] += hits[h].sum().item()
            exact &= hits[h]
        exact_hit += exact.sum().item()
        tot += o.shape[0]
    policy.train()
    return (loss_sum / tot, [h / tot for h in head_hit], exact_hit / tot)


@torch.no_grad()
def evaluate_lazy(policy, dataset, device, batch=2048):
    """Evaluate a lazy replay view with at most one batch on the device."""
    policy.eval()
    total, loss_sum = 0, 0.0
    head_hit = [0, 0, 0]
    exact_hit = 0
    for records in dataset.iter_record_batches(batch):
        obs, mask, tgt = to_tensors(records, device)
        logits = forward_heads(policy, obs, device)
        loss, hits = masked_losses(logits, mask, tgt)
        loss_sum += loss.item() * len(records)
        exact = torch.ones_like(hits[0])
        for head in range(3):
            head_hit[head] += hits[head].sum().item()
            exact &= hits[head]
        exact_hit += exact.sum().item()
        total += len(records)
        del records, obs, mask, tgt, logits, loss, hits, exact
    policy.train()
    if total == 0:
        raise ValueError("cannot evaluate an empty lazy dataset")
    return (loss_sum / total,
            [hits / total for hits in head_hit],
            exact_hit / total)


def verify_roundtrip(out_path, obs_size, config_path, trained_policy, probe_obs):
    """Save->load through the REAL torch backend loader, then compare."""
    from pufferlib.torch_pufferl import PuffeRL
    fresh, _ = load_policy_like_trainer(config_path, obs_size)
    shim = types.SimpleNamespace(device="cpu", policy=fresh)
    PuffeRL.load_weights(shim, out_path)  # torch.load + module.-strip + load_state_dict
    ref = {k: v.detach().cpu() for k, v in trained_policy.state_dict().items()}
    got = fresh.state_dict()
    assert set(ref) == set(got), "state_dict key mismatch after round-trip"
    pdiff = max((ref[k].float() - got[k].float()).abs().max().item()
                for k in ref)
    trained_cpu, _ = load_policy_like_trainer(config_path, obs_size)
    trained_cpu.load_state_dict(ref)
    with torch.no_grad():
        a = forward_heads(trained_cpu, probe_obs.cpu(), "cpu")
        b = forward_heads(fresh, probe_obs.cpu(), "cpu")
    ldiff = max((x - y).abs().max().item() for x, y in zip(a, b))
    return pdiff, ldiff


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--pairs-dir", default=os.path.join(ROOT, "validation", "pairs"))
    ap.add_argument(
        "--replay-ids", default=None,
        help="exact replay-ID allowlist; generate the BB2025 list with "
             "tools/replay_corpus_audit.py --write-bb2025-ids")
    ap.add_argument("--config", default=os.path.join(ROOT, "puffer", "config",
                                                     "bloodbowl.ini"))
    ap.add_argument("--out", default=os.path.join(ROOT, "training", "checkpoints",
                                                  "bc_bloodbowl.bin"))
    ap.add_argument("--steps", type=int, default=300)
    ap.add_argument("--batch-size", type=int, default=256)
    ap.add_argument(
        "--sampling", choices=("replay-first", "record-weighted"),
        default="replay-first",
        help="replay-first samples a replay uniformly then a record within it "
             "(default); record-weighted reproduces uniform-record semantics")
    ap.add_argument(
        "--open-shard-cache", type=int, default=8,
        help="maximum simultaneously open read-only shard memmaps")
    ap.add_argument(
        "--eval-batch-size", type=int, default=2048,
        help="records copied to CPU/device at once during train/validation eval")
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--val-frac", type=float, default=0.2)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--device", default="auto",
                    help="auto (mps if available, else cpu) | cpu | mps | cuda")
    ap.add_argument("--log-every", type=int, default=25)
    ap.add_argument("--init", default=None,
                    help="warm-start from an existing state_dict (resume)")
    ap.add_argument("--cosine", action="store_true",
                    help="cosine-decay the LR to 1%% over --steps")
    args = ap.parse_args()

    if args.steps < 1:
        raise SystemExit("--steps must be at least 1")
    if args.batch_size < 1:
        raise SystemExit("--batch-size must be at least 1")
    if args.eval_batch_size < 1:
        raise SystemExit("--eval-batch-size must be at least 1")
    if args.open_shard_cache < 1:
        raise SystemExit("--open-shard-cache must be at least 1")
    if args.log_every < 1:
        raise SystemExit("--log-every must be at least 1")

    device = resolve_device(args.device)
    torch.manual_seed(args.seed)

    replay_ids = load_replay_ids(args.replay_ids) if args.replay_ids else None
    index = ShardIndex.from_directory(
        args.pairs_dir,
        replay_ids=replay_ids,
        cache_size=args.open_shard_cache,
    )
    try:
        train_ids, val_ids = split_replay_ids(
            index.nonempty_replay_ids, args.val_frac, args.seed)
        train_data = LazyReplayDataset(index, train_ids)
        val_data = LazyReplayDataset(index, val_ids)
        print(
            f"pairs: {index.total_records} from "
            f"{len(index.nonempty_replay_ids)} nonempty replays "
            f"(obs {index.obs_size}B, mask {index.mask_size}b) | "
            f"split BY REPLAY: {len(train_data)} train / {len(val_data)} val "
            f"(held out: {list(val_ids)}) | sampling {args.sampling} | "
            f"open-shard cache {args.open_shard_cache}")
        if replay_ids is not None:
            print(
                f"allowlist: {len(replay_ids)} replay IDs | sha256 "
                f"{replay_ids_sha256(replay_ids)}")

        policy, desc = load_policy_like_trainer(args.config, index.obs_size)
        if args.init:
            policy.load_state_dict(torch.load(args.init, map_location="cpu"))
            print(f"warm-started from {args.init}")
        policy = policy.to(device).train()
        n_params = sum(p.numel() for p in policy.parameters())
        print(f"policy: {desc} | {n_params:,} params | device {device}")

        opt = torch.optim.Adam(policy.parameters(), lr=args.lr)
        sched = (torch.optim.lr_scheduler.CosineAnnealingLR(
                     opt, T_max=args.steps, eta_min=args.lr * 0.01)
                 if args.cosine else None)
        rng = np.random.default_rng(args.seed)
        sample_mode = (
            "replay" if args.sampling == "replay-first" else "record")

        first_loss = last_loss = None
        for step in range(args.steps):
            records = train_data.sample_records(
                args.batch_size, rng, mode=sample_mode)
            obs, mask, tgt = to_tensors(records, device)
            logits = forward_heads(policy, obs, device)
            loss, hits = masked_losses(logits, mask, tgt)
            opt.zero_grad()
            loss.backward()
            opt.step()
            if sched is not None:
                sched.step()
            if first_loss is None:
                first_loss = loss.item()
            last_loss = loss.item()
            if step % args.log_every == 0 or step == args.steps - 1:
                exact = (hits[0] & hits[1] & hits[2]).float().mean().item()
                accs = [h.float().mean().item() for h in hits]
                print(
                    f"step {step:4d} | loss {loss.item():7.4f} | "
                    f"acc type/arg/sq "
                    f"{accs[0]:.3f}/{accs[1]:.3f}/{accs[2]:.3f} | "
                    f"exact {exact:.3f}")
            del records, obs, mask, tgt, logits, loss, hits

        v_loss, v_accs, v_exact = evaluate_lazy(
            policy, val_data, device, batch=args.eval_batch_size)
        t_loss, t_accs, t_exact = evaluate_lazy(
            policy, train_data, device, batch=args.eval_batch_size)
        print(f"final train | loss {t_loss:.4f} | acc type/arg/sq "
              f"{t_accs[0]:.3f}/{t_accs[1]:.3f}/{t_accs[2]:.3f} | "
              f"exact {t_exact:.3f}")
        print(f"final  val  | loss {v_loss:.4f} | acc type/arg/sq "
              f"{v_accs[0]:.3f}/{v_accs[1]:.3f}/{v_accs[2]:.3f} | "
              f"exact {v_exact:.3f}")
        print(f"loss curve: {first_loss:.4f} -> {last_loss:.4f}")

        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        # Exactly PuffeRL.save_weights: torch.save(policy.state_dict(), path).
        torch.save(policy.state_dict(), args.out)
        print(f"saved {args.out} ({os.path.getsize(args.out)} bytes)")

        probe_records = next(val_data.iter_record_batches(batch_size=8))
        probe = to_tensors(probe_records, "cpu")[0]
        pdiff, ldiff = verify_roundtrip(
            args.out, index.obs_size, args.config, policy, probe)
        print(f"round-trip: pufferlib.torch_pufferl.PuffeRL.load_weights OK — "
              f"max param diff {pdiff:.3e}, max logit diff {ldiff:.3e}")
        if pdiff != 0.0:
            raise SystemExit(
                "round-trip params differ — checkpoint NOT trainer-compatible")
        print(f"streaming cache peak: {index.max_cache_entries}/"
              f"{index.cache_size} open shard memmaps")
    finally:
        index.close()


if __name__ == "__main__":
    main()
