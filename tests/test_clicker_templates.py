from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

import config
from clicker import Clicker


def test_named_template_loads_and_is_cached() -> None:
    clicker = Clicker()

    assert clicker.load_template_by_name("开始.png") is True
    assert clicker.template_w > 0
    assert clicker.template_h > 0
    cached = clicker._templates["开始.png"]

    assert clicker.load_template_by_name("开始.png") is True
    assert clicker._templates["开始.png"] is cached


def test_missing_template_returns_false_without_console_output(monkeypatch) -> None:
    clicker = Clicker()
    messages: list[str] = []
    monkeypatch.setattr("clicker.logger.error", messages.append)

    assert clicker.load_template_by_name("不存在.png") is False
    assert messages and "模板文件不存在" in messages[0]


def test_multiscale_matching_uses_current_client_resolution() -> None:
    clicker = Clicker()
    assert clicker.load_template_by_name("开始.png") is True

    scale = 1.25
    scaled = cv2.resize(
        clicker.template,
        None,
        fx=scale,
        fy=scale,
        interpolation=cv2.INTER_LINEAR,
    )
    height, width = scaled.shape[:2]
    screen = np.zeros((720, 1280, 3), dtype=np.uint8)
    screen[180:180 + height, 320:320 + width] = scaled

    result = clicker.find_target(screen, threshold=0.9)

    assert result is not None
    center_x, center_y, matched_w, matched_h, confidence = result
    assert (matched_w, matched_h) == (width, height)
    assert (center_x, center_y) == (
        320 + round(width / 2),
        180 + round(height / 2),
    )
    assert confidence > 0.99
    assert abs(clicker.last_match_scale - scale) < 0.01


def test_match_diagnostics_keep_best_score_below_threshold() -> None:
    clicker = Clicker()
    assert clicker.load_template_by_name("开始.png") is True
    height, width = clicker.template.shape[:2]
    screen = np.zeros((576, 1024, 3), dtype=np.uint8)
    screen[100:100 + height, 200:200 + width] = clicker.template

    assert clicker.find_target(screen, threshold=1.1) is None
    assert clicker.last_match_confidence > 0.99
    assert clicker.last_match_location == (200, 100)


def test_capture_region_restarts_camera_after_window_move(monkeypatch) -> None:
    class _Camera:
        is_capturing = True

        def __init__(self):
            self.calls = []

        def stop(self):
            self.calls.append(("stop",))
            self.is_capturing = False

        def start(self, **kwargs):
            self.calls.append(("start", kwargs))
            self.is_capturing = True

    clicker = Clicker()
    clicker.hwnd = 42
    clicker.camera = _Camera()
    clicker._camera_region = (10, 20, 410, 320)
    monkeypatch.setattr(
        clicker,
        "get_client_rect_screen",
        lambda: (100, 200, 500, 500),
    )

    assert clicker.refresh_capture_region(force=True) is True
    assert clicker._camera_region == (100, 200, 500, 500)
    assert clicker.capture_origin == (100, 200)
    assert clicker.camera.calls == [
        ("stop",),
        (
            "start",
            {
                "region": (100, 200, 500, 500),
                "target_fps": 60,
                "video_mode": True,
            },
        ),
    ]


def test_every_configured_hero_has_a_canonical_template_name() -> None:
    hero_directory = Path(__file__).resolve().parents[1] / "pic" / "守望先锋所有英雄"
    file_names = {item.stem for item in hero_directory.glob("*.png")}
    configured = {
        hero
        for heroes in config.HERO_CATEGORY_TABLE.values()
        for hero in heroes
    }

    assert configured <= file_names
    assert all(name == name.strip() for name in file_names)
