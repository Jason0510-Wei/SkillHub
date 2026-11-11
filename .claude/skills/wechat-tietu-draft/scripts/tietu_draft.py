#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
公众号「贴图」草稿发布器 —— 只到草稿箱，绝不发表。

设计边界（2026-11-08 与用户确认的方案 B）：
  只调用官方接口：
    1) /cgi-bin/token                    获取 access_token（本地缓存 7200s）
    2) /cgi-bin/material/add_material   上传图片永久素材，拿 image_media_id
    3) /cgi-bin/draft/add               以 article_type=newspic 建贴图草稿
    4) /cgi-bin/draft/get              回读草稿（--verify / --update）
    5) /cgi-bin/draft/update           原地改已有草稿（--update，避免草稿箱堆重复）
  **不调用 /cgi-bin/freepublish/submit**（2025-07 起个人主体/未认证账号无权限，48001），
  也不做 Cookie / Playwright / 后台逆向。最后一步由人在草稿箱或订阅号助手手动点发表。

用户固定风格（2026-11-11 确认，v1.2.0 起为默认值，全部可用命令行覆盖）：
  · 首图固定为「汤姆和杰瑞」封面：assets/cover_tom_jerry.jpg
  · 标题：【分享】TikTok爆火🔥iOS 4K高清锁屏壁纸📱
  · 正文：喜欢这组壁纸的话，留个关注❤️
          后续持续更新更多TikTok热门🔥高清壁纸！
          （空一行）
          #4K高清壁纸 #iOS壁纸 #手机壁纸 #锁屏壁纸 #高清壁纸
  注意：用户的标签是「单 # 前缀」风格，不是微信官方话题的 #话题名# 双井号格式；
  默认按用户原样输出。需要官方话题格式时显式传 --topics 壁纸,锁屏。

素材来源：复用 tiktok-image-to-wallpaper 的归档
  <壁纸根>/<博主>/<帖子ID>-<YYYYMMDD>/1_A.<ext>, 1_B.<ext>, 2_A.<ext>, 2_B.<ext> ...
  A = 桌面展示图，B = 同一张壁纸的原图（v1.9.0 起上游按此命名）；
  旧命名 1_wallpaper.jpg, 2_wallpaper.jpg ... 也完全兼容。
  目录里的 cover.* 是上游保留的固定封面，v1.3.0 起自动忽略，不会混进正文图。
  支持显式多图 / 指定帖子目录 / 最新下载的一组 / 随机未投过的一组。

张数规则（v1.3.0，按实机验证修正版固化）：
  总张数 = 1（固定封面） + min(该文件夹素材数, 18)，恒 ≤ 19（官方上限 20，留 1 张余量）。
  素材数 6/16/18/24 → 总张数 7/17/19/19。--max-images 默认即 18，可省略；
  --max-images 0（取全部）同样受 18 封顶，不会顶到 20 张。
  首图必须是固定封面：封面文件缺失会硬失败（退出码 1），不再静默降级；
  dry-run 与正式跑共用同一套挑图逻辑并做首图自检，不会出现两处结果不一致。

用法：
  # 空跑：只看会挑哪些图、完整文案（不联网、不调接口）
  python tietu_draft.py --dry-run --latest

  # 按固定风格建一条草稿（默认带汤姆和杰瑞封面）
  python tietu_draft.py --latest

  # 把已有草稿改成新风格（原地更新，不新建）
  python tietu_draft.py --update <draft_media_id>

  # 回读校验中文/图片数
  python tietu_draft.py --verify <draft_media_id>

凭证（按优先级）：
  1) 环境变量 WECHAT_APPID / WECHAT_SECRET
  2) --env 指定的文件
  3) ~/.workbuddy/wechat.env
  4) <skill_dir>/wechat.env
  文件格式 KEY=VALUE，支持 # 注释与 export 前缀。AppSecret 绝不回显、绝不写入日志。

退出码：0 成功 / 2 已投过被跳过 / 1 失败。
"""
import argparse
import datetime
import hashlib
import json
import mimetypes
import os
import random
import re
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

API = "https://api.weixin.qq.com"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(SCRIPT_DIR)
STATE_DIR = os.path.join(SKILL_DIR, ".state")
TOKEN_CACHE = os.path.join(STATE_DIR, "token_cache.json")
USED_DB = os.path.join(STATE_DIR, "used_posts.json")
DEFAULT_BASE_DIR = os.environ.get("WECHAT_TIETU_WALLPAPER_DIR", r"E:\图片\壁纸")
DEFAULT_COVER = os.environ.get(
    "WECHAT_TIETU_COVER", os.path.join(SKILL_DIR, "assets", "cover_tom_jerry.jpg"))

# ---- 用户固定风格（可用 --title / --content / --tags / --meta / --cover 覆盖）----
DEFAULT_TITLE = "【分享】TikTok爆火🔥iOS 4K高清锁屏壁纸📱"
DEFAULT_CONTENT = ("喜欢这组壁纸的话，留个关注❤️\n"
                   "后续持续更新更多TikTok热门🔥高清壁纸！")
DEFAULT_TAGS = "#4K高清壁纸 #iOS壁纸 #手机壁纸 #锁屏壁纸 #高清壁纸"

ALLOWED_EXT = {".bmp", ".png", ".jpeg", ".jpg", ".gif"}
MAX_BYTES = 10 * 1024 * 1024          # 官方 add_material 图片上限 10M
MAX_IMAGES = 20                        # 官方 newspic 硬上限 20 张（含封面），仅作兜底断言
SAFE_MAX_IMAGES = 19                   # v1.3.0：默认封顶 19 张，给官方上限留 1 张余量
DEFAULT_MATERIAL_IMAGES = 18           # v1.3.0：素材默认弹性取最多 18 张
COVER_PREFIX = "cover."                # 上游保留的固定封面文件，不作为正文素材
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp", ".heic", ".avif"}
TITLE_BYTES_DEFAULT = 128             # 放宽：用户标题含 emoji/中英混排，共 56 字节
TITLE_CHARS_DEFAULT = 64
TITLE_BYTES_STRICT = 32               # --strict-title 恢复早期保守口径

ERR_HINTS = {
    40001: "AppSecret 不对或 token 类型用错，检查 wechat.env；注意不要把 authorizer_access_token 混进来。",
    40007: "media_id 不合法。贴图图片必须是 material/add_material 返回的永久 MediaID，"
           "不能用 media/uploadimg 的 URL，也不要把草稿 media_id 当素材 ID。",
    40125: "无效的图片素材 / 图片消息参数不合法，检查 image_info.image_list 与 article_type=newspic。",
    40164: "调用方公网 IP 不在白名单。到 developers.weixin.qq.com/platform → 我的业务与服务 → 公众号 → "
           "基础信息 → 开发密钥 → API IP 白名单，把下面查到的出口 IP 加进去（云函数/家庭宽带 IP 会漂移）。",
    45003: "标题超长。微信对贴图标题的字节口径文档与实测不一致；缩短标题，"
           "或去掉 --strict-title 使用放宽口径（默认 128 字节 / 64 字符）。",
    45004: "正文超长或为空，检查 --content / --meta。",
    45009: "接口调用频率超限，稍后重试，并确认 token 是集中缓存复用的。",
    45166: "content 不合法：纯文本里不要混入 HTML/JS，也不要用外部图片 URL。",
    48001: "该接口未授权。注意：本脚本不调用发表接口；若出现在草稿环节，说明账号连草稿箱能力都未开通，"
           "检查是否已完成微信认证、认证是否过期。",
    53404: "账号已被限制带货能力，删除商品信息后重试。",
    53405: "插入的商品信息有误，检查参数。",
    53406: "请先开通带货能力。",
    53503: "草稿未通过发布检查（仅在调用发表接口时会出现，本脚本不会触发）。",
}


class WeChatError(RuntimeError):
    pass


def log(msg):
    print(msg, flush=True)


# --------------------------------------------------------------------------- 凭证 / token

def parse_env_file(path):
    out = {}
    with open(path, encoding="utf-8-sig") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[7:].strip()
            if "=" not in line:
                continue
            k, v = line.split("=", 1)
            v = v.strip().strip('"').strip("'")
            out[k.strip()] = v
    return out


def load_credentials(args):
    appid = os.environ.get("WECHAT_APPID")
    secret = os.environ.get("WECHAT_SECRET")
    if appid and secret:
        return appid, secret, "环境变量"

    candidates = []
    if args.env:
        candidates.append(args.env)
    candidates.append(os.path.join(os.path.expanduser("~"), ".workbuddy", "wechat.env"))
    candidates.append(os.path.join(SKILL_DIR, "wechat.env"))
    for p in candidates:
        if p and os.path.isfile(p):
            cfg = parse_env_file(p)
            appid = cfg.get("WECHAT_APPID") or cfg.get("APPID")
            secret = cfg.get("WECHAT_SECRET") or cfg.get("APPSECRET") or cfg.get("SECRET")
            if appid and secret:
                return appid, secret, p
    raise WeChatError(
        "找不到公众号凭证。任选一种：\n"
        "  1) 设环境变量 WECHAT_APPID / WECHAT_SECRET\n"
        "  2) 创建 ~/.workbuddy/wechat.env，内容：\n"
        "     WECHAT_APPID=wxXXXXXXXX\n"
        "     WECHAT_SECRET=XXXXXXXX\n"
        "  3) --env <path> 指定文件\n"
        "AppSecret 在 developers.weixin.qq.com/platform → 开发密钥 里生成，只明文显示一次。"
    )


def _read_json_file(path, default):
    if not os.path.isfile(path):
        return default
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return default


def _write_json_file(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)


def get_token(appid, secret, force=False):
    cache = _read_json_file(TOKEN_CACHE, {})
    fp = hashlib.sha256((appid + secret).encode("utf-8")).hexdigest()[:16]
    if not force and cache.get("fp") == fp and cache.get("expires_at", 0) > time.time() + 300:
        return cache["access_token"]

    url = API + "/cgi-bin/token?" + urllib.parse.urlencode({
        "grant_type": "client_credential", "appid": appid, "secret": secret,
    })
    data = http_json(url, None, "获取 access_token")
    token = data.get("access_token")
    if not token:
        raise WeChatError("获取 access_token 失败：" + json.dumps(data, ensure_ascii=False))
    _write_json_file(TOKEN_CACHE, {
        "fp": fp,
        "access_token": token,
        "expires_at": time.time() + int(data.get("expires_in", 7200)),
    })
    return token


# --------------------------------------------------------------------------- HTTP

def _open(req, retries=2):
    last = None
    for i in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            last = exc
            if i < retries:
                time.sleep(1.5 * (i + 1))
    raise WeChatError("网络请求失败：%s" % last)


def _check(data, ctx):
    if not isinstance(data, dict):
        raise WeChatError("[%s] 返回不是 JSON：%r" % (ctx, data))
    code = data.get("errcode", 0)
    if code == 0:
        return data
    hint = ERR_HINTS.get(code, "")
    if code == 40164:
        m = re.search(r"invalid ip\s+([\d.]+)", data.get("errmsg", ""))
        if m:
            hint += ("\n  当前出口 IP = %s  <- 把这个 IPv4 加到白名单"
                     "（errmsg 里的 ::ffff: 前缀是同一地址的 IPv6 映射，不用另加）" % m.group(1))
        hint += "\n  自查命令：curl ifconfig.me  （或 curl https://api.ipify.org）"
    raise WeChatError("[%s] errcode=%s errmsg=%s\n  %s" % (
        ctx, code, data.get("errmsg", ""), hint or "查 微信开放文档 → 全局错误码"))


def http_json(url, payload, ctx):
    if payload is None:
        req = urllib.request.Request(url, method="GET")
    else:
        # 关键：ensure_ascii=False + 手工 UTF-8 序列化，否则微信会把中文存成 \uXXXX 乱码
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            url, data=body,
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
    return _check(_open(req), ctx)


def http_upload_image(url, filepath):
    """multipart/form-data，字段名 media。文件名强制 ASCII，避免微信解析中文名出错。"""
    boundary = "----TieTuBoundary" + uuid.uuid4().hex
    ext = os.path.splitext(filepath)[1].lower() or ".jpg"
    safe_name = "image_" + uuid.uuid4().hex[:8] + ext
    ctype = mimetypes.guess_type(safe_name)[0] or "application/octet-stream"
    with open(filepath, "rb") as fh:
        filedata = fh.read()
    body = b"".join([
        ("--%s\r\n" % boundary).encode("ascii"),
        ('Content-Disposition: form-data; name="media"; filename="%s"\r\n' % safe_name).encode("ascii"),
        ("Content-Type: %s\r\n\r\n" % ctype).encode("ascii"),
        filedata,
        ("\r\n--%s--\r\n" % boundary).encode("ascii"),
    ])
    req = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": "multipart/form-data; boundary=%s" % boundary},
        method="POST",
    )
    return _check(_open(req), "上传永久素材 " + os.path.basename(filepath))


def upload_image(token, path, tmpdir=None):
    """需要时先转换（>10MB / 非微信支持格式），再上传，返回永久 media_id。"""
    if tmpdir is None:
        tmpdir = tempfile.mkdtemp(prefix="tietu_one_")
    upload_path = prepare_image(path, tmpdir)
    url = API + "/cgi-bin/material/add_material?" + urllib.parse.urlencode({
        "access_token": token, "type": "image"})
    return http_upload_image(url, upload_path)["media_id"]


# --------------------------------------------------------------------------- 挑图

def natural_key(path):
    """1_A / 1_B / 2_A / 2_B 与旧版 1_wallpaper.jpg 都能正确按数字 + A/B 排序。"""
    name = os.path.basename(path)
    m = re.match(r"(\d+)", name)
    num = int(m.group(1)) if m else 10 ** 9
    pair = re.match(r"\d+[_-]([ABab])\.", name)
    suffix = pair.group(1).upper() if pair else ""
    return (num, suffix, name.lower())


def images_in(directory):
    """挑正文素材图。v1.3.0：cover.* 是上游保留的固定封面，必须排除。

    上游 download_tiktok.py 会保留 cover.* 原名且不参与 A/B 编号；
    旧版会把它也当素材挑走（排在最后），素材少时直接混进贴图正文图里。
    """
    out = []
    for name in os.listdir(directory):
        if name.lower().startswith(COVER_PREFIX):
            continue
        p = os.path.join(directory, name)
        if os.path.isfile(p) and os.path.splitext(name)[1].lower() in IMAGE_EXT:
            out.append(p)
    return sorted(out, key=natural_key)


def ignored_covers(directory):
    """返回被自动忽略的 cover.* 文件名，供日志显式交代（不再需要人工移走）。"""
    if not directory or not os.path.isdir(directory):
        return []
    return sorted(n for n in os.listdir(directory)
                  if n.lower().startswith(COVER_PREFIX)
                  and os.path.isfile(os.path.join(directory, n)))


def post_dirs(base_dir, author=None):
    if not os.path.isdir(base_dir):
        raise WeChatError("壁纸根目录不存在：%s" % base_dir)
    if author:
        roots = [os.path.join(base_dir, author)]
    else:
        roots = [os.path.join(base_dir, d) for d in os.listdir(base_dir)
                 if os.path.isdir(os.path.join(base_dir, d)) and not d.startswith(".")]
    out = []
    for root in roots:
        if not os.path.isdir(root):
            continue
        for d in os.listdir(root):
            p = os.path.join(root, d)
            if os.path.isdir(p) and not d.startswith(".") and images_in(p):
                out.append(p)
    return out


def load_used():
    return _read_json_file(USED_DB, {})


def pick_images(args, used):
    """返回 (图片列表, post_key, post_dir 或 None)。"""
    if args.images:
        paths = [os.path.abspath(p) for p in args.images]
        missing = [p for p in paths if not os.path.isfile(p)]
        if missing:
            raise WeChatError("图片不存在：\n  " + "\n  ".join(missing))
        key = "manual:" + hashlib.sha256(
            "|".join(os.path.normcase(p) for p in paths).encode("utf-8")).hexdigest()[:16]
        return paths, key, None

    base = os.path.abspath(args.base_dir or DEFAULT_BASE_DIR)
    if args.from_dir:
        d = os.path.abspath(args.from_dir)
        if not os.path.isdir(d):
            raise WeChatError("帖子目录不存在：%s" % d)
        candidates = [d]
    else:
        candidates = post_dirs(base, args.author)
        if not candidates:
            raise WeChatError("在 %s 下没找到含图片的帖子目录" % base)

    if args.from_dir:
        chosen = candidates[0]
    elif args.random_post:
        fresh = [p for p in candidates if os.path.normcase(os.path.abspath(p)) not in used]
        chosen = random.choice(fresh or candidates)
    else:  # --latest / 默认
        chosen = max(candidates, key=lambda p: os.path.getmtime(p))

    key = os.path.normcase(os.path.abspath(chosen))
    if key in used and not args.force and not args.dry_run:
        log("跳过：这组图已经投过草稿了（%s）" % used[key].get("time", ""))
        log("  草稿 media_id: %s" % used[key].get("draft_media_id", ""))
        log("  要重投请加 --force")
        return [], key, chosen

    paths = images_in(chosen)
    # v1.3.0 弹性张数：素材最多 18 张；--max-images 0（取全部）也受同一上限保护，
    # 不会像旧版那样顶到官方 20 张。总张数在 compose_images() 加封面后再按 19 截断。
    n = args.max_images or DEFAULT_MATERIAL_IMAGES
    if n < 0:
        raise WeChatError("--max-images 不能为负数（0 = 全部，但仍受 %d 张封顶）"
                          % DEFAULT_MATERIAL_IMAGES)
    limit = min(n, DEFAULT_MATERIAL_IMAGES, SAFE_MAX_IMAGES - 1)
    return paths[:limit], key, chosen


def compose_images(args, used, cover):
    """挑素材 → 去掉重复封面 → 插入固定封面 → 19 张封顶 → 首图自检。

    v1.3.0：dry-run 与正式跑共用本函数，杜绝两处挑图结果不一致；
    封面在第一张是硬约束，自检不过直接失败，不静默降级。
    """
    images, post_key, post_dir = pick_images(args, used)
    if not images:                      # 已投过被跳过，或目录里确实没有素材
        return [], post_key, post_dir
    if cover:
        nc = os.path.normcase(os.path.abspath(cover))
        images = [p for p in images
                  if os.path.normcase(os.path.abspath(p)) != nc]
        images = [cover] + images
    images = images[:SAFE_MAX_IMAGES]
    if len(images) > MAX_IMAGES:
        raise WeChatError("图片 %d 张，超过微信 newspic 的 %d 张硬上限"
                          % (len(images), MAX_IMAGES))
    if cover and (not images or
                  os.path.normcase(os.path.abspath(images[0])) !=
                  os.path.normcase(os.path.abspath(cover))):
        raise WeChatError("首图自检失败：固定封面没有排在第一张，已中止（不会建草稿）。")
    return images, post_key, post_dir


def prepare_image(path, tmpdir):
    """返回可上传的路径。超过 10M / 非微信支持格式时，用 Pillow 转成 JPEG（不改原图）。"""
    ext = os.path.splitext(path)[1].lower()
    size = os.path.getsize(path)
    if ext in ALLOWED_EXT and size <= MAX_BYTES:
        return path
    try:
        from PIL import Image
    except ImportError:
        raise WeChatError(
            "%s 需要转换才能上传（格式 %s，%.1f MB，微信仅支持 bmp/png/jpeg/jpg/gif 且 ≤10MB）。\n"
            "  请安装 Pillow：pip install Pillow" % (path, ext, size / 1024 / 1024))
    img = Image.open(path)
    if img.mode in ("RGBA", "LA", "P"):
        rgba = img.convert("RGBA")
        canvas = Image.new("RGB", rgba.size, (255, 255, 255))
        canvas.paste(rgba, mask=rgba.split()[-1])
        img = canvas
    else:
        img = img.convert("RGB")
    out = os.path.join(tmpdir, hashlib.sha256(os.path.abspath(path).encode("utf-8")).hexdigest()[:12] + ".jpg")
    quality = 92
    while True:
        img.save(out, "JPEG", quality=quality, optimize=True)
        if os.path.getsize(out) <= MAX_BYTES or quality <= 60:
            break
        quality -= 8
    if os.path.getsize(out) > MAX_BYTES:  # 还超就按比例缩
        while os.path.getsize(out) > MAX_BYTES and img.width > 800:
            img = img.resize((int(img.width * 0.85), int(img.height * 0.85)), Image.LANCZOS)
            img.save(out, "JPEG", quality=82, optimize=True)
    if os.path.getsize(out) > MAX_BYTES:
        raise WeChatError("压缩后仍超过 10MB，请手动处理：%s" % path)
    log("  转换 %s → JPEG %.1f MB（原图未改动）" % (os.path.basename(path), os.path.getsize(out) / 1024 / 1024))
    return out


# --------------------------------------------------------------------------- 文案

def resolve_meta(args):
    """用户固定风格为默认值；命令行 / --meta 显式给的值优先。"""
    title, content, tags, topics = args.title, args.content, args.tags, args.topics
    if args.meta:
        with open(args.meta, encoding="utf-8-sig") as fh:
            m = json.load(fh)
        if title is None:
            title = m.get("title")
        if content is None:
            content = m.get("content")
        if tags is None:
            tags = m.get("tags")
        if topics is None:
            t = m.get("topics", "")
            if isinstance(t, (list, tuple)):
                t = ",".join(str(x) for x in t)
            topics = t

    title = DEFAULT_TITLE if title is None else title
    content = DEFAULT_CONTENT if content is None else content
    # 命令行里 \n 常以字面两字符传入，统一还原为真实换行
    content = content.replace("\\n", "\n")

    if args.no_tags:
        tag_line = ""
    elif topics:
        # 显式 --topics：转成微信官方话题格式 #话题名#
        tag_line = " ".join("#%s#" % t.strip().lstrip("#").rstrip("#")
                            for t in re.split(r"[,，\s]+", topics) if t.strip())
    else:
        # 默认：用户原样标签行（单 # 前缀，小红书/微博风格）
        tag_line = DEFAULT_TAGS if tags is None else tags

    tag_line = tag_line.strip()
    if tag_line and tag_line not in content:
        content = content.rstrip() + "\n\n" + tag_line
    return title.strip(), content.strip()


def validate_meta(title, content, strict=False):
    if not title:
        raise WeChatError("标题不能为空（--title 或 --meta 里的 title）")
    if not content:
        raise WeChatError("正文不能为空（--content 或 --meta 里的 content）")
    tbytes = len(title.encode("utf-8"))
    if strict:
        if tbytes > TITLE_BYTES_STRICT:
            raise WeChatError(
                "标题 %d 字节，超过 --strict-title 的 %d 字节上限。去掉该参数即用放宽口径。"
                % (tbytes, TITLE_BYTES_STRICT))
    elif tbytes > TITLE_BYTES_DEFAULT or len(title) > TITLE_CHARS_DEFAULT:
        raise WeChatError(
            "标题 %d 字节 / %d 字符，超过 %d 字节 / %d 字符上限。"
            % (tbytes, len(title), TITLE_BYTES_DEFAULT, TITLE_CHARS_DEFAULT))
    if len(content) > 20000:
        raise WeChatError("正文超过 2 万字符")
    return tbytes


# --------------------------------------------------------------------------- 草稿

def cover_path(args):
    """v1.3.0：封面缺失改为硬失败。

    旧版只打印一行提示就静默不带封面、退出码仍是 0，首图会悄悄变成 1_A.jpg，
    直接破坏「第 1 张必须是汤姆和杰瑞封面」的需求。
    """
    if args.no_cover:
        return None
    p = os.path.abspath(args.cover or DEFAULT_COVER)
    if not os.path.isfile(p):
        raise WeChatError(
            "固定封面文件不存在：%s\n"
            "  首图必须是汤姆和杰瑞固定封面，已中止（不会静默降级成不带封面）。\n"
            "  修复：把 assets/cover_tom_jerry.jpg 一起拷到新机器，或用 --cover <path> 指定；\n"
            "  确实不要封面时显式加 --no-cover。" % p)
    return p


def build_article(title, content, media_ids, args):
    article = {
        "article_type": "newspic",
        "title": title,
        "content": content,
        "need_open_comment": 0 if args.no_comment else 1,
        "only_fans_can_comment": 1 if args.fans_only_comment else 0,
        "image_info": {"image_list": [{"image_media_id": m} for m in media_ids]},
    }
    if args.square_crop:
        article["cover_info"] = {"crop_percent_list": [{
            "ratio": "1_1", "x1": "0.166454", "y1": "0",
            "x2": "0.833545", "y2": "1",
        }]}
    return article


def draft_get(token, media_id):
    url = API + "/cgi-bin/draft/get?" + urllib.parse.urlencode({"access_token": token})
    return http_json(url, {"media_id": media_id}, "读取草稿详情")


# --------------------------------------------------------------------------- 参数

def build_parser():
    p = argparse.ArgumentParser(
        description="公众号贴图草稿发布器（只到草稿箱，不发表）",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    src = p.add_argument_group("素材来源（四选一）")
    src.add_argument("--images", nargs="+", metavar="PATH", help="显式给 1~20 张图片")
    src.add_argument("--from-dir", metavar="DIR", help="指定某个帖子目录")
    src.add_argument("--latest", action="store_true", help="取最近下载的一组（默认）")
    src.add_argument("--random-post", action="store_true", help="随机挑一组未投过的")
    src.add_argument("--base-dir", metavar="DIR", help="壁纸根目录，默认 %s" % DEFAULT_BASE_DIR)
    src.add_argument("--author", metavar="NAME", help="只在该博主目录下找，如 vexaro.4k")
    src.add_argument("--max-images", type=int, default=DEFAULT_MATERIAL_IMAGES, metavar="N",
                     help="素材最多取几张，默认 %d（弹性：实际取 min(素材数,N)）；"
                          "固定封面额外占 1 张，总数恒 ≤ %d；0 = 全部但仍受 %d 封顶"
                          % (DEFAULT_MATERIAL_IMAGES, SAFE_MAX_IMAGES, DEFAULT_MATERIAL_IMAGES))

    cov = p.add_argument_group("固定封面（用户风格）")
    cov.add_argument("--cover", metavar="PATH",
                     help="首图/封面，默认 %s" % DEFAULT_COVER)
    cov.add_argument("--no-cover", action="store_true", help="本次不加固定封面")
    cov.add_argument("--cover-insert", action="store_true",
                     help="--update 时把封面插入为第一张（默认替换第一张）")

    txt = p.add_argument_group("文案（不传即用用户固定风格）")
    txt.add_argument("--title", help="贴图标题；默认「%s」" % DEFAULT_TITLE)
    txt.add_argument("--content", help="短文案；命令行里的 \\n 会自动还原为换行")
    txt.add_argument("--tags", help="标签行，原样追加（默认单 # 风格）；空一行后接在正文末尾")
    txt.add_argument("--topics", help="话题，逗号分隔，转成微信官方 #话题名# 格式（覆盖默认标签）")
    txt.add_argument("--no-tags", action="store_true", help="不追加任何标签")
    txt.add_argument("--meta", metavar="JSON", help="从 UTF-8 JSON 读 title/content/tags/topics")
    txt.add_argument("--strict-title", action="store_true", help="标题恢复 32 字节保守校验")

    ctl = p.add_argument_group("控制")
    ctl.add_argument("--env", metavar="PATH", help="凭证文件路径")
    ctl.add_argument("--force", action="store_true", help="已投过的也重投")
    ctl.add_argument("--check-only", action="store_true",
                     help="只自检凭证与 IP 白名单；v1.3.0 起强制联网换 token（忽略本地缓存，避免假 OK）")
    ctl.add_argument("--dry-run", action="store_true", help="只挑图 + 校验文案，不联网")
    ctl.add_argument("--refresh-token", action="store_true", help="强制刷新 access_token")
    ctl.add_argument("--update", metavar="MEDIA_ID",
                     help="原地更新已有草稿（draft/update）：复用其图片，只换封面/文案")
    ctl.add_argument("--rebuild-images", action="store_true",
                     help="配合 --update：不复用旧图，按本次素材来源重新上传全部图片")
    ctl.add_argument("--verify", metavar="MEDIA_ID",
                     help="回读草稿并打印标题/正文/图片数/中文编码检查")
    ctl.add_argument("--square-crop", action="store_true", help="给封面加 1:1 居中裁剪（默认不加）")
    ctl.add_argument("--no-comment", action="store_true", help="关闭评论（默认开）")
    ctl.add_argument("--fans-only-comment", action="store_true", help="仅粉丝可评论")
    ctl.add_argument("--out-json", metavar="PATH", help="把本次结果写到 JSON 文件（供定时任务通知用）")
    return p


# --------------------------------------------------------------------------- 主流程

def do_verify(token, media_id):
    r = draft_get(token, media_id)
    a = r["news_item"][0]
    imgs = a.get("image_info", {}).get("image_list", [])
    log("草稿：%s" % media_id)
    log("标题      = %r" % a.get("title"))
    log("正文      = %r" % a.get("content"))
    log("中文转义  = %s" % ("有 \\uXXXX（异常）" if "\\u" in (a.get("title", "") + a.get("content", ""))
                             else "无（正常）"))
    log("图片张数  = %d（上限 %d）" % (len(imgs), SAFE_MAX_IMAGES))
    if imgs:
        log("首图素材ID = %s...（仅 media_id，不含文件名）"
            % str(imgs[0].get("image_media_id", ""))[:20])
        log("注意：--verify 判断不了首图是不是汤姆和杰瑞封面；"
            "以 --dry-run 的「首图自检 OK」和后台草稿箱肉眼确认为准。")
    log("评论      = %s / 仅粉丝 = %s" % (
        a.get("need_open_comment"), a.get("only_fans_can_comment")))
    return 0


def do_update(args, token, title, content, tbytes, cover, tmpdir):
    old = draft_get(token, args.update)
    a = old["news_item"][0]
    old_ids = [x.get("image_media_id") for x in a.get("image_info", {}).get("image_list", [])]
    log("原草稿：标题「%s」，%d 张图" % (a.get("title"), len(old_ids)))

    if args.rebuild_images or args.images or args.from_dir:
        used = load_used()
        images, _, post_dir = compose_images(args, used, cover)
        if not images:
            raise WeChatError("没有挑到任何图片，无法重建图片列表")
        log("重新上传 %d 张图（%s）" % (len(images), post_dir or "显式指定"))
        media_ids = [upload_image(token, p, tmpdir) for p in images]
    else:
        media_ids = [m for m in old_ids if m]
        if cover:
            log("上传固定封面：%s" % os.path.basename(cover))
            cid = upload_image(token, cover, tmpdir)
            if args.cover_insert:
                media_ids = ([cid] + media_ids)[:SAFE_MAX_IMAGES]
            else:
                media_ids = ([cid] + media_ids[1:])[:SAFE_MAX_IMAGES]
                log("已用固定封面替换原第一张图（其余 %d 张复用，不重复上传）" % (len(media_ids) - 1))
    if not media_ids:
        raise WeChatError("草稿图片列表为空")
    article = build_article(title, content, media_ids, args)
    payload = {"media_id": args.update, "index": 0, "articles": article}
    url = API + "/cgi-bin/draft/update?" + urllib.parse.urlencode({"access_token": token})
    http_json(url, payload, "更新贴图草稿")
    log("\n[OK] 草稿已原地更新（未新建、未发表）：%s" % args.update)
    log("   标题「%s」（%d 字节）；正文 %d 字符；图片 %d 张" % (
        title, tbytes, len(content), len(media_ids)))
    log("   首图 = 固定封面「%s」" % (os.path.basename(cover) if cover else "（未启用）"))
    do_verify(token, args.update)
    return 0


def main(argv=None):
    args = build_parser().parse_args(argv)

    if args.check_only:
        appid, secret, cred_from = load_credentials(args)
        log("凭证来源：%s" % cred_from)
        # v1.3.0：自检必须真的联网。旧版命中本地 token 缓存就直接返回「假 OK」，
        # 换机器后 IP 白名单根本没被验证到（实机验证修正版 #4）。
        log("[自检] 强制联网重新获取 access_token（忽略本地缓存）...")
        token = get_token(appid, secret, force=True)
        log("[OK] access_token 获取成功（len=%d，已写入缓存，未回显）" % len(token))
        log("     凭证与 IP 白名单均正常。去掉 --check-only 即可正式建贴图草稿。")
        return 0

    if args.verify:
        appid, secret, _ = load_credentials(args)
        do_verify(get_token(appid, secret, force=args.refresh_token), args.verify)
        return 0

    if args.dry_run and args.update:
        log("[dry-run] --update 会真实调用 draft/update。想预演请去掉 --update 单独跑。")
        return 0

    title, content = resolve_meta(args)
    tbytes = validate_meta(title, content, args.strict_title)
    cover = cover_path(args)

    if args.dry_run and not args.update:
        used = load_used()
        images, post_key, post_dir = compose_images(args, used, cover)
        if not images and post_key in used:
            log("跳过：这组图已经投过草稿了（加 --force 可重投）")
            return 0
        if not images:
            raise WeChatError("没有挑到任何图片")
        skipped = ignored_covers(post_dir) if post_dir else []
        log("素材组：%s" % (post_dir or "显式指定图片"))
        if skipped:
            log("已自动忽略固定封面文件：%s（不必手工移走）" % ", ".join(skipped))
        log("图片 %d 张：%s" % (len(images), ", ".join(os.path.basename(p) for p in images[:6]) +
                              (" ..." if len(images) > 6 else "")))
        log("首图（封面）：%s" % (os.path.basename(cover) if cover else "（未启用固定封面）"))
        log("图片列表第一项：%s" % os.path.basename(images[0]))
        log("首图自检：%s" % ("[OK] 固定封面在第一张" if cover else "（本次 --no-cover，无封面要求）"))
        log("张数自检：[OK] %d 张 ≤ %d 张安全上限（官方硬上限 %d）"
            % (len(images), SAFE_MAX_IMAGES, MAX_IMAGES))
        log("标题：%s（%d 字节 / %d 字符）" % (title, tbytes, len(title)))
        log("正文：\n%s" % content)
        log("\n[dry-run] 预检通过，未联网、未上传、未建草稿。去掉 --dry-run 即正式执行。")
        return 0

    appid, secret, cred_from = load_credentials(args)
    log("凭证来源：%s" % cred_from)
    token = get_token(appid, secret, force=args.refresh_token)

    with tempfile.TemporaryDirectory(prefix="tietu_") as tmpdir:
        if args.update:
            return do_update(args, token, title, content, tbytes, cover, tmpdir)

        used = load_used()
        images, post_key, post_dir = compose_images(args, used, cover)
        if not images and post_key in used:
            return 2
        if not images:
            raise WeChatError("没有挑到任何图片")

        skipped = ignored_covers(post_dir) if post_dir else []
        log("素材组：%s" % (post_dir or "显式指定图片"))
        if skipped:
            log("已自动忽略固定封面文件：%s" % ", ".join(skipped))
        log("图片 %d 张（首图为固定封面，≤%d 张安全上限）：%s" % (
            len(images), SAFE_MAX_IMAGES,
            ", ".join(os.path.basename(p) for p in images[:6]) +
            (" ..." if len(images) > 6 else "")))
        log("标题：%s（%d 字节）" % (title, tbytes))
        log("正文：%d 字符" % len(content))

        if args.dry_run:
            log("\n[dry-run] 预检通过，未联网、未上传、未建草稿。")
            return 0

        media_ids = []
        for i, path in enumerate(images, 1):
            upload_path = prepare_image(path, tmpdir)
            log("[%d/%d] 上传永久素材：%s" % (i, len(images), os.path.basename(path)))
            url = API + "/cgi-bin/material/add_material?" + urllib.parse.urlencode({
                "access_token": token, "type": "image"})
            media_ids.append(http_upload_image(url, upload_path)["media_id"])

        article = build_article(title, content, media_ids, args)
        log("创建贴图草稿（newspic，%d 张图）..." % len(media_ids))
        url = API + "/cgi-bin/draft/add?" + urllib.parse.urlencode({"access_token": token})
        resp = http_json(url, {"articles": [article]}, "新增贴图草稿")
        draft_media_id = resp["media_id"]

    record = {
        "draft_media_id": draft_media_id,
        "time": datetime.datetime.now().isoformat(timespec="seconds"),
        "title": title,
        "image_count": len(media_ids),
        "post_dir": post_dir or "",
        "images": [os.path.basename(p) for p in images],
    }
    used[post_key] = record
    _write_json_file(USED_DB, used)
    if args.out_json:
        _write_json_file(os.path.abspath(args.out_json), record)

    log("\n[OK] 贴图草稿已创建：media_id = %s" % draft_media_id)
    log("   图片 %d 张（首图固定封面），标题「%s」" % (len(media_ids), title))
    log("   现在去公众号后台 → 草稿箱，或手机订阅号助手 → 贴图，手动点发表（必要时扫码确认）。")
    log("   发表后该草稿会自动从草稿箱移除，本脚本的 .state/used_posts.json 也已记下这组图，不会重复投。")
    log("   ⚠️ 本脚本不调用 freepublish/submit，不会自动发表。")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except WeChatError as exc:
        print("\n[FAIL] %s" % exc, file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n已中断", file=sys.stderr)
        sys.exit(130)
