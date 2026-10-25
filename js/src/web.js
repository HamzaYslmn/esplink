// Browser transports: Web Serial (USB) and Web Bluetooth — Chrome / Edge.
// Both must be called from a user gesture (a click) the first time, because the
// browser shows its own device picker.
import { Bridge } from "./bridge.js";

export * from "./bridge.js";

const SERVICE = "6e400001-b5a3-f393-e0a9-e50e24dcca9e";  // NUS-style link service
const RX = "6e400002-b5a3-f393-e0a9-e50e24dcca9e";       // host -> board
const TX = "6e400003-b5a3-f393-e0a9-e50e24dcca9e";       // board -> host (notify)
const USB = [0x10c4, 0x1a86, 0x303a].map((usbVendorId) => ({ usbVendorId }));  // CP210x, CH34x, native

/** USB serial. Pass `port` (a SerialPort from navigator.serial.getPorts()) to skip the picker. */
export async function connect_serial({ port, baud = 115200, ...opts } = {}) {
  port ??= await navigator.serial.requestPort({ filters: USB });
  await port.open({ baudRate: baud, bufferSize: 8192 });
  const reader = port.readable.getReader();
  const writer = port.writable.getWriter();
  const t = {
    maxInflight: 6400,
    write: (data) => writer.write(data),
    async close() {
      await reader.cancel().catch(() => {});
      reader.releaseLock();
      writer.releaseLock();
      await port.close();
    },
  };
  (async () => {
    for (;;) {
      const { value, done } = await reader.read().catch(() => ({ done: true }));
      if (done) break;
      t.onData?.(value);
    }
  })();
  await writer.write(Uint8Array.of(0));  // end any half-frame the board holds, or our first request is lost
  return Bridge.open(t, opts);
}

/** Bluetooth. Shows boards advertising as "esplink_<name-or-mac>". */
export async function connect_ble({ device, ...opts } = {}) {
  device ??= await navigator.bluetooth.requestDevice({
    filters: [{ namePrefix: "esplink_" }],
    optionalServices: [SERVICE],
  });
  const gatt = await device.gatt.connect();
  const svc = await gatt.getPrimaryService(SERVICE);
  const rx = await svc.getCharacteristic(RX);
  const tx = await svc.getCharacteristic(TX);
  // ponytail: Web Bluetooth hides the negotiated MTU, so try a 180-byte write
  // and drop to the 20 every link supports if the stack refuses it.
  let chunk = 180;
  const t = {
    maxInflight: 4300,
    needsAuth: true,
    async write(data) {
      for (let o = 0; o < data.length;) {
        const n = Math.min(chunk, data.length - o);
        try {
          await rx.writeValueWithoutResponse(data.subarray(o, o + n));
          o += n;
        } catch (e) {
          if (chunk === 20) throw e;
          chunk = 20;
        }
      }
    },
    close: async () => gatt.disconnect(),
  };
  tx.addEventListener("characteristicvaluechanged", (e) => {
    const v = e.target.value;
    t.onData?.(new Uint8Array(v.buffer, v.byteOffset, v.byteLength));
  });
  await tx.startNotifications();
  return Bridge.open(t, opts);
}
