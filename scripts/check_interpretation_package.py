"""Exercise source-bound interpretation through an installed API and console CLI."""

import hashlib
import json
import subprocess
import sys
import sysconfig
from html import escape
from html.parser import HTMLParser
from importlib.metadata import version
from pathlib import Path
from tempfile import TemporaryDirectory

import batterylog.interpretation_review as review_module
from batterylog import ValidationConfig, ValidationLimits, validate_result_semantics
from batterylog.interpretation_review import review_measurement


class _Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.paths = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.paths.extend(value for key, value in attrs if key == "href" and value)


def verify(cli: list[str], work: Path) -> dict:
    """Check independent exit/status anchors, artifact identities and real links."""
    source = work / "measurement & 'quoted'.csv"
    data = b"timestamp_s,cell_1_v,cell_2_v,temp_c\n0,3.8,3.6,25\n1,3.8,3.6,25\n"
    source.write_bytes(data)
    context = work / "context.json"
    context_bytes = b'\xef\xbb\xbf{"measurement_context_schema_version":1,"chemistry":"LFP"}\n'
    context.write_bytes(context_bytes)
    checks = []

    def run(*args, expected):
        completed = subprocess.run(
            [*cli, *map(str, args)], check=False, capture_output=True, text=True, timeout=60
        )
        assert completed.returncode == expected, (completed.returncode, completed.stderr)
        return completed

    for index, (limit, status, exit_code) in enumerate(
        [(None, "NOT_EVALUATED", 3), (0.5, "PASS", 0), (0.05, "FAIL", 1)]
    ):
        args = [source, *(["--imbalance-limit-v", str(limit)] if limit is not None else [])]
        ordinary = run(*args, expected=exit_code)
        target = work / f"cli-{index}"
        completed = run(
            *args,
            "--interpret",
            "--measurement-context",
            context,
            "--output-dir",
            target,
            expected=exit_code,
        )
        assert completed.stdout == ordinary.stdout
        assert "Physical interpretation: NOT_EVALUATED" in completed.stderr
        result = json.loads(completed.stdout)
        validate_result_semantics(result)
        assert result["validation_status"] == status
        assert result["max_delta_v"] == 0.2
        if status == "FAIL":
            assert result["violations"][0]["code"] == "CELL_IMBALANCE_HIGH"
            assert result["violations"][0]["measured_value"] == 0.2
            assert result["violations"][0]["limit_value"] == 0.05
        assert (target / "result.json").read_bytes() == completed.stdout.encode("utf-8")
        assert (target / "context.json").read_bytes() == context_bytes
        payload = json.loads((target / "interpretation.json").read_bytes())
        assert payload["engineering_status"] == status
        assert payload["physical_interpretation_status"] == "NOT_EVALUATED"
        assert payload["diagnostic_claim"] is False
        assert payload["measurement_properties_verified"] is False
        assert all(claim["status"] == "NOT_EVALUATED" for claim in payload["claims"])
        assert payload["binding"]["source"]["sha256"] == hashlib.sha256(data).hexdigest()
        for key in ("result", "context", "effective_config"):
            artifact = payload["binding"][key]
            content = (target / artifact["path"]).read_bytes()
            assert len(content) == artifact["size_bytes"]
            assert hashlib.sha256(content).hexdigest() == artifact["sha256"]
        html = (target / "interpretation.html").read_text(encoding="utf-8")
        links = _Links()
        links.feed(html)
        assert links.paths
        assert all(
            name in {"result.json", "interpretation.json", "context.json", "effective-config.json"}
            for name in links.paths
        )
        assert all((target / name).is_file() for name in links.paths)
        assert escape(source.name) in html
        assert all(
            reason in html for claim in payload["claims"] for reason in claim["reason_codes"]
        )
        api = review_measurement(
            source,
            work / f"api-{index}",
            context_path=context,
            config=ValidationConfig(limits=ValidationLimits(imbalance_max_v=limit)),
        )
        assert api.result_json == completed.stdout
        assert api.to_dict() == payload
        checks.append({"engineering_status": status, "exit_code": exit_code})

    absent = review_measurement(source, work / "no-context").to_dict()
    assert absent["binding"]["context"] is None
    assert absent["context_evidence_level"] == "NOT_SUPPLIED"
    context.write_bytes(b'{"measurement_context_schema_version":999}')
    invalid_target = work / "invalid-context"
    rejected = run(
        source,
        "--interpret",
        "--measurement-context",
        context,
        "--output-dir",
        invalid_target,
        expected=4,
    )
    assert rejected.stdout == "" and not invalid_target.exists()
    assert source.read_bytes() == data
    return {"interpretation": checks, "artifact_hashes_and_links": "verified"}


def main() -> None:
    expected_version = sys.argv[1]
    assert version("batterylog") == expected_version
    installed = Path(review_module.__file__).resolve()
    assert installed.is_relative_to(Path(sys.prefix).resolve()), installed
    cli = Path(sysconfig.get_path("scripts")) / (
        "batterylog.exe" if sys.platform == "win32" else "batterylog"
    )
    with TemporaryDirectory() as directory:
        result = verify([str(cli)], Path(directory))
    print(
        json.dumps({"version": expected_version, "installed": str(installed), **result}, indent=2)
    )


if __name__ == "__main__":
    main()
