#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
split_folders.py - 把一批编号文件夹里的壁纸，按「每组 N 张 + 1 张固定配图」重新分组。

设计红线：
  * 绝不删除任何壁纸文件，只做移动 + 复制配图。
  * 默认强制原样备份；备份失败即中止。
  * 目标文件夹已存在直接报错，不合并、不覆盖。
  * 两阶段移动（先暂存再分发），避免同名冲突与自覆盖。
  * 执行前后核对壁纸总数守恒，并落盘可回滚的映射 CSV。

用法见 SKILL.md，或 python split_folders.py --help
"""

from __future__ import annotations

import argparse
import csv
import re
import shutil
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

IMAGE_EXTS = {
    ".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif",
    ".tif", ".tiff", ".avif", ".heic", ".image",
}
NUM_RE = re.compile(r"_(\d+)")
TAIL_NUM_RE = re.compile(r"^(.*?)(\d+)$")


def die(msg: str) -> None:
    raise SystemExit(f"[ERROR] {msg}")


def natural_key(p: Path):
    """按文件名里的 _NN 数字排序，避免 _10 排到 _2 前面。"""
    m = NUM_RE.search(p.name)
    return (0, int(m.group(1)), p.name.lower()) if m else (1, 0, p.name.lower())


def folder_num(name: str):
    m = re.search(r"(\d+)$", name)
    return int(m.group(1)) if m else None


def image_files(folder: Path) -> list[Path]:
    return sorted(
        (f for f in folder.iterdir() if f.is_file() and f.suffix.lower() in IMAGE_EXTS),
        key=lambda f: f.name.lower(),
    )


def source_folders(root: Path) -> list[Path]:
    folders = [
        d for d in root.iterdir()
        if d.is_dir() and not d.name.startswith(("_", "."))
    ]
    return sorted(folders, key=lambda d: (
        folder_num(d.name) is None, folder_num(d.name) or 0, d.name.lower()
    ))


def detect_cover(groups: list[dict]) -> str | None:
    """配图 = 在 >=2 个文件夹里重复出现的同名图片；壁纸名带唯一 hash，不会重复。"""
    counter: Counter = Counter()
    for g in groups:
        for name in {f.name for f in g["images"]}:
            counter[name] += 1
    repeated = [(name, n) for name, n in counter.items() if n >= 2]
    if not repeated:
        return None
    repeated.sort(key=lambda x: (-x[1], x[0].lower()))
    return repeated[0][0]


def infer_naming(folders: list[Path]) -> tuple[str, int, int]:
    """从现有最大编号文件夹推断 (前缀, 位宽, 最大号)。"""
    for d in reversed(folders):
        m = TAIL_NUM_RE.match(d.name)
        if m:
            return m.group(1), len(m.group(2)), int(m.group(2))
    return "", 2, len(folders)


def fmt_name(prefix: str, width: int, n: int) -> str:
    return f"{prefix}{n:0{width}d}"


def build_plan(groups, per_group, mode, prefix, width, start):
    """返回 [(目标文件夹名, [壁纸Path...], is_new)]。"""
    plan: list[tuple[str, list[Path], bool]] = []

    if mode == "keep-first":
        overflow: list[Path] = []
        for g in groups:
            plan.append((g["path"].name, g["walls"][:per_group], False))
            overflow.extend(g["walls"][per_group:])
        chunks = [overflow[i:i + per_group] for i in range(0, len(overflow), per_group)]
        for i, chunk in enumerate(chunks):
            plan.append((fmt_name(prefix, width, start + i), chunk, True))

    else:  # stream
        all_walls = [f for g in groups for f in g["walls"]]
        chunks = [all_walls[i:i + per_group] for i in range(0, len(all_walls), per_group)]
        if len(chunks) < len(groups):
            die(
                f"stream 模式会留下 {len(groups) - len(chunks)} 个空文件夹，"
                "请调大 --per-group 或改用 --mode keep-first"
            )
        for i, chunk in enumerate(chunks):
            if i < len(groups):
                plan.append((groups[i]["path"].name, chunk, False))
            else:
                plan.append((fmt_name(prefix, width, start + i - len(groups)), chunk, True))
    return plan


def do_backup(root: Path, backup_dir: Path | None, tag: str):
    if backup_dir is None:
        backup_dir = root.parent / f"_{root.name}_原样备份_{tag}"
    if backup_dir.exists():
        die(f"备份目录已存在，拒绝覆盖：{backup_dir}")
    print(f"[1/5] 备份 {root} -> {backup_dir}")
    shutil.copytree(root, backup_dir)
    print(f"      已备份 {sum(1 for _ in backup_dir.rglob('*') if _.is_file())} 个文件")
    return backup_dir


def execute(root: Path, plan, cover_name, cover_src, map_csv: Path, tag: str):
    # 前置检查：新建目标不得已存在
    for name, _files, is_new in plan:
        if is_new and (root / name).exists():
            die(f"目标文件夹已存在，拒绝合并/覆盖：{root / name}")

    staging = root / f".split_tmp_{tag}"
    if staging.exists():
        die(f"暂存目录已存在（可能是上次中断留下的），请先人工检查：{staging}")

    # 计算哪些文件需要换文件夹
    moves: list[tuple[Path, Path, str, bool]] = []  # (原路径, 文件, 目标名, 是否新建)
    for name, files, is_new in plan:
        for f in files:
            if f.parent.name != name:
                moves.append((f, f, name, is_new))

    print(f"[2/5] 两阶段移动：{len(moves)} 个文件需要换组")
    staged: list[tuple[Path, Path, str, str]] = []  # (暂存文件, 原路径, 目标名, 原文件名)
    if moves:
        staging.mkdir()
        for idx, (orig, _f, target, _is_new) in enumerate(moves, 1):
            tmp = staging / f"{idx:05d}{orig.suffix.lower()}"
            shutil.move(str(orig), str(tmp))
            staged.append((tmp, orig, target, orig.name))

    print("[3/5] 分发到目标文件夹并补配图")
    cover_copied: dict[str, bool] = {}
    for name, _files, is_new in plan:
        target_dir = root / name
        if is_new:
            target_dir.mkdir()
        if not (target_dir / cover_name).exists():
            if cover_src is None or not cover_src.exists():
                die(f"找不到母版配图，无法给 {name} 补图：{cover_src}")
            shutil.copy2(cover_src, target_dir / cover_name)
            cover_copied[name] = True
        else:
            cover_copied[name] = False

    rows = []
    for tmp, orig, target, filename in staged:
        dest = root / target / filename
        if dest.exists():
            die(f"目标文件已存在，拒绝覆盖：{dest}")
        shutil.move(str(tmp), str(dest))
        rows.append({
            "group": target,
            "is_new": "1" if any(n == target and new for n, _f, new in plan) else "0",
            "file": filename,
            "from_rel": str(orig.relative_to(root)),
            "to_rel": str(dest.relative_to(root)),
            "cover_copied": cover_name if cover_copied.get(target) else "",
        })

    if staging.exists():
        try:
            staging.rmdir()  # 只删空目录，非空就报错保留
        except OSError:
            die(f"暂存目录非空，已保留供人工检查：{staging}")

    print(f"[4/5] 写映射 CSV：{map_csv}")
    map_csv.parent.mkdir(parents=True, exist_ok=True)
    with map_csv.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=[
            "group", "is_new", "file", "from_rel", "to_rel", "cover_copied"
        ])
        w.writeheader()
        w.writerows(rows)
    return rows


def verify(root: Path, plan, cover_name: str, expected: int):
    print("[5/5] 校验")
    total = 0
    ok = True
    for name, _files, _is_new in plan:
        d = root / name
        walls = [f for f in image_files(d) if f.name != cover_name]
        has_cover = (d / cover_name).exists()
        total += len(walls)
        flag = "OK" if has_cover else "缺配图!"
        if not has_cover:
            ok = False
        print(f"      {name:<20} 壁纸={len(walls):<3} 配图={'1' if has_cover else '0'}  {flag}")
    print(f"      壁纸总数 {total} / 拆分前 {expected}")
    if total != expected:
        ok = False
        print("      [ERROR] 数量不守恒！请用备份或 --rollback 恢复")
    return ok


def rollback(root: Path, csv_path: Path):
    if not csv_path.exists():
        die(f"映射 CSV 不存在：{csv_path}")
    with csv_path.open("r", encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    print(f"回滚 {len(rows)} 条移动记录：{csv_path}")
    for r in reversed(rows):
        src, dst = root / r["to_rel"], root / r["from_rel"]
        if not src.exists():
            print(f"  [跳过] 已不在目标位置：{r['to_rel']}")
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
    new_groups = sorted({r["group"] for r in rows if r["is_new"] == "1"}, reverse=True)
    for name in new_groups:
        d = root / name
        if not d.exists():
            continue
        # 只清理脚本复制进去的配图副本，壁纸一张都不删
        copies = {r["cover_copied"] for r in rows if r["group"] == name and r["cover_copied"]}
        for c in copies:
            f = d / c
            if f.exists():
                f.unlink()
        if not any(d.iterdir()):
            d.rmdir()
            print(f"  已移除新建的空文件夹：{name}")
        else:
            print(f"  [保留] 文件夹非空，未删除：{d}")
    print("回滚完成。")


def main() -> int:
    ap = argparse.ArgumentParser(
        description="按「每组 N 张壁纸 + 1 张固定配图」重新分组编号文件夹"
    )
    ap.add_argument("--root", required=True, help="待整理目录（其直接子文件夹为分组单元）")
    ap.add_argument("--per-group", type=int, default=8, help="每组壁纸张数，默认 8")
    ap.add_argument("--cover", help="母版配图文件路径")
    ap.add_argument("--cover-name", help="显式指定配图文件名（含扩展名）")
    ap.add_argument("--mode", choices=["keep-first", "stream"], default="keep-first")
    ap.add_argument("--start", type=int, help="新文件夹起始编号，默认现有最大号+1")
    ap.add_argument("--prefix", help="编号前缀，如 20261111-")
    ap.add_argument("--width", type=int, help="编号位宽，默认从现有名字推断")
    ap.add_argument("--backup-dir", help="自定义备份目录")
    ap.add_argument("--no-backup", action="store_true", help="跳过备份（不推荐）")
    ap.add_argument("--map-csv", help="自定义映射 CSV 路径")
    ap.add_argument("--dry-run", action="store_true", help="只打印方案，不改动任何文件")
    ap.add_argument("--rollback", metavar="CSV", help="按映射 CSV 回滚")
    args = ap.parse_args()

    root = Path(args.root).expanduser().resolve()
    if not root.is_dir():
        die(f"目录不存在：{root}")

    if args.rollback:
        rollback(root, Path(args.rollback).expanduser().resolve())
        return 0

    if args.per_group < 1:
        die("--per-group 必须 >= 1")

    folders = source_folders(root)
    if not folders:
        die(f"目录下没有可处理的子文件夹：{root}\n请确认源图片已放好，或重新扫描。")

    groups = [{"path": d, "images": image_files(d)} for d in folders]

    # 配图识别
    cover_name = None
    cover_src = None
    if args.cover:
        cover_path = Path(args.cover).expanduser().resolve()
        if not cover_path.is_file():
            die(f"母版配图不存在：{cover_path}")
        cover_name, cover_src = cover_path.name, cover_path
    elif args.cover_name:
        cover_name = args.cover_name
        for g in groups:
            hit = next((f for f in g["images"] if f.name == cover_name), None)
            if hit:
                cover_src = hit
                break
    else:
        cover_name = detect_cover(groups)

    if not cover_name:
        die("探测不到固定配图，请用 --cover 或 --cover-name 显式指定")
    if cover_src is None:
        for g in groups:
            hit = next((f for f in g["images"] if f.name == cover_name), None)
            if hit:
                cover_src = hit
                break
    if cover_src is None:
        die(f"找不到配图母版文件（{cover_name}），请用 --cover 指定路径")

    for g in groups:
        g["walls"] = sorted(
            (f for f in g["images"] if f.name != cover_name), key=natural_key
        )

    total_walls = sum(len(g["walls"]) for g in groups)
    inf_prefix, inf_width, max_num = infer_naming(folders)
    prefix = args.prefix if args.prefix is not None else inf_prefix
    width = args.width if args.width is not None else inf_width
    start = args.start if args.start is not None else max_num + 1

    print("=== 扫描结果 ===")
    for g in groups:
        print(f"  {g['path'].name:<20} 壁纸={len(g['walls']):<3} 配图={sum(1 for f in g['images'] if f.name == cover_name)}")
    print(f"  合计 {len(groups)} 个文件夹 / {total_walls} 张壁纸；配图 = {cover_name}")
    print(f"  命名规则 prefix={prefix!r} width={width} 新组起始号={start} 模式={args.mode}")

    plan = build_plan(groups, args.per_group, args.mode, prefix, width, start)
    new_names = [n for n, _f, is_new in plan if is_new]
    print(f"=== 方案：每组 {args.per_group} 张，共 {len(plan)} 组，新建 {len(new_names)} 个：{', '.join(new_names) or '无'} ===")
    for name, files, is_new in plan:
        label = "新建" if is_new else "现有"
        tail = " (余数组)" if len(files) < args.per_group else ""
        print(f"  [{label}] {name:<20} {len(files):>2} 张{tail}")
        if files:
            print(f"          首张 {files[0].name[:46]}")
            print(f"          末张 {files[-1].name[:46]}")

    if args.dry_run:
        print("\n[dry-run] 未改动任何文件。去掉 --dry-run 即执行。")
        return 0

    tag = datetime.now().strftime("%Y%m%d_%H%M%S")
    map_csv = Path(args.map_csv).expanduser().resolve() if args.map_csv else \
        root.parent / f"{root.name}_拆分映射_{tag}.csv"
    if map_csv.exists():
        die(f"映射 CSV 已存在，拒绝覆盖：{map_csv}")

    if not args.no_backup:
        do_backup(root, Path(args.backup_dir).expanduser().resolve() if args.backup_dir else None, tag)
    else:
        print("[1/5] 已跳过备份 (--no-backup)")

    execute(root, plan, cover_name, cover_src, map_csv, tag)
    ok = verify(root, plan, cover_name, total_walls)
    print(f"\n映射 CSV：{map_csv}")
    print(f"回滚命令：python split_folders.py --root \"{root}\" --rollback \"{map_csv}\"")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
