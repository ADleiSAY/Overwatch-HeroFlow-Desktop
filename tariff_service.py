# tariff_service.py
"""
电费服务（重写版）
- 内置 2026 年最新省份阶梯电价表（config.PROVINCE_TARIFF_TABLE）
- 联网时：IP 定位省份 → 查表获取三档电价 → 缓存到本地
- 离线时：回退缓存 → 再回退默认电价
- 支持用户自定义电价（覆盖查表结果）

电价计算说明：
  居民阶梯电价按年累计电量分三档：
    一档：基础用电（月均 ~230 度）
    二档：正常用电（月均 230-400 度）+0.05 元/度
    三档：高用电（月均 400 度以上）+0.30 元/度
  本程序为短时运行（几小时），年累计电量远未达二档门槛，
  因此默认按一档计算，但保留档位选择能力供用户参考。
"""
import json
import os
import urllib.request
import urllib.error
from datetime import datetime
from config import PROVINCE_TARIFF_TABLE, TARIFF_CACHE_FILE


# ========== 常量 ==========

# IP 定位 API（主 + 备）
IP_API_URL = "http://ip-api.com/json/?lang=zh-CN"
IP_API_BACKUP = "https://ipapi.co/json/"

# 默认电价（查表/缓存都失败时使用，取全国一档中位数 ≈ 0.52 元/kW·h）
DEFAULT_TARIFF = 0.5200

# 阶梯档位枚举
TIER_BASIC = 1      # 一档（基础）
TIER_NORMAL = 2     # 二档（正常）
TIER_HIGH = 3       # 三档（高用量）


# ========== IP 定位 ==========

def get_province_by_ip():
    """
    通过 IP 定位获取当前所在省份名称（中文）。
    失败返回 None。

    实现：
        1. 尝试主 API（ip-api.com，返回 regionName）
        2. 失败则尝试备用 API（ipapi.co，返回 region）
        3. 都失败返回 None
    """
    # 主 API: ip-api.com
    province = _query_ip_api(IP_API_URL, fields=["regionName", "region"])
    if province:
        return province

    # 备用 API: ipapi.co
    province = _query_ip_api(IP_API_BACKUP, fields=["region", "country_name"])
    if province:
        return province

    return None


def _query_ip_api(url, fields):
    """
    请求指定 IP API 并按 fields 顺序返回第一个非空中文字段。
    失败返回 None。
    """
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if isinstance(data, dict):
            # ip-api.com 有 status 字段
            if data.get("status") == "fail":
                return None
            for f in fields:
                val = data.get(f)
                if val:
                    return str(val).strip()
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return None
    return None


# ========== 电价查表 ==========

def lookup_tariff(province, tier=TIER_BASIC):
    """
    从内置 PROVINCE_TARIFF_TABLE 查找指定省份的阶梯电价。

    参数:
        province: 省份名（如 "北京"、"上海市"），支持精确/模糊匹配
        tier: 档位（1=一档, 2=二档, 3=三档）

    返回:
        float: 电价（元/kW·h）
        None: 未找到
    """
    if not province or tier not in (1, 2, 3):
        return None

    prov = province.strip()

    # 1. 精确匹配
    if prov in PROVINCE_TARIFF_TABLE:
        return float(PROVINCE_TARIFF_TABLE[prov][tier - 1])

    # 2. 模糊匹配：province 包含某 key 或某 key 包含 province
    # 例如 "北京市" 匹配 "北京"，"广东省" 匹配 "广东"
    for key in PROVINCE_TARIFF_TABLE:
        if key in prov or prov in key:
            return float(PROVINCE_TARIFF_TABLE[key][tier - 1])

    return None


# ========== 缓存 ==========

def cache_tariff(province, price, tier=TIER_BASIC):
    """缓存电价到 .tariff_cache.json"""
    try:
        data = {
            "province": province,
            "price": price,
            "tier": tier,
            "timestamp": datetime.now().isoformat(timespec="seconds"),
        }
        with open(TARIFF_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


def load_cached_tariff():
    """
    从缓存读取电价。

    返回:
        (province, price, tier) 元组或 None
    """
    if not os.path.exists(TARIFF_CACHE_FILE):
        return None
    try:
        with open(TARIFF_CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and "province" in data and "price" in data:
            return (data.get("province"), data.get("price"), data.get("tier", 1))
    except (OSError, json.JSONDecodeError):
        return None
    return None


# ========== 组合接口 ==========

def get_tariff(tier=TIER_BASIC):
    """
    组合：IP 定位 + 电价查表。

    返回:
        (province, price): 如 ("北京", 0.4883)
        (province, None): 定位成功但电价未找到
        (None, None): 定位失败
    """
    province = get_province_by_ip()
    if not province:
        return (None, None)

    price = lookup_tariff(province, tier=tier)
    return (province, price)


def get_tariff_with_cache(tier=TIER_BASIC):
    """
    联网获取电价，失败时回退缓存，再失败回退默认电价。

    返回:
        (province, price, source) 元组
        source: "network"=网络获取, "cache"=缓存, "default"=默认电价
    """
    # 1. 尝试联网
    province, price = get_tariff(tier=tier)
    if province and price is not None:
        cache_tariff(province, price, tier=tier)
        return (province, price, "network")

    # 2. 回退缓存
    cached = load_cached_tariff()
    if cached and cached[1] is not None:
        return (cached[0], cached[1], "cache")

    # 3. 回退默认电价
    return ("默认", DEFAULT_TARIFF, "default")


def calculate_cost(energy_kwh, tariff):
    """
    计算电费开销。

    参数:
        energy_kwh: 累计能耗（kW·h）
        tariff: 电价（元/kW·h）

    返回:
        float: 电费（元，2 位小数）
    """
    if energy_kwh <= 0 or tariff <= 0:
        return 0.0
    return round(energy_kwh * tariff, 2)


# ========== 自测 ==========

if __name__ == "__main__":
    print("=== 测试 tariff_service（重写版）===")
    print(f"默认电价: {DEFAULT_TARIFF} 元/kW·h")
    print(f"内置省份电价表: {len(PROVINCE_TARIFF_TABLE)} 个省市\n")

    # 1. 测试查表
    print("--- 查表测试 ---")
    for prov in ["北京", "上海", "广东", "青海", "新疆"]:
        p1 = lookup_tariff(prov, tier=1)
        p2 = lookup_tariff(prov, tier=2)
        p3 = lookup_tariff(prov, tier=3)
        print(f"  {prov}: 一档={p1}, 二档={p2}, 三档={p3}")
    print()

    # 2. 测试模糊匹配
    print("--- 模糊匹配 ---")
    for prov in ["北京市", "上海市", "广东省", "青海省"]:
        p = lookup_tariff(prov, tier=1)
        print(f"  {prov} → {p}")
    print()

    # 3. 测试 IP 定位
    print("--- IP 定位 ---")
    province = get_province_by_ip()
    print(f"  当前省份: {province}")
    if province:
        price = lookup_tariff(province, tier=1)
        print(f"  {province} 一档电价: {price} 元/kW·h")
    print()

    # 4. 测试带缓存的获取
    print("--- 带缓存的获取 ---")
    p, price, source = get_tariff_with_cache(tier=1)
    print(f"  省份: {p}, 电价: {price}, 来源: {source}")
    print()

    # 5. 测试电费计算
    print("--- 电费计算 ---")
    if price:
        for kwh in [0.1, 0.5, 1.0, 5.0]:
            cost = calculate_cost(kwh, price)
            print(f"  {kwh} kW·h × {price} 元 = {cost} 元")
