# esplink for JavaScript

Drive an ESP32 running the esplink firmware from a web page or from Node — same
wire protocol and the same API shape as the Python package
([`../python`](../python)), camelCased.

```bash
npm i esplink                 # browser: nothing else
npm i esplink serialport      # Node over USB serial
```

## Browser (Chrome / Edge)

Web Serial and Web Bluetooth need a user gesture the first time — the browser
shows its own device picker:

```js
import { connectSerial, connectBle } from "esplink/web";

button.onclick = async () => {
  const esp = await connectSerial();      // or: await connectBle()
  await esp.gpio.mode(2, "output");
  await esp.gpio.write(2, 1);
  console.log(esp.info.ident, await esp.adc.readMv(34), "mV");
};
```

`connectBle()` lists boards advertising as `esplink_<name-or-mac>`; the default
link password is `"esplink"` (`connectBle({ password: "..." })`).

## Node

```js
import { connectSerial, connectTcp } from "esplink/node";

const esp = await connectSerial();                       // first ESP32 port, or { path: "COM5" }
// const esp = await connectTcp({ host: "192.168.1.50" }); // Wi-Fi link
console.log(await esp.i2c.scan());
await esp.close();
```

## API

| | |
|---|---|
| `esp.info` | `{ ident, name, mac, chip, fwVersion, caps, gpioCount, flashMb }` |
| `esp.ping()` / `freeHeap()` / `setName(name)` / `close()` | system |
| `esp.gpio` | `mode(pin, "output")`, `write`, `read`, `watch(pin, edge, cb)` → unwatch |
| `esp.adc` / `dac` / `touch` | `config(pin, atten)`, `read`, `readMv` / `write`, `disable` / `read` |
| `esp.pwm` | `attach(pin, freq, bits)`, `write`, `detach`, `tone`, `servo(pin, angle)` |
| `esp.i2c` | `init({ sda, scl, freq })`, `scan`, `write`, `read`, `writeRead` |
| `esp.spi` | `init({ sck, miso, mosi, freq })`, `transfer(bytes, { cs })` |
| `esp.request(C.CMD, payload)` | anything else — every command id is in `C` |
| `esp.on(C.EVENT, cb)` | raw firmware events → unsubscribe function |

Requests pipeline: fire many with `Promise.all` and they overlap on the wire,
paced to the firmware's receive window. Failures reject with `RemoteError`
(`.status`) or `TimeoutError`.

`src/commands.js` is generated from the firmware header — `npm run gen` after
changing `src/esplink/commands.h`; `npm test` fails when it is stale.
