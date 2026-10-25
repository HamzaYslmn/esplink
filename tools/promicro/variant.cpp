#include "variant.h"
#include "wiring_constants.h"
#include "wiring_digital.h"
#include "nrf.h"

// P1.xx is 32 + xx. Header gaps hold the board's own parts, so an index is the silkscreen number
const uint32_t g_ADigitalPinMap[] =
{
     8, // D0  is P0.08 (RX)
     6, // D1  is P0.06 (TX)
    17, // D2  is P0.17
    20, // D3  is P0.20
    22, // D4  is P0.22 (SDA)
    24, // D5  is P0.24 (SCL)
    32, // D6  is P1.00
    11, // D7  is P0.11
    36, // D8  is P1.04
    38, // D9  is P1.06
     9, // D10 is P0.09 (NFC1)

    15, // 11  is P0.15, the onboard LED
    13, // 12  is P0.13, the VCC rail switch
     4, // 13  is P0.04, the v1 battery divider

    43, // D14 is P1.11 (MISO)
    45, // D15 is P1.13 (SCK)
    10, // D16 is P0.10 (NFC2, MOSI)

    30, // 17  is P0.30, on no header. Filler, so D18 lands on index 18

    47, // D18 is P1.15
     2, // D19 is P0.02 (AIN0)
    29, // D20 is P0.29 (AIN5)
    31, // D21 is P0.31 (AIN7)

    33, // P1_01, mid-board on a clone, absent on a nice!nano
    34, // P1_02
    39, // P1_07
};

// the core stops at analogReadVDD, the regulated rail. Own gain and resolution, so a sketch's
// analogReference() cannot move the answer
uint32_t batteryMilliVolts(void)
{
    volatile int16_t raw = 0;

    NRF_SAADC->RESOLUTION = SAADC_RESOLUTION_VAL_12bit;
    NRF_SAADC->ENABLE = 1;
    NRF_SAADC->CH[0].CONFIG = (SAADC_CH_CONFIG_RESP_Bypass  << SAADC_CH_CONFIG_RESP_Pos)
                            | (SAADC_CH_CONFIG_RESP_Bypass  << SAADC_CH_CONFIG_RESN_Pos)
                            | (SAADC_CH_CONFIG_GAIN_Gain1_6 << SAADC_CH_CONFIG_GAIN_Pos)
                            | (SAADC_CH_CONFIG_REFSEL_Internal << SAADC_CH_CONFIG_REFSEL_Pos)
                            | (SAADC_CH_CONFIG_TACQ_10us    << SAADC_CH_CONFIG_TACQ_Pos)
                            | (SAADC_CH_CONFIG_MODE_SE      << SAADC_CH_CONFIG_MODE_Pos);
    NRF_SAADC->CH[0].PSELP = SAADC_CH_PSELP_PSELP_VDDHDIV5;
    NRF_SAADC->CH[0].PSELN = SAADC_CH_PSELN_PSELN_NC;
    NRF_SAADC->RESULT.PTR = (uint32_t)&raw;
    NRF_SAADC->RESULT.MAXCNT = 1;

    NRF_SAADC->TASKS_START = 1;
    while (!NRF_SAADC->EVENTS_STARTED);
    NRF_SAADC->EVENTS_STARTED = 0;
    NRF_SAADC->TASKS_SAMPLE = 1;
    while (!NRF_SAADC->EVENTS_END);
    NRF_SAADC->EVENTS_END = 0;
    NRF_SAADC->TASKS_STOP = 1;
    while (!NRF_SAADC->EVENTS_STOPPED);
    NRF_SAADC->EVENTS_STOPPED = 0;
    NRF_SAADC->ENABLE = 0;

    if (raw < 0) raw = 0;  // the SAADC reads a little below zero at the rail
    return ((uint32_t)raw * VBAT_UV_PER_LSB) / 1000;
}

void initVariant()
{
    // power the VCC pins before anything on them is probed
    pinMode(PIN_VCC_ENABLE, OUTPUT);
    digitalWrite(PIN_VCC_ENABLE, VCC_ENABLE_ON);

    pinMode(PIN_LED, OUTPUT);
    digitalWrite(PIN_LED, !LED_STATE_ON);
}
