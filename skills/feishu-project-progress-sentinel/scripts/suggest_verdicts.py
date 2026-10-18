#!/usr/bin/env python3
"""半自动人工判读：为巡检信号生成「判读候选」，人只需确认/改判。

为什么需要它：analyze.py 只能判「线上日期过了」，判不了「是不是其实已经做完了只是没回写」。
2026-09-20 教训 —— 客户C T06 考勤报表线上逾期 8 天、群里也没动静，实际我方方案+客户版+导入脚本+
样板表早就交付了，只看线上就会误判成「没做」。本脚本把「翻本地交付物 + 翻群消息」这一步自动化。

用法:
  python3 suggest_verdicts.py --project all
  python3 suggest_verdicts.py --project 客户B --date 2026-09-21 --no-hub
  python3 suggest_verdicts.py --project 客户B --promote     # 确认无误后落成正式 verdicts（需你显式加）

产出:
  <工作区>/.workbuddy/巡检/verdicts-<项目>-<日期>.suggested.json   候选（可改后改名去掉 .suggested）
  <工作区>/.workbuddy/巡检/判读候选-<项目>-<日期>.md                给人看的勾选清单

★ 本脚本**只出候选、不改 findings、不写线上**。判读要人确认（尤其「改承诺日」一律不碰）。
"""
import argparse
import datetime
import glob
import json
import os
import re
import shutil
import sqlite3
import sys

SKILL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

TEXT_EXT = {".md", ".txt", ".py", ".json", ".csv", ".sh", ".html", ".tsv", ".yml", ".yaml"}
MAX_BYTES = 1_500_000
SKIP_DIR_PARTS = {"node_modules", ".git", "__pycache__", "飞书数据仓", ".workbuddy",
                  "dist", "build", ".venv", "venv"}
# 关键词停用词（标题切词后丢弃）
# 硬排除：这些文件是"我方自己产出的分析/报告"，命中只能说明"提过这个任务"，
# 不能当作"已交付"，否则会把巡检报告本身当成交付物证据（实测踩过）。
SELF_REPORT_RE = re.compile(
    r"(巡检报告-|findings-|verdicts-|判读候选-|table-snapshot-|raw-|run-20|"
    r"全量差异核对|D类逾期重排提案|会议摘要汇编|会议复盘清单|项目表核对|"
    r"周报|日报/|FDE|工作档案分析|任务检查报告|/归档/|_archive|README\.md|00_工作总索引|"
    r"周会|准备稿|补充建议|提案|评估|复盘|摘要|核对|案例卡|工作看板|看板\.html)")

STOP = set("的 与 和 及 或 为 在 上 下 中 内 外 一 二 三 个 项 条 版 次 等 并 对 从 到 由 按 以 后 前 支持 提供 完成 搭建 推进 整理 配置 落地 方案 文档 系统 平台 数据 需求 开发 测试 培训 服务 项目 客户 部门 相关 工作 内容 能力 流程 规则 模板 清单 情况 问题 处理 优化 确认 输出 交付 上线 迁移 整理与".split())

SIDE_OWN = "我方"
SIDE_CLIENT = "客户方"
SIDE_UNKNOWN = "未明确"


def resolve_ws(argv_ws):
    ws = argv_ws or os.environ.get("SENTINEL_WORKSPACE")
    if not ws:
        cand = os.path.dirname(os.path.dirname(os.path.dirname(SKILL)))
        ws = cand if os.path.isdir(os.path.join(cand, ".workbuddy")) else os.getcwd()
    return os.path.abspath(ws)


def load_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default



def project_dirs(ws, project, cfg):
    """该项目相关的本地目录（交付物证据所在）。"""
    d = []
    dirs_skip = set()
    for name in ("项目资料", "会议纪要", "分析", "群聊资料", "归档"):
        p = os.path.join(ws, project_dir_name(project, cfg), name)
        if os.path.isdir(p):
            d.append(p)
    globals()["_SKIP_DIRS"] = dirs_skip
    for shared in ("工具", "产物", "日报"):
        p = os.path.join(ws, shared)
        if not os.path.isdir(p):
            continue
        if shared == "产物":                       # 归档/数据 是历史快照，不作证据
            for sub in ("归档", "数据", "被@待办"):
                sp = os.path.join(p, sub)
                if os.path.isdir(sp):
                    dirs_skip.add(sp)
        d.append(p)
    return d


def project_dir_name(project, cfg):
    """项目 key → 工作区目录名（登记册里没有就直接用 key，再退化为模糊匹配）。"""
    label = (cfg.get(project) or {}).get("label") or ""
    for guess in (project, label.split(" · ")[0], label.split("·")[0].strip()):
        if guess:
            p = os.path.join(os.environ["_SUGGEST_WS"], guess)
            if os.path.isdir(p):
                return guess
    return project


def iter_files(dirs):
    skip = globals().get("_SKIP_DIRS") or set()
    for root_dir in dirs:
        for dirpath, dirnames, filenames in os.walk(root_dir):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIR_PARTS]
            if dirpath in skip:
                dirnames[:] = []
                continue
            for fn in filenames:
                p = os.path.join(dirpath, fn)
                if os.path.splitext(fn)[1].lower() not in TEXT_EXT:
                    continue
                try:
                    if os.path.getsize(p) > MAX_BYTES:
                        continue
                except OSError:
                    continue
                yield p


def scan_local(dirs):
    """遍历本地交付物目录，返回 (文件→小写全文索引, {任务编号: [(文件, 行号, 片段)]})。"""
    kw_index, no_hits = {}, {}
    for p in iter_files(dirs):
        try:
            txt = open(p, encoding="utf-8", errors="ignore").read()
        except OSError:
            continue
        rel = os.path.relpath(p, os.environ["_SUGGEST_WS"])
        if SELF_REPORT_RE.search(rel):
            continue
        for m in re.finditer(r"\bT(\d{1,3})\b", txt):
            digits = m.group(1).lstrip("0") or "0"
            no = "T" + digits
            no_hits.setdefault(no, []).append(
                (rel, 0, txt[max(0, m.start() - 30):m.start() + 40].replace("\n", " ")))
        kw_index[rel] = txt.lower()
    return kw_index, no_hits


def tokenize_split(title):
    """把标题切成 strong（≥3 字/≥4 位英文，识别度高）与 weak（2 字滑窗，识别度低）。"""
    strong, weak = [], []
    for p in re.split(r"[^\u4e00-\u9fa5A-Za-z0-9]+", title or ""):
        if not p:
            continue
        if re.fullmatch(r"[A-Za-z0-9]+", p):
            if len(p) >= 4 and p.lower() not in ("the", "and", "for"):
                strong.append(p)
            continue
        if len(p) >= 3 and p not in STOP:
            strong.append(p)
        for i in range(len(p) - 1):
            w = p[i:i + 2]
            if w not in STOP:
                weak.append(w)
    def uniq(seq, cap):
        seen, out = set(), []
        for w in seq:
            if w not in seen:
                seen.add(w)
                out.append(w)
        return out[:cap]
    # 整串（如「研发周报整合」）+ 词块；整串太长时命中率低，仍保留但排序在词块后
    return uniq(strong, 8), uniq(weak, 14)


def path_weight(rel):
    """按目录给证据分级：项目资料/工具 = 交付物；产物 = 半可信；会议纪要与日报 = 弱证据。"""
    if "/会议纪要/" in rel or rel.startswith("会议纪要/") or "/群聊资料/" in rel:
        return 0.4, "会议记录"
    if "/项目资料/" in rel or rel.startswith("项目资料/") or "/工具/" in rel or rel.startswith("工具/"):
        return 1.0, "交付物"
    if rel.startswith("产物/"):
        return 0.7, "产物"
    return 0.8, "其他"


def match_evidence(index, strong, weak, no=None, limit=3):
    """按命中强度给本地文件打分。

    打分：strong 命中 ×3、weak 命中 ×1（weak 需命中 ≥2 个才算数）；文件名含任务编号 +4、
    路径含「归档/报告」−2。返回 [(score, 文件, 命中词...)]。
    """
    strong_l = [w.lower() for w in strong]
    weak_l = [w.lower() for w in weak]
    out = []
    for rel, low in index.items():
        s_hits = [w for w in strong_l if w in low]
        w_hits = [w for w in weak_l if w in low]
        # 只看 weak 时必须命中 ≥3 个不同词 —— 2 字滑窗跨词拼接会产生「维表」「阅会」这类假词，
        # 门槛放低会把「方案里提过」误判成「已交付」（实测踩过）。
        if not s_hits and len(w_hits) < 3:
            continue
        score = 3 * len(s_hits) + len(w_hits)
        base = os.path.basename(rel)
        if no and re.search(r"\b%s\b" % re.escape(no), base, re.I):
            score += 4
        if "归档" in rel or "提取报告" in rel or "复盘" in rel:
            score -= 2
        if score <= 0:
            continue
        mult, cls = path_weight(rel)
        score = max(1, int(round(score * mult)))
        out.append((score, rel, "、".join((s_hits + w_hits)[:4]), cls))
    out.sort(key=lambda x: (-x[0], x[1]))
    return out[:limit]


def confidence_of(ev):
    if not ev:
        return "低", []
    top = ev[0][0]
    conf = "高" if top >= 7 else ("中" if top >= 3 else "低")
    if conf == "高" and all((len(x) > 3 and x[3] == "会议记录") for x in ev[:2]):
        conf = "中"          # 只靠会议纪要，撑不起「疑似已完成」
    return conf, ev


def ev_names(ev, n=2):
    return "、".join(x[1] for x in ev[:n])


def ev_is_meeting_only(ev):
    return bool(ev) and all((len(x) > 3 and x[3] == "会议记录") for x in ev)


def hub_search(ws, kws, days=14, limit=3):
    db = os.path.join(ws, "飞书数据仓", "hub.db")
    if not os.path.exists(db) or not kws:
        return []
    since = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
    out = []
    try:
        con = sqlite3.connect("file:%s?mode=ro" % db, uri=True)
        cur = con.cursor()
        for kw in kws[:6]:
            try:
                rows = cur.execute(
                    "SELECT datetime(create_time/1000,'unixepoch','+8 hours'), sender_name, "
                    "substr(replace(text,char(10),' '),1,160) FROM messages "
                    "WHERE text LIKE ? AND create_time/1000 > strftime('%s',?,'-8 hours') "
                    "ORDER BY create_time DESC LIMIT ?", ("%" + kw + "%", since + " 00:00:00", limit)).fetchall()
            except sqlite3.Error:
                continue
            for t, who, txt in rows:
                out.append({"kw": kw, "time": t, "sender": who, "text": txt})
        con.close()
    except sqlite3.Error:
        return []
    seen, uniq = set(), []
    for h in out:
        k = (h["time"], h["text"][:40])
        if k in seen:
            continue
        seen.add(k)
        uniq.append(h)
    uniq.sort(key=lambda x: x["time"], reverse=True)
    return uniq[:limit]


def owner_side(sig, our_team):
    owners = [o.get("name") for o in (sig.get("owners") or []) if o.get("name")]
    if not owners and sig.get("owner"):
        owners = [sig["owner"]]
    if not owners:
        return SIDE_UNKNOWN, []
    own = [n for n in owners if n in our_team]
    if own and len(own) == len(owners):
        return SIDE_OWN, owners
    if own:
        return SIDE_OWN, owners      # 我方牵头（含协作）
    return SIDE_CLIENT, owners


def classify(sig, side, ev_local, ev_hub):
    """返回 (verdict, note, confidence, auto_ok)。

    只有「需要判断到底做没做」的信号才用本地交付物证据（overdue / no_progress / completion_candidate）；
    due_soon / blocked / stale_table 是规则型判定，堆证据反而是噪音。
    """
    kind = sig.get("kind")
    conf, ev = confidence_of(ev_local)
    has_local = bool(ev)
    if kind == "overdue":
        if side == SIDE_OWN and has_local:
            what = "会议记录显示已开会/已讨论" if ev_is_meeting_only(ev) else "本地命中交付物"
            return ("疑似已完成未回写 · 待确认",
                    "%s：%s；确认已交付即可改状态，否则给新完成日" % (what, ev_names(ev)),
                    conf, conf == "高")
        if side == SIDE_OWN:
            return ("逾期属实 · 我方条目（本地无交付物）",
                    "项目资料/工具/产物/日报 均未找到对应产出，逾期属实，需给完成日或顺延",
                    "中", True)
        if ev_hub:
            return ("逾期属实 · 客户方条目（近期有动作）",
                    "群内近期有相关发言，非停摆，列入现场/群里统一核对即可",
                    "中", True)
        return ("逾期属实 · 客户方条目", "负责人为客户方，非我方可改，列入统一核对", "中", True)
    if kind == "no_progress":
        if has_local:
            what = "会议记录已有相关内容" if ev_is_meeting_only(ev) else "本地命中产出"
            return ("已有产出未回写", "%s：%s，补一句进展即可" % (what, ev_names(ev)), conf, False)
        return ("属实 · 需补进展", "本地无对应产出，按「日期 + 事实 + 下一步」补写", "低", False)
    if kind == "completion_candidate":
        return ("待核实是否已完成", "脚本疑为已完成，请人工核实后决定是否改状态", "低", False)
    if kind == "due_soon":
        return ("临近节点 · 当日确认", "当天到期，需确认能否按期收口；不能则提前改期", "—", False)
    if kind == "stale_table":
        return ("表停更 · 催更", "线上表长时间未更新，先催负责人更新再谈差异", "—", False)
    if kind == "blocked":
        return ("阻塞 · 需给解铃人与期限", "阻塞项必须带「谁、做什么、何时」，否则会烂在表里", "—", False)
    return (None, None, "—", False)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default="all")
    ap.add_argument("--date", default=None)
    ap.add_argument("--workspace", default=None)
    ap.add_argument("--no-hub", action="store_true", help="不查本地数据仓群消息")
    ap.add_argument("--hub-days", type=int, default=14)
    ap.add_argument("--promote", action="store_true",
                    help="把候选直接落成正式 verdicts-<项目>-<日期>.json（会覆盖同名文件）")
    a = ap.parse_args()

    ws = resolve_ws(a.workspace)
    os.environ["_SUGGEST_WS"] = ws
    out = os.path.join(ws, ".workbuddy", "巡检")
    date = a.date or datetime.date.today().isoformat()

    reg = load_json(os.path.join(SKILL, "references", "projects.json"), {}) or {}
    cfg = reg.get("projects") or {}
    our_team = set((load_json(os.path.join(SKILL, "references", "team.json"), {}) or {}).get("our_team") or [])

    keys = list(cfg) if a.project == "all" else [a.project]
    rc = 0
    for p in keys:
        fj = os.path.join(out, "findings-%s-%s.json" % (p, date))
        fd = load_json(fj)
        if not fd:
            print("✗ %s：找不到 %s（先跑 analyze 或 run_all.sh）" % (p, fj))
            rc = 1
            continue
        dirs = project_dirs(ws, p, cfg)
        kw_index, _ = scan_local(dirs)
        sigs = [s for s in (fd.get("signals") or []) if not s.get("dismissed")]
        verdicts, suggestions, lines = {}, {}, []
        for s in sigs:
            side, owners = owner_side(s, our_team)
            strong, weak = tokenize_split(s.get("title") or "")
            ev_local = match_evidence(kw_index, strong, weak, no=s.get("no"))
            ev_hub = [] if a.no_hub else hub_search(ws, (strong + weak)[:6], days=a.hub_days)
            verdict, note, conf, auto_ok = classify(s, side, ev_local, ev_hub)
            no = s.get("no") or ("REQ" if s.get("kind") == "new_requirement" else None)
            if not verdict or not no:
                continue
            verdicts[no] = {"verdict": verdict, "note": note}
            suggestions[no] = {
                "kind": s.get("kind"), "severity": s.get("severity"),
                "owner_side": side, "owners": owners, "confidence": conf,
                "auto_ok": auto_ok,
                "evidence_local": [{"file": x[1], "score": x[0], "hit": x[2]} for x in ev_local],
                "evidence_hub": [{"time": h["time"], "sender": h["sender"], "text": h["text"][:80]} for h in ev_hub],
            }
            lines.append((s.get("severity"), no, s.get("title"), verdict, conf, note, ev_local, ev_hub))

        payload = {
            "reviewed_at": None,
            "_source": "suggest_verdicts.py @ %s" % datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
            "method": "本地交付物扫描（项目资料/工具/产物/日报）+ 数据仓群消息关键词检索；仅出候选，未人工确认",
            "verdicts": verdicts,
            "_suggestions": suggestions,
            "dismiss_kinds": [],
            "_pending_review": True,
        }
        sp = os.path.join(out, "verdicts-%s-%s.suggested.json" % (p, date))
        with open(sp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=1)

        # 人看的清单
        lines.sort(key=lambda x: ({"P0": 0, "P1": 1, "P2": 2}.get(x[0], 3), x[1]))
        md = ["# 判读候选 · %s · %s" % (p, date), "",
              "> 由 suggest_verdicts.py 生成；**确认后**把 `verdicts-%s-%s.suggested.json` 改名为 "
              "`verdicts-%s-%s.json`，再跑 apply_verdicts.py 合并。" % (p, date, p, date), "",
              "| 级别 | 编号 | 任务 | 候选判读 | 置信 | 依据 |", "|---|---|---|---|---|---|"]
        for sev, no, title, v, conf, note, evl, evh in lines:
            if conf == "—":
                ev = "（规则型判定，无需证据）"
            else:
                ev = ("本地: " + "、".join(x[1] for x in evl[:2]) if evl else "本地: 无") + \
                     ("；群: " + evh[0]["text"][:40] if evh else "")
            md.append("| %s | %s | %s | %s | %s | %s |" % (sev or "", no, (title or "")[:26], v, conf, ev))
        md += ["", "## 逐条明细", ""]
        for sev, no, title, v, conf, note, evl, evh in lines:
            md.append("- [ ] **%s %s** %s → `%s`（置信 %s）" % (sev, no, title, v, conf))
            md.append("  - " + note)
            for i, (sc, rel, kw, *rest) in enumerate([] if conf == "—" else evl[:3]):
                cls = evl[i][3] if len(evl[i]) > 3 else ""
                md.append("  - 本地证据：`%s`（%s 得分 %s，命中「%s」）" % (rel, cls, sc, kw))
            for h in evh[:2]:
                md.append("  - 群证据：%s %s：%s" % (h["time"], h["sender"], h["text"][:70]))
        with open(os.path.join(out, "判读候选-%s-%s.md" % (p, date)), "w", encoding="utf-8") as f:
            f.write("\n".join(md) + "\n")

        print("● %s：%d 条待判读 → 候选 %d 条" % (p, len(sigs), len(verdicts)))
        by_conf = {}
        for v in suggestions.values():
            by_conf[v["confidence"]] = by_conf.get(v["confidence"], 0) + 1
        print("   置信分布 %s ｜ 清单：%s" % (by_conf or "{}", os.path.join(out, "判读候选-%s-%s.md" % (p, date))))

        if a.promote:
            dst = os.path.join(out, "verdicts-%s-%s.json" % (p, date))
            if os.path.exists(dst):
                shutil.copy2(dst, dst + ".bak")
            payload["_pending_review"] = False
            payload["reviewed_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
            with open(dst, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=1)
            print("   ⚠ 已 --promote 覆盖 %s（旧文件备份为 .bak）" % dst)

    if not a.promote:
        print("\n下一步：改 判读候选-*.md 或直接编辑 .suggested.json → 去掉 .suggested → "
              "python3 apply_verdicts.py --project <项目> --date %s" % date)
    return rc


if __name__ == "__main__":
    sys.exit(main())
