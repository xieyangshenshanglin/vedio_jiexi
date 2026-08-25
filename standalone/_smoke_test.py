# -*- coding: utf-8 -*-
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import parsers as P

fails = []

def check(name, got, expect):
    ok = (got == expect)
    print(("PASS " if ok else "FAIL ") + name + " => " + repr(got)[:120])
    if not ok:
        fails.append((name, got, expect))

# extract_assigned_json
html = '<script>window.__INITIAL_STATE__ = {"a":{"b":[1,2,3]},"s":"x"}; var y=1;</script>'
st = P.extract_assigned_json(html, "window.__INITIAL_STATE__")
check("extract_assigned_json", (st or {}).get("a", {}).get("b"), [1, 2, 3])

# brace-matching with nested braces and string braces
html2 = 'x = {"k":"{}","nested":{"deep":[{"v":"}"}]}} tail'
st2 = P.extract_assigned_json(html2, "x =")
check("extract nested", (st2 or {}).get("nested", {}).get("deep", [{}])[0].get("v"), "}")

# get_path
obj = {"a": {"b": [10, 20, 30]}, "video": {"play_addr": {"url_list": ["http://x/m.mp4"]}}}
check("get_path dict", P.get_path(obj, "a.b.1"), 20)
check("get_path missing", P.get_path(obj, "a.b.9"), None)
check("get_path video", P.get_path(obj, "video.play_addr.url_list.0"), "http://x/m.mp4")

# first_url
check("first_url str", P.first_url("http://a/b.mp4"), "https://a/b.mp4")
check("first_url list", P.first_url(["x", {"url": "http://c/d.jpg"}]), "https://c/d.jpg")

# unique / collect_urls（与原 JS 一致：unique 大小写敏感去重；video 模式按扩展名或 key 含 url_list 收集）
check("unique dedup case-sensitive", P.unique(["http://a/1.mp4", "HTTP://a/1.mp4", "notaurl"]), ["http://a/1.mp4", "HTTP://a/1.mp4"])
check("unique dedup same case", P.unique(["http://a/1.mp4", "http://a/1.mp4"]), ["http://a/1.mp4"])
node = {"video": {"play_addr": {"url_list": ["https://a.com/v.mp4", "https://a.com/c.jpg"]}}}
check("collect video by url_list key", P.collect_urls(node, "video"), ["https://a.com/v.mp4", "https://a.com/c.jpg"])
check("collect video by ext only", P.collect_urls({"x": "https://a.com/v.mp4"}, "video"), ["https://a.com/v.mp4"])
check("collect image", P.collect_urls(node, "image"), ["https://a.com/c.jpg"])

# douyin
check("douyin_aweme_id", P.douyin_aweme_id("https://v.douyin.com/xxx/ https://www.douyin.com/video/7301234567890"), "7301234567890")
check("is motion mp4", P.is_douyin_motion_video_url("https://www.douyin.com/aweme/v1/play/?video_id=x&ratio=1080p&line=0"), True)
check("is motion music", P.is_douyin_motion_video_url("https://x.com/music.mp3"), False)

# xhs
check("xhs note id", P.xhs_note_id_from_url("https://www.xiaohongshu.com/explore/abcdef1234567890abcdef12?xsec_token=abc"), "abcdef1234567890abcdef12")
check("xhs fileid bare", P.xhs_explicit_image_file_id("1040g0083123abcdefgh", False), "1040g0083123abcdefgh")
check("xhs fileid bucket", P.xhs_explicit_image_file_id("c/1040g0083123abcdefgh", True), "c/1040g0083123abcdefgh")
check("xhs fileid empty", P.xhs_explicit_image_file_id("https://x.com/a.jpg", True), "")
check("xhs video from key", P.xhs_original_video_from_key("stream/abcdef...mp4"), "https://sns-video-bd.xhscdn.com/stream/abcdef...mp4")
check("xhs still kind origin", P.xhs_still_source_kind("https://sns-na-i6.xhscdn.com/notes_pre_post/x", "originImage"), "origin")
check("xhs still kind display", P.xhs_still_source_kind("https://sns-webpic.xhscdn.com/x", "url"), "display")

# weibo
check("weibo image pid", P.weibo_image_url("abcdefghijklmnopqrstuvwx"), "https://ww1.sinaimg.cn/large/abcdefghijklmnopqrstuvwx.jpg")

# kuaishou maybe json
check("kuaishou maybe json", P.kuaishou_maybe_json('{"a":1}'), {"a": 1})
check("kuaishou maybe json str", P.kuaishou_maybe_json('notjson'), 'notjson')

# result
r = P.result("抖音", "video", "u", "t", "https://v.mp4", "https://c.jpg", [], "a", "av", "diag", {"Referer": "https://x/"})
check("result fields", (r["platform"], r["mediaType"], r["videoUrl"], r["requestHeaders"]), ("抖音", "video", "https://v.mp4", {"Referer": "https://x/"}))

# parse dispatch
try:
    P.parse("视频号", "https://channels.weixin.qq.com/x")
    check("视频号 raise", "no-error", "should-raise")
except P.ParseError as e:
    check("视频号 raise", "raised", "raised")
try:
    P.parse("某未知平台", "https://foo.com/x")
except P.ParseError:
    check("unknown platform", "raised", "raised")

print("")
if fails:
    print("FAILED %d checks" % len(fails))
    for n, g, e in fails:
        print("  -", n, "got", repr(g), "expect", repr(e))
    sys.exit(1)
print("ALL SMOKE CHECKS PASSED")
