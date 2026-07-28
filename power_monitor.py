# power_monitor.py
"""
功耗监控
- 通过 LibreHardwareMonitorLib.dll 实时获取整机功耗（pythonnet 调用）
- 每秒采样 CPU + GPU + 主板 + 内存 + 风扇 + 磁盘功耗（不含显示器）
- 累计能耗（kW·h）
- 预测总能源：时长模式 = 平均功率 × 总时长 / 3600
              无限制模式 = 平均功率 / 1000 × 1（kW·h/h）
- DLL 不可用时降级估算（CPU+GPU TDP × 利用率）
"""
import os
import threading
import time
from config import POWER_SAMPLE_INTERVAL
from logger import logger


# LibreHardwareMonitorLib.dll 路径（用户可配置环境变量 LHM_DLL_PATH）
LHM_DLL_PATH = os.environ.get("LHM_DLL_PATH", "LibreHardwareMonitorLib.dll")

# 默认 TDP（用于降级估算）
DEFAULT_CPU_TDP = 65  # W
DEFAULT_GPU_TDP = 200  # W


class PowerMonitor:
    def __init__(self):
        self._running = False
        self._thread = None
        self._lock = threading.Lock()
        
        # 实时数据
        self._current_power = 0.0      # 当前功率（W）
        self._total_energy = 0.0       # 累计能耗（W·s，对外接口转换为 kW·h）
        self._sample_count = 0
        self._power_sum = 0.0          # 用于计算平均功率
        
        # LibreHardwareMonitor 上下文
        self._lhm = None
        self._available = False
        self._degraded = False  # 是否降级估算
    
    def init(self):
        """
        初始化 LibreHardwareMonitorLib。
        尝试通过 pythonnet 加载 DLL。
        成功返回 True，失败返回 False（之后用降级估算）。
        """
        try:
            import clr  # pythonnet
            clr.AddReference(LHM_DLL_PATH)
            from LibreHardwareMonitor import Hardware
            
            self._lhm = Hardware.Computer()
            self._lhm.IsCpuEnabled = True
            self._lhm.IsGpuEnabled = True
            self._lhm.IsMotherboardEnabled = True
            self._lhm.IsMemoryEnabled = True
            self._lhm.IsControllerEnabled = True  # 风扇
            self._lhm.IsStorageEnabled = True    # 磁盘
            self._lhm.Open()
            self._available = True
            return True
        except Exception as e:
            logger.warn(f"LibreHardwareMonitor 加载失败，降级估算: {e}")
            self._available = False
            self._degraded = True
            return False
    
    def start(self):
        """启动采样子线程"""
        if self._running:
            return
        self.init()
        self._running = True
        self._thread = threading.Thread(target=self._sample_loop, daemon=True)
        self._thread.start()
    
    def stop(self):
        """停止采样"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None
        if self._lhm:
            try:
                self._lhm.Close()
            except Exception:
                pass
            self._lhm = None
    
    def _sample_loop(self):
        """采样循环（子线程）"""
        last_time = time.time()
        while self._running:
            now = time.time()
            dt = now - last_time
            last_time = now
            
            power = self._read_power()
            
            with self._lock:
                self._current_power = power
                self._total_energy += power * dt  # W·s
                self._sample_count += 1
                self._power_sum += power
            
            time.sleep(POWER_SAMPLE_INTERVAL)
    
    def _read_power(self):
        """读取当前整机功率（W）"""
        if self._available and self._lhm:
            try:
                return self._read_lhm_power()
            except Exception:
                self._degraded = True
                return self._estimate_power()
        else:
            return self._estimate_power()
    
    def _read_lhm_power(self):
        """从 LibreHardwareMonitor 读取各硬件功率之和"""
        total = 0.0
        for hw in self._lhm.Hardware:
            hw.Update()
            for sensor in hw.Sensors:
                # SensorType.Power = 4
                if sensor.SensorType == 4 and sensor.Value is not None:
                    total += float(sensor.Value)
        return total
    
    def _estimate_power(self):
        """降级估算：CPU+GPU TDP × 利用率（粗略）"""
        try:
            import psutil
            cpu_util = psutil.cpu_percent(interval=0.1)
            # 假设 GPU 利用率与 CPU 同步（粗略估算）
            gpu_util = cpu_util
            cpu_power = DEFAULT_CPU_TDP * (cpu_util / 100.0)
            gpu_power = DEFAULT_GPU_TDP * (gpu_util / 100.0)
            # 加上其他硬件估算 30W
            return cpu_power + gpu_power + 30.0
        except Exception:
            # psutil 不可用，返回固定估算值
            return 100.0
    
    def get_current_power(self):
        """获取当前功率（W）"""
        with self._lock:
            return self._current_power
    
    def get_total_energy(self):
        """获取累计能耗（kW·h，6 位小数，避免短时间运行精度丢失）"""
        with self._lock:
            return round(self._total_energy / 3600000.0, 6)  # W·s → kW·h
    
    def get_average_power(self):
        """获取平均功率（W）"""
        with self._lock:
            if self._sample_count == 0:
                return 0.0
            return self._power_sum / self._sample_count
    
    def predict_total_energy(self, total_duration_s):
        """
        预测总能源（时长模式）。
        
        参数:
            total_duration_s: 总时长（秒）
        
        返回:
            预测总能源（kW·h，3 位小数）
        """
        avg_power = self.get_average_power()  # W
        if avg_power == 0:
            return 0.0
        # W × s = W·s；除以 3600000 转换为 kW·h
        return round(avg_power * total_duration_s / 3600000.0, 3)
    
    def predict_hourly_energy(self):
        """预测每小时能耗（kW·h，无限制模式）"""
        avg_power = self.get_average_power()
        return round(avg_power / 1000.0, 3)
    
    def is_degraded(self):
        """是否降级估算"""
        return self._degraded
    
    def is_available(self):
        """是否使用 LibreHardwareMonitor"""
        return self._available


if __name__ == "__main__":
    print("=== 测试 PowerMonitor ===")
    pm = PowerMonitor()
    pm.start()
    
    import time
    print("采样 5 秒...")
    for i in range(5):
        time.sleep(1)
        print(f"  当前功率: {pm.get_current_power():.1f} W, 累计: {pm.get_total_energy()} kW·h, 平均: {pm.get_average_power():.1f} W")
    
    print(f"\n降级估算: {pm.is_degraded()}")
    print(f"LHM 可用: {pm.is_available()}")
    print(f"预测 1 小时能耗: {pm.predict_hourly_energy()} kW·h")
    print(f"预测 3600 秒总能耗: {pm.predict_total_energy(3600)} kW·h")
    
    pm.stop()
    print("\n已停止")
