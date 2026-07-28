from __future__ import annotations

import json
import math
import os
import secrets
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from .flow_engine import FlowEngine
from .hero_selector import HeroSelector
from backend.drivers import Clicker, DriverClicker, DriverKeyboard
from backend.monitoring import PowerMonitor
from backend.ui_services import HotkeyService, OverlayService


MAX_RUN_DURATION_S = 7 * 24 * 3600
SCHEDULE_START_GRACE_S = 60


class _LaunchCancelled(RuntimeError):
    pass


class AutomationService:
    """Coordinates scheduling, automation resources, monitoring and emergency stop."""

    def __init__(
        self,
        emit: Callable[[str, dict[str, Any]], None],
        overlay_executable: str | None = None,
        schedule_store_path: str | os.PathLike[str] | None = None,
    ):
        self.emit = emit
        self._lock = threading.RLock()
        self._persistence_lock = threading.Lock()
        self._engine: FlowEngine | None = None
        self._thread: threading.Thread | None = None
        self._schedule_thread: threading.Thread | None = None
        self._schedule_cancel = threading.Event()
        self._deadline_thread: threading.Thread | None = None
        self._deadline_cancel = threading.Event()
        self._generation = 0
        self._resources: tuple[Any, ...] | None = None
        self._status = "idle"
        self._mode = "flow"
        self._current_step = ""
        self._next_step = ""
        self._error: dict[str, str] | None = None
        self._scheduled_for: str | None = None
        self._started_at: float | None = None
        self._pause_started_at: float | None = None
        self._schedule_store_path = Path(schedule_store_path) if schedule_store_path else None
        self._confirmations: dict[str, tuple[str, float]] = {}
        self._power = PowerMonitor()
        self._power.start()
        self.overlay = OverlayService(overlay_executable)
        self.hotkey = HotkeyService(self.emergency_stop)
        self.hotkey.start()

    @property
    def running(self) -> bool:
        return self._status in {"starting", "running", "paused", "stopping"}

    def confirm_dangerous_action(self, policy: str) -> dict[str, Any]:
        if policy not in {"stop_only", "shutdown", "both"}:
            raise ValueError("invalid_shutdown_policy")
        token = secrets.token_urlsafe(24)
        expires_at = time.time() + 300
        self._confirmations[token] = (policy, expires_at)
        return {"token": token, "expires_at": datetime.fromtimestamp(expires_at).isoformat(timespec="seconds")}

    def _validate_confirmation(self, options: dict[str, Any]) -> None:
        policy = str(options.get("auto_shutdown") or "none")
        if policy == "none":
            return
        token = str(options.pop("confirmation_token", "") or "")
        confirmed = self._confirmations.pop(token, None)
        if not confirmed or confirmed[0] != policy or confirmed[1] < time.time():
            raise PermissionError("shutdown_confirmation_required")

    def start(self, options: dict[str, Any] | None = None, loop: bool = False) -> dict[str, Any]:
        return self._start(options, loop, require_confirmation=True, allow_past_schedule=False)

    def _start(
        self,
        options: dict[str, Any] | None,
        loop: bool,
        *,
        require_confirmation: bool,
        allow_past_schedule: bool,
    ) -> dict[str, Any]:
        run_options = dict(options or {})
        with self._lock:
            if self._status not in {"idle", "completed", "error"}:
                raise RuntimeError("automation_already_active")
            selected = run_options.get("hero_ratios") or {}
            if not loop and not selected:
                raise ValueError("at_least_one_hero_required")
            start_at, end_at, duration_s = self._prepare_timing(
                run_options,
                allow_past_schedule=allow_past_schedule,
            )
            if require_confirmation:
                self._validate_confirmation(run_options)
            else:
                run_options.pop("confirmation_token", None)
            self._generation += 1
            generation = self._generation
            cancel = threading.Event()
            self._schedule_cancel = cancel
            self._deadline_cancel.set()
            self._deadline_cancel = threading.Event()
            self._error = None
            self._mode = "loop" if loop else "flow"
            self._current_step = ""
            self._next_step = ""
            self._started_at = None
            self._pause_started_at = None

            if start_at is not None and end_at is not None and end_at <= time.time():
                self._status = "completed"
                self._scheduled_for = None
                self._current_step = "预约运行时段已过期，任务未启动"
                self._clear_persisted_schedule()
                self._emit_state()
                return self.snapshot()

            if start_at is not None and start_at > time.time():
                self._status = "scheduled"
                self._scheduled_for = datetime.fromtimestamp(start_at).isoformat(timespec="seconds")
                self._persist_schedule(run_options, loop)
                self._schedule_thread = threading.Thread(
                    target=self._wait_and_launch,
                    args=(start_at, end_at, duration_s, run_options, loop, generation, cancel),
                    name="automation-scheduler",
                    daemon=True,
                )
                self._schedule_thread.start()
                self._emit_state()
                return self.snapshot()

            self._status = "starting"
            self._scheduled_for = None
            self._current_step = "正在初始化自动化资源"
        self._emit_state()
        try:
            self._launch(
                run_options,
                loop,
                generation,
                cancel,
                end_at=end_at if start_at is not None else None,
                duration_s=None if start_at is not None else duration_s,
            )
        except _LaunchCancelled:
            self._finish_cancelled_launch()
            return self.snapshot()
        except Exception as exc:
            if cancel.is_set() or generation != self._generation:
                self._finish_cancelled_launch()
                return self.snapshot()
            self._set_error("start_failed", exc, generation)
            raise
        return self.snapshot()

    def _prepare_timing(
        self,
        options: dict[str, Any],
        *,
        allow_past_schedule: bool = False,
    ) -> tuple[float | None, float | None, float | None]:
        mode = str(options.get("schedule_mode") or "immediate")
        if mode not in {"immediate", "scheduled"}:
            raise ValueError("invalid_schedule_mode")
        options["schedule_mode"] = mode

        raw_duration = options.get("duration_s")
        duration_s: float | None = None
        if raw_duration is not None:
            try:
                duration_s = float(raw_duration)
            except (TypeError, ValueError) as exc:
                raise ValueError("invalid_duration") from exc
            if (
                isinstance(raw_duration, bool)
                or not math.isfinite(duration_s)
                or duration_s < 60
                or duration_s > MAX_RUN_DURATION_S
            ):
                raise ValueError("invalid_duration")
            options["duration_s"] = int(duration_s) if duration_s.is_integer() else duration_s

        if mode != "scheduled":
            return None, None, duration_s

        raw = str(options.get("start_at") or "")
        if not raw:
            raise ValueError("scheduled_start_required")
        start_at = self._parse_datetime(raw, "invalid_scheduled_start")
        if not allow_past_schedule and start_at <= time.time():
            raise ValueError("scheduled_start_must_be_future")

        end_at: float | None = None
        if duration_s is not None:
            raw_end = str(options.get("end_at") or "")
            if raw_end:
                end_at = self._parse_datetime(raw_end, "invalid_scheduled_end")
                if end_at <= start_at:
                    raise ValueError("scheduled_end_must_be_after_start")
                duration_s = end_at - start_at
                if duration_s < 60 or duration_s > MAX_RUN_DURATION_S:
                    raise ValueError("invalid_duration")
                options["duration_s"] = int(duration_s) if duration_s.is_integer() else duration_s
            else:
                end_at = start_at + duration_s
                options["end_at"] = datetime.fromtimestamp(end_at).isoformat(timespec="seconds")
        return start_at, end_at, duration_s

    @staticmethod
    def _parse_datetime(raw: str, error_code: str) -> float:
        try:
            value = datetime.fromisoformat(raw).timestamp()
        except (OSError, OverflowError, ValueError) as exc:
            raise ValueError(error_code) from exc
        return value

    def _wait_and_launch(
        self,
        start_at: float,
        end_at: float | None,
        duration_s: float | None,
        options: dict[str, Any],
        loop: bool,
        generation: int,
        cancel: threading.Event,
    ) -> None:
        while True:
            remaining = start_at - time.time()
            if remaining <= 0:
                break
            if cancel.wait(min(0.5, remaining)):
                return
        if cancel.is_set():
            return

        with self._lock:
            if generation != self._generation or self._status != "scheduled" or cancel.is_set():
                return
            if end_at is not None and end_at <= time.time():
                self._status = "completed"
                self._scheduled_for = None
                self._schedule_thread = None
                self._current_step = "预约运行时段已过期，任务未启动"
                self._clear_persisted_schedule()
                missed = True
            else:
                self._status = "starting"
                self._scheduled_for = None
                self._current_step = "预约时间已到，正在初始化自动化资源"
                missed = False
        self._emit_state()
        if missed:
            self._log("WARN", "预约运行时段已过期，已跳过本次任务")
            return

        try:
            self._launch(
                options,
                loop,
                generation,
                cancel,
                end_at=end_at,
                duration_s=None,
            )
        except _LaunchCancelled:
            self._finish_cancelled_launch()
            return
        except Exception as exc:
            if cancel.is_set() or generation != self._generation:
                self._finish_cancelled_launch()
                return
            self._set_error("scheduled_start_failed", exc, generation)

    def _ensure_launch_current(self, generation: int, cancel: threading.Event) -> None:
        with self._lock:
            if generation != self._generation or self._status != "starting" or cancel.is_set():
                raise _LaunchCancelled()

    def _finish_cancelled_launch(self) -> None:
        with self._lock:
            if self._status != "stopping" or self._engine is not None:
                return
            self._status = "idle"
            self._current_step = ""
        self._emit_state()

    def _launch(
        self,
        options: dict[str, Any],
        loop: bool,
        generation: int,
        cancel: threading.Event,
        *,
        end_at: float | None,
        duration_s: float | None,
    ) -> None:
        clicker = Clicker()
        keyboard = DriverKeyboard()
        mouse = DriverClicker()
        try:
            self._ensure_launch_current(generation, cancel)
            window_found = clicker.find_window()
            if not window_found and options.get("schedule_mode") == "scheduled":
                retry_until = time.time() + SCHEDULE_START_GRACE_S
                if end_at is not None:
                    retry_until = min(retry_until, end_at)
                while not window_found and time.time() < retry_until:
                    if cancel.wait(min(1.0, max(0.0, retry_until - time.time()))):
                        raise _LaunchCancelled()
                    self._ensure_launch_current(generation, cancel)
                    window_found = clicker.find_window()
            if not window_found:
                raise RuntimeError("overwatch_window_unavailable")
            self._ensure_launch_current(generation, cancel)
            if not clicker.init_camera():
                raise RuntimeError("screen_capture_unavailable")
            self._ensure_launch_current(generation, cancel)
            kb_ok, kb_message = keyboard.init()
            self._ensure_launch_current(generation, cancel)
            mouse_ok, mouse_message = mouse.init()
            self._ensure_launch_current(generation, cancel)
            self._log("INFO" if kb_ok else "WARN", str(kb_message))
            self._log("INFO" if mouse_ok else "WARN", str(mouse_message))
            clicker.driver = mouse
            clicker.use_driver = bool(getattr(mouse, "available", False))
            selector = HeroSelector(options.get("hero_ratios") or {"D.Va": 100})
            callbacks = {
                "on_state_change": self._on_state_change,
                "on_log": self._log,
                "on_overlay": self.overlay.update,
                "on_finish": lambda: self.emit("flow_finished", self.snapshot()),
            }
            engine_options = {**options, "duration_s": None}
            engine = FlowEngine(clicker, keyboard, mouse, selector, callbacks=callbacks, options=engine_options)
            with self._lock:
                self._ensure_launch_current(generation, cancel)
                self._resources = (clicker, keyboard, mouse)
                self._engine = engine
                self._status = "running"
                self._scheduled_for = None
                self._schedule_thread = None
                self._started_at = time.time()
                self._current_step = ""
                target = engine.run_loop2_continuous if loop else engine.run
                self._thread = threading.Thread(
                    target=self._run_guarded,
                    args=(target, generation),
                    name="automation-worker",
                    daemon=True,
                )
                deadline_cancel = threading.Event()
                self._deadline_cancel = deadline_cancel
                if end_at is not None or duration_s is not None:
                    self._deadline_thread = threading.Thread(
                        target=self._deadline_worker,
                        args=(generation, deadline_cancel, end_at, duration_s),
                        name="automation-deadline",
                        daemon=True,
                    )
                else:
                    self._deadline_thread = None
                self._thread.start()
                if self._deadline_thread:
                    self._deadline_thread.start()
                self._clear_persisted_schedule()
            self._emit_state()
        except Exception:
            self._cleanup_resources((clicker, keyboard, mouse))
            raise

    def _deadline_worker(
        self,
        generation: int,
        cancel: threading.Event,
        end_at: float | None,
        duration_s: float | None,
    ) -> None:
        remaining = duration_s
        previous = time.monotonic()
        while not cancel.wait(0.1):
            with self._lock:
                if generation != self._generation or self._status not in {"running", "paused"}:
                    return
                status = self._status
                engine = self._engine

            if end_at is not None:
                expired = time.time() >= end_at
            else:
                current = time.monotonic()
                if status == "running" and remaining is not None:
                    remaining -= max(0.0, current - previous)
                previous = current
                expired = remaining is not None and remaining <= 0

            if not expired:
                continue

            with self._lock:
                if (
                    generation != self._generation
                    or self._status not in {"running", "paused"}
                    or not self._engine
                ):
                    return
                engine = self._engine
                self._status = "stopping"
                self._current_step = "已到计划结束时间，正在结束任务"
            self._log("INFO", "已到计划结束时间，正在结束自动化任务")
            self._emit_state()
            engine.finish_due_to_timeout()
            return

    def _run_guarded(self, target: Callable[[], None], generation: int) -> None:
        failure: Exception | None = None
        try:
            target()
        except Exception as exc:
            failure = exc
            self.emit("backend_error", {"code": "flow_failed", "message": str(exc)})
        finally:
            resources = None
            update_state = False
            with self._lock:
                if generation == self._generation:
                    self._deadline_cancel.set()
                    resources, self._resources = self._resources, None
                    self._engine = None
                    self._thread = None
                    self._deadline_thread = None
                    self._status = "error" if failure else "completed"
                    if failure:
                        self._error = {"code": "flow_failed", "message": str(failure)}
                    update_state = True
            if update_state:
                self._cleanup_resources(resources)
                self._emit_state()

    def pause(self) -> dict[str, Any]:
        with self._lock:
            if self._status != "running" or not self._engine:
                raise RuntimeError("automation_not_running")
            self._engine.pause()
            self._pause_started_at = time.time()
            self._status = "paused"
        self._emit_state()
        return self.snapshot()

    def resume(self) -> dict[str, Any]:
        with self._lock:
            if self._status != "paused" or not self._engine:
                raise RuntimeError("automation_not_paused")
            self._pause_started_at = None
            self._engine.resume()
            self._status = "running"
        self._emit_state()
        return self.snapshot()

    def stop(self) -> dict[str, Any]:
        clear_persisted = False
        with self._lock:
            if self._status == "scheduled":
                self._generation += 1
                self._schedule_cancel.set()
                self._deadline_cancel.set()
                self._schedule_thread = None
                self._scheduled_for = None
                self._status = "idle"
                self._current_step = ""
                clear_persisted = True
            elif self._status == "starting":
                self._generation += 1
                self._schedule_cancel.set()
                self._deadline_cancel.set()
                self._scheduled_for = None
                self._status = "stopping"
                self._current_step = "正在取消任务初始化"
                clear_persisted = True
            elif self._engine:
                self._status = "stopping"
                self._deadline_cancel.set()
                self._engine.stop()
            elif self._status not in {"idle", "completed", "error"}:
                self._status = "idle"
        if clear_persisted:
            self._clear_persisted_schedule()
        self._emit_state()
        return self.snapshot()

    def emergency_stop(self) -> None:
        self.emit("emergency_stop", {"key": "F8"})
        self.stop()

    def set_overlay(self, enabled: bool) -> dict[str, Any]:
        value = self.overlay.set_enabled(enabled)
        self.emit("overlay_changed", {"enabled": value})
        return {"enabled": value}

    def _on_state_change(self, state, current: str, next_step: str) -> None:
        with self._lock:
            self._current_step = current
            self._next_step = next_step
        self.emit(
            "flow_state",
            {"state": getattr(state, "name", str(state)), "current_step": current, "next_step": next_step},
        )

    def _log(self, level: str, message: str) -> None:
        self.emit(
            "log_entry",
            {
                "level": str(level).upper(),
                "message": message,
                "timestamp": datetime.now().isoformat(timespec="milliseconds"),
            },
        )

    def _set_error(self, code: str, error: Exception, generation: int | None = None) -> None:
        with self._lock:
            if generation is not None and generation != self._generation:
                return
            self._schedule_cancel.set()
            self._deadline_cancel.set()
            self._status = "error"
            self._scheduled_for = None
            self._schedule_thread = None
            self._deadline_thread = None
            self._error = {"code": code, "message": str(error)}
        self._clear_persisted_schedule()
        self.emit("backend_error", self._error)
        self._emit_state()

    def _persist_schedule(self, options: dict[str, Any], loop: bool) -> None:
        path = self._schedule_store_path
        if not path:
            return
        payload = {
            "version": 1,
            "loop": bool(loop),
            "options": {key: value for key, value in options.items() if key != "confirmation_token"},
            "saved_at": datetime.now().isoformat(timespec="seconds"),
        }
        try:
            with self._persistence_lock:
                path.parent.mkdir(parents=True, exist_ok=True)
                temporary = path.with_suffix(path.suffix + ".tmp")
                with temporary.open("w", encoding="utf-8") as stream:
                    json.dump(payload, stream, ensure_ascii=False, indent=2)
                os.replace(temporary, path)
        except (OSError, TypeError, ValueError) as exc:
            self._log("WARN", f"保存预约任务失败，任务仅在本次运行中有效: {exc}")

    def _clear_persisted_schedule(self) -> None:
        path = self._schedule_store_path
        if not path:
            return
        with self._persistence_lock:
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            except OSError as exc:
                self._log("WARN", f"清理预约任务文件失败: {exc}")

    def restore_pending_schedule(self) -> dict[str, Any]:
        path = self._schedule_store_path
        if not path or not path.exists():
            return self.snapshot()
        try:
            with self._persistence_lock:
                with path.open("r", encoding="utf-8") as stream:
                    payload = json.load(stream)
            options = payload.get("options") if isinstance(payload, dict) else None
            loop = bool(payload.get("loop")) if isinstance(payload, dict) else False
            if not isinstance(options, dict) or options.get("schedule_mode") != "scheduled":
                raise ValueError("invalid_persisted_schedule")
            return self._start(
                options,
                loop,
                require_confirmation=False,
                allow_past_schedule=True,
            )
        except Exception as exc:
            self._clear_persisted_schedule()
            self._set_error("schedule_restore_failed", exc)
            return self.snapshot()

    def _emit_state(self) -> None:
        self.emit("state_snapshot", self.snapshot())

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            power = float(self._power.get_current_power() or 0)
            energy = float(self._power.get_total_energy() or 0)
            average = float(self._power.get_average_power() or 0)
            return {
                "status": self._status,
                "running": self.running,
                "paused": self._status == "paused",
                "mode": self._mode,
                "current_step": self._current_step,
                "next_step": self._next_step,
                "scheduled_for": self._scheduled_for,
                "started_at": self._started_at,
                "power": power,
                "energy": energy,
                "average_power": average,
                "degraded_power": bool(self._power.is_degraded()),
                "overlay_enabled": self.overlay.enabled,
                "hotkey_registered": self.hotkey.registered,
                "error": self._error,
            }

    def health(self) -> dict[str, Any]:
        return {
            "backend": True,
            "power_monitor": bool(self._power.is_available()),
            "power_monitor_degraded": bool(self._power.is_degraded()),
            "f8_hotkey": self.hotkey.registered,
            "overlay_available": bool(self.overlay.executable) or not getattr(__import__("sys"), "frozen", False),
            "mode": "bundled",
        }

    def _cleanup_resources(self, resources) -> None:
        if not resources:
            return
        clicker, keyboard, mouse = resources
        try:
            clicker.use_driver = False
            clicker.driver = None
            if getattr(clicker, "camera", None):
                clicker.camera.stop()
            clicker.camera = None
        except Exception:
            pass
        for resource in (keyboard, mouse):
            try:
                resource.destroy()
            except Exception:
                pass

    def close(self) -> None:
        with self._lock:
            threads = (self._schedule_thread, self._deadline_thread, self._thread)
        self.stop()
        for thread in threads:
            if thread and thread is not threading.current_thread():
                thread.join(timeout=2)
        self.overlay.close()
        self.hotkey.stop()
        self._power.stop()
