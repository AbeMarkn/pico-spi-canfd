"""DESN-SW-002/003/005/007/008/010: Tk GUI、USB worker、独立ログ保存。

起動: python -m host.main。自動試験: python -m host.main --headless --duration 12
"""

import argparse
import ast
import hashlib
from collections import OrderedDict
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import threading
import time

import serial
from serial.tools import list_ports

from pico.common import VERSION, PROFILE_FIELDS, Lines, encode, strict_json, validate_profile, integer, name


# DESN-SW-002
def load_config(path):
    """DESN-SW-002: 任意コードを実行せず、辞書の重複キーも拒否する。"""
    text = Path(path).read_text(encoding="utf-8")
    if len(text) > 65536:
        raise ValueError("設定ファイルが大きすぎます")
    tree = ast.parse(text, filename=str(path))
    body = tree.body
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
        body = body[1:]
    if (len(body) != 1 or not isinstance(body[0], ast.Assign) or len(body[0].targets) != 1
            or not isinstance(body[0].targets[0], ast.Name) or body[0].targets[0].id != "CONFIG"):
        raise ValueError("CONFIGへのリテラル代入だけを指定してください")
    for node in ast.walk(body[0].value):
        if isinstance(node, ast.Dict):
            keys = [ast.literal_eval(k) for k in node.keys]
            if len(set(keys)) != len(keys):
                raise ValueError("設定辞書の重複キー")
    cfg = ast.literal_eval(body[0].value)
    required = {"schema", "revision", "device_config_id", "duration_ms", "log_dir", "profiles"}
    if not isinstance(cfg, dict) or set(cfg) != required:
        raise ValueError("設定フィールドが一致しません")
    integer(cfg["schema"], 1, 1)
    integer(cfg["duration_ms"], 1000, 86400000)
    name(cfg["revision"])
    name(cfg["device_config_id"])
    if not isinstance(cfg["log_dir"], str) or not cfg["log_dir"] or len(cfg["log_dir"]) > 512:
        raise ValueError("ログ保存先")
    if not isinstance(cfg["profiles"], list) or not 1 <= len(cfg["profiles"]) <= 32:
        raise ValueError("設定は1〜32パターンです")
    starts, stops, ids = set(), {}, set()
    for p in cfg["profiles"]:
        validate_profile(p, host=True)
        if p["profile_id"] in ids or p["start_key"] in starts:
            raise ValueError("パターン名または開始キーの重複")
        key = (p["ide"], p["can_id"])
        if p["stop_key"] in stops and stops[p["stop_key"]] != key:
            raise ValueError("異なるIDに同じ停止キー")
        ids.add(p["profile_id"])
        starts.add(p["start_key"])
        stops[p["stop_key"]] = key
    if starts.intersection(stops):
        raise ValueError("開始・停止キーの衝突")
    return cfg


# DESN-SW-001
def utc():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


# DESN-SW-001
def wire_profile(p):
    return {k: p[k] for k in PROFILE_FIELDS}


# DESN-SW-013
def source_manifest():
    """未コミットの実装も識別できるよう、配置元ソースのSHA-256を保存する。"""
    root = Path(__file__).resolve().parent.parent
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for directory in ("host", "pico") for p in sorted((root / directory).rglob("*.py"))}


# DESN-SW-001
class LogWriter(threading.Thread):
    """DESN-SW-008: 起動準備完了通知、100ms flush、1秒fsync、有限キュー。"""

    # DESN-SW-008
    def __init__(self, directory, metadata):
        super().__init__(name="CAN-log", daemon=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        self.directory = Path(directory) / stamp
        self.metadata = metadata
        self.events = queue.Queue(4096)
        self.ready, self.finish, self.closed = threading.Event(), threading.Event(), threading.Event()
        self.failure = None
        self.count = 0

    # DESN-SW-008
    def put(self, event):
        if self.failure:
            raise OSError(self.failure)
        try:
            self.events.put_nowait(dict(event, host_utc=utc()))
        except queue.Full as exc:
            raise OSError("ログキューが満杯です") from exc

    # DESN-SW-008
    def run(self):
        files = {}
        try:
            self.directory.mkdir(parents=True, exist_ok=False)
            if shutil.disk_usage(self.directory).free < 10 * 1024 * 1024:
                raise OSError("ログ用空き容量が10MiB未満です")
            for kind, description in (("tx", "送信受付・送信結果"), ("rx", "受信フレーム"), ("error", "状態・診断・エラー")):
                f = (self.directory / (kind + ".txt")).open("x", encoding="utf-8", buffering=65536)
                files[kind] = f
                f.write("# " + description + " / JSON Lines / UTC、機器時刻us\n")
                f.write("# " + json.dumps(self.metadata, ensure_ascii=False) + "\n")
                f.flush()
                os.fsync(f.fileno())
            self.ready.set()
            flush_at = sync_at = time.monotonic()
            while not self.finish.is_set() or not self.events.empty():
                try:
                    e = self.events.get(timeout=0.025)
                except queue.Empty:
                    e = None
                if e:
                    kind = e.get("type", "")
                    target = "rx" if kind == "RX" else "tx" if kind.startswith("TX_") or kind == "TX_ACCEPTED" else "error"
                    line = json.dumps(e, ensure_ascii=False, separators=(",", ":")) + "\n"
                    files[target].write(line)
                    if kind == "ACK" and e.get("command") == "START_SESSION":
                        for f in files.values():
                            f.write("# セッション開始 " + line)
                    self.count += 1
                now = time.monotonic()
                if now - flush_at >= 0.1:
                    for f in files.values():
                        f.flush()
                    flush_at = now
                if now - sync_at >= 1:
                    for f in files.values():
                        f.flush()
                        os.fsync(f.fileno())
                    sync_at = now
            for f in files.values():
                f.flush()
                os.fsync(f.fileno())
        except Exception as exc:
            self.failure = str(exc)
            self.ready.set()
        finally:
            for f in files.values():
                try:
                    f.close()
                except OSError as exc:
                    self.failure = str(exc)
            self.closed.set()

    # DESN-SW-008
    def close(self):
        self.finish.set()
        self.join(2)
        if not self.closed.is_set():
            raise OSError("ログの排出が2秒で完了しませんでした")
        if self.failure:
            raise OSError(self.failure)


# DESN-SW-001
class Link:
    """DESN-SW-003: 単一worker所有。ACK待ちでもRXとheartbeatを処理する。"""

    # DESN-SW-003
    def __init__(self, port, event_callback, stop_flag=None):
        self.serial = serial.Serial(port, baudrate=115200, timeout=0, write_timeout=0)
        self.serial.dtr = True
        self.lines = Lines()
        self.callback = event_callback
        self.stop_flag = stop_flag or threading.Event()
        self.boot_id = self.session_id = None
        self.req = 0
        self.hb = 0
        self.last_hb = 0
        self.responses = {}
        self.seen = OrderedDict()
        self.tx = bytearray()
        self.tx_offset = 0
        self.write_started = 0
        self.ended = False
        self.info = None
        self.inflight = None

    # DESN-SW-003
    def queue_write(self, obj):
        data = encode(obj)
        if self.tx:
            raise OSError("USB送信が停滞しています")
        self.tx, self.tx_offset, self.write_started = data, 0, time.monotonic()

    # DESN-SW-003
    def pump(self, heartbeat=True):
        if self.tx:
            try:
                n = self.serial.write(self.tx[self.tx_offset:])
            except serial.SerialTimeoutException:
                n = 0
            self.tx_offset += n
            if self.tx_offset == len(self.tx):
                self.tx = bytearray()
            elif time.monotonic() - self.write_started > 0.5:
                raise OSError("USB書込み期限超過")
        data = self.serial.read(4096)
        for raw in self.lines.feed(data):
            if raw is None:
                raise OSError("機器からのJSON行が上限を超えました")
            try:
                e = strict_json(raw)
            except ValueError:
                if self.boot_id is None:
                    continue  # ポート探索時のREPL等を機器応答と誤認しない。
                raise
            if e.get("type") not in ("INFO", "ACK", "NACK", "STATUS", "RX", "TX_DONE", "TX_FAILED", "TX_ABORTED", "TX_UNKNOWN", "ERROR", "ID_STOPPED", "SESSION_END"):
                continue
            kind, req = e["type"], e.get("req")
            matched = self.inflight is not None and req == self.inflight[1]
            if self.boot_id is None:
                if not (matched and self.inflight[0] == "HELLO" and kind == "INFO"):
                    continue
                self.boot_id = e["boot_id"]
            if self.boot_id and e.get("boot_id") != self.boot_id:
                raise OSError("Picoが再起動しました。再接続が必要です")
            # START ACKと最初のRXが同じUSB読出しに入っても、先に所属を確定。
            if (matched and kind == "ACK" and self.inflight[0] == "START_SESSION"
                    and e.get("command") == "START_SESSION"):
                self.session_id, self.ended = e["session_id"], False
            response = matched and kind in ("INFO", "ACK", "NACK", "STATUS", "SESSION_END")
            if not response and (self.session_id is None or e.get("session_id") != self.session_id):
                continue  # 再接続時の旧セッションの滞留ログを新しい集計へ入れない。
            if response:
                self.responses[req] = e
                if len(self.responses) > 32:
                    self.responses.pop(next(iter(self.responses)))
            token = (e.get("boot_id"), e.get("event_seq"))
            if token not in self.seen:
                self.seen[token] = None
                if len(self.seen) > 256:
                    self.seen.popitem(last=False)
                if e["type"] == "SESSION_END":
                    self.ended = True
                self.callback(e)
        now = time.monotonic()
        if heartbeat and self.session_id and not self.ended and not self.tx and now - self.last_hb >= 0.25:
            self.hb += 1
            self.queue_write({"v": 1, "cmd": "HEARTBEAT", "req": 0,
                              "boot_id": self.boot_id, "session_id": self.session_id, "hb": self.hb})
            self.last_hb = now

    # DESN-SW-003
    def rpc(self, cmd, **fields):
        if cmd != "HELLO":
            self.req += 1
        request = {"v": 1, "cmd": cmd, "req": self.req}
        if self.boot_id and cmd != "HELLO":
            request["boot_id"] = self.boot_id
        if self.session_id and cmd != "HELLO":
            request["session_id"] = self.session_id
        request.update(fields)
        self.inflight = (cmd, self.req)
        for _ in range(3):
            deadline = time.monotonic() + 0.5
            while self.tx and time.monotonic() < deadline:
                self.pump(heartbeat=False)
                time.sleep(0.001)
            self.queue_write(request)
            while time.monotonic() < deadline:
                self.pump()
                if self.req in self.responses:
                    result = self.responses.pop(self.req)
                    if result["type"] == "NACK":
                        self.inflight = None
                        raise ValueError(result.get("code"))
                    if cmd == "HELLO":
                        if result["type"] != "INFO" or result.get("protocol") != 1:
                            raise ValueError("非対応プロトコル")
                        self.boot_id, self.info = result["boot_id"], result
                        self.req = result["next_req"]
                    elif cmd == "START_SESSION":
                        self.session_id = result["session_id"]
                        self.ended = False
                    self.inflight = None
                    return result
                if self.stop_flag.is_set() and cmd not in ("STOP_SESSION", "HELLO"):
                    raise InterruptedError("停止要求")
                time.sleep(0.001)
        raise TimeoutError(cmd + " の応答がありません")

    # DESN-SW-003
    def close(self):
        self.serial.close()


# DESN-SW-001
def connect(port, callback, stop_flag):
    candidates = [port] if port else [p.device for p in sorted(list_ports.comports(), key=lambda p: p.device, reverse=True) if p.vid == 0x2E8A]
    errors = []
    for candidate in candidates:
        link = None
        try:
            link = Link(candidate, callback, stop_flag)
            link.rpc("HELLO")
            return link
        except Exception as exc:
            errors.append(candidate + ": " + str(exc))
            if link:
                link.close()
    raise OSError("アプリ用CDCが見つかりません。 " + "; ".join(errors))


# DESN-SW-001
class Worker(threading.Thread):
    # DESN-SW-003/008/010
    def __init__(self, cfg, port=None, auto_start=False):
        super().__init__(name="CAN-USB", daemon=True)
        self.cfg, self.port, self.auto_start = cfg, port, auto_start
        self.commands = queue.Queue(64)
        self.stops = queue.Queue(64)
        self.intent = {}
        self.intent_lock = threading.Lock()
        self.stop_flag, self.ready, self.done = threading.Event(), threading.Event(), threading.Event()
        self.updates = queue.Queue(4096)
        self.failure = None
        self.logger = self.link = None
        self.generations = {(p["ide"], p["can_id"]): 0 for p in cfg["profiles"]}
        self.summary = None
        self.rx_count = self.tx_count = 0
        self.start_clock = None

    # DESN-SW-003/008/010
    def publish(self, e):
        try:
            self.updates.put_nowait(e)
        except queue.Full:
            # GUIの古い描画だけを捨てる。ログは独立キューで既に受け付ける。
            try:
                self.updates.get_nowait()
            except queue.Empty:
                pass
            self.updates.put_nowait(e)

    # DESN-SW-003/008/010
    def on_event(self, e):
        if e["type"].startswith("TX_") and "profile_id" in e and e["type"] != "TX_ACCEPTED":
            p = next((p for p in self.cfg["profiles"] if p["profile_id"] == e["profile_id"]), None)
            if p is None:
                raise ValueError("未登録profileの送信結果")
            e = dict(wire_profile(p), **e)
        if self.logger:
            self.logger.put(e)
        if e["type"] == "RX":
            self.rx_count += 1
        elif e["type"] == "TX_DONE":
            self.tx_count += 1
        elif e["type"] == "SESSION_END":
            self.summary = e
            if (e.get("dropped") or not e.get("drain_complete") or not e.get("stop_confirmed")
                    or e["stats"]["rx"] != self.rx_count
                    or e["stats"]["tx_done"] != self.tx_count):
                self.failure = "機器集計と保存受付件数の不一致、または欠落・停止未確認があります"
        self.publish(e)

    # DESN-SW-003/008/010
    def start_profile(self, pid):
        p = next(p for p in self.cfg["profiles"] if p["profile_id"] == pid)
        response = self.link.rpc("START_PROFILE", profile_id=pid,
                                 generation=self.generations[(p["ide"], p["can_id"])])
        self.generations[(p["ide"], p["can_id"])] = response["generation"]
        self.on_event(dict(response, type="TX_ACCEPTED", profile=wire_profile(p)))

    # DESN-SW-003/008/010
    def next_command(self):
        """停止を先に処理し、それ以前に受付けた同じIDの開始を破棄する。"""
        try:
            return self.stops.get_nowait()
        except queue.Empty:
            pass
        while True:
            cmd, value, key, intent = self.commands.get_nowait()
            with self.intent_lock:
                if self.intent.get(key, 0) == intent:
                    return cmd, value

    # DESN-SW-003/008/010
    def run(self):
        try:
            self.link = connect(self.port, self.on_event, self.stop_flag)
            cfg = self.cfg
            self.link.rpc("LOAD_BEGIN", revision=cfg["revision"], count=len(cfg["profiles"]))
            for p in cfg["profiles"]:
                self.link.rpc("LOAD_PROFILE", revision=cfg["revision"], profile=wire_profile(p))
            self.link.rpc("LOAD_COMMIT", revision=cfg["revision"], count=len(cfg["profiles"]))
            try:
                commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL).strip()
            except (OSError, subprocess.CalledProcessError):
                commit = "unknown"
            metadata = {"ホスト版": VERSION, "開始UTC": utc(), "Python": sys.version,
                        "機器": self.link.info, "config": cfg, "Git": commit,
                        "source_sha256": source_manifest(),
                        "TSEOF": 1, "RX時刻": "EOF最終直前ビット", "TX時刻": "EOF終了",
                        "flush_ms": 100, "fsync_ms": 1000}
            self.logger = LogWriter(cfg["log_dir"], metadata)
            self.logger.start()
            if not self.logger.ready.wait(3) or self.logger.failure:
                raise OSError(self.logger.failure or "ログ準備期限超過")
            self.link.rpc("START_SESSION", revision=cfg["revision"], duration_ms=cfg["duration_ms"],
                          device_config_id=cfg["device_config_id"])
            self.start_clock = time.monotonic()
            self.ready.set()
            if self.auto_start:
                for p in cfg["profiles"]:
                    self.start_profile(p["profile_id"])
            while not self.link.ended and not self.stop_flag.is_set():
                if time.monotonic() - self.start_clock > cfg["duration_ms"] / 1000 + 2.5:
                    raise TimeoutError("セッション終了通知の期限超過")
                self.link.pump()
                if self.logger.failure:
                    raise OSError(self.logger.failure)
                try:
                    cmd, value = self.next_command()
                except queue.Empty:
                    time.sleep(0.001)
                    continue
                try:
                    if cmd == "start":
                        self.start_profile(value)
                    elif cmd == "stop_id":
                        ide, can_id = value
                        response = self.link.rpc("STOP_ID", ide=ide, can_id=can_id)
                        self.generations[value] = response["generation"]
                except ValueError as exc:
                    self.on_event({"type": "ERROR", "code": "COMMAND_REJECTED", "detail": str(exc),
                                   "operation": cmd, "value": value})
        except Exception as exc:
            self.failure = str(exc)
            self.publish({"type": "ERROR", "code": "HOST", "detail": self.failure})
        finally:
            if self.link:
                if self.link.session_id and not self.link.ended:
                    try:
                        self.link.rpc("STOP_SESSION", reason="HOST_STOP")
                        deadline = time.monotonic() + 2.2
                        while not self.link.ended and time.monotonic() < deadline:
                            self.link.pump()
                            time.sleep(0.001)
                        if not self.link.ended:
                            self.failure = self.failure or "CAN停止・ログ完了の応答を確認できません"
                    except Exception as exc:
                        self.failure = self.failure or str(exc)
                self.link.close()
            if self.logger:
                try:
                    self.logger.close()
                except OSError as exc:
                    self.failure = self.failure or str(exc)
            self.done.set()

    # DESN-SW-003/008/010
    def request(self, cmd, value):
        try:
            with self.intent_lock:
                if cmd == "stop_id":
                    self.stops.put_nowait((cmd, value))
                    self.intent[value] = self.intent.get(value, 0) + 1
                else:
                    p = next(p for p in self.cfg["profiles"] if p["profile_id"] == value)
                    key = (p["ide"], p["can_id"])
                    self.commands.put_nowait((cmd, value, key, self.intent.get(key, 0)))
            return True
        except queue.Full:
            self.publish({"type": "ERROR", "code": "COMMAND_QUEUE_FULL"})
            return False


# DESN-SW-001
class App:
    """DESN-SW-005/007: Tk操作はこのスレッドだけ。100msごとに最新値描画。"""

    # DESN-SW-005/007
    def __init__(self, root, cfg, port=None):
        import tkinter as tk
        from tkinter import ttk
        self.root, self.cfg, self.port = root, cfg, port
        self.worker = None
        self.held = set()
        self.latest = OrderedDict()
        self.active_profiles = {}
        self.profile_labels = {}
        self.closing = False
        root.title("Pico SPI CAN FD — " + VERSION)
        root.geometry("1120x680")
        root.minsize(800, 500)
        self.state = tk.StringVar(value="停止中 — セッション開始で受信を有効化")
        self.error = tk.StringVar(value="最新エラー: なし")
        self.counts = tk.StringVar(value="RX 0 / TX完了 0")
        self.action = tk.StringVar(value="送信操作: なし")
        bar = ttk.Frame(root, padding=12)
        bar.pack(fill="x")
        self.start_button = ttk.Button(bar, text="セッション開始", command=self.start)
        self.start_button.pack(side="left")
        ttk.Button(bar, text="全停止 [Esc]", command=self.stop).pack(side="left", padx=8)
        ttk.Label(bar, textvariable=self.counts).pack(side="right")
        ttk.Label(root, textvariable=self.state, padding=(12, 4)).pack(anchor="w")
        ttk.Label(root, text="500 kbit/s / FD 2 Mbit/s    終端: 自ノードは追加なし", padding=(12, 4)).pack(anchor="w")
        profiles = ttk.Frame(root, padding=12)
        profiles.pack(fill="x")
        for p in cfg["profiles"]:
            label = "%s  %s 0x%X  %s  %d B  %d ms" % (p["profile_id"], "EXT" if p["ide"] else "STD", p["can_id"], "FD" if p["fdf"] else "Classical", len(p["data"]) // 2, p["period_ms"])
            row = ttk.Frame(profiles)
            row.pack(fill="x", pady=2)
            ttk.Label(row, text=label, width=68).pack(side="left")
            ttk.Button(row, text="開始 [" + p["start_key"] + "]", command=lambda p=p: self.profile_start(p)).pack(side="left", padx=4)
            ttk.Button(row, text="停止 [" + p["stop_key"] + "]", command=lambda p=p: self.profile_stop(p)).pack(side="left")
            status = tk.StringVar(value="停止済み")
            self.profile_labels[p["profile_id"]] = status
            ttk.Label(row, textvariable=status, width=14).pack(side="left", padx=8)
        ttk.Label(root, textvariable=self.action, wraplength=1070, padding=(12, 2)).pack(anchor="w")
        columns = ("id", "format", "len", "data", "count", "time")
        table_frame = ttk.Frame(root)
        table_frame.pack(fill="both", expand=True, padx=12, pady=8)
        self.table = ttk.Treeview(table_frame, columns=columns, show="headings")
        for c, title, width in zip(columns, ("CAN ID", "形式", "長さ", "最新受信データ", "回数", "機器時刻 us"), (110, 95, 50, 500, 70, 130)):
            self.table.heading(c, text=title)
            self.table.column(c, width=width, minwidth=40)
        self.table.grid(row=0, column=0, sticky="nsew")
        scroll_x = ttk.Scrollbar(table_frame, orient="horizontal", command=self.table.xview)
        scroll_y = ttk.Scrollbar(table_frame, orient="vertical", command=self.table.yview)
        scroll_x.grid(row=1, column=0, sticky="ew")
        scroll_y.grid(row=0, column=1, sticky="ns")
        self.table.configure(xscrollcommand=scroll_x.set, yscrollcommand=scroll_y.set)
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)
        ttk.Label(root, textvariable=self.error, foreground="#b42318", wraplength=1080, padding=12).pack(anchor="w")
        root.bind("<KeyPress>", self.key_press)
        root.bind("<KeyRelease>", self.key_release)
        root.bind("<FocusOut>", lambda _: self.held.clear())
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.after(100, self.refresh)

    # DESN-SW-005/007
    def start(self):
        if self.worker and not self.worker.done.is_set():
            return
        self.latest.clear()
        self.active_profiles.clear()
        for label in self.profile_labels.values():
            label.set("停止済み")
        for item in self.table.get_children():
            self.table.delete(item)
        self.worker = Worker(self.cfg, self.port)
        self.worker.start()
        self.start_button.configure(state="disabled")
        self.state.set("設定転送・ログ準備中")

    # DESN-SW-005/007
    def stop(self):
        if self.worker:
            self.worker.stop_flag.set()

    # DESN-SW-005/007
    def profile_start(self, p):
        if self.worker and self.worker.ready.is_set() and not self.worker.done.is_set():
            key = (p["ide"], p["can_id"])
            active = self.active_profiles.get(key)
            if active:
                current = next(q for q in self.cfg["profiles"] if q["profile_id"] == active)
                if all(current[f] == p[f] for f in ("data", "period_ms", "fdf", "brs")):
                    return
            if self.worker.request("start", p["profile_id"]):
                self.active_profiles[key] = p["profile_id"]
                self.profile_labels[p["profile_id"]].set("開始要求中")
                self.action.set("%s押下: %s 0x%X / %s / %d ms / HEX %s" % (
                    p["start_key"], "EXT" if p["ide"] else "STD", p["can_id"],
                    "FD" if p["fdf"] else "Classical", p["period_ms"], p["data"]))

    # DESN-SW-005/007
    def profile_stop(self, p):
        if self.worker and self.worker.ready.is_set() and not self.worker.done.is_set():
            if self.worker.request("stop_id", (p["ide"], p["can_id"])):
                self.profile_labels[p["profile_id"]].set("停止要求中")

    # DESN-SW-005/007
    def key_press(self, event):
        key = event.keysym.lower()
        if key == "escape":
            self.stop()
            return
        if key in self.held:
            return
        self.held.add(key)
        for p in self.cfg["profiles"]:
            if key == p["start_key"]:
                self.profile_start(p)
            elif key == p["stop_key"]:
                self.profile_stop(p)

    # DESN-SW-005/007
    def key_release(self, event):
        self.held.discard(event.keysym.lower())

    # DESN-SW-005/007
    def refresh(self):
        worker = self.worker
        if worker:
            for _ in range(4096):
                try:
                    e = worker.updates.get_nowait()
                except queue.Empty:
                    break
                if e["type"] == "RX":
                    key = (e["ide"], e["can_id"], e["fdf"])
                    count = self.latest.get(key, (None, 0))[1] + 1
                    if key not in self.latest and len(self.latest) >= 4096:
                        old, _ = self.latest.popitem(last=False)
                        self.table.delete(str(old))
                    self.latest[key] = (e, count)
                    values = ("%s %X" % ("EXT" if key[0] else "STD", key[1]),
                              ("FD" if key[2] else "Classical") + (" RTR" if e["rtr"] else ""),
                              e["length"], e["data"], count, e["device_us"])
                    if self.table.exists(str(key)):
                        self.table.item(str(key), values=values)
                    else:
                        self.table.insert("", "end", iid=str(key), values=values)
                elif e["type"] == "TX_ACCEPTED":
                    p = e["profile"]
                    pid = e.get("profile_id", p["profile_id"])
                    self.active_profiles[(p["ide"], p["can_id"])] = pid
                    for other in self.cfg["profiles"]:
                        if (other["ide"], other["can_id"]) == (p["ide"], p["can_id"]) and other["profile_id"] != pid:
                            self.profile_labels[other["profile_id"]].set("停止済み")
                    self.profile_labels[pid].set("置換待ち" if e["result"] == "REPLACING" else "周期送信中")
                elif e["type"] == "TX_DONE":
                    if self.active_profiles.get((e["ide"], e["can_id"])) == e["profile_id"]:
                        self.profile_labels[e["profile_id"]].set("周期送信中")
                elif e["type"] == "ID_STOPPED":
                    self.active_profiles.pop((e["ide"], e["can_id"]), None)
                    for p in self.cfg["profiles"]:
                        if (p["ide"], p["can_id"]) == (e["ide"], e["can_id"]):
                            self.profile_labels[p["profile_id"]].set("停止済み")
                elif e["type"] in ("ERROR", "NACK"):
                    self.error.set("最新エラー: " + str(e.get("code")) + " " + str(e.get("detail", "")))
                    if e.get("operation") == "start":
                        p = next(p for p in self.cfg["profiles"] if p["profile_id"] == e["value"])
                        self.active_profiles.pop((p["ide"], p["can_id"]), None)
                        self.profile_labels[p["profile_id"]].set("要求拒否")
            self.counts.set("RX %d / TX完了 %d" % (worker.rx_count, worker.tx_count))
            if worker.done.is_set():
                self.active_profiles.clear()
                for label in self.profile_labels.values():
                    label.set("停止済み" if worker.summary and worker.summary.get("stop_confirmed") else "停止未確認")
                self.state.set("停止済み / " + (worker.failure or str(worker.summary.get("reason") if worker.summary else "未開始")))
                self.start_button.configure(state="normal")
                if worker.failure:
                    self.error.set("最新エラー: " + worker.failure)
            elif worker.ready.is_set():
                remaining = max(0, self.cfg["duration_ms"] / 1000 - (time.monotonic() - worker.start_clock))
                self.state.set("受信中 / 残り %.1f秒 / キーで周期送信を開始 / %s" % (remaining, worker.logger.directory))
        if self.closing and (not worker or worker.done.is_set()):
            self.root.destroy()
            return
        self.root.after(100, self.refresh)

    # DESN-SW-005/007
    def close(self):
        self.closing = True
        self.stop()


# DESN-SW-001
def main():
    parser = argparse.ArgumentParser(description="Pico SPI CAN FD")
    parser.add_argument("--config", default=str(Path(__file__).with_name("config.py")))
    parser.add_argument("--port", help="アプリ用CDC。省略時はPicoから探索")
    parser.add_argument("--duration", type=int, help="試験時間（秒）。1〜86400")
    parser.add_argument("--headless", action="store_true", help="GUIなしで4 IDを開始")
    args = parser.parse_args()
    cfg = load_config(args.config)
    if args.duration is not None:
        cfg["duration_ms"] = integer(args.duration, 1, 86400) * 1000
    if args.headless:
        worker = Worker(cfg, args.port, auto_start=True)
        worker.start()
        try:
            while not worker.done.wait(0.2):
                while not worker.updates.empty():
                    e = worker.updates.get_nowait()
                    if e["type"] in ("ERROR", "NACK"):
                        print(json.dumps(e), flush=True)
        except KeyboardInterrupt:
            worker.stop_flag.set()
            worker.done.wait(7)
        print(json.dumps({"failure": worker.failure, "summary": worker.summary,
                          "logs": str(worker.logger.directory) if worker.logger else None}, ensure_ascii=False))
        return 1 if worker.failure or not worker.summary or worker.summary["reason"] != "DURATION" else 0
    import tkinter as tk
    root = tk.Tk()
    App(root, cfg, args.port)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
