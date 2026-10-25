#if defined(ARDUINO_ARCH_ESP32)
// BLE transport link: runs the bridge protocol over a NUS-style GATT service
// so a host can communicate with the board over Bluetooth without a USB cable.
// See esplink/link.h for the public API.
//
// One source for every chip, on the core's own BLE library: it is Bluedroid on
// the classic ESP32 and NimBLE on S3/C3, behind the same API. The two #if
// blocks below are the only places the stacks differ.
//
// RX: the host writes the RX characteristic, the BT host task pushes the bytes
//   into a stream buffer, and rx_task drains it through the same COBS pump the
//   USB serial path uses.
// TX: tx_task sends (ATT_MTU - 3)-byte chunks as GATT notifications.
#include "esplink/protocol.h"
#include "esplink/modules.h"
#include "esplink/link.h"

#if BRIDGE_BLE

#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLE2902.h>
#include <esp_bt.h>
#include <esp_mac.h>
#include <esp32-hal-bt.h>
#include <freertos/stream_buffer.h>

// Classic ESP32 boots a dual-mode controller; this firmware uses only BLE, so
// release the Classic BT pool and start the controller BLE-only before any BT
// init: that pool is heap Bluedroid + Wi-Fi coex need, and a full dual-mode init
// runs OBEX_Deinit on an unallocated block and crashes core 0. One-way.
void bt_prepare_ble_only() {
#if defined(CONFIG_IDF_TARGET_ESP32)
  static bool done = false;
  if (done) return;
  done = true;
  esp_bt_mem_release(ESP_BT_MODE_CLASSIC_BT);
  btStartMode(BT_MODE_BLE);  // BLEDevice::init() then finds the controller up
#endif
}

// RX stream buffer (host-to-board), sized at the host's 4300-byte in-flight cap
// plus one frame so it cannot overflow. Two max-size frames already saturate BLE
// — the central's per-connection-event write rate is the bottleneck, not
// in-flight count — and every KB here is one the radio stack loses.
#define LINK_RX_BUF 6400

static bool enabled = false;
static volatile bool connected = false;
static volatile bool authed = false;
static volatile bool congested = false;  // Bluedroid TX queue full (classic only)
static const char* link_password = "";
static BLEServer* server = nullptr;
static BLECharacteristic* tx_chr = nullptr;
static StreamBufferHandle_t rx_buf = nullptr;
static volatile uint32_t rx_dropped = 0;  // bytes lost to RX buffer overflow

#if defined(CONFIG_BLUEDROID_ENABLED)
// Bluedroid addresses a connection by the peer's address and reports a full TX
// queue as an event; a notification sent into a full queue is dropped silently
// (the classic "mysterious timeout when pipelining"), so tx_task waits it out.
static esp_bd_addr_t peer;
static void link_gatts_evt(esp_gatts_cb_event_t event, esp_gatt_if_t,
                           esp_ble_gatts_cb_param_t* param) {
  if (event == ESP_GATTS_CONGEST_EVT) congested = param->congest.congested;
  if (event == ESP_GATTS_CONNECT_EVT) memcpy(peer, param->connect.remote_bda, sizeof(peer));
}
#define PEER peer
// The classic chip's BLE 4.2 controller has no 2M PHY, and asking it for
// 251-byte packets measured no gain (FS read 38 KB/s either way).
static void fast_link() {}
#else
#include <host/ble_gap.h>
#define PEER server->getConnId()  // NimBLE addresses it by connection handle
// 2M PHY + 251-byte link-layer packets: a 2 KB reply in fewer, shorter events.
static void fast_link() {
  uint16_t h = server->getConnId();
  ble_gap_set_prefered_le_phy(h, BLE_GAP_LE_PHY_2M_MASK, BLE_GAP_LE_PHY_2M_MASK, BLE_GAP_LE_PHY_CODED_ANY);
  ble_gap_set_data_len(h, 251, 2120);
}
#endif

// Interval units are 1.25 ms, timeout 10 ms. Asked only after SYS_AUTH: forcing
// params at connect races the central's own setup (MTU/discovery) and can stall
// the link. The advert already carries the same preference, so most centrals
// apply it from connect anyway.
static void request_conn_params(uint16_t min_int, uint16_t max_int,
                                uint16_t latency, uint16_t timeout) {
  if (server && connected) server->requestConnParams(PEER, min_int, max_int, latency, timeout);
}

class LinkSrvCb : public BLEServerCallbacks {
  void onConnect(BLEServer*) override {
    authed = false;  // every connection re-authenticates
    congested = false;
    connected = true;
  }
  void onDisconnect(BLEServer* s) override {
    connected = false;
    authed = false;
    congested = false;
    if (rx_buf) xStreamBufferReset(rx_buf);
    s->startAdvertising();  // stay discoverable
  }
};
static LinkSrvCb link_srv_cb;

class LinkRxCb : public BLECharacteristicCallbacks {
  void onWrite(BLECharacteristic* c) override {
    if (rx_buf == nullptr) return;
    // The BT host task, not an ISR, so the plain stream-buffer send is right.
    // The 50 ms timeout lets a pipelined burst backpressure that task instead of
    // dropping bytes; still full after 50 ms means the host will retry anyway.
    size_t n = xStreamBufferSend(rx_buf, c->getData(), c->getLength(), pdMS_TO_TICKS(50));
    proto_rx_kick();
    if (n < c->getLength()) {
      // Never drop silently: a partial COBS frame looks like a random host-side
      // timeout. Count it (SYS_FREE_HEAP) and emit a rate-limited warning.
      rx_dropped += c->getLength() - n;
      static uint32_t last_warn = 0;
      uint32_t now = millis();
      if (now - last_warn > 1000) {
        last_warn = now;
        proto_log(2, "ble: rx overflow — frames lost (host writing faster "
                     "than commands execute)");
      }
    }
  }
};
static LinkRxCb link_rx_cb;

// NimBLE has no congestion event: a notify into an exhausted mbuf pool fails
// (BLE_HS_ENOMEM) and the chunk is freed, unsent — the same silent mid-frame
// loss as Bluedroid's full queue. notify() reports it synchronously here, so
// write_chunk can say "0 bytes, retry next pass" instead.
static bool notify_failed = false;  // tx_task only: set and read inside notify()
class LinkTxCb : public BLECharacteristicCallbacks {
  void onStatus(BLECharacteristic*, Status s, uint32_t) override {
    if (s == Status::ERROR_GATT) notify_failed = true;
  }
};
static LinkTxCb link_tx_cb;

// Min free heap before BLEDevice::init(): below it the host stack's allocations
// abort with no recoverable path, so BLE is skipped, not fatal.
#define BLE_MIN_FREE_HEAP 55000

void link_ble_init(const char* password) {
  bt_prepare_ble_only();
  if (ESP.getFreeHeap() < BLE_MIN_FREE_HEAP) {
    proto_log(2, "ble: link disabled, not enough free heap at boot");
    return;
  }
  link_password = password ? password : "";
  rx_buf = xStreamBufferCreate(LINK_RX_BUF, 1);
  if (rx_buf == nullptr) return;

  // Advertised name "esplink_<identity>": the prefix marks the board as ours
  // in any BLE scanner, and the identity is its name, or its MAC while unnamed —
  // whichever one you'd pass to Bridge(). The scan response fits ~26 characters
  // and the prefix spends 8; BRIDGE_NAME_MAX (16) keeps a named board's advert whole.
  const char* custom = sys_device_name();
  char devname[8 + BRIDGE_NAME_MAX + 1];
  if (custom[0]) {
    snprintf(devname, sizeof(devname), "esplink_%s", custom);
  } else {
    uint8_t mac[6];
    esp_read_mac(mac, ESP_MAC_WIFI_STA);
    snprintf(devname, sizeof(devname), "esplink_%02x%02x%02x%02x%02x%02x",
             mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);
  }
  BLEDevice::init(devname);
  BLEDevice::setPower(ESP_PWR_LVL_P9);  // max TX power: fewer retransmits, more range, ~3 mA
  BLEDevice::setMTU(517);
#if defined(CONFIG_BLUEDROID_ENABLED)
  BLEDevice::setCustomGattsHandler(link_gatts_evt);
#endif

  server = BLEDevice::createServer();
  server->setCallbacks(&link_srv_cb);

  BLEService* svc = server->createService(BLE_LINK_SERVICE_UUID);
  BLECharacteristic* rx = svc->createCharacteristic(
      BLE_LINK_RX_UUID, BLECharacteristic::PROPERTY_WRITE | BLECharacteristic::PROPERTY_WRITE_NR);
  rx->setCallbacks(&link_rx_cb);
  tx_chr = svc->createCharacteristic(BLE_LINK_TX_UUID, BLECharacteristic::PROPERTY_NOTIFY);
  tx_chr->setCallbacks(&link_tx_cb);
  tx_chr->addDescriptor(new BLE2902());
  svc->start();

  // Service UUID in the advert, full name in the scan response (a 128-bit UUID
  // plus the name do not fit one 31-byte packet). The preferred-interval field
  // lets centrals apply 7.5-15 ms from connect, no update request needed.
  BLEAdvertising* adv = BLEDevice::getAdvertising();
  adv->addServiceUUID(BLE_LINK_SERVICE_UUID);
  adv->setScanResponse(true);
  adv->setMinPreferred(0x06);
  adv->setMaxPreferred(0x0C);
  adv->start();
  enabled = true;
  proto_log_heap("ble: link up");
}

bool link_ble_enabled() { return enabled; }
uint32_t link_ble_rx_dropped() { return rx_dropped; }
bool link_ble_authed() { return connected && authed; }

void link_ble_set_authed(bool v) {
  authed = v;
  if (!v || !server || !connected) return;
  // Exactly 7.5 ms: offered a 7.5-15 ms range, Windows picks 15 (BLE ping 30 ms);
  // asked for 7.5 alone it grants it (ping 15 ms, measured). 1 s supervision.
  request_conn_params(0x06, 0x06, 0, 100);
  fast_link();
}
const char* link_ble_password() { return link_password; }
void* link_ble_server() { return server; }

bool link_ble_power(bool battery) {
  if (!link_ble_up()) return false;
  // battery: 50-100 ms + slave latency 4 (latency only skips events when the
  // board has nothing to send, so a busy link stays responsive); 4 s timeout
  // because the spec floor here is (1+4)*100*2 = 1 s.
  if (battery) request_conn_params(0x28, 0x50, 4, 400);
  else request_conn_params(0x06, 0x06, 0, 100);
  return true;
}

bool link_ble_up() { return enabled && connected && tx_chr != nullptr; }

uint16_t link_ble_write_chunk(const uint8_t* data, uint16_t len) {
  if (!link_ble_up() || congested || len == 0) return 0;
  uint16_t mtu = server->getPeerMTU(server->getConnId());
  uint16_t chunk = mtu > 23 ? mtu - 3 : 20;
  if (chunk > 512) chunk = 512;  // ATT caps a value at 512; NimBLE drops longer ones
  if (len < chunk) chunk = len;
  tx_chr->setValue((uint8_t*)data, chunk);
  notify_failed = false;
  tx_chr->notify();
  return notify_failed ? 0 : chunk;
}

uint16_t link_ble_read(uint8_t* buf, uint16_t maxlen) {
  if (!enabled || rx_buf == nullptr) return 0;
  return (uint16_t)xStreamBufferReceive(rx_buf, buf, maxlen, 0);
}

// SYS_RADIO_OFF: tear the whole BT stack down — advertising, host, controller —
// and give its memory back. Removes the stack's core-0 interrupt/scheduler load
// for jitter-sensitive work over USB. Bluetooth then stays off until reset.
// Refused while a central holds the link (it would saw off its own branch).
static bool bt_dead = false;

bool link_ble_shutdown() {
  if (connected) return false;
  enabled = false;
  bt_dead = true;
  tx_chr = nullptr;             // tx_task checks link_ble_up() before touching it
  BLEDevice::deinit(true);      // no-op if init was skipped (boot heap guard)...
  if (btStarted()) btStop();    // ...but the bare controller may still be up
  proto_log_heap("ble: bt stack off");
  return true;
}

bool link_bt_dead() { return bt_dead; }

#else  // !BRIDGE_BLE — stubs for the callers outside #if BRIDGE_BLE

bool link_ble_enabled() { return false; }
uint32_t link_ble_rx_dropped() { return 0; }
bool link_ble_authed() { return false; }
void link_ble_set_authed(bool) {}
const char* link_ble_password() { return ""; }
bool link_ble_power(bool) { return false; }
bool link_ble_shutdown() { return false; }

#endif
#endif  // ARDUINO_ARCH_ESP32
