"""Exact catalog lookup; unmatched names require alias verification."""
import argparse, json, re, unicodedata
from pathlib import Path

def normalize(value):
    return re.sub(r"[^a-z0-9]", "", unicodedata.normalize("NFKC",value).casefold())

def lookup(query):
    data=json.loads(Path(__file__).with_name("catalog-2026.json").read_text(encoding="utf-8"))
    key=normalize(query)
    matches=[e for e in data["entries"] if key and key in [normalize(e["abbreviation"]),normalize(e["full_name"])]]
    return {"query":query,"edition":data["edition"],"status":data["status"],"limitation":data["limitation"],"matches":matches,"match_status":"matched" if matches else "unmatched_check_aliases"}

if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument("query"); args=parser.parse_args()
    print(json.dumps(lookup(args.query),ensure_ascii=False,indent=2))
