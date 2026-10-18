#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把「人工判读」结果合并进 analyze.py 的产出（findings + 巡检报告）。

为什么需要它：analyze.py 只能做机械比对。`completion_candidate`（疑似已完成未回写）
这类信号必须由人/AI 翻群聊原文核实，否则会误报。判读结论如果只存在于对话里，
下次重跑 analyze.py 就被覆盖 —— 所以落成 verdicts 文件，用本脚本合并。

用法：
  python3 apply_verdicts.py --project 客户A
  python3 apply_verdicts.py --project 客户B --date 2026-09-17

verdicts 文件默认路径：<scratch>/verdicts-<项目>-<日期>.json，结构：

  {
    "reviewed_at": "2026-09-17 15:50",
    "method": "逐条翻群聊/文档找正面证据；无正面证据即判误报，不改线上状态",
    "conclusion": {                      # 可选：整段覆盖 analyze 的结论
      "headline": "...", "points": ["..."], "actions": ["..."]
    },
    "verdicts": {
      "T57": {"verdict": "误报·不改状态", "note": "命中证据实为 T53…"},
      "T04": {"verdict": "确认逾期·卡客户侧", "note": "交接清单：…"}
    },
    "dismiss_kinds": ["new_requirement"], # 可选·整类剔除（无编号信号必用此路）
    "req_summary": {"count": 0, "names": [], "status": "本轮无有效新增需求"},  # 剔类后必须同步改，否则卡片仍出区块
    "extra_findings": [                  # 可选：补充脚本抓不到的发现
      {"title": "客户今日新增财务请款闭环诉求", "note": "客户高管 9/17 08:47 提出，客户接口人已认领"}
    ]
  }
"""
import argparse
import datetime
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402


def load_verdicts(path):
    if not os.path.exists(path):
        raise SystemExit(f"找不到判读文件：{path}\n"
                         f"先按脚本头部的结构写一份 verdicts-<项目>-<日期>.json")
    return json.load(open(path, encoding="utf-8"))


def merge_findings(findings, vd):
    by_no = vd.get("verdicts") or {}
    applied = []
    for s in findings.get("signals") or []:
        v = by_no.get(s.get("no"))
        if not v:
            continue
        s["verdict"] = v.get("verdict")
        s["verdict_note"] = v.get("note")
        # 判为误报的信号保留在报告里（说明为什么不是问题），但不再进卡片的计数。
        # 用 dismiss_kinds 精确到信号类型：同一个编号可能「逾期属实但疑似已完成是误报」。
        dk = v.get("dismiss_kinds")
        if dk is None:
            dk = ["completion_candidate"] if "误报" in (v.get("verdict") or "") else []
        if s.get("kind") in dk:
            s["dismissed"] = True
        applied.append((s.get("no"), s.get("kind"), v.get("verdict")))
    # 顶层 dismiss_kinds：整类信号判误报。
    # 用于**没有编号**的信号 —— new_requirement 的 no 恒为 None，按编号写 verdicts 命中不了，
    # 只能整类剔除（如群聊过程片段被误抽成需求）。剔除后务必同步校正 req_summary，
    # 否则卡片仍会出现「新增诉求」区块。
    for k in vd.get("dismiss_kinds") or []:
        for s in findings.get("signals") or []:
            if s.get("kind") == k:
                s["dismissed"] = True
                applied.append((s.get("no"), k, f"[整类剔除] {k}"))
    if vd.get("conclusion"):
        findings["conclusion"] = vd["conclusion"]
    # ---- 「今天优先处理」人工覆盖：verdicts.focus = [{no, current, next, meta?, title?}]
    #       ① 按 no 替换对应条目的字段（没写的字段保留脚本生成的）；
    #       ② **支持新增**：脚本的 focus 只取 P0 逾期前 5 条，人工若判定某条非逾期项
    #          （如 due_soon 的今天到期项）今天必须处理，写进 verdicts.focus 即可插到最前。
    #          新增条目的 owners/meta 从同编号 signal 继承，避免卡片 @ 不到人。
    if vd.get("focus"):
        by_no = {x.get("no"): x for x in vd["focus"]}
        matched = set()
        for item in findings.get("focus") or []:
            v = by_no.get(item.get("no"))
            if v:
                for k in ("title", "meta", "current", "next"):
                    if v.get(k):
                        item[k] = v[k]
                matched.add(item.get("no"))
        sig_no = {}
        for s in findings.get("signals") or []:
            if s.get("no") and s["no"] not in sig_no:
                sig_no[s["no"]] = s
        extra = []
        for v in vd["focus"]:
            no = v.get("no")
            if not no or no == "REQ" or no in matched:
                continue
            s = sig_no.get(no) or {}
            meta = v.get("meta")
            if not meta:
                m = re.search(r"计划完成 (\d{4}-\d{2}-\d{2}) 已过 (\d+) 天", s.get("title_desc") or "")
                meta = (f"超期 **{m.group(2)}** 天 · 计划 {m.group(1)[5:]}" if m
                        else (s.get("title_desc") or "")[:40])
            extra.append({"no": no, "title": v.get("title") or s.get("title") or "",
                          "owners": s.get("owners") or [], "meta": meta,
                          "current": v.get("current") or "", "next": v.get("next") or ""})
        if extra:
            findings["focus"] = extra + (findings.get("focus") or [])
    # ---- 「近期关键节点」补充：脚本抓不到的节点差异（如 T67 会期 9/18 vs 表内 10/03）
    #       同编号去重，但 **warn 差异必须保留**：已脚本列出的同编号节点，把 warn 挂上去。
    kn = findings.setdefault("key_nodes", [])
    for n in vd.get("extra_key_nodes") or []:
        m = re.search(r"T\d+", n.get("label") or "")
        dup = next((x for x in kn if m and m.group(0) in (x.get("label") or "")), None)
        if dup is not None:
            if n.get("warn") and not dup.get("warn"):
                dup["warn"] = n["warn"]
                if n.get("date"):
                    dup["date"] = n["date"]          # 差异节点以实际会期排序
            continue
        if n not in kn:
            kn.append(n)
    kn.sort(key=lambda x: x.get("date") or "")
    findings["key_nodes"] = kn[:8]          # 节点太多会淹没重点，超出部分看报告
    # ---- REQ 汇总项若被人工校正，focus 里的「新增需求整理」同步用校正后的名称
    if vd.get("req_summary"):
        for item in findings.get("focus") or []:
            if item.get("no") == "REQ":
                names = (vd["req_summary"].get("names")
                         or (findings.get("req_summary") or {}).get("names") or [])
                if names:
                    item["current"] = " / ".join(names[:5]) + ("等" if len(names) > 5 else "")
    # ---- 新增诉求归类的人工校正（名称/分类/动作都可改）
    if vd.get("req_summary"):
        findings["req_summary"] = dict(findings.get("req_summary") or {}, **vd["req_summary"])
    findings["verdicts_meta"] = {
        "reviewed_at": vd.get("reviewed_at") or datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "method": vd.get("method"),
        "applied": [{"no": n, "kind": k, "verdict": v} for n, k, v in applied],
        "extra_findings": vd.get("extra_findings") or [],
        "source": vd.get("_source"),
    }
    return findings, applied


def patch_report(md, vd, applied):
    """① 在对应信号小节标题下插入判读行；② 文末追加「人工核实结论」节。

    幂等：重跑前先按 `> ✅ **人工核实：` 与结尾节标题把上一次的结果剥掉，避免重复堆叠。
    """
    md = re.sub(r"\n> ✅ \*\*人工核实：.*?(?=\n(?!> ✅ )|\Z)", "", md, flags=re.S)
    md = md.split("## 🔎 人工核实结论")[0].rstrip()

    note_by_no = {n: (v.get("verdict"), v.get("note"))
                  for n, v in (vd.get("verdicts") or {}).items()}
    if applied:
        lines = md.split("\n")
        out = []
        for ln in lines:
            out.append(ln)
            m = re.match(r"^### \[[^\]]+\] (T\d+) ", ln) or re.match(r"^### (T\d+) ", ln)
            if m:
                no = m.group(1)
                if no in note_by_no and note_by_no[no][1]:
                    out.append(f"> ✅ **人工核实：{note_by_no[no][0]}** —— {note_by_no[no][1]}")
        md = "\n".join(out)

    block = ["", "## 🔎 人工核实结论（脚本给不了的部分）", ""]
    block.append(f"- 核实时间：**{vd.get('reviewed_at', '')}**")
    if vd.get("method"):
        block.append(f"- 方法：{vd['method']}")
    block.append("")
    block.append("| 编号 | 脚本判定 | 人工裁定 | 说明 |")
    block.append("|---|---|---|---|")
    for no, v in (vd.get("verdicts") or {}).items():
        block.append(f"| {no} | 待判读 | **{v.get('verdict','')}** | {v.get('note','')} |")
    extra = vd.get("extra_findings") or []
    if extra:
        block += ["", "**脚本未捕获、但值得记的发现：**", ""]
        for e in extra:
            block.append(f"- **{e.get('title','')}** —— {e.get('note','')}")
    block += ["", "> 以上为人工判读，**未回写线上表**；如需回写请单独授权。", ""]
    return md.rstrip("\n") + "\n" + "\n".join(block)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--date", default=None)
    ap.add_argument("--verdicts", default=None)
    ap.add_argument("--workspace", default=None)
    args = ap.parse_args()

    cfg = C.load_config(args.workspace)
    day = args.date or C.today().isoformat()
    vpath = args.verdicts or os.path.join(cfg["_scratch"], f"verdicts-{args.project}-{day}.json")
    vd = load_verdicts(vpath)
    vd["_source"] = vpath

    fpath = os.path.join(cfg["_scratch"], f"findings-{args.project}-{day}.json")
    rpath = os.path.join(cfg["_scratch"], f"巡检报告-{args.project}-{day}.md")
    findings = json.load(open(fpath, encoding="utf-8"))
    findings, applied = merge_findings(findings, vd)
    C.dump(fpath, findings)

    if os.path.exists(rpath):
        md = open(rpath, encoding="utf-8").read()
        open(rpath, "w", encoding="utf-8").write(patch_report(md, vd, applied))

    print(json.dumps({"ok": True, "verdicts": vpath, "applied": len(applied),
                      "findings": fpath, "report": rpath,
                      "detail": [{"no": n, "kind": k, "verdict": v} for n, k, v in applied]},
                     ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
