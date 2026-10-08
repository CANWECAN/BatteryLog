"""Private CLI wrapper accepting one cancellation byte on its owned stdin pipe."""

import _thread
import os
import threading

from .__main__ import main as cli_main


def _wait_for_cancel() -> None:
    try:
        command = os.read(0, 1)
    except OSError:
        return
    if command == b"\x03":
        _thread.interrupt_main()


def main() -> None:
    try:
        # Raw fd reads avoid holding a buffered-stdin lock during interpreter shutdown.
        threading.Thread(target=_wait_for_cancel, daemon=True).start()
        cli_main()
    except KeyboardInterrupt:
        # The batch CLI unwinds through its existing summary-writing finally block.
        raise SystemExit(130)


if __name__ == "__main__":
    main()
