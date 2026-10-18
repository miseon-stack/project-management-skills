#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""比对层：线上实施表 × 数据源 → 差异清单 / 预警 / 决策建议。

用法：
  python3 analyze.py --project 客户B                     # 自动找当天的 raw
  python3 analyze.py --project 客户B --raw raw-客户B-2026-09-17.json
  python3 analyze.py --project all --stale-days 3

输入：collect.py 产出的 raw-*.json（没有也能跑，只是少「数据源侧」的信号）
输出：
  <scratch>/findings-<项目>-<YYYY-MM-DD>.json
  <scratch>/巡检报告-<项目>-<YYYY-MM-DD>.md
"""
import argparse
import datetime
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

STOP = set("的了和与及在是为对从到把被这那关于按照进行情况问题以及一个我们客户项目任务需求方案"
           "工作支持确认完成已经可以直接需要配合提供相关进行当前后续下一步".split())

DONE_KW = ["已完成", "完成了", "已交付", "交付了", "已上线", "上线了", "跑通", "跑通了",
           "已经可以", "没问题了", "验证通过", "通过测试", "初步测试通过", "已经好了", "搞定了",
           "已确认", "已经部署", "可以使用", "已解决", "已恢复"]
ASK_KW = ["需要", "要求", "希望", "麻烦", "请", "建议", "预计", "约定", "决定", "确认一下",
          "推进", "安排一下", "什么时候", "还不", "没有", "待确认", "卡在", "阻塞", "暂停"]
WARN_KW = ["投诉", "不满意", "不信任", "拒收", "催", "逾期", "延期", "风险", "投诉", "事故"]

# 客户「要新东西」的词（区别于 ASK_KW 的泛化请求）—— 命中即视为新增需求候选
REQ_KW = ["新增", "再加", "加一个", "加个", "增加", "补充一个", "补一个", "也要能", "能不能",
          "希望可以", "想要", "需要一个", "诉求", "需求", "要不要考虑", "顺便", "另外还",
          "能否支持", "可以支持吗", "有没有办法"]

# ★ 状态差异规则：群内「实际情况」→ 表内应有的状态。
#   key       内部分类
#   label     卡片上的中文标签
#   kws       命中即认为群内在描述这种实况
#   expect    表内若**不是**这些状态之一 → 报差异
#   sev       差异级别
STATUS_RULES = [
    dict(key="done", label="已完成/已上线", sev="P1",
         kws=["已完成", "完成了", "已交付", "交付了", "已上线", "上线了", "已发布",
              "跑通", "跑通了", "验证通过", "通过测试", "已经好了", "搞定了",
              "已经可以", "可以使用", "已解决", "已恢复", "部署完成", "已完成配置"],
         expect=["已完成", "完成"]),
    dict(key="doing", label="已启动/进行中", sev="P1",
         kws=["已启动", "启动了", "已开始", "开始了", "开始推进", "开始对接", "已在做",
              "正在对接", "正在推进", "正在调试", "在调试", "试运行", "试用中",
              "开始试用", "进入测试", "开始测试", "已经用起来"],
         expect=["进行中", "已完成", "完成"]),
    dict(key="enabled", label="已启用/已开通", sev="P1",
         kws=["已开通", "开通了", "已启用", "启用成功", "权限已给", "已授权",
              "配置完成", "已配置好", "已发布上线"],
         expect=["已完成", "完成", "进行中"]),
    dict(key="blocked", label="阻塞/卡住", sev="P0",
         kws=["卡住", "卡在", "阻塞", "暂停", "等客户", "等确认", "待客户", "推进不了",
              "没有响应", "一直没回", "被卡", "无法推进", "搁置"],
         expect=["阻塞", "待确认", "已取消"]),
]
STATUS_KW_ALL = {k for r in STATUS_RULES for k in r["kws"]}
# 命中即排除：这些是内部商务/成本口径的讨论，不是客户现场需求
REQ_STOP = ["收费", "报价", "人天", "合同", "付款", "成本", "赚", "钱", "预算", "发票", "请款"]

# ★ 新增需求的 AI 归类规则（卡片上不堆原话，按类聚合）
#   顺序即优先级：一条诉求可能同时含「审批流」和「集成」，归到更靠前的类。
REQ_CATS = [
    ("系统集成", ["集成", "对接", "erp", "crm", "api", "同步", "打通", "接口", "对接好",
                  "oa", "teambition", "钉钉数据", "数据迁移", "导入导出"]),
    ("流程能力", ["流程", "审批", "权限", "节点", "工单", "流转", "签到", "打卡规则"]),
    ("协作事项", ["培训", "文档", "会议", "内测", "试用", "账号", "席位", "开通",
                  "确认", "名单", "权限申请", "资料"]),
    ("产品能力", ["记忆", "机器人", "ai", "智能", "微信", "转发", "消息", "功能", "优化",
                  "知识", "问答", "语音", "视频", "播报", "语音转", "识别", "回复", "话术"]),
]


def categorize_req(text):
    """把一条新增诉求归到 产品能力 / 流程能力 / 系统集成 / 协作事项 之一。"""
    t = (text or "").lower()
    for cat, kws in REQ_CATS:
        if any(k in t for k in kws):
            return cat
    return "产品能力"          # 兜底：客户提的大多数新东西都是产品侧诉求


MILESTONE_KW = ["启动会", "上线", "验收", "发布", "评审", "交付", "演示", "培训", "切换"]


def load_team():
    p = os.path.join(SKILL_DIR, "references", "team.json")
    d = json.load(open(p, encoding="utf-8"))
    return set(d.get("our_team", [])), d.get("auto_footer", [])


def bigrams(text):
    """抽中文 2-gram 关键词（粗粒度，够用）。"""
    s = re.sub(r"[\s\W_]+", "", text or "")
    s = re.sub(r"[\u4e00-\u9fff]{0,1}[A-Za-z0-9./-]+", "", s)
    out = set()
    for i in range(len(s) - 1):
        g = s[i:i + 2]
        if g in STOP or any(c in STOP for c in g):
            continue
        out.add(g)
    # 补上英文/数字专有名词
    for w in re.findall(r"[A-Za-z][A-Za-z0-9]{2,}", text or ""):
        out.add(w.lower())
    return out


MIN_START = re.compile(r"开始时间:\s*(\d{4})\.(\d{2})\.(\d{2})\s+(\d{2}:\d{2})")


def _minutes_brief(raw):
    """把 raw 的妙记压成报告用简报：时间 / 标题 / 原文链接 / 摘要要点 / 待办数。"""
    out = []
    for m in raw.get("minutes", []):
        hit = MIN_START.search(m.get("desc") or "")
        when = f"{hit.group(1)}-{hit.group(2)}-{hit.group(3)} {hit.group(4)}" if hit else ""
        lines = []
        for line in (m.get("summary") or "").split("\n"):
            line = line.replace("**", "").strip(" #*-•\t")
            if len(line) >= 10:
                lines.append(line[:140])
            if len(lines) >= 6:
                break
        out.append({"time": when, "title": m.get("title"), "url": m.get("url") or "",
                    "todos": len(m.get("todo") or []), "highlights": lines})
    out.sort(key=lambda x: x["time"], reverse=True)
    return out


def sentences(raw):
    """把 raw 里的消息、文档正文、会议妙记拆成「句子」列表，带来源。"""
    out = []
    for m in raw.get("messages_flat", []):
        if len(m.get("text", "")) >= 6:
            out.append({"time": m["time"], "sender": m["sender"], "src": "群消息",
                        "sender_id": m.get("sender_id"), "chat": m.get("chat", ""), "text": m["text"]})
    for d in raw.get("docs", []):
        title = d.get("title") or ""
        body = re.sub(r"\n{2,}", "\n", d.get("content") or "")
        for line in body.split("\n"):
            line = line.strip(" #*-•\t")
            if len(line) >= 8:
                out.append({"time": d.get("generated_at", ""), "sender": title, "src": "文档",
                            "chat": title, "text": line[:400]})
    # 会议妙记：一场会的结论/分工/待办往往**不在群里**，缺了这条通道会整场丢失
    for m in raw.get("minutes", []):
        title = m.get("title") or ""
        hit = MIN_START.search(m.get("desc") or "")
        when = f"{hit.group(1)}-{hit.group(2)}-{hit.group(3)} {hit.group(4)}" if hit else ""
        body = re.sub(r"\n{2,}", "\n", m.get("summary") or "")
        for line in body.split("\n"):
            line = line.replace("**", "").strip(" #*-•\t")
            if len(line) >= 8:
                out.append({"time": when, "sender": title, "src": "妙记",
                            "chat": title, "text": line[:400]})
        for t in (m.get("todo") or []):
            c = (t.get("content") or "").strip()
            if len(c) >= 6:
                out.append({"time": when, "sender": title, "src": "妙记·待办", "chat": title,
                            "text": c[:400], "todo_done": bool(t.get("is_done"))})
    return out


def schema_check(proj):
    """结构漂移检测：配置里登记的字段名在线上是否还存在。

    共享表随时可能被客户/同事改名、改类型、删字段。字段名对不上必须**显式报警**，
    否则脚本会静默读到空值，产出一份看起来正常其实全错的报告。
    """
    res = C.lark(["base", "+field-list", "--base-token", proj["base_token"],
                  "--table-id", proj["table_id"], "--format", "json", "--as", "user"])
    fields = ((res.get("data") or {}).get("fields")) or []
    names = [f.get("name") for f in fields]
    ids = {f.get("name"): f.get("id") for f in fields}
    missing = [f"{k}={v}" for k, v in proj["fields"].items() if v and v not in names]
    known = {v for v in proj["fields"].values() if v}
    extra = [n for n in names if n not in known]
    drift_ids = []
    for nm, fid in (proj.get("field_ids") or {}).items():
        if nm in ids and ids[nm] != fid:
            drift_ids.append(f"{nm}: 期望 {fid} → 实际 {ids[nm]}")
    return names, ids, missing, extra, drift_ids


def analyze_one(cfg, key, raw_path, stale_days):
    proj = C.project_cfg(cfg, key)
    f = proj["fields"]
    today = C.today()
    names, fids, missing, extra, drift_ids = schema_check(proj)
    recs, meta = C.fetch_records(cfg, proj, f"cur-{key}.ndjson")
    if not meta.get("ok"):
        return None, f"拉取记录失败：{meta}"

    raw = {}
    if raw_path and os.path.exists(raw_path):
        raw = json.load(open(raw_path, encoding="utf-8"))
    lines = sentences(raw)
    corpus = "\n".join(l["text"] for l in lines)
    our_team, _ = load_team()
    people = C.load_people(cfg)          # open_id → 显示名（含 sender_aliases 兜底）
    name2id = C.name_to_id(cfg)          # 显示名 → open_id（文本负责人字段回退用）

    signals = []
    index = []   # 供「缺录」判断用

    if missing:
        signals.append(dict(kind="schema_drift", severity="P0", no="—", record_id="—",
                            title="表结构已变更，配置对不上",
                            title_desc="配置登记但线上已找不到的字段：" + "、".join(missing),
                            evidence=["线上现有字段：" + "、".join(names)],
                            suggestion="立刻核对是改名/改类型还是被删；先把 projects.json 的 fields 对齐线上，"
                                       "再重跑本脚本 —— 否则字段错位会产出「看起来正常其实全错」的报告。"))
    if extra:
        signals.append(dict(kind="schema_new_fields", severity="P2", no="—", record_id="—",
                            title="出现配置外的新字段",
                            title_desc="未登记字段：" + "、".join(extra),
                            suggestion="判断是否为他人新增（人员/审批/自动化字段很常见）；只记录，不影响比对。"))
    if drift_ids:
        signals.append(dict(kind="schema_drift", severity="P1", no="—", record_id="—",
                            title="字段被删除重建（field_id 变了）",
                            title_desc="；".join(drift_ids),
                            evidence=["字段名一样但底层 id 变了，说明原字段被删、重建了同名字段；"
                                      "历史记录、自动化、公式引用可能已断裂。"],
                            suggestion="核对是否有自动化/仪表盘引用了旧字段；确认编号类字段是否被重排"
                                       "（客户B 2026-09-17 实例：任务编号被重建，编号从 T64–T110 变成 T01–T42）。"))

    # ---- ★ 子项目层级（2026-09-17 客户B起用「父记录」管理子项目）
    # 有子记录的行 = 子项目汇总行：不参与逐任务信号（否则"进展空缺/状态差异"全是噪声），
    # 单独聚合成 subprojects（卡片展示 rollup 完成度）。
    # 兼容两种 cell 格式：[{"id": "recX"}]（CLI 存储）与 [{"record_ids": ["recX"]}]（原生 API）。
    rid_map = {r.get("record_id"): r for r in recs}
    child_of = {}
    for r in recs:
        cell = r.get("父记录") or []
        if isinstance(cell, list) and cell and isinstance(cell[0], dict):
            pid = cell[0].get("id") or (cell[0].get("record_ids") or [None])[0]
            if pid and pid in rid_map:
                child_of[r.get("record_id")] = pid
    parent_rids = set(child_of.values())
    children_by_parent = {}
    for c_rid, p_rid in child_of.items():
        children_by_parent.setdefault(p_rid, []).append(c_rid)

    for r in recs:
        rid = r.get("record_id")
        no = C.flat(r.get(f["id"]))
        title = C.flat(r.get(f["title"])) or C.flat(r.get("飞书方任务")) or no
        # 标题列被写成「T58」这种编号文本时（字段重建的常见后遗症），退回用任务描述
        if re.fullmatch(r"T\d+", title or ""):
            title = C.flat(r.get("飞书方任务")) or title
        status = C.flat(r.get(f["status"]))
        progress = C.flat(r.get(f["progress"]))
        due_raw = r.get(f["due"])
        due = C.parse_ts(due_raw)
        due_d = due.date() if due else None
        done = C.status_is_done(proj, status)
        tokens = bigrams(title)
        index.append({"record_id": rid, "no": no, "title": title, "tokens": tokens})

        # 子项目汇总行：只进 index（供缺录/新增需求匹配），不产信号
        if rid in parent_rids:
            continue

        # ---- 1 逾期 / 临期
        if due_d:
            delta = (due_d - today).days
            if not done and delta < 0:
                sev = "P0" if -delta >= 3 else "P1"
                signals.append(dict(kind="overdue", severity=sev, no=no, record_id=rid,
                                    title=title,
                                    title_desc=f"计划完成 {due_d} 已过 {-delta} 天，状态仍「{status}」",
                                    suggestion="核实真实进度：已完成则改状态，未完成则据实顺延并说明原因；"
                                               "若卡在客户侧，同步催办并给出我方可控的下一步。"))
            elif not done and 0 <= delta <= 3:
                signals.append(dict(kind="due_soon", severity="P1", no=no, record_id=rid,
                                    title=title,
                                    title_desc=f"计划完成 {due_d}（剩 {delta} 天），状态仍「{status}」",
                                    suggestion="今日确认能否按期收口；不能则提前改期，别等逾期。"))

        # ---- 2 阻塞 / 待确认
        if C.status_is_blocked(proj, status):
            signals.append(dict(kind="blocked", severity="P0", no=no, record_id=rid,
                                title=title,
                                title_desc=f"状态「{status}」",
                                suggestion="阻塞项必须给出「解铃人 + 动作 + 期限」，否则会烂在表里；"
                                           "对外沟通改成请求式（明确请客户做什么、何时要）。"))

        # ---- 3 进展空缺
        # 只有「进行中」却写不出进展才是真问题；「未开始」的任务进展为空是正常的，
        # 报成 P1 会稀释卡片（客户A 2026-09-17 实例：12 条 P1 里 9 条是未开始）。
        if not progress:
            st = C.flat(r.get(f["status"])) or ""
            sev = "P1" if (not done and "进行中" in st) else "P2"
            signals.append(dict(kind="no_progress", severity=sev, no=no, record_id=rid,
                                title=title, status=st,
                                title_desc="最新进展为空",
                                suggestion="补一句「日期 + 事实 + 下一步」；确实没启动的写清依赖谁。"))

        # ---- 4 状态差异：群内实况（完成/进行/启动/启用/阻塞）× 表内状态
        # 这是「表与真实进度脱节」的核心检测 —— 只要群里有人说了某件事的实况，
        # 而表内状态不是那个状态，就报一条差异。四种实况全查，不只查「已完成」。
        #
        # 两条精度约束（都是实测踩出来的）：
        # ① **只看群消息，不看文档** —— 方案/交接清单里的「待客户确认」会被反复引用，
        #    造成「文档自证式误报」（客户A T57/T67 实例）。
        # ② 重合阈值提到 3 个 2-gram —— 2 个太松，「全员功能使用培训」会命中
        #    「云打印功能的客户B使用」这种风马牛不相及的消息。
        msg_lines = [l for l in lines if l["src"] == "群消息"]
        if tokens and msg_lines:
            for rule in STATUS_RULES:
                if any(e in status for e in rule["expect"]):
                    continue                      # 表内已是应有状态 → 无差异
                hits = []
                for l in msg_lines:
                    t = l["text"]
                    if not any(k in t for k in rule["kws"]):
                        continue
                    ov = len(tokens & bigrams(t))
                    if ov >= max(3, int(len(tokens) * 0.4)):
                        hits.append((ov, l))
                if not hits:
                    continue
                hits.sort(key=lambda x: (x[0], x[1]["time"]), reverse=True)
                l = hits[0][1]
                kind = "completion_candidate" if rule["key"] == "done" else "status_delta"
                # 反向差异（表内已「已完成」却被群里说卡住/暂停）降级为 P1，避免 P0 噪声
                sev = "P1" if done else rule["sev"]
                sig = dict(kind=kind, severity=sev, no=no, record_id=rid, title=title,
                           title_desc=f"群内已「{rule['label']}」，表内仍「{status}」",
                           actual=rule["label"], table_status=status, actual_key=rule["key"],
                           evidence=[f"{l['time']} {l['sender']}（{l['src']}）：{l['text'][:180]}"],
                           suggestion="核实该条真实状态并回写；不确定就只在备注留痕，别硬改。")
                if done:
                    sig["title_desc"] = f"表内已「{status}」，群内仍见「{rule['label']}」迹象（建议复核）"
                    sig["reverse"] = True
                signals.append(sig)

        # ---- 5 表体本身是否陈旧
    upd_dates = []
    if f.get("updated"):
        for r in recs:
            t = C.parse_ts(r.get(f["updated"]))
            if t:
                upd_dates.append(t.date())
    else:
        for r in recs:
            d = C.latest_date_in_text(C.flat(r.get(f["progress"])))
            if d:
                upd_dates.append(d)
    last_table = max(upd_dates) if upd_dates else None
    table_age = (today - last_table).days if last_table else None
    if table_age is not None and table_age >= stale_days:
        signals.append(dict(kind="stale_table", severity="P0", no="—", record_id="—",
                            title="整张实施表已停更",
                            title_desc=f"表内最新时点 {last_table}，距今 {table_age} 天",
                            suggestion="先跑一轮差异回写（配合 skill feishu-project-table-sync），"
                                       "再谈别的；表停更 = 客户看到的是一张假表。"))

    # ---- 6 数据源里的事项在表中找不到（缺录候选）
    missing = []
    for l in lines:
        t = l["text"]
        if len(t) < 10 or t.startswith("["):
            continue
        if not any(k in t for k in ASK_KW):
            continue
        tb = bigrams(t)
        best, best_ov = None, 0
        for it in index:
            ov = len(it["tokens"] & tb)
            if ov > best_ov:
                best, best_ov = it, ov
        if best and best_ov >= 2:
            continue
        missing.append({"time": l["time"], "sender": l["sender"], "src": l["src"], "text": t[:220]})

    # ---- 6b ★ 客户新增需求：群内客户方提出、表内无对应条目
    # 与「缺录候选」的区别：缺录 = 提到但没进表；新增需求 = 明确在**要新东西**。
    # 后者必须单独提示 —— 漏掉一条客户需求 = 事后返工。
    #
    # 只看客户方发的群消息：我方自己人在群里讨论「要不要做/怎么收费」不是客户需求，
    # 文档正文（方案里的「增加XX能力」）也不是客户现场诉求。
    reqs = []
    for l in lines:
        if l["src"] != "群消息":
            continue
        t = (l["text"] or "").strip()
        if not (8 <= len(t) <= 160) or t.startswith("["):
            continue
        if not any(k in t for k in REQ_KW):
            continue
        if any(k in t for k in REQ_STOP):          # 内部商务/成本讨论，不进对外清单
            continue
        if (l.get("sender") or "") in our_team:    # 我方自己人的讨论不算客户需求
            continue
        tb = bigrams(t)
        if max((len(it["tokens"] & tb) for it in index), default=0) >= 3:
            continue                               # 已有对应任务，不是新增
        sid = l.get("sender_id") or ""
        nm = people.get(sid) or l.get("sender") or ""
        reqs.append({"time": l["time"], "sender": nm, "sender_id": sid, "src": l["src"],
                     "text": t[:220], "client": True})
    # 同一条需求可能被多人转述，按正文前 16 字去重
    seen_r, uniq = set(), []
    for r in reqs:
        k = re.sub(r"\s+", "", r["text"])[:16]
        if k in seen_r:
            continue
        seen_r.add(k)
        uniq.append(r)
    reqs = uniq[:8]
    # 去重（同一条消息只留最长）
    seen, dedup = set(), []
    for m in sorted(missing, key=lambda x: len(x["text"]), reverse=True):
        k = m["text"][:24]
        if k in seen:
            continue
        seen.add(k)
        dedup.append(m)
    missing = dedup[:25]

    # ---- 7 客户方沉默 / 预警词
    client_msgs = [l for l in lines if l["src"] == "群消息" and l["sender"] not in our_team]
    client_silence = None
    if client_msgs:
        last_c = max(client_msgs, key=lambda x: x["time"])
        try:
            d = datetime.datetime.strptime(last_c["time"], "%Y-%m-%d %H:%M").date()
            sn = last_c["sender"] or ""
            sid = last_c.get("sender_id") or ""
            # 显示名统一在分析的最后一刻反查：sender_aliases 补登后无需重跑 collect
            if sid and sid in people:
                sn = people[sid]
            elif sn.startswith("ou_") or sn.startswith("外部成员"):
                sn = "外部成员(" + (sid or sn)[-6:] + ")　← 未建档，可登记到 projects.json 的 sender_aliases"
            client_silence = {"last": last_c["time"], "sender": sn or "（无发送人）",
                              "sender_id": sid,
                              "days": (today - d).days, "text": last_c["text"][:200]}
        except Exception:
            pass
    warn_lines = [l for l in lines if any(k in l["text"] for k in WARN_KW)][:12]

    # ---- 8 待办/决策候选（妙记结构化待办 + 文档列表 + 群消息关键词）
    todos = []
    for l in lines:
        t = l["text"]
        if l["src"] == "妙记·待办":
            # 妙记 AI 待办是**结构化**产出（带负责人、带完成态），比从文本里猜的准，优先收
            if not l.get("todo_done"):
                todos.append(l)
        elif "内容如下" in t or "内容摘要" in t:
            continue  # 摘要导语，不是待办
        elif l["src"] == "文档" and re.match(r"^(\d+[.、)]|\-|【)", t):
            todos.append(l)
        elif any(k in t for k in ("待办", "下一步", "行动项", "需要客户", "请客户", "约定")):
            todos.append(l)
    todos.sort(key=lambda x: x["time"], reverse=True)
    todos.sort(key=lambda x: x["src"] != "妙记·待办")  # 稳定排序 → 妙记待办整体提前
    todos = todos[:20]

    # ---- 9 把负责人补进每条信号（卡片要 @ 到人，必须有 open_id）
    owner_field = f.get("owner")
    owner_by_rid, owners_by_rid = {}, {}
    for r in recs:
        rid = r.get("record_id")
        ps = C.people(r.get(owner_field)) if owner_field else []
        if not ps:
            txt = C.flat(r.get(owner_field or ""))
            ps = [{"id": name2id.get(n.strip(), ""), "name": n.strip()}
                  for n in re.split(r"[,，、/]\s*", txt) if n.strip()]
        owners_by_rid[rid] = ps
        owner_by_rid[rid] = "、".join(p["name"] for p in ps if p["name"])
    # 客户方负责人一并带上（客户A/客户B分属两个字段，卡片上要能同时点到来人）
    cowner_field = f.get("client_owner")
    if cowner_field:
        for r in recs:
            rid = r.get("record_id")
            ps = C.people(r.get(cowner_field))
            if ps:
                owners_by_rid.setdefault(rid, [])
                have = {p["id"] for p in owners_by_rid[rid]}
                owners_by_rid[rid] += [p for p in ps if p["id"] not in have]
                names = [p["name"] for p in owners_by_rid[rid] if p["name"]]
                owner_by_rid[rid] = "、".join(names)
    for s_ in signals:
        rid = s_.get("record_id") or ""
        if not s_.get("owners"):
            s_["owners"] = owners_by_rid.get(rid, [])
        if not s_.get("owner"):
            s_["owner"] = owner_by_rid.get(rid, "")

    # ---- 9b 客户新增需求 → 每条独立信号（漏一条 = 事后返工）
    for rq in reqs[:12]:
        if not rq["client"] and not any(k in rq["text"] for k in REQ_KW):
            continue
        signals.append(dict(kind="new_requirement",
                            severity="P1" if rq["client"] else "P2",
                            no="—", record_id="—",
                            title=(rq["sender"] or "群内") + " 提出的新增诉求",
                            title_desc=rq["text"][:110],
                            actual="新增需求", table_status="表内无对应任务",
                            owners=[{"id": rq.get("sender_id") or "", "name": rq["sender"] or ""}],
                            owner=rq["sender"] or "",
                            time=rq["time"], client=rq["client"],
                            evidence=[f"{rq['time']} {rq['sender']}（{rq['src']}）：{rq['text'][:180]}"],
                            suggestion="先与客户对齐范围与优先级，再决定是否建条目；不要默默接下。"))

    # ---- 10「AI 判断」（规则化聚合，事实来自表内 + 群内）
    conclusion = build_conclusion(
        {"records": len(recs),
         "last_update_in_table": last_table.isoformat() if last_table else None,
         "table_age_days": table_age},
        signals, client_silence, missing, our_team)
    req_sum = build_req_summary(reqs)
    key_nodes = build_key_nodes(recs, f, signals, today)

    # ---- 子项目 rollup：每个父行聚合子任务完成度（卡片「📦 子项目进度」的数据源）
    subprojects = []
    for p_rid, c_rids in children_by_parent.items():
        pr = rid_map.get(p_rid) or {}
        p_no = C.flat(pr.get(f["id"]))
        p_title = C.flat(pr.get(f["title"])) or C.flat(pr.get("飞书方任务")) or p_no
        if re.fullmatch(r"T\d+", p_title or ""):
            p_title = C.flat(pr.get("飞书方任务")) or p_title
        done_n = doing_n = blocked_n = 0
        kids = []
        for c_rid in c_rids:
            cr = rid_map.get(c_rid) or {}
            c_no = C.flat(cr.get(f["id"]))
            c_title = C.flat(cr.get(f["title"])) or C.flat(cr.get("飞书方任务")) or c_no
            if re.fullmatch(r"T\d+", c_title or ""):
                c_title = C.flat(cr.get("飞书方任务")) or c_title
            c_status = C.flat(cr.get(f["status"]))
            if C.status_is_done(proj, c_status):
                done_n += 1
            elif C.status_is_blocked(proj, c_status):
                blocked_n += 1
            elif "进行中" in c_status:
                doing_n += 1
            kids.append({"no": c_no, "title": c_title, "status": c_status})
        total = len(kids)
        subprojects.append({
            "no": p_no, "title": p_title, "status": C.flat(pr.get(f["status"])),
            "total": total, "done": done_n, "doing": doing_n, "blocked": blocked_n,
            "pct": round(done_n / total * 100) if total else 0,
            "children": sorted(kids, key=lambda x: x.get("no") or ""),
        })
    subprojects.sort(key=lambda x: (x.get("no") or ""))

    findings = {
        "project": key, "label": proj["label"], "as_of": today.isoformat(),
        "generated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "table": {
            "base_token": proj["base_token"], "table_id": proj["table_id"], "url": proj["url"],
            "records": len(recs),
            "status_dist": _dist(recs, f["status"]),
            "last_update_in_table": last_table.isoformat() if last_table else None,
            "table_age_days": table_age,
        },
        "sources": {
            "raw": os.path.basename(raw_path) if raw_path and os.path.exists(raw_path or "") else None,
            "messages": len(raw.get("messages_flat", [])),
            "docs": len(raw.get("docs", [])),
            "minutes": len(raw.get("minutes", [])),
            "window": raw.get("window"),
        },
        "signals": sorted(signals, key=lambda s: ({"P0": 0, "P1": 1, "P2": 2}[s["severity"]], s["kind"])),
        "subprojects": subprojects,
        "conclusion": conclusion,
        "focus": build_focus(signals, reqs, req_sum),
        "key_nodes": key_nodes,
        "req_summary": req_sum,
        "missing_candidates": missing,
        "new_requirements": reqs,
        "client_silence": client_silence,
        "risk_words": [f"{l['time']} {l['sender']}：{l['text'][:160]}" for l in warn_lines],
        "todo_candidates": [f"{l['time']} {l['sender']}（{l['src']}）：{l['text'][:200]}" for l in todos],
        "minutes": _minutes_brief(raw),
    }
    return findings, None


def _ago_txt(days):
    if days is None:
        return ""
    if days <= 0:
        return "今天"
    if days == 1:
        return "昨天"
    return f"{days} 天前"


def build_conclusion(table, signals, client_silence, missing, our_team=None):
    """「AI 判断」：把 P0/P1 的构成、归属、表与群的一致性聚合成人话结论 + 建议动作。

    原则：只陈述**表内事实与群内事实**的交叉结果，不做无证据的推断；不出现商务/内部人事措辞。
    """
    p0 = [s for s in signals if s["severity"] == "P0"]
    p1 = [s for s in signals if s["severity"] == "P1"]
    out = {"headline": "", "points": [], "actions": []}
    total = table.get("records") or 0

    if not p0:
        out["headline"] = f"线上 {total} 条暂无必须立即处理的事项，表内状态与近期群内进展基本一致。"
        if p1:
            out["points"].append(f"仍有 {len(p1)} 项待跟进（见下方分类）。")
        return out

    kind_c = {}
    for s in p0:
        kind_c[s["kind"]] = kind_c.get(s["kind"], 0) + 1
    own = {}
    for s in p0:
        raw = (s.get("owner") or "").strip()
        names = [x.strip() for x in re.split(r"[,，、/]\s*", raw) if x.strip()] or ["未填负责人"]
        for nm in set(names):
            own[nm] = own.get(nm, 0) + 1
    own_sorted = sorted(own.items(), key=lambda x: (-x[1], x[0]))

    parts = []
    for k, v in sorted(kind_c.items(), key=lambda x: -x[1]):
        parts.append(f"{KIND_LABEL.get(k, k)} {v} 项")
    pct = round(len(p0) / total * 100) if total else 0
    out["headline"] = f"P0 共 {len(p0)} 项（占线上 {pct}%）：" + "、".join(parts) + "。"

    our_team = our_team or set()

    def _tag(n):
        if n == "未填负责人":
            return n
        return f"{n}（我方）" if n in our_team else f"{n}（客户方）"

    top = own_sorted[:4]
    line = "归属集中：" + " · ".join(f"{_tag(n)} {c} 项" for n, c in top)
    if len(own_sorted) > 4:
        line += f"，另 {len(own_sorted) - 4} 人/组各 1 项"
    out["points"].append(line)

    age = table.get("table_age_days")
    if age and age >= 2:
        out["points"].append(f"表内最新时点 {table.get('last_update_in_table') or '—'}，已 {age} 天无更新 —— "
                             "群里有动作但没回写，看板与实际进度已脱节。")
    cs = client_silence or {}
    if cs.get("last") and cs.get("days") is not None:
        who = re.sub(r"（[^）]*）|（[^）]*$", "", cs.get("sender") or "").strip() or "客户侧"
        if cs["days"] <= 1:
            out["points"].append(f"客户侧{_ago_txt(cs['days'])}仍有发言（{who}），沟通面没冷，"
                                 "适合顺势把未闭环项摊开对齐。")
        else:
            out["points"].append(f"客户侧已 {cs['days']} 天未发言（最后 {cs['last']} · {who}），建议主动同步一条进展。")
    cand = [s for s in p1 if s["kind"] == "completion_candidate"]
    deltas = [s for s in p1 if s["kind"] == "status_delta"]
    if cand:
        out["points"].append(f"另有 {len(cand)} 项在群里已见完成迹象、表内状态未回写，核实后可批量转「已完成」。")
    if deltas:
        byk = {}
        for s in deltas:
            byk[s.get("actual") or "其他"] = byk.get(s.get("actual") or "其他", 0) + 1
        out["points"].append("群内实况与表内状态不一致 "
                             + " · ".join(f"{k} {v}" for k, v in sorted(byk.items()))
                             + "，看板已与真实进度脱节。")
    nr = [s for s in signals if s["kind"] == "new_requirement"]
    if nr:
        who = []
        for s in nr:
            n = (s.get("title") or "").split(" 提出")[0]
            if n and n not in who:
                who.append(n)
        out["points"].append(f"群内新增诉求 {len(nr)} 条尚未进表（{('、'.join(who[:3]))}），"
                             "漏登记就是事后返工。")
    if missing:
        out["points"].append(f"群内提到、表内无对应记录的事项 {len(missing)} 条，需逐条裁定是否入表。")

    ov = kind_c.get("overdue", 0)
    if ov:
        out["actions"].append(f"把 {ov} 项逾期逐条过一遍：已完成的改「已完成」，未完成的据实改期并写一句原因（建议今天内完成）。")
    if len(own_sorted) <= 3:
        out["actions"].append("P0 集中在" + "、".join(_tag(n).replace("（客户方）", "").replace("（我方）", "") for n, _ in own_sorted)
                              + "，建议群里点对点确认，不要只发表格。")
    if cand:
        out["actions"].append(f"先核实那 {len(cand)} 项疑似已完成项并回写状态 —— 让看板先可信，再谈排期。")
    if deltas:
        out["actions"].append(f"按群内实况同步那 {len(deltas)} 项状态（启动/进行/启用/阻塞各自归档），"
                              "今天内完成回写。")
    if nr:
        out["actions"].append(f"把 {len(nr)} 条新增诉求过一遍：确认范围与优先级后决定是否立项，别默认接下。")
    return out


def _dist(recs, status_field):
    d = {}
    for r in recs:
        s = C.flat(r.get(status_field)) or "(空)"
        d[s] = d.get(s, 0) + 1
    return d


def build_focus(signals, reqs, req_sum=None):
    """「🎯 今天优先处理」的数据层：P0 逐条结构化 + 新增需求汇总项。

    每条 = {no, title, owners, meta, current, next}：
      meta    超期天数 / 计划日（一行时点）
      current 当前卡在哪（规则化生成，人工判读可在 verdicts 里覆盖成更准的表述）
      next    下一步动作（取 suggestion 第一句）
    """
    focus, seen = [], set()
    p0 = [s for s in signals if s["severity"] == "P0" and not s.get("dismissed")
          and s.get("no") not in (None, "—")]
    # 逾期排最前（超期天数多的在前），其余按严重度
    def _days(s):
        m = re.search(r"已过 (\d+) 天", s.get("title_desc") or "")
        return -int(m.group(1)) if m else 0
    for s in sorted(p0, key=_days):
        no = s["no"]
        if no in seen:
            continue
        seen.add(no)
        m = re.search(r"计划完成 (\d{4}-\d{2}-\d{2}) 已过 (\d+) 天", s.get("title_desc") or "")
        meta = (f"超期 **{m.group(2)}** 天 · 计划 {m.group(1)[5:]}" if m
                else (s.get("title_desc") or "")[:40])
        cur = (s.get("evidence") or [""])[0]
        cur = re.sub(r"^\S+ \S+（[^）]*）：", "", cur).strip()     # 剥掉 "时间 发送人（来源）："
        if not cur or len(cur) < 6:
            cur = s.get("title_desc") or ""
        nxt = re.split(r"[；。]", s.get("suggestion") or "")[0].strip()
        focus.append({"no": no, "title": s.get("title") or "", "owners": s.get("owners") or [],
                      "meta": meta, "current": cur[:80], "next": nxt[:60]})
    if reqs:
        rs = req_sum or build_req_summary(reqs)
        names = rs.get("names") or []
        focus.append({"no": "REQ", "title": "新增需求整理", "owners": [],
                      "meta": f"{len(reqs)} 条客户诉求尚未进入项目表",
                      "current": " / ".join(names[:5]) + ("等" if len(names) > 5 else ""),
                      "next": rs.get("action") or "今天确认范围、优先级及是否立项"})
    return focus[:5]


def _req_names(reqs, limit=6):
    """从诉求原话里提取「涉及点」短名：优先取命中的能力关键词（带 2 字前缀语境）。"""
    kws = sorted({k for _, ks in REQ_CATS for k in ks}, key=len, reverse=True)
    chatter = "，。、,；;！!？?（）()我你他这那的了个是就还请意思另外帮看下能否可要让给和与跟"
    out = []
    for r in reqs:
        t = r["text"]
        got = []
        for k in kws:
            i = t.find(k)
            if i < 0:
                continue
            s = i
            while s > 0 and i - s < 2 and t[s - 1] not in chatter and not t[s - 1].isascii():
                s -= 1
            name = t[s:i + len(k)]
            if name and name not in got:
                got.append(name)
        if got:
            for g in got:
                if g not in out:
                    out.append(g)
        else:
            # 无关键词命中：剥掉开头语气词取前 10 字
            core = re.sub(r"^(我|另外|还有|请问|请教一下|意思是|就是|这个|这)[，,]?", "", t)[:10]
            if core and core not in out:
                out.append(core)
    return out[:limit]


def build_key_nodes(recs, f, signals, today):
    """「📅 近期关键节点」：未来 3 天内到期的任务 + 里程碑类任务 + 实况差异预警。"""
    nodes = []
    seen = set()
    for r in recs:
        due = C.parse_ts(r.get(f.get("due")))
        no = C.flat(r.get(f.get("id")))
        title = C.flat(r.get(f.get("title"))) or no
        if re.fullmatch(r"T\d+", title or ""):
            title = C.flat(r.get("飞书方任务")) or title
        if not due or not no:
            continue
        delta = (due.date() - today).days
        if 0 <= delta <= 3 and no not in seen:
            seen.add(no)
            nodes.append({"date": due.strftime("%m-%d"), "label": f"{no} · {title[:18]}…" if len(title) > 18 else f"{no} · {title}",
                          "status": C.flat(r.get(f.get("status"))) or ""})
    # 里程碑类任务（启动会/上线/验收…）即使计划日较远也列出；**已过去的里程碑不列**
    for r in recs:
        no = C.flat(r.get(f.get("id")))
        title = C.flat(r.get(f.get("title"))) or ""
        if re.fullmatch(r"T\d+", title or ""):
            title = C.flat(r.get("飞书方任务")) or title
        if not no or no in seen:
            continue
        if not any(k in title for k in MILESTONE_KW):
            continue
        due = C.parse_ts(r.get(f.get("due")))
        if due and (due.date() - today).days >= 0:
            seen.add(no)
            nodes.append({"date": due.strftime("%m-%d"), "label": f"{no} · {title[:18]}…" if len(title) > 18 else f"{no} · {title}",
                          "status": C.flat(r.get(f.get("status"))) or ""})
    # 状态差异里带「会/培训/评审」等字眼的 → 实况与计划可能有出入，加 ⚠️
    for s in signals:
        if s.get("kind") != "status_delta" or s.get("dismissed"):
            continue
        if not any(k in (s.get("title") or "") for k in MILESTONE_KW):
            continue
        m = re.search(r"(\d{4}-\d{2}-\d{2})", (s.get("evidence") or [""])[0])
        seen.add(s.get("no"))
        nodes.append({"date": m.group(1)[5:] if m else "",
                      "label": f"{s.get('no')} · {s.get('title')}",
                      "warn": f"群内实况与表内计划存在差异（表内 {s.get('table_status')}），建议确认口径"})
    nodes.sort(key=lambda n: n["date"])
    return nodes[:6]


def build_req_summary(reqs):
    """客户新增诉求的归类汇总（卡片只展示这个，原话进报告）。"""
    cats = {}
    for r in reqs:
        cats[categorize_req(r["text"])] = cats.get(categorize_req(r["text"]), 0) + 1
    return {"count": len(reqs),
            "categories": cats,
            "names": _req_names(reqs),
            "status": "尚未发现对应项目任务" if reqs else "",
            "action": "今天确认范围、优先级及是否立项"}


SEV_ICON = {"P0": "🔴", "P1": "🟠", "P2": "🟡"}
KIND_LABEL = {
    "overdue": "逾期未闭环", "due_soon": "节点临近", "blocked": "阻塞/待确认",
    "no_progress": "进展空缺", "completion_candidate": "群里已见完成未回写",
    "status_delta": "实况与表内状态不符", "new_requirement": "客户新增需求",
    "stale_table": "整表停更", "schema_drift": "表结构漂移", "schema_new_fields": "新增字段",
}


def render_report(f):
    L = []
    a = L.append
    a(f"# {f['label']} · 进度巡检报告")
    a("")
    a(f"- 巡检时点：**{f['generated_at']}**（数据源窗口 {f['sources']['window']['since']} → {f['sources']['window']['until']}）")
    t = f["table"]
    a(f"- 线上表：**{t['records']} 条**（{t['url']}）")
    a(f"- 状态分布：{' / '.join(f'{k} {v}' for k, v in sorted(t['status_dist'].items(), key=lambda x: -x[1]))}")
    a(f"- 表内最新时点：**{t['last_update_in_table'] or '无法判定'}**"
      + (f"（已停更 **{t['table_age_days']} 天**）" if t.get("table_age_days") is not None and t["table_age_days"] >= 3 else ""))
    s = f["sources"]
    a(f"- 数据源：群消息 {s['messages']} 条 · 云文档 {s['docs']} 篇 · 会议妙记 {s.get('minutes', 0)} 场" + (f"（{s['raw']}）" if s["raw"] else "（⚠️ 未采集）"))
    if f["client_silence"]:
        cs = f["client_silence"]
        a(f"- 客户侧最后发言：{cs['last']} **{cs['sender']}**（距今 {cs['days']} 天）")
    a("")

    counts = {}
    for sg in f["signals"]:
        counts[sg["severity"]] = counts.get(sg["severity"], 0) + 1
    a("## 0. 概览")
    a("")
    a("| 级别 | 条数 |")
    a("|---|---|")
    for k in ("P0", "P1", "P2"):
        a(f"| {SEV_ICON[k]} {k} | {counts.get(k, 0)} |")
    a("")

    for sev in ("P0", "P1", "P2"):
        group = [s for s in f["signals"] if s["severity"] == sev]
        if not group:
            continue
        a(f"## {SEV_ICON[sev]} {sev}（{len(group)} 条）")
        a("")
        for sg in group:
            a(f"### [{KIND_LABEL.get(sg['kind'], sg['kind'])}] {sg['no']} {sg['title']}")
            a(f"- 差异：{sg['title_desc']}")
            if sg.get("owner"):
                a(f"- 负责人：{sg['owner']}")
            if sg.get("evidence"):
                for e in sg["evidence"]:
                    a(f"- 证据：{e}")
            a(f"- 建议：{sg['suggestion']}")
            a("")

    if f.get("new_requirements"):
        a("## 🆕 客户新增需求（表内暂无对应任务）")
        a("")
        for r in f["new_requirements"]:
            tag = "客户方" if r.get("client") else "我方"
            a(f"- `{r['time']}` **{r['sender']}**（{tag}·{r['src']}）：{r['text']}")
        a("")

    if f["missing_candidates"]:
        a("## 📥 表内可能缺录（需人工确认，不自动新建）")
        a("")
        for m in f["missing_candidates"]:
            a(f"- `{m['time']}` **{m['sender']}**（{m['src']}）：{m['text']}")
        a("")

    if f["risk_words"]:
        a("## ⚠️ 风险词命中（客户情绪 / 投诉 / 逾期）")
        a("")
        for w in f["risk_words"]:
            a(f"- {w}")
        a("")

    if f["todo_candidates"]:
        a("## ✅ 待办 / 决策候选（来自纪要与群消息）")
        a("")
        for w in f["todo_candidates"]:
            a(f"- {w}")
        a("")

    if f.get("minutes"):
        a("## 📋 会议纪要（本窗口妙记）")
        a("")
        a("> 会议结论与分工往往只在妙记里，群里未必有人转述 —— 以下是本窗口全部相关会议。")
        a("")
        for m in f["minutes"]:
            a(f"### {m['time']} · {m['title']}")
            a("")
            a(f"[妙记原文]({m['url']}) · 待办 {m['todos']} 条" if m["url"] else f"待办 {m['todos']} 条")
            a("")
            for h in m["highlights"]:
                a(f"- {h}")
            a("")

    a("---")
    a("")
    a("> 本报告为**只读产出**。任何回写线上表、发群消息的动作，都需单独向用户确认后再执行。")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--raw", default=None, help="raw json 文件名或绝对路径；默认自动找当天的")
    ap.add_argument("--stale-days", type=int, default=3, help="表停更多少天算 P0")
    ap.add_argument("--workspace", default=None)
    a = ap.parse_args()

    cfg = C.load_config(a.workspace)
    keys = list(cfg["projects"]) if a.project == "all" else [a.project]
    out = []
    for key in keys:
        raw_path = a.raw
        if not raw_path:
            cand = C.out_path(cfg, f"raw-{key}-{C.today().isoformat()}.json")
            raw_path = cand if os.path.exists(cand) else None
        elif not os.path.isabs(raw_path):
            raw_path = os.path.join(cfg["_scratch"], raw_path)
        findings, err = analyze_one(cfg, key, raw_path, a.stale_days)
        if err:
            out.append({"ok": False, "project": key, "error": err})
            continue
        fj = C.dump(C.out_path(cfg, f"findings-{key}-{C.today().isoformat()}.json"), findings)
        rp = C.out_path(cfg, f"巡检报告-{key}-{C.today().isoformat()}.md")
        open(rp, "w", encoding="utf-8").write(render_report(findings))
        out.append({"ok": True, "project": key, "findings": fj, "report": rp,
                    "signals": len(findings["signals"]),
                    "p0": sum(1 for s in findings["signals"] if s["severity"] == "P0"),
                    "p1": sum(1 for s in findings["signals"] if s["severity"] == "P1")})
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
