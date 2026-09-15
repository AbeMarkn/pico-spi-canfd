"""TEST-SPEC/DESN: 入力境界、DLC/ID、CRC、部分I/O、設定の非実行。"""
import json
import struct
from pathlib import Path

import pytest

from host.main import load_config
from pico.common import (crc16, strict_json, Lines, Ring, ExtendedCounter,
                         id_word, unpack_id, tx_object, rx_object, validate_profile, DLC_LENGTHS)


def profile(**changes):
    p = {"profile_id": "X", "can_id": 0x123, "ide": False, "fdf": True,
         "brs": True, "data": "0102030405060708", "period_ms": 100}
    p.update(changes)
    return p


@pytest.mark.parametrize("data", [b'{"a":1,"a":2}', b'{"x":{"a":1,"a":2}}',
    b'{"a":1,"\\u0061":2}', b'{"a":[[[[1]]]]}', b'{"x":"\\u3042"}',
    b'{"x":"\\n"}', b'{"x":1}\r', b'[]', b'{"a":', b'x' * 1024])
def test_strict_json_rejects(data):
    with pytest.raises(ValueError):
        strict_json(data)


def test_json_quoted_delimiters_and_separate_objects():
    obj = {"a": {"x": '"{:['}, "b": {"x": 2}}
    assert strict_json(json.dumps(obj).encode()) == obj


def test_line_overflow_recovery_and_fragmentation():
    lines = Lines()
    assert lines.feed(b'{"a":') == []
    assert lines.feed(b'1}\n') == [b'{"a":1}']
    assert lines.feed(b"x" * 1024) == []
    assert lines.feed(b"junk\n{}\n") == [None, b"{}"]
    assert len(lines.buf) == 0


@pytest.mark.parametrize("length", DLC_LENGTHS)
def test_all_fd_dlc(length):
    p = profile(data="A5" * length)
    raw = tx_object(p, 17)
    ident, flags = struct.unpack_from("<II", raw)
    assert flags & 15 == DLC_LENGTHS.index(length)
    assert flags >> 9 == 17
    decoded = rx_object(struct.pack("<III", ident, flags, 1000) + raw[8:])
    assert decoded["data"] == p["data"]
    assert decoded["length"] == length


@pytest.mark.parametrize("changes", [dict(can_id=0x800), dict(can_id=True), dict(ide=1),
    dict(fdf=False, brs=True), dict(fdf=False, brs=False, data="00" * 12),
    dict(data="00" * 9), dict(data="ab"), dict(data="0"), dict(data="GG"),
    dict(period_ms=9), dict(period_ms=60001), dict(period_ms=True), dict(extra=1)])
def test_profile_rejects(changes):
    with pytest.raises(ValueError):
        validate_profile(profile(**changes))


def test_extended_id_known_word_and_classic_rtr():
    # データシートの独立ビット位置。連続29bitの丸ごとコピーを検出。
    assert id_word(0x18FF0101, True) == 0x18080E3F
    assert unpack_id(0x18080E3F, True) == 0x18FF0101
    assert id_word(0x7FF, False) == 0x7FF
    rx = rx_object(struct.pack("<III", 0x123, 0x2F, 9))
    assert rx["rtr"] and rx["length"] == 0 and rx["requested_length"] == 8
    with pytest.raises(ValueError):
        rx_object(struct.pack("<III", 0x123, 0xAF, 9))


def test_crc_reference_and_streaming():
    assert crc16(b"123456789") == 0xAEE7
    assert crc16(b"456789", crc16(b"123")) == 0xAEE7


def test_ring_and_timestamp_wrap():
    q = Ring(2)
    assert q.put(1) and q.put(2) and not q.put(3)
    assert q.get() == 1
    assert q.put(3)
    assert [q.get(), q.get(), q.get()] == [2, 3, None]
    c = ExtendedCounter()
    c.update(0xFFFFFFF0)
    assert c.update(20) == 0x100000014
    assert c.past(0xFFFFFFFA) == 0xFFFFFFFA


@pytest.mark.parametrize("source", ['import os\nCONFIG={}', 'CONFIG=dict(a=1)',
    'CONFIG={"x":1,"x":2}', 'CONFIG={"x":1+2}', 'CONFIG={**{}}',
    'CONFIG={}; open("BAD", "w")', 'x=CONFIG={}'])
def test_config_does_not_execute(tmp_path, source):
    path = tmp_path / "config.py"
    path.write_text(source)
    with pytest.raises((ValueError, TypeError)):
        load_config(path)
    assert not (tmp_path / "BAD").exists()


def test_sample_four_profiles():
    cfg = load_config(Path(__file__).parents[1] / "host/config.py")
    assert [p["period_ms"] for p in cfg["profiles"]] == [50, 500, 1000, 10000]
    assert [len(p["data"]) // 2 for p in cfg["profiles"]] == [8, 8, 64, 64]
