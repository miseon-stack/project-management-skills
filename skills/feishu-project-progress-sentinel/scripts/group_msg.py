#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""输出层：把「刚完成的事」变成群内话术 + 存档材料。**只生成草稿，绝不自动发送。**

用法：
  python3 group_msg.py --project 客户B --items items.json --kind both
  python3 group_msg.py --project 客户B --items items.json --kind group    # 只要群话术
  python3 group_msg.py --project 客户B --items items.json --kind archive  # 只要存档材料

items.json 结构：
{
  "date": "2026-09-17",
  "items": [
    {"no":"T108","title":"AI 输出置信度与关键字段校验规则",
     "fact":"已完成规则口径梳理，覆盖 6 个核心字段",
     "deliverable":[{"name":"《置信度与字段校验规则 v1》","url":"https://…"}]}
  ],
  "next_steps": ["9/18 前完成第二轮验证"],
  "asks": ["请客户方负责人确认需保留的核心字段清单"],
  "archive_title": "客户B · 9/17 进展同步"
}

产出：
  <scratch>/群话术-<项目>-<date>.md
  <scratch>/存档材料-<项目>-<date>.md
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402

# 对外红线：出现这些词直接拦下（客户可见口径）
RED_LINES = ["付款", "催款", "商务", "报价", "返点", "内部记录", "rec", "别把活", "研发都投",
             "测绘仅", "预算", "成本价", "不信任", "投诉", "逾期 N 天"]


def render_group(proj, data):
    d = data.get("date") or C.today().isoformat()
    out = [f"【{proj['label'].split('·')[0].strip()}】{d} 进展同步", ""]
    for it in data.get("items", []):
        head = (it.get("no") + " " if it.get("no") else "") + it.get("title", "")
        out.append(f"· {head}")
        if it.get("fact"):
            out.append(f"  {it['fact']}")
        for dv in it.get("deliverable", []) or []:
            name, url = dv.get("name", ""), dv.get("url", "")
            out.append(f"  {name}：{url}" if url else f"  {name}")
    if data.get("next_steps"):
        out += ["", "下一步："] + [f"{i+1}. {s}" for i, s in enumerate(data["next_steps"])]
    if data.get("asks"):
        out += ["", "需要确认："] + [f"{i+1}. {s}" for i, s in enumerate(data["asks"])]
    return "\n".join(out)


def render_archive(proj, data, findings):
    d = data.get("date") or C.today().isoformat()
    L = [f"# {data.get('archive_title') or (proj['label'] + ' · ' + d + ' 进展存档')}", ""]
    L.append(f"- 项目：{proj['label']}")
    L.append(f"- 线上表：{proj['url']}")
    L.append(f"- 存档时点：{C.datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}")
    L.append("")
    L.append("## 一、本期完成事项")
    L.append("")
    L.append("| 编号 | 事项 | 事实 | 交付物 |")
    L.append("|---|---|---|---|")
    for it in data.get("items", []):
        dv = " / ".join(f"[{x.get('name','')}]({x.get('url','')})" for x in (it.get("deliverable") or []))
        L.append(f"| {it.get('no','—')} | {it.get('title','')} | {it.get('fact','')} | {dv or '—'} |")
    L.append("")
    if data.get("next_steps"):
        L += ["## 二、下一步", ""] + [f"{i+1}. {s}" for i, s in enumerate(data["next_steps"])] + [""]
    if data.get("asks"):
        L += ["## 三、需确认事项", ""] + [f"{i+1}. {s}" for i, s in enumerate(data["asks"])] + [""]
    if data.get("evidence"):
        L += ["## 四、共识证据（群内原话）", ""] + [f"- {e}" for e in data["evidence"]] + [""]
    if findings:
        sg = [s for s in findings.get("signals", []) if s["severity"] in ("P0", "P1")]
        if sg:
            L += ["## 五、当前未闭环项（内部视角，勿直发客户）", ""]
            for s in sg:
                L.append(f"- [{s['severity']}] {s['no']} {s['title']} —— {s['title_desc']}")
            L.append("")
            L.append("> 以上为内部观察，对外沟通需改写为请求式表述（见 references/话术模板.md）。")
            L.append("")
    return "\n".join(L)


def check_redlines(text):
    return [w for w in RED_LINES if w in text]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--items", required=True, help="items.json 路径")
    ap.add_argument("--kind", default="both", choices=["group", "archive", "both"])
    ap.add_argument("--findings", default=None, help="findings json，用于附未闭环项")
    ap.add_argument("--workspace", default=None)
    a = ap.parse_args()

    cfg = C.load_config(a.workspace)
    proj = C.project_cfg(cfg, a.project)
    data = json.load(open(a.items if os.path.isabs(a.items) else a.items, encoding="utf-8"))
    findings = None
    if a.findings and os.path.exists(a.findings):
        findings = json.load(open(a.findings, encoding="utf-8"))
    else:
        cand = C.out_path(cfg, f"findings-{a.project}-{C.today().isoformat()}.json")
        if os.path.exists(cand):
            findings = json.load(open(cand, encoding="utf-8"))

    d = data.get("date") or C.today().isoformat()
    result = {"ok": True, "files": []}
    if a.kind in ("group", "both"):
        txt = render_group(proj, data)
        p = C.out_path(cfg, f"群话术-{a.project}-{d}.md")
        open(p, "w", encoding="utf-8").write(txt + "\n")
        result["files"].append(p)
        result["group_text"] = txt
        hits = check_redlines(txt)
        result["redline_hits"] = hits
    if a.kind in ("archive", "both"):
        txt = render_archive(proj, data, findings)
        p = C.out_path(cfg, f"存档材料-{a.project}-{d}.md")
        open(p, "w", encoding="utf-8").write(txt + "\n")
        result["files"].append(p)
        result["redline_hits"] = sorted(set(result.get("redline_hits", []) + check_redlines(txt)))
    print(json.dumps(result, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
