"""Render a Chinese paper structure map from JSON using measured text layout."""
import argparse
import json
import os
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont


def font_path(explicit=None):
    candidates = [explicit, os.environ.get("PAPERREADER_FONT"),
                  "C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simhei.ttf",
                  "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
                  "/System/Library/Fonts/PingFang.ttc"]
    if explicit:
        candidates = [explicit]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return str(candidate)
    raise FileNotFoundError("未找到中文字体，请用 --font 指定支持中文的字体文件")


def wrap(text, font, width):
    lines = []
    for paragraph in text.splitlines() or [""]:
        line = ""
        for char in paragraph:
            if line and font.getlength(line + char) > width:
                lines.append(line)
                line = ""
            line += char
        lines.append(line)
    return lines


def validate(data):
    if not isinstance(data, dict) or not isinstance(data.get("title"), str) or not data["title"].strip():
        raise ValueError("title 必须是非空字符串")
    sections = data.get("sections")
    if not isinstance(sections, list) or not 1 <= len(sections) <= 10:
        raise ValueError("sections 需要 1～10 个章节；长论文请合并次要小节")
    for section in sections:
        if not isinstance(section, dict) or not isinstance(section.get("title"), str) or not section["title"].strip():
            raise ValueError("每个章节需要非空 title")
        points = section.get("points")
        if not isinstance(points, list) or not 1 <= len(points) <= 5:
            raise ValueError("每章需要 1～5 个要点")
        if any(not isinstance(p, str) or not p.strip() or len(p) > 180 for p in points):
            raise ValueError("要点需要非空短文本，每条最多 180 字符")
    if len(data["title"]) > 180 or any(len(s["title"]) > 80 for s in sections):
        raise ValueError("标题过长，请保留可辨识主干")


def render(data, output: Path, font=None):
    validate(data)
    face = font_path(font)
    body = ImageFont.truetype(face, 28)
    heading = ImageFont.truetype(face, 30)
    title_font = ImageFont.truetype(face, 36)
    palettes = [("#f3e8ef", "#854e70"), ("#e9e7f5", "#60598c"),
                ("#e3f0eb", "#387363"), ("#e5eef8", "#416e96"), ("#f7eedf", "#886c3e")]
    # Three aligned columns: root, actual paper sections, concise section points.
    root_lines = wrap(data["title"], title_font, 300)
    row_data = []
    for section in data["sections"]:
        section_lines = wrap(section["title"], heading, 290)
        point_lines = [wrap(p, body, 660) for p in section["points"]]
        heights = [max(64, len(lines) * 40 + 24) for lines in point_lines]
        height = max(sum(heights) + 14 * (len(heights) - 1), len(section_lines) * 42 + 36)
        row_data.append((section_lines, point_lines, heights, height))
    height = max(420, sum(r[3] for r in row_data) + 34 * (len(row_data) - 1) + 150,
                 len(root_lines) * 50 + 160)
    if height > 9000:
        raise ValueError("导图过高，请压缩要点后重绘，不缩小字号")
    canvas = Image.new("RGB", (1580, height), "#fafbfe")
    draw = ImageDraw.Draw(canvas)
    root_h = len(root_lines) * 50 + 44
    root_y = (height - root_h) // 2
    root_mid = height // 2
    draw.rounded_rectangle((40, root_y, 380, root_y + root_h), 20, fill="#263b54")
    for i, line in enumerate(root_lines):
        draw.text((60, root_y + 20 + 50 * i), line, font=title_font, fill="white")
    y = 80
    first_mid = y + row_data[0][3] // 2
    last_mid = y + sum(r[3] for r in row_data[:-1]) + 34 * (len(row_data) - 1) + row_data[-1][3] // 2
    draw.line((380, root_mid, 420, root_mid), fill="#b3bfce", width=3)
    draw.line((420, min(first_mid, root_mid), 420, max(last_mid, root_mid)), fill="#b3bfce", width=3)
    for index, (section_lines, points, heights, row_h) in enumerate(row_data):
        fill, ink = palettes[index % len(palettes)]
        mid = y + row_h // 2
        box_h = len(section_lines) * 42 + 36
        top = mid - box_h // 2
        draw.line((420, mid, 460, mid), fill=ink, width=3)
        draw.rounded_rectangle((460, top, 790, top + box_h), 16, fill=fill, outline=ink, width=2)
        for i, line in enumerate(section_lines):
            draw.text((480, top + 14 + i * 42), line, font=heading, fill=ink)
        py = y
        for lines, point_h in zip(points, heights):
            pmid = py + point_h // 2
            draw.line([(790, mid), (820, mid), (820, pmid), (850, pmid)], fill=ink, width=2)
            draw.rounded_rectangle((850, py, 1550, py + point_h), 12, fill="white", outline=fill, width=3)
            for i, line in enumerate(lines):
                draw.text((870, py + 10 + i * 40), line, font=body, fill="#263447")
            py += point_h + 14
        y += row_h + 34
    draw.text((40, height - 48), "论文结构 · 辅助阅读", font=body, fill="#64748b")
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output, format="PNG")
    return canvas.size


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--font")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("输出已存在；请使用新的文件名，检查后再替换旧图")
    dimensions = render(json.loads(args.source.read_text(encoding="utf-8-sig")), args.output, args.font)
    print(f"PNG {dimensions[0]}x{dimensions[1]}: {args.output}")


if __name__ == "__main__":
    main()
