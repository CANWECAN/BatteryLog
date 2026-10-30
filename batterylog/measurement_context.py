"""Strict, immutable declarations of measurement context; no physical verification."""

import json
import math
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from importlib.resources import files
from pathlib import Path
from typing import Literal

from jsonschema import Draft202012Validator, ValidationError

MAX_CONTEXT_BYTES = 1_048_576

TopologyKind = Literal["unknown", "series", "parallel", "series_parallel"]
ChannelRole = Literal[
    "cell_voltage",
    "branch_voltage",
    "pack_voltage",
    "branch_current",
    "pack_current",
    "temperature",
]
AcquisitionMode = Literal["unknown", "simultaneous", "asynchronous", "previous_sample_hold"]
OperatingState = Literal["unknown", "rest", "charge", "discharge", "mixed"]

_ROLE_UNITS = {
    "cell_voltage": {"V", "mV"},
    "branch_voltage": {"V", "mV"},
    "pack_voltage": {"V", "mV"},
    "branch_current": {"A", "mA"},
    "pack_current": {"A", "mA"},
    "temperature": {"degC", "K"},
}


@dataclass(frozen=True)
class DeclaredTopology:
    kind: TopologyKind
    branch_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class DeclaredChannel:
    source: str
    role: ChannelRole
    unit: str | None = None
    branch_id: str | None = None
    cell_id: str | None = None
    time_basis: str | None = None
    acquisition: AcquisitionMode | None = None


@dataclass(frozen=True)
class DeclaredSOC:
    value_percent: float | None = None
    source: str | None = None


@dataclass(frozen=True)
class MeasurementContext:
    """A validated declaration, never evidence of calibrated/aligned measurements.

    Missing values stay None/empty. Subvalues are validated when assembled here.
    The JSON export contains declarations only; verification flags are derived
    attributes which cannot be supplied by JSON or constructor arguments.
    """

    topology: DeclaredTopology | None = None
    channels: tuple[DeclaredChannel, ...] = ()
    chemistry: str | None = None
    soc: DeclaredSOC | None = None
    operating_state: OperatingState | None = None
    measurement_context_schema_version: Literal[1] = field(default=1, init=False)
    evidence_level: Literal["DECLARED"] = field(default="DECLARED", init=False)
    measurement_properties_verified: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        if type(self.channels) is not tuple or any(
            type(channel) is not DeclaredChannel for channel in self.channels
        ):
            raise TypeError("channels must be a tuple of DeclaredChannel values")
        if self.topology is not None and (
            type(self.topology) is not DeclaredTopology
            or type(self.topology.branch_ids) is not tuple
        ):
            raise TypeError("topology must be DeclaredTopology with tuple branch_ids or None")
        if self.soc is not None and type(self.soc) is not DeclaredSOC:
            raise TypeError("soc must be DeclaredSOC or None")
        _validate_payload(self.to_dict())

    def to_dict(self) -> dict:
        """Return detached, JSON-compatible declarations, with no inferred fields."""
        return {
            "measurement_context_schema_version": self.measurement_context_schema_version,
            "topology": (
                {"kind": self.topology.kind, "branch_ids": list(self.topology.branch_ids)}
                if self.topology is not None
                else None
            ),
            "channels": [asdict(channel) for channel in self.channels],
            "chemistry": self.chemistry,
            "soc": asdict(self.soc) if self.soc is not None else None,
            "operating_state": self.operating_state,
        }


@lru_cache(maxsize=1)
def _validator() -> Draft202012Validator:
    schema = json.loads(
        files("batterylog").joinpath("schema/measurement-context-v1.json").read_text("utf-8")
    )
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def _check_json_values(value: object, depth: int = 0) -> None:
    if depth > 16:
        raise ValueError("Measurement context nesting exceeds 16 levels")
    if isinstance(value, str):
        if any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError("Measurement context labels must not contain control characters")
        try:
            value.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise ValueError("Measurement context labels must be valid Unicode") from exc
    elif isinstance(value, float) and not math.isfinite(value):
        raise ValueError("Measurement context numbers must be finite")
    elif isinstance(value, dict):
        for key, item in value.items():
            _check_json_values(key, depth + 1)
            _check_json_values(item, depth + 1)
    elif isinstance(value, list):
        for item in value:
            _check_json_values(item, depth + 1)


def _validate_payload(value: object) -> dict:
    if type(value) is not dict:
        raise ValueError("Measurement context must be a JSON object")
    if (
        type(value.get("measurement_context_schema_version")) is not int
        or value["measurement_context_schema_version"] != 1
    ):
        raise ValueError("measurement_context_schema_version must be integer 1")
    _check_json_values(value)
    soc = value.get("soc")
    if (
        type(soc) is dict
        and soc.get("value_percent") is not None
        and type(soc["value_percent"]) not in (int, float)
    ):
        raise ValueError("soc.value_percent must be a JSON number")
    try:
        _validator().validate(value)
    except ValidationError as exc:
        location = ".".join(str(part) for part in exc.absolute_path) or "root"
        raise ValueError(f"Measurement context {location}: {exc.message[:300]}") from None

    topology = value.get("topology")
    branches = set(topology.get("branch_ids", [])) if topology is not None else set()
    if topology is not None and topology["kind"] == "series" and branches:
        raise ValueError("Series topology cannot declare parallel branch_ids")
    sources: set[str] = set()
    physical_roles: set[tuple] = set()
    for channel in value.get("channels", []):
        source, role = channel["source"], channel["role"]
        if source in sources:
            raise ValueError(f"Duplicate source channel: {source}")
        sources.add(source)
        unit, branch, cell = channel.get("unit"), channel.get("branch_id"), channel.get("cell_id")
        if unit is not None and unit not in _ROLE_UNITS[role]:
            raise ValueError(f"Channel {source}: unit {unit!r} is incompatible with role {role}")
        if branch is not None:
            if branch not in branches:
                raise ValueError(f"Channel {source}: undeclared branch_id {branch!r}")
            if role in {"pack_voltage", "pack_current"}:
                raise ValueError(f"Channel {source}: role {role} cannot carry branch_id")
        if cell is not None and role not in {"cell_voltage", "temperature"}:
            raise ValueError(f"Channel {source}: cell_id requires cell_voltage or temperature role")
        identity = (
            (role, branch, cell)
            if role in {"cell_voltage", "temperature"} and cell is not None
            else (role, branch)
            if role in {"branch_current", "branch_voltage"} and branch is not None
            else None
        )
        if identity is not None:
            if identity in physical_roles:
                raise ValueError(f"Ambiguous physical channel mapping: {identity}")
            physical_roles.add(identity)
    return value


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    value: dict = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"Duplicate measurement context JSON key: {key}")
        value[key] = item
    return value


def _reject_constant(value: str) -> None:
    raise ValueError(f"Non-finite JSON constant in measurement context: {value}")


def load_measurement_context_bytes(data: bytes) -> MeasurementContext:
    """Parse at most 1 MiB of strict UTF-8 JSON without inferring missing context."""
    if type(data) is not bytes:
        raise TypeError("Measurement context input must be bytes")
    if len(data) > MAX_CONTEXT_BYTES:
        raise ValueError("Measurement context exceeds 1 MiB")
    try:
        raw = json.loads(
            data.decode("utf-8-sig"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError(
            "Measurement context must be valid UTF-8 JSON with bounded nesting"
        ) from exc
    raw = _validate_payload(raw)
    topology, soc = raw.get("topology"), raw.get("soc")
    return MeasurementContext(
        topology=(
            DeclaredTopology(topology["kind"], tuple(topology.get("branch_ids", [])))
            if topology is not None
            else None
        ),
        channels=tuple(DeclaredChannel(**channel) for channel in raw.get("channels", [])),
        chemistry=raw.get("chemistry"),
        soc=DeclaredSOC(**soc) if soc is not None else None,
        operating_state=raw.get("operating_state"),
    )


def load_measurement_context(path: str | Path) -> MeasurementContext:
    """Read a declaration only; source snapshots/provenance belong to the caller."""
    with Path(path).open("rb") as handle:
        return load_measurement_context_bytes(handle.read(MAX_CONTEXT_BYTES + 1))
