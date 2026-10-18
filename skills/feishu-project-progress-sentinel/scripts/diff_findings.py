#!/usr/bin/env python3
"""对比两日 findings，输出变化清单（信号增删/级别变动/focus/各清单计数）。

用法: python3 diff_findings.py [--old 2026-09-17] [--new 2026-09-18] [项目...]
注意: 两天的采集窗口必须一致，否则"消失信号"多是窗口效应（见 SKILL 坑）。
"""
import json, os, sys, datetime

SKILL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKSPACE = os.environ.get("SENTINEL_WORKSPACE") or os.path.dirname(os.path.dirname(os.path.dirname(SKILL)))
D = os.path.join(WORKSPACE, ".workbuddy", "巡检")
args = sys.argv[1:]
def opt(flag, default):
    if flag in args:
        i = args.index(flag); args.pop(i); return args.pop(i)
    return default
DAY_NEW = opt("--new", datetime.date.today().isoformat())
DAY_OLD = opt("--old", (datetime.date.fromisoformat(DAY_NEW) - datetime.timedelta(days=1)).isoformat())
PROJ = args or ["客户B", "客户A", "客户C"]


def load(p, d):
    f = os.path.join(D, f"findings-{p}-{d}.json")
    return json.load(open(f)) if os.path.exists(f) else None


for p in PROJ:
    o, n = load(p, DAY_OLD), load(p, DAY_NEW)
    print("=" * 70)
    print(f"### {p}  {DAY_OLD} → {DAY_NEW}")
    if not o or not n:
        print("  缺文件 old/new:", bool(o), bool(n)); continue
    so = {(s.get("no"), s.get("kind")): s for s in o["signals"]}
    sn = {(s.get("no"), s.get("kind")): s for s in n["signals"]}
    print(f"信号 {len(so)} → {len(sn)} | 状态分布 {o['table']['status_dist']} → {n['table']['status_dist']}")
    print(f"表内最后更新 {o['table']['last_update_in_table']} → {n['table']['last_update_in_table']} (age {n['table']['table_age_days']})")
    for k in sorted([k for k in sn if k not in so], key=str):
        s = sn[k]; print(f"  ➕ [{s['severity']}] {s.get('no')} {s['kind']} | {s.get('title_desc','')}")
    for k in sorted([k for k in so if k not in sn], key=str):
        s = so[k]; print(f"  ➖ [{s['severity']}] {s.get('no')} {s['kind']} | {s.get('title_desc','')}")
    for k in [k for k in sn if k in so and (sn[k].get("title_desc") != so[k].get("title_desc") or sn[k].get("severity") != so[k].get("severity"))]:
        print(f"  🔄 {k[0]} {k[1]}: [{so[k]['severity']}→{sn[k]['severity']}] {so[k].get('title_desc','')} → {sn[k].get('title_desc','')}")
    fo = {x.get("no"): x for x in o.get("focus", [])}
    fn = {x.get("no"): x for x in n.get("focus", [])}
    print(f"  🎯 focus {'变化' if set(fo) != set(fn) else '编号不变'}: {sorted(fo)} → {sorted(fn)}")
    for no in sorted(set(fo) & set(fn)):
        if fo[no].get("current") != fn[no].get("current"):
            print(f"     {no}: {fo[no].get('current')} → {fn[no].get('current')}")
    for key in ("new_requirements", "risk_words", "todo_candidates", "missing_candidates"):
        a, b = o.get(key) or [], n.get(key) or []
        if len(a) != len(b):
            print(f"  {key}: {len(a)} → {len(b)}")
