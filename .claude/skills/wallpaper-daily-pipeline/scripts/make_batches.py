#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
make_batches.py - 把素材库里按帖子归档的 A/B 成对壁纸，复制式拆成「8 张 + 1 张封面」发布组。

与 wallpaper-batch-splitter 的关系（同一个 8+1 规则，不同落地方式）：
  * splitter 是「移动式重排」已有编号文件夹，适合一次性整理本地散图；
  * 流水线里改用「复制式分批」，原因有三：
      1. 素材库必须保留（每帖原图要留档），不能移动/删除；
      2. 跨帖子文件都叫 1_A.jpg / 1_B.jpg，stream 重排必然撞名；
      3. A/B 必须成对不拆散，且组号要连续、可每天增量追加。
  * 本脚本因此不改动 wallpaper-batch-splitter，两者可并存。

规则（用户 2026-11-11 拍板）：
  每组 4 对 A/B = 8 张壁纸（1_A/1_B ... 4_A/4_B），A=桌面展示图、B=同款壁纸原图；
  外加 1 张固定封面 cover.png（汤姆和杰瑞），下游 wechat-tietu-draft 会忽略 cover.*
  并把同一张图插到第一张，最终每条贴图草稿 = 1 封面 + 8 素材 = 9 张。

安全红线：
  * 只复制，绝不移动/删除源文件；
  * 目标组目录已存在直接报错，不覆盖；
  * 不足 4 对的余数默认留到下次（--allow-partial 才生成残组）；
  * 已消费的源文件记在 consumed.json，重跑不会重复成组；
  * 每组写 manifest.json，批次写 batches.json，逐组校验 8+1 与封面 md5。
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tif", ".tiff", ".avif", ".heic"}
COVER_BASENAME = "cover"          # 下游按 "cover." 前缀自动忽略
NUM_RE = re.compile(r"^(\d+)")
PAIR_RE = re.compile(r"^\d+[_-]([ABab])\.")


def die(msg: str) -> None:
    raise SystemExit("[ERROR] " + msg)


def md5(path: Path) -> str:
    h = hashlib.md5()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def natural_key(path: Path):
    """与 wechat-tietu-draft 同一口径：先数字、再 A/B，最后文件名兜底。"""
    name = path.name
    m = NUM_RE.match(name)
    num = int(m.group(1)) if m else 10 ** 9
    pm = PAIR_RE.match(name)
    suffix = pm.group(1).upper() if pm else ""
    return (num, suffix, name.lower())


def rel(path: Path, root: Path) -> str:
    return os.path.relpath(str(path), str(root)).replace("\\", "/")


def pairs_in(folder: Path):
    """返回 [(组号, [A, B])]，只收「恰好 A+B 两张」的完整对；单张/异常单独返回警告。"""
    buckets: dict[int, list[Path]] = {}
    for f in sorted(folder.iterdir(), key=lambda p: p.name.lower()):
        if not f.is_file() or f.suffix.lower() not in IMAGE_EXTS:
            continue
        if f.name.lower().startswith(COVER_BASENAME + "."):
            continue
        m = NUM_RE.match(f.name)
        num = int(m.group(1)) if m else 10 ** 9
        buckets.setdefault(num, []).append(f)
    good, skipped = [], []
    for num in sorted(buckets):
        files = sorted(buckets[num], key=natural_key)
        if len(files) != 2:
            skipped.append((num, [f.name for f in files]))
            continue
        suffixes = [PAIR_RE.match(f.name).group(1).upper() if PAIR_RE.match(f.name) else "" for f in files]
        if suffixes != ["A", "B"]:
            skipped.append((num, [f.name for f in files]))
            continue
        good.append((num, files))
    return good, skipped


def load_state(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"files": [], "groups": {}}


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def next_group_number(out: Path, width: int) -> int:
    mx = 0
    if out.is_dir():
        for d in out.iterdir():
            if d.is_dir() and re.fullmatch(r"\d{%d}" % width, d.name):
                mx = max(mx, int(d.name))
    return mx + 1


def main() -> int:
    ap = argparse.ArgumentParser(description="A/B 成对壁纸 → 8+1 发布组（复制式，不动素材库）")
    ap.add_argument("--source", required=True, help="素材库博主目录，如 E:/图片/壁纸/clear__display")
    ap.add_argument("--out", required=True, help="发布批次根目录，如 E:/图片/发布批次/20261111-clear__display")
    ap.add_argument("--cover", required=True, help="固定封面母版（汤姆和杰瑞），如 .../assets/封面.png")
    ap.add_argument("--pairs-per-group", type=int, default=4, help="每组几对 A/B，默认 4 对 = 8 张")
    ap.add_argument("--allow-partial", action="store_true", help="余数不足一组时也生成残组（默认留到下次）")
    ap.add_argument("--order-file", help="榜单 CSV（如 selected.csv）：按其中 id 顺序排帖子，热门优先")
    ap.add_argument("--width", type=int, default=4, help="组号位宽，默认 4 → 0001")
    ap.add_argument("--reset", action="store_true", help="清空消费记录（不删任何文件，仅重算状态）")
    ap.add_argument("--dry-run", action="store_true", help="只打印方案，不写任何文件")
    args = ap.parse_args()

    source = Path(args.source).expanduser().resolve()
    out = Path(args.out).expanduser().resolve()
    cover = Path(args.cover).expanduser().resolve()
    if not source.is_dir():
        die("素材库目录不存在：%s" % source)
    if not cover.is_file():
        die("固定封面母版不存在：%s" % cover)
    if args.pairs_per_group < 1:
        die("--pairs-per-group 必须 >= 1")

    cover_ext = cover.suffix.lower()
    cover_name = COVER_BASENAME + cover_ext
    cover_hash = md5(cover)
    state_path = out / "_state" / "consumed.json"
    state = {"files": [], "groups": {}} if args.reset else load_state(state_path)
    consumed = set(state.get("files", []))

    # 帖子顺序：给了榜单 CSV 就按榜单 id 顺序（点赞降序、热门先发），否则按目录名。
    order: list[str] = []
    if args.order_file:
        of = Path(args.order_file).expanduser().resolve()
        if not of.is_file():
            die("榜单 CSV 不存在：%s" % of)
        with of.open(newline="", encoding="utf-8-sig") as fh:
            order = [str(r.get("id") or "").strip() for r in csv.DictReader(fh)]
    rank = {pid: i for i, pid in enumerate(order) if pid}

    def post_id(name: str) -> str:
        m = re.match(r"(\d{10,})", name)
        return m.group(1) if m else name

    post_dirs = sorted(
        (d for d in source.iterdir() if d.is_dir() and not d.name.startswith((".", "_"))),
        key=lambda d: (rank.get(post_id(d.name), 10 ** 9), d.name.lower()),
    )
    skipped_pairs: list[str] = []
    total_pairs = 0
    per = args.pairs_per_group
    chunks: list[list[tuple[str, int, list[Path]]]] = []
    tail: list[tuple[str, int, list[Path]]] = []
    pending_pairs = 0
    for d in post_dirs:
        pairs, bad = pairs_in(d)
        total_pairs += len(pairs)
        for num, names in bad:
            skipped_pairs.append("%s/#%d:%s" % (d.name, num, ",".join(names)))
        fresh: list[tuple[str, int, list[Path]]] = []
        for num, files in pairs:
            rels = [rel(f, source) for f in files]
            if all(r in consumed for r in rels):
                continue
            if any(r in consumed for r in rels):
                skipped_pairs.append("%s/#%d:部分已消费，跳过整对" % (d.name, num))
                continue
            fresh.append((d.name, num, files))
        pending_pairs += len(fresh)
        # 帖内优先装满整组，尽量不跨帖混搭；帖尾不足一组的对进 tail 池，最后统一拼组。
        k = 0
        while len(fresh) - k >= per:
            chunks.append(fresh[k:k + per])
            k += per
        tail.extend(fresh[k:])
    remainder = len(tail) % per
    for i in range(0, len(tail) - remainder, per):
        chunks.append(tail[i:i + per])
    if remainder and args.allow_partial:
        chunks.append(tail[len(tail) - remainder:])

    start = next_group_number(out, args.width)
    print("=== 扫描结果 ===")
    print("  素材库       : %s" % source)
    print("  发布批次     : %s" % out)
    print("  封面母版     : %s (md5 %s…)" % (cover, cover_hash[:12]))
    print("  帖子目录     : %d 个 / 完整 A/B 对 %d 对（已消费/跳过 %d 对）" % (
        len(post_dirs), total_pairs, total_pairs - pending_pairs))
    print("  待分组       : %d 对 → %d 组（每组 %d 对 = %d 张）%s" % (
        pending_pairs, len(chunks), per, per * 2,
        "，余 %d 对留待下次" % remainder if remainder and not args.allow_partial else ""))
    if skipped_pairs:
        print("  跳过的非成对文件（前 8 条）：")
        for s in skipped_pairs[:8]:
            print("    - %s" % s)
        if len(skipped_pairs) > 8:
            print("    …共 %d 条" % len(skipped_pairs))

    plan = []
    for i, chunk in enumerate(chunks):
        name = ("%%0%dd" % args.width) % (start + i)
        plan.append((name, chunk))
        sources = sorted({c[0] for c in chunk})
        print("  [%s] %d 对 / %d 张，来自 %s" % (
            name, len(chunk), sum(len(c[2]) for c in chunk), ", ".join(sources)))

    if not plan:
        print("\n没有可生成的新组（素材已全部消费或不足一组）。")
        return 0
    if args.dry_run:
        print("\n[dry-run] 未写任何文件。去掉 --dry-run 即生成分组。")
        return 0

    for name, _ in plan:
        if (out / name).exists():
            die("目标组目录已存在，拒绝覆盖：%s" % (out / name))
    out.mkdir(parents=True, exist_ok=True)

    created = []
    for name, chunk in plan:
        gd = out / name
        gd.mkdir()
        manifest = {
            "group": name,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "cover": cover_name,
            "cover_md5": cover_hash,
            "pairs_per_group": per,
            "sources": [],
        }
        idx = 0
        for post_name, _num, files in chunk:
            idx += 1
            for f in files:
                pm = PAIR_RE.match(f.name)
                suffix = pm.group(1).upper() if pm else "A"
                target = gd / ("%d_%s%s" % (idx, suffix, f.suffix.lower()))
                shutil.copy2(f, target)
                manifest["sources"].append({
                    "from": rel(f, source),
                    "post": post_name,
                    "to": target.name,
                })
        shutil.copy2(cover, gd / cover_name)
        (gd / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        walls = [p for p in gd.iterdir()
                 if p.is_file() and p.suffix.lower() in IMAGE_EXTS
                 and not p.name.lower().startswith(COVER_BASENAME + ".")]
        has_cover = (gd / cover_name).exists() and md5(gd / cover_name) == cover_hash
        if len(walls) != per * 2 or not has_cover:
            die("组 %s 校验失败：壁纸 %d 张（应 %d），封面 %s" % (
                name, len(walls), per * 2, "OK" if has_cover else "缺失/不一致"))
        created.append({"group": name, "walls": len(walls), "cover": cover_name,
                        "sources": len(manifest["sources"])})
        print("  [OK] %s：%d 张壁纸 + 1 张 %s（首图必须是汤姆和杰瑞封面）" % (
            name, len(walls), cover_name))
        # 逐组落盘：中途异常也不会让已复制的组在下次重跑时被重复消费
        for item in manifest["sources"]:
            consumed.add(item["from"])
        state["files"] = sorted(consumed)
        state.setdefault("groups", {})[name] = {
            "created_at": manifest["created_at"],
            "walls": len(walls), "cover": cover_name,
        }
        save_state(state_path, state)

    batch_index = {
        "batch": out.name,
        "source": str(source),
        "cover_master": str(cover),
        "cover_md5": cover_hash,
        "pairs_per_group": per,
        "walls_per_group": per * 2,
        "total_groups": next_group_number(out, args.width) - 1,
        "created_groups": [c["group"] for c in created],
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    (out / "batches.json").write_text(
        json.dumps(batch_index, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n共生成 %d 组，批次目录共 %d 组；消费清单 %s；索引 %s" % (
        len(created), batch_index["total_groups"], state_path, out / "batches.json"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
