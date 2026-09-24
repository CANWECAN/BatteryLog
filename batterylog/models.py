from typing import Literal, TypedDict

RuleCode = Literal[
    "CELL_IMBALANCE_HIGH",
    "CELL_OVERVOLTAGE",
    "CELL_UNDERVOLTAGE",
    "PACK_CHARGE_OVERCURRENT",
    "PACK_DISCHARGE_OVERCURRENT",
    "TEMPERATURE_HIGH",
    "TEMPERATURE_LOW",
    "TEMPERATURE_SPREAD_HIGH",
]

ResultSchemaVersion = Literal[7]
RESULT_SCHEMA_VERSION: ResultSchemaVersion = 7

CurrentDirection = Literal["charge", "discharge"]
ValidationStatus = Literal["NOT_EVALUATED", "PASS", "FAIL"]
DataQualityMode = Literal["strict", "exclude_invalid_rows"]
DataQualityCode = Literal[
    "MISSING_REQUIRED_VALUE",
    "NON_NUMERIC_REQUIRED_VALUE",
    "NON_FINITE_REQUIRED_VALUE",
]
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
    pack_charge_max_a: float | None
    pack_discharge_max_a: float | None
    pack_current_positive_direction: CurrentDirection | None
    temperature_spread_max_c: float | None


class AnalysisOptions(TypedDict):
    max_event_gap_s: float | None


class SignalMappingInfo(TypedDict):
    mode: SignalMappingMode
    timestamp_source: str
    cell_voltage_pattern: str | None
    temperature_pattern: str | None
    pack_current_source: str | None
    pack_voltage_source: str | None


class DataQualityEvent(TypedDict):
    code: DataQualityCode
    start_row: int
    end_row: int
    signals: list[str]
    affected_values: int


class DataQualityInfo(TypedDict):
    mode: DataQualityMode
    events: list[DataQualityEvent]


class ViolationEvent(TypedDict):
    code: RuleCode
    start_time_s: float
    end_time_s: float
    peak_time_s: float
    measured_value: float
    limit_value: float
    sample_count: int
    duration_s: float
    peak_excursion: float
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
    data_quality: DataQualityInfo
    rows_input: int
    rows_analyzed: int
    rows_excluded: int
    cells_detected: int
    temperature_sensors_detected: int
    max_cell_voltage_v: float | None
    min_cell_voltage_v: float | None
    max_delta_v: float | None
    max_temperature_c: float | None
    min_temperature_c: float | None
    max_temperature_spread_c: float | None
    max_pack_current_a: float | None
    min_pack_current_a: float | None
    max_pack_voltage_v: float | None
    min_pack_voltage_v: float | None
    violations: list[ViolationEvent]
