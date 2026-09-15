"""DESN-SW-002: CONFIGへの辞書リテラル代入だけを読み込む。"""

CONFIG = {
    "schema": 1,
    "revision": "four-id-50-500-spi8m-v2",
    "device_config_id": "pico-mcp2518fd-20m-v1",
    "duration_ms": 60000,
    "log_dir": "logs",
    "profiles": [
        {"profile_id": "T1", "can_id": 0x300, "ide": False, "fdf": False,
         "brs": False, "data": "1112131415161718", "period_ms": 50,
         "start_key": "a", "stop_key": "b"},
        {"profile_id": "T2", "can_id": 0x301, "ide": False, "fdf": False,
         "brs": False, "data": "2122232425262728", "period_ms": 500,
         "start_key": "c", "stop_key": "d"},
        {"profile_id": "T3", "can_id": 0x18FF0101, "ide": True, "fdf": True,
         "brs": True,
         "data": "000102030405060708090A0B0C0D0E0F101112131415161718191A1B1C1D1E1F202122232425262728292A2B2C2D2E2F303132333435363738393A3B3C3D3E3F",
         "period_ms": 1000, "start_key": "e", "stop_key": "f"},
        {"profile_id": "T4", "can_id": 0x18FF0102, "ide": True, "fdf": True,
         "brs": True,
         "data": "404142434445464748494A4B4C4D4E4F505152535455565758595A5B5C5D5E5F606162636465666768696A6B6C6D6E6F707172737475767778797A7B7C7D7E7F",
         "period_ms": 10000, "start_key": "g", "stop_key": "h"},
    ],
}
