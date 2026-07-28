# config.py
# 统一配置，所有可调参数集中在此

# 窗口识别
WINDOW_TITLE = "守望先锋"       # 游戏窗口标题关键词
TEMPLATE_PATH = "D:\\Desktop\\FILE\\trae project\\overwatch hero\\pic\\开始.png"     # 模板图片路径
THRESHOLD = 0.7                  # 模板匹配置信度阈值
USE_GRAY = True                  # 启用灰度匹配，速度提升约3倍

# 检测间隔（秒）
INTERVAL = 0.02

# Socket 通信
OVERLAY_HOST = "127.0.0.1"
OVERLAY_PORT = 12345

# 停止快捷键（VK键码：F8=0x77, ESC=0x1B, F9=0x78, F10=0x79）
STOP_HOTKEY = 0x77  # F8 停止识别并退出

# 调试
SAVE_DEBUG_SCREENSHOT = False     # 是否保存截图到 debug_screenshot.png
CAPTURE_REGION_CHECK_INTERVAL = 0.25  # 窗口移动/缩放检测间隔（秒）

# 模板图片以 1024×576 游戏客户区为基准。分辨率变化时按客户区比例缩放模板；
# 原尺寸仍会优先尝试，以兼容 UI 不随分辨率缩放的情况。
TEMPLATE_REFERENCE_SIZE = (1024, 576)
MATCH_SCALE_TRIGGER_DELTA = 0.03
MATCH_SCALE_FACTORS = (1.0, 0.95, 1.05)
MATCH_SCALE_MIN = 0.75
MATCH_SCALE_MAX = 2.0
MATCH_SCALED_THRESHOLD_BONUS = 0.03

# ========== 流程相关配置 ==========

# 英雄图片目录
HERO_DIR = "pic/守望先锋所有英雄"

# 鼠标移动
MOUSE_MOVE_SPEED = 500       # px/s
MOVE_DURATION = 3.0          # 持续时长（秒）

# 键盘按键时长
KEY_HOLD_DURATION = 0.05     # 默认按键按下到松开间隔（秒）
CTRL_HOLD_DURATION = 0.2     # Ctrl 长按 200ms（下蹲完成）
REQUEUE_KEY_HOLD_DURATION = 0.18  # F10 再次排队按键时长（秒）
REQUEUE_KEY_ATTEMPTS = 3          # F10 画面未响应时的按键重试次数
REQUEUE_VERIFY_TIMEOUT = 1.2      # 每次操作后等待提示消失的时间（秒）
REQUEUE_VERIFY_INTERVAL = 0.1     # 再次排队画面验证间隔（秒）
REQUEUE_RETRY_DELAY = 0.3         # 两次 F10 尝试之间的等待（秒）

# 检测间隔
POWER_SAMPLE_INTERVAL = 1.0       # 功耗采样间隔（秒）
RECOGNITION_RETRY_INTERVAL = 0.05 # 识别失败重试间隔（秒）
RECOGNITION_FOCUS_SETTLE_TIME = 0.15  # 游戏重新置前后的画面稳定时间（秒）
RECOGNITION_DIAGNOSTIC_INTERVAL = 1.0 # 未识别置信度日志节流间隔（秒）
LOOP2_CHECK_INTERVAL = 0.05       # LOOP2 中识别 F10 频率（秒）
WINDOW_RETRY_INTERVAL = 5.0       # 窗口丢失重试间隔（秒）

# 自动关机
SHUTDOWN_COUNTDOWN = 30            # 关机倒计时秒数（可取消）
AUTO_SHUTDOWN_DEFAULT = "none"    # none/stop_only/shutdown/both

# 文件路径
TARIFF_CACHE_FILE = ".tariff_cache.json"
CONFIG_PERSIST_FILE = "config.json"
LOG_DIR = "logs"

# 模板独立阈值（覆盖 THRESHOLD）
IMAGE_THRESHOLDS = {
    # "开始.png": 0.8,
    # "已找到比赛.png": 0.75,
    # 循环2退出条件：提高阈值防止误识别导致提前退出循环2
    "再次排队.png": 0.8,
}

# ========== 省份电价表（居民阶梯电价 第一/二/三档 元/kW·h）==========
# 数据来源：国家电网/南方电网/各省发改委公开信息（2026年参考值）
# 参考网页：https://www.maigoo.com/news/620010.html
PROVINCE_TARIFF_TABLE = {
    "北京": [0.4883, 0.5383, 0.7883],
    "天津": [0.4900, 0.5400, 0.7900],
    "河北": [0.5200, 0.5700, 0.8200],
    "山西": [0.4770, 0.5270, 0.7770],
    "内蒙古": [0.4150, 0.4650, 0.7150],
    "辽宁": [0.5000, 0.5500, 0.8000],
    "吉林": [0.4900, 0.5400, 0.7900],
    "黑龙江": [0.4800, 0.5300, 0.7800],
    "上海": [0.6170, 0.6670, 0.9170],
    "江苏": [0.5283, 0.5783, 0.8283],
    "浙江": [0.5380, 0.5880, 0.8380],
    "安徽": [0.5653, 0.6153, 0.8653],
    "福建": [0.4983, 0.5483, 0.7983],
    "江西": [0.6000, 0.6500, 0.9000],
    "山东": [0.5469, 0.5969, 0.8469],
    "河南": [0.5600, 0.6100, 0.8600],
    "湖北": [0.5580, 0.6080, 0.8580],
    "湖南": [0.5880, 0.6380, 0.8880],
    "广东": [0.5802, 0.6302, 0.8802],
    "广西": [0.5240, 0.5740, 0.8240],
    "海南": [0.6083, 0.6583, 0.9083],
    "重庆": [0.5200, 0.5700, 0.8200],
    "四川": [0.5224, 0.6224, 0.8224],
    "贵州": [0.4556, 0.5056, 0.7556],
    "云南": [0.4500, 0.5000, 0.7500],
    "西藏": [0.4900, 0.5400, 0.7900],
    "陕西": [0.4983, 0.5483, 0.7983],
    "甘肃": [0.5100, 0.5600, 0.8100],
    "青海": [0.3771, 0.4271, 0.6771],
    "宁夏": [0.4486, 0.4986, 0.7486],
    "新疆": [0.4750, 0.5250, 0.7750],
    "深圳": [0.6542, 0.7042, 0.9542],
    "珠海": [0.6000, 0.6500, 0.9000],
    "东莞": [0.6100, 0.6600, 0.9100],
}

# ========== 英雄分类表（坦克/输出/辅助）==========
# 对照 pic/守望先锋所有英雄/ 目录下的文件名（不含.png）
HERO_CATEGORY_TABLE = {
    "坦克": [
        "D.Va", "末日铁拳", "奥丽莎", "骇灾", "莱因哈特", "拉玛刹",
        "路霸", "西格玛", "温斯顿", "破坏球", "查莉娅", "毛加",
        "女王", "金驭",
    ],
    "输出": [
        "源氏", "猎空", "士兵76", "卡西迪", "死神", "法老之鹰",
        "半藏", "黑百合", "艾什", "回声", "索杰恩", "小美",
        "托比昂", "狂鼠", "黑影", "秩序之光", "堡垒", "探奇",
        "安燃", "斩仇", "弗蕾娅", "埃姆雷", "西拉", "死怨",
    ],
    "辅助": [
        "安娜", "巴蒂斯特", "布丽吉塔", "伊拉锐", "花男", "卢西奥",
        "天使", "莫伊拉", "和尚", "雾子", "无漾", "瑞希",
        "猫猫猫猫", "朱诺",
    ],
}

# 验证
if __name__ == "__main__":
    print(f"HERO_DIR = {HERO_DIR}")
    print(f"PROVINCE_TARIFF_TABLE 共 {len(PROVINCE_TARIFF_TABLE)} 个省市")
    print(f"HERO_CATEGORY_TABLE 坦克 {len(HERO_CATEGORY_TABLE['坦克'])} 个 / 输出 {len(HERO_CATEGORY_TABLE['输出'])} 个 / 辅助 {len(HERO_CATEGORY_TABLE['辅助'])} 个")
