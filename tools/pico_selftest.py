"""TEST-DESN: MicroPython専用高速処理を実機で照合。CAN送信はしない。"""
from common import strict_json, crc16
from usb.device.core import Buffer

invalid = [b'{"a":1,"a":2}', b'{"a":1,"\\u0061":2}',
           b'{"x":{"a":1,"a":2}}', b'{"a":[[[[1]]]]}',
           b'{"a":"\\u3042"}', b'{"a":"\\n"}', b'{"a":1}\r',
           b'[]', b'{"a":', b'"unterminated', b'x' * 1024]
for raw in invalid:
    try:
        strict_json(raw)
    except ValueError:
        pass
    else:
        raise AssertionError(raw)
assert strict_json(b'{"a":{"x":1},"b":{"x":2}}')["b"]["x"] == 2
assert strict_json(b'{"a":"a\\\"b"}')["a"] == 'a"b'
assert crc16(b"123456789") == 0xAEE7

# 部分読出し中にpending writeを完了する経路も、元のバイト順を維持する。
buf = Buffer(2048)
payload = bytes(range(256)) * 8
assert buf.write(payload) == 2048
for i in range(32):
    assert bytes(buf.pend_read()[:64]) == payload[i * 64:(i + 1) * 64]
    buf.finish_read(64)
assert buf.readable() == 0
assert buf.write(b"abcdef") == 6
pending = buf.pend_write(3)
pending[:] = b"XYZ"
buf.finish_read(2)
buf.finish_write(3)
assert bytes(buf.pend_read()) == b"cdefXYZ"
print("PICO_SELFTEST_PASS", "JSON/CRC/USB_BUFFER", len(invalid) + 37)
