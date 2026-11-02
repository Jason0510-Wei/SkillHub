#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从 TikTok 链接下载图片（或视频）到指定目录，供后续转壁纸使用。

依赖：yt-dlp（pip install yt-dlp）。若未安装会自动尝试 pip 安装。
注意：TikTok 反爬较严，部分链接/地区可能需要登录 Cookie 或代理；失败时把报错贴回来诊断。

用法：
  python3 download_tiktok.py <tiktok_url> [outdir]
默认 outdir = 当前目录下的 tiktok_download/
"""
import sys
import os
import subprocess

# 视为“媒体文件”的扩展名；convert 脚本会逐个处理这些
MEDIA_EXT = ('.jpg', '.jpeg', '.png', '.webp', '.image', '.heic',
             '.avif', '.gif', '.bmp', '.mp4', '.mov', '.webm', '.mkv')


def ensure_ytdlp():
    try:
        import yt_dlp  # noqa: F401
        return True
    except Exception:
        print("yt-dlp 未安装，正在尝试 pip install yt-dlp ...")
        r = subprocess.run([sys.executable, "-m", "pip", "install", "-q", "yt-dlp"],
                          capture_output=True, text=True)
        if r.returncode != 0:
            print("安装失败：", (r.stderr or '')[-500:])
            return False
        return True


def main():
    if len(sys.argv) < 2:
        print("usage: download_tiktok.py <tiktok_url> [outdir]")
        sys.exit(2)

    url = sys.argv[1]
    outdir = (sys.argv[2] if len(sys.argv) > 2
              else os.path.join(os.getcwd(), "tiktok_download"))
    os.makedirs(outdir, exist_ok=True)

    if not ensure_ytdlp():
        print("ERROR: 无法使用 yt-dlp，请手动 `pip install yt-dlp` 后重试")
        sys.exit(3)

    # 输出模板：帖子 id + 序号 + 原扩展名
    outtmpl = os.path.join(outdir, "%(id)s_%(playlist_index)s.%(ext)s")
    cmd = [sys.executable, "-m", "yt_dlp",
           "-o", outtmpl,
           "--no-warnings",
           "--ignore-errors",
           "--no-playlist",   # 只下当前这条帖子，不顺着相关推荐爬
           url]

    print("downloading:", url)
    r = subprocess.run(cmd, capture_output=True, text=True)

    files = sorted(
        os.path.join(outdir, f) for f in os.listdir(outdir)
        if os.path.isfile(os.path.join(outdir, f)) and f.lower().endswith(MEDIA_EXT)
    )
    print("DOWNLOADED", len(files), "files ->", outdir)
    for f in files:
        print(" -", f)

    if not files:
        print("WARN: 未下载到任何媒体文件。yt-dlp 输出如下，可贴回诊断：")
        print((r.stderr or r.stdout or '')[-2000:])


if __name__ == '__main__':
    main()
