"""Partner-facing health-sidecar adapter.

The adapter is the application-facing seam for the sidecar tickets completed
so far. It transports state, profile candidates, profile reads, and content-
free audit queries over the private Unix socket; it never opens the sidecar
database or key files.
"""

from __future__ import annotations

from typing import Any, Mapping

from .client import HealthSidecarClient
from .health_turn_context import (
    HealthTurnContextError,
    validate_health_turn_context,
)


class PartnerHealthAdapterError(RuntimeError):
    """Raised when the sidecar rejects or malforms an adapter request."""


class PartnerHealthAdapter:
    """Expose the narrow partner contract for health state and audit reads."""

    def __init__(self, socket_path: str, timeout_seconds: float = 2.0) -> None:
        self._client = HealthSidecarClient(socket_path, timeout_seconds)

    def write_state(self, subject: str, status: Mapping[str, Any]) -> int:
        data = self._require_success(self._client.set_status(subject, status))
        version = data.get("version")
        if not isinstance(version, int):
            raise PartnerHealthAdapterError("invalid-write-response")
        return version

    def read_state(self, subject: str) -> Mapping[str, Any] | None:
        data = self._require_success(self._client.get_status(subject))
        if not data.get("found"):
            return None
        status = data.get("status")
        if not isinstance(status, Mapping):
            raise PartnerHealthAdapterError("invalid-read-response")
        return dict(status)

    def read_audit(self) -> list[Mapping[str, Any]]:
        data = self._require_success(self._client.read_audit())
        events = data.get("events")
        if not isinstance(events, list) or not all(
            isinstance(event, Mapping) for event in events
        ):
            raise PartnerHealthAdapterError("invalid-audit-response")
        return [dict(event) for event in events]

    def append_audit_event_once(
        self,
        event_id: str,
        event: str,
        details: Mapping[str, Any],
    ) -> bool:
        """Persist one content-free idempotent Weixin delivery audit."""
        data = self._require_success(
            self._client.append_delivery_audit_once(
                event_id,
                event,
                details,
            )
        )
        appended = data.get("appended")
        if not isinstance(appended, bool):
            raise PartnerHealthAdapterError("invalid-delivery-audit-response")
        return appended

    def bind_profile_owner(
        self, subject: str, owner_sender_id: str, verification_token: str
    ) -> bool:
        data = self._require_success(
            self._client.bind_profile_owner(subject, owner_sender_id, verification_token)
        )
        bound = data.get("bound")
        if not isinstance(bound, bool):
            raise PartnerHealthAdapterError("invalid-owner-bind-response")
        return bound

    def transfer_profile_owner(
        self,
        subject: str,
        old_owner_sender_id: str,
        new_owner_sender_id: str,
        receipt_message_id: str,
        receipt_utc: str,
        verification_token: str,
    ) -> Mapping[str, Any]:
        return self._require_success(
            self._client.transfer_profile_owner(
                subject,
                old_owner_sender_id,
                new_owner_sender_id,
                receipt_message_id,
                receipt_utc,
                verification_token,
            )
        )

    def recover_profile_owner(
        self,
        subject: str,
        new_owner_sender_id: str,
        recovery_code: str,
        receipt_message_id: str,
        receipt_utc: str,
        verification_token: str,
    ) -> Mapping[str, Any]:
        return self._require_success(
            self._client.recover_profile_owner(
                subject,
                new_owner_sender_id,
                recovery_code,
                receipt_message_id,
                receipt_utc,
                verification_token,
            )
        )

    def record_profile_candidate(
        self,
        subject: str,
        sender_id: str,
        candidate: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        return self._require_success(
            self._client.record_profile_candidate(subject, sender_id, candidate)
        )

    def health_recording_enabled(self, subject: str, sender_id: str) -> bool:
        data = self._require_success(
            self._client.health_recording_status(subject, sender_id)
        )
        enabled = data.get("enabled")
        if not isinstance(enabled, bool):
            raise PartnerHealthAdapterError("invalid-recording-status-response")
        return enabled

    def health_recording_status(self, subject: str, sender_id: str) -> str:
        data = self._require_success(
            self._client.health_recording_status(subject, sender_id)
        )
        status = data.get("status")
        if status not in {"not_enabled", "recording_enabled", "recording_stopped"}:
            raise PartnerHealthAdapterError("invalid-recording-status-response")
        return str(status)

    def profile_message_admitted(
        self, subject: str, sender_id: str, message_id: str
    ) -> bool:
        data = self._require_success(
            self._client.profile_message_admission_status(
                subject, sender_id, message_id
            )
        )
        admitted = data.get("admitted")
        if not isinstance(admitted, bool):
            raise PartnerHealthAdapterError("invalid-admission-status-response")
        return admitted

    def begin_recording_attempt(self, subject: str, sender_id: str) -> str:
        data = self._require_success(
            self._client.begin_recording_attempt(subject, sender_id)
        )
        lease_id = data.get("lease_id")
        if not isinstance(lease_id, str) or not lease_id.strip():
            raise PartnerHealthAdapterError("invalid-recording-attempt-response")
        return lease_id.strip()

    def end_recording_attempt(self, lease_id: str) -> bool:
        data = self._require_success(self._client.end_recording_attempt(lease_id))
        released = data.get("released")
        if not isinstance(released, bool):
            raise PartnerHealthAdapterError("invalid-recording-attempt-response")
        return released

    def enable_health_recording(
        self,
        subject: str,
        owner_sender_id: str,
        receipt_message_id: str,
        receipt_utc: str,
        verification_token: str,
    ) -> Mapping[str, Any]:
        return self._require_success(
            self._client.enable_health_recording(
                subject,
                owner_sender_id,
                receipt_message_id,
                receipt_utc,
                verification_token,
            )
        )

    def stop_health_recording(
        self,
        subject: str,
        owner_sender_id: str,
        receipt_message_id: str,
        receipt_utc: str,
        verification_token: str,
    ) -> Mapping[str, Any]:
        return self._require_success(
            self._client.stop_health_recording(
                subject,
                owner_sender_id,
                receipt_message_id,
                receipt_utc,
                verification_token,
            )
        )

    def resume_health_recording(
        self,
        subject: str,
        owner_sender_id: str,
        receipt_message_id: str,
        receipt_utc: str,
        verification_token: str,
    ) -> Mapping[str, Any]:
        return self._require_success(
            self._client.resume_health_recording(
                subject,
                owner_sender_id,
                receipt_message_id,
                receipt_utc,
                verification_token,
            )
        )

    def send_recording_feedback(
        self,
        subject: str,
        owner_sender_id: str,
        receipt_message_id: str,
        receipt_utc: str,
        verification_token: str,
        feedback_status: str,
    ) -> Mapping[str, Any]:
        return self._require_success(
            self._client.send_recording_feedback(
                subject,
                owner_sender_id,
                receipt_message_id,
                receipt_utc,
                verification_token,
                feedback_status,
            )
        )

    def admit_consented_profile_candidate(
        self,
        *,
        subject: str,
        sender_id: str,
        message_id: str,
        message_utc: str,
        attempt_utc: str,
        message_text: str,
        evidence_kind: str,
        channel: str,
        profile_name: str,
        verification_token: str,
        candidate: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        return self._require_success(
            self._client.admit_consented_profile_candidate(
                subject=subject,
                sender_id=sender_id,
                message_id=message_id,
                message_utc=message_utc,
                attempt_utc=attempt_utc,
                message_text=message_text,
                evidence_kind=evidence_kind,
                channel=channel,
                profile_name=profile_name,
                verification_token=verification_token,
                candidate=candidate,
            )
        )

    def read_health_turn_context(
        self,
        *,
        subject: str,
        sender_id: str,
        message_id: str,
        message_utc: str,
        message_text: str,
        channel: str,
        profile_name: str,
        attempt_utc: str,
        verification_token: str,
    ) -> Mapping[str, Any]:
        """Read the exact, receipt-bound context allowed for one health turn."""
        data = self._require_success(
            self._client.read_health_turn_context(
                subject=subject,
                sender_id=sender_id,
                message_id=message_id,
                message_utc=message_utc,
                message_text=message_text,
                channel=channel,
                profile_name=profile_name,
                attempt_utc=attempt_utc,
                verification_token=verification_token,
            )
        )
        try:
            return validate_health_turn_context(data)
        except HealthTurnContextError as exc:
            raise PartnerHealthAdapterError(
                "invalid-health-turn-context-response"
            ) from exc

    def stage_profile_message(
        self,
        subject: str,
        sender_id: str,
        message_id: str,
        message_utc: str,
        message_text: str,
        evidence_kind: str,
        verification_token: str,
    ) -> bool:
        """Stage a gateway-verified, profile-eligible owner message.

        ``evidence_kind`` and ``verification_token`` are supplied by the
        trusted gateway's inbound-event classifier, not inferred by the model
        candidate. Ordinary chat is never eligible for staging.
        """
        data = self._require_success(
            self._client.stage_profile_message(
                subject,
                sender_id,
                message_id,
                message_utc,
                message_text,
                evidence_kind,
                verification_token,
            )
        )
        staged = data.get("staged")
        if not isinstance(staged, bool):
            raise PartnerHealthAdapterError("invalid-message-stage-response")
        return staged

    def remember_recent_owner_message(
        self,
        subject: str,
        sender_id: str,
        message_id: str,
        message_utc: str,
        message_text: str,
        evidence_kind: str,
        verification_token: str,
        *,
        attempt_utc: str | None = None,
        channel: str = "weixin",
        profile_name: str = "partner",
    ) -> bool:
        """Keep a verified owner's message in the ephemeral latest-three window."""
        data = self._require_success(
            self._client.remember_recent_owner_message(
                subject,
                sender_id,
                message_id,
                message_utc,
                message_text,
                evidence_kind,
                verification_token,
                attempt_utc=attempt_utc,
                channel=channel,
                profile_name=profile_name,
            )
        )
        remembered = data.get("remembered")
        if not isinstance(remembered, bool):
            raise PartnerHealthAdapterError("invalid-recent-message-response")
        return remembered

    def read_profile(
        self,
        subject: str,
        sender_id: str,
        receipt_message_id: str,
        receipt_utc: str,
        verification_token: str,
    ) -> Mapping[str, Any]:
        response = self._require_success(
            self._client.read_profile_with_receipt(
                subject,
                sender_id,
                receipt_message_id,
                receipt_utc,
                verification_token,
            )
        )
        profile = response.get("profile")
        if not isinstance(profile, Mapping):
            raise PartnerHealthAdapterError("invalid-profile-read-response")
        return dict(profile)

    def grant_viewer(
        self,
        subject: str,
        owner_sender_id: str,
        viewer_sender_id: str,
        receipt_message_id: str,
        receipt_utc: str,
        verification_token: str,
    ) -> Mapping[str, Any]:
        """Grant one sender complete read-only health-view permissions."""
        return self._require_success(
            self._client.grant_viewer(
                subject,
                owner_sender_id,
                viewer_sender_id,
                receipt_message_id,
                receipt_utc,
                verification_token,
            )
        )

    def delete_profile(
        self,
        subject: str,
        sender_id: str,
        receipt_message_id: str,
        receipt_utc: str,
        verification_token: str,
    ) -> Mapping[str, Any]:
        """Reject the retired public one-step deletion adapter seam."""
        raise PartnerHealthAdapterError("delete-confirmation-required")

    def request_profile_deletion(
        self,
        subject: str,
        sender_id: str,
        receipt_message_id: str,
        receipt_utc: str,
        verification_token: str,
    ) -> Mapping[str, Any]:
        """Persist the first owner receipt without deleting any health data."""
        return self._require_success(
            self._client.request_profile_deletion(
                subject,
                sender_id,
                receipt_message_id,
                receipt_utc,
                verification_token,
            )
        )

    def confirm_profile_deletion(
        self,
        subject: str,
        sender_id: str,
        request_message_id: str,
        receipt_message_id: str,
        receipt_utc: str,
        verification_token: str,
    ) -> Mapping[str, Any]:
        """Run the irreversible deletion only after the matching second receipt."""
        return self._require_success(
            self._client.confirm_profile_deletion(
                subject,
                sender_id,
                request_message_id,
                receipt_message_id,
                receipt_utc,
                verification_token,
            )
        )

    def profile_deletion_status(
        self,
        subject: str,
        sender_id: str,
        receipt_message_id: str,
        receipt_utc: str,
        verification_token: str,
    ) -> Mapping[str, Any]:
        """Return deletion liveness only for a current owner-confirm receipt."""
        return self._require_success(
            self._client.profile_deletion_status(
                subject,
                sender_id,
                receipt_message_id,
                receipt_utc,
                verification_token,
            )
        )

    def purge_backups(self) -> Mapping[str, Any]:
        """Run deterministic 30-day encrypted-backup and audit retention cleanup."""
        return self._require_success(self._client.purge_backups())

    def revoke_viewer(
        self,
        subject: str,
        owner_sender_id: str,
        viewer_sender_id: str,
        receipt_message_id: str,
        receipt_utc: str,
        verification_token: str,
    ) -> Mapping[str, Any]:
        """Revoke a viewer immediately; already-sent content is not recalled."""
        return self._require_success(
            self._client.revoke_viewer(
                subject,
                owner_sender_id,
                viewer_sender_id,
                receipt_message_id,
                receipt_utc,
                verification_token,
            )
        )

    def read_authorized_view(
        self,
        subject: str,
        sender_id: str,
        receipt_message_id: str,
        receipt_utc: str,
        verification_token: str,
    ) -> Mapping[str, Any]:
        """Read profile, evidence, tasks, reports, and scoped audit events."""
        return self._require_success(
            self._client.read_authorized_view(
                subject,
                sender_id,
                receipt_message_id,
                receipt_utc,
                verification_token,
            )
        )

    def export_profile(
        self,
        subject: str,
        sender_id: str,
        receipt_message_id: str,
        receipt_utc: str,
        verification_token: str,
    ) -> Mapping[str, Any]:
        return self._require_success(
            self._client.export_profile(
                subject,
                sender_id,
                receipt_message_id,
                receipt_utc,
                verification_token,
            )
        )

    def read_authorized_analysis_context(
        self,
        subject: str,
        sender_id: str,
        receipt_message_id: str,
        receipt_utc: str,
        verification_token: str,
    ) -> Mapping[str, Any]:
        """Read only the bounded context approved for explicit model analysis."""
        return self._require_success(
            self._client.read_authorized_analysis_context(
                subject,
                sender_id,
                receipt_message_id,
                receipt_utc,
                verification_token,
            )
        )

    def query_sources(
        self,
        query: str,
        source_url: str | None = None,
        *,
        timeout_seconds: float | None = None,
    ) -> Mapping[str, Any]:
        """Read current source cards or perform one approved on-demand fetch."""
        return self._require_success(
            self._client.query_sources(
                query,
                source_url,
                timeout_seconds=timeout_seconds,
            )
        )

    def scan_sources(self, candidates: list[str]) -> Mapping[str, Any]:
        """Run one bounded source scan for the daily-review job."""
        return self._require_success(self._client.scan_sources(candidates))

    def daily_review_snapshot(
        self, subject: str, review_utc: str, timezone: str
    ) -> Mapping[str, Any]:
        """Read the controlled fresh-session input for one daily review."""
        return self._require_success(
            self._client.daily_review_snapshot(subject, review_utc, timezone)
        )

    def run_daily_review(
        self,
        subject: str,
        review_utc: str,
        timezone: str,
        plan: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        """Validate and persist one structured daily-review plan."""
        return self._require_success(
            self._client.run_daily_review(subject, review_utc, timezone, plan)
        )

    def execute_daily_review(
        self,
        subject: str,
        review_utc: str,
        timezone: str,
        job_authorization: str,
    ) -> Mapping[str, Any]:
        """Trigger the production sidecar daily-review executor once."""
        return self._require_success(
            self._client.execute_daily_review(
                subject, review_utc, timezone, job_authorization
            )
        )

    def dispatch_due_tasks(
        self, subject: str, now_utc: str, job_authorization: str
    ) -> Mapping[str, Any]:
        """Render due tasks using the server's controlled LLM/channel ports."""
        return self._require_success(
            self._client.dispatch_due_tasks(subject, now_utc, job_authorization)
        )

    def pause_proactive_contact(
        self,
        subject: str,
        owner_sender_id: str,
        receipt_message_id: str,
        receipt_utc: str,
        verification_token: str,
        pause_until_utc: str | None = None,
    ) -> Mapping[str, Any]:
        """Pause proactive tasks through the owner-authorized socket seam."""
        return self._require_success(
            self._client.pause_proactive_contact(
                subject,
                owner_sender_id,
                receipt_message_id,
                receipt_utc,
                verification_token,
                pause_until_utc,
            )
        )

    def resume_proactive_contact(
        self,
        subject: str,
        owner_sender_id: str,
        receipt_message_id: str,
        receipt_utc: str,
        verification_token: str,
    ) -> Mapping[str, Any]:
        """Resume proactive contact only after an explicit owner action."""
        return self._require_success(
            self._client.resume_proactive_contact(
                subject,
                owner_sender_id,
                receipt_message_id,
                receipt_utc,
                verification_token,
            )
        )

    @staticmethod
    def _require_success(response: Mapping[str, Any]) -> Mapping[str, Any]:
        if response.get("ok") is not True:
            error = response.get("error")
            if isinstance(error, Mapping):
                code = error.get("code", "sidecar_error")
            else:
                code = "sidecar_error"
            raise PartnerHealthAdapterError(str(code))
        data = response.get("data")
        if not isinstance(data, Mapping):
            raise PartnerHealthAdapterError("invalid-sidecar-response")
        return data
