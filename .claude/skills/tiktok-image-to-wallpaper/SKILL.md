---
name: tiktok-image-to-wallpaper
description: >-
  把 TikTok 的图片变成手机壁纸 JPEG。三种入口：① 用户直接丢来 TikTok 链接 —— 先用 gallery-dl 下载链接里的图片，再逐个转成手机壁纸 JPEG；② 用户给本地 .image 文件（TikTok 私有 VVC/HEIF 格式，普通软件打不开）—— 直接转；③「博主作品分析 + 批量下载」—— 用户丢来任意一条能定位到博主的 TikTok 链接（帖子/@主页/短链），脚本先用 yt-dlp 定位博主主页、枚举其全部作品并按「受欢迎程度（点赞/播放/评论）」降序排出排行榜，发回给用户，由用户决定下载哪些，再用 batch_download.py 批量下载转壁纸。触发词：tiktok 链接转壁纸、tiktok 图片打不开、转成手机壁纸、TikTok image 转 jpg、.image 文件、分析这个博主的作品、把博主所有作品按热度排个序、批量下载博主壁纸。解码依赖本机 ffmpeg 的 vvc 解码器；下载依赖 gallery-dl（首选，自动解 TikTok JS 挑战、支持 /photo/ 图文帖）/ yt-dlp（兜底，兼枚举全量作品）；分析依赖 yt-dlp。下载结果按 壁纸/<博主>/<时间戳YYYYMMDDHHMM>/ 目录归档。
agent_created: true
version: 1.6.1
display_name: "TikTok图片转手机壁纸"
display_name_en: "TikTok Image to Phone Wallpaper"
description_zh: "从 TikTok 链接下载图片或读取本地 .image，转换为手机壁纸 JPEG。"
description_en: "Download images from a TikTok link (or read a local .image) and convert to phone-sized JPEG wallpapers."
visibility: "user"
---

# TikTok 图片 → 手机壁纸 JPEG

> ⚠️ **前置依赖**：这套流程依赖本机 ffmpeg 带 `vvc` 解码器（你这台已具备）；换机器先跑 `ffmpeg -decoders | grep vvc` 自检，没有就换带 VVC 解码的 ffmpeg 版本。下载环节还需要 **gallery-dl**（`pip install gallery-dl`，脚本首次运行自动装；它内置 TikTok 提取器、会自动解 TikTok 的 JS 反爬挑战，且支持 `/photo/` 图文/幻灯片帖）。yt-dlp 仅作为 gallery-dl 失败时的兜底。

## 这是什么

TikTok 保存的 `*.image` 文件其实是 **VVC（H.266）编码的 HEIF 容器**（brand `vvic`，编码项 `vvc1`），
几乎没有任何看图软件内置 VVC 解码器，所以会“打不开”。本 skill 用 ffmpeg 的 `vvc` 解码器把它还原成普通 JPEG；
如果用户给的是 TikTok **链接**，则先用 gallery-dl 把帖子里的图片下载下来，再转。

## 前置条件

- **ffmpeg**（建议 n8.1+，含原生 `vvc` 解码器）。自检：
  ```bash
  ffmpeg -hide_banner -decoders 2>/dev/null | grep -i " vvc "
  ```
- **gallery-dl**（下载用，首选）：`pip install gallery-dl`，或让脚本首次运行时自动装。它内置 TikTok 提取器，支持图文/幻灯片帖子（`/photo/`）并能自动过 JS 挑战，通常无需登录 Cookie。

## 使用流程

### 入口 A：用户给了 TikTok 链接（最常见）

**一条命令搞定**，自动按「博主 / 下载时间」分层归档：

```bash
python3 "<skill_dir>/scripts/download_tiktok.py" "<tiktok_url>"
```

脚本内部完成：
1. 用 gallery-dl（兜底 yt-dlp）下载链接里的图片/视频；
2. 自动识别博主——优先从链接里的 `@username` 取，取不到就从 gallery-dl 的下载目录（`tiktok/<user>/`）反推 TikTok handle；
3. 按**保存时间 + 帖子ID**在「壁纸」目录下建文件夹，落盘结构：

   ```
   当前目录/壁纸/<博主>/<时间戳YYYYMMDD_HHMMSS>_<帖子ID>/
   例：壁纸/vexaro.4k/20261103_120050_7695439146944400660/
   ```
   （每个博主一个文件夹，**每个帖子一个独立文件夹**——帖子ID写进文件夹名，避免同分钟内多次下载互相覆盖/合并到同一文件夹）
4. 把每个文件转成手机壁纸 JPEG（**默认宽度 ≤1080**；加 `--4k` 则长边升采样到 3840），成功后再把原始下载件移入该文件夹下的 `.originals/` 子目录（**不直接删除**，以规避本环境的批量删除保护机制），文件夹里只留 `<原名>_wallpaper.jpg`。**转换结束会打印每张的实际分辨率**（如 `1080x1920`），方便核对到底几 K。
5. **按原顺序编号**：同一帖子里的多张壁纸会按 TikTok 幻灯片的原始顺序（gallery-dl 文件名里的 `_NN` 序号）重命名为 `1_wallpaper.jpg`、`2_wallpaper.jpg`、`3_wallpaper.jpg` …，文件名中的 caption / hash 会被丢弃，仅保留位置序号，便于按序浏览与引用。

- 想自定义根目录（不用默认「壁纸」）：第 2 个参数传路径，如 `"D:/壁纸"`。
- 只想下载、不转壁纸（保留原始文件）：末尾加 `--no-convert`。
- 想要 4K 尺寸输出：末尾加 `--4k`（长边升采样到 3840）。**注意**：源本就 <4K（TikTok 图文帖源通常只有 942–1080px 宽），`--4k` 是**插值放大**，仅尺寸到 4K、细节不会凭空增加；若需要真·4K 细节，需接 AI 超分（Real-ESRGAN 等），属后续增强。

2. 用 `present_files` 把 `壁纸/<博主>/<时间戳>/` 里的 JPG 展示给用户。

> 若帖子是视频（slideshow 被当成视频），convert 会取首帧转成一张壁纸；这种情况提示用户“该链接是视频，已取首帧”。

### 入口 B：用户给了本地 `.image` 文件

```bash
python3 "<skill_dir>/scripts/convert_tiktok_image.py" "C:/path/to/xxx.image"
```
- 第二个参数可指定输出 JPG 路径；省略时输出到输入同目录，名为 `<原名>_wallpaper.jpg`。
- 输出规格：JPEG，宽度 ≤1080（9:16 手机壁纸比例，保持原比例，不放大），质量 `-q:v 3`。

### 入口 C：用户想「分析某博主的全部作品 → 我挑哪些 → 批量下载」（v1.6.0 新增）

典型诉求：「我给你发一个链接，你直接找到博主的首页，把他的作品按最受欢迎程度降序发给我，我来定哪些要批量下载。」

整条链路分两步脚本：

**第 1 步 · 分析博主全部作品（只抓榜单，不下图）**

```bash
python3 "<skill_dir>/scripts/analyze_tiktok_profile.py" "<tiktok_url>" [--metric likes|views|comments] [--top N] [--out DIR]
```

- 入参 `tiktok_url`：任意能定位到博主的链接 —— 单条帖子（`/photo/ID` 或 `/video/ID`）、`@username` 主页、或 `vt.tiktok.com` 短链都行。脚本会：
  1. 从链接取 `@handle`，再向 yt-dlp 取该博主的 `secUid`（用帖子链接取最稳，失败自动重试）；
  2. 用 `yt-dlp --flat-playlist` 枚举该博主**全部**作品（gallery-dl 的 `/posts` 对部分账号分页会卡在第一页、抓不全，故改用 yt-dlp 枚举）；
  3. 按 `--metric`（默认 `likes` 点赞；可换 `views` 播放 / `comments` 评论）降序排名。
- 输出：控制台打印排行榜（超过 60 条时只打印前 60，完整清单看文件），并在 `--out`（默认当前目录）落盘两份清单：
  - `<博主>_analysis.csv`（utf-8-sig，含 rank / author / id / type / likes / views / comments / date / caption / url）
  - `<博主>_analysis.json`
- 这两份清单就是第 2 步批量下载的输入。

**第 2 步 · 按用户挑选批量下载转壁纸**

把第 1 步的 CSV 交给 `batch_download.py`，按排名区间或序号挑选：

```bash
# 下载榜单前 10 名
python3 "<skill_dir>/scripts/batch_download.py" --from "<博主>_analysis.csv" --top 10 [--base-dir DIR] [--4k]
# 只下载第 2、5、8 名
python3 "<skill_dir>/scripts/batch_download.py" --from "<博主>_analysis.csv" --pick 2,5,8 [--base-dir DIR] [--4k]
# 也可以直接丢若干条链接（跳过分析）
python3 "<skill_dir>/scripts/batch_download.py" "<url1>" "<url2>" ... [--base-dir DIR] [--4k]
```

- `--base-dir` 自定义归档根目录（默认「壁纸」）；`--4k` 透传给 `download_tiktok.py`（长边升采样到 3840）。
- 每条链接都会复用入口 A 的 `download_tiktok.py`：下载 → 转壁纸 → 按原顺序编号 `1_wallpaper.jpg、2_wallpaper.jpg…`，各自归档到 `壁纸/<博主>/<时间戳_帖子ID>/`。
- **去重**：`batch_download.py` 默认开启跳过已下载（`--skip-existing`）——下载前扫描 `壁纸/<博主>/` 下已有文件夹（文件名/文件夹名里的帖子ID，以及 `<博主>/.downloaded.json` 清单），命中即跳过，绝不重复下载。用 `--force` 可强制重下。

> 为什么不走 gallery-dl 枚举：经实测，`gallery-dl .../@USER/posts` 调用 `creator/item_list`，对 `vexaro.4k` 这类账号只能翻到第一页（只返回最新一条），无法全量枚举。yt-dlp 走 `tiktokuser:<secUid>` 另一条接口，能稳定取到全部作品及点赞/播放等指标。下载环节（真正取图）仍用 gallery-dl，它对 `/photo/` 图文帖支持更好。

## 依赖自检 / 异常处理

- ffmpeg 列表里没有 `vvc` → 提示更换带 VVC 解码的 ffmpeg，给出自检命令。
- `download_tiktok.py` 下载 0 文件 → 把 gallery-dl/yt-dlp 的报错贴回诊断（常见原因：TikTok 反爬需登录 Cookie / 代理 / 链接失效）。脚本已自动尝试 `pip install gallery-dl`。若仍失败，可手动加 Cookie：`python3 -m gallery_dl -d out --cookies-from-browser chrome <url>`。
- 解码花屏/异常 → 该文件可能用了不同封装变体，可回退手动解析 iloc 定位数据（见 `convert_tiktok_image.py` 注释）。

## 给用户的简短说明

完成后一句话告诉用户：原图是 TikTok 私有 VVC 格式（或来自 TikTok 链接已下载）所以普通软件打不开，已转成可直接使用的手机壁纸 JPG，并给出文件路径。
