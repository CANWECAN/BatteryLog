"""Independent, non-diagnostic interpretation limits for engineering observations.

This development API records limits only. It neither inspects measurement context
nor validates, changes or authenticates an engineering result. The caller supplies
the status from its engineering analysis; source binding belongs to a later review
workflow. See docs/INTERPRETATION_CONTRACT.md.
"""

from dataclasses import dataclass, field
from typing import Literal, TypedDict

from .models import ValidationStatus

InterpretationClaim = Literal[
    "CELL_SOC_IMBALANCE",
    "PARALLEL_BRANCH_FAULT_LOCATION",
    "SENSOR_VS_CELL_FAULT_ISOLATION",
]
InterpretationReason = Literal[
    "MEASUREMENT_CONTEXT_NOT_ASSESSED",
    "SOC_IMBALANCE_MODEL_NOT_AVAILABLE",
    "BRANCH_LOCALIZATION_MODEL_NOT_AVAILABLE",
    "FAULT_ISOLATION_MODEL_NOT_AVAILABLE",
]


class ClaimLimit(TypedDict):
    claim: InterpretationClaim
    status: Literal["NOT_EVALUATED"]
    reason_codes: list[InterpretationReason]


class InterpretationPayload(TypedDict):
    interpretation_schema_version: Literal[1]
    engineering_status: ValidationStatus
    diagnostic_claim: Literal[False]
    claims: list[ClaimLimit]


_LIMITS: tuple[tuple[InterpretationClaim, InterpretationReason], ...] = (
    ("CELL_SOC_IMBALANCE", "SOC_IMBALANCE_MODEL_NOT_AVAILABLE"),
    ("PARALLEL_BRANCH_FAULT_LOCATION", "BRANCH_LOCALIZATION_MODEL_NOT_AVAILABLE"),
    ("SENSOR_VS_CELL_FAULT_ISOLATION", "FAULT_ISOLATION_MODEL_NOT_AVAILABLE"),
)


@dataclass(frozen=True)
class InterpretationReport:
    """Keep caller-supplied engineering acceptance separate from physical claims.

    All three physical claims remain NOT_EVALUATED. PASS is not a diagnostic
    status, and FAIL does not identify a fault cause. Exported dictionaries are
    detached, mutable copies; modifying one cannot change this report or another
    export. No measurement or source provenance is implied by this object.
    """

    engineering_status: ValidationStatus
    interpretation_schema_version: Literal[1] = field(default=1, init=False)
    diagnostic_claim: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        if type(self.engineering_status) is not str or self.engineering_status not in (
            "PASS",
            "FAIL",
            "NOT_EVALUATED",
        ):
            raise ValueError("engineering_status must be PASS, FAIL or NOT_EVALUATED")

    def to_dict(self) -> InterpretationPayload:
        """Return a JSON-compatible copy without modifying engineering evidence."""
        return {
            "interpretation_schema_version": self.interpretation_schema_version,
            "engineering_status": self.engineering_status,
            "diagnostic_claim": self.diagnostic_claim,
            "claims": [
                {
                    "claim": claim,
                    "status": "NOT_EVALUATED",
                    "reason_codes": ["MEASUREMENT_CONTEXT_NOT_ASSESSED", reason],
                }
                for claim, reason in _LIMITS
            ],
        }
