# esplink (Arduino library)

Flash-once ESP32 firmware that exposes **every** peripheral to Python over USB
serial, **Bluetooth or Wi-Fi**. Install the library, flash the example, then
drive the board live from the host with `pip install esplink` — no
firmware edits per project. One line per link, in any order:

```cpp
#include <EspLink.h>
void setup() {
  EspLink.usb.begin();   // USB serial
  EspLink.ble.begin();   // Bluetooth, password "esplink"
  EspLink.run();         // hands this task to the bridge
}
void loop()  {}            // never runs unless you drop the run() call
```

```python
from esplink import Bridge
with Bridge() as esp:          # USB
    print(esp.info)            # chip, MAC, fw version, capabilities
with Bridge(ble=True) as esp:  # Bluetooth (default password "esplink")
    esp.gpio.write(2, 1)
```

GPIO, ADC/DAC, PWM, touch, I2C, SPI, UART, Wi-Fi sockets, BLE, ESP-NOW, RMT,
1-Wire, CAN, I2S, LittleFS/SD, NVS and OTA — all from Python.

## Install

- **Arduino IDE / CLI Library Manager:** search **`esplink`** and
  install. Then open *File → Examples → esplink → Bridge*.
- **Manual:** clone the repo into your `Arduino/libraries/` directory
  (`library.properties` sits at the repo root, so the clone *is* the library).

## Requirements

- **arduino-esp32 core 3.x** (Boards Manager → "esp32 by Espressif Systems").
  The 3.x LEDC/String APIs are required; it will not build on 2.x.
  Tested with **3.3.12** (classic ESP32, Minimal SPIFFS partition scheme).
- No external libraries. Bluetooth is the core's own `BLE` library, which runs
  Bluedroid on the classic ESP32 and NimBLE on S3/C3 behind one API, so the
  BLE link and `esp.ble` work on every chip with a radio.

## Nordic nRF52840 (Pro Micro / Seeed XIAO)

Pro Micro nRF52840 (nice!nano-style), from the repo root:

```sh
arduino-cli compile --profile promicro examples/Bridge_nRF52
arduino-cli upload  --profile promicro -p COM12 examples/Bridge_nRF52
```

The profile (`examples/Bridge_nRF52/sketch.yaml`) targets
`Seeeduino:nrf52:promicronRF52840:softdevice=s140v6` — a Pro Micro board
definition added to the Seeed nRF52 core; `s140v6` matches the stock bootloader
(a 0.9.x bootloader needs `s140v7`, or the upload succeeds and never boots).
Arduino pin numbers are the silkscreen numbers (SDA/SCL 4/5, ADC 19-21, LED 11;
12/13/17 drive on-board parts). Upload uses the 1200-baud touch, no double-tap.

The firmware also builds for the **nRF52840** on the Adafruit/Seeed **nRF52
(Bluefruit, FreeRTOS) core** — *not* the mbed-enabled core. The protocol, wire
format and Python host are identical; the nRF build just exposes a smaller,
capability-gated set of modules:

| Available | Not available on nRF52840 |
|---|---|
| BLE link (Nordic UART Service), GPIO (+ edge-watch), ADC, PWM, I2C, SPI, UART (2nd), 1-Wire, filesystem (LittleFS), NVS, deep sleep, BLE scan | Wi-Fi, ESP-NOW, NET sockets, DAC, touch, CAN, I2S, RMT, Ethernet, camera, MCPWM, OTA, SD card, BLE GATT server/client |

The host gates every call on `SYS_INFO` capabilities, so unavailable modules are
simply never offered; `esp.info.chip` reads `NRF52840`. Flash the
**`Bridge_nRF52`** example (same per-link `begin()` calls, minus Wi-Fi).

Notes specific to this build:
- **BLE transport** uses Bluefruit's `BLEUart`, whose UUIDs are exactly the
  bridge's link service — so the same `Bridge(ble=True)` host code connects.
- **PWM** maps `attach(freq, res)` onto the nRF HardwarePWM peripheral (duty
  resolution ≤ 14 bits; up to ~4 independent PWM pins).
- **ADC** is 12-bit; `read_mv` is a nominal `raw·3600/4095` (uncalibrated,
  default 0–3.6 V reference) — no per-pin attenuation.
- **I2C** reports its fixed Wire buffer size from `i2c.init`; the host chunks
  larger transfers (e.g. OLED frames) to fit.
- **SPI** is a single host; **UART** is port 1 (`Serial1`), pins via `setPins`.
- **Filesystem** is LittleFS on internal flash (id 0 only, no SD). The Adafruit
  wrapper allows **one open file at a time** (a second open replies `BUSY`),
  reports no mtime/usage (STAT mtime and DF totals are 0).
- **NVS** and the persistent **device name** (`SYS_SET_NAME`) are LittleFS-backed
  and survive reboot; NVS keys are stored as files under `/nvs/`.
- **GPIO edge-watch** uses GPIOTE (up to 8 watched pins via `attachInterrupt`).
- **Deep sleep** is nRF System OFF and requires a **wake pin** (no timer wake in
  System OFF; the board reboots on wake). Light sleep is unsupported.
- **BLE scan** works (observer role, coexists with the link); the BLE *GATT
  server/client* (`MOD_BLE` adv/GATTS/GATTC) is not implemented — the link owns
  the peripheral role and Bluefruit's GATT client uses static discovery.
- The firmware is single-core; the per-task priority/stack table in
  `src/esplink/config.h` uses nRF-appropriate values (word-counted stacks).

Source layout: the shared protocol core lives in `src/esplink/`, with the
per-architecture peripheral implementations split into `src/esp/` and
`src/nrf/` (each file whole-guarded by `ARDUINO_ARCH_ESP32` / `ARDUINO_ARCH_NRF52`).

## API

One link per line, in any order — the bridge core starts with the first of
them and is idempotent, so nothing has to be sequenced or remembered:

```cpp
void setup() {
  EspLink.usb.begin();                 // USB serial (never authenticated)
  EspLink.ble.begin();                 // password defaults to "esplink"
  EspLink.wifi.begin("ssid", "pass");  // TCP link, port 3232
  EspLink.run();                       // optional: frees the 8 KB loop stack
}
void loop() { /* yours, unless run() was called */ }
```

| call | what it does |
|---|---|
| `usb.begin()` | starts the core; USB serial link |
| `ble.begin(password = "esplink")` | BLE link; `""` = open access |
| `wifi.begin(ssid, pass)` | joins and **listens** on port 3232 |
| `wifi.begin(ssid, pass, "10.0.0.5")` | **dials out** to your host, reconnecting forever (`Bridge.all(wifi=True)` accepts it) |
| `wifi.begin()` | uses credentials provisioned over USB/BLE (NVS) |
| `wifi.end()` | drops the link, gives the Wi-Fi heap back |
| `run()` | deletes the loop task and never returns |

`wifi.begin()` returns `false` if the link could not be armed (no credentials,
not enough heap, or ESP-NOW already owns the radio) — the board runs on
without it. A board provisioned once with `esp.wifi.link_setup(...)` starts its
link automatically on every later boot, so the prebuilt image is fleet-capable
with no reflash.

**Radio combinations.** BLE + Wi-Fi link coexist, but the firmware then keeps
Wi-Fi modem sleep on (`WIFI_PS_NONE` destabilises the coex arbiter), which
roughly triples link latency, and a classic ESP32 runs ~10 KB free with both —
measured 108 KB with the Wi-Fi link alone. ESP-NOW and the Wi-Fi link are
mutually exclusive (`ST_BUSY`): ESP-NOW owns the radio channel and an AP
association cannot survive it.

The first `begin()` spins up the FreeRTOS task model — separate TX / RX /
blocking-handler tasks, so a blocking TCP or BLE connect never stalls
GPIO/I2C/SPI. `run()` then deletes the Arduino loop task to hand its 8 KB stack
back to the heap, which a classic ESP32 running Wi-Fi + Bluetooth needs badly.
Omit `run()` and `loop()` keeps running instead: the sketch can do its own work
(on core 1, next to the command handlers) while the bridge serves the host, at
the cost of that 8 KB — fine for USB-only boards, risky with BLE + Wi-Fi up.

On dual-core chips the bridge uses **both cores**, grouped by domain: core 0
(the radio core) carries the Wi-Fi/BT stacks plus the TX path and the
blocking handlers that call into those stacks; core 1 (the app core) runs RX
and every bus-touching handler — including 1-Wire, whose IRQ-masking bit
timing must stay away from radio interrupts. Reply N transmits on core 0
while command N+1 executes on core 1. See `src/esplink/config.h` for the
named per-task core/priority/stack table.

Authentication is per link: USB never asks for a password (holding the cable is
the credential), while BLE and Wi-Fi require the client to send `SYS_AUTH` with
the password before any command is accepted. `""` makes a wireless link open.

## Partition scheme (pick one)

The Wi-Fi + BLE build needs a >1.2 MB app slot, so the **default table won't
fit** — choose one in *Tools → Partition Scheme* at the first USB flash:

| Scheme | App | OTA? | Pick when |
|---|---|---|---|
| **Huge APP (3MB No OTA/1MB SPIFFS)** | 3 MB | no | default — biggest app; you always reflash over USB |
| **Minimal SPIFFS (1.9MB APP with OTA)** | 1.9 MB | yes | you want cable-free firmware updates |

OTA (`esplink.ota`, USB *or* Bluetooth) updates the firmware binary itself —
the cable-free complement to the link for deployed boards. It needs the OTA
partition above; on Huge APP there's no OTA slot, so `esp.ota` replies
`unsupported` (expected, not a bug).

> **Compile-speed tip:** arduino-cli caches the build per FQBN, and the
> partition scheme is part of the FQBN — alternating schemes between compiles
> throws the sketch cache away each time (~minutes per build). Pick one scheme
> for all your boards, compile once, then `arduino-cli upload -p <port>` per
> board reuses the cached binaries.

## Flash without the Arduino IDE (`esplink flash`)

The host package ships a **prebuilt Huge APP image** of the example sketch, so
the first flash can happen straight from the host — no Arduino IDE, no
toolchain. It lists the serial ports, lets you pick one, and writes the image
over USB with esptool:

```sh
uvx --from "esplink[flash]" flash   # zero-install via uv
# or install once:  uv tool install "esplink[flash]"  /  pip install "esplink[flash]"
flash                # list ports and choose (also: esplink flash)
flash -p COM5        # flash a specific port
flash --erase        # wipe the whole flash first (clears NVS / name)
flash --firmware my.bin   # flash your own image instead
```

The bundled image is a **classic-ESP32 Huge APP** build (no OTA — for cable-free
updates afterwards, build/flash the Minimal SPIFFS scheme yourself and use
`esplink.ota`). It is regenerated from `examples/Bridge` by
`tools/build_firmware.py` (run in CI before each release), so it always matches
the published version.

## Optional peripherals (compile-time)

Ethernet and camera cost real flash, so they're **off by default**; board pin
maps live on the Python side (`esplink.eth` / `esplink.camera` presets), so
one build serves every board. Because Arduino compiles each library source as
its own unit, enable these with a global build flag rather than a sketch
`#define`:

```sh
# arduino-cli
arduino-cli compile --fqbn esp32:esp32:esp32:PartitionScheme=huge_app \
  --build-property "build.extra_flags=-DBRIDGE_ENABLE_ETH=1" Bridge
```

Flags: `BRIDGE_ENABLE_ETH=1` (RMII or SPI W5500), `BRIDGE_ENABLE_CAM=1`
(OV-series + PSRAM on esp32/s2/s3), `BRIDGE_ENABLE_BLE=0` (USB-only build),
`BRIDGE_SINGLE_CORE=<0|1>` (pin all bridge tasks to one core instead of the
default dual-core layout: `1` leaves the radio core untouched, `0` leaves
core 1 entirely to the sketch — pair with omitting `EspLink.run()`).

**Classic-ESP32 IRAM trade-off:** with Wi-Fi + BLE loaded the SD-card drivers
don't fit the chip's instruction RAM, so the default classic build ships without
SD (LittleFS and deep/light sleep work). Building with `-DBRIDGE_ENABLE_BLE=0`
frees the BT IRAM and re-enables SD and SDMMC. S3 and C3 have everything in
every build.

## Bluetooth discovery

The board advertises as `esplink_<name>` — or `esplink_<mac>` until you name
it — so the string you address it by is visible before connecting.
`esplink scan --ble` lists every bridge in range; `esplink set-name relays`
assigns a name (max 16 characters, so it fits the advertisement; updates on the
next reset).

## Layout

```
library.properties      Library Manager metadata
keywords.txt            IDE syntax highlighting
examples/Bridge/        the one-line example sketch
src/EspLink.*    public API (EspLink.usb/ble/wifi/run)
src/esplink/          bridge core: protocol contract, framing, links, config
src/mod_*.cpp           peripheral/task modules (GPIO, I2C, Wi-Fi, BLE, ...)
src/link_ble.cpp        Bluetooth transport (NUS-style GATT service)
```

Wire protocol: see [`docs/PROTOCOL.md`](https://github.com/HamzaYslmn/esplink/blob/main/docs/PROTOCOL.md).
The contract constants in `src/esplink/commands.h` mirror the Python
package's `esplink/constants.py`.
