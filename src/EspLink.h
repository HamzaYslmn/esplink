// esplink — flash-once firmware exposing every ESP32 peripheral to the
// Python `esplink` package over USB serial, Bluetooth or Wi-Fi.
//
//   void setup() {
//     EspLink.usb.begin();                 // the bridge core boots here
//     EspLink.ble.begin();                 // password defaults to "esplink"
//     EspLink.wifi.begin("ssid", "pass");  // TCP link, port 3232
//     EspLink.run();                       // optional; see below
//   }
//   void loop() { /* yours — runs unless run() was called */ }
//
// The core starts on the FIRST *.begin() and is idempotent, so order never
// matters. Docs: README.md, docs/FIRMWARE.md.
#pragma once
#include <Arduino.h>

class EspLinkClass {
 public:
  // USB serial (or native USB CDC). Never authenticated — holding the cable is
  // the authentication.
  struct UsbLink {
    void begin();
  } usb;

  // Bluetooth LE. `password` is what hosts present via SYS_AUTH ("" = open).
  struct BleLink {
    void begin(const char* password = "esplink");
  } ble;

  // Wi-Fi: the same protocol over TCP.
  //   begin("ssid", "pass")                    -> board listens on `port`
  //   begin("ssid", "pass", "10.0.0.5")        -> board dials that host
  //   begin()                                  -> credentials stored in NVS
  // Returns false if the link could not be armed (no credentials, not enough
  // heap, or ESP-NOW owns the radio); the board runs on regardless.
  struct WifiLink {
    bool begin(const char* ssid = nullptr, const char* pass = nullptr,
               const char* server = nullptr, uint16_t port = 0,
               const char* password = "esplink");
    void end();
  } wifi;

  // Deletes the Arduino loop task and never returns, giving its 8 KB stack back
  // to the heap — which BLE needs on a classic ESP32 running Wi-Fi too.
  void run();
};

extern EspLinkClass EspLink;
