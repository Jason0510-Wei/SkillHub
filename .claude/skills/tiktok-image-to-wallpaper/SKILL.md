---
name: tiktok-image-to-wallpaper
description: >-
  把 TikTok 的图片下载成手机壁纸。三种入口：① 用户直接丢来 TikTok 链接 —— 用 gallery-dl 下载帖子里的图片，**默认原图直出、零转码**，按 `1_A/1_B、2_A/2_B` 成对编号归档（A=桌面展示图，B=同一张壁纸的原图）；转码（宽度≤1080 JPEG / --4k 升采样）降级为显式参数，默认不启用；② 用户给本地 .image 文件（TikTok 私有 VVC/HEIF 格式，普通软件打不开）—— 用 ffmpeg vvc 解码器转成 JPG；③「博主作品分析 + 批量下载」—— 任意能定位到博主的 TikTok 链接（帖子/@主页/短链），先用 yt-dlp 枚举全部作品并按「受欢迎程度（点赞/播放/评论）」降序出排行榜，用户圈定后再用 batch_download.py 批量下载（自带去重）。触发词：tiktok 链接转壁纸、tiktok 图片打不开、转成手机壁纸、TikTok image 转 jpg、.image 文件、分析这个博主的作品、把博主所有作品按热度排个序、批量下载博主壁纸。下载依赖 gallery-dl（首选，自动解 TikTok JS 挑战、支持 /photo/ 图文帖）/ yt-dlp（兜底，兼枚举全量作品）；分析依赖 yt-dlp；转码/本地 .image 解码才需要 ffmpeg vvc 解码器。归档按 壁纸/<博主>/<帖子ID>-<年月日YYYYMMDD>/ 每个帖子独立文件夹。
agent_created: true
version: 1.9.0
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
几乎没有任何看图软件内置 VVC 解码器，所以会“打不开”。本 skill 用 ffmpeg 的 `vvc` 解码器把它还原成普通 JPEG（入口 B）。

如果用户给的是 TikTok **链接**（入口 A），则用 gallery-dl 把帖子里的图片下载下来，**默认原图直出、按序编号、不转码**；
只有显式加 `--convert` 才转成宽度 ≤1080 的 JPEG。这样能保留源图的真实分辨率（实测有 1536px 乃至 5736×8192），
尤其适合作为小红书 / 公众号的发布素材。

## 前置条件

- **ffmpeg**（建议 n8.1+，含原生 `vvc` 解码器）。自检：
  ```bash
  ffmpeg -hide_banner -decoders 2>/dev/null | grep -i " vvc "
  ```
- **gallery-dl**（下载用，首选）：`pip install gallery-dl`，或让脚本首次运行时自动装。它内置 TikTok 提取器，支持图文/幻灯片帖子（`/photo/`）并能自动过 JS 挑战，通常无需登录 Cookie。

## 使用流程

### 入口 A：用户给了 TikTok 链接（最常见）

**一条命令搞定**，自动按「博主 / 帖子」分层归档：

```bash
python3 "<skill_dir>/scripts/download_tiktok.py" "<tiktok_url>"
```

脚本内部完成：
1. 用 gallery-dl（兜底 yt-dlp）下载链接里的图片/视频；
2. 自动识别博主——优先从链接里的 `@username` 取，取不到就从 gallery-dl 的下载目录（`tiktok/<user>/`）反推 TikTok handle；
3. 按**帖子ID + 保存日期（YYYYMMDD）**在「壁纸」目录下建文件夹，落盘结构：

   ```
   当前目录/壁纸/<博主>/<帖子ID>-<年月日YYYYMMDD>/
   例：壁纸/vexaro.4k/7695439146944400660-20261108/
   ```
   （每个博主一个文件夹，**每个帖子一个独立文件夹**——v1.8.0 起帖子ID 放在最前、后接保存日期 YYYYMMDD，便于按作品检索与排序；同一帖子同日重复下载会追加 `_1` / `_2` 后缀，不会合并。旧版格式 `<时间戳YYYYMMDD_HHMMSS>_<帖子ID>` 不再生成）
4. **默认「原图直出」（v1.7.0 起）：不做任何转码**。下载到的原始媒体文件保留原始分辨率、原始格式与原始编码（无二次 JPEG 压缩），也不产生 `.originals/` 子目录。实测源图常在 1536px、甚至 5736×8192，旧的默认封顶 1080 会损失大量细节；发布到小红书/公众号时源图越清晰越占优。
5. **按原顺序两两成对编号（v1.9.0 起）**：同一帖子里的文件按 TikTok 幻灯片原始顺序（gallery-dl 文件名里的 `_NN` 序号）重命名为 `1_A.<ext>`、`1_B.<ext>`、`2_A.<ext>`、`2_B.<ext>` …。
   **A = 桌面展示图（手机锁屏效果），B = 同一张壁纸的原图**；奇数位 A、偶数位 B，第 i 张属于第 `(i+1)//2` 组。
   文件名中的 caption / hash 会被丢弃，仅保留**组号 + A/B**；原图模式下保留各自原始扩展名（jpg/png/webp/…）。
   目录里的 `cover.*`（固定封面图）不参与编号，保持原名。

**转码是可配置参数，默认不配置**：只有显式加开关才走旧的转码流程。

| 命令 | 行为 |
|------|------|
| `download_tiktok.py <url>` | **默认**：原图直出 + `1_A/1_B` 成对编号，零转码 |
| `download_tiktok.py <url> --legacy-naming` | 回到旧命名 `1_wallpaper.<ext>, 2_wallpaper.<ext> …`（兼容老脚本） |
| `download_tiktok.py <url> <base_dir> --convert` | 转码成宽度 ≤1080 的 JPEG（`-q:v 3`），原始下载件移入 `.originals/` 留档，成品统一 `_wallpaper.jpg` |
| `download_tiktok.py <url> <base_dir> --4k` | 转码时长边升采样到 3840（`--4k` 会隐含启用 `--convert`） |

- 自定义根目录（不用默认「壁纸」）：第 2 个参数传路径，如 `"D:/壁纸"`。
- `--4k` 是**插值放大**，仅尺寸到 4K、细节不增。注意很多源图本就是真 4K/8K，**直接默认下载原图即可，无需升采样**。
- 历史参数 `--no-convert` 保留为兼容 no-op（现在默认就是不转码）。
- `batch_download.py` 同样支持透传 `--convert` / `--4k` / `--legacy-naming`，默认仍是原图直出 + A/B 命名。
- **存量目录迁移**：`scripts/rename_to_ab.py` 把旧的 `N_wallpaper.<ext>` 批量改成 `1_A/1_B …`。
  **默认只预览**，确认无误后加 `--apply` 才真改；`cover.*` 不动、目标名已存在会跳过、两阶段重命名防覆盖。
  ```bash
  python3 "<skill_dir>/scripts/rename_to_ab.py"                    # 预览 E:\图片\壁纸 全部存量
  python3 "<skill_dir>/scripts/rename_to_ab.py" "E:/图片/壁纸/vexaro.4k" --apply
  ```
- 若下载到 `.image` / `.heic` / `.avif` 等私有格式，默认模式会提示「普通看图软件可能打不开」，此时加 `--convert` 转通用 JPG。

完成后用 `present_files` 把 `壁纸/<博主>/<帖子ID>-<年月日YYYYMMDD>/` 展示给用户。

> 若帖子是真视频（非图文幻灯片），默认原图模式会保留 `.mp4` 等视频文件并照常编号；只有在 `--convert` 模式下才会取首帧转成一张 JPG 壁纸。遇到这种情况提示用户「该链接是视频」。

#### A/B 成对命名规则（v1.9.0）

TikTok 壁纸帖的图片天然是「一张展示图 + 一张原图」交替出现，所以按位置两两配对：

```
下载顺序（gallery-dl _NN）   新文件名        语义
        1                    1_A.jpg        第 1 组 · 桌面展示图（锁屏效果）
        2                    1_B.jpg        第 1 组 · 壁纸原图
        3                    2_A.jpg        第 2 组 · 桌面展示图
        4                    2_B.jpg        第 2 组 · 壁纸原图
        5                    3_A.jpg        第 3 组 · 桌面展示图（奇数张时可能缺 B）
```

下游 `wechat-tietu-draft` 会按 `组号 + A/B` 自然排序挑图（也兼容旧命名），
因此不需要额外配置就能直接用。若某帖图片数为奇数，最后一张只有 A、没有对应 B，属正常现象。

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
  1. 从链接取 `@handle`；**若链接里带 `/photo/ID` 或 `/video/ID`**，再向 yt-dlp 取该博主的 `secUid`（纯 `@主页` 链接不触发 secUid 反查，被限流时没有兜底，此时优先改用带帖子 ID 的链接或短链）；
  2. 用 `yt-dlp --flat-playlist` 枚举该博主**全部**作品（gallery-dl 的 `/posts` 对部分账号分页会卡在第一页、抓不全，故改用 yt-dlp 枚举）；
  3. 按 `--metric`（默认 `likes` 点赞；可换 `views` 播放 / `comments` 评论）降序排名。
- 输出：控制台打印排行榜（超过 60 条时只打印前 60，完整清单看文件），并在 `--out`（默认当前目录）落盘两份清单：
  - `<博主>_analysis.csv`（utf-8-sig，含 rank / author / id / type / likes / views / comments / date / caption / url）
  - `<博主>_analysis.json`
- 这两份清单就是第 2 步批量下载的输入。

**第 2 步 · 按用户挑选批量下载（默认原图直出）**

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
- 每条链接都会复用入口 A 的 `download_tiktok.py`：下载 → **原图直出（默认零转码）** → 按原顺序成对编号 `1_A/1_B、2_A/2_B …`，各自归档到 `壁纸/<博主>/<帖子ID>-<年月日YYYYMMDD>/`。需要转码时给 `batch_download.py` 加 `--convert` 或 `--4k`；需要旧命名加 `--legacy-naming`，均可透传。
- **去重**：`batch_download.py` 默认开启跳过已下载（`--skip-existing`）——下载前扫描 `壁纸/<博主>/` 下已有文件夹（文件名/文件夹名里的帖子ID，以及 `<博主>/.downloaded.json` 清单），命中即跳过，绝不重复下载。用 `--force` 可强制重下。

> 为什么不走 gallery-dl 枚举：经实测，`gallery-dl .../@USER/posts` 调用 `creator/item_list`，对 `vexaro.4k` 这类账号只能翻到第一页（只返回最新一条），无法全量枚举。yt-dlp 走 `https://www.tiktok.com/@<secUid>` 另一条接口，能稳定取到全部作品及点赞/播放等指标（`tiktokuser:<secUid>` 伪协议在 yt-dlp 2026.10.26 已失效，勿再使用）。下载环节（真正取图）仍用 gallery-dl，它对 `/photo/` 图文帖支持更好。

## 依赖自检 / 异常处理

- ffmpeg 列表里没有 `vvc` → 提示更换带 VVC 解码的 ffmpeg，给出自检命令。
- `download_tiktok.py` 下载 0 文件 → 把 gallery-dl/yt-dlp 的报错贴回诊断（常见原因：TikTok 反爬需登录 Cookie / 代理 / 链接失效）。脚本已自动尝试 `pip install gallery-dl`。若仍失败，可手动加 Cookie：`python3 -m gallery_dl -d out --cookies-from-browser chrome <url>`。
- 解码花屏/异常 → 该文件可能用了不同封装变体，可回退手动解析 iloc 定位数据（见 `convert_tiktok_image.py` 注释）。

## 给用户的简短说明

完成后一句话告诉用户：原图是 TikTok 私有 VVC 格式（或来自 TikTok 链接已下载）所以普通软件打不开，已转成可直接使用的手机壁纸 JPG，并给出文件路径。

## 下游：发到微信公众号贴图草稿

归档好的图集可以直接喂给 **`wechat-tietu-draft`** skill（用户级，`~/.workbuddy/skills/wechat-tietu-draft/`）：
它按 `壁纸/<博主>/<帖子ID>-<YYYYMMDD>/1_A.jpg, 1_B.jpg …` 的自然序号挑图（兼容旧 `N_wallpaper` 命名），
自动把「汤姆和杰瑞」固定封面置顶，套用用户指定标题/正文/标签，上传永久素材后建
`article_type=newspic` 贴图草稿，**停在草稿箱由人手动发表**，不调用发表接口。

触发场景：用户说「把刚下载的壁纸发到公众号 / 做一条贴图 / 每日贴图」。
典型命令（先空跑预检）：

```bash
python "C:/Users/WFL/.workbuddy/skills/wechat-tietu-draft/scripts/tietu_draft.py" \
    --dry-run --latest --author <博主>
```

去掉 `--dry-run` 即正式建草稿。首次使用需配置公众号 AppSecret 与 API IP 白名单，见下游 skill 的 SKILL.md。
