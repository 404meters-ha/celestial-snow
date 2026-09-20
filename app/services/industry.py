"""定向行业分析、项目打标签、中文简介翻译——LLM 批量维护任务。

industry_pipeline：用户给一个行业词（如「生成视频」）→ LLM 规划关键词与代表项目 →
GitHub 搜索 + 逐个解析代表项目 → LLM 汇总行业格局报告 → 项目入库打标 → 库内已有项目匹配打标。

tagging_pipeline：一次性给库内全部项目建分类体系并打标签（不限定行业）。

translate_pipeline：为 zh_desc 缺失的项目批量生成中文一句话简介（已是中文的直接回填）。

由 TaskManager 驱动（经 api._submit 包装，签名 (github, *args, task_id, progress)）；
过程日志走 _append_log 时间线（比单行 progress 更能看出长任务在动）。
"""
import logging
import re

from sqlalchemy import select

from ..config import get_settings
from ..db import SessionLocal
from ..models import Analysis, IndustryReport, Repo, TaskRun
from ..tasks import _append_log
from .github_client import GitHubClient, GitHubRateLimitError
from .llm import (
    LLMClient,
    LLMNotConfigured,
    classify_repos,
    plan_industry,
    propose_taxonomy,
    report_industry,
    translate_descriptions,
)
from .pipeline import _upsert_repo
from .scoring import score_repo

logger = logging.getLogger(__name__)

INDUSTRY_TOP_N = 30  # 报告收录的项目数上限
SEARCH_KEYWORD_LIMIT = 5  # 有 token 时的搜索次数；无 token 时 Search API 10 次/分钟，砍半
FLAGSHIP_LIMIT = 15  # 逐个解析的 LLM 代表项目数上限
TAG_BATCH = 20  # 打标签分批大小


def _slim_repo(raw: dict) -> dict:
    """GitHub API 仓库对象（Search item / repo 详情通用）→ 候选与入库两用的精简结构。"""
    return {
        "full_name": raw.get("full_name") or "",
        "description": (raw.get("description") or "")[:300],
        "stars": int(raw.get("stargazers_count") or raw.get("stars") or 0),
        "language": raw.get("language") or "",
        "topics": raw.get("topics") or [],
        "homepage": raw.get("homepage") or "",
        "license": (raw.get("license") or {}).get("spdx_id") or "",
        "open_issues": int(raw.get("open_issues_count") or 0),
        "pushed_at": raw.get("pushed_at") or None,
        "github_created_at": raw.get("created_at") or None,
    }


async def industry_pipeline(github: GitHubClient, industry: str, task_id: str, progress) -> dict:
    settings = get_settings()
    llm = LLMClient()
    if not llm.configured:
        await llm.close()
        raise LLMNotConfigured("LLM 未配置（LLM_BASE_URL / LLM_API_KEY），无法做定向行业分析")

    def log(msg: str) -> None:
        _append_log(task_id, msg)  # 时间线 + 最新一行，长任务秒级可见

    stats: dict = {"industry": industry, "searched": 0, "flagship_resolved": 0,
                   "candidates": 0, "projects": 0, "tagged_existing": 0, "errors": []}
    try:
        # 1. LLM 规划：行业定义 + 子方向 + 搜索关键词 + 代表项目
        log(f"LLM 规划「{industry}」的调研关键词与代表项目…")
        plan = await plan_industry(llm, industry, settings.user_profile)
        keywords = [str(k).strip() for k in plan.get("search_keywords", []) if str(k).strip()]
        flagships = [str(r).strip() for r in plan.get("flagship_repos", []) if "/" in str(r)]
        log(f"规划完成：{len(keywords)} 个关键词、{len(flagships)} 个代表项目候选、"
            f"子方向 {len(plan.get('sub_categories', []))} 个")

        # 2. GitHub 按关键词搜索（stars 降序）；逐次容错，限流即止
        candidates: dict[str, dict] = {}
        kw_limit = SEARCH_KEYWORD_LIMIT if settings.github_token else max(SEARCH_KEYWORD_LIMIT // 2, 2)
        for kw in keywords[:kw_limit]:
            log(f"GitHub 搜索：{kw}")
            try:
                for raw in await github.search_repos(kw, per_page=30):
                    item = _slim_repo(raw)
                    if not item["full_name"]:
                        continue
                    old = candidates.get(item["full_name"])
                    if old is None or item["stars"] > old["stars"]:
                        candidates[item["full_name"]] = item
                    stats["searched"] += 1
            except GitHubRateLimitError as e:
                stats["errors"].append(str(e))
                log(f"搜索限流，提前结束：{e}")
                break
            except Exception as e:  # noqa: BLE001 单个关键词失败继续
                stats["errors"].append(f"搜索 {kw}: {e}")

        # 3. 解析 LLM 认知的代表项目（搜索结果里没有的逐个取详情，404 跳过）
        for name in flagships[:FLAGSHIP_LIMIT]:
            if name in candidates:
                stats["flagship_resolved"] += 1
                continue
            try:
                candidates[name] = _slim_repo(await github.get_repo(name))
                stats["flagship_resolved"] += 1
            except GitHubRateLimitError as e:
                stats["errors"].append(str(e))
                break
            except Exception as e:  # noqa: BLE001 模型记错名字/仓库没了都正常
                logger.info("代表项目解析失败 %s: %s", name, e)

        top = sorted(candidates.values(), key=lambda c: c["stars"], reverse=True)[:INDUSTRY_TOP_N]
        stats["candidates"] = len(candidates)
        if not top:
            raise ValueError("没有找到任何相关项目：换个更通用的行业词试试")
        log(f"候选项目合并去重后 {len(candidates)} 个，取 star 前 {len(top)} 个进入汇总")

        # 4. LLM 汇总行业报告（overview_md + 每项目分类定位）
        log(f"LLM 汇总「{industry}」行业格局报告…")
        report = await report_industry(llm, industry, settings.user_profile, plan, top)
        by_name = {c["full_name"]: c for c in top}
        entries: list[dict] = []
        for p in report.get("projects", []):
            name = str(p.get("full_name") or "").strip()
            base = by_name.get(name)
            if base is None:  # 模型偶尔改写 full_name，认不出的丢弃
                continue
            entries.append({**base, "category": str(p.get("category") or "").strip(),
                            "position": str(p.get("position") or "").strip()})
        if not entries:  # 全部对不上号就退回原始清单（无分类信息也比丢报告强）
            entries = [{**c, "category": "", "position": ""} for c in top]
        stats["projects"] = len(entries)

        # 5. 项目入库：走通用 upsert，统一打上行业 tag（periods 不动，非 trending 来源保持空）；
        #    新项目（rule_score 还是 0）按现有数据补一版规则分，榜单排序有据可依
        with SessionLocal() as session:
            for e in entries:
                repo = _upsert_repo(session, e)
                repo.tags = sorted(set((repo.tags or []) + [industry]))
                if not repo.rule_score:
                    repo.rule_score, repo.rule_detail = score_repo(e, period_stars=0, period_days=30)
            session.commit()
        log(f"{len(entries)} 个项目已入库并打上「{industry}」标签")

        # 6. 库内已有项目匹配打标（分批判断是否属于该行业，命中的补 tag）
        stats["tagged_existing"] = await _tag_existing_for_industry(llm, industry, plan, entries, log)

        # 7. 报告落库 + 任务 payload 挂 report_id（前端任务面板可直接跳转）
        with SessionLocal() as session:
            row = IndustryReport(
                name=industry,
                keywords=keywords,
                overview_md=str(report.get("overview_md") or ""),
                projects=[{**e, "in_lib": True} for e in entries],
                stats=stats,
                model=settings.llm_model,
                task_id=task_id,
            )
            session.add(row)
            session.commit()
            report_id = row.id
            run = session.get(TaskRun, task_id)
            if run is not None:
                run.payload = {**(run.payload or {}), "report_id": report_id}
                session.commit()
        log(f"行业报告已生成（#{report_id}）")
        return stats
    finally:
        await llm.close()


async def _tag_existing_for_industry(llm: LLMClient, industry: str, plan: dict,
                                     entries: list[dict], log) -> int:
    """判断库内已有项目（不含本次新入库的）哪些属于该行业，命中补 tag。"""
    new_names = {e["full_name"] for e in entries}
    with SessionLocal() as session:
        rows = session.execute(
            select(Repo).where(~Repo.full_name.in_(new_names)).order_by(Repo.stars.desc())
        ).scalars().all()
        compact = [
            {"full_name": r.full_name, "description": r.description[:150],
             "topics": (r.topics or [])[:6], "language": r.language}
            for r in rows
        ]
    if not compact:
        return 0

    tagged = 0
    sub_cats = [str(c) for c in plan.get("sub_categories", [])]
    for start in range(0, len(compact), TAG_BATCH):
        batch = compact[start : start + TAG_BATCH]
        try:
            # 候选分类只给行业名本身：命中 → [行业名]，不命中 → 其他（写入前过滤掉）
            tags_map = await classify_repos(llm, [industry], batch)
        except Exception as e:  # noqa: BLE001 批次失败不拖垮整体
            logger.warning("行业匹配批次失败: %s", e)
            continue
        hits = [n for n, tags in tags_map.items() if industry in tags and n not in new_names]
        if not hits:
            continue
        with SessionLocal() as session:
            for name in hits:
                repo = session.scalar(select(Repo).where(Repo.full_name == name))
                if repo is not None:
                    repo.tags = sorted(set((repo.tags or []) + [industry]))
                    tagged += 1
            session.commit()
        log(f"已有项目匹配 {start + len(batch)}/{len(compact)}：本批命中 {len(hits)} 个")
    return tagged


# ---------- 中文简介翻译 ----------

_CJK_RE = re.compile(r"[一-鿿]")


async def translate_pipeline(github: GitHubClient, task_id: str, progress) -> dict:
    """为 zh_desc 缺失的项目批量生成中文一句话简介（github 参数仅为契合 _submit 签名，不使用）。

    描述本身已是中文的直接回填（不耗 LLM）；其余分批翻译。只填空缺，不覆盖已有值
    （精析回填的 core_idea 版本与人工重跑都互不干扰）。
    """
    llm = LLMClient()
    if not llm.configured:
        await llm.close()
        raise LLMNotConfigured("LLM 未配置（LLM_BASE_URL / LLM_API_KEY），无法翻译简介")

    def log(msg: str) -> None:
        _append_log(task_id, msg)

    stats: dict = {"missing": 0, "copied": 0, "translated": 0, "errors": []}
    try:
        with SessionLocal() as session:
            rows = session.execute(
                select(Repo).where(Repo.zh_desc == "").order_by(Repo.stars.desc())
            ).scalars().all()
            stats["missing"] = len(rows)
            pending: list[Repo] = []
            copied = 0
            for r in rows:  # 描述已是中文的：直接回填，不进 LLM 批次
                if r.description and _CJK_RE.search(r.description):
                    r.zh_desc = r.description[:120]
                    copied += 1
                else:
                    pending.append(r)
            session.commit()
        stats["copied"] = copied
        if not pending:
            log(f"没有需要翻译的项目（缺失 {stats['missing']}，其中已是中文直接回填 {copied} 个）")
            return stats
        log(f"缺失中文简介 {stats['missing']} 个：{copied} 个描述已是中文直接回填，"
            f"{len(pending)} 个进入 LLM 翻译")

        done = 0
        for start in range(0, len(pending), TAG_BATCH):
            batch = pending[start : start + TAG_BATCH]
            slim = [
                {
                    "full_name": r.full_name,
                    "description": (r.description or "")[:200],
                    "language": r.language,
                    "topics": (r.topics or [])[:5],
                }
                for r in batch
            ]
            try:
                zh_map = await translate_descriptions(llm, slim)
            except Exception as e:  # noqa: BLE001 批次失败继续
                stats["errors"].append(f"批次 {batch[0].full_name}…: {e}")
                continue
            with SessionLocal() as session:
                for r in batch:
                    zh = zh_map.get(r.full_name)
                    if zh:
                        managed = session.scalar(select(Repo).where(Repo.full_name == r.full_name))
                        if managed is not None and not managed.zh_desc:
                            managed.zh_desc = zh[:120]
                            stats["translated"] += 1
                session.commit()
            done += len(batch)
            log(f"翻译 {done}/{len(pending)}…")
        log(f"完成：直接回填 {copied} + 翻译 {stats['translated']} 个")
        return stats
    finally:
        await llm.close()


# ---------- 全量自动分类打标 ----------

async def tagging_pipeline(github: GitHubClient, task_id: str, progress) -> dict:
    """一次性给库内全部项目建分类体系并打标签（github 参数仅为契合 _submit 签名，不使用）。"""
    llm = LLMClient()
    if not llm.configured:
        await llm.close()
        raise LLMNotConfigured("LLM 未配置（LLM_BASE_URL / LLM_API_KEY），无法自动分类")

    def log(msg: str) -> None:
        _append_log(task_id, msg)

    settings = get_settings()
    stats: dict = {"repos": 0, "categories": [], "tagged": 0, "errors": []}
    try:
        with SessionLocal() as session:
            rows = session.execute(
                select(Repo, Analysis)
                .outerjoin(Analysis, Analysis.repo_id == Repo.id)
                .order_by(Repo.stars.desc())
            ).unique().all()
            compact = [
                {
                    "full_name": r.full_name,
                    "description": r.description[:150],
                    "topics": (r.topics or [])[:6],
                    "language": r.language,
                    # 精析过的带上核心思想，分类更准
                    "core_idea": (a.core_idea or "")[:80] if a else "",
                }
                for r, a in rows
            ]
        if not compact:
            raise ValueError("库里还没有项目，先刷新榜单或做一次行业分析")
        stats["repos"] = len(compact)

        log(f"LLM 为 {len(compact)} 个项目提出分类体系…")
        categories = await propose_taxonomy(llm, compact)
        if not categories:
            raise ValueError("LLM 未返回有效分类体系，请重试")
        stats["categories"] = categories
        log(f"分类体系（{len(categories)} 类）：{'、'.join(categories)}")

        for start in range(0, len(compact), TAG_BATCH):
            batch = compact[start : start + TAG_BATCH]
            try:
                tags_map = await classify_repos(llm, categories, batch)
            except Exception as e:  # noqa: BLE001 批次失败继续
                stats["errors"].append(f"批次 {batch[0]['full_name']}…: {e}")
                continue
            with SessionLocal() as session:
                for name, tags in tags_map.items():
                    if not tags:
                        continue
                    repo = session.scalar(select(Repo).where(Repo.full_name == name))
                    if repo is not None:
                        # union 保留旧标签（如行业分析打的行业 tag），标签是累积的知识
                        repo.tags = sorted(set((repo.tags or []) + tags))
                        stats["tagged"] += 1
                session.commit()
            log(f"打标 {min(start + TAG_BATCH, len(compact))}/{len(compact)}…")
        log(f"完成：{stats['tagged']}/{stats['repos']} 个项目打上标签")
        return stats
    finally:
        await llm.close()
