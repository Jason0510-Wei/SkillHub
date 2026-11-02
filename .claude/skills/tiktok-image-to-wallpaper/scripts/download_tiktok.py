#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从 TikTok 链接下载图片/视频，并直接转成手机壁纸 JPEG，按下面的目录结构落盘：

    <base_dir>/<博主>/<时间戳YYYYMMDDHHMM>/

其中：
  - <base_dir> 默认是执行目录下的「壁纸」文件夹（可用第 2 个参数覆盖）；
  - <博主>    自动从链接识别 TikTok handle（@username），识别不到时退化为 "tiktok"；
  - <时间戳>  本条链接保存时的本地时间，格式 YYYYMMDDHHMM（如 202611021238）。

每个链接一个时间文件夹、每个博主一个文件夹，方便按人归档。

下载器优先级：
  1. gallery-dl（首选）：TikTok 提取器成熟，能处理「图文/幻灯片」帖子（/photo/ 路径），
     并自动解 TikTok 的 JS 挑战（反爬），通常无需登录 Cookie 即可下到图片。
  2. yt-dlp（兜底）：仅对 yt-dlp 支持的常见视频链接生效；对 /photo/ 图文帖会报
     Unsupported URL，因此只作为 gallery-dl 失败时的备胎。

依赖：gallery-dl（pip install gallery-dl）。若未安装会自动尝试 pip 安装。
本机若走代理，gallery-dl/requests 会自动读取 HTTP_PROXY/HTTPS_PROXY 环境变量。

用法：
  python3 download_tiktok.py <tiktok_url> [base_dir] [--no-convert] [--4k]
默认 base_dir = 当前目录下的「壁纸」；--no-convert 只下载不转壁纸（保留原始文件）；
--4k 把转出的壁纸长边升采样到 3840（4K 尺寸，源 <4K 时为插值放大，细节不增）。
"""
import sys
import os
import re
import shutil
import subprocess
import tempfile
import datetime

# 视为“媒体文件”的扩展名
MEDIA_EXT = ('.jpg', '.jpeg', '.png', '.webp', '.image', '.heic',
             '.avif', '.gif', '.bmp', '.mp4', '.mov', '.webm', '.mkv')
# 纯音频直接排除（壁纸不关心）
SKIP_EXT = ('.mp3', '.m4a', '.wav', '.aac', '.ogg')


def ensure(module, pkg):
    try:
        __import__(module)
        return True
    except Exception:
        print(f"{module} 未安装，正在尝试 pip install {pkg} ...")
        r = subprocess.run([sys.executable, "-m", "pip", "install", "-q", pkg],
                          capture_output=True, text=True)
        if r.returncode != 0:
            print("安装失败：", (r.stderr or '')[-500:])
            return False
        return True


def run_gallery_dl(url, outdir):
    if not ensure("gallery_dl", "gallery-dl"):
        return False
    os.makedirs(outdir, exist_ok=True)
    cmd = [sys.executable, "-m", "gallery_dl", "-d", outdir, url]
    print("gallery-dl downloading:", url)
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print("gallery-dl 报错（末段）：\n", (r.stderr or r.stdout or '')[-1500:])
        return False
    return True


def run_ytdlp(url, outdir):
    if not ensure("yt_dlp", "yt-dlp"):
        return False
    os.makedirs(outdir, exist_ok=True)
    outtmpl = os.path.join(outdir, "%(id)s_%(playlist_index)s.%(ext)s")
    cmd = [sys.executable, "-m", "yt_dlp",
           "-o", outtmpl,
           "--no-warnings",
           "--ignore-errors",
           "--no-playlist",   # 只下当前这条帖子，不顺着相关推荐爬
           url]
    print("yt-dlp downloading:", url)
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print("yt-dlp 报错（末段）：\n", (r.stderr or r.stdout or '')[-1500:])
        return False
    return True


def blogger_from_url(url):
    m = re.search(r'@([A-Za-z0-9_.]+)', url)
    return m.group(1) if m else None


def blogger_from_tree(workdir):
    """gallery-dl 下载结构为 <workdir>/tiktok/<user>/...，从中取出 <user>。"""
    for root, dirs, files in os.walk(workdir):
        parts = root.split(os.sep)
        if 'tiktok' in parts:
            i = parts.index('tiktok')
            if i + 1 < len(parts):
                return parts[i + 1]
    return None


def collect_media(workdir):
    out = []
    for root, dirs, files in os.walk(workdir):
        for f in files:
            ext = os.path.splitext(f)[1].lower()
            if ext in MEDIA_EXT:
                out.append(os.path.join(root, f))
    return out


def unique_dst(target, name):
    dst = os.path.join(target, name)
    if not os.path.exists(dst):
        return dst
    base, ex = os.path.splitext(name)
    k = 1
    while os.path.exists(os.path.join(target, f"{base}_{k}{ex}")):
        k += 1
    return os.path.join(target, f"{base}_{k}{ex}")


def main():
    args = sys.argv[1:]
    url = None
    base_dir = "壁纸"
    no_convert = False
    fourk = False
    for a in args:
        if a == "--no-convert":
            no_convert = True
        elif a == "--4k":
            fourk = True
        elif url is None:
            url = a
        else:
            base_dir = a

    if not url:
        print("usage: download_tiktok.py <tiktok_url> [base_dir] [--no-convert] [--4k]")
        sys.exit(2)

    ts = datetime.datetime.now().strftime("%Y%m%d%H%M")
    blogger = blogger_from_url(url)
    tmp = tempfile.mkdtemp(prefix="tiktok_dl_")

    ok = run_gallery_dl(url, tmp)
    if not ok:
        print("gallery-dl 失败，回退 yt-dlp ...")
        ok = run_ytdlp(url, tmp)
    if not ok:
        shutil.rmtree(tmp, ignore_errors=True)
        print("ERROR: 下载失败（gallery-dl 与 yt-dlp 均未成功），"
              "请检查链接/网络/Cookie。报错可贴回诊断。")
        sys.exit(4)

    if not blogger:
        blogger = blogger_from_tree(tmp)
    if not blogger:
        blogger = "tiktok"

    target = os.path.join(base_dir, blogger, ts)
    os.makedirs(target, exist_ok=True)

    moved = 0
    for f in collect_media(tmp):
        ext = os.path.splitext(f)[1].lower()
        if ext in SKIP_EXT:
            continue
        dst = unique_dst(target, os.path.basename(f))
        shutil.move(f, dst)
        moved += 1
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"DOWNLOADED {moved} media files -> {target}")

    if no_convert:
        print("DONE (no-convert):", target)
        return

    conv = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "convert_tiktok_image.py")
    if not os.path.exists(conv):
        print("WARN: 未找到 convert_tiktok_image.py，跳过转换。原始文件已保留在", target)
        return

    ok_conv = 0
    for f in sorted(os.listdir(target)):
        fp = os.path.join(target, f)
        if not os.path.isfile(fp):
            continue
        ext = os.path.splitext(f)[1].lower()
        if ext not in MEDIA_EXT:
            continue
        if f.endswith("_wallpaper.jpg"):   # 已是成品，跳过
            continue
        out = os.path.join(target, os.path.splitext(f)[0] + "_wallpaper.jpg")
        conv_argv = [sys.executable, conv, fp, out]
        if fourk:
            conv_argv.append("--4k")
        r = subprocess.run(conv_argv, capture_output=True, text=True)
        if r.returncode == 0 and os.path.exists(out):
            ok_conv += 1
            try:
                os.remove(fp)              # 转成功则删原始下载件，保持文件夹干净
            except OSError:
                pass
        else:
            print("convert fail:", f, "->", (r.stderr or '')[-300:])
    print(f"CONVERTED {ok_conv} -> 壁纸已存于 {target}" + (" [4K]" if fourk else ""))


if __name__ == '__main__':
    main()
