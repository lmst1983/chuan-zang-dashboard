import importlib.util
import pathlib
import unittest

SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "update_data.py"
SPEC = importlib.util.spec_from_file_location("update_data", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class UpdateDataTests(unittest.TestCase):
    def test_weather_risk(self):
        self.assertEqual(MODULE.weather_risk(95, 20, 10, 1)[0], "high")
        self.assertEqual(MODULE.weather_risk(3, 90, 10, 2)[0], "medium")
        self.assertEqual(MODULE.weather_risk(3, 90, 10, 22)[0], "high")
        self.assertEqual(MODULE.weather_risk(1, 10, 8, 0)[0], "low")

    def test_parse_xizang_latest(self):
        page = """
        <li><a title="全区国省公路路网运行情况"
        href="./202606/t20260622_1.html">全区国省公路路网运行情况</a>
        <span>2026-06-22</span></li>
        """
        url, date = MODULE.parse_xizang_latest(page)
        self.assertEqual(date, "2026-06-22")
        self.assertEqual(url, "https://jtt.xizang.gov.cn/bsfw/cxfw/202606/t20260622_1.html")

    def test_extract_only_route_relevant_g318(self):
        text = (
            "目前总体运行平稳。"
            "G318线芒康至左贡路段因落石实行临时交通管制。"
            "G318线聂拉木境内单向通行。"
        )
        notices = MODULE.extract_route_notices(text, "https://example.test", "2026-06-22")
        self.assertEqual(len(notices), 1)
        self.assertIn("芒康", notices[0]["summary"])


if __name__ == "__main__":
    unittest.main()
