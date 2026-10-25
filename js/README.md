# esplink for JavaScript

Drive an ESP32 running the esplink firmware from a web page or from Node — same
wire protocol and **the same names** as the Python package ([`../python`](../python)):
`esp.info.fw_version`, `esp.adc.read_mv`, `esp.free_heap()` work in both, and times
are seconds in both.

```bash
npm i @hamzayslmn/esplink             # browser: nothing else
npm i @hamzayslmn/esplink serialport  # Node over USB serial
```

## Browser (Chrome / Edge)

Web Serial and Web Bluetooth need a user gesture the first time — the browser
shows its own device picker:

```js
import { connect_serial, connect_ble } from "@hamzayslmn/esplink/web";

button.onclick = async () => {
  const esp = await connect_serial();     // or: await connect_ble()
  await esp.gpio.mode(esp.pins.led, "output");
  await esp.gpio.write(esp.pins.led, 1);
  console.log(esp.info.ident, await esp.adc.read_mv(34), "mV");
};
```

`connect_ble()` lists boards advertising as `esplink_<name-or-mac>`; the default
link password is `"esplink"` (`connect_ble({ password: "..." })`).

## Node

```js
import { connect_serial, connect_tcp } from "@hamzayslmn/esplink/node";

const esp = await connect_serial();                      // first ESP32 port, or { port: "COM5" }
// const esp = await connect_tcp({ host: "192.168.1.50" }); // Wi-Fi link
console.log(await esp.i2c.scan());
await esp.close();
```

## API

| | |
|---|---|
| `esp.info` | `{ ident, name, mac, chip, fw_version, chip_rev, caps, gpio_count, flash_mb }` |
| `esp.pins` | the board's default pins: `led`, `rgb`, `sda`, `scl`, `sck`, `miso`, `mosi`, `cs`, `tx`, `rx` |
| `esp.ping()` / `free_heap()` / `set_name(name)` / `close()` | system (`ping()` returns seconds) |
| `esp.gpio` | `mode(pin, "output")`, `write`, `read`, `watch(pin, edge, debounce_ms, callback)`, `unwatch(pin)` |
| `esp.adc` / `dac` / `touch` | `config(pin, atten)`, `read`, `read_mv` / `write`, `disable` / `read` |
| `esp.pwm` | `attach(pin, freq, resolution_bits)`, `write`, `duty_pct`, `detach`, `tone`, `servo(pin, angle)` |
| `esp.i2c` | `init({ sda, scl, freq })` (pins default to the board's), `scan`, `write`, `read`, `write_read`, `deinit` |
| `esp.spi` | `init({ sck, miso, mosi, freq })`, `transfer(bytes, { cs })`, `deinit` |
| `esp.request(C.CMD, payload)` | anything else — every command id is in `C` |
| `esp.on_event(C.EVENT, callback)` / `off_event` | raw firmware events |

Requests pipeline: fire many with `Promise.all` and they overlap on the wire,
paced to the firmware's receive window. Failures reject with `RemoteError`
(`.status`) or `BridgeTimeoutError`, as in Python.

`src/commands.js` is generated from the firmware header — `npm run gen` after
changing `src/esplink/commands.h`; `npm test` fails when it is stale.
