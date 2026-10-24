#include "EspLink.h"
#include "esplink/config.h"
#include "esplink/protocol.h"
#include "esplink/modules.h"
#include "esplink/link.h"
#include "esplink/platform.h"

EspLinkClass EspLink;

// The core is started by whichever link begins first, so a sketch can list its
// links in any order without a separate "start everything" call to forget.
static bool core_up = false;

static void bridge_core_start() {
  if (core_up) return;
  core_up = true;

  // Redirect vendor radio/log output away from the frame port into SYS_LOG
  // events (ESP only; a no-op on nRF). Must be installed before any radio.
  proto_log_hook_install();

  // Bring up the host-link Serial port (UART or native USB CDC, per arch).
  plat_serial_begin();

  proto_init();
  gpio_init();
  wifi_init();
  proto_start();   // spawn the bridge_tx, bridge_rx, and bridge_slow FreeRTOS tasks

  // Why the chip last reset — logged at boot so a stall that resets the board is
  // diagnosable on reconnect (brownout/watchdog/panic) instead of a mystery.
  { char msg[64];
    snprintf(msg, sizeof(msg), "boot: last reset = %s", plat_reset_reason());
    proto_log(1, msg); }

  // Send the boot banner. After a DTR/RTS auto-reset the host waits for this
  // SYS_READY event before issuing any commands.
  uint8_t info[64];
  uint16_t n = sys_build_info(info);
  proto_send_event(SYS_READY, info, n);
}

void EspLinkClass::UsbLink::begin() { bridge_core_start(); }

void EspLinkClass::BleLink::begin(const char* password) {
  bridge_core_start();
#if BRIDGE_BLE
  link_ble_init(password);   // SYS_AUTH gate uses `password`
#else
  (void)password;
#endif
}

bool EspLinkClass::WifiLink::begin(const char* ssid, const char* pass,
                                     const char* server, uint16_t port,
                                     const char* password) {
  bridge_core_start();
#if BRIDGE_WIFI_LINK
  // Eager, unlike WIFI_CONNECT: this link IS how the host reaches the board, so
  // there is no earlier command to trigger it lazily.
  return link_tcp_begin(ssid, pass, server, port, password);
#else
  (void)ssid; (void)pass; (void)server; (void)port; (void)password;
  proto_log(2, "wifi link: not supported by this build");
  return false;
#endif
}

void EspLinkClass::WifiLink::end() {
#if BRIDGE_WIFI_LINK
  link_tcp_stop();
#endif
}

void EspLinkClass::run() {
  bridge_core_start();  // run() alone is a valid (USB-only) sketch
  vTaskDelete(nullptr); // never returns; the 8 KB loop stack goes back to the heap
}
