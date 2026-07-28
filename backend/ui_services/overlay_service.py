from __future__ import annotations

import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path


OVERLAY_CLOSE_COMMAND = "__HEROFLOW_OVERLAY_CLOSE__"


class OverlayService:
    """Owns the transparent overlay process and its UDP data channel."""

    def __init__(self, executable: str | None = None, host: str = "127.0.0.1", port: int = 12345):
        self.executable = Path(executable) if executable else None
        self.host = host
        self.port = port
        self.enabled = False
        self._process: subprocess.Popen | None = None
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._lock = threading.RLock()

    def set_enabled(self, enabled: bool) -> bool:
        with self._lock:
            if enabled:
                self._start()
            else:
                self.close()
            return self.enabled

    def _start(self) -> None:
        if self._process and self._process.poll() is None:
            self.enabled = True
            return
        command: list[str] | None = None
        if self.executable and self.executable.exists():
            command = [str(self.executable), str(os.getpid()), self.host, str(self.port)]
        elif not getattr(sys, "frozen", False):
            script = Path(__file__).resolve().parents[2] / "overlay.py"
            if script.exists():
                command = [
                    sys.executable,
                    "-u",
                    str(script),
                    str(os.getpid()),
                    self.host,
                    str(self.port),
                ]
        if not command:
            raise RuntimeError("overlay_executable_unavailable")
        flags = 0x08000000 if sys.platform == "win32" else 0
        self._process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=flags,
        )
        time.sleep(0.3)
        exit_code = self._process.poll()
        if exit_code is not None:
            self._process = None
            self.enabled = False
            raise RuntimeError(f"overlay_start_failed:{exit_code}")
        self.enabled = True

    def update(self, x, y, width, height, name, step, next_step, confidence) -> None:
        if not self.enabled:
            return
        message = (
            f"{int(x)} {int(y)} {int(width)} {int(height)}|"
            f"{name}|{step}|{next_step}|{float(confidence):.3f}"
        )
        try:
            self._socket.sendto(message.encode("utf-8"), (self.host, self.port))
        except OSError:
            pass

    def close(self) -> None:
        with self._lock:
            process, self._process = self._process, None
            self.enabled = False
            if not process:
                return

            # PyInstaller onefile 在 Windows 下会生成启动器和实际窗口两个进程。
            # 先让窗口进程自行退出，启动器会随之正常结束。
            try:
                payload = OVERLAY_CLOSE_COMMAND.encode("utf-8")
                for _ in range(3):
                    self._socket.sendto(payload, (self.host, self.port))
                    time.sleep(0.03)
                process.wait(timeout=2)
                return
            except (OSError, subprocess.TimeoutExpired):
                pass

            # 主动退出消息未送达时，清理整棵进程树，防止只关闭启动器后
            # 留下仍在绘制的 overlay 子进程。
            self._terminate_process_tree(process)

    @staticmethod
    def _terminate_process_tree(process: subprocess.Popen) -> None:
        try:
            import psutil
        except ImportError:
            psutil = None

        if psutil is not None:
            try:
                parent = psutil.Process(process.pid)
                descendants = parent.children(recursive=True)
                targets = descendants + [parent]
                for target in reversed(targets):
                    try:
                        target.terminate()
                    except psutil.Error:
                        pass
                _, alive = psutil.wait_procs(targets, timeout=1.5)
                for target in alive:
                    try:
                        target.kill()
                    except psutil.Error:
                        pass
                try:
                    process.wait(timeout=1)
                except (OSError, subprocess.TimeoutExpired):
                    pass
                return
            except (psutil.Error, OSError):
                pass

        try:
            process.terminate()
            process.wait(timeout=1)
        except (OSError, subprocess.TimeoutExpired):
            try:
                process.kill()
                process.wait(timeout=1)
            except (OSError, subprocess.TimeoutExpired):
                pass
