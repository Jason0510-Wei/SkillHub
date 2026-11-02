---
name: tiktok-image-to-wallpaper
description: >-
  把 TikTok 的图片变成手机壁纸 JPEG。两种入口：① 用户直接丢来 TikTok 链接 —— 先用 gallery-dl 下载链接里的图片，再逐个转成手机壁纸 JPEG；② 用户给本地 .image 文件（TikTok 私有 VVC/HEIF 格式，普通软件打不开）—— 直接转。触发词：tiktok 链接转壁纸、tiktok 图片打不开、转成手机壁纸、TikTok image 转 jpg、.image 文件、把这条抖音/国际版抖音链接的图下载下来。解码依赖本机 ffmpeg 的 vvc 解码器；下载依赖 gallery-dl（首选，自动解 TikTok JS 挑战、支持 /photo/ 图文帖）/ yt-dlp（兜底）。下载结果按 壁纸/<博主>/<时间戳YYYYMMDDHHMM>/ 目录归档。
agent_created: true
version: 1.4.0
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
3. 按**保存时间**在「壁纸」目录下建文件夹，落盘结构：

   ```
   当前目录/壁纸/<博主>/<时间戳YYYYMMDDHHMM>/
   例：壁纸/xqteth/202611021238/
   ```
   （每个博主一个文件夹，每个链接一个时间文件夹）
4. 把每个文件转成手机壁纸 JPEG（**默认宽度 ≤1080**；加 `--4k` 则长边升采样到 3840），成功后再删除原始下载件，文件夹里只留 `<原名>_wallpaper.jpg`。**转换结束会打印每张的实际分辨率**（如 `1080x1920`），方便核对到底几 K。

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

## 依赖自检 / 异常处理

- ffmpeg 列表里没有 `vvc` → 提示更换带 VVC 解码的 ffmpeg，给出自检命令。
- `download_tiktok.py` 下载 0 文件 → 把 gallery-dl/yt-dlp 的报错贴回诊断（常见原因：TikTok 反爬需登录 Cookie / 代理 / 链接失效）。脚本已自动尝试 `pip install gallery-dl`。若仍失败，可手动加 Cookie：`python3 -m gallery_dl -d out --cookies-from-browser chrome <url>`。
- 解码花屏/异常 → 该文件可能用了不同封装变体，可回退手动解析 iloc 定位数据（见 `convert_tiktok_image.py` 注释）。

## 给用户的简短说明

完成后一句话告诉用户：原图是 TikTok 私有 VVC 格式（或来自 TikTok 链接已下载）所以普通软件打不开，已转成可直接使用的手机壁纸 JPG，并给出文件路径。
