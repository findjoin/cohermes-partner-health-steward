"""Single-region DynamoDB adapter for the existing current-head port.

The adapter accepts an already-created low-level DynamoDB client.  It does not
load credentials, create resources, bootstrap state, or retry business writes.
"""

from __future__ import annotations

import hashlib
import hmac
import re
from dataclasses import dataclass
from typing import Mapping

from .authority import (
    AuthoritySnapshot,
    AuthorityValidationError,
    ExecutionLease,
    WriterFenceProof,
    validate_opaque_text,
)
from .current_head import (
    AdvanceIdentity,
    AdvanceRequest,
    AppliedLifecycleTransition,
    AppliedTransition,
    CurrentHeadError,
    ExecutionLeaseIdentity,
    ExecutionLeaseNotFound,
    ExecutionLeaseReceipt,
    ExecutionLeaseRelease,
    ExecutionLeaseRequest,
    HeadConflict,
    HeadRead,
    HeadSnapshot,
    HeadTerminal,
    HeadTimeout,
    HeadUnknown,
    LifecycleTransitionIdentity,
    LifecycleTransitionRequest,
    TransitionNotFound,
)


_SCHEMA_VERSION = 1
_FENCE_PATTERN = re.compile(
    r"^fence:v1:[A-Za-z0-9_-]{22}:([0-9a-f]{64})$"
)
_TABLE_ARN_PATTERN = re.compile(
    r"^arn:(?P<partition>[^:]+):dynamodb:(?P<region>[^:]+):"
    r"(?P<account>[0-9]{12}):table/(?P<table>[^/]+)$"
)
_TIMEOUT_CODES = frozenset(
    {"RequestTimeout", "RequestTimeoutException", "PriorRequestNotComplete"}
)
_CONFLICT_CODES = frozenset(
    {"ConditionalCheckFailedException", "TransactionCanceledException"}
)
_KNOWN_NONAMBIGUOUS_MUTATION_ERRORS = frozenset(
    {
        "AccessDeniedException",
        "IncompleteSignatureException",
        "InvalidSignatureException",
        "MissingAuthenticationTokenException",
        "ResourceNotFoundException",
        "UnrecognizedClientException",
        "ValidationException",
    }
)

_HEAD_FIELDS = frozenset(
    {
        "PK",
        "SK",
        "schema_version",
        "generation",
        "revision_digest",
        "transition_id",
        "writer_fence",
        "terminal",
        "site",
    }
)
_EXPECTED_FIELDS = frozenset(
    {
        "expected_generation",
        "expected_revision_digest",
        "expected_transition_id",
        "expected_writer_fence",
        "expected_terminal",
        "expected_site",
    }
)
_APPLIED_FIELDS = frozenset(
    {
        "applied_generation",
        "applied_revision_digest",
        "applied_transition_id",
        "applied_writer_fence",
        "applied_terminal",
        "applied_site",
    }
)
_TRANSITION_FIELDS = frozenset(
    {"PK", "SK", "schema_version", "kind", "transition_id", "revision_digest", "operation_digest"}
) | _EXPECTED_FIELDS | _APPLIED_FIELDS
_LIFECYCLE_BASE_FIELDS = frozenset(
    {
        "PK",
        "SK",
        "schema_version",
        "kind",
        "operation_ref",
        "operation_digest",
        "transition_id",
        "revision_digest",
    }
) | _EXPECTED_FIELDS | _APPLIED_FIELDS
_LEASE_BASE_FIELDS = frozenset(
    {
        "PK",
        "SK",
        "schema_version",
        "effect_id",
        "intent_digest",
        "holder_id",
        "lease_id",
        "released",
    }
) | _EXPECTED_FIELDS
_REMOTE_ATTRIBUTES = tuple(
    sorted(
        _HEAD_FIELDS
        | _TRANSITION_FIELDS
        | _LIFECYCLE_BASE_FIELDS
        | {"target_site", "target_writer_fence_ref"}
        | _LEASE_BASE_FIELDS
        | {"released_operation_digest", "active_effect_ids"}
    )
)


def _s(value: str) -> dict[str, str]:
    return {"S": value}


def _n(value: int) -> dict[str, str]:
    return {"N": str(value)}


def _b(value: bool) -> dict[str, bool]:
    return {"BOOL": value}


def _ss(values: set[str] | frozenset[str]) -> dict[str, list[str]]:
    return {"SS": sorted(values)}


def _aws_code(exc: BaseException) -> str | None:
    response = getattr(exc, "response", None)
    if type(response) is not dict:
        return None
    error = response.get("Error")
    if type(error) is not dict or type(error.get("Code")) is not str:
        return None
    return error["Code"]


def _require_fields(item: object, allowed: frozenset[str], kind: str) -> Mapping[str, object]:
    if type(item) is not dict or frozenset(item) != allowed:
        raise CurrentHeadError(f"invalid DynamoDB {kind} item")
    return item


def _read_s(item: Mapping[str, object], name: str) -> str:
    value = item.get(name)
    if type(value) is not dict or set(value) != {"S"}:
        raise CurrentHeadError("invalid DynamoDB string attribute")
    try:
        return validate_opaque_text(value["S"], name)  # type: ignore[arg-type]
    except AuthorityValidationError as exc:
        raise CurrentHeadError("invalid DynamoDB string attribute") from exc


def _read_n(item: Mapping[str, object], name: str) -> int:
    value = item.get(name)
    if type(value) is not dict or set(value) != {"N"} or type(value["N"]) is not str:
        raise CurrentHeadError("invalid DynamoDB number attribute")
    text = value["N"]
    if not re.fullmatch(r"[1-9][0-9]*", text):
        raise CurrentHeadError("invalid DynamoDB number attribute")
    return int(text)


def _read_bool(item: Mapping[str, object], name: str) -> bool:
    value = item.get(name)
    if type(value) is not dict or set(value) != {"BOOL"} or type(value["BOOL"]) is not bool:
        raise CurrentHeadError("invalid DynamoDB boolean attribute")
    return value["BOOL"]


def _expected_values(authority: AuthoritySnapshot) -> dict[str, object]:
    return {
        "expected_generation": _n(authority.generation),
        "expected_revision_digest": _s(authority.revision_digest),
        "expected_transition_id": _s(authority.transition_id),
        "expected_writer_fence": _s(authority.writer_fence),
        "expected_terminal": _b(authority.terminal),
        "expected_site": _s(authority.site),
    }


def _applied_values(authority: AuthoritySnapshot) -> dict[str, object]:
    return {
        "applied_generation": _n(authority.generation),
        "applied_revision_digest": _s(authority.revision_digest),
        "applied_transition_id": _s(authority.transition_id),
        "applied_writer_fence": _s(authority.writer_fence),
        "applied_terminal": _b(authority.terminal),
        "applied_site": _s(authority.site),
    }


def _authority_from_fields(
    item: Mapping[str, object], installation_id: str, prefix: str = ""
) -> AuthoritySnapshot:
    return AuthoritySnapshot(
        installation_id=installation_id,
        generation=_read_n(item, prefix + "generation"),
        revision_digest=_read_s(item, prefix + "revision_digest"),
        transition_id=_read_s(item, prefix + "transition_id"),
        writer_fence=_read_s(item, prefix + "writer_fence"),
        terminal=_read_bool(item, prefix + "terminal"),
        site=_read_s(item, prefix + "site"),
    )


def _condition_names() -> dict[str, str]:
    return {
        "#g": "generation",
        "#r": "revision_digest",
        "#t": "transition_id",
        "#w": "writer_fence",
        "#x": "terminal",
        "#s": "site",
    }


def _head_condition_values(expected: AuthoritySnapshot) -> dict[str, object]:
    return {
        ":eg": _n(expected.generation),
        ":er": _s(expected.revision_digest),
        ":et": _s(expected.transition_id),
        ":ew": _s(expected.writer_fence),
        ":ex": _b(expected.terminal),
        ":es": _s(expected.site),
    }


_HEAD_CONDITION = (
    "#g = :eg AND #r = :er AND #t = :et AND #w = :ew "
    "AND #x = :ex AND #s = :es"
)


@dataclass(frozen=True)
class DynamoHeadBinding:
    """Immutable identity of the one allowed table and installation."""

    region: str
    table_name: str
    table_arn: str
    table_id: str
    installation_id: str
    local_site: str
    local_writer_fence_ref: str

    def __post_init__(self) -> None:
        for value, name in (
            (self.region, "DynamoDB region"),
            (self.table_name, "DynamoDB table name"),
            (self.table_arn, "DynamoDB table ARN"),
            (self.table_id, "DynamoDB table id"),
            (self.installation_id, "installation_id"),
            (self.local_site, "local site"),
            (self.local_writer_fence_ref, "local writer fence reference"),
        ):
            validate_opaque_text(value, name)
        match = _TABLE_ARN_PATTERN.fullmatch(self.table_arn)
        if match is None or match.group("region") != self.region or match.group("table") != self.table_name:
            raise ValueError("DynamoDB binding ARN mismatch")
        if _FENCE_PATTERN.fullmatch(self.local_writer_fence_ref) is None:
            raise ValueError("invalid public writer fence reference")

    def runtime_iam_policy(self) -> dict[str, object]:
        """Return the exact policy statement shape; this method applies nothing."""

        return {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Action": ["dynamodb:DescribeTable"],
                    "Resource": self.table_arn,
                },
                {
                    "Effect": "Allow",
                    "Action": ["dynamodb:GetItem", "dynamodb:TransactWriteItems"],
                    "Resource": self.table_arn,
                    "Condition": {
                        "ForAllValues:StringLike": {
                            "dynamodb:LeadingKeys": [self.installation_id]
                        },
                        "ForAllValues:StringEquals": {
                            "dynamodb:Attributes": list(_REMOTE_ATTRIBUTES)
                        },
                    },
                },
            ],
        }


class DynamoDBCurrentHead:
    """DynamoDB implementation of the existing nine-method ``CurrentHeadPort``."""

    def __init__(self, client: object, binding: DynamoHeadBinding) -> None:
        if type(binding) is not DynamoHeadBinding:
            raise TypeError("invalid DynamoDB current-head binding")
        self._client = client
        self._binding = binding
        try:
            response = client.describe_table(TableName=binding.table_name)  # type: ignore[attr-defined]
        except BaseException as exc:
            raise CurrentHeadError("DynamoDB table binding unavailable") from exc
        self._validate_table(response)

    def _validate_table(self, response: object) -> None:
        if type(response) is not dict or type(response.get("Table")) is not dict:
            raise CurrentHeadError("invalid DynamoDB table description")
        table = response["Table"]
        required = {
            "TableName": self._binding.table_name,
            "TableArn": self._binding.table_arn,
            "TableId": self._binding.table_id,
            "TableStatus": "ACTIVE",
        }
        if any(table.get(name) != value for name, value in required.items()):
            raise CurrentHeadError("DynamoDB table identity mismatch")
        key_schema = table.get("KeySchema")
        attribute_definitions = table.get("AttributeDefinitions")
        if (
            type(key_schema) is not list
            or len(key_schema) != 2
            or any(type(entry) is not dict for entry in key_schema)
            or {
                (entry.get("AttributeName"), entry.get("KeyType"))
                for entry in key_schema
            }
            != {("PK", "HASH"), ("SK", "RANGE")}
            or type(attribute_definitions) is not list
            or len(attribute_definitions) != 2
            or any(type(entry) is not dict for entry in attribute_definitions)
            or {
                (entry.get("AttributeName"), entry.get("AttributeType"))
                for entry in attribute_definitions
            }
            != {("PK", "S"), ("SK", "S")}
        ):
            raise CurrentHeadError("DynamoDB current-head key schema mismatch")

    def _key(self, record_key: str) -> dict[str, object]:
        return {"PK": _s(self._binding.installation_id), "SK": _s(record_key)}

    def _get(self, record_key: str) -> Mapping[str, object] | None:
        try:
            response = self._client.get_item(  # type: ignore[attr-defined]
                TableName=self._binding.table_name,
                Key=self._key(record_key),
                ConsistentRead=True,
            )
        except BaseException as exc:
            if isinstance(exc, TimeoutError) or _aws_code(exc) in _TIMEOUT_CODES:
                raise HeadTimeout("DynamoDB strong read timed out") from exc
            raise CurrentHeadError("DynamoDB strong read failed") from exc
        if type(response) is not dict or not set(response).issubset(
            {"Item", "ConsumedCapacity", "ResponseMetadata"}
        ):
            raise CurrentHeadError("invalid DynamoDB read response")
        item = response.get("Item")
        if item is None:
            return None
        if type(item) is not dict:
            raise CurrentHeadError("invalid DynamoDB item")
        return item

    def _head(self) -> HeadSnapshot:
        item = self._get("HEAD")
        if item is None:
            raise CurrentHeadError("DynamoDB current head is absent")
        item = _require_fields(item, _HEAD_FIELDS, "HEAD")
        self._verify_common(item, "HEAD")
        return HeadSnapshot(**_authority_from_fields(item, self._binding.installation_id).__dict__)

    def _verify_common(self, item: Mapping[str, object], record_key: str) -> None:
        if (
            _read_s(item, "PK") != self._binding.installation_id
            or _read_s(item, "SK") != record_key
            or _read_n(item, "schema_version") != _SCHEMA_VERSION
        ):
            raise CurrentHeadError("DynamoDB current-head namespace mismatch")

    def read(self) -> HeadRead:
        return HeadRead(self._head())

    def _proof_matches(
        self, proof: WriterFenceProof, authority: AuthoritySnapshot
    ) -> bool:
        if (
            type(proof) is not WriterFenceProof
            or proof.authority != authority
            or authority.site != self._binding.local_site
            or authority.writer_fence != self._binding.local_writer_fence_ref
        ):
            return False
        match = _FENCE_PATTERN.fullmatch(authority.writer_fence)
        if match is None:
            return False
        digest = hashlib.sha256(proof.capability.encode("utf-8")).hexdigest()
        return hmac.compare_digest(match.group(1), digest)

    def validate_writer_fence(self, proof: WriterFenceProof) -> bool:
        if type(proof) is not WriterFenceProof:
            return False
        head = self._head()
        if head.terminal:
            raise HeadTerminal("terminal current head")
        return self._proof_matches(proof, head.as_authority())

    def _verify_request_proof(self, proof: WriterFenceProof, expected: AuthoritySnapshot) -> None:
        if expected.installation_id != self._binding.installation_id:
            raise HeadConflict("current-head installation conflict")
        if expected.terminal:
            raise HeadTerminal("terminal expected authority")
        if not self._proof_matches(proof, expected):
            raise HeadConflict("current writer fence capability conflict")

    def _head_update(self, expected: AuthoritySnapshot, applied: AuthoritySnapshot) -> dict[str, object]:
        names = _condition_names()
        values = _head_condition_values(expected)
        values.update(
            {
                ":ng": _n(applied.generation),
                ":nr": _s(applied.revision_digest),
                ":nt": _s(applied.transition_id),
                ":nw": _s(applied.writer_fence),
                ":nx": _b(applied.terminal),
                ":ns": _s(applied.site),
            }
        )
        return {
            "TableName": self._binding.table_name,
            "Key": self._key("HEAD"),
            "ConditionExpression": _HEAD_CONDITION,
            "UpdateExpression": "SET #g = :ng, #r = :nr, #t = :nt, #w = :nw, #x = :nx, #s = :ns",
            "ExpressionAttributeNames": names,
            "ExpressionAttributeValues": values,
        }

    def _token(self, kind: str, *parts: str) -> str:
        digest = hashlib.sha256(
            "\0".join(
                (
                    kind,
                    self._binding.table_id,
                    self._binding.installation_id,
                    *parts,
                )
            ).encode("utf-8")
        ).hexdigest()
        return "t122-" + digest[:31]

    def _transact(
        self,
        items: list[dict[str, object]],
        token: str,
        *,
        terminal_prechecked: bool = False,
    ) -> None:
        try:
            self._client.transact_write_items(  # type: ignore[attr-defined]
                TransactItems=items,
                ClientRequestToken=token,
            )
        except BaseException as exc:
            code = _aws_code(exc)
            if code in _CONFLICT_CODES:
                if not terminal_prechecked:
                    try:
                        current = self._head()
                    except (HeadTimeout, CurrentHeadError):
                        current = None
                    if current is not None and current.terminal:
                        raise HeadTerminal("terminal current head") from exc
                raise HeadConflict("DynamoDB conditional write conflict") from exc
            if code in _KNOWN_NONAMBIGUOUS_MUTATION_ERRORS:
                raise CurrentHeadError("DynamoDB current-head write rejected") from exc
            raise HeadUnknown("DynamoDB current-head write result is unknown") from exc

    def conditional_advance(self, request: AdvanceRequest) -> HeadSnapshot:
        if type(request) is not AdvanceRequest:
            raise AuthorityValidationError("invalid advance request")
        self._verify_request_proof(request.writer_proof, request.expected)
        current = self._head()
        if current.terminal:
            raise HeadTerminal("terminal current head")
        if current.as_authority() != request.expected:
            raise HeadConflict("current-head compare-and-set conflict")
        applied = AuthoritySnapshot(
            self._binding.installation_id,
            request.expected.generation + 1,
            request.revision_digest,
            request.transition_id,
            request.writer_fence,
            False,
            request.expected.site,
        )
        identity = request.identity()
        receipt = {
            **self._key(self._transition_key(identity)),
            "schema_version": _n(_SCHEMA_VERSION),
            "kind": _s("advance"),
            **_expected_values(identity.expected),
            "transition_id": _s(identity.transition_id),
            "revision_digest": _s(identity.revision_digest),
            "operation_digest": _s(identity.operation_digest),
            **_applied_values(applied),
        }
        guard = {
            "TableName": self._binding.table_name,
            "Key": self._key("LEASE-GUARD"),
            "ConditionExpression": "generation = :eg AND writer_fence = :ew",
            "UpdateExpression": "SET generation = :ng, writer_fence = :nw",
            "ExpressionAttributeValues": {
                ":eg": _n(identity.expected.generation),
                ":ew": _s(identity.expected.writer_fence),
                ":ng": _n(applied.generation),
                ":nw": _s(applied.writer_fence),
            },
        }
        self._transact(
            [
                {"Update": self._head_update(request.expected, applied)},
                {"Update": guard},
                {
                    "Put": {
                        "TableName": self._binding.table_name,
                        "Item": receipt,
                        "ConditionExpression": "attribute_not_exists(PK) AND attribute_not_exists(SK)",
                    }
                },
            ],
            self._token("advance", repr(identity)),
            terminal_prechecked=True,
        )
        receipt_readback = self.lookup_transition(identity)
        head = self._head()
        if receipt_readback.applied != head or head.as_authority() != applied:
            raise CurrentHeadError("DynamoDB advance readback mismatch")
        return head

    @staticmethod
    def _transition_key(identity: AdvanceIdentity) -> str:
        return f"TRANSITION#{identity.transition_id}#{identity.operation_digest}"

    def lookup_transition(self, request: AdvanceIdentity) -> AppliedTransition:
        if type(request) is not AdvanceIdentity:
            raise AuthorityValidationError("invalid transition lookup request")
        item = self._get(self._transition_key(request))
        if item is None:
            raise TransitionNotFound("transition not found")
        item = _require_fields(item, _TRANSITION_FIELDS, "transition")
        self._verify_common(item, self._transition_key(request))
        observed = AdvanceIdentity(
            expected=_authority_from_fields(item, self._binding.installation_id, "expected_"),
            transition_id=_read_s(item, "transition_id"),
            revision_digest=_read_s(item, "revision_digest"),
            writer_fence=_read_s(item, "expected_writer_fence"),
            operation_digest=_read_s(item, "operation_digest"),
        )
        if _read_s(item, "kind") != "advance" or observed != request:
            raise HeadConflict("transition lookup identity conflict")
        applied = HeadSnapshot(
            **_authority_from_fields(item, self._binding.installation_id, "applied_").__dict__
        )
        return AppliedTransition(request=observed, applied=applied)

    @staticmethod
    def _lifecycle_key(identity: LifecycleTransitionIdentity) -> str:
        return f"LIFECYCLE#{identity.operation_ref}#{identity.operation_digest}"

    def conditional_lifecycle_transition(
        self, request: LifecycleTransitionRequest
    ) -> HeadSnapshot:
        if type(request) is not LifecycleTransitionRequest:
            raise AuthorityValidationError("invalid lifecycle transition request")
        self._verify_request_proof(request.writer_proof, request.expected)
        current = self._head()
        if current.terminal:
            raise HeadTerminal("terminal current head")
        if current.as_authority() != request.expected:
            raise HeadConflict("current-head lifecycle compare-and-set conflict")
        target_fence = (
            request.target_writer_fence_ref
            if request.kind == "writer-transfer"
            else request.writer_fence
        )
        if type(target_fence) is not str or _FENCE_PATTERN.fullmatch(target_fence) is None:
            raise HeadConflict("invalid lifecycle target writer fence")
        if request.kind == "writer-transfer" and target_fence == request.writer_fence:
            raise HeadConflict("writer transfer did not rotate the public fence")
        applied = AuthoritySnapshot(
            self._binding.installation_id,
            request.expected.generation + 1,
            request.revision_digest,
            request.transition_id,
            target_fence,
            request.kind == "terminal-delete",
            request.target_site or request.expected.site,
        )
        identity = request.identity()
        receipt = {
            **self._key(self._lifecycle_key(identity)),
            "schema_version": _n(_SCHEMA_VERSION),
            "kind": _s(identity.kind),
            "operation_ref": _s(identity.operation_ref),
            "operation_digest": _s(identity.operation_digest),
            **_expected_values(identity.expected),
            "transition_id": _s(identity.transition_id),
            "revision_digest": _s(identity.revision_digest),
            **_applied_values(applied),
        }
        if identity.kind == "writer-transfer":
            receipt["target_site"] = _s(identity.target_site)  # type: ignore[arg-type]
            receipt["target_writer_fence_ref"] = _s(identity.target_writer_fence_ref)  # type: ignore[arg-type]
        guard_values: dict[str, object] = {
            ":eg": _n(identity.expected.generation),
            ":ew": _s(identity.expected.writer_fence),
            ":ng": _n(applied.generation),
            ":nw": _s(applied.writer_fence),
        }
        if identity.kind == "terminal-delete":
            guard_condition = (
                "generation = :eg AND writer_fence = :ew AND "
                "attribute_not_exists(active_effect_ids)"
            )
            guard_update = "SET generation = :ng, writer_fence = :nw"
        else:
            guard_condition = "generation = :eg AND writer_fence = :ew"
            guard_update = "SET generation = :ng, writer_fence = :nw REMOVE active_effect_ids"
        guard = {
            "TableName": self._binding.table_name,
            "Key": self._key("LEASE-GUARD"),
            "ConditionExpression": guard_condition,
            "UpdateExpression": guard_update,
            "ExpressionAttributeValues": guard_values,
        }
        self._transact(
            [
                {"Update": self._head_update(identity.expected, applied)},
                {"Update": guard},
                {
                    "Put": {
                        "TableName": self._binding.table_name,
                        "Item": receipt,
                        "ConditionExpression": "attribute_not_exists(PK) AND attribute_not_exists(SK)",
                    }
                },
            ],
            self._token("lifecycle", repr(identity)),
            terminal_prechecked=True,
        )
        receipt_readback = self.lookup_lifecycle_transition(identity)
        head = self._head()
        if receipt_readback.applied != head or head.as_authority() != applied:
            raise CurrentHeadError("DynamoDB lifecycle readback mismatch")
        return head

    def lookup_lifecycle_transition(
        self, identity: LifecycleTransitionIdentity
    ) -> AppliedLifecycleTransition:
        if type(identity) is not LifecycleTransitionIdentity:
            raise AuthorityValidationError("invalid lifecycle transition lookup")
        key = self._lifecycle_key(identity)
        item = self._get(key)
        if item is None:
            raise TransitionNotFound("lifecycle transition not found")
        allowed = _LIFECYCLE_BASE_FIELDS
        if identity.kind == "writer-transfer":
            allowed |= frozenset({"target_site", "target_writer_fence_ref"})
        item = _require_fields(item, allowed, "lifecycle")
        self._verify_common(item, key)
        observed = LifecycleTransitionIdentity(
            kind=_read_s(item, "kind"),
            expected=_authority_from_fields(item, self._binding.installation_id, "expected_"),
            operation_ref=_read_s(item, "operation_ref"),
            transition_id=_read_s(item, "transition_id"),
            revision_digest=_read_s(item, "revision_digest"),
            writer_fence=_read_s(item, "expected_writer_fence"),
            operation_digest=_read_s(item, "operation_digest"),
            target_site=_read_s(item, "target_site") if "target_site" in item else None,
            target_writer_fence_ref=(
                _read_s(item, "target_writer_fence_ref")
                if "target_writer_fence_ref" in item
                else None
            ),
        )
        if observed != identity:
            raise HeadConflict("lifecycle lookup identity conflict")
        applied = HeadSnapshot(
            **_authority_from_fields(item, self._binding.installation_id, "applied_").__dict__
        )
        return AppliedLifecycleTransition(request=observed, applied=applied)

    @staticmethod
    def _lease_key(effect_id: str) -> str:
        return f"LEASE#{effect_id}"

    def _lease_receipt(
        self, item: Mapping[str, object], identity: ExecutionLeaseIdentity
    ) -> ExecutionLeaseReceipt:
        allowed = _LEASE_BASE_FIELDS | (
            frozenset({"released_operation_digest"})
            if "released_operation_digest" in item
            else frozenset()
        )
        item = _require_fields(item, allowed, "lease")
        self._verify_common(item, self._lease_key(identity.effect_id))
        observed = ExecutionLeaseIdentity(
            expected=_authority_from_fields(item, self._binding.installation_id, "expected_"),
            effect_id=_read_s(item, "effect_id"),
            intent_digest=_read_s(item, "intent_digest"),
            writer_fence=_read_s(item, "expected_writer_fence"),
            holder_id=_read_s(item, "holder_id"),
        )
        if observed != identity:
            raise HeadConflict("execution lease lookup conflict")
        lease = ExecutionLease(
            lease_id=_read_s(item, "lease_id"),
            effect_id=observed.effect_id,
            intent_digest=observed.intent_digest,
            authority=observed.expected,
            holder_id=observed.holder_id,
        )
        released = _read_bool(item, "released")
        released_operation_digest = (
            _read_s(item, "released_operation_digest") if released else None
        )
        if not released and "released_operation_digest" in item:
            raise CurrentHeadError("active DynamoDB lease has release ownership")
        return ExecutionLeaseReceipt(
            request=observed,
            lease=lease,
            released=released,
            released_operation_digest=released_operation_digest,
        )

    def acquire_execution_lease(
        self, request: ExecutionLeaseRequest
    ) -> ExecutionLeaseReceipt:
        if type(request) is not ExecutionLeaseRequest:
            raise AuthorityValidationError("invalid execution lease request")
        self._verify_request_proof(request.writer_proof, request.expected)
        identity = request.identity()
        record_key = self._lease_key(identity.effect_id)
        existing = self._get(record_key)
        if existing is not None:
            first_observation = self._lease_receipt(existing, identity)
            confirmed = self._get(record_key)
            if confirmed is not None:
                second_observation = self._lease_receipt(confirmed, identity)
                if second_observation != first_observation:
                    raise CurrentHeadError("DynamoDB lease replay readback changed")
                return second_observation
        lease_id = "lease:" + (
            request.effect_id.split(":", 1)[1]
            if ":" in request.effect_id
            else hashlib.sha256(request.effect_id.encode("utf-8")).hexdigest()
        )
        receipt_item = {
            **self._key(self._lease_key(identity.effect_id)),
            "schema_version": _n(_SCHEMA_VERSION),
            **_expected_values(identity.expected),
            "effect_id": _s(identity.effect_id),
            "intent_digest": _s(identity.intent_digest),
            "holder_id": _s(identity.holder_id),
            "lease_id": _s(lease_id),
            "released": _b(False),
        }
        guard_values: dict[str, object] = {
            ":eg": _n(identity.expected.generation),
            ":ew": _s(identity.expected.writer_fence),
            ":effect": _ss({identity.effect_id}),
        }
        permit = request._execution_overlap
        if permit is None:
            guard_condition = (
                "generation = :eg AND writer_fence = :ew AND "
                "attribute_not_exists(active_effect_ids)"
            )
        else:
            guard_values[":active"] = _ss({permit.active_effect_id})
            guard_condition = (
                "generation = :eg AND writer_fence = :ew AND active_effect_ids = :active"
            )
        guard = {
            "TableName": self._binding.table_name,
            "Key": self._key("LEASE-GUARD"),
            "ConditionExpression": guard_condition,
            "UpdateExpression": "ADD active_effect_ids :effect",
            "ExpressionAttributeValues": guard_values,
        }
        try:
            self._transact(
                [
                    {"Update": guard},
                    {
                        "Put": {
                            "TableName": self._binding.table_name,
                            "Item": receipt_item,
                            "ConditionExpression": "attribute_not_exists(PK) AND attribute_not_exists(SK)",
                        }
                    },
                ],
                self._token("lease", repr(identity)),
            )
        except HeadConflict as conflict:
            # A durable exact receipt makes an SDK/client replay idempotent.
            try:
                return self.lookup_execution_lease(identity)
            except ExecutionLeaseNotFound:
                raise conflict
        item = self._get(record_key)
        if item is None:
            raise CurrentHeadError("DynamoDB lease readback is absent")
        receipt = self._lease_receipt(item, identity)
        return receipt

    def lookup_execution_lease(
        self, identity: ExecutionLeaseIdentity
    ) -> ExecutionLeaseReceipt:
        if type(identity) is not ExecutionLeaseIdentity:
            raise AuthorityValidationError("invalid execution lease lookup request")
        item = self._get(self._lease_key(identity.effect_id))
        if item is None:
            raise ExecutionLeaseNotFound("execution lease not found")
        return self._lease_receipt(item, identity)

    def release_execution_lease(
        self, release: ExecutionLeaseRelease
    ) -> ExecutionLeaseReceipt:
        if type(release) is not ExecutionLeaseRelease:
            raise AuthorityValidationError("invalid execution lease release")
        self._verify_request_proof(release.writer_proof, release.lease.authority)
        identity = ExecutionLeaseIdentity(
            expected=release.lease.authority,
            effect_id=release.lease.effect_id,
            intent_digest=release.lease.intent_digest,
            writer_fence=release.lease.authority.writer_fence,
            holder_id=release.lease.holder_id,
        )
        known = self.lookup_execution_lease(identity)
        if known.lease != release.lease:
            raise HeadConflict("execution lease release conflict")
        if known.released:
            if known.released_operation_digest != release.operation_digest:
                raise HeadConflict("execution lease release ownership conflict")
            return known
        lease_update = {
            "TableName": self._binding.table_name,
            "Key": self._key(self._lease_key(identity.effect_id)),
            "ConditionExpression": (
                "lease_id = :lease AND holder_id = :holder AND released = :false "
                "AND (attribute_not_exists(released_operation_digest) OR "
                "released_operation_digest = :operation)"
            ),
            "UpdateExpression": "SET released = :true, released_operation_digest = :operation",
            "ExpressionAttributeValues": {
                ":lease": _s(release.lease.lease_id),
                ":holder": _s(release.lease.holder_id),
                ":false": _b(False),
                ":true": _b(True),
                ":operation": _s(release.operation_digest),
            },
        }
        guard = {
            "TableName": self._binding.table_name,
            "Key": self._key("LEASE-GUARD"),
            "ConditionExpression": "contains(active_effect_ids, :effect)",
            "UpdateExpression": "DELETE active_effect_ids :effects",
            "ExpressionAttributeValues": {
                ":effect": _s(identity.effect_id),
                ":effects": _ss({identity.effect_id}),
            },
        }
        self._transact(
            [{"Update": lease_update}, {"Update": guard}],
            self._token(
                "release",
                repr(identity),
                release.lease.lease_id,
                release.operation_digest,
            ),
        )
        item = self._get(self._lease_key(identity.effect_id))
        if item is None:
            raise CurrentHeadError("DynamoDB lease release readback is absent")
        receipt = self._lease_receipt(item, identity)
        if not receipt.released or receipt.released_operation_digest != release.operation_digest:
            raise CurrentHeadError("DynamoDB lease release readback mismatch")
        return receipt


__all__ = ["DynamoHeadBinding", "DynamoDBCurrentHead"]
