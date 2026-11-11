#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把存量图集从旧命名 N_wallpaper.<ext> 迁移到 v1.9.0 的 A/B 成对命名。

    1_wallpaper.jpg  -> 1_A.jpg   （A = 桌面展示图）
    2_wallpaper.jpg  -> 1_B.jpg   （B = 同一张壁纸的原图）
    3_wallpaper.jpg  -> 2_A.jpg
    4_wallpaper.jpg  -> 2_B.jpg
    ...

安全设计：
  · 默认 --dry-run 只打印计划，一个文件都不动；必须显式加 --apply 才真改。
  · cover.* 固定封面图不参与编号，保持原名。
  · 目标名已存在（目录里已有 A/B 命名文件）时跳过整个目录并报警，绝不覆盖。
  · 两阶段重命名（先改成 .abtmpNNNN，再改成目标名），避免同目录内互相覆盖。
  · 只处理文件名形如 <数字>_wallpaper.<ext> 的文件，其它文件一律不动。

用法：
  python rename_to_ab.py                          # 预览 E:\\图片\\壁纸 下全部存量目录
  python rename_to_ab.py "E:/图片/壁纸/vexaro.4k"  # 只预览某个博主
  python rename_to_ab.py --apply                 # 确认无误后再真正改名
"""
import argparse
import os
import re
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

OLD_RE = re.compile(r"^(\d+)_wallpaper\.(jpg|jpeg|png|webp|bmp|gif|image|heic|avif|mp4|mov)$", re.I)
DEFAULT_ROOT = r"E:\图片\壁纸"


def plan_dir(directory):
    files = [f for f in os.listdir(directory)
             if OLD_RE.match(f) and os.path.isfile(os.path.join(directory, f))]
    files.sort(key=lambda f: int(OLD_RE.match(f).group(1)))
    plan = []
    for i, f in enumerate(files, 1):
        ext = os.path.splitext(f)[1].lower()
        new = "%d_%s%s" % ((i - 1) // 2 + 1, "A" if i % 2 else "B", ext)
        plan.append((f, new))
    return plan


def apply_dir(directory, plan):
    for i, (old, _) in enumerate(plan):
        os.rename(os.path.join(directory, old),
                  os.path.join(directory, ".abtmp%04d" % i))
    for i, (_, new) in enumerate(plan):
        os.rename(os.path.join(directory, ".abtmp%04d" % i),
                  os.path.join(directory, new))


def main():
    ap = argparse.ArgumentParser(description="存量壁纸目录迁移为 1_A/1_B 成对命名")
    ap.add_argument("root", nargs="?", default=DEFAULT_ROOT, help="壁纸根目录")
    ap.add_argument("--apply", action="store_true", help="真正执行改名（默认只预览）")
    args = ap.parse_args()

    root = os.path.abspath(args.root)
    if not os.path.isdir(root):
        print("ERROR: 目录不存在:", root)
        return 1

    dirs = []
    for cur, subdirs, files in os.walk(root):
        if ".originals" in cur:
            continue
        if any(OLD_RE.match(f) for f in files):
            dirs.append(cur)
    dirs.sort()

    total_files = 0
    changed_dirs = 0
    skipped = []
    for d in dirs:
        plan = plan_dir(d)
        if not plan:
            continue
        conflicts = [new for _, new in plan
                     if os.path.exists(os.path.join(d, new)) and new not in [o for o, _ in plan]]
        if conflicts:
            skipped.append((d, "目标名已存在：" + ", ".join(conflicts[:3])))
            continue
        total_files += len(plan)
        changed_dirs += 1
        rel = os.path.relpath(d, root)
        print("[%s] %d 张" % (rel, len(plan)))
        for old, new in plan[:4]:
            print("    %s -> %s" % (old, new))
        if len(plan) > 4:
            print("    ... 共 %d 张" % len(plan))
        if args.apply:
            apply_dir(d, plan)

    print("\n合计：%d 个目录 / %d 个文件" % (changed_dirs, total_files))
    for d, why in skipped:
        print("  跳过 %s：%s" % (os.path.relpath(d, root), why))
    if args.apply:
        print("已执行改名（未删除任何文件）。")
    else:
        print("这是预览，未改动任何文件。确认后加 --apply 执行。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
