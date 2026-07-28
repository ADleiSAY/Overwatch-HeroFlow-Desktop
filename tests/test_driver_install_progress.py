import io
import zipfile
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import patch

import driver_click
from backend.ipc.server import JsonRpcServer


def test_install_driver_forwards_progress_and_restart_requirement():
    events = []
    server = object.__new__(JsonRpcServer)
    server.emit = lambda event, payload: events.append((event, payload))

    def fake_install(progress_callback):
        progress_callback(12, "downloading", "正在下载驱动")
        progress_callback(96, "verifying", "正在验证驱动")
        return True, "安装完成"

    with (
        patch("backend.ipc.server.install_driver", fake_install),
        patch("backend.ipc.server.is_driver_loaded", return_value=False),
    ):
        result = server.call("install_driver", {})

    assert result == {
        "ok": True,
        "message": "安装完成",
        "requires_restart": True,
    }
    assert events == [
        (
            "driver_install_progress",
            {"progress": 12, "phase": "downloading", "message": "正在下载驱动"},
        ),
        (
            "driver_install_progress",
            {"progress": 96, "phase": "verifying", "message": "正在验证驱动"},
        ),
        ("driver_install_finished", result),
    ]


def test_install_driver_clamps_progress_and_reports_failure():
    events = []
    server = object.__new__(JsonRpcServer)
    server.emit = lambda event, payload: events.append((event, payload))

    def fake_install(progress_callback):
        progress_callback(140, "error", "下载失败")
        return False, "下载失败"

    with (
        patch("backend.ipc.server.install_driver", fake_install),
        patch("backend.ipc.server.is_driver_loaded", return_value=False),
    ):
        result = server.call("install_driver", {})

    assert result["ok"] is False
    assert result["requires_restart"] is False
    assert events[0][1]["progress"] == 100
    assert events[-1] == ("driver_install_finished", result)


def test_successful_download_does_not_write_unencodable_console_output(tmp_path):
    events = []
    zip_path = tmp_path / "interception_install" / "Interception.zip"

    class FakeProcess:
        returncode = 0
        args = ["powershell"]

        def __init__(self, *_args, **_kwargs):
            zip_path.parent.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_STORED) as archive:
                archive.writestr(
                    "Interception/command line installer/install-interception.exe",
                    b"\0" * 110_000,
                )

        def poll(self):
            return self.returncode

        def communicate(self):
            return "", ""

    fake_windll = SimpleNamespace(
        shell32=SimpleNamespace(ShellExecuteExW=lambda _info: 0),
        kernel32=SimpleNamespace(GetLastError=lambda: 1223),
    )
    gbk_output = io.TextIOWrapper(io.BytesIO(), encoding="gbk", errors="strict")

    with (
        patch.dict("os.environ", {"TEMP": str(tmp_path)}),
        patch("driver_click.is_driver_installed", return_value=False),
        patch("driver_click.subprocess.Popen", FakeProcess),
        patch.object(driver_click.ctypes, "windll", fake_windll),
        redirect_stdout(gbk_output),
    ):
        ok, message = driver_click.install_driver(
            lambda progress, phase, text: events.append((progress, phase, text))
        )

    assert ok is False
    assert "codec can't encode" not in message
    assert any(phase == "downloaded" for _, phase, _ in events)
    assert events[-1][1] == "error"
