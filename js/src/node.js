// Node transports: USB serial (needs the `serialport` package) and Wi-Fi (TCP).
import { once } from "node:events";
import net from "node:net";
import { Bridge, BridgeError } from "./bridge.js";

export * from "./bridge.js";

const USB = ["10c4", "1a86", "303a"];  // CP210x, CH34x, Espressif native USB

/** USB serial; `path` defaults to the first ESP32-looking port. */
export async function connectSerial({ path, baudRate = 115200, ...opts } = {}) {
  const { SerialPort } = await import("serialport");
  path ??= (await SerialPort.list()).find((p) => USB.includes(p.vendorId?.toLowerCase()))?.path;
  if (!path) throw new BridgeError("no ESP32 serial port found — pass { path: 'COM5' }");
  const port = new SerialPort({ path, baudRate });
  await once(port, "open");
  const t = {
    maxInflight: 6400,
    write: (data) => new Promise((ok, fail) => port.write(data, (e) => (e ? fail(e) : ok()))),
    close: () => new Promise((ok) => (port.isOpen ? port.close(() => ok()) : ok())),
  };
  port.on("data", (d) => t.onData?.(new Uint8Array(d)));
  await t.write(Uint8Array.of(0));  // end any half-frame the board holds, or our first request is lost
  return Bridge.open(t, opts);
}

/** Wi-Fi link to a board in listen mode (firmware: EspLink.wifi.begin(...)). */
export async function connectTcp({ host, port = 3232, ...opts }) {
  const sock = net.connect({ host, port });
  await once(sock, "connect");
  sock.setNoDelay(true);  // Nagle would turn a 2 ms round trip into ~40 ms
  const t = {
    maxInflight: 6400,
    needsAuth: true,
    write: (data) => new Promise((ok, fail) => sock.write(data, (e) => (e ? fail(e) : ok()))),
    close: async () => sock.destroy(),
  };
  sock.on("data", (d) => t.onData?.(new Uint8Array(d)));
  return Bridge.open(t, opts);
}
