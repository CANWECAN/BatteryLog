from typing import Literal, TypedDict

RuleCode = Literal[
    "CELL_IMBALANCE_HIGH",
    "CELL_OVERVOLTAGE",
    "CELL_UNDERVOLTAGE",
    "TEMPERATURE_HIGH",
    "TEMPERATURE_LOW",
]

ResultSchemaVersion = Literal[2]
RESULT_SCHEMA_VERSION: ResultSchemaVersion = 2

ValidationStatus = Literal["NOT_EVALUATED", "PASS", "FAIL"]
SignalMappingMode = Literal["canonical", "explicit"]
ComparisonMode = Literal["strict_with_binary64_guard"]


class ComparisonPolicyInfo(TypedDict):
    mode: ComparisonMode
    relative_tolerance: float
    absolute_tolerance: float


class AppliedLimits(TypedDict):
    cell_min_v: float | None
    cell_max_v: float | None
    imbalance_max_v: float | None
    temperature_min_c: float | None
    temperature_max_c: float | None


class AnalysisOptions(TypedDict):
    max_event_gap_s: float | None


class SignalMappingInfo(TypedDict):
    mode: SignalMappingMode
    timestamp_source: str
    cell_voltage_pattern: str | None
    temperature_pattern: str | None


class ViolationEvent(TypedDict):
    code: RuleCode
    start_time_s: float
    end_time_s: float
    peak_time_s: float
    measured_value: float
    limit_value: float
    unit: str
    signals: list[str]


class AnalysisResult(TypedDict):
    schema_version: ResultSchemaVersion
    validation_status: ValidationStatus
    rules_evaluated: list[RuleCode]
    limits_applied: AppliedLimits
    analysis_options: AnalysisOptions
    comparison_policy: ComparisonPolicyInfo
    signal_mapping: SignalMappingInfo
    rows_analyzed: int
    cells_detected: int
    temperature_sensors_detected: int
    max_cell_voltage_v: float
    min_cell_voltage_v: float
    max_delta_v: float
    max_temperature_c: float
    min_temperature_c: float
    violations: list[ViolationEvent]
