from pathlib import Path

import pytest

from batterylog.config import (
    ValidationLimits,
    load_validation_limits,
    override_validation_limits,
)


def _write(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(content, encoding="utf-8")
    return path


def test_default_limits_preserve_existing_behavior() -> None:
    limits = ValidationLimits()

    assert limits.cell_min_v is None
    assert limits.cell_max_v is None
    assert limits.imbalance_max_v == pytest.approx(0.08)
    assert limits.temperature_min_c is None
    assert limits.temperature_max_c == pytest.approx(45.0)


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


@pytest.mark.parametrize(
    ("content", "exception_type", "message"),
    [
        ("schema_version: 2\n", ValueError, "Unsupported schema_version"),
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
