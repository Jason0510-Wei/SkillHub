#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从 TikTok 链接下载图片/视频，按下面的目录结构落盘：

    <base_dir>/<博主>/<帖子ID>-<年月日YYYYMMDD>/

其中：
  - <base_dir> 默认是执行目录下的「壁纸」文件夹（可用第 2 个参数覆盖）；
  - <博主>    自动从链接识别 TikTok handle（@username），识别不到时退化为 "tiktok"；
  - <帖子ID>  TikTok 作品 ID，放在最前便于按作品检索；
  - <年月日>  本条链接保存时的本地日期（YYYYMMDD 连写，v1.8.0 起，替代旧的秒级时间戳）。

【默认行为：原图直出，零转码 + A/B 成对命名（v1.9.0 起）】
  下载到的原始媒体文件不经过任何重编码，直接按 TikTok 幻灯片原始顺序
  （gallery-dl 文件名里的 _NN 序号）两两成对重命名为
     1_A.<ext>  1_B.<ext>  2_A.<ext>  2_B.<ext> …
  同一对 A/B 是同一张壁纸：A = 桌面展示图（手机锁屏效果），B = 壁纸原图。
  奇数位为 A、偶数位为 B；第 i 张对应第 (i+1)//2 组。
  保留原始分辨率与原始编码，无二次 JPEG 压缩，也不再产生 .originals/ 子目录。
  （实测：源图常有 1536px 甚至 5736×8192，旧的默认封顶 1080 会损失大量细节。）
  加 --legacy-naming 可回到旧命名 1_wallpaper.<ext>, 2_wallpaper.<ext> …
  目录里的 cover.*（固定封面图）不参与编号，保持原文件名。

【可选：显式转码】
  只有显式加 --convert 才走旧的转码流程（convert_tiktok_image.py）：
  转成宽度 ≤1080 的 JPEG，原始下载件移入 .originals/ 留档。
  --4k 与 --convert 同用时把长边升采样到 3840（仅尺寸放大、细节不增）。
  --4k 单独给出时会自动隐含启用 --convert。

  历史参数 --no-convert 保留为兼容 no-op（现在默认就是不转码）。

下载器优先级：
  1. gallery-dl（首选）：TikTok 提取器成熟，能处理「图文/幻灯片」帖子（/photo/ 路径），
     并自动解 TikTok 的 JS 挑战（反爬），通常无需登录 Cookie 即可下到图片。
  2. yt-dlp（兜底）：仅对 yt-dlp 支持的常见视频链接生效；对 /photo/ 图文帖会报
     Unsupported URL，因此只作为 gallery-dl 失败时的备胎。

依赖：gallery-dl（pip install gallery-dl）。若未安装会自动尝试 pip 安装。
本机若走代理，gallery-dl/requests 会自动读取 HTTP_PROXY/HTTPS_PROXY 环境变量。

用法：
  python3 download_tiktok.py <tiktok_url> [base_dir] [--convert] [--4k]
默认 base_dir = 当前目录下的「壁纸」；默认不转码、原图按编号直出。
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
# 普通看图软件可能打不开的私有/新格式（仅用于提示，不影响行为）
UNUSUAL_EXT = ('.image', '.heic', '.avif')


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


def slide_index(fname):
    """从 gallery-dl 命名的媒体文件里取出幻灯片序号（<postid>_NN ...）。"""
    stem = os.path.splitext(fname)[0]
    if stem.endswith("_wallpaper"):
        stem = stem[:-len("_wallpaper")]
    m = re.match(r'^(\d+)_(\d+)', stem)        # gallery-dl: <postid>_<NN>
    if m:
        return int(m.group(2))
    m = re.search(r'_(\d+)', stem)             # 兜底：任意 _数字
    if m:
        return int(m.group(1))
    return 0


def pair_name(i, ext):
    """第 i 张（1-based）→ A/B 成对文件名。

    TikTok 壁纸帖的原始顺序是「展示图, 原图」成对出现：
      1 -> 1_A（桌面展示图）  2 -> 1_B（同一张壁纸的原图）
      3 -> 2_A                4 -> 2_B ...
    """
    return "%d_%s%s" % ((i - 1) // 2 + 1, "A" if i % 2 else "B", ext)


NUMBERED_RE = re.compile(r'^\d+_(?:wallpaper|[ABab])\.', re.I)


def renumber_media(target, files, legacy=False):
    """按原幻灯片顺序重命名：默认 1_A/1_B、2_A/2_B…；legacy=True 时用 1_wallpaper…

    保留每个文件的原始扩展名（默认原图模式下不转码，扩展名各异）。
    cover.* 视为固定封面图，不参与编号。两阶段重命名，避免同目录内互相覆盖。
    """
    files = [f for f in files
             if os.path.isfile(os.path.join(target, f))
             and not f.lower().startswith("cover.")]
    if not files:
        return 0
    files.sort(key=slide_index)
    tmp_map = []
    for i, f in enumerate(files, 1):
        ext = os.path.splitext(f)[1].lower() or ".jpg"
        src = os.path.join(target, f)
        tmp = os.path.join(target, f".rk{i:04d}{ext}")
        os.rename(src, tmp)
        name = ("%d_wallpaper%s" % (i, ext)) if legacy else pair_name(i, ext)
        tmp_map.append((tmp, os.path.join(target, name)))
    for tmp, final in tmp_map:
        os.rename(tmp, final)
    return len(files)


def renumber(target, legacy=False):
    """兼容旧调用：对目录下已编号的文件重新按 A/B 成对编号。"""
    walls = [f for f in os.listdir(target)
             if NUMBERED_RE.match(f)
             and os.path.isfile(os.path.join(target, f))]
    return renumber_media(target, walls, legacy)


def main():
    args = sys.argv[1:]
    url = None
    base_dir = "壁纸"
    convert = False
    fourk = False
    legacy_naming = False
    for a in args:
        if a == "--convert":
            convert = True
        elif a == "--4k":
            fourk = True
            convert = True            # 4K 属于转码模式，隐含启用
        elif a == "--legacy-naming":
            legacy_naming = True
        elif a == "--no-convert":
            # 兼容旧参数：现在默认就是不转码，退化为 no-op
            pass
        elif url is None:
            url = a
        else:
            base_dir = a

    if not url:
        print("usage: download_tiktok.py <tiktok_url> [base_dir] [--convert] [--4k]")
        sys.exit(2)

    blogger = blogger_from_url(url)
    post_id = None
    pm = re.search(r'/(?:phot|vide)o/(\d+)', url)
    if pm:
        post_id = pm.group(1)
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

    # 每个帖子一个独立文件夹：<帖子ID>-<年月日YYYYMMDD>（v1.8.0 起）
    # 帖子ID 放最前，日期只到天；同一帖子同日重复下载时追加 _1/_2，避免合并
    day = datetime.datetime.now().strftime("%Y%m%d")
    folder_name = f"{post_id}-{day}" if post_id else day
    target = os.path.join(base_dir, blogger, folder_name)
    if os.path.exists(target):           # 同帖子同日重复时追加序号
        k = 1
        while os.path.exists(f"{target}_{k}"):
            k += 1
        target = f"{target}_{k}"
    os.makedirs(target, exist_ok=True)
    originals_dir = os.path.join(target, ".originals")

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

    # ---------- 默认：原图直出，零转码，直接按序编号 ----------
    if not convert:
        raw = [f for f in os.listdir(target)
               if os.path.isfile(os.path.join(target, f))
               and os.path.splitext(f)[1].lower() in MEDIA_EXT
               and not NUMBERED_RE.match(f)
               and not f.lower().startswith("cover.")]
        n = renumber_media(target, raw, legacy_naming)
        if n:
            if legacy_naming:
                print(f"RENAMED {n} -> 1..{n}_wallpaper.<原格式>（旧命名，未转码）")
            else:
                print(f"RENAMED {n} -> 1_A/1_B, 2_A/2_B ... 共 {n} 张"
                      f"（A=桌面展示图，B=壁纸原图；未转码，保留原始分辨率）")
        odd = [f for f in raw if os.path.splitext(f)[1].lower() in UNUSUAL_EXT]
        if odd:
            print(f"提示: {len(odd)} 个文件是私有/新格式（.image/.heic/.avif 等），"
                  "普通看图软件可能打不开；如需转成通用 JPG 请加 --convert")
        print("DONE (原图模式):", target)
        return

    # ---------- 可选：显式 --convert 才走转码 ----------
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
        if NUMBERED_RE.match(f):   # 已编号的成品，跳过
            continue
        out = os.path.join(target, os.path.splitext(f)[0] + "_wallpaper.jpg")
        conv_argv = [sys.executable, conv, fp, out]
        if fourk:
            conv_argv.append("--4k")
        r = subprocess.run(conv_argv, capture_output=True, text=True)
        if r.returncode == 0 and os.path.exists(out):
            ok_conv += 1
            # 转成功则把原始下载件移入 .originals/（不删除，规避环境批量删除保护）
            try:
                if not os.path.isdir(originals_dir):
                    os.makedirs(originals_dir, exist_ok=True)
                shutil.move(fp, os.path.join(originals_dir, os.path.basename(fp)))
            except OSError:
                pass
        else:
            print("convert fail:", f, "->", (r.stderr or '')[-300:])
    print(f"CONVERTED {ok_conv} -> 壁纸已存于 {target}" + (" [4K]" if fourk else "") +
          ("（原始下载件已移入 .originals/）" if ok_conv else ""))

    n = renumber(target, legacy_naming)
    if n:
        mode = "1..%d_wallpaper.jpg（旧命名）" % n if legacy_naming else "1_A/1_B, 2_A/2_B ...（A=展示图 B=原图）"
        print(f"RENAMED {n} -> 已按原顺序编号为 {mode}")


if __name__ == '__main__':
    main()
