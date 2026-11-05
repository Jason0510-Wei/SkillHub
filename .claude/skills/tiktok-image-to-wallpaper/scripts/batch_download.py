#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
按用户选择，批量把 TikTok 帖子下载并转成手机壁纸。

输入来源（三选一）：
  1. 直接传若干条 TikTok 链接：
       python3 batch_download.py <url1> <url2> ... [--base-dir DIR] [--4k]
  2. 从 analyze_tiktok_profile.py 生成的 CSV 读取，按排名区间/序号挑选：
       python3 batch_download.py --from <xxx_analysis.csv> --top 10 [--base-dir DIR] [--4k]
       python3 batch_download.py --from <xxx_analysis.csv> --pick 1,3,5,8 [--base-dir DIR] [--4k]
  3. 从含 url 列的 CSV 读取全部：
       python3 batch_download.py --from <file.csv> [--base-dir DIR] [--4k]

每条链接都会调用同目录下的 download_tiktok.py 完成「下载 + 按序编号」。
默认「原图直出」：不转码、保留原始分辨率与格式，直接按 1..N 编号。
只有显式加 --convert 才走旧转码流程（宽度≤1080 JPG，原图移入 .originals/）；
--4k 为转码升采样模式（会隐含启用转码）。两者默认都不配置。

去重（--skip-existing，默认开启）：
  下载前会检查 <base-dir>/<author>/ 下是否已有该帖子的文件：
    - 旧版文件夹文件名里带 post id（如 7690262550029536532_01...），直接命中；
    - 新版文件夹被重命名为 1_wallpaper.jpg 后不带 id，因此额外维护一份
      <base-dir>/<author>/.downloaded.json 清单（post_id -> 文件夹），下载成功后写入。
  命中则跳过，避免重复下载。用 --force 可强制重下。

用法：
  python3 batch_download.py <urls...> [--base-dir DIR] [--convert] [--4k] [--force]
  python3 batch_download.py --from <csv> [--top N | --pick a,b,c] [--base-dir DIR] [--convert] [--4k] [--force]
默认：原图直出（不转码）；--convert 显式启用转码；--4k 转码升采样到 3840。
"""
import sys
import os
import re
import csv
import json
import glob
import subprocess

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DOWNLOAD = os.path.join(SCRIPT_DIR, "download_tiktok.py")

ID_RE = re.compile(r'/(?:phot|vide)o/(\d+)')
AUTHOR_RE = re.compile(r'@([A-Za-z0-9_.-]+)')


def post_id_of(url):
    m = ID_RE.search(url)
    return m.group(1) if m else None


def author_of(url, fallback="unknown"):
    m = AUTHOR_RE.search(url)
    return m.group(1) if m else fallback


def manifest_path(base, author):
    return os.path.join(base, author, ".downloaded.json")


def build_manifest_from_files(base, author):
    """扫描已有文件夹，从文件名 / 文件夹名里提取 post id。"""
    m = {}
    root = os.path.join(base, author)
    if not os.path.isdir(root):
        return m
    for f in glob.glob(os.path.join(root, "**", "*"), recursive=True):
        if os.path.isfile(f):
            mm = re.search(r'(\d{18,20})', os.path.basename(f))
            if mm:
                m.setdefault(mm.group(1), os.path.dirname(f))
    # 新格式文件夹名含 post id（如 20261103_114312_7692114864516418868）
    for d in glob.glob(os.path.join(root, "*")):
        if os.path.isdir(d):
            mm = re.search(r'(\d{18,20})', os.path.basename(d))
            if mm:
                m.setdefault(mm.group(1), d)
    return m


def load_manifest(base, author):
    m = build_manifest_from_files(base, author)
    mp = manifest_path(base, author)
    if os.path.exists(mp):
        try:
            with open(mp, encoding="utf-8") as fh:
                stored = json.load(fh)
            if isinstance(stored, dict):
                m.update(stored)
        except Exception:
            pass
    return m, mp


def save_manifest(mp, m):
    os.makedirs(os.path.dirname(mp), exist_ok=True)
    with open(mp, "w", encoding="utf-8") as fh:
        json.dump(m, fh, ensure_ascii=False, indent=2)


def already_has(base, author, post_id, manifest):
    if post_id in manifest:
        return manifest[post_id]
    root = os.path.join(base, author)
    if os.path.isdir(root):
        for f in glob.glob(os.path.join(root, "**", "*"), recursive=True):
            if os.path.isfile(f) and post_id in os.path.basename(f):
                return os.path.dirname(f)
    return None


def latest_subdir(base, author):
    root = os.path.join(base, author)
    if not os.path.isdir(root):
        return None
    subs = [os.path.join(root, d) for d in os.listdir(root)
            if os.path.isdir(os.path.join(root, d)) and not d.startswith(".")]
    if not subs:
        return None
    return max(subs, key=lambda p: os.path.getmtime(p))


def read_urls_from_csv(csv_path, top=0, pick=None):
    if not os.path.exists(csv_path):
        print("ERROR: CSV 不存在:", csv_path)
        sys.exit(3)
    rows = []
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    if not rows:
        print("ERROR: CSV 为空。")
        sys.exit(3)
    url_col = None
    for c in ("url", "URL", "link", "链接"):
        if c in rows[0]:
            url_col = c
            break
    if url_col is None:
        for c in rows[0].keys():
            if str(rows[0][c]).startswith("http"):
                url_col = c
                break
    if url_col is None:
        print("ERROR: CSV 中找不到 url 列。")
        sys.exit(3)

    chosen = []
    if pick:
        idxs = set()
        for p in pick.split(","):
            p = p.strip()
            if p.isdigit():
                idxs.add(int(p))
        for i, row in enumerate(rows, 1):
            if i in idxs:
                chosen.append(row[url_col])
    else:
        limit = top if top else len(rows)
        for row in rows[:limit]:
            chosen.append(row[url_col])
    return chosen


def main():
    args = sys.argv[1:]
    urls = []
    base_dir = "壁纸"
    fourk = False
    convert = False
    from_csv = None
    top = 0
    pick = None
    skip_existing = True

    i = 0
    while i < len(args):
        a = args[i]
        if a == "--base-dir" and i + 1 < len(args):
            base_dir = args[i + 1]; i += 2; continue
        if a == "--from" and i + 1 < len(args):
            from_csv = args[i + 1]; i += 2; continue
        if a == "--top" and i + 1 < len(args):
            top = int(args[i + 1]); i += 2; continue
        if a == "--pick" and i + 1 < len(args):
            pick = args[i + 1]; i += 2; continue
        if a == "--4k":
            fourk = True; i += 1; continue
        if a == "--convert":
            convert = True; i += 1; continue
        if a == "--force":
            skip_existing = False; i += 1; continue
        if a == "--no-skip":
            skip_existing = False; i += 1; continue
        if a.startswith("--"):
            i += 1; continue
        urls.append(a)
        i += 1

    if from_csv:
        urls = read_urls_from_csv(from_csv, top=top, pick=pick)
    if not urls:
        print(__doc__.split("用法")[0])
        print("usage: batch_download.py <urls...> | --from <csv> [--top N|--pick a,b,c] [--base-dir DIR] [--4k] [--force]")
        sys.exit(2)
    if not os.path.exists(DOWNLOAD):
        print("ERROR: 找不到 download_tiktok.py 于", DOWNLOAD)
        sys.exit(2)

    base_dir = os.path.abspath(base_dir)
    manifest, mp = load_manifest(base_dir, author_of(urls[0]))

    mode = "转码1080" if convert else ("转码4K" if fourk else "原图直出(默认)")
    print(f"待处理 {len(urls)} 条，base-dir={base_dir} [{mode}]"
          f"{' [去重开启]' if skip_existing else ' [强制重下]'}")
    ok = 0
    skipped = 0
    for n, u in enumerate(urls, 1):
        pid = post_id_of(u)
        author = author_of(u)
        tag = f"#{pid}" if pid else u
        if skip_existing and pid:
            hit = already_has(base_dir, author, pid, manifest)
            if hit:
                print(f"\n----- [{n}/{len(urls)}] 跳过（已下载于 {os.path.basename(hit)}）{tag} -----")
                skipped += 1
                continue
        print(f"\n----- [{n}/{len(urls)}] {tag} -----")
        cmd = [sys.executable, DOWNLOAD, u, base_dir]
        if convert:
            cmd.append("--convert")
        if fourk:
            cmd.append("--4k")
        r = subprocess.run(cmd)
        if r.returncode == 0:
            ok += 1
            if pid:
                folder = latest_subdir(base_dir, author)
                if folder:
                    manifest[pid] = folder
                    save_manifest(mp, manifest)
        else:
            print("!! 该条失败（返回码", r.returncode, "），继续下一条。")
    print(f"\n批量下载完成：成功 {ok} / 跳过 {skipped} / 共 {len(urls)}")


if __name__ == '__main__':
    main()
