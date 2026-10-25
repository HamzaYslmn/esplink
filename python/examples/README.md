# Examples

Flash the firmware once ([`../../docs/FIRMWARE.md`](../../docs/FIRMWARE.md)), plug
the board in (or power it anywhere for Bluetooth), then run any example with
[uv](https://docs.astral.sh/uv/) from this folder; the local `esplink` package is
installed automatically, editable:

```sh
cd python/examples
uv run basics/blink.py
uv run wireless/ble_blink.py            # the same, over Bluetooth
```

Each file is one idea in a few lines, with no command-line arguments: settings
(pins, Wi-Fi credentials, board names) are constants at the top — edit and run.
`Bridge()` takes the first board it finds (USB, then Bluetooth, then Wi-Fi);
`Bridge("relays")` picks one by name or MAC on any link.

## basics/

| example | shows |
|---|---|
| `blink.py` | GPIO output |
| `button_interrupt.py` | edge interrupt with debounce -> Python callback |
| `adc_dac.py` | ADC read (raw + mV), DAC output and cosine generator |
| `pwm_servo.py` | PWM fade, servo, buzzer tone |
| `i2c_scan.py` | I2C bus scan |
| `spi_transfer.py` | SPI transfer (flash JEDEC ID) |
| `uart_loopback.py` | second UART for GPS / modems |
| `touch_read.py` | capacitive touch: read, then board-pushed events |
| `watch_threshold.py` | on-device watch rules: events on a condition, plus on-board actions |
| `async_fanout.py` | `AsyncBridge` + `asyncio.gather` |
| `shared_connection.py` | `esplink.connect()`: one auto-reconnecting link shared by threads |
| `rtos_concurrency.py` | a blocking Wi-Fi scan doesn't slow pings from another thread |
| `many_boards.py` | `Bridge.all()`: every board at once, over USB/BLE or Wi-Fi |

## devices/ (pure-Python drivers, `esp.<driver>(...)`)

| example | shows |
|---|---|
| `neopixel_rainbow.py` | WS2812 / NeoPixel strip |
| `dht_read.py` | DHT22 / DHT11 temperature + humidity |
| `ds18b20_temp.py` | DS18B20 1-Wire thermometers |
| `hcsr04_ping.py` | HC-SR04 ultrasonic distance |
| `ir_remote.py` | NEC IR remote receive (and send) |
| `stepper_move.py` | A4988 / DRV8825 stepper |
| `can_dump.py` | CAN bus monitor + heartbeat frame |
| `i2s_record.py` | I2S microphone -> WAV file |
| `custom_driver.py` | your own driver in a dozen lines (`register_driver`) |

`esplink drivers` lists every driver; [`../../docs/DRIVERS.md`](../../docs/DRIVERS.md) covers writing one.

## displays/

| example | shows |
|---|---|
| `oled_ssd1306.py` | SSD1306 OLED with PIL drawing |
| `ble_oled.py` | the same display over Bluetooth |

## network/ (Wi-Fi through the ESP32's radio)

| example | shows |
|---|---|
| `wifi_scan.py` | list Wi-Fi networks |
| `wifi_ap.py` | the ESP32 as an access point |
| `sockets.py` | HTTP, TCP and UDP through the ESP32 |
| `wifi_link.py` | control the board over Wi-Fi instead of a cable |

## wireless/ (Bluetooth, ESP-NOW)

| example | shows |
|---|---|
| `ble_blink.py` | GPIO over Bluetooth, no cable (password defaults to `esplink`) |
| `ble_scan.py` | the ESP32 as a BLE scanner |
| `espnow_broadcast.py` | ESP-NOW broadcast between any number of boards |
| `espnow_pingpong.py` | ESP-NOW unicast with delivery ACKs, two boards |
| `coex_all_radios.py` | Bluetooth link + ESP-NOW + Wi-Fi AP at once |
| `usb_vs_ble_benchmark.py` | latency and throughput, USB vs Bluetooth |

## system/

| example | shows |
|---|---|
| `nvs_counter.py` | key/value storage that survives power-off |
| `fs_logger.py` | files on the board's flash (LittleFS) |
| `deep_sleep.py` | deep sleep + timer wake |
| `power_profiles.py` | lower CPU clock + battery Bluetooth profile |
| `ota_update.py` | reflash the firmware over the link |
| `mcp_server.py` | MCP server for AI agents, with a custom tool |
| `multi_client.py` | several programs sharing one board through the MCP server |

## compat/ (existing Raspberry Pi / CircuitPython code, unchanged)

| example | ecosystem |
|---|---|
| [`compat/rpi_gpio/`](compat/rpi_gpio/) | **RPi.GPIO** scripts |
| [`compat/gpiozero/`](compat/gpiozero/) | **gpiozero** LED / Button / MCP3008 |
| [`compat/spidev/`](compat/spidev/) | **spidev** (MCP3008) |
| [`compat/smbus/`](compat/smbus/) | **smbus2** I2C register access |
| [`compat/adafruit/`](compat/adafruit/) | **Adafruit CircuitPython** drivers (BME280) |
| [`compat/luma/`](compat/luma/) | **luma.oled** |

## Tips

- **Name your boards** (`esplink -p COM7 set-name relays`): COM numbers move,
  names don't, and `Bridge("relays")` works over USB, Bluetooth and Wi-Fi.
- **Opening the serial port resets the board.** `Bridge(reset_on_open=False)`
  re-attaches with the running state intact.
- **Long-running scripts:** `esplink.connect(keepalive=5)` reconnects by itself
  after an unplug or reset.
- **Classic ESP32 over Bluetooth:** each extra radio (Wi-Fi, ESP-NOW) costs
  ~50 KB of heap; call `wifi.disconnect()` / `espnow.end()` when done, since
  nothing resets a Bluetooth-linked board between sessions.
