// node --test  (no dependencies; no board needed)
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import test from "node:test";

import { generate, OUT } from "../scripts/gen-commands.mjs";
import { Bridge, BridgeTimeoutError, C, PINS, RemoteError } from "../src/bridge.js";
import { crc16, decodeFrame, encodeFrame, FrameSplitter } from "../src/protocol.js";

const hex = (u8) => Buffer.from(u8).toString("hex");

test("frames are byte-identical to the Python implementation", () => {
  assert.equal(crc16(Buffer.from("123456789")), 0x29b1);  // CRC-16/CCITT-FALSE check value
  assert.equal(hex(encodeFrame(0, 1, C.SYS_PING, Buffer.from("ping"))), "010201080170696e6750e500");
  assert.equal(hex(encodeFrame(C.FLAG_EVENT, 0, C.GPIO_EDGE_EVT, Uint8Array.of(0, 1, 0, 0, 0, 7))),
               "0201031080020101010407c28700");
  const big = encodeFrame(0, 7, C.SPI_TRANSFER, Uint8Array.from({ length: 600 }, (_, i) => (i % 255) + 1));
  assert.equal(big.length, 610);  // crosses two 254-byte COBS runs
  assert.equal(createHash("sha256").update(big).digest("hex"),
               "f189d013fc1bd0dc1dba055e8be7c3450a77783d9c52257b73ffbb1f7d16c823");
  const [chunk] = new FrameSplitter().feed(big);
  assert.equal(decodeFrame(chunk).payload.length, 600);
});

test("src/commands.js matches the firmware header (run npm run gen if not)", () => {
  assert.equal(readFileSync(OUT, "utf8"), generate());
});

// A firmware stand-in: decodes what the host writes and answers like the board.
function fakeBoard({ password = "esplink", maxInflight = 6400 } = {}) {
  const split = new FrameSplitter();
  const info = Uint8Array.of(C.PROTOCOL_VERSION, 1, 0, 1, 1, 3, 0x24, 0xa1, 0x60, 0x12, 0x34, 0x56,
                             0, 0, 0, 0x0f, 40, 4, ...Buffer.from("relays"));
  const t = {
    maxInflight, needsAuth: password !== null, peak: 0, inflight: 0,
    reply(flags, seq, cmd, payload) {
      const wire = encodeFrame(flags, seq, cmd, payload);
      // deliver in two pieces, the way a radio or a UART would
      setTimeout(() => { t.onData(wire.subarray(0, 3)); t.onData(wire.subarray(3)); }, 1);
    },
    async write(data) {
      t.inflight += data.length;
      t.peak = Math.max(t.peak, t.inflight);
      for (const c of split.feed(data)) {
        const { seq, cmd, payload: p } = decodeFrame(c);
        setTimeout(() => (t.inflight -= c.length + 1), 1);
        const ok = (payload = new Uint8Array()) => t.reply(0, seq, cmd, payload);
        const err = (status) => t.reply(C.FLAG_ERROR, seq, cmd, Uint8Array.of(status));
        if (cmd === C.SYS_AUTH) Buffer.from(p).toString() === password ? ok() : err(0x0d);
        else if (cmd === C.SYS_INFO) ok(info);
        else if (cmd === C.SYS_PING) ok(p);
        else if (cmd === C.GPIO_WRITE) ok(Uint8Array.of(p[1]));
        else if (cmd === C.GPIO_WATCH) { ok(); t.reply(C.FLAG_EVENT, 0, C.GPIO_EDGE_EVT, Uint8Array.of(p[0], 1, 0, 0, 1, 0)); }
        else if (cmd === C.GPIO_UNWATCH) ok();
        else if (cmd === C.SYS_FREE_HEAP) ok(Uint8Array.from({ length: 24 }, (_, i) => (i % 4 === 3 ? i : 0)));
        else if (cmd === C.SYS_RESET) { /* silence: the board is rebooting */ }
        else err(0x01);
      }
    },
  };
  return t;
}

test("Bridge: handshake, requests, events, errors, flow control", async () => {
  const board = fakeBoard({ maxInflight: 64 });
  const esp = await Bridge.open(board);
  assert.equal(esp.info.ident, "relays");
  assert.equal(esp.info.mac, "24:a1:60:12:34:56");
  assert.deepEqual(esp.info.fw_version, [1, 0, 1]);
  assert.equal(esp.info.chip, "ESP32");
  assert.equal(esp.pins.led, 2);

  // 100 concurrent requests through a 64-byte window: all answered, window held
  const levels = await Promise.all(Array.from({ length: 100 }, (_, i) => esp.gpio.write(2, i % 2)));
  assert.deepEqual(levels, Array.from({ length: 100 }, (_, i) => i % 2));
  assert.ok(board.peak <= 64 + 16, `window overrun: ${board.peak} bytes in flight`);

  const edges = [];
  await esp.gpio.watch(4, "falling", 0, (ev) => edges.push(ev));     // Python's argument order
  await new Promise((r) => setTimeout(r, 20));
  assert.deepEqual(edges, [{ pin: 4, level: 1, micros: 256 }]);
  await esp.gpio.unwatch(4);

  assert.equal((await esp.free_heap()).serial_rx_errors, 23);
  await assert.rejects(esp.request(C.CAN_INIT), (e) => e instanceof RemoteError && /UNKNOWN_CMD/.test(e.message));
  await assert.rejects(esp.request(C.SYS_RESET, undefined, 0.03), BridgeTimeoutError);  // seconds, as in Python
  await esp.close();
});

test("Bridge: a wrong wireless password is refused", async () => {
  await assert.rejects(Bridge.open(fakeBoard(), { password: "nope" }), (e) => /DENIED/.test(e.message));
});

test("Bridge: an oversized payload is refused without leaking window bytes", async () => {
  const esp = await Bridge.open(fakeBoard({ password: null, maxInflight: 4300 }));
  const big = new Uint8Array(3000);
  await assert.rejects(esp.request(C.SYS_PING, big), RangeError);
  await assert.rejects(esp.request(C.SYS_PING, big), RangeError);   // used to hang forever
  assert.equal((await esp.request(C.SYS_PING, new Uint8Array(1500))).length, 1500);
  await esp.close();
});

test("Bridge: a timed-out request settles once", async () => {
  const board = fakeBoard({ password: null });
  const esp = await Bridge.open(board);
  const write = board.write;
  board.write = async (d) => { await new Promise((r) => setTimeout(r, 40)); throw new Error("link gone"); };
  await assert.rejects(esp.request(C.SYS_PING, undefined, 0.01), BridgeTimeoutError);  // then the write rejects too
  await new Promise((r) => setTimeout(r, 60));
  board.write = write;
  const pings = await Promise.all(Array.from({ length: 5 }, () => esp.ping()));
  assert.equal(pings.length, 5);
  await esp.close();
});

test("PINS mirror python/esplink/constants.py", () => {
  const py = readFileSync(new URL("../../python/esplink/constants.py", import.meta.url), "utf8");
  for (const [chip, pins] of Object.entries(PINS)) {
    const row = py.match(new RegExp(`ChipModel\\.${chip}:\\s*Pins\\(([^)]*)\\)`))[1];
    const want = Object.fromEntries(row.split(",").map((kv) => kv.trim().split("="))
      .map(([k, v]) => [k, v === "None" ? null : Number(v)]));
    assert.deepEqual(pins, want, chip);
  }
});
