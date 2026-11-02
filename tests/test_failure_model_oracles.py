"""Independent arithmetic and interval oracles for the three derived models."""

import numpy as np
import pandas as pd
from hypothesis import given, settings
from hypothesis import strategies as st

from batterylog import (
    BalancingConfig,
    CellSagConfig,
    FailureModelConfig,
    TemperatureRiseConfig,
    validate_result_semantics,
)
from batterylog.analysis.core import _analyze_battery_frame
from batterylog.analysis.streaming import _analyze_battery_chunks


def _run(frame, config):
    expected = _analyze_battery_frame(frame, failure_models=config)
    for size in (1, 2, 7):
        chunks = (frame.iloc[i : i + size] for i in range(0, len(frame), size))
        assert _analyze_battery_chunks(chunks, failure_models=config) == expected
    validate_result_semantics(expected)
    return expected["failure_models"]["evaluations"]


def _events(samples):
    """Group eligible exceeding samples; max uses first occurrence on a tie."""
    result = []
    active = []
    for sample in [*samples, None]:
        if sample is None:
            if active:
                peak = max(active, key=lambda item: item[1])
                result.append((active[0][0], active[-1][0], peak[0], peak[1], len(active)))
                active = []
        else:
            active.append(sample)
    return result


@settings(max_examples=60, deadline=None)
@given(
    st.lists(
        st.tuples(st.sampled_from([0, 0.5, 1, 3]), st.sampled_from([-1, -0.25, 0, 0.25, 1])),
        min_size=1,
        max_size=20,
    )
)
def test_temperature_sample_pair_oracle(rows):
    times = [0.0]
    temps = [25.0]
    for dt, change in rows:
        times.append(times[-1] + dt)
        temps.append(temps[-1] + change)
    frame = pd.DataFrame({"timestamp_s": times, "temp_c": temps, "cell_1_v": [3.5] * len(times)})
    items = _run(frame, FailureModelConfig(1, temperature_rise=TemperatureRiseConfig(20, 0.25)))
    samples = []
    pairs = 0
    for i in range(1, len(times)):
        dt = times[i] - times[i - 1]
        eligible = 0.25 <= dt <= 1
        rate = (temps[i] - temps[i - 1]) * 60 / dt if eligible else 0
        pairs += int(eligible)
        samples.append((times[i], rate) if eligible and rate > 20 else None)
    expected = _events(samples)
    assert [
        (
            e["start_time_s"],
            e["end_time_s"],
            e["peak_time_s"],
            e["measured_value"],
            e["sample_count"],
        )
        for e in items[0]["events"]
    ] == expected
    assert items[0]["evaluated_samples"] == pairs


@settings(max_examples=60, deadline=None)
@given(
    st.lists(st.tuples(*[st.sampled_from([0.0625, 0.125, 0.25, 0.5])] * 3), min_size=2, max_size=15)
)
def test_cell_sag_peer_median_oracle(drops):
    count = len(drops) + 2
    columns = {
        "timestamp_s": list(range(count)),
        "temp_c": [25.0] * count,
        "pack_current_a": [0] + [40] * len(drops) + [0],
    }
    for cell in range(3):
        columns[f"cell_{cell + 1}_v"] = [3.5] + [3.5 - row[cell] for row in drops] + [3.5]
    config = FailureModelConfig(1, cell_sag=CellSagConfig("discharge", 2, 20, 2, 1, 0.125))
    item = _run(pd.DataFrame(columns), config)[0]
    samples = []
    for t, row in enumerate(drops[1:], start=2):
        peer = sorted(row)[1]
        excess = max(v - peer for v in row)
        samples.append((float(t), excess) if excess > 0.125 else None)
    expected = _events(samples)
    assert [
        (
            e["start_time_s"],
            e["end_time_s"],
            e["peak_time_s"],
            e["measured_value"],
            e["sample_count"],
        )
        for e in item["events"]
    ] == expected


@settings(max_examples=60, deadline=None)
@given(
    st.lists(st.sampled_from([0.125, 0.21875, 0.25, 0.28125]), min_size=1, max_size=8),
    st.booleans(),
)
def test_balancing_first_deadline_and_timeout_oracle(spreads, complete):
    active = [0] + [1] * len(spreads) + ([0] if complete else [])
    spread = [0.25] + spreads + ([0.25] if complete else [])
    frame = pd.DataFrame(
        {
            "timestamp_s": np.arange(len(active), dtype=float),
            "cell_1_v": [3.5] * len(active),
            "cell_2_v": [3.5 - d for d in spread],
            "temp_c": [25.0] * len(active),
            "Bal": active,
        }
    )
    items = _run(
        frame, FailureModelConfig(1, balancing=BalancingConfig("Bal", 2, 0.03125, 0.125, 4))
    )
    initial = spreads[0]
    if len(spreads) >= 3:
        improvement = initial - spreads[2]
        assert len(items[0]["events"]) == int(improvement < 0.03125)
        if items[0]["events"]:
            assert items[0]["events"][0]["measured_value"] == improvement
            assert items[0]["events"][0]["end_time_s"] == 3
    else:
        assert items[0]["status"] == "NOT_EVALUATED"
    assert len(items[1]["events"]) == int(len(spreads) >= 6)
    if items[1]["events"]:
        assert items[1]["events"][0]["end_time_s"] == 6
        assert items[1]["events"][0]["measured_value"] == 5
    else:
        assert items[1]["status"] == ("PASS" if complete else "NOT_EVALUATED")
