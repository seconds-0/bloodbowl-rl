#!/usr/bin/env python3

from __future__ import annotations

import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools import puffer_source_manifest as source_manifest


ROOT = Path(__file__).resolve().parents[1]
COMPILED_LEDGER = ROOT / "training/puffer_compiled_backend_sources.txt"
VENDOR_LEDGER = ROOT / "training/puffer_vendor_sources.txt"

EXPECTED_COMPILED = (
    "build.sh",
    "pufferlib/pufferl.py",
    "pufferlib/selfplay.py",
    "pufferlib/sweep.py",
    "pufferlib/torch_pufferl.py",
    "src/bindings.cu",
    "src/bindings_cpu.cpp",
    "src/cudnn_conv2d.cu",
    "src/kernels.cu",
    "src/models.cu",
    "src/muon.cu",
    "src/ocean.cu",
    "src/pufferlib.cu",
    "src/tensor.h",
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
        compiled = source_manifest.read_source_ledger(
            COMPILED_LEDGER,
            expected_count=len(EXPECTED_COMPILED),
        )
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
        self.assertEqual(
            set(compiled) - set(vendor),
            {
                "pufferlib/sweep.py",
                "src/cudnn_conv2d.cu",
                "src/models.cu",
                "src/muon.cu",
                "src/ocean.cu",
                "src/tensor.h",
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

    def test_native_extension_include_closure_is_recursive_and_fail_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            payloads = {
                "src/bindings.cu": (
                    b'#include "pufferlib.cu"\n'
                    b'#include "exact_action_build_hash.h"\n'
                ),
                "src/bindings_cpu.cpp": b'#include "vecenv.h"\n',
                "src/pufferlib.cu": b'#include "models.cu"\n',
                "src/models.cu": b'#include "kernels.cu"\n',
                "src/kernels.cu": b'#include "tensor.h"\n',
                "src/vecenv.h": b'#include "tensor.h"\n',
                "src/tensor.h": b"#pragma once\n",
            }
            for relative, payload in payloads.items():
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(payload)
            sources = tuple(payloads)
            observed = source_manifest.validate_native_extension_include_closure(
                root,
                sources,
            )
            self.assertEqual(set(observed), set(sources))
            with mock.patch.object(
                source_manifest,
                "_regular_source_bytes",
                wraps=source_manifest._regular_source_bytes,
            ) as read:
                digest = (
                    source_manifest.native_extension_source_manifest_sha256(
                        root,
                        sources,
                    )
                )
            self.assertRegex(digest, r"^[0-9a-f]{64}$")
            self.assertEqual(read.call_count, len(sources))
            with self.assertRaisesRegex(
                source_manifest.PufferSourceManifestError,
                "unregistered local include",
            ):
                source_manifest.validate_native_extension_include_closure(
                    root,
                    tuple(
                        source for source in sources
                        if source != "src/tensor.h"
                    ),
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

    def test_descriptor_read_rejects_a_last_component_swap(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "build.sh"
            replacement = root / "replacement"
            source.write_bytes(b"validated source")
            replacement.write_bytes(b"unvalidated replacement")
            original_open = os.open
            swapped = False

            def swap_then_open(path, flags, *args, dir_fd=None, **kwargs):
                nonlocal swapped
                if path == "build.sh" and dir_fd is not None and not swapped:
                    swapped = True
                    source.unlink()
                    source.symlink_to(replacement.name)
                return original_open(
                    path,
                    flags,
                    *args,
                    dir_fd=dir_fd,
                    **kwargs,
                )

            with mock.patch.object(
                source_manifest.os,
                "open",
                side_effect=swap_then_open,
            ), self.assertRaisesRegex(
                source_manifest.PufferSourceManifestError,
                "regular non-symlink",
            ):
                source_manifest.source_manifest_sha256(
                    root,
                    ("build.sh",),
                )

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
