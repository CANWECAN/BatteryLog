# Copyright (c) 2026 Berk Ozfiliz
# SPDX-License-Identifier: Apache-2.0
"""Offline source-context review; no physical fault labels or production rules."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from batterylog_research.field_stress import REL, SOURCE_SHA, above, digest

CELL = [f"U_Cell_{i}" for i in range(1, 9)]
CNV = [f"I_CNV_Cell_{i}" for i in range(1, 9)]
TEMP = [f"Temperature_{i}" for i in range(1, 5)]
TARGETS = (3802126, 4521427, 4535913)


def observe_pairs(times, volts, threshold=0.05, gap=60):
    """Independent array calculation of the existing observational audit."""
    dt = np.diff(times)
    eligible = (dt > 0) & ((dt <= gap) | np.isclose(dt, gap, rtol=REL, atol=0))
    changes = np.diff(volts, axis=0)
    common = np.median(changes, axis=1)
    residual = changes - common[:, None]
    outliers = above(np.abs(residual), threshold)
    consensus = (~outliers).sum(axis=1) > volts.shape[1] // 2
    flagged = outliers & (eligible & consensus)[:, None]
    return eligible, residual, flagged


def counts(flagged, selection=None):
    selected = flagged if selection is None else flagged[selection]
    by_cell = selected.sum(axis=0)
    total = int(by_cell.sum())
    return {
        "observations": total,
        "by_cell": {str(i + 1): int(n) for i, n in enumerate(by_cell)},
        "cell_1_fraction": float(by_cell[0] / total) if total else None,
    }


def clusters(times, eligible, flagged_cell, merge_gap):
    """Review groups only: no bridge over an ineligible pair, no fault claim."""
    indices = np.flatnonzero(flagged_cell)
    if not len(indices):
        return {"groups": 0, "largest_observation_count": 0}
    blocks = np.cumsum(~eligible)
    breaks = (np.diff(times[1:][indices]) > merge_gap) | (np.diff(blocks[indices]) != 0)
    sizes = np.diff(np.r_[0, np.flatnonzero(breaks) + 1, len(indices)])
    return {"groups": len(sizes), "largest_observation_count": int(sizes.max())}


def sampled_run(times, mask, center):
    """Bound an observed threshold run without filling between measurements."""
    if not mask[center]:
        raise ValueError("Center does not meet the review condition")
    left = right = center
    while left > 0 and mask[left - 1] and 0 < times[left] - times[left - 1] <= 60:
        left -= 1
    while right + 1 < len(times) and mask[right + 1] and 0 < times[right + 1] - times[right] <= 60:
        right += 1
    return {
        "first_source_data_row": left + 1,
        "last_source_data_row": right + 1,
        "sample_count": right - left + 1,
        "observed_sample_span_s": float(times[right] - times[left]),
        "previous_neighbor_interval_s": float(times[left] - times[left - 1]) if left else None,
        "next_neighbor_interval_s": float(times[right + 1] - times[right])
        if right + 1 < len(times)
        else None,
    }


def plot_context(frame, times, output):
    """Export original samples for the two July episodes; no smoothing."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(3, 2, figsize=(12, 8), sharex="col", layout="constrained")
    for col, center in enumerate(TARGETS[1:]):
        i = center - 1
        offset = times - times[i]
        selected = (offset >= -300) & (offset <= (300 if col == 0 else 3300))
        f = frame.loc[selected]
        x = times[selected] - times[i]
        peers = f[CELL[1:]]
        axes[0, col].plot(x, f[CELL[0]], ".-", color="#c64538", label="Cell 1", markersize=3)
        axes[0, col].fill_between(
            x,
            peers.min(axis=1),
            peers.max(axis=1),
            color="#2275a7",
            alpha=0.3,
            label="Cells 2-8 range",
        )
        for limit in (2.5, 3.65):
            axes[0, col].axhline(limit, color="gray", linewidth=0.8, linestyle="--")
        axes[0, col].set_title(str(frame["Timestamp"].iloc[i]) + f" (source row {center:,})")
        axes[0, col].set_ylabel("Recorded voltage (V)")
        axes[0, col].legend(loc="best", fontsize=8)
        axes[1, col].plot(x, f["I_Battery"], ".-", color="#34485d", markersize=3)
        axes[1, col].set_ylabel("Recorded pack current (A)")
        axes[2, col].plot(
            x, f[CNV[0]], ".-", color="#9954ac", label="Cell 1 converter", markersize=3
        )
        axes[2, col].plot(
            x,
            f[CNV].abs().max(axis=1),
            color="#44917a",
            label="Max |converter|, any cell",
            linewidth=1,
        )
        axes[2, col].set_ylabel("Recorded converter current (A)")
        axes[2, col].set_xlabel("Seconds from selected voltage extreme")
        axes[2, col].legend(loc="best", fontsize=8)
        for ax in axes[:, col]:
            ax.axvline(0, color="black", linewidth=0.6)
            ax.grid(alpha=0.2)
    fig.suptitle(
        "System 4: original logged samples around cell 1 extremes\n"
        "Dashed voltage lines are review thresholds; physical cause unconfirmed",
        fontsize=12,
    )
    description = (
        "Data: Schaeffer, Lenz, Gulla, Bazant, Braatz and Findeisen; "
        "Zenodo DOI 10.5281/zenodo.13715694; CC BY-NC 4.0. "
        "BatteryLog Research derived plot of selected source measurements, "
        "with review thresholds; no fault diagnosis."
    )
    fig.savefig(output, metadata={"Description": description})
    fig.savefig(output.with_suffix(".png"), dpi=140)
    plt.close(fig)


def review(source: Path, figure=None):
    if digest(source) != SOURCE_SHA:
        raise ValueError("Unverified field source bytes")
    # Full-frame investigative calculation, not a streaming memory benchmark.
    f = pd.read_csv(
        source,
        usecols=["Timestamp", "U_Battery", "I_Battery", *CELL, *CNV, *TEMP],
        skip_blank_lines=False,
    )
    stamp = pd.to_datetime(f["Timestamp"], errors="raise")
    if stamp.isna().any() or not np.isfinite(f.drop(columns="Timestamp").to_numpy()).all():
        raise ValueError("Missing/non-finite source context")
    times = (stamp - stamp.iloc[0]).dt.total_seconds().to_numpy()
    if figure is not None:
        plot_context(f, times, figure)
    v = f[CELL].to_numpy(dtype=float)
    current = f["I_Battery"].to_numpy(dtype=float)
    pack = f["U_Battery"].to_numpy(dtype=float)
    cnv = f[CNV].to_numpy(dtype=float)
    pack_error = pack - v.sum(axis=1)
    eligible, residual, flagged = observe_pairs(times, v)
    maximum_pair_current = np.maximum(np.abs(current[:-1]), np.abs(current[1:]))
    pair_error = np.maximum(np.abs(pack_error[:-1]), np.abs(pack_error[1:]))
    pair_cnv = np.maximum(np.abs(cnv[:-1]), np.abs(cnv[1:]))
    monthly = []
    month = stamp.dt.strftime("%Y-%m").to_numpy()
    level = v[:, 0] - np.median(v[:, 1:], axis=1)
    for name in np.unique(month):
        rows = month == name
        pairs = month[1:] == name
        monthly.append(
            {
                "month": name,
                "rows": int(rows.sum()),
                "eligible_pairs": int((eligible & pairs).sum()),
                **counts(flagged, pairs),
                "cell_1_level_abs_gt_0_2_v_rows": int(above(np.abs(level[rows]), 0.2).sum()),
                "cell_1_level_abs_v_p50_p95_p99": np.quantile(
                    np.abs(level[rows]), [0.5, 0.95, 0.99]
                ).tolist(),
            }
        )
    sensitivity = {}
    for limit in (50, 100, 500, 1000):
        selected = maximum_pair_current <= limit
        sensitivity[str(limit)] = {
            "eligible_pairs": int((eligible & selected).sum()),
            **counts(flagged, selected),
        }
    clean_context = (maximum_pair_current <= 100) & (pair_error <= 0.15)
    c1 = flagged[:, 0]
    any_cnv = pair_cnv.max(axis=1)
    windows = []
    for row in TARGETS:
        i = row - 1
        take = np.abs(times - times[i]) <= 300
        selected = np.flatnonzero(take)
        # Only derived context and bounded excerpts go into the report.
        evidence = []
        for j in range(max(0, i - 2), min(len(f), i + 3)):
            evidence.append(
                {
                    "source_data_row": j + 1,
                    "timestamp_as_recorded": str(f["Timestamp"].iloc[j]),
                    "cell_1_v": float(v[j, 0]),
                    "peer_2_to_8_min_max_v": [float(v[j, 1:].min()), float(v[j, 1:].max())],
                    "pack_v": float(pack[j]),
                    "pack_minus_cell_sum_v": float(pack_error[j]),
                    "pack_current_a": float(current[j]),
                    "cell_1_converter_a": float(cnv[j, 0]),
                    "max_abs_converter_a": float(np.abs(cnv[j]).max()),
                    "temperatures_c": f[TEMP].iloc[j].astype(float).tolist(),
                }
            )
        windows.append(
            {
                "center_source_data_row": row,
                "window_half_width_s": 300,
                "rows": len(selected),
                "duplicate_pairs": int((np.diff(times[selected]) == 0).sum()),
                "gaps_gt_60_s": int((np.diff(times[selected]) > 60).sum()),
                "cell_1_v_min_max": [float(v[take, 0].min()), float(v[take, 0].max())],
                "cell_1_below_2_5_v_rows": int((v[take, 0] < 2.5).sum()),
                "cell_1_above_3_65_v_rows": int((v[take, 0] > 3.65).sum()),
                "max_abs_pack_error_v": float(np.abs(pack_error[take]).max()),
                "max_abs_current_a": float(np.abs(current[take]).max()),
                "max_abs_cell_1_converter_a": float(np.abs(cnv[take, 0]).max()),
                "bounded_source_context": evidence,
            }
        )
    windows[1]["cell_1_below_2_5_v_run"] = sampled_run(times, v[:, 0] < 2.5, TARGETS[1] - 1)
    windows[2]["cell_1_above_3_65_v_run"] = sampled_run(times, v[:, 0] > 3.65, TARGETS[2] - 1)
    for window in windows[1:]:
        run = next(value for key, value in window.items() if key.endswith("_v_run"))
        left, right = run["first_source_data_row"] - 1, run["last_source_data_row"] - 1
        span = slice(left, right + 1)
        run.update(
            first_timestamp_as_recorded=str(f["Timestamp"].iloc[left]),
            last_timestamp_as_recorded=str(f["Timestamp"].iloc[right]),
            cell_1_v_min_max=[float(v[span, 0].min()), float(v[span, 0].max())],
            pack_current_a_min_max=[float(current[span].min()), float(current[span].max())],
            max_abs_pack_error_v=float(np.abs(pack_error[span]).max()),
            max_abs_cell_1_converter_a=float(np.abs(cnv[span, 0]).max()),
            previous_neighbor_cell_1_v=float(v[left - 1, 0]) if left else None,
            next_neighbor_cell_1_v=float(v[right + 1, 0]) if right + 1 < len(f) else None,
        )
    # The older stress campaign provides an independently executed CSV oracle.
    overall = counts(flagged)
    if overall["observations"] != 4037 or overall["by_cell"]["1"] != 3958:
        raise AssertionError("Source-vector results disagree with prior CSV audit")
    return {
        "scope": "research_source_context_review",
        "diagnostic_claim": False,
        "source_doi": "10.5281/zenodo.13715694",
        "source_member": "field_data/data_sys_4.csv",
        "source_license": "CC BY-NC 4.0",
        "source_sha256": SOURCE_SHA,
        "rows": len(f),
        "eligible_pairs": int(eligible.sum()),
        "threshold_v": 0.05,
        "max_gap_s": 60,
        "overall": overall,
        "monthly": monthly,
        "both_endpoint_abs_current_at_most_a": sensitivity,
        "both_current_le_100_a_and_pack_error_le_0_15_v": {
            "eligible_pairs": int((eligible & clean_context).sum()),
            **counts(flagged, clean_context),
        },
        "cell_1_pair_context": {
            "observations": int(c1.sum()),
            "any_converter_either_endpoint_abs_gt_0_1_a": int((c1 & (any_cnv > 0.1)).sum()),
            "cell_1_converter_either_endpoint_abs_gt_0_1_a": int(
                (c1 & (pair_cnv[:, 0] > 0.1)).sum()
            ),
            "all_converters_both_endpoints_exactly_zero": int((c1 & (any_cnv == 0)).sum()),
            "pack_error_both_endpoints_le_0_15_v": int((c1 & (pair_error <= 0.15)).sum()),
            "abs_current_change_le_1_a": int((c1 & (np.abs(np.diff(current)) <= 1)).sum()),
            "relative_step_v_p50_p95_p99_max": np.quantile(
                np.abs(residual[c1, 0]), [0.5, 0.95, 0.99, 1]
            ).tolist(),
        },
        "cell_1_observation_group_sensitivity_merge_gap_s": {
            str(gap): clusters(times, eligible, c1, gap) for gap in (5, 30, 60)
        },
        "windows": windows,
        "interpretation_limits": [
            "Current/converter/pack-error cutoffs are illustrative review strata, not safety limits.",
            "Both original endpoints are tested; no pair is rebuilt across discarded rows.",
            "All source rows stay in the primary analysis; chronology is never reordered.",
            "Observation groups are not incident or physical fault counts.",
            "Converter currents are measurements, not authenticated BMS active status.",
            "Shared temperature channels and unknown sensor timing cannot establish local heating.",
            "Pack/cell-sum agreement strengthens cross-channel consistency, not causal diagnosis.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--figure", type=Path)
    options = parser.parse_args()
    result = review(options.source, options.figure)
    options.output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"rows": result["rows"], "overall": result["overall"]}))


if __name__ == "__main__":
    main()
