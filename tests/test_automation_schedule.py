import threading
import time
from datetime import datetime

import backend.core.automation_service as automation_module
from backend.core.automation_service import AutomationService


class _Power:
    def start(self):
        return None

    def stop(self):
        return None

    def get_current_power(self):
        return 0

    def get_total_energy(self):
        return 0

    def get_average_power(self):
        return 0

    def is_degraded(self):
        return False

    def is_available(self):
        return True


class _Overlay:
    enabled = False
    executable = None

    def __init__(self, executable=None):
        self.executable = executable

    def set_enabled(self, enabled):
        self.enabled = bool(enabled)
        return self.enabled

    def update(self, *args):
        return None

    def close(self):
        return None


class _Hotkey:
    registered = True

    def __init__(self, callback):
        self.callback = callback

    def start(self):
        return None

    def stop(self):
        return None


def _service(monkeypatch, schedule_path=None):
    monkeypatch.setattr(automation_module, "PowerMonitor", _Power)
    monkeypatch.setattr(automation_module, "OverlayService", _Overlay)
    monkeypatch.setattr(automation_module, "HotkeyService", _Hotkey)
    return AutomationService(
        lambda event, payload: None,
        schedule_store_path=schedule_path,
    )


def _local_iso(timestamp):
    return datetime.fromtimestamp(timestamp).isoformat()


def test_scheduled_window_uses_explicit_start_and_end(monkeypatch):
    service = _service(monkeypatch)
    start = time.time() + 600
    end = start + 3600
    options = {
        "schedule_mode": "scheduled",
        "start_at": _local_iso(start),
        "end_at": _local_iso(end),
        "duration_s": 60,
    }

    parsed_start, parsed_end, duration = service._prepare_timing(options)

    assert abs(parsed_start - start) < 1
    assert abs(parsed_end - end) < 1
    assert abs(duration - 3600) < 1


def test_cancel_during_scheduled_initialization_cannot_restart_task(monkeypatch):
    service = _service(monkeypatch)
    entered = threading.Event()
    release = threading.Event()

    class _Clicker:
        camera = None

        def find_window(self):
            entered.set()
            release.wait(2)
            return True

        def init_camera(self):
            return True

    class _Resource:
        def destroy(self):
            return None

    monkeypatch.setattr(automation_module, "Clicker", _Clicker)
    monkeypatch.setattr(automation_module, "DriverKeyboard", _Resource)
    monkeypatch.setattr(automation_module, "DriverClicker", _Resource)

    start = time.time() + 0.1
    service.start({
        "schedule_mode": "scheduled",
        "start_at": _local_iso(start),
        "end_at": _local_iso(start + 60),
        "duration_s": 60,
        "hero_ratios": {"D.Va": 100},
        "auto_shutdown": "none",
    })
    assert entered.wait(2)

    assert service.stop()["status"] == "stopping"
    release.set()
    time.sleep(0.1)

    assert service.snapshot()["status"] == "idle"
    assert service._engine is None
    service.close()


def test_duration_deadline_stops_loop_and_flow_engines(monkeypatch):
    service = _service(monkeypatch)

    class _Engine:
        finished = False

        def finish_due_to_timeout(self):
            self.finished = True

    engine = _Engine()
    service._generation = 1
    service._status = "running"
    service._engine = engine

    service._deadline_worker(1, threading.Event(), None, 0.01)

    assert engine.finished is True
    assert service.snapshot()["status"] == "stopping"


def test_expired_persisted_window_is_skipped_after_restart(monkeypatch, tmp_path):
    schedule_path = tmp_path / "pending_schedule.json"
    service = _service(monkeypatch, schedule_path)
    start = time.time() - 120
    service._persist_schedule({
        "schedule_mode": "scheduled",
        "start_at": _local_iso(start),
        "end_at": _local_iso(start + 60),
        "duration_s": 60,
        "hero_ratios": {"D.Va": 100},
        "auto_shutdown": "none",
    }, False)

    restored = _service(monkeypatch, schedule_path)
    snapshot = restored.restore_pending_schedule()

    assert snapshot["status"] == "completed"
    assert "已过期" in snapshot["current_step"]
    assert restored._engine is None
    assert not schedule_path.exists()


def test_future_persisted_schedule_is_rearmed_after_restart(monkeypatch, tmp_path):
    schedule_path = tmp_path / "pending_schedule.json"
    service = _service(monkeypatch, schedule_path)
    start = time.time() + 300
    service._persist_schedule({
        "schedule_mode": "scheduled",
        "start_at": _local_iso(start),
        "end_at": _local_iso(start + 60),
        "duration_s": 60,
        "hero_ratios": {"D.Va": 100},
        "auto_shutdown": "none",
    }, False)

    restored = _service(monkeypatch, schedule_path)
    snapshot = restored.restore_pending_schedule()

    assert snapshot["status"] == "scheduled"
    assert abs(datetime.fromisoformat(snapshot["scheduled_for"]).timestamp() - start) < 1
    restored.stop()
    assert not schedule_path.exists()
