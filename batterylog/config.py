import re
from dataclasses import dataclass, field, replace
from math import isfinite
from pathlib import Path
from typing import Any

import yaml

from batterylog.models import DataQualityMode


class _UniqueKeySafeLoader(yaml.SafeLoader):
    pass


def _construct_unique_mapping(
    loader: _UniqueKeySafeLoader,
    node: yaml.MappingNode,
    deep: bool = False,
) -> dict[Any, Any]:
    mapping: dict[Any, Any] = {}

    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"found duplicate key {key!r}",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)

    return mapping


_UniqueKeySafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def _validate_optional_number(name: str, value: float | None) -> None:
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a number or null")
    if not isfinite(value):
        raise ValueError(f"{name} must be finite or null")


@dataclass(frozen=True)
class ValidationLimits:
    cell_min_v: float | None = None
    cell_max_v: float | None = None
    imbalance_max_v: float | None = None
    temperature_min_c: float | None = None
    temperature_max_c: float | None = None

    def __post_init__(self) -> None:
        for name, value in (
            ("cell_min_v", self.cell_min_v),
            ("cell_max_v", self.cell_max_v),
            ("imbalance_max_v", self.imbalance_max_v),
            ("temperature_min_c", self.temperature_min_c),
            ("temperature_max_c", self.temperature_max_c),
        ):
            _validate_optional_number(name, value)

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


@dataclass(frozen=True)
class DataQualityConfig:
    mode: DataQualityMode = "strict"

    def __post_init__(self) -> None:
        if self.mode not in {"strict", "exclude_invalid_rows"}:
            raise ValueError("data quality mode must be 'strict' or 'exclude_invalid_rows'")


@dataclass(frozen=True)
class EventDetectionConfig:
    max_gap_s: float | None = None

    def __post_init__(self) -> None:
        _validate_optional_number("max_gap_s", self.max_gap_s)
        if self.max_gap_s is not None and self.max_gap_s < 0:
            raise ValueError("max_gap_s must be non-negative or null")


@dataclass(frozen=True)
class SignalPattern:
    pattern: str

    def __post_init__(self) -> None:
        if not isinstance(self.pattern, str):
            raise TypeError("signal pattern must be a string")
        if not self.pattern:
            raise ValueError("signal pattern must not be empty")

        try:
            compiled = re.compile(self.pattern)
        except re.error as exc:
            raise ValueError(f"Invalid signal regex: {exc}") from exc

        if "index" not in compiled.groupindex:
            raise ValueError("signal pattern must define a named 'index' capture group")


@dataclass(frozen=True)
class SignalMapping:
    timestamp: str
    cell_voltage: SignalPattern
    temperature: SignalPattern
    pack_current: str | None = None
    pack_voltage: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.timestamp, str):
            raise TypeError("signals.timestamp must be a string")
        if not self.timestamp:
            raise ValueError("signals.timestamp must not be empty")
        if not isinstance(self.cell_voltage, SignalPattern):
            raise TypeError("signals.cell_voltage must be a SignalPattern")
        if not isinstance(self.temperature, SignalPattern):
            raise TypeError("signals.temperature must be a SignalPattern")

        for name, value in (
            ("signals.pack_current", self.pack_current),
            ("signals.pack_voltage", self.pack_voltage),
        ):
            if value is not None and not isinstance(value, str):
                raise TypeError(f"{name} must be a string or null")
            if value == "":
                raise ValueError(f"{name} must not be empty")


@dataclass(frozen=True)
class ValidationConfig:
    limits: ValidationLimits = field(default_factory=ValidationLimits)
    event_detection: EventDetectionConfig = field(default_factory=EventDetectionConfig)
    signals: SignalMapping | None = None
    data_quality: DataQualityConfig = field(default_factory=DataQualityConfig, kw_only=True)

    def __post_init__(self) -> None:
        if not isinstance(self.limits, ValidationLimits):
            raise TypeError("limits must be a ValidationLimits instance")
        if not isinstance(self.event_detection, EventDetectionConfig):
            raise TypeError("event_detection must be an EventDetectionConfig instance")
        if not isinstance(self.data_quality, DataQualityConfig):
            raise TypeError("data_quality must be a DataQualityConfig instance")
        if self.signals is not None and not isinstance(self.signals, SignalMapping):
            raise TypeError("signals must be a SignalMapping instance or null")


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


def _required_string(name: str, value: Any) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    if not value:
        raise ValueError(f"{name} must not be empty")
    return value


def _optional_number(name: str, value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a number or null")
    number = float(value)
    if not isfinite(number):
        raise ValueError(f"{name} must be finite or null")
    return number


def _load_config_root_bytes(
    data: bytes,
    *,
    source_name: str,
) -> tuple[dict[str, Any], int]:
    try:
        text = data.decode("utf-8")
        raw = yaml.load(
            text,
            Loader=_UniqueKeySafeLoader,
        )
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid YAML in {source_name}: {exc}") from exc

    if raw is None:
        raw = {}
    root = _require_mapping("config", raw)
    schema_version = root.get("schema_version", 1)
    if isinstance(schema_version, bool) or not isinstance(schema_version, int):
        raise TypeError("schema_version must be an integer")
    if schema_version not in {1, 2, 3}:
        raise ValueError(f"Unsupported schema_version: {schema_version!r}")

    allowed = {"schema_version", "limits", "event_detection", "signals"}
    if schema_version >= 2:
        allowed.add("data_quality")
    _reject_unknown_keys("top-level", root, allowed)

    return root, schema_version


def _parse_limits(root: dict[str, Any]) -> ValidationLimits:
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


def _parse_data_quality(root: dict[str, Any], *, schema_version: int) -> DataQualityConfig:
    if schema_version == 1:
        return DataQualityConfig()

    raw = _require_mapping("data_quality", root.get("data_quality", {}))
    _reject_unknown_keys("data_quality", raw, {"mode"})
    mode = raw.get("mode", "strict")
    if not isinstance(mode, str):
        raise TypeError("data_quality.mode must be a string")
    return DataQualityConfig(mode=mode)  # type: ignore[arg-type]


def _parse_event_detection(root: dict[str, Any]) -> EventDetectionConfig:
    raw = _require_mapping(
        "event_detection",
        root.get("event_detection", {}),
    )
    _reject_unknown_keys("event_detection", raw, {"max_gap_s"})
    defaults = EventDetectionConfig()
    return EventDetectionConfig(
        max_gap_s=_optional_number(
            "event_detection.max_gap_s",
            raw.get("max_gap_s", defaults.max_gap_s),
        )
    )


def _parse_signal_pattern(
    name: str,
    raw_value: Any,
) -> SignalPattern:
    raw = _require_mapping(name, raw_value)
    _reject_unknown_keys(name, raw, {"pattern"})
    if "pattern" not in raw:
        raise ValueError(f"{name}.pattern is required")
    return SignalPattern(pattern=_required_string(f"{name}.pattern", raw["pattern"]))


def _parse_signals(
    root: dict[str, Any],
    *,
    schema_version: int,
) -> SignalMapping | None:
    if "signals" not in root:
        return None

    raw = _require_mapping("signals", root["signals"])
    allowed = {"timestamp", "cell_voltage", "temperature"}
    if schema_version >= 3:
        allowed.update({"pack_current", "pack_voltage"})
    _reject_unknown_keys("signals", raw, allowed)

    missing = sorted({"timestamp", "cell_voltage", "temperature"} - set(raw))
    if missing:
        joined = ", ".join(missing)
        raise ValueError(f"Missing signals key(s): {joined}")

    return SignalMapping(
        timestamp=_required_string("signals.timestamp", raw["timestamp"]),
        cell_voltage=_parse_signal_pattern(
            "signals.cell_voltage",
            raw["cell_voltage"],
        ),
        temperature=_parse_signal_pattern(
            "signals.temperature",
            raw["temperature"],
        ),
        pack_current=(
            _required_string("signals.pack_current", raw["pack_current"])
            if "pack_current" in raw
            else None
        ),
        pack_voltage=(
            _required_string("signals.pack_voltage", raw["pack_voltage"])
            if "pack_voltage" in raw
            else None
        ),
    )


def load_validation_config_bytes(
    data: bytes,
    *,
    source_name: str = "<memory>",
) -> ValidationConfig:
    root, schema_version = _load_config_root_bytes(data, source_name=source_name)
    return ValidationConfig(
        limits=_parse_limits(root),
        event_detection=_parse_event_detection(root),
        data_quality=_parse_data_quality(root, schema_version=schema_version),
        signals=_parse_signals(root, schema_version=schema_version),
    )


def load_validation_config(path: str | Path) -> ValidationConfig:
    config_path = Path(path)
    return load_validation_config_bytes(
        config_path.read_bytes(),
        source_name=str(config_path),
    )


def load_validation_limits(path: str | Path) -> ValidationLimits:
    return load_validation_config(path).limits


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


def override_event_detection(
    config: EventDetectionConfig,
    *,
    max_gap_s: float | None = None,
) -> EventDetectionConfig:
    if max_gap_s is None:
        return config
    return replace(config, max_gap_s=max_gap_s)
