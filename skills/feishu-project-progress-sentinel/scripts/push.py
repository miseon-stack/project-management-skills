#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把巡检结果推成飞书消息卡片（自定义机器人 Webhook）。

默认 **dry-run**：只生成卡片 JSON 落到 `<scratch>/cards/`，不发送任何消息。
真正发送必须显式 `--send` —— 发消息是外部动作，需用户明确授权。

用法：
  push.py --project 客户B                        # dry-run，内部口径卡片
  push.py --project 客户B --tag client            # dry-run，可外发口径卡片
  push.py --project 客户B --send                  # 真发（用配置里的 webhook）
  push.py --project 客户B --send --url https://open.feishu.cn/open-apis/bot/v2/hook/xxx
  push.py --project 客户B --send --text "一句话通知"   # 纯文本（不走卡片）

Webhook 取值优先级：--url > 环境变量 SENTINEL_WEBHOOK_<项目名> > projects.json 的 webhook。
若机器人开了「签名校验」，在配置里填 `webhook_secret`（或环境变量 SENTINEL_WEBHOOK_SECRET_<项目名>）。
"""
import argparse
import base64
import datetime
import hashlib
import hmac
import json
import os
import re
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402

KIND_LABEL = {
    "overdue": "逾期未闭环",
    "due_soon": "临期",
    "blocked": "阻塞/待确认",
    "no_progress": "进展空缺",
    "completion_candidate": "群里已见完成未回写",
    "status_delta": "实况与表内状态不符",
    "new_requirement": "客户新增需求",
    "stale_table": "整表停更",
    "schema_missing_field": "字段缺失",
    "schema_new_fields": "表结构提醒",
    "schema_field_id_changed": "字段ID变化",
    "unknown_status": "状态异常",
}
# 状态差异在卡片上单列一段（不混在 P0/P1 长列表里，一眼能看出「表落后于实况」）
DELTA_ORDER = ["done", "doing", "enabled", "blocked"]
DELTA_LABEL = {"done": "完成", "doing": "进行中", "enabled": "启用", "blocked": "阻塞"}
SEV_ORDER = {"P0": 0, "P1": 1, "P2": 2}


# ------------------------------------------------------------------ 卡片
def _header(label, as_of, template):
    return {
        "template": template,
        "title": {"tag": "plain_text", "content": f"{label} · 项目巡检"},
        "subtitle": {"tag": "plain_text", "content": as_of},
    }


def _div(md):
    return {"tag": "div", "text": {"tag": "lark_md", "content": md}}


def _btn(text, url):
    return {"tag": "action", "actions": [
        {"tag": "button", "text": {"tag": "plain_text", "content": text},
         "url": url, "type": "primary"}]}


def _note(text):
    return {"tag": "note", "elements": [{"tag": "plain_text", "content": text}]}


def _group(signals):
    """按 kind 计数，保持稳定顺序。"""
    d = {}
    for s in signals:
        d.setdefault(s["kind"], []).append(s)
    order = ["overdue", "stale_table", "blocked", "completion_candidate",
             "no_progress", "due_soon", "schema_missing_field",
             "schema_field_id_changed", "schema_new_fields", "unknown_status"]
    return [(k, d[k]) for k in order if k in d] + \
           [(k, v) for k, v in d.items() if k not in order]


def _metrics(items):
    """三列指标卡（column_set）。不能带 background_style —— 卡片 1.0 兼容性优先。"""
    cols = []
    for val, lab in items:
        cols.append({
            "tag": "column", "width": "weighted", "weight": 1, "vertical_align": "top",
            "elements": [{"tag": "div", "text": {"tag": "lark_md", "content": f"**{val}**\n{lab}"}}],
        })
    return {"tag": "column_set", "flex_mode": "none",
            "horizontal_spacing": "default", "columns": cols}


def _detail(s):
    """把 title_desc 压成一行短标签：超期 9 天 · 计划 09-08"""
    import re
    desc = s.get("title_desc") or ""
    m = re.search(r"计划完成\s*(\d{4}-\d{2}-\d{2})\s*已过\s*(\d+)\s*天", desc)
    if m:
        return f"超期 **{m.group(2)}** 天 · 计划 {m.group(1)[5:]}"
    m = re.search(r"计划完成\s*(\d{4}-\d{2}-\d{2})", desc)
    if m:
        return f"计划 {m.group(1)[5:]}"
    return desc[:36]


def _ago(days):
    if days is None:
        return ""
    if days <= 0:
        return "今天"
    if days == 1:
        return "昨天"
    return f"{days} 天前"


def build_card(f, tag="internal", top_n=0, report_url=None):
    """internal = 内部跟进口径；client = 可外发口径（去掉内部判读与措辞）。

    top_n=0（默认）表示 P0 全部列出，不折叠。
    report_url：配置了「完整巡检」在线地址（projects.json 的 report_url）时，
    卡片会多一个「查看完整巡检」按钮 —— 行动通知只给结论，分析过程留在报告页。
    """
    t = f["table"]
    sig = f.get("signals") or []
    dist = t.get("status_dist") or {}
    done = dist.get("已完成", 0)
    doing = dist.get("进行中", 0)
    todo = dist.get("未开始", 0)
    url = t.get("url") or ""
    as_of = f.get("as_of") or ""
    gen = (f.get("generated_at") or "")[-5:]
    short = (f["label"] or "").split(" · ")[0]
    el = []

    if tag == "client":
        header = _header(short, f"{as_of} {gen} · 计划内任务 {t['records']} 项", "blue")
        el.append(_div(f"**已完成 {done}** ｜ 进行中 {doing} ｜ 未开始 {todo}"))
        live = [s for s in sig if not s.get("dismissed")]
        late = [s for s in live if s["kind"] == "overdue"]
        pend = [s for s in live if s["kind"] in ("status_delta", "completion_candidate")]
        reqs = [s for s in live if s["kind"] == "new_requirement"]
        if top_n > 0:
            late, pend, reqs = late[:top_n], pend[:top_n], reqs[:top_n]
        if late:
            el.append({"tag": "hr"})
            lines = []
            for s in late:
                at = _at(s)
                lines.append(f"- **{s.get('no', '—')}** {s['title']}（{_due_of(s)}）" + (f" · {at}" if at else ""))
            el.append(_div(f"**待确认完成情况 {len(late)} 项**\n" + "\n".join(lines)))
        if pend:
            el.append({"tag": "hr"})
            lines = []
            for s in pend:
                at = _at(s)
                lines.append(f"- **{s.get('no', '—')}** {_short(s.get('title'))}"
                             f"（群内已「{s.get('actual') or '完成'}」）" + (f" · {at}" if at else ""))
            el.append(_div("**状态待同步 " + str(len(pend)) + " 项**\n" + "\n".join(lines)))
        if reqs:
            el.append({"tag": "hr"})
            lines = [f"- {s.get('title_desc') or ''}" for s in reqs]
            el.append(_div(f"**已记录的新增事项 {len(reqs)} 条**\n" + "\n".join(lines)))
        el.append(_div("烦请相关同事确认上述事项的最新状态，以便我们同步调整后续排期。"))
        el.append(_btn("查看项目计划表", url))
        el.append(_note(f"自动生成于 {f.get('generated_at', '')} · 如需调整请直接回复本消息"))
        return {"config": {"wide_screen_mode": True}, "header": header, "elements": el}

    # ---------------- internal · v6「行动通知」版式（2026-09-17 定稿）
    # 定位：**行动通知**，不是总结报告。核心目标 = 项目成员进群 30 秒看懂
    # 「今天最需要推进什么、谁负责、哪里有风险、下一步做什么」。
    # 结构：① 总览（四格口径统一）② 🎯 今天优先处理（结构化条目，核心区）
    # ③ 📅 近期关键节点 ④ 🟠 其他重点跟进 ⑤ 🆕 新增诉求（AI 归类，不堆原话）
    # ⑥ 🟡 低优先折叠 ⑦ 按钮。
    # ★ 过程信息（缺录候选/风险词/待办候选/误报阈值等）一律不进卡片 —— 那些在完整报告里。
    conc = f.get("conclusion") or {}
    live = [s for s in sig if not s.get("dismissed")]      # 已核实误报的不参与计数
    p0_all = _dedup_by_no([s for s in live if s["severity"] == "P0" and s.get("no") != "—"])
    p1_other = _dedup_by_no([s for s in live if s["severity"] == "P1"
                             and s.get("kind") != "new_requirement"])
    p2_other = [s for s in live if s["severity"] == "P2" and s.get("kind") != "new_requirement"]
    req_sum = f.get("req_summary") or {}
    n_req = req_sum.get("count") or 0
    n_p0 = len([s for s in live if s["severity"] == "P0"])          # 计数按信号算（含 — 号项）
    header = _header(short, f"{as_of} {gen} · {t['records']} 项任务",
                     "orange" if n_p0 else "blue")
    el.append(_metrics([
        (n_p0, "🔴 必须处理"),
        (len(p1_other), "🟠 重点跟进"),
        (len(p2_other), "🟡 低优先"),
        (f"{done}/{t['records']}", "✅ 已完成"),
    ]))
    tail = f" · 表停更 {t['table_age_days']} 天" if (t.get("table_age_days") or 0) > 0 else ""
    el.append(_div(f"进行中 {doing} · 未开始 {todo} · 已完成 {done}{tail}"))

    # ---- ①b 📦 子项目进度（父行 rollup，2026-09-17 客户B起用「父记录」管理子项目）
    subs = f.get("subprojects") or []
    if subs:
        el.append({"tag": "hr"})
        lines = [f"📦 **子项目进度 · {len(subs)}**"]
        for sp in subs:
            meta = f"{sp['done']}/{sp['total']} 子任务完成"
            if sp.get("doing"):
                meta += f" · 进行中 {sp['doing']}"
            if sp.get("blocked"):
                meta += f" · 阻塞 {sp['blocked']}"
            st = f" · {sp['status']}" if sp.get("status") else ""
            lines.append(f"　**{sp.get('no')}** {sp.get('title')}　{meta}{st}")
        el.append(_div("\n".join(lines)))

    # ---- ② 🎯 今天优先处理（核心区：ID+名称 / @负责人 / 时点 / 当前 / 下一步）
    focus = f.get("focus") or []
    if focus:
        el.append({"tag": "hr"})
        blocks = []
        for it in focus:
            head = f"**{it.get('no')} · {it.get('title')}**" if it.get("no") != "REQ" \
                else f"**🆕 {it.get('title')}**"
            blocks.append(head)
            at = _at_owners(it.get("owners") or [])
            if at:
                blocks.append(at)
            if it.get("meta"):
                blocks.append(it["meta"])
            if it.get("current"):
                blocks.append(f"当前：{it['current']}")
            if it.get("next"):
                blocks.append(f"→ {it['next']}")
        el.append(_div("🎯 **今天优先处理**\n" + "\n".join(blocks)))

    # ---- ③ 📅 近期关键节点（带表内状态，一眼看出哪个节点还没启动）
    nodes = f.get("key_nodes") or []
    if nodes:
        el.append({"tag": "hr"})
        lines = ["📅 **近期关键节点**"]
        for n in nodes:
            row = f"{n.get('date')} · {n.get('label')}".rstrip(" ·")
            st = n.get("status") or ""
            if st and st != "已完成":
                row += f"　表内「{st}」"
            lines.append(row)
            if n.get("warn"):
                lines.append(f"⚠️ {n['warn']}")
        el.append(_div("\n".join(lines)))

    # ---- ④ 🟠 其他重点跟进（一行一条，补一句描述 + 负责人，避免只有类型词太抽象）
    if p1_other:
        el.append({"tag": "hr"})
        lines = [f"🟠 **其他重点跟进 · {len(p1_other)}**"]
        for s in p1_other[:8]:
            if s["kind"] == "status_delta":
                lab = f"实况不符（群内「{s.get('actual') or '—'}」/表内「{s.get('table_status') or '—'}」）"
            elif s["kind"] == "no_progress":
                lab = f"进展空缺（{s.get('status') or '表内'}未填最新进展）"
            else:
                lab = KIND_LABEL.get(s["kind"], s["kind"])
            row = f"　{s.get('no', '—')} · {lab}"
            if s["kind"] in ("overdue", "due_soon"):
                d = _detail(s)
                if d:
                    row += f" · {d}"
            ow = _owners(s)
            if ow:
                row += f" · 👤 {ow}"
            lines.append(row)
        if len(p1_other) > 8:
            lines.append(f"　… 另 {len(p1_other) - 8} 项，详见完整巡检报告")
        el.append(_div("\n".join(lines)))

    # ---- ⑤ 🆕 新增诉求（AI 归类汇总，原话不进卡片）
    if n_req:
        el.append({"tag": "hr"})
        cats = " · ".join(f"{k} {v}" for k, v in sorted(req_sum.get("categories", {}).items(),
                                                        key=lambda x: -x[1]))
        lines = [f"🆕 **新增诉求 · {n_req}**"]
        if cats:
            lines.append(cats)
        names = req_sum.get("names") or []
        if names:
            lines.append("主要涉及：" + " / ".join(names[:5]) + ("等" if len(names) > 5 else ""))
        if req_sum.get("status"):
            lines.append(f"当前状态：{req_sum['status']}")
        if req_sum.get("action"):
            lines.append(f"→ {req_sum['action']}")
        el.append(_div("\n".join(lines)))

    # ---- ⑥ 🟡 低优先折叠
    if p2_other:
        el.append(_div(f"🟡 **低优先问题 · {len(p2_other)}**\n本次不展开，详见完整巡检报告"))

    # ---- ⑦ 按钮 + note
    btns = [{"tag": "button", "text": {"tag": "plain_text", "content": "打开项目表"},
             "url": url, "type": "primary"}]
    if report_url:
        btns.append({"tag": "button", "text": {"tag": "plain_text", "content": "查看完整巡检"},
                     "url": report_url, "type": "default"})
    el.append({"tag": "action", "actions": btns})
    el.append(_note("自动巡检 · 请各负责人核对名下任务状态 · 回写线上表需单独授权"))
    return {"config": {"wide_screen_mode": True}, "header": header, "elements": el}


def _at_owners(owners, limit=3):
    """focus 条目用的 @ 渲染（owners = [{id, name}]），有 open_id 就真 @。"""
    out = []
    for p in owners[:limit]:
        oid, nm = (p.get("id") or "").strip(), (p.get("name") or "").strip()
        if oid:
            out.append(f"<at id={oid}></at>")
        elif nm:
            out.append(f"@{nm}")
    return " ".join(out)


def _short(s, n=22):
    """标题压到一行：超过 n 字截断加省略号。"""
    s = (s or "").strip()
    return s if len(s) <= n else s[:n] + "…"


def _merge_signals(items):
    """同一任务编号的多条信号合成一条，问题描述并进 `_mates`。

    一条任务可能同时「逾期」又「疑似已完成」，直接列两遍用户会以为重复。
    保留首次出现的序号顺序；`_mates` 里的描述去重后由调用方渲染。
    """
    order, by_no = [], {}
    for s in items:
        no = s.get("no") or s.get("record_id")
        if no not in by_no:
            c = dict(s)
            c["_mates"] = []
            by_no[no] = c
            order.append(no)
        d = _detail(s)
        if d and d not in by_no[no]["_mates"]:
            by_no[no]["_mates"].append(d)
    return [by_no[n] for n in order]


def _dedup_by_no(items):
    """按编号去重（保留首次出现）。分组渲染前用，避免同一编号跨组重复出现。"""
    seen, out = set(), []
    for s in items:
        no = s.get("no")
        if no and no in seen:
            continue
        seen.add(no)
        out.append(s)
    return out


def _owners(s, limit=3):
    """负责人的**纯文本**写法（报告 / 无法 @ 时用）。多人用「、」连接。"""
    names = [p.get("name") for p in (s.get("owners") or []) if p.get("name")]
    if not names:
        raw = (s.get("owner") or "").strip()
        names = [x.strip() for x in re.split(r"[,，、/]\s*", raw) if x.strip()]
    if not names:
        return ""
    if len(names) > limit:
        return "、".join(names[:limit]) + f" 等 {len(names)} 人"
    return "、".join(names)


def _at(s, limit=3):
    """渲染**真实 @ 提醒**：有 open_id 用 lark_md 的 <at> 标签，没有就退化成 👤名字。

    人员字段自带 open_id（cell = [{'id': 'ou_xxx', 'name': '张三'}]），所以能直接 @ 到人。
    文本负责人字段靠 people_index / sender_aliases 反查，查不到就只显示名字。
    """
    owners = s.get("owners") or []
    if not owners:
        nm = _owners(s, limit)
        return f"👤 {nm}" if nm else ""
    out, extra = [], 0
    for p in owners:
        if len(out) >= limit:
            extra += 1
            continue
        oid, nm = (p.get("id") or "").strip(), (p.get("name") or "").strip()
        out.append(f"<at id={oid}></at>" if oid else f"👤 {nm}")
    txt = " ".join(out)
    if extra:
        txt += f" 等 {len(owners)} 人"
    return txt


def _due_of(s):
    """从 title_desc 里抠出「计划完成 YYYY-MM-DD」。"""
    import re
    m = re.search(r"计划完成\s*(\d{4}-\d{2}-\d{2})", s.get("title_desc") or "")
    return m.group(1) if m else "—"


# ------------------------------------------------------------------ 发送
def sign(secret, body):
    ts = str(int(datetime.datetime.now().timestamp()))
    s = f"{ts}\n{secret}".encode("utf-8")
    h = hmac.new(s, b"", digestmod=hashlib.sha256).digest()
    return ts, base64.b64encode(h).decode("utf-8")


def post(url, payload, secret=None):
    if secret:
        ts, sig = sign(secret, payload)
        payload = dict(payload, timestamp=ts, sign=sig)
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            raw = r.read().decode("utf-8")
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
    try:
        j = json.loads(raw)
    except json.JSONDecodeError:
        return {"ok": False, "error": raw[:300]}
    code = j.get("code", j.get("StatusCode", 0))
    return {"ok": code in (0, None), "code": code, "resp": j}


def resolve_webhook(cfg, key, proj, cli_url=None):
    if cli_url:
        return cli_url, os.environ.get(f"SENTINEL_WEBHOOK_SECRET_{key}") or proj.get("webhook_secret")
    env = os.environ.get(f"SENTINEL_WEBHOOK_{key}")
    url = env or proj.get("webhook")
    secret = os.environ.get(f"SENTINEL_WEBHOOK_SECRET_{key}") or proj.get("webhook_secret")
    return url, secret


def send_via_cli(card, chat=None, user=None, as_identity="bot"):
    """通道 B：用 lark-cli 以「人 / 机器人」身份把卡片发到指定群或私聊。

    比 webhook 灵活（可换群、可私聊），但身份是发送者本人或应用机器人。
    """
    content = json.dumps(card, ensure_ascii=False)
    args = ["im", "+messages-send", "--msg-type", "interactive",
            "--content", content, "--as", as_identity]
    if chat:
        args += ["--chat-id", chat]
    else:
        args += ["--user-id", user]
    return C.lark(args)


# ------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--tag", default="internal", choices=["internal", "client"])
    ap.add_argument("--date", default=None, help="findings 日期，默认今天")
    ap.add_argument("--top", type=int, default=0, help="P0 明细最多列几条；0（默认）= 全部列出")
    ap.add_argument("--text", default=None, help="改为发一条纯文本消息，不发卡片")
    ap.add_argument("--url", default=None, help="临时覆盖 webhook")
    ap.add_argument("--chat", default=None, help="通道B：发到指定群 oc_xxx（走 lark-cli，身份 user/bot）")
    ap.add_argument("--user", default=None, help="通道B：发到私聊 ou_xxx")
    ap.add_argument("--as", dest="as_identity", default="bot", choices=["user", "bot"],
                    help="CLI 通道身份；bot 为默认（user 身份另需 im:message.send_as_user 授权）")
    ap.add_argument("--send", action="store_true", help="真正发送（默认只生成不发送）")
    args = ap.parse_args()

    cfg = C.load_config()
    proj = C.project_cfg(cfg, args.project)
    day = args.date or C.today().isoformat()
    fpath = os.path.join(cfg["_scratch"], f"findings-{args.project}-{day}.json")
    if not os.path.exists(fpath):
        raise SystemExit(f"找不到巡检结果：{fpath}\n先跑 analyze.py --project {args.project}")

    findings = json.load(open(fpath, encoding="utf-8"))

    if args.text:
        payload = {"msg_type": "text", "content": {"text": args.text}}
    else:
        payload = {"msg_type": "interactive",
                   "card": build_card(findings, args.tag, args.top, proj.get("report_url"))}

    cards_dir = os.path.join(cfg["_scratch"], "cards")
    os.makedirs(cards_dir, exist_ok=True)
    suffix = "client" if args.tag == "client" else "internal"
    cpath = os.path.join(cards_dir, f"card-{args.project}-{day}-{suffix}.json")
    C.dump(cpath, payload)

    via = "cli" if (args.chat or args.user) else "webhook"
    url, secret = resolve_webhook(cfg, args.project, proj, args.url)
    if not args.send:
        print(json.dumps({
            "mode": "dry-run", "project": args.project, "tag": args.tag, "via": via,
            "card": cpath, "webhook": (url[:48] + "…") if url else None,
            "chat": args.chat, "user": args.user, "sent": False,
            "next": "确认内容与目标后加 --send；对外发送用 --tag client",
        }, ensure_ascii=False, indent=1))
        return

    if via == "cli":
        res = send_via_cli(payload["card"], args.chat, args.user, args.as_identity)
        ok = bool(res.get("ok"))
    else:
        if not url:
            raise SystemExit(f"{args.project} 未配置 webhook（放 projects.json 的 webhook 字段，"
                             f"或设环境变量 SENTINEL_WEBHOOK_{args.project}，或改用 --chat oc_xxx）")
        res = post(url, payload, secret)
        ok = bool(res.get("ok"))
    print(json.dumps({"mode": "send", "project": args.project, "tag": args.tag, "via": via,
                      "card": cpath, "result": res}, ensure_ascii=False, indent=1))
    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
