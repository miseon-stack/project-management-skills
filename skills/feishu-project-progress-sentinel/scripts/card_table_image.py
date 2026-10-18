#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""【表格卡图片化】把表格渲染成 PNG，供飞书卡片 `img` 元素使用。

为什么需要它：卡片 2.0 的原生 `table` 组件在本人的飞书客户端上**不渲染**，
位置显示为「暂时无法在飞书文档外展示此内容」（markdown/hr 正常）——2026-09-23 实测。
所以「对齐表格」类卡片一律走图片路线。

流程：本脚本出 PNG → `lark-cli im images create --as bot --data '{"image_type":"message"}' --file ./x.png`
→ 卡片里用 `{"tag":"img","img_key":"img_v3_xxx","scale_type":"fit_horizontal","preview":true,...}`。

**怎么用**：复制本文件，改 ROWS_A / ROWS_B 两组数据和对应标题即可。其余不用动。

硬约束（上传接口）：宽 ≤1500px、高:宽 ≤16:9、≤10M —— 逻辑宽固定 1500，
脚本会自检高宽比，超 16:9 会打 ✗（此时拆成两张图）。
字号 19px/20px 起步：图片在卡片里被缩到 ~600px 宽（0.4×），小了就糊。
"""
import os
import re
import shutil
import subprocess
import time

HERE = os.path.dirname(os.path.abspath(__file__))
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PROFILE = "/tmp/chrome-sales-shot"
W = 1500

FONT = ('-apple-system, "PingFang SC", "Hiragino Sans GB", '
        '"Microsoft YaHei", "Noto Sans CJK SC", sans-serif')

CSS = f"""
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: {FONT}; background: #ffffff; width: {W}px;
        color: #1f2329; -webkit-font-smoothing: antialiased; }}
.wrap {{ padding: 38px 40px 42px 40px; }}
.title {{ font-size: 34px; font-weight: 700; letter-spacing: .5px; }}
.sub {{ font-size: 19px; color: #8f959e; margin-top: 8px; }}
.rule {{ height: 3px; background: #3370ff; width: 92px; margin: 18px 0 26px 0;
         border-radius: 2px; }}
table {{ width: 100%; border-collapse: separate; border-spacing: 0;
         border: 1px solid #e5e6eb; border-radius: 10px; overflow: hidden;
         table-layout: fixed; }}
th {{ background: #f2f3f5; font-size: 20px; font-weight: 700; color: #1f2329;
      text-align: left; padding: 16px 14px; border-bottom: 1px solid #e5e6eb;
      border-right: 1px solid #e5e6eb; }}
th:last-child {{ border-right: none; }}
td {{ font-size: 19px; line-height: 1.6; color: #1f2329; vertical-align: top;
      padding: 15px 14px; border-bottom: 1px solid #eef0f3;
      border-right: 1px solid #eef0f3; word-break: break-word; }}
tr:last-child td {{ border-bottom: none; }}
td:last-child {{ border-right: none; }}
tr:nth-child(even) td {{ background: #fafbfc; }}
.mod {{ font-weight: 700; vertical-align: middle; white-space: nowrap; }}
.g-sale {{ background: #eef4ff !important; color: #1f4b99; }}
.g-crm {{ background: #f5f0fd !important; color: #6b32a8; }}
.g-dash {{ background: #fff5e8 !important; color: #a85508; }}
.g-int {{ background: #edf7ee !important; color: #2f6b39; }}
.g-pm {{ background: #f2f3f5 !important; color: #5b6068; }}
.g-now {{ background: #fff1f0 !important; color: #c9362b; }}
.g-later {{ background: #f2f3f5 !important; color: #5b6068; }}
.dot {{ display: inline-block; width: 13px; height: 13px; border-radius: 50%;
        margin-right: 9px; vertical-align: 1px; }}
.d-red {{ background: #f53f3f; }} .d-grey {{ background: #b4b8c0; }}
.lead {{ font-weight: 700; }}
.help {{ color: #5b6068; }}
.foot {{ margin-top: 20px; font-size: 18px; color: #8f959e; line-height: 1.7; }}
"""

# ------------------------------------------------------------------ 图 A
# (模块, 分组class, 事项, 飞书方, 客户方, 推进内容, 输出物)
ROWS_A = [
    ("销售周报AI方案", "g-sale", "收集现有周报模板",
     "本人", "客户管理员",
     "客户管理员收集客户方接口人、杨同礼、王敏亮等部门周报；本人整理分析不同模板共性", "周报样本库"),
    ("销售周报AI方案", "g-sale", "周报模板统一设计",
     "本人", "客户方接口人 / 客户管理员",
     "根据销售管理要求确定核心字段，减少销售填写成本", "《销售周报标准模板》"),
    ("AI周报Agent", "g-sale", "Agent设计与Demo开发",
     "本人", "客户方接口人提供业务规则",
     "设计Agent逻辑，将CRM、飞书沟通、ERP数据生成周报", "AI销售周报Demo"),
    ("CRM MCP测试", "g-crm", "MCP连接与能力验证",
     "客户IT负责人（技术协同）/ 本人", "客户管理员（账号）、客户IT负责人（内部系统）",
     "使用CRM账号测试MCP连接，验证商机2.0字段读取能力", "MCP测试结果"),
    ("CRM字段梳理", "g-crm", "商机2.0字段确认",
     "本人", "客户方接口人 / 客户IT负责人",
     "客户方接口人确认核心业务字段；客户IT负责人确认技术可读取范围", "CRM字段清单"),
    ("数据脱敏", "g-crm", "测试数据准备",
     "本人", "客户管理员",
     "客户管理员使用豆包进行数据脱敏，提供给飞书团队测试", "脱敏数据包"),
    ("销售经营驾驶舱", "g-dash", "指标体系设计",
     "本人", "客户方接口人 / 客户高管",
     "明确老板关注指标：客户进展、订单、回款、风险项目", "看板需求文档"),
    ("销售经营驾驶舱", "g-dash", "多维表及看板搭建",
     "本人", "客户管理员协助验证",
     "根据指标搭建飞书多维表、Dashboard", "看板Demo"),
    ("CRM/ERP集成方案", "g-int", "数据链路评估",
     "客户IT负责人 / 本人", "客户IT负责人、团队负责人协调",
     "判断CRM MCP、ERP接口、多维表同步方案", "集成方案"),
    ("ERP数据应用", "g-int", "ERP订单分析场景",
     "本人", "客户IT负责人",
     "明确订单、发货、回款数据来源及业务逻辑", "AI订单分析方案"),
    ("供应链交付", "g-int", "投产、交期、库存场景",
     "本人", "客户管理员、黄双",
     "梳理投产计划、RF需求、库存分配流程", "AI交付助手方案"),
    ("项目推进管理", "g-pm", "项目群/项目任务管理",
     "本人", "客户管理员",
     "建立项目跟进机制，跟踪CRM、ERP、AI周报事项", "项目推进表"),
]

WIDTHS_A = ["12%", "13.5%", "14.5%", "16.5%", "27%", "12%"]


def build_a():
    cols = "".join(f'<th style="width:{w}">{c}</th>' for c, w in zip(
        ["模块", "事项", "飞书方负责人", "客户A负责人", "需要推进内容", "输出物"],
        WIDTHS_A))

    # 相邻同模块合并第一列（rowspan）
    groups = []
    for r in ROWS_A:
        if groups and groups[-1][0] == r[0]:
            groups[-1][1].append(r)
        else:
            groups.append([r[0], [r]])
    body = []
    for mod, rows in groups:
        cls = rows[0][1]
        for i, r in enumerate(rows):
            tds = []
            if i == 0:
                tds.append(f'<td class="mod {cls}" rowspan="{len(rows)}">{mod}</td>')
            tds.append(f'<td class="lead">{r[2]}</td>')
            tds.append(f'<td>{r[3]}</td>')
            tds.append(f'<td>{r[4]}</td>')
            tds.append(f'<td class="help">{r[5]}</td>')
            tds.append(f'<td>{r[6]}</td>')
            body.append("<tr>" + "".join(tds) + "</tr>")
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<style>{CSS}</style></head><body><div class="wrap">
<div class="title">AI 销售管理 · 责任分工总表</div>
<div class="sub">按具体负责人拆分 · 12 项事项 · 2026-09-23</div>
<div class="rule"></div>
<table><thead><tr>{cols}</tr></thead><tbody>{''.join(body)}</tbody></table>
</div>
<div id="__sz" style="font-size:1px;color:#fff"></div>
<script>document.getElementById('__sz').textContent =
  'H=' + Math.ceil(document.body.scrollHeight) +
  ' W=' + Math.ceil(document.body.scrollWidth);</script>
</body></html>"""


# ------------------------------------------------------------------ 图 B
# (时间, 时间格class, 圆点class, 事项, 负责人)
ROWS_B = [
    ("国庆前", "g-now", "d-red", "收集各部门销售周报样本", "客户管理员"),
    ("国庆前", "g-now", "d-red", "周报样本脱敏", "客户管理员"),
    ("国庆前", "g-now", "d-red", "分析周报结构、输出统一模板", "本人"),
    ("国庆前", "g-now", "d-red", "CRM MCP连接测试", "客户IT负责人 + 客户管理员"),
    ("国庆前", "g-now", "d-red", "验证商机2.0关键字段", "客户IT负责人 + 客户方接口人"),
    ("国庆前", "g-now", "d-red", "AI周报Demo开发", "本人"),
    ("后续", "g-later", "d-grey", "看板指标确认", "客户方接口人 + 客户高管"),
    ("后续", "g-later", "d-grey", "CRM/ERP集成方案确认", "团队负责人 + 客户IT负责人"),
]


def build_b():
    body = []
    i = 0
    while i < len(ROWS_B):
        t, tcls, *_ = ROWS_B[i]
        j = i
        while j < len(ROWS_B) and ROWS_B[j][0] == t:
            j += 1
        span = j - i
        for k in range(i, j):
            r = ROWS_B[k]
            tds = []
            if k == i:
                tds.append(f'<td class="mod {r[1]}" rowspan="{span}">'
                           f'<span class="dot {r[2]}"></span>{t}</td>')
            tds.append(f'<td class="lead">{r[3]}</td>')
            tds.append(f'<td>{r[4]}</td>')
            body.append("<tr>" + "".join(tds) + "</tr>")
        i = j
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<style>{CSS}
th:nth-child(1), td:nth-child(1) {{ width: 175px; }}
th:nth-child(3), td:nth-child(3) {{ width: 340px; }}
</style></head><body><div class="wrap">
<div class="title">当前第一阶段明确负责人</div>
<div class="sub">国庆前 6 项跑通闭环，后续 2 项随数据链路推进</div>
<div class="rule"></div>
<table><thead><tr><th>时间</th><th>事项</th><th>负责人</th></tr></thead>
<tbody>{''.join(body)}</tbody></table>
<div class="foot">会议明确的角色关系：客户方接口人负责业务需求定义与销售管理规则确认；客户管理员承担资料收集、账号协调与内部推进；
客户IT负责人负责技术侧 CRM MCP 与数据连接能力验证；团队负责人负责整体项目协调与集成团队推进。</div>
</div>
<div id="__sz" style="font-size:1px;color:#fff"></div>
<script>document.getElementById('__sz').textContent =
  'H=' + Math.ceil(document.body.scrollHeight) +
  ' W=' + Math.ceil(document.body.scrollWidth);</script>
</body></html>"""


# ------------------------------------------------------------------ Chrome
def run_chrome(args, timeout=60):
    p = subprocess.Popen([CHROME] + args, stdout=subprocess.PIPE,
                         stderr=subprocess.DEVNULL)
    try:
        out, _ = p.communicate(timeout=timeout)
        return out.decode("utf-8", "ignore")
    except subprocess.TimeoutExpired:
        p.kill()
        out, _ = p.communicate()
        return out.decode("utf-8", "ignore")


def measure(html_path):
    dom = run_chrome([
        "--headless=new", "--disable-gpu", "--no-sandbox", "--hide-scrollbars",
        "--disable-background-networking", "--disable-component-update",
        "--disable-sync", "--disable-default-apps", "--no-first-run",
        "--no-default-browser-check", f"--user-data-dir={PROFILE}",
        f"--window-size={W},1400", "--virtual-time-budget=3000",
        "--dump-dom", f"file://{html_path}"])
    m = re.search(r"H=(\d+) W=(\d+)", dom)
    return (int(m.group(1)), int(m.group(2))) if m else (None, None)


def shoot(html_path, out_png, height):
    tmp = out_png[:-4] + ".shooting.png"
    if os.path.exists(tmp):
        os.remove(tmp)
    p = subprocess.Popen([
        CHROME, "--headless=new", "--disable-gpu", "--no-sandbox",
        "--hide-scrollbars", "--disable-background-networking",
        "--disable-component-update", "--disable-sync",
        "--disable-default-apps", "--no-first-run", "--no-default-browser-check",
        f"--user-data-dir={PROFILE}", f"--window-size={W},{height}",
        "--virtual-time-budget=3000", f"--screenshot={tmp}",
        f"file://{html_path}"], stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL)
    for _ in range(40):
        if os.path.exists(tmp) and os.path.getsize(tmp) > 0:
            time.sleep(1.5)
            break
        time.sleep(0.5)
    p.kill()
    p.wait()
    if os.path.exists(tmp) and os.path.getsize(tmp) > 0:
        shutil.move(tmp, out_png)
        return os.path.getsize(out_png)
    return 0


def main():
    os.makedirs(PROFILE, exist_ok=True)
    for name, html, png in [("owner", build_a(), "img-owner.png"),
                            ("stage1", build_b(), "img-stage1.png")]:
        hp = os.path.join(HERE, f"{name}.html")
        with open(hp, "w", encoding="utf-8") as f:
            f.write(html)
        h, w = measure(hp)
        if not h:
            print(f"[{name}] 测量失败")
            continue
        ratio = h / w
        print(f"[{name}] {w}x{h} 高宽比 {ratio:.2f} "
              f"{'✓' if ratio <= 16 / 9 else '✗ 超 16:9 限制'}", end="  ")
        size = shoot(hp, os.path.join(HERE, png), h)
        print(f"→ {png} {size} 字节", "✓" if size else "✗")


if __name__ == "__main__":
    main()
