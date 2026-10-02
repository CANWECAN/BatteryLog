"""Isolate the observed canmatrix/asammdf import compatibility."""

import json
import sys
from importlib.metadata import version
from pathlib import Path

root = Path.cwd()
out = root / "dist" / "mf4-dependency-review"
out.mkdir(parents=True, exist_ok=True)
stage = sys.argv[1]
if stage == "1.3":
    sys.path.insert(0, str(root / "dist" / "quality-review" / "canmatrix-13"))
from canmatrix import CanMatrix

record = {
    "stage": stage,
    "canmatrix_version": version("canmatrix"),
    "asammdf_version": version("asammdf"),
    "export_type": type(CanMatrix).__name__,
}
try:
    from asammdf import MDF

    record.update(import_ok=True, error=None, mdf_export=MDF.__name__)
except TypeError as exc:
    record.update(import_ok=False, error=str(exc))
assert record["import_ok"] == (stage == "1.2"), record
(out / ("0.10-mf4-dependency-" + stage + ".json")).write_text(
    json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
)
print(json.dumps(record), flush=True)
