"""UartPort behaves like pyserial's Serial (against a TX->RX loopback in the fake)."""
import threading
import time


def test_pyserial_semantics(bridge):
    with bridge.uart.init(baud=9600) as port:
        assert port.is_open and port.baudrate == 9600
        assert port.write(b"abc\nde") == 6
        port.timeout = 1
        assert port.read(2) == b"ab"                 # waits for exactly size bytes
        assert port.readline() == b"c\n"
        assert port.read(5, timeout=0.05) == b"de"   # fewer on timeout
        assert port.read_all() == b""
    assert not port.is_open


def test_read_blocks_until_bytes_arrive(bridge):
    port = bridge.uart.init()
    port.timeout = 2
    threading.Timer(0.1, port.write, (b"xyz",)).start()
    t0 = time.monotonic()
    assert port.read(3) == b"xyz" and time.monotonic() - t0 < 1.5


def test_iterating_yields_lines_until_timeout(bridge):
    port = bridge.uart.init()
    port.timeout = 0.1
    port.write(b"one\ntwo\n")
    assert port.readlines() == [b"one\n", b"two\n"]
