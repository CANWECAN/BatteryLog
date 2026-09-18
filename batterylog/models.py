from typing import TypedDict


class ViolationEvent(TypedDict):
    code: str
    start_time_s: float
    end_time_s: float
    peak_time_s: float
    measured_value: float
    limit_value: float
    unit: str
    signals: list[str]


class AnalysisResult(TypedDict):
    rows_analyzed: int
    cells_detected: int
    temperature_sensors_detected: int
    max_cell_voltage_v: float
    min_cell_voltage_v: float
    max_delta_v: float
    max_temperature_c: float
    min_temperature_c: float
    violations: list[ViolationEvent]
