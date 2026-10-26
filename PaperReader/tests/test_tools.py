import importlib.util
import tempfile
import unittest
from pathlib import Path
from PIL import Image

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def module(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


prepare = module("prepare_output")
mindmap = module("render_mindmap")


class OutputTests(unittest.TestCase):
    def test_identity_and_collision_preserve_user_report(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            first = prepare.prepare(root, "2016", "CVPR", "Deep Residual Learning", "a-v1")
            self.assertEqual(first.name, "2016—CVPR-Deep Residual Learning")
            (first / "report.md").write_text("用户笔记", encoding="utf-8")
            again = prepare.prepare(root, "2016", "CVPR", "Deep Residual Learning", "a-v1")
            other = prepare.prepare(root, "2016", "CVPR", "Deep Residual Learning", "b-v1")
            self.assertEqual(first, again)
            self.assertNotEqual(first, other)
            self.assertEqual((first / "report.md").read_text(encoding="utf-8"), "用户笔记")

    def test_unknown_and_invalid_filename(self):
        with tempfile.TemporaryDirectory() as temp:
            path = prepare.prepare(Path(temp), "", "", "A/B: C?*", "id")
            self.assertTrue(path.name.startswith("年份待核实—发表信息待核实-"))
            self.assertEqual(path.parent, Path(temp).resolve())
            self.assertNotIn("/", path.name)
            self.assertNotIn(":", path.name)
        self.assertEqual(prepare.safe_component("CON", "x"), "_CON")

    def test_unclaimed_directory_not_overwritten(self):
        with tempfile.TemporaryDirectory() as temp:
            original = Path(temp) / "2020—arXiv-Title"
            original.mkdir()
            result = prepare.prepare(Path(temp), "2020", "arXiv", "Title", "id")
            self.assertNotEqual(original, result)
            self.assertEqual(list(original.iterdir()), [])

    def test_invalid_year_or_identity(self):
        with tempfile.TemporaryDirectory() as temp:
            for year, identity in [("20xx", "id"), ("2020", " ")]:
                with self.assertRaises(ValueError):
                    prepare.prepare(Path(temp), year, "CVPR", "Title", identity)


class ImageTests(unittest.TestCase):
    def test_chinese_long_text_png_and_wrap_width(self):
        face = mindmap.font_path()
        font = mindmap.ImageFont.truetype(face, 28)
        lines = mindmap.wrap("中文长句用于验证测量换行。" * 8, font, 180)
        self.assertTrue(all(font.getlength(line) <= 180 for line in lines))
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "map.png"
            data = {"title": "论文结构测试", "sections": [
                {"title": "实验与适用边界", "points": ["中文长句用于验证测量换行。" * 8, "第二个节点"]},
                {"title": "方法", "points": ["保留关键假设"]}]}
            size = mindmap.render(data, output, face)
            with Image.open(output) as im:
                self.assertEqual(im.format, "PNG")
                self.assertEqual(im.size, size)
                self.assertGreater(im.height, 400)

    def test_missing_font_and_bad_structure_fail(self):
        with self.assertRaises(FileNotFoundError):
            mindmap.font_path("missing-cjk-font.ttf")
        for data in [{}, {"title": "标题", "sections": []},
                     {"title": "标题", "sections": [{"title": "方法", "points": [""]}]}]:
            with self.assertRaises(ValueError):
                mindmap.validate(data)


if __name__ == "__main__":
    unittest.main()
