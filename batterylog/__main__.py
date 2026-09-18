import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from .analysis.core import analyze_battery_log
from .config import (
    ValidationConfig,
    load_validation_config,
    override_event_detection,
    override_validation_limits,
)
from .models import AnalysisResult
from .reporting import (
    build_report_metadata,
    capture_file_evidence,
    verify_file_unchanged,
    write_html_report,
)

EXIT_PASS = 0
EXIT_VALIDATION_FAIL = 1
EXIT_ERROR = 2
EXIT_NOT_EVALUATED = 3


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Analyze EV battery test data.")
    parser.add_argument("path", help="Path to a battery CSV log")
    parser.add_argument(
        "--config",
        help="Path to a YAML validation configuration",
    )
    parser.add_argument(
        "--report",
        help="Write a self-contained HTML validation report",
    )
    parser.add_argument(
        "--cell-min-v",
        type=float,
        help="Override minimum allowed cell voltage",
    )
    parser.add_argument(
        "--cell-max-v",
        type=float,
        help="Override maximum allowed cell voltage",
    )
    parser.add_argument(
        "--imbalance-limit-v",
        type=float,
        help="Override maximum allowed cell-voltage spread",
    )
    parser.add_argument(
        "--temp-min-c",
        type=float,
        help="Override minimum allowed temperature",
    )
    parser.add_argument(
        "--temp-warning-c",
        "--temp-max-c",
        dest="temp_max_c",
        type=float,
        help="Override maximum allowed temperature",
    )
    parser.add_argument(
        "--max-event-gap-s",
        type=float,
        help="Override maximum timestamp gap within one violation event",
    )
    return parser


def _resolve_cli_config(args: argparse.Namespace) -> ValidationConfig:
    base = load_validation_config(args.config) if args.config else ValidationConfig()
    limits = override_validation_limits(
        base.limits,
        cell_min_v=args.cell_min_v,
        cell_max_v=args.cell_max_v,
        imbalance_max_v=args.imbalance_limit_v,
        temperature_min_c=args.temp_min_c,
        temperature_max_c=args.temp_max_c,
    )
    event_detection = override_event_detection(
        base.event_detection,
        max_gap_s=args.max_event_gap_s,
    )
    return ValidationConfig(
        limits=limits,
        event_detection=event_detection,
        signals=base.signals,
    )


def _paths_refer_to_same_file(left: Path | None, right: Path | None) -> bool:
    if left is None or right is None:
        return False
    if left == right:
        return True

    if not left.exists() or not right.exists():
        return False
    return left.samefile(right)


def _validation_exit_code(result: AnalysisResult) -> int:
    status = result["validation_status"]
    if status == "PASS":
        return EXIT_PASS
    if status == "FAIL":
        return EXIT_VALIDATION_FAIL
    if status == "NOT_EVALUATED":
        return EXIT_NOT_EVALUATED
    raise ValueError(f"Unsupported validation status: {status!r}")


def run(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        input_path = Path(args.path).resolve()
        report_path = Path(args.report).resolve() if args.report else None
        config_path = Path(args.config).resolve() if args.config else None

        if _paths_refer_to_same_file(report_path, input_path):
            raise ValueError("Report output path must not overwrite the input log")
        if _paths_refer_to_same_file(report_path, config_path):
            raise ValueError("Report output path must not overwrite the validation config")

        source_evidence = capture_file_evidence(input_path) if report_path else None
        config_evidence = (
            capture_file_evidence(config_path)
            if report_path is not None and config_path is not None
            else None
        )

        validation_config = _resolve_cli_config(args)
        result = analyze_battery_log(
            input_path,
            limits=validation_config.limits,
            event_detection=validation_config.event_detection,
            signal_mapping=validation_config.signals,
        )

        if report_path is not None:
            verify_file_unchanged(input_path, source_evidence)
            if config_path is not None and config_evidence is not None:
                verify_file_unchanged(config_path, config_evidence)

            metadata = build_report_metadata(source_evidence, config_evidence)
            write_html_report(
                result,
                report_path,
                metadata=metadata,
            )

        exit_code = _validation_exit_code(result)
    except (OSError, TypeError, ValueError) as exc:
        parser.exit(EXIT_ERROR, f"error: {exc}\n")

    print(json.dumps(result, indent=2, sort_keys=True))
    return exit_code


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
