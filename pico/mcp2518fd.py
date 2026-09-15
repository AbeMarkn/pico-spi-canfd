"""DESN-HW-003/005、DESN-SW-004/006/010/011: MCP2518FD専用ドライバ。

レジスタ: Microchip DS20006027B。CRC付き読出し、有限待機、TEF完了判定。
IRQ内から呼ばない。FIFOのFIFOCIは占有数・送信成功の判定に使用しない。
"""

import struct
import time

try:
    from common import crc16, rx_object, tx_object, ExtendedCounter, micropython
except ImportError:
    from pico.common import crc16, rx_object, tx_object, ExtendedCounter, micropython

CON = 0x000
TBC = 0x010
INT = 0x01C
TEFCON = 0x040
TEFSTA = 0x044
TEFUA = 0x048
FLTCON = 0x1D0
OSC = 0xE00
IOCON = 0xE04
CRC = 0xE08
ECCCON = 0xE0C
ECCSTAT = 0xE10
DEVID = 0xE14


# DESN-SW-011
def fifo(n):
    if not 1 <= n <= 31:
        raise ValueError("FIFO_NUMBER")
    return 0x050 + 12 * n


# DESN-SW-011
class CANError(Exception):
    pass


# DESN-SW-011
class MCP2518FD:
    # DESN-SW-011
    def __init__(self, spi, cs, config, clock=None, sleep=None):
        self.spi, self.cs, self.config = spi, cs, config
        self.clock = clock or time.ticks_ms
        self.sleep = sleep or time.sleep_ms
        self.pending = {}
        self.seq = 0
        self.counter = ExtendedCounter()
        self.crc_retries = 0
        self.tbc_retries = 0
        self.templates = {}
        self.reg_header = bytearray(3)
        self.reg_data = bytearray(6)
        self.reg_payload = memoryview(self.reg_data)[:4]
        self.addresses = {}
        self.cs(1)

    # DESN-SW-011
    def _elapsed(self, start):
        return (self.clock() - start) & 0x3FFFFFFF

    # DESN-SW-011
    def reset(self):
        self.cs(0)
        try:
            self.spi.write(b"\x00\x00")
        finally:
            self.cs(1)
        self.sleep(3)
        if (self.reg(CON) >> 21) & 7 != 4:
            raise CANError("RESET_NOT_CONFIRMED")
        self.pending.clear()
        self.templates.clear()
        self.counter = ExtendedCounter()

    # DESN-SW-011
    @micropython.native
    def read(self, addr, size=4):
        """CRC不一致だけ最大3回。SFRはレジスタ境界を越えない。"""
        ram = 0x400 <= addr < 0xC00
        if ram:
            if addr % 4 or size % 4 or addr + size > 0xC00:
                raise ValueError("RAM_RANGE")
        elif not 1 <= size <= 4 or addr // 4 != (addr + size - 1) // 4:
            raise ValueError("SFR_BOUNDARY")
        count = size // 4 if ram else size
        if not 1 <= count <= 255:
            raise ValueError("SPI_COUNT")
        header = bytes((0xB0 | (addr >> 8), addr & 255, count))
        for attempt in range(3):
            self.cs(0)
            try:
                self.spi.write(header)
                raw = self.spi.read(size + 2)
            finally:
                self.cs(1)
            if crc16(raw[:-2], crc16(header)) == (raw[-2] << 8 | raw[-1]):
                return raw[:-2]
            self.crc_retries += 1
        raise CANError("SPI_READ_CRC")

    # DESN-SW-011
    @micropython.native
    def reg(self, addr):
        if addr % 4 or 0x400 <= addr < 0xC00:
            raise ValueError("REGISTER_ADDRESS")
        header, data = self.reg_header, self.reg_data
        header[0], header[1], header[2] = 0xB0 | (addr >> 8), addr & 255, 4
        for _ in range(3):
            self.cs(0)
            try:
                self.spi.write(header)
                self.spi.readinto(data)
            finally:
                self.cs(1)
            if crc16(self.reg_payload, crc16(header)) == (data[4] << 8 | data[5]):
                return data[0] | (data[1] << 8) | (data[2] << 16) | (data[3] << 24)
            self.crc_retries += 1
        raise CANError("SPI_READ_CRC")

    # DESN-SW-011
    @micropython.native
    def byte(self, addr, value):
        """SFR WRITE_SAFEは1 byte。IOCONのbyte書込みエラッタにも対応。"""
        raw = bytes((0xC0 | (addr >> 8), addr & 255, value))
        crc = crc16(raw)
        self.cs(0)
        try:
            self.spi.write(raw + bytes((crc >> 8, crc & 255)))
        finally:
            self.cs(1)

    # DESN-SW-011
    def write_reg(self, addr, value, verify=False):
        for i in range(4):
            self.byte(addr + i, (value >> (8 * i)) & 255)
        if verify and self.reg(addr) != value:
            raise CANError("SFR_VERIFY_%03X" % addr)

    # DESN-SW-011
    @micropython.native
    def write_ram(self, addr, data, verify=False):
        if addr % 4 or len(data) % 4 or not 0x400 <= addr < addr + len(data) <= 0xC00:
            raise ValueError("RAM_RANGE")
        header = bytes((0xA0 | (addr >> 8), addr & 255, len(data) // 4))
        crc = crc16(data, crc16(header))
        self.cs(0)
        try:
            self.spi.write(header)
            self.spi.write(data)
            self.spi.write(bytes((crc >> 8, crc & 255)))
        finally:
            self.cs(1)
        if verify and self.read(addr, len(data)) != data:
            raise CANError("RAM_VERIFY")

    # DESN-SW-011
    def mode(self, value, timeout_ms=100):
        self.byte(CON + 3, value)
        start = self.clock()
        while (self.reg(CON) >> 21) & 7 != value:
            if self._elapsed(start) >= timeout_ms:
                raise CANError("MODE_TIMEOUT")
            self.sleep(1)

    # DESN-HW-003/005
    def initialize(self):
        cfg = self.config
        if (cfg["oscillator_hz"] not in (20000000, 40000000)
                or cfg["nominal_bitrate"] != 500000 or cfg["data_bitrate"] != 2000000):
            raise ValueError("CAN_TIMING_CONFIG")
        self.reset()
        if ((self.reg(CON) >> 21) & 7) != 4 or self.reg(DEVID) & ~255:
            raise CANError("DEVICE_NOT_FOUND")
        self.byte(OSC, 0x60)  # PLLなし、SYSCLK分周なし、CLKO=SYSCLK/10。
        start = self.clock()
        while not self.reg(OSC) & 0x400:
            if self._elapsed(start) >= 100:
                raise CANError("OSC_TIMEOUT")
        # INT0/1は入力のまま。未知のSTBY配線を能動駆動しない。
        self.byte(IOCON, 3)
        self.byte(IOCON + 3, 0x43)  # INTはOD、PM0/PM1はGPIO。
        self.write_reg(ECCCON, 7, True)
        for addr in range(0x400, 0xC00, 64):
            self.write_ram(addr, bytes(64), True)
        self.write_reg(ECCSTAT, 0)
        self.write_reg(CRC, 0x03000000)
        scale = cfg["oscillator_hz"] // 20000000
        self.write_reg(0x004, ((2 * scale - 1) << 24) | (14 << 16) | (3 << 8) | 3, True)
        self.write_reg(0x008, ((scale - 1) << 24) | (6 << 16) | (1 << 8) | 1, True)
        self.write_reg(0x00C, (2 << 16) | (8 * scale << 8), True)
        self.write_reg(0x014, (3 << 16) | (cfg["oscillator_hz"] // 1000000 - 1), True)
        self.write_reg(CON, (4 << 24) | (1 << 19) | (1 << 18) | (1 << 16) | 0x20)
        # TEF 48 + RX 1672 + TX 288 = 2008 bytes。未使用FIFOはリセット値。
        self.write_reg(TEFCON, (3 << 24) | 0x29)
        self.write_reg(fifo(1), (7 << 29) | (21 << 24) | 0x29)
        for n in range(2, 6):
            self.write_reg(fifo(n), (7 << 29) | (1 << 21) | ((6 - n) << 16) | 0x90)
        self.write_reg(0x1F0, 0, True)
        self.write_reg(0x1F4, 0, True)  # MIDE=0: 標準・拡張の両方。
        self.write_reg(FLTCON, 1, True)  # 配送先のみ設定、受信無効。
        self.write_reg(INT, 0xBF120000)  # IVM/ECC/SPI/TXAT/RXOV/SERR/CERR/TEF/RX。
        self.spi.init(baudrate=cfg["spi_hz"], polarity=0, phase=0, bits=8)
        return self.read_status()

    # DESN-SW-011
    def start(self, listen_only=False, loopback=False):
        if listen_only and loopback:
            raise ValueError("MODE_CONFLICT")
        self.mode(2 if loopback else 3 if listen_only else 0)
        for addr in [TEFCON] + [fifo(n) for n in range(1, 6)]:
            if self.reg(addr) & 0x400:
                raise CANError("FIFO_RESET_BUSY")
        # 深さ1のTX位置はセッション中固定。RX/TEFはUINCと同じ歩幅で追跡し、
        # 実UAとの一致を読むたび確認する。FIFOCIには依存しない。
        self.addresses = {TEFUA: 0x400, fifo(1) + 8: 0x430}
        for slot in range(2, 6):
            self.addresses[fifo(slot) + 8] = 0xAB8 + (slot - 2) * 72
        for addr, expected in self.addresses.items():
            if self.reg(addr) + 0x400 != expected:
                raise CANError("FIFO_LAYOUT")
        start = self.now_us()
        self.byte(FLTCON, 0x81)
        return start

    # DESN-SW-011
    def now_us(self):
        # DS20005678E §9: TBCはSPI読取り中にも更新される。
        # 連続する2読取りの上位24bitが一致した区間の後側だけを採用。
        # 下位byteの桁上がりをまたぐ値（CRC正常でもあり得る）は再読取り。
        previous = self.reg(TBC)
        for _ in range(16):
            raw = self.reg(TBC)
            if previous >> 8 == raw >> 8 and raw >= previous:
                try:
                    return self.counter.update(raw)
                except ValueError:
                    pass  # 逆戻り時はカウンタ状態を更新せず有限回再読取り。
            self.tbc_retries += 1
            previous = raw
        raise CANError("TBC_UNSTABLE")

    # DESN-SW-011
    def disable_rx(self):
        self.byte(FLTCON, 1)

    # DESN-SW-011
    @micropython.native
    def _ua(self, addr, size):
        a = self.reg(addr)
        if a % 4 or not 0 <= a <= 2048 - size or a + 0x400 != self.addresses[addr]:
            raise CANError("FIFO_ADDRESS")
        return 0x400 + a

    # DESN-SW-006
    @micropython.native
    def receive(self):
        sta = self.reg(fifo(1) + 4)
        if sta & 8:
            raise CANError("RX_OVERFLOW")
        if not sta & 1:
            return None
        raw = self.read(self._ua(fifo(1) + 8, 76), 76)
        if self.reg(ECCSTAT) & 6:
            raise CANError("ECC_UNTRUSTED_RX")
        result = rx_object(raw)
        self.now_us()
        result["device_us"] = self.counter.past(result.pop("timestamp_raw"))
        self.byte(fifo(1) + 1, 1)
        a = self.addresses[fifo(1) + 8] + 76
        self.addresses[fifo(1) + 8] = 0x430 if a == 0xAB8 else a
        return result

    # DESN-SW-004
    @micropython.native
    def submit(self, slot, profile, metadata):
        if slot not in range(2, 6) or slot in self.pending:
            raise CANError("TX_SLOT_BUSY")
        if not self.reg(fifo(slot) + 4) & 1:
            raise CANError("TX_FIFO_BUSY")
        self.seq = (self.seq + 1) & 0x7FFFFF
        pid = profile["profile_id"]
        template = self.templates.get(pid)
        if template is None or template[0] != profile:
            prepared = tx_object(profile, 0)
            size = 8 + ((len(profile["data"]) // 2 + 3) // 4) * 4
            template = (dict(profile), bytearray(prepared[:size]), struct.unpack_from("<I", prepared, 4)[0])
            self.templates[pid] = template
        raw = template[1]
        struct.pack_into("<I", raw, 4, template[2] | (self.seq << 9))
        # DLC以降の未使用payloadは送信されない。Classicalで64byte全域を
        # 毎回往復させず、ヘッダと必要な4byte境界までだけを書き検証する。
        self.write_ram(self.addresses[fifo(slot) + 8], raw, True)
        record = dict(metadata)
        record["profile_id"] = pid
        record.update(seq=self.seq, slot=slot, txreq_us=self.now_us(), abort=False)
        self.pending[slot] = record
        self.byte(fifo(slot) + 1, 3)  # UINC + TXREQ、送信成功ではない。
        return self.seq

    # DESN-SW-004
    @micropython.native
    def completions(self):
        result = []
        for _ in range(4):
            sta = self.reg(TEFSTA)
            if sta & 8:
                raise CANError("TEF_OVERFLOW")
            if not sta & 1:
                break
            raw = self.read(self._ua(TEFUA, 12), 12)
            if self.reg(ECCSTAT) & 6:
                raise CANError("ECC_UNTRUSTED_TEF")
            _, flags, timestamp = struct.unpack("<III", raw)
            seq = flags >> 9
            matches = []
            for s in self.pending:
                if self.pending[s]["seq"] == seq:
                    matches.append(s)
            if len(matches) != 1:
                raise CANError("TEF_SEQUENCE")
            record = self.pending.pop(matches[0])
            self.now_us()
            record.update(type="TX_DONE", device_us=self.counter.past(timestamp))
            result.append(record)
            self.byte(TEFCON + 1, 1)
            a = self.addresses[TEFUA] + 12
            self.addresses[TEFUA] = 0x400 if a == 0x430 else a
        # TEFに入らない中止・試行上限を区別。正常完了をFIFO空だけで推定しない。
        for slot in list(self.pending):
            sta = self.reg(fifo(slot) + 4) & 255
            if sta & 0x90 and not self.reg(fifo(slot)) & 0x200:
                if sta != self.reg(fifo(slot) + 4) & 255:
                    continue
                record = self.pending.pop(slot)
                record.update(type="TX_ABORTED" if sta & 128 else "TX_FAILED",
                              device_us=None, fifo_status=sta)
                result.append(record)
                self.byte(fifo(slot) + 1, 4)  # 失敗メッセージをFIFOから破棄。
        return result

    # DESN-SW-010
    def abort(self, slot):
        if slot in self.pending:
            self.pending[slot]["abort"] = True
            self.byte(fifo(slot) + 1, 0)

    # DESN-SW-011
    def read_status(self):
        trec = self.reg(0x034)
        mode = (self.reg(CON) >> 21) & 7
        return {"mode": mode, "tec": (trec >> 8) & 255,
                "rec": trec & 255, "bus_off": mode != 4 and bool(trec & (1 << 21)),
                "trec": trec, "bdiag0": self.reg(0x038), "bdiag1": self.reg(0x03C),
                "int": self.reg(INT), "ecc": self.reg(ECCSTAT), "crc": self.reg(CRC),
                "rx_overflow": self.reg(0x028), "tdc": self.reg(0x00C),
                "devid": self.reg(DEVID), "osc": self.reg(OSC),
                "crc_retries": self.crc_retries, "tbc_retries": self.tbc_retries}

    # DESN-SW-011
    def interrupt_status(self):
        return self.reg(INT)


# MicroPythonのレジスタ頻回読出しではCRCの7byteループまで一つの
# Viper関数へまとめる。Python版はホストのSPI異常注入試験に使う。
try:
    import micropython
    from common import _CRC_WORDS

    # DESN-SW-011
    @micropython.viper
    def _reg_fast(self, address: int) -> uint:
        header = self.reg_header
        data = self.reg_data
        hp = ptr8(header)
        dp = ptr8(data)
        table = ptr16(_CRC_WORDS)
        hp[0] = 0xB0 | (address >> 8)
        hp[1] = address & 255
        hp[2] = 4
        for attempt in range(3):
            self.cs(0)
            try:
                self.spi.write(header)
                self.spi.readinto(data)
            finally:
                self.cs(1)
            crc = 0xFFFF
            for i in range(3):
                crc = ((crc << 8) ^ table[(crc >> 8) ^ hp[i]]) & 0xFFFF
            for i in range(4):
                crc = ((crc << 8) ^ table[(crc >> 8) ^ dp[i]]) & 0xFFFF
            if crc == ((dp[4] << 8) | dp[5]):
                return uint(dp[0] | (dp[1] << 8) | (dp[2] << 16) | (dp[3] << 24))
            self.crc_retries = int(self.crc_retries) + 1
        raise CANError("SPI_READ_CRC")

    MCP2518FD.reg = _reg_fast
except ImportError:
    pass
