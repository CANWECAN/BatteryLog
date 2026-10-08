"""Prepare canonical CSV plus conversion evidence without evaluating rules."""

import json
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal, TypedDict

import pandas as pd

from .analysis.input_validation import (
    balance_values_for_frame,
    canonicalize_analysis_frame,
    coerce_required_numeric,
    contactor_values_for_frame,
    parse_binary_status,
    precharge_values_for_frame,
    raise_invalid_numeric_value,
    unloaded_values_for_frame,
)
from .config import ValidationConfig
from .loaders.csv import DEFAULT_CSV_CHUNK_ROWS, iter_battery_csv_file
from .loaders.mf4 import DEFAULT_MDF_CHUNK_RAM_BYTES, _iter_mdf_chunks, is_mdf_path
from .reporting.evidence import (
    FileEvidence,
    build_report_metadata,
    capture_file_backed_snapshot,
    sha256_file,
    verify_file_unchanged,
)
from .signals import resolve_signal_mapping
from .units import SourceUnits, unit_transform


class UnitConversion(TypedDict):
    source: str
    canonical: str
    source_unit: str
    target_unit: str
    divisor: float
    offset: float


class NormalizationResult(TypedDict):
    normalization_schema_version: Literal[1]
    analysis_performed: Literal[False]
    rows_written: int
    normalized_csv: str
    normalized_sha256: str
    conversions: list[UnitConversion]
    source: dict[str, object]
    config: dict[str, object] | None
    batterylog_version: str
    generated_at_utc: str


def normalize_measurement(
    path: str | Path,
    output_directory: str | Path,
    *,
    units: SourceUnits,
    config: ValidationConfig | None = None,
    config_evidence: FileEvidence | None = None,
) -> NormalizationResult:
    """Strictly convert selected channels to a new CSV and conversion.json.

    No rows are excluded, no interpolation or sorting is performed, and no
    engineering rule is evaluated. Each role must use one declared source unit.
    Configuration is used for mapping and required-channel checks only.
    """
    if not isinstance(units, SourceUnits):
        raise TypeError("units must be a SourceUnits instance")
    config = ValidationConfig() if config is None else config
    if not isinstance(config, ValidationConfig):
        raise TypeError("config must be a ValidationConfig instance")
    source, destination = Path(path).resolve(), Path(output_directory).resolve()
    if destination.exists():
        raise ValueError("Normalization requires a new output directory")
    if is_mdf_path(source) and units.timestamp != "s":
        raise ValueError("MDF master time is already in seconds; declare timestamp unit 's'")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with (
        capture_file_backed_snapshot(source) as snapshot,
        TemporaryDirectory(prefix=".batterylog-normalize-", dir=destination.parent) as temporary,
    ):
        staged = Path(temporary) / "prepared"
        staged.mkdir()
        csv_path = staged / "normalized.csv"
        chunks = (
            _iter_mdf_chunks(
                snapshot.handle,
                signal_mapping=config.signals,
                chunk_ram_bytes=DEFAULT_MDF_CHUNK_RAM_BYTES,
                source_units=units,
                balance_active_source=(
                    config.failure_models.balancing.active_source
                    if config.failure_models and config.failure_models.balancing
                    else None
                ),
                status_sources=(
                    (config.failure_models.precharge_current.active_source,)
                    if config.failure_models and config.failure_models.precharge_current
                    else ()
                )
                + (
                    (
                        config.failure_models.contactor_response.command_source,
                        config.failure_models.contactor_response.feedback_source,
                    )
                    if config.failure_models and config.failure_models.contactor_response
                    else ()
                ),
                unloaded_source=(
                    config.failure_models.unloaded_current.unloaded_source
                    if config.failure_models and config.failure_models.unloaded_current
                    else None
                ),
            )
            if is_mdf_path(source)
            else iter_battery_csv_file(snapshot.handle, chunk_rows=DEFAULT_CSV_CHUNK_ROWS)
        )
        rows = 0
        previous_time: float | None = None
        previous_source_time: float | None = None
        conversions: list[UnitConversion] = []
        selected_columns: list[str] | None = None
        status_presence: dict[str, bool] = {}
        try:
            with csv_path.open("w", encoding="utf-8", newline="") as output:
                for frame in chunks:
                    status_values: dict[str, pd.Series] = {}
                    status_labels: dict[str, str] = {}
                    contactor_values = contactor_values_for_frame(
                        frame, config.signals, config.failure_models
                    )
                    contactor = (
                        config.failure_models.contactor_response if config.failure_models else None
                    )
                    for label, values, state_source in (
                        (
                            "Precharge",
                            precharge_values_for_frame(
                                frame, config.signals, config.failure_models
                            ),
                            config.failure_models.precharge_current.active_source
                            if config.failure_models and config.failure_models.precharge_current
                            else None,
                        ),
                        (
                            "Balancing",
                            balance_values_for_frame(frame, config.signals, config.failure_models),
                            config.failure_models.balancing.active_source
                            if config.failure_models and config.failure_models.balancing
                            else None,
                        ),
                        (
                            "Unloaded",
                            unloaded_values_for_frame(frame, config.signals, config.failure_models),
                            config.failure_models.unloaded_current.unloaded_source
                            if config.failure_models and config.failure_models.unloaded_current
                            else None,
                        ),
                        (
                            "Contactor command",
                            contactor_values[0],
                            contactor.command_source if contactor else None,
                        ),
                        (
                            "Contactor feedback",
                            contactor_values[1],
                            contactor.feedback_source if contactor else None,
                        ),
                    ):
                        present = values is not None
                        if label in status_presence and status_presence[label] != present:
                            raise ValueError(
                                f"{label} signal presence changed during normalization"
                            )
                        status_presence[label] = present
                        if values is not None and state_source is not None:
                            status_values[state_source] = values
                            status_labels[state_source] = label
                    canonical, layout = canonicalize_analysis_frame(
                        frame, config.signals, config.limits
                    )
                    if selected_columns is None:
                        selected_columns = layout.numeric_cols
                        if config.signals is None:
                            source_names = {name: name for name in selected_columns}
                        else:
                            resolved = resolve_signal_mapping(frame.columns, config.signals)
                            source_names = dict(
                                zip(
                                    resolved.canonical_columns, resolved.source_columns, strict=True
                                )
                            )
                        roles = {
                            "timestamp_s": units.timestamp,
                            **dict.fromkeys(layout.cell_cols, units.cell_voltage),
                            **dict.fromkeys(layout.temp_cols, units.temperature),
                        }
                        for name, declared in (
                            ("pack_current_a", units.pack_current),
                            ("pack_voltage_v", units.pack_voltage),
                        ):
                            present = name in selected_columns
                            if present != (declared is not None):
                                raise ValueError(
                                    f"Declare a unit exactly when {name!r} is selected"
                                )
                            if declared is not None:
                                roles[name] = declared
                        for name in selected_columns:
                            unit = roles[name]
                            target, divisor, offset = unit_transform(unit)
                            conversions.append(
                                {
                                    "source": source_names[name],
                                    "canonical": name,
                                    "source_unit": unit,
                                    "target_unit": target,
                                    "divisor": divisor,
                                    "offset": offset,
                                }
                            )
                        for state_source in status_values:
                            conversions.append(
                                {
                                    "source": state_source,
                                    "canonical": state_source,
                                    "source_unit": "1",
                                    "target_unit": "1",
                                    "divisor": 1.0,
                                    "offset": 0.0,
                                }
                            )
                    elif layout.numeric_cols != selected_columns:
                        raise ValueError("Selected channel layout changed between chunks")
                    selected = canonical.loc[:, selected_columns]
                    numeric = coerce_required_numeric(selected)
                    raise_invalid_numeric_value(selected, numeric, row_offset=rows)
                    if numeric.empty:
                        continue
                    source_times = numeric["timestamp_s"].to_numpy(dtype=float)
                    if (source_times[1:] < source_times[:-1]).any() or (
                        previous_source_time is not None and source_times[0] < previous_source_time
                    ):
                        raise ValueError(
                            "Source timestamps must be non-decreasing during normalization"
                        )
                    previous_source_time = float(source_times[-1])
                    for conversion in conversions:
                        name = conversion["canonical"]
                        if name in status_values:
                            continue
                        original = numeric[name].to_numpy(dtype=float)
                        scaled = original / conversion["divisor"]
                        if ((original != 0) & (scaled == 0)).any():
                            raise ValueError(f"Unit conversion underflow in {name!r}")
                        numeric[name] = scaled + conversion["offset"]
                    raise_invalid_numeric_value(selected, numeric, row_offset=rows)
                    times = numeric["timestamp_s"].to_numpy(dtype=float)
                    if len(times):
                        if (times[1:] < times[:-1]).any() or (
                            previous_time is not None and times[0] < previous_time
                        ):
                            raise ValueError(
                                "Timestamps must be non-decreasing during normalization"
                            )
                        previous_time = float(times[-1])
                    for state_source, values in status_values.items():
                        statuses = []
                        for position, value in enumerate(values.to_numpy(dtype=object)):
                            active = parse_binary_status(value)
                            if active is None:
                                raise ValueError(
                                    f"{status_labels[state_source]} status must be 0/1 or boolean at data row {rows + position + 1}"
                                )
                            statuses.append(int(active))
                        numeric[state_source] = statuses
                    numeric.to_csv(output, index=False, header=rows == 0, lineterminator="\n")
                    rows += len(numeric)
        finally:
            close = getattr(chunks, "close", None)
            if close is not None:
                close()
        if rows == 0:
            raise ValueError("Battery log contains no data rows")
        metadata = build_report_metadata(snapshot.evidence, config_evidence)
        result: NormalizationResult = {
            "normalization_schema_version": 1,
            "analysis_performed": False,
            "rows_written": rows,
            "normalized_csv": "normalized.csv",
            "normalized_sha256": sha256_file(csv_path),
            "conversions": conversions,
            "source": asdict(metadata.source),
            "config": asdict(metadata.config) if metadata.config is not None else None,
            "batterylog_version": metadata.batterylog_version,
            "generated_at_utc": metadata.generated_at_utc,
        }
        (staged / "conversion.json").write_text(
            json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8"
        )
        verify_file_unchanged(source, snapshot.evidence)
        if destination.exists():
            raise ValueError("Normalization output directory was created during conversion")
        staged.rename(destination)
        return result
