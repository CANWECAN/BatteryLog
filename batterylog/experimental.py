"""Experimental offline workflows exposed by the BatteryLog command."""

import argparse
from collections.abc import Sequence


def run(argv: Sequence[str]) -> int:
    args = list(argv)
    if args and args[0] in {"can", "precharge"}:
        from batterylog_research.operator import main

        return int(main(args, prog="batterylog experimental"))
    if args and args[0] == "replay":
        from batterylog_research.can_replay import main as replay_main

        return int(replay_main(args[1:], prog="batterylog experimental replay"))
    parser = argparse.ArgumentParser(
        prog="batterylog experimental",
        description="Experimental offline observations; no physical diagnostic qualification.",
    )
    parser.add_argument("workflow", choices=["can", "precharge", "replay"])
    parser.parse_args(args)
    return 2
