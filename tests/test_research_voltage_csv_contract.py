"""Reject unreliable CSV evidence and demonstrate acquisition confounders."""

import io
import json

import pytest

from batterylog_research.voltage_step_audit import audit_voltage_csv, main


def run_csv(text, *, threshold=0.05, gap=1, max_examples=3):
    return audit_voltage_csv(
        io.StringIO(text),
        peer_step_threshold_v=threshold,
        max_gap_s=gap,
        max_examples=max_examples,
    )


@pytest.mark.parametrize(
    "text",
    [
        "",
        "timestamp_s,cell_1_v,cell_2_v\n0,3.5,3.5\n",
        "timestamp_s,cell_1_v,cell_2_v,cell_3_v,cell_3_v\n0,3.5,3.5,3.5,3.5\n",
        "timestamp_s,cell_1_v,cell_01_v,cell_2_v\n0,3.5,3.5,3.5\n",
        "timestamp_s,cell_1_v,cell_2_v,cell_3_v\n0,3.5,3.5,3.5,EXTRA\n",
        "timestamp_s,cell_1_v,cell_2_v,cell_3_v\n0,3.5,3.5\n",
        "timestamp_s,cell_1_v,cell_2_v,cell_3_v\n",
    ],
)
def test_malformed_or_incomplete_csv_fails_closed(text):
    with pytest.raises(ValueError):
        run_csv(text)


def test_timestamp_regression_fails_closed():
    raw = "timestamp_s,cell_1_v,cell_2_v,cell_3_v\n2,3.5,3.5,3.5\n1,3.5,3.5,3.5\n"
    with pytest.raises(ValueError, match="decreases"):
        run_csv(raw)


def test_asynchronous_zoh_looks_like_single_cell_step():
    # Physically uniform -200 mV step arrives one sample late in cell 2.
    raw = (
        "timestamp_s,cell_1_v,cell_2_v,cell_3_v,cell_4_v,pack_current_a\n"
        "0,4,4,4,4,0\n1,3.8,4,3.8,3.8,100\n2,3.8,3.8,3.8,3.8,100\n"
    )
    result = run_csv(raw)
    assert result["cell_step_observations_flagged"] == 2
    assert result["diagnostic_claim"] is False
    assert result["examples"][0]["delta_current_a"] == 100
    assert result["examples"][1]["delta_current_a"] == 0


def test_steady_differential_voltage_deviation_does_not_make_step():
    raw = "timestamp_s,cell_1_v,cell_2_v,cell_3_v\n0,3.5,3.5,3.1\n1,3.5,3.5,3.1\n2,3.5,3.5,3.1\n"
    result = run_csv(raw)
    assert result["cell_step_observations_flagged"] == 0
    assert result["eligible_sample_pairs"] == 2


def test_cli_preserves_csv_and_prints_machine_readable_json(tmp_path, capsys):
    path = tmp_path / "source.csv"
    path.write_text(
        "timestamp_s,cell_1_v,cell_2_v,cell_3_v\n0,3.5,3.5,3.5\n1,3.5,3.2,3.5\n", encoding="utf-8"
    )
    original = path.read_bytes()
    assert main([str(path), "--peer-step-threshold-v", ".05", "--max-gap-s", "1"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["cell_step_observations_flagged"] == 1
    assert data["ambiguous_peer_reference_pairs"] == 0
    assert path.read_bytes() == original


def test_many_rows_counts_and_bounded_examples():
    header = "timestamp_s,cell_1_v,cell_2_v,cell_3_v,cell_4_v\n"
    records = [f"{t},3.5,{3.4 if t % 2 else 3.5},3.5,3.5\n" for t in range(10001)]
    result = run_csv(header + "".join(records), max_examples=2)
    assert result["cell_step_observations_flagged"] == 10000
    assert len(result["examples"]) == 2
    assert result["ambiguous_peer_reference_pairs"] == 0
