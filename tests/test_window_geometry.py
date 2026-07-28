import window_geometry


class _Win32Gui:
    @staticmethod
    def IsWindow(hwnd):
        return hwnd == 42

    @staticmethod
    def GetClientRect(hwnd):
        assert hwnd == 42
        return (0, 0, 1920, 1080)

    @staticmethod
    def ClientToScreen(hwnd, point):
        assert (hwnd, point) == (42, (0, 0))
        return (100, 200)


def test_get_client_geometry_and_center(monkeypatch):
    monkeypatch.setattr(window_geometry, "win32gui", _Win32Gui)

    geometry = window_geometry.get_client_geometry(42)

    assert geometry == window_geometry.WindowGeometry(42, 100, 200, 1920, 1080)
    assert geometry.center == (1060, 740)


def test_get_client_geometry_rejects_invalid_window(monkeypatch):
    monkeypatch.setattr(window_geometry, "win32gui", _Win32Gui)

    assert window_geometry.get_client_geometry(None) is None
    assert window_geometry.get_client_geometry(99) is None
