"""DESN-SW-002/003/011: CPythonとMicroPythonで共用する境界検証。"""

import json
import struct
import binascii

try:
    import micropython
except ImportError:
    # DESN-SW-002
    class micropython:
        # DESN-SW-002
        @staticmethod
        def native(fn):
            return fn

VERSION = "0.1.0"
DLC_LENGTHS = (0, 1, 2, 3, 4, 5, 6, 7, 8, 12, 16, 20, 24, 32, 48, 64)
PROFILE_FIELDS = ("profile_id", "can_id", "ide", "fdf", "brs", "data", "period_ms")


# DESN-SW-002
def integer(value, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError("INTEGER_RANGE")
    return value


# DESN-SW-002
def name(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 48:
        raise ValueError("NAME")
    if any(not ("a" <= c <= "z" or "A" <= c <= "Z" or "0" <= c <= "9" or c in "_-.")
           for c in value):
        raise ValueError("NAME")
    return value


# DESN-SW-002
def validate_profile(p, host=False):
    fields = PROFILE_FIELDS + (("start_key", "stop_key") if host else ())
    if not isinstance(p, dict) or set(p) != set(fields):
        raise ValueError("PROFILE_FIELDS")
    name(p["profile_id"])
    for key in ("ide", "fdf", "brs"):
        if type(p[key]) is not bool:
            raise ValueError("BOOL_REQUIRED")
    integer(p["can_id"], 0, 0x1FFFFFFF if p["ide"] else 0x7FF)
    integer(p["period_ms"], 10, 60000)
    data = p["data"]
    if not isinstance(data, str) or len(data) % 2 or len(data) > 128:
        raise ValueError("DATA_LENGTH")
    if any(c not in "0123456789ABCDEF" for c in data):
        raise ValueError("DATA_HEX")
    if len(data) // 2 not in (DLC_LENGTHS if p["fdf"] else DLC_LENGTHS[:9]):
        raise ValueError("DLC_LENGTH")
    if not p["fdf"] and p["brs"]:
        raise ValueError("CLASSIC_BRS")
    if host:
        for key in ("start_key", "stop_key"):
            if not isinstance(p[key], str) or len(p[key]) != 1 or p[key] not in "abcdefghijklmnopqrstuvwxyz0123456789":
                raise ValueError("KEY")
        if p["start_key"] == p["stop_key"]:
            raise ValueError("KEY_CONFLICT")
    return {k: p[k] for k in fields}


# DESN-SW-003
@micropython.native
def strict_json(raw):
    """重複キーをパーサが潰す前に字句走査。深さ・ASCII・長さも制限する。"""
    if len(raw) > 1023 or not raw:
        raise ValueError("JSON_ENCODING_LENGTH")
    for c in raw:
        if c < 32 or c > 126:
            raise ValueError("JSON_ENCODING_LENGTH")
    s = bytes(raw).decode("ascii")
    stack, i = [], 0
    while i < len(s):
        c = s[i]
        if c in "{[":
            stack.append(set() if c == "{" else None)
            if len(stack) > 4:
                raise ValueError("JSON_DEPTH")
        elif c in "}]":
            if not stack:
                raise ValueError("JSON_STRUCTURE")
            stack.pop()
        elif c == '"':
            start = i
            i = s.find('"', i + 1)
            while i >= 0:
                back = i - 1
                while back > start and s[back] == "\\":
                    back -= 1
                if (i - back - 1) % 2 == 0:
                    break
                i = s.find('"', i + 1)
            if i < 0:
                raise ValueError("JSON_STRING")
            value = s[start + 1:i]
            if "\\" in value:
                value = json.loads(s[start:i + 1])
                for c in value:
                    if ord(c) < 32 or ord(c) > 126:
                        raise ValueError("JSON_STRING")
            if len(value) > 128:
                raise ValueError("JSON_STRING")
            j = i + 1
            while j < len(s) and s[j] == " ":
                j += 1
            if j < len(s) and s[j] == ":":
                if not stack or stack[-1] is None or value in stack[-1]:
                    raise ValueError("JSON_DUPLICATE_KEY")
                stack[-1].add(value)
        i += 1
    obj = json.loads(s)
    if not isinstance(obj, dict):
        raise ValueError("JSON_OBJECT")
    return obj


# DESN-SW-002
@micropython.native
def encode(obj):
    raw = json.dumps(obj, separators=(",", ":")).encode("ascii") + b"\n"
    if len(raw) > 1024:
        raise ValueError("OUTPUT_TOO_LONG")
    return raw


# DESN-SW-002
class Lines:
    """DESN-SW-003: LFまで破棄する状態を持つ、有限長の受信器。"""

    # DESN-SW-003
    def __init__(self):
        self.buf = bytearray()
        self.discard = False

    # DESN-SW-003
    @micropython.native
    def feed(self, data):
        result = []
        for c in data:
            if c == 10:
                result.append(None if self.discard else bytes(self.buf))
                self.buf = bytearray()
                self.discard = False
            elif not self.discard:
                if len(self.buf) == 1023:
                    self.buf = bytearray()
                    self.discard = True
                else:
                    self.buf.append(c)
        return result


# DESN-SW-002
class Ring:
    """DESN-SW-011: 枠を事前確保し、満杯を呼出側へ通知する。"""

    # DESN-SW-011
    def __init__(self, capacity):
        self.items = [None] * capacity
        self.head = self.tail = self.count = 0

    # DESN-SW-011
    @micropython.native
    def put(self, item):
        if self.count == len(self.items):
            return False
        self.items[self.head] = item
        self.head = (self.head + 1) % len(self.items)
        self.count += 1
        return True

    # DESN-SW-011
    @micropython.native
    def get(self):
        if not self.count:
            return None
        item = self.items[self.tail]
        self.items[self.tail] = None
        self.tail = (self.tail + 1) % len(self.items)
        self.count -= 1
        return item


# DESN-SW-002
class ExtendedCounter:
    """DESN-SW-008: 半周未満の間隔で呼ぶカウンタ拡張。"""

    # DESN-SW-008
    def __init__(self, bits=32):
        self.mask = (1 << bits) - 1
        self.half = 1 << (bits - 1)
        self.last = None
        self.total = 0

    # DESN-SW-008
    @micropython.native
    def update(self, raw):
        if self.last is None:
            self.total = raw
        else:
            delta = (raw - self.last) & self.mask
            # 半周未満の呼出し間隔が前提。逆戻りを一周分の経過にしない。
            if delta >= self.half:
                raise ValueError("COUNTER_BACKWARD_OR_GAP")
            self.total += delta
        self.last = raw
        return self.total

    # DESN-SW-008
    @micropython.native
    def past(self, raw):
        return self.total - ((self.last - raw) & self.mask)


# DESN-SW-006
def id_word(can_id, ide):
    """MCP2518FD: SID[10:0]とEID[28:11]に分割。"""
    return ((can_id >> 18) | ((can_id & 0x3FFFF) << 11)) if ide else can_id


# DESN-SW-006
def unpack_id(word, ide):
    return ((word & 0x7FF) << 18) | ((word >> 11) & 0x3FFFF) if ide else word & 0x7FF


# DESN-SW-006
def tx_object(p, seq):
    validate_profile(p)
    integer(seq, 0, 0x7FFFFF)
    data = binascii.unhexlify(p["data"])
    flags = DLC_LENGTHS.index(len(data)) | (p["ide"] << 4) | (p["brs"] << 6) | (p["fdf"] << 7) | (seq << 9)
    return struct.pack("<II", id_word(p["can_id"], p["ide"]), flags) + data + bytes(64 - len(data))


# DESN-SW-006
@micropython.native
def rx_object(raw):
    ident, flags, timestamp = struct.unpack_from("<III", raw)
    ide, fdf, rtr = bool(flags & 16), bool(flags & 128), bool(flags & 32)
    if fdf and rtr:
        raise ValueError("FD_RTR")
    dlc = flags & 15
    length = DLC_LENGTHS[dlc] if fdf else min(dlc, 8)
    size = 0 if rtr else length
    if len(raw) < 12 + size:
        raise ValueError("RX_SHORT")
    return {"can_id": unpack_id(ident, ide), "ide": ide, "fdf": fdf,
            "brs": bool(flags & 64), "esi": bool(flags & 256), "rtr": rtr,
            "dlc": dlc, "length": size, "requested_length": length if rtr else 0,
            "data": binascii.hexlify(raw[12:12 + size]).decode().upper(),
            "timestamp_raw": timestamp}


# DESN-SW-011
def _crc_table():
    table = []
    for b in range(256):
        c = b << 8
        for _ in range(8):
            c = ((c << 1) ^ (0x8005 if c & 0x8000 else 0)) & 0xFFFF
        table.append(c)
    return tuple(table)


CRC_TABLE = _crc_table()


# DESN-SW-011
@micropython.native
def crc16(data, crc=0xFFFF):
    """DESN-SW-011: SPI用、非反転0x8005、初期値FFFF、xorout=0。"""
    for b in data:
        crc = ((crc << 8) ^ CRC_TABLE[(crc >> 8) ^ b]) & 0xFFFF
    return crc


# RP2040ではCRCを毎フレーム複数回計算する。Viperの整数ループで
# Pythonオブジェクト演算を避ける。ホスト試験は同じ既知ベクトルで照合する。
try:
    import micropython
    from array import array
    _CRC_WORDS = array("H", CRC_TABLE)

    # DESN-SW-011
    @micropython.viper
    def _crc_fast(data, initial: int) -> int:
        b = ptr8(data)
        table = ptr16(_CRC_WORDS)
        count = int(len(data))
        c = initial
        for i in range(count):
            c = ((c << 8) ^ table[(c >> 8) ^ b[i]]) & 0xFFFF
        return c

    # DESN-SW-011
    def crc16(data, crc=0xFFFF):
        return _crc_fast(data, crc)

    # DESN-SW-003
    @micropython.viper
    def _json_tokens(raw, output) -> int:
        data = ptr8(raw)
        tokens = ptr16(output)
        count = int(len(raw))
        i = 0
        used = 0
        depth = 0
        while i < count:
            c = int(data[i])
            if c < 32 or c > 126 or used >= 254:
                return -1
            if c == 34:
                start = i
                i += 1
                while i < count:
                    c = int(data[i])
                    if c < 32 or c > 126:
                        return -1
                    if c == 34:
                        break
                    if c == 92:
                        i += 1
                        if i >= count or int(data[i]) < 32 or int(data[i]) > 126:
                            return -1
                    i += 1
                if i >= count:
                    return -1
                tokens[used] = 0x4000 | start
                tokens[used + 1] = i
                used += 2
            elif c == 123 or c == 91:
                depth += 1
                if depth > 4:
                    return -1
                tokens[used] = 0x1000 if c == 123 else 0x2000
                used += 1
            elif c == 125 or c == 93:
                depth -= 1
                if depth < 0:
                    return -1
                tokens[used] = 0x3000
                used += 1
            i += 1
        return used if depth == 0 else -1

    # DESN-SW-002
    @micropython.native
    def _strict_fast(raw):
        if not raw or len(raw) > 1023:
            raise ValueError("JSON_ENCODING_LENGTH")
        tokens = array("H", bytes(512))
        count = _json_tokens(raw, tokens)
        if count < 0:
            raise ValueError("JSON_STRUCTURE")
        s = bytes(raw).decode("ascii")
        stack = []
        i = 0
        while i < count:
            token = tokens[i]
            if token == 0x1000:
                stack.append(set())
            elif token == 0x2000:
                stack.append(None)
            elif token == 0x3000:
                stack.pop()
            else:
                start = token & 0xFFF
                i += 1
                end = tokens[i]
                value = s[start + 1:end]
                if "\\" in value:
                    value = json.loads(s[start:end + 1])
                    for c in value:
                        if ord(c) < 32 or ord(c) > 126:
                            raise ValueError("JSON_STRING")
                if len(value) > 128:
                    raise ValueError("JSON_STRING")
                j = end + 1
                while j < len(s) and s[j] == " ":
                    j += 1
                if j < len(s) and s[j] == ":":
                    if not stack or stack[-1] is None or value in stack[-1]:
                        raise ValueError("JSON_DUPLICATE_KEY")
                    stack[-1].add(value)
            i += 1
        obj = json.loads(s)
        if not isinstance(obj, dict):
            raise ValueError("JSON_OBJECT")
        return obj

    strict_json = _strict_fast
except ImportError:
    pass
