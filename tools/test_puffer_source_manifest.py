#!/usr/bin/env python3

from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from tools import puffer_source_manifest as source_manifest


ROOT = Path(__file__).resolve().parents[1]
COMPILED_LEDGER = ROOT / "training/puffer_compiled_backend_sources.txt"
VENDOR_LEDGER = ROOT / "training/puffer_vendor_sources.txt"

EXPECTED_COMPILED = (
    "build.sh",
    "pufferlib/pufferl.py",
    "pufferlib/selfplay.py",
    "pufferlib/torch_pufferl.py",
    "src/bindings.cu",
    "src/bindings_cpu.cpp",
    "src/kernels.cu",
    "src/pufferlib.cu",
    "src/vecenv.h",
)
EXPECTED_VENDOR = (
    "build.sh",
    "pufferlib/__init__.py",
    "pufferlib/pufferl.py",
    "pufferlib/selfplay.py",
    "pufferlib/torch_pufferl.py",
    "pufferlib/models.py",
    "pufferlib/muon.py",
    "src/pufferlib.cu",
    "src/bindings.cu",
    "src/bindings_cpu.cpp",
    "src/kernels.cu",
    "src/vecenv.h",
)


class PufferSourceManifestTests(unittest.TestCase):
    def test_checked_in_ledgers_have_the_exact_distinct_ordered_closures(self):
        compiled = source_manifest.read_source_ledger(COMPILED_LEDGER, expected_count=9)
        vendor = source_manifest.read_source_ledger(VENDOR_LEDGER, expected_count=12)
        self.assertEqual(compiled, EXPECTED_COMPILED)
        self.assertEqual(vendor, EXPECTED_VENDOR)
        self.assertEqual(
            set(vendor) - set(compiled),
            {
                "pufferlib/__init__.py",
                "pufferlib/models.py",
                "pufferlib/muon.py",
            },
        )

    def test_digest_is_ordered_and_path_bound(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for relative, payload in (
                ("build.sh", b"build\n"),
                ("src/vecenv.h", b"vec\n"),
            ):
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(payload)
            sources = ("build.sh", "src/vecenv.h")
            expected_stream = b"".join(
                hashlib.sha256((root / relative).read_bytes()).hexdigest().encode()
                + b"  "
                + relative.encode()
                + b"\n"
                for relative in sources
            )
            observed = source_manifest.source_manifest_sha256(root, sources)
            self.assertEqual(observed, hashlib.sha256(expected_stream).hexdigest())
            self.assertNotEqual(
                observed,
                source_manifest.source_manifest_sha256(root, reversed(sources)),
            )

    def test_ledger_rejects_open_or_unsafe_path_sets(self):
        cases = {
            "blank": b"build.sh\n\n",
            "comment": b"# comment\n",
            "duplicate": b"build.sh\nbuild.sh\n",
            "absolute": b"/build.sh\n",
            "dot": b"./build.sh\n",
            "parent": b"src/../build.sh\n",
            "backslash": b"src\\vecenv.h\n",
            "carriage-return": b"build.sh\r\n",
            "unterminated": b"build.sh",
        }
        with tempfile.TemporaryDirectory() as temporary:
            ledger = Path(temporary) / "ledger.txt"
            for name, payload in cases.items():
                with self.subTest(name=name):
                    ledger.write_bytes(payload)
                    with self.assertRaises(source_manifest.PufferSourceManifestError):
                        source_manifest.read_source_ledger(ledger)

    def test_hash_rejects_missing_and_symlink_sources(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            real = root / "real"
            real.write_bytes(b"source")
            link = root / "build.sh"
            link.symlink_to(real.name)
            with self.assertRaisesRegex(
                source_manifest.PufferSourceManifestError,
                "regular non-symlink",
            ):
                source_manifest.source_manifest_sha256(root, ("build.sh",))
            link.unlink()
            with self.assertRaisesRegex(
                source_manifest.PufferSourceManifestError, "missing"
            ):
                source_manifest.source_manifest_sha256(root, ("build.sh",))

    def test_hash_rejects_a_symlinked_parent_that_escapes_the_root(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "root"
            outside = base / "outside"
            root.mkdir()
            outside.mkdir()
            (outside / "vecenv.h").write_bytes(b"escaped source")
            (root / "src").symlink_to(outside, target_is_directory=True)
            with self.assertRaisesRegex(
                source_manifest.PufferSourceManifestError,
                "parent must be a real directory",
            ):
                source_manifest.source_manifest_sha256(
                    root,
                    ("src/vecenv.h",),
                )


if __name__ == "__main__":
    unittest.main()
