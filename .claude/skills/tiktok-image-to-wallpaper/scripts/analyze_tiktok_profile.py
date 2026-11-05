#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
分析一个 TikTok 博主的全部作品，并按「受欢迎程度」降序输出排行榜。

入口：任意一条能定位到博主的 TikTok 链接（帖子链接 / @username 主页 / vt.tiktok.com 短链）。
      脚本先用 yt-dlp 解析出博主 handle 与 secUid，再用 yt-dlp 的 flat-playlist 把该博主
      主页的全部作品（含点赞数、播放数、评论数、发布日期、文案、作品链接）抓下来，
      按点赞数（like_count）降序排好，打印排行榜，并把完整清单存成 CSV/JSON 方便后续批量下载。

为什么用 yt-dlp？
  gallery-dl 的 /posts 提取器走 creator/item_list，对部分账号分页会卡在第一页、抓不全；
  yt-dlp 走另一条接口（tiktokuser:<secUid>），能稳定枚举全量作品并直接给热度指标。
  真正的「下载转壁纸」仍交给 gallery-dl（download_tiktok.py / batch_download.py）。

排序指标（--metric，默认 likes）：
  likes    按点赞数降序 —— 最贴近“受欢迎程度”
  views    按播放数降序
  comments 按评论数降序

输出文件（落盘到执行目录，名为 <博主>_analysis.<csv|json>）：
  包含每一条的 rank / author / id / type / likes / views / comments / date / caption / url，
  供 batch_download.py 直接读取做批量下载。

依赖：yt-dlp（pip install yt-dlp）。首次运行会自动装。

用法：
  python3 analyze_tiktok_profile.py <tiktok_url> [--metric likes|views|comments]
                                      [--top N] [--out DIR]
  --top N   只打印排行榜前 N 条（默认全部，超过 60 条时仅打印前 60 并提示看 CSV）
  --out DIR 指定分析清单的保存目录（默认当前目录）
"""
import sys
import os
import re
import json
import csv
import subprocess
import time

# yt-dlp --print 各字段之间的分隔符（单位分隔符，文案里不会出现）
SEP = "\x1f"


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


def _yt_dlp_print(url, template):
    cmd = [sys.executable, "-m", "yt_dlp", "--no-warnings", "--skip-download",
           "--socket-timeout", "20", "--retries", "1",
           "--print", template, url]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        return (r.stdout or "").strip(), (r.stderr or "")
    except subprocess.TimeoutExpired:
        return "", "TIMEOUT"


def resolve_target(url):
    """解析博主 handle 与 secUid。返回 (blogger, sec_uid)。

    优先从链接里取 @handle；再去 yt-dlp 取 secUid（用帖子链接最稳，
    没有帖子 id 时退化为对主页取，主页取 secUid 偶发被挑战，会重试）。
    """
    blogger = None
    m = re.search(r'@([A-Za-z0-9_.-]+)', url)
    if m:
        blogger = m.group(1)
    post_id = None
    pm = re.search(r'/(?:phot|vide)o/(\d+)', url)
    if pm:
        post_id = pm.group(1)

    if not blogger:
        # 短链等情况：让 yt-dlp 报出 uploader（handle）
        out, _ = _yt_dlp_print(url, "%(uploader)s")
        if out and not out.startswith("ERROR"):
            blogger = out.strip()

    # 只有「帖子链接」才值得去取 secUid（帖子页能稳定给 channel_id）。
    # 纯主页链接取 secUid 常被挑战且耗时，主页本身即可直接列举，故跳过。
    sec_uid = None
    if ensure("yt_dlp", "yt-dlp") and post_id and blogger:
        probe = f"https://www.tiktok.com/@{blogger}/video/{post_id}"
        for attempt in range(1, 4):
            out, err = _yt_dlp_print(probe, "%(channel_id)s")
            if out and not out.startswith("ERROR") and out.startswith("MS4w"):
                sec_uid = out.strip()
                break
            if attempt < 3:
                print(f"  secUid 解析第 {attempt} 次失败，5 秒后重试 ...")
                time.sleep(5)
    return blogger, sec_uid


def _try_fetch(listing_url):
    """对某个 listing URL 跑 yt-dlp flat-playlist，重试 3 次，返回记录列表。"""
    if not ensure("yt_dlp", "yt-dlp"):
        return []
    fmt = (f"%(id)s{SEP}%(like_count)s{SEP}%(view_count)s{SEP}"
           f"%(comment_count)s{SEP}%(duration)s{SEP}%(upload_date)s{SEP}"
           f"%(title)s")
    cmd = [sys.executable, "-m", "yt_dlp", "--flat-playlist", "--no-warnings",
           "--skip-download", "--socket-timeout", "20", "--retries", "1",
           "--print", fmt, listing_url]
    last_err = ""
    for attempt in range(1, 4):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        except subprocess.TimeoutExpired:
            last_err = "TIMEOUT"
            print(f"  yt-dlp 第 {attempt} 次超时，8 秒后重试 ...")
            if attempt < 3:
                time.sleep(8)
            continue
        out = (r.stdout or "").strip()
        if out and not out.startswith("ERROR"):
            return _parse(out)
        last_err = (r.stderr or '')[-1200:]
        if attempt < 3:
            print(f"  yt-dlp 第 {attempt} 次未取到（可能限流/挑战），8 秒后重试 ...")
            time.sleep(8)
    if last_err:
        print("yt-dlp 报错（末段）：\n", last_err)
    return []


def _parse(stdout):
    records = []
    seen = set()
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        # 字段顺序：id | likes | views | comments | duration | upload_date | title
        p = line.split(SEP)
        if len(p) < 6:
            continue
        pid = p[0]
        if pid in seen:
            continue
        seen.add(pid)

        def num(v):
            v = (v or "").strip()
            if v in ("", "NA", "None"):
                return 0
            try:
                return int(float(v))
            except Exception:
                return 0

        dur = p[4] if len(p) > 4 else ""
        # 类型仅作参考：TikTok 图文幻灯片也会带 duration，故仅当时长 >60s 才判为视频；
        # 真正下载时 gallery-dl 对图文帖会取图片、对视频取首帧，都可作为壁纸。
        ptype = "video" if num(dur) > 60 else "photo"
        upload_date = p[5] if len(p) > 5 else ""
        date = ""
        if len(upload_date) == 8 and upload_date.isdigit():
            date = f"{upload_date[0:4]}-{upload_date[4:6]}-{upload_date[6:8]}"
        title = p[6] if len(p) > 6 else ""
        records.append({
            "id": pid,
            "likes": num(p[1]) if len(p) > 1 else 0,
            "views": num(p[2]) if len(p) > 2 else 0,
            "comments": num(p[3]) if len(p) > 3 else 0,
            "shares": 0,
            "type": ptype,
            "date": date,
            "caption": title.replace(SEP, " ").replace("\n", " ").strip(),
        })
    return records


def fetch_profile(blogger, sec_uid):
    """枚举全量作品：多候选 URL 依次尝试，任一成功即返回。

    首选主页 `https://www.tiktok.com/@<handle>`（yt-dlp 直接支持，实测最可靠）。
    secUid 兜底用 `https://www.tiktok.com/@<secUid>` 形式——旧版脚本用的
    `tiktokuser:<secUid>` 伪协议在 yt-dlp 2026.10.26 已失效，会报
    `Unsupported url scheme: "tiktokuser"`。
    """
    candidates = []
    if blogger:
        candidates.append(f"https://www.tiktok.com/@{blogger}")
    if sec_uid:
        candidates.append(f"https://www.tiktok.com/@{sec_uid}")
    for u in candidates:
        print(f"  尝试列举: {u}")
        recs = _try_fetch(u)
        if recs:
            return recs
        print("  该路径未取到，换下一种 ...")
    return []


def human(n):
    if n is None:
        return "0"
    n = float(n)
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n/1_000:.1f}K"
    return str(int(n))


def main():
    args = sys.argv[1:]
    url = None
    metric = "likes"
    top = 0          # 0 = 全部
    out_dir = "."
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--metric" and i + 1 < len(args):
            metric = args[i + 1]; i += 2; continue
        if a == "--top" and i + 1 < len(args):
            top = int(args[i + 1]); i += 2; continue
        if a == "--out" and i + 1 < len(args):
            out_dir = args[i + 1]; i += 2; continue
        if url is None:
            url = a
        i += 1

    if not url:
        print(__doc__.split("用法")[0])
        print("usage: analyze_tiktok_profile.py <tiktok_url> [--metric ...] [--top N] [--out DIR]")
        sys.exit(2)

    blogger, sec_uid = resolve_target(url)
    if not blogger:
        print("ERROR: 无法解析博主 @handle，请直接给包含 @username 的链接。")
        sys.exit(3)
    print("博主主页:", f"https://www.tiktok.com/@{blogger}")
    if sec_uid:
        print("secUid:", sec_uid[:24] + "…")

    records = fetch_profile(blogger, sec_uid)
    if not records:
        print("ERROR: 未抓到任何作品（可能博主隐私/需登录 Cookie/链接失效/被限流）。")
        sys.exit(4)
    # 给每条补 author 与下载用 url
    for r in records:
        r["author"] = blogger
        r["url"] = f"https://www.tiktok.com/@{blogger}/video/{r['id']}"
    print(f"抓到作品总数: {len(records)}")

    metric_key = {"likes": "likes", "views": "views",
                  "comments": "comments"}.get(metric, "likes")
    records.sort(key=lambda r: r[metric_key], reverse=True)

    # 打印排行榜
    show = top if top else len(records)
    cap = 60
    print(f"\n=== {blogger} 作品排行榜（按 {metric_key} 降序）===")
    header = (f"{'#':>3}  {'类型':<5} {'点赞':>8} {'播放':>9} {'评论':>7}  "
              f"{'日期':<10}  {'ID':<20} 文案")
    print(header)
    print("-" * len(header))
    for idx, r in enumerate(records[:min(show, cap)], 1):
        cap_txt = r["caption"][:24] + ("…" if len(r["caption"]) > 24 else "")
        print(f"{idx:>3}  {r['type']:<5} {human(r['likes']):>8} "
              f"{human(r['views']):>9} {human(r['comments']):>7}  "
              f"{r['date']:<10}  {r['id']:<20} {cap_txt}")
    if len(records) > cap and not top:
        print(f"…（共 {len(records)} 条，仅显示前 {cap} 条；完整清单见 CSV/JSON）")

    # 保存 CSV / JSON
    os.makedirs(out_dir, exist_ok=True)
    csv_path = os.path.join(out_dir, f"{blogger}_analysis.csv")
    json_path = os.path.join(out_dir, f"{blogger}_analysis.json")
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["rank", "author", "id", "type", "likes",
                                          "views", "comments", "shares",
                                          "date", "caption", "url"])
        w.writeheader()
        for idx, r in enumerate(records, 1):
            row = dict(r); row["rank"] = idx
            w.writerow(row)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
    print(f"\n已保存完整清单：\n  {csv_path}\n  {json_path}")
    print("下一步：把要下载的序号告诉我（例如“下载前 10 个 / 下载 #2,5,8”），"
          "我用 batch_download.py 批量下载。")


if __name__ == '__main__':
    main()
