"""Check records and literal protection. This does not judge style or semantics."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re

NUMBERS = re.compile(r"(?<![A-Za-z0-9_])[+-]?\d+(?:,\d{3})*(?:\.\d+)?(?:[eE][+-]?\d+)?%?(?![A-Za-z0-9_])")
JUDGMENTS = {"基本符合", "部分符合", "明显偏离", "材料不足无法判断"}
STATUSES = {"passed", "needs_clarification", "not_passed", "checked_only"}
RULES = {f"XR{i:02d}" for i in range(1, 11)}


def digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def final_text(result):
    return "\n\n".join(unit["revised"] for unit in result["units"])


def validate(source, result):
    errors = []
    if source.get("schema_version") != 1 or result.get("schema_version") != 1:
        return ["Unsupported schema_version"]
    original = source.get("units", [])
    revised = result.get("units", [])
    if not original or not revised:
        return ["Missing units"]
    ids = [unit.get("id") for unit in original]
    if any(not isinstance(item, str) or not item for item in ids) or len(ids) != len(set(ids)):
        return ["Invalid or duplicate source unit IDs"]
    if [unit.get("id") for unit in revised] != ids:
        return ["Units missing, duplicated or reordered without a stable mapping"]
    if any(not isinstance(unit.get("text"), str) or not unit["text"].strip() for unit in original):
        return ["Invalid original text"]
    if any(not isinstance(unit.get("revised"), str) or not unit["revised"].strip() for unit in revised):
        return ["Empty revised text"]
    initial_text = "\n\n".join(unit["text"] for unit in original)
    output_text = final_text(result)
    if result.get("original_sha256") != digest(initial_text):
        errors.append("Original baseline hash mismatch")
    if result.get("final_sha256") != digest(output_text):
        errors.append("Final text hash mismatch")
    if result.get("judgment") not in JUDGMENTS:
        errors.append("Invalid style judgment")
    if result.get("status") not in STATUSES:
        errors.append("Invalid status")
    changed = set()
    for old, new in zip(original, revised):
        uid = old["id"]
        before, after = old["text"], new["revised"]
        if before != after:
            changed.add(uid)
        if Counter(NUMBERS.findall(before)) != Counter(NUMBERS.findall(after)):
            errors.append(f"{uid}: numerical tokens changed; return to source review")
        for span in old.get("protected_spans", []):
            if not isinstance(span, str) or not span or span not in before:
                errors.append(f"{uid}: invalid protected span")
            elif span not in after:
                errors.append(f"{uid}: protected span changed: {span}")
    changes = result.get("changes", [])
    if not isinstance(changes, list):
        return errors + ["Invalid changes"]
    change_ids = [item.get("unit_id") for item in changes]
    if len(change_ids) != len(set(change_ids)) or set(change_ids) != changed:
        errors.append("Change manifest must cover exactly the changed units")
    before_by_id = {u["id"]: u["text"] for u in original}
    after_by_id = {u["id"]: u["revised"] for u in revised}
    for change in changes:
        uid = change.get("unit_id")
        if change.get("before") != before_by_id.get(uid) or change.get("after") != after_by_id.get(uid):
            errors.append(f"{uid}: before/after differs from actual text")
        if not isinstance(change.get("reason"), str) or not change["reason"].strip():
            errors.append(f"{uid}: missing change reason")
    for issue in result.get("issues", []):
        if issue.get("unit_id") not in ids or not issue.get("observation"):
            errors.append("Issue missing unit or observation")
        if issue.get("kind") not in {"style", "language", "content"}:
            errors.append("Invalid issue kind")
        if issue.get("kind") == "style" and issue.get("rule_id") not in RULES:
            errors.append("Style issue missing a valid rule ID")
        if issue.get("kind") == "content" and issue.get("state") == "unresolved" and result.get("status") == "passed":
            errors.append("Unresolved source issue cannot pass")
    limit = source.get("max_rounds", 3)
    rounds = result.get("style_revision_rounds")
    if type(limit) is not int or not 0 <= limit <= 10:
        errors.append("Invalid source round limit")
    elif type(rounds) is not int or not 0 <= rounds <= limit:
        errors.append("Style round budget exceeded or invalid")
    elif rounds == 0 and changed:
        errors.append("Changed text needs a recorded modification round")
    batches = result.get("text_readable_batches", [])
    if not isinstance(batches, list) or len(batches) > 2:
        errors.append("TextReadable batch budget exceeded or invalid")
    else:
        for batch in batches:
            n = batch.get("revision_rounds")
            if type(n) is not int or not 0 <= n <= 3:
                errors.append("TextReadable round budget exceeded or invalid")
        if result.get("status") == "passed":
            if not batches or batches[-1].get("status") != "passed" or batches[-1].get("final_sha256") != digest(output_text):
                errors.append("Missing TextReadable check bound to final text")
    if result.get("status") == "passed":
        if result.get("judgment") == "材料不足无法判断":
            errors.append("Insufficient basis cannot be overall passed")
        if result.get("unresolved"):
            errors.append("Unresolved items cannot pass")
        for name in ["semantic_fidelity", "style", "readability", "requirements", "claim_strength"]:
            review = result.get("review", {}).get(name, {})
            if review.get("status") != "pass" or not review.get("evidence"):
                errors.append(f"Missing actual review record: {name}")
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("original", type=Path)
    parser.add_argument("result", type=Path)
    args = parser.parse_args()
    try:
        source = json.loads(args.original.read_text(encoding="utf-8"))
        result = json.loads(args.result.read_text(encoding="utf-8"))
        errors = validate(source, result)
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as error:
        errors = [str(error)]
    print(json.dumps({"status": "fail" if errors else "pass", "errors": errors,
                      "scope": "record_integrity_and_literal_protection_only"}, ensure_ascii=False, indent=2))
    raise SystemExit(bool(errors))


if __name__ == "__main__":
    main()
