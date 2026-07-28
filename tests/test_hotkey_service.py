from __future__ import annotations

import threading
import time

from backend.ui_services.hotkey_service import HotkeyService


class _FakeKernel32:
    @staticmethod
    def GetCurrentThreadId() -> int:
        return 42


class _FakeUser32:
    def __init__(self) -> None:
        self.register_calls = 0
        self.key_states = iter((0, 0, 0x8000, 0x8000, 0))

    @staticmethod
    def PeekMessageW(*_args) -> int:
        return 0

    def RegisterHotKey(self, *_args) -> int:
        self.register_calls += 1
        return 0

    def GetAsyncKeyState(self, _key: int) -> int:
        return next(self.key_states, 0)


class _FakeWindll:
    def __init__(self, user32: _FakeUser32) -> None:
        self.user32 = user32
        self.kernel32 = _FakeKernel32()


def test_f8_polling_fallback_triggers_once(monkeypatch) -> None:
    import backend.ui_services.hotkey_service as module

    fake_user32 = _FakeUser32()
    monkeypatch.setattr(module.sys, "platform", "win32")
    monkeypatch.setattr(module.ctypes, "windll", _FakeWindll(fake_user32))
    monkeypatch.setattr(module.ctypes, "set_last_error", lambda _value: None)
    monkeypatch.setattr(module.ctypes, "get_last_error", lambda: 1409)
    monkeypatch.setattr(HotkeyService, "POLL_INTERVAL_SECONDS", 0.001)
    monkeypatch.setattr(HotkeyService, "REGISTER_RETRY_SECONDS", 60.0)

    triggered = threading.Event()
    calls = []
    service = HotkeyService(lambda: (calls.append("F8"), triggered.set()))

    try:
        assert service.start() is True
        assert service.mode == "polling"
        assert triggered.wait(0.25)
        time.sleep(0.01)
        assert calls == ["F8"]
    finally:
        service.stop()

    assert service.registered is False
    assert service.mode == "unavailable"


def test_start_is_idempotent_while_fallback_is_running(monkeypatch) -> None:
    import backend.ui_services.hotkey_service as module

    fake_user32 = _FakeUser32()
    monkeypatch.setattr(module.sys, "platform", "win32")
    monkeypatch.setattr(module.ctypes, "windll", _FakeWindll(fake_user32))
    monkeypatch.setattr(module.ctypes, "set_last_error", lambda _value: None)
    monkeypatch.setattr(module.ctypes, "get_last_error", lambda: 1409)
    monkeypatch.setattr(HotkeyService, "REGISTER_RETRY_SECONDS", 60.0)

    service = HotkeyService(lambda: None)
    try:
        assert service.start() is True
        assert service.start() is True
        assert fake_user32.register_calls == 1
    finally:
        service.stop()
