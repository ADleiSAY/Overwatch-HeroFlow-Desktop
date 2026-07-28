import json
import io
import tempfile
import unittest
from pathlib import Path

from backend.config import ConfigStore, normalize_ratios, validate_config
from backend.ipc.server import repair_hero_names
from backend import main as backend_main


class ConfigValidationTests(unittest.TestCase):
    def test_protocol_writer_is_ascii_and_round_trips_chinese(self):
        stream = io.BytesIO()
        original = backend_main._PROTOCOL_STREAM
        try:
            backend_main._PROTOCOL_STREAM = stream
            backend_main.write_protocol({"message": "女王与奥丽莎"})
        finally:
            backend_main._PROTOCOL_STREAM = original
        wire = stream.getvalue()
        self.assertTrue(wire.isascii())
        self.assertEqual(json.loads(wire)["message"], "女王与奥丽莎")

    def test_ratios_always_total_one_hundred(self):
        value = normalize_ratios(["A", "B", "C"], {"A": 80, "B": 10, "C": 10})
        self.assertEqual(sum(value.values()), 100)
        self.assertEqual(value["A"], 80)

    def test_single_hero_is_one_hundred_percent(self):
        self.assertEqual(normalize_ratios(["D.Va"], {"D.Va": 1}), {"D.Va": 100})

    def test_invalid_values_are_clamped(self):
        value = validate_config({
            "mouse_speed": 99999,
            "duration_seconds": 1,
            "tariff_tier": 9,
            "auto_shutdown": "invalid",
        })
        self.assertEqual(value["mouse_speed"], 2000)
        self.assertEqual(value["duration_seconds"], 60)
        self.assertEqual(value["tariff_tier"], 3)
        self.assertEqual(value["auto_shutdown"], "none")

    def test_unencodable_hero_name_is_removed(self):
        value = validate_config({
            "selected_heroes": ["D.Va", "\udcb9", "女王"],
            "hero_ratios": {"D.Va": 30, "\udcb9": 30, "女王": 40},
        })
        self.assertEqual(value["selected_heroes"], ["D.Va", "女王"])
        self.assertEqual(sum(value["hero_ratios"].values()), 100)

    def test_valid_hero_name_survives_trailing_surrogate(self):
        value = validate_config({
            "selected_heroes": ["D.Va", "女王\udcb9", "奥丽莎\udcff"],
            "hero_ratios": {"D.Va": 34, "女王\udcb9": 33, "奥丽莎\udcff": 33},
        })
        self.assertEqual(value["selected_heroes"], ["D.Va", "女王", "奥丽莎"])
        self.assertEqual(value["hero_ratios"], {"D.Va": 34, "女王": 33, "奥丽莎": 33})

    def test_unencodable_hero_name_does_not_break_save(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ConfigStore(directory)
            saved = store.save({"selected_heroes": ["D.Va", "\udcb9"]})
            self.assertEqual(saved["selected_heroes"], ["D.Va"])
            json.loads(store.path.read_text(encoding="utf-8"))

    def test_multiple_chinese_heroes_survive_sequential_saves(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ConfigStore(directory)
            selected = ["D.Va"]
            for name in ["女王", "奥丽莎", "安娜", "雾子"]:
                selected = [*selected, name]
                saved = store.save({
                    "selected_heroes": selected,
                    "hero_ratios": {hero: 1 for hero in selected},
                })
                self.assertEqual(saved["selected_heroes"], selected)
                self.assertEqual(sum(saved["hero_ratios"].values()), 100)
            self.assertEqual(store.load()["selected_heroes"], selected)

    def test_mojibake_hero_names_are_repaired(self):
        canonical = ["D.Va", "女王", "奥丽莎", "拉玛刹", "末日铁拳"]
        aliases = {}
        for index, name in enumerate(canonical):
            alias = name
            for _ in range(index % 3 + 1):
                alias = alias.encode("utf-8").decode("gbk", errors="ignore")
            aliases[name] = alias
        selected = [aliases[name] for name in canonical]
        repaired = repair_hero_names({
            "selected_heroes": [*selected, "无法恢复的乱码"],
            "hero_ratios": {**{name: 20 for name in selected}, "无法恢复的乱码": 20},
        }, canonical)
        self.assertEqual(repaired["selected_heroes"], canonical)
        self.assertEqual(repaired["hero_ratios"], {name: 20 for name in canonical})

    def test_hero_names_with_legacy_whitespace_are_repaired(self):
        repaired = repair_hero_names({
            "selected_heroes": ["安燃 "],
            "hero_ratios": {"安燃 ": 100},
        }, ["安燃"])

        self.assertEqual(repaired["selected_heroes"], ["安燃"])
        self.assertEqual(repaired["hero_ratios"], {"安燃": 100})

    def test_legacy_config_is_migrated_on_save(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            legacy = root / "legacy.json"
            legacy.write_text(json.dumps({"mouse_speed": 321, "selected_heroes": ["A"]}), encoding="utf-8")
            store = ConfigStore(root / "data", legacy)
            loaded = store.load()
            self.assertEqual(loaded["mouse_speed"], 321)
            saved = store.save({"overlay_enabled": True})
            self.assertEqual(saved["schema_version"], 2)
            self.assertTrue((root / "data" / "config.json").exists())


if __name__ == "__main__":
    unittest.main()
