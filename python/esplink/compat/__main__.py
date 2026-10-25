"""Run an unmodified Raspberry Pi script against an ESP32.

    python -m esplink.compat [--board NAME] script.py [args...]

``import RPi.GPIO``, ``spidev``, ``smbus2``/``smbus`` and gpiozero's default
pin factory all resolve to the board (see :func:`esplink.compat.install`).
"""
import argparse
import runpy
import sys

from ..bridge import Bridge
from . import install


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="python -m esplink.compat", description=__doc__.split("\n")[0])
    ap.add_argument("--board", help="board name or MAC (default: the first one found)")
    ap.add_argument("script")
    ap.add_argument("args", nargs=argparse.REMAINDER)
    a = ap.parse_args(argv)
    with Bridge(a.board) as esp:
        install(esp)
        sys.argv = [a.script, *a.args]
        runpy.run_path(a.script, run_name="__main__")


if __name__ == "__main__":
    main()
