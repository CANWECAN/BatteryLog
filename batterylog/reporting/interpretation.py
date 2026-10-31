"""Self-contained HTML separating engineering observations and physical limits."""

from html import escape


def _value(value: object, missing: str = "Not supplied") -> str:
    return escape(missing if value is None else str(value))


def _table(headers: list[str], rows: list[list[object]]) -> str:
    return (
        '<div class="table-wrap"><table><thead><tr>'
        + "".join(f'<th scope="col">{escape(label)}</th>' for label in headers)
        + "</tr></thead><tbody>"
        + "".join(
            "<tr>" + "".join(f"<td>{_value(value)}</td>" for value in row) + "</tr>" for row in rows
        )
        + "</tbody></table></div>"
    )


def render_interpretation_report(review: dict) -> str:
    """Render the generated review payload; all declarations remain escaped text.

    Links use fixed bundle filenames, never untrusted metadata or source paths.
    Every physical reason is shown; engineering events are previewed with their
    full count and a link to the unchanged complete result.
    """
    binding = review["binding"]
    observation = review["observations"]
    status = _value(review["engineering_status"])
    physical_status = _value(review["physical_interpretation_status"])
    links = '<a href="result.json">Analysis JSON</a> · <a href="interpretation.json">Interpretation JSON</a> · <a href="effective-config.json">Effective analysis settings</a>'
    if binding["context"] is not None:
        links += ' · <a href="context.json">Original context declaration</a>'
    evidence_rows: list[list[object]] = [
        ["Measurement", binding["source"]["name"], binding["source"]["sha256"]],
        ["Analysis JSON", "result.json", binding["result"]["sha256"]],
        ["Effective settings", "effective-config.json", binding["effective_config"]["sha256"]],
    ]
    if binding["context"] is not None:
        evidence_rows.append(
            [
                "Context declaration",
                binding["context"]["original_name"],
                binding["context"]["sha256"],
            ]
        )
    violations = observation["violations"]
    event_rows = [
        [
            event["code"],
            f"{event['start_time_s']} – {event['end_time_s']}",
            f"{event['measured_value']} {event['unit']}",
            f"{event['limit_value']} {event['unit']}",
        ]
        for event in violations[:50]
    ]
    events = (
        _table(["Rule", "Interval (s)", "Measured", "Limit"], event_rows)
        if event_rows
        else "<p>No ordinary engineering threshold events were recorded.</p>"
    )
    models = observation.get("failure_models")
    model_table = (
        "<h3>Configured temporal/model checks</h3>"
        + _table(
            ["Check", "Engineering status", "Reason"],
            [[item["code"], item["status"], item["reason"]] for item in models["evaluations"]],
        )
        if models is not None
        else ""
    )
    titles = {
        "CELL_SOC_IMBALANCE": "SOC interpretation of voltage spread",
        "PARALLEL_BRANCH_FAULT_LOCATION": "Parallel branch fault location",
        "SENSOR_VS_CELL_FAULT_ISOLATION": "Sensor versus cell fault cause",
    }
    fallback_details = {
        "MEASUREMENT_CONTEXT_NOT_ASSESSED": "Sensor and cell fault causes have not been assessed by this review.",
        "FAULT_ISOLATION_MODEL_NOT_AVAILABLE": "No validated sensor-versus-cell isolation method is implemented.",
    }
    sections = []
    for claim in review["claims"]:
        declarations = ""
        if claim["claim"] == "CELL_SOC_IMBALANCE":
            soc = claim["declared_soc"] or {}
            declarations = _table(
                ["Declared context", "Value"],
                [
                    ["Chemistry", claim["declared_chemistry"]],
                    ["SOC (%)", soc.get("value_percent")],
                    ["SOC source", soc.get("source")],
                    ["Operating state", claim["declared_operating_state"]],
                ],
            )
            if claim["cell_voltage_channels"]:
                declarations += "<h4>Declared cell-voltage sources</h4>" + _table(
                    ["Source", "Cell / branch", "Unit", "Clock / acquisition"],
                    [
                        [
                            channel["source"],
                            f"{channel['cell_id'] or 'Unassigned'} / {channel['branch_id'] or 'Unassigned'}",
                            channel["unit"],
                            f"{channel['time_basis'] or 'Unspecified'} / {channel['acquisition'] or 'Unspecified'}",
                        ]
                        for channel in claim["cell_voltage_channels"]
                    ],
                )
        elif claim["claim"] == "PARALLEL_BRANCH_FAULT_LOCATION":
            declarations = f"<p>Declared topology: {_value(claim['topology_kind'])}. Physical branch inventory remains unverified.</p>"
            if claim["branches"]:
                declarations += _table(
                    [
                        "Branch",
                        "Current sources",
                        "Terminal-voltage sources",
                        "Cell-voltage sources",
                    ],
                    [
                        [
                            branch["branch_id"],
                            ", ".join(branch["current_sources"]) or "None declared",
                            ", ".join(branch["terminal_voltage_sources"]) or "None declared",
                            ", ".join(branch["cell_voltage_sources"]) or "None declared",
                        ]
                        for branch in claim["branches"]
                    ],
                )
        issues = claim.get("issues")
        rows = (
            [
                [
                    issue["code"],
                    issue["field"],
                    issue.get("source") or issue.get("branch_id"),
                    issue["detail"],
                ]
                for issue in issues
            ]
            if issues is not None
            else [
                [reason, "Physical cause", None, fallback_details.get(reason, reason)]
                for reason in claim["reason_codes"]
            ]
        )
        sections.append(
            f'<section class="claim"><h3>{escape(titles[claim["claim"]])}</h3>'
            f'<p class="neutral">Physical status: <strong>{_value(claim["status"])}</strong></p>'
            f"{declarations}<h4>Limits and additional evidence</h4>"
            + '<ul class="reasons">'
            + "".join(
                f"<li><strong>{_value(row[0])}</strong><p>{_value(row[3])}</p>"
                f'<p class="location">Field: {_value(row[1])}; source / branch: {_value(row[2])}</p></li>'
                for row in rows
            )
            + "</ul>"
            + "</section>"
        )
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        "<title>BatteryLog Interpretation Review</title><style>"
        "*{box-sizing:border-box}body{font:16px/1.5 system-ui,Segoe UI,Arial,sans-serif;color:#182338;background:#fff;margin:0 auto;max-width:1120px;padding:24px}"
        "h1{font-size:1.8rem;line-height:1.2}h2{font-size:1.4rem;margin-top:2rem}h3{font-size:1.15rem}h4{font-size:1rem;margin-bottom:.5rem}"
        "p,td,th{overflow-wrap:anywhere}a{color:#174ea6}a:focus{outline:2px solid #174ea6}.outcome,.neutral{border-left:4px solid #52647a;background:#f1f5f9;padding:12px 16px}"
        ".claim{border-top:1px solid #b8c3d1;margin-top:24px;padding-top:8px}table{width:100%;table-layout:fixed;border-collapse:collapse;font-size:.875rem;margin:12px 0}"
        ".reasons{list-style:none;padding:0}.reasons li{border-bottom:1px solid #d7dfe8;padding:10px 0}.reasons strong{overflow-wrap:anywhere}.reasons p{margin:.4rem 0}.location{font-size:.875rem;color:#42536a}"
        "th,td{border:1px solid #cbd5e1;text-align:left;vertical-align:top;padding:8px;word-break:normal}th{background:#eaf0f6}code{overflow-wrap:anywhere}"
        "@media(max-width:600px){body{padding:12px;font-size:15px}th,td{padding:5px;font-size:12px}h1{font-size:1.5rem}}"
        "@media print{body{max-width:none;padding:0;font-size:11pt}table{font-size:9pt}thead{display:table-header-group}tr{break-inside:avoid}h2,h3,h4{break-after:avoid}a{color:inherit}}"
        "</style></head><body><h1>BatteryLog Interpretation Review</h1>"
        f'<div class="outcome"><p>Engineering: <strong>{status}</strong></p>'
        f"<p>Physical interpretation: <strong>{physical_status}</strong></p></div>"
        "<p>Engineering threshold observations and physical causes are separate. Missing context does not erase a threshold violation. Passing the configured checks does not establish battery health or safety.</p>"
        f'<nav aria-label="Evidence files">{links}</nav><h2>Engineering observations</h2>'
        + _table(
            ["Observation", "Value"],
            [
                ["Maximum cell-voltage spread (V)", observation["max_delta_v"]],
                [
                    "Configured voltage-spread limit (V)",
                    observation["voltage_spread_limit_v"]
                    if observation["voltage_spread_limit_v"] is not None
                    else "Not configured",
                ],
                ["Threshold events (all rules)", len(violations)],
                ["Data-quality events", len(observation["data_quality_events"])],
            ],
        )
        + f'<p>Showing up to 50 of {len(violations)} threshold events. Full event details and units are in <a href="result.json">Analysis JSON</a>.</p>'
        + events
        + model_table
        + "<h2>Physical interpretation limits</h2><p>All metadata below are declarations. Channel existence, units, calibration, timing, physical identity and operating conditions have not been verified by this review. No SOC difference, faulty branch or sensor/cell cause is estimated.</p>"
        + "".join(sections)
        + "<h2>Source and evidence identity</h2><p>Analysis used the captured source bytes. These hashes associate the source, unchanged engineering result, effective settings and optional context. They do not authenticate the declarations or verify physical measurement properties.</p>"
        + _table(["Evidence", "Name", "SHA-256"], evidence_rows)
        + "<p>The original measurement is identified by hash and is not copied into this bundle. Effective settings record what analysis used; they are not a copy or hash of the original YAML file. Artifact hashes are integrity references, not digital signatures.</p>"
        + "</body></html>"
    )
