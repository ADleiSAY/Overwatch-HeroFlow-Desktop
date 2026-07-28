# hero_selector.py
"""
英雄比例交替选择算法
按用户设定的英雄比例，以"次数比例交替"方式循环选择英雄。
如 A:B = 7:3 → 展开为周期序列 [A,A,A,A,A,A,A,B,B,B] 循环
"""
from math import gcd
from functools import reduce


def lcm(a, b):
    """最小公倍数"""
    return a * b // gcd(a, b)


class HeroSelector:
    def __init__(self, hero_ratios):
        """
        参数:
            hero_ratios: dict[str, float] - 英雄名→比例（0~1）
                        如 {"A": 0.7, "B": 0.3}
                        总和应为 1.0（不强制，会自动归一化）
        """
        self.hero_ratios = hero_ratios or {}
        self._sequence = []  # 展开后的周期序列
        self._index = 0     # 当前周期索引
        if self.hero_ratios:
            self._sequence = self.expand_to_sequence()
    
    def expand_to_sequence(self, max_length=100):
        """
        将比例展开为周期序列。
        算法：按最小公倍数展开为整数次数序列。
        如 A:B = 7:3 → [A,A,A,A,A,A,A,B,B,B]
        参数:
            max_length: 序列最大长度限制（默认 100）
        返回:
            list[str] - 展开后的英雄名序列
        """
        if not self.hero_ratios:
            return []
        # 单英雄直接返回单元素列表
        if len(self.hero_ratios) == 1:
            return [list(self.hero_ratios.keys())[0]]
        # 归一化比例
        total = sum(self.hero_ratios.values())
        if total <= 0:
            return []
        ratios = {k: v / total for k, v in self.hero_ratios.items()}
        # 转为整数次数（× 100 取整，至少 1 次）
        int_counts = {}
        for hero, ratio in ratios.items():
            cnt = max(1, int(round(ratio * 100)))
            int_counts[hero] = cnt
        # 用 GCD 化简整数次数到最简比例（如 70:30 → 7:3）
        counts = list(int_counts.values())
        common_gcd = reduce(gcd, counts)
        if common_gcd > 1:
            int_counts = {h: c // common_gcd for h, c in int_counts.items()}
        # 若仍超过 max_length，等比例缩小
        period_len = sum(int_counts.values())
        if period_len > max_length:
            scale = max_length / period_len
            int_counts = {h: max(1, int(round(c * scale))) for h, c in int_counts.items()}
        # 展开序列：每个英雄连续出现其次数次
        sequence = []
        for hero, count in int_counts.items():
            sequence.extend([hero] * count)
        return sequence
    
    def next_hero(self):
        """
        返回周期序列中下一个英雄名。
        索引到尾后回到起点。
        """
        if not self._sequence:
            return None
        hero = self._sequence[self._index % len(self._sequence)]
        self._index += 1
        return hero
    
    def reset(self):
        """重置索引"""
        self._index = 0
    
    def current_sequence(self):
        """返回当前展开的序列（用于调试/显示）"""
        return list(self._sequence)


if __name__ == "__main__":
    # 自测
    print("=== 测试 HeroSelector ===")
    
    # 单英雄
    s1 = HeroSelector({"A": 1.0})
    print(f"单英雄序列: {s1.current_sequence()}")
    print(f"next_hero ×3: {[s1.next_hero() for _ in range(3)]}")
    
    # 多英雄 7:3
    s2 = HeroSelector({"A": 0.7, "B": 0.3})
    print(f"\nA:B=7:3 序列: {s2.current_sequence()}")
    print(f"next_hero ×12: {[s2.next_hero() for _ in range(12)]}")
    
    # 三英雄
    s3 = HeroSelector({"A": 0.5, "B": 0.3, "C": 0.2})
    print(f"\nA:B:C=5:3:2 序列: {s3.current_sequence()}")
    print(f"next_hero ×15: {[s3.next_hero() for _ in range(15)]}")
    
    # 边界：比例和不为 1
    s4 = HeroSelector({"A": 7, "B": 3})
    print(f"\nA:B=7:3（未归一化）序列长度: {len(s4.current_sequence())}")
