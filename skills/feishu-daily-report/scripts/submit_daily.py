#!/usr/bin/env python3
"""把本地日报草稿提交到飞书多维表格（日报表）。

用法:
  python3 submit_daily.py --file 日报/2026-09-10_本人日报.md --date 2026-09-10 --time 22:00 [--dry-run]

草稿格式约定（与 SKILL.md 一致）:
  ## 今日工作总结
  ...
  ## 明日工作计划
  ...

依赖: 本机已安装并登录 lark-cli（--as user）。
"""
import argparse
import json
import re
import subprocess
import sys

DEFAULT_BASE = "<TOKEN>"
DEFAULT_TABLE = "<TABLE_ID>"

FIELD_TODAY = "今日工作总结"
FIELD_TOMORROW = "明日工作计划"
FIELD_DATE = "日报提交日期"


def parse_sections(md_text):
    """按 '## ' 二级标题切分，返回 {标题: 正文}。"""
    sections = {}
    cur = None
    buf = []
    for line in md_text.splitlines():
        m = re.match(r"^##\s+(.+?)\s*$", line)
        if m:
            if cur is not None:
                sections[cur] = "\n".join(buf).strip()
            cur = m.group(1).strip()
            buf = []
        elif cur is not None:
            buf.append(line)
    if cur is not None:
        sections[cur] = "\n".join(buf).strip()
    return sections


def pick(sections, keyword):
    for k, v in sections.items():
        if keyword in k:
            return v
    return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", required=True, help="本地日报草稿 .md 路径")
    ap.add_argument("--date", required=True, help="日期，如 2026-09-10")
    ap.add_argument("--time", default="22:00", help="提交时间 HH:MM，默认 22:00")
    ap.add_argument("--base-token", default=DEFAULT_BASE)
    ap.add_argument("--table-id", default=DEFAULT_TABLE)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    with open(args.file, encoding="utf-8") as f:
        sections = parse_sections(f.read())

    today = pick(sections, "今日工作总结")
    tomorrow = pick(sections, "明日工作计划")
    if not today:
        sys.exit("ERROR: 草稿里没找到 '## 今日工作总结' 段落")
    if not tomorrow:
        print("WARN: 没找到 '## 明日工作计划' 段落，该列将留空", file=sys.stderr)

    payload = {
        "create_records": [
            {
                FIELD_TODAY: today,
                FIELD_TOMORROW: tomorrow,
                FIELD_DATE: f"{args.date} {args.time}",
            }
        ]
    }

    cmd = [
        "lark-cli", "base", "+record-batch-create",
        "--base-token", args.base_token,
        "--table-id", args.table_id,
        "--json", json.dumps(payload, ensure_ascii=False),
        "--as", "user",
    ]
    if args.dry_run:
        cmd.append("--dry-run")

    proc = subprocess.run(cmd, capture_output=True, text=True)
    out = proc.stdout or ""
    print(out[:1500] or proc.stderr[:1500])
    if proc.returncode != 0:
        sys.exit(proc.returncode)

    try:
        data = json.loads(out)
    except Exception:
        sys.exit("ERROR: 无法解析 lark-cli 返回，请人工检查")

    if not data.get("ok"):
        sys.exit("ERROR: 提交失败: " + json.dumps(data, ensure_ascii=False)[:500])

    if args.dry_run:
        print("DRY-RUN OK —— 未写入。去掉 --dry-run 即真正提交。")
        return

    rec_ids = (data.get("data") or {}).get("record_id_list") or []
    print("SUBMITTED record_id:", ", ".join(rec_ids) or "(未返回)")
    for rid in rec_ids:
        print("  回读: lark-cli base +record-get --base-token %s --table-id %s "
              "--record-id %s --format json --as user" % (args.base_token, args.table_id, rid))


if __name__ == "__main__":
    main()
