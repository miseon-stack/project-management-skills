#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""公共工具：lark-cli 调用、项目配置、记录解析、日期工具。

设计要点（都是实测踩过的坑）：
- lark-cli 的 --output / --json @ 只接受「当前目录内的相对路径」→ 一律用 scratch 目录作 cwd。
- 群消息不能用 `im +chat-messages-list`（缺 im:message.reactions:read scope），必须走原生 API。
- `base +record-list` 的 ndjson 是扁平结构，字段名直接挂在行对象上。
"""
import json
import os
import re
import subprocess
import sys
import datetime
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(HERE)
DEFAULT_WORKSPACE = "<WORKSPACE>"
CFG_PATH = os.path.join(SKILL_DIR, "references", "projects.json")
SECRETS_PATH = os.path.join(SKILL_DIR, "references", "secrets.local.json")
PEOPLE_LOCAL = os.path.join(SKILL_DIR, "references", "people.local.json")


# ---------------------------------------------------------------- 配置
def load_config(workspace=None):
    ws = workspace or os.environ.get("SENTINEL_WORKSPACE") or DEFAULT_WORKSPACE
    raw = open(CFG_PATH, encoding="utf-8").read().replace("<WORKSPACE>", ws.rstrip("/"))
    cfg = json.loads(raw)
    cfg["_workspace"] = ws.rstrip("/")
    cfg["_scratch"] = cfg["scratch_dir"]
    os.makedirs(os.path.join(cfg["_scratch"], ".scratch"), exist_ok=True)
    _merge_secrets(cfg)
    return cfg


def _merge_secrets(cfg):
    """把 references/secrets.local.json 的凭据合并进各项目配置。

    该文件不入库（.gitignore 排除），projects.json 里 webhook 一律为 null。
    按项目键合并；缺失或格式错不报错 —— 未配凭据时 push 会给出明确提示。
    """
    cfg["_secrets"] = {}
    if not os.path.exists(SECRETS_PATH):
        return cfg
    try:
        sec = json.load(open(SECRETS_PATH, encoding="utf-8"))
    except Exception as e:
        cfg["_secrets_error"] = f"{SECRETS_PATH} 解析失败：{e}"
        return cfg
    for key, vals in (sec.get("projects") or {}).items():
        p = cfg["projects"].get(key)
        if not isinstance(p, dict) or not isinstance(vals, dict):
            continue
        for f in ("webhook", "webhook_secret"):
            if vals.get(f):
                p[f] = vals[f]
        cfg["_secrets"][key] = True
    return cfg


def project_cfg(cfg, key):
    p = cfg["projects"].get(key)
    if not p:
        raise SystemExit(f"未知项目 {key}；可选：{list(cfg['projects'])}")
    return p


# ---------------------------------------------------------------- lark-cli
def lark(args, cwd=None, timeout=180, retries=2):
    """跑 lark-cli，返回解析后的 JSON。失败返回 {'ok': False, 'error': ...}。"""
    last = None
    for attempt in range(retries + 1):
        r = subprocess.run(["lark-cli"] + args, capture_output=True, text=True,
                           cwd=cwd or os.path.join(load_config()["_scratch"], ".scratch"),
                           timeout=timeout)
        out = (r.stdout or "").strip()
        if out.startswith("{") or out.startswith("["):
            try:
                return json.loads(out)
            except json.JSONDecodeError:
                last = out[:400]
        else:
            last = (out or r.stderr or "")[:400]
        if "1254290" in str(last) or "1254291" in str(last) or "TooManyRequest" in str(last):
            time.sleep(1.5 * (attempt + 1))
            continue
        break
    return {"ok": False, "error": last}


# ---------------------------------------------------------------- 记录
def fetch_records(cfg, proj, scratch_file="cur.ndjson"):
    """拉全量记录，返回 (records, meta)。ndjson 扁平结构。"""
    work = os.path.join(cfg["_scratch"], ".scratch")
    rel = scratch_file
    res = lark(["base", "+record-list", "--base-token", proj["base_token"],
                "--table-id", proj["table_id"], "--format", "ndjson",
                "--output", "./" + rel, "--overwrite", "--as", "user"], cwd=work)
    path = os.path.join(work, rel)
    if not os.path.exists(path):
        return [], {"ok": False, "error": res.get("error"), "raw": res}
    recs = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
    return recs, {"ok": True, "count": len(recs), "raw": res}


def flat(v):
    """把 Base 各种 CellValue 压成可读字符串。"""
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, list):
        return ", ".join(flat(i) for i in v if flat(i))
    if isinstance(v, dict):
        for k in ("text", "name", "en_name", "file_name", "id"):
            if v.get(k):
                return str(v[k])
        return ""
    s = str(v)
    s = re.sub(r"\[@([^\]]+)\]\([^)]*\)", r"@\1", s)
    s = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", s)
    s = re.sub(r"\[([^\]]*)\]\(([^)]*)\)", r"\1<\2>", s)
    return s.strip()


def people(v):
    """把「人员」字段 cell 解析成 [{'id': open_id, 'name': 显示名}]。

    人员字段的原始值是 [{'id': 'ou_xxx', 'name': '张三'}, ...]，**带 open_id** ——
    这是卡片里 @ 到具体人的唯一可靠来源（文本负责人字段只能靠 people_index 反查）。
    """
    out = []
    if not v:
        return out
    items = v if isinstance(v, list) else [v]
    for it in items:
        if isinstance(it, dict):
            oid = it.get("id") or it.get("open_id") or ""
            nm = it.get("name") or it.get("en_name") or it.get("text") or ""
            if oid or nm:
                out.append({"id": oid, "name": nm})
        elif isinstance(it, str) and it.strip():
            out.append({"id": "", "name": it.strip()})
    return out


def name_to_id(cfg):
    """显示名 → open_id 反查表（用于只有文本负责人、没有人员字段的项目）。

    优先级：表内实测映射（people.local.json）> people_index > sender_aliases。
    别名里的「（客户B方）」这类后缀会被剥掉再索引，两种写法都能命中。
    """
    idx = {}
    for oid, nm in _people_local().items():
        clean = re.sub(r"（[^）]*）", "", nm).strip()
        for n in {nm, clean}:
            if n and n not in idx:
                idx[n] = oid
    p = cfg.get("people_index")
    if p and os.path.exists(p):
        try:
            data = json.load(open(p, encoding="utf-8"))
        except Exception:
            data = None
        lst = (data if isinstance(data, list) else data.get("people") or []) if data else []
        for it in lst:
            if not isinstance(it, dict):
                continue
            nm = it.get("name") or it.get("名字")
            ids = it.get("open_ids") or []
            if isinstance(ids, str):
                ids = [ids]
            oid = it.get("open_id")
            if oid:
                ids = list(ids) + [oid]
            for i in ids:
                if i and nm and nm not in idx:
                    idx[nm] = i
    for k, v in (cfg.get("sender_aliases") or {}).items():
        if not k or not v or not k.startswith("ou_"):
            continue
        clean = re.sub(r"（[^）]*）", "", v).strip()
        for nm in {v, clean}:
            if nm and nm not in idx:
                idx[nm] = k
    return idx


def status_is_done(proj, status):
    s = flat(status)
    for d in proj.get("done_values", ["已完成", "完成"]):
        if d in s:
            return True
    return False


def status_is_blocked(proj, status):
    s = flat(status)
    return any(b in s for b in proj.get("blocked_values", ["阻塞"]))


# ---------------------------------------------------------------- 日期
def today():
    return datetime.date.today()


def parse_ts(v):
    """Base 时间字段取值可能有两种形态：
    - 原生 API：毫秒时间戳（int / 数字字符串）
    - ndjson 导出：ISO 字符串，如 '2026-09-17T10:56:11.000+08:00'
    两种都要能吃下。
    """
    if v in (None, "", []):
        return None
    if isinstance(v, str) and "T" in v:
        s = v.replace("Z", "+00:00")
        try:
            return datetime.datetime.fromisoformat(s).replace(tzinfo=None)
        except ValueError:
            try:
                return datetime.datetime.strptime(v[:19], "%Y-%m-%dT%H:%M:%S")
            except ValueError:
                return None
    try:
        ms = int(v)
    except (TypeError, ValueError):
        return None
    if ms < 10 ** 11:
        ms *= 1000
    return datetime.datetime.fromtimestamp(ms / 1000)


DATE_PAT = re.compile(r"(?:(20\d{2})[-/年])?(\d{1,2})[-/月](\d{1,2})")


def dates_in_text(text, ref_year=None):
    """从自由文本里抠出「9/15」「2026-09-15」这类日期，返回 date 列表。"""
    out = []
    ref = ref_year or today().year
    for m in DATE_PAT.finditer(text or ""):
        y, mo, d = m.group(1), int(m.group(2)), int(m.group(3))
        try:
            out.append(datetime.date(int(y) if y else ref, mo, d))
        except ValueError:
            continue
    return out


def latest_date_in_text(text, ref_year=None):
    ds = dates_in_text(text, ref_year)
    return max(ds) if ds else None


def parse_since(s):
    if s in (None, ""):
        return today() - datetime.timedelta(days=3)
    for f in ("%Y-%m-%d", "%Y/%m/%d", "%m-%d"):
        try:
            d = datetime.datetime.strptime(s, f).date()
            if f == "%m-%d":
                d = d.replace(year=today().year)
            return d
        except ValueError:
            continue
    raise SystemExit(f"无法解析日期：{s}")


# ---------------------------------------------------------------- 人员
def _people_local():
    """读 references/people.local.json（由 sync_people.py 从各表人员字段自动收拢）。

    跨租户客户成员在 contact +search-user 里查不到，但他们**在实施表的人员字段里
    带着 open_id + 姓名**——这份文件是最全也最准的来源。
    """
    if not os.path.exists(PEOPLE_LOCAL):
        return {}
    try:
        d = json.load(open(PEOPLE_LOCAL, encoding="utf-8"))
    except Exception:
        return {}
    return {k: v for k, v in d.items() if k.startswith("ou_") and isinstance(v, str)}


def load_people(cfg):
    idx = dict(_people_local())
    p = cfg.get("people_index")
    if p and os.path.exists(p):
        try:
            data = json.load(open(p, encoding="utf-8"))
        except Exception:
            data = None
        lst = (data if isinstance(data, list) else data.get("people") or []) if data else []
        for it in lst:
            if not isinstance(it, dict):
                continue
            name = it.get("name") or it.get("名字")
            ids = it.get("open_ids") or []
            if isinstance(ids, str):
                ids = [ids]
            oid = it.get("open_id")
            if oid:
                ids = list(ids) + [oid]
            for i in ids:
                if i and name:
                    idx[i] = name
    # 手工别名优先级最高：跨租户的客户成员在通讯录里查不到（search-user 返回空），只能登记兜底
    for k, v in (cfg.get("sender_aliases") or {}).items():
        if k and v:
            idx[k] = v
    return idx


# ---------------------------------------------------------------- 输出
def out_path(cfg, name):
    d = cfg["_scratch"]
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, name)


def dump(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    return path


def msg(t):
    print(t, file=sys.stderr)
