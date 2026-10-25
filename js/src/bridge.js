// esplink for JavaScript — the same wire protocol, and the same names, as the
// Python package (esp.info.fw_version, esp.adc.read_mv, esp.free_heap(), ...),
// over any transport (Web Serial / Web Bluetooth in ./web.js, Node serial / TCP
// in ./node.js). Times are seconds, as in Python.
//
//   import { connect_serial } from "@hamzayslmn/esplink/web";
//   const esp = await connect_serial();
//   await esp.gpio.mode(esp.pins.led, "output");
//   await esp.gpio.write(esp.pins.led, 1);
//
// ponytail: the common peripherals have helpers below; everything else is one
// esp.request(C.SOME_CMD, payload) away (payload layouts: docs/PROTOCOL.md).
import * as C from "./commands.js";
import { decodeFrame, encodeFrame, FrameSplitter } from "./protocol.js";

export { C };

export class BridgeError extends Error {}
export class BridgeTimeoutError extends BridgeError {}
export class RemoteError extends BridgeError {
  constructor(status, cmd) {
    super(`command 0x${cmd.toString(16).padStart(4, "0")} failed: ${C.STATUS[status] ?? status}`);
    this.status = status;
    this.cmd = cmd;
  }
}

// A board's default pins, by chip — mirror of python/esplink/constants.py PINS
// (the test suite checks they match).
export const PINS = {
  ESP32:    { led: 2, rgb: null, sda: 21, scl: 22, sck: 18, miso: 19, mosi: 23, cs: 5, tx: 17, rx: 16 },
  ESP32S3:  { led: null, rgb: 48, sda: 8, scl: 9, sck: 12, miso: 13, mosi: 11, cs: 10, tx: 16, rx: 15 },
  ESP32C3:  { led: null, rgb: 8, sda: 8, scl: 9, sck: 4, miso: 5, mosi: 6, cs: 7, tx: 21, rx: 20 },
  NRF52840: { led: 11, rgb: null, sda: 4, scl: 5, sck: 15, miso: 14, mosi: 16, cs: null, tx: 1, rx: 0 },
};

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

function parse_info(p) {
  if (p.length < 18) throw new BridgeError(`short SYS_INFO payload: ${p.length} bytes`);
  const mac = [...p.subarray(6, 12)].map((x) => x.toString(16).padStart(2, "0")).join(":");
  const name = new TextDecoder().decode(p.subarray(18));
  return { protocol: p[0], fw_version: [p[1], p[2], p[3]], chip: C.CHIP[p[4]] ?? "UNKNOWN",
           chip_rev: p[5], mac, caps: u32(p, 12), gpio_count: p[16], flash_mb: p[17], name,
           ident: name || mac };
}

const MODES = { input: 0, output: 1, input_pullup: 2, input_pulldown: 3, output_open_drain: 4 };
const EDGES = { rising: 1, falling: 2, change: 3, both: 3 };
const ATTEN = { 0: 0, 2.5: 1, 6: 2, 11: 3 };
// Finest PWM resolution that still fits `freq` (same rule as Python's pwm_bits).
const pwm_bits = (freq) => Math.max(1, Math.min(14, Math.floor(Math.log2(16_000_000 / Math.max(1, freq)))));

export class Bridge {
  #t; #split = new FrameSplitter(); #pending = new Map(); #handlers = new Map();
  #seq = 0; #inflight = 0; #waiters = []; #writes = Promise.resolve();

  /** Handshake over an open transport: {write(u8), close(), onData, needsAuth, maxInflight}. */
  static async open(transport, { password = "esplink", timeout = 2.0 } = {}) {  // firmware default password
    const esp = new Bridge(transport, timeout);
    try {
      if (transport.needsAuth) await esp.request(C.SYS_AUTH, bytes(password), 5.0);
      // A board that just reset (port open pulses DTR) is deaf for ~1 s and then
      // announces itself with SYS_READY; a running one simply answers SYS_INFO.
      for (let i = 0; i < 5 && !esp.info; i++) {
        try { esp.info = parse_info(await esp.request(C.SYS_INFO, undefined, 1.0)); }
        catch (e) { if (!(e instanceof BridgeTimeoutError)) throw e; }
      }
      if (!esp.info) throw new BridgeTimeoutError("no response from esplink firmware — is it flashed?");
      if (esp.info.protocol !== C.PROTOCOL_VERSION)
        throw new BridgeError(`protocol mismatch: firmware v${esp.info.protocol}, library v${C.PROTOCOL_VERSION}`);
      return esp;
    } catch (e) {
      await esp.close();
      throw e;
    }
  }

  constructor(transport, timeout = 2.0) {
    this.#t = transport;
    this.timeout = timeout;
    this.info = null;
    transport.onData = (data) => this.#feed(data);
    this.on_event(C.SYS_READY, (p) => { try { this.info = parse_info(p); } catch {} });
    this.on_event(C.SYS_LOG, (p) => p[0] >= 2 && console.warn("[esplink fw]", new TextDecoder().decode(p.subarray(1))));
    this.gpio = gpio(this); this.adc = adc(this); this.dac = dac(this); this.touch = touch(this);
    this.pwm = pwm(this); this.i2c = i2c(this); this.spi = spi(this);
  }

  /** This board's default pins (LED, I2C, SPI, UART) — what init() uses when you pass none. */
  get pins() { return PINS[this.info?.chip] ?? PINS.ESP32; }

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

  /** Call `callback(payload)` for every firmware event `cmd`. */
  on_event(cmd, callback) {
    if (!this.#handlers.has(cmd)) this.#handlers.set(cmd, new Set());
    this.#handlers.get(cmd).add(callback);
  }

  off_event(cmd, callback) {
    this.#handlers.get(cmd)?.delete(callback);
  }

  /** Send a request and resolve with the reply payload (rejects with RemoteError / BridgeTimeoutError). */
  async request(cmd, payload = new Uint8Array(), timeout = this.timeout) {
    // Flow control: cap bytes in flight at the firmware's RX window, or a
    // pipelined burst overflows its link buffer and frames are lost.
    if (payload.length > C.MAX_PAYLOAD) throw new RangeError(`payload too large: ${payload.length} > ${C.MAX_PAYLOAD}`);
    const size = payload.length + 8;
    while ((this.#inflight && this.#inflight + size > (this.#t.maxInflight ?? Infinity)) || this.#pending.size >= 255)
      await new Promise((r) => this.#waiters.push(r));
    this.#inflight += size;
    let seq = this.#seq;
    do seq = (seq % 255) + 1; while (this.#pending.has(seq));  // 1..255; 0 = fire-and-forget
    this.#seq = seq;
    const frame = encodeFrame(0, seq, cmd, payload);
    return new Promise((resolve, reject) => {
      let settled = false;  // a timeout and a failed write can both report; count it once
      const done = (err, value) => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        this.#pending.delete(seq);
        this.#inflight -= size;
        this.#waiters.splice(0).forEach((r) => r());
        err ? reject(err) : resolve(value);
      };
      const timer = setTimeout(() => done(new BridgeTimeoutError(`no response for command 0x${cmd.toString(16)} within ${timeout} s`)), timeout * 1000);
      this.#pending.set(seq, done);
      // One write at a time: a BLE frame goes out as several chunks, and two
      // frames' chunks must never interleave.
      this.#writes = this.#writes.then(() => this.#t.write(frame)).catch(done);
    });
  }

  /** Round trip a payload; returns the latency in seconds. */
  async ping(payload = bytes("ping")) {
    const t0 = performance.now();
    await this.request(C.SYS_PING, payload);
    return (performance.now() - t0) / 1000;
  }

  async free_heap() {
    const r = await this.request(C.SYS_FREE_HEAP);
    const keys = ["free", "min_free", "largest_block", "dropped_events", "link_rx_dropped", "serial_rx_errors"];
    return Object.fromEntries(keys.map((k, i) => [k, u32(r, i * 4)]));
  }

  async set_name(name) {
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

// ---- sub-APIs: the Python names, arguments and defaults ---------------------

const gpio = (b) => {
  const watchers = new Map();  // pin -> event handler
  return {
    mode: (pin, mode) => b.request(C.GPIO_SET_MODE, pack("BB", pin, MODES[mode] ?? mode)),
    write: async (pin, value) => (await b.request(C.GPIO_WRITE, pack("BB", pin, value ? 1 : 0)))[0],
    read: async (pin) => (await b.request(C.GPIO_READ, pack("B", pin)))[0],
    /** callback({pin, level, micros}) on each edge. */
    watch: async (pin, edge = "change", debounce_ms = 0, callback = null) => {
      if (callback) {
        const h = (p) => p[0] === pin && callback({ pin, level: p[1], micros: u32(p, 2) });
        watchers.set(pin, h);
        b.on_event(C.GPIO_EDGE_EVT, h);
      }
      await b.request(C.GPIO_WATCH, pack("BBH", pin, EDGES[edge] ?? edge, debounce_ms));
    },
    unwatch: async (pin) => {
      b.off_event(C.GPIO_EDGE_EVT, watchers.get(pin));
      watchers.delete(pin);
      await b.request(C.GPIO_UNWATCH, pack("B", pin));
    },
  };
};

const adc = (b) => ({
  config: (pin, atten = 11) => {
    if (!(atten in ATTEN)) throw new RangeError(`atten must be one of 0, 2.5, 6, 11 dB, not ${atten}`);
    return b.request(C.ADC_CONFIG, pack("BB", pin, ATTEN[atten]));
  },
  read: async (pin) => u16(await b.request(C.ADC_READ, pack("B", pin))),
  read_mv: async (pin) => u16(await b.request(C.ADC_READ_MV, pack("B", pin))),
});

const dac = (b) => ({
  write: (pin, value) => b.request(C.DAC_WRITE, pack("BB", pin, value & 0xff)),
  disable: (pin) => b.request(C.DAC_DISABLE, pack("B", pin)),
});

const touch = (b) => ({
  read: async (pin) => u32(await b.request(C.TOUCH_READ, pack("B", pin))),
});

const pwm = (b) => {
  const attached = new Map();  // pin -> [freq, resolution_bits]
  const api = {
    /** Resolution defaults to 10 bits, or the finest that fits when `freq` is too high for 10. */
    attach: async (pin, freq = 1000, resolution_bits = null) => {
      resolution_bits ??= Math.min(10, pwm_bits(freq));
      await b.request(C.PWM_ATTACH, pack("BIB", pin, freq, resolution_bits));
      attached.set(pin, [freq, resolution_bits]);
    },
    write: (pin, duty) => b.request(C.PWM_WRITE, pack("BI", pin, duty)),
    duty_pct: async (pin, percent) => {
      if (!attached.has(pin)) await api.attach(pin);
      const bits = attached.get(pin)[1];
      await api.write(pin, Math.round(((1 << bits) - 1) * Math.max(0, Math.min(100, percent)) / 100));
    },
    detach: async (pin) => { await b.request(C.PWM_DETACH, pack("B", pin)); attached.delete(pin); },
    tone: (pin, freq) => b.request(C.PWM_TONE, pack("BI", pin, freq)),
    /** Hobby servo: 50 Hz, 14-bit, angle 0..180 mapped onto min_us..max_us. */
    servo: async (pin, angle, { min_us = 500, max_us = 2500 } = {}) => {
      const [f, bits] = attached.get(pin) ?? [];
      if (f !== 50 || bits !== 14) await api.attach(pin, 50, 14);
      const us = min_us + ((max_us - min_us) * Math.max(0, Math.min(180, angle))) / 180;
      await api.write(pin, Math.round((us / 20000) * 16383));
    },
  };
  return api;
};

const i2c = (b) => ({
  /** Pins default to the board's (esp.pins.sda / .scl). */
  init: async ({ sda = null, scl = null, freq = 400000, bus = 0 } = {}) => {
    await b.request(C.I2C_INIT, pack("BBBI", bus, sda ?? b.pins.sda, scl ?? b.pins.scl, freq));
  },
  scan: async (bus = 0) => {
    const r = await b.request(C.I2C_SCAN, pack("B", bus), 5.0);
    return [...r.subarray(1, 1 + r[0])];
  },
  write: (addr, data, bus = 0) => b.request(C.I2C_WRITE, concat(pack("BB", bus, addr), bytes(data))),
  read: (addr, n, bus = 0) => b.request(C.I2C_READ, pack("BBB", bus, addr, n)),
  write_read: (addr, wdata, rlen, bus = 0) => {
    const w = bytes(wdata);
    return b.request(C.I2C_WRITE_READ, concat(pack("BBB", bus, addr, w.length), w, pack("B", rlen)));
  },
  deinit: (bus = 0) => b.request(C.I2C_DEINIT, pack("B", bus)),
});

const spi = (b) => ({
  /** Pins default to the board's (esp.pins.sck / .miso / .mosi). */
  init: ({ sck = null, miso = null, mosi = null, freq = 1000000, mode = 0, msb_first = true, host = 0 } = {}) =>
    b.request(C.SPI_INIT, pack("BbbbIBB", host, sck ?? b.pins.sck, miso ?? b.pins.miso,
                                mosi ?? b.pins.mosi, freq, mode, msb_first ? 1 : 0)),
  /** Full duplex, CS held low for the whole transfer (one frame: ≤ MAX_PAYLOAD - 2 bytes). */
  transfer: (tx, { cs = null, host = 0 } = {}) =>
    b.request(C.SPI_TRANSFER, concat(pack("BB", host, cs ?? 255), bytes(tx)), 10.0),
  deinit: (host = 0) => b.request(C.SPI_DEINIT, pack("B", host)),
});
