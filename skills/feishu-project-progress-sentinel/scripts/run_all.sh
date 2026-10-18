#!/usr/bin/env bash
# 一键巡检：collect → snapshot → analyze → diff → 汇总
#
# 用法:
#   ./run_all.sh                          # 三项目，3 天窗口，含快照与 diff
#   ./run_all.sh --project 客户B --days 7  # 只跑客户B，7 天窗口
#   ./run_all.sh --json                   # 末尾输出单个 JSON（供接口/程序消费）
#   ./run_all.sh --skip-collect           # 只重算（已有当天 raw 时）
#   ./run_all.sh --no-snapshot --no-diff  # 最省时的最小跑
#
# 退出码: 0 全成功 / 1 有步骤失败 / 2 参数或环境错误
#
# 环境变量:
#   SENTINEL_WORKSPACE  工作区根（默认按脚本路径推导，可显式指定）
#   SENTINEL_PYTHON     python 解释器（默认自动挑 3.13）
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(dirname "$SCRIPT_DIR")"

# ---------- 工作区解析 ----------
WS="${SENTINEL_WORKSPACE:-}"
if [ -z "$WS" ]; then
  # 技能装在 <工作区>/.workbuddy/skills/ 下时，三层上去就是工作区
  CAND="$(cd "$SKILL_DIR/../../.." 2>/dev/null && pwd || true)"
  if [ -n "$CAND" ] && [ -d "$CAND/.workbuddy" ]; then WS="$CAND"; else WS="$(pwd)"; fi
fi
if [ ! -d "$WS/.workbuddy" ]; then
  echo "✗ 找不到工作区（$WS 下没有 .workbuddy/）。请用 SENTINEL_WORKSPACE=... 指定。" >&2
  exit 2
fi
export SENTINEL_WORKSPACE="$WS"
OUT_DIR="$WS/.workbuddy/巡检"
mkdir -p "$OUT_DIR"

# ---------- python 解释器 ----------
PY="${SENTINEL_PYTHON:-}"
if [ -z "$PY" ]; then
  for c in "$HOME/.workbuddy/binaries/python/versions/3.13.12/bin/python3" "$(command -v python3)"; do
    [ -x "$c" ] && PY="$c" && break
  done
fi
if [ -z "$PY" ] || ! "$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3,9) else 1)' 2>/dev/null; then
  echo "✗ 找不到可用的 python3" >&2
  exit 2
fi

# ---------- 参数 ----------
PROJECT="all"; DAYS="3"; SINCE=""
DO_COLLECT=1; DO_SNAPSHOT=1; DO_ANALYZE=1; DO_DIFF=1; AS_JSON=0
while [ $# -gt 0 ]; do
  case "$1" in
    --project|-p) PROJECT="${2:?}"; shift 2 ;;
    --days|-d)    DAYS="${2:?}"; shift 2 ;;
    --since)      SINCE="${2:?}"; shift 2 ;;
    --skip-collect) DO_COLLECT=0; shift ;;
    --no-snapshot)  DO_SNAPSHOT=0; shift ;;
    --no-analyze)   DO_ANALYZE=0; shift ;;
    --no-diff)      DO_DIFF=0; shift ;;
    --json)       AS_JSON=1; shift ;;
    -h|--help)    sed -n '2,20p' "$0"; exit 0 ;;
    *) echo "未知参数: $1" >&2; exit 2 ;;
  esac
done

DATE="$("$PY" -c 'import datetime;print(datetime.date.today().isoformat())')"
if [ -n "$SINCE" ]; then
  PREV_DATE="$("$PY" -c "import datetime;print((datetime.date.fromisoformat('$SINCE')-datetime.timedelta(days=1)).isoformat())")"
else
  PREV_DATE="$("$PY" -c "import datetime;print((datetime.date.today()-datetime.timedelta(days=$DAYS+1)).isoformat())")"
fi

LOG="$OUT_DIR/.run-${DATE}.log"
: > "$LOG"
say() { printf '%s\n' "$*" | tee -a "$LOG" >&2; }
FAILED=0
step() {  # step <名称> <命令...>
  local name="$1"; shift
  local t0=$(date +%s)
  say ""
  say "▶ ${name}"
  if "$@" >>"$LOG" 2>&1; then
    say "  ✓ ${name}  ($(( $(date +%s) - t0 ))s)"
  else
    say "  ✗ ${name} 失败（详见 ${LOG}）"
    tail -5 "$LOG" >&2
    FAILED=1
  fi
}

T_START=$(date +%s)
say "== 一键巡检 ${DATE} ==  项目=$PROJECT  窗口=$DAYS 天  工作区=$WS"

if [ "$DO_COLLECT" = 1 ]; then
  if [ -n "$SINCE" ]; then
    step "① 采集 collect" "$PY" "$SCRIPT_DIR/collect.py" --project "$PROJECT" --since "$SINCE"
  else
    step "① 采集 collect" "$PY" "$SCRIPT_DIR/collect.py" --project "$PROJECT" --days "$DAYS"
  fi
else
  say "① 采集 collect —— 跳过（--skip-collect）"
fi

if [ "$DO_SNAPSHOT" = 1 ]; then
  # snapshot_table.py 使用位置参数：<日期> [项目...]
  if [ "$PROJECT" = "all" ]; then
    step "② 表快照 snapshot" "$PY" "$SCRIPT_DIR/snapshot_table.py" "$DATE"
  else
    step "② 表快照 snapshot" "$PY" "$SCRIPT_DIR/snapshot_table.py" "$DATE" "$PROJECT"
  fi
else
  say "② 表快照 snapshot —— 跳过（--no-snapshot）"
fi

if [ "$DO_ANALYZE" = 1 ]; then
  step "③ 比对 analyze" "$PY" "$SCRIPT_DIR/analyze.py" --project "$PROJECT"
else
  say "③ 比对 analyze —— 跳过（--no-analyze）"
fi

if [ "$DO_DIFF" = 1 ]; then
  if [ "$PROJECT" = "all" ]; then
    step "④ 变化 diff（信号）" "$PY" "$SCRIPT_DIR/diff_findings.py" --old "$PREV_DATE" --new "$DATE"
    step "④ 变化 diff（消息）" "$PY" "$SCRIPT_DIR/diff_messages.py" --old "$PREV_DATE" --new "$DATE"
  else
    step "④ 变化 diff（信号）" "$PY" "$SCRIPT_DIR/diff_findings.py" --old "$PREV_DATE" --new "$DATE" "$PROJECT"
    step "④ 变化 diff（消息）" "$PY" "$SCRIPT_DIR/diff_messages.py" --old "$PREV_DATE" --new "$DATE" "$PROJECT"
  fi
else
  say "④ 变化 diff —— 跳过（--no-diff）"
fi

# ---------- ⑤ 回灌当天的人工判读（analyze 会用 raw 重建 findings，判读必须重新合并） ----------
if [ "$DO_ANALYZE" = 1 ]; then
  if [ "$PROJECT" = "all" ]; then REAPPLY_KEYS="客户B 客户A 客户C"; else REAPPLY_KEYS="$PROJECT"; fi
  for p in $REAPPLY_KEYS; do
    if [ -f "$OUT_DIR/verdicts-$p-$DATE.json" ]; then
      step "⑤ 回灌判读 $p" "$PY" "$SCRIPT_DIR/apply_verdicts.py" --project "$p" --date "$DATE"
    else
      say "⑤ 回灌判读 $p —— 无 verdicts-${p}-${DATE}.json，跳过"
    fi
  done
fi

# ---------- 汇总 ----------
export RUN_WS="$WS" RUN_DATE="$DATE" RUN_PROJECT="$PROJECT" RUN_PREV="$PREV_DATE" \
       RUN_FAILED="$FAILED" RUN_OUT="$OUT_DIR" RUN_JSON="$AS_JSON"
SUMMARY="$("$PY" - <<'PYEOF'
import json, os, glob
ws, date, proj = os.environ["RUN_WS"], os.environ["RUN_DATE"], os.environ["RUN_PROJECT"]
out = os.environ["RUN_OUT"]
keys = ["客户B", "客户A", "客户C"] if proj == "all" else [proj]
rep = {}
for p in keys:
    fj, rp = os.path.join(out, f"findings-{p}-{date}.json"), os.path.join(out, f"巡检报告-{p}-{date}.md")
    if not os.path.exists(fj):
        rep[p] = {"ok": False, "reason": "无当日 findings（采集或比对未成功）"}
        continue
    d = json.load(open(fj, encoding="utf-8"))
    sig = [s for s in (d.get("signals") or []) if not s.get("dismissed")]
    sev = {}
    for s in sig:
        sev[s.get("severity") or "?"] = sev.get(s.get("severity") or "?", 0) + 1
    rep[p] = {
        "ok": True, "label": d.get("label"), "as_of": d.get("as_of"),
        "generated_at": d.get("generated_at"),
        "records": (d.get("table") or {}).get("records"),
        "status_dist": (d.get("table") or {}).get("status_dist"),
        "table_age_days": (d.get("table") or {}).get("table_age_days"),
        "signals_total": len(sig), "severity": sev,
        "unreviewed": sum(1 for s in sig if not s.get("verdict")),
        "headline": (d.get("conclusion") or {}).get("headline"),
        "report": rp if os.path.exists(rp) else None,
    }
summary = {
    "ok": os.environ["RUN_FAILED"] == "0",
    "date": date, "prev_date": os.environ["RUN_PREV"], "project": proj,
    "workspace": ws, "out_dir": out,
    "reports": {p: (os.path.join(out, f"巡检报告-{p}-{date}.md")
                   if os.path.exists(os.path.join(out, f"巡检报告-{p}-{date}.md")) else None) for p in keys},
    "projects": rep,
}
print(json.dumps(summary, ensure_ascii=False, indent=1))
PYEOF
)"
printf '%s\n' "$SUMMARY" > "$OUT_DIR/run-${DATE}.json"

say ""
say "== 完成（$(( $(date +%s) - T_START ))s，失败步骤: ${FAILED}）=="
[ "$AS_JSON" = 1 ] && printf '%s\n' "$SUMMARY"
if [ "$AS_JSON" = 0 ]; then
  printf '%s\n' "$SUMMARY"
fi
exit "$FAILED"
