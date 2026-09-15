"""DESN-SW-008/011: MicroPython上の時刻回帰試験。CAN送信は行わない。"""
from common import ExtendedCounter
from config import CONFIG
from mcp2518fd import MCP2518FD, CANError

for bits in (30, 32):
    c = ExtendedCounter(bits)
    c.update(12416602)
    try:
        c.update(12416601)
    except ValueError:
        pass
    else:
        raise AssertionError("逆戻りを許容")
    assert c.last == c.total == 12416602
    assert c.update(12416612) == 12416612
    c = ExtendedCounter(bits)
    c.update((1 << bits) - 16)
    assert c.update(20) == (1 << bits) + 20

for boundary in (0x100, 0x10000, 0x1000000, 0x100000000):
    can = MCP2518FD(None, lambda _: None, CONFIG)
    values = iter([(boundary + 255) & 0xFFFFFFFF,
                   (boundary + 10) & 0xFFFFFFFF, (boundary + 20) & 0xFFFFFFFF])
    can.reg = lambda _: next(values)
    can.counter.update(boundary - 20)
    assert can.now_us() == boundary + 20

can = MCP2518FD(None, lambda _: None, CONFIG)
can.counter.update(1000000)
can.reg = lambda _: 100
try:
    can.now_us()
except CANError as exc:
    assert str(exc) == "TBC_UNSTABLE"
else:
    raise AssertionError("不安定な時刻を許容")
assert can.counter.total == 1000000
print("PICO_TIMESTAMP_SELFTEST_PASS", "逆戻り/30・32bit周回/全byte桁上がり/有限再試行")
