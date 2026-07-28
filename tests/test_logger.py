from __future__ import annotations

import logger


class InvalidConsole:
    encoding = "utf-8"
    buffer = None

    def write(self, _value: str) -> int:
        raise OSError(22, "Invalid argument")

    def flush(self) -> None:
        raise OSError(22, "Invalid argument")


def test_console_failure_does_not_break_logging(monkeypatch) -> None:
    monkeypatch.setattr(logger.sys, "stderr", InvalidConsole())

    logger.Logger._safe_console_write("打包版后台日志")

