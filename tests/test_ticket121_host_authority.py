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
import stat
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
_NONCE = "ABEiM0RVZneImaq7zN3u_w"
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


def _writer_capability() -> str:
    body = b"partner-health-steward/writer-capability/v1\0" + _canonical(
        [_INSTALLATION, _SITE, _NONCE]
    )
    return hmac.new(_WRITER_MASTER, body, hashlib.sha256).hexdigest()


def _fence_ref() -> str:
    return f"fence:v1:{_NONCE}:{hashlib.sha256(_writer_capability().encode()).hexdigest()}"


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

    def _facility(self, root: Path) -> Path:
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
        return facility

    def test_v121_01_key_provider_rejects_unsafe_files(self) -> None:
        module = self._require(red=True)
        with tempfile.TemporaryDirectory(prefix="ticket121-") as raw:
            facility = self._facility(Path(raw))
            provider = module.HostPrivateKeyProvider(facility, _INSTALLATION)
            self.assertEqual(
                provider.key_id,
                "key:v1:" + hashlib.sha256(_DATA_KEY).hexdigest(),
            )
            self.assertEqual(provider.get_key(), _DATA_KEY)
            self.assertNotIn(_DATA_KEY.hex(), repr(provider))

            key_path = facility / "data-key.v1"
            replacement = facility / "replacement"
            replacement.write_bytes(_DATA_KEY)
            replacement.chmod(0o400)
            os.replace(replacement, key_path)
            with self.assertRaises(Exception):
                provider.get_key()

            for name, setup in (
                ("wrong-size", lambda p: p.write_bytes(b"short")),
                ("wide-mode", lambda p: (p.write_bytes(_DATA_KEY), p.chmod(0o640))),
            ):
                case = Path(raw) / name
                case.mkdir(mode=0o700)
                for filename, value in (
                    ("data-key.v1", _DATA_KEY),
                    ("writer-master.v1", _WRITER_MASTER),
                    ("execution-master.v1", _EXECUTION_MASTER),
                ):
                    target = case / filename
                    target.write_bytes(value)
                    target.chmod(0o400)
                setup(case / "data-key.v1")
                with self.assertRaises(Exception):
                    module.HostPrivateKeyProvider(case, _INSTALLATION)

    def test_v121_02_writer_holder_is_exclusive_and_crash_recoverable(self) -> None:
        module = self._require()
        with tempfile.TemporaryDirectory(prefix="ticket121-") as raw:
            facility = self._facility(Path(raw))
            first = module.HostPrivateWriterFenceVault(facility)
            second = module.HostPrivateWriterFenceVault(facility)
            session = first.acquire_or_resume(
                _INSTALLATION, _SITE, WriterHolderClaim("holder:first")
            )
            self.assertIsNotNone(session)
            self.assertIsNone(
                second.acquire_or_resume(
                    _INSTALLATION, _SITE, WriterHolderClaim("holder:second")
                )
            )
            proof = session.proof_for(_authority())
            self.assertEqual(proof.capability, _writer_capability())
            session.release()
            recovered = second.acquire_or_resume(
                _INSTALLATION, _SITE, WriterHolderClaim("holder:second")
            )
            self.assertIsNotNone(recovered)
            recovered.release()

    def test_v121_03_writer_proof_is_exact_and_secret_free(self) -> None:
        module = self._require()
        with tempfile.TemporaryDirectory(prefix="ticket121-") as raw:
            facility = self._facility(Path(raw))
            vault = module.HostPrivateWriterFenceVault(facility)
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
            (facility / "writer-master.v1").unlink()
            self.assertIsNone(session.proof_for(_authority()))

    def test_v121_04_execution_capability_has_exact_binding(self) -> None:
        module = self._require()
        with tempfile.TemporaryDirectory(prefix="ticket121-") as raw:
            facility = self._facility(Path(raw))
            writer = module.HostPrivateWriterFenceVault(facility)
            holder = writer.acquire_or_resume(
                _INSTALLATION, _SITE, WriterHolderClaim("holder:execution")
            )
            proof = holder.proof_for(_authority())
            vault = module.HostPrivateExecutionCapabilityVault(facility)
            session = vault.acquire_or_resume_session(_authority(), proof)
            binding = ExecutionCapabilityBinding(
                authority=_authority(),
                effect_id="effect:t121",
                intent_digest="sha256:t121-intent",
                vault_claim_ref="claim:t121",
            )
            capability = session.mint(binding)
            self.assertEqual(session.mint(binding), capability)
            self.assertIsNone(
                session.recover(
                    ExecutionCapabilityBinding(
                        authority=_authority(),
                        effect_id="effect:other",
                        intent_digest=binding.intent_digest,
                        vault_claim_ref=binding.vault_claim_ref,
                    ),
                    capability,
                )
            )
            session.release()
            resumed = module.HostPrivateExecutionCapabilityVault(
                facility
            ).acquire_or_resume_session(_authority(), proof)
            self.assertEqual(
                resumed.recover(binding, holder_id_for(capability)), capability
            )

    def test_v121_05_terminal_key_destruction_is_bounded(self) -> None:
        module = self._require()
        with tempfile.TemporaryDirectory(prefix="ticket121-") as raw:
            facility = self._facility(Path(raw))
            provider = module.HostPrivateKeyProvider(facility, _INSTALLATION)
            nonterminal = {
                "operation_ref": "delete:t121",
                "authority_binding": _authority().to_storage(),
                "transition_id": _authority().transition_id,
            }
            with self.assertRaises(Exception):
                provider.destroy(nonterminal)
            terminal = dict(nonterminal)
            terminal["authority_binding"] = _authority(terminal=True).to_storage()
            self.assertEqual(provider.destroy(terminal), {"status": "confirmed"})
            self.assertEqual(provider.absence(terminal), {"status": "absent"})
            self.assertEqual(provider.destroy(terminal), {"status": "confirmed"})
            self.assertTrue((facility / "writer-master.v1").is_file())
            self.assertTrue((facility / "execution-master.v1").is_file())

    def test_v121_06_linux_file_type_and_output_closure(self) -> None:
        module = self._require()
        with tempfile.TemporaryDirectory(prefix="ticket121-") as raw:
            root = Path(raw)
            facility = self._facility(root)
            original = facility / "data-key.v1"
            original.unlink()
            os.symlink(facility / "writer-master.v1", original)
            self.assertTrue(stat.S_ISLNK(os.lstat(original).st_mode))
            with self.assertRaises(Exception) as caught:
                module.HostPrivateKeyProvider(facility, _INSTALLATION)
            public = repr(caught.exception)
            for secret in (_DATA_KEY.hex(), _WRITER_MASTER.hex(), _EXECUTION_MASTER.hex(), raw):
                self.assertNotIn(secret, public)


if __name__ == "__main__":
    unittest.main()
