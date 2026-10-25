// Frame codec: COBS framing + CRC-16/CCITT-FALSE (see docs/PROTOCOL.md).
//   logical frame = flags u8 | seq u8 | cmd u16 BE | payload | crc16 BE
//   on the wire   = COBS(logical) + 0x00
import { MAX_PAYLOAD } from "./commands.js";

export function crc16(data) {
  let crc = 0xffff;
  for (const b of data) {
    crc ^= b << 8;
    for (let i = 0; i < 8; i++) crc = crc & 0x8000 ? ((crc << 1) ^ 0x1021) & 0xffff : (crc << 1) & 0xffff;
  }
  return crc;
}

export function cobsEncode(data) {
  const out = new Uint8Array(data.length + Math.ceil(data.length / 254) + 1);
  let code = 1, codeAt = 0, w = 1;
  for (const b of data) {
    if (b !== 0) out[w++] = b;
    if (b === 0 || ++code === 0xff) {
      out[codeAt] = code;
      code = 1;
      codeAt = w++;
    }
  }
  out[codeAt] = code;
  return out.subarray(0, w);
}

export function cobsDecode(data) {
  const out = [];
  for (let i = 0; i < data.length;) {
    const code = data[i++];
    if (code === 0 || i + code - 1 > data.length) throw new Error("bad COBS frame");
    for (let k = 1; k < code; k++) out.push(data[i++]);
    if (code !== 0xff && i < data.length) out.push(0);
  }
  return Uint8Array.from(out);
}

export function encodeFrame(flags, seq, cmd, payload = new Uint8Array()) {
  if (payload.length > MAX_PAYLOAD) throw new Error(`payload too large: ${payload.length} > ${MAX_PAYLOAD}`);
  const f = new Uint8Array(6 + payload.length);
  f.set([flags, seq, cmd >> 8, cmd & 0xff]);
  f.set(payload, 4);
  const crc = crc16(f.subarray(0, 4 + payload.length));
  f.set([crc >> 8, crc & 0xff], 4 + payload.length);
  const enc = cobsEncode(f);
  const wire = new Uint8Array(enc.length + 1);  // trailing 0x00 delimiter
  wire.set(enc);
  return wire;
}

export function decodeFrame(chunk) {
  const f = cobsDecode(chunk);
  if (f.length < 6) throw new Error(`frame too short: ${f.length} bytes`);
  const n = f.length - 2;
  if (crc16(f.subarray(0, n)) !== ((f[n] << 8) | f[n + 1])) throw new Error("CRC mismatch");
  return { flags: f[0], seq: f[1], cmd: (f[2] << 8) | f[3], payload: f.slice(4, n) };
}

// Collects transport bytes and hands back each COBS chunk between 0x00 delimiters.
export class FrameSplitter {
  #buf = [];
  feed(data) {
    const chunks = [];
    for (const b of data) {
      if (b !== 0) this.#buf.push(b);
      else if (this.#buf.length) chunks.push(Uint8Array.from(this.#buf.splice(0)));
    }
    return chunks;
  }
}
