// esplink — per-chip configuration & capability flags.
// ESP path requires arduino-esp32 core 3.x; nRF52 path requires the Adafruit/
// Seeed nRF52 (Bluefruit, FreeRTOS) core. Peripheral implementations live in
// src/esp/ and src/nrf/; this header holds the shared, arch-selected config.
#pragma once
#include <Arduino.h>
#include "commands.h"

// Set to 0 to build without BLE (smaller flash, more heap).
#ifndef BRIDGE_ENABLE_BLE
#define BRIDGE_ENABLE_BLE 1
#endif

#define BRIDGE_NAME "esplink"

#if defined(ARDUINO_ARCH_NRF52)
// ============================================================================
// Nordic nRF52840 (Seeed XIAO / Adafruit Bluefruit core)
// ----------------------------------------------------------------------------
// Capability-gated subset (the caps in src/nrf/mod_sys.cpp). No Wi-Fi/ESP-NOW
// radio and none of the ESP-IDF peripheral drivers, so those modules compile
// to ST_UNSUPPORTED stubs (src/nrf/mod_stubs.cpp) and the host — which gates
// each feature on SYS_INFO.caps — never offers them.
// ============================================================================
#define BRIDGE_CHIP        CHIP_NRF52840

// The Bluefruit BLE stack is always present on this core, so BRIDGE_BLE
// tracks the opt-in alone.
#if BRIDGE_ENABLE_BLE
#define BRIDGE_BLE 1
#else
#define BRIDGE_BLE 0
#endif

// Single-core MCU: pin every bridge task to the one core. The pinned-core API
// is ESP-only, so map it to the portable FreeRTOS xTaskCreate.
#define CORE_RADIO 0
#define CORE_APP   0
#define xTaskCreatePinnedToCore(fn, name, stack, arg, prio, handle, core) \
        xTaskCreate(fn, name, stack, arg, prio, handle)

// nRF FreeRTOS differs from arduino-esp32 in two ways the shared task sizing
// must respect: task priorities run in a small range (configMAX_PRIORITIES),
// and the stack DEPTH argument is in words (StackType_t = 4 B), not bytes. Set
// arch-appropriate values here; the shared tail leaves these alone (#ifndef).
#define TX_TASK_PRIO     3
#define RX_TASK_PRIO     2
#define SLOW_TASK_PRIO   2
#define TX_TASK_STACK    1024   // words (~4 KB)
#define RX_TASK_STACK    2048   // words (~8 KB) — holds the 256 B rx chunk + frame work
#define SLOW_TASK_STACK  1024   // words (~4 KB) — FS/NVS on LittleFS; the rest are stubs

#else
// ============================================================================
// Espressif (arduino-esp32 3.x)
// ============================================================================
// Every supported Espressif chip has BLE, ESP-NOW, RMT, TWAI and I2S; only the
// flags below differ. MCPWM/SDMMC come from SOC_* (soc_caps.h, via Arduino.h).
#if defined(CONFIG_IDF_TARGET_ESP32)
  #define BRIDGE_CHIP        CHIP_ESP32
  #define BRIDGE_HAS_DAC     1
  #define BRIDGE_HAS_TOUCH   1
  #define BRIDGE_HAS_BT_CLASSIC 1
  #define BRIDGE_SPI_HOST0   VSPI
  #define BRIDGE_SPI_HOST1   HSPI
#elif defined(CONFIG_IDF_TARGET_ESP32S3)
  #define BRIDGE_CHIP        CHIP_ESP32S3
  #define BRIDGE_HAS_DAC     0
  #define BRIDGE_HAS_TOUCH   1
  #define BRIDGE_HAS_BT_CLASSIC 0
  #define BRIDGE_SPI_HOST0   FSPI
  #define BRIDGE_SPI_HOST1   HSPI
#elif defined(CONFIG_IDF_TARGET_ESP32C3)
  #define BRIDGE_CHIP        CHIP_ESP32C3
  #define BRIDGE_HAS_DAC     0
  #define BRIDGE_HAS_TOUCH   0
  #define BRIDGE_HAS_BT_CLASSIC 0
  #define BRIDGE_SPI_HOST0   FSPI
  #define BRIDGE_SPI_HOST1   FSPI
#else
  #error "esplink supports ESP32, ESP32-S3, ESP32-C3 and nRF52840"
#endif

// Classic ESP32 with Wi-Fi + BLE: the SD-SPI and SDMMC drivers' IRAM-resident
// ISRs overflow iram0_0_seg; sleep alone fits (measured, core 3.3.12).
// BRIDGE_ENABLE_BLE 0 frees the room and brings SD back.
#if defined(CONFIG_IDF_TARGET_ESP32) && BRIDGE_ENABLE_BLE
  #define BRIDGE_HAS_SD    0
#else
  #define BRIDGE_HAS_SD    1
#endif
#if BRIDGE_HAS_SD && defined(SOC_SDMMC_HOST_SUPPORTED)
  #define BRIDGE_HAS_SDMMC 1
#else
  #define BRIDGE_HAS_SDMMC 0
#endif
#ifdef SOC_MCPWM_SUPPORTED  // esp32/s3 — NOT c3
  #define BRIDGE_HAS_MCPWM 1
#else
  #define BRIDGE_HAS_MCPWM 0
#endif

// Heavy optional modules, off by default. Enable with -DBRIDGE_ENABLE_ETH=1 or
// -DBRIDGE_ENABLE_CAM=1 at build time.
//   ETH requires a PHY chip: RMII on classic ESP32, or W5500/DM9051 over SPI on any chip.
//   CAM requires an OV-series sensor + PSRAM; ESP32/S3 only.
#ifndef BRIDGE_ENABLE_ETH
#define BRIDGE_ENABLE_ETH 0
#endif
#ifndef BRIDGE_ENABLE_CAM
#define BRIDGE_ENABLE_CAM 0
#endif
#if BRIDGE_ENABLE_ETH && defined(CONFIG_ETH_ENABLED)
  #define BRIDGE_ETH 1
#else
  #define BRIDGE_ETH 0
#endif
#if BRIDGE_ENABLE_CAM && (defined(CONFIG_IDF_TARGET_ESP32) || defined(CONFIG_IDF_TARGET_ESP32S3))
  #define BRIDGE_CAM 1
#else
  #define BRIDGE_CAM 0
#endif

// The core's BLE library builds on whichever host the chip's IDF ships —
// Bluedroid on the classic ESP32, NimBLE on S3/C3 — so every chip with a
// BLE radio gets the link (same guard as the library itself).
#if BRIDGE_ENABLE_BLE && defined(SOC_BLE_SUPPORTED) && \
    (defined(CONFIG_BLUEDROID_ENABLED) || defined(CONFIG_NIMBLE_ENABLED))
  #define BRIDGE_BLE 1
#else
  #define BRIDGE_BLE 0
#endif

// Native USB CDC (S3/C3): Serial is HWCDC, baud is meaningless.
#if defined(ARDUINO_USB_CDC_ON_BOOT) && ARDUINO_USB_CDC_ON_BOOT
  #define BRIDGE_NATIVE_USB 1
#else
  #define BRIDGE_NATIVE_USB 0
#endif

// S3 devkits put UART0 on a second USB port (CH343/CP2102 bridge), so on S3
// both wired ports are links: same protocol, no auth, like the classic chip.
// LINK_UART is the UART link's port wherever there is one.
#if BRIDGE_NATIVE_USB && defined(CONFIG_IDF_TARGET_ESP32S3)
  #define BRIDGE_UART0_LINK 1
  #define LINK_UART Serial0
#else
  #define BRIDGE_UART0_LINK 0
  #if !BRIDGE_NATIVE_USB
    #define LINK_UART Serial
  #endif
#endif

// ---- task layout ------------------------------------------------------------
// Dual-core ESP32 (Wi-Fi/BT pinned to core 0). The bridge's three tasks split by
// domain so reply N transmits while command N+1 executes:
//   CORE_RADIO (0): bridge_tx   (encode+write, prio 12, yields to the radio)
//                   bridge_slow (blocking Wi-Fi/NET/ESP-NOW/BLE/FS/OTA handlers,
//                                next to the stacks they call)
//   CORE_APP   (1): bridge_rx   (frame pump + fast inline handlers incl. 1-Wire,
//                                whose IRQ-masking slots must avoid the radio core)
//                   user loop() (when the sketch omits EspLink.run())
// Opt-out: -DBRIDGE_SINGLE_CORE=N pins all bridge tasks to core N (1 = leave the
// radio core untouched; 0 = leave core 1 to the sketch, but bus timing then
// shares a core with radio interrupts).
#if CONFIG_FREERTOS_UNICORE
  #define CORE_RADIO 0
  #define CORE_APP   0
#elif defined(BRIDGE_SINGLE_CORE)
  #define CORE_RADIO BRIDGE_SINGLE_CORE
  #define CORE_APP   BRIDGE_SINGLE_CORE
#else
  #define CORE_RADIO 0
  #define CORE_APP   1
#endif

#endif  // arch select (ARDUINO_ARCH_NRF52 / Espressif)

// ---- Wi-Fi (TCP) link -------------------------------------------------------
// Third transport for the frame stream (see link.h). Needs the Wi-Fi driver, so
// it is Espressif-only. Set -DBRIDGE_ENABLE_WIFI_LINK=0 to compile it out.
#ifndef BRIDGE_ENABLE_WIFI_LINK
#define BRIDGE_ENABLE_WIFI_LINK 1
#endif
#if BRIDGE_ENABLE_WIFI_LINK && defined(ARDUINO_ARCH_ESP32)
#define BRIDGE_WIFI_LINK 1
#else
#define BRIDGE_WIFI_LINK 0
#endif
// Arming the link below this much free heap is refused: Wi-Fi bring-up costs
// ~52 KB, and starting it thinner just crashes later, usually inside BLE. (The
// link's own ~4.5 KB of frame buffers are malloc'd by link_tcp_begin(), so a
// board that never calls EspLink.wifi.begin() pays nothing.)
#ifndef LINK_TCP_MIN_HEAP
#define LINK_TCP_MIN_HEAP 60000
#endif
// Dial-home backoff: attempt N waits N seconds, capped here, plus up to 1 s of
// jitter so 1000 boards don't all reconnect on the same tick after a restart.
#ifndef LINK_TCP_RETRY_MAX_MS
#define LINK_TCP_RETRY_MAX_MS 10000
#endif

// ---- task sizing & frame/buffer layout (architecture-independent) -----------
// PRIO/STACK are #ifndef-guarded so the nRF branch (above) can set values that
// fit its FreeRTOS (smaller priority range, stack depth counted in words). On
// ESP these take the original byte-counted defaults.
#ifndef TX_TASK_PRIO
#define TX_TASK_PRIO     12
#endif
#ifndef TX_TASK_STACK
#define TX_TASK_STACK    4096
#endif
#ifndef RX_TASK_PRIO
#define RX_TASK_PRIO     10
#endif
#ifndef RX_TASK_STACK
#define RX_TASK_STACK    8192
#endif
#ifndef SLOW_TASK_PRIO
#define SLOW_TASK_PRIO   9
#endif
#ifndef SLOW_TASK_STACK
#define SLOW_TASK_STACK  8192
#endif

// Logical frame layout: 4-byte header + payload (up to MAX_PAYLOAD) + 2-byte CRC.
#define MAX_FRAME      (4 + MAX_PAYLOAD + 2)
// COBS worst-case overhead: 1 extra byte per started 254-byte block, plus the
// 0x00 frame delimiter appended by tx_task.
#define ENC_BUF_SIZE   (MAX_FRAME + (MAX_FRAME / 254) + 2)

// RX ring absorbs the host's pipelined burst while a slow inline handler (e.g. an
// 80 ms I2C scan) blocks rx_task: the host caps in-flight bytes at 6400, and the
// ring holds that plus one frame so it can't overflow (errors counted, SYS_FREE_HEAP).
// TX ring is small on purpose — tx_task's cursor refills it every ~1 ms, so it
// only bridges wake-up latency, not whole frames. (2112 B on S3 native USB,
// holding a whole frame: measured no gain on a 2 KB echo or FS read.)
#define SERIAL_RX_BUF  8704
#define SERIAL_TX_BUF  1024

// Radio bring-up costs real heap (classic ESP32, core 3.3.6: ~52 KB first start,
// ~33 KB restart since ~18 KB stays resident). With a BLE central up, handlers
// refuse a bring-up landing below a ~6 KB floor (ST_NO_MEM) rather than starve the
// link — Wi-Fi + BLE + ESP-NOW together fits (~4 KB min free in a 30 s soak), but
// large transfers fail cleanly with NO_MEM while that thin. Ops on an already-
// running driver (scan/connect/softAP) cost only ~4-8 KB → the smaller WARM margin,
// which is what lets a BLE session run Wi-Fi + ESP-NOW. The UP/REUP margins
// apply to whichever user (STA/AP/ESP-NOW) brings the driver up. All -D overridable.
#ifndef WIFI_UP_BLE_MIN_HEAP
#define WIFI_UP_BLE_MIN_HEAP     58000
#endif
#ifndef WIFI_REUP_BLE_MIN_HEAP
#define WIFI_REUP_BLE_MIN_HEAP   39000
#endif
#ifndef RADIO_WARM_BLE_MIN_HEAP
#define RADIO_WARM_BLE_MIN_HEAP  8000
#endif

#define NET_MAX_SOCKETS 8
#define NET_WINDOW      4096   // per-socket credit window (bytes)

// Depth of the queue feeding bridge_slow (blocking handlers). Deeper = more
// concurrent slow requests can be in flight from a multi-threaded host before
// one is rejected with ST_BUSY; the cost is just queue slots (Req structs).
#define SLOWQ_DEPTH     32

// Depth of EACH per-link outbound frame queue (bridge_tx drains one stream
// per link with non-blocking writes). Replies wait up to 250 ms for a slot;
// events are dropped (and counted) when their link's queue is full. In-flight
// replies are bounded by the host's flow-control window (~3 frames), so 16
// slots is mostly event headroom.
#define TXQ_DEPTH       16

// rx_task / slow_task yield a scheduler tick at least this often even under
// continuous traffic. Without it a busy high-priority bridge task starves the
// core's idle task and trips the idle Task-WDT — a reset that looks like a
// random stall under sustained load. Cost: ~1 ms per this many messages.
#define RX_YIELD_EVERY  48

#define BLE_MAX_CHARS   16
