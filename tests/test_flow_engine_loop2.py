import flow_engine
from driver_click import VK_A, VK_D, VK_E, VK_F10
from types import SimpleNamespace
from window_geometry import WindowGeometry


class _Mouse:
    available = True

    def __init__(self, action_order=None):
        self.moves = []
        self.action_order = action_order

    def move_relative(self, dx, dy, duration, speed, check_callback=None):
        if self.action_order is not None:
            self.action_order.append("move")
        self.moves.append((dx, dy, duration, speed))
        return True


class _Keyboard:
    def __init__(self):
        self.events = []
        self.stop = lambda: None

    def key_down(self, key):
        self.events.append(("down", key))

    def key_up(self, key):
        self.events.append(("up", key))

    def press_key(self, key, duration_s):
        self.events.append(("press", key, duration_s))
        if key == VK_E:
            self.stop()


def test_loop2_moves_both_directions_and_holds_d_then_a_equally(monkeypatch):
    now = [0.0]
    monkeypatch.setattr(flow_engine.time, "time", lambda: now[0])
    monkeypatch.setattr(flow_engine.time, "sleep", lambda seconds: now.__setitem__(0, now[0] + seconds))

    mouse = _Mouse()
    keyboard = _Keyboard()
    engine = flow_engine.FlowEngine(
        clicker=object(),
        keyboard=keyboard,
        mouse_driver=mouse,
        hero_selector=object(),
        options={"move_duration": 0.1, "mouse_speed": 400},
    )
    keyboard.stop = lambda: setattr(engine, "_running", False)
    monkeypatch.setattr(engine, "_click_game_center_to_focus", lambda: True)
    monkeypatch.setattr(engine, "_check_f10", lambda: False)
    monkeypatch.setattr(engine, "_click_current_position", lambda: None)

    assert engine._handle_loop2() is False

    assert mouse.moves[:2] == [
        (10, 0, 0.1, 400),
        (-10, 0, 0.1, 400),
    ]
    assert keyboard.events[:4] == [
        ("down", VK_D),
        ("up", VK_D),
        ("down", VK_A),
        ("up", VK_A),
    ]


def test_loop2_clicks_game_center_before_mouse_move(monkeypatch):
    now = [0.0]
    monkeypatch.setattr(flow_engine.time, "time", lambda: now[0])
    monkeypatch.setattr(flow_engine.time, "sleep", lambda seconds: now.__setitem__(0, now[0] + seconds))

    action_order = []
    mouse = _Mouse(action_order)
    keyboard = _Keyboard()
    engine = flow_engine.FlowEngine(
        clicker=object(),
        keyboard=keyboard,
        mouse_driver=mouse,
        hero_selector=object(),
        options={"move_duration": 0.1, "mouse_speed": 400},
    )
    keyboard.stop = lambda: setattr(engine, "_running", False)
    monkeypatch.setattr(
        engine,
        "_click_game_center_to_focus",
        lambda: action_order.append("focus_click") or True,
    )
    monkeypatch.setattr(engine, "_check_f10", lambda: False)
    monkeypatch.setattr(engine, "_click_current_position", lambda: None)

    assert engine._handle_loop2() is False
    assert action_order[:2] == ["focus_click", "move"]


def test_center_focus_click_moves_to_window_center_and_clicks_once(monkeypatch):
    class _User32:
        def __init__(self):
            self.calls = []

        def SetCursorPos(self, x, y):
            self.calls.append(("move", x, y))

        def mouse_event(self, flags, dx, dy, data, extra):
            self.calls.append(("mouse", flags))

        def GetForegroundWindow(self):
            return 42

    user32 = _User32()
    mouse = _Mouse()
    engine = flow_engine.FlowEngine(
        clicker=SimpleNamespace(hwnd=42),
        keyboard=_Keyboard(),
        mouse_driver=mouse,
        hero_selector=object(),
    )
    monkeypatch.setattr(
        flow_engine,
        "get_client_geometry",
        lambda hwnd: WindowGeometry(42, 100, 200, 1600, 900),
    )
    monkeypatch.setattr(engine, "_activate_window", lambda: True)
    monkeypatch.setattr(flow_engine.ctypes, "windll", SimpleNamespace(user32=user32))
    monkeypatch.setattr(flow_engine.time, "sleep", lambda seconds: None)

    assert engine._click_game_center_to_focus() is True
    assert user32.calls == [
        ("move", 900, 650),
        ("mouse", 0x0002),
        ("mouse", 0x0004),
    ]


def test_recognition_preparation_activates_then_refreshes_capture(monkeypatch):
    events = []

    class _Clicker:
        hwnd = 42

        @staticmethod
        def refresh_capture_region(force=False):
            events.append(("refresh", force))
            return True

    user32 = SimpleNamespace(GetForegroundWindow=lambda: 7)
    engine = flow_engine.FlowEngine(
        clicker=_Clicker(),
        keyboard=_Keyboard(),
        mouse_driver=_Mouse(),
        hero_selector=object(),
    )
    monkeypatch.setattr(flow_engine.win32gui, "IsWindow", lambda hwnd: hwnd == 42)
    monkeypatch.setattr(
        flow_engine.ctypes,
        "windll",
        SimpleNamespace(user32=user32),
    )
    monkeypatch.setattr(
        engine,
        "_activate_window",
        lambda: events.append(("activate",)) or True,
    )
    monkeypatch.setattr(
        engine,
        "_sleep_interruptible",
        lambda seconds: events.append(("settle", seconds)) or True,
    )

    assert engine._prepare_recognition_window() is True
    assert events == [
        ("activate",),
        ("settle", flow_engine.config.RECOGNITION_FOCUS_SETTLE_TIME),
        ("refresh", True),
    ]


def test_send_f10_reports_driver_rejection(monkeypatch):
    class _RejectingKeyboard:
        available = True

        def __init__(self):
            self.calls = []

        def press_key(self, key, duration_s):
            self.calls.append((key, duration_s))
            return False

    keyboard = _RejectingKeyboard()
    engine = flow_engine.FlowEngine(
        clicker=object(),
        keyboard=keyboard,
        mouse_driver=_Mouse(),
        hero_selector=object(),
    )

    assert engine._send_f10() is False
    assert keyboard.calls == [
        (VK_F10, flow_engine.config.REQUEUE_KEY_HOLD_DURATION),
    ]


def test_requeue_retries_f10_until_visual_confirmation(monkeypatch):
    class _Clicker:
        def __init__(self):
            self.clicks = []

        def click(self, x, y):
            self.clicks.append((x, y))

    clicker = _Clicker()
    engine = flow_engine.FlowEngine(
        clicker=clicker,
        keyboard=_Keyboard(),
        mouse_driver=_Mouse(),
        hero_selector=object(),
    )
    engine._loop_end_match = (120, 80, 0.95)
    send_results = []
    visual_results = iter([False, True])

    monkeypatch.setattr(flow_engine.config, "REQUEUE_KEY_ATTEMPTS", 3)
    monkeypatch.setattr(engine, "_activate_window", lambda: True)
    monkeypatch.setattr(
        engine,
        "_send_f10",
        lambda: send_results.append("f10") or True,
    )
    monkeypatch.setattr(
        engine,
        "_wait_for_requeue_response",
        lambda timeout=None: next(visual_results),
    )
    monkeypatch.setattr(engine, "_sleep_interruptible", lambda seconds: True)

    assert engine._requeue_with_verification() is True
    assert send_results == ["f10", "f10"]
    assert clicker.clicks == []


def test_requeue_clicks_recognized_button_after_keyboard_retries(monkeypatch):
    class _Clicker:
        def __init__(self):
            self.clicks = []

        def click(self, x, y):
            self.clicks.append((x, y))

    clicker = _Clicker()
    engine = flow_engine.FlowEngine(
        clicker=clicker,
        keyboard=_Keyboard(),
        mouse_driver=_Mouse(),
        hero_selector=object(),
    )
    engine._loop_end_match = (150, 90, 0.91)
    visual_results = iter([False, False, True])

    monkeypatch.setattr(flow_engine.config, "REQUEUE_KEY_ATTEMPTS", 2)
    monkeypatch.setattr(engine, "_activate_window", lambda: True)
    monkeypatch.setattr(engine, "_send_f10", lambda: True)
    monkeypatch.setattr(
        engine,
        "_wait_for_requeue_response",
        lambda timeout=None: next(visual_results),
    )
    monkeypatch.setattr(engine, "_sleep_interruptible", lambda seconds: True)

    assert engine._requeue_with_verification() is True
    assert clicker.clicks == [(150, 90)]


def test_requeue_response_requires_two_consecutive_missing_frames(monkeypatch):
    class _Clicker:
        def __init__(self):
            self.results = iter([
                None,
                (100, 60, 0.94),
                None,
                None,
            ])
            self.check_count = 0

        def check_target(self, image_name):
            assert image_name == flow_engine.LOOP_END_IMAGE
            self.check_count += 1
            return next(self.results)

    now = [0.0]
    clicker = _Clicker()
    engine = flow_engine.FlowEngine(
        clicker=clicker,
        keyboard=_Keyboard(),
        mouse_driver=_Mouse(),
        hero_selector=object(),
    )

    monkeypatch.setattr(flow_engine.time, "time", lambda: now[0])
    monkeypatch.setattr(
        engine,
        "_sleep_interruptible",
        lambda seconds: now.__setitem__(0, now[0] + seconds) or True,
    )

    assert engine._wait_for_requeue_response(timeout=1.0) is True
    assert clicker.check_count == 4
