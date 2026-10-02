"""Explicit, finite set of source units for measurement preparation."""

from dataclasses import dataclass


@dataclass(frozen=True)
class SourceUnits:
    timestamp: str
    cell_voltage: str
    temperature: str
    pack_current: str | None = None
    pack_voltage: str | None = None

    def __post_init__(self) -> None:
        for role, allowed in (
            ("timestamp", {"s", "ms", "us"}),
            ("cell_voltage", {"V", "mV"}),
            ("temperature", {"degC", "K"}),
            ("pack_current", {None, "A", "mA"}),
            ("pack_voltage", {None, "V", "mV"}),
        ):
            unit = getattr(self, role)
            if unit is not None and not isinstance(unit, str):
                raise TypeError(f"{role} unit must be a string")
            if unit not in allowed:
                raise ValueError(f"Unsupported {role} source unit: {unit!r}")

    def for_mdf_kind(self, kind: str) -> str:
        role = {
            "cell-voltage": "cell_voltage",
            "temperature": "temperature",
            "pack-current": "pack_current",
            "pack-voltage": "pack_voltage",
        }[kind]
        unit = getattr(self, role)
        if unit is None:
            raise ValueError(f"An explicit {role} unit is required for a selected channel")
        return str(unit)


def unit_transform(unit: str) -> tuple[str, float, float]:
    """Return target unit, divisor and offset: target = source / divisor + offset."""
    return {
        "s": ("s", 1.0, 0.0),
        "ms": ("s", 1000.0, 0.0),
        "us": ("s", 1000000.0, 0.0),
        "V": ("V", 1.0, 0.0),
        "mV": ("V", 1000.0, 0.0),
        "A": ("A", 1.0, 0.0),
        "mA": ("A", 1000.0, 0.0),
        "degC": ("degC", 1.0, 0.0),
        "K": ("degC", 1.0, -273.15),
    }[unit]
