"""SX1280 — Semtech 2.4 GHz LoRa / FLRC transceiver (SPI, command-based).

A "bring your own" SPI driver over the bridge's spi + gpio primitives, in the
SX126x family style but for the 2.4 GHz SX1280: every operation is a command
``transfer([opcode, ...args], cs=cs)`` framed by a BUSY-pin handshake — the chip
holds BUSY high while it digests the previous command, so we poll BUSY low
before each transfer.

NOT wired to the dev boards: this driver is datasheet-based (Semtech SX1280/1281
Data Sheet Rev 3.2, March 2020) and verified only at the protocol level by
``tests/test_sx128x.py`` (a fake SPI/GPIO that records frames and feeds canned
replies). The opcodes, the 2.4 GHz PLL frequency formula and the LoRa parameter
encodings below are cited from that datasheet; on-air behaviour has not been
exercised against real silicon.

    from esplink import Bridge

    with Bridge() as esp:
        # transmitter
        radio = esp.sx128x(cs=5, reset=4, busy=2, dio1=15,
                           freq=2_400_000_000, sf=7, bw=400_000, cr=1,
                           tx_power=13)
        radio.send(b"hello 2.4GHz")

        # receiver (same RF settings on the other node)
        radio = esp.sx128x(cs=5, reset=4, busy=2, dio1=15)
        pkt = radio.receive(timeout=5.0)   # bytes, or None on timeout / bad CRC
        if pkt:
            print(pkt)

Wiring: SPI (mode 0, MSB-first) on SCK/MISO/MOSI + CS, plus RESET (active low),
BUSY (chip→host, required) and optionally DIO1 (TxDone/RxDone IRQ, polled if
given). The SX1280 uses a 52 MHz XTAL, so FREQ_STEP = 52e6 / 2**18 ≈ 198.36 Hz.
"""
from __future__ import annotations

import time

# --- Command opcodes (SX1280 datasheet §11.4 "List of Commands") -------------
# NOTE: several opcodes differ from the SX126x sub-GHz family — verified against
# the SX1280 datasheet, e.g. WriteBuffer/ReadBuffer/GetIrqStatus/ClrIrqStatus.
_GET_STATUS = 0xC0
_WRITE_BUFFER = 0x1A          # SX1280: 0x1A  (SX126x uses 0x0E)
_READ_BUFFER = 0x1B           # SX1280: 0x1B  (SX126x uses 0x1E)
_SET_SLEEP = 0x84
_SET_STANDBY = 0x80
_SET_TX = 0x83
_SET_RX = 0x82
_SET_PACKET_TYPE = 0x8A
_SET_RF_FREQUENCY = 0x86
_SET_TX_PARAMS = 0x8E
_SET_BUFFER_BASE = 0x8F
_SET_MODULATION_PARAMS = 0x8B
_SET_PACKET_PARAMS = 0x8C
_GET_RX_BUFFER_STATUS = 0x17
_SET_DIO_IRQ_PARAMS = 0x8D
_GET_IRQ_STATUS = 0x15        # SX1280: 0x15  (SX126x uses 0x12)
_CLR_IRQ_STATUS = 0x97        # SX1280: 0x97  (SX126x uses 0x02)
_WRITE_REGISTER = 0x18
_READ_REGISTER = 0x19

# --- Constants ----------------------------------------------------------------
_STDBY_RC = 0x00              # SetStandby arg: internal RC oscillator
_PACKET_TYPE_LORA = 0x01      # SetPacketType: LoRa
_RAMP_20US = 0xE0             # SetTxParams ramp time code (datasheet §11.7.3)

# SX1280 uses a 52 MHz crystal; PLL resolution FREQ_STEP = XTAL / 2**18.
_XTAL_HZ = 52_000_000
_FREQ_DIV = 2 ** 18           # freq_reg = round(freq * 2**18 / 52e6)

# LoRa bandwidth -> SetModulationParams code (datasheet §11.7.7). These are
# SX1280-specific and unrelated to the SX126x BW codes.
_BW_CODES = {
    1_600_000: 0x0A,
    800_000: 0x18,
    400_000: 0x26,
    200_000: 0x34,
}

# After SetModulationParams(LoRa) the datasheet (§14.4.1) requires register
# 0x925 = 0x1E (SF5/6), 0x37 (SF7/8) or 0x32 (SF9-12), and bit 0 of 0x93C set
# (frequency-error compensation).
_REG_LORA_SF_CONFIG = 0x0925
_REG_FREQ_ERROR_CORRECTION = 0x093C

# LoRa preamble length is one byte, (exponent << 4) | mantissa, length =
# mantissa * 2**exponent (§14.4.2): 12 symbols = 6 * 2**1.
_PREAMBLE_12 = (1 << 4) | 6

# IRQ bit masks (datasheet §11.9, Table "IRQ register").
_IRQ_TX_DONE = 0x0001
_IRQ_RX_DONE = 0x0002
_IRQ_RX_TX_TIMEOUT = 0x4000
_IRQ_HEADER_ERROR = 0x0020
_IRQ_CRC_ERROR = 0x0040
_IRQ_ALL = 0xFFFF

# SetTx/SetRx period base 0x02 == 1 ms tick (datasheet §11.6.4 / §11.6.5).
_PERIOD_BASE_1MS = 0x02

_BUSY_TIMEOUT = 1.0           # seconds to wait for BUSY to fall before erroring


class SX128x:
    """Semtech SX128x (SX1280/1281) 2.4 GHz LoRa transceiver over the bridge SPI primitive."""

    def __init__(self, bridge, *, cs, reset, busy, dio1=None,
                 freq=2_400_000_000, tx_power=13, sf=7, bw=400_000, cr=1,
                 sck=None, miso=None, mosi=None, spi_freq=8_000_000,
                 init_spi=True):
        if not (2_400_000_000 <= freq <= 2_500_000_000):
            raise ValueError(f"freq {freq} Hz out of SX1280 ISM band (2.400-2.500 GHz)")
        if not (-18 <= tx_power <= 13):
            raise ValueError(f"tx_power {tx_power} dBm out of range (-18..+13)")
        if not (5 <= sf <= 12):
            raise ValueError(f"sf {sf} out of range (5..12)")
        if bw not in _BW_CODES:
            raise ValueError(f"bw {bw} Hz invalid; choose one of {sorted(_BW_CODES)}")
        if not (1 <= cr <= 7):  # 4/5..4/8, then long-interleave 4/5..4/7
            raise ValueError(f"cr {cr} out of range (1..7)")

        self._b = bridge
        self._cs = cs
        self._reset = reset
        self._busy = busy
        self._dio1 = dio1

        if init_spi:  # pins left out are the board's (esp.pins)
            self._b.spi.init(sck=sck, miso=miso, mosi=mosi, freq=spi_freq, mode=0)

        gpio = self._b.gpio
        gpio.mode(reset, "output")
        gpio.mode(busy, "input")
        if dio1 is not None:
            gpio.mode(dio1, "input")

        self._reset_chip()
        self._command(_SET_STANDBY, _STDBY_RC)              # SetStandby(STDBY_RC)
        self._command(_SET_PACKET_TYPE, _PACKET_TYPE_LORA)  # SetPacketType(LoRa)
        self._apply_frequency(freq)                         # SetRfFrequency
        self._command(_SET_BUFFER_BASE, 0x00, 0x00)         # SetBufferBaseAddress(tx=0, rx=0)
        # SetModulationParams(LoRa): SF in the high nibble, BW code, CR code.
        self._command(_SET_MODULATION_PARAMS, (sf << 4) & 0xF0, _BW_CODES[bw], cr)
        sf_cfg = 0x1E if sf <= 6 else 0x37 if sf <= 8 else 0x32
        self._write_register(_REG_LORA_SF_CONFIG, sf_cfg)
        fec = self._read_command(_READ_REGISTER, 1, *_REG_FREQ_ERROR_CORRECTION.to_bytes(2, "big"))
        self._write_register(_REG_FREQ_ERROR_CORRECTION, fec[0] | 0x01)
        self._apply_packet_params(0)                        # SetPacketParams (payload set per-send)
        # SetTxParams: power code = dBm + 18 (0..31 for -18..+13 dBm), ramp time.
        self._command(_SET_TX_PARAMS, tx_power + 18, _RAMP_20US)
        # SetDioIrqParams: enable TxDone | RxDone | RxTxTimeout | header/CRC
        # errors in the IRQ register (a masked IRQ never sets its bit, so a bad
        # CRC would otherwise read as a good packet); route the done/timeout
        # ones to DIO1 (16-bit BE masks; DIO2/DIO3 unused).
        dio1 = _IRQ_TX_DONE | _IRQ_RX_DONE | _IRQ_RX_TX_TIMEOUT
        mask = dio1 | _IRQ_HEADER_ERROR | _IRQ_CRC_ERROR
        self._command(_SET_DIO_IRQ_PARAMS, mask >> 8, mask & 0xFF, dio1 >> 8, dio1 & 0xFF,
                      0x00, 0x00, 0x00, 0x00)

    # --- low-level command plumbing ------------------------------------------
    def _wait_busy(self) -> None:
        """Block until BUSY falls (chip ready for the next command)."""
        deadline = time.monotonic() + _BUSY_TIMEOUT
        while self._b.gpio.read(self._busy):
            if time.monotonic() > deadline:
                raise TimeoutError("SX1280 BUSY stuck high")

    def _command(self, opcode: int, *args: int) -> None:
        """Write a command: wait BUSY low, then transfer([opcode, *args])."""
        self._wait_busy()
        self._b.spi.transfer(bytes([opcode, *args]), cs=self._cs)

    def _read_command(self, opcode: int, nread: int, *args: int) -> bytes:
        """Read command: send opcode (+args) + a NOP status byte + nread dummies;
        the chip returns its data after the status byte. Returns the nread bytes."""
        self._wait_busy()
        # Frame = opcode | args | status(0x00) | nread*0x00; reply data trails status.
        tx = bytes([opcode, *args, 0x00]) + b"\x00" * nread
        rx = self._b.spi.transfer(tx, cs=self._cs)
        return rx[len(args) + 2:]

    def _write_register(self, addr: int, value: int) -> None:
        self._command(_WRITE_REGISTER, addr >> 8, addr & 0xFF, value)

    def _reset_chip(self) -> None:
        """Active-low RESET pulse, then wait for BUSY to settle."""
        gpio = self._b.gpio
        gpio.write(self._reset, 1)
        gpio.write(self._reset, 0)   # assert reset (active low)
        gpio.write(self._reset, 1)   # release
        self._wait_busy()

    # --- configuration helpers -----------------------------------------------
    def _apply_frequency(self, freq: int) -> None:
        # 2.4 GHz PLL: freq_reg = round(freq * 2**18 / 52e6); 3 bytes, MSB first.
        reg = round(freq * _FREQ_DIV / _XTAL_HZ)
        self._command(_SET_RF_FREQUENCY,
                      (reg >> 16) & 0xFF, (reg >> 8) & 0xFF, reg & 0xFF)

    def _apply_packet_params(self, payload_len: int) -> None:
        # SetPacketParams(LoRa), 7 params (§14.4.2): preamble (one exp/mant
        # byte), explicit header (0x00), payload len, CRC on (0x20), standard
        # IQ (0x40), two reserved.
        self._command(_SET_PACKET_PARAMS, _PREAMBLE_12, 0x00, payload_len & 0xFF,
                      0x20, 0x40, 0x00, 0x00)

    def _get_irq_status(self) -> int:
        r = self._read_command(_GET_IRQ_STATUS, 2)
        return (r[0] << 8) | r[1]

    def _clear_irq_status(self, mask: int = _IRQ_ALL) -> None:
        self._command(_CLR_IRQ_STATUS, (mask >> 8) & 0xFF, mask & 0xFF)

    # --- public API -----------------------------------------------------------
    def set_frequency(self, hz: int) -> None:
        """Retune the RF carrier (2.400-2.500 GHz)."""
        if not (2_400_000_000 <= hz <= 2_500_000_000):
            raise ValueError(f"freq {hz} Hz out of SX1280 ISM band (2.400-2.500 GHz)")
        self.standby()
        self._apply_frequency(hz)

    def standby(self) -> None:
        """Put the radio in STDBY_RC."""
        self._command(_SET_STANDBY, _STDBY_RC)

    def sleep(self) -> None:
        """Put the radio to sleep (config retained: data buffer + RAM kept)."""
        # SetSleep config: bit1 = retain data buffer, bit0 = retain data RAM.
        self._command(_SET_SLEEP, 0x03)

    def send(self, data) -> None:
        """Transmit a LoRa packet and block until TxDone (or BUSY/IRQ timeout)."""
        data = bytes(data)
        if not 1 <= len(data) <= 255:
            raise ValueError(f"payload must be 1..255 bytes, got {len(data)}")
        self.standby()
        self._command(_SET_BUFFER_BASE, 0x00, 0x00)
        self._command(_WRITE_BUFFER, 0x00, *data)   # WriteBuffer(offset=0, data)
        self._apply_packet_params(len(data))
        self._clear_irq_status()
        # SetTx: periodBase=1ms, count=0xFFFF -> long timeout guard.
        self._command(_SET_TX, _PERIOD_BASE_1MS, 0xFF, 0xFF)
        self._wait_irq(_IRQ_TX_DONE, _IRQ_RX_TX_TIMEOUT, timeout=10.0)
        self._clear_irq_status()

    def receive(self, timeout=None):
        """Receive one LoRa packet. Returns bytes, or None on timeout / CRC error.

        ``timeout`` is in seconds (None = block indefinitely on RxDone).
        """
        self.standby()
        self._clear_irq_status()
        self._command(_SET_RX, _PERIOD_BASE_1MS, 0xFF, 0xFF)   # continuous-ish RX window
        try:
            irq = self._wait_irq(_IRQ_RX_DONE, _IRQ_RX_TX_TIMEOUT, timeout=timeout)
        except TimeoutError:
            self.standby()
            return None
        bad = _IRQ_RX_TX_TIMEOUT | _IRQ_HEADER_ERROR | _IRQ_CRC_ERROR
        if irq & bad or not (irq & _IRQ_RX_DONE):
            self._clear_irq_status()
            return None
        self._clear_irq_status()
        status = self._read_command(_GET_RX_BUFFER_STATUS, 2)  # [payloadLen, startPtr]
        length, start = status[0], status[1]
        if length == 0:
            return None
        payload = self._read_command(_READ_BUFFER, length, start)  # ReadBuffer(offset)
        return bytes(payload[:length])

    # --- IRQ waiting ----------------------------------------------------------
    def _wait_irq(self, done_mask: int, fail_mask: int, *, timeout=None) -> int:
        """Poll the IRQ register (gated by DIO1 if wired) until a done/fail bit
        is set. Returns the IRQ word. Raises TimeoutError when ``timeout`` elapses."""
        deadline = None if timeout is None else time.monotonic() + timeout
        want = done_mask | fail_mask
        while True:
            # If DIO1 is wired, only spend an SPI read once the line asserts.
            if self._dio1 is None or self._b.gpio.read(self._dio1):
                irq = self._get_irq_status()
                if irq & want:
                    return irq
            if deadline is not None and time.monotonic() > deadline:
                raise TimeoutError("SX1280 IRQ wait timed out")
