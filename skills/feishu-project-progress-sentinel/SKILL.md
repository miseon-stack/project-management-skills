---
name: feishu-project-progress-sentinel
description: 项目进度巡检哨兵——定期扫描群聊/云文档/**会议妙记（智能纪要+待办）**等数据源，与线上实施表比对差异，输出分级预警（P0/P1/P2）、给客户的沟通建议与下一步行动，并把已完成事项生成群内话术与存档材料（共识留痕）。触发场景：用户说"巡检一下项目""扫一遍进度""检查项目表和实际的差异""有什么风险和预警""下一步该怎么跟客户说""把刚做的事生成群话术/存档共识""定期帮我看项目""扫一下数据更新/检查变化""卡片推送到 webhook/推给测试群/**改成客户可转发的对外版**"，「**做成项目周报（≤500 字）/周报推给我**」，或要求对客户A/客户B/客户C三个项目的进展做差异核对与决策辅助。含十四个可直接跑的脚本（**一键 run_all.sh** / **半自动判读 suggest_verdicts.py** / **本地接口 api_server.py** / 采集 collect.py（群消息+文档+日历+**妙记**）/ 比对 analyze.py / **人工判读 apply_verdicts.py** / 变化对比 snapshot_table.py+diff_findings.py+diff_messages.py / 话术与存档 group_msg.py / 卡片推送 push.py / 人员同步 sync_people.py）、项目×数据源登记册、决策与话术手册、**卡片对外化白名单规范**。默认只读产出：回写线上表与发送卡片消息都需单独授权。
agent_created: true
---

# 项目进度巡检哨兵

## ⚠️⚠️ 先决条件：飞书命令必须使用有权限的用户身份

本 skill 的所有 `lark-cli` 调用**必须使用拥有目标群组与多维表格权限的用户身份**（`--as user`）。
默认的应用/机器人身份对实施表会返回 `91403` 权限错误，且只能看到极少数群组。
巡检脚本里所有 `lark-cli` 调用**必须补 `--as user`**。
若你的环境需要多套身份，可在 lark-cli 中配置具名 profile 并显式指定（凭据文件自行保管，勿入库）。
报 91403 或 user 身份 missing → 重跑 `lark-cli auth login --as user --no-wait --json --domain all`
+ 扫码 + `--device-code`（详见 `feishu-project-table-sync`）。

一眼看清「表里写的」和「实际发生的」差多少，并告诉你**该做什么、该怎么跟客户说**。

## 铁律

1. **只读优先。** 本 skill 的产出是**差异清单 + 预警 + 建议 + 话术草稿**。回写线上表走 `feishu-project-table-sync`，发群消息必须用户确认——本 skill 不自动做这两件事。
2. **三张实施表全部按「客户可见」处理**（客户A / 客户B / 客户C）。对外措辞是硬约束，不是风格偏好。
3. **不发明事实。** 差异必须带证据（群消息原句 / 文档段落 / 记录号）。找不到证据的写「待确认」，不写成结论。
4. **线上是唯一事实源。** 一切以当次实读的线上表为准，不信本地 md 快照。
5. **跟踪范围 = 客户A、客户B、客户C。** 客户D / 其他客户非主责，不主动扫。
6. ★**判「逾期未动」前必须先查本地交付物（2026-09-20 教训）。** 「线上日期过了 + 群内没动静」**不等于没做** —— 可能是**已交付但没写进表**。动笔前先翻：各项目 `项目资料/`（方案 md、客户版文档）、`工具/`（脚本）、`产物/`。客户C T06 考勤报表就是这样：线上停在 9/12 逾期 8 天、群内无动作，实际我方方案 + 客户版 + 导入脚本 + 多维表格样板**早已交付**，只是没回写 → 误判成「没做」。**本地无交付物 + 群内无动静**才能写「逾期未动」。
7. ★**改「计划开始 / 计划完成」属于改承诺，比改状态更敏感（2026-09-20 立规）。** 三张实施表的排期是双方共识：
   - **负责人是我方**的条目，可提建议但**仍要用户点名才落库**；
   - **负责人是客户方**的条目（客户B大量任务负责人 = 客户方负责人），**一律不擅自改**，只列「现值 → 建议值」清单交用户人工处理 / 与客户同步后统一改；
   - 输出重排提案时**必须打上归属列**（我方 / 客户方），用户才能一眼看出哪些能自己定。


## 目录结构

```
scripts/collect.py    采集：群消息 + 云文档（纪要/方案）+ 日历 + **会议妙记** → raw-<项目>-<日期>.json
scripts/analyze.py    比对：线上表 × raw → findings-*.json + 巡检报告-*.md
scripts/apply_verdicts.py  ★ 把人工判读合并进 findings 与报告（保住判读，不被下次 analyze 覆盖）
scripts/sync_people.py ★ 从各表「人员」字段自动收拢 open_id↔姓名 → references/people.local.json
scripts/snapshot_table.py ★ 实读三表 → 逐条快照 table-snapshot-<项目>-<日期>.json（次日 diff 的基线）
scripts/diff_findings.py ★ 对比两日 findings：信号增删/级别变动/focus/各清单计数
scripts/diff_messages.py ★ 对比两日 raw：列出新增群消息（原始事实增量）
scripts/group_msg.py  输出：群内话术草稿 + 存档材料（共识留痕）
scripts/push.py       推送：巡检结果 → 飞书消息卡片（webhook / lark-cli 双通道，默认 dry-run）
scripts/run_all.sh    ★ 一键：采集→快照→比对→diff→回灌判读→汇总（run-<日期>.json）
scripts/suggest_verdicts.py ★ 半自动判读：翻本地交付物 + 群消息 → 判读候选（人只确认）
scripts/api_server.py  ★ 本地 HTTP 接口（127.0.0.1:8787，只读为主 + 异步巡检）
scripts/common.py     公共库（lark-cli 调用、记录解析、日期、人员、@ 渲染用的 id 映射）
references/projects.json  项目 × 数据源登记册（base/table/群 oc/字段名）——**不含凭据，可入库**
references/secrets.local.json  机器人 webhook 等凭据 ——**不入库**（.gitignore 排除），缺失时功能降级
references/people.local.json   ★ open_id↔姓名映射（来自实施表人员字段，是姓名不是凭据，可入库）
references/team.json      我方成员名单（用于区分客户方发言）
references/playbook.md    ★ 决策建议规则 + 对外话术模板 + 存档共识做法
```

**本 skill 双位置同步**（2026-09-17 用户要求）：项目级
`<工作区>/.workbuddy/skills/feishu-project-progress-sentinel/`（随 GitHub 备份）
与用户级 `~/.workbuddy/skills/feishu-project-progress-sentinel/` **各放一份，改完必须互相同步**
（`rsync -a --delete 项目级/ 用户级/` 即可；secrets.local.json 不要带去用户级也行，凭据以项目级为准）。

产出默认落在 **`<工作区>/.workbuddy/巡检/`**。

---

## 快速开始（最短路径）

```bash
# ★ 一键（推荐）：采集 → 表快照 → 比对 → 变化 diff → 回灌当天判读 → 汇总
cd "<WORKSPACE>/.workbuddy/skills/feishu-project-progress-sentinel/scripts"
./run_all.sh                       # 三项目 + 3 天窗口；末尾打印 / 落一份 JSON 汇总
./run_all.sh --project 客户B --days 7 --json
./run_all.sh --skip-collect --no-diff          # 已有当天 raw 时只重算，十几秒

# 分步（要单跑某一步时才用）
python3 collect.py --project all --days 3      # 采集（约 1 分钟）
python3 analyze.py  --project all              # 比对出报告
# 报告：<工作区>/.workbuddy/巡检/巡检报告-<项目>-<日期>.md
# ★ 判读落盘后再合并（见下文「三步」）：先写 verdicts-<项目>-<日期>.json
python3 apply_verdicts.py --project 客户A   # 人工判读写进 findings + 报告
python3 group_msg.py --project 客户B --items items.json --kind both   # 话术 + 存档
python3 push.py --project 客户B                          # 生成卡片预览（不发送）
python3 push.py --project 客户B --send                   # 真发到该项目的机器人群
```

路径不固定时用 `cd "$(dirname …)"` 或直接写绝对路径；`common.py` 里 `DEFAULT_WORKSPACE=<WORKSPACE>`。

已挂自动化：**工作日 08:30** 自动跑 `all` + 3 天窗口，只汇报不落手。

## 一键入口 / 半自动判读 / 接口层（2026-09-21 新增）

> 人看的操作手册（常用命令、接口 curl 示例、排错表）在 [`USAGE.md`](USAGE.md)；本节只讲设计取舍与坑。

巡检原来要按顺序敲 4–5 条命令、判读全靠人逐条读。现在这三件事都补齐了：

### ① `run_all.sh` —— 一条命令跑完

```bash
./run_all.sh [--project all|客户B|客户A|客户C] [--days N | --since YYYY-MM-DD]
             [--skip-collect] [--no-snapshot] [--no-analyze] [--no-diff] [--json]
```

步骤与顺序（**顺序不能换**）：`collect → snapshot_table → analyze → diff_findings /
diff_messages → apply_verdicts（自动回灌当天判读）→ 汇总`。

- **为什么末尾要自动回灌判读**：`analyze.py` 是拿 raw **重建** findings，当天已确认的判读会被冲掉；
  `run_all.sh` 检测到 `verdicts-<项目>-<今天>.json` 就自动 `apply_verdicts` 合并。
- 汇总落 `<工作区>/.workbuddy/巡检/run-<日期>.json`；带 `--json` 时把同一份 JSON 打到 stdout（给接口/程序消费）。
- 逐步日志落 `.workbuddy/巡检/.run-<日期>.log`；某步失败不中断整轮，退出码 `1`（全成功 `0`，参数或环境错 `2`）。
- 工作区自动推导（技能装在 `<工作区>/.workbuddy/skills/` 下时三层上去就是工作区），也可
  `SENTINEL_WORKSPACE=...` 显式指定；解释器用 `SENTINEL_PYTHON=...` 覆盖。
- ⚠️ **shell 坑（踩过一次）**：`$VAR）` 这种「变量紧跟全角括号」会被 bash 当成变量名的一部分
  （报 `FAILED\uXXXX: unbound variable`）→ 中文文案里引用变量一律写 `${VAR}`。

### ② `suggest_verdicts.py` —— 判读只做确认，不从零判断

```bash
python3 suggest_verdicts.py --project all            # 出候选
python3 suggest_verdicts.py --project 客户B --no-hub  # 不查数据仓群消息
python3 suggest_verdicts.py --project 客户B --promote # 确认后直接落成正式 verdicts（旧文件自动备份 .bak）
```

对每条未判读信号自动给出**候选判读 + 置信度 + 证据**，产出：

- `verdicts-<项目>-<日期>.suggested.json`（结构与正式 verdicts 一致，改完去掉 `.suggested` 即可用）
- `判读候选-<项目>-<日期>.md`（人看的勾选清单，逐条列证据）

它自动做两件原来必须人工做的事：**翻本地交付物**（`项目资料/`、`工具/`、`产物/`、`日报/`）与
**翻数据仓群消息**（`hub.db` LIKE 检索，默认 14 天窗口）。

判读规则（信号类型 × 归属 → 候选）：

| 信号类型 | 归属 | 候选判读 |
|---|---|---|
| `overdue` | 我方 + 本地有强命中交付物 | **疑似已完成未回写 · 待确认**（确认后改状态） |
| `overdue` | 我方 + 本地无命中 | 逾期属实 · 我方条目（本地无交付物）→ 给完成日或顺延 |
| `overdue` | 客户方 + 群内有动作 | 逾期属实 · 客户方条目（近期有动作）→ 催办即可 |
| `overdue` | 客户方 + 无动作 | 逾期属实 · 客户方条目 → 统一核对 |
| `no_progress` | 本地有产出 | **已有产出未回写** → 补一句进展 |
| `due_soon` / `blocked` / `stale_table` | —— | 规则型判定，**不挂证据**（挂上是噪音） |

★ **证据分级与假阳性（实测调了 4 轮，别退回旧参数）**：

1. **硬排除「自产分析物」** —— `巡检报告-`/`findings-`/`verdicts-`/`判读候选-`/`全量差异核对`/
   `D类逾期重排提案`/`会议摘要汇编`/`周会`/`提案`/`评估`/`复盘`/`汇总`/`周报`/`日报/`/`/归档/`/`README.md`
   等一律不作证据 —— **否则会把我方自己写的巡检报告当成交付物**（第一轮就踩到：T08 的证据竟是自己那份「全量差异核对」）。
2. **路径分级权重**：`项目资料/`、`工具/` = 交付物（×1.0）；`产物/` ×0.7；**`会议纪要/`、`群聊资料/` ×0.4
   （只能证明"会上说过"，不能证明"做完"）**；`产物/归档|数据|被@待办` 整个目录不扫。
3. **弱词门槛**：标题按 2 字滑窗切词会产生「维表」「阅会」这类跨词假词 → **只看弱词时必须命中 ≥3 个不同词**；
   命中 `strong`（≥3 字词块 / ≥4 位英文）按 ×3 加权；文件名含任务编号 +4。
4. **置信度封顶**：若前两条证据全是「会议记录」，置信度**最高只能到「中」** —— 只靠会议纪要撑不起
   「疑似已完成」。

判读落盘口径不变：候选 → 人确认（改 `.suggested.json`，或在 `判读候选-*.md` 上批注后照改）
→ 正式 `verdicts-*.json` → `apply_verdicts.py`（`run_all.sh` 会自动做最后这步）。

### ③ `api_server.py` —— 把巡检暴露成本地接口

```bash
SENTINEL_WORKSPACE=<WORKSPACE> python3 api_server.py   # 127.0.0.1:8787
python3 api_server.py --port 8899 --token mysecret                # POST 需 X-Token 头
```

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/` | 人看的首页：三项目状态分布 + 未判读数 + 报告链接 |
| GET | `/health` | 健康检查（工作区、项目、最新巡检日期） |
| GET | `/summary[?date=]` | 各项目汇总（有 `run-<date>.json` 直接用，否则现算） |
| GET | `/findings?project=客户B[&date=latest]` | 结构化 findings（**程序消费用这个**） |
| GET | `/report?project=客户B[&date=latest]` | 巡检报告 markdown 原文 |
| GET | `/verdicts?project=客户B` | 当天已确认的判读 |
| POST | `/inspect {"project":"all","days":3}` | 后台跑 `run_all.sh` → 立即返回 `job_id` |
| GET | `/jobs`、`/jobs/<id>` | 任务状态 + 日志尾（采集要 1 分钟以上，必须异步） |
| POST | `/verdicts/suggest?project=` | 生成判读候选，返回清单路径 |
| POST | `/push?project=客户B&tag=internal` | 卡片**预览**（dry-run） |

★ **接口层的红线（不要为了"完整"放开）**：

- **只监听 `127.0.0.1`**。改 `--host 0.0.0.0` 会打警告 —— 服务没有额外鉴权加固，只适合本机 / 内网可信环境。
- **`/push` 永远只 dry-run**：传 `dry_run=0` 直接返回 403，真发送必须人工在命令行执行 `push.py --send`。
- **接口里没有「写线上表」**：那是 `feishu-project-table-sync` 的职责，且需用户点名授权。
- `/verdicts/suggest` 的 `promote=true` 会覆盖正式 verdicts（自动备份 `.bak`）—— 只在人已确认候选时用。

**能被谁调用**：妙搭应用、多维表格 / 仪表盘的外部数据源、你自己的看板、其他 Agent（`curl` / `fetch`），
或后续在群内加「@机器人 巡检」的机器人（需要一台常驻进程的机器，配合 `--token` 收口）。


## 标准流程

### 0. 确认范围与窗口

| 参数 | 默认 | 说明 |
|---|---|---|
| 项目 | 用户指定 | `客户B` / `客户A` / `客户C` / `all` |
| 窗口 | 今天 −3 天 → 今天 | **上次巡检之后再没跑过就往前放**；跨周建议 7 天 |
| 表停更阈值 | 3 天 | 超过即 P0 |

### 1. 采集

```bash
cd "<WORKSPACE>/.workbuddy/skills/feishu-project-progress-sentinel/scripts"
python3 collect.py --project 客户B --since 2026-09-15
python3 collect.py --project all --days 7 --max-docs 10
python3 collect.py --project 客户A --since 2026-09-14 --no-docs   # 只要群消息，快
```

- 群消息走**原生 API**（`im +chat-messages-list` 在本机必然因缺 scope 失败，已在脚本内绕开）。
- 云文档 = 群消息里出现的 docx/wiki 链接 + 按项目关键词搜到的纪要/方案，各取前 N 篇。
- **会议妙记 = 独立通道，不能漏**（2026-09-18 补）：
  `minutes +search --participant-ids me --start … --end …` 按「我参与 + 时间窗」拉妙记，
  再用标题匹配 `search_keywords` 过滤，然后 `minutes +detail --summary --todo --keyword` 取 AI 摘要与**结构化待办**（带负责人、带完成态）。
  - ⚠️ **妙记不在云空间**：`drive +search` 搜不到、群消息里也常没人贴链接 —— 只靠前两条通道会**整场会议的结论与分派全部丢失**（2026-09-18 实测：9/10–9/18 共 14 场会全部漏采）。
  - ⚠️ `minutes` 子命令会先往 stdout 打 `[minutes +detail] querying …` 日志行，`C.lark()` 只认首字符是 `{` 的输出会直接判失败 → 用 `_lark_raw()`（找第一个 `{` 再 parse）。
  - 妙记待办是**结构化**产出，比从文本里猜准得多，`analyze` 里已让它整体优先于其他待办候选。
  - `--no-minutes` 可关掉；会议刚结束时妙记可能还没生成，下一轮巡检才会补上（正常现象，报告里别当成缺口）。
- 有群读不到（受限群 231203 / 无权限）脚本会打 ⚠️，**要在报告里写明数据源缺口**，不要假装覆盖完整。

### 2. 比对 + 预警

```bash
python3 analyze.py --project 客户B                    # 自动找当天 raw
python3 analyze.py --project all --stale-days 3
```

产出 `findings-<项目>-<日期>.json` 与 `巡检报告-<项目>-<日期>.md`。

### 2.5 看变化（「扫一下数据更新 / 检查变化」标准动作，2026-09-18 起）

用户说「扫一下数据更新」「看看有什么变化」「和昨天比变了什么」时，跑这套**日增量对比**：

```bash
cd scripts
# ① 采集必须与前一份 raw 同窗口 —— 先读前一天 raw 的 window.since
python3 -c "import json;print(json.load(open('<巡检目录>/raw-<项目>-<昨日>.json'))['window'])"
python3 collect.py --project 客户A --since <昨日 raw 的 since>   # 逐项目对齐
python3 analyze.py --project all
# ② 逐条快照（建立基线，供明天 diff）
python3 snapshot_table.py 2026-09-18
# ③ 两类 diff
python3 diff_findings.py --old 2026-09-17 --new 2026-09-18
python3 diff_messages.py --old 2026-09-17 --new 2026-09-18
```

- **`diff_messages` 是「数据更新」的事实来源**：`diff_findings` 只反映信号口径变化，真正的进展（客户定角色、会期敲定、验收口径松动）都在新增消息里。先看 diff_messages，再用 diff_findings 交叉验证。
- **窗口不一致 = 假消失** ⭐ 最容易踩：昨天用 `--days 7`、今天用 `--days 2`，会出现一堆「消失信号」（new_requirement / risk_words / todo_candidates 计数暴跌），其实是消息掉出窗口。**每次对比前对齐 since**。
- **父行跳过会造成「预警盲区」**：父行（有子记录引用）只进 index、不产信号，所以**父行自身逾期会静默不报**（客户A T04 实例：`计划完成 9/04` 逾期 14 天、「进行中」，一旦被挂上子记录就再不预警）。发现"某条信号莫名消失但记录还在"时先查 `父记录` 字段，是父行就说明被规则跳过 —— 需要时在报告里单独提示，**不要当成进度更新**。
- `diff_findings` 的 ✅ 输出规范：把变化拆成「表内变化（状态/计划日/进展）」「群内事实增量」「信号增删」三段给用户，不要只贴脚本文本。

**脚本能自动识别的信号**

| kind | 含义 | 级别 |
|---|---|---|
| `stale_table` | 整张表停更 ≥ N 天 | P0 |
| `blocked` | 状态含「阻塞 / 待确认」 | P0 |
| `overdue` | 计划完成已过、状态未完成（≥3 天升 P0） | P0/P1 |
| `due_soon` | ≤3 天内到期仍未完成 | P1 |
| `completion_candidate` | 群消息出现**完成**迹象、表内仍非完成态 | P1 |
| `status_delta` | 群消息出现**启动/进行/启用/阻塞**实况、表内状态不符 | P0(阻塞)/P1 |
| `new_requirement` | ★ 客户方群消息里**要新东西**、表内无对应任务 | P1 |
| `no_progress` | 最新进展为空（**仅「进行中」**） | P1/P2 |

状态差异（4/5/6 三类）统称「**实况与表内不符**」，卡片上单列一段「🔄」并附证据行 —— **只给证据不自动改状态**，人工核实后走 verdicts 落盘。

另外产出四张「人工判读」清单：**表内可能缺录 / 客户新增需求(new_requirements) / 风险词命中 / 待办候选 / 客户侧最后发言距今**。

**★ 子项目层级（2026-09-17 客户B起用「父记录」字段）**：表内行分两种 ——
- **父行（有子记录引用它）= 子项目汇总行**：只进 index（供缺录/新增需求匹配），**不产任何逐任务信号**（否则"进展空缺/状态差异"全是噪声）。聚合产出 `findings.subprojects = [{no,title,status,total,done,doing,blocked,pct,children[]}]`。
- **子行**：正常参与全部信号检测。
- 卡片新增「📦 子项目进度」区块：每个子项目一行 `T02 知识库迁移与搭建　3/5 子任务完成 · 进行中 2`。
- ⚠️ 父行的状态是人工维护的汇总口径，**不与子任务自动校验**；子项目下的风险仍看子行信号。

**状态差异的两条精度约束（2026-09-17 实测踩出，改代码别放松）**：
1. **只看群消息，不看文档** —— 方案/交接清单里的「待客户确认」会被反复引用，造成文档自证式误报（客户A T57/T67 实例）。
2. **重合阈值 ≥3 个 2-gram** —— 2 个太松，「全员功能使用培训」会命中「云打印功能的客户B使用」这种不相干消息。
`new_requirement` 同理：只收**客户方**的群消息（我方自己人讨论不算），带内部商务词（收费/报价/人天/合同/付款/成本/钱/预算/发票/请款）的一律排除。

### 3. ★ Agent 必须补的三步（脚本给不了）

脚本只做机械比对，**以下必须由你（模型）完成，不能省**：

1. **逐条核实 `completion_candidate`** —— 脚本命中后，翻到该群**最后一轮对话**，找**客户方那句正面反馈**（「谢谢，很清晰」「已经可以用了」）。找到 → 建议改「已完成」；找不到 → 不动，只在报告里标待确认。
   ⚠️ **这类信号误报率很高**：脚本是按"完成类关键词 + 该编号在原文出现过"匹配的，很容易把**同一段整体汇报**同时命中到多条任务上。客户A 2026-09-17 的 2 条全部是误报（一条实际属于 T53、一条实际属于 T69）。
2. **裁定 `missing_candidates`** —— 逐条判断「要不要进表」：
   - 进：客户可感知的交付/配置/集成事项；
   - 不进：内部资源、成本、商务、催款、我方投入量。
   形成 `拟新增 N 条` 的清单交用户，**不自动新建**。
3. **写决策建议** —— 读 `references/playbook.md` 的 A 表，把每条 P0/P1 落成「动作 + 负责人 + 期限」，并按「客户能感知优先」排序。报告里的 `suggestion` 只是模板句，要**结合本项目上下文重写**成能直接执行的话。

**判读必须落盘**，否则下次 `analyze.py` 会把结论冲掉。写 `<scratch>/verdicts-<项目>-<日期>.json`，再 `apply_verdicts.py` 合并：

```json
{
  "reviewed_at": "2026-09-18 15:05",
  "method": "逐条翻群聊原文找正面证据；找不到即判误报，不改线上状态",
  "conclusion": {"headline": "…", "points": ["…"], "actions": ["…"]},
  "focus": [
    {"no": "T09", "title": "工单功能评估与一期落地", "meta": "今天到期 · 计划 09-18",
     "current": "…", "next": "…"}
  ],
  "dismiss_kinds": ["new_requirement"],
  "req_summary": {"count": 0, "names": [], "status": "本轮无有效新增需求"},
  "verdicts": {
    "T57": {"verdict": "逾期属实 · 「疑似已完成」系误报",
            "dismiss_kinds": ["completion_candidate"],
            "note": "命中证据实为 T53；真实情况是仍在调试"},
    "T04": {"verdict": "确认逾期 · 卡客户侧试测", "note": "交接清单：…"}
  },
  "extra_findings": [{"title": "客户新增 X 诉求", "note": "…"}]
}
```

```bash
python3 apply_verdicts.py --project 客户A
```

- `verdicts` 按**任务编号**索引，会写到该编号的**所有**信号上；条目内的 `dismiss_kinds` 精确指定哪些信号类型算误报。
- **顶层的 `dismiss_kinds`（2026-09-18 新增）= 整类剔除**，专门用于**没有编号**的信号。`new_requirement` 的 `no` 恒为 `None`，按编号写 verdicts 永远命中不了 —— 群聊里的过程片段（吐槽、玩笑、追问）被抽成需求时，只能整类剔。剔完**务必同步改 `req_summary`**（见下），否则卡片仍会渲染「🆕 新增诉求」区块。
- `focus` 支持**覆盖 + 新增**（2026-09-18 起）：
  - 覆盖：脚本 focus 里的同编号条目，`title/meta/current/next` 按你写的替换（每次巡检最该做的一件事）。
  - 新增：脚本 focus 只取 P0 逾期前 5 条，**人工判定今天必须处理但未入选的**（如今天到期的 `due_soon` 项）写进 `focus` 即可插到最前。新增条目的 `owners` 从同编号 signal 继承，`meta` 缺省自动算「超期 N 天 · 计划 MM-DD」，也可手写。
- `req_summary` 给了就整段覆盖 —— 整类剔除 `new_requirement` 后**必须**同步设 `count: 0` / `names: []`，否则卡片还留着需求块。
- `dismiss_kinds` 命中的信号会带 `dismissed: true` → **卡片计数自动剔除，但报告里保留**（说明为什么不是问题）。
- `conclusion` 给了就整段覆盖脚本的自动结论 —— 卡片上的「AI 判断」直接用它，所以判读一次、报告与卡片口径自动一致。
- `extra_findings` 用来记脚本抓不到的发现（客户新诉求、会期与计划日不一致等），会追加到报告末尾。

### 4. 生成话术与存档材料

先写 `items.json`（只放**真的做完、且客户认可**的事）：

```json
{
  "date": "2026-09-17",
  "items": [
    {"no": "T108", "title": "AI 输出置信度与关键字段校验规则",
     "fact": "规则口径已梳理完成，覆盖 6 个核心字段",
     "deliverable": [{"name": "《置信度与字段校验规则 v1》", "url": "https://…"}]}
  ],
  "next_steps": ["9/18 前完成第二轮验证"],
  "asks": ["请客户方负责人确认需保留的核心字段清单"],
  "evidence": ["9/17 11:02 客户方负责人：这个规则可以，就按这个来"],
  "archive_title": "客户B · 9/17 进展同步"
}
```

```bash
python3 group_msg.py --project 客户B --items items.json --kind both
```

- `--kind group` 出群话术；`archive` 出存档材料（含「本期完成 / 下一步 / 需确认 / 共识证据 / 未闭环项」五段）。
- 脚本会用**对外红线词表**自检（付款/催款/商务/内部记录号…），命中会返回 `redline_hits` —— **有命中必须改掉再给用户**。
- 交付物链接**贴进消息前先核实标题**：`lark-cli drive +inspect --url <url>` → `data.title`。

### 5. 交付与收尾

- 把 `巡检报告-*.md` 和话术草稿呈现给用户（`present_files`），**明确列出待确认项**。
- 用户确认后才执行：回写线上表（`feishu-project-table-sync`）/ 发群消息（`lark-cli im`，@ 人需带 `ou_` 提及结构）。
- 存档材料按项目规范落到 `<项目目录>/会议纪要/` 或 `项目资料/`，并更新该项目的 `README.md` 要点。

---

## 已知坑（都已在脚本内处理，改脚本时注意）

| 坑 | 表现 | 处理 |
|---|---|---|
| 群消息命令不可用 | `missing required scope(s): im:message.reactions:read` | 一律走 `lark-cli api GET /open-apis/im/v1/messages` |
| `--output` 路径限制 | 绝对路径报 `unsafe output path` | 脚本固定 `cwd=<scratch>/.scratch` + 相对文件名 |
| ndjson 结构 | 字段扁平在行对象上，不在 `fields` 里 | 直接 `r["字段名"]` |
| `--jq` 与 ndjson 不兼容 | `--jq does not support ndjson` | 先落盘再用 Python 解析 |
| 受限群 | 报错码 `231203` | 脚本记 ⚠️ 并在报告标注缺口 |
| zsh 不做词分割 | `set -- $spec` 在 zsh 里拿不到 $2 | 脚本内全用 Python，不依赖 shell 拆参 |
| 表无「最后更新时间」字段 | 客户A / 客户C没有 | 退化为从「最新进展」文本抠最大日期 |
| 完成/进行中判定 | 各表 status 选项名不同 | 走 `done_values` / `blocked_values` 配置，不要硬编码 |
| **表结构漂移** | 字段被改名/改类型/删掉重建，脚本静默读到空值 | `schema_check()` 每次比对前查一遍；字段对不上 → 发 P0 并**先修配置再跑** |
| **人员字段名带类型后缀** | 客户B表里字段叫 `负责人 (人员 )`（含空格），按 `'负责人'` 取值恒为 `None`，会误判「负责人全空」 | 实读字段名再断言，别凭印象；配置里优先用 **field_id**（客户B `<FIELD_ID>`）而非名称。发现字段名带空格/括号时，先 `field-list` 打印全部 name，再决定匹配方式 |
| **「未登记字段」噪声** | `schema_new_fields` 把模板自带的字段全报一遍 | 新项目接入时把**全部字段名**登记进 `fields`（键名随意，值用线上原名），否则每次必报 P2。客户A 19 个字段已于 2026-09-17 全登记 |
| **同一任务在卡片里出现两遍** | 一条任务同时命中「逾期」+「疑似已完成」，P0/P1 各列一次（客户C T56 出现两次、客户B T20 跨组重复） | `_merge_signals()` 把同一编号合成一条、描述并进 `_mates`（渲染成 `状态「待确认」 · 超期 5 天 · 计划 09-12`）；`_dedup_by_no()` 让 P1 跨组只出现一次 |
| **「进展空缺」噪声淹掉真问题** | 所有任务的「最新进展」为空都报 P1，12 条里有 9 条其实是**未开始**的任务（本来就没进展） | `no_progress` 只对**「进行中」**且进展为空报 P1，其余降 P2；P2 只在卡片上给一行计数 |
| **误报进了卡片计数** | 判读说「是误报」，卡片上仍写着「疑似已完成未回写 2」 | `apply_verdicts.py` 用 `dismiss_kinds` 打 `dismissed: true`；`push.py` 的 P1 分组自动剔除 |
| **「停更 −1 天」** | 表无「最后更新时间」字段时，从「最新进展」文本抠日期，可能抠到**前瞻日期**（如「9/18 启动会」） | `push.py` 只在 `table_age_days > 0` 时才显示停更天数；报告里照实显示表内日期 |
| **补登别名后名字还不生效** | 改完 `projects.json` 的 `sender_aliases`，卡片仍写「外部成员(abc123)」 | 显示名统一在 **analyze 阶段**用 `sender_id` 反查 `load_people()` → 补登别名后**重跑 analyze 即可**，不用重跑 collect |
| **客户方负责人写不进人员字段？** | 以为 Base 人员字段只能放本租户成员，于是把客户方负责人降级写进「协作方」文本 | **跨租户成员可以写**：`lark-cli contact +search-user --query <姓名>` 拿 open_id（返回 `is_cross_tenant: true` 且 `department` 是客户公司名即是客户租户的人）→ 用 `[{"id": "<ou_...>"}]` 写入即可，回读正常。客户C T66 负责人 = 任海滨 `<OPEN_ID>` 已实测通过 |
| **写 Base 时字段名取不到值** | 用中文名当 key，遇到「负责人 (人员 )」这类**带空格/后缀**的字段名恒为 None | 写库一律优先用 **field_id** 当 key（`+field-list` 先实读）；同样的坑在 `analyze.py` 读快照时也存在 |
| 人员字段名带空格/全角括号 | 客户B是 `负责人 (人员 )`（带空格），客户C 9/18 已改名为纯 `负责人`，客户A是 `飞书方负责人` | 逐字照抄线上字段名，不要"顺手规范化"；**改名后必须同步 `projects.json`**，否则报 `schema_drift` |
| **回写后回读：`+record-get` 参数是 `--record-id`（单数），不是 `--record-ids`** | 传 `--record-ids` 报 `unknown flag`；且 `+record-get` 的输出结构与 `record-list` 不同，按 `data.records` 取会得到 0 条 | 回读最稳的做法是**重跑 `snapshot_table.py` 再 diff 旧快照**：既能核验又能同步基线（2026-09-23 客户B 11 条实测） |
| **`+record-batch-update` 静默不校验** | 响应只返回 `record_id_list`，字段名写错/选项名不存在都不报错 | 写库 key 一律用 **field_id**（`fld...`）；datetime 传 `"2026-09-24 00:00"`，select 传数组；写完**必须回读核验** |
| **改「计划完成」前先分清归属** | 负责人=客户方（客户B大量条目是客户方负责人/汤忠冬）的日期改动是**改客户承诺** | 客户方条目**只列不改**；我方条目的顺延也要用户点名后才落库（2026-09-23 用户「全部更新…在项目表」= 明确授权，才执行 11 条） |

## ⚠️ 表结构漂移的识别与处理（2026-09-17 客户B / 2026-09-18 客户C 两例）

三张实施表**客户和同事都能编辑**，结构变更是常态。**同一个套路已发生两次**：

| 日期 | 项目 | 发生了什么 |
|---|---|---|
| 09-17 | 客户B | 原「任务编号」（自动编号）被**重建**，旧字段转文本并成为主字段「任务标题」，**编号体系 T64–T110 整体重排为 T01–T42**，另有 9 条记录标题退回成编号文本 |
| 09-18 | 客户C | 同款：原「任务编号」→ 转 text 主字段**「任务名称」**（20 条全空，随后按用户要求回填），新增 auto_number**「编号」**，**编号 T51–T70 重排为 T01–T20**（旧 T51→T01 … T64→T14、T65→T15 … T70→T20）；同时 `负责人 (人员 )`→**`负责人`**、`协作方`→**`协作人`**（同名同 id，仅改名），14 条老记录的「客户C方任务」也被补齐 |

**关键判断：先分清是谁改的。**
- **负责人本人主动调整** → 这是**基线更新**，不是事故：立刻改 `references/projects.json` 的字段名/field_ids，补全字段登记，登记映射表，然后把残留数据（如退回的标题）按最新口径补齐。
- **他人/来源不明改动** → 当事故处理：产出差异清单与映射表交用户，**拿到授权再动手**。

**每次巡检固定动作：**

1. **跑 `schema_check`**（analyze.py 已内置）——登记字段名找不到、field_id 变化 → P0/P1 信号。
2. **发现编号重排，立刻产出「旧编号 ↔ 新编号 ↔ 标题」映射表**，并写明是主动调整还是未知来源。
3. 引用线上记录（备注、群消息、任务描述）**优先用标题或 record_id，少用编号**。
4. `schema_drift` 报「找不到字段」时，**先 `+field-list` 实读原始字符**（`repr()` 打印）——多数是**改名**（改了空格/后缀/同义词），不是删除重建；改名只需改 `projects.json` 的 `fields`，**不要**去动线上。

## 遇到「字段/编号漂移」时的处理顺序

1. `+field-list` 实读 → 与 `references/projects.json` 的 `fields` / `field_ids` 对齐；
2. 全表回读，逐条比对**同名不同值**的行，定位被覆盖/退回的数据；
3. 产出映射表 + 差异清单交用户；
4. **拿到授权后**再补写（补写用 record_id 定位，不用编号）。

## 消息卡片推送（`scripts/push.py`）

把巡检结果推成飞书卡片。**默认 dry-run**：只生成卡片 JSON 落到 `<scratch>/cards/`，不发送；
`--send` 才会真发 —— 发消息是外部动作，**必须先取得用户明确授权**。

**两条通道**

| 通道 | 用法 | 身份 | 适用 |
|---|---|---|---|
| A. Webhook（推荐，每项目一个机器人） | 凭据放 `references/secrets.local.json`；`push.py --project 客户B --send` | 该群自定义机器人 | 定点群推送，无需 OAuth scope |
| B. lark-cli 直发 | `push.py --project 客户B --chat oc_xxx --send`（或 `--user ou_xxx`） | 默认 `bot`；`--as user` 需 `im:message.send_as_user` 授权 | 临时换群 / 私聊；bot 需在目标群内 |

**凭据取值优先级**：`--url` ＞ 环境变量 `SENTINEL_WEBHOOK_<项目名>` ＞ `references/secrets.local.json` ＞ `projects.json`。
`projects.json` 里的 `webhook` 恒为 `null`，**必须保持为 null** —— 该文件要进 git（本仓用 `.gitignore` 白名单放行 `.workbuddy/skills/**`），凭据只能放 `secrets.local.json`（已被排除）。
换机器恢复时需**手工补一次** `secrets.local.json`，或临时用环境变量 / `--url` 代替。

**两种口径**

| `--tag` | 内容 | 用途 |
|---|---|---|
| `internal`（默认） | P0 明细 + P1 分类计数 + 客户沉默天数 + 待判读清单（缺录/风险词/待办） | 内部跟进群 |
| `client` | 只写「待确认完成情况 N 项 + 计划完成日 + 请协助确认」，无内部措辞、无内部人名判断、无风险词 | 客户群 / 客户可见场合 |

**铁律**：① 默认 dry-run，`--send` 需授权；② 推到客户群一律用 `--tag client`；③ webhook 是凭据，不要写进对外文档或截图；④ 卡片只是提醒，**回写线上表仍需单独授权**；⑤ **Webhook 通道发出即不可撤回**（返回体不含 `message_id`）；CLI 通道会返回 `message_id`，必要时可删除。所以推之前**先确认目标群与口径**，别边试边发。

其它参数：`--text "..."` 发纯文本；`--top N` 控制 P0 明细条数；`--url` 临时覆盖 webhook。

**跨租户成员名字**：客户方 open_id 在通讯录查不到（`contact +search-user --user-ids` 返回空数组），会显示成 `外部成员(xxxxxx)`。
把已知的人登记进 `projects.json` → `sender_aliases`（open_id → 名字，优先级高于 `people_index`），卡片与报告就会显示真名。

### 卡片设计规范（2026-09-17 五轮迭代后定稿 v6「行动通知」）

演进史：v1 报告塞一个 div → v2 修层次 → v3 去折叠/补判断/点到人 → v4 条目化 → v5 真实 @ + 实况差异/新增需求区块 → **v6 定位升维：卡片是「行动通知」，完整分析在报告页**。核心目标 = 项目成员进群 **30 秒**看懂「今天最需要推进什么、谁负责、哪里有风险、下一步做什么」。

| 段 | 写法 | 要点 |
|---|---|---|
| 抬头 | `{项目短名} · 项目巡检` + `{日期} {巡检时刻} · {N} 项任务` | 标题只留 `label` 第一段 |
| **总览（口径必须自洽）** | 四格 column_set：`**2**\n🔴 必须处理` / `**4**\n🟠 重点跟进` / `**10**\n🟡 低优先` / `11/31\n✅ 已完成` | ★ 四个数字与后文各区块**严格对得上**：🟠 = 「其他重点跟进」条数（P1 去 req 去重后），🟡 = 「低优先问题」计数。不写 `background_style`（卡片 1.0 兼容） |
| 分流 | `进行中 8 · 未开始 12 · 已完成 11` | 停更只在 >0 天时显示 |
| **🎯 今天优先处理（核心区）** | 每项五行块：`**T04 · 标题**` ⏎ `<at id=ou_..></at>` ⏎ `超期 **13** 天 · 计划 09-04` ⏎ `当前：等待客户重新试测` ⏎ `→ 今天确认评估结论…`；末尾一条 `**🆕 新增需求整理**` 汇总项 | 数据来自 `findings.focus`（`analyze.py → build_focus()` 自动生成 P0 结构化条目；**verdicts.focus 可按 no 覆盖 current/next/meta** —— 人工判读的表述更准，优先用人工的）。成员不用读上下文就能直接干活 |
| **📅 近期关键节点** | `09-18 · T66 · 组建双方项目组团队　表内「进行中」`，差异节点带 `⚠️ T67 表内计划日 10/03 与 9/18 启动会存在差异，建议确认计划口径` | 来自 `findings.key_nodes`：3 天内到期任务 + 里程碑任务（启动会/上线/验收…，**过期的不列**）+ 实况差异预警。每条**补表内状态**（v6.1，一眼看出哪个节点没启动）；上限 8 条；同编号去重但 **warn 必须保留**（挂在已有节点上） |
| **🟠 其他重点跟进 · N** | 一行一条带描述与负责人（v6.1）：`　T66 · 临期 · 计划 09-18 · 👤 CSM负责人、客户接口人`；`　T07 · 进展空缺（进行中未填最新进展） · 👤 同事、客户IT负责人`；实况差异写成 `T12 · 实况不符（群内「已完成」/表内「未开始」） · 👤 …` | **条目不能只是干巴巴的类型词**（用户反馈"太抽象"）：临期带计划日、进展空缺带当前状态、逾期带超期天数；负责人用 **👤 纯文本名字不发 @ 提醒**（次要信息不扰人，真 @ 只保留在核心区）。超过 8 条截断 |
| **🆕 新增诉求 · N** | `产品能力 3 · 流程能力 1 · 系统集成 1 · 协作事项 1` ⏎ `主要涉及：清除记忆 / 审批流 / …` ⏎ `当前状态：尚未发现对应项目任务` ⏎ `→ 今天确认范围、优先级及是否立项` | ★ **AI 归类，不堆原话**。分类规则 `REQ_CATS`（系统集成→流程→协作→产品 兜底）；涉及点 `_req_names()` 从原话提取能力关键词；`verdicts.req_summary` 可整体覆盖 |
| **🟡 低优先问题 · N** | `本次不展开，详见完整巡检报告` | 折叠，只给计数 |
| 收尾 | `[打开项目表] [查看完整巡检]` + note | 第二个按钮仅在 `projects.json` 配了 `report_url`（完整巡检的在线地址）时出现；note：`自动巡检 · 请各负责人核对名下任务状态 · 回写线上表需单独授权` |

**★ v6 硬约束 —— 过程信息不进卡片**：「缺录候选 25 / 风险词 12 / 待办候选 20 / 误报阈值收紧 / 🤖判断 / 💬客户最近发言」这类**系统运行状态与分析中间结果**一律不出现在群卡片，只进完整巡检报告。群里只出现**已形成明确判断、可以执行**的结论。这是「行动通知 vs 自动总结机器人」的分界线。

**★ emoji 红线（2026-09-22 用户明确要求）**：卡片里**只允许颜色 emoji（🔴🟠🟡🟢）**，其余 emoji 一律禁用（🎓📊🔐🆕⏰👤🎯📅 全部不许出现）—— 项目线状态用颜色点标识即可。定稿前自检：`[ch for ch in json.dumps(card,ensure_ascii=False) if ord(ch)>0x1F000 and ch not in set('🔴🟠🟡🟢')]` 应为空。

**其它硬约束**：元素总数 ≤ 14；`--top 0` 默认全列；表头 template `P0>0 → orange` 否则 `blue`；`wide_screen_mode: true`。

**「查看完整巡检」按钮的工作流**：在 `projects.json` 配 `report_url`（飞书云空间的原生 md 文件链接）。做法：`lark-cli markdown +create --name "巡检报告-<项目>-最新.md" --file ./巡检报告-<项目>-<日期>.md --as user` 建一次，之后**每天巡检后用 `markdown +overwrite --file-token <token>` 覆盖同一文件** —— 链接永远不变，卡片按钮不用改。注意 `--file` 只接受相对路径（cd 到巡检目录再跑）。

**@ 到人的实现与边界（v5 新增，用户 2026-09-17 明确要求）**：
- `_at(s)` 渲染负责人：**人员字段 cell 自带 open_id**（`[{'id':'ou_xxx','name':'张三'}]`）→ `analyze.py` 把它解析进 `s.owners=[{id,name}]`，卡片用 lark_md `<at id=ou_xxx></at>` 真实 @；文本负责人字段靠 `name_to_id()` 反查（people.local.json > people_index > sender_aliases），查不到才退化 `👤 名字`。
- **`sync_people.py` 每次巡检后跑一次**：从三张表的人员字段收拢 open_id↔姓名 → `references/people.local.json`。跨租户客户成员（通讯录查不到）的真名与 @ 全靠它 —— 客户A方客户管理员/客户IT负责人/同事/同事/客户接口人/同事等 18 人就是这么覆盖的。
- ⚠️ @ 是**真实提醒**（对方会收到通知）。往**客户群**推 `--tag client` 时同样会 @ 客户方负责人 —— 推之前把卡片内容给用户过目。
- ⚠️ **@ 客户方在内部群等于白发**（2026-09-18 客户B实例）：8 条 P0 里 4 条负责人是客户方（客户方负责人），内部群卡片 `<at id=ou_客户>` 只会显示名字、不产生通知。**卡片通知只对我方负责人有效**，对客户方的催办必须另走项目群消息或电话。判断方法：`findings.signals[].owners` 的 id 在不在本租户通讯录里（跨租户查不到，`contact +search-user` 返空数组即为外部成员）。

### 手工卡片对外化（要转发到客户群时必做，2026-09-18 立规）

巡检卡片用 `--tag client` 自动降口径；但**手工卡片**（如「任务分工草稿待确认」）要转发到客户群时，必须人工改一版，规则如下。

**只做这 5 类改动（白名单）**：

| # | 改什么 | 内部版 → 对外版 |
|---|---|---|
| 1 | 删内部块 | 删除「待你拍板 N 点」「是否新增/是否合并/阶段归属/客户方是否进负责人」等只能内部看的决策项 |
| 2 | note 中性化 | `草稿未写入线上 · 回复「提交」再落库 · 本卡片仅供预览` → `以上由双方会议共识整理 · 如有调整请在群内直接回复 · <日期>` |
| 3 | 标题/头色 | `新增任务草稿待确认`（orange）→ `项目任务分工与推进计划`（blue）；不出现「草稿」「待确认」「内部」字样 |
| 4 | 视角措辞 | `飞书方 / 客户C方` → `飞书侧 / 客户C侧`；`卡点是…` → `关键前提：…` |
| 5 | 单位/口径 | 去掉内部编号以外的内部术语；金额、日期、人名与表内保持一致 |

**⛔ 硬禁：不得顺手改未授权的任务字段。** 2026-09-18 客户C实例：用户只要求改 T66 负责人，第一版脚本却把 T65 负责人、T69/T70 协作方一并"优化"了 —— 对外物里这类擅自改动等于替客户改分工。
**正确做法**：以**用户已确认的那份 JSON** 为输入做**白名单字符串替换**，不要重新手写内容；脚本末尾**逐条打印每条任务的负责人**，你肉眼核对只有授权项发生变化，再发送。
推荐脚本形态：`tmp/<项目>_card/rebuild_client.py`（读原 JSON → 白名单替换 → 自检打印 → `--send`）。

**webhook 载荷**：必须包成 `{"msg_type": "interactive", "card": {...}}`，**裸卡片 JSON 会被拒**（`push.py` 生成的文件已自带这层包装，手工造的卡片要自己加）。

**能力边界**：webhook 自定义机器人**只能放跳转按钮**（`url`），**不能做「一键确认」回调**（`card.action.trigger` 需要应用机器人 + 事件订阅）。所以对外卡片的收尾只能是「请在群内回复」，别承诺点按钮即回写。

**发送前必做**：① 内部词残留自检（`待你拍板/草稿/未写入线上/落库/预览` 命中数应为 0）；② 确认目标群；③ webhook 发出**不可撤回**（返回体无 `message_id`）。

**口径提醒**：`internal` 卡片是**项目级回顾**，收件人包含团队其他成员（我方项目组）。所以：① 每项任务必须带负责人；② 不要用"误报""脚本初判"这类只有我方看得懂的审计措辞，改写成中性表述（如"逐条核实后仍在推进，状态无需调整"）；③ 涉及商务/付款/内部投入量的措辞一律不出现。

**改版前的排查顺序**：用户说"不好看/老样子"时，先**对比两张已认可的卡片 JSON**（结构同构 → 说明不是渲染降级，而是内容排布或文案问题），再动版式。不要盲改代码。

### ★★ 表格类卡片一律走「图片化」，不要用原生 table（2026-09-23 修正）

> **实测结论：卡片 2.0 的原生 `table` 组件在本人的飞书客户端上不渲染。**
> 2026-09-23 私聊推了一张含 2 个 `table` 的卡片，用户侧看到的是：
> `table` 的位置显示**「暂时无法在飞书文档外展示此内容」**，而**同一张卡片里的 `markdown` 标题、`hr` 分隔线正常显示**。
> 排查过程：① 逐字段对照 `lark-cli skills read lark-im/references/card/components/table.md`，写法完全合规；② 发送接口返回 `ok`，有 `message_id`；③ 换 `width_mode: fill`、减列数均无效。
> → 是**客户端渲染能力**问题，命令侧无法修复。**不要再用 `table` 组件做交付卡片。**

**兜底方案（已验证可用）：把表格渲染成 PNG，用卡片 `img` 元素承载。**

```bash
# 1. 渲染（脚本已备：scripts/card_table_image.py，复制后改 ROWS 数据）
python3 scripts/card_table_image.py          # → img-owner.png / img-stage1.png

# 2. 上传拿 image_key（bot 身份；--file 要相对路径，先 cd）
lark-cli im images create --as bot --data '{"image_type":"message"}' --file ./img-owner.png

# 3. 卡片里用 img 元素
# {"tag":"img","img_key":"img_v3_xxx","scale_type":"fit_horizontal","preview":true,
#  "alt":{"tag":"plain_text","content":"说明文字"}}
```

硬规则与坑：

| 项 | 事实 |
|---|---|
| 上传限制 | 宽 **≤1500px**、高:宽 **≤16:9**、≤10M。逻辑宽固定 1500，脚本会自检比例并打 ✗ |
| 截图前必须先量高 | Chrome `--screenshot` 按视口截。页面尾部放 `<div id="__sz">`，加载时把 `document.body.scrollHeight` 写进去，`--dump-dom` 读出来再按精确高截 |
| 看门狗 | macOS 上 Chrome headless 写完文件**不退出**；判据是「目标文件非空」+ `sleep 1.5` 落盘 + `kill -9` |
| 字号 | 图片在卡片里被缩到 ~600px 宽（0.4×）。正文 **19px** / 表头 **20px** / 大标题 34px 才够看，点开可放大 |
| 列宽 | `table-layout: fixed` + 百分比；**短列（模块/负责人）必须 `white-space: nowrap`**，否则「销售周报AI方案」会断成两行 |
| 分组 | 相邻同模块行用 `rowspan` 合并首列 + 浅色底，一眼看出分组 |
| ★坑 | 「圆点」用的颜色 class（`d-red` 是 background 红）**不能套到整格** —— 第一版把「国庆前」整格刷成大红色。底色要用独立 class（`g-now`/`g-later`） |
| 卡片其他元素 | `markdown` / `hr` 显示正常，可继续用来写标题、角色关系、灰色脚注 |

### ★ 责任到人卡片（@ 具体负责人）—— 2026-09-23 定稿

用户说「卡片里需要直接 @ 具体负责人，让大家知道谁负责什么」时用这节。

- **at 语法**：卡片 `markdown` 元素内 `<at id=ou_xxx></at>`；批量 `<at ids=id1,id2></at>`；`<at id=all></at>`（需群主开权限）。
- **★每人一个独立 markdown 元素。** 多人拼在同一个 markdown 里时，`<at>` 紧跟在上一个**列表末尾**会被吸进同一行
  —— 实测读回是 `…配合 MCP 技术验证@客户IT负责人(ou_…)`；拆成独立元素后完全正常（每人 = 人名行 + 其下 bullet）。
- **发完必须验证**：`im +messages-mget --message-ids om_xxx --as bot`，看返回的 **`mentions[]`**。
  飞书把 at 解析成 `[{id, key, name}]` —— **`name` 能反查出人名 = 该 open_id 有效**。5/5 全中才算过。
- **跨租户人员照样能 at**：客户A的客户管理员/客户IT负责人/客户方接口人都能正常解析。
  ⚠️ 但 `contact +get-user` 查他们会报 **41050 no user authority error**（通讯录权限不足），
  **这不代表 open_id 无效**，别被误导去改 id。
- **open_id 从哪拿**：`飞书数据仓/data/people.csv`（340 人，带 open_id）。
  **同租户内 open_id 跨应用一致**（实证：团队负责人的 people.csv 值 == 会议纪要 cite 的 user-id == bot `+get-user` 查得到的值）。
  常用：本人 `<OPEN_ID>`、团队负责人 `<OPEN_ID>`。
- 文案：禁用非颜色 emoji（用户原稿里的 📌/👤 要拿掉），侧别用颜色点分组（🟠 客户侧 / 🟢 飞书侧）。

### 存档：卡片 2.0 原生 `table` 的写法（现仅作语法参考，勿用于交付卡片）

用户要「像 table 列一样对齐」的卡片时，**卡片 1.0 做不到** —— 1.0 没有边框，`column_set` 逐行拼出来的"表格"在飞书里是浮动文字流，行高参差、列宽压不住（2026-09-22 客户A日报连改 v2/v3/v7 三版都被否）。原生 `table` 组件语法上是正解（真表头、真分列、真行高），**但在用户客户端渲染不出来**（见上）。语法留档如下：

```json
{
  "schema": "2.0",
  "config": {"update_multi": true, "width_mode": "fill"},
  "header": {"template": "indigo",
    "title": {"tag":"plain_text","content":"项目日报"},
    "subtitle": {"tag":"plain_text","content":"9/22 周二 · 全员动态"}},
  "body": {"elements": [
    {"tag":"markdown","content":"**1** 逾期 ｜ **2** 到期"},
    {"tag":"hr"},
    {"tag":"table","page_size":10,"row_height":"auto",
     "columns":[
       {"name":"who","display_name":"成员","data_type":"text","width":"110px","horizontal_align":"left","vertical_align":"top"},
       {"name":"today","display_name":"今日工作","data_type":"text","width":"auto","horizontal_align":"left","vertical_align":"top"},
       {"name":"tmrw","display_name":"明日安排","data_type":"text","width":"auto","horizontal_align":"left","vertical_align":"top"}],
     "rows":[{"who":"张三 · 交付","today":"…","tmrw":"…"}]},
    {"tag":"markdown","content":"<font color='grey'>…（⚠️ 2.0 不支持 note 标签，实测报 230099 unsupported tag note；脚注用灰色 markdown）</font>"}
  ]}
}
```

坑（都实测过）：

| 坑 | 事实 |
|---|---|
| 2.0 用 `body.elements`，元素标签是 `markdown`/`hr`/`table`/`note` —— **不是** 1.0 的 `div`+`lark_md` | 混用会报解析错误 |
| `header_style.background_color` **非法** | 报 `230099 / 200621 unknown property ... header_style`；先**整块去掉 `header_style`**（默认样式已可用）或改用 `background_style` |
| `POST /open-apis/cardkit/v1/cards` **不校验字段合法性** | 拿它当"静默校验"会误判全部通过（连 `bogus_field` 都返回 card_id）——只有真发消息那条路径会校验 |
| 想零打扰试 schema | 只能发到**只有自己可见的测试 webhook / 私聊**；别为了试字段反复发给用户 |
| 单元格文案 | 一句一行、用「；」分隔，**避免换行** → 行高整齐才像表；列宽用 `110px` + `auto` 组合 |
| ★列数 ≥5 的宽表必须 `config.width_mode: "fill"` | 2.0 用 `width_mode`（`default`/`fill`/`compact`），**1.0 的 `wide_screen_mode` 在 2.0 下不生效**。默认宽度下 3 个 `auto` 列各被压到 ~80px，7 列表完全没法读（2026-09-23 实测「AI 销售管理项目推进总表」7 列）。列宽配比：短枚举列固定 `88–112px`、长文本列 `auto`、姓名列 `96px` |
| 多步动作压行 | `①②③` + 「；」写在一格内（如「① 配置MCP连接；② 测试账号权限」），比换行列表省一半行高 |
| 人物列 | 姓名 + ` · ` 角色（如「CSM负责人 · 交付」）压在一格，比单独开一列省宽度；多人用「 / 」分隔 |

**数据来源**：`analyze.py` 在每条 signal 上补 `owners=[{id,name}]`（人员字段直接带 open_id；`client_owner` 一并并入，卡片能同时 @ 双方负责人）与纯文本 `owner`，并产出四个结构化区块数据：`conclusion`（判断+建议）、`focus`（今天优先处理）、`key_nodes`（近期关键节点）、`req_summary`（新增诉求归类）。卡片只做呈现，判断逻辑都在 analyze 里 → 报告与卡片口径自动一致。

**多人负责的坑**：负责人人员字段可能是多人（`C.flat` → `"CSM同事, 本人"`）。聚合统计前必须按 `[,，、/]` 拆开再计数，否则会把"两个人"当成一个名字，且每个人都被少算。`build_conclusion()` 已处理。

## 项目周报（三项目 · ≤500 字，2026-09-19 定稿）

用户口径：「**这个相当于周报的形式 —— 项目周报，然后压缩在 500 字内**」。即把巡检结果**收敛成一份可直接看 / 直接转发的周报**；周报是汇报物，巡检报告是证据物，**不要把报告搬出去**。

- **结构固定四块**：`📊 项目周报 · <起> → <止>` + 三项目各 **3 条**（① 本周关键事件带日期 ② 表内数字 ③ `⚠️` 卡点/硬节点）+ `🎯 下周重点` 3 条 + note 数据源。
- **硬约束**：可见字符 **≤500**（含标点、含标题；2026-09-19 定稿实测 447 为安全基准）。一条一行、一行一个信息点，禁止长段落。
- ★**称谓**：**一律写任务名，绝不出现任务编号**（`T14`/`T21`）—— 用户 2026-09-19 明示「不能说 T14，要说名字」。名字过长可用可识别简称，但不能退回编号；定稿前跑 `T\d{2}` 残留自检（应为空）。
- **产出**：`.workbuddy/巡检/周报-<日期>.md` + `cards/card-周报-<日期>.json`；改版时旧版另存 `-v1`。
- **自检**（必跑）：`python3 -c "import json,re; c=json.load(open('cards/card-周报-<日期>.json',encoding='utf-8'))['card']; t=''.join(e['text']['content'] for e in c['elements'] if e['tag']=='div'); print(len(re.sub(r'\s','',re.sub(r'[*•#]','',t))))"`
- **数据来源**：`巡检报告-<项目>-<日期>.md` 概览段 + 妙记结论 + 记忆里的硬节点，**不重新采集**。
- **推送**：默认 **bot 私信本人**（「推送给我」= 私信本人，不是发群）。传 **card 本体**、不包 `msg_type` 外壳；`--idempotency-key weekly-report-<日期>` **改版重发必须换 key**，否则被静默去重。发群 / 正式 webhook 另需授权。
- 详细模板、字数口径与 4 个已踩的坑见 `references/weekly-report.md`。

## 定时巡检

已可挂自动化：工作日 08:30 跑 `all` + 3 天窗口，产出报告后**只汇报不落手**；用户当日跟进时再决定回写与发群。
