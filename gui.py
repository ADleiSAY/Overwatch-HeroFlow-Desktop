# gui.py
# 现代控制台风格界面 - 集成所有模块（Clicker / Driver / HeroSelector / PowerMonitor / Tariff / FlowEngine）
import sys
import os
import json
import time
import socket
import threading
import subprocess
import ctypes
from ctypes import wintypes

# ===== 首次启动依赖引导（必须在 PyQt5 导入前运行）=====
# 检测必需依赖是否已安装；若缺失则自动 pip install 后提示重启。
import importlib.util as _ilu

if _ilu.find_spec("PyQt5.QtWidgets") is None or _ilu.find_spec("PyQt5.QtCore") is None:
    # 缺失必需依赖 → 调用 bootstrap 自动安装
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        from bootstrap import ensure_dependencies
        _ok = ensure_dependencies()
    except Exception as _e:
        _ok = False
        print(f"bootstrap 异常: {_e}")
    if not _ok:
        # 安装失败或被取消
        try:
            ctypes.windll.user32.MessageBoxW(
                0,
                "必需依赖安装失败，程序将退出。\n请手动执行：\n  pip install -r requirements.txt",
                "Overwatch Hero - 依赖缺失",
                0x10  # MB_ICONERROR
            )
        except Exception:
            pass
        sys.exit(1)
    # 安装完成，提示用户重启程序使新装的依赖生效
    try:
        ctypes.windll.user32.MessageBoxW(
            0,
            "依赖已安装完成。\n请重新运行程序以加载新依赖。",
            "Overwatch Hero - 安装完成",
            0x40  # MB_ICONINFORMATION
        )
    except Exception:
        pass
    sys.exit(0)
else:
    # 依赖已存在，但仍需首次运行提醒（联网提示等）
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        from bootstrap import is_first_run, ensure_dependencies
        if is_first_run():
            # 不阻塞，仅显示提醒；失败也继续启动
            try:
                ensure_dependencies()
            except Exception:
                pass
    except Exception:
        pass

# ===== 正常导入 PyQt5 等第三方包 =====
# 开启 DPI 感知（物理坐标），确保 dxcam 截图像素与窗口坐标一致
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PER_MONITOR_AWARE_V2
except (AttributeError, OSError):
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except (AttributeError, OSError):
        pass

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QSlider, QComboBox, QCheckBox, QGroupBox,
    QGridLayout, QDateTimeEdit, QTimeEdit, QLineEdit, QTextEdit,
    QFrame, QScrollArea, QSizePolicy, QMessageBox, QProgressBar
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer, QDateTime, QTime, QMargins
from PyQt5.QtGui import QFont, QColor, QTextCharFormat, QBrush

# PyQtChart（可选，未安装时显示提示但不崩溃）
try:
    from PyQt5.QtChart import QChart, QChartView, QLineSeries, QValueAxis, QDateTimeAxis
    CHART_AVAILABLE = True
except ImportError:
    CHART_AVAILABLE = False

import config
from clicker import Clicker
from driver_click import (
    DriverClicker, DriverKeyboard,
    is_driver_installed, is_driver_loaded, install_driver,
    VK_CTRL, VK_D, VK_E
)
from hero_selector import HeroSelector
from power_monitor import PowerMonitor
from tariff_service import (
    get_tariff_with_cache, lookup_tariff, calculate_cost, DEFAULT_TARIFF
)
from flow_engine import FlowEngine, FlowState, STEP_FLOW
from logger import logger, LEVEL_COLORS

# ===== 加载 HarmonyOS Sans 字体 =====
# 注意：字体加载在 QApplication 创建前可能导致崩溃，改为延迟加载
FONT_FAMILY = "Microsoft YaHei"


# ========== 样式表（暗色主题 + 现代风格）==========
STYLE_SHEET = """
/* ===== 全局 ===== */
QMainWindow {
    background-color: #0d1117;
}
QWidget { background-color: transparent; }
QLabel { color: #c9d1d9; font-size: 13px; background: transparent; }
QLabel#title {
    color: #f7931e; font-size: 16px; font-weight: bold;
    padding: 14px 12px; background: transparent;
    border: none;
    border-radius: 8px;
}
QLabel#status { font-size: 14px; padding: 6px 10px; background: transparent; }
QLabel#value { color: #f7931e; font-size: 13px; font-weight: bold; background: transparent; }
QLabel#section {
    color: #8b949e; font-size: 12px; font-weight: bold;
    padding-top: 10px; background: transparent;
    border: none; border-bottom: 1px solid #21262d; padding-bottom: 4px;
}

/* ===== 分组框 ===== */
QGroupBox {
    color: #8b949e; font-size: 12px; font-weight: bold;
    border: 1px solid #21262d; border-radius: 10px;
    margin-top: 14px; padding: 18px 12px 12px 12px;
    background-color: rgba(22, 27, 34, 150);
}
QGroupBox::title {
    subcontrol-origin: margin; left: 14px; padding: 0 8px;
    color: #f7931e;
}

/* ===== 按钮（主操作） ===== */
QPushButton {
    background-color: #238636; color: #ffffff; border: none;
    border-radius: 8px; padding: 10px 20px;
    font-size: 14px; font-weight: bold;
    min-height: 22px;
}
QPushButton:hover {
    background-color: #2ea043;
    border: 1px solid #3fb950;
}
QPushButton:pressed { background-color: #1a7f37; }
QPushButton:disabled { background-color: #21262d; color: #6e7681; }
QPushButton#stopBtn { background-color: #da3633; }
QPushButton#stopBtn:hover { background-color: #f85149; border: 1px solid #ff6b6b; }
QPushButton#stopBtn:disabled { background-color: #3d2626; color: #6e7681; }
QPushButton#pauseBtn { background-color: #d29922; color: #1a1a1a; }
QPushButton#pauseBtn:hover { background-color: #e3b341; border: 1px solid #f0c050; }
QPushButton#pauseBtn:disabled { background-color: #21262d; color: #6e7681; }
QPushButton#loop2Btn {
    background-color: #6f42c1; color: #fff;
    border: 1px solid #8957e5;
}
QPushButton#loop2Btn:hover {
    background-color: #8957e5;
    border: 1px solid #a371f7;
}
QPushButton#loop2Btn:checked {
    background-color: #da3633;
    border: 1px solid #f85149;
}
QPushButton#loop2Btn:checked:hover {
    background-color: #f85149;
}
QPushButton#secondary {
    background-color: rgba(33, 38, 45, 200); color: #c9d1d9;
    border: 1px solid #30363d; font-size: 12px; padding: 6px 14px;
    border-radius: 6px;
}
QPushButton#secondary:hover {
    background-color: #30363d;
    border: 1px solid #484f58;
    color: #f0f6fc;
}

/* ===== 滑块 ===== */
QSlider::groove:horizontal {
    height: 6px; background: #21262d; border-radius: 3px;
    border: 1px solid #161b22;
}
QSlider::handle:horizontal {
    background: #f7931e;
    border-radius: 10px; width: 18px; height: 18px; margin: -7px 0;
    border: 2px solid #0d1117;
}
QSlider::handle:horizontal:hover {
    background: #ffa657;
    border: 2px solid #f7931e;
}
QSlider::sub-page:horizontal {
    background: #f7931e;
    border-radius: 3px;
}
QSlider::handle:horizontal:disabled { background: #484f58; border: 2px solid #161b22; }
QSlider::sub-page:horizontal:disabled { background: #484f58; }

/* ===== 下拉框 ===== */
QComboBox {
    background-color: rgba(33, 38, 45, 200); color: #c9d1d9;
    border: 1px solid #30363d; border-radius: 6px; padding: 5px 10px;
    min-height: 20px;
}
QComboBox:hover {
    border: 1px solid #484f58;
    background-color: rgba(48, 54, 61, 230);
}
QComboBox::drop-down {
    border: none; width: 22px;
    border-left: 1px solid #30363d;
}
QComboBox::down-arrow {
    image: none; width: 0; height: 0;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid #8b949e;
}
QComboBox QAbstractItemView {
    background-color: #161b22; color: #c9d1d9;
    selection-background-color: #f7931e;
    selection-color: #0d1117;
    border: 1px solid #30363d; border-radius: 4px;
    padding: 4px; outline: none;
}

/* ===== 输入框 ===== */
QLineEdit {
    background-color: rgba(33, 38, 45, 200); color: #c9d1d9;
    border: 1px solid #30363d; border-radius: 6px; padding: 5px 10px;
    selection-background-color: #f7931e; selection-color: #0d1117;
}
QLineEdit:focus {
    border: 1px solid #f7931e;
    background-color: rgba(48, 54, 61, 230);
}
QTextEdit {
    background-color: #010409; color: #c9d1d9;
    border: 1px solid #21262d; border-radius: 8px;
    font-family: 'Consolas', 'Microsoft YaHei', monospace;
    font-size: 12px; padding: 6px;
    selection-background-color: #f7931e; selection-color: #0d1117;
}

/* ===== 复选框 ===== */
QCheckBox { color: #c9d1d9; font-size: 13px; spacing: 8px; background: transparent; }
QCheckBox::indicator {
    width: 18px; height: 18px; border-radius: 4px;
    border: 1px solid #30363d; background: #21262d;
}
QCheckBox::indicator:hover {
    border: 1px solid #f7931e;
    background: #30363d;
}
QCheckBox::indicator:checked {
    background: #f7931e;
    border: 1px solid #f7931e;
}
QCheckBox::indicator:disabled { background: #161b22; border: 1px solid #21262d; }

/* ===== 日期时间 ===== */
QDateTimeEdit, QTimeEdit {
    background-color: rgba(33, 38, 45, 200); color: #c9d1d9;
    border: 1px solid #30363d; border-radius: 6px; padding: 5px 10px;
    min-height: 20px;
}
QDateTimeEdit:hover, QTimeEdit:hover {
    border: 1px solid #484f58;
    background-color: rgba(48, 54, 61, 230);
}
QDateTimeEdit:disabled, QTimeEdit:disabled {
    background-color: #161b22; color: #6e7681;
}

/* ===== 分割线 ===== */
QFrame#divider {
    background-color: #21262d; max-height: 1px;
    border: none; border-radius: 0;
}

/* ===== 滚动区域 ===== */
QScrollArea {
    border: none; background-color: transparent;
    border-radius: 8px;
}
QScrollBar:vertical {
    background: transparent; width: 10px; margin: 4px 2px 4px 0;
    border: none; border-radius: 5px;
}
QScrollBar::handle:vertical {
    background: #30363d; border-radius: 4px; min-height: 30px;
}
QScrollBar::handle:vertical:hover { background: #f7931e; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal {
    background: transparent; height: 10px; margin: 0 4px 2px 4px;
    border: none; border-radius: 5px;
}
QScrollBar::handle:horizontal {
    background: #30363d; border-radius: 4px; min-width: 30px;
}
QScrollBar::handle:horizontal:hover { background: #f7931e; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }

/* ===== 进度条 ===== */
QProgressBar {
    background-color: #21262d; border: 1px solid #30363d;
    border-radius: 6px; text-align: center;
    color: #c9d1d9; font-size: 11px;
}
QProgressBar::chunk {
    background: #f7931e;
    border-radius: 5px;
}

/* ===== 图表 ===== */
QChartView {
    background-color: transparent; border: 1px solid #21262d;
    border-radius: 8px;
}

/* ===== 自定义标题栏 ===== */
QWidget#titleBar {
    background-color: #161b22;
    border-bottom: 1px solid #21262d;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
}

/* ===== 窗口控制按钮 ===== */
QPushButton#windowBtn {
    background-color: transparent;
    border: none;
    border-radius: 0px;
    color: #8b949e;
    font-size: 14px;
    font-weight: bold;
    padding: 0px;
    min-height: 0px;
}
QPushButton#windowBtn:hover {
    background-color: #30363d;
    color: #c9d1d9;
}
QPushButton#windowBtn:pressed {
    background-color: #484f58;
}
QPushButton#closeBtn {
    background-color: transparent;
    border: none;
    border-radius: 0px;
    color: #8b949e;
    font-size: 14px;
    font-weight: bold;
    padding: 0px;
    min-height: 0px;
}
QPushButton#closeBtn:hover {
    background-color: #da3633;
    color: #ffffff;
}
QPushButton#closeBtn:pressed {
    background-color: #f85149;
}
"""


# ========== 辅助函数：QTime ↔ 秒 ==========
def qtime_to_seconds(qtime):
    """QTime 转秒数"""
    return qtime.hour() * 3600 + qtime.minute() * 60 + qtime.second()


def seconds_to_qtime(seconds):
    """秒数转 QTime（对 24 小时取模）"""
    seconds = max(0, int(seconds))
    hours = (seconds // 3600) % 24
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    return QTime(hours, minutes, secs)


# ========== 应用图标（QPainter 自绘）==========
def _create_app_icon():
    """用 QPainter 绘制应用图标（橙色圆形 + 白色 OW 字样 + 底部橙色弧线）"""
    from PyQt5.QtGui import QPixmap, QPainter, QColor, QPen, QBrush, QFont, QPainterPath
    from PyQt5.QtCore import QRectF, Qt

    size = 256
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)

    # 外圈：深色背景圆
    rect = QRectF(8, 8, size - 16, size - 16)
    painter.setBrush(QBrush(QColor("#0d1117")))
    pen = QPen(QColor("#f7931e"))
    pen.setWidthF(6)
    painter.setPen(pen)
    painter.drawEllipse(rect)

    # 内圈：橙色渐变圆（模拟发光）
    inner_rect = QRectF(28, 28, size - 56, size - 56)
    painter.setBrush(QBrush(QColor("#f7931e")))
    pen = QPen(QColor("#ffa657"))
    pen.setWidthF(2)
    painter.setPen(pen)
    painter.drawEllipse(inner_rect)

    # 中央文字 "OW"
    painter.setPen(QColor("#0d1117"))
    font = QFont("Arial", 72, QFont.Bold)
    painter.setFont(font)
    painter.drawText(rect, Qt.AlignCenter, "OW")

    # 底部弧线（装饰）
    painter.setPen(QPen(QColor("#ffffff"), 3))
    painter.setBrush(Qt.NoBrush)
    arc_rect = QRectF(40, size - 60, size - 80, 40)
    painter.drawArc(arc_rect, 0 * 16, 180 * 16)

    painter.end()

    from PyQt5.QtGui import QIcon
    return QIcon(pixmap)


# ========== 窗口控制按钮（QPainter 矢量图标）==========
class WindowButton(QPushButton):
    """自定义窗口控制按钮，用 QPainter 绘制矢量图标
    icon_type: 'minimize' / 'maximize' / 'close'
    """
    def __init__(self, icon_type, parent=None):
        super().__init__(parent)
        self.icon_type = icon_type
        self._hover = False
        self._pressed = False

    def enterEvent(self, event):
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover = False
        self._pressed = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        self._pressed = True
        self.update()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        self._pressed = False
        self.update()
        super().mouseReleaseEvent(event)

    def paintEvent(self, event):
        from PyQt5.QtGui import QPainter, QPen, QColor, QBrush
        from PyQt5.QtCore import QRectF, QPointF

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)

        w = self.width()
        h = self.height()

        # 背景
        if self.icon_type == 'close' and self._hover:
            bg_color = QColor("#da3633") if not self._pressed else QColor("#f85149")
        elif self._hover:
            bg_color = QColor("#30363d") if not self._pressed else QColor("#484f58")
        else:
            bg_color = QColor("transparent")
        painter.fillRect(self.rect(), QBrush(bg_color))

        # 图标颜色
        if self.icon_type == 'close' and self._hover:
            icon_color = QColor("#ffffff")
        elif self._hover:
            icon_color = QColor("#c9d1d9")
        else:
            icon_color = QColor("#8b949e")

        pen = QPen(icon_color)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)

        cx, cy = w / 2, h / 2

        if self.icon_type == 'minimize':
            # 最小化：一条水平线
            pen.setWidthF(1.6)
            painter.setPen(pen)
            y = cy + 2
            painter.drawLine(QPointF(cx - 7, y), QPointF(cx + 7, y))

        elif self.icon_type == 'maximize':
            # 最大化：方框
            pen.setWidthF(1.4)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            rect = QRectF(cx - 7, cy - 6, 14, 12)
            painter.drawRoundedRect(rect, 1.5, 1.5)
            # 顶部小条（标题栏）
            painter.drawLine(QPointF(cx - 7, cy - 3), QPointF(cx + 7, cy - 3))

        elif self.icon_type == 'close':
            # 关闭：X 图标
            pen.setWidthF(1.6)
            painter.setPen(pen)
            r = 7
            painter.drawLine(QPointF(cx - r, cy - r), QPointF(cx + r, cy + r))
            painter.drawLine(QPointF(cx + r, cy - r), QPointF(cx - r, cy + r))

        painter.end()


# ========== 英雄卡片（可点击图片多选）==========
class HeroCard(QWidget):
    """
    英雄卡片：图片 + 名字 + 选中边框
    - 点击卡片任意位置切换选中状态
    - 选中时显示橙色高亮边框 + 半透明橙色蒙层
    - 兼容 QCheckBox 接口：isChecked / setChecked / stateChanged 信号
    """
    stateChanged = pyqtSignal(int)

    CARD_SIZE = 68          # 卡片宽高（紧凑）
    IMAGE_SIZE = 50         # 图片尺寸（紧凑）

    # 选中/未选中样式
    STYLE_NORMAL = """
        QWidget#heroCard {
            background-color: #161b22;
            border: 1px solid #30363d;
            border-radius: 5px;
        }
        QWidget#heroCard:hover {
            background-color: #21262d;
            border: 1px solid #484f58;
        }
        QLabel#heroName {
            color: #c9d1d9;
            font-size: 9px;
            font-weight: bold;
        }
    """
    STYLE_SELECTED = """
        QWidget#heroCard {
            background-color: #2d1b0e;
            border: 2px solid #f7931e;
            border-radius: 5px;
        }
        QWidget#heroCard:hover {
            background-color: #3d2614;
        }
        QLabel#heroName {
            color: #f7931e;
            font-size: 9px;
            font-weight: bold;
        }
    """

    def __init__(self, hero_name, image_path, parent=None):
        super().__init__(parent)
        self._checked = False
        self._enabled = True
        self.hero_name = hero_name
        self.image_path = image_path

        self.setFixedSize(self.CARD_SIZE, self.CARD_SIZE)
        self.setObjectName("heroCard")
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet(self.STYLE_NORMAL)

        # 布局：垂直，图片在上，名字在下
        layout = QVBoxLayout(self)
        layout.setContentsMargins(3, 4, 3, 3)
        layout.setSpacing(1)

        # 图片标签
        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setFixedSize(self.IMAGE_SIZE, self.IMAGE_SIZE)
        self._load_image(image_path)
        layout.addWidget(self.image_label, 1, Qt.AlignCenter)

        # 名字标签
        self.name_label = QLabel(hero_name.strip())
        self.name_label.setObjectName("heroName")
        self.name_label.setAlignment(Qt.AlignCenter)
        self.name_label.setWordWrap(False)
        layout.addWidget(self.name_label)

    def _load_image(self, image_path):
        """加载英雄图片，失败则显示占位符"""
        from PyQt5.QtGui import QPixmap
        pixmap = QPixmap(image_path)
        if pixmap.isNull():
            # 占位符：灰色矩形 + 英雄名首字
            pixmap = QPixmap(self.IMAGE_SIZE, self.IMAGE_SIZE)
            pixmap.fill(QColor("#30363d"))
            from PyQt5.QtGui import QPainter, QFont
            painter = QPainter(pixmap)
            painter.setPen(QColor("#c9d1d9"))
            font = QFont("Microsoft YaHei", 11, QFont.Bold)
            painter.setFont(font)
            painter.drawText(pixmap.rect(), Qt.AlignCenter, self.hero_name.strip()[:1])
            painter.end()
        else:
            pixmap = pixmap.scaled(
                self.IMAGE_SIZE, self.IMAGE_SIZE,
                Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
        self.image_label.setPixmap(pixmap)

    def mousePressEvent(self, event):
        """点击切换选中状态"""
        if not self._enabled:
            return
        if event.button() == Qt.LeftButton:
            self.setChecked(not self._checked)
        super().mousePressEvent(event)

    def isChecked(self):
        return self._checked

    def setChecked(self, checked):
        """设置选中状态（触发 stateChanged 信号）"""
        if self._checked == checked:
            return
        self._checked = checked
        self.setStyleSheet(self.STYLE_SELECTED if checked else self.STYLE_NORMAL)
        # stateChanged 信号兼容 QCheckBox
        self.stateChanged.emit(2 if checked else 0)

    def setEnabled(self, enabled):
        """禁用时变灰"""
        self._enabled = enabled
        super().setEnabled(enabled)
        if enabled:
            self.setStyleSheet(self.STYLE_SELECTED if self._checked else self.STYLE_NORMAL)
        else:
            # 禁用样式
            if self._checked:
                self.setStyleSheet(
                    "QWidget#heroCard { background-color: #1a1208; border: 2px solid #6e4a1e; border-radius: 6px; }"
                    "QLabel#heroName { color: #6e4a1e; font-size: 11px; font-weight: bold; }"
                )
            else:
                self.setStyleSheet(
                    "QWidget#heroCard { background-color: #0d1117; border: 1px solid #21262d; border-radius: 6px; }"
                    "QLabel#heroName { color: #484f58; font-size: 11px; font-weight: bold; }"
                )

    def blockSignals(self, block):
        """兼容 QCheckBox.blockSignals"""
        return super().blockSignals(block)


# ========== 工作线程：FlowEngine ==========
class FlowWorker(QThread):
    """在子线程运行 FlowEngine，通过信号通知主线程"""
    state_signal = pyqtSignal(str, str, str)   # state_value, current_op, next_op
    log_signal = pyqtSignal(str, str)           # level, message
    overlay_signal = pyqtSignal(int, int, int, int, str, str, str, float)
    finish_signal = pyqtSignal()

    def __init__(self, clicker, keyboard, mouse_driver, hero_selector, options):
        super().__init__()
        self.clicker = clicker
        self.keyboard = keyboard
        self.mouse_driver = mouse_driver
        self.hero_selector = hero_selector
        self.options = options
        self.engine = None

    def run(self):
        """子线程入口：创建 FlowEngine 并运行"""
        callbacks = {
            'on_state_change': lambda s, cur, nxt: self.state_signal.emit(s.value, cur, nxt),
            'on_log': lambda lvl, msg: self.log_signal.emit(lvl, msg),
            'on_overlay': lambda x, y, w, h, name, step, next_step, conf:
                self.overlay_signal.emit(int(x), int(y), int(w), int(h), str(name), str(step), str(next_step), float(conf)),
            'on_finish': lambda: self.finish_signal.emit(),
        }
        self.engine = FlowEngine(
            clicker=self.clicker,
            keyboard=self.keyboard,
            mouse_driver=self.mouse_driver,
            hero_selector=self.hero_selector,
            callbacks=callbacks,
            options=self.options
        )
        self.engine.run()

    def pause(self):
        if self.engine:
            self.engine.pause()

    def resume(self):
        if self.engine:
            self.engine.resume()

    def stop(self):
        if self.engine:
            self.engine.stop()


# ========== 工作线程：循环2持续模式 ==========
class Loop2Worker(QThread):
    """单独运行循环2的子线程（不识别退出条件，一直循环）"""
    log_signal = pyqtSignal(str, str)
    finish_signal = pyqtSignal()

    def __init__(self, clicker, keyboard, mouse_driver, options):
        super().__init__()
        self.clicker = clicker
        self.keyboard = keyboard
        self.mouse_driver = mouse_driver
        self.options = options
        self.engine = None

    def run(self):
        callbacks = {
            'on_state_change': lambda s, cur, nxt: None,
            'on_log': lambda lvl, msg: self.log_signal.emit(lvl, msg),
            'on_overlay': lambda *args: None,
            'on_finish': lambda: self.finish_signal.emit(),
        }
        self.engine = FlowEngine(
            clicker=self.clicker,
            keyboard=self.keyboard,
            mouse_driver=self.mouse_driver,
            hero_selector=None,
            callbacks=callbacks,
            options=self.options
        )
        self.engine.run_loop2_continuous()

    def stop(self):
        if self.engine:
            self.engine.stop()


# ========== 主窗口 ==========
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Overwatch Hero - 脚本化刷取控制台")
        # 无边框窗口
        self.setWindowFlags(Qt.FramelessWindowHint)
        # 默认尺寸 1560x1080（宽不变，高度在原 30% 基础上再增 5%）
        self.resize(1560, 1080)
        self.setMinimumSize(1200, 800)
        self.setStyleSheet(STYLE_SHEET)
        # 鼠标拖拽窗口相关
        self._dragging = False
        self._drag_offset = None
        # 设置应用图标（窗口 + 任务栏）
        self.setWindowIcon(_create_app_icon())

        # ===== 运行状态 =====
        self.worker = None
        self.loop2_worker = None
        self.overlay_process = None
        self.power_monitor = PowerMonitor()
        self.tariff = None          # (province, price, from_cache) 或 None
        self.clicker = None
        self.keyboard = None
        self.mouse_driver = None
        self.hero_checkboxes = {}       # {英雄名: QCheckBox}
        self.hero_ratio_sliders = {}    # {英雄名: QSlider}
        self.hero_ratio_labels = {}      # {英雄名: QLabel}（百分比标签）
        self.power_chart_series = None
        self.power_chart_lower = None
        self.power_chart_area = None
        self.power_chart = None
        self._syncing_time = False      # 防止时段同步递归
        self._syncing_ratio = False     # 防止比例同步递归
        self._last_chart_time = 0.0     # 上次图表采样时间
        self._hotkey_id = 1             # F8 热键 ID

        # 加载持久化配置
        self._load_config()

        # 构建 UI
        self._build_ui()

        # 从持久化配置恢复 UI 状态（必须在 _build_ui 之后、_check_driver 之前）
        self._restore_config_to_ui()

        # 初始化 Logger 回调
        logger.add_callback(self._on_log_callback)

        # 检测驱动状态
        self._check_driver()

        # 检测依赖状态（更新按钮显示）
        self._check_deps()

        # 异步获取电价
        threading.Thread(target=self._fetch_tariff_async, daemon=True).start()

        # 启动功耗监控子线程
        self.power_monitor.start()

        # 启动 overlay 子进程（默认开启）
        if self.config_data.get('overlay_enabled', True):
            self._start_overlay()
            self.overlay_check.setChecked(True)

        # 200ms 定时刷新 UI
        self.ui_timer = QTimer()
        self.ui_timer.timeout.connect(self._update_ui)
        self.ui_timer.start(200)

        # 注册 F8 全局热键
        self._register_hotkey()

        logger.info("控制台启动完成")

    # ==================== UI 构建 ====================

    def _build_ui(self):
        """构建主界面"""
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(20, 8, 20, 16)

        # ===== 自定义标题栏（无边框窗口） =====
        title_bar = QWidget()
        title_bar.setObjectName("titleBar")
        title_bar.setFixedHeight(40)
        title_bar_layout = QHBoxLayout(title_bar)
        title_bar_layout.setContentsMargins(0, 0, 0, 0)
        title_bar_layout.setSpacing(0)

        # 标题栏文字
        title_label = QLabel("Overwatch Hero")
        title_label.setObjectName("titleBarLabel")
        title_label.setStyleSheet(
            "color: #f7931e; font-size: 14px; font-weight: bold; "
            "padding-left: 8px; background: transparent;"
        )
        title_bar_layout.addWidget(title_label)
        title_bar_layout.addStretch()

        # 窗口控制按钮（QPainter 矢量图标）
        self.btn_minimize = WindowButton('minimize')
        self.btn_minimize.setFixedSize(46, 32)
        self.btn_minimize.setToolTip("最小化")
        self.btn_minimize.clicked.connect(self.showMinimized)
        title_bar_layout.addWidget(self.btn_minimize)

        self.btn_maximize = WindowButton('maximize')
        self.btn_maximize.setFixedSize(46, 32)
        self.btn_maximize.setToolTip("最大化/还原")
        self.btn_maximize.clicked.connect(self._toggle_maximize)
        title_bar_layout.addWidget(self.btn_maximize)

        self.btn_close = WindowButton('close')
        self.btn_close.setFixedSize(46, 32)
        self.btn_close.setToolTip("关闭")
        self.btn_close.clicked.connect(self.close)
        title_bar_layout.addWidget(self.btn_close)

        main_layout.addWidget(title_bar)

        # 顶部提示
        title = QLabel("请打开守望先锋，窗口化，调成最小，帧率上限30FPS，窗口无遮挡（最好放在右侧），点左上角主页🏠")
        title.setObjectName("title")
        title.setWordWrap(True)
        title.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(title)

        # 状态栏
        status_row = QHBoxLayout()
        self.status_label = QLabel("状态: 就绪")
        self.status_label.setObjectName("status")
        self.status_label.setStyleSheet("color: #6e7681;")
        status_row.addWidget(self.status_label)
        status_row.addStretch()
        main_layout.addLayout(status_row)

        # 分割线
        divider = QFrame()
        divider.setObjectName("divider")
        divider.setFrameShape(QFrame.HLine)
        main_layout.addWidget(divider)

        # 左右两列布局
        content_row = QHBoxLayout()
        content_row.setSpacing(10)

        left_widget = self._build_left_panel()
        content_row.addWidget(left_widget, 2)

        right_widget = self._build_right_panel()
        content_row.addWidget(right_widget, 3)

        main_layout.addLayout(content_row, 1)

        # 控制按钮区
        ctrl_row = self._build_control_buttons()
        main_layout.addLayout(ctrl_row)

        # 驱动管理卡片（独立卡片，位于日志区上方）
        driver_group = QGroupBox("驱动管理")
        driver_layout = QHBoxLayout(driver_group)
        self.driver_status_label = QLabel("驱动: 检测中...")
        self.driver_status_label.setObjectName("value")
        driver_layout.addWidget(self.driver_status_label)
        driver_layout.addStretch()
        self.driver_btn = QPushButton("安装驱动")
        self.driver_btn.setObjectName("secondary")
        self.driver_btn.clicked.connect(self._install_driver)
        driver_layout.addWidget(self.driver_btn)
        # 一键安装依赖按钮（检测并安装所有缺失的必需+可选依赖）
        self.deps_btn = QPushButton("安装依赖")
        self.deps_btn.setObjectName("secondary")
        self.deps_btn.clicked.connect(self._install_deps)
        driver_layout.addWidget(self.deps_btn)
        main_layout.addWidget(driver_group)

        # 底部日志区
        log_group = QGroupBox("日志")
        log_layout = QVBoxLayout(log_group)
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(150)
        log_layout.addWidget(self.log_text)
        # 依赖安装进度条容器（默认隐藏，安装时显示）
        self.deps_progress_widget = QWidget()
        self.deps_progress_widget.setVisible(False)
        deps_progress_layout = QVBoxLayout(self.deps_progress_widget)
        deps_progress_layout.setContentsMargins(0, 4, 0, 0)
        deps_progress_layout.setSpacing(2)
        self.deps_progress_widget.setLayout(deps_progress_layout)
        log_layout.addWidget(self.deps_progress_widget)
        main_layout.addWidget(log_group)

    def _build_left_panel(self):
        """左侧：参数配置（可滚动）"""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        # 禁用水平滚动条（只保留垂直滚动）
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setSpacing(10)

        # ---- 1. 时段/时长 ----
        time_group = QGroupBox("时段/时长")
        time_layout = QVBoxLayout(time_group)

        # 开始时间 + 「现在」按钮
        start_row = QHBoxLayout()
        start_row.addWidget(QLabel("开始时间"))
        self.start_time_edit = QDateTimeEdit(QDateTime.currentDateTime())
        self.start_time_edit.setDisplayFormat("yyyy-MM-dd HH:mm")
        self.start_time_edit.editingFinished.connect(self._on_start_time_changed)
        start_row.addWidget(self.start_time_edit, 1)
        now_btn = QPushButton("现在")
        now_btn.setObjectName("secondary")
        now_btn.clicked.connect(self._on_now_clicked)
        start_row.addWidget(now_btn)
        time_layout.addLayout(start_row)

        # 结束时间
        end_row = QHBoxLayout()
        end_row.addWidget(QLabel("结束时间"))
        self.end_time_edit = QDateTimeEdit(QDateTime.currentDateTime().addSecs(3600))
        self.end_time_edit.setDisplayFormat("yyyy-MM-dd HH:mm")
        self.end_time_edit.editingFinished.connect(self._on_end_time_changed)
        end_row.addWidget(self.end_time_edit, 1)
        time_layout.addLayout(end_row)

        # 时长
        duration_row = QHBoxLayout()
        duration_row.addWidget(QLabel("时长"))
        self.duration_edit = QTimeEdit()
        self.duration_edit.setDisplayFormat("HH:mm:ss")
        # 初始时长 = 结束 - 开始（1 小时）
        self.duration_edit.setTime(seconds_to_qtime(3600))
        self.duration_edit.editingFinished.connect(self._on_duration_changed)
        duration_row.addWidget(self.duration_edit, 1)
        time_layout.addLayout(duration_row)

        # 无限制模式
        self.unlimited_check = QCheckBox("无限制模式（持续运行直到手动停止）")
        self.unlimited_check.stateChanged.connect(self._on_unlimited_changed)
        time_layout.addWidget(self.unlimited_check)

        layout.addWidget(time_group)

        # ---- 2. 英雄选择（按类别 + 图片卡片）----
        hero_group = QGroupBox("英雄选择（点击图片选择）")
        hero_layout = QVBoxLayout(hero_group)
        hero_layout.setSpacing(4)
        hero_layout.setContentsMargins(8, 6, 8, 6)

        # 从 config.HERO_DIR 加载英雄图片文件名
        hero_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), config.HERO_DIR)
        dir_heroes = []
        if os.path.isdir(hero_dir):
            for f in os.listdir(hero_dir):
                if f.lower().endswith('.png'):
                    dir_heroes.append(f[:-4])  # 去掉 .png

        # 建立 stripped 名 → 实际文件名 的映射（处理 "安燃 .png" 这类带空格的文件名）
        hero_name_map = {}
        for name in dir_heroes:
            hero_name_map[name.strip()] = name

        # 类别颜色（小色块 + 文字）
        category_colors = {'坦克': '#58a6ff', '输出': '#f85149', '辅助': '#3fb950'}

        # 按类别分组显示
        for category in ['坦克', '输出', '辅助']:
            cat_heroes = config.HERO_CATEGORY_TABLE.get(category, [])
            # 取交集：分类表中的英雄 且 在目录中有图片
            available = []
            for h in cat_heroes:
                h_stripped = h.strip()
                if h_stripped in hero_name_map:
                    available.append(hero_name_map[h_stripped])
            # 去重
            seen = set()
            available = [h for h in available if not (h in seen or seen.add(h))]
            if not available:
                continue

            # 类别标题（带色块）
            cat_title = QHBoxLayout()
            cat_title.setSpacing(4)
            cat_title.setContentsMargins(0, 2, 0, 2)
            color_dot = QLabel("●")
            color_dot.setStyleSheet(f"color: {category_colors.get(category, '#8b949e')}; font-size: 11px;")
            cat_title.addWidget(color_dot)
            cat_label = QLabel(f"{category}（{len(available)}）")
            cat_label.setObjectName("section")
            cat_label.setStyleSheet(
                f"color: {category_colors.get(category, '#8b949e')}; "
                "font-size: 11px; font-weight: bold; padding-top: 2px;"
            )
            cat_title.addWidget(cat_label)
            cat_title.addStretch()
            hero_layout.addLayout(cat_title)

            # 网格布局：图片卡片
            grid = QGridLayout()
            grid.setSpacing(3)
            cols = 8
            for i, hero_name in enumerate(available):
                image_path = os.path.join(hero_dir, hero_name + '.png')
                card = HeroCard(hero_name, image_path)
                card.setProperty("hero_name", hero_name)
                card.stateChanged.connect(self._on_hero_selection_changed)
                self.hero_checkboxes[hero_name] = card
                grid.addWidget(card, i // cols, i % cols)
            hero_layout.addLayout(grid)

        layout.addWidget(hero_group)

        # ---- 3. 比例设置（动态显示）----
        self.ratio_group = QGroupBox("比例设置")
        ratio_layout = QVBoxLayout(self.ratio_group)
        self.ratio_avg_btn = QPushButton("一键平均分配")
        self.ratio_avg_btn.setObjectName("secondary")
        self.ratio_avg_btn.clicked.connect(self._on_avg_clicked)
        ratio_layout.addWidget(self.ratio_avg_btn)
        self.ratio_container = QWidget()
        self.ratio_container_layout = QVBoxLayout(self.ratio_container)
        self.ratio_container_layout.setSpacing(4)
        ratio_layout.addWidget(self.ratio_container)
        self.ratio_group.hide()  # 默认隐藏，多选时显示
        layout.addWidget(self.ratio_group)

        # ---- 4. 高级选项 ----
        adv_group = QGroupBox("高级选项")
        adv_layout = QVBoxLayout(adv_group)

        # 鼠标右移速度
        speed_row = QHBoxLayout()
        speed_row.addWidget(QLabel("鼠标右移速度"))
        self.speed_slider = QSlider(Qt.Horizontal)
        self.speed_slider.setMinimum(100)
        self.speed_slider.setMaximum(2000)
        self.speed_slider.setValue(self.config_data.get('mouse_speed', config.MOUSE_MOVE_SPEED))
        self.speed_slider.valueChanged.connect(self._on_speed_changed)
        speed_row.addWidget(self.speed_slider)
        self.speed_value = QLabel(f"{self.speed_slider.value()} px/s")
        self.speed_value.setObjectName("value")
        speed_row.addWidget(self.speed_value)
        adv_layout.addLayout(speed_row)

        # 自动关机选项
        shutdown_row = QHBoxLayout()
        shutdown_row.addWidget(QLabel("自动关机"))
        self.shutdown_combo = QComboBox()
        self.shutdown_combo.addItem("不执行任何操作", "none")
        self.shutdown_combo.addItem("关闭游戏", "stop_only")
        self.shutdown_combo.addItem("关闭计算机", "shutdown")
        self.shutdown_combo.addItem("关闭游戏并关闭计算机", "both")
        # 设置默认值
        default_shutdown = self.config_data.get('auto_shutdown', config.AUTO_SHUTDOWN_DEFAULT)
        for i in range(self.shutdown_combo.count()):
            if self.shutdown_combo.itemData(i) == default_shutdown:
                self.shutdown_combo.setCurrentIndex(i)
                break
        shutdown_row.addWidget(self.shutdown_combo, 1)
        adv_layout.addLayout(shutdown_row)

        # 重置按钮
        reset_btn = QPushButton("重置参数到默认")
        reset_btn.setObjectName("secondary")
        reset_btn.clicked.connect(self._on_reset_clicked)
        adv_layout.addWidget(reset_btn)

        layout.addWidget(adv_group)
        layout.addStretch()

        scroll.setWidget(container)
        return scroll

    def _build_right_panel(self):
        """右侧：实时状态 + 功耗曲线图"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(10)

        # ---- 1. 实时状态卡片 ----
        status_group = QGroupBox("实时状态")
        status_layout = QGridLayout(status_group)
        status_layout.setSpacing(8)

        # 当前操作
        status_layout.addWidget(QLabel("当前操作"), 0, 0)
        self.cur_op_label = QLabel("—")
        self.cur_op_label.setObjectName("value")
        status_layout.addWidget(self.cur_op_label, 0, 1)

        # 下一步操作
        status_layout.addWidget(QLabel("下一步操作"), 1, 0)
        self.next_op_label = QLabel("—")
        self.next_op_label.setObjectName("value")
        status_layout.addWidget(self.next_op_label, 1, 1)

        # 整机功耗
        status_layout.addWidget(QLabel("整机功耗"), 2, 0)
        self.power_label = QLabel("0.0 W")
        self.power_label.setObjectName("value")
        status_layout.addWidget(self.power_label, 2, 1)

        # 已消耗能源
        status_layout.addWidget(QLabel("已消耗能源"), 3, 0)
        self.energy_label = QLabel("0.000 kW·h")
        self.energy_label.setObjectName("value")
        status_layout.addWidget(self.energy_label, 3, 1)

        # 预测总能源
        status_layout.addWidget(QLabel("预测总能源"), 4, 0)
        self.predict_label = QLabel("— kW·h")
        self.predict_label.setObjectName("value")
        status_layout.addWidget(self.predict_label, 4, 1)

        # 当前电价 + 档位 + 自定义输入
        status_layout.addWidget(QLabel("当前电价"), 5, 0)
        tariff_row = QHBoxLayout()
        self.tariff_label = QLabel("获取中...")
        self.tariff_label.setObjectName("value")
        tariff_row.addWidget(self.tariff_label)
        self.tier_combo = QComboBox()
        self.tier_combo.addItem("一档", 1)
        self.tier_combo.addItem("二档", 2)
        self.tier_combo.addItem("三档", 3)
        self.tier_combo.currentIndexChanged.connect(self._on_tier_changed)
        tariff_row.addWidget(self.tier_combo)
        self.tariff_input = QLineEdit()
        self.tariff_input.setPlaceholderText("自定义电价")
        self.tariff_input.setMaximumWidth(100)
        self.tariff_input.textChanged.connect(self._on_tariff_input_changed)
        tariff_row.addWidget(self.tariff_input)
        status_layout.addLayout(tariff_row, 5, 1)

        # 预计开销
        status_layout.addWidget(QLabel("预计开销"), 6, 0)
        self.cost_label = QLabel("0.00 元")
        self.cost_label.setObjectName("value")
        status_layout.addWidget(self.cost_label, 6, 1)

        layout.addWidget(status_group)

        # ---- 2. 功耗曲线图 ----
        chart_group = QGroupBox("功耗曲线（最近 5 分钟）")
        chart_layout = QVBoxLayout(chart_group)

        if CHART_AVAILABLE:
            from PyQt5.QtGui import QPen, QLinearGradient, QGradient, QPainter, QFont
            from PyQt5.QtChart import QAreaSeries

            # 主曲线
            self.power_chart_series = QLineSeries()
            pen = QPen(QColor("#f7931e"))
            pen.setWidth(2)
            pen.setCapStyle(Qt.RoundCap)
            pen.setJoinStyle(Qt.RoundJoin)
            self.power_chart_series.setPen(pen)

            # 区域填充系列（曲线 + X 轴形成的封闭区域）
            self.power_chart_lower = QLineSeries()  # 下边界（0 基线）
            self.power_chart_area = QAreaSeries(self.power_chart_series, self.power_chart_lower)
            # 渐变填充：顶部橙色 → 底部透明
            gradient = QLinearGradient(0, 0, 0, 200)
            gradient.setColorAt(0.0, QColor(247, 147, 30, 180))   # 顶部半透明橙
            gradient.setColorAt(0.6, QColor(247, 147, 30, 60))
            gradient.setColorAt(1.0, QColor(247, 147, 30, 0))     # 底部全透明
            self.power_chart_area.setBrush(QBrush(gradient))
            area_pen = QPen(QColor(247, 147, 30, 120))
            area_pen.setWidth(1)
            self.power_chart_area.setPen(area_pen)

            # 图表
            self.power_chart = QChart()
            self.power_chart.addSeries(self.power_chart_area)
            self.power_chart.addSeries(self.power_chart_series)
            self.power_chart.setTitle("")
            self.power_chart.legend().hide()
            self.power_chart.setMargins(QMargins(4, 4, 4, 4))
            self.power_chart.layout().setContentsMargins(4, 4, 4, 4)

            # X 轴：时间
            axis_x = QDateTimeAxis()
            axis_x.setFormat("HH:mm:ss")
            axis_x.setTitleText("时间")
            axis_x.setLabelsColor(QColor("#8b949e"))
            axis_x.setTitleBrush(QBrush(QColor("#8b949e")))
            axis_x.setLinePenColor(QColor("#30363d"))
            axis_x.setGridLineColor(QColor("#21262d"))
            axis_x.setMinorGridLineColor(QColor("#161b22"))
            self.power_chart.addAxis(axis_x, Qt.AlignBottom)
            self.power_chart_series.attachAxis(axis_x)
            self.power_chart_lower.attachAxis(axis_x)
            self.power_chart_area.attachAxis(axis_x)

            # Y 轴：功率（W）
            axis_y = QValueAxis()
            axis_y.setRange(0, 300)
            axis_y.setTitleText("功率 (W)")
            axis_y.setLabelFormat("%.0f")
            axis_y.setLabelsColor(QColor("#8b949e"))
            axis_y.setTitleBrush(QBrush(QColor("#8b949e")))
            axis_y.setLinePenColor(QColor("#30363d"))
            axis_y.setGridLineColor(QColor("#21262d"))
            axis_y.setMinorGridLineColor(QColor("#161b22"))
            self.power_chart.addAxis(axis_y, Qt.AlignLeft)
            self.power_chart_series.attachAxis(axis_y)
            self.power_chart_lower.attachAxis(axis_y)
            self.power_chart_area.attachAxis(axis_y)

            # 图表背景（透明 + 暗色画布）
            self.power_chart.setBackgroundBrush(QColor("#0d1117"))
            self.power_chart.setBackgroundPen(QPen(Qt.NoPen))
            # 绘图区域背景（略深）
            self.power_chart.setPlotAreaBackgroundBrush(QColor("#010409"))
            self.power_chart.setPlotAreaBackgroundVisible(True)

            # 图表视图（抗锯齿）
            chart_view = QChartView(self.power_chart)
            chart_view.setRenderHint(QPainter.Antialiasing, True)
            chart_view.setRenderHint(QPainter.SmoothPixmapTransform, True)
            chart_view.setMinimumHeight(220)
            chart_layout.addWidget(chart_view)
        else:
            hint = QLabel("⚠️ 未安装 PyQtChart，无法显示图表\n请运行: pip install PyQtChart")
            hint.setStyleSheet("color: #d29922; font-size: 13px;")
            hint.setAlignment(Qt.AlignCenter)
            chart_layout.addWidget(hint)

        layout.addWidget(chart_group, 1)

        return widget

    def _build_control_buttons(self):
        """控制按钮区"""
        layout = QHBoxLayout()
        layout.setSpacing(10)

        # 开始运行
        self.start_btn = QPushButton("▶  开始运行")
        self.start_btn.setMinimumHeight(48)
        self.start_btn.setEnabled(False)
        self.start_btn.setToolTip("请至少选择一个英雄")
        self.start_btn.clicked.connect(self._on_start_clicked)
        layout.addWidget(self.start_btn)

        # 暂停 / 恢复
        self.pause_btn = QPushButton("⏸  暂停")
        self.pause_btn.setObjectName("pauseBtn")
        self.pause_btn.setMinimumHeight(48)
        self.pause_btn.setEnabled(False)
        self.pause_btn.clicked.connect(self._on_pause_clicked)
        layout.addWidget(self.pause_btn)

        # 停止
        self.stop_btn = QPushButton("■  停止")
        self.stop_btn.setObjectName("stopBtn")
        self.stop_btn.setMinimumHeight(48)
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._on_stop_clicked)
        layout.addWidget(self.stop_btn)

        # 自动循环（循环2持续模式）
        self.loop2_btn = QPushButton("🔁  自动循环")
        self.loop2_btn.setObjectName("loop2Btn")
        self.loop2_btn.setMinimumHeight(48)
        self.loop2_btn.setCheckable(True)
        self.loop2_btn.setToolTip("按下后一直运行循环2，再按一次停止")
        self.loop2_btn.clicked.connect(self._on_loop2_clicked)
        layout.addWidget(self.loop2_btn)

        layout.addStretch()

        # Overlay 开关
        self.overlay_check = QCheckBox("显示覆盖层")
        self.overlay_check.setChecked(self.config_data.get('overlay_enabled', True))
        self.overlay_check.stateChanged.connect(self._on_overlay_toggled)
        layout.addWidget(self.overlay_check)

        return layout

    # ==================== 时段/时长同步 ====================

    def _on_start_time_changed(self):
        """改开始时间 → 结束时间 = 开始 + 时长"""
        if self._syncing_time:
            return
        self._syncing_time = True
        duration_s = qtime_to_seconds(self.duration_edit.time())
        new_end = self.start_time_edit.dateTime().addSecs(duration_s)
        self.end_time_edit.setDateTime(new_end)
        self._syncing_time = False

    def _on_end_time_changed(self):
        """改结束时间 → 时长 = 结束 - 开始"""
        if self._syncing_time:
            return
        self._syncing_time = True
        start = self.start_time_edit.dateTime()
        end = self.end_time_edit.dateTime()
        duration_s = start.msecsTo(end) / 1000.0
        if duration_s >= 0:
            self.duration_edit.setTime(seconds_to_qtime(duration_s))
        self._syncing_time = False

    def _on_duration_changed(self):
        """改时长 → 结束时间 = 开始 + 时长"""
        if self._syncing_time:
            return
        self._syncing_time = True
        duration_s = qtime_to_seconds(self.duration_edit.time())
        new_end = self.start_time_edit.dateTime().addSecs(duration_s)
        self.end_time_edit.setDateTime(new_end)
        self._syncing_time = False

    def _on_now_clicked(self):
        """「现在」按钮：开始时间填当前时间"""
        self._syncing_time = True
        now = QDateTime.currentDateTime()
        self.start_time_edit.setDateTime(now)
        duration_s = qtime_to_seconds(self.duration_edit.time())
        new_end = now.addSecs(duration_s)
        self.end_time_edit.setDateTime(new_end)
        self._syncing_time = False

    def _on_unlimited_changed(self, state):
        """无限制模式：禁用三个时间输入框"""
        unlimited = bool(state)
        self.start_time_edit.setEnabled(not unlimited)
        self.end_time_edit.setEnabled(not unlimited)
        self.duration_edit.setEnabled(not unlimited)
        if unlimited:
            logger.warn("已启用无限制模式，将持续运行直到手动停止")

    # ==================== 英雄选择 ====================

    def _on_hero_selection_changed(self):
        """英雄选择变化：更新比例面板 + 开始按钮状态"""
        selected = []
        for hero_name, cb in self.hero_checkboxes.items():
            if cb.isChecked():
                selected.append(hero_name)

        # 更新开始按钮状态（仅非运行时）
        if not (self.worker and self.worker.isRunning()):
            self.start_btn.setEnabled(len(selected) > 0)
        if selected:
            self.start_btn.setToolTip("")
        else:
            self.start_btn.setToolTip("请至少选择一个英雄")

        # 不足 2 个时隐藏比例面板
        if len(selected) <= 1:
            self.ratio_group.hide()
            return

        self.ratio_group.show()

        # 清空旧的比例面板
        while self.ratio_container_layout.count():
            item = self.ratio_container_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self._clear_layout(item.layout())
        self.hero_ratio_sliders.clear()
        self.hero_ratio_labels.clear()

        # 平均分配初始值
        avg = 100 // len(selected)
        for hero in selected:
            row = QHBoxLayout()
            display_name = hero.strip()
            name_label = QLabel(display_name)
            name_label.setMinimumWidth(80)
            row.addWidget(name_label)

            slider = QSlider(Qt.Horizontal)
            slider.setMinimum(0)
            slider.setMaximum(100)
            slider.setValue(avg)
            slider.valueChanged.connect(lambda v, h=hero: self._on_ratio_changed(h, v))
            self.hero_ratio_sliders[hero] = slider
            row.addWidget(slider)

            pct_label = QLabel(f"{avg}%")
            pct_label.setObjectName("value")
            pct_label.setMinimumWidth(50)
            self.hero_ratio_labels[hero] = pct_label
            row.addWidget(pct_label)

            self.ratio_container_layout.addLayout(row)

    def _clear_layout(self, layout):
        """递归清空布局中的所有 widget"""
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self._clear_layout(item.layout())

    def _on_ratio_changed(self, hero, value):
        """调整某个英雄比例：其他英雄按相对比例缩放，保持总和=100%"""
        if self._syncing_ratio:
            return
        self._syncing_ratio = True

        # 更新当前英雄的百分比标签
        pct_label = self.hero_ratio_labels.get(hero)
        if pct_label:
            pct_label.setText(f"{value}%")

        # 其他英雄按相对比例缩放
        other_sliders = {h: s for h, s in self.hero_ratio_sliders.items() if h != hero}
        if other_sliders:
            other_total = sum(s.value() for s in other_sliders.values())
            remaining = 100 - value
            if remaining < 0:
                remaining = 0
            if other_total == 0:
                # 其他全为 0，平均分配剩余
                avg = remaining // len(other_sliders)
                for h, s in other_sliders.items():
                    s.setValue(avg)
            else:
                # 按相对比例缩放
                for h, s in other_sliders.items():
                    new_val = int(s.value() * remaining / other_total)
                    s.setValue(new_val)

        # 更新所有百分比标签
        for h, s in self.hero_ratio_sliders.items():
            pct = self.hero_ratio_labels.get(h)
            if pct:
                pct.setText(f"{s.value()}%")

        self._syncing_ratio = False

    def _on_avg_clicked(self):
        """一键平均分配：所有英雄均分 100/N %"""
        if not self.hero_ratio_sliders:
            return
        self._syncing_ratio = True
        n = len(self.hero_ratio_sliders)
        avg = 100 // n
        remainder = 100 - avg * n
        for i, (h, s) in enumerate(self.hero_ratio_sliders.items()):
            val = avg + (1 if i < remainder else 0)
            s.setValue(val)
            pct = self.hero_ratio_labels.get(h)
            if pct:
                pct.setText(f"{val}%")
        self._syncing_ratio = False

    # ==================== 高级选项 ====================

    def _on_speed_changed(self, val):
        """鼠标速度变化"""
        self.speed_value.setText(f"{val} px/s")

    def _on_reset_clicked(self):
        """重置所有参数到默认值"""
        self.speed_slider.setValue(config.MOUSE_MOVE_SPEED)
        # 关机选项重置到默认
        default_shutdown = config.AUTO_SHUTDOWN_DEFAULT
        for i in range(self.shutdown_combo.count()):
            if self.shutdown_combo.itemData(i) == default_shutdown:
                self.shutdown_combo.setCurrentIndex(i)
                break
        self.unlimited_check.setChecked(False)
        for cb in self.hero_checkboxes.values():
            cb.setChecked(False)
        self.tariff_input.clear()
        self.tier_combo.setCurrentIndex(0)
        # 重置时段
        self._syncing_time = True
        now = QDateTime.currentDateTime()
        self.start_time_edit.setDateTime(now)
        self.end_time_edit.setDateTime(QDateTime.currentDateTime().addSecs(3600))
        self.duration_edit.setTime(seconds_to_qtime(3600))
        self._syncing_time = False
        logger.info("参数已重置到默认值")

    # ==================== 控制按钮 ====================

    def _on_start_clicked(self):
        """开始运行"""
        selected = []
        for hero_name, cb in self.hero_checkboxes.items():
            if cb.isChecked():
                selected.append(hero_name)
        if not selected:
            return

        # 构建英雄比例
        if len(selected) == 1:
            hero_ratios = {selected[0]: 1.0}
        else:
            hero_ratios = {}
            for h in selected:
                slider = self.hero_ratio_sliders.get(h)
                ratio = slider.value() / 100.0 if slider else 1.0 / len(selected)
                hero_ratios[h] = ratio

        hero_selector = HeroSelector(hero_ratios)

        # 计算时长
        if self.unlimited_check.isChecked():
            duration_s = None
        else:
            duration_s = qtime_to_seconds(self.duration_edit.time())

        # 构建选项
        options = {
            'duration_s': duration_s,
            'auto_shutdown': self.shutdown_combo.currentData(),
            'mouse_speed': self.speed_slider.value(),
            'move_duration': config.MOVE_DURATION,
        }

        # 初始化 Clicker
        self.clicker = Clicker()
        if not self.clicker.find_window():
            QMessageBox.warning(self, "错误", "未找到 Overwatch 窗口")
            return
        if not self.clicker.init_camera():
            QMessageBox.warning(self, "错误", "摄像头初始化失败")
            return

        # 初始化键盘驱动
        self.keyboard = DriverKeyboard()
        kb_ok, kb_msg = self.keyboard.init()
        if not kb_ok:
            logger.warn(f"键盘驱动初始化失败: {kb_msg}")

        # 初始化鼠标驱动
        self.mouse_driver = DriverClicker()
        md_ok, md_msg = self.mouse_driver.init()
        if not md_ok:
            logger.warn(f"鼠标驱动初始化失败: {md_msg}")

        # 将鼠标驱动共享给 clicker，使其 click() 能进行驱动级点击
        self.clicker.driver = self.mouse_driver
        self.clicker.use_driver = self.mouse_driver.available
        if self.clicker.use_driver:
            logger.info("Clicker 驱动级点击已启用")
        else:
            logger.warn("Clicker 驱动级点击不可用，将回退到 SendInput（游戏内可能无效）")

        # 启动 worker 子线程
        self.worker = FlowWorker(
            self.clicker, self.keyboard, self.mouse_driver, hero_selector, options
        )
        self.worker.state_signal.connect(self._on_state_change)
        self.worker.log_signal.connect(self._on_log_signal)
        self.worker.overlay_signal.connect(self._on_overlay_signal)
        self.worker.finish_signal.connect(self._on_flow_finish)
        self.worker.start()

        # UI 状态更新
        self.start_btn.setEnabled(False)
        self.start_btn.setText("运行中...")
        self.pause_btn.setEnabled(True)
        self.pause_btn.setText("⏸  暂停")
        self.stop_btn.setEnabled(True)
        self._set_lock_state(True)
        self.status_label.setText("状态: 运行中")
        self.status_label.setStyleSheet("color: #2ea043; font-size: 14px; padding: 4px 8px;")

    def _on_pause_clicked(self):
        """暂停 / 恢复"""
        if not self.worker:
            return
        if self.pause_btn.text().startswith("⏸"):
            self.worker.pause()
            self.pause_btn.setText("▶  恢复")
            self.status_label.setText("状态: 已暂停")
            self.status_label.setStyleSheet("color: #d29922; font-size: 14px; padding: 4px 8px;")
        else:
            self.worker.resume()
            self.pause_btn.setText("⏸  暂停")
            self.status_label.setText("状态: 运行中")
            self.status_label.setStyleSheet("color: #2ea043; font-size: 14px; padding: 4px 8px;")

    def _on_stop_clicked(self):
        """停止运行"""
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.worker.wait(3000)
        self._on_flow_finish()

    def _on_loop2_clicked(self):
        """自动循环（循环2持续模式）：按下启动，再按一次停止"""
        if self.loop2_btn.isChecked():
            # 启动循环2
            if not self._start_loop2():
                self.loop2_btn.setChecked(False)
        else:
            # 停止循环2
            self._stop_loop2()

    def _start_loop2(self):
        """启动循环2持续模式"""
        if self.worker and self.worker.isRunning():
            QMessageBox.warning(self, "提示", "请先停止当前运行的流程")
            return False

        # 初始化 Clicker
        self.clicker = Clicker()
        if not self.clicker.find_window():
            QMessageBox.warning(self, "错误", "未找到 Overwatch 窗口")
            return False
        if not self.clicker.init_camera():
            QMessageBox.warning(self, "错误", "摄像头初始化失败")
            return False

        # 初始化键盘驱动
        self.keyboard = DriverKeyboard()
        kb_ok, kb_msg = self.keyboard.init()
        if not kb_ok:
            logger.warn(f"键盘驱动初始化失败: {kb_msg}")

        # 初始化鼠标驱动
        self.mouse_driver = DriverClicker()
        md_ok, md_msg = self.mouse_driver.init()
        if not md_ok:
            logger.warn(f"鼠标驱动初始化失败: {md_msg}")

        self.clicker.driver = self.mouse_driver
        self.clicker.use_driver = self.mouse_driver.available

        # 构建选项
        options = {
            'duration_s': None,
            'auto_shutdown': 'none',
            'mouse_speed': self.speed_slider.value(),
            'move_duration': config.MOVE_DURATION,
        }

        # 启动循环2子线程
        self.loop2_worker = Loop2Worker(
            self.clicker, self.keyboard, self.mouse_driver, options
        )
        self.loop2_worker.log_signal.connect(self._on_log_signal)
        self.loop2_worker.finish_signal.connect(self._on_loop2_finish)
        self.loop2_worker.start()

        self.loop2_btn.setText("⏹  停止循环")
        self.status_label.setText("状态: 循环2运行中")
        self.status_label.setStyleSheet("color: #8957e5; font-size: 14px; padding: 4px 8px;")
        self._set_lock_state(True)
        return True

    def _stop_loop2(self):
        """停止循环2持续模式"""
        if self.loop2_worker and self.loop2_worker.isRunning():
            self.loop2_worker.stop()
            self.loop2_worker.wait(3000)

    def _on_loop2_finish(self):
        """循环2结束回调"""
        self.loop2_btn.setChecked(False)
        self.loop2_btn.setText("🔁  自动循环")
        self.status_label.setText("状态: 已停止")
        self.status_label.setStyleSheet("color: #6e7681; font-size: 14px; padding: 4px 8px;")
        self._set_lock_state(False)
        # 清理 Clicker 和驱动
        if self.clicker:
            try:
                self.clicker.use_driver = False
                self.clicker.driver = None
                if self.clicker.camera:
                    try:
                        self.clicker.camera.stop()
                    except Exception:
                        pass
                    del self.clicker.camera
                    self.clicker.camera = None
            except Exception:
                pass
            self.clicker = None
        if self.keyboard:
            self.keyboard.destroy()
            self.keyboard = None
        if self.mouse_driver:
            self.mouse_driver.destroy()
            self.mouse_driver = None

    def _on_flow_finish(self):
        """流程结束回调"""
        self.start_btn.setEnabled(True)
        self.start_btn.setText("▶  开始运行")
        self.pause_btn.setEnabled(False)
        self.pause_btn.setText("⏸  暂停")
        self.stop_btn.setEnabled(False)
        self._set_lock_state(False)
        self.status_label.setText("状态: 已停止")
        self.status_label.setStyleSheet("color: #6e7681; font-size: 14px; padding: 4px 8px;")
        # 更新开始按钮可用性（取决于是否有选中英雄）
        selected = [h for h, cb in self.hero_checkboxes.items() if cb.isChecked()]
        self.start_btn.setEnabled(len(selected) > 0)
        # 清理 Clicker（含 dxcam）— 必须先清理 clicker 再清理 mouse_driver，
        # 因为 clicker 持有 mouse_driver 的引用，若先 destroy mouse_driver 再访问 clicker.driver 会崩溃
        if self.clicker:
            try:
                # 先解除 clicker 对 mouse_driver 的引用，避免悬空指针
                self.clicker.use_driver = False
                self.clicker.driver = None
                # 停止 dxcam 连续捕获（在子线程创建，需小心）
                if self.clicker.camera:
                    try:
                        self.clicker.camera.stop()
                    except Exception:
                        pass
                    try:
                        del self.clicker.camera
                    except Exception:
                        pass
                    self.clicker.camera = None
            except Exception as e:
                logger.warn(f"清理 Clicker 异常: {e}")
            self.clicker = None
        # 清理驱动上下文
        if self.keyboard:
            self.keyboard.destroy()
            self.keyboard = None
        if self.mouse_driver:
            self.mouse_driver.destroy()
            self.mouse_driver = None

    def _set_lock_state(self, locked):
        """流程启动后部分锁定：英雄选择/时段/关机选项禁用"""
        for cb in self.hero_checkboxes.values():
            cb.setEnabled(not locked)
        self.unlimited_check.setEnabled(not locked)
        self.start_time_edit.setEnabled(not locked and not self.unlimited_check.isChecked())
        self.end_time_edit.setEnabled(not locked and not self.unlimited_check.isChecked())
        self.duration_edit.setEnabled(not locked and not self.unlimited_check.isChecked())
        self.shutdown_combo.setEnabled(not locked)
        # 速度可改但生效需重启
        self.speed_slider.setEnabled(True)

    # ==================== 状态回调 ====================

    def _on_state_change(self, state_value, cur, nxt):
        """FlowEngine 状态变化"""
        self.cur_op_label.setText(cur)
        self.next_op_label.setText(nxt)

    def _on_log_signal(self, level, message):
        """FlowEngine 日志信号（Logger 回调已处理显示，此处无需重复）"""
        pass

    def _on_overlay_signal(self, x, y, w, h, name, step, next_step, conf):
        """Overlay 信号：发送到 overlay 子进程（复用 socket 提升性能）"""
        try:
            if not hasattr(self, '_overlay_sock') or self._overlay_sock is None:
                self._overlay_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            msg = f"{int(x)} {int(y)} {int(w)} {int(h)}|{name}|{step}|{next_step}|{conf:.3f}"
            self._overlay_sock.sendto(msg.encode(), (config.OVERLAY_HOST, config.OVERLAY_PORT))
        except Exception as e:
            # 仅在调试时打印，避免刷屏
            if not hasattr(self, '_overlay_err_logged') or not self._overlay_err_logged:
                logger.debug(f"overlay 发送失败: {e}")
                self._overlay_err_logged = True

    def _on_log_callback(self, level, message, timestamp):
        """Logger 回调（可能来自子线程，用 QTimer.singleShot 转发到主线程）"""
        QTimer.singleShot(0, lambda: self._append_log(level, message, timestamp))

    def _append_log(self, level, message, timestamp):
        """追加日志到日志区（主线程）"""
        color = LEVEL_COLORS.get(level, "#c9d1d9")
        # HTML 转义
        safe_msg = message.replace("<", "&lt;").replace(">", "&gt;")
        self.log_text.append(
            f'<span style="color:{color}">[{timestamp}] [{level}] {safe_msg}</span>'
        )
        # 限制最近 50 条
        doc = self.log_text.document()
        if doc.blockCount() > 50:
            cursor = self.log_text.textCursor()
            cursor.movePosition(cursor.Start)
            cursor.movePosition(cursor.Down, cursor.KeepAnchor, doc.blockCount() - 50)
            cursor.removeSelectedText()

    # ==================== UI 定时刷新 ====================

    def _update_ui(self):
        """200ms 定时刷新所有状态字段"""
        # 功耗
        power = self.power_monitor.get_current_power()
        self.power_label.setText(f"{power:.1f} W")

        # 已消耗能源（6 位小数，短时间也能看到变化）
        energy = self.power_monitor.get_total_energy()
        self.energy_label.setText(f"{energy:.6f} kW·h")

        # 预测总能源
        if self.unlimited_check.isChecked():
            predict = self.power_monitor.predict_hourly_energy()
            self.predict_label.setText(f"{predict:.3f} kW·h/h（每小时预估）")
        else:
            duration_s = qtime_to_seconds(self.duration_edit.time())
            predict = self.power_monitor.predict_total_energy(duration_s)
            self.predict_label.setText(f"{predict:.3f} kW·h")

        # 电价 + 开销（基于预测总能源，修改时长会立即影响预计开销）
        tariff = self._get_current_tariff()
        if tariff is not None and tariff > 0:
            # 预计开销 = 预测总能源 × 电价
            cost = predict * tariff
            self.cost_label.setText(f"{cost:.4f} 元")
        else:
            self.cost_label.setText("—")

        # 功耗曲线图：每 1 秒添加一个数据点
        if self.power_chart_series is not None:
            now = time.time()
            if now - self._last_chart_time >= 1.0:
                self._last_chart_time = now
                now_ms = QDateTime.currentMSecsSinceEpoch()
                self.power_chart_series.append(now_ms, power)
                # 下边界同步（保持 0 基线，用于 QAreaSeries 填充）
                if hasattr(self, 'power_chart_lower') and self.power_chart_lower is not None:
                    self.power_chart_lower.append(now_ms, 0)
                # 保留最近 5 分钟数据（300 个点 × 1 秒）
                while self.power_chart_series.count() > 300:
                    self.power_chart_series.remove(0)
                    if hasattr(self, 'power_chart_lower') and self.power_chart_lower is not None:
                        self.power_chart_lower.remove(0)
                # 调整 X 轴范围（最近 5 分钟）
                if self.power_chart:
                    axes_x = self.power_chart.axes(Qt.Horizontal)
                    if axes_x:
                        axis_x = axes_x[0]
                        axis_x.setRange(
                            QDateTime.fromMSecsSinceEpoch(now_ms - 300000),
                            QDateTime.fromMSecsSinceEpoch(now_ms)
                        )
                    # Y 轴自适应（基于数据最大值，至少留 20% 余量）
                    axes_y = self.power_chart.axes(Qt.Vertical)
                    if axes_y:
                        axis_y = axes_y[0]
                        # 计算最近数据最大值
                        max_val = power
                        for i in range(self.power_chart_series.count()):
                            v = self.power_chart_series.at(i).y()
                            if v > max_val:
                                max_val = v
                        # 上限：max_val × 1.25，至少 100W
                        upper = max(max_val * 1.25, 100)
                        # 取整到 50 的倍数
                        upper = int((upper + 49) // 50 * 50)
                        axis_y.setRange(0, upper)

    def _get_current_tariff(self):
        """获取当前电价：优先用户自定义输入 > 查表 > 默认电价

        返回:
            float: 电价（元/kW·h）
            None: 无可用电价
        """
        # 1. 优先用户自定义输入
        custom = self.tariff_input.text().strip()
        if custom:
            try:
                price = float(custom)
                if price > 0:
                    return price
            except ValueError:
                pass

        # 2. 查表（含档位切换）
        if self.tariff:
            province, price, _ = self.tariff
            if province and province != "默认":
                tier = self.tier_combo.currentData()
                looked = lookup_tariff(province, tier=tier)
                if looked is not None:
                    return looked
            # 3. 回退到已获取的电价
            if price is not None:
                return price

        # 4. 最终回退默认电价
        return DEFAULT_TARIFF

    # ==================== 电价获取 ====================

    def _fetch_tariff_async(self):
        """异步获取电价（子线程）
        调用 get_tariff_with_cache：联网 → 缓存 → 默认电价三级回退
        """
        try:
            province, price, source = get_tariff_with_cache(tier=1)
            if price is not None:
                self.tariff = (province, price, source)
                QTimer.singleShot(0, self._update_tariff_display)
            else:
                QTimer.singleShot(0, lambda: self.tariff_label.setText("获取失败，请输入电价"))
        except Exception as e:
            QTimer.singleShot(0, lambda: self.tariff_label.setText(f"获取失败: {e}"))

    def _update_tariff_display(self):
        """更新电价显示（含来源标识）"""
        if not self.tariff:
            return
        province, price, source = self.tariff
        # 来源标识：网络获取无后缀，缓存显示"（缓存）"，默认显示"（默认）"
        source_str = ""
        if source == "cache":
            source_str = "（缓存）"
        elif source == "default":
            source_str = "（默认）"
        tier = self.tier_combo.currentData()
        self.tariff_label.setText(
            f"{province} 第{tier}档 {price:.4f} 元/kW·h{source_str}"
        )

    def _on_tier_changed(self):
        """档位变化：重新查表并更新显示"""
        if not self.tariff:
            return
        province, _, source = self.tariff
        tier = self.tier_combo.currentData()
        # 重新按新档位查表
        price = lookup_tariff(province, tier=tier)
        if price is not None:
            self.tariff = (province, price, source)
            self._update_tariff_display()
        else:
            # 该省份无此档位数据，保留原价
            self._update_tariff_display()

    def _on_tariff_input_changed(self, text):
        """用户输入自定义电价（实时覆盖查表结果）"""
        text = text.strip()
        if text:
            try:
                custom_price = float(text)
                if custom_price > 0:
                    logger.info(f"用户自定义电价: {custom_price} 元/kW·h")
            except ValueError:
                pass

    # ==================== 驱动管理 ====================

    def _check_driver(self):
        """检测驱动状态（三态：未安装/已安装需重启/已加载）"""
        if not is_driver_installed():
            self.driver_status_label.setText("驱动: 未安装")
            self.driver_status_label.setStyleSheet(
                "color: #da3633; font-size: 13px; font-weight: bold;"
            )
            self.driver_btn.setText("安装驱动")
        elif not is_driver_loaded():
            self.driver_status_label.setText("驱动: 已安装 ⚠️需重启")
            self.driver_status_label.setStyleSheet(
                "color: #d29922; font-size: 13px; font-weight: bold;"
            )
            self.driver_btn.setText("重新安装")
        else:
            self.driver_status_label.setText("驱动: 已加载 ✅")
            self.driver_status_label.setStyleSheet(
                "color: #2ea043; font-size: 13px; font-weight: bold;"
            )
            self.driver_btn.setText("重新安装")

    def _install_driver(self):
        """安装驱动（子线程）"""
        self.driver_btn.setEnabled(False)
        self.driver_btn.setText("安装中...")

        def run():
            ok, msg = install_driver()
            QTimer.singleShot(0, lambda: self._on_driver_installed(ok, msg))

        t = threading.Thread(target=run, daemon=True)
        t.start()

    def _on_driver_installed(self, ok, msg):
        """驱动安装完成回调"""
        self.driver_btn.setEnabled(True)
        if ok:
            QMessageBox.information(self, "驱动安装", msg)
        else:
            QMessageBox.warning(self, "安装失败", msg)
        self._check_driver()

    def _check_deps(self):
        """检测依赖状态，全部已安装则按钮显示 √"""
        from bootstrap import check_missing_required, check_missing_optional
        missing = check_missing_required() + check_missing_optional()
        if missing:
            self.deps_btn.setText("安装依赖")
            self.deps_btn.setEnabled(True)
        else:
            self.deps_btn.setText("√ 依赖已安装")
            self.deps_btn.setEnabled(False)

    def _install_deps(self):
        """一键安装所有缺失依赖（必需 + 可选），日志区显示每个依赖的进度条"""
        from bootstrap import (
            check_missing_required, check_missing_optional,
            install_package, is_package_installed
        )
        missing = check_missing_required() + check_missing_optional()
        if not missing:
            QMessageBox.information(self, "依赖检查", "所有依赖已安装，无需操作。")
            return

        names = [p[0] for p in missing]
        reply = QMessageBox.question(
            self, "安装依赖",
            f"检测到缺失 {len(missing)} 个依赖：\n  "
            + "\n  ".join(names)
            + "\n\n是否立即联网安装？",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        # 准备进度条 UI：每个依赖一行（标签 + 进度条）
        # 清空旧内容
        layout = self.deps_progress_widget.layout()
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        # 为每个依赖创建一行
        progress_bars = {}  # pip_name -> (QProgressBar, QLabel)
        for pip_name, _ in missing:
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(6)
            label = QLabel(f"⏳ {pip_name}")
            label.setFixedWidth(140)
            label.setStyleSheet("color: #c9d1d9; font-size: 11px;")
            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setValue(0)
            bar.setFixedHeight(12)
            bar.setTextVisible(False)
            row_layout.addWidget(label)
            row_layout.addWidget(bar, 1)
            layout.addWidget(row)
            progress_bars[pip_name] = (bar, label)
        self.deps_progress_widget.setVisible(True)

        self.deps_btn.setEnabled(False)
        total = len(missing)

        def run():
            failed = []
            for i, (pip_name, module_name) in enumerate(missing):
                # 更新按钮文字
                QTimer.singleShot(0, lambda i=i, pip_name=pip_name:
                    self.deps_btn.setText(f"安装中 {i+1}/{total}: {pip_name}"))
                logger.info(f"[{i+1}/{total}] 正在安装 {pip_name}...")
                # 安装过程（pip 输出实时解析进度）
                ok, output = self._install_with_progress(pip_name, progress_bars[pip_name])
                if ok and is_package_installed(module_name):
                    QTimer.singleShot(0, lambda pn=pip_name:
                        progress_bars[pn][1].setText(f"✓ {pn}"))
                    # 进度条设为 100% 绿色
                    bar, _ = progress_bars[pip_name]
                    QTimer.singleShot(0, lambda b=bar:
                        (b.setValue(100),
                         b.setStyleSheet("QProgressBar {{ border-radius: 6px; background-color: #21262d; border: 1px solid #2ea043; } QProgressBar::chunk {{ background-color: #2ea043; border-radius: 5px; }} }")))
                    logger.info(f"✓ {pip_name} 安装成功")
                else:
                    failed.append(pip_name)
                    bar, _ = progress_bars[pip_name]
                    QTimer.singleShot(0, lambda b=bar, pn=pip_name:
                        (progress_bars[pn][1].setText(f"✗ {pn}"),
                         b.setValue(100),
                         b.setStyleSheet("QProgressBar {{ border-radius: 6px; background-color: #21262d; border: 1px solid #da3633; } QProgressBar::chunk {{ background-color: #da3633; border-radius: 5px; }} }")))
                    logger.error(f"✗ {pip_name} 安装失败")
            QTimer.singleShot(0, lambda: self._on_deps_installed(failed, names))

        t = threading.Thread(target=run, daemon=True)
        t.start()

    def _install_with_progress(self, pip_name, progress_info):
        """安装单个包并实时更新进度条

        通过 subprocess.Popen 逐行读取 pip 输出，
        检测 'Downloading' 行的百分比更新进度条。
        """
        import subprocess
        cmd = [sys.executable, "-m", "pip", "install", "--progress-bar", "on", pip_name]
        try:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace", bufsize=1
            )
            bar, label = progress_info
            last_pct = 0
            for line in proc.stdout:
                line = line.rstrip()
                # 解析 pip 的进度行，如 "Downloading numpy-1.24.0-cp310... |██████████--| 78% 1.2MB/s"
                if "Downloading" in line and "%" in line:
                    try:
                        pct_str = line.split("%")[0].rsplit("|", 1)[-1].strip()
                        pct = int(pct_str)
                        if pct > last_pct:
                            last_pct = pct
                            QTimer.singleShot(0, lambda p=pct, b=bar: b.setValue(p))
                    except (ValueError, IndexError):
                        pass
            proc.wait(timeout=180)
            return proc.returncode == 0, ""
        except subprocess.TimeoutExpired:
            proc.kill()
            return False, f"安装超时"
        except Exception as e:
            return False, f"安装异常：{e}"

    def _on_deps_installed(self, failed, all_names):
        """依赖安装完成回调"""
        self.deps_btn.setEnabled(True)
        if not failed:
            self.deps_btn.setText("√ 依赖已安装")
            self.deps_btn.setEnabled(False)
            QMessageBox.information(
                self, "依赖安装",
                "所有依赖安装完成！\n建议重启程序以加载新依赖。"
            )
        else:
            self.deps_btn.setText("安装依赖")
            self.deps_btn.setEnabled(True)
            QMessageBox.warning(
                self, "依赖安装",
                f"以下依赖安装失败：\n  " + "\n  ".join(failed)
                + "\n\n建议手动执行：\n  pip install -r requirements.txt"
            )

    # ==================== 无边框窗口拖拽 ====================

    def _toggle_maximize(self):
        """切换最大化/还原"""
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def mousePressEvent(self, event):
        """鼠标按下：开始拖拽窗口（仅在标题栏区域）"""
        if event.button() == Qt.LeftButton:
            # 检查是否在标题栏区域（顶部 40px）
            if event.pos().y() <= 40:
                self._dragging = True
                self._drag_offset = event.globalPos() - self.frameGeometry().topLeft()
                event.accept()

    def mouseMoveEvent(self, event):
        """鼠标移动：拖拽窗口"""
        if self._dragging and event.buttons() & Qt.LeftButton:
            self.move(event.globalPos() - self._drag_offset)
            event.accept()

    def mouseReleaseEvent(self, event):
        """鼠标释放：结束拖拽"""
        if self._dragging:
            self._dragging = False
            event.accept()

    # ==================== Overlay 子进程 ====================

    def _on_overlay_toggled(self, state):
        """Overlay 开关"""
        if state:
            self._start_overlay()
        else:
            self._stop_overlay()

    def _start_overlay(self):
        """启动 overlay 子进程"""
        base_dir = os.path.dirname(os.path.abspath(__file__))
        venv_python = os.path.join(base_dir, ".venv", "Scripts", "python.exe")
        if not os.path.exists(venv_python):
            venv_python = sys.executable
        overlay_script = os.path.join(base_dir, "overlay.py")
        if not os.path.exists(overlay_script):
            logger.warn(f"overlay.py 不存在: {overlay_script}")
            return
        try:
            # 传入父进程 PID，overlay 会监控父进程退出并自动关闭
            creationflags = 0x08000000 if sys.platform == "win32" else 0  # CREATE_NO_WINDOW
            self.overlay_process = subprocess.Popen(
                [venv_python, "-u", overlay_script, str(os.getpid())],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=creationflags
            )
            # 等 500ms 看进程是否立即崩溃
            time.sleep(0.5)
            if self.overlay_process.poll() is not None:
                logger.error(f"Overlay 启动后崩溃 (exit={self.overlay_process.returncode})")
                self.overlay_process = None
            else:
                logger.info(f"Overlay 子进程已启动 (PID={self.overlay_process.pid})")
        except Exception as e:
            logger.error(f"启动 overlay 失败: {e}")

    def _stop_overlay(self):
        """停止 overlay 子进程（terminate → wait → kill 三重保证）"""
        if self.overlay_process:
            proc = self.overlay_process
            self.overlay_process = None
            # 1. terminate（SIGTERM 等价）
            try:
                proc.terminate()
                proc.wait(2000)
            except Exception:
                pass
            # 2. 若仍存活，kill（SIGKILL 等价）
            try:
                if proc.poll() is None:  # 仍在运行
                    proc.kill()
                    proc.wait(2000)
            except Exception:
                pass
            # 3. 最终兜底：直接 taskkill /F /PID 强杀
            try:
                if proc.poll() is None:
                    import subprocess as _sp
                    _sp.run(["taskkill", "/F", "/PID", str(proc.pid)],
                            capture_output=True, timeout=5)
            except Exception:
                pass
            logger.info("Overlay 子进程已停止")

    # ==================== F8 全局热键 ====================

    def _register_hotkey(self):
        """注册 F8 全局热键（RegisterHotKey + nativeEvent 捕获）"""
        try:
            # F8 = 0x77, MOD_NONE = 0
            result = ctypes.windll.user32.RegisterHotKey(
                int(self.winId()), self._hotkey_id, 0, 0x77
            )
            if result:
                logger.info("F8 全局热键已注册（紧急停止）")
            else:
                logger.warn("F8 全局热键注册失败（可能已被其他程序占用）")
        except Exception as e:
            logger.warn(f"注册 F8 失败: {e}")

    def nativeEvent(self, eventType, message):
        """捕获 Windows 消息（用于 F8 全局热键）"""
        # 注意: PyQt5 在 Windows 上 eventType 是 bytes 类型 (b"windows_generic_MSG")
        if eventType == b"windows_generic_MSG" or eventType == "windows_generic_MSG":
            try:
                msg = wintypes.MSG.from_address(int(message))
                if msg.message == 0x0312:  # WM_HOTKEY
                    if msg.wParam == self._hotkey_id:
                        logger.warn("F8 紧急停止！")
                        # 停止 FlowEngine
                        if self.worker and self.worker.isRunning():
                            self.worker.stop()
                        # 停止 PowerMonitor
                        self.power_monitor.stop()
                        return True, 0
            except Exception:
                pass
        return super().nativeEvent(eventType, message)

    # ==================== 配置持久化 ====================

    def _load_config(self):
        """从 config.json 加载持久化配置"""
        self.config_data = {}
        config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), config.CONFIG_PERSIST_FILE)
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                self.config_data = json.load(f)
        except Exception:
            self.config_data = {}

    def _save_config(self):
        """保存配置到 config.json"""
        data = {
            'overlay_enabled': self.overlay_check.isChecked() if hasattr(self, 'overlay_check') else True,
            'mouse_speed': self.speed_slider.value() if hasattr(self, 'speed_slider') else config.MOUSE_MOVE_SPEED,
            'auto_shutdown': self.shutdown_combo.currentData() if hasattr(self, 'shutdown_combo') else config.AUTO_SHUTDOWN_DEFAULT,
            'unlimited_mode': self.unlimited_check.isChecked() if hasattr(self, 'unlimited_check') else False,
            'selected_heroes': [h for h, cb in self.hero_checkboxes.items() if cb.isChecked()],
            'hero_ratios': {h: s.value() for h, s in self.hero_ratio_sliders.items()},
            'tariff_tier': self.tier_combo.currentData() if hasattr(self, 'tier_combo') else 1,
            'custom_tariff': self.tariff_input.text() if hasattr(self, 'tariff_input') else '',
        }
        config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), config.CONFIG_PERSIST_FILE)
        try:
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存配置失败: {e}")

    def _restore_config_to_ui(self):
        """启动时从持久化配置恢复 UI 状态"""
        cfg = self.config_data

        # 1. 恢复英雄选择（在 _on_hero_selection_changed 触发前批量设置）
        selected = cfg.get('selected_heroes', [])
        # 临时断开信号，避免逐个勾选时触发 _on_hero_selection_changed
        for name, cb in self.hero_checkboxes.items():
            cb.blockSignals(True)
            cb.setChecked(name in selected)
            cb.blockSignals(False)
        # 主动触发一次 selection changed 以更新比例面板
        if selected:
            self._on_hero_selection_changed()

        # 2. 恢复英雄比例（在 _on_hero_selection_changed 创建滑块之后）
        ratios = cfg.get('hero_ratios', {})
        if ratios:
            self._syncing_ratio = True
            for name, slider in self.hero_ratio_sliders.items():
                if name in ratios:
                    # _save_config 存储的是 slider.value()（0-100 的百分比），直接恢复
                    val = max(0, min(100, int(ratios[name])))
                    slider.setValue(val)
            # 更新百分比标签
            for name, slider in self.hero_ratio_sliders.items():
                if name in self.hero_ratio_labels:
                    self.hero_ratio_labels[name].setText(f"{slider.value()}%")
            self._syncing_ratio = False

        # 3. 恢复无限制模式
        if 'unlimited_mode' in cfg:
            self.unlimited_check.blockSignals(True)
            self.unlimited_check.setChecked(cfg['unlimited_mode'])
            self.unlimited_check.blockSignals(False)
            # 手动调用以同步禁用状态
            self._on_unlimited_changed(cfg['unlimited_mode'])

        # 4. 恢复电价档位
        if 'tariff_tier' in cfg:
            idx = max(0, min(2, int(cfg['tariff_tier']) - 1))
            self.tier_combo.setCurrentIndex(idx)

        # 5. 恢复自定义电价
        if 'custom_tariff' in cfg and cfg['custom_tariff']:
            self.tariff_input.setText(str(cfg['custom_tariff']))

    # ==================== 关闭事件 ====================

    def closeEvent(self, event):
        """关闭窗口：停止所有子线程/子进程并保存配置"""
        # 停止 FlowEngine
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.worker.wait(3000)
        # 停止功耗监控
        self.power_monitor.stop()
        # 停止 overlay 子进程（三重保证：terminate → kill → taskkill）
        self._stop_overlay()
        # 注销全局热键
        try:
            ctypes.windll.user32.UnregisterHotKey(int(self.winId()), self._hotkey_id)
        except Exception:
            pass
        # 保存配置
        self._save_config()
        # 关闭 logger
        logger.close()
        event.accept()
        # 最终兜底：递归终止所有由本进程派生的子进程（含 overlay、driver 安装等）
        try:
            import psutil
            parent = psutil.Process(os.getpid())
            children = parent.children(recursive=True)
            for child in children:
                try:
                    child.terminate()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            # 等待 2 秒让子进程优雅退出
            _, alive = psutil.wait_procs(children, timeout=2)
            # 仍存活的强杀
            for child in alive:
                try:
                    child.kill()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
        except Exception:
            pass


# ========== 入口 ==========
if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setWindowIcon(_create_app_icon())
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())
