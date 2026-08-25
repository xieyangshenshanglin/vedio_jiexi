# -*- coding: utf-8 -*-
"""
水印鸭 · 独立本地解析器 —— 平台解析逻辑（从 assets/platform-parsers.js 移植）。

只做「本地可解」的平台：抖音 / 快手 / 小红书 / 皮皮虾 / 最右 / 微博 / X / 小米社区 / 公众号。
不依赖任何第三方服务器（不连 analytics.milodev.cn，不用 version.json / 云端接口 / 签名规则）。

依赖：requests（你机器上已装 2.34.2）。
"""

import json
import math
import re
import urllib.parse

import requests

DEFAULT_UA = (
    "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"
)

_SESSION = requests.Session()
_SESSION.headers.update({"User-Agent": DEFAULT_UA})


class ParseError(Exception):
    def __init__(self, message, code=""):
        super().__init__(message)
        self.code = code
        self.diagnostic = ""


# ---------------------------------------------------------------------------
# 通用工具
# ---------------------------------------------------------------------------

def normalize_known_share_url(url):
    url = (url or "").strip()
    hosts = [
        r"^http://(?:www\.)?xhslink\.(?:com|cn)/",
        r"^http://(?:v\.)?kuaishou\.com/",
        r"^http://(?:[\w-]+\.)?gifshow\.com/",
        r"^http://h5\.pipix\.com/",
        r"^http://(?:(?:h5\.)?video\.weibo\.com|(?:m\.)?weibo\.cn|(?:www\.)?weibo\.com)/",
        r"^http://(?:(?:www|mobile)\.)?(?:x|twitter)\.com/",
        r"^http://t\.co/",
        r"^http://(?:s\.xiaomi\.cn|(?:[\w-]+\.)?xiaomi\.cn|(?:[\w-]+\.)?miui\.com)/",
        r"^http://mp\.weixin\.qq\.com/",
    ]
    for pat in hosts:
        if re.match(pat, url, re.I):
            return re.sub(r"^http:", "https:", url, count=1, flags=re.I)
    return url


def _request(url, method="GET", headers=None, body=None, referer=None, timeout=30):
    headers = dict(headers or {})
    headers.setdefault("User-Agent", DEFAULT_UA)
    if referer and "Referer" not in headers:
        headers["Referer"] = referer
    method = method.upper()
    kwargs = dict(headers=headers, timeout=timeout, allow_redirects=True)
    if body is not None:
        kwargs["data"] = body
    return _SESSION.request(method, url, **kwargs)


def fetch_text(url, options=None):
    options = options or {}
    url = normalize_known_share_url(url)
    headers = dict(options.get("headers") or {})
    referer = options.get("referer") or (
        "https://www.xiaohongshu.com/"
        if re.search(r"xiaohongshu\.com|xhslink\.(?:com|cn)", url)
        else url
    )
    method = (options.get("method") or "GET").upper()
    body = options.get("body") or None
    last_err = None
    for _ in range(2):
        try:
            resp = _request(url, method, headers, body, referer)
        except requests.RequestException as exc:
            last_err = exc
            continue
        text = resp.text
        if resp.status_code >= 400:
            raise ParseError("HTTP %d%s" % (resp.status_code, (" · " + text[:120]) if text else ""))
        return {"url": resp.url, "text": text, "headers": resp.headers}
    raise ParseError("请求失败: %s" % (last_err,))


def fetch_json(url, options=None):
    options = dict(options or {})
    headers = dict(options.get("headers") or {})
    headers.setdefault("Accept", "application/json,text/plain,*/*")
    options["headers"] = headers
    resp = fetch_text(url, options)
    try:
        return {"url": resp["url"], "data": json.loads(resp["text"])}
    except json.JSONDecodeError:
        raise ParseError("接口没有返回有效 JSON")


def fetch_web_json(url, options=None):
    # 与 fetch_json 一致；cookies 已由 Session 维护（对应 JS 里的 credentials: include）。
    return fetch_json(url, options)


def get_path(root, path):
    parts = list(path) if isinstance(path, (list, tuple)) else str(path or "").split(".")
    cur = root
    for p in parts:
        if cur is None:
            return None
        if isinstance(cur, list):
            try:
                cur = cur[int(p)]
            except (ValueError, IndexError):
                return None
        elif isinstance(cur, dict):
            cur = cur.get(p)
        else:
            return None
    return cur


def walk(root, visitor, path=None, seen=None):
    if path is None:
        path = []
    if seen is None:
        seen = set()
    if root is None:
        return
    if isinstance(root, (dict, list)):
        if id(root) in seen:
            return
        seen.add(id(root))
        if isinstance(root, list):
            for i, v in enumerate(root):
                walk(v, visitor, path + [str(i)], seen)
        else:
            for k, v in root.items():
                walk(v, visitor, path + [str(k)], seen)
        return
    visitor(root, path)


def unique(values):
    out, seen = [], set()
    for v in values:
        s = str(v or "").replace("\\u002F", "/").replace("\\/", "/").replace("&amp;", "&")
        if not re.match(r"^https?://", s, re.I) or s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


def collect_urls(root, kind):
    urls = []

    def visitor(value, path):
        key = ".".join(path).lower()
        lower = value.lower()
        if not lower.startswith(("http://", "https://")):
            return
        if kind == "video":
            if re.search(r"\.(mp4|m4v|mov|webm)(\?|$)", lower) or re.search(
                r"video|play|master|stream|manifest|srcurl|photo_url|url_list", key
            ):
                urls.append(value)
        elif kind == "image":
            if re.search(r"\.(jpg|jpeg|png|webp|avif)(\?|$)", lower) or re.search(
                r"image|cover|poster|avatar|photo", key
            ):
                urls.append(value)

    walk(root, visitor)
    return unique(urls)


def first_url(value):
    if isinstance(value, str):
        return re.sub(r"^http:", "https:", value) if re.match(r"^https?://", value, re.I) else ""
    if isinstance(value, list):
        for v in value:
            u = first_url(v)
            if u:
                return u
        return ""
    if isinstance(value, dict):
        for key in ["masterUrl", "masterUrls", "backupUrls", "url", "urlList", "baseUrl", "src", "playUrl", "downloadUrl"]:
            if key in value:
                u = first_url(value[key])
                if u:
                    return u
        for v in value.values():
            u = first_url(v)
            if u:
                return u
    return ""


def first_non_empty(*args):
    for v in args:
        if v is not None and str(v).strip():
            return str(v).strip()
    return ""


def find_string_by_key(root, names):
    wanted = [str(n).lower() for n in names]
    found = [""]

    def visit(value):
        if found[0] or not isinstance(value, (dict, list)):
            return
        if isinstance(value, list):
            for item in value:
                if found[0]:
                    return
                visit(item)
            return
        for k, v in value.items():
            if str(k).lower() in wanted and isinstance(v, str) and v.strip():
                found[0] = v.strip()
                return
        for v in value.values():
            if found[0]:
                return
            visit(v)

    visit(root)
    return found[0]


def first_text(root, keys, fallback=""):
    wanted = [k.lower() for k in keys]
    found = [""]

    def visitor(value, path):
        if found[0] or not isinstance(value, str):
            return
        key = (path[-1] if path else "").lower()
        if key in wanted and 0 < len(value.strip()) < 500:
            found[0] = value.strip()

    walk(root, visitor)
    return found[0] or (fallback or "")


def pick_video(urls):
    if not urls:
        return ""
    preferred = [
        u for u in urls
        if re.search(r"\.(mp4|m4v|mov|webm)(\?|$)", u.lower())
        or re.search(r"video|playurl|play_url|srcurl", u.lower())
    ]
    chosen = (preferred[0] if preferred else urls[0]) or ""
    return re.sub(r"^http:", "https:", chosen)


def normalize_images(urls, limit=40):
    return [
        {"url": u, "livePhotoUrl": ""}
        for u in unique(urls)[: (limit or 40)]
        if not re.search(r"avatar|profile|logo|icon", u, re.I)
    ]


def find_object(root, predicate):
    found = [None]

    def visit(value):
        if found[0] is not None or not isinstance(value, (dict, list)):
            return
        if isinstance(value, dict):
            try:
                if predicate(value):
                    found[0] = value
                    return
            except Exception:
                pass
            for v in value.values():
                visit(v)
                if found[0] is not None:
                    return
        else:
            for item in value:
                visit(item)
                if found[0] is not None:
                    return

    visit(root)
    return found[0]


def extract_assigned_json(html, marker):
    idx = html.find(marker)
    if idx < 0:
        return None
    i = idx + len(marker)
    n = len(html)
    while i < n and html[i] in " \t\r\n=:":
        i += 1
    while i < n and html[i] not in "{[":
        i += 1
    if i >= n:
        return None
    opener = html[i]
    closer = "}" if opener == "{" else "]"
    depth = 0
    quote = ""
    esc = False
    j = i
    while j < n:
        ch = html[j]
        if quote:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == quote:
                quote = ""
            j += 1
            continue
        if ch in "\"'":
            quote = ch
            j += 1
            continue
        if ch == opener:
            depth += 1
        elif ch == closer:
            depth -= 1
            if depth == 0:
                raw = re.sub(r"\bundefined\b", "null", html[i:j + 1])
                try:
                    return json.loads(raw)
                except Exception:
                    return None
        j += 1
    return None


def decode_escaped_json_string(value):
    value = str(value or "")
    try:
        return json.loads('"' + value.replace('"', '\\"') + '"')
    except Exception:
        return (
            value.replace("\\u002F", "/")
            .replace("\\u0026", "&")
            .replace("\\/", "/")
            .replace("\\n", "\n")
            .replace('\\"', '"')
        )


def extract_initial_state(html):
    state = (
        extract_assigned_json(html, "window.__INITIAL_STATE__")
        or extract_assigned_json(html, "window.INIT_STATE")
        or extract_assigned_json(html, "__INITIAL_STATE__")
    )
    if state is not None:
        return state
    m = re.search(r"(?:window\.)?__INITIAL_STATE__\s*=\s*JSON\.parse\(\s*\"([\s\S]*?)\"\s*\)", html, re.I)
    if m:
        try:
            return json.loads(re.sub(r"\bundefined\b", "null", decode_escaped_json_string(m.group(1))))
        except Exception:
            pass
    m = re.search(
        r"<script[^>]+(?:id|data-name)=[\"'](?:__INITIAL_STATE__|initial-state)[\"'][^>]*>([\s\S]*?)</script>",
        html, re.I,
    )
    if m:
        try:
            return json.loads(m.group(1).strip().replace("&quot;", '"').replace("&quot;", '"'))
        except Exception:
            pass
    return None


def unescape_page_value(value):
    return (
        str(value or "")
        .replace("\\u002F", "/")
        .replace("\\u0026", "&")
        .replace("\\u003D", "=")
        .replace("\\/", "/")
        .replace("&amp;", "&")
    )


def decode_html_json_text(value):
    value = str(value or "").strip().replace("&quot;", '"').replace("&amp;", "&")
    if re.match(r"^%7B|^%5B", value, re.I):
        try:
            value = urllib.parse.unquote(value)
        except Exception:
            pass
    return value.replace("\\u002F", "/").replace("\\/", "/")


def decoded_url_lower(value):
    lower = str(value or "").lower()
    for _ in range(2):
        try:
            decoded = urllib.parse.unquote(lower)
        except Exception:
            break
        if decoded == lower:
            break
        lower = decoded
    return lower


def strip_html(value):
    text = str(value or "")
    text = re.sub(r"<script[\s\S]*?</script>", "", text, flags=re.I)
    text = re.sub(r"<style[\s\S]*?</style>", "", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = (
        text.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
    )
    return text.strip()


def extract_digits(text, patterns):
    for p in patterns:
        m = re.search(p, str(text or ""))
        if m:
            return m.group(1)
    return ""


def result(platform, type_, source_url, title, video_url, cover, items,
           author_name="", author_avatar="", diagnostic="", request_headers=None,
           media_candidates=None, music_url="", extras=None):
    out = {
        "ok": True,
        "platform": platform,
        "mediaType": type_,
        "sourceUrl": source_url,
        "title": title or (platform + "内容"),
        "mediaUrl": video_url or "",
        "videoUrl": video_url or "",
        "cover": cover or "",
        "items": items or [],
        "authorName": author_name or "",
        "authorAvatar": author_avatar or "",
        "diagnostic": diagnostic or "",
        "requestHeaders": request_headers or {},
        "mediaCandidates": media_candidates or [],
        "musicUrl": music_url or "",
    }
    if extras and isinstance(extras, dict):
        out.update(extras)
    return out


# ---------------------------------------------------------------------------
# 抖音
# ---------------------------------------------------------------------------

def douyin_aweme_id(value):
    text = str(value or "")
    patterns = [
        r"/(?:video|note|slides)/(\d{8,})(?:[/?#\s]|$)",
        r"/share/(?:video|note|slides)/(\d{8,})(?:[/?#\s]|$)",
        r"[?&](?:aweme_id|item_id|modal_id)=(\d{8,})",
        r'"aweme_id"\s*:\s*"?(\d{8,})',
    ]
    for p in patterns:
        m = re.search(p, text, re.I)
        if m:
            return m.group(1)
    return ""


def is_douyin_motion_video_url(value):
    lower = decoded_url_lower(value)
    if re.search(r"\.mp3(?:[?#&/]|$)|music|audio", lower):
        return False
    if re.search(r"video_id=https?://[^?#&]+\.mp3", lower):
        return False
    if re.search(r"//(?:m\.|www\.)?douyin\.com/share/video/", lower):
        return False
    if not lower:
        return False
    return bool(
        re.search(r"\.mp4(?:\?|$)", lower)
        or re.search(r"douyinvod|tos-cn-v|/play(?:wm)?/|/video/tos/", lower)
    )


def normalize_douyin_motion_url(url):
    url = str(url or "").replace("http://", "https://", 1).replace("/playwm/", "/play/")
    if "v26-web" in url:
        url = re.sub(r"://([^/]+)", "://v26-luna.douyinvod.com", url, count=1)
    return url


def pick_douyin_motion_candidate(value):
    urls = [u for u in collect_urls(value, "video") if is_douyin_motion_video_url(u)]
    if not urls:
        return ""
    for pref in ("v3-web", "v26-web"):
        hit = next((u for u in urls if pref in u), None)
        if hit:
            return normalize_douyin_motion_url(hit)
    return normalize_douyin_motion_url(urls[1] if len(urls) > 1 else urls[0])


def douyin_original_image_url(image):
    image = image or {}
    url = first_url(
        image.get("origin_image") or image.get("originImage")
        or image.get("url_list") or image.get("urlList")
        or image.get("display_image") or image.get("displayImage")
    )
    if not url:
        url = first_url(image.get("download_url_list") or image.get("downloadUrlList") or image)
    return re.sub(r"^http:", "https:", url) if url else ""


def douyin_motion_url(image):
    image = image or {}
    explicit_paths = [
        ["video", "play_addr", "url_list"],
        ["video", "playAddr"],
        ["video", "playApi"],
        ["video", "playAddr", "urlList"],
        ["video", "play_addr_h264", "url_list"],
        ["video", "play_addr_265", "url_list"],
        ["video", "play_addr_265", "urlList"],
        ["video", "download_addr", "url_list"],
        ["video", "bit_rate", "0", "play_addr", "url_list"],
        ["video", "bitRate", "0", "playAddr", "urlList"],
        ["live_photo", "video", "play_addr", "url_list"],
        ["live_photo", "video", "download_addr", "url_list"],
        ["livePhoto", "video", "playAddr", "urlList"],
        ["motion", "video", "play_addr", "url_list"],
        ["clip_video", "play_addr", "url_list"],
        ["dynamic_video", "play_addr", "url_list"],
    ]
    for path in explicit_paths:
        val = get_path(image, path)
        u = pick_douyin_motion_candidate(val) or first_url(val)
        if u and is_douyin_motion_video_url(u):
            return normalize_douyin_motion_url(u)
    roots = [
        image.get("live_photo"), image.get("livePhoto"),
        image.get("live_photo_info"), image.get("livePhotoInfo"),
        image.get("motion"), image.get("motion_info"), image.get("motionInfo"),
        image.get("clip_video"), image.get("clipVideo"),
        image.get("video"), image.get("video_info"), image.get("videoInfo"),
        image.get("dynamic_video"), image.get("dynamicVideo"),
    ]
    for root in roots:
        if not root:
            continue
        direct = first_url(root)
        if direct and is_douyin_motion_video_url(direct):
            return normalize_douyin_motion_url(direct)
        collected = [u for u in collect_urls(root, "video") if is_douyin_motion_video_url(u)]
        picked = pick_douyin_motion_candidate(root) or pick_video(collected)
        if picked and is_douyin_motion_video_url(picked):
            return normalize_douyin_motion_url(picked)
    all_urls = [
        u for u in collect_urls(image, "video")
        if is_douyin_motion_video_url(u) and not re.search(r"download_url_list|owner_watermark", u)
    ]
    picked = pick_video(all_urls)
    return normalize_douyin_motion_url(picked) if picked and is_douyin_motion_video_url(picked) else ""


def douyin_image_expects_live(image):
    if not isinstance(image, dict):
        return False
    clip = image.get("clipType", image.get("clip_type"))
    live = image.get("livePhotoType", image.get("live_photo_type"))
    try:
        clip = int(clip) if clip is not None else None
    except (TypeError, ValueError):
        clip = None
    try:
        live = int(live) if live is not None else None
    except (TypeError, ValueError):
        live = None
    return clip == 5 or live == 1 or isinstance(image.get("video"), dict)


def live_pairing_status(has_expected_live, item_count, motion_count, paired_count, expected_live_count):
    if motion_count > 0 and paired_count == item_count and item_count > 0:
        return "paired"
    if motion_count > 0:
        try:
            expected = float(expected_live_count)
            if math.isfinite(expected) and expected > 0 and paired_count >= expected:
                return "paired"
        except (TypeError, ValueError):
            pass
        return "partial"
    return "live_source_unavailable" if has_expected_live else "original_only"


def result_live_contract_extras(items, has_expected_live, selected_still_source=""):
    items = items if isinstance(items, list) else []
    item_count = len(items)
    motion_count = sum(1 for e in items if e and e.get("livePhotoUrl"))
    paired_count = sum(1 for e in items if e and e.get("url") and e.get("livePhotoUrl"))
    trusted_still_count = 0
    for e in items:
        if not e or not e.get("url"):
            continue
        kind = str(e.get("stillSourceKind") or e.get("selectedStillSource") or e.get("sourceKind") or "origin")
        if kind not in ("display", "rendered", "share"):
            trusted_still_count += 1
    expected_live_count = sum(
        1 for e in items
        if str(e.get("pairingStatus") or "") in ("paired", "live_source_unavailable")
    )
    pairing = live_pairing_status(has_expected_live, item_count, motion_count, paired_count, expected_live_count)
    if motion_count > 0 and trusted_still_count < item_count:
        pairing = "partial"
    return {
        "stillCount": item_count,
        "trustedStillCount": trusted_still_count,
        "motionCount": motion_count,
        "partial": pairing == "partial" or (motion_count > 0 and trusted_still_count < item_count),
        "pairingStatus": pairing,
        "liveStatus": pairing,
        "selectedStillSource": selected_still_source
        or (items[0].get("selectedStillSource") or items[0].get("stillSourceKind") or items[0].get("sourceKind") or "")
        if items
        else "",
    }


def collect_douyin_motion_candidates(root):
    candidates, seen = [], set()

    def visitor(value, path):
        if not isinstance(value, str) or not value.lower().startswith(("http://", "https://")):
            return
        key = ".".join(path).lower()
        lower = value.lower()
        if not re.search(r"(?:images?\.\d+\..*(?:video|play_addr)|live_photo|livephoto|motion|clip_video|dynamic_video)", key):
            return
        if re.search(r"cover|image|avatar|music|audio|download_url_list|owner_watermark", key) and not re.search(
            r"video|play_addr|motion|live", key
        ):
            return
        if not is_douyin_motion_video_url(lower):
            return
        normalized = value.replace("http://", "https://", 1).replace("/playwm/", "/play/")
        if normalized not in seen:
            seen.add(normalized)
            candidates.append(normalized)

    walk(root, visitor)
    return candidates


def collect_douyin_motion_urls_from_html(html):
    html = decode_html_json_text(html)
    results, seen = [], set()
    for m in re.finditer(r"https?://[^\"'\s<>\\]+", html):
        url = m.group(0).replace("&amp;", "&")
        lower = decoded_url_lower(url)
        if not is_douyin_motion_video_url(lower):
            continue
        if re.search(r"cover|avatar|music|audio", lower):
            continue
        url = url.replace("http://", "https://", 1).replace("/playwm/", "/play/")
        if url not in seen:
            seen.add(url)
            results.append(url)
    return results


def build_douyin_media_items(item, pages):
    item = item or {}
    images = item.get("images") if isinstance(item.get("images"), list) else []
    media_items, seen = [], set()
    image_owned_motion = []
    motion_candidates = collect_douyin_motion_candidates(item)
    page_motion_candidates = []
    for page in pages or []:
        for c in collect_douyin_motion_urls_from_html(page.get("text") or ""):
            if c not in page_motion_candidates:
                page_motion_candidates.append(c)
    for image in images[:60]:
        image_url = douyin_original_image_url(image)
        if not image_url or image_url in seen:
            continue
        seen.add(image_url)
        motion_url = douyin_motion_url(image) or ""
        if motion_url and not is_douyin_motion_video_url(motion_url):
            motion_url = ""
        if motion_url and motion_url not in image_owned_motion:
            image_owned_motion.append(motion_url)
        media_items.append({
            "url": image_url,
            "livePhotoUrl": motion_url,
            "stillSourceKind": "origin",
            "selectedStillSource": "origin",
            "sourceKind": "origin",
            "motionSourceKind": "image-owned" if motion_url else "",
            "pairingStatus": "paired"
            if motion_url
            else ("live_source_unavailable" if douyin_image_expects_live(image) else "original_only"),
        })
    unscoped = [c for c in (motion_candidates + page_motion_candidates)
                if c not in image_owned_motion]
    unscoped_unique = []
    for c in unscoped:
        if c not in unscoped_unique:
            unscoped_unique.append(c)
    return {
        "items": media_items,
        "pageMotionCandidates": page_motion_candidates,
        "unscopedMotionCandidateCount": len(unscoped_unique),
        "expectedLiveImageCount": sum(1 for i in images[:60] if douyin_image_expects_live(i)),
    }


def find_douyin_work_page(loader_data):
    if not isinstance(loader_data, dict):
        return None
    for node in loader_data.values():
        if isinstance(node, dict) and (node.get("videoInfoRes") or node.get("noteInfoRes")):
            return node
    return find_object(loader_data, lambda n: isinstance(n, dict) and (n.get("videoInfoRes") or n.get("noteInfoRes")))


def find_douyin_item_in_payload(payload, aweme_id):
    if not isinstance(payload, dict):
        return None
    direct_arrays = [
        payload.get("aweme_details"), payload.get("awemeDetails"),
        payload.get("aweme_list"), payload.get("item_list"),
        get_path(payload, "data.aweme_details"), get_path(payload, "data.aweme_list"),
        get_path(payload, "data.item_list"),
    ]
    for lst in direct_arrays:
        if not isinstance(lst, list):
            continue
        for candidate in lst:
            cid = str((candidate or {}).get("aweme_id") or (candidate or {}).get("awemeId") or (candidate or {}).get("item_id") or "")
            if isinstance(candidate, dict) and isinstance(candidate.get("images"), list) and (not aweme_id or not cid or cid == str(aweme_id)):
                return candidate
    detail = payload.get("aweme_detail") or payload.get("awemeDetail") or get_path(payload, "data.aweme_detail")
    if isinstance(detail, dict) and isinstance(detail.get("images"), list):
        return detail
    return find_object(payload, lambda node: isinstance(node, dict)
                       and isinstance(node.get("images"), list) and len(node.get("images", []))
                       and (not aweme_id
                            or not str(node.get("aweme_id") or node.get("awemeId") or node.get("item_id") or "")
                            or str(node.get("aweme_id") or node.get("awemeId") or node.get("item_id") or "") == str(aweme_id)))


def extract_douyin_item_from_html(html, aweme_id):
    html = str(html or "")
    assigned = [
        extract_assigned_json(html, "window._ROUTER_DATA"),
        extract_assigned_json(html, "_ROUTER_DATA"),
        extract_assigned_json(html, "window.__INITIAL_STATE__"),
        extract_assigned_json(html, "window.RENDER_DATA"),
    ]
    for payload in assigned:
        if payload is None:
            continue
        direct = find_douyin_item_in_payload(payload, aweme_id)
        if direct:
            return direct
        work = find_douyin_work_page(payload.get("loaderData") or payload)
        info = (work or {}).get("videoInfoRes") or (work or {}).get("noteInfoRes")
        direct = find_douyin_item_in_payload(info, aweme_id)
        if direct:
            return direct
    for m in re.finditer(
        r"<script[^>]+(?:id|data-name)=[\"'](?:RENDER_DATA|ROUTER_DATA|__NEXT_DATA__|SIGI_STATE)[\"'][^>]*>([\s\S]*?)</script>",
        html, re.I,
    ):
        text = decode_html_json_text(m.group(1))
        try:
            payload = json.loads(text)
        except Exception:
            continue
        item = find_douyin_item_in_payload(payload, aweme_id)
        if item:
            return item
        work = find_douyin_work_page(payload.get("loaderData") or payload)
        item = find_douyin_item_in_payload((work or {}).get("videoInfoRes") or (work or {}).get("noteInfoRes"), aweme_id)
        if item:
            return item
    return None


def fetch_douyin_slides_info(aweme_id):
    referer = "https://www.iesdouyin.com/share/slides/%s/" % aweme_id
    primed_page = None
    try:
        primed_page = fetch_text(referer, {
            "referer": "https://www.douyin.com/",
            "headers": {"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"},
        })
        page_item = extract_douyin_item_from_html(primed_page["text"], aweme_id)
        if page_item and isinstance(page_item.get("images"), list) and page_item["images"]:
            return page_item
    except Exception:
        pass
    if primed_page:
        fallback = extract_douyin_item_from_html(primed_page["text"], aweme_id)
        if fallback:
            return fallback
    return None


def douyin_page_has_work_data(text):
    text = str(text or "")
    return any(k in text for k in ("_ROUTER_DATA", "videoInfoRes", "noteInfoRes", "aweme_list", "item_list"))


def replace_url_param(url, name, value):
    url = str(url or "")
    if not url:
        return ""
    re_ = re.compile(r"([?&]%s=)[^&#]*" % re.escape(name), re.I)
    if re_.search(url):
        return re_.sub(r"\g<1>%s" % value, url)
    sep = "&" if "?" in url else "?"
    return url + sep + name + "=" + value


def douyin_video_candidates(video_url):
    video_url = str(video_url or "").replace("/playwm/", "/play/")
    out, seen = [], set()

    def add(url, source_field, primary):
        if not re.match(r"^https?://", url) or url in seen:
            return
        seen.add(url)
        out.append({"url": url, "sourceField": source_field, "primary": bool(primary), "requestHeaders": {}})

    if re.search(r"[?&]video_id=", video_url):
        for ratio in ("1080p", "540p", "720p"):
            for line in ("0", "1", "2"):
                add(replace_url_param(replace_url_param(video_url, "ratio", ratio), "line", line),
                    "douyin:%s:line%s" % (ratio, line), len(out) == 0)
    add(video_url, "douyin:selected", len(out) == 0)
    return out


def parse_douyin(url):
    first_page = fetch_text(url, {
        "headers": {"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"},
    })
    aweme_id = douyin_aweme_id((first_page["url"] or url) + "\n" + (first_page["text"] or ""))
    if not aweme_id:
        raise ParseError("未识别到抖音作品 ID")
    pages = [first_page]
    if first_page.get("url") and first_page["url"] != url and not douyin_page_has_work_data(first_page["text"]):
        try:
            pages.append(fetch_text(first_page["url"], {
                "referer": "https://www.douyin.com/",
                "headers": {"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"},
            }))
        except Exception:
            pass
    page_urls = [
        "https://m.douyin.com/share/video/" + aweme_id,
        "https://www.iesdouyin.com/share/video/%s/?from_ssr=1" % aweme_id,
        "https://www.iesdouyin.com/share/note/%s/?from_ssr=1" % aweme_id,
        "https://www.iesdouyin.com/share/slides/%s/" % aweme_id,
    ]
    for pi, pu in enumerate(page_urls):
        if pu == first_page.get("url"):
            continue
        try:
            pages.append(fetch_text(pu, {
                "referer": "https://www.douyin.com/" if pi == 0 else "https://www.iesdouyin.com/",
                "headers": {"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"},
            }))
        except Exception:
            pass

    item = None
    active_page = first_page
    for page in pages:
        if item:
            break
        router = extract_assigned_json(page["text"] or "", "window._ROUTER_DATA") or extract_assigned_json(page["text"] or "", "_ROUTER_DATA")
        if router is None:
            continue
        work_page = find_douyin_work_page(router.get("loaderData") or router)
        if not work_page:
            continue
        info = work_page.get("videoInfoRes") or work_page.get("noteInfoRes")
        if not info or int(info.get("status_code") or 0) != 0:
            continue
        lst = info.get("item_list") or info.get("aweme_list") or []
        if isinstance(lst, list) and lst:
            item = lst[0]
            active_page = page
    if not item:
        try:
            item = fetch_douyin_slides_info(aweme_id)
        except Exception:
            pass
    if not item:
        raise ParseError("抖音分享页没有返回可保存的作品数据")

    if isinstance(item.get("images"), list) and item["images"]:
        try:
            slides_item = fetch_douyin_slides_info(aweme_id)
            if slides_item and isinstance(slides_item.get("images"), list) and slides_item["images"]:
                item = slides_item
        except Exception:
            pass

    title = str(item.get("desc") or item.get("title") or "抖音作品").strip() or "抖音作品"
    author = str(get_path(item, "author.nickname") or get_path(item, "author.unique_id") or "")
    avatar = first_url(get_path(item, "author.avatar_larger") or get_path(item, "author.avatar_medium") or get_path(item, "author.avatar_thumb"))
    douyin_media = build_douyin_media_items(item, pages)
    media_items = douyin_media["items"]
    page_motion_candidates = douyin_media["pageMotionCandidates"]

    if media_items:
        has_live = any(e.get("livePhotoUrl") for e in media_items)
        expects_live = has_live or douyin_media["expectedLiveImageCount"] > 0
        live_extras = result_live_contract_extras(media_items, expects_live, "origin")
        return result(
            "抖音", "live" if has_live else "gallery", active_page.get("url") or first_page.get("url") or url,
            title, "", media_items[0]["url"], media_items, author, avatar,
            "douyin:" + ("live-original" if has_live else "gallery-original") + ":" + aweme_id +
            ":motion=%d:pairing=%s:unscopedCandidates=%d:pageCandidates=%d" % (
                sum(1 for e in media_items if e.get("livePhotoUrl")),
                live_extras["pairingStatus"], douyin_media["unscopedMotionCandidateCount"], len(page_motion_candidates)),
            None, None, "", live_extras,
        )

    video_root = item.get("video") or {}
    video = first_url(video_root.get("play_addr") or video_root.get("play_addr_h264") or video_root.get("download_addr"))
    if video:
        video = video.replace("http://", "https://", 1).replace("/playwm/", "/play/")
    cover = first_url(video_root.get("cover") or video_root.get("origin_cover") or video_root.get("dynamic_cover"))
    if video:
        video_result = result("抖音", "video", active_page.get("url") or first_page.get("url") or url, title, video, cover, [], author, avatar, "douyin:video:" + aweme_id)
        video_result["mediaCandidates"] = douyin_video_candidates(video_result["videoUrl"] or video)
        if video_result["mediaCandidates"]:
            video_result["videoUrl"] = video_result["mediaCandidates"][0]["url"]
            video_result["mediaUrl"] = video_result["mediaCandidates"][0]["url"]
        return video_result
    raise ParseError("抖音作品已识别，但没有返回可保存媒体")


# ---------------------------------------------------------------------------
# 快手
# ---------------------------------------------------------------------------

def kuaishou_media_headers(source_url):
    return {"Referer": source_url or "https://www.kuaishou.com/"}


def kuaishou_motion_candidate(value):
    urls = []
    for u in collect_urls(value, "video"):
        lower = u.lower()
        if re.search(r"music|audio|\.m4a(?:[?#]|$)|\.mp3(?:[?#]|$)", lower):
            continue
        if re.search(r"\.(mp4|mov|m4v|webm)(?:[?#]|$)|livephoto|live_photo|motion|dynamic|mainmvurls|manifest", lower):
            urls.append(u.replace("http://", "https://", 1))
    return pick_video(urls)


def kuaishou_maybe_json(value):
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text.startswith(("[", "{")):
        return value
    try:
        return json.loads(text)
    except Exception:
        return value


def kuaishou_live_photo_infos(photo, atlas):
    roots = [
        get_path(atlas, "atlasLivePhotoInfos"), get_path(atlas, "atlas_live_photo_infos"),
        get_path(photo, "atlasLivePhotoInfos"), get_path(photo, "atlas_live_photo_infos"),
        get_path(photo, "ext_params.atlasLivePhotoInfos"), get_path(photo, "ext_params.atlas_live_photo_infos"),
        get_path(photo, "ext_params.atlas.atlasLivePhotoInfos"), get_path(photo, "ext_params.atlas.atlas_live_photo_infos"),
    ]
    for r in roots:
        if isinstance(r, list):
            return r
    return []


def _is_true_flag(value):
    return value is True or value == 1 or value == "1" or str(value).lower() == "true"


def kuaishou_atlas_has_live_photo(photo, atlas):
    metas = [
        get_path(atlas, "atlasLivePhotoMeta"), get_path(atlas, "atlas_live_photo_meta"),
        get_path(photo, "atlasLivePhotoMeta"), get_path(photo, "atlas_live_photo_meta"),
        get_path(photo, "ext_params.atlasLivePhotoMeta"), get_path(photo, "ext_params.atlas_live_photo_meta"),
        get_path(photo, "ext_params.atlas.atlasLivePhotoMeta"), get_path(photo, "ext_params.atlas.atlas_live_photo_meta"),
    ]
    for meta in metas:
        if not isinstance(meta, dict):
            continue
        flag = meta.get("atlasHasLivePhoto", meta.get("atlas_has_live_photo"))
        if flag is not None and _is_true_flag(flag):
            return True
    return any(
        info and _is_true_flag(info.get("isLivePhoto", info.get("is_live_photo")))
        for info in kuaishou_live_photo_infos(photo, atlas)
    )


def kuaishou_info_is_live_photo(info):
    if not isinstance(info, dict):
        return False
    flag = info.get("isLivePhoto", info.get("is_live_photo"))
    return flag is not None and _is_true_flag(flag)


def kuaishou_stream_manifest_motion_url(info):
    if not isinstance(info, dict):
        return ""
    roots = [
        info.get("streamManifest"), info.get("stream_manifest"),
        info.get("kwaiManifest"), info.get("kwai_manifest"), info.get("manifest"),
        get_path(info, "streamManifest.KwaiManifest"), get_path(info, "streamManifest.kwaiManifest"),
        get_path(info, "stream_manifest.KwaiManifest"), get_path(info, "stream_manifest.kwaiManifest"),
    ]
    roots = [kuaishou_maybe_json(r) for r in roots]
    for root in roots:
        if not root:
            continue
        nested = kuaishou_maybe_json(root.get("KwaiManifest") or root.get("kwaiManifest") or root.get("manifest") or root) if isinstance(root, dict) else root
        if not isinstance(nested, dict):
            continue
        sets = nested.get("adaptationSet") or nested.get("adaptationSets") or nested.get("adaptation_set")
        sets = sets if isinstance(sets, list) else ([sets] if sets else [])
        for s in sets:
            if not isinstance(s, dict):
                continue
            reps = s.get("representation") or s.get("representations") or s.get("representationList") or s.get("representation_list")
            reps = reps if isinstance(reps, list) else ([reps] if reps else [])
            for rep in reps:
                if not isinstance(rep, dict):
                    continue
                direct = first_url(rep.get("url") or rep.get("playUrl") or rep.get("play_url")
                                   or rep.get("backupUrl") or rep.get("backup_url")
                                   or rep.get("backupUrls") or rep.get("backup_urls")
                                   or rep.get("urlList") or rep.get("url_list") or rep)
                if direct:
                    return direct.replace("http://", "https://", 1)
                collected = kuaishou_motion_candidate(rep)
                if collected:
                    return collected
        candidate = kuaishou_motion_candidate(nested)
        if candidate:
            return candidate
    return ""


def kuaishou_official_atlas_live_contract(photo, atlas, atlas_count):
    infos = kuaishou_live_photo_infos(photo, atlas)
    has_intent = kuaishou_atlas_has_live_photo(photo, atlas)
    live_indexes, motion_urls = {}, {}
    live_count = paired_count = 0
    for index, info in enumerate(infos):
        if not kuaishou_info_is_live_photo(info):
            continue
        live_indexes[index] = True
        live_count += 1
        motion_url = kuaishou_stream_manifest_motion_url(info)
        if motion_url:
            motion_urls[index] = motion_url
            paired_count += 1
    if has_intent and not live_count and not infos and atlas_count > 0:
        for i in range(atlas_count):
            live_indexes[i] = True
        live_count = atlas_count
    return {
        "hasIntent": has_intent,
        "infosCount": len(infos),
        "atlasCount": atlas_count or 0,
        "countMismatch": bool(has_intent and infos and atlas_count > 0 and len(infos) != atlas_count),
        "liveIndexes": live_indexes,
        "motionUrls": motion_urls,
        "liveCount": live_count,
        "pairedCount": paired_count,
        "complete": bool(has_intent and live_count > 0 and live_count == paired_count and not (infos and atlas_count > 0 and len(infos) != atlas_count)),
    }


def kuaishou_motion_url_for_atlas_item(photo, atlas, atlas_item, index):
    official = kuaishou_official_atlas_live_contract(photo, atlas, len(get_path(atlas, "list")) if isinstance(get_path(atlas, "list"), list) else 0)
    if official["hasIntent"]:
        return official["motionUrls"].get(index, "")
    direct = kuaishou_motion_candidate(atlas_item)
    if direct:
        return direct
    indexed_roots = [
        get_path(atlas, "livePhotos"), get_path(atlas, "livePhotoList"), get_path(atlas, "live_photo_list"),
        get_path(atlas, "motionList"), get_path(atlas, "motion_list"),
        get_path(atlas, "dynamicVideos"), get_path(atlas, "dynamic_video_list"),
        get_path(photo, "imageLivePhotos"), get_path(photo, "image_live_photos"),
        get_path(photo, "livePhotoUrls"), get_path(photo, "live_photo_urls"),
        get_path(photo, "motionUrls"), get_path(photo, "motion_urls"),
    ]
    for lst in indexed_roots:
        if isinstance(lst, list) and index < len(lst):
            direct = kuaishou_motion_candidate(lst[index])
            if direct:
                return direct
    found = [""]

    def visitor(value, path):
        if found[0] or not isinstance(value, str):
            return
        key = ".".join(path).lower()
        if not re.search(r"live[_-]?photo|motion|dynamic[_-]?video|atlas.*video|image[_-]?live", key):
            return
        if str(index) not in path and ("." + str(index) + ".") not in key:
            return
        candidate = kuaishou_motion_candidate(value)
        if candidate:
            found[0] = candidate

    walk(photo, visitor)
    return found[0]


def parse_kuaishou(url):
    page = fetch_text(url, {"headers": {"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}})
    state = extract_assigned_json(page["text"], "window.INIT_STATE") or extract_assigned_json(page["text"], "window.__INITIAL_STATE__")
    if state is None:
        raise ParseError("快手分享页没有返回 INIT_STATE")

    def kuaishou_photo_has_media(photo):
        return bool(photo and isinstance(photo, dict) and (
            photo.get("mainMvUrls") or photo.get("manifest") or photo.get("caption")
            or photo.get("coverUrls") or (photo.get("ext_params") or {}).get("atlas")
        ))

    envelope = find_object(state, lambda node: isinstance(node, dict) and kuaishou_photo_has_media(node.get("photo"))
                           and (node.get("result") == 1 or node.get("result") == "1" or node.get("result") is None))
    photo = (envelope or {}).get("photo") if envelope else None
    if not photo:
        photo = find_object(state, lambda node: isinstance(node, dict) and (
            node.get("mainMvUrls") or node.get("manifest")
            or ((node.get("ext_params") or {}).get("atlas"))
            or (node.get("caption") and node.get("coverUrls"))
        ))
    if not photo:
        raise ParseError("快手分享页状态数据中没有作品信息")

    manifest_video = (
        first_url(get_path(photo, "manifest.adaptationSet.0.representation.0.backupUrl"))
        or first_url(get_path(photo, "manifest.adaptationSet.0.representation.0.url"))
        or first_url(get_path(photo, "manifest.adaptationSet.0.representation"))
        or pick_video(collect_urls(photo.get("manifest") or {}, "video"))
    )
    video = first_url(get_path(photo, "mainMvUrls.0.url")) or first_url(photo.get("mainMvUrls")) or manifest_video or pick_video(collect_urls(photo, "video"))
    cover = first_url(get_path(photo, "coverUrls.0.url")) or first_url(photo.get("coverUrls"))
    title = str(photo.get("caption") or photo.get("title") or "快手内容")
    author = str(photo.get("userName") or get_path(photo, "user.name") or "")
    avatar = first_url(photo.get("headUrl")) or first_url(get_path(photo, "user.headUrl"))
    atlas = get_path(photo, "ext_params.atlas") or ((envelope or {}).get("atlas")) or None
    atlas_host = str(get_path(atlas, "cdn.0") or get_path(atlas, "cdnList.0.cdn") or "")
    atlas_list = get_path(atlas, "list")
    official_atlas_live = kuaishou_official_atlas_live_contract(photo, atlas, len(atlas_list) if isinstance(atlas_list, list) else 0)
    media_headers = kuaishou_media_headers(page.get("url") or url)
    atlas_music_path = str(get_path(atlas, "music") or "")
    atlas_music_host = str(get_path(atlas, "musicCdnList.0.cdn") or "")
    atlas_music = first_url(atlas_music_path) or ("https://" + atlas_music_host + "/" + atlas_music_path.lstrip("/")
                                                  if atlas_music_host and atlas_music_path else "")

    items = []
    if atlas_host and isinstance(atlas_list, list):
        for item_index, item in enumerate(atlas_list[:40]):
            key = item if isinstance(item, str) else first_url(item)
            image_url = key if re.match(r"^https?://", key) else "https://" + atlas_host + "/" + str(key or "").lstrip("/")
            motion_url = kuaishou_motion_url_for_atlas_item(photo, atlas, item, item_index)
            expected_live = bool(official_atlas_live["liveIndexes"].get(item_index)) if official_atlas_live["hasIntent"] else bool(motion_url)
            if image_url and image_url != "https://" + atlas_host + "/":
                items.append({
                    "url": image_url,
                    "livePhotoUrl": motion_url,
                    "requestHeaders": media_headers,
                    "stillSourceKind": "origin", "selectedStillSource": "origin", "sourceKind": "origin",
                    "motionSourceKind": "public-page" if motion_url else "",
                    "pairingStatus": "paired" if motion_url else ("live_source_unavailable" if expected_live else "original_only"),
                })
    if not items and (photo.get("singlePicture") or str(photo.get("photoType") or "").upper() == "SINGLE_PICTURE"):
        single = first_url(photo.get("webpCoverUrls")) or first_url(photo.get("coverUrls")) or cover
        if single:
            items.append({"url": single, "livePhotoUrl": "", "requestHeaders": media_headers,
                          "stillSourceKind": "origin", "selectedStillSource": "origin", "sourceKind": "origin",
                          "pairingStatus": "original_only"})

    if video and not items:
        return result("快手", "video", page.get("url") or url, title, video, cover, [], author, avatar,
                      "kuaishou:init-state:" + ("manifest" if manifest_video else "photo"), media_headers)

    if items:
        motion_count = sum(1 for e in items if e.get("livePhotoUrl"))
        has_expected_atlas_live = official_atlas_live["hasIntent"] or motion_count > 0
        live_extras = result_live_contract_extras(items, has_expected_atlas_live, "origin")
        if official_atlas_live["countMismatch"] and live_extras["pairingStatus"] == "paired":
            live_extras["pairingStatus"] = "partial"
            live_extras["liveStatus"] = "partial"
            live_extras["partial"] = True
        raw_motion_count = motion_count
        raw_pairing = live_extras["pairingStatus"]
        is_complete = bool(official_atlas_live["complete"] and motion_count > 0
                           and live_extras["pairingStatus"] == "paired"
                           and live_extras["stillCount"] == motion_count)
        if not is_complete:
            items = [{**e, "livePhotoUrl": "", "motionSourceKind": "", "pairingStatus": "original_only"} for e in items]
            motion_count = 0
            live_extras = result_live_contract_extras(items, False, "origin")
        return result(
            "快手", "live" if is_complete else "gallery", page.get("url") or url, title, "", cover or items[0]["url"],
            items, author, avatar,
            "kuaishou:init-state:" + ("atlas:" if atlas_host and isinstance(atlas_list, list) else "single-picture:")
            + "%d:officialLive=%s:liveInfos=%d:motion=%d:pairing=%s:music=%s" % (
                len(items), "1" if official_atlas_live["hasIntent"] else "0", official_atlas_live["infosCount"],
                motion_count, live_extras["pairingStatus"], "1" if atlas_music else "0")
            + (":downgrade=original_only:rawMotion=%d:rawPairing=%s" % (raw_motion_count, raw_pairing) if not is_complete and has_expected_atlas_live else ""),
            media_headers, [], atlas_music, live_extras,
        )
    raise ParseError("快手作品已识别，但没有返回可保存的视频或图集")


# ---------------------------------------------------------------------------
# 小红书
# ---------------------------------------------------------------------------

def xhs_note_id_from_url(value):
    m = re.search(r"/(?:explore|discovery/item)/([0-9a-f]{24})(?:[/?#]|$)", str(value or ""), re.I)
    return m.group(1) if m else ""


def xhs_canonical_url(value, fallback_id=""):
    note_id = xhs_note_id_from_url(value) or fallback_id or ""
    if not note_id:
        return ""
    token = ""
    try:
        token = urllib.parse.urlsplit(value).query and dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(value).query)).get("xsec_token") or ""
    except Exception:
        token = ""
    query = ("?xsec_token=" + urllib.parse.quote(token) + "&xsec_source=pc_share") if token else ""
    return "https://www.xiaohongshu.com/explore/" + note_id + query


def xhs_source_image_path_prefixes():
    prefixes = [
        "notes_pre_post/", "notes_pre_post/spectrum/", "notes_uhdr/",
        "note_pre_post/", "note_pre_post_uhdr/",
        "oss-sg/notes/", "oss-cn/notes/",
    ]
    return prefixes


def xhs_trusted_image_path(value):
    path = re.sub(r"^https?://[^/]+/", "", str(value or ""), count=1)
    path = path.lstrip("/")
    path = re.sub(r"[?#].*$", "", path)
    path = re.sub(r"!.*", "", path)
    lower = path.lower()
    for prefix in xhs_source_image_path_prefixes():
        index = lower.rfind(prefix)
        if index < 0:
            continue
        candidate = path[index:]
        if re.match(r"^[0-9a-z_/-]{12,}$", candidate, re.I) and "//" not in candidate:
            return candidate
    m = re.search(r"/?spectrum/([^/?#]+)$", path, re.I)
    if m:
        return "spectrum/" + m.group(1)
    return ""


def xhs_explicit_image_file_id(value, allow_bucket_prefix=False):
    value = str(value or "").strip()
    if not value or re.match(r"^https?://", value, re.I):
        return ""
    value = value.lstrip("/")
    value = re.sub(r"[?#].*$", "", value)
    value = re.sub(r"!.*", "", value)
    trusted = xhs_trusted_image_path(value)
    if trusted:
        return trusted
    if re.match(r"^(?:1040|1000)[0-9a-z_-]{12,}$", value, re.I):
        return value
    if allow_bucket_prefix and re.match(r"^[0-9a-z]{1,3}/(?:1040|1000)[0-9a-z_-]{12,}$", value, re.I):
        return value
    return ""


def xhs_image_file_id(image, allow_bucket_prefix=False):
    image = image or {}
    explicit = xhs_explicit_image_file_id(
        image.get("fileId") or image.get("file_id") or image.get("imageId") or image.get("image_id"),
        allow_bucket_prefix,
    )
    if explicit:
        return explicit
    if isinstance(image.get("infoList"), list):
        for k in image["infoList"]:
            explicit = xhs_explicit_image_file_id(
                (k or {}).get("fileId") or (k or {}).get("file_id") or (k or {}).get("imageId") or (k or {}).get("image_id"),
                allow_bucket_prefix,
            )
            if explicit:
                return explicit
    return ""


def xhs_source_image_url_from_file_id(image, allow_bucket_prefix=False):
    file_id = xhs_image_file_id(image, allow_bucket_prefix)
    if not file_id:
        return ""
    source_host = [""]

    def visitor(value, path):
        if source_host[0] or not isinstance(value, str) or "sns-na-i" not in value:
            return
        try:
            host = urllib.parse.urlsplit(unescape_page_value(value).replace("http://", "https://", 1)).hostname or ""
            if re.match(r"^sns-na-i\d+\.xhscdn\.com$", host.lower()):
                source_host[0] = host.lower()
        except Exception:
            pass

    walk(image, visitor)
    return "https://" + (source_host[0] or "sns-na-i6.xhscdn.com") + "/" + file_id


def xhs_normalize_image_url(value):
    value = unescape_page_value(str(value or "").strip())
    if not re.match(r"^https?://", value, re.I):
        return ""
    value = value.replace("http://", "https://", 1)
    if re.search(r"(?:xhscdn\.com|xiaohongshu\.com)", value, re.I) and re.search(
        r"(?:!|imageView2|redImage|sign=|sns-webpic|sns-na|style_)", value
    ):
        return value
    return re.sub(r"!.*", "", value)


def xhs_is_source_format_transcode_url(value):
    try:
        parsed = urllib.parse.urlsplit(str(value or ""))
        if parsed.scheme != "https":
            return False
        if not re.match(r"^sns-na-i\d+\.xhscdn\.com$", parsed.hostname.lower()):
            return False
        if "!" in parsed.path or len(parsed.path) < 2:
            return False
        query = urllib.parse.unquote(parsed.query).lower()
        return re.match(r"^imageview2/(?:\d/)?format/(?:jpg|jpeg|png|webp)(?:/q/\d{1,3})?$", query) is not None
    except Exception:
        return False


def xhs_still_source_kind(url, source_field=""):
    lower = str((source_field or "") + " " + (url or "")).lower()
    field = str(source_field or "").lower()
    url_lower = str(url or "").lower()
    if re.search(r"sns-webpic|!(?:h5_|nd_dft|nd_prv|style_)|redimage", url_lower):
        return "display"
    if "imageview2" in url_lower and not xhs_is_source_format_transcode_url(url):
        return "display"
    if re.search(r"urldefault|urlpre|preview|share|trace|render|cover|display|masterurl|html|direct-html|h5_dtl|h5_prv|h5_detail|h5_preview", field):
        return "display"
    if re.search(r"originimage|origin_image|original|sourceimage|source_image|source-fileid|sourcefileid", field):
        return "origin"
    if re.search(r"sns-webpic|sns-na|preview|share|trace|render|h5_", lower):
        return "display"
    return "unknown"


def xhs_preview_image_url(original_url):
    original_url = xhs_normalize_image_url(original_url)
    if not original_url:
        return ""
    if re.search(r"sns-na[^/]*\.xhscdn\.com", original_url, re.I) and not re.search(r"[?&]imageView2/", original_url, re.I) and "!" not in original_url:
        return original_url + ("&" if "?" in original_url else "?") + "imageView2/format/jpg"
    if re.search(r"(?:xhscdn\.com|sns-webpic|sns-na)", original_url, re.I):
        return original_url
    if re.search(r"ci\.xiaohongshu\.com", original_url, re.I) and not re.search(r"[?&]imageView2/", original_url, re.I):
        return original_url + ("&" if "?" in original_url else "?") + "imageView2/format/jpg"
    return original_url


def xhs_still_image_selection(image, allow_bucket_prefix=False):
    image = image or {}
    candidates, seen = [], set()

    def add(value, source_field, rank):
        direct = value if isinstance(value, str) else first_url(value)
        direct = xhs_normalize_image_url(direct)
        if not direct or direct in seen:
            return
        try:
            host = urllib.parse.urlsplit(direct).hostname or ""
            if not re.search(r"(^|\.)(?:xhscdn|xiaohongshu)\.com$", host, re.I):
                return
        except Exception:
            return
        seen.add(direct)
        source_kind = xhs_still_source_kind(direct, source_field)
        candidates.append({
            "url": direct,
            "previewUrl": xhs_preview_image_url(direct),
            "sourceKind": source_kind,
            "sourceField": source_field or "unknown",
            "trusted": source_kind == "origin",
            "rank": rank or 0,
        })

    add(image.get("originImage"), "originImage", 120)
    add(image.get("origin_image"), "origin_image", 100)
    add(image.get("original"), "original", 95)
    add(image.get("sourceImage"), "sourceImage", 95)
    add(image.get("source_image"), "source_image", 95)
    add(xhs_source_image_url_from_file_id(image, allow_bucket_prefix), "sourceImageVerified", 110)
    add(image.get("url"), "url", 50)
    add(image.get("urlDefault"), "urlDefault", 20)
    add(image.get("urlPre"), "urlPre", 10)
    if isinstance(image.get("infoList"), list):
        for index, entry in enumerate(image["infoList"]):
            add((entry or {}).get("originImage") or (entry or {}).get("origin_image") or (entry or {}).get("original"), "infoList.%d.origin" % index, 90)
            scene = re.sub(r"[^a-z0-9_-]", "_", str((entry or {}).get("imageScene") or "url"), flags=re.I)[:30]
            add((entry or {}).get("url") or entry, "infoList.%d.%s" % (index, scene), 75 if scene in ("H5_DTL", "H5_DETAIL", "WB_DFT") else 40)
    candidates.sort(key=lambda c: (not c["trusted"], -(c["rank"])))
    return candidates[0] if candidates else {"url": "", "previewUrl": "", "sourceKind": "missing", "sourceField": "", "trusted": False}


def xhs_original_source_unavailable(source_kind, item_count):
    err = ParseError("平台当前未返回可保存的无水印原图，请稍后重试。", "xhs_original_source_unavailable")
    err.diagnostic = "xiaohongshu:xhs_original_source_unavailable:sourceKind=%s:itemCount=%d" % (
        re.sub(r"[^a-z0-9_-]", "_", str(source_kind or "missing"), flags=re.I)[:40], max(0, int(item_count or 0)))
    return err


def xhs_deliverable_still_url(url, source_transcode):
    url = str(url or "")
    if not source_transcode:
        return url
    if not re.search(r"sns-na[^/]*\.xhscdn\.com", url, re.I):
        return url
    if re.search(r"[?&]imageView2/", url, re.I) or "!" in url:
        return url
    return url + ("&" if "?" in url else "?") + "imageView2/format/jpg/q/100"


def xhs_path_allows_bare_video_key(path):
    return re.search(r"originvideokey|origin_video_key|originkey|origin_key|sourcevideokey|source_video_key|sourcekey|source_key", str(path or "").lower()) is not None


def xhs_video_host_is_controlled(host):
    host = str(host or "").lower()
    return host == "xhscdn.com" or host.endswith(".xhscdn.com")


def xhs_url_authority_has_user_info(value):
    m = re.match(r"^[a-z][a-z0-9+.-]*://([^/?#]*)", str(value or ""), re.I)
    return bool(m and "@" in m.group(1))


def xhs_url_has_allowed_port(parsed):
    port = parsed.port
    return (not port
            or (parsed.scheme == "http" and port == 80)
            or (parsed.scheme == "https" and port == 443))


def xhs_original_video_from_key(value, allow_bare_key=False):
    value = unescape_page_value(str(value or "").strip())
    if not value:
        return ""

    def source_host_for_path(path):
        return "https://sns-video-bd.xhscdn.com/" + path

    if re.match(r"^https?://", value, re.I):
        try:
            if xhs_url_authority_has_user_info(value):
                return ""
            parsed = urllib.parse.urlsplit(value.replace("http://", "https://", 1))
            if parsed.scheme not in ("http", "https") or not xhs_url_has_allowed_port(parsed):
                return ""
            path = parsed.path.lstrip("/")
            if xhs_video_host_is_controlled(parsed.hostname) and re.match(r"^stream/", path, re.I):
                return source_host_for_path(path)
            if xhs_video_host_is_controlled(parsed.hostname) and allow_bare_key and re.match(r"^(?:1040|1000)[0-9a-z_-]{12,}$", path, re.I):
                return source_host_for_path(path)
        except Exception:
            pass
        return re.sub(r"^http:", "https:", value.replace("&amp;", "&")) if re.search(r"\.mp4(?:\?|$)", value, re.I) else ""
    value = value.lstrip("/")
    value = re.sub(r"[?#].*$", "", value)
    if not re.match(r"^(?:stream|pre_post)/", value, re.I) and not (allow_bare_key and re.match(r"^(?:1040|1000)[0-9a-z_-]{12,}$", value, re.I)) and not re.match(r"\.mp4$", value, re.I):
        return ""
    return source_host_for_path(value)


def xhs_video_source_proof(path):
    clean = str(path or "").lower()
    clean = re.sub(r"\[\d+\]", "", clean)
    parts = clean.split(".")
    field = parts[-1] if parts else ""
    return "explicit-origin-field" if field in (
        "originvideokey", "origin_video_key", "sourcevideokey", "source_video_key",
        "originkey", "origin_key", "sourcekey", "source_key") else "none"


def xhs_video_negative_signal(url, path, raw_value):
    field = str(path or "").lower()
    lower = (unescape_page_value(str(raw_value or "")) + "\n" + str(url or "")).lower()
    return bool(re.search(r"masterurl|master_url|urlpre|preview|rendered|display|playwm|(?:^|[._])wm(?:[._]|$)|cover|poster", field)
                or re.search(r"watermark|playwm|owner_watermark|(?:^|[^a-z])wm(?:[^a-z]|$)|(?:^|[^a-z0-9])259(?:[^a-z0-9]|$)|_259\.mp4|rendered|display", lower))


def xhs_controlled_video_identity(url):
    try:
        parsed = urllib.parse.urlsplit(str(url or ""))
        host = parsed.hostname.lower()
        path = parsed.path.lstrip("/").lower()
        if xhs_url_authority_has_user_info(url) or not xhs_url_has_allowed_port(parsed) or not xhs_video_host_is_controlled(host):
            return False
        return bool(re.match(r"^(?:stream|spectrum|pre_post|notes_pre_post)/", path)
                    or re.match(r"^(?:1040|1000)[0-9a-z_-]{12,}", path)
                    or re.search(r"\.mp4$", path))
    except Exception:
        return False


def xhs_video_safe_field(path):
    return re.sub(r"[^a-z0-9_.\[\]-]", "_", str(path or "unknown"), flags=re.I)[:120]


def xhs_video_identity_key(url):
    try:
        parsed = urllib.parse.urlsplit(str(url or ""))
        host = parsed.hostname.lower()
        path = parsed.path.lstrip("/").lower()
        if xhs_video_host_is_controlled(host) and path:
            return "xhscdn:" + path
    except Exception:
        pass
    return str(url or "")


def xhs_video_candidate(value, path):
    source_proof = xhs_video_source_proof(path)
    normalized = xhs_original_video_from_key(value, source_proof == "explicit-origin-field")
    if not normalized or not re.search(r"\.mp4(?:\?|$)|video|xhscdn|sns-video", normalized, re.I):
        return None
    negative = xhs_video_negative_signal(normalized, path, value)
    controlled = xhs_controlled_video_identity(normalized)
    score = 200 if source_proof == "explicit-origin-field" else 0
    if re.search(r"\.h264(?:\.|\[|$)", "." + str(path or ""), re.I):
        score += 30
    if re.search(r"/(?:spectrum|pre_post|notes_pre_post)/", normalized, re.I):
        score += 100
    elif re.search(r"/stream/", normalized, re.I):
        score += 60
    if negative:
        score -= 400
    return {
        "url": re.sub(r"^http:", "https:", normalized),
        "sourceField": xhs_video_safe_field(path),
        "sourceProof": source_proof,
        "controlledSourceIdentity": controlled,
        "negativeSourceSignal": negative,
        "trusted": source_proof == "explicit-origin-field" and controlled and not negative,
        "score": score,
    }


def xhs_unique_video_candidates(candidates):
    out, indexes = [], {}
    for candidate in candidates or []:
        if not candidate or not candidate.get("url"):
            continue
        key = xhs_video_identity_key(candidate["url"])
        if key not in indexes:
            indexes[key] = len(out)
            out.append(candidate)
            continue
        existing = out[indexes[key]]
        preferred = (
            (candidate["trusted"] and not existing["trusted"])
            or (candidate["sourceProof"] == "explicit-origin-field" and existing["sourceProof"] != "explicit-origin-field")
            or (candidate["trusted"] == existing["trusted"] and candidate["score"] > existing["score"])
        )
        if preferred:
            out[indexes[key]] = candidate
    return out


def xhs_collect_video_candidates(root):
    candidates = []

    def visitor(value, path):
        candidate = xhs_video_candidate(value, ".".join(path))
        if candidate:
            candidates.append(candidate)

    walk(root, visitor)
    return xhs_unique_video_candidates(candidates)


def xhs_video_selection(candidates):
    candidates = xhs_unique_video_candidates(candidates or [])
    trusted = [c for c in candidates if c["trusted"]]
    trusted.sort(key=lambda c: -c["score"])
    selected = trusted[0] if trusted else None
    return {
        "url": selected["url"] if selected else "",
        "sourceField": selected["sourceField"] if selected else "",
        "sourceProof": selected["sourceProof"] if selected else "none",
        "candidateCount": len(candidates),
        "explicitSourceCount": sum(1 for c in candidates if c["sourceProof"] == "explicit-origin-field"),
        "negativeSignalCount": sum(1 for c in candidates if c["negativeSourceSignal"]),
        "candidates": candidates,
    }


def xhs_trusted_video_selection(note):
    return xhs_video_selection(xhs_collect_video_candidates((note or {}).get("video")))


def xhs_raw_video_selection_from_html(html):
    html = str(html or "")
    candidates = []
    rejected_pattern = re.compile(r"[\"'](masterUrl|master_url|urlPre|url_pre|preview|rendered|display|wm|playwm|backupUrls?|backup_urls?|url)[\"']\s*:\s*[\"']([^\"']+)[\"']", re.I)
    direct_pattern = re.compile(r"(https?:\/\/[^\"'\s<>]+(?:xhscdn|sns-video|\.mp4)[^\"'\s<>]*)", re.I)
    for m in rejected_pattern.finditer(html):
        candidate = xhs_video_candidate(m.group(2), "rawHtml." + m.group(1))
        if candidate:
            candidates.append(candidate)
    for m in direct_pattern.finditer(html):
        candidate = xhs_video_candidate(m.group(1), "rawHtml.directUrl")
        if candidate:
            candidates.append(candidate)
    return xhs_video_selection(candidates)


def xhs_raw_video_from_html(html):
    return xhs_raw_video_selection_from_html(html)["url"]


def xhs_clean_video_source_unavailable(selection):
    selection = selection or {}
    err = ParseError("小红书页面未提供可确认的无水印视频源", "xhs_clean_video_source_unavailable")
    err.diagnostic = "xiaohongshu:xhs_clean_video_source_unavailable:candidateCount=%d:explicitSourceCount=%d:negativeSignalCount=%d" % (
        max(0, int(selection.get("candidateCount") or 0)),
        max(0, int(selection.get("explicitSourceCount") or 0)),
        max(0, int(selection.get("negativeSignalCount") or 0)))
    return err


def collect_xhs_live_candidates_from_html(html):
    return []


def xhs_live_video_url(image):
    return xhs_video_selection(xhs_collect_video_candidates(image or {}))["url"]


def collect_xhs_image_candidates_from_html(html):
    html = str(html or "")
    candidates, seen = {}, {}

    def add(raw, score, source):
        raw = unescape_page_value(raw or "").replace("http://", "https://", 1)
        if not raw:
            return
        if re.search(r"\.(?:js|css|svg)(?:[?#]|$)|fe-static\.xhscdn\.com|fe-platform\.xhscdn\.com|avatar|favicon|sprite|logo|icon", raw, re.I):
            return
        url = raw if re.match(r"^https?://", raw, re.I) else ""
        if not re.match(r"^https?://", url, re.I):
            return
        try:
            host = urllib.parse.urlsplit(url).hostname or ""
            if not re.search(r"(^|\.)(?:xhscdn|xiaohongshu)\.com$", host, re.I):
                return
        except Exception:
            return
        if url not in seen or score > seen[url]["score"]:
            source_kind = xhs_still_source_kind(url, source or "html")
            seen[url] = {"url": url, "previewUrl": xhs_preview_image_url(url), "score": score,
                         "source": source or "html", "sourceKind": source_kind, "trusted": source_kind == "origin"}

    path_pattern = re.compile(r"https?:(?:\\?/){2}[^\"'\s<>]*(?:notes_pre_post/spectrum/|notes_pre_post/|notes_uhdr/|note_pre_post_uhdr/|note_pre_post/|oss-sg/notes/|oss-cn/notes/)[^\"'\s<>]*", re.I)
    for m in path_pattern.finditer(html):
        add(m.group(0), 220, "source-path")
    direct_pattern = re.compile(r"(https?:(?:\\?/){2}[^\"'\s<>]+(?:ci\.xiaohongshu\.com|sns-webpic|sns-na|xhscdn\.com)[^\"'\s<>]*)", re.I)
    for m in direct_pattern.finditer(html):
        add(m.group(1), 80, "direct-html")
    return sorted(seen.values(), key=lambda c: -c["score"])


def xhs_html_live_fallback_result(html, active_page, page, url, meta_title, note_id):
    image_candidates = collect_xhs_image_candidates_from_html(html)
    live_candidates = collect_xhs_live_candidates_from_html(html)
    if not image_candidates:
        return None
    visible_images = [i for i in image_candidates[:40] if i["trusted"]]
    if not visible_images:
        first = image_candidates[0] or {}
        raise xhs_original_source_unavailable(first.get("sourceKind") or "missing", len(image_candidates))
    items = []
    for index, image in enumerate(visible_images):
        items.append({
            "url": image["url"],
            "previewUrl": image.get("previewUrl") or xhs_preview_image_url(image["url"]),
            "livePhotoUrl": live_candidates[index]["url"] if index < len(live_candidates) else "",
            "stillSourceKind": image.get("sourceKind") or "unknown",
            "selectedStillSource": image.get("sourceKind") or "unknown",
            "sourceKind": image.get("sourceKind") or "unknown",
            "motionSourceKind": live_candidates[index]["source"] if index < len(live_candidates) else "",
            "pairingStatus": "paired" if index < len(live_candidates) and image.get("trusted") is not False
            else ("partial" if index < len(live_candidates) else "live_source_unavailable"),
        })
    has_live = any(i.get("livePhotoUrl") for i in items)
    return result(
        "小红书", "live" if has_live else "gallery", (active_page or {}).get("url") or (page or {}).get("url") or url,
        meta_title or "小红书内容", "", items[0]["url"], items, "", "",
        "xiaohongshu:html-" + ("live" if has_live else "gallery") + "-fallback:" + (note_id or "unknown")
        + ":motion=%d:raw=%d:images=%d" % (
            sum(1 for e in items if e.get("livePhotoUrl")), len(live_candidates), len(image_candidates))
    )


def parse_xhs(url, source_transcode=False):
    page = fetch_text(url, {
        "referer": "https://www.xiaohongshu.com/",
        "headers": {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Upgrade-Insecure-Requests": "1",
        },
    })
    pages = [page]
    note_id = xhs_note_id_from_url(page.get("url") or url)
    canonical = xhs_canonical_url(page.get("url") or url, note_id)
    if canonical and canonical != page.get("url") and not re.search(r"/explore/", page.get("url") or "", re.I):
        try:
            pages.insert(0, fetch_text(canonical, {
                "referer": page.get("url") or "https://www.xiaohongshu.com/",
                "headers": {
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                    "Upgrade-Insecure-Requests": "1",
                },
            }))
        except Exception:
            pass

    state = None
    active_page = pages[0]
    for p in pages:
        candidate = extract_initial_state(p["text"])
        if candidate is not None:
            state = candidate
            active_page = p
            break

    note = None
    note_id = note_id or xhs_note_id_from_url(active_page.get("url") or url)
    if state is not None:
        note_id = str(get_path(state, "note.currentNoteId") or get_path(state, "noteData.noteId")
                      or get_path(state, "note.noteId") or note_id or "")
        maps = [get_path(state, "note.noteDetailMap"), get_path(state, "noteDetailMap"),
                get_path(state, "noteData.noteDetailMap"), get_path(state, "noteData.data.noteDetailMap")]
        for m in maps:
            if not isinstance(m, dict):
                continue
            if note_id and m.get(note_id):
                note = m[note_id].get("note") or m[note_id]
            if not note:
                for mk in list(m.keys()):
                    candidate = m[mk]
                    candidate = (candidate or {}).get("note") or (candidate or {}).get("noteData") or candidate
                    if isinstance(candidate, dict) and (candidate.get("video") or candidate.get("imageList") or candidate.get("images")):
                        note = candidate
                        note_id = note_id or mk
                        break
            if note:
                break
        if not note:
            note = find_object(state, lambda node: isinstance(node, dict)
                               and (node.get("imageList") or node.get("images")
                                    or (node.get("video") and (node.get("user") or node.get("author") or node.get("noteId"))))
                               and (node.get("title") is not None or node.get("desc") is not None or node.get("noteId") is not None))

    html = "\n".join(p.get("text") or "" for p in pages)
    mv = re.search(r"<meta[^>]+(?:property|name)=[\"'](?:og:video|og:video:url)[\"'][^>]+content=[\"']([^\"']+)[\"']", html, re.I) \
        or re.search(r"<meta[^>]+content=[\"']([^\"']+)[\"'][^>]+(?:property|name)=[\"'](?:og:video|og:video:url)[\"']", html, re.I)
    mc = re.search(r"<meta[^>]+(?:property|name)=[\"']og:image[\"'][^>]+content=[\"']([^\"']+)[\"']", html, re.I) \
        or re.search(r"<meta[^>]+content=[\"']([^\"']+)[\"'][^>]+(?:property|name)=[\"']og:image[\"']", html, re.I)
    mt = re.search(r"<meta[^>]+(?:property|name)=[\"']og:title[\"'][^>]+content=[\"']([^\"']+)[\"']", html, re.I) \
        or re.search(r"<meta[^>]+content=[\"']([^\"']+)[\"'][^>]+(?:property|name)=[\"']og:title[\"']", html, re.I)
    meta_video = unescape_page_value(mv.group(1)) if mv else ""
    meta_cover = unescape_page_value(mc.group(1)) if mc else ""
    meta_title = unescape_page_value(mt.group(1)) if mt else ""

    if not note:
        html_live_fallback = xhs_html_live_fallback_result(html, active_page, page, url, meta_title, note_id)
        if html_live_fallback:
            return html_live_fallback
        raw_video_selection = xhs_raw_video_selection_from_html(html)
        if raw_video_selection["url"]:
            return result("小红书", "video", active_page.get("url") or page.get("url") or url, meta_title or "小红书视频",
                          raw_video_selection["url"], meta_cover.replace("http://", "https://", 1), [], "", "",
                          "xiaohongshu:raw-video:sourceProof=%s:candidateCount=%d:cleanSource=true" % (
                              raw_video_selection["sourceProof"], raw_video_selection["candidateCount"]))
        if raw_video_selection["candidateCount"] > 0:
            raise xhs_clean_video_source_unavailable(raw_video_selection)
        if not meta_video:
            marker = "state-marker-present" if "__INITIAL_STATE__" in html else "state-marker-missing"
            raise ParseError("小红书公开页面未返回可保存视频（%s，最终地址：%s）" % (marker, str(active_page.get("url") or page.get("url") or url)[:180]))
        raise xhs_clean_video_source_unavailable({"candidateCount": 1, "explicitSourceCount": 0, "negativeSignalCount": 0})

    video_selection = xhs_trusted_video_selection(note)
    video = video_selection["url"]
    image_list = note.get("imageList") if isinstance(note.get("imageList"), list) else (note.get("images") if isinstance(note.get("images"), list) else [])
    raw_live_candidates = collect_xhs_live_candidates_from_html(html)
    items = []
    for image_index, image in enumerate(image_list[:40]):
        still = xhs_still_image_selection(image, source_transcode)
        image_url = still["url"]
        if not still["trusted"]:
            raise xhs_original_source_unavailable(still.get("sourceKind") or "missing", len(image_list))
        if not image_url:
            raise xhs_original_source_unavailable("missing", len(image_list))
        live_url = xhs_live_video_url(image)
        if not live_url and len(raw_live_candidates) == len(image_list) and image_index < len(raw_live_candidates):
            live_url = raw_live_candidates[image_index]["url"]
        elif not live_url and len(image_list) == 1 and raw_live_candidates:
            live_url = raw_live_candidates[0]["url"]
        image_url = xhs_deliverable_still_url(image_url.replace("http://", "https://", 1), source_transcode)
        items.append({
            "url": image_url,
            "previewUrl": still.get("previewUrl") or xhs_preview_image_url(image_url),
            "livePhotoUrl": str(live_url or "").replace("http://", "https://", 1),
            "stillSourceKind": still.get("sourceKind"),
            "selectedStillSource": still.get("sourceKind"),
            "sourceKind": still.get("sourceKind"),
            "stillSourceField": still.get("sourceField"),
            "motionSourceKind": "public-page" if live_url else "",
            "pairingStatus": "paired" if live_url else ("partial" if not still.get("trusted") else "live_source_unavailable"),
        })
    title = str(note.get("title") or note.get("desc") or meta_title or "小红书内容")
    author = str(get_path(note, "user.nickname") or get_path(note, "user.nickName") or get_path(note, "author.nickname") or "")
    avatar = first_url(get_path(note, "user.avatar") or get_path(note, "author.avatar"))
    cover = items[0]["url"] if items else first_url(note.get("cover") or get_path(note, "video.cover")) or meta_cover
    if video:
        return result("小红书", "video", active_page.get("url") or page.get("url") or url, title,
                      video.replace("http://", "https://", 1), (cover or "").replace("http://", "https://", 1),
                      [], author, avatar,
                      "xiaohongshu:video:selectedField=%s:sourceProof=%s:candidateCount=%d:cleanSource=true" % (
                          video_selection["sourceField"], video_selection["sourceProof"], video_selection["candidateCount"]))
    if note.get("video"):
        raise xhs_clean_video_source_unavailable(video_selection)
    if items:
        has_live = any(i.get("livePhotoUrl") for i in items)
        return result("小红书", "live" if has_live else "gallery", active_page.get("url") or page.get("url") or url,
                      title, "", cover, items, author, avatar,
                      "xiaohongshu:" + ("live" if has_live else "gallery") + ":" + (note_id or "unknown")
                      + ":motion=%d:stillSource=%s:pairing=%s:raw=%d" % (
                          sum(1 for e in items if e.get("livePhotoUrl")),
                          items[0].get("selectedStillSource") or "missing",
                          result_live_contract_extras(items, has_live, items[0].get("selectedStillSource") or "")["pairingStatus"],
                          len(raw_live_candidates)),
                      None, None, "", result_live_contract_extras(items, has_live, items[0].get("selectedStillSource") or ""))
    empty_items_live_fallback = xhs_html_live_fallback_result(html, active_page, page, url, title or meta_title, note_id)
    if empty_items_live_fallback:
        return empty_items_live_fallback
    raise ParseError("小红书笔记已识别，但没有返回可保存媒体")


# ---------------------------------------------------------------------------
# 皮皮虾
# ---------------------------------------------------------------------------

def parse_pipixia(url):
    page = fetch_text(url, {"headers": {"Accept": "text/html,application/xhtml+xml"}})
    pid = extract_digits(page["url"] + "\n" + page["text"], [
        r"[?&](?:cell_id|item_id|id)=(\d{8,})",
        r"/(?:ppx/)?item/(\d{8,})",
        r'"cell_id"\s*:\s*"?(\d{8,})',
        r'"itemId"\s*:\s*"?(\d{8,})',
        r"%22(?:groupId|itemId)%22%3A%22(\d{8,})%22",
    ])
    if not pid:
        raise ParseError("未识别到皮皮虾作品 ID")
    api = "https://api.pipix.com/bds/cell/cell_comment/?offset=0&cell_type=1&api_version=1&cell_id=%s&ac=wifi&channel=huawei_1319_64&aid=1319&app_name=super" % urllib.parse.quote(pid)
    payload = fetch_json(api, {"headers": {"Accept": "application/json"}})["data"]
    item = get_path(payload, "data.cell_comments.0.comment_info.item")
    if not item:
        item = find_object(payload, lambda node: isinstance(node, dict) and node.get("video") and node.get("author") and (node.get("content") is not None or node.get("note")))
    if not item:
        raise ParseError("皮皮虾接口未返回作品详情")
    video = first_url(get_path(item, "video.video_high.url_list.0.url")) or first_url(get_path(item, "video.video_download.url_list.0.url")) or pick_video(collect_urls(item.get("video") or item, "video"))
    multi = get_path(item, "note.multi_image")
    items = []
    if isinstance(multi, list):
        for image in multi[:40]:
            image_url = first_url(get_path(image, "url_list.0.url")) or first_url(image)
            if image_url:
                items.append({"url": image_url, "livePhotoUrl": ""})
    title = str(item.get("content") or item.get("text") or item.get("title") or "皮皮虾内容")
    author = str(get_path(item, "author.name") or "")
    avatar = first_url(get_path(item, "author.avatar.download_list.0.url"))
    cover = first_url(get_path(item, "cover.url_list.0.url")) or (items[0]["url"] if items else "") or ""
    if video:
        return result("皮皮虾", "video", page.get("url") or url, title, video, cover, [], author, avatar, "pipixia:cell-comment:" + pid)
    if items:
        return result("皮皮虾", "gallery", page.get("url") or url, title, "", cover, items, author, avatar, "pipixia:gallery:" + pid)
    raise ParseError("皮皮虾作品已识别，但没有返回可保存媒体")


# ---------------------------------------------------------------------------
# 最右
# ---------------------------------------------------------------------------

def parse_zuiyou(url):
    pid = extract_digits(url, [r"[?&]pid=(\d+)", r"/post/(\d+)"])
    if not pid:
        raise ParseError("未识别到最右作品 PID")
    api = "https://share.xiaochuankeji.cn/planck/share/post/detail_h5"
    payload = fetch_json(api, {
        "method": "POST",
        "headers": {"Content-Type": "application/json", "Accept": "application/json"},
        "body": json.dumps({"h_av": "5.2.13.011", "pid": int(pid)}),
    })["data"]
    post = get_path(payload, "data.post") or find_object(payload, lambda node: isinstance(node, dict) and node.get("videos") and node.get("imgs") and node.get("content") is not None)
    if not post:
        raise ParseError("最右接口未返回作品详情")
    first_image = post.get("imgs")[0] if isinstance(post.get("imgs"), list) and post["imgs"] else None
    video_key = str((first_image or {}).get("id") or "")
    videos = post.get("videos") or {}
    video_node = videos.get(video_key) if video_key else None
    if not video_node and isinstance(videos, dict):
        keys = list(videos.keys())
        if keys:
            video_node = videos[keys[0]]
    video = first_url((video_node or {}).get("url")) or pick_video(collect_urls(video_node or post, "video"))
    cover = first_url((video_node or {}).get("cover_urls")) or first_url(first_image)
    title = str(post.get("content") or post.get("text") or post.get("title") or "最右视频")
    author = str(get_path(post, "member.name") or "")
    avatar = first_url(get_path(post, "member.avatar_urls.origin.urls.0"))
    if not video:
        raise ParseError("最右作品已识别，但接口没有返回视频文件")
    return result("最右", "video", url, title, video, cover, [], author, avatar, "zuiyou:detail-h5:" + pid)


# ---------------------------------------------------------------------------
# 微博
# ---------------------------------------------------------------------------

def weibo_post_id(url):
    value = str(url or "")
    m = re.search(r"/(?:detail|status)/([A-Za-z0-9:]+)(?:[/?#]|$)", value, re.I)
    if m:
        return m.group(1)
    path = ""
    try:
        path = urllib.parse.urlsplit(value).path
    except Exception:
        pass
    parts = [p for p in path.strip("/").split("/") if p]
    return parts[-1] if parts else ""


def weibo_image_url(value):
    if isinstance(value, dict):
        value = first_url(value) or value.get("pid") or value.get("pic_id") or value.get("picId") or value.get("id") or ""
    value = str(value or "").replace("http://", "https://", 1)
    if re.match(r"^[0-9a-z]{16,}(?:\.(?:jpg|jpeg|png|webp|gif))?$", value, re.I):
        return "https://ww1.sinaimg.cn/large/" + re.sub(r"\.(?:jpg|jpeg|png|webp|gif)$", "", value, flags=re.I) + ".jpg"
    m = re.match(r"^https?://[^/]+\.sinaimg\.cn/(?:mw\d+|orj\d+|large|original|bmiddle|thumbnail|crop[^/]*)/(.+)$", value, re.I)
    if m:
        return "https://ww1.sinaimg.cn/large/" + m.group(1)
    for host in ("wx1", "wx2", "wx3", "wx4", "tvax1", "tvax2", "tva1"):
        value = value.replace(host + ".sinaimg.cn", "ww1.sinaimg.cn")
    return value


def weibo_preview_image_url(value):
    image = weibo_image_url(value)
    return image.replace("/large/", "/orj480/") if image else ""


def weibo_pic_id(pic, fallback_id):
    candidates = [pic.get("pid"), pic.get("pic_id"), pic.get("picId"), pic.get("mblogpicid"), pic.get("id"), fallback_id] if isinstance(pic, dict) else [fallback_id]
    for v in candidates:
        v = str(v or "").strip()
        if re.match(r"^[0-9a-z]{16,}(?:\.(?:jpg|jpeg|png|webp|gif))?$", v, re.I):
            return v
    return ""


def weibo_pic_image_url(pic, fallback_id):
    pic = pic or {}
    image = first_url([
        get_path(pic, "largest.url"), get_path(pic, "original.url"), get_path(pic, "large.url"),
        get_path(pic, "bmiddle.url"), get_path(pic, "mw2000.url"), get_path(pic, "geo.url"),
        pic.get("largest"), pic.get("original"), pic.get("large"), pic.get("bmiddle"), pic.get("url"),
    ])
    if image:
        return weibo_image_url(image)
    return weibo_image_url(weibo_pic_id(pic, fallback_id))


def weibo_media_headers():
    return {
        "Referer": "https://weibo.com/",
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.0 Mobile/15E148 Safari/604.1",
    }


def weibo_live_photo_url(value):
    value = str(value or "").replace("&amp;", "&").replace("//", "https://", 1).strip()
    if not value:
        return ""

    def wrap(url):
        url = str(url or "").replace("http://", "https://", 1)
        return "https://video.weibo.com/media/play?livephoto=" + urllib.parse.quote(url) if url else ""

    try:
        parsed = urllib.parse.urlsplit(value)
        query = dict(urllib.parse.parse_qsl(parsed.query))
        live = query.get("livephoto") or ""
        if live:
            return wrap(live)
    except Exception:
        pass
    return wrap(value) if re.match(r"^https?://", value) and re.search(r"\.(?:mov|mp4)(?:\?|$)", value, re.I) else ""


def parse_weibo_video_id(video_id):
    api = "https://h5.video.weibo.com/api/component?page=/show/" + urllib.parse.quote(video_id)
    payload = fetch_web_json(api, {
        "method": "POST",
        "headers": {
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json,text/plain,*/*",
            "Referer": "https://h5.video.weibo.com/show/" + video_id,
        },
        "body": "data=" + urllib.parse.quote(json.dumps({"Component_Play_Playinfo": {"oid": video_id}})),
    })
    data = get_path(payload["data"], "data.Component_Play_Playinfo") or get_path(payload["data"], "Component_Play_Playinfo")
    if not data:
        raise ParseError("微博视频接口未返回播放信息")
    video = ""
    urls = data.get("urls")
    if isinstance(urls, dict):
        for key in ("高清 1080P", "高清 720P", "标清 480P", "流畅 360P"):
            if urls.get(key):
                video = urls[key]
                break
        if not video:
            keys = list(urls.keys())
            if keys:
                video = urls[keys[0]]
    video = str(video or "").replace("//", "https://", 1).replace("http://", "https://", 1)
    if not video:
        raise ParseError("微博视频接口没有可保存地址")
    return result("微博", "video", "https://video.weibo.com/show?fid=" + video_id,
                  strip_html(data.get("title") or "微博视频"), video,
                  str(data.get("cover_image") or "").replace("//", "https://", 1).replace("http://", "https://", 1),
                  [], str(data.get("author") or ""), str(data.get("avatar") or "").replace("//", "https://", 1),
                  "weibo:video:" + video_id)


def parse_weibo_status(data, source_url):
    title = strip_html(data.get("text") or data.get("text_raw") or "微博内容") or "微博内容"
    author = str(get_path(data, "user.screen_name") or "")
    avatar = weibo_image_url(get_path(data, "user.avatar_large") or get_path(data, "user.profile_image_url") or "")
    media_info = get_path(data, "page_info.media_info") or {}
    video = first_non_empty(
        media_info.get("stream_url_hd"), media_info.get("stream_url"),
        media_info.get("mp4_1080p_mp4"), media_info.get("mp4_720p_mp4"),
        media_info.get("mp4_hd_url"), media_info.get("mp4_sd_url"),
    ).replace("http://", "https://", 1)
    page_url = str(get_path(data, "page_info.page_url") or get_path(data, "page_info.media_info.video_url") or "")
    if not video and re.search(r"video\.weibo\.com/show\?fid=", page_url):
        video = page_url
    items = []
    pic_infos = data.get("pic_infos")
    if isinstance(pic_infos, dict):
        for key, pic in pic_infos.items():
            pic = pic or {}
            image = weibo_pic_image_url(pic, key)
            live = weibo_live_photo_url(pic.get("videoSrc") or pic.get("video_src") or get_path(data, "live_photo.%d" % len(items)))
            if image:
                items.append({"url": weibo_image_url(image), "previewUrl": weibo_preview_image_url(image),
                              "livePhotoUrl": live, "requestHeaders": weibo_media_headers()})
    elif isinstance(data.get("pics"), list):
        for index, pic in enumerate(data["pics"]):
            image = weibo_pic_image_url(pic, "")
            live = weibo_live_photo_url(pic.get("videoSrc") or pic.get("video_src") or get_path(data, "live_photo.%d" % index))
            if not live:
                raw_id = str(image or "").split("/")[-1]
                raw_id = re.sub(r"\.(?:jpg|jpeg|png|webp).*$", "", raw_id, flags=re.I)
                live = weibo_live_photo_url(get_path(data, "live_photo_video_data.%s.video" % raw_id)
                                            or get_path(data, "live_photo_video_data.%s.url" % raw_id))
            if image:
                items.append({"url": weibo_image_url(image), "previewUrl": weibo_preview_image_url(image),
                              "livePhotoUrl": live, "requestHeaders": weibo_media_headers()})
    cover = items[0]["url"] if items else weibo_image_url(get_path(data, "page_info.page_pic.url") or get_path(data, "page_info.page_pic") or "")
    if video:
        return result("微博", "video", source_url, title, video, cover, [], author, avatar, "weibo:status:video")
    if items:
        has_live = any(i.get("livePhotoUrl") for i in items)
        return result("微博", "live" if has_live else "gallery", source_url, title, "", cover, items, author, avatar,
                      "weibo:status:" + ("live" if has_live else "gallery") + ":%d%s" % (
                          len(items), (":motion=%d" % sum(1 for i in items if i.get("livePhotoUrl"))) if has_live else ""))
    raise ParseError("微博内容已识别，但没有返回可保存媒体")


def parse_weibo(url):
    fid = ""
    try:
        fid = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query)).get("fid") or ""
    except Exception:
        fid = ""
    if re.search(r"video\.weibo\.com/show", url) and fid:
        return parse_weibo_video_id(fid)
    post_id = weibo_post_id(url)
    if not post_id:
        raise ParseError("未识别到微博作品 ID")
    api = "https://m.weibo.cn/statuses/show?id=" + urllib.parse.quote(post_id)
    payload = fetch_json(api, {
        "referer": "https://m.weibo.cn/",
        "headers": {"Accept": "application/json,text/plain,*/*", "X-Requested-With": "XMLHttpRequest", "Referer": "https://m.weibo.cn/"},
    })
    data = payload["data"].get("data") if isinstance(payload["data"], dict) and "data" in payload["data"] else payload["data"]
    if not isinstance(data, dict):
        raise ParseError("微博接口未返回作品详情")
    parsed = parse_weibo_status(data, payload.get("url") or url)
    if parsed["mediaType"] == "video" and re.search(r"video\.weibo\.com/show\?fid=", parsed["videoUrl"]):
        m = re.search(r"fid=([^&\s]+)", parsed["videoUrl"])
        if m:
            return parse_weibo_video_id(m.group(1))
    return parsed


# ---------------------------------------------------------------------------
# X (Twitter)
# ---------------------------------------------------------------------------

def x_media_headers(source_url):
    return {"Referer": source_url or "https://x.com/", "Accept": "*/*"}


def x_status_id(url):
    m = re.search(r"/status(?:es)?/(\d{8,})(?:[/?#]|$)", str(url or ""), re.I)
    return m.group(1) if m else ""


def x_canonical_status_url(url, status_id=""):
    status_id = status_id or x_status_id(url)
    if not status_id:
        return normalize_known_share_url(url)
    return "https://x.com/i/status/" + status_id


def x_clean_url(value):
    return re.sub(r"[\\\",}<\]\s]+$", "", unescape_page_value(str(value or ""))
        .replace("\\u002F", "/").replace("\\u0026", "&").replace("\\/", "/")
        .replace("&amp;", "&").replace("&quot;", '"').replace("http://", "https://", 1))


def x_meta_content(html, names):
    html = str(html or "")
    for name in names:
        escaped = re.escape(name)
        m = re.search(r"<meta[^>]+(?:property|name)=[\"']" + escaped + r"[\"'][^>]+content=[\"']([^\"']*)[\"'][^>]*>", html, re.I)
        if m and m.group(1):
            return strip_html(m.group(1))
        m = re.search(r"<meta[^>]+content=[\"']([^\"']*)[\"'][^>]+(?:property|name)=[\"']" + escaped + r"[\"']", html, re.I)
        if m and m.group(1):
            return strip_html(m.group(1))
    return ""


def x_title_from_html(html):
    title = x_meta_content(html, ["og:title", "twitter:title"])
    if not title:
        m = re.search(r"<title[^>]*>([\s\S]*?)</title>", html, re.I)
        title = strip_html(m.group(1)) if m else ""
    title = re.sub(r"\s*/\s*X\s*$", "", str(title or "X 内容"), flags=re.I)
    title = re.sub(r"\s+on\s+X\s*:\s*$", "", title, flags=re.I)
    title = re.sub(r"^X\s+on\s+X:\s*", "", title, flags=re.I)
    return title.strip() or "X 内容"


def x_image_original_url(raw):
    url = x_clean_url(raw)
    if not re.match(r"^https?://pbs\.twimg\.com/(?:media|amplify_video_thumb|ext_tw_video_thumb|tweet_video_thumb)/", url, re.I):
        return ""
    m = re.match(r"^([^?#]+?\.(?:jpe?g|png|webp)):(?:orig|large|medium|small|thumb)([?#].*)?$", url, re.I)
    if m:
        return m.group(1) + "?name=large"
    if "?" in url:
        url = re.sub(r"([?&])name=[^&]*", r"\1name=large", url, flags=re.I)
        if not re.search(r"[?&]name=", url, re.I):
            url += "&name=large"
        return url
    path = url.split("#")[0]
    m = re.search(r"\.([a-z0-9]+)$", path, re.I)
    fmt = m.group(1).lower() if m else "jpg"
    return url + "?format=" + urllib.parse.quote(fmt) + "&name=large"


def x_video_score(url):
    score = 0
    m = re.search(r"/(\d{2,5})x(\d{2,5})/", url)
    if m:
        score += int(m.group(1)) * int(m.group(2))
    m = re.search(r"(?:bitrate|br)=(\d+)", url, re.I)
    if m:
        score += int(m.group(1)) * 100
    if "tweet_video" in url:
        score += 1
    return score


def x_collect_media(html):
    decoded = decode_html_json_text(unescape_page_value(html or ""))
    videos, images, seen_video, seen_image = [], [], set(), set()

    def add_video(raw):
        url = x_clean_url(raw)
        if not re.match(r"^https?://video\.twimg\.com/[^\"'<>\\\s]+\.mp4(?:[?#][^\"'<>\\\s]*)?$", url, re.I):
            return
        url = url.replace("&amp;", "&")
        if url in seen_video:
            return
        seen_video.add(url)
        videos.append(url)

    def add_image(raw):
        url = x_image_original_url(raw)
        if not url or url in seen_image:
            return
        seen_image.add(url)
        images.append(url)

    for m in re.finditer(r"https?:\\?/\\?/video\.twimg\.com/[^\"'<>\\\s]+?\.mp4(?:\?[^\"'<>\\\s]*)?", decoded, re.I):
        add_video(m.group(0))
    for m in re.finditer(r"https?:\\?/\\?/pbs\.twimg\.com/(?:media|amplify_video_thumb|ext_tw_video_thumb|tweet_video_thumb)/[^\"'<>\\\s]+", decoded, re.I):
        add_image(m.group(0))
    relay_video_patterns = [
        r'content_type\s*:\s*"video/mp4"[\s\S]{0,360}?url\s*:\s*"([^"]+?\.mp4(?:\?[^"]*)?)"',
        r'url\s*:\s*"([^"]+?\.mp4(?:\?[^"]*)?)"[\s\S]{0,360}?content_type\s*:\s*"video/mp4"',
    ]
    for pat in relay_video_patterns:
        for m in re.finditer(pat, decoded, re.I):
            add_video(m.group(1))
    for m in re.finditer(r'media_url_https\s*:\s*"([^"]+?pbs\.twimg\.com/(?:media|amplify_video_thumb|ext_tw_video_thumb|tweet_video_thumb)/[^"]+)"', decoded, re.I):
        add_image(m.group(1))
    videos.sort(key=x_video_score, reverse=True)
    return {"videos": videos, "images": images}


def x_fetch_syndication(status_id):
    api = "https://cdn.syndication.twimg.com/tweet-result?id=%s&lang=en&token=%s" % (urllib.parse.quote(status_id), status_id)
    res = fetch_text(api, {"referer": "https://platform.twitter.com/", "headers": {"Accept": "application/json,text/plain,*/*"}})
    try:
        return json.loads(res["text"])
    except Exception:
        return None


def x_syndication_photo_url(raw_url):
    clean = str(raw_url or "").split("?")[0]
    clean = re.sub(r":(?:large|medium|small|thumb|orig)$", "", clean, flags=re.I)
    if not re.match(r"^https://pbs\.twimg\.com/", clean, re.I):
        return ""
    dot = clean.rfind(".")
    ext = clean[dot + 1:].lower() if dot > 0 else "jpg"
    if ext not in ("jpg", "jpeg", "png", "webp"):
        ext = "jpg"
    return clean[:dot if dot > 0 else len(clean)] + "?format=" + ("jpg" if ext == "jpeg" else ext) + "&name=orig"


def x_syndication_video_variants(detail):
    variants = ((detail or {}).get("video_info") or {}).get("variants") or []
    return sorted(
        [v for v in variants
         if isinstance(v, dict)
         and str(v.get("content_type") or "").lower() == "video/mp4"
         and re.match(r"^https://video\.twimg\.com/", str(v.get("url") or ""), re.I)],
        key=lambda v: -(int(v.get("bitrate") or 0)),
    )


def x_syndication_media(payload):
    details = (payload or {}).get("mediaDetails") or []
    photos, videos = [], []
    for detail in details:
        if not isinstance(detail, dict):
            continue
        type_ = str(detail.get("type") or "").lower()
        if type_ in ("video", "animated_gif"):
            best = (x_syndication_video_variants(detail) or [{}])[0]
            if best.get("url"):
                videos.append({"url": best["url"], "bitrate": int(best.get("bitrate") or 0),
                               "animated": type_ == "animated_gif",
                               "thumb": x_syndication_photo_url(detail.get("media_url_https"))})
        elif type_ == "photo":
            photo = x_syndication_photo_url(detail.get("media_url_https"))
            if photo:
                photos.append(photo)
    return {"photos": photos, "videos": videos}


def x_tombstone_message(payload):
    try:
        raw = str((payload.get("tombstone") or {}).get("text") or {}).get("text") or ""
    except Exception:
        raw = ""
    if re.search(r"suspended account", raw, re.I):
        return "这条 X 帖子的发布账号已被封禁"
    if re.search(r"deleted by the Post author|deleted by the Tweet author", raw, re.I):
        return "作者已删除这条 X 帖子"
    if re.search(r"no longer exists", raw, re.I):
        return "这条 X 帖子的发布账号已注销"
    if re.search(r"age|sensitive|restricted", raw, re.I):
        return "这条 X 帖子受年龄或敏感内容限制，未登录拿不到"
    return ""


def x_network_error(error):
    return bool(re.search(r"请求失败|failed to fetch|network|timeout|timed out|超时|could not resolve|ssl|证书|连接",
                          str(getattr(error, "message", "") or error or ""), re.I))


def x_classified_error(reason):
    mapping = {
        "login_required": "X 这条内容需要登录后才能看，无法获取（login_required）",
        "network_unreachable": "当前网络连不上 X。请确认这台机器现在能连上 X，再回来解析（network_unreachable）",
        "public_source_changed": "X 页面结构变了，没找到可保存的媒体（public_source_changed）",
        "no_video": "这条 X 帖子里没有可保存的视频或图片（no_video）",
        "deleted_private": "这条 X 帖子已删除或不公开（deleted_private）",
    }
    if reason == "x_unreadable":
        err = ParseError("没能读取这条 X 帖子。最常见的原因是当前网络连不上 X（x_unreadable）", "x_unreadable")
    else:
        err = ParseError(mapping.get(reason, "没能读取这条 X 帖子（%s）" % reason), "x_" + reason)
    return err


def parse_x(url):
    status_id = x_status_id(url)
    if not status_id:
        try:
            source_host = urllib.parse.urlsplit(url).hostname.lower()
        except Exception:
            source_host = ""
        if source_host == "t.co":
            short_page = None
            try:
                short_page = fetch_text(url, {"referer": "https://x.com/", "headers": {
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8", "Referer": "https://x.com/"}})
            except Exception as short_error:
                if x_network_error(short_error):
                    raise x_classified_error("network_unreachable")
                raise
            resolved = x_short_status_url(url, short_page)
            status_id = x_status_id(resolved)
            if status_id:
                url = resolved
    if not status_id:
        raise ParseError("未识别到 X 帖子 ID")

    syndication = None
    try:
        syndication = x_fetch_syndication(status_id)
    except Exception as syndication_error:
        if x_network_error(syndication_error):
            raise x_classified_error("network_unreachable")
    if syndication and str(syndication.get("__typename") or "") == "TweetTombstone":
        tomb = x_tombstone_message(syndication)
        if tomb:
            raise ParseError(tomb + "（deleted_private）", "x_deleted_private")
        raise x_classified_error("deleted_private")
    if syndication and str(syndication.get("__typename") or "") == "Tweet":
        syn = x_syndication_media(syndication)
        syn_user = str((syndication.get("user") or {}).get("screen_name") or "")
        syn_title = re.sub(r"https://t\.co/\S+", "", str(syndication.get("text") or ""), flags=re.I).strip() or "X 内容"
        syn_avatar = str((syndication.get("user") or {}).get("profile_image_url_https") or "")
        syn_source = x_canonical_status_url(url, status_id)
        syn_headers = x_media_headers(syn_source)
        if syn["videos"]:
            syn_candidates = [{"url": e["url"], "sourceField": "x:syndication:%s:%d" % ("animated-gif" if e["animated"] else "video", i),
                               "primary": i == 0, "requestHeaders": syn_headers} for i, e in enumerate(syn["videos"])]
            return result("X", "video", syn_source, syn_title, syn_candidates[0]["url"],
                          syn["photos"][0] if syn["photos"] else syn["videos"][0]["thumb"], [], syn_user.lstrip("@"), syn_avatar,
                          "x:syndication:video:%s:variants=%d:bitrate=%d" % (status_id, len(syn["videos"]), syn["videos"][0]["bitrate"]),
                          syn_headers, syn_candidates)
        if syn["photos"]:
            return result("X", "gallery", syn_source, syn_title, "", syn["photos"][0],
                          [{"url": p, "previewUrl": p, "livePhotoUrl": "", "requestHeaders": syn_headers} for p in syn["photos"]],
                          syn_user.lstrip("@"), syn_avatar, "x:syndication:gallery:%s:count=%d" % (status_id, len(syn["photos"])), syn_headers)
        quoted = syndication.get("quoted_tweet")
        quoted_media = x_syndication_media(quoted or {})
        if quoted and (quoted_media["videos"] or quoted_media["photos"]):
            quoted_id = str((quoted or {}).get("id_str") or "")
            quoted_user = str(((quoted or {}).get("user") or {}).get("screen_name") or "")
            quoted_link = "https://x.com/%s/status/%s" % (quoted_user or "i", quoted_id) if quoted_id else ""
            err = ParseError("这条 X 帖子本身只有文字，你看到的内容在它引用的那条里。" + ("请改用这条链接：" + quoted_link if quoted_link else "请复制被引用那条帖子的链接再试") + "（quoted_media）", "x_quoted_media")
            raise err
        raise x_classified_error("no_video")

    request_url = x_canonical_status_url(url, status_id)
    try:
        page = fetch_text(request_url, {"referer": "https://x.com/", "headers": {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8", "Referer": "https://x.com/"}})
    except Exception as error:
        if re.search(r"\b404\b|not found|不存在|已删除", str(getattr(error, "message", "") or error), re.I):
            raise x_classified_error("deleted_private")
        if x_network_error(error):
            raise x_classified_error("network_unreachable")
        raise
    page_text = str(page.get("text") or "")
    unavailable = x_unavailable_reason(page_text)
    if unavailable:
        raise x_classified_error(unavailable)
    media = x_collect_media(page_text)
    source_url = page.get("url") or url
    headers = x_media_headers(source_url)
    title = x_title_from_html(page_text)
    author = x_meta_content(page_text, ["profile:username", "twitter:site"]) or ""
    avatar = x_meta_content(page_text, ["twitter:image:src"]) or ""
    cover = media["images"][0] if media["images"] else x_meta_content(page_text, ["og:image", "twitter:image"]) or ""
    if media["videos"]:
        candidates = [{"url": u, "sourceField": "x:%s:%d" % ("animated-gif" if "tweet_video" in u else "video", i),
                       "primary": i == 0, "requestHeaders": headers} for i, u in enumerate(media["videos"])]
        return result("X", "video", source_url, title, candidates[0]["url"], cover, [], author.lstrip("@"), avatar,
                      "x:" + ("animated-gif-as-video:" if "tweet_video" in candidates[0]["url"] else "video:") + status_id,
                      headers, candidates)
    if media["images"]:
        return result("X", "gallery", source_url, title, "", media["images"][0],
                      [{"url": u, "previewUrl": u, "livePhotoUrl": "", "requestHeaders": headers} for u in media["images"][:20]],
                      author.lstrip("@"), avatar, "x:gallery:%s:images=%d" % (status_id, len(media["images"])), headers)
    if re.search(r"relayRecords|__NEXT_DATA__|og:url|twitter:card", page_text):
        raise x_classified_error("no_video")
    raise x_classified_error("public_source_changed")


def x_unavailable_reason(html):
    page_text = str(html or "")
    if re.search(r"Log in to X|Sign in to X|login_required|LoginForm|auth_token", page_text, re.I):
        return "login_required"
    if re.search(r"<title[^>]*>\s*Post Not Found - X \| 404 Error\s*</title>", page_text, re.I):
        return "deleted_private"
    if re.search(r"ErrorState_NotFound|errors/404-|page doesn(?:'|\\u0027)t exist", page_text, re.I):
        return "deleted_private"
    has_deleted = bool(re.search(r"could not be found or may have been deleted", page_text, re.I))
    has_not_found = bool(re.search(r"\bisNotFound\s*:\s*!0\b", page_text))
    has_null = bool(re.search(r"\bresult\s*:\s*null\b", page_text))
    return "deleted_private" if (has_deleted and (has_not_found or has_null)) else ""


def x_short_status_url(source_url, fetched_page):
    try:
        source_host = urllib.parse.urlsplit(source_url).hostname.lower()
    except Exception:
        source_host = ""
    if source_host != "t.co":
        return ""
    fetched_page = fetched_page or {}
    candidates = [str(fetched_page.get("url") or "")]
    page_text = unescape_page_value(str(fetched_page.get("text") or ""))
    for m in re.finditer(r"https?://(?:(?:www|mobile)\.)?(?:x|twitter)\.com/[^\"'<>\\\s]*?/status(?:es)?/\d{8,}(?:/[^\"'<>\\\s]*)?", page_text, re.I):
        candidates.append(m.group(0))
    for candidate in candidates:
        candidate = x_clean_url(candidate)
        try:
            host = urllib.parse.urlsplit(candidate).hostname.lower()
        except Exception:
            host = ""
        if not re.match(r"^(?:(?:www|mobile)\.)?(?:x|twitter)\.com$", host):
            continue
        if x_status_id(candidate):
            return candidate
    return ""


# ---------------------------------------------------------------------------
# 小米社区
# ---------------------------------------------------------------------------

def xiaomi_media_headers(source_url):
    return {
        "Referer": source_url or "https://web.vip.miui.com/",
        "User-Agent": "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Mobile Safari/537.36",
        "Accept": "*/*",
    }


def xiaomi_post_id(url):
    try:
        parsed = urllib.parse.urlsplit(url)
        query = dict(urllib.parse.parse_qsl(parsed.query))
        return query.get("postId") or query.get("id") or ""
    except Exception:
        pass
    m = re.search(r"(?:postId|id)=([0-9]+)", str(url or ""), re.I)
    return m.group(1) if m else ""


def xiaomi_image_url(item):
    if not item:
        return ""
    if isinstance(item, str):
        return re.sub(r"^http:", "https:", item) if re.match(r"^https?://", item, re.I) else ""
    return first_url(item.get("originUrl") or item.get("originalUrl") or item.get("largeUrl") or item.get("url") or item.get("imageUrl") or item.get("picUrl") or item)


def parse_xiaomi_community(url):
    page = fetch_text(url, {"referer": "https://web.vip.miui.com/", "headers": {"Accept": "text/html,application/xhtml+xml,application/json,text/plain,*/*"}})
    source_url = page.get("url") or url
    post_id = xiaomi_post_id(source_url) or xiaomi_post_id(url)
    if not post_id:
        m = re.search(r"postId[\"'=:\s]+([0-9]+)", page.get("text") or "", re.I)
        post_id = m.group(1) if m else ""
    if not post_id:
        raise ParseError("小米社区链接已识别，但没有找到帖子 ID")
    api = "https://api.vip.miui.com/api/community/post/detail?postId=" + urllib.parse.quote(post_id)
    payload = fetch_web_json(api, {"referer": source_url, "headers": {"Accept": "application/json,text/plain,*/*", "Referer": source_url}})
    data = payload["data"]
    entity = data.get("entity") if isinstance(data, dict) else None
    if not isinstance(entity, dict):
        entity = get_path(data, "data.entity") or (data.get("data") if isinstance(data, dict) else None)
    if not isinstance(entity, dict):
        raise ParseError("小米社区接口未返回作品详情")

    title = first_non_empty(entity.get("title"), entity.get("summary"), entity.get("textContent"), "小米社区内容")
    author_name = get_path(entity, "author.name") or ""
    author_avatar = get_path(entity, "author.icon") or ""
    headers = xiaomi_media_headers(source_url)
    videos = entity.get("videoInfo") if isinstance(entity.get("videoInfo"), list) else []
    for video in videos:
        video = video or {}
        video_url = first_url(video.get("url") or video.get("playUrl") or video.get("videoUrl") or video.get("downloadUrl") or video)
        if not video_url or not re.search(r"\.(mp4|m4v|mov|webm)(\?|$)", video_url, re.I):
            continue
        cover = first_url(video.get("cover") or video.get("defCoverUrl") or video.get("coverUrl") or entity.get("cover") or (collect_urls(entity, "image")[0] if collect_urls(entity, "image") else ""))
        return result("小米社区", "video", source_url, title, video_url, cover, [], author_name, author_avatar, "xiaomi:post:video:" + post_id,
                      headers, [{"url": video_url, "sourceField": "xiaomi:videoInfo.url", "primary": True, "requestHeaders": headers}])
    image_urls = []
    for item in (entity.get("picList") if isinstance(entity.get("picList"), list) else []):
        picked = xiaomi_image_url(item)
        if picked:
            image_urls.append(picked)
    if not image_urls:
        image_urls = collect_urls(entity.get("picList") or entity, "image")
    items = [{"url": i["url"], "previewUrl": i["previewUrl"] if i.get("previewUrl") else i["url"], "livePhotoUrl": "", "requestHeaders": headers}
             for i in normalize_images(image_urls, 40)]
    if items:
        return result("小米社区", "image", source_url, title, "", items[0]["url"], items, author_name, author_avatar, "xiaomi:post:gallery:" + post_id, headers)
    raise ParseError("小米社区作品已识别，但没有返回可保存的视频或图片")


# ---------------------------------------------------------------------------
# 公众号
# ---------------------------------------------------------------------------

def wechat_mp_media_headers(source_url, media_kind):
    return {
        "Referer": source_url or "https://mp.weixin.qq.com/",
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.50",
        "Accept": "*/*" if media_kind == "video" else "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
    }


def decode_wechat_mp_text(value):
    value = str(value or "")
    value = re.sub(r"\\x([0-9a-fA-F]{2})", lambda m: chr(int(m.group(1), 16)), value)
    value = value.replace("\\r", "").replace("\\n", "\n").replace("&nbsp;", " ")
    return strip_html(unescape_page_value(value))


def wechat_mp_picture_block(html):
    html = str(html or "")
    m = re.search(r"window\.picture_page_info_list\s*=\s*\[([\s\S]*?)\]\s*\.slice\s*\(\s*0\s*,\s*20\s*\)", html, re.I) \
        or re.search(r"window\.picture_page_info_list\s*=\s*\[([\s\S]*?)\]\s*;", html, re.I)
    return m.group(1) if m else ""


def slice_balanced_js_block(text, open_brace_index):
    depth = 0
    quote = ""
    escaped = False
    for i in range(open_brace_index, len(text)):
        ch = text[i]
        if quote:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == quote:
                quote = ""
            continue
        if ch in "'\"":
            quote = ch
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[open_brace_index:i + 1]
    return ""


def wechat_mp_live_photo_block(entry_text):
    entry_text = str(entry_text or "")
    m = re.search(r"(?:^|[,{\s])live_photo\s*:\s*\{", entry_text, re.I)
    if not m:
        return ""
    open_idx = entry_text.find("{", m.start())
    return slice_balanced_js_block(entry_text, open_idx) if open_idx >= 0 else ""


def is_wechat_mp_live_video_url(url):
    lower = str(url or "").lower()
    if not lower.startswith(("http://", "https://")):
        return False
    if re.search(r"\.(?:jpe?g|png|webp|gif|avif|svg)(?:[?#]|$)", lower):
        return False
    return bool(re.search(r"\.(?:mp4|mov|m4v|webm)(?:[?#]|$)", lower)
                or re.search(r"(?:mmbizmp4|mpvideo|vweixinf|finder\.video\.qq\.com|/video/)", lower))


def wechat_mp_video_urls_from_text(text):
    urls = []
    for m in re.finditer(r"https?://[^\"'\s<>\\]+", unescape_page_value(text)):
        urls.append(m.group(0))
    return [u.replace("http://", "https://", 1) for u in unique(urls) if is_wechat_mp_live_video_url(u)]


def wechat_mp_live_photo_url(entry_text):
    block = wechat_mp_live_photo_block(entry_text)
    if not block:
        return ""
    urls = unique(wechat_mp_video_urls_from_text(block) + collect_urls(block, "video"))
    urls = [u for u in urls if is_wechat_mp_live_video_url(u)]
    if urls:
        return urls[0].replace("http://", "https://", 1)
    return ""


def wechat_mp_title_from_html(html):
    title = x_meta_content(html, ["og:title", "twitter:title"])
    if title:
        return title
    m = re.search(r"window\.desc\s*=\s*\"([\s\S]*?)\"\.replace", str(html or ""), re.I)
    if m:
        title = re.sub(r"\s+", " ", decode_wechat_mp_text(m.group(1))).strip()
        if title:
            return title
    return "公众号图片"


def wechat_mp_author_from_html(html):
    m = re.search(r"window\.name\s*=\s*\"([\s\S]*?)\";", str(html or ""), re.I)
    return re.sub(r"\s+", " ", decode_wechat_mp_text(m.group(1))).strip() if m else ""


def wechat_mp_picture_items(html, source_url):
    block = wechat_mp_picture_block(html)
    if not block:
        return []
    image_headers = wechat_mp_media_headers(source_url, "image")
    video_headers = wechat_mp_media_headers(source_url, "video")
    items, seen = [], set()
    pattern = re.compile(r"\{\s*width:\s*'([^']*)'\s*\*\s*1\s*,\s*height:\s*'([^']*)'\s*\*\s*1\s*,\s*cdn_url:\s*'([^']*)'", re.I)
    matches = list(pattern.finditer(block))
    for i, m in enumerate(matches):
        image_url = unescape_page_value(m.group(3)).replace("http://", "https://", 1)
        if not re.match(r"^https?://(?:mmbiz|mmecoa)\.qpic\.cn/", image_url, re.I) or image_url in seen:
            continue
        seen.add(image_url)
        next_index = matches[i + 1].start() if i + 1 < len(matches) else len(block)
        entry_text = block[m.start():next_index]
        live_photo_url = wechat_mp_live_photo_url(entry_text)
        items.append({
            "url": image_url, "previewUrl": image_url, "livePhotoUrl": live_photo_url,
            "width": int(m.group(1)) if m.group(1).isdigit() else 0,
            "height": int(m.group(2)) if m.group(2).isdigit() else 0,
            "requestHeaders": video_headers if live_photo_url else image_headers,
        })
    return items


def wechat_mp_extract_param(html, source_url, names):
    text = unescape_page_value(str(html or "") + "\n" + str(source_url or ""))
    for name in names:
        re_ = re.compile(r"(?:[?&]|\b)%s\s*(?:=|:)\s*['\"]?([^'\"&\s,;#]+)" % re.escape(name), re.I)
        m = re_.search(text)
        if m and m.group(1):
            return m.group(1)
    return ""


def wechat_mp_video_info_from_html(html, source_url):
    return {
        "vid": wechat_mp_extract_param(html, source_url, ["vid", "hit_vid", "txvideo_vid"]),
        "biz": wechat_mp_extract_param(html, source_url, ["__biz", "biz", "data-biz"]),
        "mid": wechat_mp_extract_param(html, source_url, ["mid", "appmsgid"]),
        "idx": wechat_mp_extract_param(html, source_url, ["idx"]) or "1",
    }


def wechat_mp_video_api_url(info):
    if not info or not info.get("vid") or not info.get("biz") or not info.get("mid"):
        return ""
    return ("https://mp.weixin.qq.com/mp/videoplayer?action=get_mp_video_play_url&preview=0"
            "&__biz=%s&mid=%s&idx=%s&vid=%s&uin=&key=&pass_ticket=&wxtoken=&appmsg_token=&x5=0&f=json" % (
                urllib.parse.quote(info["biz"]), urllib.parse.quote(info["mid"]),
                urllib.parse.quote(info.get("idx") or "1"), urllib.parse.quote(info["vid"])))


def wechat_mp_video_urls_from_payload(payload):
    urls = []

    def visitor(value, path):
        if not isinstance(value, str):
            return
        key = ".".join(path).lower()
        if not value.lower().startswith(("http://", "https://")):
            return
        if not re.search(r"(?:url|play|video|mp4|src)", key) and not is_wechat_mp_live_video_url(value):
            return
        urls.append(value)

    walk(payload, visitor)
    return [u.replace("http://", "https://", 1) for u in unique(urls) if is_wechat_mp_live_video_url(u)]


def parse_wechat_mp_video(html, source_url):
    headers = wechat_mp_media_headers(source_url, "video")
    info = wechat_mp_video_info_from_html(html, source_url)
    direct_urls = wechat_mp_video_urls_from_text(html)
    video_url = direct_urls[0] if direct_urls else ""
    api_tried = False
    if not video_url:
        api_url = wechat_mp_video_api_url(info)
        if api_url:
            api_tried = True
            try:
                payload = fetch_json(api_url, {"referer": source_url or "https://mp.weixin.qq.com/", "headers": {"Accept": "application/json,text/plain,*/*"}})
                video_url = (wechat_mp_video_urls_from_payload(payload["data"]) or [""])[0]
            except Exception:
                pass
    if not video_url:
        if info.get("vid"):
            raise ParseError("公众号视频已识别，但公开接口没有返回可保存视频" if api_tried else "公众号视频已识别，但缺少公开下载参数")
        return None
    cover = x_meta_content(html, ["og:image", "twitter:image"]) or wechat_mp_extract_param(html, source_url, ["cdn_url"])
    return result("公众号", "video", source_url, wechat_mp_title_from_html(html), video_url,
                  str(cover or "").replace("http://", "https://", 1), [], wechat_mp_author_from_html(html), "",
                  "wechat-mp:video:%s:api=%s" % (info.get("vid") or "direct", "1" if api_tried else "0"),
                  headers, [{"url": video_url, "sourceField": "wechat-mp:video", "primary": True, "requestHeaders": headers}])


def parse_wechat_mp(url):
    page = fetch_text(url, {"headers": {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.50",
    }})
    source_url = page.get("url") or url
    html = page.get("text") or ""
    items = wechat_mp_picture_items(html, source_url)
    if not items:
        video_result = parse_wechat_mp_video(html, source_url)
        if video_result:
            return video_result
        if wechat_mp_picture_block(html):
            raise ParseError("公众号图片页已识别，但没有返回可保存图片")
        raise ParseError("公众号链接已识别，但不是可保存的图片页")
    headers = wechat_mp_media_headers(source_url, "image")
    has_live = any(i.get("livePhotoUrl") for i in items)
    return result("公众号", "live" if has_live else "gallery", source_url, wechat_mp_title_from_html(html), "",
                  items[0]["url"], items, wechat_mp_author_from_html(html), "",
                  "wechat-mp:picture-page:%s%d:motion=%d" % ("live:" if has_live else "", len(items), sum(1 for i in items if i.get("livePhotoUrl"))),
                  headers)


# ---------------------------------------------------------------------------
# 平台识别 / 链接提取（CLI 与服务端共用）
# ---------------------------------------------------------------------------

def extract_url(text):
    text = str(text or "")
    m = re.search(r"https?://[^\s\"'一-鿿<>]+", text, re.I)
    if not m:
        return ""
    return re.sub(r"[),;\]}]+$", "", m.group(0))


def detect_platform(url):
    u = url.lower()
    if re.search(r"(^|\.)douyin\.com|iesdouyin\.com|amemv\.com", u):
        return "抖音"
    if re.search(r"kuaishou\.com|gifshow\.com|chenzhongtech\.com", u):
        return "快手"
    if re.search(r"xiaohongshu\.com|xhslink\.(com|cn)", u):
        return "小红书"
    if re.search(r"pipix\.com|pipixia\.com", u):
        return "皮皮虾"
    if re.search(r"izuiyou\.com|xiaochuankeji\.cn", u):
        return "最右"
    if re.search(r"weibo\.com|weibo\.cn", u):
        return "微博"
    if re.search(r"(?:^|[./])(?:x|twitter)\.com(?:[/:]|$)|(?:^|[./])t\.co(?:[/:]|$)", u):
        return "X"
    if re.search(r"vip\.miui\.com|xiaomi\.cn|miui\.com", u):
        return "小米社区"
    if re.search(r"mp\.weixin\.qq\.com", u):
        return "公众号"
    if re.search(r"channels\.weixin|finder\.video\.qq\.com", u):
        return "视频号"
    if re.search(r"doubao\.com", u):
        return "豆包"
    return ""


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

_PARSERS = {
    "抖音": parse_douyin,
    "快手": parse_kuaishou,
    "小红书": parse_xhs,
    "皮皮虾": parse_pipixia,
    "最右": parse_zuiyou,
    "微博": parse_weibo,
    "X": parse_x,
    "小米社区": parse_xiaomi_community,
    "公众号": parse_wechat_mp,
}

SUPPORTED_PLATFORMS = sorted(_PARSERS.keys())
CLOUD_ONLY_PLATFORMS = ["视频号", "豆包"]


def parse(platform, url, options=None):
    options = options or {}
    if platform == "视频号":
        raise ParseError("视频号需要云端解析服务（需服务器保持微信登录态），本地解析不支持")
    fn = _PARSERS.get(platform)
    if not fn:
        raise ParseError("该平台暂无本地解析器")
    if platform == "小红书":
        return fn(url, bool(options.get("xhsSourceTranscode")))
    return fn(url)
