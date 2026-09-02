"""decidable: an evaluation harness for agents whose outputs can be verified."""

from decidable.models import (
    Agent,
    Artifact,
    Evidence,
    EvidenceValue,
    HarnessError,
    Report,
    RunMetadata,
    Stage,
    Status,
    Suite,
    Task,
    TaskResult,
    Verdict,
    VerifierRef,
    roll_up,
)

__version__ = "0.1.0"

__all__ = [
    "Agent",
    "Artifact",
    "Evidence",
    "EvidenceValue",
    "HarnessError",
    "Report",
    "RunMetadata",
    "Stage",
    "Status",
    "Suite",
    "Task",
    "TaskResult",
    "Verdict",
    "VerifierRef",
    "__version__",
    "roll_up",
]
