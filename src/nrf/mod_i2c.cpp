// I2C master (nRF52) on Wire / Wire1: bus setup here, transfers in esplink/mod_i2c.cpp.
// The nRF52 TwoWire takes pins via setPins() (before begin) rather than
// begin(sda, scl, freq), and has no setBufferSize — the buffer is fixed, and
// I2C_INIT reports its capacity so the host chunks larger transfers to fit.
#if defined(ARDUINO_ARCH_NRF52)
#include "esplink/protocol.h"
#include "esplink/modules.h"
#include <Wire.h>

#ifdef BUFFER_LENGTH
  #define NRF_WIRE_BUF BUFFER_LENGTH
#else
  #define NRF_WIRE_BUF 32
#endif

static bool i2c_inited[2];

static TwoWire* bus_for_index(uint8_t idx) {
  if (idx == 0) return &Wire;
#if defined(WIRE_INTERFACES_COUNT) && (WIRE_INTERFACES_COUNT > 1)
  if (idx == 1) return &Wire1;
#endif
  return nullptr;
}

void i2c_handle(uint8_t op, uint8_t seq, const uint8_t* p, uint16_t len) {
  uint16_t cmd = CMD(MOD_I2C, op);
  NEED(1);
  TwoWire* w = bus_for_index(p[0]);
  if (!w) { proto_reply_err(seq, cmd, ST_BAD_ARGS); return; }
  uint8_t bus = p[0];

  if (op != 0x01 && !i2c_inited[bus]) { proto_reply_err(seq, cmd, ST_NOT_INIT); return; }

  switch (op) {
    case 0x01: {  // INIT: bus, sda, scl, freq u32 -> wire_buf u16
      NEED(7);
      if (i2c_inited[bus]) w->end();
      w->setPins(p[1], p[2]);   // must precede begin() on this core
      w->begin();
      w->setClock(read_be32(p + 3));
      i2c_inited[bus] = true;
      uint8_t out[2];
      write_be16(out, NRF_WIRE_BUF);
      proto_reply(seq, cmd, out, 2);
      break;
    }

    case 0x06: {  // DEINIT
      w->end();
      i2c_inited[bus] = false;
      proto_reply_ok(seq, cmd);
      break;
    }

    default:  // the transfers: src/esplink/mod_i2c.cpp
      if (!i2c_transfer(w, op, seq, p, len)) proto_reply_err(seq, cmd, ST_UNKNOWN_CMD);
  }
}

#endif  // ARDUINO_ARCH_NRF52
