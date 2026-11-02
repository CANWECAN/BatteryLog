"""Review voltage-spread context without estimating physical SOC imbalance."""

from dataclasses import dataclass, field
from typing import Literal, TypedDict

from .measurement_context import AcquisitionMode, MeasurementContext, OperatingState

VoltageReason = Literal[
    "MEASUREMENT_CONTEXT_NOT_SUPPLIED",
    "CHEMISTRY_NOT_DECLARED",
    "SOC_VALUE_NOT_DECLARED",
    "SOC_SOURCE_NOT_DECLARED",
    "OPERATING_STATE_NOT_DECLARED",
    "UNDER_LOAD_OPERATION_DECLARED",
    "REST_EQUILIBRATION_NOT_VERIFIED",
    "CELL_VOLTAGE_CHANNELS_NOT_DECLARED",
    "CELL_IDENTITY_NOT_DECLARED",
    "CHANNEL_UNIT_NOT_DECLARED",
    "CHANNEL_TIME_BASIS_NOT_DECLARED",
    "CHANNEL_ACQUISITION_NOT_DECLARED",
    "ASYNCHRONOUS_ACQUISITION_DECLARED",
    "PREVIOUS_SAMPLE_HOLD_DECLARED",
    "MULTIPLE_TIME_BASES_DECLARED",
    "CELL_INVENTORY_NOT_VERIFIED",
    "OPERATING_CONTEXT_NOT_VERIFIED",
    "MEASUREMENT_PROPERTIES_NOT_VERIFIED",
    "SOC_IMBALANCE_MODEL_NOT_AVAILABLE",
]


class VoltageIssue(TypedDict):
    code: VoltageReason
    field: str
    source: str | None
    detail: str


class SOCDeclaration(TypedDict):
    value_percent: float | None
    source: str | None


class CellVoltageDeclaration(TypedDict):
    source: str
    unit: str | None
    branch_id: str | None
    cell_id: str | None
    time_basis: str | None
    acquisition: AcquisitionMode | None


class VoltageSpreadPayload(TypedDict):
    voltage_spread_context_schema_version: Literal[1]
    scope: Literal["declared_measurement_context_only"]
    claim: Literal["CELL_SOC_IMBALANCE"]
    status: Literal["NOT_EVALUATED"]
    diagnostic_claim: Literal[False]
    context_supplied: bool
    declared_chemistry: str | None
    declared_soc: SOCDeclaration | None
    declared_operating_state: OperatingState | None
    declared_time_bases: list[str]
    cell_voltage_channels: list[CellVoltageDeclaration]
    cell_inventory_verified: Literal[False]
    operating_context_verified: Literal[False]
    measurement_properties_verified: Literal[False]
    soc_imbalance_method_available: Literal[False]
    reason_codes: list[VoltageReason]
    issues: list[VoltageIssue]


@dataclass(frozen=True)
class VoltageSpreadAssessment:
    """Describe declared context gaps independently of engineering observations.

    No samples or engineering result are accepted, converted or changed here.
    Chemistry, SOC and rest labels cannot enable an SOC estimate. A later
    source-bound workflow must associate this review with actual observations.
    """

    context: MeasurementContext | None = None
    status: Literal["NOT_EVALUATED"] = field(default="NOT_EVALUATED", init=False)
    diagnostic_claim: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        if self.context is not None and type(self.context) is not MeasurementContext:
            raise TypeError("context must be a validated MeasurementContext or None")

    def to_dict(self) -> VoltageSpreadPayload:
        context = self.context
        issues: list[VoltageIssue] = []
        channels: list[CellVoltageDeclaration] = []
        time_bases: set[str] = set()

        def add(code: VoltageReason, location: str, detail: str, source: str | None = None) -> None:
            issues.append({"code": code, "field": location, "source": source, "detail": detail})

        add(
            "SOC_IMBALANCE_MODEL_NOT_AVAILABLE",
            "soc_imbalance_method",
            "This review implements no validated SOC-imbalance method or voltage-to-SOC conversion. Complete declarations cannot enable an estimate.",
        )
        add(
            "MEASUREMENT_PROPERTIES_NOT_VERIFIED",
            "measurement_properties",
            "Source existence, units, calibration, freshness and acquisition alignment have not been verified by this declaration review.",
        )
        add(
            "OPERATING_CONTEXT_NOT_VERIFIED",
            "operating_context",
            "Chemistry, SOC provenance and operating-state declarations have not been verified against the recording; no time intervals are classified.",
        )
        add(
            "CELL_INVENTORY_NOT_VERIFIED",
            "channels",
            "Declared cell labels do not establish a complete physical inventory or a valid cell comparison group.",
        )

        if context is None:
            add(
                "MEASUREMENT_CONTEXT_NOT_SUPPLIED",
                "context",
                "No measurement context was supplied.",
            )
        else:
            if context.chemistry is None:
                add(
                    "CHEMISTRY_NOT_DECLARED",
                    "chemistry",
                    "No chemistry label is declared; no chemistry or voltage-to-SOC relation is inferred.",
                )
            if context.soc is None or context.soc.value_percent is None:
                add("SOC_VALUE_NOT_DECLARED", "soc.value_percent", "No SOC value is declared.")
            if context.soc is None or context.soc.source is None:
                add(
                    "SOC_SOURCE_NOT_DECLARED",
                    "soc.source",
                    "No source for the declared SOC context is supplied; a numeric value alone is not provenance.",
                )
            if context.operating_state in {None, "unknown"}:
                add(
                    "OPERATING_STATE_NOT_DECLARED",
                    "operating_state",
                    "Load/rest conditions are unspecified; none are inferred from channel names or voltage spread.",
                )
            elif context.operating_state == "rest":
                add(
                    "REST_EQUILIBRATION_NOT_VERIFIED",
                    "operating_state",
                    "A rest label does not verify relaxation duration or equilibrium, or establish that terminal samples are open-circuit voltages.",
                )
            else:
                add(
                    "UNDER_LOAD_OPERATION_DECLARED",
                    "operating_state",
                    "Charge, discharge or mixed operation is declared. This review does not separate load response from physical SOC differences.",
                )

            for channel in context.channels:
                if channel.role != "cell_voltage":
                    continue
                source = channel.source
                channels.append(
                    {
                        "source": source,
                        "unit": channel.unit,
                        "branch_id": channel.branch_id,
                        "cell_id": channel.cell_id,
                        "time_basis": channel.time_basis,
                        "acquisition": channel.acquisition,
                    }
                )
                if channel.cell_id is None:
                    add(
                        "CELL_IDENTITY_NOT_DECLARED",
                        "channels.cell_id",
                        "No physical cell label is declared; none is inferred from the source name.",
                        source,
                    )
                if channel.unit is None:
                    add(
                        "CHANNEL_UNIT_NOT_DECLARED",
                        "channels.unit",
                        "No source unit is declared.",
                        source,
                    )
                if channel.time_basis is None:
                    add(
                        "CHANNEL_TIME_BASIS_NOT_DECLARED",
                        "channels.time_basis",
                        "No time-basis label is declared.",
                        source,
                    )
                else:
                    time_bases.add(channel.time_basis)
                if channel.acquisition in {None, "unknown"}:
                    add(
                        "CHANNEL_ACQUISITION_NOT_DECLARED",
                        "channels.acquisition",
                        "The acquisition mode is unspecified.",
                        source,
                    )
                elif channel.acquisition == "asynchronous":
                    add(
                        "ASYNCHRONOUS_ACQUISITION_DECLARED",
                        "channels.acquisition",
                        "Asynchronous acquisition is declared; comparison-time alignment is unverified.",
                        source,
                    )
                elif channel.acquisition == "previous_sample_hold":
                    add(
                        "PREVIOUS_SAMPLE_HOLD_DECLARED",
                        "channels.acquisition",
                        "Previous-sample holding is declared; repeated rows do not establish fresh cell acquisitions.",
                        source,
                    )
            if not channels:
                add(
                    "CELL_VOLTAGE_CHANNELS_NOT_DECLARED",
                    "channels.cell_voltage",
                    "No cell-voltage sources are declared here. Pack/branch voltage is not substituted; this does not assert absence from the recording.",
                )
            if len(time_bases) > 1:
                add(
                    "MULTIPLE_TIME_BASES_DECLARED",
                    "channels.time_basis",
                    "Multiple cell-voltage time-basis labels are declared; synchronization and clock relationships are unverified.",
                )

        channels.sort(key=lambda channel: channel["source"])
        issues.sort(key=lambda issue: (issue["code"], issue["source"] or "", issue["field"]))
        return {
            "voltage_spread_context_schema_version": 1,
            "scope": "declared_measurement_context_only",
            "claim": "CELL_SOC_IMBALANCE",
            "status": self.status,
            "diagnostic_claim": self.diagnostic_claim,
            "context_supplied": context is not None,
            "declared_chemistry": context.chemistry if context is not None else None,
            "declared_soc": (
                {"value_percent": context.soc.value_percent, "source": context.soc.source}
                if context is not None and context.soc is not None
                else None
            ),
            "declared_operating_state": context.operating_state if context is not None else None,
            "declared_time_bases": sorted(time_bases),
            "cell_voltage_channels": channels,
            "cell_inventory_verified": False,
            "operating_context_verified": False,
            "measurement_properties_verified": False,
            "soc_imbalance_method_available": False,
            "reason_codes": sorted({issue["code"] for issue in issues}),
            "issues": issues,
        }
