"""Small synthetic example for the desktop launcher; limits are illustrative only."""

import shutil
import tempfile
from pathlib import Path

_MEASUREMENT = """timestamp_s,temp_c,cell_1_v,cell_2_v,cell_3_v,cell_4_v
0,28,3.95,3.94,3.95,3.94
1,30,3.91,3.90,3.91,3.90
2,34,3.84,3.83,3.84,3.82
3,42,3.76,3.74,3.75,3.71
4,48,3.68,3.66,3.67,3.58
"""

_CONFIG = """# Synthetic demo only. These are not recommended battery safety limits.
limits:
  cell_voltage:
    max_delta_v: 0.08
  temperature:
    max_c: 45
"""


def create_demo(output_parent: Path) -> Path:
    """Write a new, separate demo folder without replacing the user's files."""
    output_parent = output_parent.expanduser().resolve(strict=True)
    if not output_parent.is_dir():
        raise ValueError("Select an existing folder for the demo.")
    directory = Path(tempfile.mkdtemp(prefix="batterylog-demo-", dir=output_parent))
    try:
        (directory / "synthetic_demo.csv").write_text(_MEASUREMENT, encoding="utf-8")
        (directory / "validation.yaml").write_text(_CONFIG, encoding="utf-8")
    except OSError as exc:
        try:
            shutil.rmtree(directory)
        except OSError as cleanup:
            raise OSError(f"{exc}\nDemo cleanup failed for {directory}: {cleanup}") from exc
        raise
    return directory
