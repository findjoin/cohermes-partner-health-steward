"""Verifier-owned frozen gates for Ticket 121.

The implementation task must not edit this file.  Formal green evidence is
Linux-only because the contract depends on real POSIX ownership, file types,
flock and process-death behaviour.
"""

from __future__ import annotations

import hashlib
import hmac
import importlib
import json
import os
import base64
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from partner_health_steward.authority import (
    AuthoritySnapshot,
    ExecutionCapabilityBinding,
    WriterHolderClaim,
    holder_id_for,
)


_INSTALLATION = "installation:t121-fixture"
_SITE = "site:t121-fixture"
_EPOCH = "writer-epoch:t121-initial"
_DATA_KEY = bytes(range(32))
_WRITER_MASTER = bytes(range(32, 64))
_EXECUTION_MASTER = bytes(range(64, 96))


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _nonce() -> str:
    body = b"partner-health-steward/writer-nonce/v1\0" + _canonical(
        [_INSTALLATION, _SITE, _EPOCH]
    )
    raw = hmac.new(_WRITER_MASTER, body, hashlib.sha256).digest()[:16]
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _writer_capability() -> str:
    body = b"partner-health-steward/writer-capability/v1\0" + _canonical(
        [_INSTALLATION, _SITE, _nonce()]
    )
    return hmac.new(_WRITER_MASTER, body, hashlib.sha256).hexdigest()


def _fence_ref() -> str:
    return f"fence:v1:{_nonce()}:{hashlib.sha256(_writer_capability().encode()).hexdigest()}"


def _authority(*, terminal: bool = False, fence: str | None = None) -> AuthoritySnapshot:
    return AuthoritySnapshot(
        installation_id=_INSTALLATION,
        generation=4,
        revision_digest="sha256:t121-revision",
        transition_id="transition:t121-current",
        writer_fence=fence or _fence_ref(),
        terminal=terminal,
        site=_SITE,
    )


class Ticket121HostAuthorityTests(unittest.TestCase):
    module = None
    prerequisite_error: BaseException | None = None

    @classmethod
    def setUpClass(cls) -> None:
        try:
            cls.module = importlib.import_module("partner_health_steward.host_authority")
        except BaseException as exc:  # the one intended pre-code red gate
            cls.prerequisite_error = exc

    def _require(self, *, red: bool = False):
        if self.module is None:
            message = "Ticket 121 production host-authority module is absent"
            if red:
                self.fail(message)
            self.skipTest(message)
        if sys.platform != "linux":
            self.skipTest("Ticket 121 formal gates require an isolated Linux host")
        return self.module

    def _facility(self, root: Path):
        module = self.module
        root.mkdir(parents=True, exist_ok=True)
        facility = root / "authority"
        facility.mkdir(mode=0o700)
        for name, value in (
            ("data-key.v1", _DATA_KEY),
            ("writer-master.v1", _WRITER_MASTER),
            ("execution-master.v1", _EXECUTION_MASTER),
        ):
            path = facility / name
            path.write_bytes(value)
            path.chmod(0o400)
        locks = facility / "locks"
        locks.mkdir(mode=0o700)
        return module.HostPrivateFacilityPaths(
            data_key=facility / "data-key.v1",
            writer_master=facility / "writer-master.v1",
            execution_master=facility / "execution-master.v1",
            lock_directory=locks,
        )

    def test_v121_01_key_provider_rejects_unsafe_files(self) -> None:
        module = self._require(red=True)
        with tempfile.TemporaryDirectory(prefix="ticket121-") as raw:
            paths = self._facility(Path(raw))
            provider = module.HostPrivateKeyProvider(paths, _INSTALLATION)
            self.assertEqual(
                provider.key_id,
                "key:v1:" + hashlib.sha256(_DATA_KEY).hexdigest(),
            )
            self.assertEqual(provider.get_key(), _DATA_KEY)
            self.assertNotIn(_DATA_KEY.hex(), repr(provider))

            key_path = Path(paths.data_key)
            replacement = key_path.parent / "replacement"
            replacement.write_bytes(_DATA_KEY)
            replacement.chmod(0o400)
            os.replace(replacement, key_path)
            with self.assertRaises(Exception):
                provider.get_key()

            for name, setup in (
                ("wrong-size", lambda p: p.write_bytes(b"short")),
                ("wide-mode", lambda p: (p.write_bytes(_DATA_KEY), p.chmod(0o640))),
            ):
                case_paths = self._facility(Path(raw) / name)
                setup(Path(case_paths.data_key))
                with self.assertRaises(Exception):
                    module.HostPrivateKeyProvider(case_paths, _INSTALLATION)

            missing_paths = self._facility(Path(raw) / "missing")
            Path(missing_paths.data_key).unlink()
            with self.assertRaises(Exception):
                module.HostPrivateKeyProvider(missing_paths, _INSTALLATION)

    def test_v121_02_writer_holder_is_exclusive_and_crash_recoverable(self) -> None:
        module = self._require()
        with tempfile.TemporaryDirectory(prefix="ticket121-") as raw:
            paths = self._facility(Path(raw))
            first = module.HostPrivateWriterFenceVault(paths)
            self.assertEqual(
                first.prepare_fence_ref(_INSTALLATION, _SITE, _EPOCH), _fence_ref()
            )
            self.assertNotEqual(
                first.prepare_fence_ref(
                    _INSTALLATION, _SITE, "writer-epoch:t121-return"
                ),
                _fence_ref(),
            )
            script = """
import sys, time, hashlib, hmac, json
from pathlib import Path
from partner_health_steward.authority import WriterHolderClaim
from partner_health_steward.host_authority import HostPrivateFacilityPaths, HostPrivateWriterFenceVault
root = Path(sys.argv[1])
paths = HostPrivateFacilityPaths(root/'data-key.v1', root/'writer-master.v1', root/'execution-master.v1', root/'locks')
session = HostPrivateWriterFenceVault(paths).acquire_or_resume('installation:t121-fixture','site:t121-fixture',WriterHolderClaim('holder:child'))
print('READY' if session is not None else 'FAILED', flush=True)
time.sleep(60)
"""
            child = subprocess.Popen(
                [sys.executable, "-c", script, str(Path(paths.data_key).parent)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            try:
                self.assertEqual(child.stdout.readline().strip(), "READY")
                self.assertIsNone(
                    first.acquire_or_resume(
                        _INSTALLATION, _SITE, WriterHolderClaim("holder:parent")
                    )
                )
            finally:
                child.kill()
                child.wait(timeout=10)
            recovered = first.acquire_or_resume(
                _INSTALLATION, _SITE, WriterHolderClaim("holder:second")
            )
            self.assertIsNotNone(recovered)
            self.assertEqual(recovered.proof_for(_authority()).capability, _writer_capability())
            recovered.release()
            clean = first.acquire_or_resume(
                _INSTALLATION, _SITE, WriterHolderClaim("holder:clean")
            )
            self.assertIsNotNone(clean)
            clean.release()

    def test_v121_03_writer_proof_is_exact_and_secret_free(self) -> None:
        module = self._require()
        with tempfile.TemporaryDirectory(prefix="ticket121-") as raw:
            paths = self._facility(Path(raw))
            vault = module.HostPrivateWriterFenceVault(paths)
            session = vault.acquire_or_resume(
                _INSTALLATION, _SITE, WriterHolderClaim("holder:exact")
            )
            proof = session.proof_for(_authority())
            self.assertEqual(
                hashlib.sha256(proof.capability.encode()).hexdigest(),
                _fence_ref().rsplit(":", 1)[1],
            )
            self.assertIsNone(session.proof_for(_authority(fence="fence:v1:bad:bad")))
            self.assertIsNone(session.proof_for(_authority(terminal=True)))
            self.assertNotIn(proof.capability, repr(vault))
            Path(paths.writer_master).unlink()
            self.assertIsNone(session.proof_for(_authority()))

    def test_v121_04_execution_capability_has_exact_binding(self) -> None:
        module = self._require()
        with tempfile.TemporaryDirectory(prefix="ticket121-") as raw:
            paths = self._facility(Path(raw))
            from partner_health_steward.authority import WriterFenceProof
            proof = WriterFenceProof(_authority(), _writer_capability())
            script = """
import sys, time, hashlib, hmac, json
from pathlib import Path
from partner_health_steward.authority import AuthoritySnapshot, WriterFenceProof
from partner_health_steward.host_authority import HostPrivateFacilityPaths, HostPrivateExecutionCapabilityVault
root, fence = Path(sys.argv[1]), sys.argv[2]
paths = HostPrivateFacilityPaths(root/'data-key.v1', root/'writer-master.v1', root/'execution-master.v1', root/'locks')
authority = AuthoritySnapshot('installation:t121-fixture',4,'sha256:t121-revision','transition:t121-current',fence,False,'site:t121-fixture')
nonce = fence.split(':')[2]
body = b'partner-health-steward/writer-capability/v1\0' + json.dumps(['installation:t121-fixture','site:t121-fixture',nonce],ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
capability = hmac.new((root/'writer-master.v1').read_bytes(), body, hashlib.sha256).hexdigest()
session = HostPrivateExecutionCapabilityVault(paths).acquire_or_resume_session(authority, WriterFenceProof(authority, capability))
print('READY' if session is not None else 'FAILED', flush=True)
time.sleep(60)
"""
            child = subprocess.Popen(
                [sys.executable, "-c", script, str(Path(paths.data_key).parent), _fence_ref()],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            vault = module.HostPrivateExecutionCapabilityVault(paths)
            try:
                self.assertEqual(child.stdout.readline().strip(), "READY")
                self.assertIsNone(vault.acquire_or_resume_session(_authority(), proof))
            finally:
                child.kill()
                child.wait(timeout=10)
            session = vault.acquire_or_resume_session(_authority(), proof)
            binding = ExecutionCapabilityBinding(
                authority=_authority(),
                effect_id="effect:t121",
                intent_digest="sha256:t121-intent",
                vault_claim_ref="claim:t121",
            )
            capability = session.mint(binding)
            self.assertEqual(session.mint(binding), capability)
            self.assertIsNone(module.HostPrivateExecutionCapabilityVault(paths).acquire_or_resume_session(_authority(), proof))
            mutations = (
                ExecutionCapabilityBinding(_authority(), "effect:other", binding.intent_digest, binding.vault_claim_ref),
                ExecutionCapabilityBinding(_authority(), binding.effect_id, "sha256:other", binding.vault_claim_ref),
                ExecutionCapabilityBinding(_authority(), binding.effect_id, binding.intent_digest, "claim:other"),
                ExecutionCapabilityBinding(_authority(fence="fence:v1:bad:bad"), binding.effect_id, binding.intent_digest, binding.vault_claim_ref),
                ExecutionCapabilityBinding(
                    AuthoritySnapshot(
                        _INSTALLATION,
                        5,
                        _authority().revision_digest,
                        _authority().transition_id,
                        _authority().writer_fence,
                        False,
                        _SITE,
                    ),
                    binding.effect_id,
                    binding.intent_digest,
                    binding.vault_claim_ref,
                ),
            )
            for changed in mutations:
                self.assertIsNone(session.recover(changed, holder_id_for(capability)))
            self.assertIsNone(session.recover(binding, "holder:wrong"))
            session.release()
            resumed = module.HostPrivateExecutionCapabilityVault(paths).acquire_or_resume_session(_authority(), proof)
            self.assertEqual(
                resumed.recover(binding, holder_id_for(capability)), capability
            )

    def test_v121_05_terminal_key_destruction_is_bounded(self) -> None:
        module = self._require()
        with tempfile.TemporaryDirectory(prefix="ticket121-") as raw:
            paths = self._facility(Path(raw))
            provider = module.HostPrivateKeyProvider(paths, _INSTALLATION)
            nonterminal = {
                "operation_ref": "delete:t121",
                "authority_binding": _authority().to_storage(),
                "transition_id": _authority().transition_id,
            }
            with self.assertRaises(Exception):
                provider.destroy(nonterminal)
            terminal = dict(nonterminal)
            terminal["authority_binding"] = _authority(terminal=True).to_storage()
            original_replace = module.os.replace
            module.os.replace = lambda *args, **kwargs: (_ for _ in ()).throw(
                OSError("synthetic pre-replace crash")
            )
            try:
                with self.assertRaises(Exception):
                    provider.destroy(terminal)
            finally:
                module.os.replace = original_replace
            provider = module.HostPrivateKeyProvider(paths, _INSTALLATION)
            self.assertEqual(provider.get_key(), _DATA_KEY)
            self.assertEqual(provider.destroy(terminal), {"status": "confirmed"})
            self.assertEqual(provider.absence(terminal), {"status": "absent"})
            receipt_bytes = Path(paths.data_key).read_bytes()
            for secret in (_DATA_KEY, _WRITER_MASTER, _EXECUTION_MASTER):
                self.assertNotIn(secret, receipt_bytes)
            restarted = module.HostPrivateKeyProvider(paths, _INSTALLATION)
            self.assertEqual(restarted.destroy(terminal), {"status": "confirmed"})
            changed = dict(terminal)
            changed["operation_ref"] = "delete:other"
            with self.assertRaises(Exception):
                restarted.destroy(changed)
            self.assertTrue(Path(paths.writer_master).is_file())
            self.assertTrue(Path(paths.execution_master).is_file())

    def test_v121_06_linux_file_type_and_output_closure(self) -> None:
        module = self._require()
        with tempfile.TemporaryDirectory(prefix="ticket121-") as raw:
            root = Path(raw)
            paths = self._facility(root)
            original = Path(paths.data_key)
            original.unlink()
            os.symlink(Path(paths.writer_master), original)
            self.assertTrue(stat.S_ISLNK(os.lstat(original).st_mode))
            with self.assertRaises(Exception) as caught:
                module.HostPrivateKeyProvider(paths, _INSTALLATION)
            public = repr(caught.exception)
            for secret in (_DATA_KEY.hex(), _WRITER_MASTER.hex(), _EXECUTION_MASTER.hex(), raw):
                self.assertNotIn(secret, public)

            fifo_root = root / "fifo-case"
            fifo_paths = self._facility(fifo_root)
            Path(fifo_paths.data_key).unlink()
            os.mkfifo(fifo_paths.data_key, mode=0o400)
            with self.assertRaises(Exception):
                module.HostPrivateKeyProvider(fifo_paths, _INSTALLATION)

            hard_root = root / "hardlink-case"
            hard_paths = self._facility(hard_root)
            os.link(hard_paths.data_key, hard_root / "second-link")
            with self.assertRaises(Exception):
                module.HostPrivateKeyProvider(hard_paths, _INSTALLATION)

            writer_root = root / "writer-symlink-case"
            writer_paths = self._facility(writer_root)
            Path(writer_paths.writer_master).unlink()
            os.symlink(writer_paths.execution_master, writer_paths.writer_master)
            with self.assertRaises(Exception):
                module.HostPrivateWriterFenceVault(writer_paths)

            execution_root = root / "execution-mode-case"
            execution_paths = self._facility(execution_root)
            Path(execution_paths.execution_master).chmod(0o640)
            with self.assertRaises(Exception):
                module.HostPrivateExecutionCapabilityVault(execution_paths)

            if os.geteuid() != 0:
                self.fail("V121-06 requires root to prove wrong uid/gid rejection")
            owner_root = root / "owner-case"
            owner_paths = self._facility(owner_root)
            os.chown(owner_paths.data_key, 65534, 65534)
            with self.assertRaises(Exception):
                module.HostPrivateKeyProvider(owner_paths, _INSTALLATION)


if __name__ == "__main__":
    unittest.main()
