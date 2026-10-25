// Pro Micro nRF52840: the nice!nano footprint, sold as ProMicro or SuperMini.
#ifndef _PROMICRO_NRF52840_H_
#define _PROMICRO_NRF52840_H_

#define VARIANT_MCK       (64000000ul)

// the crystal is on these boards. A batch without one never advertises: swap to LFRC
#define USE_LFXO
//#define USE_LFRC

#include "WVariant.h"

#ifdef __cplusplus
extern "C"
{
#endif // __cplusplus

// the index is the silkscreen number. 11, 12, 13 and 17 are the board's parts, not header pins
#define PINS_COUNT              (25)
#define NUM_DIGITAL_PINS        (25)
#define NUM_ANALOG_INPUTS       (3)
#define NUM_ANALOG_OUTPUTS      (0)

// the only LED on a pin. The other is the charger's; colours vary by board
#define LED_BLUE                (11)    // Bluefruit wants this name
#define PIN_LED                 (LED_BLUE)
#define LED_BUILTIN             (PIN_LED)
#define LED_STATE_ON            (1)     // anode on the pin
#define LED_PWR                 (PINS_COUNT)
#define PIN_NEOPIXEL            (PINS_COUNT)
#define NEOPIXEL_NUM            (0)

#define PIN_BUTTON1             (PINS_COUNT)  // no button, RST is a pad

static const uint8_t D0  = 0 ;  // P0.08, RX
static const uint8_t D1  = 1 ;  // P0.06, TX
static const uint8_t D2  = 2 ;  // P0.17
static const uint8_t D3  = 3 ;  // P0.20
static const uint8_t D4  = 4 ;  // P0.22, SDA here
static const uint8_t D5  = 5 ;  // P0.24, SCL here
static const uint8_t D6  = 6 ;  // P1.00
static const uint8_t D7  = 7 ;  // P0.11
static const uint8_t D8  = 8 ;  // P1.04
static const uint8_t D9  = 9 ;  // P1.06
static const uint8_t D10 = 10;  // P0.09, NFC1
static const uint8_t D14 = 14;  // P1.11, MISO
static const uint8_t D15 = 15;  // P1.13, SCK
static const uint8_t D16 = 16;  // P0.10, NFC2, MOSI
static const uint8_t D18 = 18;  // P1.15
static const uint8_t D19 = 19;  // P0.02, AIN0
static const uint8_t D20 = 20;  // P0.29, AIN5
static const uint8_t D21 = 21;  // P0.31, AIN7

// three pads the clones add mid-board, by the name printed next to them
static const uint8_t P1_01 = 22;
static const uint8_t P1_02 = 23;
static const uint8_t P1_07 = 24;

// NFC until one power cycle after the core clears UICR, so nothing here uses them
#define PIN_NFC1                (10)
#define PIN_NFC2                (16)

// P0.13 gates the VCC rail. HIGH is on here, a nice!nano v1 is the other way up
#define PIN_VCC_ENABLE          (12)
#define VCC_ENABLE_ON           (1)

// the schematic's divider is wired to P0.24 on real boards, which has no ADC
#define PIN_VBAT_DIVIDER        (13)

// the cell through VDDH/5, in mV. USB raises it. Trim against a meter, the 0.6 V ref drifts
#define VBAT_UV_PER_LSB         (4395)  // 12 bit: 0.6 V / (1/6) / 4096, times the /5
extern uint32_t batteryMilliVolts(void);

// only these three reach the ADC, whatever the silkscreen calls the rest
#define PIN_A1                  (19)   // P0.02, AIN0
#define PIN_A2                  (20)   // P0.29, AIN5
#define PIN_A3                  (21)   // P0.31, AIN7

static const uint8_t A0  = 18;   // P1.15, digital only: port 1 has no ADC
static const uint8_t A1  = PIN_A1;
static const uint8_t A2  = PIN_A2;
static const uint8_t A3  = PIN_A3;

#define ADC_RESOLUTION          (12)

#define PIN_SERIAL1_RX          (0)
#define PIN_SERIAL1_TX          (1)

#define SPI_INTERFACES_COUNT    (1)

#define PIN_SPI_MISO            (14)
#define PIN_SPI_MOSI            (16)
#define PIN_SPI_SCK             (15)

static const uint8_t SS   = 18;
static const uint8_t MOSI = PIN_SPI_MOSI;
static const uint8_t MISO = PIN_SPI_MISO;
static const uint8_t SCK  = PIN_SPI_SCK ;

#define WIRE_INTERFACES_COUNT   (1)

#define PIN_WIRE_SDA            (4)
#define PIN_WIRE_SCL            (5)

static const uint8_t SDA = PIN_WIRE_SDA;
static const uint8_t SCL = PIN_WIRE_SCL;

// no QSPI flash: the filesystem lives in internal flash

#ifdef __cplusplus
}
#endif

#endif
