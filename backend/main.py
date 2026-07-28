from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

# Support both repository execution and a PyInstaller entrypoint.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    _PROTOCOL_STREAM = os.fdopen(os.dup(sys.stdout.fileno()), "wb", buffering=0)
except (AttributeError, OSError, ValueError):
    _PROTOCOL_STREAM = None


def write_protocol(value: dict[str, Any]) -> None:
    line = (
        json.dumps(value, ensure_ascii=True, separators=(",", ":")) + "\n"
    ).encode("ascii")
    if _PROTOCOL_STREAM is not None:
        _PROTOCOL_STREAM.write(line)
        return
    sys.stdout.buffer.write(line)
    sys.stdout.buffer.flush()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="HeroFlow Desktop automation sidecar")
    parser.add_argument("--data-dir", default=str(ROOT / ".heroflow"))
    parser.add_argument("--legacy-config", default=str(ROOT / "config.json"))
    parser.add_argument("--heroes-dir", default="")
    parser.add_argument("--overlay-bin", default="")
    return parser.parse_args()


def emit_startup(progress: int, phase: str, message: str) -> None:
    write_protocol(
        {
            "type": "event",
            "version": 2,
            "event": "startup_progress",
            "payload": {
                "progress": progress,
                "phase": phase,
                "message": message,
            },
            "timestamp": datetime.now().isoformat(timespec="milliseconds"),
        }
    )


def main() -> None:
    args = parse_args()
    emit_startup(10, "environment", "正在准备本地运行环境")
    from backend.ipc import JsonRpcServer

    emit_startup(48, "core", "正在加载自动化核心与输入驱动")
    server = JsonRpcServer(
        data_dir=os.path.abspath(args.data_dir),
        legacy_config=os.path.abspath(args.legacy_config) if args.legacy_config else None,
        heroes_dir=os.path.abspath(args.heroes_dir) if args.heroes_dir else None,
        overlay_executable=os.path.abspath(args.overlay_bin) if args.overlay_bin else None,
        protocol_writer=write_protocol,
    )
    emit_startup(82, "services", "正在初始化配置、热键与监控服务")
    server.run()


if __name__ == "__main__":
    main()
