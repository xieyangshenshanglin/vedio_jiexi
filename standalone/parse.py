# -*- coding: utf-8 -*-
"""
水印鸭 · 独立本地解析器 —— 命令行入口

用法：
    python parse.py "分享链接或整段分享文本"
    python parse.py <链接> --json          # 输出原始 JSON
    python parse.py <链接> --download      # 解析后下载到 ./downloads

只支持「本地可解」平台：抖音 / 快手 / 小红书 / 皮皮虾 / 最右 / 微博 / X / 小米社区 / 公众号。
不依赖任何第三方服务器。依赖：requests。
"""

import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from parsers import ParseError, parse, extract_url, detect_platform

DEFAULT_UA = (
    "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"
)


def media_ext(url):
    u = str(url or "")
    if re.search(r"imageView2/format/jpg", u, re.I):
        return ".jpg"
    path = re.sub(r"[?#].*$", "", u)
    m = re.search(r"\.(mp4|m4v|mov|webm|jpg|jpeg|png|webp|gif|avif)(?:$|/)", path, re.I)
    if m:
        return "." + m.group(1).lower()
    if re.search(r"\.mp4(?:[?#]|$)|douyinvod|video\.twimg|playwm|sns-video", u, re.I):
        return ".mp4"
    if re.search(r"xhscdn|sinaimg|twimg|qpic", u, re.I):
        return ".jpg"
    return ".bin"


def safe_name(title, maxlen=60):
    name = re.sub(r'[\\/:*?"<>|\r\n\t]+', "_", str(title or ""))
    name = name.strip().strip(".").strip() or "media"
    return name[:maxlen]


def download_one(url, headers, file_path):
    import requests

    h = dict(headers or {})
    h.setdefault("User-Agent", DEFAULT_UA)
    try:
        resp = requests.get(url, headers=h, timeout=60, stream=True)
        resp.raise_for_status()
        with open(file_path, "wb") as f:
            for chunk in resp.iter_content(65536):
                f.write(chunk)
        size = os.path.getsize(file_path)
        print("  已保存 %s (%d bytes)" % (file_path, size))
        return True
    except Exception as exc:
        print("  下载失败 %s：%s" % (url[:100], exc))
        return False


def download_result(r):
    out_dir = os.path.join(os.getcwd(), "downloads")
    os.makedirs(out_dir, exist_ok=True)
    base = safe_name(r.get("title") or "media")
    headers = r.get("requestHeaders") or {}
    if r.get("mediaType") == "video" or r.get("videoUrl"):
        u = r.get("videoUrl") or r.get("mediaUrl")
        if u:
            download_one(u, headers, os.path.join(out_dir, base + media_ext(u)))
    items = r.get("items") or []
    for i, it in enumerate(items):
        if it.get("url"):
            download_one(it["url"], it.get("requestHeaders") or headers,
                         os.path.join(out_dir, "%s_%d%s" % (base, i + 1, media_ext(it["url"]))))
        if it.get("livePhotoUrl"):
            download_one(it["livePhotoUrl"], it.get("requestHeaders") or headers,
                         os.path.join(out_dir, "%s_%d_live%s" % (base, i + 1, media_ext(it["livePhotoUrl"]))))


def print_result(r):
    print("")
    print("平台     : %s" % r.get("platform"))
    print("类型     : %s" % r.get("mediaType"))
    print("标题     : %s" % r.get("title"))
    if r.get("authorName"):
        print("作者     : %s" % r.get("authorName"))
    if r.get("videoUrl"):
        print("视频地址 : %s" % r.get("videoUrl"))
    if r.get("cover"):
        print("封面     : %s" % r.get("cover"))
    items = r.get("items") or []
    for i, it in enumerate(items):
        print("  第 %d 张: %s" % (i + 1, it.get("url")))
        if it.get("livePhotoUrl"):
            print("         Live: %s" % it.get("livePhotoUrl"))
    print("")


def usage():
    print("用法：python parse.py \"<分享链接或整段分享文本>\" [--json] [--download]")


def main():
    args = [a for a in sys.argv[1:]]
    raw_input = " ".join(a for a in args if not a.startswith("--"))
    want_json = "--json" in args
    want_download = "--download" in args or "-d" in args

    if not raw_input.strip():
        usage()
        return

    url = extract_url(raw_input) or raw_input.strip()
    platform = detect_platform(url)
    if not platform:
        print("无法识别平台。请确认链接来自：抖音 / 快手 / 小红书 / 皮皮虾 / 最右 / 微博 / X / 小米社区 / 公众号。")
        return

    print("识别平台 : %s" % platform)
    print("解析中   : %s" % url)
    try:
        result = parse(platform, url, {"xhsSourceTranscode": True})
    except ParseError as exc:
        print("解析失败 : %s" % exc)
        return
    except Exception as exc:  # 网络等兜底
        print("解析失败 : %s" % exc)
        return

    if want_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print_result(result)

    if want_download:
        download_result(result)


if __name__ == "__main__":
    main()
