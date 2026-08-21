"""Owner grants and read-only viewer access for a health profile."""

from __future__ import annotations

import copy
import uuid
from typing import Any, Mapping

from .health_turn_context import (
    MAX_HEALTH_TURN_EVIDENCE_IDS,
    MAX_HEALTH_TURN_EVIDENCE_IDS_PER_CONCLUSION,
)
from .profile import ProfileStoreError, _empty_profile, _profile_from_status
from .store import HealthSidecarStore, StoreError


VIEWER_PERMISSIONS = (
    "profile",
    "evidence",
    "tasks",
    "reports",
    "audit",
)


def _non_empty(value: Any, code: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProfileStoreError(code)
    return value.strip()


def _profile(store: HealthSidecarStore, subject: str) -> dict[str, Any]:
    try:
        return _profile_from_status(
            store.read_subject_status(subject, _allow_profile_state=True)
        )
    except ProfileStoreError:
        raise
    except StoreError as exc:
        raise ProfileStoreError(str(exc)) from exc


def _profile_for_authorized_read(
    store: HealthSidecarStore,
    subject: str,
    sender_id: str,
) -> dict[str, Any]:
    """Project an unpersisted empty owner view after consent but before facts."""
    try:
        return _profile(store, subject)
    except ProfileStoreError as exc:
        recording_status = store.health_recording_status(subject, sender_id)
        if (
            str(exc) != "profile-not-bound"
            or recording_status == "not_enabled"
        ):
            raise
        profile = _empty_profile(sender_id)
        profile["recording_status"] = recording_status
        return profile


def _audit(store: HealthSidecarStore, event: str, details: Mapping[str, Any]) -> None:
    store.append_audit_event(event, details)


def _verify_access_receipt(
    store: HealthSidecarStore,
    subject: str,
    actor_sender_id: str,
    target_sender_id: str,
    action: str,
    message_id: str,
    message_utc: str,
    verification_token: str,
    actor_role: str,
) -> None:
    valid = store.message_verifier.verify_access_receipt(
        action=action,
        subject=subject,
        actor_sender_id=actor_sender_id,
        target_sender_id=target_sender_id,
        message_id=message_id,
        message_utc=message_utc,
        token=verification_token,
    )
    if not valid:
        _audit(
            store,
            "access_denied",
            {
                "subject": subject,
                "actor_role": actor_role,
                "actor_id": actor_sender_id,
                "action": action,
                "object_id": target_sender_id,
                "result": "denied",
                "reason": "unverified-access-receipt",
            },
        )
        raise ProfileStoreError("unverified-access-receipt")
    try:
        store.consume_access_receipt(subject, message_id, message_utc)
    except ProfileStoreError as exc:
        _audit(
            store,
            "access_denied",
            {
                "subject": subject,
                "actor_role": actor_role,
                "actor_id": actor_sender_id,
                "action": action,
                "object_id": target_sender_id,
                "result": "denied",
                "reason": str(exc),
            },
        )
        raise


def grant_profile_viewer(
    store: HealthSidecarStore,
    subject: str,
    owner_sender_id: str,
    viewer_sender_id: str,
    message_id: str,
    message_utc: str,
    verification_token: str,
) -> Mapping[str, Any]:
    subject = _non_empty(subject, "subject-required")
    owner_sender_id = _non_empty(owner_sender_id, "owner-sender-required")
    viewer_sender_id = _non_empty(viewer_sender_id, "viewer-sender-required")
    if (
        store.expected_viewer_sender_id
        and viewer_sender_id != store.expected_viewer_sender_id
    ):
        _audit(
            store,
            "access_denied",
            {
                "subject": subject,
                "actor_role": "owner",
                "actor_id": owner_sender_id,
                "action": "health.access.grant",
                "object_id": viewer_sender_id,
                "result": "denied",
                "reason": "viewer-not-configured",
            },
        )
        raise ProfileStoreError("viewer-not-configured")
    if viewer_sender_id == owner_sender_id:
        _audit(
            store,
            "access_denied",
            {
                "subject": subject,
                "actor_role": "owner",
                "actor_id": owner_sender_id,
                "action": "health.access.grant",
                "object_id": viewer_sender_id,
                "result": "denied",
                "reason": "viewer-is-owner",
            },
        )
        raise ProfileStoreError("viewer-must-not-be-owner")
    profile = _profile(store, subject)
    if profile.get("owner_sender_id") != owner_sender_id:
        _audit(
            store,
            "access_denied",
            {
                "subject": subject,
                "actor_role": "owner",
                "actor_id": owner_sender_id,
                "action": "health.access.grant",
                "object_id": viewer_sender_id,
                "result": "denied",
                "reason": "access-owner-mismatch",
            },
        )
        raise ProfileStoreError("access-owner-mismatch")
    _verify_access_receipt(
        store,
        subject,
        owner_sender_id,
        viewer_sender_id,
        "health.access.grant",
        message_id,
        message_utc,
        verification_token,
        "owner",
    )

    def mutate(current: Mapping[str, Any]) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
        profile = _profile_from_status(current)
        if profile.get("owner_sender_id") != owner_sender_id:
            raise ProfileStoreError("access-owner-mismatch")
        grants = copy.deepcopy(list(profile.get("viewer_grants", [])))
        configured = store.expected_viewer_sender_id
        if configured and profile.get("viewer_configuration_sender_id") != configured:
            revoked_utc = store.now_utc().replace(microsecond=0).isoformat()
            for grant in grants:
                if isinstance(grant, dict) and grant.get("active", True):
                    grant["active"] = False
                    grant["revoked_utc"] = revoked_utc
                    grant["revocation_reason"] = "viewer-configuration-changed"
            profile["viewer_configuration_sender_id"] = configured
        active = next(
            (
                item
                for item in grants
                if item.get("viewer_sender_id") == viewer_sender_id
                and item.get("active", True)
            ),
            None,
        )
        changed = active is None
        if active is None:
            active = {
                "grant_id": f"grant-{uuid.uuid4().hex}",
                "viewer_sender_id": viewer_sender_id,
                "permissions": list(VIEWER_PERMISSIONS),
                "granted_utc": store.now_utc().replace(microsecond=0).isoformat(),
                "revoked_utc": None,
                "active": True,
            }
            grants.append(active)
        profile["viewer_grants"] = grants
        return profile, {
            "subject": subject,
            "viewer_sender_id": viewer_sender_id,
            "permissions": list(active["permissions"]),
            "granted": True,
            "changed": changed,
            "grant_id": active["grant_id"],
        }

    def audit_builder(result: Mapping[str, Any]):
        return ((
            "access_grant",
            {
                "subject": subject,
                "actor_role": "owner",
                "actor_id": owner_sender_id,
                "action": "health.access.grant",
                "target_id": viewer_sender_id,
                "object_id": result["grant_id"],
                "result": "granted" if result["changed"] else "unchanged",
            },
        ),)

    result = store.mutate_subject_status(
        subject,
        mutate,
        audit_builder=audit_builder,
    )
    return result


def revoke_profile_viewer(
    store: HealthSidecarStore,
    subject: str,
    owner_sender_id: str,
    viewer_sender_id: str,
    message_id: str,
    message_utc: str,
    verification_token: str,
) -> Mapping[str, Any]:
    subject = _non_empty(subject, "subject-required")
    owner_sender_id = _non_empty(owner_sender_id, "owner-sender-required")
    viewer_sender_id = _non_empty(viewer_sender_id, "viewer-sender-required")
    if (
        store.expected_viewer_sender_id
        and viewer_sender_id != store.expected_viewer_sender_id
    ):
        _audit(
            store,
            "access_denied",
            {
                "subject": subject,
                "actor_role": "owner",
                "actor_id": owner_sender_id,
                "action": "health.access.revoke",
                "object_id": viewer_sender_id,
                "result": "denied",
                "reason": "viewer-not-configured",
            },
        )
        raise ProfileStoreError("viewer-not-configured")
    profile = _profile(store, subject)
    if profile.get("owner_sender_id") != owner_sender_id:
        _audit(
            store,
            "access_denied",
            {
                "subject": subject,
                "actor_role": "owner",
                "actor_id": owner_sender_id,
                "action": "health.access.revoke",
                "object_id": viewer_sender_id,
                "result": "denied",
                "reason": "access-owner-mismatch",
            },
        )
        raise ProfileStoreError("access-owner-mismatch")
    _verify_access_receipt(
        store,
        subject,
        owner_sender_id,
        viewer_sender_id,
        "health.access.revoke",
        message_id,
        message_utc,
        verification_token,
        "owner",
    )

    def mutate(current: Mapping[str, Any]) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
        profile = _profile_from_status(current)
        if profile.get("owner_sender_id") != owner_sender_id:
            raise ProfileStoreError("access-owner-mismatch")
        grants = copy.deepcopy(list(profile.get("viewer_grants", [])))
        target = next(
            (
                item
                for item in grants
                if item.get("viewer_sender_id") == viewer_sender_id
                and item.get("active", True)
            ),
            None,
        )
        configured = store.expected_viewer_sender_id
        if configured and profile.get("viewer_configuration_sender_id") != configured:
            revoked_utc = store.now_utc().replace(microsecond=0).isoformat()
            for grant in grants:
                if isinstance(grant, dict) and grant.get("active", True):
                    grant["active"] = False
                    grant["revoked_utc"] = revoked_utc
                    grant["revocation_reason"] = "viewer-configuration-changed"
            profile["viewer_configuration_sender_id"] = configured
        if target is None:
            profile["viewer_grants"] = grants
            return profile, {
                "subject": subject,
                "viewer_sender_id": viewer_sender_id,
                "revoked": False,
                "changed": False,
                "grant_id": None,
            }
        target = next(
            item
            for item in grants
            if item.get("grant_id") == target.get("grant_id")
        )
        if target.get("active", True):
            target["active"] = False
            target["revoked_utc"] = store.now_utc().replace(
                microsecond=0
            ).isoformat()
        profile["viewer_grants"] = grants
        return profile, {
            "subject": subject,
            "viewer_sender_id": viewer_sender_id,
            "revoked": True,
            "changed": True,
            "grant_id": target["grant_id"],
        }

    def audit_builder(result: Mapping[str, Any]):
        return ((
            "access_revoke",
            {
                "subject": subject,
                "actor_role": "owner",
                "actor_id": owner_sender_id,
                "action": "health.access.revoke",
                "target_id": viewer_sender_id,
                "object_id": result["grant_id"] or viewer_sender_id,
                "result": "revoked" if result["changed"] else "unchanged",
            },
        ),)

    result = store.mutate_subject_status(
        subject,
        mutate,
        audit_builder=audit_builder,
    )
    return result


def _authorized_role(
    store: HealthSidecarStore,
    profile: Mapping[str, Any],
    subject: str,
    sender_id: str,
    action: str,
    message_id: str,
    message_utc: str,
    verification_token: str,
) -> str:
    owner = str(profile.get("owner_sender_id", ""))
    if sender_id == owner:
        _verify_access_receipt(
            store,
            subject,
            sender_id,
            sender_id,
            action,
            message_id,
            message_utc,
            verification_token,
            "owner",
        )
        return "owner"
    configured_viewer = (
        not store.expected_viewer_sender_id
        or (
            sender_id == store.expected_viewer_sender_id
            and profile.get("viewer_configuration_sender_id")
            == store.expected_viewer_sender_id
        )
    )
    if configured_viewer and any(
        item.get("viewer_sender_id") == sender_id and item.get("active", True)
        for item in profile.get("viewer_grants", [])
    ):
        _verify_access_receipt(
            store,
            subject,
            sender_id,
            sender_id,
            action,
            message_id,
            message_utc,
            verification_token,
            "viewer",
        )
        return "viewer"
    _audit(
        store,
        "access_denied",
        {
            "subject": subject,
            "actor_role": "unknown",
            "actor_id": sender_id,
            "action": action,
            "object_id": subject,
            "result": "denied",
            "reason": "no-active-grant",
        },
    )
    raise ProfileStoreError("access-not-authorized")


def _subject_audit(store: HealthSidecarStore, subject: str) -> list[Mapping[str, Any]]:
    events = []
    for event in store.read_audit_events():
        details = event.get("details")
        if isinstance(details, Mapping) and details.get("subject") == subject:
            events.append(copy.deepcopy(event))
    return events


def read_authorized_view(
    store: HealthSidecarStore,
    subject: str,
    sender_id: str,
    message_id: str,
    message_utc: str,
    verification_token: str,
    action: str = "health.access.read",
) -> Mapping[str, Any]:
    subject = _non_empty(subject, "subject-required")
    sender_id = _non_empty(sender_id, "sender-required")
    profile = _profile_for_authorized_read(store, subject, sender_id)
    role = _authorized_role(
        store,
        profile,
        subject,
        sender_id,
        action,
        message_id,
        message_utc,
        verification_token,
    )
    view_profile = copy.deepcopy(profile)
    view_profile.pop("access_receipt_ids", None)
    if role == "viewer":
        view_profile.pop("viewer_grants", None)
    tasks = copy.deepcopy(list(view_profile.get("tasks", [])))
    reports = copy.deepcopy(list(view_profile.get("reports", [])))
    if action == "health.access.read":
        view_profile.pop("tasks", None)
        view_profile.pop("reports", None)
    result = {
        "subject": subject,
        "role": role,
        "profile": view_profile,
        "tasks": tasks,
        "reports": reports,
        "audit": _subject_audit(store, subject),
    }
    _audit(
        store,
        "access_read",
        {
            "subject": subject,
            "actor_role": role,
            "actor_id": sender_id,
            "action": action,
            "object_id": subject,
            "result": "allowed",
        },
    )
    return result


def read_authorized_analysis_context(
    store: HealthSidecarStore,
    subject: str,
    sender_id: str,
    message_id: str,
    message_utc: str,
    verification_token: str,
) -> Mapping[str, Any]:
    """Return the bounded current profile projection for explicit analysis."""
    subject = _non_empty(subject, "subject-required")
    sender_id = _non_empty(sender_id, "sender-required")
    profile = _profile_for_authorized_read(store, subject, sender_id)
    action = "health.access.analyze"
    role = _authorized_role(
        store,
        profile,
        subject,
        sender_id,
        action,
        message_id,
        message_utc,
        verification_token,
    )
    current_version_id = profile.get("current_version_id")
    evidence_ids: list[str] = []
    for conclusion in profile.get("conclusions", []):
        if (
            not isinstance(conclusion, Mapping)
            or not conclusion.get("active", True)
        ):
            continue
        accepted_for_conclusion = 0
        for evidence_id in conclusion.get("evidence_ids", []):
            if (
                isinstance(evidence_id, str)
                and evidence_id.strip()
                and evidence_id not in evidence_ids
            ):
                evidence_ids.append(evidence_id)
                accepted_for_conclusion += 1
            if (
                accepted_for_conclusion
                >= MAX_HEALTH_TURN_EVIDENCE_IDS_PER_CONCLUSION
                or len(evidence_ids) >= MAX_HEALTH_TURN_EVIDENCE_IDS
            ):
                break
        if len(evidence_ids) >= MAX_HEALTH_TURN_EVIDENCE_IDS:
            break
    result = {
        "analysis_context_schema_version": 1,
        "subject": subject,
        "role": role,
        "current_version_id": current_version_id,
        "profile_summary_zh": str(profile.get("profile_summary_zh", "")),
        "evidence_ids": evidence_ids,
    }
    _audit(
        store,
        "access_analysis",
        {
            "subject": subject,
            "actor_role": role,
            "actor_id": sender_id,
            "action": action,
            "object_id": subject,
            "result": "allowed",
            "evidence_ids": evidence_ids,
            "version_id": current_version_id,
        },
    )
    return result


def export_profile(
    store: HealthSidecarStore,
    subject: str,
    sender_id: str,
    message_id: str,
    message_utc: str,
    verification_token: str,
) -> Mapping[str, Any]:
    subject = _non_empty(subject, "subject-required")
    sender_id = _non_empty(sender_id, "sender-required")
    profile = _profile(store, subject)
    role = _authorized_role(
        store,
        profile,
        subject,
        sender_id,
        "health.profile.export",
        message_id,
        message_utc,
        verification_token,
    )
    if role != "owner":
        _audit(
            store,
            "access_denied",
            {
                "subject": subject,
                "actor_role": role,
                "actor_id": sender_id,
                "action": "health.profile.export",
                "object_id": subject,
                "result": "denied",
                "reason": "owner-only-export",
            },
        )
        raise ProfileStoreError("owner-only-export")
    view_profile = copy.deepcopy(profile)
    view_profile.pop("access_receipt_ids", None)
    result = {
        "subject": subject,
        "role": role,
        "profile": view_profile,
        "tasks": list(view_profile.get("tasks", [])),
        "reports": list(view_profile.get("reports", [])),
        "audit": _subject_audit(store, subject),
    }
    _audit(
        store,
        "access_read",
        {
            "subject": subject,
            "actor_role": role,
            "actor_id": sender_id,
            "action": "health.profile.export",
            "object_id": subject,
            "result": "allowed",
        },
    )
    result["export_schema_version"] = 1
    result["exported"] = True
    _audit(
        store,
        "profile_export",
        {
            "subject": subject,
            "actor_role": role,
            "actor_id": sender_id,
            "action": "health.profile.export",
            "object_id": subject,
            "result": "allowed",
        },
    )
    return result
