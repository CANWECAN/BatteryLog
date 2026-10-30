"""Review declared parallel-branch instrumentation without diagnosing a fault."""

from dataclasses import dataclass, field
from typing import Literal, TypedDict

from .measurement_context import MeasurementContext, TopologyKind

BranchReason = Literal[
    "MEASUREMENT_CONTEXT_NOT_SUPPLIED",
    "PARALLEL_TOPOLOGY_NOT_DECLARED",
    "NON_PARALLEL_TOPOLOGY_DECLARED",
    "BRANCH_IDENTITIES_NOT_DECLARED",
    "ELECTRICAL_CHANNELS_NOT_DECLARED",
    "BRANCH_ASSIGNMENT_NOT_DECLARED",
    "BRANCH_CURRENT_NOT_DECLARED",
    "BRANCH_TERMINAL_VOLTAGE_NOT_DECLARED",
    "CHANNEL_UNIT_NOT_DECLARED",
    "CHANNEL_TIME_BASIS_NOT_DECLARED",
    "CHANNEL_ACQUISITION_NOT_DECLARED",
    "ASYNCHRONOUS_ACQUISITION_DECLARED",
    "PREVIOUS_SAMPLE_HOLD_DECLARED",
    "MULTIPLE_TIME_BASES_DECLARED",
    "COMMON_TERMINAL_DATA_PERMUTATION_AMBIGUITY",
    "BRANCH_INVENTORY_NOT_VERIFIED",
    "MEASUREMENT_PROPERTIES_NOT_VERIFIED",
    "BRANCH_LOCALIZATION_MODEL_NOT_AVAILABLE",
]


class BranchIssue(TypedDict):
    code: BranchReason
    field: str
    branch_id: str | None
    source: str | None
    detail: str


class BranchInventory(TypedDict):
    branch_id: str
    current_sources: list[str]
    terminal_voltage_sources: list[str]
    cell_voltage_sources: list[str]


class ParallelBranchPayload(TypedDict):
    parallel_branch_context_schema_version: Literal[1]
    scope: Literal["declared_measurement_context_only"]
    claim: Literal["PARALLEL_BRANCH_FAULT_LOCATION"]
    status: Literal["NOT_EVALUATED"]
    diagnostic_claim: Literal[False]
    context_supplied: bool
    topology_kind: TopologyKind | None
    declared_branch_ids: list[str]
    declared_time_bases: list[str]
    branch_inventory_verified: Literal[False]
    measurement_properties_verified: Literal[False]
    localization_method_available: Literal[False]
    branches: list[BranchInventory]
    reason_codes: list[BranchReason]
    issues: list[BranchIssue]


_ELECTRICAL = {"pack_voltage", "pack_current", "branch_voltage", "branch_current", "cell_voltage"}
_BRANCH_ROLES = {"branch_voltage", "branch_current", "cell_voltage"}


@dataclass(frozen=True)
class ParallelBranchAssessment:
    """Inventory declarations and missing fields, never certify identifiability.

    Current/terminal-voltage gaps are descriptive inventory notes, not a claim
    that both measurements are universally necessary or sufficient. This object
    does not inspect source samples, prove acquisition or select a faulty branch.
    Every export is a detached copy with deterministic ordering.
    """

    context: MeasurementContext | None = None
    status: Literal["NOT_EVALUATED"] = field(default="NOT_EVALUATED", init=False)
    diagnostic_claim: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        if self.context is not None and type(self.context) is not MeasurementContext:
            raise TypeError("context must be a validated MeasurementContext or None")

    def to_dict(self) -> ParallelBranchPayload:
        context = self.context
        topology = context.topology if context is not None else None
        branch_ids = sorted(topology.branch_ids) if topology is not None else []
        issues: list[BranchIssue] = []
        branches: dict[str, BranchInventory] = {
            branch: {
                "branch_id": branch,
                "current_sources": [],
                "terminal_voltage_sources": [],
                "cell_voltage_sources": [],
            }
            for branch in branch_ids
        }
        time_bases: set[str] = set()

        def add(
            code: BranchReason,
            location: str,
            detail: str,
            branch: str | None = None,
            source: str | None = None,
        ) -> None:
            issues.append(
                {
                    "code": code,
                    "field": location,
                    "branch_id": branch,
                    "source": source,
                    "detail": detail,
                }
            )

        add(
            "BRANCH_LOCALIZATION_MODEL_NOT_AVAILABLE",
            "localization_method",
            "No validated branch-localization method is implemented by this review.",
        )
        add(
            "MEASUREMENT_PROPERTIES_NOT_VERIFIED",
            "measurement_properties",
            "This declaration review has not verified source existence, units, calibration, acquisition or alignment.",
        )
        add(
            "BRANCH_INVENTORY_NOT_VERIFIED",
            "topology.branch_ids",
            "Declared branch labels are not proof of a complete physical branch inventory.",
        )

        if context is None:
            add(
                "MEASUREMENT_CONTEXT_NOT_SUPPLIED",
                "context",
                "No measurement context was supplied.",
            )
        elif topology is not None and topology.kind == "series":
            add(
                "NON_PARALLEL_TOPOLOGY_DECLARED",
                "topology.kind",
                "The declared topology is series; this parallel-branch review does not apply.",
            )
        else:
            if topology is None or topology.kind == "unknown":
                add(
                    "PARALLEL_TOPOLOGY_NOT_DECLARED",
                    "topology.kind",
                    "No explicit parallel or series-parallel topology kind is declared.",
                )
            if not branch_ids:
                add(
                    "BRANCH_IDENTITIES_NOT_DECLARED",
                    "topology.branch_ids",
                    "No physical parallel-branch labels are declared; none are inferred from channel names.",
                )
            electrical = [channel for channel in context.channels if channel.role in _ELECTRICAL]
            if not electrical:
                add(
                    "ELECTRICAL_CHANNELS_NOT_DECLARED",
                    "channels",
                    "No electrical source channels are declared in this context.",
                )
            roles = {channel.role for channel in electrical}
            if (
                topology is not None
                and topology.kind in {"parallel", "series_parallel"}
                and {"pack_voltage", "pack_current"} <= roles
                and roles <= {"pack_voltage", "pack_current"}
                and not any(channel.branch_id is not None for channel in context.channels)
            ):
                add(
                    "COMMON_TERMINAL_DATA_PERMUTATION_AMBIGUITY",
                    "channels",
                    "For ideal parallel connections, common voltage and total current are invariant to hidden branch-identity permutations; these declarations do not localize a branch.",
                )

            for channel in electrical:
                branch, source = channel.branch_id, channel.source
                if channel.role in _BRANCH_ROLES:
                    if branch is None:
                        add(
                            "BRANCH_ASSIGNMENT_NOT_DECLARED",
                            "channels.branch_id",
                            "This electrical source has no explicit physical branch assignment.",
                            source=source,
                        )
                    else:
                        inventory = branches[branch]
                        if channel.role == "branch_current":
                            inventory["current_sources"].append(source)
                        elif channel.role == "branch_voltage":
                            inventory["terminal_voltage_sources"].append(source)
                        else:
                            inventory["cell_voltage_sources"].append(source)
                if channel.unit is None:
                    add(
                        "CHANNEL_UNIT_NOT_DECLARED",
                        "channels.unit",
                        "No source unit is declared.",
                        branch,
                        source,
                    )
                if channel.time_basis is None:
                    add(
                        "CHANNEL_TIME_BASIS_NOT_DECLARED",
                        "channels.time_basis",
                        "No time-basis label is declared.",
                        branch,
                        source,
                    )
                else:
                    time_bases.add(channel.time_basis)
                if channel.acquisition in {None, "unknown"}:
                    add(
                        "CHANNEL_ACQUISITION_NOT_DECLARED",
                        "channels.acquisition",
                        "The acquisition mode is unspecified.",
                        branch,
                        source,
                    )
                elif channel.acquisition == "asynchronous":
                    add(
                        "ASYNCHRONOUS_ACQUISITION_DECLARED",
                        "channels.acquisition",
                        "Asynchronous acquisition is declared; no alignment has been verified.",
                        branch,
                        source,
                    )
                elif channel.acquisition == "previous_sample_hold":
                    add(
                        "PREVIOUS_SAMPLE_HOLD_DECLARED",
                        "channels.acquisition",
                        "Previous-sample holding is declared; held rows do not prove new acquisitions.",
                        branch,
                        source,
                    )

            if len(time_bases) > 1:
                add(
                    "MULTIPLE_TIME_BASES_DECLARED",
                    "channels.time_basis",
                    "Multiple electrical-channel time-basis labels are declared; their synchronization or offset relationships are unverified.",
                )
            for branch, inventory in branches.items():
                if not inventory["current_sources"]:
                    add(
                        "BRANCH_CURRENT_NOT_DECLARED",
                        "channels.branch_current",
                        "No branch-current source is assigned here. This inventory note is not a universal instrumentation requirement.",
                        branch,
                    )
                if not inventory["terminal_voltage_sources"]:
                    add(
                        "BRANCH_TERMINAL_VOLTAGE_NOT_DECLARED",
                        "channels.branch_voltage",
                        "No branch-terminal-voltage source is assigned here; cell-voltage sources are not substituted. This is an inventory note, not a universal requirement.",
                        branch,
                    )
                inventory["current_sources"].sort()
                inventory["terminal_voltage_sources"].sort()
                inventory["cell_voltage_sources"].sort()

        issues.sort(
            key=lambda issue: (
                issue["code"],
                issue["branch_id"] or "",
                issue["source"] or "",
                issue["field"],
            )
        )
        return {
            "parallel_branch_context_schema_version": 1,
            "scope": "declared_measurement_context_only",
            "claim": "PARALLEL_BRANCH_FAULT_LOCATION",
            "status": self.status,
            "diagnostic_claim": self.diagnostic_claim,
            "context_supplied": context is not None,
            "topology_kind": topology.kind if topology is not None else None,
            "declared_branch_ids": branch_ids,
            "declared_time_bases": sorted(time_bases),
            "branch_inventory_verified": False,
            "measurement_properties_verified": False,
            "localization_method_available": False,
            "branches": list(branches.values()),
            "reason_codes": sorted({issue["code"] for issue in issues}),
            "issues": issues,
        }
