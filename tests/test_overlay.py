from overlay import OverlayData, _get_endpoint, parse_overlay_message


def test_parse_overlay_message_with_full_payload():
    assert parse_overlay_message(
        "120 240 80 40|start.png|正在识别|点击开始|0.927"
    ) == OverlayData(
        x=120,
        y=240,
        width=80,
        height=40,
        image_name="start.png",
        step_name="正在识别",
        next_step="点击开始",
        confidence=0.927,
    )


def test_parse_overlay_message_supports_legacy_coordinates():
    assert parse_overlay_message("-20 30 50 60") == OverlayData(
        x=-20,
        y=30,
        width=50,
        height=60,
    )


def test_parse_overlay_message_rejects_invalid_payload():
    assert parse_overlay_message("") is None
    assert parse_overlay_message("10 20 30") is None
    assert parse_overlay_message("x 20 30 40") is None


def test_parse_overlay_message_sanitizes_dimensions_and_confidence():
    assert parse_overlay_message("1 2 -3 -4||||1.8") == OverlayData(
        x=1,
        y=2,
        width=0,
        height=0,
        confidence=1.0,
    )


def test_overlay_endpoint_defaults_and_custom_values():
    assert _get_endpoint(["overlay.py"]) == ("127.0.0.1", 12345)
    assert _get_endpoint(["overlay.py", "123", "127.0.0.2", "23456"]) == (
        "127.0.0.2",
        23456,
    )
