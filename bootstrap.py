# bootstrap.py
"""
首次启动引导：
- 检测依赖完整性
- 自动 pip install 缺失的依赖
- 首次运行提醒用户保持联网以使用完整功能

仅依赖 Python 标准库（ctypes / importlib / subprocess / os / sys），
在 PyQt5 等第三方包未安装时也能正常工作。
"""
import os
import sys
import subprocess
import importlib.util
import ctypes
import threading
from ctypes import wintypes, c_int, c_uint, c_void_p, c_long, c_ulong, c_short, c_ushort

# 项目根目录
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# 首次运行完成标记文件
MARKER_FILE = os.path.join(BASE_DIR, ".bootstrap_done")

# ===== 依赖清单 =====
# (pip 包名, 检测用的 import 模块名, 是否必需)
REQUIRED_PACKAGES = [
    ("PyQt5", "PyQt5", True),
    ("PyQtChart", "PyQt5.QtChart", True),
    ("opencv-python", "cv2", True),
    ("numpy", "numpy", True),
    ("dxcam", "dxcam", True),
    ("pywin32", "win32gui", True),
    ("psutil", "psutil", True),
    ("requests", "requests", True),
]

OPTIONAL_PACKAGES = [
    ("pythonnet", "clr", False),
    ("interception", "interception", False),
]


# ==================== 辅助函数 ====================

def is_package_installed(module_name):
    """检测模块是否可导入"""
    try:
        return importlib.util.find_spec(module_name) is not None
    except (ImportError, ModuleNotFoundError):
        return False
    except Exception:
        return False


def is_first_run():
    """是否首次运行（标记文件不存在）"""
    return not os.path.exists(MARKER_FILE)


def mark_bootstrap_done():
    """写入标记文件"""
    try:
        with open(MARKER_FILE, "w", encoding="utf-8") as f:
            f.write("bootstrap complete\n")
    except Exception:
        pass


def show_message(title, text, flags=0x40):
    """
    Win32 MessageBox（仅依赖 ctypes）。
    flags 常用值：
      0x40 = MB_ICONINFORMATION（信息提示）
      0x30 = MB_ICONWARNING（警告）
      0x10 = MB_ICONERROR（错误）
      0x34 = MB_YESNO | MB_ICONWARNING（是/否 + 警告图标）
      返回：6 = IDYES, 7 = IDNO, 1 = IDOK
    """
    try:
        return ctypes.windll.user32.MessageBoxW(0, text, title, flags)
    except Exception:
        # 极端情况下连 ctypes 都不可用，仅打印到控制台
        print(f"[{title}] {text}")
        return 6  # 默认按「是」


# ==================== 进度条窗口（Win32 API）====================

# Win32 常量
_WS_VISIBLE = 0x10000000
_WS_CHILD = 0x40000000
_WS_CAPTION = 0x00C00000
_WS_SYSMENU = 0x00080000
_WS_EX_TOOLWINDOW = 0x00000080
_WS_EX_APPWINDOW = 0x00040000
_PBS_SMOOTH = 0x01
_WM_DESTROY = 0x0002
_WM_CLOSE = 0x0010
_WM_PAINT = 0x000F
_PBM_SETPOS = 0x0402
_PBM_SETRANGE32 = 0x0406
_PBM_SETSTEP = 0x0404
_PBM_STEPIT = 0x0405
_COLOR_BTNFACE = 15
_SS_CENTER = 0x00000001

# 注册窗口类用的结构
class WNDCLASS(ctypes.Structure):
    _fields_ = [
        ("style", c_uint),
        ("lpfnWndProc", c_void_p),
        ("cbClsExtra", c_int),
        ("cbWndExtra", c_int),
        ("hInstance", c_void_p),
        ("hIcon", c_void_p),
        ("hCursor", c_void_p),
        ("hbrBackground", c_void_p),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    ]


class ProgressWindow:
    """
    用 Win32 API 创建的简单进度条窗口。
    包含：标题标签 + 进度条 + 状态文字。
    在子线程跑消息循环，主线程可调用 update() 更新进度。
    """

    def __init__(self, title="安装进度", total=100):
        self.title = title
        self.total = max(1, int(total))
        self._hwnd = None
        self._label_hwnd = None
        self._progress_hwnd = None
        self._status_hwnd = None
        self._thread = None
        self._running = False
        self._closed_by_user = False
        self._lock = threading.Lock()
        self._user32 = ctypes.windll.user32
        self._gdi32 = ctypes.windll.gdi32
        self._kernel32 = ctypes.windll.kernel32

        # 设置 Win32 函数的参数类型（防止 OverflowError）
        self._user32.DefWindowProcW.argtypes = [
            c_void_p, c_uint, wintypes.WPARAM, wintypes.LPARAM
        ]
        self._user32.DefWindowProcW.restype = c_long
        self._user32.CreateWindowExW.argtypes = [
            c_ulong, wintypes.LPCWSTR, wintypes.LPCWSTR, c_ulong,
            c_int, c_int, c_int, c_int,
            c_void_p, c_void_p, c_void_p, c_void_p
        ]
        self._user32.CreateWindowExW.restype = c_void_p
        self._user32.SendMessageW.argtypes = [c_void_p, c_uint, wintypes.WPARAM, wintypes.LPARAM]
        self._user32.SendMessageW.restype = c_long
        self._user32.PostMessageW.argtypes = [c_void_p, c_uint, wintypes.WPARAM, wintypes.LPARAM]
        self._user32.PostMessageW.restype = c_int
        self._user32.SetWindowTextW.argtypes = [c_void_p, wintypes.LPCWSTR]
        self._user32.InvalidateRect.argtypes = [c_void_p, c_void_p, c_int]
        self._user32.UpdateWindow.argtypes = [c_void_p]
        self._user32.ShowWindow.argtypes = [c_void_p, c_int]
        self._user32.DestroyWindow.argtypes = [c_void_p]
        self._user32.PostQuitMessage.argtypes = [c_int]
        self._user32.LoadCursorW.argtypes = [c_void_p, c_ulong]
        self._user32.LoadCursorW.restype = c_void_p
        self._user32.GetSystemMetrics.argtypes = [c_int]
        self._user32.PeekMessageW.argtypes = [c_void_p, c_void_p, c_uint, c_uint, c_uint]
        self._user32.TranslateMessage.argtypes = [c_void_p]
        self._user32.DispatchMessageW.argtypes = [c_void_p]
        self._user32.RegisterClassW.argtypes = [c_void_p]
        self._user32.RegisterClassW.restype = c_ushort
        self._kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        self._kernel32.GetModuleHandleW.restype = c_void_p
        self._gdi32.GetStockObject.argtypes = [c_int]
        self._gdi32.GetStockObject.restype = c_void_p

    def _wnd_proc(self, hwnd, msg, wparam, lparam):
        if msg == _WM_CLOSE:
            with self._lock:
                self._closed_by_user = True
            self._user32.DestroyWindow(hwnd)
            return 0
        if msg == _WM_DESTROY:
            self._user32.PostQuitMessage(0)
            return 0
        return self._user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _create_window(self):
        # 加载 comctl32（进度条控件）
        ctypes.windll.kernel32.LoadLibraryW("comctl32.dll")

        hinst = self._kernel32.GetModuleHandleW(None)
        # 临时类名（避免冲突）
        class_name = f"BootstrapProgress_{id(self)}"

        # 窗口过程（必须保留为实例属性防止被 GC）
        self._wnd_proc_func = ctypes.WINFUNCTYPE(
            c_long, c_void_p, c_uint, wintypes.WPARAM, wintypes.LPARAM
        )(self._wnd_proc)

        wc = WNDCLASS()
        wc.style = 0
        wc.lpfnWndProc = ctypes.cast(self._wnd_proc_func, c_void_p)
        wc.cbClsExtra = 0
        wc.cbWndExtra = 0
        wc.hInstance = hinst
        wc.hIcon = 0
        wc.hCursor = self._user32.LoadCursorW(0, 32512)  # IDC_ARROW
        wc.hbrBackground = self._gdi32.GetStockObject(_COLOR_BTNFACE)
        wc.lpszMenuName = 0
        wc.lpszClassName = class_name
        self._user32.RegisterClassW(ctypes.byref(wc))

        # 创建主窗口
        width, height = 480, 180
        screen_w = self._user32.GetSystemMetrics(0)
        screen_h = self._user32.GetSystemMetrics(1)
        x = (screen_w - width) // 2
        y = (screen_h - height) // 2

        self._hwnd = self._user32.CreateWindowExW(
            0, class_name, self.title,
            _WS_CAPTION | _WS_SYSMENU,
            x, y, width, height,
            0, 0, hinst, None
        )

        # 创建标题标签
        self._label_hwnd = self._user32.CreateWindowExW(
            0, "Static", "正在安装依赖...",
            _WS_VISIBLE | _WS_CHILD | _SS_CENTER,
            20, 15, width - 40, 25,
            self._hwnd, 0, hinst, None
        )

        # 创建进度条
        self._progress_hwnd = self._user32.CreateWindowExW(
            0, "msctls_progress32", "",
            _WS_VISIBLE | _WS_CHILD | _PBS_SMOOTH,
            20, 55, width - 40, 22,
            self._hwnd, 0, hinst, None
        )
        # 设置范围
        self._user32.SendMessageW(self._progress_hwnd, _PBM_SETRANGE32, 0, self.total)
        self._user32.SendMessageW(self._progress_hwnd, _PBM_SETSTEP, 1, 0)

        # 创建状态文字
        self._status_hwnd = self._user32.CreateWindowExW(
            0, "Static", "准备中...",
            _WS_VISIBLE | _WS_CHILD | _SS_CENTER,
            20, 95, width - 40, 20,
            self._hwnd, 0, hinst, None
        )

        # 设置字体（系统默认 GUI 字体）
        hfont = self._gdi32.GetStockObject(17)  # DEFAULT_GUI_FONT
        self._user32.SendMessageW(self._label_hwnd, 0x0030, hfont, 0)  # WM_SETFONT
        self._user32.SendMessageW(self._status_hwnd, 0x0030, hfont, 0)
        self._user32.SendMessageW(self._progress_hwnd, 0x0030, hfont, 0)

        # 显示窗口
        self._user32.ShowWindow(self._hwnd, 5)  # SW_SHOW
        self._user32.UpdateWindow(self._hwnd)

        # 消息循环
        msg = wintypes.MSG()
        while self._running:
            while self._user32.PeekMessageW(ctypes.byref(msg), 0, 0, 0, 1):  # PM_REMOVE
                if msg.message == 0x0012:  # WM_QUIT
                    self._running = False
                    break
                self._user32.TranslateMessage(ctypes.byref(msg))
                self._user32.DispatchMessageW(ctypes.byref(msg))
            # 处理重绘
            self._user32.InvalidateRect(self._hwnd, None, False)
            import time
            time.sleep(0.03)

    def show(self):
        """启动窗口线程（非阻塞）"""
        self._running = True
        self._thread = threading.Thread(target=self._create_window, daemon=True)
        self._thread.start()
        import time
        time.sleep(0.2)  # 等待窗口创建完成

    def update(self, current, status_text):
        """更新进度和状态文字"""
        if not self._hwnd:
            return
        if self._closed_by_user:
            return
        current = max(0, min(int(current), self.total))
        self._user32.SendMessageW(self._progress_hwnd, _PBM_SETPOS, current, 0)
        self._user32.SetWindowTextW(self._status_hwnd, status_text)
        # 强制重绘
        self._user32.InvalidateRect(self._progress_hwnd, None, True)
        self._user32.UpdateWindow(self._hwnd)

    def close(self):
        """关闭窗口"""
        self._running = False
        if self._hwnd:
            try:
                self._user32.PostMessageW(self._hwnd, _WM_CLOSE, 0, 0)
            except Exception:
                pass
        if self._thread:
            self._thread.join(timeout=2)


def install_package(pip_name, timeout=180):
    """用 pip 安装单个包，返回 (是否成功, 输出文本)"""
    cmd = [sys.executable, "-m", "pip", "install", "--upgrade", pip_name]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace"
        )
        return result.returncode == 0, (result.stdout or "") + (result.stderr or "")
    except subprocess.TimeoutExpired:
        return False, f"安装超时（{timeout} 秒）"
    except Exception as e:
        return False, f"安装异常：{e}"


def check_missing_required():
    """返回缺失的必需包列表 [(pip_name, module_name), ...]"""
    missing = []
    for pip_name, module_name, _ in REQUIRED_PACKAGES:
        if not is_package_installed(module_name):
            missing.append((pip_name, module_name))
    return missing


def check_missing_optional():
    """返回缺失的可选包列表 [(pip_name, module_name), ...]"""
    missing = []
    for pip_name, module_name, _ in OPTIONAL_PACKAGES:
        if not is_package_installed(module_name):
            missing.append((pip_name, module_name))
    return missing


# ==================== 主引导流程 ====================

def ensure_dependencies():
    """
    在 GUI 启动前调用：
    1. 检测必需依赖，缺失则自动 pip install
    2. 首次运行显示联网提醒
    3. 询问是否安装可选增强组件

    返回 True 表示可以继续启动 GUI；
    返回 False 表示无法继续（用户拒绝安装或安装失败）。
    """
    # ===== 第 1 步：检测并安装必需依赖 =====
    missing_required = check_missing_required()

    if missing_required:
        names = [p[0] for p in missing_required]
        msg = (
            "检测到缺失以下必需依赖：\n\n"
            + "\n".join(f"  - {n}" for n in names)
            + "\n\n是否立即联网自动安装？\n（推荐：点击「是」自动安装）\n"
            "点击「否」将退出程序。"
        )
        result = show_message(
            "Overwatch Hero - 依赖安装",
            msg,
            flags=0x34  # MB_YESNO | MB_ICONWARNING
        )
        if result != 6:  # 非 IDYES
            show_message(
                "退出",
                "未安装必需依赖，程序将退出。\n如需手动安装：\n  pip install -r requirements.txt",
                flags=0x10  # MB_ICONERROR
            )
            return False

        # 创建进度条窗口
        total_count = len(missing_required)
        progress = ProgressWindow("Overwatch Hero - 依赖安装", total=total_count)
        progress.show()

        # 逐个安装（带进度条）
        failed = []
        for i, (pip_name, module_name) in enumerate(missing_required):
            progress.update(i, f"[{i+1}/{total_count}] 正在安装 {pip_name}...")
            ok, output = install_package(pip_name, timeout=180)
            if ok and is_package_installed(module_name):
                progress.update(i + 1, f"[{i+1}/{total_count}] ✓ {pip_name} 安装成功")
            else:
                failed.append((pip_name, output))
                progress.update(i + 1, f"[{i+1}/{total_count}] ✗ {pip_name} 安装失败")

        progress.close()

        if failed:
            failed_names = [p[0] for p in failed]
            show_message(
                "依赖安装未完成",
                f"以下依赖安装失败，程序可能无法正常工作：\n"
                + "\n".join(f"  - {n}" for n in failed_names)
                + "\n\n建议手动执行：\n  pip install -r requirements.txt",
                flags=0x30  # MB_ICONWARNING
            )

    # ===== 第 2 步：首次运行提示 =====
    if is_first_run():
        # 检查可选组件缺失
        optional_missing = check_missing_optional()

        opt_section = ""
        if optional_missing:
            opt_names = [p[0] for p in optional_missing]
            opt_section = (
                "\n\n━━━━━━━━━━━━━━━━━━━━\n"
                "检测到以下可选增强组件未安装：\n"
                + "\n".join(f"  - {n}" for n in opt_names)
                + "\n\n作用说明：\n"
                "  • pythonnet → 精确功耗监控（调用 LibreHardwareMonitorLib）\n"
                "  • interception → 驱动级键盘/鼠标模拟（绕过游戏 RawInput 独占）\n"
                "\n是否一并安装？\n"
                "（是 = 安装可选组件，否 = 暂不安装，稍后可手动执行）"
            )

        welcome_msg = (
            "════════════════════════════════\n"
            "  欢迎使用 Overwatch Hero\n"
            "  脚本化刷取控制台\n"
            "════════════════════════════════\n\n"
            "首次使用请保持联网，以启用完整功能：\n"
            "  • IP 自动定位 → 获取当地电价\n"
            "  • 自动下载 Interception 驱动\n"
            "  • 可选组件在线安装\n"
            "  • 在线更新依赖检查\n\n"
            "提示：核心功能不依赖联网，但以下功能需要联网：\n"
            "  - 自动电价查询（可手动输入）\n"
            "  - 驱动下载（可手动安装）"
            + opt_section
        )

        if optional_missing:
            result = show_message(
                "首次启动 - 联网提醒",
                welcome_msg,
                flags=0x34  # MB_YESNO | MB_ICONWARNING
            )
            if result == 6:  # IDYES
                # 创建进度条窗口用于可选依赖
                opt_total = len(optional_missing)
                opt_progress = ProgressWindow("Overwatch Hero - 可选组件安装", total=opt_total)
                opt_progress.show()
                for i, (pip_name, module_name) in enumerate(optional_missing):
                    opt_progress.update(i, f"[{i+1}/{opt_total}] 正在安装 {pip_name}...")
                    ok, output = install_package(pip_name, timeout=180)
                    if ok and is_package_installed(module_name):
                        opt_progress.update(i + 1, f"[{i+1}/{opt_total}] ✓ {pip_name} 安装成功")
                    else:
                        opt_progress.update(i + 1, f"[{i+1}/{opt_total}] ✗ {pip_name} 安装失败")
                opt_progress.close()
        else:
            # 没有缺失的可选组件，仅显示欢迎信息
            show_message(
                "首次启动 - 欢迎",
                welcome_msg,
                flags=0x40  # MB_ICONINFORMATION
            )

        # 标记首次运行已完成
        mark_bootstrap_done()

    return True


def main():
    """命令行入口：单独运行 bootstrap.py 时调用"""
    print("=" * 60)
    print("Overwatch Hero - 依赖引导")
    print("=" * 60)

    print("\n[1] 检测必需依赖...")
    missing_required = check_missing_required()
    if missing_required:
        print(f"  缺失 {len(missing_required)} 个：")
        for pip_name, _ in missing_required:
            print(f"    - {pip_name}")
    else:
        print("  全部已安装 ✓")

    print("\n[2] 检测可选依赖...")
    missing_optional = check_missing_optional()
    if missing_optional:
        print(f"  缺失 {len(missing_optional)} 个：")
        for pip_name, _ in missing_optional:
            print(f"    - {pip_name}")
    else:
        print("  全部已安装 ✓")

    print(f"\n[3] 首次运行标记：{'未完成' if is_first_run() else '已完成'}")

    print("\n" + "=" * 60)
    ok = ensure_dependencies()
    if ok:
        print("\n引导完成，可以启动 GUI。")
    else:
        print("\n引导未完成，请检查依赖。")
        sys.exit(1)


if __name__ == "__main__":
    main()
