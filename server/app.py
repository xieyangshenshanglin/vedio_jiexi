# -*- coding: utf-8 -*-
"""
水印鸭 · 自建解析服务（FastAPI）

接口：
    GET  /                   服务信息
    GET  /health             健康检查
    GET  /config             更新配置（你自己 version.json 的雏形）
    GET  /config/version.json  同上（与原版 updateConfigUrl 路径对齐）
    POST /parse              提交链接，返回解析结果 JSON

依赖本地解析核心 ../standalone/parsers.py。视频号/豆包为 cloud_only 占位，待后续实现。
"""

import os
import sys

# 让 app.py 能 import 到 ../standalone/parsers.py（本地目录结构 & Docker 内 /app/standalone 都适用）
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "standalone"))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from parsers import (
    ParseError,
    parse,
    extract_url,
    detect_platform,
    SUPPORTED_PLATFORMS,
    CLOUD_ONLY_PLATFORMS,
)

SERVICE_VERSION = "1.0.0"

app = FastAPI(title="水印鸭自建解析服务", version=SERVICE_VERSION)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ParseRequest(BaseModel):
    url: str
    platform: str = ""  # 可留空，自动识别


@app.get("/")
def root():
    return {
        "ok": True,
        "service": "水印鸭自建解析服务",
        "version": SERVICE_VERSION,
        "supportedPlatforms": SUPPORTED_PLATFORMS,
        "cloudOnlyPlatforms": CLOUD_ONLY_PLATFORMS,
    }


@app.get("/health")
def health():
    return {"ok": True, "version": SERVICE_VERSION}


def _config_payload():
    # 这是你自己「更新配置」的种子：将来 App 启动时拉这里做热更新（版本 / 平台开关 / 解析端点）。
    return {
        "ok": True,
        "versionName": SERVICE_VERSION,
        "versionCode": 1,
        "supportedPlatforms": SUPPORTED_PLATFORMS,
        "cloudOnlyPlatforms": CLOUD_ONLY_PLATFORMS,
        "parseEndpoint": "/parse",
        "update": {"decision": "NO_UPDATE", "latestVersionName": SERVICE_VERSION},
    }


@app.get("/config")
@app.get("/config/version.json")
def config():
    return _config_payload()


@app.post("/parse")
def parse_endpoint(req: ParseRequest):
    url = extract_url(req.url) or (req.url or "").strip()
    if not url:
        return {"ok": False, "error": "缺少链接", "code": "bad_request"}

    platform = (req.platform or "").strip() or detect_platform(url)
    if not platform:
        return {"ok": False, "error": "无法识别平台", "code": "unsupported_platform"}

    if platform in CLOUD_ONLY_PLATFORMS:
        return {
            "ok": False,
            "error": "%s 暂不支持（需服务端登录态 / 处理任务，待实现）" % platform,
            "code": "cloud_only",
            "platform": platform,
        }

    if platform not in SUPPORTED_PLATFORMS:
        return {"ok": False, "error": "平台 %s 暂无解析器" % platform, "code": "unsupported_platform", "platform": platform}

    try:
        return parse(platform, url, {"xhsSourceTranscode": True})
    except ParseError as exc:
        return {"ok": False, "error": str(exc), "code": exc.code or "", "platform": platform}
    except Exception as exc:
        return {"ok": False, "error": "解析失败: %s" % exc, "code": "internal", "platform": platform}
