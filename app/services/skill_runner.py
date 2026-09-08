"""通用技能执行器：把 Claude Code 技能变成平台可一键调用的能力。

机制：`claude -p "/<技能> <参数>"` 无头执行，cwd 固定在项目根。
技能（SKILL.md）是每次 claude 会话启动时从磁盘现读的——因此
新增/修改 `.claude/skills/` 或 `~/.claude/skills/` 下的技能，
下一次调用即生效，服务端无需重启，也没有任何注册动作。
"""
import asyncio
import json
import os
import re
import shutil
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
PROJECT_SKILLS_DIR = PROJECT_ROOT / ".claude" / "skills"
USER_SKILLS_DIR = Path.home() / ".claude" / "skills"


def _parse_frontmatter(text: str) -> dict:
    """SKILL.md 的 frontmatter 只有扁平 key: value，正则解析足够，不引 yaml 依赖。

    描述若是 YAML 折叠/字面标量（>、|- 等），回退为正文第一个非空行——列表展示够用。
    """
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)", text, re.S)
    fields: dict[str, str] = {}
    if not m:
        return fields
    for line in m.group(1).splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            fields[key.strip()] = value.strip().strip('"')
    if fields.get("description", "") in (">", ">-", "|", "|-", "|+", "+"):
        body_line = next((ln.strip() for ln in m.group(2).splitlines() if ln.strip()), "")
        fields["description"] = body_line[:120]
    return fields


def list_skills() -> list[dict]:
    """现扫磁盘（不缓存）：项目级覆盖同名的用户级。"""
    skills: list[dict] = []
    seen: set[str] = set()
    for scope, root in (("project", PROJECT_SKILLS_DIR), ("user", USER_SKILLS_DIR)):
        if not root.is_dir():
            continue
        for d in sorted(root.iterdir()):
            skill_md = d / "SKILL.md"
            if not d.is_dir() or not skill_md.is_file():
                continue
            try:
                fm = _parse_frontmatter(skill_md.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                continue
            name = fm.get("name") or d.name
            if name in seen:
                continue
            seen.add(name)
            skills.append({
                "name": name,
                "scope": scope,
                "description": fm.get("description", ""),
                "argument_hint": fm.get("argument-hint", ""),
            })
    return skills


def _child_env() -> dict:
    """剥离外层 Claude 会话的环境变量，避免嵌套会话检测/配置串扰。"""
    env = {k: v for k, v in os.environ.items()
           if k != "CLAUDECODE" and not k.startswith("CLAUDE_")}
    env["CI"] = "1"  # 无头环境：关闭交互式提示分支
    return env


async def run_skill(name: str, args: str, task_id: str, progress, timeout: int = 3600) -> dict:
    """无头执行一个技能，stream-json 事件实时转成任务进度。

    返回 {result, cost_usd, duration_ms, num_turns}；由调用方（任务层）落库。
    """
    from ..config import get_settings

    claude = shutil.which("claude")
    if not claude:
        raise RuntimeError("未找到 claude CLI（PATH 里没有 claude），无法无头执行技能")

    cmd = [claude, "-p", f"/{name} {args}".strip(), "--output-format", "stream-json", "--verbose"]
    if get_settings().skill_run_bypass_permissions:
        cmd.append("--dangerously-skip-permissions")

    proc = await asyncio.create_subprocess_exec(
        *cmd, cwd=str(PROJECT_ROOT),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        env=_child_env(),
    )
    progress(f"已启动 claude -p /{name}（pid {proc.pid}）")

    stderr_tail: list[str] = []

    async def _drain_stderr() -> None:
        while True:
            line = await proc.stderr.readline()
            if not line:
                return
            stderr_tail.append(line.decode("utf-8", errors="replace").rstrip())
            del stderr_tail[:-20]  # 只留尾部 20 行用于报错

    stderr_task = asyncio.create_task(_drain_stderr())
    result: dict = {"result": "", "cost_usd": None, "duration_ms": None, "num_turns": None}

    async def _pump() -> None:
        while True:
            line = await proc.stdout.readline()
            if not line:
                return
            raw = line.decode("utf-8", errors="replace").strip()
            if not raw.startswith("{"):
                continue
            try:
                event = json.loads(raw)
            except json.JSONDecodeError:
                continue
            etype = event.get("type")
            if etype == "assistant":
                for block in (event.get("message") or {}).get("content") or []:
                    if block.get("type") == "tool_use":
                        brief = str(block.get("input") or {}).replace("\n", " ")[:100]
                        progress(f"{block.get('name', 'tool')}: {brief}")
                    elif block.get("type") == "text" and block.get("text", "").strip():
                        progress("生成中: " + block["text"].strip().replace("\n", " ")[:100])
            elif etype == "result":
                result["result"] = event.get("result") or ""
                result["cost_usd"] = event.get("total_cost_usd")
                result["duration_ms"] = event.get("duration_ms")
                result["num_turns"] = event.get("num_turns")

    try:
        await asyncio.wait_for(asyncio.gather(_pump(), stderr_task, proc.wait()), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        raise RuntimeError(f"技能执行超时（>{timeout}s），已终止") from None

    if proc.returncode != 0:
        tail = "\n".join(stderr_tail[-10:]) or "(无 stderr)"
        raise RuntimeError(f"claude 退出码 {proc.returncode}：{tail}")

    progress("执行完成")
    return result
