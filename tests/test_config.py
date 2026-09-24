from pathlib import Path

import pytest

from batterylog.config import (
    DataQualityConfig,
    EventDetectionConfig,
    SignalMapping,
    SignalPattern,
    ValidationConfig,
    ValidationLimits,
    load_validation_config,
    load_validation_config_bytes,
    load_validation_limits,
    override_event_detection,
    override_validation_limits,
)


def _write(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(content, encoding="utf-8")
    return path


def test_default_limits_enable_no_engineering_rules() -> None:
    limits = ValidationLimits()

    assert limits.cell_min_v is None
    assert limits.cell_max_v is None
    assert limits.imbalance_max_v is None
    assert limits.temperature_min_c is None
    assert limits.temperature_max_c is None
    assert limits.temperature_spread_max_c is None


def test_load_validation_limits_from_yaml(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
schema_version: 1
limits:
  cell_voltage:
    min_v: 2.8
    max_v: 4.2
    max_delta_v: 0.06
  temperature:
    min_c: -20
    max_c: 55
""",
    )

    limits = load_validation_limits(path)

    assert limits == ValidationLimits(
        cell_min_v=2.8,
        cell_max_v=4.2,
        imbalance_max_v=0.06,
        temperature_min_c=-20.0,
        temperature_max_c=55.0,
    )


def test_null_disables_individual_rules(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
limits:
  cell_voltage:
    max_delta_v: null
  temperature:
    max_c: null
""",
    )

    limits = load_validation_limits(path)

    assert limits.imbalance_max_v is None
    assert limits.temperature_max_c is None
    assert limits.temperature_spread_max_c is None


@pytest.mark.parametrize(
    ("content", "exception_type", "message"),
    [
        ("schema_version: 6\n", ValueError, "Unsupported schema_version"),
        ("limits: []\n", TypeError, "limits must be a mapping"),
        (
            "limits:\n  cell_voltage:\n    typo_v: 4.2\n",
            ValueError,
            "Unknown limits.cell_voltage key",
        ),
        (
            "limits:\n  temperature:\n    max_c: hot\n",
            TypeError,
            "limits.temperature.max_c must be a number",
        ),
        (
            "limits:\n  temperature:\n    max_c: .nan\n",
            ValueError,
            "must be finite",
        ),
    ],
)
def test_invalid_configs_are_rejected(
    tmp_path: Path,
    content: str,
    exception_type: type[Exception],
    message: str,
) -> None:
    with pytest.raises(exception_type, match=message):
        load_validation_limits(_write(tmp_path, content))


def test_inconsistent_ranges_are_rejected() -> None:
    with pytest.raises(ValueError, match="cell_min_v must be lower"):
        ValidationLimits(cell_min_v=4.2, cell_max_v=4.2)

    with pytest.raises(ValueError, match="temperature_min_c must be lower"):
        ValidationLimits(temperature_min_c=60.0, temperature_max_c=50.0)


def test_override_validation_limits_changes_only_explicit_values() -> None:
    base = ValidationLimits(
        cell_min_v=2.8,
        cell_max_v=4.2,
        imbalance_max_v=0.08,
        temperature_min_c=-20.0,
        temperature_max_c=55.0,
    )

    updated = override_validation_limits(
        base,
        cell_max_v=4.15,
        temperature_max_c=50.0,
    )

    assert updated.cell_min_v == base.cell_min_v
    assert updated.imbalance_max_v == base.imbalance_max_v
    assert updated.temperature_min_c == base.temperature_min_c
    assert updated.cell_max_v == pytest.approx(4.15)
    assert updated.temperature_max_c == pytest.approx(50.0)


def test_empty_config_uses_defaults(tmp_path: Path) -> None:
    assert load_validation_limits(_write(tmp_path, "")) == ValidationLimits()


def test_invalid_yaml_reports_parse_error(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Invalid YAML"):
        load_validation_limits(_write(tmp_path, "limits: [\n"))


@pytest.mark.parametrize("content", ["schema_version: true\n", "schema_version: 1.0\n"])
def test_schema_version_must_be_an_integer(tmp_path: Path, content: str) -> None:
    with pytest.raises(TypeError, match="schema_version must be an integer"):
        load_validation_limits(_write(tmp_path, content))


@pytest.mark.parametrize("value", ["4.2", True])
def test_validation_limits_reject_non_numeric_values(value: object) -> None:
    with pytest.raises(TypeError, match="must be a number or null"):
        ValidationLimits(cell_max_v=value)  # type: ignore[arg-type]


def test_duplicate_yaml_keys_are_rejected(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
limits:
  cell_voltage:
    max_v: 4.2
    max_v: 4.1
""",
    )

    with pytest.raises(ValueError, match="Invalid YAML"):
        load_validation_limits(path)


def test_config_schema_v1_defaults_to_strict_data_quality(tmp_path: Path) -> None:
    config = load_validation_config(_write(tmp_path, "schema_version: 1\n"))

    assert config.data_quality == DataQualityConfig(mode="strict")


def test_config_schema_v1_rejects_data_quality_block(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Unknown top-level key.*data_quality"):
        load_validation_config(
            _write(
                tmp_path,
                "schema_version: 1\ndata_quality:\n  mode: exclude_invalid_rows\n",
            )
        )


def test_config_schema_v2_parses_data_quality_mode(tmp_path: Path) -> None:
    config = load_validation_config(
        _write(
            tmp_path,
            "schema_version: 2\ndata_quality:\n  mode: exclude_invalid_rows\n",
        )
    )

    assert config.data_quality == DataQualityConfig(mode="exclude_invalid_rows")


def test_config_schema_v2_defaults_data_quality_to_strict(tmp_path: Path) -> None:
    config = load_validation_config(_write(tmp_path, "schema_version: 2\n"))

    assert config.data_quality == DataQualityConfig(mode="strict")


@pytest.mark.parametrize(
    ("content", "exception_type", "message"),
    [
        (
            "schema_version: 2\ndata_quality: []\n",
            TypeError,
            "data_quality must be a mapping",
        ),
        (
            "schema_version: 2\ndata_quality:\n  unknown: true\n",
            ValueError,
            "Unknown data_quality key",
        ),
        (
            "schema_version: 2\ndata_quality:\n  mode: 1\n",
            TypeError,
            "data_quality.mode must be a string",
        ),
        (
            "schema_version: 2\ndata_quality:\n  mode: interpolate\n",
            ValueError,
            "data quality mode must be 'strict' or 'exclude_invalid_rows'",
        ),
    ],
)
def test_invalid_data_quality_config_is_rejected(
    tmp_path: Path,
    content: str,
    exception_type: type[Exception],
    message: str,
) -> None:
    with pytest.raises(exception_type, match=message):
        load_validation_config(_write(tmp_path, content))


def test_data_quality_config_rejects_invalid_mode_directly() -> None:
    with pytest.raises(ValueError, match="data quality mode"):
        DataQualityConfig(mode="interpolate")  # type: ignore[arg-type]


def test_load_validation_config_includes_event_detection(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
schema_version: 1
limits:
  cell_voltage:
    max_delta_v: 0.08
event_detection:
  max_gap_s: 0.5
""",
    )

    config = load_validation_config(path)

    assert config == ValidationConfig(
        limits=ValidationLimits(imbalance_max_v=0.08),
        event_detection=EventDetectionConfig(max_gap_s=0.5),
    )


def test_load_validation_limits_remains_backward_compatible_with_event_config(
    tmp_path: Path,
) -> None:
    path = _write(
        tmp_path,
        """
limits:
  temperature:
    max_c: 50
event_detection:
  max_gap_s: 1.0
""",
    )

    limits = load_validation_limits(path)

    assert limits == ValidationLimits(temperature_max_c=50.0)


@pytest.mark.parametrize(
    ("content", "exception_type", "message"),
    [
        (
            "event_detection: []\n",
            TypeError,
            "event_detection must be a mapping",
        ),
        (
            "event_detection:\n  unknown: 1\n",
            ValueError,
            "Unknown event_detection key",
        ),
        (
            "event_detection:\n  max_gap_s: fast\n",
            TypeError,
            "event_detection.max_gap_s must be a number",
        ),
        (
            "event_detection:\n  max_gap_s: -0.1\n",
            ValueError,
            "max_gap_s must be non-negative",
        ),
        (
            "event_detection:\n  max_gap_s: .inf\n",
            ValueError,
            "must be finite",
        ),
    ],
)
def test_invalid_event_detection_config_is_rejected(
    tmp_path: Path,
    content: str,
    exception_type: type[Exception],
    message: str,
) -> None:
    with pytest.raises(exception_type, match=message):
        load_validation_config(_write(tmp_path, content))


@pytest.mark.parametrize("value", ["0.5", True])
def test_event_detection_config_rejects_non_numeric_values(value: object) -> None:
    with pytest.raises(TypeError, match="must be a number or null"):
        EventDetectionConfig(max_gap_s=value)  # type: ignore[arg-type]


def test_override_event_detection_changes_only_explicit_value() -> None:
    base = EventDetectionConfig(max_gap_s=1.0)

    unchanged = override_event_detection(base)
    updated = override_event_detection(base, max_gap_s=0.25)

    assert unchanged is base
    assert updated == EventDetectionConfig(max_gap_s=0.25)


def test_load_validation_config_parses_explicit_signal_mapping(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        r"""
signals:
  timestamp: Time_s
  cell_voltage:
    pattern: 'BMS_CellVoltage_(?P<index>\d+)'
  temperature:
    pattern: 'T_Module_(?P<index>\d+)'
""",
    )

    config = load_validation_config(path)

    assert config.signals == SignalMapping(
        timestamp="Time_s",
        cell_voltage=SignalPattern(r"BMS_CellVoltage_(?P<index>\d+)"),
        temperature=SignalPattern(r"T_Module_(?P<index>\d+)"),
    )


def test_config_schema_v3_parses_optional_pack_signal_sources(tmp_path: Path) -> None:
    config = load_validation_config(
        _write(
            tmp_path,
            r"""
schema_version: 3
signals:
  timestamp: Time_s
  pack_current: PackCurrent
  pack_voltage: PackVoltage
  cell_voltage:
    pattern: 'BMS_CellVoltage_(?P<index>\d+)'
  temperature:
    pattern: 'T_Module_(?P<index>\d+)'
""",
        )
    )

    assert config.signals == SignalMapping(
        timestamp="Time_s",
        cell_voltage=SignalPattern(r"BMS_CellVoltage_(?P<index>\d+)"),
        temperature=SignalPattern(r"T_Module_(?P<index>\d+)"),
        pack_current="PackCurrent",
        pack_voltage="PackVoltage",
    )


def test_config_schema_v2_rejects_pack_signal_sources(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Unknown signals key.*pack_current"):
        load_validation_config(
            _write(
                tmp_path,
                r"""
schema_version: 2
signals:
  timestamp: Time_s
  pack_current: PackCurrent
  cell_voltage:
    pattern: 'BMS_CellVoltage_(?P<index>\d+)'
  temperature:
    pattern: 'T_Module_(?P<index>\d+)'
""",
            )
        )


def test_load_validation_limits_accepts_config_with_signal_mapping(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        r"""
limits:
  temperature:
    max_c: 50
signals:
  timestamp: Time_s
  cell_voltage:
    pattern: 'BMS_CellVoltage_(?P<index>\d+)'
  temperature:
    pattern: 'T_Module_(?P<index>\d+)'
""",
    )

    limits = load_validation_limits(path)

    assert limits == ValidationLimits(temperature_max_c=50.0)


@pytest.mark.parametrize(
    ("content", "exception_type", "message"),
    [
        (
            "signals: []\n",
            TypeError,
            "signals must be a mapping",
        ),
        (
            "signals:\n  timestamp: Time_s\n",
            ValueError,
            "Missing signals key",
        ),
        (
            (
                "signals:\n"
                "  timestamp: Time_s\n"
                "  cell_voltage:\n"
                "    pattern: 'Cell_(?P<index>\\d+)'\n"
                "  temperature:\n"
                "    pattern: 'Temp_(?P<index>\\d+)'\n"
                "  unexpected: true\n"
            ),
            ValueError,
            "Unknown signals key",
        ),
        (
            (
                "signals:\n"
                "  timestamp: Time_s\n"
                "  cell_voltage:\n"
                "    pattern: 'Cell_(\\d+)'\n"
                "  temperature:\n"
                "    pattern: 'Temp_(?P<index>\\d+)'\n"
            ),
            ValueError,
            "named 'index' capture group",
        ),
        (
            (
                "signals:\n"
                "  timestamp: Time_s\n"
                "  cell_voltage:\n"
                "    pattern: '[invalid'\n"
                "  temperature:\n"
                "    pattern: 'Temp_(?P<index>\\d+)'\n"
            ),
            ValueError,
            "Invalid signal regex",
        ),
        (
            (
                "signals:\n"
                "  timestamp: ''\n"
                "  cell_voltage:\n"
                "    pattern: 'Cell_(?P<index>\\d+)'\n"
                "  temperature:\n"
                "    pattern: 'Temp_(?P<index>\\d+)'\n"
            ),
            ValueError,
            "signals.timestamp must not be empty",
        ),
        (
            (
                "signals:\n"
                "  timestamp: Time_s\n"
                "  cell_voltage:\n"
                "    pattern: ''\n"
                "  temperature:\n"
                "    pattern: 'Temp_(?P<index>\\d+)'\n"
            ),
            ValueError,
            "signals.cell_voltage.pattern must not be empty",
        ),
    ],
)
def test_invalid_signal_mapping_config_is_rejected(
    tmp_path: Path,
    content: str,
    exception_type: type[Exception],
    message: str,
) -> None:
    with pytest.raises(exception_type, match=message):
        load_validation_config(_write(tmp_path, content))


@pytest.mark.parametrize("value", [123, True])
def test_signal_pattern_requires_a_string(value: object) -> None:
    with pytest.raises(TypeError, match="signal pattern must be a string"):
        SignalPattern(value)  # type: ignore[arg-type]


def test_signal_pattern_rejects_empty_string_directly() -> None:
    with pytest.raises(ValueError, match="signal pattern must not be empty"):
        SignalPattern("")


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        (
            {
                "timestamp": 123,
                "cell_voltage": SignalPattern(r"Cell_(?P<index>\d+)"),
                "temperature": SignalPattern(r"Temp_(?P<index>\d+)"),
            },
            "signals.timestamp must be a string",
        ),
        (
            {
                "timestamp": "",
                "cell_voltage": SignalPattern(r"Cell_(?P<index>\d+)"),
                "temperature": SignalPattern(r"Temp_(?P<index>\d+)"),
            },
            "signals.timestamp must not be empty",
        ),
        (
            {
                "timestamp": "Time_s",
                "cell_voltage": "bad",
                "temperature": SignalPattern(r"Temp_(?P<index>\d+)"),
            },
            "signals.cell_voltage must be a SignalPattern",
        ),
        (
            {
                "timestamp": "Time_s",
                "cell_voltage": SignalPattern(r"Cell_(?P<index>\d+)"),
                "temperature": "bad",
            },
            "signals.temperature must be a SignalPattern",
        ),
        (
            {
                "timestamp": "Time_s",
                "cell_voltage": SignalPattern(r"Cell_(?P<index>\d+)"),
                "temperature": SignalPattern(r"Temp_(?P<index>\d+)"),
                "pack_current": 123,
            },
            "signals.pack_current must be a string or null",
        ),
        (
            {
                "timestamp": "Time_s",
                "cell_voltage": SignalPattern(r"Cell_(?P<index>\d+)"),
                "temperature": SignalPattern(r"Temp_(?P<index>\d+)"),
                "pack_voltage": "",
            },
            "signals.pack_voltage must not be empty",
        ),
    ],
)
def test_signal_mapping_validates_public_constructor(
    kwargs: dict[str, object],
    message: str,
) -> None:
    with pytest.raises((TypeError, ValueError), match=message):
        SignalMapping(**kwargs)  # type: ignore[arg-type]


def test_signal_mapping_pattern_field_is_required(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        r"""
signals:
  timestamp: Time_s
  cell_voltage: {}
  temperature:
    pattern: 'Temp_(?P<index>\d+)'
""",
    )

    with pytest.raises(ValueError, match="signals.cell_voltage.pattern is required"):
        load_validation_config(path)


def test_signal_mapping_yaml_fields_must_be_strings(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        r"""
signals:
  timestamp: 123
  cell_voltage:
    pattern: 'Cell_(?P<index>\d+)'
  temperature:
    pattern: 'Temp_(?P<index>\d+)'
""",
    )

    with pytest.raises(TypeError, match="signals.timestamp must be a string"):
        load_validation_config(path)


def test_missing_config_file_propagates_os_error(tmp_path: Path) -> None:
    with pytest.raises(OSError):
        load_validation_config(tmp_path / "missing.yaml")


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        (
            {"limits": {}},
            "limits must be a ValidationLimits instance",
        ),
        (
            {"event_detection": {}},
            "event_detection must be an EventDetectionConfig instance",
        ),
        (
            {"signals": "bad"},
            "signals must be a SignalMapping instance or null",
        ),
    ],
)
def test_validation_config_rejects_invalid_component_types(
    kwargs: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(TypeError, match=message):
        ValidationConfig(**kwargs)  # type: ignore[arg-type]


def test_validation_config_preserves_legacy_positional_signals_argument() -> None:
    mapping = SignalMapping(
        timestamp="Time_s",
        cell_voltage=SignalPattern(r"Cell_(?P<index>\d+)"),
        temperature=SignalPattern(r"Temp_(?P<index>\d+)"),
    )

    with_none = ValidationConfig(ValidationLimits(), EventDetectionConfig(), None)
    with_mapping = ValidationConfig(
        ValidationLimits(),
        EventDetectionConfig(),
        mapping,
    )

    assert with_none.signals is None
    assert with_none.data_quality == DataQualityConfig(mode="strict")
    assert with_mapping.signals is mapping


def test_validation_config_accepts_data_quality_only_by_keyword() -> None:
    quality = DataQualityConfig(mode="exclude_invalid_rows")

    config = ValidationConfig(data_quality=quality)

    assert config.data_quality is quality
    with pytest.raises(TypeError):
        ValidationConfig(
            ValidationLimits(),
            EventDetectionConfig(),
            None,
            quality,  # type: ignore[misc]
        )


def test_validation_config_bytes_match_path_loader(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "limits:\n  cell_voltage:\n    max_v: 4.2\nevent_detection:\n  max_gap_s: 0.5\n",
    )

    from_path = load_validation_config(path)
    from_bytes = load_validation_config_bytes(
        path.read_bytes(),
        source_name=str(path),
    )

    assert from_bytes == from_path


def test_config_schema_v4_parses_pack_current_rule_contract(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "schema_version: 4\n"
        "limits:\n"
        "  pack_current:\n"
        "    charge_max_a: 60\n"
        "    discharge_max_a: 120\n"
        "    positive_direction: discharge\n",
    )

    config = load_validation_config(path)

    assert config.limits.pack_charge_max_a == pytest.approx(60.0)
    assert config.limits.pack_discharge_max_a == pytest.approx(120.0)
    assert config.limits.pack_current_positive_direction == "discharge"


def test_config_schema_v3_rejects_pack_current_limits(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "schema_version: 3\n"
        "limits:\n"
        "  pack_current:\n"
        "    charge_max_a: 60\n"
        "    positive_direction: discharge\n",
    )

    with pytest.raises(ValueError, match="Unknown limits key"):
        load_validation_config(path)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"pack_charge_max_a": -1.0}, "non-negative"),
        ({"pack_discharge_max_a": -1.0}, "non-negative"),
        (
            {"pack_charge_max_a": 60.0},
            "pack_current_positive_direction is required",
        ),
        (
            {"pack_current_positive_direction": "forward"},
            "must be 'charge', 'discharge', or null",
        ),
    ],
)
def test_pack_current_limit_contract_rejects_ambiguous_values(
    kwargs: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        ValidationLimits(**kwargs)  # type: ignore[arg-type]


def test_config_schema_v5_parses_temperature_spread_limit(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "schema_version: 5\nlimits:\n  temperature:\n    max_spread_c: 12\n",
    )
    config = load_validation_config(path)
    assert config.limits.temperature_spread_max_c == pytest.approx(12.0)


def test_config_schema_v4_rejects_temperature_spread_limit(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "schema_version: 4\nlimits:\n  temperature:\n    max_spread_c: 12\n",
    )
    with pytest.raises(ValueError, match="Unknown limits.temperature key"):
        load_validation_config(path)


def test_temperature_spread_limit_must_be_non_negative() -> None:
    with pytest.raises(ValueError, match="temperature_spread_max_c must be non-negative"):
        ValidationLimits(temperature_spread_max_c=-0.1)
