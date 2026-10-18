#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把各项目表里「人员」字段的 open_id ↔ 姓名自动收进 references/people.local.json。

为什么需要它：
- 跨租户客户成员（客户A、客户B等）在 contact +search-user 里查不到，
  但**实施表的人员字段里带着他们的 open_id 和姓名**。
- 卡片要 @ 到人、客户沉默检测要显示真名，都需要这份映射。
- 每次巡检后跑一次即可（analyze 已经拉过记录，这里直接读缓存的 ndjson，不再打接口）。

产出：references/people.local.json
  {"ou_xxx": "张三", "_meta": {...}}
该文件是**人名映射、不是凭据**，可以入库（不含 webhook/token）。
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(HERE)
OUT = os.path.join(SKILL_DIR, "references", "people.local.json")


def fields_of(proj):
    """从项目配置里挑出所有「人员」类型的字段名。"""
    f = proj.get("fields") or {}
    keys = ("owner", "client_owner", "collab")
    out = []
    for k in keys:
        v = f.get(k)
        if v:
            out.append(v)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default="all")
    ap.add_argument("--workspace", default=None)
    a = ap.parse_args()

    cfg = C.load_config(a.workspace)
    keys = list(cfg["projects"]) if a.project == "all" else [a.project]
    work = os.path.join(cfg["_scratch"], ".scratch")

    idx, per_proj = {}, {}
    for key in keys:
        proj = C.project_cfg(cfg, key)
        path = os.path.join(work, f"cur-{key}.ndjson")
        if not os.path.exists(path):
            print(f"[skip] {key}: 找不到 {path}（先跑 analyze.py）", file=sys.stderr)
            continue
        recs = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
        n = 0
        for r in recs:
            for fld in fields_of(proj):
                for p in C.people(r.get(fld)):
                    if p["id"] and p["name"]:
                        idx[p["id"]] = p["name"]
                        n += 1
        per_proj[key] = n

    if os.path.exists(OUT):
        try:
            old = json.load(open(OUT, encoding="utf-8"))
        except Exception:
            old = {}
    else:
        old = {}
    merged = {k: v for k, v in old.items() if k.startswith("ou_")}
    before = len(merged)
    merged.update(idx)

    out = {k: merged[k] for k in sorted(merged)}
    out["_meta"] = {
        "note": "自动生成，勿手改。来源 = 各项目表「人员」字段。是姓名映射，不是凭据，可入库。",
        "count": len(merged),
        "by_project": per_proj,
    }
    C.dump(OUT, out)
    print(json.dumps({"ok": True, "out": OUT, "total": len(merged),
                      "added": len(merged) - before, "by_project": per_proj},
                     ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
