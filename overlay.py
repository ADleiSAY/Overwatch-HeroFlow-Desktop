"""HeroFlow 的只读游戏覆盖层。

覆盖层通过 UDP 接收识别结果，只负责绘制，不参与任何鼠标或键盘交互。
消息格式：
    x y width height|image_name|step_name|next_step|confidence
"""

from __future__ import annotations

import ctypes
import logging
import os
import socket
import sys
import threading
from dataclasses import dataclass
from pathlib import Path

from PyQt5.QtCore import QRect, QRectF, Qt, QTimer
from PyQt5.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PyQt5.QtWidgets import QApplication, QWidget

from window_geometry import WindowGeometry, get_game_client_geometry


def _enable_dpi_awareness() -> None:
    """让窗口坐标与截图使用的物理像素坐标保持一致。"""
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except (AttributeError, OSError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass


_enable_dpi_awareness()


def _build_logger() -> logging.Logger:
    logger = logging.getLogger("heroflow.overlay")
    logger.setLevel(logging.INFO)
    if logger.handlers:
        return logger
    try:
        data_dir = Path(os.environ.get("HEROFLOW_DATA_DIR") or Path.cwd())
        log_dir = data_dir / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(log_dir / "overlay.log", encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        logger.addHandler(handler)
    except Exception:
        logger.addHandler(logging.NullHandler())
    return logger


overlay_logger = _build_logger()
OVERLAY_CLOSE_COMMAND = "__HEROFLOW_OVERLAY_CLOSE__"


@dataclass(frozen=True)
class OverlayData:
    x: int
    y: int
    width: int
    height: int
    image_name: str = ""
    step_name: str = ""
    next_step: str = ""
    confidence: float = 0.0


def parse_overlay_message(message: str) -> OverlayData | None:
    """解析 UDP 消息；无效或不完整的数据直接忽略。"""
    parts = message.strip().split("|")
    coordinates = parts[0].split() if parts else []
    if len(coordinates) < 4:
        return None

    try:
        x, y, width, height = (int(value) for value in coordinates[:4])
        confidence = float(parts[4]) if len(parts) > 4 and parts[4].strip() else 0.0
    except (TypeError, ValueError):
        return None

    return OverlayData(
        x=x,
        y=y,
        width=max(0, width),
        height=max(0, height),
        image_name=parts[1].strip() if len(parts) > 1 else "",
        step_name=parts[2].strip() if len(parts) > 2 else "",
        next_step=parts[3].strip() if len(parts) > 3 else "",
        confidence=max(0.0, min(1.0, confidence)),
    )


class OverlayWindow(QWidget):
    """置顶、不可聚焦、完全点击穿透的绘制窗口。"""

    ACCENT = QColor("#F59E42")
    WINDOW_ACCENT = QColor("#42B6F5")
    TEXT_PRIMARY = QColor("#F7F8FA")
    TEXT_SECONDARY = QColor("#AEB6C2")
    SURFACE = QColor(15, 19, 27, 222)
    SURFACE_BORDER = QColor(255, 255, 255, 28)

    def __init__(self, host: str = "127.0.0.1", port: int = 12345):
        super().__init__()
        self.host = host
        self.port = port
        self.current_data: OverlayData | None = None
        self.window_geometry: WindowGeometry | None = None
        self.data_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._shutdown_requested = threading.Event()
        self._server_socket: socket.socket | None = None

        flags = (
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
            | Qt.WindowDoesNotAcceptFocus
        )
        if hasattr(Qt, "WindowTransparentForInput"):
            flags |= Qt.WindowTransparentForInput
        self.setWindowFlags(flags)
        self.setFocusPolicy(Qt.NoFocus)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)

        primary_screen = QApplication.primaryScreen()
        if primary_screen is not None:
            self.setGeometry(primary_screen.virtualGeometry())

        self.server_thread = threading.Thread(
            target=self._socket_server,
            name="overlay-udp",
            daemon=True,
        )
        self.server_thread.start()

        self.repaint_timer = QTimer(self)
        self.repaint_timer.timeout.connect(self._on_tick)
        self.repaint_timer.start(33)

        self.window_tracker_timer = QTimer(self)
        self.window_tracker_timer.timeout.connect(self._refresh_window_geometry)
        self.window_tracker_timer.start(100)
        self._refresh_window_geometry()

        self.topmost_timer = QTimer(self)
        self.topmost_timer.timeout.connect(self._apply_native_window_style)
        self.topmost_timer.start(2000)

        overlay_logger.info("覆盖层已初始化（输入穿透已启用）")

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._apply_native_window_style()

    def _apply_native_window_style(self) -> None:
        """为 Windows 增加原生点击穿透，作为 Qt 标志之外的第二层保障。"""
        if sys.platform != "win32":
            return
        try:
            from ctypes import wintypes

            hwnd = wintypes.HWND(int(self.winId()))
            user32 = ctypes.windll.user32
            get_style = getattr(user32, "GetWindowLongPtrW", user32.GetWindowLongW)
            set_style = getattr(user32, "SetWindowLongPtrW", user32.SetWindowLongW)
            get_style.argtypes = [wintypes.HWND, ctypes.c_int]
            get_style.restype = ctypes.c_ssize_t
            set_style.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
            set_style.restype = ctypes.c_ssize_t

            gwl_exstyle = -20
            ws_ex_transparent = 0x00000020
            ws_ex_toolwindow = 0x00000080
            ws_ex_layered = 0x00080000
            ws_ex_noactivate = 0x08000000
            extended_style = get_style(hwnd, gwl_exstyle)
            required_style = (
                ws_ex_transparent
                | ws_ex_toolwindow
                | ws_ex_layered
                | ws_ex_noactivate
            )
            if extended_style & required_style != required_style:
                set_style(hwnd, gwl_exstyle, extended_style | required_style)

            hwnd_topmost = -1
            swp_flags = 0x0001 | 0x0002 | 0x0010 | 0x0020
            user32.SetWindowPos(hwnd, hwnd_topmost, 0, 0, 0, 0, swp_flags)
        except Exception as exc:
            overlay_logger.warning("应用原生窗口样式失败: %s", exc)

    def _socket_server(self) -> None:
        server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.settimeout(0.5)
        self._server_socket = server
        try:
            server.bind((self.host, self.port))
            overlay_logger.info("覆盖层正在监听 %s:%s", self.host, self.port)
        except OSError as exc:
            overlay_logger.exception("覆盖层 UDP 服务启动失败: %s", exc)
            server.close()
            return

        try:
            while not self._stop_event.is_set():
                try:
                    payload, _ = server.recvfrom(4096)
                except socket.timeout:
                    continue
                except OSError:
                    break

                message = payload.decode("utf-8", errors="replace").strip()
                if message == OVERLAY_CLOSE_COMMAND:
                    self._shutdown_requested.set()
                    continue

                data = parse_overlay_message(message)
                if data is not None:
                    with self.data_lock:
                        self.current_data = data
        finally:
            server.close()
            self._server_socket = None

    def _on_tick(self) -> None:
        """在 GUI 线程中处理退出请求，避免从 UDP 工作线程直接关闭窗口。"""
        if self._shutdown_requested.is_set():
            self.close()
            app = QApplication.instance()
            if app is not None:
                app.quit()
            return
        self.update()

    def _refresh_window_geometry(self) -> None:
        """每 100ms 重新读取游戏客户区，实时标定窗口位置、尺寸和中心点。"""
        geometry = get_game_client_geometry()
        if geometry != self.window_geometry:
            self.window_geometry = geometry
            self.update()

    def paintEvent(self, event) -> None:
        del event
        with self.data_lock:
            data = self.current_data
        geometry = self.window_geometry
        if data is None and geometry is None:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)
        if geometry is not None:
            self._draw_window_calibration(painter, geometry)
        if data is None:
            return
        self._draw_step_card(painter, data.step_name, data.next_step)
        if data.width > 0 and data.height > 0:
            target = QRect(
                data.x - self.geometry().x(),
                data.y - self.geometry().y(),
                data.width,
                data.height,
            )
            self._draw_target(painter, target)
            self._draw_target_label(painter, target, data.image_name, data.confidence)

    def _draw_window_calibration(self, painter: QPainter, geometry: WindowGeometry) -> None:
        """绘制实时客户区边框与供循环2使用的中心坐标。"""
        target = QRect(
            geometry.x - self.geometry().x(),
            geometry.y - self.geometry().y(),
            geometry.width,
            geometry.height,
        )
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(self.WINDOW_ACCENT, 1.5, Qt.DashLine))
        painter.drawRect(target)

        center = target.center()
        painter.setPen(QPen(self.WINDOW_ACCENT, 1.5))
        painter.drawLine(center.x() - 12, center.y(), center.x() + 12, center.y())
        painter.drawLine(center.x(), center.y() - 12, center.x(), center.y() + 12)
        painter.setBrush(self.WINDOW_ACCENT)
        painter.drawEllipse(center, 3, 3)

        center_x, center_y = geometry.center
        label_text = (
            f"游戏客户区  {geometry.x}, {geometry.y}  ·  {geometry.width}×{geometry.height}"
            f"\n中心坐标  {center_x}, {center_y}"
        )
        font = QFont("Microsoft YaHei UI", 9, QFont.Medium)
        painter.setFont(font)
        metrics = QFontMetrics(font)
        label_width = max(
            metrics.horizontalAdvance(line) for line in label_text.splitlines()
        ) + 20
        label_height = 48
        label_x = max(12, min(target.left() + 10, self.width() - label_width - 12))
        label_y = max(12, min(target.top() + 10, self.height() - label_height - 12))
        label = QRectF(label_x, label_y, label_width, label_height)
        painter.setPen(QPen(self.SURFACE_BORDER, 1))
        painter.setBrush(self.SURFACE)
        painter.drawRoundedRect(label, 8, 8)
        painter.setPen(self.WINDOW_ACCENT)
        painter.drawText(label.adjusted(10, 6, -10, -6), Qt.AlignVCenter | Qt.AlignLeft, label_text)

    def _draw_step_card(self, painter: QPainter, step: str, next_step: str) -> None:
        if not step and not next_step:
            return

        card_width = min(520, max(300, self.width() - 32))
        has_next = bool(next_step)
        card_height = 74 if has_next else 54
        card = QRectF((self.width() - card_width) / 2, 20, card_width, card_height)

        painter.setPen(QPen(self.SURFACE_BORDER, 1))
        painter.setBrush(self.SURFACE)
        painter.drawRoundedRect(card, 12, 12)

        accent = QRectF(card.left(), card.top() + 12, 3, card.height() - 24)
        painter.setPen(Qt.NoPen)
        painter.setBrush(self.ACCENT)
        painter.drawRoundedRect(accent, 1.5, 1.5)

        content_left = int(card.left()) + 18
        content_width = int(card.width()) - 34
        title_font = QFont("Microsoft YaHei UI", 11, QFont.DemiBold)
        title_metrics = QFontMetrics(title_font)
        title = title_metrics.elidedText(step or "正在执行", Qt.ElideRight, content_width)
        painter.setFont(title_font)
        painter.setPen(self.TEXT_PRIMARY)
        title_y = int(card.top()) + (29 if has_next else 34)
        painter.drawText(content_left, title_y, title)

        if has_next:
            next_font = QFont("Microsoft YaHei UI", 9)
            next_metrics = QFontMetrics(next_font)
            next_text = next_metrics.elidedText(
                f"下一步  {next_step}",
                Qt.ElideRight,
                content_width,
            )
            painter.setFont(next_font)
            painter.setPen(self.TEXT_SECONDARY)
            painter.drawText(content_left, int(card.top()) + 55, next_text)

    def _draw_target(self, painter: QPainter, target: QRect) -> None:
        painter.setPen(Qt.NoPen)
        fill = QColor(self.ACCENT)
        fill.setAlpha(12)
        painter.setBrush(fill)
        painter.drawRoundedRect(QRectF(target), 6, 6)

        corner_length = max(10, min(22, min(target.width(), target.height()) // 4))
        path = QPainterPath()
        left, top, right, bottom = (
            target.left(),
            target.top(),
            target.right(),
            target.bottom(),
        )
        path.moveTo(left, top + corner_length)
        path.lineTo(left, top)
        path.lineTo(left + corner_length, top)
        path.moveTo(right - corner_length, top)
        path.lineTo(right, top)
        path.lineTo(right, top + corner_length)
        path.moveTo(right, bottom - corner_length)
        path.lineTo(right, bottom)
        path.lineTo(right - corner_length, bottom)
        path.moveTo(left + corner_length, bottom)
        path.lineTo(left, bottom)
        path.lineTo(left, bottom - corner_length)

        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(self.ACCENT, 2.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        painter.drawPath(path)

        center = target.center()
        painter.setPen(QPen(self.ACCENT, 1.5))
        painter.setBrush(QColor(15, 19, 27, 190))
        painter.drawEllipse(center, 4, 4)
        painter.setPen(Qt.NoPen)
        painter.setBrush(self.ACCENT)
        painter.drawEllipse(center, 1, 1)

    def _draw_target_label(
        self,
        painter: QPainter,
        target: QRect,
        image_name: str,
        confidence: float,
    ) -> None:
        if not image_name and confidence <= 0:
            return

        font = QFont("Microsoft YaHei UI", 9, QFont.Medium)
        painter.setFont(font)
        metrics = QFontMetrics(font)
        name = Path(image_name).stem if image_name else "已识别"
        confidence_text = f"{confidence:.0%}" if confidence > 0 else ""
        label_text = f"{name}  ·  {confidence_text}" if confidence_text else name
        max_text_width = min(320, max(80, self.width() - 48))
        label_text = metrics.elidedText(label_text, Qt.ElideMiddle, max_text_width)

        label_width = metrics.horizontalAdvance(label_text) + 20
        label_height = 30
        label_x = max(12, min(target.left(), self.width() - label_width - 12))
        label_y = target.top() - label_height - 7
        if label_y < 12:
            label_y = target.bottom() + 7
        label_y = min(label_y, self.height() - label_height - 12)
        label = QRectF(label_x, label_y, label_width, label_height)

        painter.setPen(QPen(self.SURFACE_BORDER, 1))
        painter.setBrush(self.SURFACE)
        painter.drawRoundedRect(label, 8, 8)
        painter.setPen(self.TEXT_PRIMARY)
        painter.drawText(label, Qt.AlignCenter, label_text)

    def closeEvent(self, event) -> None:
        self._stop_event.set()
        if self._server_socket is not None:
            try:
                self._server_socket.close()
            except OSError:
                pass
        overlay_logger.info("覆盖层已退出")
        event.accept()


def _get_parent_pid(arguments: list[str]) -> int:
    if len(arguments) > 1:
        try:
            return int(arguments[1])
        except ValueError:
            pass
    return os.getppid()


def _get_endpoint(arguments: list[str]) -> tuple[str, int]:
    host = arguments[2] if len(arguments) > 2 and arguments[2] else "127.0.0.1"
    try:
        port = int(arguments[3]) if len(arguments) > 3 else 12345
    except ValueError:
        port = 12345
    return host, port


def _parent_exists(parent_pid: int) -> bool:
    try:
        import psutil

        return psutil.pid_exists(parent_pid)
    except ImportError:
        if sys.platform != "win32":
            return True
        try:
            process_query_limited_information = 0x1000
            handle = ctypes.windll.kernel32.OpenProcess(
                process_query_limited_information,
                False,
                parent_pid,
            )
            if not handle:
                return False
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        except Exception:
            return True
    except Exception as exc:
        overlay_logger.warning("检查父进程时出错: %s", exc)
        return True


def main() -> int:
    parent_pid = _get_parent_pid(sys.argv)
    host, port = _get_endpoint(sys.argv)
    app = QApplication(sys.argv)
    window = OverlayWindow(host, port)
    window.show()

    def check_parent() -> None:
        if not _parent_exists(parent_pid):
            overlay_logger.info("父进程 PID=%s 已退出，覆盖层自动关闭", parent_pid)
            app.quit()

    parent_timer = QTimer()
    parent_timer.timeout.connect(check_parent)
    parent_timer.start(1000)
    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
