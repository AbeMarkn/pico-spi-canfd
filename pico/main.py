"""DESN-SW-001〜012: ベアメタル上の単一協調ループ。IRQはフラグだけ。"""

import time
import gc

try:
    from common import micropython
except ImportError:
    from pico.common import micropython

try:
    from common import VERSION, Lines, Ring, encode, strict_json, integer, name, validate_profile
except ImportError:
    from pico.common import VERSION, Lines, Ring, encode, strict_json, integer, name, validate_profile

COMMAND_FIELDS = {
    "HELLO": (), "STATUS": (), "HEARTBEAT": ("hb",),
    "LOAD_BEGIN": ("revision", "count"),
    "LOAD_PROFILE": ("revision", "profile"),
    "LOAD_COMMIT": ("revision", "count"),
    "START_SESSION": ("revision", "duration_ms", "device_config_id"),
    "START_PROFILE": ("profile_id", "generation"),
    "STOP_ID": ("ide", "can_id"), "STOP_SESSION": ("reason",),
}


# DESN-SW-001
def id_key(profile):
    return (profile["ide"], profile["can_id"])


# DESN-SW-001
def schedule_key(job):
    return job["due"], job["profile"]["period_ms"]


# DESN-SW-001
class Engine:
    """時刻とドライバを注入できるため、実機なしで競合・期限を検証できる。"""

    # DESN-SW-001
    def __init__(self, can, config, boot_id, clock):
        self.can, self.config, self.boot_id, self.clock = can, config, boot_id, clock
        self.state = "IDLE"
        self.session_id = None
        self.session_number = 0
        self.event_seq = 0
        self.controls, self.frames = Ring(16), Ring(64)
        self.current = None
        self.offset = 0
        self.latest_error = None
        self.emergency = False
        self.dropped = 0
        self.profiles = {}
        self.revision = None
        self.staging = None
        self.jobs = {}
        self.generations = {}
        self.cache = []
        self.high_req = -1
        self.hb = -1
        self.last_hb = 0
        self.last_status = 0
        self.last_diag = None
        self.stats = {"rx": 0, "tx_done": 0, "tx_failed": 0, "skipped": 0}
        self.final_event = None
        self.stop_req = None

    # DESN-SW-001
    @micropython.native
    def event(self, kind, **fields):
        self.event_seq += 1
        e = {"type": kind, "boot_id": self.boot_id, "session_id": self.session_id,
             "event_seq": self.event_seq}
        e.update(fields)
        return e

    # DESN-SW-001
    @micropython.native
    def emit(self, e):
        q = self.frames if e["type"] == "RX" else self.controls
        if not q.put(e):
            self.dropped += 1
            self.emergency = True
            self.latest_error = "USB_QUEUE_OVERFLOW"

    # DESN-SW-001
    def error(self, code, **fields):
        self.latest_error = code
        self.emit(self.event("ERROR", code=code, **fields))

    # DESN-SW-003
    @micropython.native
    def flush(self, usb):
        """部分書込みを保持し、行の途中に他イベントを挿入しない。"""
        if not usb.ioctl(3, 4) & 4:
            return 0
        if self.current is None:
            event = self.controls.get() or self.frames.get()
            self.current = encode(event) if event is not None else None
            self.offset = 0
        if self.current is not None:
            written = usb.write(memoryview(self.current)[self.offset:]) or 0
            if not 0 <= written <= len(self.current) - self.offset:
                raise OSError("USB_WRITE_COUNT")
            self.offset += written
            if self.offset == len(self.current):
                self.current = None
            return written
        return 0

    # DESN-SW-003
    def command(self, raw):
        """DESN-SW-003: 有限再送、同一reqの再実行防止、世代による停止優先。"""
        req = None
        obj = None
        accepted = False
        try:
            obj = strict_json(raw)
            cmd = obj.get("cmd")
            if cmd not in COMMAND_FIELDS:
                raise ValueError("UNKNOWN_COMMAND")
            integer(obj.get("v"), 1, 1)
            req = integer(obj.get("req"), 0, 0x7FFFFFFF)
            allowed = {"v", "cmd", "req"} | set(COMMAND_FIELDS[cmd])
            if cmd != "HELLO":
                allowed.add("boot_id")
                if obj.get("boot_id") != self.boot_id:
                    raise ValueError("STALE_BOOT")
            if "session_id" in obj:
                allowed.add("session_id")
                if obj["session_id"] != self.session_id:
                    raise ValueError("STALE_SESSION")
            if set(obj) != allowed:
                raise ValueError("COMMAND_FIELDS")
            if cmd in ("START_PROFILE", "STOP_ID", "HEARTBEAT", "STOP_SESSION"):
                if obj.get("session_id") != self.session_id or self.session_id is None:
                    raise ValueError("SESSION_REQUIRED")
            if cmd == "HEARTBEAT":
                hb = integer(obj["hb"], 0, 0x7FFFFFFF)
                if hb > self.hb:
                    self.hb, self.last_hb = hb, self.clock()
                return  # ACK不要。制御再送窓と分離する。
            if cmd == "HELLO":
                response = self.execute(cmd, obj)
                response.update(req=req, next_req=self.high_req + 1)
                self.emit(response)
                return
            for old_req, old_obj, response in self.cache:
                if old_req == req:
                    if old_obj != obj:
                        raise ValueError("REQ_REUSED")
                    self.emit(response)
                    return
            if req <= self.high_req:
                raise ValueError("STALE_REQ")
            self.high_req = req
            accepted = True
            response = self.execute(cmd, obj)
            response["req"] = req
            self.cache.append((req, obj, response))
            if len(self.cache) > 16:
                self.cache.pop(0)
            self.emit(response)
        except (ValueError, KeyError, TypeError) as exc:
            response = self.event("NACK", req=req, code=str(exc)[:80])
            if accepted:
                self.cache.append((req, obj, response))
                if len(self.cache) > 16:
                    self.cache.pop(0)
            self.emit(response)
        except Exception as exc:
            self.fault("DRIVER_COMMAND", str(exc)[:80])
            self.emit(self.event("NACK", req=req, code="DRIVER_COMMAND"))

    # DESN-SW-010
    def fault(self, code, detail):
        """初期化途中・通常運転のどちらで失敗しても、外付けCANの停止を試みる。"""
        pending = list(self.can.pending.values())
        confirmed = False
        try:
            self.can.reset()
            confirmed = True
        except Exception:
            pass
        self.jobs.clear()
        for record in pending:
            self.emit(self.event("TX_UNKNOWN", **record))
        self.error(code, detail=detail, stop_confirmed=confirmed)
        if self.session_id:
            self.stop_clock = self.clock()
            self.final_event = dict(reason=code, stats=dict(self.stats), dropped=self.dropped,
                                    stop_confirmed=confirmed, drain_complete=False,
                                    tx_unknown=len(pending), req=None)
            self.state = "DRAINING"
        else:
            self.state = "FAULT"

    # DESN-SW-003/004/009
    def execute(self, cmd, obj):
        if cmd == "HELLO":
            return self.event("INFO", firmware=VERSION, schema=1, protocol=1,
                              device_config_id=self.config["device_config_id"],
                              oscillator_hz=self.config["oscillator_hz"],
                              electrical_verified=self.config["electrical_verified"],
                              nominal_bitrate=500000, data_bitrate=2000000,
                              max_profiles=32, max_active=4, max_line=1024, state=self.state)
        if cmd == "STATUS":
            active = [{"profile_id": j["profile"]["profile_id"],
                       "generation": j["generation"], "slot": j["slot"],
                       "stopping": j["stopping"]} for j in self.jobs.values()]
            return self.event("STATUS", state=self.state, active=active,
                              revision=self.revision, dropped=self.dropped, stats=dict(self.stats),
                              latest_error=self.latest_error, hardware=self.can.read_status())
        if cmd.startswith("LOAD_"):
            if self.state not in ("IDLE", "PREPARED", "ENDED", "FAULT"):
                raise ValueError("LOAD_WHILE_RUNNING")
            revision = name(obj["revision"])
            if cmd == "LOAD_BEGIN":
                count = integer(obj["count"], 1, 32)
                self.staging = {"revision": revision, "count": count, "profiles": {}}
            else:
                if self.staging is None or revision != self.staging["revision"]:
                    raise ValueError("STAGING_REVISION")
                profiles = self.staging["profiles"]
                if cmd == "LOAD_PROFILE":
                    p = validate_profile(obj["profile"])
                    if p["profile_id"] in profiles or len(profiles) >= self.staging["count"]:
                        raise ValueError("PROFILE_DUPLICATE_CAPACITY")
                    profiles[p["profile_id"]] = p
                else:
                    integer(obj["count"], 1, 32)
                    if len(profiles) != obj["count"] or len(profiles) != self.staging["count"]:
                        raise ValueError("PROFILE_COUNT")
                    self.profiles, self.revision = profiles, revision
                    self.generations = {id_key(p): 0 for p in profiles.values()}
                    self.staging = None
                    self.state = "PREPARED"
            return self.event("ACK", command=cmd)
        if cmd == "START_SESSION":
            if self.state not in ("PREPARED", "ENDED") or not self.profiles:
                raise ValueError("NOT_PREPARED")
            if obj["revision"] != self.revision or obj["device_config_id"] != self.config["device_config_id"]:
                raise ValueError("CONFIG_MISMATCH")
            duration = integer(obj["duration_ms"], 1000, 86400000)
            self.can.initialize()
            self.session_number += 1
            self.session_id = str(self.session_number)  # 一意性はboot_idとの組で保持。
            self.start_us = self.can.start()
            self.deadline_us = self.start_us + duration * 1000
            self.last_hb = self.clock()
            self.hb = -1
            self.jobs.clear()
            self.generations = {id_key(p): 0 for p in self.profiles.values()}
            self.stats = {"rx": 0, "tx_done": 0, "tx_failed": 0, "skipped": 0}
            self.dropped = 0
            self.latest_error = self.last_diag = self.final_event = None
            self.stop_req = None
            self.state = "RUNNING"
            return self.event("ACK", command=cmd, start_time_us=self.start_us,
                              deadline_us=self.deadline_us, initial_generation=0)
        if cmd == "STOP_SESSION":
            name(obj["reason"])
            if self.state == "ENDED" and self.final_event:
                return dict(self.final_event)
            self.stop_req = obj["req"]
            self.stop(obj["reason"])
            return self.event("ACK", command=cmd, result="STOPPING")
        if self.state != "RUNNING" or self.can.now_us() >= self.deadline_us:
            raise ValueError("SESSION_NOT_RUNNING")
        if cmd == "STOP_ID":
            if type(obj["ide"]) is not bool:
                raise ValueError("BOOL_REQUIRED")
            integer(obj["can_id"], 0, 0x1FFFFFFF if obj["ide"] else 0x7FF)
            key = id_key(obj)
            if key not in self.generations:
                raise ValueError("UNKNOWN_ID")
            self.generations[key] += 1
            if key in self.jobs:
                job = self.jobs[key]
                job["stopping"], job["replacement"] = True, None
                job["stop_clock"] = self.clock()
                self.can.abort(job["slot"])
            return self.event("ACK", command=cmd, generation=self.generations[key],
                              result="STOPPING" if key in self.jobs else "STOPPED")
        if cmd == "START_PROFILE":
            p = self.profiles[obj["profile_id"]]
            key = id_key(p)
            generation = integer(obj["generation"], 0, 0x7FFFFFFF)
            if generation != self.generations[key]:
                raise ValueError("STALE_GENERATION")
            if key in self.jobs:
                job = self.jobs[key]
                same = all(job["profile"][f] == p[f] for f in ("data", "period_ms", "fdf", "brs"))
                if same and not job["stopping"]:
                    return self.event("ACK", command=cmd, result="ALREADY_ACTIVE", generation=generation,
                                      profile_id=job["profile"]["profile_id"])
                if job["stopping"]:
                    raise ValueError("ID_STOPPING")
                job["stopping"], job["replacement"] = True, p
                self.generations[key] += 1
                generation = self.generations[key]
                job["replacement_generation"] = generation
                job["replacement_req"] = obj["req"]
                job["stop_clock"] = self.clock()
                self.can.abort(job["slot"])
                result = "REPLACING"
            else:
                if len(self.jobs) >= 4:
                    raise ValueError("ACTIVE_CAPACITY")
                used = [j["slot"] for j in self.jobs.values()]
                slot = next(n for n in range(2, 6) if n not in used)
                self.jobs[key] = self.new_job(p, slot, generation, obj["req"])
                result = "STARTED"
            return self.event("ACK", command=cmd, result=result, generation=generation,
                              profile_id=p["profile_id"])
        raise ValueError("UNKNOWN_COMMAND")

    # DESN-SW-001
    def new_job(self, p, slot, generation, req):
        return {"profile": p, "slot": slot, "generation": generation, "req": req,
                "due": self.clock(), "stopping": False, "replacement": None}

    # DESN-SW-009
    def stop(self, reason):
        if self.state == "STOPPING":
            return
        if self.state != "RUNNING":
            return
        self.state = "STOPPING"
        self.stop_reason = reason
        self.stop_clock = self.clock()
        self.stop_deadline = min(self.deadline_us, self.can.now_us())
        self.can.disable_rx()
        for key, job in self.jobs.items():
            self.generations[key] += 1
            job["stopping"], job["replacement"] = True, None
            job["stop_clock"] = self.clock()
            self.can.abort(job["slot"])

    # DESN-SW-004/006/009
    @micropython.native
    def service(self):
        now = self.clock()
        if self.state == "RUNNING":
            if self.emergency:
                self.stop("USB_QUEUE_OVERFLOW")
            elif self.can.now_us() >= self.deadline_us:
                self.stop("DURATION")
            elif now - self.last_hb >= self.config["heartbeat_timeout_ms"] * 1000:
                self.staging = None
                self.stop("HEARTBEAT_LOST")
        if self.state not in ("RUNNING", "STOPPING"):
            return
        irq = self.can.interrupt_status()
        need_tx = bool(irq & 0x410)
        for job in self.jobs.values():
            if job["stopping"]:
                need_tx = True
        completed = self.can.completions() if need_tx else ()
        for record in completed:
            kind = record.pop("type")
            self.stats["tx_done" if kind == "TX_DONE" else "tx_failed"] += 1
            # 送信payloadはセッション中不変のprofileでホストが復元する。
            # SEQに紐づく機器内の元レコードは、ここまで変更しない。
            for field in ("slot", "abort", "due_mono_us", "submit_mono_us"):
                record.pop(field, None)
            self.emit(self.event(kind, **record))
            if kind == "TX_FAILED":
                self.error("TX_ATTEMPTS_EXHAUSTED")
                self.stop("TX_FAILED")
        rx_empty = False
        for _ in range(8 if irq & 2 or self.state == "STOPPING" else 0):
            frame = self.can.receive()
            if frame is None:
                rx_empty = True
                break
            end = self.deadline_us if self.state == "RUNNING" else self.stop_deadline
            if self.start_us <= frame["device_us"] < end:
                self.stats["rx"] += 1
                self.emit(self.event("RX", **frame))
            if self.clock() - now >= 1000:
                break
        for key in list(self.jobs):
            job = self.jobs[key]
            pending = self.can.pending.get(job["slot"])
            if (pending and not job["stopping"]
                    and now - pending["submit_mono_us"] >= 100000):
                self.error("TX_COMPLETION_TIMEOUT")
                self.stop("TX_COMPLETION_TIMEOUT")
            if (job["stopping"] and job["slot"] in self.can.pending
                    and now - job["stop_clock"] >= 100000 and self.state == "RUNNING"):
                self.error("ID_STOP_TIMEOUT")
                self.stop("ID_STOP_TIMEOUT")
            if job["stopping"] and job["slot"] not in self.can.pending:
                p = job["replacement"]
                del self.jobs[key]
                if p and self.state == "RUNNING":
                    self.jobs[key] = self.new_job(p, job["slot"], job["replacement_generation"], job["replacement_req"])
                else:
                    self.emit(self.event("ID_STOPPED", ide=key[0], can_id=key[1],
                                         generation=self.generations[key]))
        if self.state == "STOPPING":
            expired = now - self.stop_clock >= 100000
            if expired or (not self.can.pending and rx_empty):
                if self.can.pending:
                    for record in self.can.pending.values():
                        self.emit(self.event("TX_UNKNOWN", **record))
                    self.can.pending.clear()
                status = self.can.read_status()
                self.can.mode(4)
                self.jobs.clear()
                self.state = "DRAINING"
                self.final_event = dict(reason=self.stop_reason, stats=dict(self.stats),
                                        dropped=self.dropped, stop_confirmed=True,
                                        drain_complete=rx_empty, hardware=status, req=self.stop_req)
            return
        if now - self.last_status >= 100000 or irq & 0xFB00:
            self.last_status = now
            status = self.can.read_status()
            fatal = (status["bus_off"] or status["rx_overflow"] or status["ecc"] & 6
                     or status["crc"] & 0x30000 or status["int"] & 0x1000
                     or status["mode"] != 0)
            diag = (status["tec"], status["rec"], status["bdiag0"], status["bdiag1"] >> 16)
            if fatal or (diag != self.last_diag and any(diag)):
                self.error("CAN_FATAL" if fatal else "CAN_DIAGNOSTIC", hardware=status)
            self.last_diag = diag
            if fatal:
                self.stop("CAN_FATAL")
                return
        self.transmit_due()

    # DESN-SW-004
    @micropython.native
    def transmit_due(self):
        now = self.clock()
        ready = [j for j in self.jobs.values() if not j["stopping"] and now >= j["due"]]
        for job in sorted(ready, key=schedule_key):
            now = self.clock()
            if self.can.now_us() >= self.deadline_us:
                self.stop("DURATION")
                return
            period = job["profile"]["period_ms"] * 1000
            skipped = (now - job["due"]) // period
            due = job["due"]
            job["due"] += (skipped + 1) * period
            self.stats["skipped"] += skipped
            if job["slot"] in self.can.pending:
                self.stats["skipped"] += 1
                continue
            self.can.submit(job["slot"], job["profile"],
                            {"generation": job["generation"], "req": job["req"],
                             "due_mono_us": due, "late_us": now - due})
            self.can.pending[job["slot"]]["submit_mono_us"] = now

    # DESN-SW-009
    def drain(self):
        if self.state == "DRAINING":
            if not self.controls.count and not self.frames.count and self.current is None:
                # 最後のイベント番号は既存キュー排出後に確定。
                self.final_event["dropped"] = self.dropped
                self.final_event = self.event("SESSION_END", **self.final_event)
                self.emit(self.final_event)
                self.state = "ENDED"
                self.emergency = False
            elif self.clock() - self.stop_clock > 2100000:
                # USB停止でもCANの再開はしない。ログ未完了を後のSTATUSで識別。
                self.latest_error = "USB_DRAIN_TIMEOUT"


# DESN-SW-001/010
def run():
    """DESN-SW-001/010/012: ハードウェア所有と例外時の有限停止。"""
    from machine import Pin, SPI, WDT, unique_id
    import machine
    import binascii
    import os
    import usb.device
    from config import CONFIG
    from mcp2518fd import MCP2518FD
    from common import ExtendedCounter

    pins = (CONFIG[k] for k in ("sck", "mosi", "miso", "cs", "int", "clk", "int0", "int1"))
    if tuple(pins) != (18, 19, 16, 17, 26, 20, 21, 22):
        raise ValueError("PIN_CONFIG")
    for n in (20, 21, 22):
        Pin(n, Pin.IN)
    interrupt = Pin(26, Pin.IN, Pin.PULL_UP)
    flag = bytearray(1)

    # DESN-SW-001
    def irq(_):
        flag[0] = 1

    interrupt.irq(trigger=Pin.IRQ_FALLING, handler=irq)
    spi = SPI(0, baudrate=CONFIG["spi_init_hz"], polarity=0, phase=0,
              sck=Pin(18), mosi=Pin(19), miso=Pin(16))
    can = MCP2518FD(spi, Pin(17, Pin.OUT, value=1), CONFIG)
    mono = ExtendedCounter(30)

    # DESN-SW-001
    def clock():
        return mono.update(time.ticks_us())

    boot_id = binascii.hexlify(unique_id()[-4:] + os.urandom(4)).decode()
    engine = Engine(can, CONFIG, boot_id, clock)
    try:
        can.initialize()
    except Exception as exc:
        engine.error("INITIALIZE", detail=str(exc)[:80])
    usb = usb.device.can_cdc
    lines = Lines()
    raw_pending = []
    wdt = WDT(timeout=CONFIG["watchdog_ms"])
    last_poll = clock()
    gc.collect()
    gc.enable()
    gc.threshold(gc.mem_free() // 4 + gc.mem_alloc())
    while True:
        try:
            data = usb.read(256) if usb.ioctl(3, 1) & 1 else None
            if data:
                pending = lines.feed(data)
                for raw in pending:
                    if len(raw_pending) == 8:
                        engine.error("INPUT_QUEUE_FULL")
                        engine.stop("INPUT_QUEUE_FULL")
                    else:
                        raw_pending.append(raw)
                raw_pending.sort(key=lambda r: 0 if r and (b'"STOP_' in r) else 1)
            now = clock()
            if flag[0] or not interrupt.value() or now - last_poll >= 1000:
                mask = machine.disable_irq()
                flag[0] = 0
                machine.enable_irq(mask)
                last_poll = now
                engine.service()
            if raw_pending:
                raw = raw_pending.pop(0)
                if raw is None:
                    engine.error("INPUT_TOO_LONG")
                else:
                    engine.command(raw)
            flush_start = clock()
            for _ in range(16):
                if clock() - flush_start >= 3000 or not engine.flush(usb):
                    break
            engine.drain()
            wdt.feed()
            time.sleep_us(50)
        except KeyboardInterrupt:
            try:
                can.reset()
            finally:
                # WDTは停止不能なので、明示REPL割込みだけ1回限りの保守起動へ。
                with open(".maintenance", "w") as f:
                    f.write("1")
                machine.reset()
        except Exception as exc:
            engine.fault("RUNTIME", str(exc)[:80])
            # CAN停止済みで明示再設定を待つ。例外原因をREPLにも残す。
            import sys
            sys.print_exception(exc)


if __name__ == "__main__":
    import os
    try:
        os.stat(".maintenance")
    except OSError:
        run()
    else:
        os.remove(".maintenance")
        print("CAN stopped. Maintenance REPL; reset to run application.")
