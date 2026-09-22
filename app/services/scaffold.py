"""脚手架链路编排：一句话需求 → 整体框架匹配（V1）；拆条与条目选型 V2 落地时补全。

match_pipeline：LLM 归纳需求与关键词 → 本地库（tags/精析优先）+ GitHub Search 双通道 →
双轨适配度评分（规则 0-40 + LLM 0-60，fit 指纹缓存优先）→ 回写候选与状态 →
新仓库入库打 domain 标签（下次同类需求本地库即命中，反哺情报站主库）。

由 TaskManager 驱动（经 api._submit 包装，签名 (github, *args, task_id, progress)）；
过程日志走 _append_log 时间线。设计见 doc/scaffold/architecture.md。
"""
import hashlib
import json
import logging
import re

from sqlalchemy import select

from ..config import get_settings
from ..db import SessionLocal
from ..models import Repo, ScaffoldCache, ScaffoldRequest, TaskRun
from ..tasks import _append_log
from .github_client import GitHubClient, GitHubRateLimitError
from .industry import _slim_repo
from .llm import LLMClient, LLMNotConfigured, scaffold_brief, scaffold_fit_batch
from .pipeline import _upsert_repo
from .scoring import scaffold_rule_fit, score_repo
from .tags import ensure_tags

logger = logging.getLogger(__name__)

MATCH_CANDIDATES = 8   # 整体匹配候选数上限
MATCH_MIN = 3          # 少于这个数说明检索面太窄，直接报错让用户换说法
SEARCH_KEYWORD_LIMIT = 5  # GitHub 搜索次数上限（无 token 砍半，同行业分析）
LOCAL_TOP_N = 5        # 本地库每个关键词取的条数


# ---------- 指纹与缓存 ----------

def _norm(text: str) -> str:
    """指纹前的规范化：去空白差异与大小写。"""
    return re.sub(r"\s+", " ", (text or "").strip()).lower()


def _fp(*parts: str) -> str:
    return hashlib.sha1("|".join(_norm(p) for p in parts).encode("utf-8")).hexdigest()


def _cache_get(key: str) -> dict | None:
    with SessionLocal() as session:
        row = session.get(ScaffoldCache, key)
        return row.payload if row else None


def _cache_put(key: str, kind: str, payload: dict) -> None:
    with SessionLocal() as session:
        if session.get(ScaffoldCache, key) is None:
            session.add(ScaffoldCache(key=key, kind=kind, payload=payload))
            session.commit()


def _json_like(value: str) -> str:
    """JSON 列的 LIKE 模式（topics/tags 存成 json.dumps 转义后的形态，见 api._json_like）。"""
    return f"%{json.dumps(value)}%"


# ---------- 整体匹配（V1） ----------

async def match_pipeline(github: GitHubClient, request_id: int, task_id: str, progress) -> dict:
    """整体框架匹配：需求一句话 → 候选 5-8 个（双轨适配度 + 理由）→ status=matched。"""
    settings = get_settings()
    with SessionLocal() as session:
        req = session.get(ScaffoldRequest, request_id)
        if req is None:
            raise ValueError(f"脚手架需求 {request_id} 不存在")
        raw_text = req.raw_text

    llm = LLMClient()
    if not llm.configured:
        await llm.close()
        raise LLMNotConfigured("LLM 未配置（LLM_BASE_URL / LLM_API_KEY），无法做框架匹配")

    def log(msg: str) -> None:
        _append_log(task_id, msg)

    stats: dict = {"searched": 0, "local_hits": 0, "candidates": 0, "new_repos": 0,
                   "fit_cached": 0, "errors": []}
    try:
        # 1. LLM 需求归纳 + 检索关键词规划
        log("LLM 归纳需求与检索关键词…")
        brief = await scaffold_brief(llm, raw_text, settings.user_profile)
        keywords = [str(k).strip() for k in brief.get("search_keywords", []) if str(k).strip()]
        keywords += [str(k).strip() for k in brief.get("tech_hints", []) if str(k).strip()]
        if not keywords:
            keywords = [raw_text]
        log(f"归纳完成：领域「{brief.get('domain', '?')}」，{len(set(keywords))} 个检索关键词")

        # 2. 本地库优先（需求关键词 × 描述/话题/标签，精析分高的排前）
        merged: dict[str, dict] = {}
        with SessionLocal() as session:
            for kw in dict.fromkeys(keywords[:4]):  # 去重保序
                rows = session.execute(
                    select(Repo)
                    .where(Repo.description.like(f"%{kw}%")
                           | Repo.full_name.like(f"%{kw}%")
                           | Repo.topics.like(_json_like(kw))
                           | Repo.tags.like(_json_like(kw)))
                    .order_by(Repo.total_score.desc())
                    .limit(LOCAL_TOP_N)
                ).scalars().all()
                for r in rows:
                    merged[r.full_name] = {
                        "full_name": r.full_name, "description": r.description[:300],
                        "zh_desc": r.zh_desc or "", "stars": r.stars, "language": r.language,
                        "topics": (r.topics or [])[:8], "license": r.license,
                        "pushed_at": r.pushed_at.isoformat() if r.pushed_at else None,
                        "github_created_at": (r.github_created_at.isoformat()
                                              if r.github_created_at else None),
                        "in_lib": True,
                    }
        stats["local_hits"] = len(merged)
        if merged:
            log(f"本地库命中 {len(merged)} 个相关项目")

        # 3. GitHub Search 补充（stars 降序；限流即止）
        kw_limit = SEARCH_KEYWORD_LIMIT if settings.github_token else max(SEARCH_KEYWORD_LIMIT // 2, 2)
        for kw in list(dict.fromkeys(keywords))[:kw_limit]:
            log(f"GitHub 搜索：{kw}")
            try:
                for raw in await github.search_repos(kw, per_page=15):
                    item = _slim_repo(raw)
                    if item["full_name"]:
                        merged.setdefault(item["full_name"], item)  # 本地命中优先，远程只补缺
                        stats["searched"] += 1
            except GitHubRateLimitError as e:
                stats["errors"].append(str(e))
                log(f"搜索限流，提前结束：{e}")
                break
            except Exception as e:  # noqa: BLE001 单个关键词失败继续
                stats["errors"].append(f"搜索 {kw}: {e}")

        ranked = sorted(merged.values(), key=lambda c: c["stars"], reverse=True)[:MATCH_CANDIDATES]
        if len(ranked) < MATCH_MIN:
            raise ValueError(f"只检索到 {len(ranked)} 个相关项目（需 ≥{MATCH_MIN}），换个更明确的说法试试")
        stats["candidates"] = len(ranked)

        # 4. 双轨评分：规则分（全量）+ LLM 批量评分（只评未缓存的）
        need_text = (f"{raw_text}\n归纳：{brief.get('summary', '')}；"
                     f"功能：{'、'.join(brief.get('features', []))}")
        item_fp = _fp(raw_text)  # 整体匹配阶段「条目指纹」= 需求指纹
        skills = [s.strip() for s in settings.user_skills.split(",") if s.strip()]
        llm_pend: list[dict] = []
        for c in ranked:
            c["clone_url"] = f"https://github.com/{c['full_name']}.git"
            c["rule_score"], c["rule_reason"] = scaffold_rule_fit(keywords, c, skills)
            cached = _cache_get(f"fit:{item_fp}:{c['full_name']}")
            if cached and "llm_score" in cached:
                c["llm_score"] = cached["llm_score"]
                c["reason"] = cached.get("reason", "")
                stats["fit_cached"] += 1
            else:
                llm_pend.append({"full_name": c["full_name"], "description": c.get("description", ""),
                                 "stars": c["stars"], "language": c.get("language", ""),
                                 "topics": (c.get("topics") or [])[:6]})
        if llm_pend:
            log(f"LLM 评估 {len(llm_pend)} 个候选的适配度…")
            try:
                scored = await scaffold_fit_batch(llm, need_text, llm_pend)
            except Exception as e:  # noqa: BLE001 评分失败不拖垮匹配（候选仍有规则分）
                stats["errors"].append(f"LLM 评分: {e}")
                log(f"LLM 评分失败，退回纯规则分：{e}")
                scored = []
            by_name = {s["full_name"]: s for s in scored if s.get("full_name")}
            for c in ranked:
                if "llm_score" in c:
                    continue
                s = by_name.get(c["full_name"]) or {}
                try:
                    c["llm_score"] = min(60, max(0, round(float(s.get("score") or 0) * 0.6)))
                except (TypeError, ValueError):
                    c["llm_score"] = 0
                c["reason"] = str(s.get("reason") or "")[:200]
                _cache_put(f"fit:{item_fp}:{c['full_name']}", "fit",
                           {"llm_score": c["llm_score"], "reason": c["reason"]})
        for c in ranked:
            c["fit_score"] = round(min(100, c["rule_score"] + c.get("llm_score", 0)), 1)
        ranked.sort(key=lambda c: c["fit_score"], reverse=True)

        # 5. 候选入库 + 打 domain 标签（累积知识，下次同类需求本地库直接命中）
        domain_raw = str(brief.get("domain") or "").strip()
        domain_tag = ""
        if domain_raw:
            try:
                mapping = await ensure_tags(llm, [domain_raw], source="scaffold")
                domain_tag = mapping.get(domain_raw, domain_raw)
            except Exception as e:  # noqa: BLE001 归一失败不阻塞，退回原词
                logger.info("domain 标签归一失败: %s", e)
                domain_tag = domain_raw
        with SessionLocal() as session:
            for c in ranked:
                if c.get("in_lib"):
                    continue
                repo = _upsert_repo(session, c)
                if domain_tag:
                    repo.tags = sorted(set((repo.tags or []) + [domain_tag]))
                if not repo.rule_score:
                    repo.rule_score, repo.rule_detail = score_repo(c, period_stars=0, period_days=30)
                c["in_lib"] = True
                stats["new_repos"] += 1
            session.commit()

        # 6. 回写需求记录 + 任务 payload 挂 stats/request_id（前端任务面板可直接跳详情）
        with SessionLocal() as session:
            req = session.get(ScaffoldRequest, request_id)
            req.need_brief = brief
            req.framework_candidates = ranked
            req.status = "matched"
            session.commit()
        with SessionLocal() as session:
            run = session.get(TaskRun, task_id)
            if run is not None:
                run.payload = {**(run.payload or {}), "stats": stats, "request_id": request_id}
                session.commit()
        log(f"匹配完成：{len(ranked)} 个候选，最高适配度 {ranked[0]['fit_score']}"
            f"（{ranked[0]['full_name']}）")
        return stats
    finally:
        await llm.close()
