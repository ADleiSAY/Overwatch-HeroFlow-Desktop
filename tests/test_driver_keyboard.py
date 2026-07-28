from types import SimpleNamespace

import driver_click


def test_driver_keyboard_press_requires_down_and_up_to_succeed(monkeypatch):
    responses = iter([1, 0])
    sent_states = []

    class _Lib:
        INTERCEPTION_KEY_DOWN = 0
        INTERCEPTION_KEY_UP = 1

        @staticmethod
        def interception_send(context, device, stroke, count):
            sent_states.append(stroke.state)
            return next(responses)

    user32 = SimpleNamespace(MapVirtualKeyW=lambda vk_code, mode: 0x44)
    monkeypatch.setattr(driver_click, "lib", _Lib())
    monkeypatch.setattr(
        driver_click.ctypes,
        "windll",
        SimpleNamespace(user32=user32),
    )
    monkeypatch.setattr(driver_click.time, "sleep", lambda seconds: None)

    keyboard = driver_click.DriverKeyboard()
    keyboard.context = object()
    keyboard.keyboard_device = 1
    keyboard.kstroke = SimpleNamespace(code=0, state=0, information=0)
    keyboard.available = True

    assert keyboard.press_key(driver_click.VK_F10, duration_s=0.18) is False
    assert sent_states == [_Lib.INTERCEPTION_KEY_DOWN, _Lib.INTERCEPTION_KEY_UP]


def test_driver_keyboard_press_returns_true_when_both_events_are_accepted(monkeypatch):
    class _Lib:
        INTERCEPTION_KEY_DOWN = 0
        INTERCEPTION_KEY_UP = 1

        @staticmethod
        def interception_send(context, device, stroke, count):
            return 1

    user32 = SimpleNamespace(MapVirtualKeyW=lambda vk_code, mode: 0x44)
    monkeypatch.setattr(driver_click, "lib", _Lib())
    monkeypatch.setattr(
        driver_click.ctypes,
        "windll",
        SimpleNamespace(user32=user32),
    )
    monkeypatch.setattr(driver_click.time, "sleep", lambda seconds: None)

    keyboard = driver_click.DriverKeyboard()
    keyboard.context = object()
    keyboard.keyboard_device = 1
    keyboard.kstroke = SimpleNamespace(code=0, state=0, information=0)
    keyboard.available = True

    assert keyboard.press_key(driver_click.VK_F10, duration_s=0.18) is True
