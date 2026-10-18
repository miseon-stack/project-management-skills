# 项目管理 Skill 集

> 11 个可直接跑在 AI Agent 里的**项目管理 Skill**，覆盖「进度巡检 → 任务排期 → 日报/周报 → 会议转卡片 → 组合复盘」的完整闭环。
>
> 全部基于 [飞书开放平台](https://open.feishu.cn/) + [`lark-cli`](https://www.npmjs.com/package/lark-cli) 落地，方法论、脚本、踩坑记录均为实战沉淀。

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Skills](https://img.shields.io/badge/skills-11-blue.svg)](#一包含哪些-skill)

---

## 一、包含哪些 Skill

| # | Skill | 一句话定位 |
|---|---|---|
| 1 | [`feishu-project-progress-sentinel`](skills/feishu-project-progress-sentinel/) | **进度巡检哨兵**：扫群/文档/妙记 vs 线上表，出 P0/P1/P2 预警与群话术 |
| 2 | [`feishu-project-table-sync`](skills/feishu-project-table-sync/) | **项目表回写**：定位 base/table → 读现值 → dry-run → 批量写 → 回读验收 |
| 3 | [`feishu-daily-report`](skills/feishu-daily-report/) | **个人日报**：汇总当日 → 起草 → 确认 → 写入飞书日报表 |
| 4 | [`feishu-team-daily-digest`](skills/feishu-team-daily-digest/) | **团队日报横向梳理**：产能画像、协作图谱、风险信号 |
| 5 | [`feishu-meeting-cards`](skills/feishu-meeting-cards/) | **会议转任务卡**：纪要 → 报告 + 任务卡片 + 推进建议 |
| 6 | [`feishu-meeting-minutes-digest`](skills/feishu-meeting-minutes-digest/) | **纪要汇总**：当天所有会的结论与分派给自己的待办 |
| 7 | [`feishu-daily-task-plan`](skills/feishu-daily-task-plan/) | **每日任务计划**：读变更 → ≤10 条今日任务 → 建飞书任务并挂 Base |
| 8 | [`project-action-brief`](skills/project-action-brief/) | **行动清单**：讨论/决策记录 → 负责人 + 截止日的 follow-up |
| 9 | [`project-rhythm-check`](skills/project-rhythm-check/) | **进度体检**：数据源盘点 → P0-P2 重排 → T-1/D-Day 执行表 |
| 10 | [`project-portfolio-review`](skills/project-portfolio-review/) | **组合复盘**：多项目的里程碑/依赖/风险/产能冲突/待决策 |
| 11 | [`leader`](skills/leader/) | **目标任务书**：一句话想法 → ≤4000 字符可独立执行的任务书 |

前 7 个是**飞书深度集成**（需要 `lark-cli` 和有权限的用户身份）；第 8–11 个是**纯方法论型**，不依赖任何外部系统，放进任何 Agent 都能用。

## 二、安装

Skill 是「文件夹 + `SKILL.md`」的形式，Agent 启动时扫描技能目录自动加载。

```bash
git clone https://github.com/miseon-stack/project-management-skills.git
cd project-management-skills

# 装到用户级（所有项目可用）
cp -R skills/* ~/.workbuddy/skills/

# 或者只装到你当前项目
mkdir -p .workbuddy/skills && cp -R skills/* .workbuddy/skills/
```

> 目录约定：`~/.workbuddy/skills/<skill-name>/SKILL.md`。其他 Agent 平台（Claude Code、Cursor 等）只需把 `skills/*` 放到各自的 skills 目录即可，`SKILL.md` 的 frontmatter 格式通用。

安装后**重启会话**，技能才会出现在可用列表里。

### 前置条件

飞书类 Skill 需要：

1. 安装并登录 `lark-cli`，且使用**用户身份**（`--as user`）—— 应用/Bot 身份看不到你的 Base、群和日历。
2. 按各 Skill 的「先决条件」节申请对应 scope。常见几个容易漏的：

| scope | 用途 |
|---|---|
| `base:record:read` / `base:record:update` | 读写多维表格 |
| `space:document:retrieve` | 列出云盘文件夹 |
| `calendar:calendar.event:read` | 读日程（日报、任务计划依赖） |
| `task:task:write` | 创建任务、挂任务清单 |
| `im:message` / `im:message.send_as_user` | 读群消息 / 以本人身份发消息 |
| `minutes:minutes.artifacts:read` | 读妙记与智能纪要 |

## 三、脱敏口径（读之前先看这一节）

本仓库是**通用化脱敏版**。原件中含真实客户名、同事姓名、多维表格 token、群 ID、公司主体、本机路径等内部信息，已按下表统一替换：

| 类别 | 替换为 | 说明 |
|---|---|---|
| 客户名 | **客户A / 客户B / 客户C / 客户D / 其他客户** | 按项目分别对应不同客户；首次使用请换成你自己的项目名 |
| 同事姓名 | **本人 / 团队负责人 / CSM负责人 / CSM同事 / FDE同事 / 部门负责人 / 设计同事 / 同事** | 按角色代称，保留"谁在什么位置"的结构 |
| 客户方人员 | **客户方负责人 / 客户方接口人 / 客户IT负责人 / 客户管理员 / 客户营销负责人 / 客户产品负责人 / 客户高管 / 客户财务同事 / 客户开发人员** | 同上 |
| 公司主体 / 群名 | **我方公司 / 服务商 / 事业部&客户服务沟通群** 等泛化表述 | — |
| 多维表格 token | `<BASE_TOKEN>` `<TABLE_ID>` `<VIEW_ID>` `<FIELD_ID>` `<TOKEN>` | 需填入你自己 Base 的 token |
| 群 / 人 ID | `<CHAT_ID>` `<OPEN_ID>` `<GROUP_CODE>` | — |
| 凭据 | `<WEBHOOK_URL>` | 见 `secrets.local.json.example` |
| 本机路径 | `<WORKSPACE>` | 换成你的工作区根目录 |
| 租户域名 | `example.feishu.cn` | 换成你自己的 |

**未脱敏的内容**：产品名（飞书、多维表格、妙记、豆包等）、方法论、脚本逻辑、字段结构、踩坑记录、日期。这些是 Skill 的价值所在，保留才能用。

## 四、使用

装好之后，直接用自然语言触发对应场景即可，例如：

| 你说 | 触发的 Skill |
|---|---|
| "巡检一下项目" / "有什么风险和预警" | `feishu-project-progress-sentinel` |
| "把进度写进项目表" / "以线上为准核对一下" | `feishu-project-table-sync` |
| "写今天的日报" / "帮我提交日报" | `feishu-daily-report` |
| "看看其他人的日报" / "谁在做什么" | `feishu-team-daily-digest` |
| "把这段会议记录整理成任务" | `feishu-meeting-cards` |
| "今天开了哪些会" / "会议纪要整理一下" | `feishu-meeting-minutes-digest` |
| "排一下今天要做什么" | `feishu-daily-task-plan` |
| "把这个讨论整理成行动清单" | `project-action-brief` |
| "项目体检" / "下一步怎么排" | `project-rhythm-check` |
| "多个项目一起复盘一下" | `project-portfolio-review` |
| "帮我给 agent 写个目标" | `leader` |

### 需要你自己补的配置

只有 `feishu-project-progress-sentinel` 需要本地配置文件，其余 Skill 直接从对话里拿参数：

```bash
cd ~/.workbuddy/skills/feishu-project-progress-sentinel/references/

# 1) 项目登记册：填 base_token / table_id / field_ids / 群 ID
$EDITOR projects.json

# 2) 团队名单：区分"我方 / 客户方"发言
$EDITOR team.json

# 3) 机器人 webhook（仅推送卡片时需要；不填则相关功能优雅降级）
cp secrets.local.json.example secrets.local.json
$EDITOR secrets.local.json
```

## 五、注意事项

- **首次使用必然报权限错**：所有 `lark-cli` 调用都需要**有权限的用户身份**（`--as user`）。应用身份访问未授权的 Base 会返回 `91403`，这是预期行为，按各 Skill 的「先决条件」节处理。
- **`projects.json` 是模板不是可用配置**：里面的 token 全是占位符，必须换成你自己的。
- **`secrets.local.json` 不入库**：仓库只提交 `.example`，真实凭据文件由使用者本地生成（已在 `.gitignore` 中排除）。
- **口径类硬规则已保留**（如日报"不写遇到的问题""全文 ≤800 字"、写表"先 dry-run 再授权"），这些是实践沉淀，改之前先想清楚。
- **写操作默认都要二次确认**：回写线上表、发送群消息这类动作，Skill 会先给方案再等你授权，不会自己动手。

## 六、目录结构

```
project-management-skills/
├── README.md
├── LICENSE
├── .gitignore
└── skills/
    ├── feishu-daily-report/
    │   ├── SKILL.md
    │   └── scripts/submit_daily.py
    ├── feishu-project-progress-sentinel/
    │   ├── SKILL.md            # 57KB，最完整的一个
    │   ├── README.md / USAGE.md
    │   ├── references/         # projects.json / team.json / playbook.md
    │   ├── scripts/            # 14 个脚本：collect / analyze / push / run_all.sh …
    │   └── templates/
    ├── leader/
    │   ├── SKILL.md
    │   └── references/anatomy.md, style.md
    └── … 其余 8 个
```

## 七、License

[MIT](LICENSE) © 2026 miseon-stack

---

*脱敏口径：通用化替换（客户名 → 行业代称 / 人名 → 角色 / token → 占位符 / 公司主体 → 我方公司）。*
*目标：零客户可识别信息残留，同时保留全部方法论与脚本可用性。*
