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
    AdvanceRequest,
    HeadConflict,
    HeadRead,
    HeadUnknown,
    LifecycleTransitionRequest,
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


class _AwsError(RuntimeError):
    def __init__(self, code: str):
        self.response = {"Error": {"Code": code}}
        super().__init__("opaque aws failure")


class _ScriptedDynamo:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.items: list[dict[str, object] | None] = [_head_item()]
        self.transact_error: BaseException | None = None

    def describe_table(self, **kwargs):
        self.calls.append(("DescribeTable", kwargs))
        return {
            "Table": {
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
        }

    def get_item(self, **kwargs):
        self.calls.append(("GetItem", kwargs))
        item = self.items.pop(0) if self.items else None
        return {} if item is None else {"Item": item}

    def transact_write_items(self, **kwargs):
        self.calls.append(("TransactWriteItems", kwargs))
        if self.transact_error is not None:
            raise self.transact_error
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

    def _binding(self):
        module = self.module
        return module.DynamoHeadBinding(
            region="us-east-1",
            table_name="t122-fixture",
            table_arn=_TABLE_ARN,
            table_id="11111111-2222-3333-4444-555555555555",
            installation_id=_INSTALLATION,
            local_site="site:a",
            local_writer_fence_ref=_FENCE,
        )

    def _port(self, client: _ScriptedDynamo):
        return self.module.DynamoDBCurrentHead(client, self._binding())

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

    def test_v122_02_cas_and_receipt_are_one_transaction(self) -> None:
        self._require()
        client = _ScriptedDynamo()
        client.items = [_head_item(generation=2)]
        port = self._port(client)
        applied = port.conditional_advance(self._advance())
        self.assertEqual(applied.generation, 2)
        transactions = [value for name, value in client.calls if name == "TransactWriteItems"]
        self.assertEqual(len(transactions), 1)
        actions = transactions[0]["TransactItems"]
        self.assertEqual(len(actions), 2)
        self.assertTrue(all("ConditionCheck" not in action for action in actions))
        self.assertTrue(any("Update" in action and "ConditionExpression" in action["Update"] for action in actions))

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

        conflict = _ScriptedDynamo()
        conflict.transact_error = _AwsError("ConditionalCheckFailedException")
        with self.assertRaises(HeadConflict):
            self._port(conflict).conditional_advance(self._advance())

    def test_v122_04_execution_lease_surface_remains_exact(self) -> None:
        self._require()
        client = _ScriptedDynamo()
        port = self._port(client)
        for name in (
            "acquire_execution_lease",
            "lookup_execution_lease",
            "release_execution_lease",
        ):
            self.assertTrue(callable(getattr(port, name, None)))
        policy = self._binding().runtime_iam_policy()
        self.assertNotIn("dynamodb:Query", repr(policy))
        self.assertNotIn("dynamodb:Scan", repr(policy))

    def test_v122_05_transfer_uses_target_fence_instead_of_generating_one(self) -> None:
        self._require()
        client = _ScriptedDynamo()
        target_capability = "ticket122-target-capability"
        target_nonce = "8PH2_ZG7NnKq1oYfqxI9VQ"
        target_fence = (
            f"fence:v1:{target_nonce}:"
            f"{hashlib.sha256(target_capability.encode()).hexdigest()}"
        )
        client.items = [_head_item(generation=2, site="site:b", fence=target_fence)]
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
        wire = repr([value for name, value in client.calls if name == "TransactWriteItems"])
        self.assertIn(target_fence, wire)

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


if __name__ == "__main__":
    unittest.main()
