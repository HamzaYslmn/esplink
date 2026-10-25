// I2C transfers (SCAN / WRITE / READ / WRITE_READ), shared by both archs: only
// bus setup differs (src/esp/mod_i2c.cpp, src/nrf/mod_i2c.cpp), the Wire calls
// after it are the same Arduino API on every core.
#include "esplink/protocol.h"
#include "esplink/modules.h"
#include <Wire.h>

bool i2c_transfer(TwoWire* w, uint8_t op, uint8_t seq, const uint8_t* p, uint16_t len) {
  uint16_t cmd = CMD(MOD_I2C, op);
  uint8_t buf[255];
  switch (op) {
    case 0x02: {  // SCAN -> n, addr[n]  (1 count + up to 119 addrs, 0x01..0x77)
      uint8_t n = 0;
      for (uint8_t a = 1; a < 0x78; a++) {
        w->beginTransmission(a);
        uint8_t r = w->endTransmission();
        if (r == 0) buf[1 + n++] = a;
        // Anything but ACK/NACK (timeout, bus error) means the bus itself is
        // dead — no pull-ups, a line held low. Bail on the first one: 119 x the
        // 50 ms Wire timeout is ~6 s inline on rx_task, every link stalled.
        else if (r != 2) { proto_reply_err(seq, cmd, ST_IO); return true; }
      }
      buf[0] = n;
      proto_reply(seq, cmd, buf, 1 + n);
      return true;
    }

    case 0x03: {  // WRITE: bus, addr, data..
      if (len < 2) { proto_reply_err(seq, cmd, ST_BAD_ARGS); return true; }
      w->beginTransmission(p[1]);
      // write() returns the bytes accepted: a short count means the Wire buffer
      // overflowed (the host should chunk to I2C_INIT's wire_buf).
      uint8_t st = ST_OK;
      if (len > 2 && w->write(p + 2, len - 2) != (size_t)(len - 2)) {
        w->endTransmission();
        st = ST_BAD_ARGS;
      } else if (w->endTransmission() != 0) {
        st = ST_IO;  // NACK / bus error
      }
      if (st == ST_OK) { proto_reply_ok(seq, cmd); return true; }
      // seq 0 = fire-and-forget: no reply channel, so log a rate-limited warning
      // instead, or burst-write failures would vanish completely.
      static uint32_t last_warn = 0;
      if (seq == 0 && millis() - last_warn > 1000) {
        last_warn = millis();
        proto_log(2, st == ST_IO ? "i2c: unacked write failed (NACK/bus)"
                                 : "i2c: unacked write exceeds wire buffer");
      }
      proto_reply_err(seq, cmd, st);
      return true;
    }

    case 0x04:    // READ: bus, addr, len -> data
    case 0x05: {  // WRITE_READ: bus, addr, wlen, wdata[wlen], rlen -> data (repeated start)
      if (len < 3) { proto_reply_err(seq, cmd, ST_BAD_ARGS); return true; }
      uint8_t addr = p[1], rlen = p[2];
      if (op == 0x05) {
        uint8_t wlen = p[2];
        if (len < (uint16_t)(4 + wlen)) { proto_reply_err(seq, cmd, ST_BAD_ARGS); return true; }
        rlen = p[3 + wlen];
        w->beginTransmission(addr);
        w->write(p + 3, wlen);
        if (w->endTransmission(false) != 0) { proto_reply_err(seq, cmd, ST_IO); return true; }
      }
      if (w->requestFrom(addr, (size_t)rlen) != rlen) { proto_reply_err(seq, cmd, ST_IO); return true; }
      w->readBytes(buf, rlen);  // bulk drain, not 255 virtual read() calls
      proto_reply(seq, cmd, buf, rlen);
      return true;
    }
  }
  return false;
}
