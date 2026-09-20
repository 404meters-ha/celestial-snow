"""全局配置：.env + 环境变量，全部可通过 .env 覆盖。"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # GitHub
    github_token: str = ""
    github_proxy: str = ""  # 空则不启用 trending 网页爬取通道

    # LLM（OpenAI 兼容）
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = "glm-4.7"

    # 搜索
    search_provider: str = ""  # bocha | tavily | zai | 空
    search_api_key: str = ""

    # 用户画像（贡献方向推荐与匹配度评分用）
    user_profile: str = "后端开发为主（Java/Python），正在扩展 AI 应用方向，关注 AI 基建、开发者工具"
    # 技能清单（issue 规则预分关键词 + LLM 匹配提示），逗号分隔
    user_skills: str = "Python,Java,FastAPI,Spring Boot,MySQL,Redis,LLM,AI Agent,RAG,后端,开发者工具"

    # 规模
    candidate_pool: int = 100
    top_n_llm: int = 30
    sched_hour: int = 8

    # 数据库
    db_url: str = "sqlite:///./celestial.db"

    # 内置 Agent SDK（vendored cc-mini，in-process）
    skill_run_timeout: int = 3600  # 单次 agent/技能执行超时（秒）
    # PlatformAPI 工具访问的本服务地址（云端部署时改成对外域名）
    platform_api_base: str = "http://127.0.0.1:8100"

    # 课程发布：本地磁盘落盘（Linux 服务器建议指向 nginx 托管目录；
    # base_url 留空时由本服务静态托管在 /published，见 main.py）
    local_publish_dir: str = "./published"  # 发布根目录：相对项目根或绝对路径
    local_publish_base_url: str = ""  # 对外访问前缀；空 = {platform_api_base}/published

    @property
    def llm_configured(self) -> bool:
        return bool(self.llm_base_url and self.llm_api_key)

    @property
    def search_configured(self) -> bool:
        return bool(self.search_provider and self.search_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
