"""Create an identity-checked local paper directory; no network or overwrites."""
import argparse
import hashlib
import json
import re
from pathlib import Path

DEFAULT_ROOT = Path(__file__).resolve().parents[1] / "outputs"


def safe_component(value: str, fallback: str, limit: int = 64) -> str:
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "-", value.strip())
    value = re.sub(r"\s+", " ", value).strip(" .")[:limit].rstrip(" .")
    if not value:
        value = fallback
    if re.fullmatch(r"(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?", value):
        value = "_" + value
    return value


def prepare(root: Path, year: str, venue: str, title: str, paper_id: str) -> Path:
    if not paper_id.strip() or not title.strip():
        raise ValueError("paper-id 和短标题不能为空")
    if year and not re.fullmatch(r"\d{4}", year):
        raise ValueError("年份必须为四位数字；未知时省略 --year")
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    identity = paper_id.strip()
    base = f"{year or '年份待核实'}—{safe_component(venue, '发表信息待核实', 40)}-{safe_component(title, '短标题待核实')}"
    suffix = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:10]
    for name in (base, f"{base}-{suffix}"):
        directory = root / name
        if directory.is_symlink() or directory.resolve().parent != root:
            raise ValueError("目标路径超出 outputs，拒绝写入")
        marker = directory / ".paper.json"
        if directory.exists():
            if not directory.is_dir():
                continue
            if marker.is_file():
                try:
                    existing = json.loads(marker.read_text(encoding="utf-8"))
                except (ValueError, OSError):
                    continue
                if existing.get("paper_id") == identity:
                    return directory
            continue
        directory.mkdir()
        marker.write_text(json.dumps({"paper_id": identity, "year": year or None,
                                      "venue": venue or None, "short_title": title},
                                     ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return directory
    raise FileExistsError("名称与标识均冲突；请核查身份，不覆盖已有目录")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", default="")
    parser.add_argument("--venue", default="")
    parser.add_argument("--title", required=True)
    parser.add_argument("--paper-id", required=True, help="已核实的 DOI、版本化 URL 或其他稳定身份")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    args = parser.parse_args()
    print(prepare(args.root, args.year, args.venue, args.title, args.paper_id))


if __name__ == "__main__":
    main()
