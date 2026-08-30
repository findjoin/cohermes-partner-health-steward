"""Verifier-owned frozen gates for Ticket 122.

This file fixes the public constructor, AWS call surface and seven externally
observable gates.  It deliberately does not import boto3.
"""

from __future__ import annotations

import hashlib
import importlib
import unittest

from partner_health_steward.authority import AuthoritySnapshot, WriterFenceProof
from partner_health_steward.current_head import (
    AdvanceIdentity,
    AdvanceRequest,
    ExecutionLeaseIdentity,
    ExecutionLeaseRequest,
    ExecutionLeaseRelease,
    ExecutionLeaseNotFound,
    CurrentHeadError,
    HeadConflict,
    HeadRead,
    HeadTerminal,
    HeadTimeout,
    HeadUnknown,
    LifecycleTransitionIdentity,
    LifecycleTransitionRequest,
    TransitionNotFound,
)


_CAPABILITY = "ticket122-writer-capability"
_NONCE = "ABEiM0RVZneImaq7zN3u_w"
_FENCE = f"fence:v1:{_NONCE}:{hashlib.sha256(_CAPABILITY.encode()).hexdigest()}"
_INSTALLATION = "installation:t122-fixture"
_TABLE_ARN = "arn:aws:dynamodb:us-east-1:111122223333:table/t122-fixture"


def _ddb_s(value: str) -> dict[str, str]:
    return {"S": value}


def _ddb_n(value: int) -> dict[str, str]:
    return {"N": str(value)}


def _head_item(*, generation: int = 1, terminal: bool = False, site: str = "site:a", fence: str = _FENCE):
    return {
        "PK": _ddb_s(_INSTALLATION),
        "SK": _ddb_s("HEAD"),
        "schema_version": _ddb_n(1),
        "generation": _ddb_n(generation),
        "revision_digest": _ddb_s("sha256:empty" if generation == 1 else "sha256:next"),
        "transition_id": _ddb_s("transition:empty" if generation == 1 else "transition:next"),
        "writer_fence": _ddb_s(fence),
        "terminal": {"BOOL": terminal},
        "site": _ddb_s(site),
    }


def _transition_item(request: AdvanceRequest):
    return {
        "PK": _ddb_s(_INSTALLATION),
        "SK": _ddb_s("TRANSITION#transition:next#sha256:operation"),
        "schema_version": _ddb_n(1),
        "kind": _ddb_s("advance"),
        "expected_generation": _ddb_n(1),
        "expected_revision_digest": _ddb_s("sha256:empty"),
        "expected_transition_id": _ddb_s("transition:empty"),
        "expected_writer_fence": _ddb_s(_FENCE),
        "expected_terminal": {"BOOL": False},
        "expected_site": _ddb_s("site:a"),
        "transition_id": _ddb_s("transition:next"),
        "revision_digest": _ddb_s("sha256:next"),
        "operation_digest": _ddb_s("sha256:operation"),
        "applied_generation": _ddb_n(2),
        "applied_revision_digest": _ddb_s("sha256:next"),
        "applied_transition_id": _ddb_s("transition:next"),
        "applied_writer_fence": _ddb_s(_FENCE),
        "applied_terminal": {"BOOL": False},
        "applied_site": _ddb_s("site:a"),
    }


def _lease_item(*, released: bool = False):
    item = {
        "PK": _ddb_s(_INSTALLATION),
        "SK": _ddb_s("LEASE#effect:t122"),
        "schema_version": _ddb_n(1),
        "expected_generation": _ddb_n(1),
        "expected_revision_digest": _ddb_s("sha256:empty"),
        "expected_transition_id": _ddb_s("transition:empty"),
        "expected_writer_fence": _ddb_s(_FENCE),
        "expected_terminal": {"BOOL": False},
        "expected_site": _ddb_s("site:a"),
        "effect_id": _ddb_s("effect:t122"),
        "intent_digest": _ddb_s("sha256:intent"),
        "holder_id": _ddb_s("holder:t122"),
        "lease_id": _ddb_s("lease:t122"),
        "released": {"BOOL": released},
    }
    if released:
        item["released_operation_digest"] = _ddb_s("sha256:release")
    return item


def _lifecycle_item(target_fence: str):
    return {
        "PK": _ddb_s(_INSTALLATION),
        "SK": _ddb_s("LIFECYCLE#migration:t122#sha256:migration"),
        "schema_version": _ddb_n(1),
        "kind": _ddb_s("writer-transfer"),
        "operation_ref": _ddb_s("migration:t122"),
        "operation_digest": _ddb_s("sha256:migration"),
        "expected_generation": _ddb_n(1),
        "expected_revision_digest": _ddb_s("sha256:empty"),
        "expected_transition_id": _ddb_s("transition:empty"),
        "expected_writer_fence": _ddb_s(_FENCE),
        "expected_terminal": {"BOOL": False},
        "expected_site": _ddb_s("site:a"),
        "transition_id": _ddb_s("transition:next"),
        "revision_digest": _ddb_s("sha256:next"),
        "target_site": _ddb_s("site:b"),
        "target_writer_fence_ref": _ddb_s(target_fence),
        "applied_generation": _ddb_n(2),
        "applied_revision_digest": _ddb_s("sha256:next"),
        "applied_transition_id": _ddb_s("transition:next"),
        "applied_writer_fence": _ddb_s(target_fence),
        "applied_terminal": {"BOOL": False},
        "applied_site": _ddb_s("site:b"),
    }


class _AwsError(RuntimeError):
    def __init__(self, code: str):
        self.response = {"Error": {"Code": code}}
        super().__init__("opaque aws failure")


class _ScriptedDynamo:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.items: list[dict[str, object] | None] = []
        self.records: dict[str, dict[str, object]] = {"HEAD": _head_item()}
        self.active_effect: str | None = None
        self.get_error: BaseException | None = None
        self.transact_error: BaseException | None = None
        self.transact_error_after_apply: BaseException | None = None
        self.table_overrides: dict[str, object] = {}

    def describe_table(self, **kwargs):
        self.calls.append(("DescribeTable", kwargs))
        table = {
                "TableName": "t122-fixture",
                "TableArn": _TABLE_ARN,
                "TableId": "11111111-2222-3333-4444-555555555555",
                "TableStatus": "ACTIVE",
                "KeySchema": [
                    {"AttributeName": "PK", "KeyType": "HASH"},
                    {"AttributeName": "SK", "KeyType": "RANGE"},
                ],
                "AttributeDefinitions": [
                    {"AttributeName": "PK", "AttributeType": "S"},
                    {"AttributeName": "SK", "AttributeType": "S"},
                ],
            }
        table.update(self.table_overrides)
        return {"Table": table}

    def get_item(self, **kwargs):
        self.calls.append(("GetItem", kwargs))
        if self.get_error is not None:
            raise self.get_error
        if self.items:
            item = self.items.pop(0)
        else:
            key = kwargs["Key"]
            item = self.records.get(key["SK"]["S"])
        return {} if item is None else {"Item": item}

    def transact_write_items(self, **kwargs):
        self.calls.append(("TransactWriteItems", kwargs))
        if self.transact_error is not None:
            raise self.transact_error
        actions = kwargs["TransactItems"]
        puts = [action["Put"]["Item"] for action in actions if "Put" in action]
        updates = [action["Update"] for action in actions if "Update" in action]
        head_updates = [
            update for update in updates if update["Key"]["SK"]["S"] == "HEAD"
        ]
        if head_updates:
            update = head_updates[0]
            values = update.get("ExpressionAttributeValues", {})
            condition = update.get("ConditionExpression", "")
            required = {
                ":expected_generation": self.records["HEAD"]["generation"],
                ":expected_revision_digest": self.records["HEAD"]["revision_digest"],
                ":expected_transition_id": self.records["HEAD"]["transition_id"],
                ":expected_writer_fence": self.records["HEAD"]["writer_fence"],
                ":expected_terminal": self.records["HEAD"]["terminal"],
                ":expected_site": self.records["HEAD"]["site"],
            }
            if any(name not in condition or name not in values for name in required):
                raise AssertionError("HEAD condition does not bind the complete expected authority")
            if any(values[name] != value for name, value in required.items()):
                raise _AwsError("ConditionalCheckFailedException")
            if any(item["SK"]["S"].startswith("LIFECYCLE#") for item in puts):
                receipt = next(item for item in puts if item["SK"]["S"].startswith("LIFECYCLE#"))
                if receipt["kind"]["S"] == "terminal-delete" and self.active_effect is not None:
                    raise _AwsError("ConditionalCheckFailedException")
                self.records["HEAD"] = _head_item(
                    generation=int(receipt["applied_generation"]["N"]),
                    terminal=receipt["applied_terminal"]["BOOL"],
                    site=receipt["applied_site"]["S"],
                    fence=receipt["applied_writer_fence"]["S"],
                )
                self.records[receipt["SK"]["S"]] = receipt
                self.active_effect = None
            else:
                receipt = next(item for item in puts if item["SK"]["S"].startswith("TRANSITION#"))
                self.records["HEAD"] = _head_item(
                    generation=int(receipt["applied_generation"]["N"])
                )
                self.records[receipt["SK"]["S"]] = receipt
        elif any(item["SK"]["S"].startswith("LEASE#") for item in puts):
            receipt = next(item for item in puts if item["SK"]["S"].startswith("LEASE#"))
            guard = next(update for update in updates if update["Key"]["SK"]["S"] == "LEASE-GUARD")
            condition = guard.get("ConditionExpression", "")
            values = guard.get("ExpressionAttributeValues", {})
            for name, value in (
                (":expected_generation", self.records["HEAD"]["generation"]),
                (":expected_writer_fence", self.records["HEAD"]["writer_fence"]),
                (":effect_id", receipt["effect_id"]),
            ):
                if values.get(name) != value or name not in condition:
                    raise AssertionError("lease guard condition is incomplete")
            if self.active_effect is not None:
                raise _AwsError("ConditionalCheckFailedException")
            self.active_effect = receipt["effect_id"]["S"]
            self.records[receipt["SK"]["S"]] = receipt
        else:
            lease_updates = [
                update
                for update in updates
                if update["Key"]["SK"]["S"].startswith("LEASE#")
            ]
            if lease_updates:
                lease_update = lease_updates[0]
                condition = lease_update.get("ConditionExpression", "")
                values = lease_update.get("ExpressionAttributeValues", {})
                for name in (":lease_id", ":holder_id", ":released_false", ":release_operation_digest"):
                    if name not in values or name not in condition:
                        raise AssertionError("lease release condition is incomplete")
                sk = lease_update["Key"]["SK"]["S"]
                receipt = dict(self.records[sk])
                if receipt["released"]["BOOL"]:
                    raise _AwsError("ConditionalCheckFailedException")
                receipt["released"] = {"BOOL": True}
                receipt["released_operation_digest"] = values[":release_operation_digest"]
                self.records[sk] = receipt
                self.active_effect = None
        if self.transact_error_after_apply is not None:
            raise self.transact_error_after_apply
        return {}


class Ticket122DynamoDBCurrentHeadTests(unittest.TestCase):
    module = None

    @classmethod
    def setUpClass(cls) -> None:
        try:
            cls.module = importlib.import_module(
                "partner_health_steward.dynamodb_current_head"
            )
        except BaseException:
            cls.module = None

    def _require(self, *, red: bool = False):
        if self.module is None:
            message = "Ticket 122 DynamoDB current-head module is absent"
            if red:
                self.fail(message)
            self.skipTest(message)
        return self.module

    def _binding(self, *, site: str = "site:a", fence: str = _FENCE):
        module = self.module
        return module.DynamoHeadBinding(
            region="us-east-1",
            table_name="t122-fixture",
            table_arn=_TABLE_ARN,
            table_id="11111111-2222-3333-4444-555555555555",
            installation_id=_INSTALLATION,
            local_site=site,
            local_writer_fence_ref=fence,
        )

    def _port(self, client: _ScriptedDynamo, *, site: str = "site:a", fence: str = _FENCE):
        return self.module.DynamoDBCurrentHead(client, self._binding(site=site, fence=fence))

    def _authority(self) -> AuthoritySnapshot:
        return AuthoritySnapshot(
            _INSTALLATION,
            1,
            "sha256:empty",
            "transition:empty",
            _FENCE,
            False,
            "site:a",
        )

    def _advance(self) -> AdvanceRequest:
        authority = self._authority()
        return AdvanceRequest(
            expected=authority,
            transition_id="transition:next",
            revision_digest="sha256:next",
            writer_fence=_FENCE,
            operation_digest="sha256:operation",
            writer_proof=WriterFenceProof(authority, _CAPABILITY),
        )

    def test_v122_01_binds_resource_and_uses_strong_reads(self) -> None:
        self._require(red=True)
        client = _ScriptedDynamo()
        port = self._port(client)
        read = port.read()
        self.assertIsInstance(read, HeadRead)
        self.assertEqual(read.head.as_authority(), self._authority())
        self.assertEqual(client.calls[0], ("DescribeTable", {"TableName": "t122-fixture"}))
        get = [value for name, value in client.calls if name == "GetItem"][-1]
        self.assertIs(get.get("ConsistentRead"), True)
        self.assertEqual(get.get("TableName"), "t122-fixture")

        missing = _ScriptedDynamo()
        missing.records.pop("HEAD")
        with self.assertRaises(CurrentHeadError):
            self._port(missing).read()
        self.assertFalse(
            any(name == "TransactWriteItems" for name, _ in missing.calls)
        )

        for override in (
            {"TableArn": _TABLE_ARN + "-recreated"},
            {"TableId": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"},
            {"TableStatus": "CREATING"},
            {"KeySchema": [{"AttributeName": "PK", "KeyType": "HASH"}]},
        ):
            bad = _ScriptedDynamo()
            bad.table_overrides = override
            with self.assertRaises(CurrentHeadError):
                self._port(bad)

        unknown = _ScriptedDynamo()
        unknown.records["HEAD"] = dict(_head_item(), unexpected=_ddb_s("no"))
        with self.assertRaises(CurrentHeadError):
            self._port(unknown).read()

    def test_v122_02_cas_and_receipt_are_one_transaction(self) -> None:
        self._require()
        client = _ScriptedDynamo()
        port = self._port(client)
        applied = port.conditional_advance(self._advance())
        self.assertEqual(applied.generation, 2)
        transactions = [value for name, value in client.calls if name == "TransactWriteItems"]
        self.assertEqual(len(transactions), 1)
        actions = transactions[0]["TransactItems"]
        self.assertEqual(len(actions), 2)
        self.assertTrue(all("ConditionCheck" not in action for action in actions))
        self.assertTrue(any("Update" in action and "ConditionExpression" in action["Update"] for action in actions))
        rendered = repr(actions)
        for value in (
            _INSTALLATION,
            "sha256:empty",
            "transition:empty",
            _FENCE,
            "site:a",
            "sha256:operation",
            "sha256:next",
            "transition:next",
        ):
            self.assertIn(value, rendered)
        receipt_puts = [action["Put"]["Item"] for action in actions if "Put" in action]
        self.assertEqual(receipt_puts, [_transition_item(self._advance())])

        with self.assertRaises(HeadConflict):
            port.conditional_advance(self._advance())
        self.assertIn(
            sum(name == "TransactWriteItems" for name, _ in client.calls),
            {1, 2},
        )
        self.assertEqual(client.records["HEAD"]["generation"], _ddb_n(2))
        self.assertEqual(
            len([key for key in client.records if key.startswith("TRANSITION#")]),
            1,
        )

    def test_v122_03_maps_ambiguous_mutation_without_retry(self) -> None:
        self._require()
        client = _ScriptedDynamo()
        client.transact_error = _AwsError("RequestTimeout")
        port = self._port(client)
        with self.assertRaises(HeadUnknown):
            port.conditional_advance(self._advance())
        self.assertEqual(
            sum(name == "TransactWriteItems" for name, _ in client.calls),
            1,
        )

        lost = _ScriptedDynamo()
        lost.transact_error_after_apply = _AwsError("RequestTimeout")
        lost_port = self._port(lost)
        with self.assertRaises(HeadUnknown):
            lost_port.conditional_advance(self._advance())
        lost.transact_error_after_apply = None
        recovered = lost_port.lookup_transition(self._advance().identity())
        self.assertEqual(recovered.request, self._advance().identity())

        conflict = _ScriptedDynamo()
        conflict.transact_error = _AwsError("ConditionalCheckFailedException")
        with self.assertRaises(HeadConflict):
            self._port(conflict).conditional_advance(self._advance())

        timed_read = _ScriptedDynamo()
        timed_read.get_error = _AwsError("RequestTimeout")
        with self.assertRaises(HeadTimeout):
            self._port(timed_read).read()
        self.assertEqual(sum(name == "GetItem" for name, _ in timed_read.calls), 1)

        lookup = _ScriptedDynamo()
        lookup.items = [_transition_item(self._advance())]
        applied = self._port(lookup).lookup_transition(self._advance().identity())
        self.assertEqual(applied.request, self._advance().identity())
        self.assertEqual(applied.applied.generation, 2)
        get = [value for name, value in lookup.calls if name == "GetItem"][-1]
        self.assertIs(get.get("ConsistentRead"), True)
        missing = _ScriptedDynamo()
        missing.items = [None]
        with self.assertRaises(TransitionNotFound):
            self._port(missing).lookup_transition(self._advance().identity())

    def test_v122_04_execution_lease_surface_remains_exact(self) -> None:
        self._require()
        client = _ScriptedDynamo()
        client.items = [_lease_item()]
        port = self._port(client)
        request = ExecutionLeaseRequest(
            expected=self._authority(),
            effect_id="effect:t122",
            intent_digest="sha256:intent",
            writer_fence=_FENCE,
            holder_id="holder:t122",
            writer_proof=WriterFenceProof(self._authority(), _CAPABILITY),
        )
        receipt = port.acquire_execution_lease(request)
        self.assertEqual(receipt.request, request.identity())
        self.assertFalse(receipt.released)
        transaction = [value for name, value in client.calls if name == "TransactWriteItems"][-1]
        self.assertEqual(len(transaction["TransactItems"]), 2)
        self.assertIn("LEASE-GUARD", repr(transaction))
        self.assertIn("effect:t122", repr(transaction))
        lease_put = next(
            action["Put"]["Item"]
            for action in transaction["TransactItems"]
            if "Put" in action
        )
        self.assertEqual(lease_put, _lease_item())
        before_repeat = sum(name == "TransactWriteItems" for name, _ in client.calls)
        self.assertEqual(port.acquire_execution_lease(request), receipt)
        self.assertEqual(
            sum(name == "TransactWriteItems" for name, _ in client.calls),
            before_repeat,
        )

        lookup = _ScriptedDynamo()
        lookup.items = [_lease_item()]
        self.assertEqual(self._port(lookup).lookup_execution_lease(request.identity()).request, request.identity())

        release_client = _ScriptedDynamo()
        release_client.records["LEASE#effect:t122"] = _lease_item()
        release_client.active_effect = "effect:t122"
        release_port = self._port(release_client)
        released = release_port.release_execution_lease(
            ExecutionLeaseRelease(
                lease=receipt.lease,
                writer_proof=WriterFenceProof(self._authority(), _CAPABILITY),
                operation_digest="sha256:release",
            )
        )
        self.assertTrue(released.released)
        self.assertEqual(released.released_operation_digest, "sha256:release")

        with self.assertRaises(HeadConflict):
            release_port.release_execution_lease(
                ExecutionLeaseRelease(
                    lease=receipt.lease,
                    writer_proof=WriterFenceProof(self._authority(), _CAPABILITY),
                    operation_digest="sha256:different-release",
                )
            )

        overlap_request = ExecutionLeaseRequest(
            expected=self._authority(),
            effect_id="effect:other",
            intent_digest="sha256:other-intent",
            writer_fence=_FENCE,
            holder_id="holder:other",
            writer_proof=WriterFenceProof(self._authority(), _CAPABILITY),
        )
        with self.assertRaises(HeadConflict):
            port.acquire_execution_lease(overlap_request)

        missing = _ScriptedDynamo()
        missing.items = [None]
        with self.assertRaises(ExecutionLeaseNotFound):
            self._port(missing).lookup_execution_lease(request.identity())

        other_holder = ExecutionLeaseIdentity(
            expected=self._authority(),
            effect_id="effect:t122",
            intent_digest="sha256:intent",
            writer_fence=_FENCE,
            holder_id="holder:other",
        )
        wrong = _ScriptedDynamo()
        wrong.items = [_lease_item()]
        with self.assertRaises(HeadConflict):
            self._port(wrong).lookup_execution_lease(other_holder)

        terminal = _ScriptedDynamo()
        terminal.transact_error = _AwsError("ConditionalCheckFailedException")
        terminal.items = [_head_item(terminal=True)]
        with self.assertRaises(HeadTerminal):
            self._port(terminal).acquire_execution_lease(request)

    def test_v122_05_transfer_uses_target_fence_instead_of_generating_one(self) -> None:
        self._require()
        client = _ScriptedDynamo()
        target_capability = "ticket122-target-capability"
        target_nonce = "8PH2_ZG7NnKq1oYfqxI9VQ"
        target_fence = (
            f"fence:v1:{target_nonce}:"
            f"{hashlib.sha256(target_capability.encode()).hexdigest()}"
        )
        client.records["LEASE#effect:t122"] = _lease_item()
        client.active_effect = "effect:t122"
        port = self._port(client)
        request = LifecycleTransitionRequest(
            kind="writer-transfer",
            expected=self._authority(),
            operation_ref="migration:t122",
            transition_id="transition:next",
            revision_digest="sha256:next",
            writer_fence=_FENCE,
            operation_digest="sha256:migration",
            writer_proof=WriterFenceProof(self._authority(), _CAPABILITY),
            target_site="site:b",
            target_writer_fence_ref=target_fence,
        )
        applied = port.conditional_lifecycle_transition(request)
        self.assertEqual(applied.writer_fence, target_fence)
        transactions = [value for name, value in client.calls if name == "TransactWriteItems"]
        wire = repr(transactions)
        self.assertIn(target_fence, wire)
        self.assertIn("site:b", wire)
        self.assertIn("LEASE-GUARD", wire)
        self.assertNotIn(target_capability, wire)
        self.assertIn("LEASE#effect:t122", client.records)
        self.assertIsNone(client.active_effect)
        self.assertFalse(port.validate_writer_fence(WriterFenceProof(self._authority(), _CAPABILITY)))

        target_client = _ScriptedDynamo()
        target_client.items = [_head_item(generation=2, site="site:b", fence=target_fence)]
        target_authority = AuthoritySnapshot(
            _INSTALLATION,
            2,
            "sha256:next",
            "transition:next",
            target_fence,
            False,
            "site:b",
        )
        self.assertTrue(
            self._port(target_client, site="site:b", fence=target_fence).validate_writer_fence(
                WriterFenceProof(target_authority, target_capability)
            )
        )

        lookup = _ScriptedDynamo()
        lookup.items = [_lifecycle_item(target_fence)]
        result = self._port(lookup).lookup_lifecycle_transition(request.identity())
        self.assertEqual(result.request, request.identity())
        self.assertEqual(result.applied.writer_fence, target_fence)

        lost = _ScriptedDynamo()
        lost.transact_error_after_apply = _AwsError("RequestTimeout")
        lost_port = self._port(lost)
        with self.assertRaises(HeadUnknown):
            lost_port.conditional_lifecycle_transition(request)
        lost.transact_error_after_apply = None
        self.assertEqual(
            lost_port.lookup_lifecycle_transition(request.identity()).request,
            request.identity(),
        )

        terminal_client = _ScriptedDynamo()
        terminal_client.records["LEASE#effect:t122"] = _lease_item()
        terminal_client.active_effect = "effect:t122"
        terminal_request = LifecycleTransitionRequest(
            kind="terminal-delete",
            expected=self._authority(),
            operation_ref="delete:t122",
            transition_id="transition:next",
            revision_digest="sha256:next",
            writer_fence=_FENCE,
            operation_digest="sha256:delete",
            writer_proof=WriterFenceProof(self._authority(), _CAPABILITY),
        )
        with self.assertRaises(HeadConflict):
            self._port(terminal_client).conditional_lifecycle_transition(
                terminal_request
            )

    def test_v122_06_exposes_exact_existing_port_only(self) -> None:
        self._require()
        port = self._port(_ScriptedDynamo())
        expected = {
            "read",
            "conditional_advance",
            "lookup_transition",
            "conditional_lifecycle_transition",
            "lookup_lifecycle_transition",
            "validate_writer_fence",
            "acquire_execution_lease",
            "lookup_execution_lease",
            "release_execution_lease",
        }
        self.assertTrue(all(callable(getattr(port, name, None)) for name in expected))
        self.assertFalse(hasattr(port, "create_table"))
        self.assertFalse(hasattr(port, "bootstrap_head"))

    def test_v122_07_iam_and_requests_have_a_closed_data_surface(self) -> None:
        self._require()
        client = _ScriptedDynamo()
        port = self._port(client)
        port.read()
        policy = self._binding().runtime_iam_policy()
        rendered = repr((client.calls, policy))
        for forbidden in (
            _CAPABILITY,
            "health_body",
            "owner_id",
            "contact_id",
            "credential",
            "dynamodb:Query",
            "dynamodb:Scan",
        ):
            self.assertNotIn(forbidden, rendered)
        self.assertIn(_TABLE_ARN, rendered)
        self.assertIn("dynamodb:LeadingKeys", rendered)
        self.assertIn("ForAllValues:StringLike", rendered)
        actions = {
            action
            for statement in policy["Statement"]
            for action in statement["Action"]
        }
        self.assertEqual(
            actions,
            {"dynamodb:DescribeTable", "dynamodb:GetItem", "dynamodb:TransactWriteItems"},
        )
        data_statements = [
            statement
            for statement in policy["Statement"]
            if "dynamodb:GetItem" in statement["Action"]
        ]
        self.assertEqual(len(data_statements), 1)
        condition = data_statements[0]["Condition"]
        self.assertIn("dynamodb:LeadingKeys", repr(condition))
        self.assertIn("dynamodb:Attributes", repr(condition))


if __name__ == "__main__":
    unittest.main()
