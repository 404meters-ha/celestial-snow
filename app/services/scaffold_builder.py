"""脚手架生成器：把「需求 + 技术条目 + 开源选型」交给 agent_sdk 生成可启动项目骨架。

S6（技术验证门）先落生成规范与 prompt 组装；S7 补全管线：
base 预判 → agent 生成 → 六件套校验 → zipfile 打包 → 产物指纹缓存。
设计见 doc/scaffold/architecture.md 第 4 节。
"""

# 生成轮次上限：整项目 10+ 文件，/tech 课程实测 16 轮起步，60 不够用
BUILD_MAX_TURNS = 120
# 单轮输出上限：vendor 默认 openai 回落 8192，整文件写入的轮次不够用
BUILD_MAX_TOKENS = 16384

# 平台侧校验的六件套（缺任一即 build 任务失败，见 stories.md S7-AC2）
REQUIRED_FILES = [
    "README.md",          # 启动说明（三步内）
    "LICENSES.md",        # 各组件 license 清单
    "docs/research.md",   # 行业调研文档（全链路汇编）
    "docs/requirement.md",  # 原始需求 + 归纳
    "docs/architecture.md",  # 条目 + 选型 + 集成关系
]

SCAFFOLD_SYSTEM = """你是 celestial-snow 平台的脚手架生成 agent，任务：把「用户需求 + 技术条目 + 开源选型」\
变成一个解压即可启动的项目骨架。

## 环境与工具
- 你运行在云服务进程内，没有 Shell，不能执行安装/运行命令——产物必须做到「用户解压后按 README 三步内启动成功」。
- 工具：WebFetch（查开源项目 README/文档，辅助集成）、ReadFile/ListDir（核对已写文件）、
  WriteFile（写工作区文件）、PlatformAPI（调平台 API）。
- 所有文件只写到本次任务指定的工作区目录下。

## 产物规范（六件套，缺一不可）
1. 项目代码骨架：base 框架的目录结构 + 每个技术条目一个模块位（文件/包 + 最小可运行实现）
2. 前端页面：必有。浏览器打开即用的入口页（优先零构建：原生 HTML/JS 或 CDN 引入库），作为项目控制台或主界面
3. docs/research.md：行业调研文档——候选对比与选型理由全链路留痕（任务输入会提供素材）
4. docs/requirement.md：原始需求（用户原话）+ 系统归纳
5. docs/architecture.md：技术条目清单、每条选型结果与集成关系（谁挂在谁上面）
6. LICENSES.md：所用开源组件的 license 列表（组件 / 仓库 / 协议）

## 验收线（平台会校验，也是你的完成标准）
- 解压 → 装依赖（pip install -r requirements.txt 或 npm install）→ README 里的一条启动命令 → 页面可打开
- 每个条目模块的接口位接好；核心业务逻辑用结构化 TODO 占位，格式统一：
  `# TODO [条目名] 一句话描述 | 参考: owner/repo | 状态: 待实现`
- 不承诺功能完整——骨架能跑、结构清晰、TODO 指路即可

## 选型落位规则
- 包型选型（以 pip/npm 包分发的）→ 进依赖清单 requirements.txt / package.json，代码里 import 使用
- 应用型选型（独立运行的程序）→ vendor/ 下放 README 说明 + clone.sh 克隆脚本，不打包其源码
- 自研条目（无开源选型）→ 从零写最小骨架

## 质量要求
- 文件总量 10-25 个，单文件不超过 ~300 行
- 每写完一批用 ListDir 核对；最后清点六件套齐全
- README 启动步骤 ≤3 步，写清端口与访问地址
- 文档中文；代码命名贴合所选生态的惯例
"""


def build_prompt(raw_text: str, need_brief: dict, items: list[dict],
                 base_hint: str, workspace: str) -> str:
    """组装一次生成任务的指令。items 元素含 no/name/desc/keywords/selected(或 None=自研)/reason。"""
    lines = [f"## 本次任务\n", f"### 用户需求（原话）\n{raw_text}\n"]
    if need_brief:
        brief = need_brief if isinstance(need_brief, str) else "\n".join(
            f"- {k}: {v}" for k, v in need_brief.items() if v)
        lines.append(f"### 需求归纳\n{brief}\n")
    lines.append("### 技术条目与选型")
    for it in items:
        sel = it.get("selected") or "自研（无开源选型，从零写最小骨架）"
        lines.append(
            f"{it.get('no')}. {it.get('name')} → {sel}\n"
            f"   职责：{it.get('desc', '')}\n   选型理由：{it.get('reason', '')}")
    lines.append(f"\n### base 框架\n{base_hint}\n")
    lines.append(f"### 工作区\n`{workspace}` —— 所有文件写该目录下，zip 将从该目录打包。\n")
    lines.append(
        "现在开始：先简短规划文件清单（10 行以内），然后逐个 WriteFile 生成，"
        "最后 ListDir 核对六件套齐全并输出一段总结（生成了什么、怎么启动、遗留 TODO 数）。")
    return "\n".join(lines)
