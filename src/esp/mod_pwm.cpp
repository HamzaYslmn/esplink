#if defined(ARDUINO_ARCH_ESP32)
// PWM via LEDC (arduino-esp32 3.x pin-based API).
#include "esplink/protocol.h"
#include "esplink/modules.h"

void pwm_handle(uint8_t op, uint8_t seq, const uint8_t* p, uint16_t len) {
  uint16_t cmd = CMD(MOD_PWM, op);
  switch (op) {
    case 0x01: {  // ATTACH: pin, freq u32, res_bits
      NEED(6);
      NEED_FREE_PINS(p, 1);
      uint8_t pin = p[0], res = p[5];
      uint32_t freq = read_be32(p + 1);
      // The timer's width is the chip's (S3/C3 14 bits, classic 20; the wire caps
      // at 16). freq x 2^res must also fit the LEDC clock — 40 MHz XTAL on S3/C3,
      // 80 MHz APB on classic — which only ledcAttach can judge: ST_IO.
      if (res < 1 || res > 16 || res > SOC_LEDC_TIMER_BIT_WIDTH || freq == 0) { proto_reply_err(seq, cmd, ST_BAD_ARGS); return; }
      if (!ledcAttach(pin, freq, res)) { proto_reply_err(seq, cmd, ST_IO); return; }
      proto_reply_ok(seq, cmd);
      break;
    }
    case 0x02: {  // WRITE: pin, duty u32
      NEED(5);
      if (!ledcWrite(p[0], read_be32(p + 1))) { proto_reply_err(seq, cmd, ST_NOT_INIT); return; }
      proto_reply_ok(seq, cmd);
      break;
    }
    case 0x03: {  // DETACH: pin
      NEED(1);
      ledcDetach(p[0]);
      proto_reply_ok(seq, cmd);
      break;
    }
    case 0x04: {  // TONE: pin, freq u32 (0 = off)
      NEED(5);
      ledcWriteTone(p[0], read_be32(p + 1));
      proto_reply_ok(seq, cmd);
      break;
    }
    default:
      proto_reply_err(seq, cmd, ST_UNKNOWN_CMD);
  }
}
#endif  // ARDUINO_ARCH_ESP32
