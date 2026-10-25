// BLE transport link (nRF52): runs the bridge protocol over the Bluefruit
// Nordic UART Service (BLEUart), whose UUIDs are exactly the protocol's link
// UUIDs (6e400001/2/3-...). Counterpart to src/esp/link_ble.cpp.
// See esplink/link.h for the public API contract.
//
// RX: the central writes the NUS RX characteristic; Bluefruit buffers it in the
//   BLEUart FIFO, which rx_task drains via link_ble_read() through the same COBS
//   pump as USB. TX: tx_task pushes one (MTU-3)-byte notification per pass via
//   link_ble_write_chunk(). Auth (SYS_AUTH) is enforced in protocol.cpp.
#if defined(ARDUINO_ARCH_NRF52)
#include "esplink/protocol.h"
#include "esplink/modules.h"
#include "esplink/link.h"

#if BRIDGE_BLE

#include <bluefruit.h>

static bool enabled = false;
static volatile bool connected = false;
static volatile bool authed = false;
static volatile uint16_t conn_handle = BLE_CONN_HANDLE_INVALID;
static const char* link_password = "";
static BLEUart bleuart;  // Nordic UART Service — matches BLE_LINK_*_UUID

void nrf_read_mac(uint8_t mac[6]);  // mod_sys.cpp

static void connect_cb(uint16_t h) {
  conn_handle = h;
  connected = true;
  authed = false;  // re-authenticate on every connection (host presents SYS_AUTH)
}

static void disconnect_cb(uint16_t h, uint8_t reason) {
  (void)h; (void)reason;
  connected = false;
  authed = false;
  conn_handle = BLE_CONN_HANDLE_INVALID;
  // advertising restarts automatically (restartOnDisconnect(true))
}

void link_ble_init(const char* password) {
  link_password = password ? password : "";

  // Raise the negotiable ATT MTU / event length before begin() for throughput
  // (default MTU is 23 → 20-byte notifications, which throttles bulk frames).
  // BANDWIDTH_MAX, but 8 queued notifications instead of 3: a 2 KB reply fits
  // one connection event, and notify() no longer blocks tx_task on a full queue.
  Bluefruit.configPrphConn(247, 100, 8, BLE_GATTC_WRITE_CMD_TX_QUEUE_SIZE_DEFAULT);
  if (!Bluefruit.begin()) proto_log(2, "ble: SoftDevice refused the config (RAM)");
  Bluefruit.setTxPower(4);    // dBm — max range; the board is wired-powered

  // Advertised name "esplink_<name-or-mac>" — see the ESP counterpart in
  // src/esp/link_ble.cpp for why only one identity fits.
  const char* custom = sys_device_name();
  char devname[10 + BRIDGE_NAME_MAX + 1];
  if (custom[0]) {
    snprintf(devname, sizeof(devname), "esplink_%s", custom);
  } else {
    uint8_t mac[6];
    nrf_read_mac(mac);
    snprintf(devname, sizeof(devname), "esplink_%02x%02x%02x%02x%02x%02x",
             mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);
  }
  Bluefruit.setName(devname);

  Bluefruit.Periph.setConnectCallback(connect_cb);
  Bluefruit.Periph.setDisconnectCallback(disconnect_cb);

  bleuart.begin();

  // Advertising: flags + NUS service UUID in the packet, full name in the scan
  // response (keeps the 31-byte ADV packet within budget).
  Bluefruit.Advertising.addFlags(BLE_GAP_ADV_FLAGS_LE_ONLY_GENERAL_DISC_MODE);
  Bluefruit.Advertising.addTxPower();
  Bluefruit.Advertising.addService(bleuart);
  Bluefruit.ScanResponse.addName();
  Bluefruit.Advertising.restartOnDisconnect(true);
  Bluefruit.Advertising.setInterval(32, 244);  // units of 0.625 ms (20 ms / 152.5 ms)
  Bluefruit.Advertising.setFastTimeout(30);
  Bluefruit.Advertising.start(0);              // 0 = advertise forever

  enabled = true;
  proto_log_heap("ble: link up");
}

bool link_ble_enabled() { return enabled; }
uint32_t link_ble_rx_dropped() { return 0; }  // BLEUart FIFO drops are not counted on this core
bool link_ble_authed() { return connected && authed; }
// Ask for exactly 7.5 ms, as the ESP side does: the SoftDevice's default
// preference is 20-30 ms, centrals keep their own unless asked, and Windows
// takes 15 ms from any range (BLE ping 30 ms vs 15, measured). Then 251-byte
// packets, which Bluefruit only accepts, never asks for. No 2M PHY: with it,
// every FS write over BLE hung in its flash operation on S140 6.1.1 (measured).
static void request_fast(BLEConnection* c) {
  c->requestConnectionParameter(6);
  c->requestDataLengthUpdate();
}

void link_ble_set_authed(bool v) {
  authed = v;
  BLEConnection* c = v && connected ? Bluefruit.Connection(conn_handle) : nullptr;
  if (c) request_fast(c);
}
const char* link_ble_password() { return link_password; }

bool link_ble_up() { return enabled && connected; }

bool link_ble_power(bool battery) {
  if (!link_ble_up()) return false;
  BLEConnection* c = Bluefruit.Connection(conn_handle);
  if (!c) return false;
  // battery: ~100 ms interval (1.25 ms units); performance: back to 7.5-15 ms.
  if (battery) c->requestConnectionParameter(80);
  else request_fast(c);
  return true;
}

static bool link_ble_writable() {
  return link_ble_up() && bleuart.notifyEnabled(conn_handle);
}

uint16_t link_ble_write_chunk(const uint8_t* data, uint16_t len) {
  if (!link_ble_writable() || len == 0) return 0;
  uint16_t mtu = 23;
  BLEConnection* c = Bluefruit.Connection(conn_handle);
  if (c) mtu = c->getMtu();
  uint16_t chunk = mtu > 3 ? mtu - 3 : 20;
  if (len < chunk) chunk = len;
  return (uint16_t)bleuart.write(data, chunk);  // 0 if the BT stack can't take it now
}

uint16_t link_ble_read(uint8_t* buf, uint16_t maxlen) {
  if (!enabled) return 0;
  int avail = bleuart.available();
  if (avail <= 0) return 0;
  if ((uint16_t)avail > maxlen) avail = maxlen;
  int n = bleuart.read(buf, avail);
  return n > 0 ? (uint16_t)n : 0;
}

#else  // !BRIDGE_BLE — stubs for the callers outside #if BRIDGE_BLE

bool link_ble_enabled() { return false; }
uint32_t link_ble_rx_dropped() { return 0; }
bool link_ble_authed() { return false; }
void link_ble_set_authed(bool) {}
const char* link_ble_password() { return ""; }
bool link_ble_power(bool) { return false; }

#endif  // BRIDGE_BLE
#endif  // ARDUINO_ARCH_NRF52
