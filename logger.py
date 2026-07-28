# logger.py
"""
日志服务
- 实时写入 logs/时间戳.log 文件
- 通知 UI 更新最近 50 条（线程安全）
- 颜色规则：INFO 白色 / WARN 黄色 / ERROR 红色 / DEBUG 灰色
"""
import os
import sys
import threading
from datetime import datetime
from collections import deque
from config import LOG_DIR


# 日志级别
LEVEL_INFO = "INFO"
LEVEL_WARN = "WARN"
LEVEL_ERROR = "ERROR"
LEVEL_DEBUG = "DEBUG"

# 颜色（用于 UI 显示，hex 颜色字符串）
LEVEL_COLORS = {
    LEVEL_INFO: "#c9d1d9",    # 白
    LEVEL_WARN: "#d29922",    # 黄
    LEVEL_ERROR: "#f85149",   # 红
    LEVEL_DEBUG: "#6e7681",   # 灰
}


class Logger:
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls, *args, **kwargs):
        """单例模式"""
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._buffer = deque(maxlen=50)  # 最近 50 条
        self._buffer_lock = threading.Lock()
        self._file_lock = threading.Lock()
        self._file = None
        self._callbacks = []  # UI 回调函数列表
        self._callbacks_lock = threading.Lock()
        self._start()
    
    def _start(self):
        """启动日志文件（在 logs/ 目录创建时间戳文件）"""
        data_dir = os.environ.get("HEROFLOW_DATA_DIR", "").strip()
        log_dir = os.path.join(data_dir, "logs") if data_dir else LOG_DIR
        try:
            os.makedirs(log_dir, exist_ok=True)
            timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
            filepath = os.path.join(log_dir, f"{timestamp}.log")
            self._file = open(filepath, "a", encoding="utf-8")
            self._file.write(f"=== 日志开始 {datetime.now().isoformat()} ===\n")
            self._file.flush()
        except Exception as e:
            self._safe_console_write(f"日志文件创建失败: {e}")
            self._file = None

    @staticmethod
    def _safe_console_write(message):
        """输出到受限编码控制台时使用替换字符，日志服务不能因输出失败而崩溃。"""
        text = str(message)
        try:
            print(text, file=sys.stderr)
        except UnicodeEncodeError:
            encoding = getattr(sys.stderr, "encoding", None) or "utf-8"
            buffer = getattr(sys.stderr, "buffer", None)
            if buffer is not None:
                try:
                    buffer.write((text + "\n").encode(encoding, errors="replace"))
                    buffer.flush()
                except (OSError, ValueError):
                    pass
        except (OSError, ValueError):
            # PyInstaller windowed sidecars may expose a stderr object backed by
            # an invalid Windows console handle. Logging must remain best-effort:
            # the file and UI sinks above have already received this entry.
            pass
    
    def add_callback(self, callback):
        """添加 UI 回调函数（callback 接收 level, message, timestamp 三参数）"""
        with self._callbacks_lock:
            self._callbacks.append(callback)
    
    def remove_callback(self, callback):
        """移除 UI 回调函数"""
        with self._callbacks_lock:
            if callback in self._callbacks:
                self._callbacks.remove(callback)
    
    def _notify_callbacks(self, level, message, timestamp):
        """通知所有 UI 回调（线程安全）"""
        with self._callbacks_lock:
            for cb in self._callbacks:
                try:
                    cb(level, message, timestamp)
                except Exception:
                    pass
    
    def log(self, level, message):
        """写入日志"""
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        line = f"[{timestamp}] [{level}] {message}"
        
        # 1. 写入文件
        with self._file_lock:
            if self._file:
                try:
                    self._file.write(line + "\n")
                    self._file.flush()
                except Exception:
                    pass
        
        # 2. 加入缓冲区
        entry = {
            "level": level,
            "message": message,
            "timestamp": timestamp,
            "color": LEVEL_COLORS.get(level, LEVEL_COLORS[LEVEL_INFO]),
        }
        with self._buffer_lock:
            self._buffer.append(entry)
        
        # 3. 通知 UI 回调
        self._notify_callbacks(level, message, timestamp)
        
        # 4. 控制台输出
        self._safe_console_write(line)
    
    def info(self, message):
        self.log(LEVEL_INFO, message)
    
    def warn(self, message):
        self.log(LEVEL_WARN, message)
    
    def error(self, message):
        self.log(LEVEL_ERROR, message)
    
    def debug(self, message):
        self.log(LEVEL_DEBUG, message)
    
    def get_recent(self, count=50):
        """获取最近 count 条日志（线程安全）"""
        with self._buffer_lock:
            return list(self._buffer)[-count:]
    
    def close(self):
        """关闭日志文件"""
        with self._file_lock:
            if self._file:
                try:
                    self._file.write(f"=== 日志结束 {datetime.now().isoformat()} ===\n")
                    self._file.close()
                except Exception:
                    pass
                self._file = None


# 模块级单例
logger = Logger()


if __name__ == "__main__":
    # 自测
    print("=== 测试 Logger ===")
    
    received = []
    def callback(level, message, timestamp):
        received.append((level, message, timestamp))
    
    logger.add_callback(callback)
    logger.info("启动程序")
    logger.warn("驱动未加载")
    logger.error("窗口丢失")
    logger.debug("识别开始.png 失败，重试")
    logger.info("流程启动")
    
    print(f"\n回调收到的消息数: {len(received)}")
    print(f"最近 50 条: {len(logger.get_recent(50))} 条")
    for entry in logger.get_recent(50):
        print(f"  [{entry['level']}] {entry['message']} ({entry['color']})")
    
    logger.close()
    print(f"\n日志文件已创建在 {LOG_DIR}/ 目录")
