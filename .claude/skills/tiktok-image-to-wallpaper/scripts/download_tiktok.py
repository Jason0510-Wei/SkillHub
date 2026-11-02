#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从 TikTok 链接下载图片/视频到指定目录，供后续转壁纸使用。

下载器优先级：
  1. gallery-dl（首选）：TikTok 提取器成熟，能处理「图文/幻灯片」帖子（/photo/ 路径），
     并自动解 TikTok 的 JS 挑战（反爬），通常无需登录 Cookie 即可下到图片。
  2. yt-dlp（兜底）：仅对 yt-dlp 支持的常见视频链接生效；对 /photo/ 图文帖会报
     Unsupported URL，因此只作为 gallery-dl 失败时的备胎。

依赖：gallery-dl（pip install gallery-dl）。若未安装会自动尝试 pip 安装。
注意：TikTok 反爬较严，个别链接/地区可能仍需登录 Cookie 或代理；失败时把报错贴回诊断。
本机若走代理，gallery-dl/requests 会自动读取 HTTP_PROXY/HTTPS_PROXY 环境变量。

用法：
  python3 download_tiktok.py <tiktok_url> [outdir]
默认 outdir = 当前目录下的 tiktok_download/
"""
import sys
import os
import shutil
import subprocess

# 视为“媒体文件”的扩展名；convert 脚本会逐个处理这些
MEDIA_EXT = ('.jpg', '.jpeg', '.png', '.webp', '.image', '.heic',
             '.avif', '.gif', '.bmp', '.mp4', '.mov', '.webm', '.mkv')
# 壁纸转换只关心图片和视频，纯音频直接排除
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


def flatten(outdir):
    """gallery-dl 会把文件下到 tiktok/<user>/... 嵌套目录，并可能附带音频。
    这里把媒体文件提到 outdir 根、删掉纯音频、清理空目录，方便下一步 convert 直接遍历。"""
    moved = 0
    for root, dirs, files in os.walk(outdir):
        if root == outdir:
            continue
        for f in files:
            ext = os.path.splitext(f)[1].lower()
            src = os.path.join(root, f)
            if ext in SKIP_EXT:
                try:
                    os.remove(src)
                except OSError:
                    pass
                continue
            if ext in MEDIA_EXT:
                dst = os.path.join(outdir, f)
                if os.path.exists(dst):
                    base, ex = os.path.splitext(f)
                    k = 1
                    while os.path.exists(os.path.join(outdir, f"{base}_{k}{ex}")):
                        k += 1
                    dst = os.path.join(outdir, f"{base}_{k}{ex}")
                shutil.move(src, dst)
                moved += 1
    for root, dirs, files in os.walk(outdir, topdown=False):
        if root == outdir:
            continue
        try:
            if not os.listdir(root):
                os.rmdir(root)
        except OSError:
            pass
    return moved


def main():
    if len(sys.argv) < 2:
        print("usage: download_tiktok.py <tiktok_url> [outdir]")
        sys.exit(2)

    url = sys.argv[1]
    outdir = (sys.argv[2] if len(sys.argv) > 2
              else os.path.join(os.getcwd(), "tiktok_download"))
    os.makedirs(outdir, exist_ok=True)

    ok = run_gallery_dl(url, outdir)
    if not ok:
        print("gallery-dl 失败，回退 yt-dlp ...")
        ok = run_ytdlp(url, outdir)

    moved = flatten(outdir)
    files = sorted(
        os.path.join(outdir, f) for f in os.listdir(outdir)
        if os.path.isfile(os.path.join(outdir, f))
        and os.path.splitext(f)[1].lower() in MEDIA_EXT
    )
    print("DOWNLOADED", len(files), "media files ->", outdir,
          "(从子目录归并", moved, "个)")
    for f in files:
        print(" -", f)

    if not files:
        print("WARN: 未下载到任何媒体文件。请检查链接是否有效，"
              "或 TikTok 是否要求登录 Cookie / 代理；报错可贴回诊断。")


if __name__ == '__main__':
    main()
