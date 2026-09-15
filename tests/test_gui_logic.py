"""DESN-SW-005: OS画面を操作しないキー状態の自動試験。"""
import threading
from types import SimpleNamespace

from host.main import App, load_config


class Value:
    def set(self, value):
        self.value = value


def app():
    ui = App.__new__(App)
    ui.cfg = load_config("host/config.py")
    ui.held, ui.active_profiles = set(), {}
    ui.profile_labels = {p["profile_id"]: Value() for p in ui.cfg["profiles"]}
    ui.action = Value()
    requested = []
    ready = threading.Event()
    ready.set()
    ui.worker = SimpleNamespace(ready=ready, done=threading.Event(), stop_flag=threading.Event(),
                                request=lambda *args: requested.append(args) or True)
    return ui, requested


def test_held_and_released_active_key_do_not_repeat_start():
    ui, requested = app()
    key = SimpleNamespace(keysym="a")
    for _ in range(20):
        ui.key_press(key)
    ui.key_release(key)
    ui.key_press(key)
    assert requested == [("start", "T1")]
    assert "0x300" in ui.action.value and "1112131415161718" in ui.action.value


def test_escape_and_individual_stop_have_distinct_scope():
    ui, requested = app()
    ui.key_press(SimpleNamespace(keysym="b"))
    assert requested == [("stop_id", (False, 0x300))]
    assert not ui.worker.stop_flag.is_set()
    ui.key_press(SimpleNamespace(keysym="Escape"))
    assert ui.worker.stop_flag.is_set()


def test_unprepared_gui_ignores_send_key():
    ui, requested = app()
    ui.worker.ready.clear()
    ui.key_press(SimpleNamespace(keysym="a"))
    assert not requested
