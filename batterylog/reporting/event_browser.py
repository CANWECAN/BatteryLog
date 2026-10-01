"""Self-contained navigation for large HTML event tables."""

import json
from collections import Counter
from html import escape

from batterylog.models import ViolationEvent

EVENT_PAGE_SIZE = 100


def violation_cells(event: ViolationEvent) -> list[str]:
    chain = (
        f"pack {event['pack_voltage_v']:.12g} V; "
        f"cell sum {event['cell_voltage_sum_v']:.12g} V; "
        f"signed error {event['signed_error_v']:.12g} V"
        if event["code"] == "PACK_VOLTAGE_CELL_SUM_MISMATCH"
        else "—"
    )
    return [
        event["code"],
        f"{event['start_time_s']:.12g}",
        f"{event['end_time_s']:.12g}",
        f"{event['peak_time_s']:.12g}",
        f"{event['measured_value']:.12g} {event['unit']}",
        f"{event['limit_value']:.12g} {event['unit']}",
        str(event["sample_count"]),
        f"{event['duration_s']:.12g}",
        f"{event['peak_excursion']:.12g} {event['unit']}",
        ", ".join(event["signals"]),
        chain,
    ]


def render_event_browser(events: list[ViolationEvent]) -> tuple[str, str]:
    counts = Counter(event["code"] for event in events)
    signals = sorted({signal for event in events for signal in event["signals"]})
    code_options = "".join(
        f'<option value="{escape(code, quote=True)}">{escape(code)}</option>'
        for code in sorted(counts)
    )
    signal_options = "".join(
        f'<option value="{escape(signal, quote=True)}">{escape(signal)}</option>'
        for signal in signals
    )
    summary = "".join(
        f'<tr><th scope="row"><a class="rule-link" href="#violation-events" '
        f'data-rule="{escape(code, quote=True)}" '
        f'aria-label="Show {escape(code, quote=True)} events">{escape(code)}</a></th>'
        f"<td>{counts[code]}</td></tr>"
        for code in sorted(counts)
    )
    controls = f"""
<table id="violation-summary"><caption>Events by rule — complete report</caption>
<thead><tr><th>Rule</th><th>Events</th></tr></thead><tbody>{summary}</tbody></table>
<p>All {len(events)} events are retained in this file. The table displays
{EVENT_PAGE_SIZE} events per page. Printing includes the displayed page only.</p>
<form id="event-filters" hidden>
<label>Rule <select id="event-rule"><option value="">All rules</option>{code_options}</select></label>
<label>Signal <select id="event-signal"><option value="">All signals</option>{signal_options}</select></label>
<label>From (s) <input id="event-from" type="number" step="any"></label>
<label>To (s) <input id="event-to" type="number" step="any"></label>
<button type="submit">Apply filters</button><button type="reset">Reset filters</button>
<p class="small">Time filtering uses original event timestamps and includes overlapping events.
Filters affect this table only; charts and overall status show the complete analysis.</p>
</form>
<p id="event-error" role="alert"></p>
<div id="event-pages" hidden><button type="button" data-page="first">First page</button>
<button type="button" data-page="previous">Previous page</button>
<button type="button" data-page="next">Next page</button>
<button type="button" data-page="last">Last page</button></div>
<p id="event-count" role="status" aria-live="polite">Showing 1–{EVENT_PAGE_SIZE} of {len(events)} events.</p>
<noscript><p>JavaScript is disabled. The table shows the first {EVENT_PAGE_SIZE} events only.
The complete event list is retained in this file's embedded data. Use the JSON
output for machine-readable evidence.</p></noscript>
"""
    payload = [
        {
            "cells": violation_cells(event),
            "signals": event["signals"],
            "start": event["start_time_s"],
            "end": event["end_time_s"],
        }
        for event in events
    ]
    data = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    # A literal '<' could terminate the inert JSON script element.
    data = data.replace("<", "\\u003c")
    scripts = (
        f'<script id="event-data" type="application/json">{data}</script>\n'
        f"<script>{_EVENT_BROWSER_SCRIPT.replace('PAGE_SIZE_VALUE', str(EVENT_PAGE_SIZE))}</script>"
    )
    return controls, scripts


_EVENT_BROWSER_SCRIPT = r"""
(() => {
  "use strict";
  const events = JSON.parse(document.getElementById("event-data").textContent);
  const pageSize = PAGE_SIZE_VALUE;
  const form = document.getElementById("event-filters");
  const rule = document.getElementById("event-rule");
  const signal = document.getElementById("event-signal");
  const from = document.getElementById("event-from");
  const to = document.getElementById("event-to");
  const error = document.getElementById("event-error");
  const count = document.getElementById("event-count");
  const region = document.querySelector(".event-table");
  const body = region.querySelector("tbody");
  const buttons = [...document.querySelectorAll("#event-pages button")];
  let matches = events;
  let page = 0;

  function render() {
    const start = page * pageSize;
    const end = Math.min(start + pageSize, matches.length);
    const fragment = document.createDocumentFragment();
    for (const event of matches.slice(start, end)) {
      const row = document.createElement("tr");
      event.cells.forEach((text, index) => {
        const cell = document.createElement("td");
        if (index === 0) {
          const code = document.createElement("code");
          code.textContent = text;
          cell.append(code);
        } else {
          cell.textContent = text;
        }
        row.append(cell);
      });
      fragment.append(row);
    }
    body.replaceChildren(fragment);
    region.scrollTop = 0;
    count.textContent = matches.length
      ? "Showing " + (start + 1) + "–" + end + " of " + matches.length
        + " matching events (" + events.length + " total). Page "
        + (page + 1) + " of " + Math.ceil(matches.length / pageSize) + "."
      : "No matching events (" + events.length + " total).";
    buttons.forEach(button => {
      const action = button.dataset.page;
      button.disabled = (action === "first" || action === "previous")
        ? page === 0 : end >= matches.length;
    });
  }

  function apply() {
    const lower = from.value === "" ? -Infinity : Number(from.value);
    const upper = to.value === "" ? Infinity : Number(to.value);
    if ((from.value !== "" && !Number.isFinite(lower))
        || (to.value !== "" && !Number.isFinite(upper))) {
      error.textContent = "Time bounds must be finite.";
      return;
    }
    if (lower > upper) {
      error.textContent = "From must not exceed To.";
      return;
    }
    error.textContent = "";
    matches = events.filter(event =>
      (!rule.value || event.cells[0] === rule.value)
      && (!signal.value || event.signals.includes(signal.value))
      && event.end >= lower && event.start <= upper);
    page = 0;
    render();
  }

  form.addEventListener("submit", event => { event.preventDefault(); apply(); });
  form.addEventListener("reset", () => {
    rule.value = ""; signal.value = ""; from.value = ""; to.value = "";
    apply();
  });
  buttons.forEach(button => button.addEventListener("click", () => {
    const action = button.dataset.page;
    if (action === "first") page = 0;
    if (action === "previous") page = Math.max(0, page - 1);
    if (action === "next") page++;
    if (action === "last") page = Math.max(0, Math.ceil(matches.length / pageSize) - 1);
    render();
  }));
  document.querySelectorAll(".rule-link").forEach(link => {
    link.addEventListener("click", event => {
      event.preventDefault();
      form.reset();
      rule.value = link.dataset.rule;
      apply();
      region.scrollIntoView({block: "nearest"});
    });
  });
  render();
  form.hidden = false;
  document.getElementById("event-pages").hidden = false;
})();
"""
