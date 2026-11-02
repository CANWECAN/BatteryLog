"""Anchor independent field references on duplicates, gaps and real evidence."""

import json
import sys
from types import SimpleNamespace

import pandas as pd

from batterylog_research.field_stress import CELLS, TEMPS, model_references, peak_rss_mib


def test_optional_peak_rss_on_windows_does_not_import_unavailable_resource(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setitem(sys.modules, "resource", None)
    assert peak_rss_mib() is None
    assert json.dumps({"whole_process_peak_rss_mib": peak_rss_mib()}) == (
        '{"whole_process_peak_rss_mib": null}'
    )


def test_linux_peak_rss_retains_kib_to_mib_conversion(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setitem(
        sys.modules,
        "resource",
        SimpleNamespace(
            RUSAGE_SELF=0,
            getrusage=lambda who: SimpleNamespace(ru_maxrss=8192),
        ),
    )
    assert peak_rss_mib() == 8.0


def frame(times, temperatures, spread=0.0):
    f = pd.DataFrame({"timestamp_s": times})
    for name in CELLS:
        f[name] = 3.0
    f[CELLS[0]] += spread
    for name in TEMPS:
        f[name] = 20.0
    f[TEMPS[0]] = temperatures
    f["pack_current_a"] = 0.0
    f["pack_voltage_v"] = f[CELLS].sum(axis=1)
    return f


def test_duplicate_replaces_temperature_reference_and_gap_breaks_chain():
    refs = model_references(frame([0, 1, 1, 2, 63, 64, 65], [20, 21, 22, 23, 24, 25, 26]))
    eligible, events = refs["TEMPERATURE_RISE_HIGH"]
    assert eligible == 4
    assert [e["start_time_s"] for e in events] == [1, 2, 64]
    assert [e["sample_count"] for e in events] == [1, 1, 2]
    assert events[1]["evidence"] == {
        "previous_time_s": 1.0,
        "interval_s": 1.0,
        "previous_temperature_c": 22.0,
        "temperature_c": 23.0,
    }
    assert events[2]["peak_time_s"] == 64


def test_duplicate_does_not_reset_elapsed_sustained_observation():
    refs = model_references(frame([0, 10, 10, 20, 30, 31], [20] * 6, spread=0.06))
    eligible, events = refs["CELL_IMBALANCE_SUSTAINED"]
    assert eligible == 2
    assert len(events) == 1
    assert events[0]["start_time_s"] == 0
    assert events[0]["end_time_s"] == 31
    assert events[0]["peak_time_s"] == 0
    assert events[0]["sample_count"] == 6


def test_invalid_source_row_censors_temporal_reference():
    f = frame([0, 1, 2, 3, 4], [20, 21, 22, 23, 24])
    f.loc[2, "pack_current_a"] = float("nan")
    eligible, events = model_references(f)["TEMPERATURE_RISE_HIGH"]
    assert eligible == 2
    assert [e["peak_time_s"] for e in events] == [1, 4]


def test_integer_temperature_channels_use_floating_rate_arithmetic():
    f = frame([0, 1, 2], [20, 21, 22])
    f[TEMPS] = f[TEMPS].astype(int)
    eligible, events = model_references(f)["TEMPERATURE_RISE_HIGH"]
    assert eligible == 2
    assert len(events) == 1
    assert events[0]["measured_value"] == 60.0
    assert events[0]["evidence"]["previous_temperature_c"] == 20.0
