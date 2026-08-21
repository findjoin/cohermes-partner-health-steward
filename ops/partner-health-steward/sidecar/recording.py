"""Shared recording-lifecycle domain constants."""

from __future__ import annotations


FEEDBACK_BACKFILLED = "backfilled"
FEEDBACK_NOT_RECORDED = "not_recorded"
ACTION_RECORDING_FEEDBACK_BACKFILLED = "health.recording.feedback.backfilled"
ACTION_RECORDING_FEEDBACK_NOT_RECORDED = "health.recording.feedback.not_recorded"

RECORDING_FEEDBACK_ACTION_BY_STATUS = {
    FEEDBACK_BACKFILLED: ACTION_RECORDING_FEEDBACK_BACKFILLED,
    FEEDBACK_NOT_RECORDED: ACTION_RECORDING_FEEDBACK_NOT_RECORDED,
}
RECORDING_FEEDBACK_STATUS_BY_ACTION = {
    action: status for status, action in RECORDING_FEEDBACK_ACTION_BY_STATUS.items()
}
RECORDING_FEEDBACK_MESSAGE_BY_STATUS = {
    FEEDBACK_BACKFILLED: "〔健康管家：已补录〕",
    FEEDBACK_NOT_RECORDED: "〔健康管家：本次未记录〕",
}
