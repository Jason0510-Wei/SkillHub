#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pipeline.py - 壁纸日更流水线「薄编排层」。

只负责把三个已存在的 skill 串起来，不复制它们的实现逻辑，也不改变
「下载」与「发帖」两个 skill 互相独立的事实：

    tiktok-image-to-wallpaper (analyze / batch_download)
        ↓ A/B 成对原图，归档 壁纸/<博主>/<帖子>-<日期>/
    wallpaper-daily-pipeline make_batches.py (本 skill，8+1 复制式分批)
        ↓ 发布批次/<批次>/0001/ 里 1_A..4_B + cover.png
    wechat-tietu-draft (tietu_draft.py)
        ↓ 每天取 N 组，各建 1 条 newspic 贴图草稿；发表永远由人工点击

子命令：
    analyze   枚举博主全部作品并按点赞降序出榜单 CSV/JSON
    select    按 --min-likes / --photo-only 从榜单筛出下载清单
    download  调用 batch_download.py 批量下载（自带去重）
    batch     调用 make_batches.py 生成 8+1 发布组
    draft     从发布组队列取 --per-day 组，逐组建公众号贴图草稿
    all       串起上面五步（可 --skip-download / --no-draft / --dry-run）

网络接缝（实机踩坑固化）：
    * TikTok 子进程强制走 --proxy（默认 http://127.0.0.1:7890），
      因为 WorkBuddy 会注入 http_proxy=127.0.0.1:12741，yt-dlp / gallery-dl
      继承后连不上外网；
    * 微信 API 子进程反过来清空所有代理变量并设 NO_PROXY=api.weixin.qq.com，
      国内接口必须直连，否则出口 IP 变化还会触发 40164 白名单错误。

用法：
    python pipeline.py --help
    python pipeline.py select --from "<榜单.csv>" --min-likes 10000 --photo-only
    python pipeline.py draft --batch-dir "<批次目录>" --per-day 4 --dry-run
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

HERE = Path(__file__).resolve().parent
DEFAULT_SKILLS_ROOT = Path.home() / ".workbuddy" / "skills"
DEFAULT_WALLPAPER_DIR = os.environ.get("WALLPAPER_PIPELINE_DIR", r"E:\图片\壁纸")
DEFAULT_BATCH_ROOT = os.environ.get("WALLPAPER_BATCH_DIR", r"E:\图片\发布批次")
DEFAULT_PROXY = os.environ.get("TIKTOK_PROXY", "http://127.0.0.1:7890")
DEFAULT_PAIRS_PER_GROUP = 4          # 4 对 A/B = 8 张壁纸
DEFAULT_PER_DAY = 4                  # 每天 4 组 = 4 条贴图草稿
PROXY_KEYS = ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy",
              "ALL_PROXY", "all_proxy")


def die(msg: str) -> None:
    raise SystemExit("[ERROR] " + msg)


def log(msg: str = "") -> None:
    print(msg, flush=True)


def script_path(skills_root: Path, skill: str, name: str) -> Path:
    p = skills_root / skill / "scripts" / name
    if not p.is_file():
        die("找不到脚本：%s\n请确认 --skills-root 指向 skills 目录（当前 %s）" % (p, skills_root))
    return p


def cover_path(args) -> Path:
    if args.cover:
        p = Path(args.cover).expanduser().resolve()
    else:
        assets = Path(args.skills_root) / "wechat-tietu-draft" / "assets"
        # 用户 2026-11-13 22:33 指定 封面.png 为唯一权威文件名；兼容旧 clone 的旧名
        names = ("封面.png", "cover_tom_jerry.png")
        p = next((assets / n for n in names if (assets / n).is_file()),
                 assets / names[0])
    if not p.is_file():
        die("汤姆和杰瑞固定封面不存在：%s（首图硬性要求，不能缺）" % p)
    return p


def env_for(kind: str, proxy: str) -> dict:
    env = os.environ.copy()
    if kind == "tiktok":
        for k in PROXY_KEYS:
            env[k] = proxy
        env["NO_PROXY"] = "localhost,127.0.0.1"
        env["no_proxy"] = "localhost,127.0.0.1"
    elif kind == "wechat":
        for k in PROXY_KEYS:
            env.pop(k, None)
        env["NO_PROXY"] = "api.weixin.qq.com,localhost,127.0.0.1"
        env["no_proxy"] = "api.weixin.qq.com,localhost,127.0.0.1"
    return env


def run(cmd, env, capture=False, check=True, quiet=False):
    if not quiet:
        log("  $ " + " ".join(str(c) for c in cmd))
    r = subprocess.run([str(c) for c in cmd], env=env,
                       capture_output=capture, text=True,
                       encoding="utf-8", errors="replace")
    if capture:
        if r.stdout and not quiet:
            log(r.stdout.rstrip())
        if r.stderr and not quiet:
            log(r.stderr.rstrip())
    if check and r.returncode != 0:
        die("子进程退出码 %d：%s" % (r.returncode, " ".join(str(c) for c in cmd[:3])))
    return r


def author_of(url: str) -> str:
    m = re.search(r"@([A-Za-z0-9_.-]+)", url or "")
    return m.group(1) if m else ""


def batch_dir_of(args, author: str) -> Path:
    name = args.batch_name or ("%s-%s" % (datetime.now().strftime("%Y%m%d"), author or "batch"))
    return Path(args.batch_root).expanduser().resolve() / name


def md5(path: Path) -> str:
    h = hashlib.md5()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


# --------------------------------------------------------------------------- 各阶段

def cmd_analyze(args):
    out = Path(args.out).expanduser().resolve() if args.out else \
        Path(args.wallpaper_dir).expanduser().resolve() / "_榜单"
    out.mkdir(parents=True, exist_ok=True)
    s = script_path(Path(args.skills_root), "tiktok-image-to-wallpaper",
                    "analyze_tiktok_profile.py")
    run([sys.executable, s, args.url, "--metric", "likes", "--out", out],
        env_for("tiktok", args.proxy))
    author = author_of(args.url)
    csv_path = out / ("%s_analysis.csv" % author)
    log("[analyze] 榜单：%s" % csv_path)
    return csv_path


def cmd_select(args):
    src = Path(args.src).expanduser().resolve()
    if not src.is_file():
        die("榜单 CSV 不存在：%s" % src)
    with src.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        fields = list(reader.fieldnames or [])
        rows = list(reader)
    if "url" not in fields:
        die("榜单 CSV 缺少 url 列：%s" % src)
    chosen = []
    for r in rows:
        try:
            likes = int(float(r.get("likes") or 0))
        except ValueError:
            likes = 0
        if likes < args.min_likes:
            continue
        is_photo = (r.get("type") or "").lower() != "video"
        if args.photo_only and not is_photo:
            continue
        # analyze_tiktok_profile.py 生成的清单统一写 /video/<id>；
        # 图文帖改回 /photo/<id>，gallery-dl 的 TikTok 图文提取器才能稳定取到全部幻灯片。
        if is_photo and "/video/" in (r.get("url") or ""):
            r["url"] = r["url"].replace("/video/", "/photo/")
        chosen.append(r)
    if args.top and args.top > 0:
        chosen = chosen[:args.top]
    if not chosen:
        die("没有作品满足 likes >= %d%s" % (
            args.min_likes, " 且只要图文" if args.photo_only else ""))
    out = Path(args.out).expanduser().resolve() if args.out else src.parent
    out.mkdir(parents=True, exist_ok=True)
    csv_out = out / "selected.csv"
    json_out = out / "selected.json"
    with csv_out.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(chosen)
    json_out.write_text(json.dumps(chosen, ensure_ascii=False, indent=2), encoding="utf-8")
    log("[select] 共 %d 条作品，筛出 %d 条（likes >= %d%s）" % (
        len(rows), len(chosen), args.min_likes,
        "，仅图文" if args.photo_only else ""))
    for i, r in enumerate(chosen, 1):
        log("  %2d. %s  %-5s  %s 赞  %s" % (
            i, r.get("id", ""), r.get("type", ""), r.get("likes", ""), r.get("date", "")))
    log("  下载清单：%s\n  明细：%s" % (csv_out, json_out))
    return csv_out


def cmd_download(args):
    csv_path = Path(args.src).expanduser().resolve()
    if not csv_path.is_file():
        die("下载清单不存在：%s（先跑 select）" % csv_path)
    s = script_path(Path(args.skills_root), "tiktok-image-to-wallpaper", "batch_download.py")
    cmd = [sys.executable, s, "--from", csv_path, "--base-dir",
           Path(args.wallpaper_dir).expanduser().resolve()]
    if args.top:
        cmd += ["--top", str(args.top)]
    run(cmd, env_for("tiktok", args.proxy))
    log("[download] 完成，素材库：%s" % Path(args.wallpaper_dir).expanduser().resolve())


def cmd_batch(args):
    parent = Path(args.wallpaper_dir).expanduser().resolve()
    source = Path(args.source).expanduser().resolve() if args.source else \
        parent / (args.author or "")
    out = batch_dir_of(args, args.author or source.name)
    cover = cover_path(args)
    s = HERE / "make_batches.py"
    cmd = [sys.executable, s, "--source", source, "--out", out,
           "--cover", cover, "--pairs-per-group", str(args.pairs_per_group)]
    order_file = getattr(args, "order_file", None)
    if order_file:
        cmd += ["--order-file", Path(order_file).expanduser().resolve()]
    if args.allow_partial:
        cmd.append("--allow-partial")
    if args.reset_batches:
        cmd.append("--reset")
    if args.dry_run:
        cmd.append("--dry-run")
    run(cmd, os.environ.copy())
    log("[batch] 发布批次目录：%s" % out)
    return out


def group_dirs(batch_dir: Path):
    return sorted((d for d in batch_dir.iterdir()
                   if d.is_dir() and re.fullmatch(r"\d+", d.name)),
                  key=lambda d: d.name)


def validate_group(g: Path, master_md5: str, expected_walls: int):
    covers = [p for p in g.iterdir()
              if p.is_file() and p.name.lower().startswith("cover.")]
    if len(covers) != 1:
        die("组 %s 必须有且只有 1 张 cover.* 封面（实际 %d）" % (g.name, len(covers)))
    if md5(covers[0]) != master_md5:
        die("组 %s 的封面与母版不一致（首图必须是汤姆和杰瑞封面）：%s" % (g.name, covers[0]))
    walls = [p for p in g.iterdir()
             if p.is_file() and not p.name.lower().startswith("cover.")
             and p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}]
    if len(walls) != expected_walls:
        die("组 %s 壁纸 %d 张，应为 %d 张（8+1 规则）" % (g.name, len(walls), expected_walls))
    return covers[0], len(walls)


def cmd_draft(args):
    batch = Path(args.batch_dir).expanduser().resolve()
    if not batch.is_dir():
        die("发布批次目录不存在：%s" % batch)
    skills = Path(args.skills_root).expanduser().resolve()
    s = script_path(skills, "wechat-tietu-draft", "tietu_draft.py")
    master = cover_path(args)
    master_md5 = md5(master)
    expected_walls = args.pairs_per_group * 2
    wechat_env = env_for("wechat", args.proxy)

    groups = group_dirs(batch)
    if not groups:
        die("批次目录里没有编号组目录（先跑 batch）：%s" % batch)

    posted_path = batch / "_state" / "posted.json"
    posted = json.loads(posted_path.read_text(encoding="utf-8")) if posted_path.is_file() else {}
    used_path = skills / "wechat-tietu-draft" / ".state" / "used_posts.json"
    used = json.loads(used_path.read_text(encoding="utf-8")) if used_path.is_file() else {}

    candidates = []
    for g in groups:
        key = os.path.normcase(os.path.abspath(str(g)))
        if g.name in posted and not args.force:
            continue
        if key in used and not args.force:
            continue
        candidates.append(g)
    chosen = candidates[:args.per_day]
    log("[draft] 批次 %s：共 %d 组，已投 %d 组，本次取 %d 组" % (
        batch.name, len(groups), len(groups) - len(candidates), len(chosen)))
    if not chosen:
        log("没有未投过的组，无需新建草稿。")
        return None
    for g in chosen:
        _cover, n = validate_group(g, master_md5, expected_walls)
        log("  %s：%d 张壁纸 + 1 张汤姆杰瑞封面（校验通过）" % (g.name, n))

    # 逐组预检：下游 dry-run 会做「固定封面在第一张」的硬自检
    log("\n=== 预检（逐组 --dry-run，不联网、不上传）===")
    for g in chosen:
        r = run([sys.executable, s, "--dry-run", "--from-dir", g,
                 "--max-images", str(expected_walls), "--cover", master],
                wechat_env, capture=True, check=False, quiet=True)
        out = (r.stdout or "") + (r.stderr or "")
        ok = (r.returncode == 0 and "首图自检" in out and "[OK]" in out
              and ("图片 %d 张" % (expected_walls + 1)) in out)
        log("  %s  %s" % (g.name, "首图自检 [OK]，共 %d 张" % (expected_walls + 1) if ok else "失败"))
        if not ok:
            log(out.rstrip())
            die("组 %s 预检未通过，已中止（不会建任何草稿）" % g.name)
    if args.dry_run:
        log("\n[dry-run] 预检全部通过：将新建 %d 条贴图草稿，每条 1 封面 + %d 张素材。"
            "去掉 --dry-run 即正式执行。" % (len(chosen), expected_walls))
        return None

    # 正式投递前强制联网自检凭证与 IP 白名单
    log("\n=== 凭证 / IP 白名单联网自检 ===")
    chk = run([sys.executable, s, "--check-only"], wechat_env,
              capture=True, check=False, quiet=True)
    log((chk.stdout or "").rstrip())
    if chk.returncode != 0:
        log((chk.stderr or "").rstrip())
        die("公众号凭证自检失败（常见 40164 白名单），未建任何草稿")

    results = []
    report_dir = batch / "_reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    for i, g in enumerate(chosen, 1):
        log("\n--- [%d/%d] 投递组 %s ---" % (i, len(chosen), g.name))
        out_json = report_dir / ("draft_%s.json" % g.name)
        r = run([sys.executable, s, "--from-dir", g,
                 "--max-images", str(expected_walls), "--cover", master,
                 "--out-json", out_json], wechat_env, capture=True, check=False, quiet=True)
        log((r.stdout or "").rstrip())
        if r.returncode != 0:
            log((r.stderr or "").rstrip())
            die("组 %s 建草稿失败，已成功 %d 组；状态已保存，重跑会跳过已投组" % (
                g.name, len(results)))
        record = json.loads(out_json.read_text(encoding="utf-8"))
        posted[g.name] = {
            "time": datetime.now().isoformat(timespec="seconds"),
            "draft_media_id": record.get("draft_media_id", ""),
            "image_count": record.get("image_count", 0),
            "group_dir": str(g),
        }
        posted_path.parent.mkdir(parents=True, exist_ok=True)
        posted_path.write_text(json.dumps(posted, ensure_ascii=False, indent=2), encoding="utf-8")
        results.append({"group": g.name,
                        "draft_media_id": record.get("draft_media_id", ""),
                        "image_count": record.get("image_count", 0)})
    report = {
        "batch": batch.name,
        "time": datetime.now().isoformat(timespec="seconds"),
        "per_day": args.per_day,
        "cover": str(master),
        "cover_md5": master_md5,
        "drafts": results,
        "note": "只到草稿箱，发表由人工在公众号后台/订阅号助手点；本流水线不调用 freepublish/submit",
    }
    report_path = report_dir / ("drafts_%s.json" % datetime.now().strftime("%Y%m%d_%H%M%S"))
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    log("\n[OK] 本次新建 %d 条贴图草稿（每条 1 封面 + %d 张素材 = %d 张，首图均为汤姆和杰瑞封面）" % (
        len(results), expected_walls, expected_walls + 1))
    for x in results:
        log("  %s  media_id=%s  %d 张" % (x["group"], x["draft_media_id"], x["image_count"]))
    log("  汇总：%s" % report_path)
    log("  下一步：去公众号后台 → 草稿箱（或订阅号助手 → 贴图）手动点发表。")
    return report_path


def cmd_all(args):
    if args.url:
        csv_path = cmd_analyze(args)
    elif args.src:
        csv_path = Path(args.src).expanduser().resolve()
    else:
        die("all 需要 --url（重新分析）或 --from（现成榜单 CSV）")
    args.src = str(csv_path)
    selected = cmd_select(args)
    args.src = str(selected)
    if not args.skip_download:
        cmd_download(args)
    args.author = args.author or author_of(args.url or "") or ""
    if args.batch_dir:
        batch = Path(args.batch_dir).expanduser().resolve()
        log("[all] 复用已有批次目录：%s" % batch)
    else:
        args.source = None
        args.order_file = args.src          # selected.csv：点赞高的帖子优先成组
        batch = cmd_batch(args)
    if not args.no_draft:
        args.batch_dir = str(batch)
        cmd_draft(args)


# --------------------------------------------------------------------------- CLI

def build_parser():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--skills-root", default=str(DEFAULT_SKILLS_ROOT),
                        help="skills 根目录，默认 ~/.workbuddy/skills")
    common.add_argument("--wallpaper-dir", default=DEFAULT_WALLPAPER_DIR,
                        help="素材库根目录，默认 %s" % DEFAULT_WALLPAPER_DIR)
    common.add_argument("--batch-root", default=DEFAULT_BATCH_ROOT,
                        help="发布批次根目录，默认 %s" % DEFAULT_BATCH_ROOT)
    common.add_argument("--cover", help="汤姆和杰瑞封面母版，默认取 wechat-tietu-draft/assets/封面.png（唯一指定版，兼容旧名 cover_tom_jerry.png）")
    common.add_argument("--proxy", default=DEFAULT_PROXY,
                        help="TikTok 下载代理，默认 %s（微信 API 会自动直连）" % DEFAULT_PROXY)

    p = argparse.ArgumentParser(description="壁纸日更流水线编排层（下载 / 发帖 skill 保持独立）")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("analyze", parents=[common], help="枚举博主作品并按点赞出榜单")
    a.add_argument("--url", required=True, help="任意能定位到博主的 TikTok 链接")
    a.add_argument("--out", help="榜单输出目录，默认 <wallpaper-dir>/_榜单")
    a.set_defaults(func=cmd_analyze)

    s = sub.add_parser("select", parents=[common], help="按点赞门槛筛选下载清单")
    s.add_argument("--from", dest="src", required=True, help="榜单 CSV")
    s.add_argument("--min-likes", type=int, default=10000, help="点赞下限，默认 10000")
    s.add_argument("--photo-only", action="store_true", help="排除 video 类型，只保留图文")
    s.add_argument("--top", type=int, help="最多保留前 N 条")
    s.add_argument("--out", help="清单输出目录，默认与榜单 CSV 同目录")
    s.set_defaults(func=cmd_select)

    d = sub.add_parser("download", parents=[common], help="批量下载（去重、A/B 命名）")
    d.add_argument("--from", dest="src", required=True, help="selected.csv")
    d.add_argument("--top", type=int, help="只下清单前 N 条")
    d.set_defaults(func=cmd_download)

    b = sub.add_parser("batch", parents=[common], help="生成 8+1 发布组")
    b.add_argument("--source", help="素材库博主目录，默认 <wallpaper-dir>/<author>")
    b.add_argument("--author", default="", help="博主 handle（决定默认 source 与批次名）")
    b.add_argument("--batch-name", help="批次目录名，默认 YYYYMMDD-<author>")
    b.add_argument("--pairs-per-group", type=int, default=DEFAULT_PAIRS_PER_GROUP,
                   help="每组几对 A/B，默认 4 对 = 8 张")
    b.add_argument("--allow-partial", action="store_true", help="余数不足一组也生成")
    b.add_argument("--order-file", help="榜单 CSV（如 selected.csv），按 id 顺序让热门帖先成组")
    b.add_argument("--reset-batches", action="store_true", help="清空消费记录（不删文件）")
    b.add_argument("--dry-run", action="store_true", help="只打印方案")
    b.set_defaults(func=cmd_batch)

    t = sub.add_parser("draft", parents=[common], help="按队列取 N 组建公众号贴图草稿")
    t.add_argument("--batch-dir", required=True, help="发布批次目录（如 .../20261111-clear__display）")
    t.add_argument("--per-day", type=int, default=DEFAULT_PER_DAY, help="本次投几组，默认 4")
    t.add_argument("--pairs-per-group", type=int, default=DEFAULT_PAIRS_PER_GROUP,
                   help="每组几对 A/B，用于校验 8+1")
    t.add_argument("--force", action="store_true", help="忽略已投记录强制重投")
    t.add_argument("--dry-run", action="store_true", help="只预检，不建草稿")
    t.set_defaults(func=cmd_draft)

    allp = sub.add_parser("all", parents=[common], help="一键串起 analyze→select→download→batch→draft")
    allp.add_argument("--url", help="博主链接；不给则用 --from 指定现成榜单 CSV")
    allp.add_argument("--from", dest="src", help="现成榜单 CSV（不跑 analyze 时用）")
    allp.add_argument("--out", help="榜单/清单输出目录")
    allp.add_argument("--min-likes", type=int, default=10000)
    allp.add_argument("--photo-only", action="store_true")
    allp.add_argument("--top", type=int)
    allp.add_argument("--author", default="")
    allp.add_argument("--batch-name")
    allp.add_argument("--source")
    allp.add_argument("--batch-dir", help="指定已有批次目录（跳过 batch 生成）")
    allp.add_argument("--pairs-per-group", type=int, default=DEFAULT_PAIRS_PER_GROUP)
    allp.add_argument("--per-day", type=int, default=DEFAULT_PER_DAY)
    allp.add_argument("--allow-partial", action="store_true")
    allp.add_argument("--reset-batches", action="store_true")
    allp.add_argument("--force", action="store_true")
    allp.add_argument("--skip-download", action="store_true", help="跳过下载，用现有素材")
    allp.add_argument("--no-draft", action="store_true", help="只准备素材，不建草稿")
    allp.add_argument("--dry-run", action="store_true", help="全流程只预检")
    allp.set_defaults(func=cmd_all)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    args.skills_root = str(Path(args.skills_root).expanduser().resolve())
    result = args.func(args)
    # 子命令可能返回 Path（清单/批次目录）；sys.exit(非 int) 会打印对象并以 1 退出，
    # 这里统一收敛成 0/整数退出码。
    return result if isinstance(result, int) else 0


if __name__ == "__main__":
    sys.exit(main())
