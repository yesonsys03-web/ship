import os
import sys

from ship_sender.server import main


def ensure_standard_streams() -> None:
    if sys.stdin is None:
        sys.stdin = open(os.devnull, "r", encoding="utf-8")
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")


if __name__ == "__main__":
    ensure_standard_streams()
    main()
