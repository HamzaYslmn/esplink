// esplink for JavaScript — the same wire protocol and API shape as the Python
// package, over any transport (Web Serial / Web Bluetooth in ./web.js, Node
// serial / TCP in ./node.js).
//
//   import { connectSerial } from "esplink/web";
//   const esp = await connectSerial();
//   await esp.gpio.mode(2, "output");
//   await esp.gpio.write(2, 1);
//
// ponytail: the common peripherals have helpers below; everything else is one
// esp.request(C.SOME_CMD, payload) away (payload layouts: docs/PROTOCOL.md).
import * as C from "./commands.js";
import { decodeFrame, encodeFrame, FrameSplitter } from "./protocol.js";

export { C };

export class BridgeError extends Error {}
export class TimeoutError extends BridgeError {}
export class RemoteError extends BridgeError {
  constructor(status, cmd) {
    super(`command 0x${cmd.toString(16).padStart(4, "0")} failed: ${C.STATUS[status] ?? status}`);
    this.status = status;
    this.cmd = cmd;
  }
}

// ---- payload packing: big-endian, struct-style ("BIB" = u8, u32, u8) --------
const SIZE = { B: 1, b: 1, H: 2, h: 2, I: 4, i: 4 };
export function pack(fmt, ...vals) {
  const out = new Uint8Array([...fmt].reduce((n, c) => n + SIZE[c], 0));
  const dv = new DataView(out.buffer);
  let o = 0;
  [...fmt].forEach((c, i) => {
    const v = vals[i];
    if (c === "B") dv.setUint8(o, v); else if (c === "b") dv.setInt8(o, v);
    else if (c === "H") dv.setUint16(o, v); else if (c === "h") dv.setInt16(o, v);
    else if (c === "I") dv.setUint32(o, v); else dv.setInt32(o, v);
    o += SIZE[c];
  });
  return out;
}
const concat = (...parts) => {
  const out = new Uint8Array(parts.reduce((n, p) => n + p.length, 0));
  parts.reduce((o, p) => (out.set(p, o), o + p.length), 0);
  return out;
};
const u16 = (b, o = 0) => (b[o] << 8) | b[o + 1];
const u32 = (b, o = 0) => new DataView(b.buffer, b.byteOffset).getUint32(o);
const bytes = (d) => (typeof d === "string" ? new TextEncoder().encode(d) : Uint8Array.from(d));

function parseInfo(p) {
  if (p.length < 18) throw new BridgeError(`short SYS_INFO payload: ${p.length} bytes`);
  const mac = [...p.subarray(6, 12)].map((x) => x.toString(16).padStart(2, "0")).join(":");
  const name = new TextDecoder().decode(p.subarray(18));
  return { protocol: p[0], fwVersion: [p[1], p[2], p[3]], chip: p[4], chipRev: p[5], mac,
           caps: u32(p, 12), gpioCount: p[16], flashMb: p[17], name, ident: name || mac };
}

const MODES = { input: 0, output: 1, input_pullup: 2, input_pulldown: 3, output_open_drain: 4 };
const EDGES = { rising: 1, falling: 2, change: 3 };
const ATTEN = { 0: 0, 2.5: 1, 6: 2, 11: 3 };

export class Bridge {
  #t; #split = new FrameSplitter(); #pending = new Map(); #handlers = new Map();
  #seq = 0; #inflight = 0; #waiters = []; #writes = Promise.resolve();

  /** Handshake over an open transport: {write(u8), close(), onData, needsAuth, maxInflight}. */
  static async open(transport, { password = "esplink", timeout = 2000 } = {}) {  // firmware default password
    const esp = new Bridge(transport, timeout);
    try {
      if (transport.needsAuth) await esp.request(C.SYS_AUTH, bytes(password), 5000);
      // A board that just reset (port open pulses DTR) is deaf for ~1 s and then
      // announces itself with SYS_READY; a running one simply answers SYS_INFO.
      for (let i = 0; i < 5 && !esp.info; i++) {
        try { esp.info = parseInfo(await esp.request(C.SYS_INFO, undefined, 1000)); }
        catch (e) { if (!(e instanceof TimeoutError)) throw e; }
      }
      if (!esp.info) throw new TimeoutError("no response from esplink firmware — is it flashed?");
      if (esp.info.protocol !== C.PROTOCOL_VERSION)
        throw new BridgeError(`protocol mismatch: firmware v${esp.info.protocol}, library v${C.PROTOCOL_VERSION}`);
      return esp;
    } catch (e) {
      await esp.close();
      throw e;
    }
  }

  constructor(transport, timeout = 2000) {
    this.#t = transport;
    this.timeout = timeout;
    this.info = null;
    transport.onData = (data) => this.#feed(data);
    this.on(C.SYS_READY, (p) => { try { this.info = parseInfo(p); } catch {} });
    this.on(C.SYS_LOG, (p) => p[0] >= 2 && console.warn("[esplink fw]", new TextDecoder().decode(p.subarray(1))));
    this.gpio = gpio(this); this.adc = adc(this); this.dac = dac(this); this.touch = touch(this);
    this.pwm = pwm(this); this.i2c = i2c(this); this.spi = spi(this);
  }

  #feed(data) {
    for (const chunk of this.#split.feed(data)) {
      let f;
      try { f = decodeFrame(chunk); } catch { continue; }  // corrupted: the request times out
      if (f.flags & C.FLAG_EVENT) {
        for (const cb of this.#handlers.get(f.cmd) ?? []) {
          try { cb(f.payload); } catch (e) { console.error(e); }
        }
      } else {
        this.#pending.get(f.seq)?.(f.flags & C.FLAG_ERROR ? new RemoteError(f.payload[0] ?? 0xff, f.cmd) : null, f.payload);
      }
    }
  }

  /** Subscribe to firmware event `cmd`; returns the unsubscribe function. */
  on(cmd, cb) {
    if (!this.#handlers.has(cmd)) this.#handlers.set(cmd, new Set());
    this.#handlers.get(cmd).add(cb);
    return () => this.#handlers.get(cmd).delete(cb);
  }

  /** Send a request and resolve with the reply payload (rejects with RemoteError / TimeoutError). */
  async request(cmd, payload = new Uint8Array(), timeout = this.timeout) {
    // Flow control: cap bytes in flight at the firmware's RX window, or a
    // pipelined burst overflows its link buffer and frames are lost.
    const size = payload.length + 8;
    while ((this.#inflight && this.#inflight + size > (this.#t.maxInflight ?? Infinity)) || this.#pending.size >= 255)
      await new Promise((r) => this.#waiters.push(r));
    this.#inflight += size;
    let seq = this.#seq;
    do seq = (seq % 255) + 1; while (this.#pending.has(seq));  // 1..255; 0 = fire-and-forget
    this.#seq = seq;
    const frame = encodeFrame(0, seq, cmd, payload);
    return new Promise((resolve, reject) => {
      const done = (err, value) => {
        clearTimeout(timer);
        this.#pending.delete(seq);
        this.#inflight -= size;
        this.#waiters.splice(0).forEach((r) => r());
        err ? reject(err) : resolve(value);
      };
      const timer = setTimeout(() => done(new TimeoutError(`no response for command 0x${cmd.toString(16)} within ${timeout} ms`)), timeout);
      this.#pending.set(seq, done);
      // One write at a time: a BLE frame goes out as several chunks, and two
      // frames' chunks must never interleave.
      this.#writes = this.#writes.then(() => this.#t.write(frame)).catch(done);
    });
  }

  async ping() {
    const t0 = performance.now();
    await this.request(C.SYS_PING, bytes("ping"));
    return performance.now() - t0;  // ms
  }

  async freeHeap() {
    const r = await this.request(C.SYS_FREE_HEAP);
    const keys = ["free", "minFree", "largestBlock", "droppedEvents", "linkRxDropped", "serialRxErrors"];
    return Object.fromEntries(keys.map((k, i) => [k, u32(r, i * 4)]));
  }

  async setName(name) {
    const b = bytes(name);
    if (b.length > C.BRIDGE_NAME_MAX) throw new RangeError(`name must be at most ${C.BRIDGE_NAME_MAX} bytes`);
    await this.request(C.SYS_SET_NAME, b);
    if (this.info) this.info = { ...this.info, name, ident: name || this.info.mac };
  }

  async close() {
    for (const done of [...this.#pending.values()]) done(new BridgeError("connection closed"));
    await this.#t.close?.();
  }
}

// ---- sub-APIs: same names and defaults as the Python package -----------------

const gpio = (b) => ({
  mode: (pin, mode) => b.request(C.GPIO_SET_MODE, pack("BB", pin, MODES[mode] ?? mode)),
  write: async (pin, value) => (await b.request(C.GPIO_WRITE, pack("BB", pin, value ? 1 : 0)))[0],
  read: async (pin) => (await b.request(C.GPIO_READ, pack("B", pin)))[0],
  /** cb({pin, level, millis}) on each edge; resolves to a function that stops watching. */
  watch: async (pin, edge, cb, debounceMs = 0) => {
    const off = b.on(C.GPIO_EDGE_EVT, (p) => p[0] === pin && cb({ pin, level: p[1], millis: u32(p, 2) }));
    await b.request(C.GPIO_WATCH, pack("BBH", pin, EDGES[edge] ?? edge, debounceMs));
    return async () => { off(); await b.request(C.GPIO_UNWATCH, pack("B", pin)); };
  },
});

const adc = (b) => ({
  config: (pin, atten = 11) => b.request(C.ADC_CONFIG, pack("BB", pin, ATTEN[atten] ?? atten)),
  read: async (pin) => u16(await b.request(C.ADC_READ, pack("B", pin))),
  readMv: async (pin) => u16(await b.request(C.ADC_READ_MV, pack("B", pin))),
});

const dac = (b) => ({
  write: (pin, value) => b.request(C.DAC_WRITE, pack("BB", pin, value & 0xff)),
  disable: (pin) => b.request(C.DAC_DISABLE, pack("B", pin)),
});

const touch = (b) => ({
  read: async (pin) => u32(await b.request(C.TOUCH_READ, pack("B", pin))),
});

const pwm = (b) => ({
  attach: (pin, freq = 1000, resolutionBits = 10) => b.request(C.PWM_ATTACH, pack("BIB", pin, freq, resolutionBits)),
  write: (pin, duty) => b.request(C.PWM_WRITE, pack("BI", pin, duty)),
  detach: (pin) => b.request(C.PWM_DETACH, pack("B", pin)),
  tone: (pin, freq) => b.request(C.PWM_TONE, pack("BI", pin, freq)),
  /** Hobby servo: 50 Hz, 14-bit, angle 0..180 mapped onto minUs..maxUs. */
  servo: async (pin, angle, minUs = 500, maxUs = 2500) => {
    await b.request(C.PWM_ATTACH, pack("BIB", pin, 50, 14));
    const us = minUs + ((maxUs - minUs) * Math.max(0, Math.min(180, angle))) / 180;
    await b.request(C.PWM_WRITE, pack("BI", pin, Math.round((us / 20000) * 16383)));
  },
});

const i2c = (b) => ({
  init: async ({ sda = 21, scl = 22, freq = 400000, bus = 0 } = {}) => {
    await b.request(C.I2C_INIT, pack("BBBI", bus, sda, scl, freq));
  },
  scan: async (bus = 0) => {
    const r = await b.request(C.I2C_SCAN, pack("B", bus), 5000);
    return [...r.subarray(1, 1 + r[0])];
  },
  write: (addr, data, bus = 0) => b.request(C.I2C_WRITE, concat(pack("BB", bus, addr), bytes(data))),
  read: (addr, n, bus = 0) => b.request(C.I2C_READ, pack("BBB", bus, addr, n)),
  writeRead: (addr, wdata, rlen, bus = 0) => {
    const w = bytes(wdata);
    return b.request(C.I2C_WRITE_READ, concat(pack("BBB", bus, addr, w.length), w, pack("B", rlen)));
  },
});

const spi = (b) => ({
  init: ({ sck = 18, miso = 19, mosi = 23, freq = 1000000, mode = 0, msbFirst = true, host = 0 } = {}) =>
    b.request(C.SPI_INIT, pack("BbbbIBB", host, sck, miso, mosi, freq, mode, msbFirst ? 1 : 0)),
  /** Full duplex, CS held low for the whole transfer (one frame: ≤ MAX_PAYLOAD - 2 bytes). */
  transfer: (tx, { cs = 255, host = 0 } = {}) => b.request(C.SPI_TRANSFER, concat(pack("BB", host, cs), bytes(tx)), 10000),
});
