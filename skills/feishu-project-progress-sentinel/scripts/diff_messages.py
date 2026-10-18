#!/usr/bin/env python3
"""对比两日 raw，列出新增群消息（按项目/群分组）。

用法: python3 diff_messages.py [--old 2026-09-17] [--new 2026-09-18] [项目...]
这才是"数据更新"的原始事实来源 —— 信号变化看 diff_findings，事实增量看这里。
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

for p in PROJ:
    fo, fn = os.path.join(D, f"raw-{p}-{DAY_OLD}.json"), os.path.join(D, f"raw-{p}-{DAY_NEW}.json")
    if not (os.path.exists(fo) and os.path.exists(fn)):
        print(f"### {p}: 缺 raw 文件"); continue
    o, n = json.load(open(fo)), json.load(open(fn))
    def key(m): return m.get("message_id") or (m.get("time"), (m.get("text") or "")[:60])
    old = {key(m) for m in o["messages_flat"]}
    new = [m for m in n["messages_flat"] if key(m) not in old]
    print("=" * 78)
    print(f"### {p}  新增 {len(new)} 条  (窗口 {o['window']['since']}→{n['window']['until']})")
    by = {}
    for m in new:
        by.setdefault(m.get("src") or m.get("chat") or "?", []).append(m)
    for src, ms in by.items():
        print(f"\n--- {src}（{len(ms)} 条）")
        for m in sorted(ms, key=lambda x: x.get("time", "")):
            print(f"  {m.get('time','')} {m.get('sender','')}: {(m.get('text') or '').replace(chr(10),' ')[:150]}")
