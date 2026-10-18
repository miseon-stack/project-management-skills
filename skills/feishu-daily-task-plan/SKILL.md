---
name: feishu-daily-task-plan
description: 读当天新增变更 → 排今日任务 → 用 lark-cli 在飞书任务里创建「本人」的今日任务（含开始日期、结束日期、关联项目清单、描述里带对应项目多维表格链接）并回读核验。触发场景：用户说"读取更新变更，安排今天的任务，创建到飞书任务""排一下今天要做什么""把今天的活儿建成待办""今天的任务安排""给任务关联对应多维表格"等。核心流程：① 拉今日日程 `calendar +agenda`；② 拉已有未完成任务 `task +get-my-tasks`；③ 实读三个项目线上实施表（客户A / 客户B / 客户C）找逾期与近期到期项；④ 用原生 API 读关键群最新消息，捞出"昨夜至今早"的新需求；⑤ 归纳成 ≤10 条今日任务；⑥ `task +create` 建任务 → `tasks patch` 补开始日期与「【对应多维表格】+链接」描述 → `+tasklist-task-add` 挂项目清单（**只 assignee 本人，不加他人**）；⑦ 回读核验 start/due/tasklists/members/描述链接。含已验证的 CLI 参数与坑，以及「任务清单 ↔ Base 无原生绑定」的能力边界。
agent_created: true
---

# 飞书 · 每日任务计划（读变更 → 排任务 → 建飞书任务）

## 铁律

1. **只创建本人的任务。** `--assignee <OPEN_ID>`（本人），**默认不加 follower、不加其他成员**（用户 2026-09-17 明确："只创建我的任务，不要搞给别人的"）。要给别人派活必须先问。
2. **全程走 `lark-cli`。** 不开浏览器、不用 present_files、不建本地镜像。
3. **创建前把清单讲清楚**（哪几条、截止今天、依据什么），创建后**回读核验**再回复。
4. **任务数量克制**：一天 8–12 条为宜。逾期已久但不影响今日硬节点的项，列为"顺延项"在回复里说明，不硬塞进任务。
5. **标题格式**：`项目名｜动作`（如 `客户B｜约并拉通「服务商+客户B+Udesk」三方研发沟通会`）；超过 3 条同项目就统一前缀，便于扫读。
6. **描述要带来源依据**：谁在哪个群/哪张表的哪一条、什么时间说的、线上任务编号与状态。下一个人看到任务不用再翻聊天记录。
7. **每条任务三字段必齐：开始日期 + 结束日期 + 关联清单**（用户 2026-09-17 明确）。少任何一个都要补。
8. **每条任务的描述顶部必须带「对应项目多维表格」链接**（用户 2026-09-17 明确："每个任务其实是有任务的多维表格，你可以关联一下"）。格式见下节，少这一步要补。

## 取数五步（并行做，别串行等）

| 步 | 目的 | 命令 |
| --- | --- | --- |
| 1 | 今日日程（判断有几个会、有没有该约还没约的会） | `lark-cli calendar +agenda --start 2026-09-17 --end 2026-09-18` |
| 2 | 已有未完成任务（避免重复建） | `lark-cli task +get-my-tasks --complete=false --page-all` |
| 3 | 三项目线上实施表（唯一事实源，找逾期/近期到期） | 见下表 base/table |
| 4 | 关键群昨夜至今早新消息（新需求都在这里） | `lark-cli api GET /open-apis/im/v1/messages` |
| **4b** | **服务商侧 + 客户项目重点群扫描（★必做，别只扫客户群）** | `python3 飞书数据仓/scripts/scan_watch_groups.py --days 2` |
| 5 | 数据仓增量同步（可选，全量约 13 分钟，后台跑） | `python3 飞书数据仓/scripts/sync_messages.py > /tmp/sync_$(date +%m%d).log 2>&1 &` |

### 第 4b 步详解：为什么必须扫「服务商侧群」

> ★ 2026-09-25 教训：此前排今日任务**只扫客户项目群 + 会议纪要**，结果漏掉团队负责人在「【内部-专项】工作坊」群 @我 的明确指派（「讲师材料 @本人 负责」）。**用户公司侧（服务商侧）的群同样会派人派活，必须纳入扫描。**

群清单在 `飞书数据仓/data/watch_groups.json`（**独立文件，不会被 `refresh_hub.py` 覆盖**），分两档：

- `tier=service`：服务商侧 / 公司侧 —— 服务商飞书协作主群、公司全员群、事业部&客户服务沟通群、区域客户服务对接群、渠道伙伴技术支持群、伙伴 CSM 赋能交流群、FDE 内部同步群、产品企业版内部沟通群、【内部】关键项目进展同步群、【内部-专项】工作坊。
- `tier=customer`：三家客户的项目群 / 服务群。

```bash
cd 飞书数据仓
python3 scripts/scan_watch_groups.py --days 2                 # 全部重点群，今天+昨天
python3 scripts/scan_watch_groups.py --tier service --days 3  # 只看服务商侧
python3 scripts/scan_watch_groups.py --json                   # 程序消费
```

输出三类：**🔴 @我（需回应）** / 🟠 正文提到我 / 🟡 通知·安排·待办。脚本已内置忽略名单：

- `<APP_ID>`（日报提交提醒机器人）
- 正文含「请升级至最新版本客户端」等卡片占位
- 正文含「**金雨田**」（部门负责人账号上的豆包定时任务发的「金雨田 · 日报/周报点评」——**AI 自动生成，不作优先级依据**）

> ★ **不要按发送者忽略 `<OPEN_ID>`**。2026-09-28 用 `im +chat-members-list --member-types user` 反查确认：**这个 open_id 是部门负责人本人**（`sender_type=user`），既发真实工作消息、也发上述 AI 点评。按发送者整体忽略会连带丢掉部门负责人的真实指派 —— 只能按正文关键词「金雨田」过滤。
> 教训：判断"是不是 bot"不能只看内容像不像 AI，必须查 `sender_type` / 成员表。

要增减群或忽略项，直接改 `watch_groups.json` 的 `groups`（也支持 `ignore_senders` / `ignore_text_kw` 覆盖脚本默认值）。

⚠️ 脚本读 `messages/*.json` 原始层（hub.db **不存 mentions**，无法判 @我），所以**先同步再扫**；数据旧了先跑 `bash 飞书数据仓/sync_all.sh messages`（或 `all`）。

### 线上实施表（按需扩项目）

| 项目 | base_token | 任务表 table_id |
| --- | --- | --- |
| 客户A | `<TOKEN>` | `<TABLE_ID>` |
| 客户B | `<TOKEN>` | `<TABLE_ID>` |
| 客户C | `<TOKEN>` | `<TABLE_ID>` |

关键项目群 chat_id 见 `飞书数据仓/data/groups.json` 的 `related_project` 字段。最需要盯的 8 个群：
客户BAI客服沟通群 `<CHAT_ID>`、（内部）客户B项目 `<CHAT_ID>`、
客户A信息化侧沟通群 `<CHAT_ID>`、【内部】客户A项目沟通群 `<CHAT_ID>`、
客户A研发需求demo `<CHAT_ID>`、项目-飞书导入 `<CHAT_ID>`、
客户C&飞书办公软件沟通群 `<CHAT_ID>`、客户C发票流程讨论组 `<CHAT_ID>`。

```bash
# 读某群最近 25 条（原生 API，绕开 reactions scope）
lark-cli api GET /open-apis/im/v1/messages --as user \
  --params '{"container_id_type":"chat","container_id":"oc_xxx","sort_type":"ByCreateTimeDesc","page_size":"25"}' \
  > /tmp/raw_oc_xxx.json
# create_time 是毫秒字符串；正文在 body.content（JSON 字符串，post 型要展平 content[][].text）
```

## 创建任务（三条字段缺一不可：开始日期 / 结束日期 / 关联清单）

**用户明确要求（2026-09-17）：每条任务都必须有开始日期、结束日期、关联清单。**

```bash
# ① 建任务（--due 即「结束日期」，按日期存为 all_day）
lark-cli task +create \
  --summary "客户B｜约并拉通「服务商+客户B+Udesk」三方研发沟通会" \
  --description "客户方接口人 9/16 18:51 要求今天拉通……（含来源依据）" \
  --due 2026-09-17 \
  --assignee <OPEN_ID> \
  --format json

# ② 补「开始日期」——+update 不支持 start，只能走 tasks patch
lark-cli task tasks patch --task-guid <guid> \
  --data '{"task":{"start":{"timestamp":"1789603200000","is_all_day":true}},"update_fields":["start"]}'

# ③ 关联清单
lark-cli task +tasklist-task-add --tasklist-id <清单 guid> --task-id <guid,guid,guid>
```

- `--due` 接受 `2026-09-17` / ISO / `+2d` / 毫秒时间戳。**当天 all-day 的毫秒值**：2026-09-17 = `1789603200000`（= 当日 00:00 +08:00；换天按 86400000 递增，或用 `date -j -f "%Y-%m-%d %H:%M" "..." +%s` 换算）。
- ⚠️ **start 与 due 的 `is_all_day` 必须相同，且 start ≤ due**，否则 patch 报错。
- 建任务时若已知清单，可直接 `+create --tasklist-id <清单 guid>`；**补挂已有任务只能走 `+tasklist-task-add`**。

### 关联清单对照（用户的项目清单体系，2026-09-01 建）

| 清单 | guid |
| --- | --- |
| 客户A项目（2026-09-17 新建，补齐该套） | `<TASKLIST_GUID>` |
| 客户B项目 | `<TASKLIST_GUID>` |
| 客户C项目 | `<TASKLIST_GUID>` |
| 其他待办 | `<TASKLIST_GUID>` |

客户D项目 / FDE认证与团队事务 等清单也存在，但**客户D非本人主责，不往那里加**。清单 guid 会变，用前先 `task tasklists list --page-size 100` 确认。

- 无需 tasklist 的兜底：不传即落「我的任务」——但用户要求必须有清单，不要省这一步。
- 多条任务用 Python 脚本循环调 subprocess（含中文与多行描述时分号拼命令必翻车）；**不要在 bash `for` 里用 `set --` 拆参数**。

## 描述里带「对应多维表格」链接（用户 2026-09-17 明确要求）

描述**顶部固定两块**，原描述不要在链接之前：

```
【对应多维表格】<项目表名>（本任务对应记录 T99 ← 有线上的任务编号才写）
<链接含 ?table=&view=>

【任务详情】
<原有描述全文>
```

补写命令（**不要用 `+update`，它只认 summary/description/due 三个 flag；用 `tasks patch`**）：

```bash
lark-cli task tasks patch --task-guid <guid> \
  --data '{"task":{"description":"<新描述>"},"update_fields":["description"]}'
```

### 三个项目的正式链接（含视图，直接用）

| 项目 | 表名 | 链接 |
| --- | --- | --- |
| 客户A | 客户A&飞书项目推进计划表 › 上线计划总表 | `https://example.feishu.cn/base/<BASE_TOKEN>?table=<TABLE_ID>&view=<VIEW_ID>` |
| 客户B | 【客户B】飞书实施项目表 › 上线计划总表 | `https://example.feishu.cn/wiki/<WIKI_TOKEN>?table=<TABLE_ID>&view=<VIEW_ID>` |
| 客户C | 【客户C】项目上线计划表 › 上线计划总表 | `https://example.feishu.cn/base/<BASE_TOKEN>?table=<TABLE_ID>&view=<VIEW_ID>` |

- **客户B在 wiki 里，用 `/wiki/<node_token>`；另两个不在 wiki，用 `/base/<app_token>`**。判定：`lark-cli drive +inspect --url <url>` 看返回的 `wiki_node` 有没有值；或 `wiki +node-get --token <app_token> --obj-type bitable`，报 `131005 not found: document is not in wiki` 就是不在。
- ⚠️ **wiki 链接里的 node_token 不能当 `--base-token`**（实测 `91402 NOTEXIST`），调 API 必须用 `obj_token`（客户B = `<TOKEN>`）。
- 取视图 id：`lark-cli base +view-list --base-token <app_token> --table-id <tbl>` → 结果在 **`data.views[]`**（键是 `views` 不是 items，元素字段是 `id`/`name`/`type`）。优先选第一个 `type=grid` 且 name 为「全部/表格」的。
- 三个项目表由**同一模板拷贝**，`view_id` 都是 `<VIEW_ID>` —— view id 是**表内作用域**，跨表重复是正常的，不是抓错了。

### 「任务清单 ↔ 多维表格」没有原生绑定（别再承诺）

- Base 只有两条腿：① 左下角 **新建 > 导入/同步数据 > 连接器中心 > 飞书任务清单** → 把清单拉成一张**新建的只读同步表**（每小时自动刷、不可编辑、**挂不到已有项目表**）；② 自动化动作 **「创建飞书任务」** 从记录建任务，**不回写完成状态**。
- 命令侧**建不出来**：`lark-cli` 工作流节点枚举只有 `AddRecordAction / SetRecordAction / FindRecordAction / HTTPClientAction / Delay / LarkMessageAction / GenerateAiTextAction / AIAnalysisAction`，**没有创建任务节点** → 只能在网页端手工配。
- 用户要的是"任务里点得到那张表"，不是真绑定 —— 按上节写链接即可。

## 回读核验

```bash
# 清单维度
lark-cli task tasklists tasks --tasklist-guid <清单 guid> --page-size 50 --format json
# 逐条维度：start / due / tasklists / members
lark-cli task tasks get --task-guid <guid> --format json
```
核验点：① 条数 = 预期；② 每条 `start.timestamp` 与 `due.timestamp` 都有值且 all_day 一致；③ 每条 `tasklists` 非空且落在正确项目清单；④ `members` **只有 assignee 本人**；⑤ 描述第一行是 `【对应多维表格】…`、第二行是可点链接。

## 踩过的坑（照抄别再踩）

1. `lark-cli im +chat-messages-list` → `missing_scope: im:message.reactions:read`，**读群消息必失败**。一律走 `lark-cli api GET /open-apis/im/v1/messages`。
2. `base +record-list` **没有 `--page-all`**，用 `--limit 200`；`--base-token`（不是 `--app-token`）。
3. `base +record-list --field-id` 的**列序 = 传入顺序**，与 `field-list` 返回顺序无关；要按名字取列必须显式排 `--field-id`。
4. `base +field-list` 的字段名在 `data.fields[].name`（不是 `data.items`）。
5. `task +get-my-tasks` 没有 `--page-size`，用 `--page-limit` / `--page-all`。
6. `task +update` **只支持 summary / description / due**，改 start 必须 `task tasks patch --data`（`update_fields` 里必须显式列出 `start`，否则清空）。
7. `task tasklists list` 偶发 `1470500 Failed to list tasklist`（retryable）→ **去掉 `--page-all`、用 `--page-size 100` 即成功**。
8. 同一任务重复建：先查 `+get-my-tasks` 和项目清单内已有任务，已有的只补充（补 start / 挂清单）不新建。
9. bash `for` 循环内 `set -- $pair` 拆参数会让 lark-cli 抛出**上一次的陈旧错误**（unknown flag）——逐条直接执行命令最稳。
10. **清单权限坑（改挂必踩）**：别人建的清单挂不进去。例：`客户A飞书迁移项目待办（0826调研会）` `<TASKLIST_GUID>` 由团队负责人创建、成员仅一个服务群 viewer，本人不是成员 → `+tasklist-task-add` 报 `1470403 permission_denied`（user lacks permission）；换 bot 身份报 `99991672` 缺 `task:task:write` scope。**只能请清单创建者把本人加为 editor**。
    - 挂之前先 `task tasklists get --tasklist-guid <guid>` 看 `members` 里有没有自己。**清单只对无权限的人可见、不能写**，`tasklists list` 能看到 ≠ 能挂任务。
11. **任务移出清单没有可用接口**：CLI 无「移除清单内任务」；`DELETE /open-apis/task/v2/tasklists/{tl}/tasks/{guid}` → **404**。所谓「改挂」实际只能 = **挂到新清单 + 删掉旧清单（仅限自建、`task tasklists delete`）**。执行前务必先确认新清单挂得上，再删旧的，否则任务会失去全部清单关联。
12. **加共同负责人**：`task members add --task-guid <guid> --data '{"members":[{"id":"ou_xxx","type":"user","role":"assignee"}]}'`。客户B的协作人**FDE同事 = `<OPEN_ID>`**（与本人共担线上任务 T99 中间层）。
13. ★**`task +create --format json` 返回的 guid 在 `data.guid`，不是 `data.task.guid`**（2026-09-29 实测）。写脚本解析时按错路径取 → guid 为 None → `continue` 跳过后续 start patch，**任务其实已经建出来了**，于是出现「10 条任务全建了但一条都没有开始日期」。兜底修复：把执行前后的 `+get-my-tasks` 结果做**差集**（`guid not in before`）找出新建项再补 patch。
14. ★**start 的毫秒时间戳别自己用本地 `date` 换算**：CLI 内部按 UTC 基准存（同日 due 的实测值才是基准，如 9/29 = `1790640000000`），本地 `date -j -f` 得到的是 +08 基准，差 8 小时。**做法：先用 `--due <同日>` 建任务拿到 due.timestamp，再把这个值当 start 用**；写完必须回读比对 `start.timestamp == due.timestamp`（同日任务）。
15. **创建前先看旧任务堆积**：`+get-my-tasks` 里经常躺着更早的每日计划任务（2026-09-29 实测有 9/8–9/17 的客户B 5 条未完成、含已作废的 T103 编号）。同项目同事项**不要重复建**，改为在回复里列出「建议标完成的陈旧任务」请用户决定，不擅自 `task +update --completed`。
