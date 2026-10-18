---
name: feishu-meeting-minutes-digest
description: 拉取本人当天（或指定日期）所有会议的智能纪要、文字记录与参会人，并汇总会议结论与分派给自己的待办。触发场景：用户说"看看会议的部分""今天的会都聊了什么""把会议纪要整理一下""日报里的会议部分补一下""今天开了哪些会"，或需要为日报/周报补齐会议内容时。
agent_created: true
metadata:
  requires:
    bins: ["lark-cli"]
---

# 飞书会议纪要拉取与汇总

把「我某天开了哪些会 + 每场会议谈成了什么 + 分派给我什么待办」一次性拉齐。日报、周报、项目复盘的会议部分都走这条链路。

## 核心事实（先看这个，能省半小时）

**`vc` 域的读取权限是没开的，不要在这上面浪费时间。** 实测以下命令全部报 `missing_scope`：

| 命令 | 缺的 scope |
|---|---|
| `vc +search` | `vc:meeting.search:read` |
| `vc +detail` | `vc:meeting.meetingevent:read`、`vc:record:readonly` |
| `vc +recording` | `vc:record:readonly` |
| `im +messages-search` | `im:message.reactions:read`（搜索强制拉表情回复） |

> **⚠️ 2026-09-19 更新**：`minutes:minutes.search:read` **已授权**（`auth status` 的 scope 里能看到，
> 同时还有 `minutes:minutes:readonly`、`minutes:minutes.media:export`）。上表里 `minutes +search` 一行
> 已过时 —— 现在可以先用妙记搜索试一次，成功就不必绕云文档。**`vc` 域仍不可用。**

**但智能纪要本身就是普通云文档，走 `docs` 权限，而 `docs` / `drive` 权限是齐的。** 所以最稳路径仍是：**用云文档搜索捞纪要文档**，而不是去查会议。

已授权的相关 scope：`minutes:minutes.artifacts:read`、`minutes:minutes.basic:read`、`minutes:minutes.search:read`、`minutes:minutes:readonly`、`docs:document.content:read`、`drive:drive.metadata:readonly`、`calendar:calendar.event:read`、`contact:user.base:readonly`、`search:docs:read`。

## 流程

### 1. 拿当天的日程（确定"开了哪些会"）

```bash
lark-cli calendar +agenda --start <YYYY-MM-DD>T00:00:00+08:00 --end <YYYY-MM-DD>T23:59:59+08:00 --as user
```

返回 `data[]`，每场含 `summary` / `start_time` / `end_time` / `event_organizer.display_name` / `event_id`。
**注意**：
- `+agenda` 不返回参会人，`description` 通常为空。
- **`start_time` / `end_time` 是对象 `{datetime, timezone}`，不是字符串** —— 直接切片会 `KeyError`。
  取法：`(e.get('start_time') or {}).get('datetime','')`。

### 2. 补参会人（把没名称的"会议"定性出来）

日程标题经常就叫「会议」，没有参会人无法定性。按 `event_id` 拉参会人：

```bash
lark-cli calendar +list-attendees --event-id <event_id> --as user
```

`data.attendees[]` 含 `display_name` / `is_external` / `is_organizer` / `rsvp_status` / `user_id(open_id)`。
用参会人 + 已知项目关键人就能判断议题（例：客户IT负责人=客户A IT 负责人、同事=飞书侧、同事=客户研发 → 客户A线）。
`calendar +get --event-id` 也能取，但 `attendees` 字段实测返回空，**必须用 `+list-attendees`**。

顺带可拿 `meeting_id`（`calendar +meeting --event-ids <ids>` 批量），但拿到也读不了产物，除非补授权。

### 3. 用云文档搜索捞智能纪要 ★关键步骤

```bash
lark-cli drive +search --query "智能纪要" --sort edit_time --page-size 20 --as user
```

同一天生成的每场会通常有**两份**文档，命名规律固定：

- `智能纪要：<会议主题> <日期>` —— AI 摘要（含总结 / 待办 / 相关链接），**直接读这份**
- `文字记录：<会议主题> <日期>` —— 逐字稿，只在需要抠原话时读

也可用 `--query "会议纪要"` 或会议主题关键词补搜。**加 `--edited-since 3d` 反而会漏**（智能纪要的 `update_time` 与创建日可能错位），按 `--sort edit_time` 取前 20 条再按当天日期过滤更稳。

> **★ 补搜历史日期必须用「会议主题关键词」，只搜「智能纪要」会漏（2026-09-19 实测踩坑）**
> `--sort edit_time --page-size 30` 只返回**最近编辑**的 30 条。定位较早日期时，那天的纪要早已被挤出榜单：
> 实测搜「智能纪要」**找不到 9/17 的任何纪要**，改搜 `--query "Udesk"` 才命中
> `智能纪要：【客户B】Udesk三方对齐 2026年9月17日`。所以补历史日期时按**项目名 / 会议主题词**
> （项目名、系统名、客户名，如「Udesk」「客户C」「客户B」「启动会」）逐个搜，而不是只搜「智能纪要」。
> 关键词搜索还能顺带捞出**非纪要但相关的线上成果文档**（如《客户B-AI客服-内部进展同步-最新.md》）。

**解析坑**：结果在 `data.results[]`，标题是 `title_highlighted`（带 `<h>` 高亮标签，要正则剥掉），元数据在 `result_meta`（`token` / `doc_types` / `update_time_iso` / `owner_name`）。**不是** `data.items[]`，按 `items` 解析会得到 0 命中并误判为"搜不到"。

**文档类型分流**（拿到 token 后别一律 `docs +fetch`）：

| token 实际类型 | 正确命令 |
|---|---|
| docx / 云文档 | `lark-cli docs +fetch --doc <token> --doc-format markdown` |
| **Drive 里的原生 `.md` 文件** | `lark-cli markdown +fetch --file-token <token>`；用 `docs +fetch` 会**静默返回空内容**（`content` 长度为 0），最容易被误判成"文档没内容" |
| bitable / sheet | 改用 `base +record-list` / `sheet` 域命令 |

`drive +inspect` 可判类型，但**参数是 `--url`（不是 `--token`）**：`lark-cli drive +inspect --url <url>`。

### 4. 读正文

```bash
lark-cli docs +fetch --doc <token> --doc-format markdown --as user
```

正文在 `data.document.content`。纪要标准结构：`<title>` → 会议主题/时间/参会人 blockquote → `# 总结` → `# 待办` → `# 相关链接`（含妙记 URL 与文字记录链接）。

- 逐字稿很长（17k+ 字），用 `head -c` / 取尾部切片看结论，别整篇灌进上下文
- 妙记 token 可从 `# 相关链接` 里的 `/minutes/<token>` 抠出来，再 `lark-cli minutes +detail --minute-tokens <token> --summary`（**参数是复数 `--minute-tokens`**，单数会报 unknown flag）
- ⚠️ **要会议的"开始时间 / 时长"，别用 `minutes +detail`** —— 实测它只回 `title` 和 `note_id`，没有 `start_time`（`vc +detail` 也不是这个用途）。可靠来源是 `minutes +search` 结果里的 `display_info`：`开始时间: 2026.09.17 10:00:26 时长: 18 分 11 秒`（需先正则剥掉 `&lt;b&gt;` 等实体）。判断"两场同名会是不是同一场"时，这是最省事的服务端证据。

### 5. 汇总

按时间顺序列会议，每场压到 1–2 句：**谁组织 · 对齐了什么 · 定了什么**。
再把纪要「待办」里 @自己 的条目单独摘出来——这是日报"明日计划"的现成素材。

## 妙记检索：找"某一场特定妙记"（验收取证场景）

> 场景：验收/审计要求提交「某客户 · 某主题的培训妙记链接」时，逐个猜关键词很慢且会误判"没有"。

### 全量枚举法（先枚举，再筛）

**`minutes +search` 的 `--query` 是搜妙记「内容」，可以省略**。省略后按时间倒序列举，这才是"找出这个客户到底有哪些妙记"的正确姿势。

```bash
# 空 query + 时间范围；输出里 data.items[]，has_more/page_token 分页
lark-cli minutes +search --start 2026-08-01 --end 2026-10-01 --page-size 30 --format json
```

★ **单次时间窗口硬上限 50 条**（不是 page-size），到顶后 `has_more` 会变 false，容易误以为"就这么多"。
必须**按时间切片**多拉几轮再去重（例：9/15–9/20、9/1–9/16、8/1–9/2、6/1–8/2）。

每条 `items[]` 的结构：

| 字段 | 内容 |
|---|---|
| `display_info` | 标题 + `<b>关键词:</b> …` + `所有者: X 开始时间: Y 时长: Z`（HTML 实体要剥） |
| `meta_data.app_link` | **妙记链接**（`https://<域>/minutes/<token>`） |
| `token` | minute_token |

### 按人列举（补"他人名下漏检"）

```bash
lark-cli minutes +search --owner-ids <open_id> --start ... --end ... --format json
lark-cli minutes +search --participant-ids me --start ... --end ... --format json
```

委派关系里妙记常记在 **CSM / 同事名下**（不是自己），只用关键词搜自己可见范围会漏；`--owner-ids` 能直接列某人全部。open_id 用 `飞书数据仓/data/people.json` 的 `open_ids` 反查。

### 内容命中 + 交叉验证

拿到全量清单后，再叠加关键词做内容命中，**两个维度交叉**（标题枚举 ∩ 内容命中）才下结论：

```bash
for k in 智能伙伴 Aily 知识问答 智能纪要 妙搭 企业豆包; do
  lark-cli minutes +search --query "$k" --start 2026-06-01 --end 2026-10-01 --page-size 30 --format json
done
```

判断口径：**全 0 命中 + 全量清单里也没有该主题场次 → 才可下"确无"结论**；只凭单关键词 0 命中不能下结论。

### 三个必踩的坑

1. **命令输出混了进度行**：`lark-cli` 会把 `[minutes +detail] querying …` 之类进度写进 stdout，直接 `json.load` 会失败。**先取第一个 `{` 再解析**（`raw[raw.find('{'):]`）。别用 `2>/dev/null` 掩盖，会把 JSON 一起吞掉。
2. **`+detail` 参数是 `--minute-tokens`（复数、逗号批量）**，不是 `--token`；单数报 unknown flag。
3. **群消息里的链接常常不是自己客户的**。例：「飞书战队」群一条群发给了"基础功能/AI功能/多维表格"三条妙记，实际分别属于**其他客户、其他客户**等他人项目 —— 拿链接前必须 `minutes +detail` 验标题与归属，别直接当自己客户的材料上交。

### 拿到候选后：验内容是否覆盖某个子主题

验收常要求"A 场覆盖主题甲、B 场覆盖主题乙"。判断某场能否兼作多个主题，用章节 + 摘要：

```bash
lark-cli minutes +detail --minute-tokens <token> --chapter --summary --todo --format json
```

`artifacts.chapters[]` 给 `title` / `summary_content` / `start_ms` / `stop_ms` —— 可直接看出**该主题占了哪些章节、多少分钟**，是"能否一场顶两条"的关键证据，也能据此剪专章。

## 已知边界

- **跨租户纪要读不到**：外部同事（如飞书官方侧）组织的会议，其智能纪要可能落在对方租户，`docs +fetch` 报 `3380004 No permission`。此时退回读自己租户内的**文字记录**，同样能定性会议内容。
- **不在自己日历上的会**：临时小会（如会前 7 分钟内部对齐）不会出现在 `+agenda`，但会有纪要文档。所以**第 3 步的文档搜索是主路径，日程只是校验**，不要只依赖日程。
- **招聘日会之类的例行会**：通常 0 参会人、无纪要，无实质内容，别硬凑进日报。
- 若某天纪要搜索为空，可能是 AI 总结未开启或尚未生成，如实说明，不要编。

## 相关技能

- `feishu-daily-report` —— 本技能产出的会议内容正好填它的「今日会议」段
- `lark-meeting`（connector）—— 会议领域模型与产物关系（Note / Minutes / Doc 的区别），补授权后再用
