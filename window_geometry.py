"""读取《守望先锋》窗口客户区的实时几何信息。"""

from __future__ import annotations

from dataclasses import dataclass

import win32gui


WINDOW_TITLE = "守望先锋"


@dataclass(frozen=True)
class WindowGeometry:
    """窗口客户区的物理屏幕坐标与尺寸。"""

    hwnd: int
    x: int
    y: int
    width: int
    height: int

    @property
    def center(self) -> tuple[int, int]:
        return (self.x + self.width // 2, self.y + self.height // 2)


def find_game_window(title: str = WINDOW_TITLE) -> int | None:
    """查找标题包含指定文本的可见游戏窗口。"""
    matches: list[int] = []

    def enum_callback(hwnd: int, _unused: object) -> bool:
        if win32gui.IsWindowVisible(hwnd) and title.lower() in win32gui.GetWindowText(hwnd).lower():
            matches.append(hwnd)
        return True

    win32gui.EnumWindows(enum_callback, None)
    return matches[0] if matches else None


def get_client_geometry(hwnd: int | None) -> WindowGeometry | None:
    """返回指定窗口客户区的实时物理坐标；窗口无效或最小化时返回 None。"""
    if not hwnd or not win32gui.IsWindow(hwnd):
        return None
    try:
        _, _, width, height = win32gui.GetClientRect(hwnd)
        if width <= 0 or height <= 0:
            return None
        x, y = win32gui.ClientToScreen(hwnd, (0, 0))
        return WindowGeometry(hwnd=hwnd, x=x, y=y, width=width, height=height)
    except Exception:
        return None


def get_game_client_geometry() -> WindowGeometry | None:
    """查找《守望先锋》并返回其当前客户区几何信息。"""
    return get_client_geometry(find_game_window())
