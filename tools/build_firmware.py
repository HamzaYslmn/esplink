#!/usr/bin/env python3
"""Build the prebuilt firmware images that `esplink flash` ships and writes.

One image per supported board, copied into ``python/esplink/firmware/`` so it
gets bundled into the wheel:

- ``esp32``    classic ESP32, merged **Huge APP** image (3 MB app, no OTA —
               the documented default for end users, always reflash over USB)
- ``esp32s3``  ESP32-S3, merged Huge APP image on its native USB, 4 MB flash
               layout so it fits every S3 module
- ``promicro`` Pro Micro nRF52840 (nice!nano), a UF2 for its stock bootloader

    python tools/build_firmware.py                    # all three
    python tools/build_firmware.py esp32 esp32s3      # just these

Run in CI before `uv build`, or locally to refresh the bundled binaries. The
ESP targets need the esp32:esp32 core, ``promicro`` needs Seeeduino:nrf52 plus
``adafruit-nrfutil`` on PATH; the Pro Micro board definition (which neither
core ships) is copied in from ``tools/promicro/`` first.

IMPORTANT — local cache: arduino-cli keys its build cache by FQBN, and the
partition scheme is part of the FQBN, so building Huge APP here would normally
evict a warm Minimal-SPIFFS dev cache (~minutes to rebuild). To avoid that this
script compiles into a *dedicated, isolated* build + cache path under
``tools/.fw-build/`` — your day-to-day min_spiffs cache is left untouched.
"""
from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEST_DIR = REPO_ROOT / "python" / "esplink" / "firmware"
PROMICRO_DIR = REPO_ROOT / "tools" / "promicro"
# Isolated --build-path so the Huge APP build gets its own sketch build dir and
# never evicts the warm min_spiffs dev cache (the scheme is part of the FQBN, so
# a shared build dir would be thrown away on every scheme switch).
WORK_DIR = REPO_ROOT / "tools" / ".fw-build"

# target -> (FQBN, sketch, bundled file name)
TARGETS = {
    "esp32": ("esp32:esp32:esp32:PartitionScheme=huge_app",
              "Bridge", "bridge.esp32.huge_app.bin"),
    # hwcdc + CDCOnBoot: the same USB setup as the esp32s3 profile in
    # examples/Bridge/sketch.yaml. A board without OPI PSRAM boots anyway.
    "esp32s3": ("esp32:esp32:esp32s3:USBMode=hwcdc,CDCOnBoot=cdc,FlashSize=4M,"
                "PSRAM=opi,PartitionScheme=huge_app",
                "Bridge", "bridge.esp32s3.huge_app.bin"),
    # s140v6 = the stock bootloader's SoftDevice (see examples/Bridge_nRF52/sketch.yaml)
    "promicro": ("Seeeduino:nrf52:promicronRF52840:softdevice=s140v6",
                 "Bridge_nRF52", "bridge.promicro.uf2"),
}


def _run(cmd: list[str]) -> None:
    print("+", " ".join(cmd))
    subprocess.run(cmd, check=True)


def _seeed_core(cli: str) -> Path:
    """The installed Seeeduino nRF52 core folder."""
    out = subprocess.run([cli, "config", "get", "directories.data"],
                         check=True, capture_output=True, text=True).stdout
    roots = sorted(Path(out.strip()).glob("packages/Seeeduino/hardware/nrf52/*"))
    if not roots:
        raise SystemExit("Seeeduino:nrf52 core not installed (arduino-cli core install Seeeduino:nrf52)")
    return roots[-1]


def _install_promicro(core: Path) -> None:
    """Drop the Pro Micro board into the core. boards.local.txt is the platform
    spec's own door for extra boards, so the core's files are never edited."""
    variant = core / "variants" / "ProMicro_nRF52840"
    variant.mkdir(parents=True, exist_ok=True)
    for name in ("variant.h", "variant.cpp"):
        shutil.copy2(PROMICRO_DIR / name, variant / name)
    shutil.copy2(PROMICRO_DIR / "boards.local.txt", core / "boards.local.txt")


def _check(target: str, data: bytes) -> bool:
    if target == "promicro":
        return data[:4] == b"UF2\n"
    # A merged full-flash image starts with 0xFF padding; the 0xE9 ESP32 image
    # magic sits at the bootloader offset (0x1000 on classic ESP32/S2, 0x0 on
    # S3/C3). Accept either so the check works across chips.
    return len(data) > 0x1000 and (data[0] == 0xE9 or data[0x1000] == 0xE9)


def build(target: str, cli: str) -> Path:
    fqbn, sketch, dest_name = TARGETS[target]
    build_dir = WORK_DIR / target / "build"
    out_dir = WORK_DIR / target / "out"
    for d in (build_dir, out_dir):
        shutil.rmtree(d, ignore_errors=True)
    out_dir.mkdir(parents=True)

    core = None
    if target == "promicro":
        core = _seeed_core(cli)
        _install_promicro(core)

    cmd = [cli, "compile",
           "--fqbn", fqbn,
           "--library", str(REPO_ROOT),       # the repo root *is* the library
           "--build-path", str(build_dir),    # isolated: protects the dev cache
           "--output-dir", str(out_dir),
           str(REPO_ROOT / "examples" / sketch)]
    _run(cmd)

    if core:
        # The core's own uf2 step converts only for Seeed's LoRaWAN tracker, so
        # convert the hex here with the core's uf2conv (family = nRF52840).
        hexfile = next(out_dir.glob("*.hex"))
        _run([sys.executable, str(core / "tools" / "uf2conv" / "uf2conv.py"),
              "-f", "0xADA52840", "-c", "-o", str(out_dir / "bridge.uf2"), str(hexfile)])
        image = out_dir / "bridge.uf2"
    else:
        image = next(out_dir.glob("*.merged.bin"))

    DEST_DIR.mkdir(parents=True, exist_ok=True)
    dest = DEST_DIR / dest_name
    shutil.copy2(image, dest)
    data = dest.read_bytes()
    if not _check(target, data):
        raise SystemExit(f"built image doesn't look like a {target} image: {dest}")
    print(f"\nfirmware: {dest}")
    print(f"size    : {len(data) / 1024:.0f} KB")
    print(f"sha256  : {hashlib.sha256(data).hexdigest()}\n")
    return dest


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("targets", nargs="*", metavar="target",
                    help=f"boards to build: {', '.join(TARGETS)} (default: all)")
    ap.add_argument("--arduino-cli", default="arduino-cli",
                    help="arduino-cli executable (default: on PATH)")
    args = ap.parse_args(argv)
    unknown = set(args.targets) - TARGETS.keys()
    if unknown:
        ap.error(f"unknown target(s): {', '.join(sorted(unknown))}")
    for target in args.targets or TARGETS:
        build(target, args.arduino_cli)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
