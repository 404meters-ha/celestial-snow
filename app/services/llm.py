"""LLM provider：OpenAI 兼容 chat 接口（GLM coding plan 等），JSON 输出解析。

未配置 key 时抛 LLMNotConfigured，由上层决定降级（榜单只显示规则分，不阻塞抓取）。
"""
import json
import re

import httpx

from ..config import get_settings


class LLMNotConfigured(RuntimeError):
    pass


class LLMError(RuntimeError):
    pass


class LLMClient:
    def __init__(self) -> None:
        s = get_settings()
        self._base_url = s.llm_base_url.rstrip("/")
        self._api_key = s.llm_api_key
        self._model = s.llm_model
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers={"Authorization": f"Bearer {self._api_key}"},
            timeout=120,
        )

    @property
    def configured(self) -> bool:
        return bool(self._base_url and self._api_key)

    async def close(self) -> None:
        await self._client.aclose()

    async def chat(self, system: str, user: str, *, max_tokens: int = 4000) -> str:
        """单轮对话，返回助手文本。

        glm-4.7 等思考模型会把推理链写进 reasoning_content 并挤占 max_tokens，
        极端时 content 为空（finish_reason=length）——提取类任务一律关掉思考；
        端点不认 thinking 字段时自动退回普通请求。仍超长则翻倍 max_tokens 重试一次。
        """
        if not self.configured:
            raise LLMNotConfigured("LLM 未配置（LLM_BASE_URL / LLM_API_KEY）")
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        data = await self._post_chat(messages, max_tokens, thinking=False)
        if not (data.get("choices") or [{}])[0].get("message", {}).get("content"):
            # 空响应：翻倍额度再试一次（仍不带思考）
            data = await self._post_chat(messages, max_tokens * 2, thinking=False)
        try:
            return data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError) as e:
            raise LLMError(f"LLM 响应结构异常: {e}") from e

    async def _post_chat(self, messages: list[dict], max_tokens: int, *, thinking: bool) -> dict:
        payload: dict = {"model": self._model, "messages": messages, "max_tokens": max_tokens}
        if thinking is False:
            payload["thinking"] = {"type": "disabled"}
        resp = await self._client.post("/chat/completions", json=payload)
        if resp.status_code == 400 and "thinking" in resp.text and payload.get("thinking"):
            return await self._post_chat(messages, max_tokens, thinking=True)  # 旧端点不认该字段
        if resp.status_code != 200:
            raise LLMError(f"LLM 返回 {resp.status_code}: {resp.text[:300]}")
        return resp.json()

    async def chat_json(self, system: str, user: str, *, max_tokens: int = 4000) -> dict:
        """要求 JSON 输出并解析；模型偶尔包 ```json 围栏或夹带说明文字，逐一兜住。"""
        text = await self.chat(system, user, max_tokens=max_tokens)
        return parse_json_object(text)


def parse_json_object(text: str) -> dict:
    """从 LLM 输出中提取第一个平衡的 JSON 对象。"""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        newline = cleaned.find("\n")
        cleaned = cleaned[newline + 1 :] if newline >= 0 else ""
        end = cleaned.rfind("```")
        if end >= 0:
            cleaned = cleaned[:end]
    try:
        obj = json.loads(cleaned)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass
    # 首个平衡的 {...}
    start = cleaned.find("{")
    if start < 0:
        raise LLMError(f"LLM 输出中没有 JSON: {text[:200]}")
    depth = 0
    in_str = False
    escape = False
    for i in range(start, len(cleaned)):
        ch = cleaned[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    obj = json.loads(cleaned[start : i + 1])
                    if isinstance(obj, dict):
                        return obj
                except json.JSONDecodeError:
                    break
    raise LLMError(f"LLM 输出 JSON 无法解析: {re.sub(chr(10), ' ', text[:200])}")


# ---------- 领域 prompt ----------

ANALYZE_SYSTEM = """你是开源项目情报分析师。分析 GitHub 仓库的 README，输出严格 JSON（不要 markdown 围栏）：
{
  "core_idea": "这个项目要解决什么问题、核心思想是什么（150字内）",
  "enterprise_cases": [
    {"company": "公司/组织名", "scenario": "在什么场景用", "evidence": "README/官网原句（逐字引用）"}
  ],
  "enterprise_potential": {"score": 0-100, "reason": "评分理由（80字内）"},
  "match": {"score": 0-100, "reason": "与用户画像的匹配度及理由（80字内）"},
  "learning_value": {"score": 0-100, "reason": "核心思想/学习价值及理由（80字内）"}
}
enterprise_cases 只收 README/官网中**明确声明**的生产使用案例（如 "used by X in production"、官方用户列表）；
没有确凿证据就返回空数组，绝不凭记忆编造公司名。"""

PROFILE_NOTE = "用户画像（用于 match 维度）：{profile}"


async def analyze_repo(llm: LLMClient, profile: str, full_name: str, readme: str) -> dict:
    """LLM 精析单个仓库：核心思想 + 企业案例（保守提取）+ 三维评分。"""
    user = PROFILE_NOTE.format(profile=profile) + f"\n\n仓库：{full_name}\n\nREADME（截断）：\n{readme[:12000]}"
    return await llm.chat_json(ANALYZE_SYSTEM, user)


SCREEN_SYSTEM = """你是开源贡献机会筛选器。给定仓库信息、用户技能清单和 open issues 列表（JSON），挑出**适合外部贡献者**参与的 issue 并打匹配分。
排除：核心维护者的内部任务、缺复现步骤且无人回应的、需要深度领域知识而外部人无法上手的。
输出严格 JSON（不要 markdown 围栏）：
{"picked": [{"number": 123, "match": 0-100, "difficulty": "低|中|高", "reason": "为什么适合这位开发者（50字内）"}]}
match 是「与用户技能方向的贴合度 + 外部贡献者上手可行性」综合分；最多挑 8 个；一个都没有就返回 {"picked": []}。"""

REPORT_SYSTEM = """你是开源贡献导师，面向一位「后端为主、正在扩展 AI 应用方向」的开发者。对单个 issue 输出深度解读，严格 JSON（不要 markdown 围栏）：
{"number": 123,
 "title": "原标题",
 "url": "issue 链接",
 "labels": ["标签"],
 "background": "这个 issue 的来龙去脉（120字内）",
 "why_it_matters": "为什么值得修/是坑（100字内）",
 "modules": "预计涉及的代码模块/目录（按仓库结构推测）",
 "difficulty": "低|中|高",
 "approach": "建议切入方式（120字内，具体可执行）",
 "fit_reason": "为什么适合这位开发者"}
全部中文。"""

VERDICT_SYSTEM = """你是开源贡献顾问。基于仓库概况、已挑选的 issue 清单和 CONTRIBUTING 情况，给出这个仓库值不值得投入的综合判断，严格 JSON（不要 markdown 围栏）：
{"verdict": "综合判断（150字内）",
 "worth_investing": true,
 "directions": ["除这些 issue 外的长期贡献方向建议"],
 "health": "维护活跃度/社区友好度/对新人态度的评价（100字内）"}
全部中文。"""

SUMMARIZE_SYSTEM = """你是 issue 摘要器。对输入的每个 GitHub issue 输出一句话摘要和一句话行动建议，严格 JSON（不要 markdown 围栏）：
{"items": [{"number": 123,
  "summary": "这个 issue 说了个什么事（≤50字，具体到现象/需求本身，不要套话）",
  "action": "需要贡献者做什么（≤50字，具体可执行的下一步）"}]}
必须覆盖输入里的每一个 number；正文太短看不出所以然的，summary 写标题的展开、action 写「阅读 issue 并向维护者确认复现步骤」这类合理下一步。全部中文。"""


async def summarize_issues(llm: LLMClient, issues: list[dict]) -> dict[int, dict]:
    """批量摘要：输入 [{number, title, body}]，返回 {number: {summary, action}}。"""
    if not issues:
        return {}
    user = json.dumps(
        [{"number": i["number"], "title": i.get("title", ""), "body": (i.get("body") or "")[:600]} for i in issues],
        ensure_ascii=False,
    )
    data = await llm.chat_json(SUMMARIZE_SYSTEM, user, max_tokens=3000)
    return {item["number"]: item for item in data.get("items", []) if item.get("number") is not None}


async def screen_issues(llm: LLMClient, full_name: str, contributing: str, issues: list[dict], skills: str) -> list[dict]:
    """LLM 预筛适合外部贡献者的 issue，返回 [{number, match, difficulty, reason}]。"""
    slim = [
        {
            "number": i["number"],
            "title": i.get("title", ""),
            "labels": [lb.get("name", "") for lb in i.get("labels", [])],
            "comments": i.get("comments", 0),
            "body": (i.get("body") or "")[:800],
            "created_at": i.get("created_at", ""),
        }
        for i in issues
    ]
    user = (
        f"仓库：{full_name}\n用户技能：{skills}\n"
        f"CONTRIBUTING 摘要：{contributing[:1500] or '（无）'}\n\n"
        f"open issues（{len(slim)} 个）：\n{json.dumps(slim, ensure_ascii=False)}"
    )
    data = await llm.chat_json(SCREEN_SYSTEM, user, max_tokens=3000)
    return data.get("picked", [])


async def report_issue(
    llm: LLMClient, profile: str, full_name: str, issue: dict, comments: list[dict], contributing: str
) -> dict:
    """单 issue 深度解读。"""
    comment_text = "\n".join(
        f"- {c.get('user', {}).get('login', '?')}: {(c.get('body') or '')[:400]}" for c in comments
    )
    user = (
        f"用户画像：{profile}\n仓库：{full_name}\n"
        f"CONTRIBUTING 摘要：{contributing[:1000] or '（无）'}\n\n"
        f"Issue #{issue['number']} {issue.get('title', '')}\n"
        f"正文：{(issue.get('body') or '')[:2500]}\n\n评论（最近）：\n{comment_text or '（无）'}"
    )
    data = await llm.chat_json(REPORT_SYSTEM, user, max_tokens=2500)
    return data if data else {}


async def repo_verdict(
    llm: LLMClient,
    full_name: str,
    repo_meta: dict,
    picked: list[dict],
    contributing: str,
    contributors_count: int,
) -> dict:
    """仓库综合判断：值不值得投入。"""
    user = (
        f"仓库：{full_name}\n概况：{json.dumps(repo_meta, ensure_ascii=False)}\n"
        f"贡献者数量：{contributors_count}\n"
        f"CONTRIBUTING：{'有' if contributing else '无'}\n"
        f"已挑选的 issue：{json.dumps(picked, ensure_ascii=False)}"
    )
    return await llm.chat_json(VERDICT_SYSTEM, user, max_tokens=1500)
