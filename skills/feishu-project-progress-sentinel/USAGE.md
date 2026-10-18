# 项目巡检哨兵 · 使用说明

> 面向人看的操作手册。技能本身的规则与踩坑记在 [`SKILL.md`](SKILL.md)。
> 覆盖项目：**客户A / 客户B / 客户C**。产出默认落 `<工作区>/.workbuddy/巡检/`。

---

## 0. 一分钟上手

```bash
cd "<WORKSPACE>/.workbuddy/skills/feishu-project-progress-sentinel/scripts"
./run_all.sh                                # ① 跑完一整轮巡检（约 1–4 分钟，取决于采集）
python3 suggest_verdicts.py --project all   # ② 出判读候选
# ③ 打开 .workbuddy/巡检/判读候选-<项目>-<日期>.md 过一遍，把不对的改掉
#     确认方式二选一：改 .suggested.json 内容后去掉文件名里的 .suggested
#     或直接 python3 suggest_verdicts.py --project <项目> --promote
./run_all.sh --skip-collect --no-diff       # ④ 回灌判读（十几秒，产出终版报告）
```

一句话：**一键跑 → 判读候选 → 人工确认 → 回灌**。写线上表和发群消息**不在本工具范围内**，永远要人工。

---

## 1. 三种用法

### 1.1 命令行一键（最常用）

```bash
./run_all.sh                                  # 三项目，3 天窗口
./run_all.sh --project 客户B --days 7          # 单项目、7 天窗口
./run_all.sh --since 2026-09-14               # 指定起点（跨周复盘用）
./run_all.sh --skip-collect --no-diff         # 已有当天数据，只重算（~13 秒）
./run_all.sh --json                           # 末尾输出 JSON（给程序/管道消费）
```

参数全表：

| 参数 | 作用 |
|---|---|
| `--project all\|客户B\|客户A\|客户C` | 项目范围，默认 `all` |
| `--days N` / `--since YYYY-MM-DD` | 采集窗口，二选一，默认 `--days 3` |
| `--skip-collect` | 跳过采集（已有当天 raw 时用） |
| `--no-snapshot` / `--no-analyze` / `--no-diff` | 跳过对应步骤 |
| `--json` | 末尾把汇总 JSON 打到 stdout |

- 每日汇总：`.workbuddy/巡检/run-<日期>.json`
- 逐步日志：`.workbuddy/巡检/.run-<日期>.log`（出问题先看它）
- 退出码：`0` 全成功 / `1` 有步骤失败 / `2` 参数或环境问题
- 工作区自动推导，换机器时用 `SENTINEL_WORKSPACE=/path/to/工作区`；解释器用 `SENTINEL_PYTHON=` 覆盖

### 1.2 半自动判读（把「逐条读」变成「勾选」）

```bash
python3 suggest_verdicts.py --project all              # 出候选（含群消息检索）
python3 suggest_verdicts.py --project 客户B --no-hub    # 不查数据仓，更快
python3 suggest_verdicts.py --project 客户B --promote   # 确认后直接落成正式 verdicts
```

它自动替你翻两处：**本地交付物**（各项目 `项目资料/`、`工具/`、`产物/`）和**数据仓群消息**。

产出两张：

| 文件 | 给谁看 |
|---|---|
| `判读候选-<项目>-<日期>.md` | **你**。每条列候选判读 + 置信度 + 证据，勾一遍即可 |
| `verdicts-<项目>-<日期>.suggested.json` | 程序。结构与正式 verdicts 一致，改完去掉 `.suggested` 就是正式件 |

确认后回灌：

```bash
python3 apply_verdicts.py --project 客户B --date 2026-09-21
# 或者直接 ./run_all.sh（它会自动检测并回灌当天判读）
```

> ⚠️ **判读必须落盘**：`analyze.py` 每轮都从 raw 重建 findings，不写 `verdicts-<项目>-<日期>.json` 就会白做。
> `--promote` 会覆盖正式件，旧文件自动备份为 `.bak`。

### 1.3 本地接口（给程序 / 看板 / 机器人用）

```bash
SENTINEL_WORKSPACE=<WORKSPACE> python3 api_server.py            # 127.0.0.1:8787
python3 api_server.py --port 8899 --token mysecret                        # POST 需 X-Token 头
```

浏览器直接打开 `http://127.0.0.1:8787/` 就是一块看板：三项目状态分布 + 未判读数 + 报告链接。

---

## 2. 接口速查

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/` | 看板首页（人看） |
| GET | `/health` | 健康检查（工作区、最新巡检日期） |
| GET | `/projects` | 项目与数据源登记 |
| GET | `/summary[?date=YYYY-MM-DD]` | 各项目汇总（条数/状态分布/信号分级/未判读数/一句话结论） |
| GET | `/findings?project=客户B[&date=latest]` | **结构化 findings（程序消费用这个）** |
| GET | `/report?project=客户B[&date=latest]` | 巡检报告 markdown 原文 |
| GET | `/verdicts?project=客户B` | 当天已确认的判读 |
| POST | `/inspect` | 后台跑一轮巡检，立即返回 `job_id` |
| GET | `/jobs` · `/jobs/<id>` | 任务状态 + 日志尾 |
| POST | `/verdicts/suggest?project=` | 生成判读候选 |
| POST | `/push?project=客户B&tag=internal` | 卡片**预览**（永远 dry-run） |

复制即用：

```bash
BASE=http://127.0.0.1:8787

# 今天三个项目的概况
curl -s "$BASE/summary" | python3 -m json.tool | head -40

# 只看客户A的 P0
curl -s "$BASE/findings?project=客户A" \
  | python3 -c 'import sys,json;d=json.load(sys.stdin)["findings"];
print("\n".join(f"{s[\"no\"]} {s[\"severity\"]} {s[\"title\"][:30]} | {s.get(\"verdict\") or \"未判读\"}" for s in d["signals"] if s.get("severity")=="P0"))'

# 触发一轮巡检（异步）
JID=$(curl -s -X POST "$BASE/inspect" -H 'Content-Type: application/json' \
      -d '{"project":"all","days":3}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["job_id"])')
curl -s "$BASE/jobs/$JID" | python3 -c 'import sys,json;j=json.load(sys.stdin)["job"];print(j["status"]);print("\n".join(j["log_tail"][-8:]))'

# 卡片预览（不发）
curl -s -X POST "$BASE/push?project=客户C&tag=internal" | python3 -m json.tool
```

带 token 时统一加 `-H 'X-Token: mysecret'`。

---

## 3. 产出文件一览

目录：`<工作区>/.workbuddy/巡检/`

| 文件 | 说明 |
|---|---|
| `raw-<项目>-<日期>.json` | 采集原始数据（群消息 / 云文档 / 日历 / 妙记） |
| `table-snapshot-<项目>-<日期>.json` | 线上表逐条快照（次日 diff 的基线） |
| `findings-<项目>-<日期>.json` | **结构化比对结果**（含信号、结论、focus、待办） |
| `巡检报告-<项目>-<日期>.md` | 人看的报告 |
| `verdicts-<项目>-<日期>.json` | 当天人工判读（**必须落盘**） |
| `verdicts-*.suggested.json` | 判读候选（未确认） |
| `判读候选-<项目>-<日期>.md` | 判读勾选清单 |
| `run-<日期>.json` | 一键流程汇总（三项目一张表） |
| `cards/` | 卡片 JSON（`card-<项目>-<日期>-<tag>.json`） |

---

## 4. 三条红线（不要绕过）

1. **本工具不写线上表、不发群消息。** 回写表走 `feishu-project-table-sync`；发卡片必须人工加 `--send`。
   接口层的 `/push` 传 `dry_run=0` 会直接返回 403 —— 这是故意的。
2. **对外卡片用 `--tag client`，且只用白名单替换。** 内部决策块、任务分工里的负责人一律不得擅自改。
3. **接口只监听 `127.0.0.1`。** 改 `--host 0.0.0.0` 会打警告；服务没有额外鉴权加固，别往公网放。

另外两条业务口径（写进 SKILL.md 的铁律）：

- **判「逾期未动」前必须查本地交付物** —— 「线上逾期 + 群里没动静」≠ 没做，可能是**已交付但没回写**。
- **改「计划开始 / 计划完成」是改承诺**，比改状态敏感。客户方负责人的条目**一律不擅自改**，只列「现值 → 建议值」给人处理。

---

## 5. 常见问题

| 现象 | 原因与处理 |
|---|---|
| 报告里某项目「无当日数据」 | 采集或比对失败 → 看 `.run-<日期>.log`；单独重跑 `python3 collect.py --project <项目> --days 3` 再 `analyze.py` |
| 判读写好了但报告里没有 | 没跑 `apply_verdicts.py`；`run_all.sh` 会自动做，手搓步骤时容易忘 |
| 判读候选里证据看着不相关 | 置信度低/中就是提示"要人工核"。可在 `.suggested.json` 里直接改 `verdicts` 段，或删掉该条 |
| 抄送的人 @ 不到 | 实施表里人员字段为空或跨租户未登记别名 → 补 `references/people.local.json` 或 `projects.json` 的 `sender_aliases` |
| 某个群扫不到 | 受限群（`231203 Restricted Mode`）无解；在报告里注明数据源缺口，别当成"没发生" |
| 接口调不通 | 确认服务在跑（`curl 127.0.0.1:8787/health`）；POST 带 `--token` 时要加 `X-Token` 头 |
| 中文搜不到群消息 | `hub.db` 的 FTS5 是 trigram，**2 字词**（回款/验收/发票）走 LIKE 回退，已内置 |

---

## 6. 挂自动化

现有自动化：**工作日 08:30** 跑 `all` + 3 天窗口，只汇报不落手。
需要改成别的窗口/时间，或用接口触发（`POST /inspect`），复用同一套脚本即可，不要把步骤散到别处。

---

## 7. 换机器怎么恢复

技能目录 `.workbuddy/skills/**` 与项目记忆 `.workbuddy/memory/**` 已入库，克隆仓库即可恢复。
**凭据不入库**：`references/secrets.local.json`（webhook）需手工补一份，缺失时脚本会自动降级。
