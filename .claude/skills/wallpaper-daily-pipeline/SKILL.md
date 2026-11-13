---
name: wallpaper-daily-pipeline
description: >-
  壁纸日更流水线的「薄编排层」：把 tiktok-image-to-wallpaper（下载）、wallpaper-batch-splitter（8+1 分组规则）、
  wechat-tietu-draft（公众号贴图草稿）三个独立 skill 串成一条链。典型诉求「下载某博主点赞过万的壁纸 →
  按 8+1 拆成文件夹 → 每天发 4 组进公众号草稿」。编排层只负责调度与数据格式对齐，不重写下载/发帖实现，
  下载与发帖仍是两个互不依赖的 skill。固定规则：每组 4 对 A/B（1_A/1_B … 4_A/4_B，共 8 张壁纸）
  + 1 张汤姆和杰瑞固定封面，首图必须是该封面；每条贴图草稿 = 1 封面 + 8 素材 = 9 张。
  只到草稿箱，绝不调用 freepublish/submit、不碰 Cookie/RPA，发表由人工点击。
  触发词：整合 skill、壁纸流水线、下载博主点赞过万的图、8+1 分组后发公众号、每天发 4 组贴图、
  日更壁纸草稿、wallpaper pipeline。
agent_created: true
version: 1.0.0
display_name: "壁纸日更流水线"
display_name_en: "Wallpaper Daily Pipeline"
description_zh: "串联下载、8+1 分组与公众号贴图草稿的编排层，下载/发帖 skill 保持独立。"
description_en: "Orchestrates TikTok wallpaper download, 8+1 batching and WeChat newspic drafts."
visibility: "user"
---

# 壁纸日更流水线（编排层）

> **薄编排，不是大合并。** `tiktok-image-to-wallpaper`（下载）和 `wechat-tietu-draft`（发帖草稿）
> 依然是两个完全独立、可单独使用的 skill；本 skill 只做三件事：把三个 skill 的**数据格式对齐**、
> **代理/网络环境隔离**、**队列与去重状态管理**。任何一个原子 skill 单独升级，编排层不用跟着改。

## 数据流

```
① analyze    analyze_tiktok_profile.py   → <博主>_analysis.csv / .json（474 条作品，按点赞降序）
② select     pipeline.py select          → selected.csv（likes ≥ 1 万、仅图文、/video/ 改写 /photo/）
③ download   batch_download.py           → 壁纸/<博主>/<帖子ID>-<YYYYMMDD>/1_A,1_B,2_A,2_B …
④ batch      make_batches.py             → 发布批次/<批次>/0001/  1_A..4_B (8 张) + cover.png
⑤ draft      tietu_draft.py × N          → 每组 1 条 newspic 贴图草稿（首图固定汤姆和杰瑞封面）
                                            发表永远由人在草稿箱点一下
```

## 用户拍板的固定规则（2026-11-11）

| 项 | 规则 |
|---|---|
| 一组的内容 | **4 对 A/B = 8 张壁纸**：`1_A/1_B, 2_A/2_B, 3_A/3_B, 4_A/4_B`。A=桌面展示图，B=同款壁纸原图，成对不拆散 |
| 「+1」 | 每组放一张 `cover.png`，**就是汤姆和杰瑞固定封面**（`wechat-tietu-draft/assets/cover_tom_jerry.png`） |
| 首图 | **必须是汤姆和杰瑞封面，排在第一张** —— 编排层 md5 校验 + 下游 `--dry-run` 首图自检 + 下游 `cover_path()` 硬失败，三重保障 |
| 去重语义 | 下游 `images_in()` 自动忽略 `cover.*` 并把同一张图插到首位 → 每条草稿恰好 1 封面 + 8 素材 = **9 张**，不会出现两张封面 |
| 每次投递 | 默认 `--per-day 4`，即 4 组 → 4 条草稿；发表仍人工 |
| 定时任务 | **当前未启用**（用户明确选择「只跑今天，不建定时任务」）。能力已就绪，随时可启用，见下节 |

### 唯一封面硬约束（2026-11-13 用户最终裁定，不可替换）

所有批次、所有草稿的首图**一律只用** `wechat-tietu-draft/assets/cover_tom_jerry.png`
（权威来源 `E:\图片\壁纸\vexaro.4k\20261108_110501_7694083696076295445\cover.png` 的字节级副本，
941×1671 RGBA PNG，3,667,249 字节）。

- SHA-256：`ed31ea7dc4ce144999a61e10371a397c4b5079e992a2a116d6c751501b72481a`
- 视觉特征：仰视蓝天白云，左侧汤姆与右侧杰瑞低头俯看镜头嬉笑；
  **四角绿叶 + 左下白色前爪 + 白字 `Photo 4k wallpaper iOS 27` / `>>>>>>>` + 右下「AI生成」水印**。
  **「有没有字母/文字」是最快判断标志 —— 有字才对**
- 2026-11-13 用户**推翻 11-12 的「无树木、无文字」版**：那张是原版壁纸，不是封面
- 换机器或更新 skill 后先核对再用：`sha256sum <skills>/wechat-tietu-draft/assets/cover_tom_jerry.png`
- **禁止**替换为任何归档旧版；不得裁剪、重新生成
- 已废弃：`_archive/cover_tom_jerry_NO_TEXT_2026-11-12_DEPRECATED.png`（无字版）、
  `_archive/cover_tom_jerry_v1_1080x1918.jpg`（带字但无树木）、
  `_archive/cover_tom_jerry_v2_compressed_noAI_DEPRECATED.png`（压缩版无水印，非母版）
- 换已投草稿的首图：用 `tietu_draft.py --update <media_id>` **原地替换第一张**，复用其余旧图，不新建草稿

## 为什么 batch 不直接调用 `wallpaper-batch-splitter`

规则一致（每组 8 张 + 1 配图），但落地方式必须换成「复制式分批」：

1. 素材库要留档，splitter 是**移动/重排**语义，会破坏 `<帖子ID>-<日期>` 归档；
2. 不同帖子的文件都叫 `1_A.jpg` / `1_B.jpg`，跨帖 stream 重排必然撞名（splitter 会硬性报「目标文件已存在」）；
3. 组号要连续、可每天增量追加，并且要记录「哪些源图已消费」。

因此 `make_batches.py` 只**复制**（绝不移动/删除源图），把每对重命名为组内的 `N_A/N_B`，
补一份 `cover.png`，逐组写 `manifest.json`、批次写 `batches.json`，并把已消费源文件记进
`_state/consumed.json`。分组时**帖内优先装满 4 对**，只有各帖尾部余数才跨帖拼组，
避免把同一帖的画风拆散；给 `--order-file` 时按榜单顺序让点赞高的帖子先发。splitter skill 仍保留，适合单独整理本地散图；整合过程中顺手修了它
的 A/B 排序缺陷（v1.0.1：`natural_key` 现在能正确排 `1_A,1_B,2_A … 10_A`，不会把 10 排到 2 前）。

## 目录约定（全部可用参数覆盖，无强制盘符）

```
<wallpaper-dir>/                    默认 E:\图片\壁纸        素材库（只增不改）
  <博主>/<帖子ID>-<YYYYMMDD>/
  _榜单/<博主>_analysis.csv|json、selected.csv|json
<batch-root>/<批次名>/              默认 E:\图片\发布批次\20261111-<博主>\
  0001/ 0002/ …                    每组 8 张壁纸 + cover.png + manifest.json
  _state/consumed.json              已消费源文件
  _state/posted.json                已投组 → media_id
  _reports/drafts_*.json            每次投递汇总
  batches.json                      批次索引
```

## 五步命令（可复制）

`<skills>` = `C:\Users\WFL\.workbuddy\skills`，`<pipe>` = `<skills>\wallpaper-daily-pipeline\scripts\pipeline.py`

```bash
# ① 分析博主全部作品（TikTok 走代理 7890）
python "<pipe>" analyze --url "https://www.tiktok.com/@clear__display/photo/7706754841145625877" \
    --wallpaper-dir "E:/图片/壁纸"

# ② 筛点赞 ≥1 万、只要图文（--photo-only 排除 video；/video/ 自动改 /photo/）
python "<pipe>" select --from "E:/图片/壁纸/_榜单/clear__display_analysis.csv" \
    --min-likes 10000 --photo-only

# ③ 批量下载（复用 batch_download.py，自带已下载去重、A/B 成对命名）
python "<pipe>" download --from "E:/图片/壁纸/_榜单/selected.csv" \
    --wallpaper-dir "E:/图片/壁纸"

# ④ 生成 8+1 组：先预检，再执行（--order-file 让点赞高的帖子优先成组）
python "<pipe>" batch --author clear__display --wallpaper-dir "E:/图片/壁纸" \
    --batch-root "E:/图片/发布批次" --order-file "E:/图片/壁纸/_榜单/selected.csv" --dry-run
python "<pipe>" batch --author clear__display --wallpaper-dir "E:/图片/壁纸" \
    --batch-root "E:/图片/发布批次" --order-file "E:/图片/壁纸/_榜单/selected.csv"

# ⑤ 投 4 组进草稿箱：先预检，再正式
python "<pipe>" draft --batch-dir "E:/图片/发布批次/20261111-clear__display" --per-day 4 --dry-run
python "<pipe>" draft --batch-dir "E:/图片/发布批次/20261111-clear__display" --per-day 4
```

一条命令跑完全链（换博主时最省事）：

```bash
python "<pipe>" all --url "https://www.tiktok.com/@clear__display/photo/7706754841145625877" \
    --min-likes 10000 --photo-only --author clear__display \
    --wallpaper-dir "E:/图片/壁纸" --batch-root "E:/图片/发布批次" \
    --per-day 4 --dry-run
```

去掉 `--dry-run` 即正式执行；`--skip-download` 复用现有素材、`--no-draft` 只备料不投递、
`--batch-dir` 复用已有批次。

## 「每天 4 组」怎么启用

用户当前只要求**今天跑一次**。以后要每天自动跑，两种方式（都不自动发表）：

- 手动/外部计划任务：每天执行上面第 ⑤ 步（不带 `--dry-run`）。`posted.json` + 下游
  `used_posts.json` 保证同一组不会重复投，跑完自动取接下来的 4 组。
- WorkBuddy 定时任务：明确说「每天 9 点自动投 4 组」时，建一条 recurring automation，
  提示词写「用 wallpaper-daily-pipeline 的 `draft` 子命令，对批次目录 <绝对路径> 取 4 个未投组
  建公众号贴图草稿，只到草稿箱，完成后把 media_id 汇总通知我」。**没有用户明确要求就不要建。**

批次组耗尽时脚本会打印「没有未投过的组」，此时回到 ①~④ 追加新素材即可，组号自动往下排。

## 参数速查

| 子命令 | 关键参数 |
|---|---|
| `analyze` | `--url`（必填）、`--out` 榜单目录 |
| `select` | `--from` 榜单 CSV、`--min-likes`、`--photo-only`、`--top`、`--out` |
| `download` | `--from selected.csv`、`--top` |
| `batch` | `--source` 博主素材目录 / `--author`、`--batch-name`、`--pairs-per-group`（默认 4 对）、`--order-file` 榜单 CSV（热门优先）、`--allow-partial`、`--reset-batches`、`--dry-run` |
| `draft` | `--batch-dir`（必填）、`--per-day`（默认 4）、`--pairs-per-group`、`--force`、`--dry-run` |
| 公共 | `--skills-root`、`--wallpaper-dir`、`--batch-root`、`--cover`、`--proxy` |

## 网络接缝（实机踩坑，已固化进代码）

| 环节 | 处理 |
|---|---|
| TikTok 下载 / 榜单 | 子进程强制注入 `HTTP(S)_PROXY` = `--proxy`（默认 `http://127.0.0.1:7890`）。WorkBuddy 会注入 `http_proxy=127.0.0.1:12741`，yt-dlp / gallery-dl 若继承会直接连不上外网 |
| 公众号 API | 子进程**清空全部代理变量**并设 `NO_PROXY=api.weixin.qq.com`，国内接口直连；否则出口 IP 变化还会触发 `40164` 白名单错误 |
| 凭证 | 仍从 `%USERPROFILE%\.workbuddy\wechat.env` 或环境变量读，编排层不接触、不回显 AppSecret |
| 榜单 URL | `analyze_tiktok_profile.py` 生成的清单统一写 `/video/<id>`；`select` 把图文帖改回 `/photo/<id>`，gallery-dl 的 TikTok 图文提取器才稳定取全幻灯片 |

## 去重与失败安全

- `consumed.json`：已消费的源图路径，重跑 `batch` 只处理新增素材，绝不重复成组。
- `posted.json`：每个组 → `draft_media_id`，逐组落盘；中途失败重跑会跳过已投组。
- 下游 `used_posts.json`（key = 组目录绝对路径）也会被读取，双保险。
- `draft` 正式投递前：逐组 `--dry-run` 预检（首图自检 + 9 张自检）→ 全部通过才联网；
  再跑一次 `--check-only` 强制换 token 验 IP 白名单；任一环节失败**不建任何草稿**。
- 目标组目录已存在、封面 md5 不符、壁纸不足 8 张 → 直接报错退出，不覆盖、不降级。

## 边界（与用户约定一致）

- **不调用** `freepublish/submit`，不用 Cookie / Playwright / 后台逆向接口；草稿箱就是待发队列，人工点发表。
- 下载与发帖保持两个独立 skill，本 skill 不合并它们的代码。
- 素材库只读，`batch` 全程 `copy2`；不删、不移、不改原图。
- 不自动创建定时任务，除非用户明确要求。

## 排错

| 现象 | 处理 |
|---|---|
| `analyze` 抓不到作品 / 超时 | 确认 Clash 在跑且 7890 可用：`curl -s -m 10 --proxy http://127.0.0.1:7890 -o /dev/null -w "%{http_code}" https://www.tiktok.com/@clear__display`；换 `--proxy` |
| `download` 0 文件 | 多为 TikTok 反爬；清单里的 URL 应已是 `/photo/` 形式，仍失败就手动 `python -m gallery_dl -d out --cookies-from-browser chrome "<url>"` 诊断 |
| `40164` | 出口 IP 不在白名单；`--check-only` 会打印当前 IP，加到公众号「开发密钥 → API IP 白名单」后重跑 |
| 组数不够 4 组 | 素材不足 4 对 × 4 组；回到 ①~④ 补素材。`--allow-partial` 生成的残组会被 `draft` 的「每组必须 8 张」校验拦下，仅供手工处理，不要直接投 |
| 首图不是汤姆和杰瑞 | 编排层 md5 校验与下游硬失败都会拦下；先检查 `assets/cover_tom_jerry.png` 是否被换过 |
| 想换分组粒度 | `batch` 与 `draft` 同时给同一个 `--pairs-per-group`（如 8 对 = 16 张，加封面 17 张，仍在 19 张安全上限内） |

## 给用户的简短说明

一句话交代：本次下了几条帖子、生成几组 8+1、投了几条草稿（每组 9 张、首图汤姆和杰瑞封面）、
汇总 JSON 在哪；并提醒「去草稿箱手动点发表」。不要说「已发布」。
