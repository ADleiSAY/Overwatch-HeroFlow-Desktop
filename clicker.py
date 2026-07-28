# clicker.py
import os
import time
import socket
import ctypes
import threading
import cv2
import numpy as np
import dxcam
import win32gui
import win32api
import win32con
from config import *
from driver_click import DriverClicker, is_driver_installed, is_driver_loaded
from logger import logger


def _enable_dpi_awareness():
    """Use physical pixels so Win32 coordinates and DXGI frames agree."""
    try:
        user32 = ctypes.windll.user32
        setter = getattr(user32, "SetProcessDpiAwarenessContext", None)
        if setter is not None and setter(ctypes.c_void_p(-4)):  # PER_MONITOR_AWARE_V2
            return
    except (AttributeError, OSError, ValueError):
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except (AttributeError, OSError, ValueError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError, ValueError):
            pass


_enable_dpi_awareness()


# SendInput 结构定义
INPUT_MOUSE = 0
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_ABSOLUTE = 0x8000


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", ctypes.c_long),
                ("dy", ctypes.c_long),
                ("mouseData", ctypes.c_ulong),
                ("dwFlags", ctypes.c_ulong),
                ("time", ctypes.c_ulong),
                ("dwExtraInfo", ctypes.c_void_p)]


class _INPUTunion(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", ctypes.c_ulong),
                ("union", _INPUTunion)]


def send_input_click(screen_x, screen_y):
    """使用SendInput发送绝对坐标点击，游戏RawInput下也有效"""
    # 转换为绝对坐标(0-65535范围)
    screen_w = ctypes.windll.user32.GetSystemMetrics(0)
    screen_h = ctypes.windll.user32.GetSystemMetrics(1)
    abs_x = int(screen_x * 65535 / screen_w)
    abs_y = int(screen_y * 65535 / screen_h)

    # 移动鼠标
    inp_move = INPUT()
    inp_move.type = INPUT_MOUSE
    inp_move.union.mi.dx = abs_x
    inp_move.union.mi.dy = abs_y
    inp_move.union.mi.dwFlags = MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE

    # 按下
    inp_down = INPUT()
    inp_down.type = INPUT_MOUSE
    inp_down.union.mi.dx = abs_x
    inp_down.union.mi.dy = abs_y
    inp_down.union.mi.dwFlags = MOUSEEVENTF_LEFTDOWN | MOUSEEVENTF_ABSOLUTE

    # 抬起
    inp_up = INPUT()
    inp_up.type = INPUT_MOUSE
    inp_up.union.mi.dx = abs_x
    inp_up.union.mi.dy = abs_y
    inp_up.union.mi.dwFlags = MOUSEEVENTF_LEFTUP | MOUSEEVENTF_ABSOLUTE

    ctypes.windll.user32.SendInput(1, ctypes.byref(inp_move), ctypes.sizeof(INPUT))
    time.sleep(0.01)
    ctypes.windll.user32.SendInput(1, ctypes.byref(inp_down), ctypes.sizeof(INPUT))
    time.sleep(0.01)
    ctypes.windll.user32.SendInput(1, ctypes.byref(inp_up), ctypes.sizeof(INPUT))


_overlay_sock = None


def send_coords_to_overlay(x, y, w, h):
    """发送框选区域到覆盖层（UDP，复用socket）"""
    global _overlay_sock
    try:
        if _overlay_sock is None:
            _overlay_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        _overlay_sock.sendto(f"{int(x)} {int(y)} {int(w)} {int(h)}".encode(), (OVERLAY_HOST, OVERLAY_PORT))
        return True
    except:
        return False


class Clicker:
    def __init__(self):
        self.hwnd = None
        self.camera = None
        self.template = None
        self.template_gray = None
        self.template_w = 0
        self.template_h = 0
        self.running = False
        self.last_rect = None  # 缓存窗口客户区矩形，避免每帧重设
        self.capture_origin = None  # 截图区域原点（物理屏幕坐标），供 overlay 对齐
        self._camera_region = None
        self._last_region_check = 0.0
        self._camera_lock = threading.RLock()
        self._match_lock = threading.RLock()
        # 驱动级点击器
        self.driver = DriverClicker()
        self.use_driver = False  # 是否使用驱动级点击
        self.driver_msg = ""     # 驱动初始化消息（供 GUI 显示）
        # 实时状态数据（供GUI读取）
        self.status = "就绪"
        self.last_x = 0
        self.last_y = 0
        self.last_conf = 0.0
        self.click_count = 0
        # 未达到阈值时也保留最高分，便于区分“差一点”和“完全没截到”。
        self.last_match_name = ""
        self.last_match_confidence = 0.0
        self.last_match_scale = 1.0
        self.last_match_size = (0, 0)
        self.last_match_location = None
        # 模板缓存：name -> (template, template_gray, w, h)
        self._templates = {}

    def find_window(self):
        def enum_callback(hwnd, hwnd_list):
            if win32gui.IsWindowVisible(hwnd):
                title = win32gui.GetWindowText(hwnd)
                if WINDOW_TITLE.lower() in title.lower():
                    hwnd_list.append(hwnd)
            return True

        hwnd_list = []
        win32gui.EnumWindows(enum_callback, hwnd_list)
        if hwnd_list:
            self.hwnd = hwnd_list[0]
            return True
        return False

    def get_client_rect_screen(self):
        """获取客户区在屏幕上的矩形（与click()坐标系一致）"""
        rect = win32gui.GetClientRect(self.hwnd)  # (0, 0, width, height)
        pt = win32gui.ClientToScreen(self.hwnd, (0, 0))
        left, top = pt[0], pt[1]
        return (left, top, left + rect[2], top + rect[3])

    def load_template(self):
        if not os.path.exists(TEMPLATE_PATH):
            logger.error(f"模板文件不存在: {TEMPLATE_PATH}")
            return False
        # 使用 imdecode + np.fromfile 读取（支持中文路径）
        try:
            arr = np.fromfile(TEMPLATE_PATH, dtype=np.uint8)
            self.template = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        except Exception as e:
            logger.error(f"读取模板失败: {e}")
            return False
        if self.template is None:
            logger.error("无法解码模板图片（可能不是有效图片）")
            return False
        if USE_GRAY:
            self.template_gray = cv2.cvtColor(self.template, cv2.COLOR_BGR2GRAY)
        else:
            self.template_gray = None
        self.template_h, self.template_w = self.template.shape[:2]
        logger.info(f"模板加载成功: {self.template_w}x{self.template_h}")
        return True

    def init_camera(self):
        if self.hwnd is None:
            return False
        client_rect = self.get_client_rect_screen()
        region = self.clamp_region_to_screen(client_rect)
        if not region or region[2] <= region[0] or region[3] <= region[1]:
            return False
        with self._camera_lock:
            try:
                if self.camera is None or getattr(self.camera, "is_released", False):
                    self.camera = dxcam.create(region=region, output_color="BGR")
                elif getattr(self.camera, "is_capturing", False):
                    self.camera.stop()
                # dxcam.create 会复用同一输出的实例，因此 region 必须显式
                # 传给 start，否则重新找到窗口后仍可能沿用旧截图区域。
                self.camera.start(region=region, target_fps=60, video_mode=True)
            except Exception as e:
                logger.error(f"摄像头初始化失败: {e}")
                return False
            self.last_rect = client_rect
            self._camera_region = region
            self._last_region_check = time.monotonic()
            self.capture_origin = (region[0], region[1])
            self.status = "摄像头就绪"
            return True

    def refresh_capture_region(self, force=False):
        """窗口移动、恢复或缩放后，让连续截图自动跟随新的客户区。"""
        if self.hwnd is None:
            return False
        now = time.monotonic()
        if (
            not force
            and self.camera is not None
            and now - self._last_region_check < CAPTURE_REGION_CHECK_INTERVAL
        ):
            return True

        try:
            client_rect = self.get_client_rect_screen()
            region = self.clamp_region_to_screen(client_rect)
        except Exception as e:
            logger.debug(f"读取游戏窗口截图区域失败: {e}")
            return False

        self._last_region_check = now
        if not region or region[2] <= region[0] or region[3] <= region[1]:
            return False
        if self.camera is None:
            return self.init_camera()
        if region == self._camera_region:
            self.last_rect = client_rect
            self.capture_origin = (region[0], region[1])
            return True

        with self._camera_lock:
            try:
                if getattr(self.camera, "is_capturing", False):
                    self.camera.stop()
                self.camera.start(region=region, target_fps=60, video_mode=True)
            except Exception as e:
                logger.error(f"更新游戏截图区域失败: {e}")
                return False
            old_region = self._camera_region
            self._camera_region = region
            self.last_rect = client_rect
            self.capture_origin = (region[0], region[1])
            logger.info(f"游戏窗口区域已变化，截图区域从 {old_region} 更新为 {region}")
            return True

    def clamp_region_to_screen(self, region):
        """将区域限制在屏幕范围内"""
        user32 = ctypes.windll.user32
        screen_w = user32.GetSystemMetrics(0)
        screen_h = user32.GetSystemMetrics(1)
        left = max(0, region[0])
        top = max(0, region[1])
        right = min(screen_w, region[2])
        bottom = min(screen_h, region[3])
        return (left, top, right, bottom)

    def capture(self):
        if not self.camera or self.hwnd is None:
            return None
        if not self.refresh_capture_region():
            return None
        # 使用 get_latest_frame 获取连续捕获的最新帧
        with self._camera_lock:
            frame = self.camera.get_latest_frame()
        if SAVE_DEBUG_SCREENSHOT and frame is not None:
            cv2.imwrite("debug_screenshot.png", frame)
        return frame

    @staticmethod
    def _append_unique_scale(scales, value):
        value = max(MATCH_SCALE_MIN, min(MATCH_SCALE_MAX, float(value)))
        if not any(abs(value - existing) < 0.01 for existing in scales):
            scales.append(value)

    def _candidate_template_scales(self, screen):
        """返回原尺寸，以及由当前客户区分辨率推导出的模板尺寸。"""
        scales = [1.0]
        reference_w, reference_h = TEMPLATE_REFERENCE_SIZE
        if reference_w <= 0 or reference_h <= 0:
            return scales
        screen_h, screen_w = screen.shape[:2]
        expected = min(screen_w / reference_w, screen_h / reference_h)
        if abs(expected - 1.0) < MATCH_SCALE_TRIGGER_DELTA:
            return scales
        for factor in MATCH_SCALE_FACTORS:
            self._append_unique_scale(scales, expected * factor)
        return scales

    def find_target(self, screen, threshold=None):
        """模板匹配查找目标

        参数:
            screen: 截图帧
            threshold: 可选阈值，None 时使用 config.THRESHOLD
        返回:
            (cx, cy, w, h, conf) 或 None
        """
        if screen is None or self.template is None:
            return None
        if USE_GRAY and self.template_gray is not None:
            screen_gray = cv2.cvtColor(screen, cv2.COLOR_BGR2GRAY)
            source_template = self.template_gray
        else:
            screen_gray = screen
            source_template = self.template

        use_threshold = threshold if threshold is not None else THRESHOLD
        best = None
        accepted = None
        for scale in self._candidate_template_scales(screen):
            if abs(scale - 1.0) < 0.01:
                candidate = source_template
            else:
                candidate = cv2.resize(
                    source_template,
                    None,
                    fx=scale,
                    fy=scale,
                    interpolation=cv2.INTER_LINEAR,
                )
            candidate_h, candidate_w = candidate.shape[:2]
            if (
                candidate_h <= 1
                or candidate_w <= 1
                or screen_gray.shape[0] < candidate_h
                or screen_gray.shape[1] < candidate_w
            ):
                continue

            result = cv2.matchTemplate(
                screen_gray,
                candidate,
                cv2.TM_CCOEFF_NORMED,
            )
            _, max_val, _, max_loc = cv2.minMaxLoc(result)
            required = use_threshold
            if abs(scale - 1.0) >= 0.01:
                required = min(0.99, required + MATCH_SCALED_THRESHOLD_BONUS)
            match = (
                float(max_val),
                max_loc,
                candidate_w,
                candidate_h,
                scale,
                required,
            )
            if best is None or match[0] > best[0]:
                best = match
            if max_val >= required and (accepted is None or match[0] > accepted[0]):
                accepted = match

        if best is None:
            self.last_match_confidence = 0.0
            self.last_match_scale = 1.0
            self.last_match_size = (0, 0)
            self.last_match_location = None
            return None

        # 即使未达到阈值，也记录最高分，供日志诊断。
        self.last_match_confidence = best[0]
        self.last_match_scale = best[4]
        self.last_match_size = (best[2], best[3])
        self.last_match_location = best[1]

        if accepted is not None:
            max_val, max_loc, matched_w, matched_h, matched_scale, _ = accepted
            self.last_match_confidence = max_val
            self.last_match_scale = matched_scale
            self.last_match_size = (matched_w, matched_h)
            self.last_match_location = max_loc
            cx = max_loc[0] + round(matched_w / 2)
            cy = max_loc[1] + round(matched_h / 2)
            return (cx, cy, matched_w, matched_h, max_val)
        return None

    def load_template_by_name(self, name):
        """根据图片文件名加载模板（带缓存）

        参数:
            name: 图片文件名（如 "开始.png"）
        返回:
            True/False
        """
        # 已缓存则直接恢复并返回
        if name in self._templates:
            template, template_gray, w, h = self._templates[name]
            self.template = template
            self.template_gray = template_gray
            self.template_w = w
            self.template_h = h
            return True

        # 从 pic 目录加载（兼容原有 TEMPLATE_PATH 模式）
        pic_path = os.path.join(os.path.dirname(__file__), "pic", name)
        if not os.path.exists(pic_path):
            logger.error(f"模板文件不存在: {pic_path}")
            return False

        # 使用 imdecode + np.fromfile 读取（支持中文路径）
        try:
            arr = np.fromfile(pic_path, dtype=np.uint8)
            template = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        except Exception as e:
            logger.error(f"读取模板失败: {e}")
            return False

        if template is None:
            logger.error(f"无法解码模板图片: {name}")
            return False

        # 计算灰度版本
        if USE_GRAY:
            template_gray = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)
        else:
            template_gray = None

        h, w = template.shape[:2]

        # 写入缓存
        self._templates[name] = (template, template_gray, w, h)

        # 同步到当前实例字段（供 find_target 使用）
        self.template = template
        self.template_gray = template_gray
        self.template_w = w
        self.template_h = h

        return True

    def find_target_by_name(self, name):
        """根据模板名识别目标

        流程: load_template_by_name -> capture -> find_target
        阈值查表: IMAGE_THRESHOLDS.get(name, THRESHOLD)
        返回:
            (cx, cy, w, h, conf) 或 None
        """
        with self._match_lock:
            self.last_match_name = name
            if not self.load_template_by_name(name):
                self.last_match_confidence = 0.0
                return None

            screen = self.capture()
            if screen is None:
                self.last_match_confidence = 0.0
                return None

            # 阈值查表，不硬编码
            threshold = IMAGE_THRESHOLDS.get(name, THRESHOLD)
            return self.find_target(screen, threshold=threshold)

    def click_target_by_name(self, name):
        """识别并点击指定模板（严格中心，不偏移）

        返回:
            True/False
        """
        result = self.find_target_by_name(name)
        if result is None:
            return False
        cx, cy, w, h, conf = result

        # 通知覆盖层（绿框）— 使用截图区域原点对齐
        if self.capture_origin is not None:
            ox, oy = self.capture_origin
        else:
            pt = win32gui.ClientToScreen(self.hwnd, (0, 0))
            ox, oy = pt[0], pt[1]
        rect_x = ox + cx - w // 2
        rect_y = oy + cy - h // 2
        send_coords_to_overlay(rect_x, rect_y, w, h)

        # 严格点击中心，不偏移
        self.click(cx, cy)
        return True

    def check_target(self, name):
        """仅识别不点击，用于 LOOP2 中检查 F10 识别

        返回:
            (x, y, conf) 或 None
        """
        result = self.find_target_by_name(name)
        if result is None:
            return None
        cx, cy, w, h, conf = result
        return (cx, cy, conf)

    def click(self, win_x, win_y):
        """点击：优先驱动级，回退SendInput + mouse_event"""
        assert self.hwnd is not None, "No window handle available for click"
        client_left_top = win32gui.ClientToScreen(self.hwnd, (0, 0))
        screen_x = client_left_top[0] + win_x
        screen_y = client_left_top[1] + win_y

        # 方法1: 驱动级点击（绕过DX11 RawInput独占）
        if self.use_driver and self.driver.available:
            if self.driver.click(screen_x, screen_y):
                return screen_x, screen_y

        # 方法2: SendInput (绝对坐标)
        try:
            send_input_click(screen_x, screen_y)
        except:
            pass

        # 方法3: mouse_event 回退
        try:
            ctypes.windll.user32.SetCursorPos(screen_x, screen_y)
            time.sleep(0.005)
            ctypes.windll.user32.mouse_event(0x0002, 0, 0, 0, 0)  # LEFTDOWN
            time.sleep(0.005)
            ctypes.windll.user32.mouse_event(0x0004, 0, 0, 0, 0)  # LEFTUP
        except:
            pass

        return screen_x, screen_y

    def run_once(self):
        if self.hwnd is None:
            if not self.find_window():
                self.status = "未找到窗口"
                send_coords_to_overlay(0, 0, 0, 0)
                return
        if self.hwnd is None:
            return

        screen = self.capture()
        if screen is None:
            return

        target = self.find_target(screen)
        # 使用截图区域原点对齐 overlay
        if self.capture_origin is not None:
            ox, oy = self.capture_origin
        else:
            pt = win32gui.ClientToScreen(self.hwnd, (0, 0))
            ox, oy = pt[0], pt[1]

        if target:
            cx, cy, w, h, conf = target
            self.last_x = cx
            self.last_y = cy
            self.last_conf = conf
            self.status = "已识别"

            # 发送框选区域给覆盖层（绿色框）
            rect_x = ox + cx - w // 2
            rect_y = oy + cy - h // 2
            send_coords_to_overlay(rect_x, rect_y, w, h)

            # 点击
            try:
                self.click(cx, cy)
                self.click_count += 1
            except Exception as e:
                self.status = f"点击失败"
        else:
            self.status = "搜索中"
            send_coords_to_overlay(0, 0, 0, 0)

    def stop(self):
        """停止运行"""
        self.running = False

    def start(self):
        """启动循环（阻塞调用，供子线程使用）

        注意: 此方法为向后兼容保留，供旧版 GUI 调用。
        flow_engine.py 编排时应使用 find_target_by_name /
        click_target_by_name / check_target 等工具方法。
        """
        if not self.load_template():
            self.status = "模板加载失败"
            return False
        if not self.find_window():
            self.status = "未找到窗口"
            return False
        assert self.hwnd is not None
        if not self.init_camera():
            self.status = "摄像头初始化失败"
            return False

        # 初始化驱动级点击
        if not is_driver_installed():
            # 驱动未安装
            self.use_driver = False
            self.driver_msg = "驱动未安装（点击「安装驱动」按钮）"
            self.status = "运行中（SendInput，游戏内无效）"
        elif not is_driver_loaded():
            # 驱动已安装但未重启（驱动栈未加载）
            self.use_driver = False
            self.driver_msg = (
                "驱动已安装但未加载！必须重启电脑后驱动才会生效。"
                "重启后再次运行程序即可在游戏内点击。"
            )
            self.status = "需重启电脑（驱动未加载）"
        else:
            # 驱动已加载，初始化点击器
            ok, msg = self.driver.init()
            self.driver_msg = msg
            if ok:
                self.use_driver = True
                self.status = "驱动级运行中"
            else:
                self.use_driver = False
                self.status = f"驱动初始化失败→SendInput"

        self.running = True
        try:
            while self.running:
                self.run_once()
                time.sleep(INTERVAL)
        except Exception as e:
            self.status = f"运行错误: {e}"
        finally:
            self.running = False
            self.status = "已停止"
            send_coords_to_overlay(0, 0, 0, 0)
            if self.camera:
                self.camera.stop()
            if self.use_driver:
                self.driver.destroy()
        return True


if __name__ == "__main__":
    # 工具类自测
    c = Clicker()
    print(f"窗口查找: {c.find_window()}")
    if c.hwnd:
        print(f"模板加载: {c.load_template_by_name('开始.png')}")
        print(f"摄像头初始化: {c.init_camera()}")
        import time
        time.sleep(0.5)
        result = c.find_target_by_name("开始.png")
        print(f"识别开始.png: {result}")
        c.camera.stop() if c.camera else None
