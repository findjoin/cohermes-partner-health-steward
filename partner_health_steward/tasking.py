"""Compatibility/public name for the Ticket 115 task authority."""

from .tasks import (
    TASK_APPROVAL_STATUSES,
    TASK_INITIAL_PHASES,
    TASK_PHASES,
    TASK_PRIMARY_LABELS,
    TASK_SOURCE_KINDS,
    TASK_UNKNOWN_RESOLUTIONS,
    ManagedTask,
    TaskAcceptance,
    TaskAcceptanceCriterionProof,
    TaskApprovalBinding,
    TaskCandidate,
    TaskContractViolation,
    TaskEngine,
    TaskExternalBoundary,
    TaskLease,
    TaskRuntimeState,
    TaskTerminalFact,
    TaskTransition,
    TaskUnknownFact,
)

HealthTask = ManagedTask
HealthTaskCandidate = TaskCandidate

__all__ = [
    "TASK_APPROVAL_STATUSES",
    "TASK_INITIAL_PHASES",
    "TASK_PHASES",
    "TASK_PRIMARY_LABELS",
    "TASK_SOURCE_KINDS",
    "TASK_UNKNOWN_RESOLUTIONS",
    "HealthTask",
    "HealthTaskCandidate",
    "ManagedTask",
    "TaskAcceptance",
    "TaskAcceptanceCriterionProof",
    "TaskApprovalBinding",
    "TaskCandidate",
    "TaskContractViolation",
    "TaskEngine",
    "TaskExternalBoundary",
    "TaskLease",
    "TaskRuntimeState",
    "TaskTerminalFact",
    "TaskTransition",
    "TaskUnknownFact",
]
