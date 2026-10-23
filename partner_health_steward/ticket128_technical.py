"""Two fixed native technical receipts in the existing acceptance artifacts.

This module has no health authority, network client or cursor operation. The
trusted adapter calls it only after the Core admitted the same ordinary event.
"""
from __future__ import annotations

import copy
import fcntl
import json
import os
import re
import secrets
import stat
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .admission import AdmissionPolicy, live_native_event_identity
from .initialization import stable_digest

_HEX = re.compile(r"[0-9a-f]{32,64}\Z")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_GATES = {"119-G11", "128-ND12"}
_IDENTITY = {"release_digest", "distribution_digest", "run_id", "run_scope", "target"}


def _now():
    return datetime.now(timezone.utc).isoformat()


def _time(value):
    if type(value) is not str:
        raise ValueError("technical timestamp unavailable")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.utcoffset() is None:
        raise ValueError("technical timestamp unavailable")
    return parsed


def _bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def technical_candidate(body):
    """Reserve both prefixes, including malformed challenges, from the Agent."""
    return type(body) is str and (body.startswith("连接测试") or body.startswith("验收反馈"))


class TechnicalAcceptanceChannel:
    def __init__(self, root, identity, admission_policy=None):
        self.root = Path(root)
        if (not self.root.is_absolute() or self.root.is_symlink()
                or type(identity) is not dict or not _IDENTITY.issubset(identity)
                or identity["target"] != "default" or identity["run_scope"] not in {"full", "non-diagnostic"}
                or any(_DIGEST.fullmatch(str(identity[name])) is None for name in ("release_digest", "distribution_digest"))):
            raise ValueError("technical acceptance binding unavailable")
        self.identity = {name: identity[name] for name in _IDENTITY}
        self.policy = admission_policy
        if admission_policy is not None and type(admission_policy) is not AdmissionPolicy:
            raise ValueError("technical native admission unavailable")

    def _directory(self):
        details = self.root.lstat()
        if (not stat.S_ISDIR(details.st_mode) or details.st_uid != os.geteuid()
                or stat.S_IMODE(details.st_mode) not in {0o700, 0o500}):
            raise ValueError("technical private artifact directory unavailable")

    def _read(self, path):
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            details = os.fstat(fd)
            if (not stat.S_ISREG(details.st_mode) or details.st_uid != os.geteuid()
                    or stat.S_IMODE(details.st_mode) != 0o600 or details.st_size > 65536):
                raise ValueError("technical artifact unavailable")
            with os.fdopen(fd, "rb", closefd=False) as stream:
                value = json.loads(stream.read())
            if type(value) is not dict:
                raise ValueError("technical artifact unavailable")
            return value
        finally:
            os.close(fd)

    def _write(self, path, value):
        # Replace only inside the already-verified private artifact directory.
        pending = self.root / (".technical-" + secrets.token_hex(16))
        fd = os.open(pending, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(_bytes(value))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(pending, path)
            directory = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            pending.unlink(missing_ok=True)

    @contextmanager
    def _locked(self):
        self._directory()
        fd = os.open(self.root / ".technical.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            details = os.fstat(fd)
            if (not stat.S_ISREG(details.st_mode) or details.st_uid != os.geteuid()
                    or stat.S_IMODE(details.st_mode) != 0o600):
                raise ValueError("technical lock unavailable")
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            os.close(fd)

    def _path(self, execution_key, suffix):
        if type(execution_key) is not str or re.fullmatch(r"(?:ticket119:)?[0-9a-f]{64}", execution_key) is None:
            raise ValueError("technical execution key unavailable")
        return self.root / (execution_key.removeprefix("ticket119:") + ".technical-" + suffix + ".json")

    def _permit(self, attempt):
        approval = attempt["approval_ref"]
        if type(approval) is not str or _DIGEST.fullmatch(approval) is None:
            raise ValueError("technical approval unavailable")
        permit = self._read(self.root.parent / ".ticket120-deployment-permits" / (approval[7:] + ".json"))
        if stable_digest(permit) != approval:
            raise ValueError("technical approval digest unavailable")
        if permit.get("contract") != "ticket128-gate-permit-v1":
            raise ValueError("technical approval contract unavailable")
        identity = attempt["identity"]
        expected = {**identity, "gate_id": attempt["gate_id"]}
        # The original deployment target is a fixed target object, while this
        # internal identity names that same target as 'default'.
        target = permit.get("target")
        if type(target) is dict:
            if target != {"profile": "default", "hermes_home": "/root/.hermes", "service": "hermes-gateway.service"}:
                raise ValueError("technical target mismatch")
            expected.pop("target")
        if any(permit.get(name) != value for name, value in expected.items()):
            raise ValueError("technical approval binding unavailable")
        expiry = permit.get("expires_at", permit.get("expires_at_utc"))
        if (_time(expiry) <= datetime.now(timezone.utc)
                or _time(attempt["expires_at_utc"]) > _time(expiry)):
            raise ValueError("technical approval expired")
        consumed = self._read(self.root.parent / ".ticket120-consumed-permits" / approval[7:]
                              / (attempt["execution_key"] + ".json"))
        if consumed != {"execution_key": attempt["execution_key"], "permit_digest": approval,
                        "release_digest": identity["release_digest"]}:
            raise ValueError("technical approval consumption unavailable")

    def _validated(self, attempt):
        identity = attempt.get("identity")
        if (type(identity) is not dict or set(identity) != _IDENTITY
                or any(identity[name] != self.identity[name] for name in _IDENTITY - {"run_id"})
                or attempt.get("gate_id") not in _GATES
                or _HEX.fullmatch(str(attempt.get("challenge"))) is None
                or (attempt["gate_id"] == "128-ND12" and identity["run_scope"] != "non-diagnostic")):
            raise ValueError("technical current binding unavailable")
        self._path(attempt["execution_key"], "attempt")
        # prepare's current run must still be the owner of this attempt.
        binding = self.root.parent / ".ticket128-deployment-binding.json"
        current = self._read(binding)
        for name in ("run_id", "run_scope", "release_digest", "distribution_digest"):
            actual = current.get(name, current.get("run_context", {}).get(name))
            if actual != identity[name]:
                raise ValueError("technical run no longer current")
        self._permit(attempt)
        return attempt

    def begin(self, gate_id, execution_key, approval_ref, expires_at_utc, sequence_digest=None):
        if gate_id not in _GATES or _time(expires_at_utc) <= datetime.now(timezone.utc):
            raise ValueError("technical gate unavailable")
        if gate_id == "128-ND12" and (type(sequence_digest) is not str or _DIGEST.fullmatch(sequence_digest) is None):
            raise ValueError("technical feedback sequence unavailable")
        with self._locked():
            path = self._path(execution_key, "attempt")
            pointer = self.root / "current-technical.json"
            if pointer.exists():
                previous_key = self._read(pointer)["execution_key"]
                if previous_key != execution_key:
                    previous = self._read(self._path(previous_key, "attempt"))
                    terminal = previous.get("send_result")
                    model = previous.get("model_result")
                    unresolved = ((previous.get("model_attempted_at_utc") is not None
                                   and (model is None or model.get("status") == "unknown"))
                                  or previous.get("attempted_at_utc") is not None
                                  and (terminal is None or terminal.get("status") == "unknown"
                                       or terminal.get("status") == "accepted" and not self._path(previous_key, "action").exists()))
                    if unresolved:
                        raise ValueError("previous technical attempt remains unresolved")
            if path.exists():
                attempt = self._validated(self._read(path))
                if (attempt["gate_id"], attempt["approval_ref"], attempt["sequence_digest"]) != (gate_id, approval_ref, sequence_digest):
                    raise ValueError("technical attempt conflict")
            else:
                attempt = {"contract": "ticket128-technical-attempt-v1", "identity": self.identity,
                    "gate_id": gate_id, "execution_key": execution_key, "approval_ref": approval_ref,
                    "expires_at_utc": expires_at_utc, "sequence_digest": sequence_digest,
                    "challenge": secrets.token_hex(16), "formed_at_utc": _now(),
                    "send_requested": False, "model_attempted_at_utc": None, "model_result": None,
                    "attempted_at_utc": None, "send_result": None}
                self._validated(attempt)
                self._write(path, attempt)
            self._write(self.root / "current-technical.json", {"execution_key": execution_key})
            return copy.deepcopy(attempt)

    def _current(self):
        pointer = self._read(self.root / "current-technical.json")
        if set(pointer) != {"execution_key"}:
            raise ValueError("technical current attempt unavailable")
        return self._validated(self._read(self._path(pointer["execution_key"], "attempt")))

    def request_send(self, execution_key):
        with self._locked():
            attempt = self._current()
            if attempt["execution_key"] != execution_key:
                raise ValueError("technical current attempt mismatch")
            if not attempt["send_requested"]:
                attempt["send_requested"] = True
                self._write(self._path(execution_key, "attempt"), attempt)

    def claim_model(self):
        with self._locked():
            try:
                attempt = self._current()
            except FileNotFoundError:
                return None
            if (attempt["gate_id"] != "119-G11" or not attempt["send_requested"]
                    or attempt["model_attempted_at_utc"] is not None):
                return None
            attempt["model_attempted_at_utc"] = _now()
            self._write(self._path(attempt["execution_key"], "attempt"), attempt)
            return copy.deepcopy(attempt)

    def mark_model(self, execution_key, result):
        fields = {"status", "terminal_proven", "actual_model_allowed", "accepted", "result_ref"}
        if (type(result) is not dict or set(result) != fields
                or result["status"] not in {"completed", "incomplete", "failed", "unknown", "not-attempted"}
                or any(type(result[name]) is not bool for name in ("terminal_proven", "actual_model_allowed", "accepted"))
                or type(result["result_ref"]) is not str
                or result["accepted"] and not (result["status"] == "completed"
                    and result["terminal_proven"] and result["actual_model_allowed"])):
            raise ValueError("technical model terminal unavailable")
        with self._locked():
            attempt = self._validated(self._read(self._path(execution_key, "attempt")))
            if attempt["model_attempted_at_utc"] is None or attempt["gate_id"] != "119-G11":
                raise ValueError("technical model never attempted")
            if attempt["model_result"] is not None:
                if attempt["model_result"] != result:
                    raise ValueError("technical model terminal conflict")
                return
            attempt["model_result"] = copy.deepcopy(result)
            self._write(self._path(execution_key, "attempt"), attempt)

    def claim_send(self):
        with self._locked():
            try:
                attempt = self._current()
            except FileNotFoundError:
                return None
            if not attempt["send_requested"] or attempt["attempted_at_utc"] is not None:
                return None
            if attempt["gate_id"] == "119-G11" and not (attempt["model_result"] or {}).get("accepted"):
                return None
            attempt["attempted_at_utc"] = _now()
            self._write(self._path(attempt["execution_key"], "attempt"), attempt)
            return copy.deepcopy(attempt)

    def mark_sent(self, execution_key, result):
        if (type(result) is not dict or set(result) != {"status", "result_ref", "evidence_ref"}
                or result["status"] not in {"accepted", "rejected", "unknown"}):
            raise ValueError("technical send result unavailable")
        with self._locked():
            attempt = self._validated(self._read(self._path(execution_key, "attempt")))
            if attempt["attempted_at_utc"] is None:
                raise ValueError("technical send never attempted")
            if attempt["send_result"] is not None:
                if attempt["send_result"] != result:
                    raise ValueError("technical terminal conflict")
                return
            attempt["send_result"] = copy.deepcopy(result)
            attempt["send_observed_at_utc"] = _now()
            self._write(self._path(execution_key, "attempt"), attempt)

    def attempt(self, execution_key):
        with self._locked():
            return copy.deepcopy(self._validated(self._read(self._path(execution_key, "attempt"))))

    def action(self, execution_key):
        with self._locked():
            try:
                return copy.deepcopy(self._read(self._path(execution_key, "action")))
            except FileNotFoundError:
                return None

    def handle(self, headers, body, response, *, initialization_phase=None):
        """Return True only after a durable receipt or a reserved invalid form."""
        if not technical_candidate(body):
            return None
        if (self.policy is None or response.get("status") not in {"accepted", "replayed"}
                or response.get("reason_code") != "ordinary-hermes-route"
                or response.get("causal_id") != headers.get("causal_id")
                or headers.get("partner_id") != self.policy.partner_id
                or headers.get("sender_id") != self.policy.owner_sender_id
                or headers.get("conversation_id") != self.policy.conversation_id
                or headers.get("message_id") is None):
            return False
        with self._locked():
            try:
                attempt = self._current()
            except FileNotFoundError:
                return True
            if attempt["gate_id"] == "128-ND12" and initialization_phase != "enabled":
                return False
            expected = (("连接测试 " + attempt["challenge"]) if attempt["gate_id"] == "119-G11"
                        else "验收反馈 " + attempt["challenge"] + " 有用 清楚 可信")
            if body != expected:
                return True
            if not attempt.get("send_result") or attempt["send_result"]["status"] != "accepted":
                return False
            stamp = _time(headers["protocol_timestamp"])
            if (int(stamp.timestamp() * 1000) < int(_time(attempt["attempted_at_utc"]).timestamp() * 1000)
                    or stamp > datetime.now(timezone.utc)):
                return False
            native = live_native_event_identity(headers)
            source = headers["causal_id"]
            action_path = self._path(attempt["execution_key"], "action")
            if action_path.exists():
                prior = self._read(action_path)
                return prior["native_event_identity"] == native
            common = {"execution_key": attempt["execution_key"], "gate_id": attempt["gate_id"],
                      "challenge": attempt["challenge"], "native_event_identity": native,
                      "sequence_digest": attempt["sequence_digest"]}
            delivered = {**common, "kind": "canary-delivery-inferred-from-independent-native-reply",
                         "send_result_ref": attempt["send_result"]["result_ref"]}
            action = {**common, "kind": "owner-exact-challenge-action", "source_causal_id": source,
                      "native_timestamp": headers["protocol_timestamp"]}
            receipt = {"contract": "ticket128-technical-action-v1", **common,
                       "source_causal_id": source, "observed_at_utc": _now(),
                       "delivery_inference": delivered, "action_observation": action,
                       "delivered_ref": "technical-delivery:" + stable_digest(delivered)[7:],
                       "read_or_action_ref": "technical-action:" + stable_digest(action)[7:]}
            self._write(action_path, receipt)
            return True
