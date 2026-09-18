from dataclasses import dataclass, replace
from math import isfinite
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class ValidationLimits:
    cell_min_v: float | None = None
    cell_max_v: float | None = None
    imbalance_max_v: float | None = 0.08
    temperature_min_c: float | None = None
    temperature_max_c: float | None = 45.0

    def __post_init__(self) -> None:
        for name, value in (
            ("cell_min_v", self.cell_min_v),
            ("cell_max_v", self.cell_max_v),
            ("imbalance_max_v", self.imbalance_max_v),
            ("temperature_min_c", self.temperature_min_c),
            ("temperature_max_c", self.temperature_max_c),
        ):
            if value is None:
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"{name} must be a number or null")
            if not isfinite(value):
                raise ValueError(f"{name} must be finite or null")

        if self.imbalance_max_v is not None and self.imbalance_max_v < 0:
            raise ValueError("imbalance_max_v must be non-negative or null")
        if (
            self.cell_min_v is not None
            and self.cell_max_v is not None
            and self.cell_min_v >= self.cell_max_v
        ):
            raise ValueError("cell_min_v must be lower than cell_max_v")
        if (
            self.temperature_min_c is not None
            and self.temperature_max_c is not None
            and self.temperature_min_c >= self.temperature_max_c
        ):
            raise ValueError("temperature_min_c must be lower than temperature_max_c")


def _require_mapping(name: str, value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError(f"{name} must be a mapping")
    return value


def _reject_unknown_keys(
    name: str,
    mapping: dict[str, Any],
    allowed: set[str],
) -> None:
    unknown = sorted(set(mapping) - allowed)
    if unknown:
        joined = ", ".join(unknown)
        raise ValueError(f"Unknown {name} key(s): {joined}")


def _optional_number(name: str, value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a number or null")
    number = float(value)
    if not isfinite(number):
        raise ValueError(f"{name} must be finite or null")
    return number


def load_validation_limits(path: str | Path) -> ValidationLimits:
    config_path = Path(path)
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except OSError:
        raise
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid YAML in {config_path}: {exc}") from exc

    if raw is None:
        raw = {}
    root = _require_mapping("config", raw)
    _reject_unknown_keys("top-level", root, {"schema_version", "limits"})

    schema_version = root.get("schema_version", 1)
    if isinstance(schema_version, bool) or not isinstance(schema_version, int):
        raise TypeError("schema_version must be an integer")
    if schema_version != 1:
        raise ValueError(f"Unsupported schema_version: {schema_version!r}")

    limits_raw = _require_mapping("limits", root.get("limits", {}))
    _reject_unknown_keys("limits", limits_raw, {"cell_voltage", "temperature"})

    cell_raw = _require_mapping(
        "limits.cell_voltage",
        limits_raw.get("cell_voltage", {}),
    )
    _reject_unknown_keys(
        "limits.cell_voltage",
        cell_raw,
        {"min_v", "max_v", "max_delta_v"},
    )

    temp_raw = _require_mapping(
        "limits.temperature",
        limits_raw.get("temperature", {}),
    )
    _reject_unknown_keys(
        "limits.temperature",
        temp_raw,
        {"min_c", "max_c"},
    )

    defaults = ValidationLimits()
    return ValidationLimits(
        cell_min_v=_optional_number(
            "limits.cell_voltage.min_v",
            cell_raw.get("min_v", defaults.cell_min_v),
        ),
        cell_max_v=_optional_number(
            "limits.cell_voltage.max_v",
            cell_raw.get("max_v", defaults.cell_max_v),
        ),
        imbalance_max_v=_optional_number(
            "limits.cell_voltage.max_delta_v",
            cell_raw.get("max_delta_v", defaults.imbalance_max_v),
        ),
        temperature_min_c=_optional_number(
            "limits.temperature.min_c",
            temp_raw.get("min_c", defaults.temperature_min_c),
        ),
        temperature_max_c=_optional_number(
            "limits.temperature.max_c",
            temp_raw.get("max_c", defaults.temperature_max_c),
        ),
    )


def override_validation_limits(
    limits: ValidationLimits,
    *,
    cell_min_v: float | None = None,
    cell_max_v: float | None = None,
    imbalance_max_v: float | None = None,
    temperature_min_c: float | None = None,
    temperature_max_c: float | None = None,
) -> ValidationLimits:
    updates: dict[str, float] = {}
    for name, value in (
        ("cell_min_v", cell_min_v),
        ("cell_max_v", cell_max_v),
        ("imbalance_max_v", imbalance_max_v),
        ("temperature_min_c", temperature_min_c),
        ("temperature_max_c", temperature_max_c),
    ):
        if value is not None:
            updates[name] = value

    return replace(limits, **updates)
