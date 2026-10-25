# esplink

[Türkçe README](docs/README-TR.md)

Flash one firmware onto an ESP32 once, then drive **every peripheral** from
Python or JavaScript — over USB, Bluetooth or Wi-Fi. GPIO, PWM, ADC, DAC, touch,
I2C, SPI, UART, RMT, 1-Wire, CAN, I2S, files, NVS, sleep, Wi-Fi sockets, BLE,
ESP-NOW, Ethernet, camera, OTA. No reflashing per project.

The firmware exposes small hardware primitives; device protocols (WS2812, NEC IR,
DHT, 1-Wire search, stepper ramps) live on the host, where they are easy to read
and change.

![OLED driven over the bridge](docs/img/oled.png)

## Install

```sh
pip install esplink               # USB + Bluetooth + Wi-Fi
pip install "esplink[oled]"       # + Pillow for displays   ([mcp], [flash], [all])
npm i @hamzayslmn/esplink         # JavaScript: browser and Node
```

**Flash the firmware once** — the prebuilt image, no Arduino IDE needed:

```sh
uvx --from "esplink[flash]" flash
```

Or build it: install the **esplink** library in the Arduino IDE (core 3.x) and
upload *File → Examples → esplink → Bridge*. With arduino-cli the repo's
`sketch.yaml` picks the board, so no `--fqbn`:

```sh
arduino-cli compile examples/Bridge && arduino-cli upload -p COM3 examples/Bridge
```

Details and build flags: [docs/FIRMWARE.md](docs/FIRMWARE.md).

## Use

```python
from esplink import Bridge

with Bridge() as esp:                     # USB first, then Bluetooth, then Wi-Fi
    esp.gpio.mode(esp.pins.led, "output") # the board's LED (S3/C3: a WS2812 on esp.pins.rgb)
    esp.gpio.write(esp.pins.led, 1)       # returns the pin's read-back level
    print(esp.adc.read_mv(34), "mV")
    esp.pwm.servo(13, angle=90)
    esp.i2c.init()                        # the board's SDA/SCL; or init(sda=1, scl=2)
    print(esp.i2c.scan())
```

### Pick a board and a link

```python
Bridge("relays")                    # by name (esplink set-name relays) or MAC
Bridge(port="COM7")                 # a serial port
Bridge(ble=True)                    # Bluetooth only   (ble=False: USB only)
Bridge(host="192.168.1.50")         # Wi-Fi; wifi=True finds boards by broadcast
Bridge(ble=True, password="...")    # wireless links authenticate (default "esplink")
```

A link keyword pins the link — no silent fallback. On the command line:
`esplink` (info), `esplink ports`, `esplink scan [--ble]`, `esplink set-name NAME`.

### Peripherals

| | |
|---|---|
| `esp.gpio` | modes, read/write, `write_many`, `status`, edge interrupts → callbacks (µs timestamps) |
| `esp.adc` / `dac` / `touch` | mV reads, true 8-bit DAC + cosine generator, touch pads |
| `esp.pwm` / `mcpwm` | LEDC duty/tone/servo; complementary pairs with deadtime |
| `esp.i2c` / `spi` / `uart` | buses on the board's default pins (`esp.pins`) or any you name; UART ports behave like pyserial |
| `esp.rmt` / `onewire` | pulse trains and 1-Wire primitives (the drivers below) |
| `esp.can` / `i2s` | TWAI bus; PCM in/out |
| `esp.fs` / `nvs` / `ota` | LittleFS/SD files; key/value store; firmware update over the link |
| `esp.wifi` / `net` / `eth` | join/AP/scan; TCP/UDP sockets through the board; Ethernet |
| `esp.ble` / `espnow` | scan, advertise, GATT server/client; ESP-NOW messaging |
| `esp.watch` | rules the board evaluates itself — and acts on, `do=("gpio", 26, 1)` |
| `esp.camera` | JPEG snapshots (ESP32-CAM, XIAO-S3-Sense) |
| `esp.deep_sleep` / `light_sleep` / `cpu_freq` / `radio_off` | power |

### Drivers

24 bundled, all pure Python: `neopixel`, `dht`, `ds18b20`, `hcsr04`, `ir_sender`,
`stepper`, `oled`, `bme280`, `mpu6050`, `ads1115`, `pca9685`, `motor`, `nrf24`,
`sx127x`… (`esplink drivers` lists them).

```python
strip = esp.neopixel(pin=5, n=30)
strip.fill((0, 0, 64)); strip.show()
print(esp.dht(4).read())                          # (23.1, 65.5)
with esp.oled(sda=21, scl=22).draw() as d:        # PIL drawing
    d.text((0, 0), "Hello!", fill=1)
```

A driver is any class that takes the bridge first; `register_driver("name", cls)`
adds the `esp.name(...)` shortcut. Guide: [docs/DRIVERS.md](docs/DRIVERS.md).

### Raspberry Pi code, unchanged

The Pi's own APIs run against the ESP32's pins — **gpiozero**, **RPi.GPIO**,
**spidev**, **smbus2**, **Adafruit CircuitPython** and **luma**. Pin numbers are
ESP32 GPIO numbers.

```sh
python -m esplink.compat --board relays blink.py    # an unmodified Pi script
```

```python
from esplink import Bridge, compat

compat.install(Bridge())             # RPi.GPIO, spidev, smbus2 + gpiozero now mean the ESP32
from gpiozero import LED, Button
led, btn = LED(2), Button(4)
btn.when_pressed = led.toggle        # callbacks may drive pins freely
```

On top of what a Pi has: real ADC and DAC, capacitive touch, PWM on any pin,
ESP-NOW, on-device rules (`esp.watch`), sleep, OTA — and it works over Bluetooth.

### Threads and asyncio

One `Bridge` is thread-safe and pipelines concurrent requests; the firmware's
RTOS tasks run them side by side, so a slow Wi-Fi call never stalls a GPIO read.

```python
import esplink, asyncio
from esplink import AsyncBridge, constants as C
from esplink.gpio import EdgeEvent

async def main():
    async with AsyncBridge(ble=False) as esp:     # or AsyncBridge.wrap(esplink.connect())
        level, mv = await asyncio.gather(esp.gpio.write(2, 1), esp.adc.read_mv(34))
        await esp.gpio.watch(4, edge="falling")
        async for ev in esp.events(C.GPIO_EDGE_EVT, EdgeEvent.parse):
            print(ev.pin, ev.level)

asyncio.run(main())
```

### Many boards, Wi-Fi

```python
with Bridge.all() as boards:                      # every board on the desk
    boards.each(lambda esp: esp.ping())           # -> {ident: result}
    boards["relays"].gpio.write(2, 1)

with Bridge(port="COM3") as usb:                  # provision Wi-Fi once
    usb.wifi.link_setup("ssid", "pw")             # or server="10.0.0.5" to dial home
with Bridge.all(wifi=True) as boards:
    boards.wait_for(100, timeout=60)              # dial-home boards keep arriving
```

## JavaScript

Same protocol and the same names as Python (`esp.info.fw_version`, `esp.adc.read_mv`, …) — [js/README.md](js/README.md).

```js
import { connect_serial, connect_ble } from "@hamzayslmn/esplink/web";   // or "@hamzayslmn/esplink/node"
const esp = await connect_serial();                          // from a click handler
await esp.gpio.write(2, 1);
console.log(await esp.adc.read_mv(34));
```

## AI agents (MCP)

`esplink-mcp` exposes one tool per API method to Claude Code, Gemini CLI, Codex,
Cursor and Ollama clients ([docs/MCP.md](docs/MCP.md)):

```sh
uv tool install "esplink[mcp]"
```

## Speed

Measured on real boards, Windows 11 host:

| | classic ESP32 (CP2102) | ESP32-S3 (native USB) | nRF52840 Pro Micro |
|---|---|---|---|
| USB ping p50 / p99 | 1.9 / 2.1 ms | 0.23 / 0.36 ms | 0.30 / 0.43 ms |
| USB connect | 1–2.5 s (resets the board) | 0.01 s | 0.01 s |
| USB pipelined (8 threads) | 3,800 req/s | 7,500–9,200 req/s | 4,400 req/s |
| BLE ping p50 | 15 ms | 15 ms | 15 ms |
| file read USB / BLE | 142 / 40 KB/s | 749 / 67 KB/s | 246 / 27 KB/s |
| GPIO edge → host event | | +0.16 ms | |
| I2C register read | | 0.38 ms | |
| OLED 128×64, typical / full frame | | 477 / 33 fps (58 at 1 MHz I2C) | |

The host spends about 20 µs per request. A BLE round trip is two connection
intervals: the board asks for exactly 7.5 ms, which Windows grants about 2 s
after connecting (offered a 7.5–15 ms range, it picks 15).

## Hardware

| board | build | notes |
|---|---|---|
| classic **ESP32** (CP2102/CH340) | `arduino-cli compile examples/Bridge` | everything; with BLE there's no room for SD (LittleFS works) |
| **ESP32-S3** (native USB or UART port) | `--profile esp32s3` | both USB ports are links; light sleep needs a non-USB link |
| **ESP32-C3** | `--fqbn esp32:esp32:esp32c3:CDCOnBoot=cdc,PartitionScheme=min_spiffs` | compile-checked |
| **nRF52840** Pro Micro | `--profile promicro examples/Bridge_nRF52` | BLE, GPIO, ADC, PWM, I2C, SPI, UART, 1-Wire, files, NVS, sleep |

arduino-esp32 core 3.x (tested 3.3.12). The firmware reports what each chip
has; anything missing raises `UnsupportedError`. Pins the board is using for
its host link are refused with `BAD_PIN`. Details: [docs/FIRMWARE.md](docs/FIRMWARE.md).

## Troubleshooting

Errors name the command and what to check, and a timeout pings the board to say
whether the link died or one frame got lost. `ESPLINK_DEBUG=1 python app.py`
traces every request; `esp.free_heap()` reports heap and dropped-frame counters.

## Layout

| path | |
|---|---|
| `src/`, `examples/Bridge/` | Arduino library: the firmware and its sketch |
| `python/` | Python package `esplink`, tests, examples |
| `js/` | JavaScript package `esplink` |
| `docs/` | [protocol](docs/PROTOCOL.md), [firmware](docs/FIRMWARE.md), [drivers](docs/DRIVERS.md), [MCP](docs/MCP.md) |
