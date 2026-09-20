"""卡奥斯 OSS 上传：Java 侧 com.cosmoplat.hyida:hyida-starter-obs 的 Python 等价实现。

该 starter 底层就是 aws-java-sdk-s3（见其 pom），所以这里用 boto3 对齐它 ObsServiceImpl#init 的每一项设定：

    EndpointConfiguration(endPoint, "us-east-1")   → endpoint_url + region_name="us-east-1"
    BasicAWSCredentials(accessKey, secretKey)      → aws_access_key_id / aws_secret_access_key
    disableChunkedEncoding()                       → 用 bytes/MultipartFile 方式 put，不用流式分块
    withPathStyleAccessEnabled(true)               → s3={"addressing_style": "path"}

另有两条只能实测得到、读代码看不出来的（本项目已实测确认）：

1. 配置里的 urlPrefix（hdCosmo100）是**租户前缀，不是桶名**。S3 API 用裸桶名，公网直读地址必须带租户前缀：
   `https://hd-oss.cosmoplat.com/hdCosmo100:courses/<key>` → 200；`.../courses/<key>` → 404 NoSuchBucket。
   Java 代码里对 `url.replace(urlPrefix + ":" + bucketName, bucketName)` 的处理就是为这件事，但反向替换后
   的裸桶名地址公网打不开，故此处默认按带前缀形式生成 URL。
2. botocore ≥ 1.36 默认给 put_object 加 CRC32 校验和头，本网关不认，必须用
   request_checksum_calculation="when_required" 关掉（等价于 Java 侧的 disableChunkedEncoding）。
"""
from __future__ import annotations

import mimetypes
import threading
from urllib.parse import quote

from ..config import get_settings

# 显式指定，避免 Windows 注册表把 .js/.md 映射成奇怪类型；带 charset 保证浏览器按 UTF-8 渲染
_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".htm": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    # 用 text/plain 而非 text/markdown：课程页面里有 RESOURCES.md / reference/*.md 的链接，
    # 浏览器对 text/markdown 常常直接下载，text/plain 才会在标签页里直接显示出来
    ".md": "text/plain; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".pdf": "application/pdf",
}

_client_lock = threading.Lock()
_client = None


class OSSNotConfigured(RuntimeError):
    """.env 里没配齐卡奥斯 OSS 凭据。"""


def content_type_for(path: str) -> str:
    """按后缀给 Content-Type。OSS 上 Content-Type 错了浏览器会直接下载而不是渲染。"""
    lower = path.lower()
    for ext, ctype in _CONTENT_TYPES.items():
        if lower.endswith(ext):
            return ctype
    guessed, _ = mimetypes.guess_type(path)
    return guessed or "application/octet-stream"


def is_enabled() -> bool:
    return get_settings().obs_configured


def _build_client():
    """按 Java 侧 init() 的等价设定构造 boto3 客户端（懒加载 + 复用）。"""
    global _client
    s = get_settings()
    if not s.obs_configured:
        raise OSSNotConfigured(
            "卡奥斯 OSS 未配置：请在 .env 填 HYIDA_OBS_ACCESS_KEY / HYIDA_OBS_SECRET_KEY "
            "（并确认 HYIDA_OBS_ENDPOINT / HYIDA_OBS_BUCKET / HYIDA_OBS_ENABLED=1）"
        )
    with _client_lock:
        if _client is None:
            import boto3
            from botocore.config import Config

            cfg = Config(
                s3={"addressing_style": "path"},  # withPathStyleAccessEnabled(true)
                signature_version="s3v4",
                # 关掉 botocore 默认的 CRC32 校验和 / 分块，否则本网关拒收
                request_checksum_calculation="when_required",
                response_checksum_validation="when_required",
                retries={"max_attempts": 3, "mode": "standard"},
                connect_timeout=10,
                read_timeout=60,
            )
            _client = boto3.client(
                "s3",
                endpoint_url=s.hyida_obs_endpoint,
                aws_access_key_id=s.hyida_obs_access_key,
                aws_secret_access_key=s.hyida_obs_secret_key,
                region_name=s.hyida_obs_region,
                config=cfg,
            )
        return _client


def reset_client() -> None:
    """测试或改配置后丢弃缓存的客户端。"""
    global _client
    with _client_lock:
        _client = None


def public_url(key: str) -> str:
    """对象的公网直读地址（桶为公共读，可直接分享）。

    带租户前缀的 {endpoint}/{urlPrefix}:{bucket}/{key} 才是公网可达形式（已实测）。
    """
    s = get_settings()
    base = s.hyida_obs_endpoint.rstrip("/")
    path = quote(key, safe="/")  # 中文文件名按 UTF-8 百分号编码，斜杠保留做层级
    if s.hyida_obs_url_account_qualified and s.hyida_obs_url_prefix:
        return f"{base}/{s.hyida_obs_url_prefix}:{s.hyida_obs_bucket}/{path}"
    return f"{base}/{s.hyida_obs_bucket}/{path}"


def put_bytes(key: str, data: bytes, content_type: str | None = None) -> str:
    """上传一段字节到 OSS，返回公网 URL。对应 Java 侧 putObject(bucket, key, stream, metadata)。"""
    s = get_settings()
    client = _build_client()
    client.put_object(
        Bucket=s.hyida_obs_bucket,
        Key=key,
        Body=data,  # bytes body：不做流式分块，等价 disableChunkedEncoding
        ContentType=content_type or content_type_for(key),
        ContentLength=len(data),
    )
    return public_url(key)


def delete_key(key: str) -> None:
    """删除单个对象（重发课程时清掉上一版多余文件）。"""
    s = get_settings()
    _build_client().delete_object(Bucket=s.hyida_obs_bucket, Key=key)


def list_prefix(prefix: str = "", limit: int = 1000) -> list[str]:
    """列出某前缀下的所有 key（不含「目录」占位对象）。"""
    s = get_settings()
    client = _build_client()
    keys: list[str] = []
    token = None
    while True:
        kwargs = {"Bucket": s.hyida_obs_bucket, "Prefix": prefix, "MaxKeys": 1000}
        if token:
            kwargs["ContinuationToken"] = token
        resp = client.list_objects_v2(**kwargs)
        for obj in resp.get("Contents", []):
            key = obj["Key"]
            if not key.endswith("/"):  # 跳过目录占位
                keys.append(key)
        if len(keys) >= limit or not resp.get("IsTruncated"):
            break
        token = resp.get("NextContinuationToken")
    return keys[:limit]
