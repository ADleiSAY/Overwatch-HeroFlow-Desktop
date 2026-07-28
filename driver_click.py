"""
驱动级鼠标点击模块
使用 Interception 内核驱动在驱动层注入鼠标中断，绕过 DX11 RawInput 独占。

原理：
  Interception 驱动作为 USB/HID 设备栈的过滤驱动安装，
  通过 DeviceIoControl 直接向设备驱动发送 IRP，
  注入的鼠标事件在内核层就被注入到 HID 栈，绕过所有用户层钩子。

安装驱动：
  1. 下载 Interception 驱动: https://github.com/oblitum/Interception/releases
  2. 解压后运行: install-interception.exe /install
  3. 重启电脑使过滤驱动生效
"""

import ctypes
import os
import subprocess
import sys
import time
import urllib.request
import zipfile

# Interception 库
try:
    from interception import ffi, lib
    from interception.utils import get_screen_width, get_screen_height
    INTERCEPTION_AVAILABLE = True
except Exception:
    INTERCEPTION_AVAILABLE = False

INTERCEPTION_MAX_KEYBOARD = 10

# 屏幕分辨率（用于绝对坐标归一化）
SCREEN_W = ctypes.windll.user32.GetSystemMetrics(0)
SCREEN_H = ctypes.windll.user32.GetSystemMetrics(1)


def _find_mouse_device(ctx):
    """
    遍历所有鼠标设备号(11-20)，找到第一个能成功发送事件的设备。
    Interception 设备号约定：1-10 键盘，11-20 鼠标。
    返回设备号；找不到返回 0。
    """
    if ctx == 0:
        return 0
    try:
        stroke = ffi.new('InterceptionMouseStroke *')
        stroke.state = 0
        stroke.flags = 0
        stroke.x = 0
        stroke.y = 0
        stroke.rolling = 0
        stroke.information = 0
        for dev in range(INTERCEPTION_MAX_KEYBOARD + 1, INTERCEPTION_MAX_KEYBOARD + 11):
            try:
                if lib.interception_send(ctx, dev, stroke, 1) > 0:
                    return dev
            except Exception:
                continue
    except Exception:
        pass
    return 0


def is_driver_installed():
    r"""
    检测 Interception 驱动是否已安装。
    Interception 安装后会：
      1. 创建 keyboard.sys / mouse.sys（过滤驱动，非原生 i8042prt/kbdclass）
      2. 注册 HKLM\SYSTEM\CurrentControlSet\Services\keyboard 服务
      3. 在键盘/鼠标设备类的 UpperFilters 添加 "keyboard" / "mouse"
    注意：驱动需要重启电脑后才会真正加载到 HID 设备栈。
    重启前 interception_send 会返回 0（设备不可用），这是正常的。
    """
    # 方法1：检查注册表服务项是否存在（最可靠）
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r"SYSTEM\CurrentControlSet\Services\keyboard") as key:
            display = winreg.QueryValueEx(key, "DisplayName")[0]
            if "Upper Filter" in display or "Interception" in display:
                return True
    except Exception:
        pass
    # 方法2：检查 keyboard.sys 是否为 Interception 的过滤驱动
    # 原生 Windows 没有 keyboard.sys（只有 i8042prt.sys / kbdclass.sys）
    try:
        sys_path = r"C:\Windows\System32\drivers\keyboard.sys"
        if os.path.exists(sys_path):
            # Interception 的 keyboard.sys 很小（约 18KB）
            if os.path.getsize(sys_path) < 100000:
                return True
    except Exception:
        pass
    return False


def is_driver_loaded():
    """
    检测 Interception 驱动是否已加载（重启后才会加载）。
    通过实际发送测试事件验证驱动栈是否工作。
    """
    if not INTERCEPTION_AVAILABLE:
        return False
    try:
        ctx = lib.interception_create_context()
        if ctx == 0:
            return False
        found = _find_mouse_device(ctx)
        lib.interception_destroy_context(ctx)
        return found > 0
    except Exception:
        return False


def install_driver(progress_callback=None):
    """
    下载并安装 Interception 驱动（需要管理员权限）。
    使用国内 GitHub 镜像下载，使用 ShellExecute runas 以管理员权限运行 install-interception.exe。
    安装后必须重启电脑，驱动才会加载到 HID 设备栈。
    """
    def report(progress, phase, message):
        if progress_callback is None:
            return
        try:
            progress_callback(progress, phase, message)
        except Exception:
            # 安装不能因为界面进度上报失败而中断。
            pass

    report(3, "checking", "正在检查 Interception 驱动")
    if is_driver_installed():
        report(100, "complete", "Interception 驱动已安装")
        return True, "驱动已经安装，请重启电脑后再检查加载状态。"

    # 官方版本 v1.0.1（GitHub API 确认存在）
    github_url = "https://github.com/oblitum/Interception/releases/download/v1.0.1/Interception.zip"
    # 国内镜像列表（GitHub 在中国大陆通常无法直接访问）
    mirrors = [
        "https://gh-proxy.com/" + github_url,
        "https://ghps.cc/" + github_url,
        "https://kkgithub.com/oblitum/Interception/releases/download/v1.0.1/Interception.zip",
        github_url,  # 直连作为最后兜底
    ]
    temp_dir = os.path.join(os.environ.get("TEMP", "."), "interception_install")
    zip_path = os.path.join(temp_dir, "Interception.zip")
    os.makedirs(temp_dir, exist_ok=True)
    report(8, "preparing", "正在准备驱动安装文件")

    # 用 PowerShell 下载（比 urllib 更可靠，能走系统代理），逐个镜像尝试
    download_ok = False
    last_err = ""
    for index, url in enumerate(mirrors):
        attempt = index + 1
        progress_base = 12 + index * 10
        report(progress_base, "downloading", f"正在下载驱动（线路 {attempt}/{len(mirrors)}）")
        try:
            if os.path.exists(zip_path):
                os.remove(zip_path)
            ps_cmd = (
                f"Invoke-WebRequest -Uri '{url}' -OutFile '{zip_path}' "
                f"-UseBasicParsing -TimeoutSec 45"
            )
            process = subprocess.Popen(
                ["powershell", "-NoProfile", "-Command", ps_cmd],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            started_at = time.monotonic()
            while process.poll() is None:
                elapsed = time.monotonic() - started_at
                if elapsed >= 50:
                    process.kill()
                    process.communicate()
                    raise subprocess.TimeoutExpired(process.args, 50)
                step = min(8, int(elapsed / 5))
                report(
                    progress_base + step,
                    "downloading",
                    f"正在下载驱动（线路 {attempt}/{len(mirrors)}）",
                )
                time.sleep(1)
            _, stderr = process.communicate()
            valid_zip = (
                process.returncode == 0
                and os.path.exists(zip_path)
                and os.path.getsize(zip_path) > 100000
                and zipfile.is_zipfile(zip_path)
            )
            if valid_zip:
                download_ok = True
                report(55, "downloaded", "驱动安装包下载完成")
                break
            else:
                detail = (stderr or "").strip().splitlines()
                last_err = detail[-1][:240] if detail else f"{url} 返回的文件无效"
                if os.path.exists(zip_path):
                    os.remove(zip_path)
        except subprocess.TimeoutExpired:
            last_err = f"{url} 超时"
        except Exception as e:
            last_err = f"{url} 失败: {e}"

    if not download_ok:
        report(100, "error", "驱动安装包下载失败")
        return False, (
            f"下载失败（所有镜像都失败）：{last_err}\n"
            f"请手动下载并解压：\n  {github_url}\n"
            f"然后运行 install-interception.exe /install（管理员权限）"
        )

    # 解压
    report(62, "extracting", "正在解压驱动安装包")
    try:
        with zipfile.ZipFile(zip_path, 'r') as z:
            z.extractall(temp_dir)
    except Exception as e:
        report(100, "error", "驱动安装包解压失败")
        return False, f"解压失败: {e}"

    # 查找 install-interception.exe
    exe_name = "install-interception.exe"
    exe_path = None
    for root, dirs, files in os.walk(temp_dir):
        if exe_name in files:
            exe_path = os.path.join(root, exe_name)
            break

    if not exe_path:
        report(100, "error", "驱动安装程序缺失")
        return False, "未找到 install-interception.exe（下载的zip可能损坏）"

    # 以管理员权限运行安装（ShellExecuteExW + runas 弹 UAC，同步等待完成）
    report(72, "awaiting_uac", "请在系统弹窗中允许管理员权限")
    try:
        import ctypes
        from ctypes import wintypes

        SEE_MASK_NOCLOSEPROCESS = 0x00000040
        SW_HIDE = 0
        WAIT_OBJECT_0 = 0
        WAIT_TIMEOUT = 258

        class SHELLEXECUTEINFO(ctypes.Structure):
            _fields_ = [
                ("cbSize", ctypes.c_ulong),
                ("fMask", ctypes.c_ulong),
                ("hwnd", wintypes.HWND),
                ("lpVerb", wintypes.LPCWSTR),
                ("lpFile", wintypes.LPCWSTR),
                ("lpParameters", wintypes.LPCWSTR),
                ("lpDirectory", wintypes.LPCWSTR),
                ("nShow", ctypes.c_int),
                ("hInstApp", wintypes.HINSTANCE),
                ("lpIDList", wintypes.LPVOID),
                ("lpClass", wintypes.LPCWSTR),
                ("hkeyClass", wintypes.HKEY),
                ("dwHotKey", wintypes.DWORD),
                ("hIcon", wintypes.HANDLE),
                ("hProcess", wintypes.HANDLE),
            ]

        info = SHELLEXECUTEINFO()
        info.cbSize = ctypes.sizeof(SHELLEXECUTEINFO)
        info.fMask = SEE_MASK_NOCLOSEPROCESS
        info.lpVerb = "runas"  # 触发 UAC 提权
        info.lpFile = exe_path
        info.lpParameters = "/install"
        info.nShow = SW_HIDE  # 隐藏窗口（命令行安装程序无 GUI）
        ok = ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(info))
        if not ok:
            err = ctypes.windll.kernel32.GetLastError()
            report(100, "error", "管理员授权被取消或安装程序无法启动")
            return False, f"无法启动安装程序（错误码 {err}，可能 UAC 被拒绝）。\n可手动运行: {exe_path} /install"

        # 等待安装进程结束，并在等待 UAC/安装期间持续反馈界面进度。
        if info.hProcess:
            started_at = time.monotonic()
            wait_result = WAIT_TIMEOUT
            try:
                while wait_result == WAIT_TIMEOUT:
                    wait_result = ctypes.windll.kernel32.WaitForSingleObject(info.hProcess, 500)
                    elapsed = time.monotonic() - started_at
                    report(
                        min(92, 78 + int(elapsed / 8)),
                        "installing",
                        "正在安装 Interception 驱动",
                    )
                    if elapsed >= 120 and wait_result == WAIT_TIMEOUT:
                        report(100, "error", "等待驱动安装程序超时")
                        return False, "等待驱动安装程序超时，请确认 UAC 弹窗并手动完成安装。"
                if wait_result != WAIT_OBJECT_0:
                    report(100, "error", "无法读取驱动安装结果")
                    return False, f"无法读取驱动安装结果（等待状态 {wait_result}）。"
                exit_code = wintypes.DWORD()
                if ctypes.windll.kernel32.GetExitCodeProcess(info.hProcess, ctypes.byref(exit_code)):
                    if exit_code.value != 0:
                        report(100, "error", "驱动安装程序执行失败")
                        return False, f"驱动安装程序执行失败（退出码 {exit_code.value}）。"
            finally:
                ctypes.windll.kernel32.CloseHandle(info.hProcess)

        # 验证：Interception 安装后创建 keyboard.sys / mouse.sys（不是 Interception.sys）
        # 并在注册表注册 "Keyboard Upper Filter Driver" 服务
        report(96, "verifying", "正在验证驱动安装结果")
        if is_driver_installed():
            report(100, "complete", "驱动安装完成，请重启电脑")
            return True, (
                "✅ 驱动安装成功！已检测到 Interception 过滤驱动。\n"
                "  - C:\\Windows\\System32\\drivers\\keyboard.sys\n"
                "  - 注册表服务: HKLM\\SYSTEM\\CurrentControlSet\\Services\\keyboard\n\n"
                "⚠️ 必须重启电脑后驱动才会加载到 HID 设备栈！\n"
                "重启后再次运行程序，「点击方式」应显示「驱动级 (Interception)」绿色文字。"
            )
        else:
            report(100, "error", "未检测到已安装的驱动")
            return False, (
                "安装程序已运行，但未检测到 Interception 过滤驱动。\n"
                "可能原因：UAC 被取消 / 杀毒软件拦截 / install-interception.exe 失败。\n\n"
                f"请手动以管理员身份运行:\n  {exe_path} /install"
            )
    except Exception as e:
        report(100, "error", "驱动安装失败")
        return False, f"安装失败: {e}\n可手动运行: {exe_path} /install"


class DriverClicker:
    """驱动级鼠标控制器"""

    def __init__(self):
        self.context = None
        self.mouse_device = None  # 鼠标设备号
        self.available = False
        self.mstroke = None  # 复用 stroke 对象减少分配

    def init(self):
        """
        初始化驱动级输入上下文。
        遍历所有鼠标设备号(11-20)找到第一个能成功发送的设备。
        不设置过滤，避免拦截用户输入。
        """
        if not INTERCEPTION_AVAILABLE:
            return False, "Interception 库未安装（pip install interception）"

        try:
            self.context = lib.interception_create_context()
            if self.context == 0:
                return False, "无法创建 Interception 上下文（驱动未安装或未重启？）"

            self.mstroke = ffi.new('InterceptionMouseStroke *')

            # 遍历设备号找到真实可用的鼠标设备
            dev = _find_mouse_device(self.context)
            if dev == 0:
                lib.interception_destroy_context(self.context)
                self.context = None
                return False, "未找到可用鼠标设备（驱动未安装/未重启？）"

            self.mouse_device = dev
            self.available = True
            return True, f"驱动级输入就绪 (鼠标设备={dev})"
        except Exception as e:
            return False, f"初始化失败: {e}"

    def auto_find_mouse(self, timeout_ms=3000):
        """
        等待鼠标移动事件以自动识别鼠标设备号。
        如果在 timeout_ms 内没有检测到鼠标，尝试直接发送到设备 11。
        """
        if not self.available:
            return False

        start = time.time()
        timeout_s = timeout_ms / 1000.0

        while time.time() - start < timeout_s:
            device = lib.interception_wait_with_timeout(self.context, 100)
            if device == 0:
                continue
            if not lib.interception_receive(self.context, device, self.mstroke, 1):
                continue
            if lib.interception_is_mouse(device):
                self.mouse_device = device
                # 转发原始事件（不拦截用户操作）
                lib.interception_send(self.context, device, self.mstroke, 1)
                return True
            else:
                # 转发键盘事件
                lib.interception_send(self.context, device, self.mstroke, 1)

        # 超时：直接尝试设备 11（第一个鼠标设备）
        self.mouse_device = INTERCEPTION_MAX_KEYBOARD + 1
        return True

    def click(self, x, y):
        """
        驱动级绝对坐标点击：移动 + 按下 + 抬起
        所有事件通过 DeviceIoControl -> IRP 注入到 HID 驱动栈，
        绕过 DX11 RawInput 独占。

        关键：按下和抬起事件也必须设置 MOVE_ABSOLUTE 标志，
        否则 x/y 会被解释为相对移动量，导致点击位置严重偏移。
        """
        if not self.available or self.mouse_device is None:
            return False

        # 归一化为 0-0xFFFF 范围的绝对坐标
        norm_x = int((0xFFFF * x) / SCREEN_W)
        norm_y = int((0xFFFF * y) / SCREEN_H)

        # 1. 移动到目标位置（绝对坐标）
        self.mstroke.state = 0
        self.mstroke.flags = lib.INTERCEPTION_MOUSE_MOVE_ABSOLUTE
        self.mstroke.x = norm_x
        self.mstroke.y = norm_y
        self.mstroke.rolling = 0
        self.mstroke.information = 0
        lib.interception_send(self.context, self.mouse_device, self.mstroke, 1)

        # 2. 按下左键（必须保持 MOVE_ABSOLUTE，否则 x/y 变成相对移动）
        self.mstroke.state = lib.INTERCEPTION_MOUSE_LEFT_BUTTON_DOWN
        self.mstroke.flags = lib.INTERCEPTION_MOUSE_MOVE_ABSOLUTE
        self.mstroke.x = norm_x
        self.mstroke.y = norm_y
        lib.interception_send(self.context, self.mouse_device, self.mstroke, 1)

        # 3. 微小延迟模拟真实点击
        time.sleep(0.03)

        # 4. 抬起左键（同样保持 MOVE_ABSOLUTE）
        self.mstroke.state = lib.INTERCEPTION_MOUSE_LEFT_BUTTON_UP
        self.mstroke.flags = lib.INTERCEPTION_MOUSE_MOVE_ABSOLUTE
        self.mstroke.x = norm_x
        self.mstroke.y = norm_y
        lib.interception_send(self.context, self.mouse_device, self.mstroke, 1)

        return True

    def move_relative(self, total_dx, total_dy, duration_s, speed_px_s, check_callback=None):
        """
        驱动级鼠标相对持续移动。
        在指定时长内按速度持续发送相对移动事件，常用于"向右持续移动鼠标 3s"。

        参数：
            total_dx: 总位移 X（像素，正=右移）
            total_dy: 总位移 Y（像素，正=下移）
            duration_s: 持续时长（秒）
            speed_px_s: 速度（像素/秒）
            check_callback: 可选回调函数，每 50ms 调用一次。
                           回调返回 True 时立即停止移动（用于 LOOP2 中检查 F10 识别）。

        返回：
            True=正常完成 / False=被回调中断或不可用

        实现要点：
            - 每次发送的位移 = speed_px_s * 0.05（每 50ms 发一次事件）
            - 总事件次数 = duration_s / 0.05
            - 剩余位移在最后一次事件中补齐
            - 使用 INTERCEPTION_MOUSE_MOVE_RELATIVE（相对移动）标志
            - 每次事件后 sleep(0.05) 秒
            - 每次事件前调用 check_callback，返回 True 立即停止并返回 False
            - 移动过程中使用 mstroke 复用对象
            - 不可用或设备为 None 时直接返回 False
        """
        # 不可用或设备为 None 时直接返回 False
        if not self.available or self.mouse_device is None:
            return False

        # 获取相对移动标志（兼容不同版本 interception 库）
        try:
            MOVE_RELATIVE = lib.INTERCEPTION_MOUSE_MOVE_RELATIVE
        except AttributeError:
            MOVE_RELATIVE = 1

        # 每帧间隔 50ms
        interval = 0.05
        # 每帧位移量（基于速度计算）
        step = int(speed_px_s * interval)
        # X 方向每帧位移（保留 total_dx 的符号）
        if total_dx > 0:
            dx_per_event = step
        elif total_dx < 0:
            dx_per_event = -step
        else:
            dx_per_event = 0
        # Y 方向每帧不移动（由最后一帧补齐）
        dy_per_event = 0
        # 总事件数
        total_events = int(duration_s / interval)

        # 累计已发送位移
        sent_dx = 0
        sent_dy = 0

        for i in range(total_events):
            # 每帧前调用回调，返回 True 时立即停止
            if check_callback is not None and check_callback():
                return False

            # 最后一帧补齐剩余位移
            if i == total_events - 1:
                dx = total_dx - sent_dx
                dy = total_dy - sent_dy
            else:
                dx = dx_per_event
                dy = dy_per_event

            # 设置 mstroke（仅移动，不按键）
            self.mstroke.state = 0
            self.mstroke.flags = MOVE_RELATIVE
            self.mstroke.x = dx
            self.mstroke.y = dy
            self.mstroke.rolling = 0
            self.mstroke.information = 0
            lib.interception_send(self.context, self.mouse_device, self.mstroke, 1)

            sent_dx += dx
            sent_dy += dy

            time.sleep(interval)

        return True

    def move(self, x, y):
        """驱动级绝对坐标移动（不点击）"""
        if not self.available or self.mouse_device is None:
            return False

        norm_x = int((0xFFFF * x) / SCREEN_W)
        norm_y = int((0xFFFF * y) / SCREEN_H)

        self.mstroke.state = 0
        self.mstroke.flags = lib.INTERCEPTION_MOUSE_MOVE_ABSOLUTE
        self.mstroke.x = norm_x
        self.mstroke.y = norm_y
        lib.interception_send(self.context, self.mouse_device, self.mstroke, 1)
        return True

    def destroy(self):
        """销毁上下文"""
        if self.context:
            try:
                lib.interception_destroy_context(self.context)
            except:
                pass
            self.context = None
        self.available = False


# ==================== 键盘驱动级输入 ====================

# Windows 标准 VK 码常量
VK_CTRL = 0x11
VK_A = 0x41
VK_D = 0x44
VK_E = 0x45
VK_F10 = 0x79
VK_ALT = 0x12
VK_F4 = 0x73

# SendInput 键盘回退结构定义（Interception 不可用时使用）
INPUT_KEYBOARD = 1
KEYEVENTF_KEYDOWN = 0x0000  # 默认（按下）
KEYEVENTF_KEYUP = 0x0002


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", ctypes.c_ushort),
                ("wScan", ctypes.c_ushort),
                ("dwFlags", ctypes.c_ulong),
                ("time", ctypes.c_ulong),
                ("dwExtraInfo", ctypes.c_void_p)]


class _KEYBD_INPUTunion(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT)]


class _KEYBD_INPUT(ctypes.Structure):
    _fields_ = [("type", ctypes.c_ulong),
                ("union", _KEYBD_INPUTunion)]


def _send_input_key(vk_code, is_down):
    """使用 SendInput 发送键盘事件（Interception 不可用时的回退方案）"""
    inp = _KEYBD_INPUT()
    inp.type = INPUT_KEYBOARD
    inp.union.ki.wVk = vk_code
    inp.union.ki.wScan = 0
    inp.union.ki.dwFlags = KEYEVENTF_KEYDOWN if is_down else KEYEVENTF_KEYUP
    # time / dwExtraInfo 默认为 0
    return ctypes.windll.user32.SendInput(
        1, ctypes.byref(inp), ctypes.sizeof(_KEYBD_INPUT)
    ) == 1


def _find_keyboard_device(ctx):
    """
    遍历所有键盘设备号(1-10)，找到第一个能成功发送事件的设备。
    Interception 设备号约定：1-10 键盘，11-20 鼠标。
    返回设备号；找不到返回 0。
    """
    if ctx == 0:
        return 0
    try:
        stroke = ffi.new('InterceptionKeyStroke *')
        stroke.code = 0
        stroke.state = 0
        stroke.information = 0
        for dev in range(1, INTERCEPTION_MAX_KEYBOARD + 1):
            try:
                if lib.interception_send(ctx, dev, stroke, 1) > 0:
                    return dev
            except Exception:
                continue
    except Exception:
        pass
    return 0


class DriverKeyboard:
    """驱动级键盘控制器（Interception 注入 + SendInput 回退）"""

    def __init__(self):
        self.context = None
        self.keyboard_device = None
        self.available = False
        self.kstroke = None  # InterceptionKeyStroke *

    def init(self):
        """
        初始化驱动级键盘上下文，返回 (ok, msg)。
        遍历所有键盘设备号(1-10)找到第一个能成功发送的设备。
        不设置过滤，避免拦截用户输入。
        """
        if not INTERCEPTION_AVAILABLE:
            return False, "Interception 库未安装（pip install interception）"

        try:
            self.context = lib.interception_create_context()
            if self.context == 0:
                return False, "无法创建 Interception 上下文（驱动未安装或未重启？）"

            self.kstroke = ffi.new('InterceptionKeyStroke *')

            # 遍历设备号找到真实可用的键盘设备
            dev = _find_keyboard_device(self.context)
            if dev == 0:
                lib.interception_destroy_context(self.context)
                self.context = None
                return False, "未找到可用键盘设备（驱动未安装/未重启？）"

            self.keyboard_device = dev
            self.available = True
            return True, f"驱动级键盘就绪 (键盘设备={dev})"
        except Exception as e:
            return False, f"初始化失败: {e}"

    def key_down(self, vk_code):
        """按下键"""
        if self.available and self.keyboard_device is not None:
            # Interception code 字段需要扫描码，VK 码需转换（MAPVK_VK_TO_VSC=0）
            scan_code = ctypes.windll.user32.MapVirtualKeyW(vk_code, 0)
            self.kstroke.code = scan_code
            self.kstroke.state = lib.INTERCEPTION_KEY_DOWN
            self.kstroke.information = 0
            try:
                return lib.interception_send(
                    self.context, self.keyboard_device, self.kstroke, 1
                ) > 0
            except Exception:
                return False
        else:
            # 回退 SendInput
            return _send_input_key(vk_code, is_down=True)

    def key_up(self, vk_code):
        """松开键"""
        if self.available and self.keyboard_device is not None:
            scan_code = ctypes.windll.user32.MapVirtualKeyW(vk_code, 0)
            self.kstroke.code = scan_code
            self.kstroke.state = lib.INTERCEPTION_KEY_UP
            self.kstroke.information = 0
            try:
                return lib.interception_send(
                    self.context, self.keyboard_device, self.kstroke, 1
                ) > 0
            except Exception:
                return False
        else:
            # 回退 SendInput
            return _send_input_key(vk_code, is_down=False)

    def press_key(self, vk_code, duration_s=0.05):
        """按下 + 等待 + 松开"""
        down_ok = self.key_down(vk_code)
        try:
            time.sleep(duration_s)
        finally:
            # 即使等待期间发生异常，也尽量发出抬键，避免键位卡住。
            up_ok = self.key_up(vk_code)
        return bool(down_ok and up_ok)

    def combo(self, vk_codes):
        """组合键：按顺序按下所有键 → 倒序松开所有键（支持 Alt+F4）"""
        sent_ok = True
        # 顺序按下
        for vk in vk_codes:
            sent_ok = self.key_down(vk) and sent_ok
            time.sleep(0.01)
        # 倒序松开
        for vk in reversed(vk_codes):
            sent_ok = self.key_up(vk) and sent_ok
            time.sleep(0.01)
        return sent_ok

    def destroy(self):
        """销毁上下文"""
        if self.context:
            try:
                lib.interception_destroy_context(self.context)
            except:
                pass
            self.context = None
        self.available = False


if __name__ == "__main__":
    # 测试鼠标
    print("=== 测试 DriverClicker ===")
    clicker = DriverClicker()
    ok, msg = clicker.init()
    print(msg)
    if ok:
        clicker.destroy()

    # 测试键盘
    print("\n=== 测试 DriverKeyboard ===")
    kb = DriverKeyboard()
    ok, msg = kb.init()
    print(msg)
    if ok:
        # 模拟按 Ctrl（不真按，只发送事件验证）
        print("按下 Ctrl 200ms")
        kb.press_key(VK_CTRL, duration_s=0.2)
        print("按下 E 50ms")
        kb.press_key(VK_E, duration_s=0.05)
        print("Alt+F4 组合键（注释掉以避免误关窗口）")
        # kb.combo([VK_ALT, VK_F4])
        kb.destroy()
    else:
        print("键盘不可用，可能驱动未安装或未重启")

    # 测试相对移动
    print("\n=== 测试 move_relative ===")
    ck = DriverClicker()
    ok, _ = ck.init()
    if ok:
        import time
        print("向右移动 3 秒（速度 500 px/s，应移动 1500 像素）")
        result = ck.move_relative(1500, 0, 3.0, 500, check_callback=lambda: False)
        print(f"结果: {result}")
        ck.destroy()
