# 水印鸭 · 自建解析服务

把 `../standalone/parsers.py`（9 个本地可解平台）包装成 HTTP 服务，部署到你自己的 Linux 服务器。
视频号 / 豆包为 `cloud_only` 占位，后续作为「job」接入（见文末）。

## 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/` | 服务信息（版本 / 支持平台） |
| GET | `/health` | 健康检查 |
| GET | `/config` 或 `/config/version.json` | 更新配置（你自己 version.json 的雏形） |
| POST | `/parse` | 提交链接，返回解析结果 JSON |

`/parse` 请求体：

```json
{ "url": "https://v.douyin.com/xxxx/", "platform": "" }
```

`platform` 可留空（自动识别）。成功返回媒体结果；失败统一返回 `{"ok": false, "error": "...", "code": "..."}`。

## 部署（二选一）

### 方式 A：Docker（推荐，你已装 Docker）

把 `standalone/` 和 `server/` 两个目录上传到服务器同一个父目录下（例如 `/opt/shuiyinya/`），结构：

```
/opt/shuiyinya/
  standalone/parsers.py
  server/app.py  Dockerfile  docker-compose.yml  requirements.txt
```

然后：

```bash
cd /opt/shuiyinya/server
docker compose up -d --build
```

（`docker-compose.yml` 里 `context: ..` 会自动把父目录作为构建上下文，从而 COPY 到 `standalone/parsers.py`。）

验证：

```bash
curl http://localhost:8000/health
curl -X POST http://localhost:8000/parse -H 'Content-Type: application/json' -d '{"url":"https://v.douyin.com/xxxx/"}'
```

### 方式 B：宝塔「Python 项目」管理器（不用 Docker）

1. 宝塔 → 软件商店 → 安装「Python 项目管理器」。
2. 新建项目，Python 版本选 3.12，框架选 FastAPI，启动方式 uvicorn，启动命令：
   `uvicorn app:app --host 0.0.0.0 --port 8000`
3. 项目根目录填 `server/` 所在位置；把 `standalone/` 放在 `server/` 的上一级（保证 `app.py` 里 `../standalone/parsers.py` 能解析到）。
4. 在宝塔「网站」里建一个站点，反向代理到 `127.0.0.1:8000`，即可用域名 + HTTPS 访问。

> 注意：服务端的 `app.py` 通过相对路径 `../standalone/parsers.py` 找解析核心。两种方式都要保持 `standalone/` 与 `server/` 的相对位置不变。

## 下一步：视频号 / 豆包 job

当前 `/parse` 对这两个平台返回 `{"ok": false, "code": "cloud_only"}`。后续接入方式：

- **视频号**：需要一个保持微信登录态的抓取器（Playwright 无头浏览器 + 扫码登录 + 保活 + 定期重登），实现成一个独立的 `job`，`/parse` 命中视频号时转给它。
- **豆包**：需要摸清当前公开接口 + 服务端去水印流水线（ffmpeg 裁水印/重编码），实现成异步任务（提交 → 轮询 → 结果）。

两者都建议先单独验证通过，再挂到 `/parse` 的路由里。
