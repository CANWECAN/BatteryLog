import argparse
import json

from .analysis.core import analyze_battery_log


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Analyze EV battery test data.")
    parser.add_argument("path", help="Path to a battery CSV log")
    parser.add_argument(
        "--imbalance-limit-v",
        type=float,
        default=0.08,
        help="Maximum allowed cell-voltage spread in volts (default: 0.08)",
    )
    parser.add_argument(
        "--temp-warning-c",
        type=float,
        default=45.0,
        help="Temperature warning threshold in degC (default: 45.0)",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        result = analyze_battery_log(
            args.path,
            imbalance_limit_v=args.imbalance_limit_v,
            temp_warning_c=args.temp_warning_c,
        )
    except (OSError, ValueError) as exc:
        parser.exit(2, f"error: {exc}\n")

    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
