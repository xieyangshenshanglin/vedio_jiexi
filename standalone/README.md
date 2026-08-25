# 水印鸭 · 独立本地解析器（Python）

从 `../assets/platform-parsers.js` 移植的**本地**多平台媒体解析器。**不依赖任何第三方服务器**——
解析请求直接从你这台机器发到内容平台（抖音/快手/小红书…），不经过 `analytics.milodev.cn`，
不用 version.json、云端接口、签名规则。

## 支持平台

| 平台 | 说明 |
|---|---|
| 抖音 | 视频 / 图集 / Live 图 |
| 快手 | 视频 / 图集 / Live 图 |
| 小红书 | 视频 / 图集（优先无水印原图） |
| 微博 | 视频 / 图集 / Live 图 |
| 皮皮虾 | 视频 / 图集 |
| 最右 | 视频 |
| X (Twitter) | 视频 / GIF / 图集（走公开 syndication 接口） |
| 小米社区 | 视频 / 图片 |
| 公众号 | 图片 / Live 图 / 视频 |

**不支持**：视频号、豆包等 —— 这些在原版里走云端去水印服务（需要服务器 + 账号登录态），本地无法复刻。

## 环境要求

- Python 3.8+（已在 3.12 验证）
- `requests` 库（已装 2.34.2；如缺失：`pip install requests`）

## 用法

```powershell
# 只解析，打印媒体地址
python parse.py "https://v.douyin.com/xxxx/"

# 也支持粘贴整段分享文本（自动提取里面的链接）
python parse.py "7.99 复制打开抖音…… https://v.douyin.com/xxxx/"

# 输出原始 JSON
python parse.py "链接" --json

# 解析并下载到 ./downloads
python parse.py "链接" --download
```

## 示例输出

```
识别平台 : 抖音
解析中   : https://v.douyin.com/xxxx/

平台     : 抖音
类型     : video
标题     : xxx
作者     : xxx
视频地址 : https://...mp4
封面     : https://...jpeg
```

## 已知限制

1. **反爬**：本地用普通 HTTP 客户端（带浏览器 UA + Referer），不如原版 App 原生层那样做反爬/签名。
   少数平台在数据中心 IP 或高频请求下可能被拦，返回登录页/验证页，此时解析会报「未返回作品数据」。
   可考虑在 `parsers.py` 顶部把 `DEFAULT_UA` 换成真实移动端 UA，或自行接入代理。
2. **Live 图 / 无水印原图**：移植保留了原版的「可信原图」判定逻辑，尽量取无水印源；但平台改版后字段可能变化。
3. **下载**：媒体地址需带正确 Referer 下载（`--download` 已处理）；个别 CDN 的链接有较短有效期，解析后尽快保存。

## 与后续「封装 App / 更新」的关系

- 这份 `parsers.py` 就是核心解析逻辑。将来封装 Android App 时：
  - 方案 A（WebView 壳）：把 `platform-parsers.js`（原版 JS）放进 APK 即可，逻辑等价。
  - 方案 B（自建后端）：把 `parsers.py` 包一层 HTTP 接口跑在你服务器上，App 只提交链接。
- 「更新」最省事的方式：把解析逻辑放在你自己的仓库，坏了就改仓库（热更新），不必重发 APK。
