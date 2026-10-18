#!/usr/bin/env python3
"""巡检接口层：把「项目进度巡检」暴露成本地 HTTP 接口，供程序/看板/飞书机器人调用。

设计原则（与 SKILL 铁律一致）：
  · 默认只监听 127.0.0.1，不对外网暴露。
  · 只读接口占多数；**任何"发群 / 写线上表"的能力都不在本服务里**（永远需要人确认）。
  · 耗时的采集跑后台线程，接口立即返回 job_id，用 /jobs/<id> 查进度。

启动:
  python3 api_server.py                      # 默认 127.0.0.1:8787
  python3 api_server.py --port 8899 --token mysecret
  SENTINEL_WORKSPACE=<WORKSPACE> python3 api_server.py

接口:
  GET  /                                    服务说明（浏览器可直接打开）
  GET  /health                              健康检查（含工作区、项目、最新巡检日期）
  GET  /projects                            项目与数据源登记
  GET  /summary[?date=YYYY-MM-DD]           各项目汇总（有 run-<date>.json 直接用，否则现算）
  GET  /findings?project=客户B[&date=latest] 结构化 findings（程序消费）
  GET  /report?project=客户B[&date=latest]   巡检报告 markdown 原文
  POST /inspect                             {project, days} → 后台跑 run_all.sh，返回 job_id
  GET  /jobs                                所有后台任务
  GET  /jobs/<id>                           单个任务状态 + 日志尾
  POST /verdicts/suggest                    生成判读候选（半自动），返回清单路径
  GET  /verdicts?project=客户B[&date=]       读取当天已确认的 verdicts
  POST /push?project=客户B&tag=client&dry_run=1   生成卡片预览（dry_run 默认 1）
"""
import argparse
import datetime
import http.server
import json
import os
import re
import subprocess
import sys
import threading
import urllib.parse
import uuid

SKILL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(SKILL, "scripts")
PY = sys.executable


def resolve_ws(explicit=None):
    ws = explicit or os.environ.get("SENTINEL_WORKSPACE")
    if ws:
        return os.path.abspath(ws)
    cand = os.path.dirname(os.path.dirname(os.path.dirname(SKILL)))
    if os.path.isdir(os.path.join(cand, ".workbuddy")):
        return cand
    return os.getcwd()


WS = None
OUT = None
TOKEN = None
JOBS = {}
JOBS_LOCK = threading.Lock()


def reg():
    try:
        with open(os.path.join(SKILL, "references", "projects.json"), encoding="utf-8") as f:
            return json.load(f).get("projects") or {}
    except Exception:
        return {}


def proj_key(name):
    cfg = reg()
    if not name or name == "all":
        return None
    for k in cfg:
        if k == name or name in k:
            return k
    return None


def latest_date(project=None):
    """巡检产出的最新日期。"""
    pat = re.compile(r"^(findings|巡检报告)-(.+)-(\d{4}-\d{2}-\d{2})\.(json|md)$")
    best = None
    for fn in os.listdir(OUT) if os.path.isdir(OUT) else []:
        m = pat.match(fn)
        if not m:
            continue
        if project and m.group(2) != project:
            continue
        d = m.group(3)
        if not best or d > best:
            best = d
    return best or datetime.date.today().isoformat()


def read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def summary_for(project, date):
    fj = os.path.join(OUT, "findings-%s-%s.json" % (project, date))
    d = read_json(fj)
    if not d:
        return {"ok": False, "reason": "无该日 findings", "project": project, "date": date}
    sig = [s for s in (d.get("signals") or []) if not s.get("dismissed")]
    sev = {}
    for s in sig:
        sev[s.get("severity") or "?"] = sev.get(s.get("severity") or "?", 0) + 1
    rp = os.path.join(OUT, "巡检报告-%s-%s.md" % (project, date))
    sp = os.path.join(OUT, "table-snapshot-%s-%s.json" % (project, date))
    vp = os.path.join(OUT, "verdicts-%s-%s.json" % (project, date))
    gp = os.path.join(OUT, "判读候选-%s-%s.md" % (project, date))
    return {
        "ok": True, "project": project, "label": d.get("label"), "date": date, "as_of": d.get("as_of"),
        "generated_at": d.get("generated_at"),
        "records": (d.get("table") or {}).get("records"),
        "status_dist": (d.get("table") or {}).get("status_dist"),
        "table_age_days": (d.get("table") or {}).get("table_age_days"),
        "signals_total": len(sig), "severity": sev,
        "severity_all": _sev_all(d),
        "unreviewed": sum(1 for s in sig if not s.get("verdict")),
        "reviewed_at": (d.get("verdicts_meta") or {}).get("reviewed_at"),
        "headline": (d.get("conclusion") or {}).get("headline"),
        "focus": [{"no": x.get("no"), "title": x.get("title"), "meta": x.get("meta")} for x in (d.get("focus") or [])],
        "files": {"report": rp if os.path.exists(rp) else None,
                  "findings": fj, "snapshot": sp if os.path.exists(sp) else None,
                  "verdicts": vp if os.path.exists(vp) else None,
                  "verdict_candidates": gp if os.path.exists(gp) else None},
    }


def _sev_all(d):
    """含被判为误报的完整分级（报告口径）。"""
    sev = {}
    for s in (d.get("signals") or []):
        sev[s.get("severity") or "?"] = sev.get(s.get("severity") or "?", 0) + 1
    return sev


def run_script(args, timeout=600):
    env = dict(os.environ, SENTINEL_WORKSPACE=WS, PYTHONIOENCODING="utf-8")
    try:
        p = subprocess.run([PY] + args, capture_output=True, text=True, timeout=timeout,
                           cwd=SCRIPTS, env=env)
        return p.returncode, (p.stdout or ""), (p.stderr or "")
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"
    except OSError as e:
        return 1, "", str(e)


def job_new(kind, cmd):
    jid = uuid.uuid4().hex[:12]
    with JOBS_LOCK:
        JOBS[jid] = {"id": jid, "kind": kind, "cmd": cmd, "status": "running",
                     "started": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                     "finished": None, "returncode": None, "log": []}
    return jid


def job_run(jid, cmd, cwd=None, env_extra=None):
    env = dict(os.environ, SENTINEL_WORKSPACE=WS, PYTHONIOENCODING="utf-8")
    if env_extra:
        env.update(env_extra)
    try:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                             cwd=cwd or SCRIPTS, env=env, bufsize=1)
        for line in p.stdout:
            with JOBS_LOCK:
                JOBS[jid]["log"].append(line.rstrip())
                if len(JOBS[jid]["log"]) > 400:
                    JOBS[jid]["log"] = JOBS[jid]["log"][-400:]
        p.wait()
        rc = p.returncode
    except OSError as e:
        with JOBS_LOCK:
            JOBS[jid]["log"].append("启动失败: %s" % e)
        rc = 1
    with JOBS_LOCK:
        JOBS[jid]["returncode"] = rc
        JOBS[jid]["status"] = "done" if rc == 0 else "failed"
        JOBS[jid]["finished"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class Handler(http.server.BaseHTTPRequestHandler):
    server_version = "SentinelAPI/1.0"

    # ---------- 工具 ----------
    def log_message(self, fmt, *args):
        if os.environ.get("SENTINEL_API_QUIET") != "1":
            sys.stderr.write("[api] %s\n" % (fmt % args))

    def send_json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False, indent=1).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_text(self, text, code=200, ctype="text/plain; charset=utf-8"):
        body = text.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_body(self):
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b""
        if not raw:
            return {}
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return {}

    def check_token(self):
        if not TOKEN:
            return True
        if self.headers.get("X-Token") == TOKEN:
            return True
        self.send_json({"ok": False, "error": "需要 X-Token 头"}, 401)
        return False

    # ---------- 路由 ----------
    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        path = u.path.rstrip("/") or "/"
        try:
            if path == "/":
                return self.page_index()
            if path == "/health":
                return self.send_json({
                    "ok": True, "service": "项目进度巡检接口", "workspace": WS,
                    "out_dir": OUT, "latest_date": latest_date(),
                    "projects": list(reg()),
                    "jobs": len(JOBS), "time": datetime.datetime.now().isoformat(timespec="seconds"),
                })
            if path == "/projects":
                cfg = reg()
                return self.send_json({"ok": True, "projects": {
                    k: {"label": v.get("label"), "url": v.get("url"), "records_table": v.get("table_id"),
                        "chats": len(v.get("chats") or []), "visibility": v.get("visibility")}
                    for k, v in cfg.items()}})
            if path == "/summary":
                date = (q.get("date") or [None])[0] or latest_date()
                p = (q.get("project") or ["all"])[0]
                keys = list(reg()) if p == "all" else [proj_key(p) or p]
                rj = os.path.join(OUT, "run-%s.json" % date)
                return self.send_json({"ok": True, "date": date,
                                       "run_all": read_json(rj),
                                       "projects": {k: summary_for(k, date) for k in keys}})
            if path == "/findings":
                p = proj_key((q.get("project") or [""])[0])
                if not p:
                    return self.send_json({"ok": False, "error": "project 参数必须是 %s 之一" % list(reg())}, 400)
                date = (q.get("date") or ["latest"])[0]
                date = latest_date(p) if date == "latest" else date
                d = read_json(os.path.join(OUT, "findings-%s-%s.json" % (p, date)))
                if not d:
                    return self.send_json({"ok": False, "error": "无 findings-%s-%s.json" % (p, date)}, 404)
                return self.send_json({"ok": True, "project": p, "date": date, "findings": d})
            if path == "/report":
                p = proj_key((q.get("project") or [""])[0])
                if not p:
                    return self.send_json({"ok": False, "error": "project 参数无效"}, 400)
                date = (q.get("date") or ["latest"])[0]
                date = latest_date(p) if date == "latest" else date
                rp = os.path.join(OUT, "巡检报告-%s-%s.md" % (p, date))
                if not os.path.exists(rp):
                    return self.send_json({"ok": False, "error": "无 %s" % os.path.basename(rp)}, 404)
                return self.send_text(open(rp, encoding="utf-8").read(), ctype="text/markdown; charset=utf-8")
            if path == "/verdicts":
                p = proj_key((q.get("project") or [""])[0])
                if not p:
                    return self.send_json({"ok": False, "error": "project 参数无效"}, 400)
                date = (q.get("date") or ["latest"])[0]
                date = latest_date(p) if date == "latest" else date
                vp = os.path.join(OUT, "verdicts-%s-%s.json" % (p, date))
                return self.send_json({"ok": os.path.exists(vp), "file": vp if os.path.exists(vp) else None,
                                       "verdicts": read_json(vp)})
            if path == "/jobs":
                with JOBS_LOCK:
                    return self.send_json({"ok": True, "jobs": [
                        {k: v for k, v in j.items() if k != "log"} for j in JOBS.values()]})
            if path.startswith("/jobs/"):
                jid = path.split("/", 2)[2]
                with JOBS_LOCK:
                    j = JOBS.get(jid)
                    if not j:
                        return self.send_json({"ok": False, "error": "无此任务"}, 404)
                    out = dict(j)
                    out["log_tail"] = out.pop("log")[-25:]
                return self.send_json({"ok": True, "job": out})
            return self.send_json({"ok": False, "error": "未知路径", "path": path}, 404)
        except BrokenPipeError:
            pass
        except Exception as e:  # 不让单次异常打挂服务
            return self.send_json({"ok": False, "error": "%s: %s" % (type(e).__name__, e)}, 500)

    def do_POST(self):
        if not self.check_token():
            return
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        path = u.path.rstrip("/")
        body = self.read_body()
        try:
            if path == "/inspect":
                p = body.get("project") or (q.get("project") or ["all"])[0]
                p = proj_key(p) or "all" if p != "all" else "all"
                days = str(body.get("days") or (q.get("days") or ["3"])[0])
                cmd = [os.path.join(SCRIPTS, "run_all.sh"), "--project", p, "--days", days, "--json"]
                if body.get("no_snapshot") or (q.get("no_snapshot") or ["0"])[0] == "1":
                    cmd.append("--no-snapshot")
                if body.get("no_diff") or (q.get("no_diff") or ["0"])[0] == "1":
                    cmd.append("--no-diff")
                if body.get("skip_collect") or (q.get("skip_collect") or ["0"])[0] == "1":
                    cmd.append("--skip-collect")
                jid = job_new("inspect", cmd)
                threading.Thread(target=job_run, args=(jid, cmd), daemon=True).start()
                return self.send_json({"ok": True, "job_id": jid, "cmd": cmd,
                                       "poll": "/jobs/%s" % jid}, 202)
            if path == "/verdicts/suggest":
                p = body.get("project") or (q.get("project") or ["all"])[0]
                p = proj_key(p) or "all" if p != "all" else "all"
                cmd = [os.path.join(SCRIPTS, "suggest_verdicts.py"), "--project", p]
                if body.get("date") or (q.get("date") or [None])[0]:
                    cmd += ["--date", str(body.get("date") or (q.get("date") or [""])[0])]
                if body.get("promote"):
                    cmd.append("--promote")
                rc, so, se = run_script(cmd, timeout=300)
                date = body.get("date") or (q.get("date") or [None])[0] or latest_date()
                return self.send_json({"ok": rc == 0, "returncode": rc, "stdout": so[-2000:],
                                       "stderr": se[-1000:],
                                       "candidates": {
                                           "verdicts": os.path.join(
                                               OUT, "verdicts-%s-%s.suggested.json" % (p, date))
                                           if p != "all" else "（all 时逐项目生成）",
                                           "checklist": [
                                               os.path.join(OUT, "判读候选-%s-%s.md" % (k, date))
                                               for k in (list(reg()) if p == "all" else [p])]}})
            if path == "/push":
                p = proj_key((q.get("project") or [""])[0] or body.get("project") or "")
                if not p:
                    return self.send_json({"ok": False, "error": "project 参数无效"}, 400)
                tag = body.get("tag") or (q.get("tag") or ["internal"])[0]
                dry = str(body.get("dry_run", (q.get("dry_run") or ["1"])[0])).lower() not in ("0", "false", "no")
                cmd = [os.path.join(SCRIPTS, "push.py"), "--project", p, "--tag", tag]
                if not dry:
                    # 真发送是高风险动作：本接口故意不支持，必须人工在命令行加 --send
                    return self.send_json({"ok": False,
                                           "error": "本接口只做 dry-run 预览；真发送请在命令行显式执行 push.py --send"}, 403)
                rc, so, se = run_script(cmd, timeout=120)
                return self.send_json({"ok": rc == 0, "dry_run": True, "returncode": rc,
                                       "stdout": so[-4000:], "stderr": se[-800:]})
            return self.send_json({"ok": False, "error": "未知路径", "path": path}, 404)
        except Exception as e:
            return self.send_json({"ok": False, "error": "%s: %s" % (type(e).__name__, e)}, 500)

    # ---------- 人看的首页 ----------
    def page_index(self):
        date = latest_date()
        rows = []
        for k in reg():
            s = summary_for(k, date)
            if not s.get("ok"):
                rows.append("<tr><td>%s</td><td colspan=5>无当日数据</td></tr>" % k)
                continue
            sev = s.get("severity") or {}
            rows.append(
                "<tr><td><b>%s</b><br><small>%s</small></td><td>%s</td><td>%s</td>"
                "<td>%s</td><td>%s</td><td><a href='/report?project=%s'>报告</a> · "
                "<a href='/findings?project=%s'>JSON</a></td></tr>" % (
                    k, s.get("label") or "", s.get("records"),
                    " / ".join("%s %s" % (a, b) for a, b in (s.get("status_dist") or {}).items()),
                    "<span style='color:#c00'>P0 %s</span> · P1 %s · P2 %s" % (
                        sev.get("P0", 0), sev.get("P1", 0), sev.get("P2", 0)),
                    "%s 条未判读" % s.get("unreviewed"),
                    urllib.parse.quote(k), urllib.parse.quote(k)))
        html = """<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<title>项目进度巡检接口</title><style>
body{font:14px/1.7 -apple-system,"PingFang SC",sans-serif;margin:32px;color:#222;background:#fff}
h1{font-size:20px} table{border-collapse:collapse;width:100%%;margin:16px 0}
th,td{border:1px solid #e5e7eb;padding:8px 10px;text-align:left;vertical-align:top}
th{background:#f6f8fa;font-weight:600} code{background:#f6f8fa;padding:2px 6px;border-radius:4px}
small{color:#666} ol{padding-left:20px}
</style></head><body>
<h1>项目进度巡检接口</h1>
<p>工作区 <code>%s</code> ｜ 最新巡检日期 <b>%s</b> ｜ 只监听本机</p>
<table><thead><tr><th>项目</th><th>表内条数</th><th>状态分布</th><th>信号</th><th>判读</th><th>查看</th></tr></thead>
<tbody>%s</tbody></table>
<h3>接口</h3><ol>
<li><code>GET /health</code> · <code>GET /projects</code> · <code>GET /summary</code></li>
<li><code>GET /findings?project=客户B</code>（结构化，程序消费）· <code>GET /report?project=客户B</code>（markdown）</li>
<li><code>POST /inspect {"project":"all","days":3}</code> → 后台跑一键巡检，返回 <code>job_id</code>；<code>GET /jobs/&lt;id&gt;</code> 查进度</li>
<li><code>POST /verdicts/suggest</code> → 生成判读候选（半自动，仍需人确认）</li>
<li><code>POST /push?project=客户B&tag=internal</code> → 卡片 <b>dry-run 预览</b>（真发送只能走命令行）</li>
</ol>
<p><small>本服务不提供「写线上表 / 发群」能力 —— 那两道门永远需要人工确认。</small></p>
</body></html>""" % (WS, date, "".join(rows))
        self.send_text(html, ctype="text/html; charset=utf-8")


def main():
    global WS, OUT, TOKEN
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1", help="默认只监听 127.0.0.1（改 0.0.0.0 请自担风险）")
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--workspace", default=None)
    ap.add_argument("--token", default=None, help="设置后 POST 接口需要 X-Token 头")
    a = ap.parse_args()

    WS = resolve_ws(a.workspace)
    if not os.path.isdir(os.path.join(WS, ".workbuddy")):
        print("✗ 工作区看起来不对：%s 下没有 .workbuddy/" % WS, file=sys.stderr)
        return 2
    OUT = os.path.join(WS, ".workbuddy", "巡检")
    TOKEN = a.token
    if a.host not in ("127.0.0.1", "localhost", "::1"):
        print("⚠ 你正在把服务暴露到 %s —— 本服务没有任何鉴权加固，建议只用 127.0.0.1" % a.host, file=sys.stderr)

    srv = http.server.ThreadingHTTPServer((a.host, a.port), Handler)
    print("巡检接口已启动: http://%s:%d/  （工作区 %s）" % (a.host, a.port, WS))
    print("按 Ctrl+C 停止。POST 需要 token：%s" % ("是" if TOKEN else "否"))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
    finally:
        srv.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
