#if defined(ARDUINO_ARCH_ESP32)
// RMT pulse-train TX and RX (arduino-esp32 3.x HAL). Device-level protocol
// decoding stays host-side; this module only moves raw symbols.
// Handlers run on slow_task: TX blocks until the frame is sent, RECV blocks up
// to the caller-supplied timeout.
// Wire symbol format: u16 big-endian, bit 15 = level, bits 14..0 = duration in
// RMT ticks (1..0x7FFF). Two symbols pack into one rmt_data_t hardware word;
// the unused half of an odd trailing symbol is left zero, which the RMT hardware
// interprets as an end-of-frame marker.
#include "esplink/protocol.h"
#include "esplink/modules.h"
#include <esp32-hal-rmt.h>
#include <esp32-hal-periman.h>
#include <driver/rmt_tx.h>

struct RmtChan {
  int8_t pin = -1;
  uint8_t dir;          // 0 tx, 1 rx
  uint32_t tick_hz;
  rmt_data_t* loop_buf; // heap buffer kept alive while TX_LOOP is running; the RMT hardware reads it on every loop iteration
};
#define RMT_MAX_CHANS 4
static RmtChan chans[RMT_MAX_CHANS];

static RmtChan* channel_for_pin(uint8_t pin) {
  for (auto& c : chans) if (c.pin == (int8_t)pin) return &c;
  return nullptr;
}

static bool setup_channel(RmtChan* c) {
  // RX gets 2 memory blocks (~192+ edges), which is enough for DHT, NEC IR, and
  // most other common IR remotes. DMA is not used for RX.
  return rmtInit(c->pin, c->dir ? RMT_RX_MODE : RMT_TX_MODE,
                 c->dir ? RMT_MEM_NUM_BLOCKS_2 : RMT_MEM_NUM_BLOCKS_1, c->tick_hz)
         && (c->dir || rmtSetEOT(c->pin, 0));  // TX idles low (WS2812/IR)
}

// Convert host-side u16 symbols to rmt_data_t hardware words.
// Two symbols pack into one hardware word (duration0/level0 and duration1/level1).
// Returns the number of hardware words written; accumulates total tick count in *ticks.
static size_t symbols_to_words(const uint8_t* p, uint16_t nsyms, rmt_data_t* out,
                            uint32_t* ticks) {
  size_t w = 0;
  for (uint16_t i = 0; i < nsyms; i++) {
    uint16_t s = read_be16(p + 2 * i);
    *ticks += s & 0x7FFF;
    if ((i & 1) == 0) {
      out[w].val = 0;
      out[w].duration0 = s & 0x7FFF;
      out[w].level0 = s >> 15;
    } else {
      out[w].duration1 = s & 0x7FFF;
      out[w].level1 = s >> 15;
      w++;
    }
  }
  if (nsyms & 1) w++;
  return w;
}

// Transmit without parking slow_task for the whole train. A blocking rmtWrite
// on a long train (a slow stepper chunk is seconds) starves every other slow
// handler — most damagingly watch_poll, whose on-device actions are supposed
// to be the realtime path. The RMT hardware streams from its own ring buffer,
// so the CPU only needs to start the write and check back: pump watch rules
// while it drains. Short trains (< 3 ms, e.g. a NeoPixel frame) keep the
// blocking write — a pump tick would cost more latency than it saves.
static bool rmt_write_pumped(RmtChan* c, rmt_data_t* buf, size_t words,
                             uint32_t est_ms) {
  uint32_t timeout = est_ms + 50;
  if (est_ms < 3) return rmtWrite(c->pin, buf, words, timeout);
  if (!rmtWriteAsync(c->pin, buf, words)) return false;
  uint32_t t0 = millis();
  while (!rmtTransmitCompleted(c->pin)) {
    if ((uint32_t)(millis() - t0) > timeout) return false;
    watch_poll();
    vTaskDelay(1);
  }
  return true;
}

static void do_tx(RmtChan* c, uint8_t seq, uint16_t cmd,
                      const uint8_t* p, uint16_t len, bool loop) {
  uint16_t nsyms = len / 2;
  if (nsyms == 0) { proto_reply_err(seq, cmd, ST_BAD_ARGS); return; }
  rmt_data_t* buf = (rmt_data_t*)malloc(((nsyms + 1) / 2) * sizeof(rmt_data_t));
  if (!buf) { proto_reply_err(seq, cmd, ST_NO_MEM); return; }
  uint32_t ticks = 0;
  size_t w = symbols_to_words(p, nsyms, buf, &ticks);
  if (loop) {
    rmtWriteLooping(c->pin, nullptr, 0);  // stop a previous loop first
    free(c->loop_buf);
    if (!rmtWriteLooping(c->pin, buf, w)) {
      free(buf);
      c->loop_buf = nullptr;
      proto_reply_err(seq, cmd, ST_IO);
      return;
    }
    c->loop_buf = buf;
    proto_reply_ok(seq, cmd);
  } else {
    bool ok = rmt_write_pumped(c, buf, w, ticks / (c->tick_hz / 1000));
    free(buf);
    ok ? proto_reply_ok(seq, cmd) : proto_reply_err(seq, cmd, ST_IO);
  }
}

// The HAL keeps its IDF channel private: it is the first member of the per-pin
// bus object (struct rmt_obj_s, esp32-hal-rmt.c, core 3.x), which is what the
// peripheral manager hands back for an RMT TX pin.
static rmt_channel_handle_t idf_tx_channel(int8_t pin) {
  void* bus = perimanGetPinBus(pin, ESP32_BUS_TYPE_RMT_TX);
  return bus ? *(rmt_channel_handle_t*)bus : nullptr;
}

// Bytes -> pulses in the IDF bytes encoder, MSB-first: the RMT ISR expands each
// bit into its symbol as it refills channel memory, so a frame of any length
// goes out gapless (WS2812) with no per-bit buffer on the heap. The wire bitN
// u32 is (first symbol << 16 | second); rmt_symbol_word_t keeps the first
// symbol in the low half, so the halves swap.
static void do_tx_bytes(RmtChan* c, uint8_t seq, uint16_t cmd,
                            const uint8_t* p, uint16_t len) {
  NEED(9);
  rmt_channel_handle_t ch = idf_tx_channel(c->pin);
  rmt_bytes_encoder_config_t cfg = {};
  uint32_t v0 = read_be32(p), v1 = read_be32(p + 4);
  cfg.bit0.val = (v0 << 16) | (v0 >> 16);
  cfg.bit1.val = (v1 << 16) | (v1 >> 16);
  cfg.flags.msb_first = 1;
  rmt_encoder_handle_t enc = nullptr;
  if (!ch || rmt_new_bytes_encoder(&cfg, &enc) != ESP_OK) { proto_reply_err(seq, cmd, ST_IO); return; }
  rmtWriteLooping(c->pin, nullptr, 0);  // a running TX_LOOP would hold the queue forever
  free(c->loop_buf);
  c->loop_buf = nullptr;
  rmt_transmit_config_t tc = {};        // one shot; EOT low, as setup_channel set it
  uint32_t bit_ticks = cfg.bit0.duration0 + cfg.bit0.duration1;
  uint32_t est_ms = (uint32_t)(len - 8) * 8 * bit_ticks / (c->tick_hz / 1000);
  esp_err_t e = rmt_transmit(ch, enc, p + 8, len - 8, &tc);
  // Long trains pump the watch rules while the hardware drains (see rmt_write_pumped),
  // then one wait for the rest: each timed-out wait logs "flush timeout" as an
  // error, so polling it would flood SYS_LOG (and its first timeout ended the frame).
  for (uint32_t t0 = millis(); e == ESP_OK && (uint32_t)(millis() - t0) < est_ms; vTaskDelay(1))
    watch_poll();
  if (e == ESP_OK) e = rmt_tx_wait_all_done(ch, 50);
  if (e == ESP_ERR_TIMEOUT) { rmt_disable(ch); rmt_enable(ch); }  // abort: frees the encoder
  rmt_del_encoder(enc);
  e == ESP_OK ? proto_reply_ok(seq, cmd) : proto_reply_err(seq, cmd, ST_IO);
}

// Arm the RX channel, optionally fire a trigger pulse, then wait for capture or
// timeout. The trigger pulse supports two wiring styles:
//   - Same pin as RX (open-drain): line releases high after the pulse; used for DHT.
//   - Separate trigger pin (push-pull): used for HC-SR04 and similar devices.
// Replies with the captured symbols, or an empty payload if nothing was received.
static void do_recv(RmtChan* c, uint8_t seq, uint16_t cmd,
                        const uint8_t* p, uint16_t len) {
  NEED(13);
  uint16_t idle = read_be16(p + 1), timeout = read_be16(p + 3), max_syms = read_be16(p + 5);
  NEED_FREE_PINS(p + 7, 1);  // trigger pin (0xFF = none)
  uint8_t trig_pin = p[7], trig_level = p[8];
  uint32_t trig_us = read_be32(p + 9);
  if (max_syms == 0 || max_syms > RMT_MAX_RX_SYMS) max_syms = RMT_MAX_RX_SYMS;

  size_t words = (max_syms + 1) / 2;
  rmt_data_t* buf = (rmt_data_t*)malloc(words * sizeof(rmt_data_t));
  if (!buf) { proto_reply_err(seq, cmd, ST_NO_MEM); return; }
  rmtSetRxMaxThreshold(c->pin, idle);
  size_t num = words;
  if (!rmtReadAsync(c->pin, buf, &num)) {
    // rmtReadAsync() fails when the channel is still armed from a previous
    // RECV that timed out without completing. Deinit and reinit to reset
    // the channel state, then retry once.
    rmtDeinit(c->pin);
    num = words;
    if (!setup_channel(c) || !rmtSetRxMaxThreshold(c->pin, idle)
        || !rmtReadAsync(c->pin, buf, &num)) {
      free(buf);
      proto_reply_err(seq, cmd, ST_IO);
      return;
    }
  }

  if (trig_pin != 0xFF) {
    // 0xFF means no trigger. Otherwise, drive the trigger pin:
    // same pin as RX -> use open-drain so the RMT receiver stays connected and
    // the line can float high (DHT style); separate pin -> plain push-pull (HC-SR04).
    pinMode(trig_pin, trig_pin == (uint8_t)c->pin ? OUTPUT_OPEN_DRAIN : OUTPUT);
    digitalWrite(trig_pin, trig_level);
    if (trig_us >= 1000) delay(trig_us / 1000);
    delayMicroseconds(trig_us % 1000);
    digitalWrite(trig_pin, !trig_level);
  }

  uint32_t t0 = millis();
  while (!rmtReceiveCompleted(c->pin) && millis() - t0 < timeout) vTaskDelay(1);

  if (!rmtReceiveCompleted(c->pin)) {
    rmtDeinit(c->pin);  // disarm the channel; the next operation will re-init it via setup_channel()
    setup_channel(c);
    free(buf);
    proto_reply(seq, cmd, nullptr, 0);
    return;
  }
  // Repack the rmt_data_t words back into u16 BE wire symbols in place.
  // Each hardware word covers 4 bytes and contains two symbols (duration0/level0
  // and duration1/level1), so reads and writes stay within the same buffer.
  uint8_t* out = (uint8_t*)buf;
  uint16_t halves = 0;
  for (size_t i = 0; i < num; i++) {
    uint16_t h0 = (buf[i].level0 << 15) | buf[i].duration0;
    uint16_t h1 = (buf[i].level1 << 15) | buf[i].duration1;
    write_be16(out + 4 * i, h0);
    write_be16(out + 4 * i + 2, h1);
    halves += 2;
  }
  while (halves && (read_be16(out + 2 * (halves - 1)) & 0x7FFF) == 0) halves--;  // strip trailing zero-duration symbols (RMT end-of-frame markers)
  proto_reply(seq, cmd, out, halves * 2);
  free(buf);
}

void rmt_handle(uint8_t op, uint8_t seq, const uint8_t* p, uint16_t len) {
  uint16_t cmd = CMD(MOD_RMT, op);
  if (op == 0x01) {  // INIT: pin|dir|tick_hz
    if (len < 6 || p[1] > 1) { proto_reply_err(seq, cmd, ST_BAD_ARGS); return; }
    uint32_t hz = read_be32(p + 2);
    if (hz < 1000) { proto_reply_err(seq, cmd, ST_BAD_ARGS); return; }
    NEED_FREE_PINS(p, 1);
    RmtChan* c = channel_for_pin(p[0]);
    if (c) { rmtDeinit(c->pin); free(c->loop_buf); c->loop_buf = nullptr; }
    else c = channel_for_pin(0xFF);  // no existing slot for this pin; find a free slot (pin == -1 means unused)
    if (!c) { proto_reply_err(seq, cmd, ST_NO_MEM); return; }
    c->pin = p[0]; c->dir = p[1]; c->tick_hz = hz;
    if (!setup_channel(c)) { c->pin = -1; proto_reply_err(seq, cmd, ST_IO); return; }
    proto_reply_ok(seq, cmd);
    return;
  }
  RmtChan* c = len >= 1 ? channel_for_pin(p[0]) : nullptr;
  if (!c) { proto_reply_err(seq, cmd, len ? ST_NOT_INIT : ST_BAD_ARGS); return; }
  switch (op) {
    case 0x02:  // DEINIT: pin
      rmtWriteLooping(c->pin, nullptr, 0);
      rmtDeinit(c->pin);
      free(c->loop_buf);
      c->loop_buf = nullptr;
      c->pin = -1;
      proto_reply_ok(seq, cmd);
      break;
    case 0x03: do_tx(c, seq, cmd, p + 1, len - 1, false); break;  // TX
    case 0x04: do_tx_bytes(c, seq, cmd, p + 1, len - 1); break;   // TX_BYTES
    case 0x05: do_tx(c, seq, cmd, p + 1, len - 1, true); break;   // TX_LOOP
    case 0x06:  // TX_STOP
      rmtWriteLooping(c->pin, nullptr, 0);
      free(c->loop_buf);
      c->loop_buf = nullptr;
      proto_reply_ok(seq, cmd);
      break;
    case 0x07: do_recv(c, seq, cmd, p, len); break;  // RECV
    case 0x08:  // CARRIER: pin|freq u32|duty_pct u8|enable u8
      NEED(7);
      if (!rmtSetCarrier(c->pin, p[6], true, read_be32(p + 1), p[5] / 100.0f))
        { proto_reply_err(seq, cmd, ST_IO); return; }
      proto_reply_ok(seq, cmd);
      break;
    default:
      proto_reply_err(seq, cmd, ST_UNKNOWN_CMD);
  }
}
#endif  // ARDUINO_ARCH_ESP32
