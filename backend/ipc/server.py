from __future__ import annotations

import json
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from backend.config import ConfigStore
from backend.core import AutomationService
from backend.drivers import install_driver, is_driver_installed, is_driver_loaded
from backend.monitoring import get_tariff_with_cache, lookup_tariff


PROTOCOL_VERSION = 2


def repair_hero_names(saved: dict[str, Any], canonical_names: list[str]) -> dict[str, Any]:
    aliases = {name: name for name in canonical_names}
    for name in canonical_names:
        # 兼容旧资源中意外带有首尾空格的英雄文件名。
        aliases.setdefault(name.strip(), name)
        alias = name
        for _ in range(4):
            try:
                alias = alias.encode("utf-8").decode("gbk", errors="ignore")
            except (LookupError, UnicodeError):
                break
            if not alias or alias in aliases:
                break
            aliases[alias] = name
    def resolve(name: Any) -> str | None:
        if not isinstance(name, str):
            return None
        return aliases.get(name) or aliases.get(name.strip())

    selected = [
        resolved
        for name in saved.get("selected_heroes", [])
        if (resolved := resolve(name)) is not None
    ]
    raw_ratios = saved.get("hero_ratios")
    ratios = (
        {
            resolved: value
            for name, value in raw_ratios.items()
            if (resolved := resolve(name)) is not None
        }
        if isinstance(raw_ratios, dict)
        else raw_ratios
    )
    return {**saved, "selected_heroes": selected, "hero_ratios": ratios}


class JsonRpcServer:
    def __init__(
        self,
        data_dir: str,
        legacy_config: str | None = None,
        heroes_dir: str | None = None,
        overlay_executable: str | None = None,
        protocol_writer: Callable[[dict[str, Any]], None] | None = None,
    ):
        self.config = ConfigStore(data_dir, legacy_config)
        self.heroes_dir = Path(heroes_dir) if heroes_dir else None
        self._write_lock = threading.Lock()
        self._protocol_writer = protocol_writer
        self._shutdown = False
        self.service = AutomationService(
            self.emit,
            overlay_executable,
            schedule_store_path=Path(data_dir) / "pending_schedule.json",
        )
        saved = self._repair_saved_hero_names(self.config.load())
        if saved.get("overlay_enabled"):
            try:
                self.service.set_overlay(True)
            except Exception as exc:
                self.emit("backend_error", {"code": "overlay_start_failed", "message": str(exc)})
        self.service.restore_pending_schedule()

    def emit(self, event: str, payload: dict[str, Any]) -> None:
        self._send(
            {
                "type": "event",
                "version": PROTOCOL_VERSION,
                "event": event,
                "payload": payload,
                "timestamp": datetime.now().isoformat(timespec="milliseconds"),
            }
        )

    def _send(self, value: dict[str, Any]) -> None:
        with self._write_lock:
            if self._protocol_writer:
                self._protocol_writer(value)
                return
            # The bundled Windows sidecar may inherit a legacy console code page.
            # ASCII-only JSON keeps the pipe transport encoding-independent.
            sys.stdout.write(json.dumps(value, ensure_ascii=True, separators=(",", ":")) + "\n")
            sys.stdout.flush()

    def _repair_saved_hero_names(self, saved: dict[str, Any]) -> dict[str, Any]:
        canonical_names = [hero["name"] for hero in self.heroes()]
        repaired = repair_hero_names(saved, canonical_names)
        if repaired == saved:
            return saved
        return self.config.save({
            "selected_heroes": repaired["selected_heroes"],
            "hero_ratios": repaired["hero_ratios"],
        })

    def heroes(self) -> list[dict[str, str]]:
        directory = self.heroes_dir
        if not directory or not directory.exists():
            root = Path(__file__).resolve().parents[2]
            pic_root = root / "pic"
            directory = (
                next((item for item in pic_root.iterdir() if item.is_dir() and any(item.glob("*.png"))), None)
                if pic_root.exists()
                else None
            )
        if not directory:
            return []
        try:
            names = sorted(item.stem for item in directory.glob("*.png"))
        except OSError:
            names = []
        categories: dict[str, str] = {}
        try:
            import config as legacy_config

            for category, values in legacy_config.HERO_CATEGORY_TABLE.items():
                for name in values:
                    categories[str(name).strip()] = str(category)
        except Exception:
            pass
        return [
            {
                "name": name,
                "display_name": name.strip(),
                "category": categories.get(name.strip(), "其他"),
                "image": f"/heroes/{name}.png",
            }
            for name in names
        ]

    def bootstrap(self) -> dict[str, Any]:
        return {
            "protocol_version": PROTOCOL_VERSION,
            "app_name": "HeroFlow Desktop",
            "config": self.config.load(),
            "heroes": self.heroes(),
            "state": self.service.snapshot(),
            "health": self._health(),
        }

    def _health(self) -> dict[str, Any]:
        value = self.service.health()
        value["driver_installed"] = bool(is_driver_installed())
        value["driver_loaded"] = bool(is_driver_loaded())
        return value

    def call(self, method: str, params: Any) -> Any:
        values = params if isinstance(params, dict) else {}
        if method in {"bootstrap", "get_bootstrap"}:
            return self.bootstrap()
        if method == "get_config":
            return self.config.load()
        if method == "save_config":
            saved = self.config.save(values.get("config", values))
            if "overlay_enabled" in values.get("config", values):
                self.service.set_overlay(bool(saved["overlay_enabled"]))
            return saved
        if method == "reset_config":
            return self.config.reset()
        if method == "get_heroes":
            return self.heroes()
        if method == "get_app_state":
            return self.service.snapshot()
        if method == "start_flow":
            return self.service.start(values, False)
        if method in {"start_loop", "start_loop2"}:
            return self.service.start(values, True)
        if method == "pause_flow":
            return self.service.pause()
        if method == "resume_flow":
            return self.service.resume()
        if method in {"stop_flow", "stop_loop", "cancel_schedule"}:
            return self.service.stop()
        if method == "confirm_dangerous_action":
            return self.service.confirm_dangerous_action(str(values.get("policy") or ""))
        if method in {"get_health", "check_dependencies"}:
            return self._health()
        if method == "check_driver":
            return {"installed": bool(is_driver_installed()), "loaded": bool(is_driver_loaded())}
        if method == "install_driver":
            result = install_driver(
                lambda progress, phase, message: self.emit(
                    "driver_install_progress",
                    {
                        "progress": max(0, min(100, int(progress))),
                        "phase": str(phase),
                        "message": str(message),
                    },
                )
            )
            ok, message = result if isinstance(result, tuple) else (bool(result), "")
            payload = {
                "ok": bool(ok),
                "message": str(message),
                "requires_restart": bool(ok) and not bool(is_driver_loaded()),
            }
            self.emit("driver_install_finished", payload)
            return payload
        if method in {"get_tariff", "refresh_tariff"}:
            tier = max(1, min(3, int(values.get("tier", 1))))
            province, price, source = get_tariff_with_cache(tier)
            return {"province": province, "price": price, "source": source, "tier": tier}
        if method == "lookup_tariff":
            tier = max(1, min(3, int(values.get("tier", 1))))
            return {"price": lookup_tariff(str(values.get("province") or ""), tier)}
        if method == "set_tariff":
            return self.config.save({"custom_tariff": str(values.get("price", "0.52"))})
        if method == "toggle_overlay":
            result = self.service.set_overlay(bool(values.get("enabled", False)))
            self.config.save({"overlay_enabled": result["enabled"]})
            return result
        if method == "shutdown_app":
            self._shutdown = True
            self.service.close()
            return {"ok": True}
        raise KeyError(f"unknown_method:{method}")

    def run(self) -> None:
        self.emit("backend_ready", {"protocol_version": PROTOCOL_VERSION, "app_name": "HeroFlow Desktop"})
        try:
            for line in sys.stdin:
                request: dict[str, Any] | None = None
                try:
                    request = json.loads(line)
                    if not isinstance(request, dict):
                        raise ValueError("request_must_be_an_object")
                    result = self.call(str(request.get("method") or ""), request.get("params"))
                    self._send(
                        {
                            "type": "response",
                            "version": PROTOCOL_VERSION,
                            "id": request.get("id"),
                            "ok": True,
                            "result": result,
                        }
                    )
                    if self._shutdown:
                        break
                except Exception as exc:
                    self._send(
                        {
                            "type": "response",
                            "version": PROTOCOL_VERSION,
                            "id": request.get("id") if request else None,
                            "ok": False,
                            "error": {"code": type(exc).__name__, "message": str(exc)},
                        }
                    )
        finally:
            self.service.close()
