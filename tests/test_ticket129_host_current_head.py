"""Independent finite gates for the owner-selected host current-head port.

These tests use a real private file, real host writer vault, SQLite locking,
and independent processes. They never contact AWS or read a running profile.
"""
from __future__ import annotations

import contextlib
import copy
import importlib
import io
import multiprocessing
import os
import signal
import sqlite3
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from partner_health_steward.authority import WriterFenceProof, WriterHolderClaim
from partner_health_steward.current_head import (
    AdvanceRequest, CurrentHeadError, ExecutionLeaseRequest, ExecutionLeaseRelease,
    HeadConflict, HeadSnapshot, HeadTerminal, HeadTimeout, LifecycleTransitionRequest,
    TransitionNotFound, _ExecutionOverlapPermit,
)
from partner_health_steward.host_authority import HostPrivateWriterFenceVault
from tests import test_ticket123_production_core_service as service_fixture


_INSTALLATION = "installation:ticket129-offline"
_SITE = "site:ticket129-source"


def _race_worker(binding, request, start, pipe):
    from partner_health_steward.host_current_head import HostSQLiteCurrentHead
    port = HostSQLiteCurrentHead(binding)
    try:
        pipe.send("ready")
        if not start.wait(10):
            raise RuntimeError("offline CAS barrier timed out")
        try:
            result = port.conditional_advance(request)
            pipe.send(("applied", result.to_storage()))
        except CurrentHeadError as exc:
            pipe.send(("rejected", type(exc).__name__))
    finally:
        port.close()
        pipe.close()


def _commit_then_die(binding, request, pipe):
    from partner_health_steward.host_current_head import HostSQLiteCurrentHead
    port = HostSQLiteCurrentHead(binding)
    port.conditional_advance(request)
    # No head/result is returned to the caller. The process dies with its
    # connection open, after commit and before any application response.
    pipe.send("after-commit-before-response")
    os.kill(os.getpid(), signal.SIGKILL)


class Ticket129HostCurrentHeadVerificationTests(unittest.TestCase):
    maxDiff = None

    def _module(self):
        try:
            module = importlib.import_module("partner_health_steward.host_current_head")
        except ModuleNotFoundError:
            self.fail("129 prerequisite: persistent host current-head Provider is absent")
        self.assertTrue(callable(getattr(module, "HostHeadBinding", None)))
        self.assertTrue(callable(getattr(module, "HostSQLiteCurrentHead", None)))
        return module

    def _fixture(self):
        module = self._module()
        temporary = tempfile.TemporaryDirectory(prefix="ticket129-host-head-")
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        paths = service_fixture.Ticket123ProductionCoreServiceTests._facility(
            importlib.import_module("partner_health_steward.host_authority"), root)
        vault = HostPrivateWriterFenceVault(paths)
        fence = vault.prepare_fence_ref(_INSTALLATION, _SITE, "epoch:ticket129-source")
        holder = vault.acquire_or_resume(_INSTALLATION, _SITE, WriterHolderClaim("holder:ticket129-source"))
        self.assertIsNotNone(holder)
        self.addCleanup(holder.release)
        directory = root / "head"
        directory.mkdir(mode=0o700)
        binding = module.HostHeadBinding(str(directory / "current.sqlite"), _INSTALLATION, _SITE, fence)
        initial = HeadSnapshot(_INSTALLATION, 1, "sha256:v129-empty", "transition:v129-empty",
                               fence, False, _SITE)
        return module, root, paths, vault, holder, binding, initial

    def _bootstrap(self):
        values = self._fixture()
        module, _, _, _, holder, binding, initial = values
        port = module.HostSQLiteCurrentHead.bootstrap(binding, initial)
        self.addCleanup(port.close)
        proof = holder.proof_for(initial.as_authority())
        self.assertIsNotNone(proof)
        return (*values, port, proof)

    @staticmethod
    def _advance(head, proof, suffix="next", **changes):
        values = {
            "expected": head.as_authority(), "transition_id": "transition:v129-" + suffix,
            "revision_digest": "sha256:v129-" + suffix, "writer_fence": head.writer_fence,
            "operation_digest": "sha256:v129-operation-" + suffix, "writer_proof": proof,
        }
        values.update(changes)
        return AdvanceRequest(**values)

    def test_v129_01_only_explicit_new_bootstrap_and_private_identity_are_accepted(self):
        module, root, _, _, _, binding, initial = self._fixture()
        path = Path(binding.database_path)
        with self.assertRaises((CurrentHeadError, ValueError, OSError)):
            module.HostSQLiteCurrentHead(binding)
        self.assertFalse(path.exists())
        port = module.HostSQLiteCurrentHead.bootstrap(binding, initial)
        self.assertEqual(port.read().head, initial)
        port.close()
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        before = path.read_bytes()
        with self.assertRaises((CurrentHeadError, ValueError, OSError)):
            module.HostSQLiteCurrentHead.bootstrap(binding, replace(initial, revision_digest="sha256:overwrite"))
        self.assertEqual(path.read_bytes(), before)
        wrong = module.HostHeadBinding(str(path), "installation:wrong", _SITE, initial.writer_fence)
        with self.assertRaises((CurrentHeadError, ValueError, OSError)):
            module.HostSQLiteCurrentHead(wrong)
        self.assertEqual(path.read_bytes(), before)
        link = root / "head" / "linked.sqlite"
        link.symlink_to(path.name)
        with self.assertRaises((CurrentHeadError, ValueError, OSError)):
            module.HostSQLiteCurrentHead(module.HostHeadBinding(str(link), _INSTALLATION, _SITE, initial.writer_fence))
        link.unlink()
        os.link(path, link)
        with self.assertRaises((CurrentHeadError, ValueError, OSError)):
            module.HostSQLiteCurrentHead(binding)
        link.unlink()
        path.chmod(0o644)
        with self.assertRaises((CurrentHeadError, ValueError, OSError)):
            module.HostSQLiteCurrentHead(binding)
        path.chmod(0o600)
        path.parent.chmod(0o755)
        with self.assertRaises((CurrentHeadError, ValueError, OSError)):
            module.HostSQLiteCurrentHead(binding)
        path.parent.chmod(0o700)

    def test_v129_02_independent_processes_have_one_cas_winner_and_exact_receipt(self):
        module, _, _, _, _, binding, initial, port, proof = self._bootstrap()
        requests = [self._advance(initial, proof, suffix) for suffix in ("left", "right")]
        ctx = multiprocessing.get_context("fork")
        start = ctx.Event()
        pairs = [ctx.Pipe(duplex=False) for _ in requests]
        processes = [ctx.Process(target=_race_worker, args=(binding, request, start, child))
                     for request, (_, child) in zip(requests, pairs)]
        try:
            for process in processes: process.start()
            for parent, _ in pairs:
                self.assertTrue(parent.poll(10), "CAS worker did not open the real file")
                self.assertEqual(parent.recv(), "ready")
            start.set()
            results = []
            for parent, _ in pairs:
                self.assertTrue(parent.poll(10), "CAS worker did not return a bounded result")
                results.append(parent.recv())
            self.assertEqual([r[0] for r in results].count("applied"), 1, results)
            self.assertEqual([r[0] for r in results].count("rejected"), 1, results)
            winner = [r[0] for r in results].index("applied")
            observed = port.read().head
            self.assertEqual(observed.generation, initial.generation + 1)
            self.assertEqual(observed.to_storage(), results[winner][1])
            receipt = port.lookup_transition(requests[winner].identity())
            self.assertEqual(receipt.applied, observed)
            self.assertEqual(receipt.request, requests[winner].identity())
            with self.assertRaises((TransitionNotFound, HeadConflict)):
                port.lookup_transition(requests[1 - winner].identity())
            with self.assertRaises((TransitionNotFound, HeadConflict)):
                port.lookup_transition(replace(requests[winner].identity(), operation_digest="sha256:wrong-operation"))
            reopened = module.HostSQLiteCurrentHead(binding)
            try:
                self.assertEqual(reopened.lookup_transition(requests[winner].identity()), receipt)
                self.assertEqual(reopened.read().head, observed)
            finally: reopened.close()
            for process in processes:
                process.join(timeout=5)
                self.assertEqual(process.exitcode, 0)
        finally:
            for process in processes:
                process.join(timeout=2)
                if process.is_alive(): process.kill(); process.join(timeout=2)
            for parent, child in pairs: parent.close(); child.close()

    def test_v129_03_public_fence_does_not_replace_capability_or_current_authority(self):
        _, _, _, _, holder, _, initial, port, proof = self._bootstrap()
        forged = WriterFenceProof(initial.as_authority(), "SECRET_V129_FORGED_CAPABILITY")
        self.assertFalse(port.validate_writer_fence(forged))
        with self.assertRaises(HeadConflict):
            port.conditional_advance(self._advance(initial, forged, "forged"))
        self.assertEqual(port.read().head, initial)
        next_head = port.conditional_advance(self._advance(initial, proof))
        self.assertFalse(port.validate_writer_fence(proof))
        with self.assertRaises(HeadConflict):
            port.conditional_advance(self._advance(initial, proof, "old-holder"))
        current = holder.proof_for(next_head.as_authority())
        self.assertTrue(port.validate_writer_fence(current))

    def test_v129_04_lease_overlap_transfer_and_terminal_keep_liveness_separate_from_history(self):
        module, _, _, vault, holder, binding, initial, port, proof = self._bootstrap()
        request = ExecutionLeaseRequest(initial.as_authority(), "effect:v129-first", "sha256:v129-intent",
                                        initial.writer_fence, "holder:v129-effect", proof)
        receipt = port.acquire_execution_lease(request)
        self.assertEqual(port.acquire_execution_lease(request), receipt)
        self.assertEqual(port.lookup_execution_lease(request.identity()), receipt)
        with self.assertRaises(HeadConflict):
            port.acquire_execution_lease(replace(request, effect_id="effect:v129-competitor"))
        with self.assertRaises(HeadConflict):
            port.conditional_advance(self._advance(initial, proof, "without-overlap"))
        # This is the existing Core-only typed permit, not a new wire flag.
        advanced = port.conditional_advance(self._advance(
            initial, proof, "permitted-overlap",
            _execution_overlap=_ExecutionOverlapPermit(request.effect_id)))
        release = ExecutionLeaseRelease(receipt.lease, proof, "sha256:v129-release")
        released = port.release_execution_lease(release)
        self.assertTrue(released.released)
        self.assertEqual(port.release_execution_lease(release), released)
        with self.assertRaises(HeadConflict):
            port.release_execution_lease(replace(release, operation_digest="sha256:conflicting-release"))
        current_proof = holder.proof_for(advanced.as_authority())
        active = ExecutionLeaseRequest(advanced.as_authority(), "effect:v129-transfer", "sha256:v129-transfer-intent",
                                       advanced.writer_fence, "holder:v129-transfer-effect", current_proof)
        active_receipt = port.acquire_execution_lease(active)
        target_site = "site:ticket129-target"
        target_fence = vault.prepare_fence_ref(_INSTALLATION, target_site, "epoch:ticket129-target")
        transfer = LifecycleTransitionRequest(
            "writer-transfer", advanced.as_authority(), "operation:v129-transfer", "transition:v129-transfer",
            "sha256:v129-transfer", advanced.writer_fence, "sha256:v129-transfer-operation", current_proof,
            target_site, target_fence)
        transferred = port.conditional_lifecycle_transition(transfer)
        self.assertEqual((transferred.site, transferred.writer_fence), (target_site, target_fence))
        self.assertEqual(port.lookup_lifecycle_transition(transfer.identity()).applied, transferred)
        self.assertEqual(port.lookup_execution_lease(active.identity()), active_receipt)
        with self.assertRaises((HeadConflict, HeadTerminal)):
            port.acquire_execution_lease(active)
        with self.assertRaises((HeadConflict, HeadTerminal)):
            port.release_execution_lease(ExecutionLeaseRelease(active_receipt.lease, current_proof, "sha256:old-site-release"))
        target_binding = module.HostHeadBinding(binding.database_path, _INSTALLATION, target_site, target_fence)
        target = module.HostSQLiteCurrentHead(target_binding)
        self.addCleanup(target.close)
        target_holder = vault.acquire_or_resume(_INSTALLATION, target_site, WriterHolderClaim("holder:v129-target"))
        self.assertIsNotNone(target_holder)
        self.addCleanup(target_holder.release)
        target_proof = target_holder.proof_for(transferred.as_authority())
        pending = ExecutionLeaseRequest(transferred.as_authority(), "effect:v129-target", "sha256:v129-target-intent",
                                        target_fence, "holder:v129-target-effect", target_proof)
        target_receipt = target.acquire_execution_lease(pending)
        deletion = LifecycleTransitionRequest(
            "terminal-delete", transferred.as_authority(), "operation:v129-delete", "transition:v129-delete",
            "sha256:v129-delete", target_fence, "sha256:v129-delete-operation", target_proof)
        with self.assertRaises(HeadConflict): target.conditional_lifecycle_transition(deletion)
        target.release_execution_lease(ExecutionLeaseRelease(target_receipt.lease, target_proof, "sha256:target-release"))
        terminal = target.conditional_lifecycle_transition(deletion)
        self.assertTrue(terminal.terminal)
        self.assertEqual(target.lookup_lifecycle_transition(deletion.identity()).applied, terminal)
        with self.assertRaises(HeadTerminal): target.acquire_execution_lease(pending)
        with self.assertRaises(HeadTerminal): target.validate_writer_fence(target_proof)
        with self.assertRaises((CurrentHeadError, ValueError, OSError)):
            module.HostSQLiteCurrentHead.bootstrap(target_binding, initial)

    def test_v129_05_real_process_death_busy_and_replaced_or_corrupt_files_fail_closed(self):
        module, _, _, _, _, binding, initial, port, proof = self._bootstrap()
        request = self._advance(initial, proof, "lost-response")
        ctx = multiprocessing.get_context("fork")
        parent, child = ctx.Pipe(duplex=False)
        worker = ctx.Process(target=_commit_then_die, args=(binding, request, child))
        try:
            worker.start()
            self.assertTrue(parent.poll(10))
            self.assertEqual(parent.recv(), "after-commit-before-response")
            worker.join(timeout=5)
            self.assertEqual(worker.exitcode, -signal.SIGKILL)
        finally:
            if worker.is_alive(): worker.kill(); worker.join(timeout=2)
            parent.close(); child.close()
        recovered = module.HostSQLiteCurrentHead(binding)
        try:
            receipt = recovered.lookup_transition(request.identity())
            self.assertEqual(recovered.read().head, receipt.applied)
            self.assertEqual(receipt.applied.generation, 2)
        finally: recovered.close()
        current = port.read().head
        current_proof = replace(proof, authority=current.as_authority())
        blocked = self._advance(current, current_proof, "busy")
        external_lock = sqlite3.connect(binding.database_path, timeout=0.1)
        try:
            external_lock.execute("BEGIN IMMEDIATE")
            with self.assertRaises((HeadTimeout, HeadConflict)):
                port.conditional_advance(blocked)
        finally:
            external_lock.rollback(); external_lock.close()
        self.assertEqual(port.read().head, current)
        with self.assertRaises(TransitionNotFound): port.lookup_transition(blocked.identity())
        path = Path(binding.database_path)
        displaced = path.with_name("displaced.sqlite")
        path.rename(displaced)
        path.write_bytes(displaced.read_bytes()); path.chmod(0o600)
        with self.assertRaises(CurrentHeadError): port.read()
        path.write_bytes(b"CORRUPT_V129_MUST_NOT_BOOTSTRAP")
        before = path.read_bytes()
        with self.assertRaises((CurrentHeadError, ValueError, OSError)):
            module.HostSQLiteCurrentHead(binding)
        self.assertEqual(path.read_bytes(), before)

    def test_v129_06_no_capability_is_persisted_and_production_reports_host_provider(self):
        module, _, _, _, _, binding, initial, port, proof = self._bootstrap()
        self.assertEqual(port.provider_kind, "host-sqlite")
        output = io.StringIO()
        marker = "SECRET_V129_FORGED_CAPABILITY"
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            with self.assertRaises(HeadConflict) as captured:
                port.conditional_advance(self._advance(initial, WriterFenceProof(initial.as_authority(), marker), "redacted"))
            port.conditional_advance(self._advance(initial, proof, "no-secret"))
        self.assertNotIn(marker, str(captured.exception) + output.getvalue())
        for path in Path(binding.database_path).parent.iterdir():
            if path.is_file():
                raw = path.read_bytes()
                self.assertNotIn(proof.capability.encode(), raw)
                self.assertNotIn(marker.encode(), raw)
        producer = importlib.import_module("partner_health_steward.production_core_service")
        runtime_root = os.environ.get("TICKET123_RUNTIME_ROOT")
        self.assertIsNotNone(runtime_root, "formal production identity gate requires the 3.11 runtime")
        self.assertTrue(Path(producer.__file__).resolve().is_relative_to(Path(runtime_root).resolve()))
        fixture = service_fixture.Ticket123ProductionCoreServiceTests()
        fixture.module = producer
        with tempfile.TemporaryDirectory(prefix="ticket129-production-") as directory:
            _, service_binding, old_head, _ = fixture._fixture(Path(directory))
            parent = Path(directory) / "head"
            parent.mkdir(mode=0o700)
            authority = old_head.read().head
            host_binding = module.HostHeadBinding(str(parent / "current.sqlite"), authority.installation_id,
                                                  authority.site, authority.writer_fence)
            host = module.HostSQLiteCurrentHead.bootstrap(host_binding, authority)
            service = producer.ProductionCoreService(copy.deepcopy(service_binding), current_head=host)
            try:
                endpoint = service.start()
                response = fixture._request(endpoint, {"protocol_version": 1, "kind": "managed-read",
                    "request_id": "ticket129-provider-kind", "payload": {"projection": "health-runtime"}})
                self.assertEqual(response["payload"]["current_head_provider"], "host-sqlite")
                self.assertFalse(response["payload"]["health_writes_allowed"])
            finally:
                service.close(); host.close()


if __name__ == "__main__":
    unittest.main()
