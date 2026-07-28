import subprocess
from unittest.mock import Mock, patch

from backend.ui_services.overlay_service import (
    OVERLAY_CLOSE_COMMAND,
    OverlayService,
)


def test_close_sends_shutdown_command_and_waits_for_clean_exit():
    service = OverlayService(port=23456)
    process = Mock(pid=1234)
    service._process = process
    service._socket = Mock()
    service.enabled = True

    service.close()

    assert service._socket.sendto.call_count == 3
    service._socket.sendto.assert_called_with(
        OVERLAY_CLOSE_COMMAND.encode("utf-8"),
        ("127.0.0.1", 23456),
    )
    process.wait.assert_called_once_with(timeout=2)
    assert service._process is None
    assert service.enabled is False


def test_close_terminates_process_tree_when_overlay_does_not_exit():
    service = OverlayService(port=23457)
    process = Mock(pid=5678)
    process.wait.side_effect = subprocess.TimeoutExpired("overlay", 2)
    service._process = process
    service._socket = Mock()

    with patch.object(service, "_terminate_process_tree") as terminate_tree:
        service.close()

    terminate_tree.assert_called_once_with(process)
