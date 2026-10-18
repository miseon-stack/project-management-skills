# 项目进度巡检哨兵

> 一眼看清「线上实施表里写的」和「实际发生的」差多少，并给出**该做什么、该怎么跟客户说**。
> 覆盖项目：**客户A / 客户B / 客户C**。

## 先看哪份文档

| 你是谁 / 想干什么 | 打开 |
| --- | --- |
| **人**：想跑一轮巡检、看报告、调接口、排错 | **[`USAGE.md`](USAGE.md)** ← 操作手册（含复制即用的 curl） |
| **Agent / 开发者**：要改脚本、了解规则与踩坑 | [`SKILL.md`](SKILL.md) |
| 要看某天的实际产出 | `<工作区>/.workbuddy/巡检/`（**不入库**，含客户群摘要） |

## 一分钟上手

```bash
cd .workbuddy/skills/feishu-project-progress-sentinel/scripts
./run_all.sh                                # 一键：采集→快照→比对→diff→回灌判读→汇总
python3 suggest_verdicts.py --project all   # 出判读候选（半自动，人只做确认）
# 确认后（改 .suggested.json 或加 --promote），再跑一次回灌
./run_all.sh --skip-collect --no-diff
```

## 目录

```
README.md      本文件（入口）
USAGE.md       ★ 面向人的使用说明：命令、接口 curl、产出清单、红线、排错表
SKILL.md       技能定义与实现细节（Agent 读）
scripts/       14 个可直接跑的脚本
  run_all.sh           一键串联（含自动回灌当天判读）
  collect.py           采集：群消息 + 云文档 + 日历 + 会议妙记
  snapshot_table.py    线上表逐条快照（次日 diff 基线）
  analyze.py           比对 → findings + 巡检报告
  diff_findings.py     两日信号增删 / 级别变动
  diff_messages.py     两日新增群消息（事实增量）
  suggest_verdicts.py  半自动判读候选（翻本地交付物 + 群消息）
  apply_verdicts.py    人工判读合并进 findings 与报告
  group_msg.py         群内话术 + 存档材料
  push.py              卡片推送（默认 dry-run）
  api_server.py        本地 HTTP 接口（127.0.0.1:8787）
  sync_people.py       人员 open_id ↔ 姓名同步
  common.py            公共库
references/    项目 × 数据源登记册、团队名单、话术手册、周报规范
templates/     卡片模板
```

## 三条红线

1. **本技能不写线上表、不发群消息。** 回写表走 `feishu-project-table-sync`；发卡片必须人工加 `--send`。
2. **对外材料只做「可见性」必要替换**，不擅自改任务分工与负责人。
3. **接口只监听 `127.0.0.1`**，`/push` 恒为 dry-run —— 这是设计，不是待办。

## 入库范围

`skills/**` 入库（随 GitHub 私有仓备份）；`巡检/**` **不入库**（客户群摘要与内部判断，敏感度最高）；
`references/secrets.local.json`（webhook 等凭据）不入库，**换机器需手工补一份**，缺失时脚本自动降级。
