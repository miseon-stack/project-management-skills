#!/usr/bin/env python3
"""实读项目表 → 逐条快照 JSON（供次日 diff）。

用法: python3 snapshot_table.py [YYYY-MM-DD] [项目名...]
每次巡检都跑一次，留下「逐条基线」；否则次日只能靠汇总数字推断变化。
"""
import json, os, subprocess, sys, datetime

SKILL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKSPACE = os.environ.get("SENTINEL_WORKSPACE") or os.path.dirname(os.path.dirname(os.path.dirname(SKILL)))
D = os.path.join(WORKSPACE, ".workbuddy", "巡检")
REG = json.load(open(os.path.join(SKILL, "references", "projects.json")))
DAY = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1][0].isdigit() else datetime.date.today().isoformat()
ONLY = [a for a in sys.argv[1:] if not a[0].isdigit()]


def run(args):
    return json.loads(subprocess.run(args, capture_output=True, text=True).stdout)


for name, cfg in REG["projects"].items():
    if ONLY and name not in ONLY:
        continue
    out = run(["lark-cli", "base", "+field-list", "--base-token", cfg["base_token"],
               "--table-id", cfg["table_id"], "--format", "json"])
    fid2name = {f["id"]: f["name"] for f in out["data"]["fields"]}
    res = run(["lark-cli", "base", "+record-list", "--base-token", cfg["base_token"],
               "--table-id", cfg["table_id"], "--page-size", "200", "--format", "json"])
    d = res["data"]
    names = [fid2name.get(i, i) for i in d["field_id_list"]]
    recs = [{"record_id": rid, "cells": dict(zip(names, row))}
            for rid, row in zip(d["record_id_list"], d["data"])]
    snap = {"project": name, "as_of": DAY, "table_id": cfg["table_id"],
            "count": len(recs), "records": recs}
    p = os.path.join(D, f"table-snapshot-{name}-{DAY}.json")
    json.dump(snap, open(p, "w"), ensure_ascii=False, indent=1)
    print(f"{name}: {len(recs)} 条 → {os.path.basename(p)}")
