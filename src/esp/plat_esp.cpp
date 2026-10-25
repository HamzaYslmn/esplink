// esplink — ESP32 platform glue (heap, reset cause, link Serial,
// and the IDF log redirect). Pulled out of the shared protocol core so that
// core stays architecture-independent.
#if defined(ARDUINO_ARCH_ESP32)
#include "esplink/platform.h"
#include "esplink/protocol.h"
#include "esplink/config.h"
#include <esp_system.h>
#include <esp_log.h>
#include <esp_rom_sys.h>

uint32_t plat_free_heap() { return ESP.getFreeHeap(); }

const char* plat_reset_reason() {
  switch (esp_reset_reason()) {
    case ESP_RST_POWERON:   return "power-on";
    case ESP_RST_EXT:       return "external reset";
    case ESP_RST_SW:        return "software reset";
    case ESP_RST_PANIC:     return "panic/exception";
    case ESP_RST_INT_WDT:   return "interrupt watchdog";
    case ESP_RST_TASK_WDT:  return "task watchdog (a task starved the CPU)";
    case ESP_RST_WDT:       return "watchdog";
    case ESP_RST_DEEPSLEEP: return "deep-sleep wake";
    case ESP_RST_BROWNOUT:  return "brownout (supply voltage dropped)";
    default:                return "unknown";
  }
}

void plat_serial_begin() {
#ifdef LINK_UART
  LINK_UART.setRxBufferSize(SERIAL_RX_BUF);   // must precede begin(); the default 256-byte buffer is far too small for protocol frames
  LINK_UART.setTxBufferSize(SERIAL_TX_BUF);
  LINK_UART.begin(115200);
  // RX interrupt defaults to 120 of 128 FIFO bytes — ~53 µs margin at 1.5 Mbaud,
  // which a load spike can overrun and corrupt a frame. Fire at 64: same
  // throughput, 8x the margin.
  LINK_UART.setRxFIFOFull(64);
  LINK_UART.onReceive(proto_rx_kick);         // runs on the UART event task
#endif
#if BRIDGE_NATIVE_USB
  Serial.setRxBufferSize(SERIAL_RX_BUF);
#if ARDUINO_USB_MODE                       // HW CDC (USB-Serial-JTAG); TinyUSB keeps the 1 ms poll
  // HW CDC's default 256 B TX ring drains well inside the 1 ms tx_task waits
  // once it is full, capping big replies near 256 KB/s; 1 KB covers the tick.
  Serial.setTxBufferSize(SERIAL_TX_BUF);
  Serial.begin();                          // native USB CDC — baud argument ignored by the USB driver
  Serial.onEvent(ARDUINO_HW_CDC_RX_EVENT, [](void*, esp_event_base_t, int32_t, void*) { proto_rx_kick(); });
#else
  Serial.begin();
#endif
#endif
}

// ---- IDF log capture --------------------------------------------------------
// Wi-Fi/BT/driver stacks log via esp_log to the console, and the console is the
// link on every build: UART0 on the classic chip, and on native USB the IDF's
// secondary console writes the USB-Serial-JTAG FIFO directly, under HW CDC's
// ring — a ledc_timer_config error landed inside a PWM_ATTACH reply frame.
// This hook redirects IDF log output into SYS_LOG events on both.
// (ROM boot and crash/panic text still hit the console raw; uninterceptable here.)
static int bridge_vprintf(const char* fmt, va_list ap) {
  char line[160];
  int n = vsnprintf(line, sizeof(line), fmt, ap);
  // esp_log appends CR/LF; strip it since SYS_LOG delivers one line at a time.
  size_t L = n < 0 ? 0 : (n < (int)sizeof(line) ? (size_t)n : sizeof(line) - 1);
  while (L && (line[L - 1] == '\n' || line[L - 1] == '\r')) line[--L] = 0;
  if (L) proto_log(1, line);  // no-op before proto_init() (tx queue guard)
  return n;
}

void proto_log_hook_install() {
  esp_log_set_vprintf(bridge_vprintf);
#if BRIDGE_NATIVE_USB
  // ets_printf (Arduino log_x at CORE_DEBUG_LEVEL >= 1, early/ISR logs) goes to
  // ROM channel 2 = the USB-Serial-JTAG FIFO, the same raw injection. Leave it
  // only channel 1, UART0 — raw there, as on the classic chip.
  esp_rom_install_channel_putc(2, nullptr);
#endif
}

#endif  // ARDUINO_ARCH_ESP32
