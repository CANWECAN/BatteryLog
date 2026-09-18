import argparse
import json

from .analysis.core import analyze_battery_log
from .config import (
    ValidationLimits,
    load_validation_limits,
    override_validation_limits,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Analyze EV battery test data.")
    parser.add_argument("path", help="Path to a battery CSV log")
    parser.add_argument(
        "--config",
        help="Path to a YAML validation configuration",
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
    return parser


def _resolve_cli_limits(args: argparse.Namespace) -> ValidationLimits:
    limits = load_validation_limits(args.config) if args.config else ValidationLimits()
    return override_validation_limits(
        limits,
        cell_min_v=args.cell_min_v,
        cell_max_v=args.cell_max_v,
        imbalance_max_v=args.imbalance_limit_v,
        temperature_min_c=args.temp_min_c,
        temperature_max_c=args.temp_max_c,
    )


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        limits = _resolve_cli_limits(args)
        result = analyze_battery_log(args.path, limits=limits)
    except (OSError, TypeError, ValueError) as exc:
        parser.exit(2, f"error: {exc}\n")

    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
