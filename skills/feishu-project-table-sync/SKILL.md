---
name: feishu-project-table-sync
description: 把项目最新进度写进飞书「项目表」（多维表格），并回读校验。触发场景：用户说"更新项目表/项目进度写进多维表格/保持项目表最新/回写云端计划表/同步进度到飞书/以线上为准/漏掉的补一下"，或要求把某个项目的进展记录到对应 Base。核心流程：定位 base/table → 读当前值 → 查字段 → dry-run → 批量更新 → 统一回读验收。全程走 lark-cli，不开浏览器预览、不在本地做完整镜像。含多个已验证的坑：--json @ 与 --output 只接受当前目录内的相对路径、只读字段（Formula/Lookup/自动编号）、select 写入不存在的选项会自动新建选项、异步生效不可逐项写完即读、table-list 的 ID 键名是 id、状态是 select 数组、错误码含义。
agent_created: true
---

# 飞书项目表进度同步

## ⚠️⚠️ 先决条件：必须使用有权限的用户身份（`--as user`）

**默认的应用 / 机器人身份读不到目标 Base。** 访问客户 Base 时，若应用未被授权、也未被加入文档协作者，
会一律返回 `91403 you don't have permission`。

**所有命令都要带上 `--as user`**：

```bash
lark-cli base +field-list --base-token <BASE> --table-id <TABLE> \
  --format json --as user
```

- 需要多套身份时，可在 lark-cli 中配置具名 profile（凭据文件自行保管，**含 secret，勿入库**）。
- 该身份需具备 **user 权限**（设备码登录，授权所需业务域），才能读取目标实施表与群组。
- 若某次报 `91403` 或 user 身份 `missing` → 重跑：
  ```bash
  lark-cli auth login --as user --no-wait --json --domain all
  # 把 verification_url 转二维码给用户扫（lark-cli auth qrcode <url> -o ./qr.png），
  # 同一轮不要阻塞轮询；用户确认后再：
  lark-cli auth login --as user --device-code <code>
  ```
- 下文所有示例为简洁省略了身份参数，**实际执行必须补上**。

## 铁律

1. **线上是唯一事实源，本地极简。**（用户 2026-09-14 明确：「以后全部以线上文档为准，漏掉的就补，然后有更新就更新到飞书多维表格上，本地不用搞这么多」）
   - 要进度**先读线上**，不要相信本地 md 的旧快照；本地与线上冲突时**以线上为准**。
   - 发现线上缺字段/缺记录/缺进展 → **直接补到线上**，不要先写本地等确认。
   - **不产出 HTML 报告、不做完整 md 镜像**。本地只留导航（`00_工作总索引.md`）、各项目 `README.md`（要点 + 线上链接）、以及无法上云的原始材料。
2. **全程走 `lark-cli`。** 不要用 present_files 打开飞书链接、不要开浏览器预览。
3. **写前必读当前值，写后必验收。** 保留旧值便于说明"从什么改到什么"。
4. **分级授权**：`最新进展`（纯文本）可直接写；`状态`变更要有可溯源证据；**对外承诺、排期变更、金额、客户可见口径**需先跟用户确认。
5. **优先 `--as user`**（官方约定：操作 Base 优先用户身份）。

## ⚠️ 工作目录约定（最容易踩的坑）

**`--json @<file>` 和 `--output <file>` 都只接受「当前目录内的相对路径」，绝对路径会被直接拒绝：**

- `--json @/tmp/x.json` → ❌ `--file must be a relative path within the current directory`
- `--output /tmp/x.ndjson` → ❌ `unsafe output path`
- `--json @./x.json` → ✅
- `--output ./x.ndjson` → ✅

`--json` **也不支持 stdin（`-`）**，会被当成字面 JSON 解析报错。

→ **正确姿势：先 `cd` 到一个 scratch 目录，再用相对路径。**

```bash
mkdir -p /tmp/larkwork && cd /tmp/larkwork
# 之后所有 --json @./x.json / --output ./x.ndjson 都在这里
```

这样也天然避免了记录文件散落到项目根目录。

### 导出记录的三个硬约束（实测）

1. **`--output` 目标文件已存在会报 `output file already exists`** → 加 `--overwrite`。（重跑同一路径时最容易撞到。）
2. **`--jq` 与 `--format ndjson` 不兼容**，报 `--jq does not support ndjson` → 先导出，再用 Python 读文件；manifest 摘要也用 Python 解析 stdout。
3. **表里有 `button` / `not_support` 等字段时，整表 ndjson 导出会失败**：`field "xxx" has unsupported field type "button"` → 必须用 `--field-id` 逐个投影出需要的字段，不能整表导。
4. 字段名可能带 **emoji、空格、全角括号**（如 `🚥 质检结果`、`F 码`、`✍️ 任务负责人（原培训人）`）。shell 里容易转义出错 → 用 Python `subprocess` 传参数列表最稳，且必须**逐字照抄** `+field-list` 返回的 `name`。

## 🔎 盘点「某客户全部相关对象」

收到「检查 XX 相关全部的」这类要求时，**不要只查自己知道的那张表**——同一客户往往散落多个 Base、多条业务线。

```bash
lark-cli base +title-resolve --title '<客户关键词>' --as user
```

- 返回 `candidates` 列表，**逐个** `+table-list` 看有哪些表、多少条。
- `+table-list` 的返回键是 **`tables`**（不是 `items` / `data.items`），每项含 `id` / `name` / `records_count` / `rev`。
- 拿到表清单后，先判断**每条线分别属于谁**：客户交付主表、客户方自维护表、通用迁移/推广线、内部培训线……**不同 owner、不同业务线的表不要混着改**。
- 无关的表要**明确排除并说明理由**（例如按客户名筛选后 0 条命中）。
- 交叉核对的顺序：**交付主表 → 阶段表 → 客户方明细表 → 群聊原始消息 → 其它旁路表**。群聊消息常能挖出表格里没有的事故与决策。


## 项目表登记册（2026-09-15 实查）

> **每个客户项目都有一张线上「项目实施表」**（命名不统一：客户A叫「项目推进计划表」、客户B叫「飞书实施项目表」、客户C叫「项目上线计划表」）。标准结构 = **上线计划总表（主表）+ 项目阶段 + 项目上线进度监控仪表盘**。

### 交付主表（我方维护）

| 项目 | Base token | 子表 | table_id | 记录数 |
|---|---|---|---|---|
| 客户A | `<TOKEN>` | 上线计划总表（**主表**） | `<TABLE_ID>` | 31 |
| 客户A | 同上 | 项目阶段 | `<TABLE_ID>` | 6 |
| 客户A | 同上 | 项目组成员 | `<TABLE_ID>` | 6 |
| 客户A | 同上 | 仪表盘 / 工作流 | `<DASHBOARD_ID>` / `<WORKFLOW_ID>` | — |
| 客户B AI 客服 | `<TOKEN>` | 上线计划总表（**主表**） | `<TABLE_ID>` | 42 |
| 客户B | 同上 | 项目阶段 | `<TABLE_ID>` | 5 |
| 客户B | 同上 | 仪表盘 | `<DASHBOARD_ID>` | — |
| **客户C** | `<TOKEN>` | 上线计划总表（**主表**） | `<TABLE_ID>` | 13 |
| 客户C | 同上 | 项目阶段 | `<TABLE_ID>` | 4 |
| 客户C | 同上 | 仪表盘 | `<DASHBOARD_ID>` | — |

**客户D / 其他客户 未发现实施表**，且**非本人主责（2026-09-15 用户明确），只登记不跟踪** —— 客户D只有排班数据与日报 Base；其他客户只有《🍺其他客户AI效率先锋活动案例收集表》`<TOKEN>`。**不要主动为这两个项目扫缺口、写进展或建表**；仅当用户明确要求时才处理。需要时先 `+title-resolve` 复查，不要凭印象断言。

**本人主责项目（跟踪范围）= 客户A、客户B、客户C。**

**客户C的其它线上材料**（均≠实施表）：
- ERP 业务看板 `<TOKEN>` → 订单数据 `<TABLE_ID>` / 字段说明 `<TABLE_ID>`（2026-09-15：1597 / 13 条）+ 3 个仪表盘。
- 订单演示 Base `<TOKEN>` → 演示数据 100 条 / 字段说明 13 条。
- 启动前置调研副本 `<TOKEN>` → 收集表 5 条（客户方同事维护，只读作证据）。
- AI 手写单据识别 `<TOKEN>` → 测试 5 条，正式订单/识别测试均 0 条；属于原型验证，不要误判为已交付。

客户C实施表旧疑似副本 `<TOKEN>` 已于 2026-09-15 回读确认为已删除（API 返回 `note has been deleted`）；当前唯一有效实施表为 `<TOKEN>`。

### 只读旁路表（**他人维护，只读作证据，不要改**）

| 归属 | Base token | 表 | table_id | 记录数 | 说明 |
|---|---|---|---|---|---|
| 客户B·客户方 | `<TOKEN>` | 飞书AI智能体功能点明细表 | `<TABLE_ID>` | 35 | 客户方负责人维护，细颗粒功能进度 |
| 客户B·CSM同事 | `<TOKEN>` | 问题收集 | `<TABLE_ID>` | 70 | 通用迁移问题（是否解决/分类/严重程度） |
| 客户B·CSM同事 | `<TOKEN>` | 数据表（8.4 上线计划） | `<TABLE_ID>` | 38 | 8 月通用飞书上线推广线 |
| 客户B·CSM同事 | `<TOKEN>` | 数据表 | `<TABLE_ID>` | 2 | 仅文档索引 |
| 内部（无关） | `<TOKEN>` | 豆包进飞书培训任务 | `<TABLE_ID>` | 5735 | bytedance 域；按客户名筛「客户B」得 **0 条**，与客户B交付无关 |

**（已更正 2026-09-15）** 旧记录曾写「客户C没有项目进度表」——**错误**。客户C实施表为《【客户C】项目上线计划表》`<TOKEN>`（13 + 4 条），当时只查了 ERP 订单看板那个 Base 就下了结论。**教训：盘点某客户资产时必须用 `+title-resolve` 全量解析，不能只查自己已知的那张表。**

**记录数会变**（任务会新增、删除，展示名称也可修改）。每次先 `+record-list` 实读，别信上表；稳定映射用 record_id，不因出现新编号就断言旧任务被重编号。

## 标准流程

### 0. 定位 Base

**优先用 CLI 解析，不要靠 grep 本地文档：**

```bash
lark-cli base +url-resolve --url '<Base URL>' --as user      # 从链接拿 base_token / table_id
lark-cli base +title-resolve --title '<关键词>' --as user    # 从标题找 base_token
lark-cli drive +search --doc-types bitable --sort open_time --opened-since 3m --page-size 20 --as user
```

再列子表 —— **ID 的键名是 `id`，不是 `table_id`**：

```bash
lark-cli base +table-list --base-token <BASE> --format json --as user
```

### 1. 读当前值（保留旧值）

```bash
cd /tmp/larkwork
lark-cli base +record-list \
  --base-token <BASE> --table-id <TABLE> \
  --field-id <字段1> --field-id <字段2> \
  --format ndjson --output ./cur.ndjson \
  --as user
# 1.0.90 的 +record-list --help 未列出 --minimal-stdout，不传未支持的参数。
# ndjson 与 --jq 不兼容；先导出，再用 Python 读取记录或摘要 manifest。
# shell 中带括号的字段名必须引用，例如 --field-id '进度(%)'。
```

- `--field-id` 做投影，只取需要的字段（可重复传）。
- **`--format ndjson` 不打印记录**：记录写入 `--output` 文件，stdout 只返回 manifest（`record_file` / `records_count` / `has_more`）。
- **ndjson 记录是「扁平结构」**，字段直接在行对象上，不在 `fields` 里：`{"record_id":"rec...","状态":["进行中"],"最新进展":"..."}`。别照 `+record-get` 的嵌套结构解析。
- `has_more=true` 说明被截断（默认上限 2000 行），需用 `--filter-json` 下推谓词收窄。

用 python 解析落盘文件：

```python
import json
rows = [json.loads(l) for l in open('./cur.ndjson', encoding='utf-8') if l.strip()]
```

缩小范围：文本关键词 → `+record-search`；结构化条件 → `+record-list --filter-json`：

```jsonc
{"logic":"and","conditions":[
  ["状态","intersects",["进行中"]],
  ["负责人","intersects",[{"id":"ou_xxx"}]],
  ["备注","non_empty"]
]}
```

⚠️ **自动编号字段不能 `intersects`，必须 `==`**；OR 组合也只能写成多个 `==` 子条件。

### 2. 查字段类型与选项（写前必做）

```bash
lark-cli base +field-list --base-token <BASE> --table-id <TABLE> --format json --as user
```

**只读字段绝不可写**：`formula` / `lookup` / `auto_number` / 附件 / 系统字段。误传会在返回里出现 `ignored_fields` / `READONLY`。

已知只读字段：
- 客户A「项目阶段」：`进度(%)`（formula）、`工期(天)`（formula）、`显示名称`（formula）。只能写 `状态`（`未开始/进行中/完成`）、`计划开始`、`计划结束`、文本字段。
- 客户B「项目阶段」：`进度(%)`（formula）、`工期(天)`、`显示名称`。`状态` 选项同为 `未开始/进行中/完成`。
- 客户B「上线计划总表」：`任务编号`（auto_number）、`最后更新时间`（updated_at）。`状态` 选项 `未开始/进行中/已完成/阻塞/待确认`。
- 客户B「功能点明细表」：`功能点状态` 选项 `待开始/进行中/已完成/已阻塞/已卡死/pass/转让飞书/转后期待定`。

**三张实施表常用字段 ID（2026-09-20 实读，三表同名同 ID，可直接用）**：

| 字段 | field_id | 说明 |
|---|---|---|
| 状态 | `<FIELD_ID>` | select，单选也写数组 `["进行中"]` |
| 最新进展 | `<FIELD_ID>` | text |
| 计划开始 / 计划完成 | `<FIELD_ID>` / `<FIELD_ID>` | datetime |
| 优先级 | `<FIELD_ID>` | select |
| 交付物/产出（客户A）· 交付（客户C）· 附件（客户B） | `<FIELD_ID>` | text |
| 主字段 | 客户A `<FIELD_ID>`=任务编号(auto_number) · 客户B `<FIELD_ID>`=任务标题 · 客户C `<FIELD_ID>`=任务名称 | 客户C另有 auto_number「编号」`<FIELD_ID>` |

→ **写 `--json` 时 key 一律用 field_id，不要用显示名**（客户B「负责人 (人员 )」显示名含空格，按名取值恒 None）。

**已核实的阶段 `进度(%)` 算法**：= `关联上线计划总表` 中 `状态="已完成"` 的记录数 ÷ 关联记录总数（0~1 小数）。以当次字段 expression 为准；NDJSON 中 formula 结果为字符串，数值比较前显式转换。
**完成率与状态不一致只触发核查，不自动改成完成。** 先核对关联任务是否齐全、阶段目标及验收是否闭环；100%可能只反映部分关联任务，0%也可能因未关联记录。客户功能点表的 `完成进度` 是手填 number，不是同一公式。不得将手填100%、单功能初测、阶段任务完成率或整体项目验收混为一谈。

**「进度恒为 0%」的正确修法 = 补关联，不是改公式**（2026-09-17 客户B实践）：`进度(%)` 公式首项就是 `IF(COUNTA(关联上线计划总表)=0, 0, …)` —— **关联为空的记录永远算 0**，与真实完成度无关。客户B P1 子阶段「完成相关知识库的导入、创建及调用P1」`<RECORD_ID>` 就是空关联恒 0；补上对应任务（T70/T86/T87/T88）后自动计算即恢复。
→ 补关联用 `+record-batch-update` 写 link 字段：`{"关联上线计划总表":[{"id":"rec_xxx"},{"id":"rec_yyy"}]}`（**数组即该字段全量值，是覆盖语义**，先读回现值再追加）。
→ 补完要跟用户讲清：**如果关联任务本身都没标「已完成」，补完仍会显示 0%** —— 低值来自任务状态，不是公式 bug。**绝不要为了「好看」改公式或硬标完成**（阶段进度同时被仪表盘引用）。

### 2.5 批量新增记录（`+record-batch-create`）

```bash
cd /tmp/larkwork
# 1) 写 ./add.json：{"create_records":[{<field_id>:<value>}, ...]}（单批 ≤200 条）
lark-cli base +record-batch-create --base-token <BASE> --table-id <TABLE> \
  --json @./add.json --dry-run --as user      # dry-run 只看 body，不校验 CellValue
# 2) 正式写
lark-cli base +record-batch-create --base-token <BASE> --table-id <TABLE> \
  --json @./add.json --as user
```

- ★ **`+record-batch-create` 是 `write` 级（不是 high-risk-write），不接受 `--yes`** —— 加了会报 `unknown flag "--yes"`。只有 `+record-delete` / `+field-update` 这类 high-risk-write 才要 `--yes`。
- CellValue 口径（2026-09-23 实测通过）：`text` → 字符串；`select` → `["未开始"]`；`datetime` → `"2026-09-24 00:00"`；`user` → `[{"id":"ou_xxx"}]`（多人就多元素）；`link` → `[{"id":"rec_xxx"}]`。
- **key 优先用 field_id**（字段名可能带空格/全角括号，见 §1 第 4 条）；**不要写 auto_number / formula / lookup / 附件字段**，`任务编号` 由系统自动分配。
- 返回 `data.record_id_list` 与提交顺序**一一对应**，拿它做后续校验即可，不必立刻全表回读。
- ⚠️ 若 target 记录里某人 open_id 解析不到（跨租户无通讯录权限属正常），该字段**留空不报错**，但要在备注里标注「负责人待补充」。
- 实例（2026-09-23）：客户A上线计划总表批量新增「AI 销售经营助手」12 条 → 自动编号 T78–T89，全表 31 → 43 条。

### 3. 组装并写入

```bash
cd /tmp/larkwork
# 1) 写 ./upd.json：{"update_records":{"recA":{"最新进展":"..."}}}
# 2) dry-run 看 body
lark-cli base +record-batch-update --base-token <BASE> --table-id <TABLE> \
  --json @./upd.json --dry-run --as user
# 3) 正式写
lark-cli base +record-batch-update --base-token <BASE> --table-id <TABLE> \
  --json @./upd.json --as user
```

- 单批最多 200 条（超限报 `1254104`，拆批）。
- ⚠️ **一个 batch 只能装同一张表的记录**（2026-09-17 实测）：把「项目阶段」表的记录混进主表的 batch 里，该条会单独返回 `record_not_found`，**其余记录照常写入成功** —— 不会整体报错，极易漏察。跨表写入必须**按 table-id 分开提交**，并逐表回读。
- 同一 Table 连续批量写入**串行执行**；`1254291` = 并发写冲突，短暂等待后重试当前批次。
- `1254045` = 字段不存在（重新 `+field-list` 取真实字段名或 field_id）；`1254015` = CellValue 类型不匹配。
- 中文/换行放 JSON 文件里，别用 shell 拼字符串。
- ⚠️ **写 select 字段时，若值不在选项列表里，Lark 会「静默新建该选项」而不是报错。** 实例：把 `@本人@FDE同事`（人名）误写进「优先级」select，结果字段选项里真的多出一个叫 `@本人@FDE同事` 的优先级。→ 写 select 前必须核对 `+field-list` 的 `options`，写错了要同时改记录值 + 清理字段选项。

#### 清理被污染的 select 选项（`+field-update`）

```bash
cd /tmp/larkwork
# 写 ./field.json：**options 与 multiple 放在顶层，不要包在 property 里**
lark-cli base +field-update --base-token <BASE> --table-id <TABLE> \
  --field-id <fld_xxx> --json @./field.json --yes --as user
```

⚠️ **`+field-update` 是 PUT 全量语义**：必须提交该字段的完整定义（含全部要保留的选项），漏掉的选项会被删掉。
⚠️ **不接受 `property` 包装**：写成 `{"field_name":...,"type":"select","property":{"options":[...]}}` 会报
`800010701 Unrecognized key(s) in object: 'property'`。正确写法是 options / multiple 直接放顶层：

```json
{"field_name":"优先级","type":"select","multiple":false,
 "options":[{"hue":"Red","lightness":"Standard","name":"P0-紧急"}]}
```

⚠️ `--dry-run` **不做 schema 校验**，会照样打印带 `property` 的 body 然后正式执行才报错 —— 所以 dry-run 通过 ≠ 结构正确。
⚠️ 改字段前先确认**没有记录还在用**那个待删选项（全表读回来筛一遍），否则那些记录的值会被清空。
⚠️ 改完**必须回读**：`+field-list` 看选项列表 + `+record-list` 统计各选项记录数，确认没丢数据。

### 3.5 删除记录（空壳/误建）

```bash
cd /tmp/larkwork
lark-cli base +record-delete --base-token <BASE> --table-id <TABLE> \
  --record-id <rec_xxx> --yes --as user          # --record-id 可重复传
```

- 属 **high-risk-write**，必须 `--yes`；**先跟用户确认**再删（删了不能从 CLI 恢复）。
- ⚠️ `任务编号` 是 `auto_number`，**删除后该编号不会被回收复用** —— 会出现编号断号（如删掉 T98 后从 T99 直接接 T100）。这是正常的，不要以为是丢数据。
- 删完回读全表确认条数 -1、目标 record_id 消失。

### 4. 验收

⚠️ **Table 更新多为异步生效：接口成功返回后立即读可能看不到最新值。**
→ **以写入成功响应作为操作结果**；需要确认最终状态时，**先完成本轮全部变更，再统一读取验收**，不要逐项写完立刻读回。

验收用 `+record-get` 精确读目标记录（比全表 `+record-list` 省）：

```bash
lark-cli base +record-get --base-token <BASE> --table-id <TABLE> \
  --record-id <rec_xxx> --format json --as user
```

⚠️ **`+record-get --format json` 的 `data.data` 是「无表头行数组」**（`data.data[0]` 是一行值的 list，不是 dict），按 `rec['fields']['字段名']` 解析会报 `'list' object has no attribute 'get'`。行内值的顺序与 `--field-id` 传入顺序一致，但更稳的做法是**直接用 `--format ndjson` 回读**（字段名扁平在行对象上），或用 `--field-id` 投影后按索引取值。

⛔ **不要为了「读原值」去 `+record-get` 再自建遍历解析 —— 这是踩过的真实事故（2026-09-20，客户A T57）。**
当时用 `+record-get` + 递归 walk（找 `field_id=='最新进展'`）取值，walk 未命中返回 `None`，于是「原值 + 新句」实际变成「`""` + 新句」，**把 332 字的进展正文整段覆盖成了一句 83 字**，且 `ok=true` 无任何报错。
→ **需要「读原值再追加」时，一律用 `+record-list` 读（结构确定：`data.data` 行数组 + `data.field_id_list` / `data.fields` 做列映射 + `data.record_id_list` 对齐行），拼接后再写。**
→ **任何长文本字段写入后必须回读全文比对长度**，不能只看 `ok=true`。
→ **万一已被覆盖，兜底手段是 `+record-history-list`**：`field_changes[].after` 保存了历史上每次写入的**完整原文**（记录按 rev 倒序），取回后原样写回即可恢复。见下方「误覆盖恢复」。

```bash
# 误覆盖恢复：先取历史，再找目标字段的 after 全量原文
lark-cli base +record-history-list --base-token <BASE> --table-id <TABLE> \
  --record-id <rec_xxx> --page-size 5 --format json --as user
# → data.items[N].field_changes[M] = {field_id, field_name, before, after}
# 用 field_id 匹配 + after 以原文开头特征校验，拼上新内容后 batch-update 写回，再回读确认长度
```

⚠️ **批量写入的返回体里没有 `data.update_records`**（`ok=true` 但条数为 0 是正常的），别据此判断"没写进去"——**必须以回读为准**。

**注意：batch-update 不预校验 record ID 是否存在**，所以验收是必要的。

### CellValue 速查

| 字段类型 | 写法 |
|---|---|
| text | `"字符串"` |
| select | `["选项名"]`（单选也只能是数组） |
| datetime | `"2026-09-14 00:00"` |
| user / group / link | `[{"id":"ou_xxx"}]` |
| number | `12.5` |
| checkbox | `true` |

## 进展取证（先说清「最近发生了什么」再动笔）

「检查最新进展 / 和项目表差多少」= **读线上表** + **拉近期群消息**两件事。只读表必然得出过时结论（客户A 2026-09-17 复核：表停在 9/14–9/15 口径，三天内 14 处对不上）。

### 拉群消息必须走原生 API

`lark-cli im +chat-messages-list` 在本机**必然失败**：报 `missing required scope(s): im:message.reactions:read`。改用原生接口：

```bash
# 秒级时间戳：date -j -f "%Y-%m-%d %H:%M:%S" "2026-09-14 00:00:00" "+%s"
lark-cli api GET /open-apis/im/v1/messages --params \
  '{"container_id_type":"chat","container_id":"<oc_>","start_time":"<秒>","end_time":"<秒>","sort_type":"ByCreateTimeDesc","page_size":50}'
```

返回 `data.items[].body.content` 是 **JSON 字符串**，按 `msg_type` 解析：`text`→`j["text"]`；`post`→`j["content"]` 逐块拼 text；`interactive`（卡片）→ 正则抽 `"text"` / `"title"` 字段；`file`/`image`/`media` 给占位符。`sender.id` 是 open_id，用 `飞书数据仓/data/people.json` 的 `open_ids` 数组反查姓名（注意是数组，一人可能多 id）。

### 客户A项目群 oc 清单

| 群 | chat_id |
|---|---|
| 【内部】客户A项目沟通群 | `<CHAT_ID>` |
| 【客户A】飞书迁移集成专项群 | `<CHAT_ID>` |
| 客户A&飞书 信息化侧沟通群 | `<CHAT_ID>` |
| 客户A研发需求demo | `<CHAT_ID>` |
| 【服务群】客户A | `<CHAT_ID>` |
| CRM、ERP与飞书场景集成沟通 | `<CHAT_ID>` |
| 客户A&飞书 Demo 交流 | `<CHAT_ID>` |
| 项目-飞书导入 / 飞书会议整合 | `<CHAT_ID>` / `<CHAT_ID>` |

### 客户B项目群 oc 清单

| 群 | chat_id |
|---|---|
| 【服务群】客户BAI智能客服沟通群（主战场） | `<CHAT_ID>` |
| （内部）客户B项目 | `<CHAT_ID>` |
| 【内】客户B打单群 | `<CHAT_ID>` |
| 【飞书服务】客户B管理员对接群（<GROUP_CODE>） | `<CHAT_ID>` |

> 客户B的会议产品链：业务群先发 `share_calendar_event` → 到点发 `video_chat`（含 `meet_number`）→ 会后群内出现 `docx` 链接。**顺着「智能纪要」docx 的「相关链接」段可以一次拿到妙记 + 文字记录两个链接**，比搜 drive 更快。

### 会议纪要怎么找（vc / minutes 搜索本机缺 scope，改走 drive 搜索）

- `vc +search`、`minutes +search`、`vc +detail`、`vc +recording` 在本机**必然报 missing scope**（`vc:meeting.search:read` / `minutes:minutes.search:read` / `vc:record:readonly`），需用户重新 OAuth 才能用 —— 不要在这上面耗轮次，直接走下面两条路。
- **路径 1（首选）**：`lark-cli drive +search --query "<会议主题关键词>"`。结果在 **`data.results[]`**（不是 `items`），取 `title_highlighted` / `result_meta.url` / `result_meta.doc_types`。智能纪要在云文档搜索里标题形如「智能纪要：<会议主题> <日期>」，同场会同时命中「文字记录：…」和「妙记」链接（`/minutes/obcn…`）。
- **路径 2**：`lark-cli calendar +agenda --start <ISO> --end <ISO>` 列日程 —— 返回的是**数组**（`data` 直接是 list，不是 dict），拿 `event_id` + `summary` 反推要找哪场会。
- 读全文：`lark-cli docs +fetch --doc "<url>" --doc-format markdown --format json` → `data.document.content`（含参会人 cite、总结、待办、相关链接）。
- 贴进表前核实标题：`lark-cli drive +inspect --url <url>` → `data.title`。

### 判定「完成」看客户侧最后一句确认语，不要凭推断保守

**2026-09-17 教训**：T53（技术问题卡）、T58（流片抓取）我按「内部 Demo ≠ 交付」判为未完成，实际客户侧早已部署并认可 ——
- T53：客户 9/14 18:26「目前技术问题卡导入工具是部署好了，和刘莹试了下，可以实现网页端的 excel 导入功能」（跑在客户自己租户 `pcnnquzzd2wv`）；
- T58：客户 9/16 16:19「谢谢，很清晰」，16:35/18:41 已在追问 skill 怎么改、能不能定时跑。

**要点：翻到该群最后一轮对话，找客户方那句正面反馈，再定状态。**「客户还没做培训」≠「未交付」；「我方还没打包」≠「客户没用上」。

## 缺口扫描（「漏掉的」怎么找）

收到「检查某项目 / 漏掉的补一下」时，按这个顺序扫一遍，比逐条读快得多：

1. **进展空缺**：全表读回来，筛 `最新进展` 为空或空白的记录。
2. **空壳记录**：只有 `任务编号` + `优先级`，没有主题/计划/负责人的记录 —— 通常是没填完的占位符，**要问用户是补还是删，不要自己编内容**。
3. **状态与数据打架**：阶段 `进度(%)`=1 但 `状态`≠完成；任务计划完成日已过但 `状态`=未开始且无进展。
4. **字段填错**：select 字段里出现明显不属于该字段语义的选项（如优先级里出现人名）。
5. **客户方表**（如客户B「功能点明细表」）由客户维护，**只读不写**；发现客户侧已完成的证据，用来回填我方表的进展，而不是去改客户的表。

## 进展文案写法

### ⚠️ 先判断「这张表是对外还是对内」（2026-09-15 教训）

**有的项目表客户可以直接查看**（实例：客户B「上线计划总表」`<TABLE_ID>`，用户 2026-09-15 明确「是对外的，他们也可以看到」）。**写之前必须先确认表性质**；对外的表，`最新进展` / `备注` 全部按「客户会逐字读到」来写。

**对外表绝对不能写**：

| 禁止内容 | 反面示例 |
|---|---|
| 内部核对/审计口吻 | 「2026-09-15 线上核对」「本表原记录」「纠正前次进展」「撤回原表述」「排期未调整」 |
| 我方字段管理动作 | 「本任务主负责人字段当前为空，需确认后补齐」 |
| 对客户方表格的评判 | 「客户填报的分项进度，不代表项目整体完成率」「客户表与本表存在差异」 |
| 内部指令与分工 | 「请客户方负责人及售前确认…」「本次不改权限、验收范围或状态」 |
| 客户负面信息 | 客户投诉、客户数据误删事故、「客户认为偏短」 |
| 安全弱点细节 | 「隔离已被实测绕过」「通过引导即可让智能体返回全部内容」 |
| 金额 / 催款 / 商务线 | ¥金额、催款通知书、付款状态 |
| 内部来源与编号 | `recv…` 记录号、「群内事实」「内部记录」 |

**对外表正确写法**：`日期 + 已完成的事实 + 下一步 / 待确认事项`，中性正向、可对客户陈述。逾期可写，但用对外中性表述（「计划完成日 X 已过，最新完成时间待更新」），不写内部口径。

**⚠️ 重要更正（2026-09-17）**：**客户A「上线计划总表」`<TOKEN>` 同样是对外可见的** —— 用户 9/17 明确「这个表客户是可见的，所以不要写的过分详细，用词注意是双方都可以接受的程度」。**默认把三张实施表（客户A / 客户B / 客户C）全部按对外处理**；只有用户明确说「这张是内部表」时才放开。

判定依据（反面教材，均已在 2026-09-17 清除）：客户A表里曾出现「按原计划 9/4 完成日仍逾期 10 天，本周请客户方再安排一次试测，并联系客户方接口人输出结论」「**未交付状态**：…**客户环境尚未部署、客户未实际使用 → 未交付，不算完成**」「9/14 复核：时间已重排…逾期表述作废」——这些是纯内部话术，客户逐字可见即失分。

对外表的措辞标准（客户A 2026-09-17 实践）：**日期 + 客户可验证的事实 + 下一步**，一段控制在一到两句，不写天数催办、不写我方内部分工与人名指派、不写「未交付 / 不算完成 / 逾期 N 天」。

### 通用要求

- 结构：**日期 + 事实 + 影响/下一步**。例：`9/11 架构决策：由单一智能体改为两个独立智能体（物理隔离），维护成本需写入方案；本项搭建范围与 9/25 验收范围需同步调整。`
- 用明确状态文字，不默认添加表情符号。
- 不写内部红线、不对客户披露的措辞（该表可能客户可见）。
- 逾期依据真实 `计划完成`，不要把 `计划开始` 当期限；需要天数时用日期库计算。不得将未发现结果写成确定未完成，也不擅自改排期。
- 「拿到输入材料」不等于「完成验证」；「单项初测通过」不等于「客户验收」。旧方案已有替代路径不等于原技术限制消失，不能把历史阻塞全部标成解除。
- 引用客户侧记录时分开写核对日期、证据日期、表名/record_id与验证范围。既有链接能打开，不代表已决定取消API开发；客户表与我方表在范围、比例、状态上有冲突，写明待确认，不能只选择较乐观的一侧。
- 子任务只部分启动时，不写成全部已启动；任务已明确负责人时不重复要求重新指定；试用覆盖与badcase台账未见证据时只写已查记录未提供，不断言从未开展。
- 客户侧表作为本轮只读证据；需要调整其内容或权限时另获授权，不从通用补漏推定授权。

## 收尾

1. **不再维护本地完整镜像**。只在必要时更新 `<项目>/README.md` 的要点 + 线上链接；已存在的 `项目资料/*.md` 镜像逐步停止维护，不再逐条同步。
2. 追加工作日志到 `<工作区>/.workbuddy/memory/YYYY-MM-DD.md`（append-only）。
3. 确认没有 ndjson / manifest 散件落在项目根目录（scratch 目录用完可清）。
