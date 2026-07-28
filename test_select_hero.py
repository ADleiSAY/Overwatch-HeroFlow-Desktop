# test_select_hero.py
"""
独立测试模块：选择英雄
流程：识别英雄图片 → 激活窗口 → 从窗口中心线性移动到图片 → 驱动级连续点击5次
按 F8 退出测试
"""
import sys
import os
import time
import ctypes

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import win32gui
from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import Qt

# 开启 DPI 感知（物理像素坐标系）
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

from clicker import Clicker
from driver_click import DriverKeyboard, DriverClicker, is_driver_installed, is_driver_loaded
from hero_selector import HeroSelector
import config


# ===== 全局停止热键（F8） =====
_stop_flag = {'stop': False}

app = QApplication(sys.argv)


def install_hotkey():
    """注册 F8 全局热键"""
    HOTKEY_ID = 0xC0DE
    MOD_NONE = 0x0000
    VK_F8 = 0x77
    user32 = ctypes.windll.user32
    if user32.RegisterHotKey(None, HOTKEY_ID, MOD_NONE, VK_F8):
        print("✅ F8 热键已注册（停止测试）")
    return HOTKEY_ID


def nativeEventFilter():
    """nativeEventFilter 捕获 WM_HOTKEY"""
    from PyQt5.QtCore import QAbstractNativeEventFilter
    class _Filter(QAbstractNativeEventFilter):
        def nativeEventFilter(self, eventType, message):
            try:
                if eventType == b"windows_generic_MSG":
                    import ctypes.wintypes as wt
                    msg = wt.MSG.from_address(int(message))
                    if msg.message == 0x0312:  # WM_HOTKEY
                        print("\n🛑 收到 F8，停止测试")
                        _stop_flag['stop'] = True
                        app.quit()
                        return True, 0
            except Exception:
                pass
            return False, 0
    f = _Filter()
    app.installNativeEventFilter(f)


def linear_move_to(clicker, mouse_driver, target_x, target_y, steps=30, total_duration=0.3, start_pos=None):
    """从起点线性移动到目标屏幕坐标（默认起点为窗口中心）

    参数:
        clicker: Clicker 实例（提供 hwnd）
        mouse_driver: DriverClicker 实例
        target_x, target_y: 目标屏幕坐标
        steps: 移动步数
        total_duration: 总耗时（秒）
        start_pos: 可选起点 (sx, sy)，None 时使用窗口中心
    """
    client_pt = win32gui.ClientToScreen(clicker.hwnd, (0, 0))
    rect = win32gui.GetClientRect(clicker.hwnd)
    if start_pos is None:
        start_x = client_pt[0] + rect[2] // 2
        start_y = client_pt[1] + rect[3] // 2
    else:
        start_x, start_y = start_pos

    use_driver = mouse_driver.available and mouse_driver.mouse_device is not None and mouse_driver.mstroke is not None
    if use_driver:
        from interception import lib as _ilib
        screen_w = ctypes.windll.user32.GetSystemMetrics(0)
        screen_h = ctypes.windll.user32.GetSystemMetrics(1)

    step_delay = total_duration / steps if steps > 0 else 0
    for i in range(1, steps + 1):
        if _stop_flag['stop']:
            return
        t = i / steps
        cur_x = int(start_x + (target_x - start_x) * t)
        cur_y = int(start_y + (target_y - start_y) * t)
        if use_driver:
            norm_x = int((0xFFFF * cur_x) / screen_w)
            norm_y = int((0xFFFF * cur_y) / screen_h)
            mouse_driver.mstroke.state = 0
            mouse_driver.mstroke.flags = _ilib.INTERCEPTION_MOUSE_MOVE_ABSOLUTE
            mouse_driver.mstroke.x = norm_x
            mouse_driver.mstroke.y = norm_y
            mouse_driver.mstroke.rolling = 0
            mouse_driver.mstroke.information = 0
            _ilib.interception_send(mouse_driver.context, mouse_driver.mouse_device, mouse_driver.mstroke, 1)
        else:
            ctypes.windll.user32.SetCursorPos(cur_x, cur_y)
        time.sleep(step_delay)
    print(f"  线性移动完成: ({start_x},{start_y}) → ({target_x},{target_y})")


def activate_window(clicker):
    """激活游戏窗口"""
    try:
        hwnd = clicker.hwnd
        if hwnd is None:
            return
        ctypes.windll.user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        ctypes.windll.user32.SetForegroundWindow(hwnd)
        time.sleep(0.1)
        print("  窗口已激活")
    except Exception as e:
        print(f"  激活窗口失败: {e}")


def select_hero_test(clicker, mouse_driver, hero_img_name, click_count=5):
    """选择英雄测试：识别 → 线性移动 → 激活 → 连续点击

    参数:
        clicker: Clicker 实例
        mouse_driver: DriverClicker 实例
        hero_img_name: 英雄图片名（如 "守望先锋所有英雄/士兵76.png"）
        click_count: 点击次数
    """
    print(f"\n{'='*60}")
    print(f"选择英雄测试: {hero_img_name}")
    print(f"点击次数: {click_count}")
    print(f"{'='*60}")

    # 1. 查找窗口
    if clicker.hwnd is None:
        if not clicker.find_window():
            print("❌ 未找到 Overwatch 窗口")
            return False
        print("✅ 已找到 Overwatch 窗口")

    # 2. 初始化摄像头
    if clicker.camera is None:
        if not clicker.init_camera():
            print("❌ 摄像头初始化失败")
            return False
        print("✅ 摄像头已就绪")

    # 3. 循环识别英雄（超时3s后改为识别并点击继续.png）
    HERO_TIMEOUT = 3.0
    attempt = 0
    hero_start = time.time()
    while not _stop_flag['stop']:
        # 超时检查：超过3s未识别到英雄，改为识别并点击继续.png
        if time.time() - hero_start >= HERO_TIMEOUT:
            print(f"\n--- 英雄 {HERO_TIMEOUT}s 未识别到，改为识别并点击 继续.png ---")
            cont_start = time.time()
            while time.time() - cont_start < 10:
                if _stop_flag['stop']:
                    break
                try:
                    cont_result = clicker.find_target_by_name("继续.png")
                except Exception as e:
                    print(f"  识别 继续.png 异常: {e}")
                    time.sleep(0.5)
                    continue
                if cont_result:
                    ccx, ccy, ccw, cch, ccconf = cont_result
                    print(f"  ✅ 识别到 继续.png (conf={ccconf:.3f}, 位置=({ccx},{ccy}))")
                    clicker.click(ccx, ccy)
                    print(f"  已点击 继续.png ({ccx}, {ccy})")
                    break
                time.sleep(0.5)
            print("\n✅ 测试完成！")
            break

        attempt += 1
        print(f"\n--- 第 {attempt} 次尝试 ---")

        # 识别英雄
        try:
            result = clicker.find_target_by_name(hero_img_name)
        except Exception as e:
            print(f"  识别异常: {e}")
            time.sleep(0.5)
            continue

        if not result:
            print(f"  未识别到 {hero_img_name}，0.5s 后重试...")
            time.sleep(0.5)
            continue

        cx, cy, w, h, conf = result
        print(f"  ✅ 识别到 {hero_img_name} (conf={conf:.3f}, 位置=({cx},{cy}), 尺寸={w}x{h})")

        # 计算屏幕坐标
        client_pt = win32gui.ClientToScreen(clicker.hwnd, (0, 0))
        click_screen_x = client_pt[0] + cx
        click_screen_y = client_pt[1] + cy
        print(f"  图片屏幕坐标: ({click_screen_x},{click_screen_y})")

        # 1. 激活窗口
        print("  [1/5] 激活窗口...")
        activate_window(clicker)
        time.sleep(0.3)

        if _stop_flag['stop']:
            break

        # 2. 点击英雄图片位置（第一次）
        print(f"  [2/5] 点击英雄图片 ({click_screen_x},{click_screen_y})...")
        clicker.click(cx, cy)

        if _stop_flag['stop']:
            break

        # 3. 等待0.5s
        print("  [3/5] 等待0.5s...")
        time.sleep(0.5)

        if _stop_flag['stop']:
            break

        # 4. 在英雄图片位置再点击一次
        print(f"  [4/5] 再次点击英雄图片 ({click_screen_x},{click_screen_y})...")
        clicker.click(cx, cy)

        if _stop_flag['stop']:
            break

        # 5. 两段线性移动：先水平移到英雄x，再垂直移到英雄下1/4处 → 驱动级点击
        print(f"  [5/6] 两段线性移动并驱动级点击...")
        rect = win32gui.GetClientRect(clicker.hwnd)
        center_sx = client_pt[0] + rect[2] // 2
        center_sy = client_pt[1] + rect[3] // 2
        target_y = client_pt[1] + cy + h // 4
        # 第一段：水平移到英雄x（保持中心y）
        print(f"    第一段: 水平移动 ({center_sx},{center_sy}) → ({click_screen_x},{center_sy})")
        linear_move_to(clicker, mouse_driver, click_screen_x, center_sy, steps=30, total_duration=0.6)
        # 第二段：垂直移到英雄下1/4处（保持英雄x，从第一段终点开始）
        print(f"    第二段: 垂直移动 ({click_screen_x},{center_sy}) → ({click_screen_x},{target_y})")
        linear_move_to(clicker, mouse_driver, click_screen_x, target_y, steps=30, total_duration=0.6,
                       start_pos=(click_screen_x, center_sy))
        clicker.click(cx, cy)

        if _stop_flag['stop']:
            break

        # 6. 识别并点击"继续.png"
        print(f"  [6/6] 识别并点击 继续.png...")
        cont_start = time.time()
        while time.time() - cont_start < 10:
            if _stop_flag['stop']:
                break
            try:
                cont_result = clicker.find_target_by_name("继续.png")
            except Exception as e:
                print(f"  识别 继续.png 异常: {e}")
                time.sleep(0.5)
                continue
            if cont_result:
                ccx, ccy, ccw, cch, ccconf = cont_result
                print(f"  ✅ 识别到 继续.png (conf={ccconf:.3f}, 位置=({ccx},{ccy}))")
                clicker.click(ccx, ccy)
                print(f"  已点击 继续.png ({ccx}, {ccy})")
                break
            time.sleep(0.5)

        print(f"\n✅ 测试完成！")
        break

    return not _stop_flag['stop']


def main():
    print("="*60)
    print("选择英雄独立测试模块")
    print("流程: 识别英雄 → 激活窗口 → 线性移动 → 连续点击5次")
    print("按 F8 停止测试")
    print("="*60)

    # 安装 F8 热键
    install_hotkey()
    nativeEventFilter()

    # 初始化 Clicker
    clicker = Clicker()
    if not clicker.find_window():
        print("❌ 未找到 Overwatch 窗口，请先打开游戏")
        return
    print(f"✅ Overwatch 窗口: hwnd={clicker.hwnd}")

    if not clicker.init_camera():
        print("❌ 摄像头初始化失败")
        return
    print("✅ 摄像头已就绪")

    # 初始化驱动
    mouse_driver = DriverClicker()
    ok, msg = mouse_driver.init()
    clicker.driver = mouse_driver
    if ok and is_driver_installed() and is_driver_loaded():
        clicker.use_driver = True
        print(f"✅ 驱动级点击: {msg}")
    else:
        clicker.use_driver = False
        print(f"⚠️ 驱动不可用: {msg}（将使用 SendInput 回退）")

    # 让用户选择英雄图片
    hero_dir = os.path.join(os.path.dirname(__file__), "pic", "守望先锋所有英雄")
    if not os.path.isdir(hero_dir):
        print(f"❌ 英雄图片目录不存在: {hero_dir}")
        return

    heroes = sorted([f for f in os.listdir(hero_dir) if f.lower().endswith('.png')])
    if not heroes:
        print("❌ 未找到英雄图片")
        return

    print(f"\n可选英雄（共 {len(heroes)} 个）:")
    for i, h in enumerate(heroes):
        print(f"  {i+1}. {h}")

    # 命令行参数指定英雄
    if len(sys.argv) > 1:
        idx = int(sys.argv[1]) - 1
        if 0 <= idx < len(heroes):
            hero_file = heroes[idx]
        else:
            print(f"❌ 无效索引: {sys.argv[1]}")
            return
    else:
        try:
            idx = int(input(f"\n输入英雄编号(1-{len(heroes)}): ")) - 1
            if not (0 <= idx < len(heroes)):
                print("❌ 无效编号")
                return
            hero_file = heroes[idx]
        except (ValueError, EOFError):
            print("❌ 输入无效")
            return

    hero_img = f"守望先锋所有英雄/{hero_file}"
    print(f"\n选定英雄: {hero_img}")

    # 运行测试
    select_hero_test(clicker, mouse_driver, hero_img, click_count=5)

    # 清理
    try:
        clicker.camera.stop()
    except Exception:
        pass
    print("\n测试结束")


if __name__ == "__main__":
    main()
