from __future__ import annotations

import json
import os
import threading
from copy import deepcopy
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 2
DEFAULTS: dict[str, Any] = {
    "schema_version": SCHEMA_VERSION,
    "overlay_enabled": False,
    "mouse_speed": 500,
    "auto_shutdown": "none",
    "unlimited_mode": False,
    "schedule_mode": "immediate",
    "start_at": "",
    "end_at": "",
    "duration_seconds": 3600,
    "selected_heroes": ["D.Va"],
    "hero_ratios": {"D.Va": 100},
    "tariff_tier": 1,
    "custom_tariff": "0.52",
}

_SHUTDOWN_POLICIES = {"none", "stop_only", "shutdown", "both"}
_SCHEDULE_MODES = {"immediate", "scheduled"}


def sanitize_utf8_text(value: str) -> str:
    """Remove isolated UTF-16 surrogate code points while preserving valid text."""
    return "".join(character for character in value if not 0xD800 <= ord(character) <= 0xDFFF)


def is_utf8_text(value: str) -> bool:
    """Return whether text can be persisted in a UTF-8 JSON file."""
    return sanitize_utf8_text(value) == value


def normalize_ratios(selected: list[str], raw: Any) -> dict[str, int]:
    names = list(dict.fromkeys(name for name in selected if isinstance(name, str) and name))
    if not names:
        return {}
    if len(names) == 1:
        return {names[0]: 100}
    source = raw if isinstance(raw, dict) else {}
    weights = {name: max(0.0, float(source.get(name, 1) or 0)) for name in names}
    total = sum(weights.values())
    if total <= 0:
        weights = {name: 1.0 for name in names}
        total = float(len(names))
    result = {name: int(weights[name] * 100 / total) for name in names}
    remainder = 100 - sum(result.values())
    for name in names[:remainder]:
        result[name] += 1
    return result


def validate_config(value: Any) -> dict[str, Any]:
    incoming = value if isinstance(value, dict) else {}
    result = deepcopy(DEFAULTS)
    result.update(incoming)
    result["schema_version"] = SCHEMA_VERSION
    result["overlay_enabled"] = bool(result.get("overlay_enabled"))
    result["unlimited_mode"] = bool(result.get("unlimited_mode"))
    result["mouse_speed"] = max(100, min(2000, int(result.get("mouse_speed", 500))))
    result["duration_seconds"] = max(60, min(7 * 24 * 3600, int(result.get("duration_seconds", 3600))))
    result["auto_shutdown"] = (
        result.get("auto_shutdown") if result.get("auto_shutdown") in _SHUTDOWN_POLICIES else "none"
    )
    result["schedule_mode"] = (
        result.get("schedule_mode") if result.get("schedule_mode") in _SCHEDULE_MODES else "immediate"
    )
    result["start_at"] = str(result.get("start_at") or "")
    result["end_at"] = str(result.get("end_at") or "")
    selected = result.get("selected_heroes")
    result["selected_heroes"] = (
        list(
            dict.fromkeys(
                clean
                for item in selected
                if isinstance(item, str)
                for clean in [sanitize_utf8_text(item)]
                if clean
            )
        )
        if isinstance(selected, list)
        else []
    )
    raw_ratios = result.get("hero_ratios")
    clean_ratios = (
        {
            sanitize_utf8_text(name): ratio
            for name, ratio in raw_ratios.items()
            if isinstance(name, str) and sanitize_utf8_text(name)
        }
        if isinstance(raw_ratios, dict)
        else raw_ratios
    )
    result["hero_ratios"] = normalize_ratios(result["selected_heroes"], clean_ratios)
    result["tariff_tier"] = max(1, min(3, int(result.get("tariff_tier", 1))))
    try:
        price = float(result.get("custom_tariff", "0.52"))
        result["custom_tariff"] = f"{max(0.01, price):g}"
    except (TypeError, ValueError):
        result["custom_tariff"] = DEFAULTS["custom_tariff"]
    return result


class ConfigStore:
    def __init__(self, data_dir: str | os.PathLike[str], legacy_path: str | os.PathLike[str] | None = None):
        self.data_dir = Path(data_dir)
        self.path = self.data_dir / "config.json"
        self.legacy_path = Path(legacy_path) if legacy_path else None
        self._lock = threading.RLock()

    def _read(self, path: Path) -> dict[str, Any]:
        try:
            with path.open("r", encoding="utf-8") as stream:
                value = json.load(stream)
            return value if isinstance(value, dict) else {}
        except (OSError, ValueError):
            return {}

    def load(self) -> dict[str, Any]:
        with self._lock:
            source = self.path if self.path.exists() else self.legacy_path
            return validate_config(self._read(source) if source and source.exists() else {})

    def save(self, value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise ValueError("config_must_be_an_object")
        with self._lock:
            merged = self.load()
            merged.update(value)
            validated = validate_config(merged)
            self.data_dir.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".json.tmp")
            with tmp.open("w", encoding="utf-8") as stream:
                json.dump(validated, stream, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
            return validated

    def reset(self) -> dict[str, Any]:
        return self.save(deepcopy(DEFAULTS))
