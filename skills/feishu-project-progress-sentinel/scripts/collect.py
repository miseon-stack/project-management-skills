#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""采集层：把「数据源」抓成本地 raw json。

用法：
  python3 collect.py --project 客户B --since 2026-09-15
  python3 collect.py --project all --days 3 --no-docs
  python3 collect.py --project 客户C --since 2026-09-10 --max-pages 20

数据源：
  1) 项目相关群聊消息（原生 API，绕开 reactions scope 坑）
  2) 群内出现的云文档（智能纪要 / 文字记录 / 方案）+ 按关键词搜到的纪要
  3) 日历日程（会议安排本身也是进度信号）
  4) 会议妙记（minutes +search 按「我参与+时间」拉，含 AI 摘要与待办）
     ★ 妙记**不在云空间**，drive +search 搜不到，必须走这条独立通道

输出：
  <scratch>/raw-<项目>-<YYYY-MM-DD>.json
"""
import argparse
import datetime
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402

DOC_LINK = re.compile(r"https://[\w.-]*feishu\.cn/(docx|wiki|docs|minutes|base|sheets|slides)/[A-Za-z0-9]+")
MSG_SINCE_LIMIT = 12  # 每个群最多翻多少页


def parse_message(m, people):
    mt = m.get("msg_type") or "unknown"
    sid = (m.get("sender") or {}).get("id") or ""
    raw = (m.get("body") or {}).get("content") or ""
    text = ""
    try:
        j = json.loads(raw)
    except Exception:
        j = {}
    if mt == "text":
        text = j.get("text", "")
    elif mt == "post":
        parts = []
        blocks = j.get("content") or (j.get("post") or {}).get("zh_cn", {}).get("content") or []
        for para in blocks:
            if isinstance(para, list):
                parts.append("".join(s.get("text", "") for s in para if isinstance(s, dict)))
        text = " / ".join(p for p in parts if p)
    elif mt in ("interactive", "card"):
        found = re.findall(r'"text"\s*:\s*"([^"]{2,120})"', raw)
        titles = re.findall(r'"title"\s*:\s*"([^"]{2,80})"', raw)
        text = "[卡片] " + " | ".join((titles + found)[:12])
    elif mt == "file":
        text = f"[文件] {j.get('file_name', '')}"
    elif mt == "image":
        text = "[图片]"
    elif mt == "media":
        text = f"[视频] {j.get('file_name', '')}"
    elif mt == "audio":
        text = "[语音]"
    elif mt == "merge_forward":
        text = "[合并转发]"
    elif mt == "share_calendar_event":
        text = "[日程分享]"
    elif mt == "video_chat":
        text = "[会议发起]"
    else:
        text = f"[{mt}]"
    for mm in (m.get("mentions") or []):
        key = mm.get("key")
        if key:
            text = text.replace(key, "@" + str(mm.get("name") or ""))
    text = re.sub(r"\s+", " ", text).strip()
    ts = int(m.get("create_time") or 0)
    return {
        "chat_ts": ts,
        "time": datetime.datetime.fromtimestamp(ts / 1000).strftime("%Y-%m-%d %H:%M") if ts else "",
        "sender_id": sid,
        "sender": people.get(sid, sid or "?"),
        "msg_type": mt,
        "text": text,
        "links": [x.group(0) for x in DOC_LINK.finditer(raw)],
    }


def fetch_chat(oc, since_d, until_d, people, max_pages):
    start = int(datetime.datetime.combine(since_d, datetime.time(0, 0)).timestamp())
    end = int(datetime.datetime.combine(until_d, datetime.time(23, 59, 59)).timestamp())
    msgs, token, pages = [], None, 0
    while pages < max_pages:
        params = {"container_id_type": "chat", "container_id": oc,
                  "start_time": str(start), "end_time": str(end),
                  "sort_type": "ByCreateTimeAsc", "page_size": 50}
        if token:
            params["page_token"] = token
        res = C.lark(["api", "GET", "/open-apis/im/v1/messages",
                      "--params", json.dumps(params), "--as", "user"])
        if not isinstance(res, dict) or not res.get("data"):
            return msgs, {"ok": False, "error": str(res)[:200]}
        d = res["data"]
        for m in d.get("items") or []:
            if (m.get("deleted") is True) or m.get("msg_type") == "unknown":
                continue
            msgs.append(parse_message(m, people))
        pages += 1
        if not d.get("has_more") or not d.get("page_token"):
            return msgs, {"ok": True, "pages": pages}
        token = d["page_token"]
    return msgs, {"ok": True, "pages": pages, "truncated": True}


def resolve_names(ids, people):
    """把 people 索引里没有的 open_id 批量补名（contact +search-user --user-ids）。"""
    unknown = [i for i in ids if i and i not in people and i.startswith("ou_")]
    for i in range(0, len(unknown), 20):
        chunk = unknown[i:i + 20]
        res = C.lark(["contact", "+search-user", "--user-ids", ",".join(chunk), "--as", "user"])
        users = ((res.get("data") or {}).get("users")
                 or (res.get("data") or {}).get("items") or [])
        for u in users:
            oid = u.get("open_id") or u.get("user_id")
            nm = u.get("name") or u.get("en_name")
            if oid and nm:
                people[oid] = nm
    return people


def fetch_doc(url, cache):
    if url in cache:
        return cache[url]
    res = C.lark(["docs", "+fetch", "--doc", url, "--doc-format", "markdown",
                  "--format", "json", "--as", "user"], timeout=120)
    info = {"url": url, "ok": False, "title": "", "content": ""}
    try:
        doc = res["data"]["document"]
        info["ok"] = True
        info["content"] = (doc.get("content") or "")[:20000]
    except Exception:
        info["error"] = str(res)[:200]
    # docs +fetch 不返回标题 → 用 drive +inspect 补
    ins = C.lark(["drive", "+inspect", "--url", url, "--as", "user"])
    try:
        info["title"] = (ins.get("data") or {}).get("title") or ""
    except Exception:
        pass
    if not info["title"]:
        first = (info["content"] or "").strip().split("\n")
        info["title"] = first[0].lstrip("# ").strip()[:80] if first and first[0] else ""
    cache[url] = info
    return info


def search_docs(keywords, since_d):
    """按关键词搜云文档，挑出纪要/方案类。返回 [{title,url}]"""
    hits, seen = [], set()
    for kw in keywords:
        res = C.lark(["drive", "+search", "--query", kw, "--page-size", "20", "--as", "user"])
        for it in ((res.get("data") or {}).get("results") or []):
            meta = it.get("result_meta") or {}
            url = meta.get("url") or ""
            title = (it.get("title_highlighted") or meta.get("title") or "").replace("<h>", "").replace("</h>", "")
            if not url or url in seen:
                continue
            seen.add(url)
            hits.append({"title": title, "url": url, "doc_types": meta.get("doc_types")})
    return hits


def _lark_raw(args, timeout=240):
    """跑 lark-cli 并剥离前置日志行后解析 JSON。

    `minutes +search/+detail` 会先往 stdout 打 `[minutes +detail] querying ...`
    这类日志，C.lark 只认首字符是 `{` 的输出 → 这里用「找第一个 {」的方式兜住。
    """
    r = subprocess.run(["lark-cli"] + args, capture_output=True, text=True,
                       cwd=os.path.join(C.load_config()["_scratch"], ".scratch"),
                       timeout=timeout)
    s = (r.stdout or "").strip()
    i = s.find("{")
    if i < 0:
        return {}
    try:
        return json.loads(s[i:])
    except json.JSONDecodeError:
        return {}


def fetch_minutes(since_d, until_d, keywords, max_items=30):
    """拉「我参与过」的会议妙记，按项目关键词过滤标题，再取 AI 摘要 + 待办。

    为什么要这条通道：会议的智能纪要（妙记）只存在于 minutes 体系里，
    既不是云文档（drive +search 搜不到），也不一定有人把它贴进群；
    只靠「群消息 + 群内文档」会**整场会议的结论与分派全部丢失**。

    返回 [{token,title,url,owner,duration,summary,todo,keywords}]
    """
    res = _lark_raw(["minutes", "+search", "--participant-ids", "me",
                     "--start", since_d.isoformat(), "--end", until_d.isoformat(),
                     "--page-size", str(max_items), "--as", "user"])
    items = (res.get("data") or {}).get("items") or []
    picked = []
    for it in items:
        disp = it.get("display_info") or ""
        title = disp.split("\n")[0].strip()
        if not title:
            continue
        if keywords and not any(k in title for k in keywords):
            continue
        meta = it.get("meta_data") or {}
        desc = meta.get("description") or ""
        picked.append({
            "token": it.get("token"),
            "title": title,
            "url": meta.get("app_link") or "",
            "desc": desc.replace("\n", " "),
            "from": "minutes",
        })
    if not picked:
        return []
    toks = ",".join(x["token"] for x in picked if x.get("token"))
    det = _lark_raw(["minutes", "+detail", "--minute-tokens", toks,
                     "--summary", "--todo", "--keyword", "--as", "user"])
    by = {m.get("minute_token"): m for m in ((det.get("data") or {}).get("minutes") or [])}
    for x in picked:
        m = by.get(x.get("token")) or {}
        a = m.get("artifacts") or {}
        x["note_id"] = m.get("note_id")
        x["summary"] = a.get("summary") or ""
        x["todo"] = a.get("todo") or a.get("todos") or []
        x["keywords"] = a.get("keywords") or []
    return picked


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True, help="客户B | 客户A | 客户C | all")
    ap.add_argument("--since", default=None, help="YYYY-MM-DD，默认今天-3天")
    ap.add_argument("--days", type=int, default=None, help="与 --since 二选一")
    ap.add_argument("--max-pages", type=int, default=MSG_SINCE_LIMIT)
    ap.add_argument("--no-docs", action="store_true", help="不抓云文档正文")
    ap.add_argument("--no-minutes", action="store_true", help="不抓会议妙记（摘要/待办）")
    ap.add_argument("--max-docs", type=int, default=10)
    ap.add_argument("--workspace", default=None)
    a = ap.parse_args()

    cfg = C.load_config(a.workspace)
    since_d = C.parse_since(a.since) if a.since else C.today() - datetime.timedelta(days=(a.days or 3))
    until_d = C.today()
    people = C.load_people(cfg)

    keys = list(cfg["projects"]) if a.project == "all" else [a.project]
    for key in keys:
        proj = C.project_cfg(cfg, key)
        C.msg(f"== 采集 {proj['label']} | {since_d} → {until_d}")
        chat_data, all_msgs = {}, []
        for name, oc in proj["chats"].items():
            msgs, stat = fetch_chat(oc, since_d, until_d, people, a.max_pages)
            chat_data[name] = {"chat_id": oc, "count": len(msgs), "stat": stat, "messages": msgs}
            all_msgs.extend(msgs)
            C.msg(f"   {name}: {len(msgs)} 条 {'' if stat.get('ok') else '⚠️ ' + str(stat)[:80]}")

        # 补名：数据仓 people.json 没覆盖到的 open_id，走通讯录批量解析
        resolve_names({m["sender_id"] for m in all_msgs}, people)
        for m in chat_data.values():
            for x in m["messages"]:
                if x["sender_id"] in people:
                    x["sender"] = people[x["sender_id"]]

        docs = []
        if not a.no_docs:
            urls, seen = [], set()
            for m in sorted(all_msgs, key=lambda x: x["chat_ts"], reverse=True):
                for u in m["links"]:
                    if u not in seen:
                        seen.add(u)
                        urls.append(u)
            urls = urls[: a.max_docs]
            cache = {}
            for u in urls:
                info = fetch_doc(u, cache)
                if info.get("ok"):
                    docs.append(info)
                    C.msg(f"   文档 {info['title'][:40]}")
            found = search_docs(proj.get("search_keywords", []), since_d)
            for f in found[: a.max_docs]:
                if any(f["url"] == d["url"] for d in docs):
                    continue
                if not any(k in f["title"] for k in ("纪要", "周报", "记录", "方案", "总结", "会议")):
                    continue
                info = fetch_doc(f["url"], cache)
                if info.get("ok"):
                    info["from"] = "search"
                    docs.append(info)
                    C.msg(f"   搜索命中 {info['title'][:40]}")

        cal = C.lark(["calendar", "+agenda",
                      "--start", since_d.isoformat() + "T00:00:00",
                      "--end", until_d.isoformat() + "T23:59:59", "--as", "user"])
        events = cal.get("data") if isinstance(cal.get("data"), list) else []

        # 会议妙记：会议结论与分派的唯一可靠来源，不能只靠群里有没有人贴链接
        mins = []
        if not a.no_minutes:
            mins = fetch_minutes(since_d, until_d, proj.get("search_keywords", []))
            for x in mins:
                C.msg(f"   妙记 {x['title'][:34]} | 摘要 {len(x.get('summary') or '')} 字"
                      f" | 待办 {len(x.get('todo') or [])}")
            if not mins:
                C.msg("   妙记 无（窗口内无匹配会议，或纪要未生成）")

        payload = {
            "project": key,
            "label": proj["label"],
            "generated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
            "window": {"since": since_d.isoformat(), "until": until_d.isoformat()},
            "chats": chat_data,
            "messages_flat": sorted(all_msgs, key=lambda x: x["chat_ts"]),
            "docs": docs,
            "minutes": mins,
            "calendar": [{"summary": e.get("summary"), "start": e.get("start_time") or e.get("start"),
                          "end": e.get("end_time") or e.get("end")} for e in events],
        }
        path = C.out_path(cfg, f"raw-{key}-{C.today().isoformat()}.json")
        C.dump(path, payload)
        print(json.dumps({"ok": True, "project": key, "raw": path,
                          "messages": len(all_msgs), "docs": len(docs),
                          "minutes": len(mins), "calendar": len(payload["calendar"])},
                         ensure_ascii=False))


if __name__ == "__main__":
    main()
