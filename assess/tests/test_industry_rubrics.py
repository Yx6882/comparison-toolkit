"""行业规则库的测试：验证生成器输出、方向判定、加载完整性。"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import assess as az  # noqa: E402
import gen_industry_rubrics as gen  # noqa: E402

INDUSTRY_DIR = ROOT / "rubrics" / "industry"


class TestGenerator(unittest.TestCase):
    def test_rubric_structure(self):
        rubric = gen.build_rubric(gen.INDUSTRIES[0])
        self.assertTrue(rubric["id"].startswith("industry-"))
        self.assertIn("disclaimer", rubric)
        self.assertIn("source", rubric)
        self.assertGreaterEqual(len(rubric["items"]), 3)

    def test_cost_ratio_direction(self):
        """成本类指标（租金、人力）越高应该判「偏高」，不是「较好」。"""
        entry = next(item for item in gen.INDUSTRIES if item[0] == "software-outsourcing")
        rubric = gen.build_rubric(entry)
        labour = next(item for item in rubric["items"] if item["key"] == "labour_ratio")
        levels = [entry_["level"] for entry_ in labour["ranges"]]
        self.assertIn("偏高", levels)
        self.assertNotIn("较好", levels)
        # 最高一档必须是高成本提示
        self.assertEqual(labour["ranges"][-1]["level"], "偏高")
        self.assertEqual(labour["ranges"][-1]["severity"], "注意")

    def test_time_ratio_direction(self):
        """时间类指标（周转天数）越长越差。"""
        entry = next(item for item in gen.INDUSTRIES if item[0] == "software-outsourcing")
        rubric = gen.build_rubric(entry)
        days = next(item for item in rubric["items"] if item["key"] == "receivable_days")
        self.assertEqual(days["ranges"][0]["level"], "偏快")
        self.assertEqual(days["ranges"][-1]["level"], "偏慢")

    def test_margin_direction(self):
        """毛利率越高越好，但高毛利要提示别牺牲周转。"""
        entry = gen.INDUSTRIES[0]
        rubric = gen.build_rubric(entry)
        gross = next(item for item in rubric["items"] if item["key"] == "gross_margin")
        self.assertEqual(gross["ranges"][0]["level"], "偏低")
        self.assertEqual(gross["ranges"][-1]["level"], "偏高")

    def test_all_entries_have_profiles(self):
        for entry in gen.INDUSTRIES:
            self.assertIn(entry[3], gen.PROFILES, f"{entry[0]} 的 profile 不存在")

    def test_industry_count(self):
        self.assertGreaterEqual(len(gen.INDUSTRIES), 110, "至少覆盖 110 个行业")


class TestGeneratedFiles(unittest.TestCase):
    def test_all_files_load(self):
        files = sorted(INDUSTRY_DIR.glob("*.json"))
        self.assertGreaterEqual(len(files), 110)
        for path in files:
            rubric = az.load_rubric(path)
            self.assertTrue(rubric.items, f"{path.name} 没有指标")

    def test_resolve_by_id_from_subdir(self):
        """resolve_rubric 要能找到子目录里的 rubric。"""
        path = az.resolve_rubric("industry-restaurant-full")
        self.assertTrue(path.exists())
        self.assertEqual(path.parent.name, "industry")

    def test_one_industry_runs_end_to_end(self):
        rubric = az.load_rubric(az.resolve_rubric("industry-restaurant-full"))
        results = az.assess(rubric, {"毛利率": 58, "净利率": 12, "租售比": 15, "人力成本占比": 25})
        self.assertTrue(all(not r.missing for r in results))
        self.assertTrue(all(r.level == "正常" for r in results))

    def test_out_of_range_flags(self):
        rubric = az.load_rubric(az.resolve_rubric("industry-restaurant-full"))
        results = az.assess(rubric, {"租售比": 35})
        target = next(r for r in results if "租售比" in r.name)
        self.assertEqual(target.level, "偏高")


class TestMarketData(unittest.TestCase):
    """上市公司真实数据接入（东方财富）。"""

    def test_market_file_exists(self):
        market = ROOT.parent / "data" / "industry-financials.json"
        self.assertTrue(market.exists(), "缺少 data/industry-financials.json")

    def test_market_file_structure(self):
        market = ROOT.parent / "data" / "industry-financials.json"
        data = json.loads(market.read_text(encoding="utf-8"))
        self.assertGreater(data["company_count"], 5000, "应覆盖全市场")
        self.assertGreater(data["industry_count"], 100)
        self.assertIn("caveat", data, "必须带口径说明")

    def test_rubric_carries_market_data(self):
        rubric = az.load_rubric(az.resolve_rubric("industry-software-outsourcing"))
        self.assertTrue(rubric.market_data, "软件外包应有真实数据")
        self.assertEqual(rubric.market_data["board"], "软件开发")
        self.assertGreater(rubric.market_data["gross_margin"]["count"], 100)

    def test_render_shows_market_comparison(self):
        rubric = az.load_rubric(az.resolve_rubric("industry-software-outsourcing"))
        results = az.assess(rubric, {"毛利率": 44})
        report = az.render_markdown(rubric, results)
        self.assertIn("A 股同行业真实数据", report)
        self.assertIn("上市公司", report)
        self.assertIn("44.24", report, "应显示真实毛利率中位数")

    def test_most_industries_have_data(self):
        files = sorted(INDUSTRY_DIR.glob("*.json"))
        with_data = 0
        for path in files:
            rubric = json.loads(path.read_text(encoding="utf-8"))
            if rubric.get("market_data"):
                with_data += 1
        self.assertGreaterEqual(with_data, 80, "至少 80 个行业能对上真实数据")


if __name__ == "__main__":
    unittest.main()
