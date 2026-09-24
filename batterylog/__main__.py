import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from .analysis.core import analyze_battery_log
from .analysis.streaming import analyze_battery_file_with_report_series
from .config import (
    EventDetectionConfig,
    ValidationConfig,
    ValidationLimits,
    load_validation_config,
    load_validation_config_bytes,
    override_event_detection,
)
from .models import AnalysisResult
from .reporting import (
    build_report_metadata,
    capture_file_snapshot,
    render_json_result,
    verify_file_unchanged,
    write_html_report,
    write_json_result,
)
from .reporting.evidence import capture_file_backed_snapshot

EXIT_PASS = 0
EXIT_VALIDATION_FAIL = 1
EXIT_USAGE_ERROR = 2
EXIT_NOT_EVALUATED = 3
EXIT_RUNTIME_ERROR = 4


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Analyze EV battery test data.")
    parser.add_argument("path", help="Path to a battery CSV or MDF/MF4 measurement")
    parser.add_argument(
        "--config",
        help="Path to a YAML validation configuration",
    )
    parser.add_argument(
        "--report",
        help="Write a self-contained HTML validation report",
    )
    parser.add_argument(
        "--json-out",
        help="Write the JSON result atomically as UTF-8; stdout is still emitted",
    )
    cell_min_group = parser.add_mutually_exclusive_group()
    cell_min_group.add_argument(
        "--cell-min-v",
        type=float,
        help="Override minimum allowed cell voltage",
    )
    cell_min_group.add_argument(
        "--no-cell-min-v",
        action="store_true",
        help="Disable minimum cell-voltage validation",
    )

    cell_max_group = parser.add_mutually_exclusive_group()
    cell_max_group.add_argument(
        "--cell-max-v",
        type=float,
        help="Override maximum allowed cell voltage",
    )
    cell_max_group.add_argument(
        "--no-cell-max-v",
        action="store_true",
        help="Disable maximum cell-voltage validation",
    )

    imbalance_group = parser.add_mutually_exclusive_group()
    imbalance_group.add_argument(
        "--imbalance-limit-v",
        type=float,
        help="Override maximum allowed cell-voltage spread",
    )
    imbalance_group.add_argument(
        "--no-imbalance-limit-v",
        action="store_true",
        help="Disable cell-voltage imbalance validation",
    )

    temp_min_group = parser.add_mutually_exclusive_group()
    temp_min_group.add_argument(
        "--temp-min-c",
        type=float,
        help="Override minimum allowed temperature",
    )
    temp_min_group.add_argument(
        "--no-temp-min-c",
        action="store_true",
        help="Disable minimum temperature validation",
    )

    temp_max_group = parser.add_mutually_exclusive_group()
    temp_max_group.add_argument(
        "--temp-warning-c",
        "--temp-max-c",
        dest="temp_max_c",
        type=float,
        help="Override maximum allowed temperature",
    )
    temp_max_group.add_argument(
        "--no-temp-warning-c",
        "--no-temp-max-c",
        dest="no_temp_max_c",
        action="store_true",
        help="Disable maximum temperature validation",
    )

    temp_spread_group = parser.add_mutually_exclusive_group()
    temp_spread_group.add_argument(
        "--temp-spread-max-c",
        type=float,
        help="Override maximum allowed temperature spread",
    )
    temp_spread_group.add_argument(
        "--no-temp-spread-max-c",
        action="store_true",
        help="Disable temperature-spread validation",
    )

    charge_current_group = parser.add_mutually_exclusive_group()
    charge_current_group.add_argument(
        "--pack-charge-max-a",
        type=float,
        help="Override maximum allowed pack charge-current magnitude",
    )
    charge_current_group.add_argument(
        "--no-pack-charge-max-a",
        action="store_true",
        help="Disable pack charge-overcurrent validation",
    )

    discharge_current_group = parser.add_mutually_exclusive_group()
    discharge_current_group.add_argument(
        "--pack-discharge-max-a",
        type=float,
        help="Override maximum allowed pack discharge-current magnitude",
    )
    discharge_current_group.add_argument(
        "--no-pack-discharge-max-a",
        action="store_true",
        help="Disable pack discharge-overcurrent validation",
    )
    parser.add_argument(
        "--pack-current-positive-direction",
        choices=("charge", "discharge"),
        help="Declare which current direction is represented by positive values",
    )

    event_gap_group = parser.add_mutually_exclusive_group()
    event_gap_group.add_argument(
        "--max-event-gap-s",
        type=float,
        help="Override maximum timestamp gap within one violation event",
    )
    event_gap_group.add_argument(
        "--no-max-event-gap-s",
        action="store_true",
        help="Disable the YAML event-gap limit and group by row contiguity only",
    )
    return parser


def _resolve_cli_limit(
    current: float | None,
    override: float | None,
    disabled: bool,
) -> float | None:
    if disabled:
        return None
    if override is not None:
        return override
    return current


def _resolve_cli_config(
    args: argparse.Namespace,
    *,
    base: ValidationConfig | None = None,
) -> ValidationConfig:
    if base is None:
        base = load_validation_config(args.config) if args.config else ValidationConfig()
    limits = ValidationLimits(
        cell_min_v=_resolve_cli_limit(
            base.limits.cell_min_v,
            args.cell_min_v,
            args.no_cell_min_v,
        ),
        cell_max_v=_resolve_cli_limit(
            base.limits.cell_max_v,
            args.cell_max_v,
            args.no_cell_max_v,
        ),
        imbalance_max_v=_resolve_cli_limit(
            base.limits.imbalance_max_v,
            args.imbalance_limit_v,
            args.no_imbalance_limit_v,
        ),
        temperature_min_c=_resolve_cli_limit(
            base.limits.temperature_min_c,
            args.temp_min_c,
            args.no_temp_min_c,
        ),
        temperature_max_c=_resolve_cli_limit(
            base.limits.temperature_max_c,
            args.temp_max_c,
            args.no_temp_max_c,
        ),
        temperature_spread_max_c=_resolve_cli_limit(
            base.limits.temperature_spread_max_c,
            args.temp_spread_max_c,
            args.no_temp_spread_max_c,
        ),
        pack_charge_max_a=_resolve_cli_limit(
            base.limits.pack_charge_max_a,
            args.pack_charge_max_a,
            args.no_pack_charge_max_a,
        ),
        pack_discharge_max_a=_resolve_cli_limit(
            base.limits.pack_discharge_max_a,
            args.pack_discharge_max_a,
            args.no_pack_discharge_max_a,
        ),
        pack_current_positive_direction=(
            args.pack_current_positive_direction or base.limits.pack_current_positive_direction
        ),
    )
    event_detection = (
        EventDetectionConfig(max_gap_s=None)
        if args.no_max_event_gap_s
        else override_event_detection(base.event_detection, max_gap_s=args.max_event_gap_s)
    )
    return ValidationConfig(
        limits=limits,
        event_detection=event_detection,
        data_quality=base.data_quality,
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
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code or EXIT_PASS)

    try:
        input_path = Path(args.path).resolve()
        report_path = Path(args.report).resolve() if args.report else None
        json_out_path = Path(args.json_out).resolve() if args.json_out else None
        config_path = Path(args.config).resolve() if args.config else None

        if _paths_refer_to_same_file(report_path, input_path):
            raise ValueError("Report output path must not overwrite the input log")
        if _paths_refer_to_same_file(report_path, config_path):
            raise ValueError("Report output path must not overwrite the validation config")
        if _paths_refer_to_same_file(json_out_path, input_path):
            raise ValueError("JSON output path must not overwrite the input log")
        if _paths_refer_to_same_file(json_out_path, config_path):
            raise ValueError("JSON output path must not overwrite the validation config")
        if _paths_refer_to_same_file(json_out_path, report_path):
            raise ValueError("JSON output path must not overwrite the HTML report")

        if report_path is not None:
            with capture_file_backed_snapshot(input_path) as source_snapshot:
                config_snapshot = (
                    capture_file_snapshot(config_path) if config_path is not None else None
                )
                base_config = (
                    load_validation_config_bytes(
                        config_snapshot.data,
                        source_name=str(config_path),
                    )
                    if config_snapshot is not None
                    else ValidationConfig()
                )
                validation_config = _resolve_cli_config(args, base=base_config)
                result, report_series = analyze_battery_file_with_report_series(
                    source_snapshot.handle,
                    source_name=input_path.name,
                    limits=validation_config.limits,
                    event_detection=validation_config.event_detection,
                    data_quality=validation_config.data_quality,
                    signal_mapping=validation_config.signals,
                )

                verify_file_unchanged(input_path, source_snapshot.evidence)
                if config_path is not None and config_snapshot is not None:
                    verify_file_unchanged(config_path, config_snapshot.evidence)

                metadata = build_report_metadata(
                    source_snapshot.evidence,
                    config_snapshot.evidence if config_snapshot is not None else None,
                )
                write_html_report(
                    result,
                    report_path,
                    metadata=metadata,
                    series=report_series,
                )
        else:
            validation_config = _resolve_cli_config(args)
            result = analyze_battery_log(
                input_path,
                limits=validation_config.limits,
                event_detection=validation_config.event_detection,
                data_quality=validation_config.data_quality,
                signal_mapping=validation_config.signals,
            )

        json_text = render_json_result(result)

        if json_out_path is not None:
            write_json_result(result, json_out_path)

        exit_code = _validation_exit_code(result)
    except (ImportError, OSError, TypeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_RUNTIME_ERROR

    sys.stdout.write(json_text)
    return exit_code


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
