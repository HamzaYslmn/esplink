"""Flash the bundled bridge firmware to a board over USB — no Arduino IDE.

Prebuilt images ship inside the package, one per supported board: merged
"Huge APP" (3 MB app, no OTA) images of ``examples/Bridge`` for the classic
ESP32 and the ESP32-S3, written with esptool, and a UF2 of
``examples/Bridge_nRF52`` for the Pro Micro nRF52840, copied onto its
bootloader drive. The board is picked from the port's USB ID (or, behind a
USB-UART bridge, by asking the chip); ``--chip`` overrides it.

    esplink flash               # list ports, pick one, flash
    esplink flash -p COM5       # flash a specific port
    esplink flash --erase       # wipe the whole flash first (clears NVS)

The ESP32 boards need the [flash] extra (pulls in esptool):

    uvx --from "esplink[flash]" esplink flash
    pip install "esplink[flash]"

This is the one-time initial flash over the cable. Once the firmware is
running, later updates can also go over the air with ``esplink.ota`` — but
note the Huge APP image bundled here has no OTA partition, so cable-free
updates need the Minimal SPIFFS scheme instead (see docs/FIRMWARE.md).
"""
from __future__ import annotations

import contextlib
import shutil
import string
import sys
import time
from importlib import resources
from pathlib import Path

from ._log import log
from .errors import BridgeError
from .transports import PortInfo, find_ports

# The bundled ESP images are Huge APP builds: one merged image that already
# carries the bootloader + partition table + app, written at 0x0.
CHIPS = ("esp32", "esp32s3", "promicro")
FIRMWARE_OFFSET = "0x0"
DEFAULT_BAUD = 921600  # Arduino's default upload speed; safe on every adapter
_FIRMWARE_PKG = "esplink.firmware"


def firmware_path(chip: str = "esp32") -> Path:
    """Filesystem path to the bundled firmware image for `chip`.

    Raises BridgeError when the package was built without the binary — e.g. a
    source checkout that hasn't run ``tools/build_firmware.py`` yet. Release
    wheels from PyPI always include it.
    """
    try:
        root = resources.files(_FIRMWARE_PKG)
        for entry in root.iterdir():
            if entry.name.startswith(f"bridge.{chip}.") and entry.is_file():
                # Wheels install unzipped, so the traversable is a real path.
                return Path(str(entry))
    except (ModuleNotFoundError, FileNotFoundError):
        pass
    if chip not in CHIPS:
        raise BridgeError(f"no bundled image for chip {chip!r} (have: {', '.join(CHIPS)}); "
                          "pass --firmware <path>")
    raise BridgeError(
        f"no bundled {chip} firmware image found — this build of esplink "
        "shipped without the prebuilt binary.\n"
        "Build it with `python tools/build_firmware.py`, install a release "
        "wheel (`pip install esplink`), or pass --firmware <path>."
    )


def _all_serial_ports() -> list[PortInfo]:
    """Every serial port, ESP32-like or not — a blank board may enumerate on an
    adapter we don't recognise, so don't hide ports just because the VID/PID
    isn't in the known list."""
    from serial.tools import list_ports

    return [PortInfo(p.device, None, p.description or "")
            for p in list_ports.comports() if p.device]


def _choose_port(ports: list[PortInfo]) -> str:
    """Print a numbered menu and read the operator's choice (Enter picks #1)."""
    print("Available serial ports:")
    for i, p in enumerate(ports, 1):
        chip = f"  [{p.usb_chip}]" if p.usb_chip else ""
        desc = f"  {p.description}" if p.description else ""
        print(f"  {i}) {p.device}{chip}{desc}")
    prompt = f"Select a port [1-{len(ports)}, Enter = 1, q = cancel]: "
    while True:
        try:
            raw = input(prompt).strip()
        except EOFError:
            raise BridgeError("no port selected (no interactive console; "
                              "pass -p PORT explicitly)")
        if raw.lower() in ("q", "quit"):
            raise BridgeError("cancelled")
        if raw == "":  # bare Enter → the first (most likely) port
            return ports[0].device
        if raw.isdigit() and 1 <= int(raw) <= len(ports):
            return ports[int(raw) - 1].device
        for p in ports:  # also accept typing the port name directly
            if raw.lower() == p.device.lower():
                return p.device
        print("  invalid selection — enter a number from the list")


def select_port(port: str | None = None) -> str:
    """Resolve a port: honour an explicit one, else show the menu (or, with no
    interactive console, auto-pick a lone port)."""
    if port:
        return port
    ports = find_ports() or _all_serial_ports()
    if not ports:
        raise BridgeError("no serial ports found — plug the ESP32 in over USB, "
                          "or pass -p PORT")
    interactive = bool(getattr(sys.stdin, "isatty", lambda: False)())
    if not interactive:  # piped/CI: can't prompt, so a lone port or bust
        if len(ports) == 1:
            log.info(f"using the only serial port found: {ports[0].device}")
            return ports[0].device
        names = ", ".join(p.device for p in ports)
        raise BridgeError(f"several serial ports ({names}); pass -p PORT "
                          "(no interactive console to choose from)")
    return _choose_port(ports)


def detect_chip(port: str) -> str:
    """Pick the board: a native USB ID names it; behind a USB-UART bridge (a
    classic DevKit, or an S3's UART port) ask the chip itself."""
    from serial.tools import list_ports

    vid = next((p.vid for p in list_ports.comports() if p.device == port), None)
    # ponytail: 303A is every Espressif native-USB chip, not just the S3; on a
    # C3/C6 esptool refuses the S3 image (wrong chip) and --chip picks the right one.
    if vid in (0x303A, 0x239A):
        return {0x303A: "esp32s3", 0x239A: "promicro"}[vid]
    try:
        import esptool
        with esptool.detect_chip(port) as esp:
            return "esp32s3" if esp.CHIP_NAME == "ESP32-S3" else "esp32"
    except Exception:  # no esptool or no answer: write-flash reports the real error
        return "esp32"


def _uf2_drives() -> list[Path]:
    """Mounted UF2 bootloader drives (they all carry an INFO_UF2.TXT)."""
    if sys.platform == "win32":
        roots = [Path(f"{c}:/") for c in string.ascii_uppercase[2:]]
    else:
        roots = [*Path("/Volumes").glob("*"), *Path("/media").glob("*/*"),
                 *Path("/run/media").glob("*/*")]
    return [r for r in roots if (r / "INFO_UF2.TXT").is_file()]


def _flash_uf2(port: str, fw: Path, timeout: float = 15.0) -> None:
    """Pro Micro nRF52840: a 1200-baud touch drops the app into its UF2
    bootloader, which mounts a drive; copying the .uf2 onto it is the flash."""
    import serial

    if not _uf2_drives():
        with contextlib.suppress(serial.SerialException):
            serial.Serial(port, 1200).close()
    deadline = time.monotonic() + timeout
    while not (drives := _uf2_drives()):
        if time.monotonic() > deadline:
            raise BridgeError("no UF2 bootloader drive appeared — double-tap the "
                              "board's reset button and run this again")
        time.sleep(0.25)
    log.info(f"copying {fw.name} to {drives[0]}")
    try:
        shutil.copyfile(fw, drives[0] / fw.name)
    except OSError:
        # The bootloader reboots into the app as soon as the last block lands,
        # which some OSes report as a failed copy: only a drive still there is one.
        if (drives[0] / "INFO_UF2.TXT").exists():
            raise


def flash_firmware(port: str | None = None, *,
                   baud: int = DEFAULT_BAUD,
                   erase: bool = False,
                   firmware: str | Path | None = None,
                   chip: str = "auto") -> None:
    """Write the (bundled, or given) firmware image to a board over USB.

    ESP32 boards: drives esptool exactly the way the Arduino toolchain does for
    the initial cable flash. Pro Micro: copies the UF2 onto its bootloader
    drive. Raises BridgeError on any failure.
    """
    port = select_port(port)
    if chip == "auto":
        chip = detect_chip(port)
        log.info(f"board: {chip} (--chip overrides)")
    fw = Path(firmware) if firmware else firmware_path(chip)
    if not fw.is_file():
        raise BridgeError(f"firmware image not found: {fw}")

    if fw.suffix == ".uf2":
        if erase:
            raise BridgeError("--erase is for the ESP32 boards only")
        _flash_uf2(port, fw)
        log.info("done — the board reboots into the bridge firmware "
                 "(connect with `esplink info`)")
        return

    try:
        import esptool
    except ModuleNotFoundError:
        raise BridgeError(
            "esptool is required to flash. Install the [flash] extra:\n"
            '  pip install "esplink[flash]"\n'
            '  uvx --from "esplink[flash]" esplink flash'
        )

    # All-dashed spellings throughout: esptool 5 renamed every underscore form
    # and the [flash] extra requires >=5, so there is no older syntax to serve.
    argv = ["--chip", chip, "--port", port, "--baud", str(baud),
            "--before", "default-reset", "--after", "hard-reset", "write-flash"]
    if erase:
        argv.append("--erase-all")
    argv += ["--flash-size", "keep", FIRMWARE_OFFSET, str(fw)]

    size_kb = fw.stat().st_size / 1024
    log.info(f"flashing {fw.name} ({size_kb:.0f} KB) to {port} at {baud} baud")
    try:
        esptool.main(argv)
    except SystemExit as e:  # esptool calls sys.exit() on argument/connect errors
        if e.code:
            raise BridgeError(f"esptool exited with status {e.code}")
    except Exception as e:  # FatalError and friends — surface a clean message
        raise BridgeError(f"flash failed: {e}")
    log.info("done — the board will reboot into the bridge firmware "
             "(connect with `esplink info`)")


def main(argv: list[str] | None = None) -> int:
    """The standalone `flash` command (``uvx --from "esplink[flash]" flash``):
    exactly `esplink flash`."""
    from .cli import main as cli_main

    return cli_main(["flash", *(sys.argv[1:] if argv is None else argv)])


if __name__ == "__main__":
    raise SystemExit(main())
