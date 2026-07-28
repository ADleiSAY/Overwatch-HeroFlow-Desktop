import flow_engine


class _Keyboard:
    def __init__(self):
        self.combos = []

    def combo(self, keys):
        self.combos.append(tuple(keys))


def test_end_policy_matches_user_visible_choices(monkeypatch):
    monkeypatch.setattr(flow_engine.config, "SHUTDOWN_COUNTDOWN", 0)
    shutdown_calls = []
    monkeypatch.setattr(
        flow_engine.subprocess,
        "run",
        lambda args, check=False: shutdown_calls.append(tuple(args)),
    )

    expected = {
        "none": (False, False),
        "stop_only": (True, False),
        "shutdown": (False, True),
        "both": (True, True),
    }
    for policy, (closes_game, shuts_down_pc) in expected.items():
        keyboard = _Keyboard()
        calls_before = len(shutdown_calls)
        engine = flow_engine.FlowEngine(
            clicker=object(),
            keyboard=keyboard,
            mouse_driver=object(),
            hero_selector=object(),
            options={"auto_shutdown": policy},
        )

        engine._execute_shutdown()

        assert bool(keyboard.combos) is closes_game
        assert (len(shutdown_calls) > calls_before) is shuts_down_pc


def test_manual_stop_cancels_shutdown_but_timed_finish_does_not(monkeypatch):
    monkeypatch.setattr(flow_engine.config, "SHUTDOWN_COUNTDOWN", 1)
    shutdown_calls = []
    monkeypatch.setattr(flow_engine.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(
        flow_engine.subprocess,
        "run",
        lambda args, check=False: shutdown_calls.append(tuple(args)),
    )

    manual = flow_engine.FlowEngine(
        object(), _Keyboard(), object(), object(),
        options={"auto_shutdown": "shutdown"},
    )
    manual.stop()
    manual._execute_shutdown()

    timed = flow_engine.FlowEngine(
        object(), _Keyboard(), object(), object(),
        options={"auto_shutdown": "shutdown"},
    )
    timed.finish_due_to_timeout()
    timed._execute_shutdown()

    assert shutdown_calls == [("shutdown", "/s", "/t", "0")]
