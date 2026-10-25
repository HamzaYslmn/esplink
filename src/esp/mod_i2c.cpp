#if defined(ARDUINO_ARCH_ESP32)
// I2C master on Wire / Wire1: bus setup here, transfers in esplink/mod_i2c.cpp.
#include "esplink/protocol.h"
#include "esplink/modules.h"
#include <Wire.h>

static bool i2c_inited[2];

static TwoWire* bus_for_index(uint8_t idx) {
  if (idx == 0) return &Wire;
#if SOC_I2C_NUM > 1
  if (idx == 1) return &Wire1;  // C3 has a single I2C controller
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
      NEED_FREE_PINS(p + 1, 2);  // sda, scl
      if (i2c_inited[bus]) w->end();
      // The default 128 B Wire TX buffer silently truncates larger writes.
      // setBufferSize() requires ~2× the requested size in free heap, so try
      // progressively smaller sizes and report whichever one actually succeeded.
      uint16_t got = 0;
      for (uint16_t sz : {MAX_PAYLOAD, 512, 128}) {
        if (sz > 128 && ESP.getFreeHeap() < 2u * sz + 8192) continue;
        if (w->setBufferSize(sz) && w->begin(p[1], p[2], read_be32(p + 3))) { got = sz; break; }
      }
      if (!got) { proto_reply_err(seq, cmd, ST_NO_MEM); return; }
      i2c_inited[bus] = true;
      uint8_t out[2];
      write_be16(out, got);
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
#endif  // ARDUINO_ARCH_ESP32
