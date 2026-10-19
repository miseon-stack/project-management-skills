---
name: feishu-daily-report
description: 起草并提交本人的飞书日报到多维表格（自动汇总当日工作、拉取次日日程、按公司群公开口径精简、写入日报表并回读核验）。触发场景：用户说"写今天的日报""帮我提交日报""日报草稿""日报表"，或给出 example.feishu.cn/base/<TOKEN> 的日报表链接。
agent_created: true
metadata:
  version: "1.2"
---

# 飞书日报 · 起草与提交

面向 **本人（服务商 FDE）** 的日报流水线：汇总当日工作 → 起草精简版 → 用户确认 → 拉取次日日程 → 写入飞书日报表 → 回读核验。

## 何时用
- "帮我写今天的日报""参考我之前的日报写一份""帮我提交日报"。
- 用户给出日报表链接（Base `<TOKEN>` / table `<TABLE_ID>`）。

## ⚠️ 内容铁律（2026-09-10 用户确立，必须遵守）
1. **日报会自动同步到公司群 → 必须简洁**。每条事项压到 **1–2 句**；★**全文总长控制在 800 字内**（2026-09-24 用户明确嫌长）；会议每条 1 句、项目推进按项目合并、私聊可合成 1 条；不堆实施细节、不列权限/字段级明细、不写内部风险猜测。
2. **不写「遇到的问题」**。该字段留空（这是用户明确要求，不是遗漏）。
3. **顺序：客户A在前，客户B在后**。
4. **不要写"最优先/优先级最高"之类表述**。
5. 草稿先落本地文件给用户过目，**确认后**才写飞书。
6. **写入授权必须明确**（2026-09-14 用户纠正）：只有用户说出「**提交**」「**发布**」「写进去」等**明确的写入指令**才算授权。**「go」「继续」「好」「嗯」等模糊回应一律视为未授权**——先问一句「要提交吗？」，不要自己判断为可以发布。用户习惯是「先看草稿、自己改、再让我发」，宁可多问一次。
7. **产出文档必须带关联（2026-09-24 用户要求）**：凡当日产出/改动的**云文档**，在正文条目里用 markdown 链接给出可点击地址（形如 `[考卷](https://example.feishu.cn/wiki/xxx)`）；本地文件（如 `项目资料/xxx.md`）不写路径，改用中性描述（日报自动同步公司群，本地路径对他人无意义）。
8. **私聊也算工作量，要写进去（2026-09-24 用户要求；2026-10-19 起并入固定三段格式）**：实质私聊（对齐分工、把控质量、协调资源、给客户答疑）逐条列进「**二. 今日事项**」，一句话一条，格式「与 <姓名> —— 事项……」；**不再单列「三、协同沟通（私聊）」段**——固定格式只有三段；寒暄、表情、自动回复卡片不写。
9. **内部管理信息不进正文**（2026-09-21 用户提交前亲手删减确立）：日报会自动同步公司群，**绩效考核方案细则**（岗位拆分、权重、绩效基数、系数、分成规则）、组织人事决策、客户名单与经营指标等**管理侧内容一律不写进正文**，只保留「宣贯/同步了某方案」这类中性表述。起草时遇到内部管理类会议，默认只写「发生了这件事 + 落地方向」，不写规则正文 —— 用户 9/21 就是这么删的。

## 表结构
| 字段 | 类型 | 是否可写 |
|---|---|---|
| 今日工作总结 | text | ✅ |
| 明日工作计划 | text | ✅ |
| 日报提交日期 | datetime | ✅（传文本 `"2026-09-10 22:00"` 即可） |
| 遇到的问题 | text | ✅（**留空**） |
| 提交人 | created_by | ❌ 自动 |
| 部门 / 汇报对象 | lookup | ❌ 自动 |
| AI汇总 | text | ❌ 自动生成 |
| 查看状态 | select | 可不填 |

## 流程

### 0. 先实读线上表，确认目标日期是否已有记录（★ 2026-09-19 新增）

**别假设「线上已有、只是本地缺草稿」——线上也可能真的缺日期。** 实测：线上表本人记录共 16 条，
最新一条停在 **2026-09-16**，9/17、9/18 线上根本没有。这种情况就不是「补本地草稿」，而是
**需要按线上材料回补并起草后请用户确认提交**。

```bash
# 机读用 ndjson（带字段名）；markdown 表格是给人看的，别拿去解析
lark-cli base +record-list --base-token <TOKEN> \
  --table-id <TABLE_ID> --format ndjson --output /tmp/daily.ndjson --overwrite --as user
```

```python
import json
rows=[json.loads(l) for l in open('/tmp/daily.ndjson',encoding='utf-8') if l.strip()]
mine=[r for r in rows if any(p.get('name')=='本人' for p in (r.get('提交人') or []))]
print(sorted(r['日报提交日期'][:10] for r in mine))   # 最快看出漏了哪几天
```

**格式坑**：`base +record-list` 默认输出 **markdown 表格**（不是 JSON），`--json` 给的是
**无字段名的矩阵**，结构在 `data.data`（行数组，按表字段顺序）。要字段名一律用
`--format ndjson --output <path>`。

回补稿在草稿顶部显式标注「**回补稿：线上表无此日记录，按线上纪要/日程/群消息起草**」，
避免日后被误当成当天正常提交的稿子。

### 1. 汇总当日工作
优先级顺序（有就不重复找）：
- 工作区记忆：`<workspace>/.workbuddy/memory/<今日>.md`（当日做了什么、产出文件路径都在里面）
- 各项目 README / 会议纪要 / 项目资料：`<workspace>/<项目名>/`
- 飞书数据仓：`<workspace>/飞书数据仓/`（`python3 scripts/query.py person|group|project|timeline <kw>`）
- 必要时用 lark-cli 读日报表历史记录，对齐格式：
  ```bash
  lark-cli base +record-list --base-token <TOKEN> \
    --table-id <TABLE_ID> --as user --format ndjson --output /tmp/daily.ndjson
  ```
  （提交人可用 python 过滤 `提交人 == 本人` 拿到历史范文）

#### 1.5 抓取当日私聊（数据仓不含私聊，必须走 API）

`飞书数据仓/hub.db` **只同步群聊**（`groups` 表无 p2p 记录，验证方式：messages 里 `chat_id` 全部能在 groups 命中）——私聊必须直接查：

```bash
lark-cli im +messages-search --sender <OPEN_ID> \
  --chat-type p2p --query " " --start 2026-09-24T00:00:00+08:00 \
  --end 2026-09-24T23:59:59+08:00 --page-all --page-size 50
```
- 结果在 `data.messages[]`（不是 results/items）；字段 `chat_partner.open_id`、`content`（JSON 字符串，取 `text`）、`create_time`。
- `chat_partner` **只有 open_id、没有姓名**；`contact +get-user` 对跨租户返回空。反查姓名：先取该 p2p 的 `chat_id`，再 `im +chat-members-list --chat-id <oc> --member-types user`（返回 `本人` + 对方姓名）；或先用 `hub.db` 的 `messages.sender_id → sender_name` 兜底。
- 与群消息合并后判读：私聊里常有「协调加班支持 / 把控回复质量 / 给客户答疑」这类**不出现在群里的真实工作量**。

**批量反查姓名（一次搞定 10+ 会话）**：先把结果落盘（`... --page-all --page-size 50 --as user > /tmp/p2p.json`），再跑

```bash
# 1) 输出 open_id → chat_id 映射
python3 -c "import json;d=json.load(open('/tmp/p2p.json'));[print(m['chat_partner']['open_id'],m['chat_id']) for m in d['data']['messages']]" | sort -u > /tmp/ou2chat.txt
# 2) 逐个会话取成员名（p2p 里除自己外的那个人即对方）
while read ou oc; do
  echo -n "$ou => "; lark-cli im +chat-members-list --chat-id "$oc" --page-all --member-types user --format json --as user | python3 -c "import json,sys;u=json.load(sys.stdin)['data']['users'];print(' | '.join(x['name'] for x in u))"
done < /tmp/ou2chat.txt
```

★`+messages-search` **不支持 `--output`**（会静默不落盘），必须用 shell 重定向 `> /tmp/p2p.json`。

### 2. 起草本地草稿
写到 `<workspace>/日报/YYYY-MM-DD_本人日报.md`。**正文格式固定（2026-10-19 用户确立，不许改）**：

- 三段固定：`一. 今日会议` → `二. 今日事项` → `明日工作计划`；
- **每段独立编号，各自从 1 开始**（不跨段连续编号——10/16 用户纠错过一次 1–7 连排的版本）；
- **正文不放表格、不加粗**——卡片渲染出来就是纯文本（10/16 用户纠错过"表格"和"没序号"两件事）；
- 事项条目用**全角「｜」**分隔对象与标题：`项目/对象｜事项标题。一句话说明。`；
- 会议条目带时间区间：`【项目/客户】会议名（HH:MM–HH:MM）。结论一句话。`；
- `⚠️ 遇到的问题：` 恒留空（铁律 2）。

```markdown
# 日报 · YYYY-MM-DD（周X）

（顶部 1–2 行起草说明：数据来源、待确认项——**提交前删掉，不进正文**）

✅ 今日工作总结：

一. 今日会议
1. 【项目/客户】会议名（HH:MM–HH:MM）。结论…计划…
2. …

二. 今日事项
1. 项目/对象｜事项标题。一句话说明。…
2. …

📖 明日工作计划：
1. 项目/对象｜事项。动作。…
2. …

⚠️ 遇到的问题：
```

- `✅/📖/⚠️` 三处标记是卡片里的呈现样式；`submit_daily.py` 按这三个标记切字段，提交前会自动剥掉标记行，**字段里只留下正文**。
- 实质私聊**并入「二. 今日事项」**（格式「与 <姓名> —— 事项……」），不单列第三段。

写出后用 `present_files` 给用户看，**对话里展示也要按同格式**（无表格、带序号、每段独立编号）——用户看的是回复里的排版，不只是文件。

### 2.5 补齐「今日会议」段（强烈推荐，别只靠日程标题）

只读 `calendar +agenda` 只能拿到会议**标题**，写不出结论，而且标题常是「会议」这类空名。**会议的实际结论要去搜智能纪要云文档**：

★★**第一件事：把当日纪要条目全列出来当「会议清单」**（2026-09-30 实测：日程只显示 2 场，当天实际开了 **4 场** —— 漏掉的 10:29 智能体优化、11:45 销售系统落地沟通会只存在于妙记/纪要里）。做法：`drive +search --query "智能纪要" --sort edit_time --page-size 25` 后按标题里的**日期**过滤当日，再拿 `calendar +agenda` 校准时间；**不要用日程反推会议数量**。

```bash
lark-cli drive +search --query "智能纪要" --sort edit_time --page-size 20 --as user
lark-cli docs +fetch --doc <token> --doc-format markdown --as user
```

- 命名规律：`智能纪要：<会议主题> <日期>` + `文字记录：<会议主题> <日期>`
- 结果在 `data.results[]`（**不是 `data.items[]`**），标题在 `title_highlighted`（需剥 `<h>` 标签），token 在 `result_meta.token`
- **确认本人是否参会**：纪要开头 blockquote 里有「会议主题 / 会议时间 / 参会人」；参会人是 `<cite user-id="ou_..." user-name="姓名">`，**用本人 open_id 匹配**（比姓名可靠）。
- 会议标题为空或无法定性时，用 `calendar +list-attendees --event-id <id>` 按参会人反推议题
- 纪要的「待办」里 @自己的条目 = 明日计划的现成素材（注意：**待办里的 cite 常是提出人/负责人**，不全是我——拿不准就反查会中共享文档的人员分工表）
- ⚠️ `vc` 域读取权限未开通（`vc +search` / `+detail` / `+recording` 全部报 missing_scope），**不要往那条路上试**；智能纪要走 `docs` 权限，是通的

> 完整流程、权限清单与踩坑记录见技能 **`feishu-meeting-minutes-digest`**。

### 3. 拉取次日日程（写"明日工作计划"前）
```bash
lark-cli calendar +agenda --start 2026-09-11T00:00:00+08:00 --end 2026-09-11T23:59:59+08:00 --as user
```
> `+agenda` **没有 `--date` 参数**，必须用 `--start/--end`；返回 `data` 是**数组**，字段为 `summary` / `start_time.datetime` / `end_time.datetime` / `event_organizer.display_name`。
> 同时检查时间冲突（撞会要主动提示用户）。

**calendar 无权限时的替代通路（2026-10-16 实测可行）**：`docs +search --query "<YYYY年M月D日>"` 或
`drive +search --query "智能纪要" --sort edit_time` → 按 `result_meta.create_time_iso` 筛当天创建的
「智能纪要：…」DOCX → `docs +fetch` 读开头 blockquote 里的「会议主题 / 会议时间（精确到分钟）/ 参会人」，
参会人是 `<cite user-id="ou_..." user-name="姓名">`，**用本人 open_id 精确确认是否参会**。
→ 拿到的「会议清单 + 起止时间 + 参会人」比日程还全。

### 4. 用户确认后提交
```bash
python3 scripts/submit_daily.py --file "<workspace>/日报/YYYY-MM-DD_本人日报.md" \
  --date 2026-09-10 --time "22:00" --dry-run    # 先预览
python3 scripts/submit_daily.py --file ... --date 2026-09-10 --time "22:00"   # 真正提交
```

### 5. 回读核验
```bash
lark-cli base +record-get --base-token <TOKEN> \
  --table-id <TABLE_ID> --record-id <rec_id> --format json --as user
```
确认：提交人=本人、日期正确、两栏正文落库、遇到的问题为空。

## 坑（已踩）
- **★提交前核对三段齐全**（2026-09-28 踩到类似问题；2026-10-19 起改为固定三段格式）：**dry-run 时逐段确认「一. 今日会议 / 二. 今日事项 / 明日工作计划」都在**，别只看字数。`submit_daily.py` 按 `✅/📖/⚠️` 卡片标记切两个字段（旧版按 `## ` 二级标题切的逻辑已兼容保留）。
- **★妙记与小群素材要「等同步跑完再补扫一遍」**（2026-09-28 踩到）：只靠「上午已同步的数据仓 + 当日工作日志」起草，会漏掉**当天最重要的客户推进会**——实测 9/28 的 16:52 妙记实为「客户B使用价值复盘 + Q4 落地推进会」（含客户、有 @我的待办），而日志与旧数据仓里都没有。**正确顺序：先跑 `sync_all.sh` → 等完成 → 再全量扫当日妙记（`minutes` 表 `d=当日`）+ 有我的小群**（`chat_name like '%<我>%'`），最后定稿。
- ⚠️ `minutes +detail --minute-tokens` **只接受纯 token**（如 `obcna9mvc58ur6egcc38m53j`），传完整 URL 会报 `invalid_argument: must contain only lowercase alphanumeric characters`；数据仓 `minutes.url` 存的是整条 URL，须自己截取末段。
- **没有 `+record-create` 命令**，用 `+record-batch-create`（HTTP 层 `POST /open-apis/base/v3/bases/{base}/tables/{table}/records/batch_create`）。
- `+record-get` / `+record-list` **默认输出 markdown**，要 JSON 必须显式 `--format json`；`+record-get` 的 JSON 是 `data.data` 二维矩阵（按字段顺序），不是字段名字典——直接回读请用 `--format ndjson --output`。
  实测字段顺序（2026-09-14 验证）：`[0] 日报提交日期` / `[1] 遇到的问题(null)` / `[2] 明日工作计划` / `[3] 提交人([{id,name}])` / `[6] AI摘要(自动)` / `[7] 今日工作总结`。按 `data.record.fields` 取值会全 None，别那么写。
- 表里有 **AI 自动摘要字段**（形如「1. …完成…项目推进及内外部会议」），是自动化生成的，**不要手动覆盖**。
- datetime 字段接受文本 `"2026-09-10 22:00"`，无需自己算毫秒时间戳（易算错年份）。
- lookup（部门/汇报对象）与 created_by（提交人）**不可写**，别塞进 payload 会报错。

## 参考
- 数据仓查询与人物/项目索引：技能 `feishu-data-hub`。
- 日报表链接示例：`https://example.feishu.cn/base/<BASE_TOKEN>?table=<TABLE_ID>&view=<VIEW_ID>`
