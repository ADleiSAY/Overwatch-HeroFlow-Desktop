# flow_engine.py
"""
状态机驱动的流程引擎
编排 Clicker / DriverKeyboard / DriverClicker / HeroSelector 完成自动匹配流程

状态流转:
  WAIT_READY → FIND_START → FIND_ARCADE → FIND_DEATHMATCH
  → FIND_MATCH(识别已找到比赛.png → 等5s) → SELECT_HERO(识别英雄3s)
    - 识别到英雄 → 等5s锁定 → FIND_CONTINUE(识别继续.png) → LOOP2
    - 3s未识别到英雄 → LOOP2
  → LOOP2(识别赞赏玩家.png) → 回到 SELECT_HERO 循环
  → (时长到 + 赞赏玩家识别) → END
"""
import time
import threading
import subprocess
import ctypes
from enum import Enum

import win32gui
import win32api

import config
from logger import logger
from driver_click import VK_CTRL, VK_A, VK_D, VK_E, VK_ALT, VK_F4, VK_F10
from window_geometry import get_client_geometry


# 循环结束识别图片（识别到后按F10，不点击）
LOOP_END_IMAGE = "再次排队.png"
# 英雄识别超时（秒）：超时后直接进入循环2
HERO_SELECT_TIMEOUT = 3.0
# 点击已找到比赛后等待时长（秒）
MATCH_FOUND_WAIT = 5.0
# 英雄锁定动画等待时长（秒）
HERO_LOCK_WAIT = 5.0


class FlowState(Enum):
    """流程状态枚举"""
    WAIT_READY = "等待就绪"
    FIND_START = "识别开始.png"
    FIND_ARCADE = "识别街机先锋.png"
    FIND_DEATHMATCH = "识别死斗.png"
    FIND_MATCH = "识别已找到比赛.png"
    SELECT_HERO = "选择英雄"
    FIND_CONTINUE = "识别继续.png"
    LOOP2 = "循环2: 鼠标右移+技能"
    END = "结束"


# 步骤映射（用于 UI 显示当前/下一步）
# 注：循环结束识别改为"赞赏玩家.png"（原"按下F10再次排队.png"）
STEP_FLOW = [
    ("WAIT_READY", "等待就绪", "识别开始.png"),
    ("FIND_START", "识别开始.png", "识别街机先锋.png"),
    ("FIND_ARCADE", "识别街机先锋.png", "识别死斗.png"),
    ("FIND_DEATHMATCH", "识别死斗.png", "识别已找到比赛.png"),
    ("FIND_MATCH", "识别已找到比赛.png", "选择英雄"),
    ("SELECT_HERO", "选择英雄", "识别继续.png"),
    ("FIND_CONTINUE", "识别继续.png", "进入循环2"),
    ("LOOP2", "循环2: 鼠标右移+技能", f"识别{LOOP_END_IMAGE}"),
]


class FlowEngine:
    def __init__(self, clicker, keyboard, mouse_driver, hero_selector, callbacks=None, options=None):
        """
        参数:
            clicker: Clicker 实例（已 find_window + init_camera）
            keyboard: DriverKeyboard 实例（已 init）
            mouse_driver: DriverClicker 实例（已 init，用于 move_relative）
            hero_selector: HeroSelector 实例
            callbacks: dict 可选回调
                - 'on_state_change': (current_state, current_op, next_op) -> None
                - 'on_log': (level, message) -> None
                - 'on_overlay': (x, y, w, h, image_name, step_name, next_step, conf) -> None
                - 'on_finish': () -> None
            options: dict 运行参数
                - 'duration_s': 总时长（秒），None=无限制模式
                - 'auto_shutdown': "none"/"stop_only"/"shutdown"/"both"
                - 'mouse_speed': 鼠标右移速度（默认 500 px/s）
                - 'move_duration': 鼠标右移时长（默认 3.0s）
        """
        self.clicker = clicker
        self.keyboard = keyboard
        self.mouse_driver = mouse_driver
        self.hero_selector = hero_selector
        self.callbacks = callbacks or {}
        self.options = options or {}

        # 运行控制
        self._running = True
        self._paused = threading.Event()    # set=暂停
        self._stop_event = threading.Event()  # set=停止（F8）

        # 时长监控
        self._duration_start_time = None   # 首次进入 SELECT_HERO 时设置
        self._time_up_notified = False     # LOOP2 结束后标记

        # F10 检测标志（供 _check_f10 与 _handle_loop2 通信）
        self._f10_detected = False
        self._loop_end_match = None
        self._last_recognition_diag = {}

    # ==================== 主循环 ====================

    def run_loop2_continuous(self):
        """只运行循环2，不识别再次排队.png，一直循环直到 stop() 被调用"""
        self._running = True
        self._start_time = time.time()
        self._log('info', "启动循环2持续模式（不识别退出条件）")

        move_duration = self.options.get('move_duration', config.MOVE_DURATION)
        mouse_speed = self.options.get('mouse_speed', config.MOUSE_MOVE_SPEED)
        total_dx = int(mouse_speed * move_duration) // 4

        loop_count = 0
        while self._running:
            if self._paused.is_set():
                time.sleep(0.1)
                continue
            loop_count += 1
            self._log('info', f"循环2 第{loop_count}组开始（视角右移后左移，各{total_dx}px）")

            # 1. 在游戏客户区中心点击一次，使《守望先锋》获得焦点
            if not self._click_game_center_to_focus():
                time.sleep(0.1)
                continue

            # 2. 鼠标右移
            if self.mouse_driver.available:
                self.mouse_driver.move_relative(
                    total_dx, 0, move_duration, mouse_speed,
                    check_callback=lambda: not self._running or self._paused.is_set()
                )
                if not self._running:
                    break
            else:
                self._move_relative_fallback(total_dx, 0, move_duration, mouse_speed)
                if not self._running:
                    break

            if self._paused.is_set():
                continue

            # 2. 鼠标左移，与右移时长相同
            if self.mouse_driver.available:
                self.mouse_driver.move_relative(
                    -total_dx, 0, move_duration, mouse_speed,
                    check_callback=lambda: not self._running or self._paused.is_set()
                )
                if not self._running:
                    break
            else:
                self._move_relative_fallback(-total_dx, 0, move_duration, mouse_speed)
                if not self._running:
                    break

            if self._paused.is_set():
                continue

            # 3. 按住 D 键
            if not self._running:
                break
            self.keyboard.key_down(VK_D)
            start_t = time.time()
            while time.time() - start_t < move_duration:
                if not self._running:
                    self.keyboard.key_up(VK_D)
                    break
                if self._paused.is_set():
                    break
                time.sleep(config.LOOP2_CHECK_INTERVAL)
            self.keyboard.key_up(VK_D)
            if not self._running:
                break
            if self._paused.is_set():
                continue

            # 4. 按住 A 键，与 D 键时长相同
            if not self._running:
                break
            self.keyboard.key_down(VK_A)
            start_t = time.time()
            while time.time() - start_t < move_duration:
                if not self._running:
                    self.keyboard.key_up(VK_A)
                    break
                if self._paused.is_set():
                    break
                time.sleep(config.LOOP2_CHECK_INTERVAL)
            self.keyboard.key_up(VK_A)
            if not self._running:
                break
            if self._paused.is_set():
                continue

            # 5. 左键点击
            if not self._running:
                break
            self._click_current_position()
            time.sleep(0.05)

            # 6. Ctrl
            if not self._running:
                break
            self.keyboard.press_key(VK_CTRL, duration_s=config.CTRL_HOLD_DURATION)

            # 7. E
            if not self._running:
                break
            self.keyboard.press_key(VK_E, duration_s=config.KEY_HOLD_DURATION)

        self._log('info', "循环2持续模式已停止")
        self._notify_finish()

    def run(self):
        """主循环（在子线程运行）"""
        self._running = True
        self._start_time = time.time()

        state = FlowState.WAIT_READY
        while self._running and state != FlowState.END:
            # 暂停检测
            if self._paused.is_set():
                time.sleep(0.1)
                continue

            # 通知状态变化
            self._notify_state_change(state)

            # 时长到且本轮 F10 已识别 → 结束（跳过 FIND_MATCH，改在 SELECT_HERO 判断）
            if state == FlowState.SELECT_HERO and self._is_time_up() and self._time_up_notified:
                state = FlowState.END
                break

            # 状态处理
            if state == FlowState.WAIT_READY:
                if not self._handle_wait_ready():
                    break
                state = FlowState.FIND_START

            elif state == FlowState.FIND_START:
                if not self._find_and_click("开始.png", "识别开始.png", "识别街机先锋.png"):
                    break
                state = FlowState.FIND_ARCADE

            elif state == FlowState.FIND_ARCADE:
                if not self._find_and_click("街机先锋.png", "识别街机先锋.png", "识别死斗.png"):
                    break
                state = FlowState.FIND_DEATHMATCH

            elif state == FlowState.FIND_DEATHMATCH:
                # 死斗后识别"已找到比赛.png"
                if not self._find_and_click("死斗.png", "识别死斗.png", "识别已找到比赛.png"):
                    break
                state = FlowState.FIND_MATCH

            elif state == FlowState.FIND_MATCH:
                # 识别"已找到比赛.png" → 点击 → 等5秒
                if not self._find_and_click("已找到比赛.png", "识别已找到比赛.png", "选择英雄"):
                    break
                self._log('info', f"已找到比赛，等待 {MATCH_FOUND_WAIT}s 进入英雄选择...")
                self._sleep_interruptible(MATCH_FOUND_WAIT)
                state = FlowState.SELECT_HERO

            elif state == FlowState.SELECT_HERO:
                # 时长监控起点（首次进入时记录）
                if self._duration_start_time is None:
                    self._duration_start_time = time.time()
                hero_name = self.hero_selector.next_hero()
                hero_img = f"守望先锋所有英雄/{hero_name}.png"
                # 选英雄期间彻底禁用 overlay（不绘制绿框、不绘制顶部步骤文字）
                # 避免 overlay 窗口的置顶/文字遮挡影响英雄识别和点击
                self._notify_overlay(0, 0, 0, 0, "", "", "", 0.0)
                # 识别英雄3秒，超时直接进入循环2
                start_time = time.time()
                hero_clicked = False
                while self._running:
                    if self._paused.is_set():
                        time.sleep(0.1)
                        continue
                    if (time.time() - start_time) >= HERO_SELECT_TIMEOUT:
                        self._log('info', f"英雄 {HERO_SELECT_TIMEOUT}s 未识别到，直接进入循环2")
                        break
                    if not self._wait_for_window():
                        continue
                    if not self._prepare_recognition_window():
                        time.sleep(config.RECOGNITION_RETRY_INTERVAL)
                        continue
                    try:
                        result = self.clicker.find_target_by_name(hero_img)
                    except Exception as e:
                        self._log('error', f"识别 {hero_img} 异常: {e}")
                        time.sleep(config.RECOGNITION_RETRY_INTERVAL)
                        continue
                    if result:
                        cx, cy, w, h, conf = result
                        self._log('info', f"识别到 {hero_img} (conf={conf:.2f})，开始选择流程")
                        # 1. 激活游戏窗口
                        self._activate_window()
                        time.sleep(0.3)
                        # 2. 点击英雄图片位置（第一次）
                        self.clicker.click(cx, cy)
                        self._log('info', f"第一次点击 ({cx}, {cy})")
                        # 3. 等待0.5s
                        self._sleep_interruptible(0.5)
                        # 4. 在英雄图片位置再点击一次
                        self.clicker.click(cx, cy)
                        self._log('info', f"第二次点击 ({cx}, {cy})")
                        # 5. 两段线性移动：先水平移到英雄x，再垂直移到英雄下1/4处
                        self._two_stage_move(cx, cy, h)
                        # 6. 驱动级点击
                        self.clicker.click(cx, cy)
                        self._log('info', f"驱动级点击 ({cx}, {cy})")
                        hero_clicked = True
                        break
                    self._log_recognition_miss(hero_img)
                    time.sleep(config.RECOGNITION_RETRY_INTERVAL)

                if not self._running:
                    break
                if not hero_clicked:
                    # 英雄未识别到，也必须先识别并点击"继续.png"才进入循环2
                    state = FlowState.FIND_CONTINUE
                else:
                    self._log('info', f"英雄已双击，等待 {HERO_LOCK_WAIT}s 锁定...")
                    self._sleep_interruptible(HERO_LOCK_WAIT)
                    state = FlowState.FIND_CONTINUE

            elif state == FlowState.FIND_CONTINUE:
                # 识别继续.png → 点击 → 进入循环2
                if not self._find_and_click("继续.png", "识别继续.png", "进入循环2"):
                    break
                state = FlowState.LOOP2

            elif state == FlowState.LOOP2:
                result = self._handle_loop2()
                if not result:  # 被停止
                    break
                # 识别到"再次排队.png"后必须确认画面已经响应，不能只以发送调用成功为准。
                if not self._requeue_with_verification():
                    if not self._running:
                        break
                    self._log('warn', "再次排队操作尚未生效，保持当前状态后继续重试")
                    self._sleep_interruptible(1.0)
                    state = FlowState.LOOP2
                    continue
                # 跳转到识别"已找到比赛.png"
                self._time_up_notified = True if self._is_time_up() else False
                state = FlowState.FIND_MATCH
                # 时长到则结束
                if self._is_time_up():
                    state = FlowState.END

        # 结束后动作
        self._execute_shutdown()
        self._notify_finish()

    # ==================== 控制接口 ====================

    def pause(self):
        """暂停"""
        self._paused.set()
        self._log('warn', "流程已暂停")

    def resume(self):
        """恢复"""
        self._paused.clear()
        self._log('info', "流程已恢复")

    def stop(self):
        """停止（F8 或主动停止，不执行 Alt+F4 与关机）"""
        self._running = False
        self._stop_event.set()
        self._log('warn', "流程已被强制停止（F8）")

    def finish_due_to_timeout(self):
        """到达计划结束时间；结束流程，但保留正常的结束后动作。"""
        self._running = False
        self._log('info', "流程已到计划结束时间")

    def _sleep_interruptible(self, seconds):
        """可中断的睡眠（F8 停止立即退出；暂停时阻塞，恢复后继续等剩余时间）

        参数:
            seconds: 要等待的秒数
        返回:
            True=正常等完，False=被停止
        """
        remaining = seconds
        while remaining > 0:
            # F8 停止：立即退出
            if not self._running:
                return False
            if self._stop_event.wait(0.1):
                return False
            # 暂停时不消耗 remaining，等恢复后继续
            if self._paused.is_set():
                time.sleep(0.1)
                continue
            remaining -= 0.1
        return True

    # ==================== 时长监控 ====================

    def _is_time_up(self):
        """检查时长是否到（无限制模式永远返回 False）"""
        duration_s = self.options.get('duration_s')
        if duration_s is None:
            return False
        if self._duration_start_time is None:
            return False
        elapsed = time.time() - self._duration_start_time
        return elapsed >= duration_s

    # ==================== 窗口丢失处理 ====================

    def _wait_for_window(self):
        """窗口检查，丢失时每 5 秒重试"""
        if self.clicker.hwnd and win32gui.IsWindow(self.clicker.hwnd):
            return True
        self._log('warn', "Overwatch 窗口丢失，重试查找...")
        while self._running:
            if self._paused.is_set():
                time.sleep(0.1)
                continue
            if self.clicker.find_window():
                self._log('info', "Overwatch 窗口已重新找到")
                # 重新初始化摄像头（新窗口可能位置不同）
                try:
                    if self.clicker.camera:
                        self.clicker.camera.stop()
                except Exception:
                    pass
                try:
                    self.clicker.init_camera()
                except Exception as e:
                    self._log('error', f"摄像头重新初始化失败: {e}")
                return True
            time.sleep(config.WINDOW_RETRY_INTERVAL)
        return False

    def _prepare_recognition_window(self):
        """保证游戏内容无遮挡，并在恢复/移动后同步截图区域。"""
        hwnd = self.clicker.hwnd
        if not hwnd or not win32gui.IsWindow(hwnd):
            return False
        activated = False
        try:
            foreground = ctypes.windll.user32.GetForegroundWindow()
        except Exception:
            foreground = None
        if foreground != hwnd:
            if not self._activate_window():
                return False
            activated = True
            if not self._sleep_interruptible(config.RECOGNITION_FOCUS_SETTLE_TIME):
                return False

        refresh = getattr(self.clicker, "refresh_capture_region", None)
        if refresh is not None:
            try:
                if not refresh(force=activated):
                    self._log('debug', "游戏截图区域尚未就绪")
                    return False
            except Exception as e:
                self._log('debug', f"刷新游戏截图区域异常: {e}")
                return False
        return True

    def _log_recognition_miss(self, image_name):
        """按图片节流记录最高匹配分，避免每 50ms 刷屏。"""
        now = time.monotonic()
        last = self._last_recognition_diag.get(image_name, 0.0)
        if now - last < config.RECOGNITION_DIAGNOSTIC_INTERVAL:
            return
        self._last_recognition_diag[image_name] = now
        confidence = float(getattr(self.clicker, "last_match_confidence", 0.0) or 0.0)
        scale = float(getattr(self.clicker, "last_match_scale", 1.0) or 1.0)
        threshold = config.IMAGE_THRESHOLDS.get(image_name, config.THRESHOLD)
        self._log(
            'debug',
            f"未识别到 {image_name}：最高置信度={confidence:.3f}，"
            f"阈值={threshold:.3f}，模板缩放={scale:.3f}",
        )

    # ==================== 截图区域原点 ====================

    def _get_capture_origin(self):
        """获取截图区域原点（物理屏幕坐标）

        dxcam 截图帧的 (0,0) 对应此原点。
        优先使用 clicker.capture_origin（init_camera 时存储的 clamp 后原点），
        若不可用则回退到 ClientToScreen（窗口客户区原点）。
        返回: (origin_x, origin_y)
        """
        if self.clicker.capture_origin is not None:
            return self.clicker.capture_origin
        # 回退：窗口客户区原点
        pt = win32gui.ClientToScreen(self.clicker.hwnd, (0, 0))
        return (pt[0], pt[1])

    # ==================== 通用识别+点击 ====================

    def _find_and_click(self, image_name, step_name, next_step, timeout=None):
        """识别 + 点击图片中心（每帧实时发送 overlay）

        参数:
            image_name: 图片文件名
            step_name: 当前步骤名（显示用）
            next_step: 下一步名（显示用）
            timeout: 超时秒数（None=无限重试，>0=超时返回 None）

        返回:
            True=成功点击，False=被停止，None=超时（仅在 timeout 指定时）
        """
        start_time = time.time()
        while self._running:
            if self._paused.is_set():
                time.sleep(0.1)
                continue

            # 超时检查
            if timeout is not None and (time.time() - start_time) >= timeout:
                self._log('info', f"识别 {image_name} 超时({timeout}s)，切换下一步")
                return None

            # 窗口检查
            if not self._wait_for_window():
                continue
            if not self._prepare_recognition_window():
                time.sleep(config.RECOGNITION_RETRY_INTERVAL)
                continue

            # 识别
            try:
                result = self.clicker.find_target_by_name(image_name)
            except Exception as e:
                self._log('error', f"识别 {image_name} 异常: {e}")
                # 异常时通知 overlay 清除绿框
                self._notify_overlay(0, 0, 0, 0, image_name, step_name, next_step, 0.0)
                time.sleep(config.RECOGNITION_RETRY_INTERVAL)
                continue

            if result:
                cx, cy, w, h, conf = result
                # 先通知 overlay 实时跟随绿框（在点击前发送，确保绿框立即可见）
                # 使用截图区域原点（capture_origin）而非 ClientToScreen，
                # 因为 dxcam 截图帧的 (0,0) 对应的是 clamp 后的区域原点
                try:
                    ox, oy = self._get_capture_origin()
                    self._notify_overlay(
                        ox + cx - w // 2,
                        oy + cy - h // 2,
                        w, h, image_name, step_name, next_step, conf
                    )
                except Exception as e:
                    self._log('debug', f"overlay 通知失败: {e}")
                # 点击中心（严格不偏移）
                self.clicker.click(cx, cy)
                self._log('info', f"识别到 {image_name} (conf={conf:.2f}) 并点击中心 ({cx}, {cy})")
                # 点击后等待 0.5s 再进入下一步
                self._sleep_interruptible(0.5)
                return True

            # 未识别到，通知 overlay 清除绿框（实时反馈）
            self._notify_overlay(0, 0, 0, 0, image_name, step_name, next_step, 0.0)
            self._log_recognition_miss(image_name)
            time.sleep(config.RECOGNITION_RETRY_INTERVAL)

        return False

    # ==================== 等待就绪 ====================

    def _handle_wait_ready(self):
        """5 秒倒计时"""
        self._log('info', "请确认：守望先锋窗口化 + 最小化 + 30fps，5 秒后开始")
        for i in range(5, 0, -1):
            if not self._running:
                return False
            self._log('info', f"{i} 秒后开始...")
            time.sleep(1)
        return True

    # ==================== 循环2 ====================

    def _check_f10(self):
        """循环结束识别回调（供 move_relative / D 键循环使用）
        识别"再次排队.png"（识别到后按F10，不点击）
        返回 True 时停止当前动作（识别到再次排队或暂停/停止）
        """
        if not self._running or self._paused.is_set():
            return True
        # 循环动作期间用户切到其他窗口时，先中断当前动作并恢复游戏前台，
        # 避免截图被遮挡，也避免后续按键发送到其他应用。
        if not self._prepare_recognition_window():
            return True
        try:
            result = self.clicker.check_target(LOOP_END_IMAGE)
            if result:
                cx, cy, conf = result
                self._f10_detected = True
                self._loop_end_match = (cx, cy, conf)
                # 通知 overlay 显示识别绿框
                try:
                    # 多尺度匹配时使用实际命中的模板尺寸。
                    w, h = getattr(
                        self.clicker,
                        "last_match_size",
                        (self.clicker.template_w, self.clicker.template_h),
                    )
                    ox, oy = self._get_capture_origin()
                    self._notify_overlay(
                        ox + cx - w // 2,
                        oy + cy - h // 2,
                        w, h, LOOP_END_IMAGE,
                        "循环2: 鼠标右移+技能", f"识别{LOOP_END_IMAGE}", conf
                    )
                except Exception:
                    pass
                self._log('info', f"循环2 中识别到 {LOOP_END_IMAGE}")
                return True
            else:
                # 未识别到，清除绿框
                self._notify_overlay(0, 0, 0, 0, LOOP_END_IMAGE,
                                     "循环2: 鼠标右移+技能", f"识别{LOOP_END_IMAGE}", 0.0)
                self._log_recognition_miss(LOOP_END_IMAGE)
        except Exception as e:
            self._log('debug', f"循环结束识别异常: {e}")
        return False

    def _send_f10(self):
        """模拟 F10 按键；返回输入后端是否接受了按下和抬起事件。"""
        try:
            if self.keyboard and self.keyboard.available:
                sent = self.keyboard.press_key(
                    VK_F10, duration_s=config.REQUEUE_KEY_HOLD_DURATION
                )
                # 兼容旧的键盘实现/测试替身：只有显式 False 才判定发送失败。
                if sent is False:
                    self._log('warn', "驱动拒绝了 F10 按下或抬起事件")
                    return False
                self._log('info', "驱动已接受 F10 按下和抬起事件")
                return True
            else:
                # 回退：Win32 SendInput
                ctypes.windll.user32.keybd_event(VK_F10, 0, 0, 0)
                time.sleep(config.REQUEUE_KEY_HOLD_DURATION)
                ctypes.windll.user32.keybd_event(VK_F10, 0, 0x0002, 0)
                self._log('info', "已调用 Win32 F10 回退")
                return True
        except Exception as e:
            self._log('error', f"F10 按键发送失败: {e}")
            return False

    def _wait_for_requeue_response(self, timeout=None):
        """确认“再次排队”提示连续两帧消失，避免单帧漏识别造成误判。"""
        if timeout is None:
            timeout = config.REQUEUE_VERIFY_TIMEOUT

        deadline = time.time() + timeout
        consecutive_misses = 0
        while self._running and time.time() < deadline:
            if self._paused.is_set():
                time.sleep(config.REQUEUE_VERIFY_INTERVAL)
                continue
            try:
                result = self.clicker.check_target(LOOP_END_IMAGE)
            except Exception as e:
                self._log('debug', f"验证再次排队画面异常: {e}")
                consecutive_misses = 0
            else:
                if result:
                    cx, cy, conf = result
                    self._loop_end_match = (cx, cy, conf)
                    consecutive_misses = 0
                else:
                    consecutive_misses += 1
                    if consecutive_misses >= 2:
                        self._log('info', "再次排队提示已消失，确认操作生效")
                        return True

            if not self._sleep_interruptible(config.REQUEUE_VERIFY_INTERVAL):
                return False
        return False

    def _requeue_with_verification(self):
        """激活游戏并执行 F10；画面无响应时重试，最后点击提示中心兜底。"""
        self._log('info', "识别到再次排队.png，开始执行带画面确认的再次排队")

        if not self._activate_window():
            self._log('warn', "F10 前游戏未获得焦点，尝试用窗口中心单击恢复焦点")
            if not self._click_game_center_to_focus():
                self._log('warn', "无法确认游戏焦点，仍将尝试驱动级 F10")

        for attempt in range(1, config.REQUEUE_KEY_ATTEMPTS + 1):
            if not self._running:
                return False
            self._log(
                'info',
                f"发送 F10 再次排队（第 {attempt}/{config.REQUEUE_KEY_ATTEMPTS} 次）"
            )
            if not self._send_f10():
                self._log('warn', f"第 {attempt} 次 F10 未被输入后端接受")

            if self._wait_for_requeue_response():
                return True

            self._log('warn', f"第 {attempt} 次 F10 后提示仍存在")
            if attempt < config.REQUEUE_KEY_ATTEMPTS:
                self._activate_window()
                if not self._sleep_interruptible(config.REQUEUE_RETRY_DELAY):
                    return False

        # 键盘路径均未让画面变化时，直接利用已经识别出的按钮中心点击兜底。
        if self._loop_end_match is None:
            try:
                result = self.clicker.check_target(LOOP_END_IMAGE)
                if result:
                    self._loop_end_match = result
            except Exception as e:
                self._log('debug', f"点击兜底前重新识别失败: {e}")

        if self._loop_end_match is not None:
            cx, cy, _conf = self._loop_end_match
            self._activate_window()
            self._log('warn', f"F10 未生效，改用鼠标点击再次排队中心 ({cx}, {cy})")
            try:
                self.clicker.click(cx, cy)
            except Exception as e:
                self._log('error', f"再次排队鼠标点击兜底失败: {e}")
            else:
                if self._wait_for_requeue_response():
                    return True
                self._log('error', "鼠标点击后再次排队提示仍存在")
        else:
            self._log('error', "F10 重试后已无法定位再次排队按钮，暂不切换状态")

        return False

    def _move_to_and_click(self, win_x, win_y, img_w=0, img_h=0,
                           steps=30, total_duration=0.3, do_click=True):
        """从窗口中心线性移动到目标位置，在图片范围内小范围左右线性移动，再点击

        参数:
            win_x, win_y: 目标在客户区坐标系中的位置
            img_w, img_h: 图片宽高（用于限制小范围移动边界）
            steps: 中心到目标的移动步数
            total_duration: 中心到目标的移动耗时（秒）
            do_click: 是否在移动完成后点击（False=只移动不点击）
        """
        client_pt = win32gui.ClientToScreen(self.clicker.hwnd, (0, 0))
        rect = win32gui.GetClientRect(self.clicker.hwnd)
        center_x = client_pt[0] + rect[2] // 2
        center_y = client_pt[1] + rect[3] // 2
        target_x = client_pt[0] + win_x
        target_y = client_pt[1] + win_y

        md = self.mouse_driver
        use_driver = md.available and md.mouse_device is not None and md.mstroke is not None
        if use_driver:
            from interception import lib as _ilib
            screen_w = ctypes.windll.user32.GetSystemMetrics(0)
            screen_h = ctypes.windll.user32.GetSystemMetrics(1)

        def _move_to(cur_x, cur_y, n_steps, delay):
            if n_steps <= 0:
                return
            step_delay = delay / n_steps
            start_x, start_y = self._last_mouse_pos if hasattr(self, '_last_mouse_pos') and self._last_mouse_pos else (center_x, center_y)
            for i in range(1, n_steps + 1):
                if not self._running:
                    return
                t = i / n_steps
                nx = int(start_x + (cur_x - start_x) * t)
                ny = int(start_y + (cur_y - start_y) * t)
                if use_driver:
                    norm_x = int((0xFFFF * nx) / screen_w)
                    norm_y = int((0xFFFF * ny) / screen_h)
                    md.mstroke.state = 0
                    md.mstroke.flags = _ilib.INTERCEPTION_MOUSE_MOVE_ABSOLUTE
                    md.mstroke.x = norm_x
                    md.mstroke.y = norm_y
                    md.mstroke.rolling = 0
                    md.mstroke.information = 0
                    _ilib.interception_send(md.context, md.mouse_device, md.mstroke, 1)
                else:
                    ctypes.windll.user32.SetCursorPos(nx, ny)
                time.sleep(step_delay)
            self._last_mouse_pos = (cur_x, cur_y)

        # 1. 从窗口中心线性移动到图片中心
        _move_to(target_x, target_y, steps, total_duration)

        # 2. 在图片范围内小范围左右线性移动（3次往返）
        if img_w > 0:
            half_w = max(img_w // 4, 5)
            left = target_x - half_w
            right = target_x + half_w
            _move_to(left, target_y, 10, 0.1)
            _move_to(right, target_y, 10, 0.1)
            _move_to(left, target_y, 10, 0.1)
            _move_to(target_x, target_y, 10, 0.05)

        # 3. 点击（可选）
        if do_click:
            self.clicker.click(win_x, win_y)

    def _two_stage_move(self, hero_cx, hero_cy, hero_h):
        """两段线性移动：先水平移到英雄x，再垂直移到英雄下1/4处

        参数:
            hero_cx, hero_cy: 英雄图片在客户区坐标系中的中心位置
            hero_h: 英雄图片高度
        """
        client_pt = win32gui.ClientToScreen(self.clicker.hwnd, (0, 0))
        rect = win32gui.GetClientRect(self.clicker.hwnd)
        center_x = client_pt[0] + rect[2] // 2
        center_y = client_pt[1] + rect[3] // 2
        hero_x = client_pt[0] + hero_cx
        # 英雄下1/4处 = 英雄中心y + 高度/4
        target_y = client_pt[1] + hero_cy + hero_h // 4

        md = self.mouse_driver
        use_driver = md.available and md.mouse_device is not None and md.mstroke is not None
        if use_driver:
            from interception import lib as _ilib
            screen_w = ctypes.windll.user32.GetSystemMetrics(0)
            screen_h = ctypes.windll.user32.GetSystemMetrics(1)

        def _move_to(cur_x, cur_y, n_steps, delay, start_pos):
            if n_steps <= 0:
                return start_pos
            step_delay = delay / n_steps
            start_x, start_y = start_pos
            for i in range(1, n_steps + 1):
                if not self._running:
                    return (cur_x, cur_y)
                t = i / n_steps
                nx = int(start_x + (cur_x - start_x) * t)
                ny = int(start_y + (cur_y - start_y) * t)
                if use_driver:
                    norm_x = int((0xFFFF * nx) / screen_w)
                    norm_y = int((0xFFFF * ny) / screen_h)
                    md.mstroke.state = 0
                    md.mstroke.flags = _ilib.INTERCEPTION_MOUSE_MOVE_ABSOLUTE
                    md.mstroke.x = norm_x
                    md.mstroke.y = norm_y
                    md.mstroke.rolling = 0
                    md.mstroke.information = 0
                    _ilib.interception_send(md.context, md.mouse_device, md.mstroke, 1)
                else:
                    ctypes.windll.user32.SetCursorPos(nx, ny)
                time.sleep(step_delay)
            return (cur_x, cur_y)

        start_pos = (center_x, center_y)
        # 第一段：水平移到英雄x（保持中心y）
        start_pos = _move_to(hero_x, center_y, 30, 0.6, start_pos)
        # 第二段：垂直移到英雄下1/4处（保持英雄x）
        start_pos = _move_to(hero_x, target_y, 30, 0.6, start_pos)

    def _activate_window(self):
        """前置游戏窗口并验证其是否获得焦点。"""
        try:
            hwnd = self.clicker.hwnd
            if not hwnd or not win32gui.IsWindow(hwnd):
                return False

            user32 = ctypes.windll.user32
            foreground = user32.GetForegroundWindow()
            target_thread = user32.GetWindowThreadProcessId(hwnd, None)
            foreground_thread = (
                user32.GetWindowThreadProcessId(foreground, None)
                if foreground and foreground != hwnd
                else 0
            )
            threads_attached = False
            try:
                # Windows 的前台锁定会阻止后台线程直接前置其他窗口。
                # 临时附加当前前台线程与游戏窗口线程后再激活，可覆盖常见锁定场景。
                if foreground_thread and foreground_thread != target_thread:
                    threads_attached = bool(
                        user32.AttachThreadInput(foreground_thread, target_thread, True)
                    )
                if user32.IsIconic(hwnd):
                    user32.ShowWindow(hwnd, 9)  # SW_RESTORE
                user32.BringWindowToTop(hwnd)
                user32.SetForegroundWindow(hwnd)
                user32.SetFocus(hwnd)
            finally:
                if threads_attached:
                    user32.AttachThreadInput(foreground_thread, target_thread, False)

            activated = user32.GetForegroundWindow() == hwnd
            if not activated:
                self._log('warn', "Windows 拒绝将《守望先锋》设为前台窗口")
            return activated
        except Exception as e:
            self._log('debug', f"激活窗口异常: {e}")
            return False

    def _click_game_center_to_focus(self):
        """移动到实时窗口中心单击一次，并验证游戏窗口确实获得焦点。"""
        try:
            geometry = get_client_geometry(self.clicker.hwnd)
            if geometry is None:
                self._log('warn', "无法在窗口中心点击：未找到《守望先锋》窗口")
                return False

            # 先走显式激活，再进行中心单击；单击仍只执行一次。
            self._activate_window()
            center_x, center_y = geometry.center
            user32 = ctypes.windll.user32
            user32.SetCursorPos(center_x, center_y)
            user32.mouse_event(0x0002, 0, 0, 0, 0)  # LEFTDOWN
            user32.mouse_event(0x0004, 0, 0, 0, 0)  # LEFTUP
            time.sleep(0.05)
            if user32.GetForegroundWindow() == geometry.hwnd:
                return True

            # 合成单击未能激活时再尝试一次显式前置，但不重复单击。
            if self._activate_window():
                return True
            self._log('warn', "窗口中心单击后《守望先锋》仍未获得焦点，本轮已跳过")
            return False
        except Exception as e:
            self._log('debug', f"窗口中心点击异常: {e}")
            return False

    def _wiggle_on_image(self, win_x, win_y, img_w):
        """在图片上小范围左右线性移动（不超出图片区域）

        参数:
            win_x, win_y: 图片中心在客户区坐标系中的位置
            img_w: 图片宽度（限制移动边界）
        """
        try:
            client_pt = win32gui.ClientToScreen(self.clicker.hwnd, (0, 0))
            target_x = client_pt[0] + win_x
            target_y = client_pt[1] + win_y

            md = self.mouse_driver
            use_driver = md.available and md.mouse_device is not None and md.mstroke is not None
            if use_driver:
                from interception import lib as _ilib
                screen_w = ctypes.windll.user32.GetSystemMetrics(0)
                screen_h = ctypes.windll.user32.GetSystemMetrics(1)

            half_w = max(img_w // 4, 5)
            left = target_x - half_w
            right = target_x + half_w

            def _move_to(cur_x, cur_y, n_steps, delay):
                if n_steps <= 0:
                    return
                step_delay = delay / n_steps
                start_x, start_y = self._last_mouse_pos if hasattr(self, '_last_mouse_pos') and self._last_mouse_pos else (target_x, target_y)
                for i in range(1, n_steps + 1):
                    if not self._running:
                        return
                    t = i / n_steps
                    nx = int(start_x + (cur_x - start_x) * t)
                    ny = int(start_y + (cur_y - start_y) * t)
                    if use_driver:
                        norm_x = int((0xFFFF * nx) / screen_w)
                        norm_y = int((0xFFFF * ny) / screen_h)
                        md.mstroke.state = 0
                        md.mstroke.flags = _ilib.INTERCEPTION_MOUSE_MOVE_ABSOLUTE
                        md.mstroke.x = norm_x
                        md.mstroke.y = norm_y
                        md.mstroke.rolling = 0
                        md.mstroke.information = 0
                        _ilib.interception_send(md.context, md.mouse_device, md.mstroke, 1)
                    else:
                        ctypes.windll.user32.SetCursorPos(nx, ny)
                    time.sleep(step_delay)
                self._last_mouse_pos = (cur_x, cur_y)

            # 左 → 右 → 左 → 中心
            _move_to(left, target_y, 10, 0.1)
            _move_to(right, target_y, 10, 0.1)
            _move_to(left, target_y, 10, 0.1)
            _move_to(target_x, target_y, 10, 0.05)
        except Exception as e:
            self._log('debug', f"图片上左右移动异常: {e}")

    def _click_current_position(self):
        """在当前鼠标位置执行左键点击"""
        try:
            pos = win32api.GetCursorPos()
            if self.mouse_driver.available:
                self.mouse_driver.click(pos[0], pos[1])
            else:
                # 回退：mouse_event 在当前位置点击
                ctypes.windll.user32.mouse_event(0x0002, 0, 0, 0, 0)  # LEFTDOWN
                time.sleep(0.005)
                ctypes.windll.user32.mouse_event(0x0004, 0, 0, 0, 0)  # LEFTUP
        except Exception as e:
            self._log('error', f"左键点击失败: {e}")

    def _move_relative_fallback(self, total_dx, total_dy, duration_s, speed_px_s):
        """Win32 mouse_event 相对移动回退（不需要驱动）

        在指定时长内按速度持续发送相对移动事件，期间检查赞赏玩家识别。
        """
        step_interval = 0.05  # 50ms 一次
        step_dx = int(speed_px_s * step_interval)
        step_dy = int(speed_px_s * step_interval)
        steps = int(duration_s / step_interval)
        remaining_dx = total_dx
        remaining_dy = total_dy
        for _ in range(steps):
            if not self._running or self._paused.is_set():
                return
            if self._check_f10():
                return
            if remaining_dx > 0:
                dx = min(step_dx, remaining_dx)
            elif remaining_dx < 0:
                dx = max(-step_dx, remaining_dx)
            else:
                dx = 0
            if remaining_dy > 0:
                dy = min(step_dy, remaining_dy)
            elif remaining_dy < 0:
                dy = max(-step_dy, remaining_dy)
            else:
                dy = 0
            if dx != 0 or dy != 0:
                # MOUSEEVENTF_MOVE = 0x0001
                ctypes.windll.user32.mouse_event(0x0001, dx, dy, 0, 0)
                remaining_dx -= dx
                remaining_dy -= dy
            time.sleep(step_interval)

    def _handle_loop2(self):
        """
        循环2：整组重复「视角右移 → 等时长左移 → 按住 D → 等时长按住 A → 左键 → Ctrl → E」
        动作执行期间每 50ms 检查赞赏玩家识别，识别到立即跳出
        没识别到赞赏玩家.png 时一直循环不退出
        返回 True=识别到赞赏玩家，False=被停止
        """
        self._log('info', "进入循环2")

        move_duration = self.options.get('move_duration', config.MOVE_DURATION)
        mouse_speed = self.options.get('mouse_speed', config.MOUSE_MOVE_SPEED)
        # 右移距离 = 原来的 1/4
        total_dx = int(mouse_speed * move_duration) // 4
        self._log('info', f"循环2 视角右移后左移，各{total_dx}px（原值的1/4）")

        while self._running:
            # 暂停检测
            if self._paused.is_set():
                time.sleep(0.1)
                continue

            self._f10_detected = False

            # ---- 1. 在游戏客户区中心点击一次，使《守望先锋》获得焦点----
            if not self._click_game_center_to_focus():
                time.sleep(0.1)
                continue

            # ---- 2. 鼠标右移 move_duration 秒（带 F10 检查回调）----
            # 驱动可用时用驱动级移动，不可用时用 Win32 mouse_event 回退
            if self.mouse_driver.available:
                result = self.mouse_driver.move_relative(
                    total_dx, 0, move_duration, mouse_speed,
                    check_callback=self._check_f10
                )
                if not result:
                    if self._f10_detected:
                        return True
                    if not self._running:
                        return False
                    continue
            else:
                # 回退：Win32 mouse_event 相对移动（不需要驱动）
                self._move_relative_fallback(total_dx, 0, move_duration, mouse_speed)
                # fallback 中若识别到再次排队（_f10_detected=True），立即退出
                if self._f10_detected:
                    return True
                if not self._running:
                    return False
                if self._paused.is_set():
                    continue

            # ---- 2. 鼠标左移 move_duration 秒（与右移时长相同，带 F10 检查回调）----
            if self.mouse_driver.available:
                result = self.mouse_driver.move_relative(
                    -total_dx, 0, move_duration, mouse_speed,
                    check_callback=self._check_f10
                )
                if not result:
                    if self._f10_detected:
                        return True
                    if not self._running:
                        return False
                    continue
            else:
                self._move_relative_fallback(-total_dx, 0, move_duration, mouse_speed)
                if self._f10_detected:
                    return True
                if not self._running:
                    return False
                if self._paused.is_set():
                    continue

            # ---- 3. 按住 D 键 move_duration 秒（带 F10 检查）----
            d_interrupted = False
            self.keyboard.key_down(VK_D)
            start_t = time.time()
            while time.time() - start_t < move_duration:
                if not self._running:
                    self.keyboard.key_up(VK_D)
                    return False
                if self._paused.is_set():
                    d_interrupted = True
                    break
                if self._check_f10():
                    self.keyboard.key_up(VK_D)
                    if self._f10_detected:
                        return True
                    if not self._running:
                        return False
                    d_interrupted = True
                    break
                time.sleep(config.LOOP2_CHECK_INTERVAL)
            self.keyboard.key_up(VK_D)
            if d_interrupted:
                continue  # 重新开始一组

            # ---- 4. 按住 A 键 move_duration 秒（与 D 键时长相同，带 F10 检查）----
            a_interrupted = False
            self.keyboard.key_down(VK_A)
            start_t = time.time()
            while time.time() - start_t < move_duration:
                if not self._running:
                    self.keyboard.key_up(VK_A)
                    return False
                if self._paused.is_set():
                    a_interrupted = True
                    break
                if self._check_f10():
                    self.keyboard.key_up(VK_A)
                    if self._f10_detected:
                        return True
                    if not self._running:
                        return False
                    a_interrupted = True
                    break
                time.sleep(config.LOOP2_CHECK_INTERVAL)
            self.keyboard.key_up(VK_A)
            if a_interrupted:
                continue  # 重新开始一组

            # ---- 5. 左键点击 ----
            if self._check_f10():
                if self._f10_detected:
                    return True
                if not self._running:
                    return False
                continue
            self._click_current_position()
            time.sleep(0.05)

            # ---- 6. Ctrl（按下 200ms）----
            if self._check_f10():
                if self._f10_detected:
                    return True
                if not self._running:
                    return False
                continue
            self.keyboard.press_key(VK_CTRL, duration_s=config.CTRL_HOLD_DURATION)

            # ---- 7. E（按下 50ms）----
            if self._check_f10():
                if self._f10_detected:
                    return True
                if not self._running:
                    return False
                continue
            self.keyboard.press_key(VK_E, duration_s=config.KEY_HOLD_DURATION)

            # 一组动作完成，回到循环开头继续下一组

        return False

    # ==================== 结束动作 ====================

    def _execute_shutdown(self):
        """结束时执行 Alt+F4 + 自动关机选项"""
        # F8 紧急停止时不执行 Alt+F4 和关机
        if self._stop_event.is_set():
            self._log('info', "流程被强制停止（F8），跳过 Alt+F4 和关机")
            return

        shutdown_option = self.options.get('auto_shutdown', config.AUTO_SHUTDOWN_DEFAULT)

        if shutdown_option == "none":
            self._log('info', "流程结束：不执行额外操作")
            return

        if shutdown_option in ("stop_only", "both"):
            # Alt+F4 关闭游戏
            self._log('info', "流程结束：按 Alt+F4 关闭游戏")
            try:
                self.keyboard.combo([VK_ALT, VK_F4])
            except Exception as e:
                self._log('error', f"Alt+F4 失败: {e}")

        if shutdown_option in ("shutdown", "both"):
            # 30 秒倒计时（可取消）
            self._log('warn', f"⚠️ {config.SHUTDOWN_COUNTDOWN} 秒后将关闭计算机！按 F8 取消")
            for i in range(config.SHUTDOWN_COUNTDOWN, 0, -1):
                if self._stop_event.is_set():  # F8 或用户取消
                    self._log('info', "关机已取消")
                    return
                if i % 5 == 0:
                    self._log('warn', f"关机倒计时: {i} 秒")
                time.sleep(1)
            # 执行关机
            self._log('error', "正在关闭计算机...")
            subprocess.run(["shutdown", "/s", "/t", "0"], check=False)

    # ==================== 回调通知 ====================

    def _notify_state_change(self, state):
        """通知状态变化（查表获取中文操作名）"""
        if self.callbacks and 'on_state_change' in self.callbacks:
            for key, current_op, next_op in STEP_FLOW:
                if key == state.name:
                    self.callbacks['on_state_change'](state, current_op, next_op)
                    return

    def _log(self, level, message):
        """日志通知（同时写入 logger 单例）"""
        if self.callbacks and 'on_log' in self.callbacks:
            self.callbacks['on_log'](level, message)
        if level == 'info':
            logger.info(message)
        elif level == 'warn':
            logger.warn(message)
        elif level == 'error':
            logger.error(message)
        else:
            logger.debug(message)

    def _notify_overlay(self, x, y, w, h, image_name, step_name, next_step, conf):
        """通知覆盖层显示识别框"""
        if self.callbacks and 'on_overlay' in self.callbacks:
            self.callbacks['on_overlay'](x, y, w, h, image_name, step_name, next_step, conf)

    def _notify_finish(self):
        """通知流程结束"""
        if self.callbacks and 'on_finish' in self.callbacks:
            self.callbacks['on_finish']()


if __name__ == "__main__":
    print("=== FlowEngine 自测（需要 Overwatch 窗口）===")
    from clicker import Clicker
    from driver_click import DriverKeyboard, DriverClicker, VK_CTRL, VK_D, VK_E
    from hero_selector import HeroSelector

    c = Clicker()
    if not c.find_window():
        print("❌ 未找到 Overwatch 窗口，跳过测试")
        exit(0)
    c.init_camera()

    kb = DriverKeyboard()
    ok, msg = kb.init()
    print(f"键盘: {msg}")

    md = DriverClicker()
    ok, msg = md.init()
    print(f"鼠标驱动: {msg}")

    hs = HeroSelector({"士兵76": 1.0})

    def on_state(state, cur, nxt):
        print(f"[状态] {state.value} | 当前: {cur} | 下一步: {nxt}")

    def on_log(level, msg):
        print(f"[{level}] {msg}")

    engine = FlowEngine(
        clicker=c, keyboard=kb, mouse_driver=md, hero_selector=hs,
        callbacks={'on_state_change': on_state, 'on_log': on_log},
        options={'duration_s': 60, 'auto_shutdown': 'none', 'mouse_speed': 500}
    )

    print("启动流程（60秒时长，无自动关机）")
    engine.run()
