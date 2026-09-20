import json
from pathlib import Path
from tempfile import NamedTemporaryFile

from batterylog.models import AnalysisResult


def render_json_result(result: AnalysisResult) -> str:
    return (
        json.dumps(
            result,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
    )


def write_json_result(
    result: AnalysisResult,
    output_path: str | Path,
) -> Path:
    path = Path(output_path)
    content = render_json_result(result)

    temp_path: Path | None = None
    try:
        with NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write(content.encode("utf-8"))
            temp_path = Path(handle.name)

        temp_path.replace(path)
    except Exception:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        raise

    return path
