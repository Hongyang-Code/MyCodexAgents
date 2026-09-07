"""Validate explicit Markdown structure requirements; never assess factual coverage."""
import argparse
import hashlib
import json
import re
from pathlib import Path


def visible_lines(text):
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    lines, fence = [], None
    for line in text.splitlines():
        match = re.match(r"^ {0,3}(`{3,}|~{3,})", line)
        if match:
            token = match.group(1)
            if fence is None:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence):
                fence = None
            continue
        if fence is None:
            lines.append(line.strip())
    return lines


def validate(text, requirements):
    errors = []
    def invalid(message):
        return {"status": "fail", "errors": [message]}
    if requirements is None:
        requirements = {}
    if not isinstance(requirements, dict):
        return invalid("requirements must be an object")
    if set(requirements) - {"content", "format"}:
        return invalid("unknown requirements key")
    content = requirements.get("content", [])
    if not isinstance(content, list):
        return invalid("content must be a list")
    ids = []
    for item in content:
        if not isinstance(item, dict) or any(not isinstance(item.get(k), str) or not item[k].strip() for k in ("id", "scope", "requirement")):
            return invalid("content item requires id, scope and requirement")
        ids.append(item["id"])
    if len(ids) != len(set(ids)):
        return invalid("duplicate content id")
    fmt = requirements.get("format")
    if fmt is None or fmt == {}:
        return {"status": "not_applicable", "errors": []}
    if not isinstance(fmt, dict) or set(fmt) - {"document_headings", "sections", "unit_level"}:
        return invalid("invalid format keys")
    headings = fmt.get("document_headings", [])
    sections = fmt.get("sections", [])
    def heading_valid(value):
        return isinstance(value, str) and re.fullmatch(r"#{1,6} +\S.*", value) is not None
    if not isinstance(headings, list) or not all(heading_valid(h) for h in headings) or len(set(headings)) != len(headings):
        return invalid("invalid or duplicate document headings")
    if not isinstance(sections, list):
        return invalid("sections must be a list")
    for section in sections:
        if not isinstance(section, dict) or set(section) != {"heading", "required_markers"} or not heading_valid(section["heading"]):
            return invalid("invalid section")
        markers = section["required_markers"]
        if not isinstance(markers, list) or not all(isinstance(m, str) and m.strip() for m in markers) or len(set(markers)) != len(markers):
            return invalid("invalid or duplicate required markers")
    expected = [s["heading"] for s in sections]
    if len(set(expected)) != len(expected):
        return invalid("duplicate section heading")
    level = fmt.get("unit_level")
    if level is not None and (type(level) is not int or not 1 <= level <= 6):
        return invalid("unit_level must be 1..6")
    lines = visible_lines(text)
    found = [(i, len(m.group(1)), line) for i, line in enumerate(lines) if (m := re.match(r"^(#{1,6}) +", line))]
    for heading in dict.fromkeys(headings + expected):
        if sum(line == heading for _, _, line in found) != 1:
            errors.append("missing or repeated heading: " + heading)
    if level is not None:
        actual = [line for _, n, line in found if n == level]
        if set(actual) != set(expected) or len(actual) != len(expected):
            errors.append("unit headings do not match the complete section list")
    for section in sections:
        matches = [(i, n) for i, n, line in found if line == section["heading"]]
        if len(matches) != 1:
            continue
        start, depth = matches[0]
        end = next((i for i, n, _ in found if i > start and n <= depth), len(lines))
        body = lines[start + 1:end]
        for marker in section["required_markers"]:
            values = [line[len(marker):].strip() for line in body if line.startswith(marker)]
            if len(values) != 1 or not values[0].strip("| ") or re.search(r"\{\{.*?\}\}|^TODO$|^待填写$", values[0], re.I):
                errors.append(section["heading"] + ": missing, repeated, empty or placeholder marker " + marker)
    return {"status": "fail" if errors else "pass", "errors": errors}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--text", required=True)
    parser.add_argument("--requirements")
    args = parser.parse_args()
    try:
        raw = Path(args.text).read_bytes()
        requirements = json.loads(Path(args.requirements).read_text(encoding="utf-8-sig")) if args.requirements else None
        result = validate(raw.decode("utf-8-sig"), requirements)
        result["sha256"] = hashlib.sha256(raw).hexdigest()
    except (OSError, ValueError) as exc:
        result = {"status": "fail", "errors": [str(exc)]}
    print(json.dumps(result, ensure_ascii=True))
    return 1 if result["status"] == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())
