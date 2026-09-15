"""TEST-DESN: 桁上がり中のTBC読取り、逆戻り、真の32bit周回を検証。"""
import pytest

from pico.common import ExtendedCounter
from pico.config import CONFIG
from pico.mcp2518fd import MCP2518FD, CANError, TBC


def sampled_driver(values, last=None):
    can = MCP2518FD(None, lambda _: None, CONFIG, clock=lambda: 0, sleep=lambda _: None)
    stream = iter(values)
    def register(addr):
        assert addr == TBC
        return next(stream)
    can.reg = register
    if last is not None:
        can.counter.update(last)
    return can


@pytest.mark.parametrize("bits", [30, 32])
def test_backward_does_not_mutate_counter(bits):
    c = ExtendedCounter(bits)
    c.update(12416602)
    with pytest.raises(ValueError, match="COUNTER_BACKWARD"):
        c.update(12416601)
    assert c.total == c.last == 12416602
    assert c.update(12416612) == 12416612


@pytest.mark.parametrize("bits", [30, 32])
def test_real_wrap_and_old_event_timestamp(bits):
    c = ExtendedCounter(bits)
    modulus = 1 << bits
    c.update(modulus - 16)
    assert c.update(20) == modulus + 20
    assert c.past(modulus - 6) == modulus - 6


def test_half_range_is_ambiguous_and_rejected():
    c = ExtendedCounter()
    c.update(0)
    with pytest.raises(ValueError):
        c.update(1 << 31)
    assert c.total == 0 and c.last == 0


@pytest.mark.parametrize("boundary", [0x100, 0x10000, 0x1000000, 0x100000000])
def test_torn_read_at_every_byte_carry(boundary):
    # 下位byteが旧FF、上位byteが桁上がり後の混合値。CRC正常でも起こり得る。
    mask = 0xFFFFFFFF
    torn = (boundary + 255) & mask
    can = sampled_driver([torn, (boundary + 10) & mask, (boundary + 20) & mask],
                         last=boundary - 20)
    assert can.now_us() == boundary + 20
    assert can.tbc_retries == 1


def test_backward_sample_recovers_without_early_300_second_deadline():
    can = sampled_driver([12416590, 12416591, 12416610, 12416620], last=12416602)
    now = can.now_us()
    assert now == 12416610 and now < 300015662
    assert can.tbc_retries == 1


def test_large_stable_backward_read_is_error_not_duration():
    can = sampled_driver([100] * 17, last=1000000)
    with pytest.raises(CANError, match="TBC_UNSTABLE"):
        can.now_us()
    assert can.counter.total == can.counter.last == 1000000
    assert can.tbc_retries == 16


def test_no_coherent_sample_has_bounded_failure():
    can = sampled_driver([i * 256 for i in range(17)])
    with pytest.raises(CANError, match="TBC_UNSTABLE"):
        can.now_us()
    assert can.counter.last is None and can.tbc_retries == 16


def test_same_tick_is_legal():
    can = sampled_driver([1234, 1234], last=1234)
    assert can.now_us() == 1234
