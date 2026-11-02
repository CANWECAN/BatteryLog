"""Optional desktop entry point; help remains available without Tcl/Tk."""

import argparse
import sys
from collections.abc import Sequence


def run(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Open the BatteryLog desktop launcher.")
    parser.parse_args(argv)
    try:
        import tkinter  # noqa: F401 - verify the optional dependency before importing the UI
    except ImportError:
        print("error: Desktop mode requires Python with Tkinter/Tcl/Tk support.", file=sys.stderr)
        return 4
    from .desktop_ui import launch

    return launch()


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
