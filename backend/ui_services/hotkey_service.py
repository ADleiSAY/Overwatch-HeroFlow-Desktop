from __future__ import annotations

import ctypes
import sys
import threading
import time
from ctypes import wintypes
from typing import Callable


class HotkeyService:
    """Provides a process-wide F8 emergency stop without a GUI dependency."""

    WM_HOTKEY = 0x0312
    WM_QUIT = 0x0012
    PM_NOREMOVE = 0x0000
    MOD_NOREPEAT = 0x4000
    VK_F8 = 0x77
    KEY_DOWN_MASK = 0x8000
    HOTKEY_ID = 1
    POLL_INTERVAL_SECONDS = 0.03
    REGISTER_RETRY_SECONDS = 2.0

    def __init__(self, callback: Callable[[], None]):
        self.callback = callback
        self._thread: threading.Thread | None = None
        self._thread_id = 0
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._native_registered = False
        self.registered = False
        self.mode = "unavailable"
        self.last_error = 0

    def start(self) -> bool:
        if sys.platform != "win32":
            return False

        with self._lock:
            if self._thread and self._thread.is_alive():
                return self.registered
            self._stop_event.clear()
            self.registered = False
            self.mode = "starting"
            self.last_error = 0

        ready = threading.Event()

        def run() -> None:
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
            self._thread_id = kernel32.GetCurrentThreadId()

            # PostThreadMessage only works after the target thread owns a message queue.
            message = wintypes.MSG()
            user32.PeekMessageW(ctypes.byref(message), None, 0, 0, self.PM_NOREMOVE)

            next_register_attempt = 0.0
            was_down = bool(user32.GetAsyncKeyState(self.VK_F8) & self.KEY_DOWN_MASK)
            try:
                while not self._stop_event.is_set():
                    now = time.monotonic()
                    if now >= next_register_attempt:
                        ctypes.set_last_error(0)
                        self._native_registered = bool(
                            user32.RegisterHotKey(
                                None,
                                self.HOTKEY_ID,
                                self.MOD_NOREPEAT,
                                self.VK_F8,
                            )
                        )
                        self.last_error = 0 if self._native_registered else ctypes.get_last_error()
                        if self._native_registered:
                            self.registered = True
                            self.mode = "registered"
                            ready.set()
                            break

                        # A different process may temporarily own F8. Polling keeps the
                        # emergency stop usable while we periodically retry registration.
                        self.registered = True
                        self.mode = "polling"
                        ready.set()
                        next_register_attempt = now + self.REGISTER_RETRY_SECONDS

                    is_down = bool(user32.GetAsyncKeyState(self.VK_F8) & self.KEY_DOWN_MASK)
                    if is_down and not was_down:
                        self._invoke_callback()
                    was_down = is_down
                    self._stop_event.wait(self.POLL_INTERVAL_SECONDS)

                if self._native_registered and not self._stop_event.is_set():
                    while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
                        if message.message == self.WM_HOTKEY and message.wParam == self.HOTKEY_ID:
                            self._invoke_callback()
            finally:
                if self._native_registered:
                    user32.UnregisterHotKey(None, self.HOTKEY_ID)
                self._native_registered = False
                self.registered = False
                self.mode = "unavailable"
                self._thread_id = 0
                ready.set()
                with self._lock:
                    if self._thread is threading.current_thread():
                        self._thread = None

        with self._lock:
            self._thread = threading.Thread(target=run, name="f8-hotkey", daemon=True)
            self._thread.start()
        ready.wait(2)
        return self.registered

    def _invoke_callback(self) -> None:
        try:
            self.callback()
        except Exception:
            # An emergency hotkey must remain alive even if one callback fails.
            pass

    def stop(self) -> None:
        self._stop_event.set()
        with self._lock:
            thread = self._thread
            thread_id = self._thread_id
            native_registered = self._native_registered
        if thread_id and native_registered and sys.platform == "win32":
            ctypes.windll.user32.PostThreadMessageW(thread_id, self.WM_QUIT, 0, 0)
        if thread and thread is not threading.current_thread():
            thread.join(timeout=2)
