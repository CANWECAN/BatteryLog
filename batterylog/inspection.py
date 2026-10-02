"""Read channel metadata without decoding or validating measurement samples."""

from collections.abc import Iterable
from pathlib import Path
from typing import Literal, TypedDict

import pandas as pd

from .analysis.input_validation import canonicalize_analysis_frame
from .config import ValidationConfig
from .loaders import mf4
from .loaders.csv import _read_csv_header, _validate_header
from .signals import resolve_signal_mapping


class InspectionChannel(TypedDict):
    name: str
    unit: str | None
    group: int | None
    index: int | None


class InspectionBinding(TypedDict):
    source: str
    canonical: str


class InspectionResult(TypedDict):
    inspection_schema_version: Literal[1]
    source_format: Literal["csv", "mf4"]
    scope: Literal["channel_metadata_only"]
    analysis_performed: Literal[False]
    metadata_status: Literal["OK", "ISSUES"]
    time_basis: Literal["csv_column", "mdf_master"]
    channels: list[InspectionChannel]
    bindings: list[InspectionBinding]
    issues: list[str]


def _bindings(names: list[str], config: ValidationConfig) -> list[InspectionBinding]:
    _, layout = canonicalize_analysis_frame(
        pd.DataFrame(columns=names), config.signals, config.limits
    )
    pairs: Iterable[tuple[str, str]]
    if config.signals is not None:
        resolved = resolve_signal_mapping(names, config.signals)
        pairs = zip(resolved.source_columns, resolved.canonical_columns, strict=True)
    else:
        pairs = ((name, name) for name in layout.numeric_cols)
    return [{"source": source, "canonical": canonical} for source, canonical in pairs]


def inspect_measurement(
    path: str | Path, *, config: ValidationConfig | None = None
) -> InspectionResult:
    """List channels and check their selection using the analysis loader's policy.

    A readable inventory is returned even when selection fails. Only the first
    blocking selection issue is reported. Sample values, CSV row structure and
    time alignment are not checked; OK is not an engineering validation result.
    """
    if config is None:
        config = ValidationConfig()
    if not isinstance(config, ValidationConfig):
        raise TypeError("config must be a ValidationConfig")
    source = Path(path)
    result: InspectionResult = {
        "inspection_schema_version": 1,
        "source_format": "mf4" if mf4.is_mdf_path(source) else "csv",
        "scope": "channel_metadata_only",
        "analysis_performed": False,
        "metadata_status": "OK",
        "time_basis": "mdf_master" if mf4.is_mdf_path(source) else "csv_column",
        "channels": [],
        "bindings": [],
        "issues": [],
    }
    if result["source_format"] == "csv":
        with source.open("rb") as handle:
            names = _read_csv_header(handle)
        result["channels"] = [
            {"name": name, "unit": None, "group": None, "index": None} for name in names
        ]
        try:
            _validate_header(names)
            result["bindings"] = _bindings(names, config)
        except (TypeError, ValueError) as exc:
            result["issues"].append(str(exc))
    else:
        MDF, MdfException = mf4._load_asammdf()
        try:
            with MDF(source, use_display_names=False, process_bus_logging=False) as mdf:
                for name in sorted(mdf.channels_db):
                    for group, index in mdf.whereis(name):
                        unit = mdf.get_channel_unit(name=name, group=group, index=index)
                        result["channels"].append(
                            {
                                "name": name,
                                "unit": unit if isinstance(unit, str) else None,
                                "group": group,
                                "index": index,
                            }
                        )
                try:
                    timestamp, names, _ = mf4._resolve_mdf_selection(mdf, config.signals)
                    result["bindings"] = _bindings([timestamp, *names], config)
                except (TypeError, ValueError) as exc:
                    result["issues"].append(str(exc))
        except MdfException as exc:
            raise ValueError(f"Failed to read MDF measurement: {exc}") from exc
    if result["issues"]:
        result["metadata_status"] = "ISSUES"
    return result
