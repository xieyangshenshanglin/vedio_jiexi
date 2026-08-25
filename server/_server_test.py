# -*- coding: utf-8 -*-
"""服务端接口自测（不依赖外网，验证路由与 cloud_only/识别逻辑）。"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi.testclient import TestClient
from app import app

c = TestClient(app)
fails = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + ((" | " + str(detail)[:160]) if detail else ""))
    if not cond:
        fails.append(name)


r = c.get("/health")
check("GET /health", r.status_code == 200 and r.json().get("ok") is True, r.json())

r = c.get("/config/version.json")
j = r.json()
check("GET /config/version.json", r.status_code == 200 and j.get("ok") is True and isinstance(j.get("supportedPlatforms"), list), j)

r = c.get("/")
j = r.json()
check("GET / platform list", set(j.get("supportedPlatforms") or []) >= {"抖音", "快手", "小红书"}, j)

# 云平台占位
r = c.post("/parse", json={"url": "https://www.doubao.com/note/123"})
check("POST doubao -> cloud_only", r.json().get("code") == "cloud_only", r.json())

r = c.post("/parse", json={"url": "https://channels.weixin.qq.com/v/x"})
check("POST 视频号 -> cloud_only", r.json().get("code") == "cloud_only", r.json())

# 未知平台
r = c.post("/parse", json={"url": "https://foo.example.com/bar"})
check("POST unknown -> unsupported_platform", r.json().get("code") == "unsupported_platform", r.json())

# 空链接
r = c.post("/parse", json={"url": ""})
check("POST empty -> bad_request", r.json().get("code") == "bad_request", r.json())

# 显式平台参数
r = c.post("/parse", json={"url": "https://v.douyin.com/abc/", "platform": "抖音"})
j = r.json()
check("POST explicit douyin -> not cloud_only (parse attempted)", j.get("code") != "cloud_only", j)

print("")
print("FAILED %d" % len(fails) if fails else "ALL SERVER CHECKS PASSED")
sys.exit(1 if fails else 0)
