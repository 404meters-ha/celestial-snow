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

    # 卡奥斯 OSS（对应 Java 侧 com.cosmoplat.hyida:hyida-starter-obs）
    # 该 starter 底层就是 aws-java-sdk-s3 + path-style + us-east-1，Python 侧等价实现用 boto3。
    hyida_obs_enabled: bool = False
    hyida_obs_access_key: str = ""
    hyida_obs_secret_key: str = ""
    hyida_obs_endpoint: str = "https://hd-oss.cosmoplat.com"
    hyida_obs_bucket: str = "courses"  # 桶名（S3 API 用裸名；Java 侧由调用方传入）
    hyida_obs_url_prefix: str = "hdCosmo100"  # 对应 Java 侧 urlPrefix：租户前缀，公网 URL 需要它
    # 公网直读地址是否写成 {endpoint}/{urlPrefix}:{bucket}/{key}。实测：带前缀 200，裸桶名 404
    hyida_obs_url_account_qualified: bool = True
    hyida_obs_key_prefix: str = ""  # 对象 key 一级目录：{key_prefix}/...，专用桶留空即可
    hyida_obs_region: str = "us-east-1"  # Java 侧硬编码 us-east-1
    hyida_obs_check_max_size: bool = False  # 对应 isCheckMaxSize（Java 侧非空即跳过校验）
    hyida_obs_max_size_mb: int = 20  # check_max_size 开启时的单文件上限

    @property
    def llm_configured(self) -> bool:
        return bool(self.llm_base_url and self.llm_api_key)

    @property
    def search_configured(self) -> bool:
        return bool(self.search_provider and self.search_api_key)

    @property
    def obs_configured(self) -> bool:
        return bool(
            self.hyida_obs_enabled
            and self.hyida_obs_access_key
            and self.hyida_obs_secret_key
            and self.hyida_obs_endpoint
            and self.hyida_obs_bucket
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
