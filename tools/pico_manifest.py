"""DESN-SW-013: 保守REPLで配置ファイルSHA-256と停止モードを読戻す。"""
import hashlib
import binascii
import json
from machine import SPI, Pin
from config import CONFIG
from mcp2518fd import MCP2518FD

manifest = {}
for path in ("boot.py", "config.py", "common.py", "main.py", "mcp2518fd.py",
             "lib/usb/device/__init__.py", "lib/usb/device/core.py", "lib/usb/device/cdc.py"):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            data = f.read(4096)
            if not data:
                break
            digest.update(data)
    manifest["pico/" + path] = binascii.hexlify(digest.digest()).decode()
spi = SPI(0, baudrate=1000000, sck=Pin(18), mosi=Pin(19), miso=Pin(16))
can = MCP2518FD(spi, Pin(17, Pin.OUT, value=1), CONFIG)
status = can.initialize()
assert status["mode"] == 4
print("MANIFEST", json.dumps({"sha256": manifest, "hardware": status}))
