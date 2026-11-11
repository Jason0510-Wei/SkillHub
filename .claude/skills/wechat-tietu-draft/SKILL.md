---
name: wechat-tietu-draft
description: >-
  把本地图片（默认复用 tiktok-image-to-wallpaper 下载的壁纸图集）自动做成微信公众号「贴图」草稿，
  停在草稿箱等人手动发表。默认套用用户固定风格：汤姆和杰瑞封面图当第一张 + 指定标题/正文/标签。
  走官方接口 token → material/add_material（永久图片素材）→ draft/add（article_type=newspic），
  另支持 draft/get（--verify）与 draft/update（--update 原地改草稿）。不调用 freepublish/submit、
  不做 Cookie/Playwright 后台自动化。触发词：发贴图、公众号贴图、贴图草稿、把壁纸发到公众号、
  每日贴图、改一下草稿文案、wechat tietu。适用于个人订阅号等无 API 发表权限的账号。
agent_created: true
version: 1.2.0
display_name: "公众号贴图草稿"
display_name_en: "WeChat Tietu Draft"
description_zh: "按固定风格把壁纸图集做成微信公众号贴图草稿，人工在草稿箱发表。"
description_en: "Create styled WeChat Official Account image-post (newspic) drafts from wallpaper images."
visibility: "user"
---

# 公众号贴图草稿（只到草稿箱，不发表）

> **这是 `tiktok-image-to-wallpaper` 的下游 skill**。上游负责「下载并归档壁纸」，本 skill 负责
> 「把归档好的图做成公众号贴图草稿」。中间不需要人工搬文件。

## 边界（先看这个）

| 谁 | 做什么 |
|---|---|
| 本 skill（自动） | 挑图 → 固定封面置顶 → 上传永久图片素材 → 建 `newspic` 贴图草稿 → 记录已投，避免重复 |
| 人（一次点击） | 公众号后台「草稿箱」或手机订阅号助手首页「贴图」→ 点发表（必要时扫码确认） |

**明确不做**：不调用 `/cgi-bin/freepublish/submit`（2025-07 起个人主体/未认证账号已被回收发表接口权限，
返回 `48001`）；不碰 Cookie、CSRF token、Playwright、后台逆向接口。这样绕开了资质门槛、
封号风控、平台推荐开关缺失、异步发布状态轮询等一整套麻烦。

官方还确认：草稿「被群发或发布后，该素材将从草稿箱中移除」——所以**草稿箱本身就是待发队列**，
发表完自动清空，不需要额外维护"哪条已发"的状态。

## 用户固定风格（v1.2.0 起为默认值，全部可覆盖）

用户于 2026-11-11 确认，不接受每次重新口述；不传任何文案参数就自动套用：

| 项 | 默认值 |
|---|---|
| 首图 / 封面 | `assets/cover_tom_jerry.jpg` —— 「蓝天白云 + 汤姆和杰瑞 + Photo 4k wallpaper iOS 27」固定封面 |
| 标题 | `【分享】TikTok爆火🔥iOS 4K高清锁屏壁纸📱`（26 字符 / 56 UTF-8 字节，已实测微信接受） |
| 正文 | `喜欢这组壁纸的话，留个关注❤️`<br>`后续持续更新更多TikTok热门🔥高清壁纸！` |
| 空行 | 正文与标签之间固定空一行（`\n\n`） |
| 标签 | `#4K高清壁纸 #iOS壁纸 #手机壁纸 #锁屏壁纸 #高清壁纸` |

封面文件独立放在 skill 的 `assets/` 下，**不受素材组重命名影响**；换封面只要替换这个文件，
或临时用 `--cover <path>` 指定；`--no-cover` 可关闭；环境变量 `WECHAT_TIETU_COVER` 可改默认路径。

> ⚠️ 用户标签是**单 `#` 前缀**风格（小红书/微博式），不是微信官方话题的 `#话题名#` 双井号格式。
> 默认按用户原样输出（微信里表现为纯文本，不生成话题链接）。需要官方话题时显式传
> `--topics 壁纸,锁屏`，会转成 `#壁纸# #锁屏#` 覆盖默认标签。`--tags` 可原样换标签行，`--no-tags` 关闭。

**标题长度**：早期按 32 字节保守拦截会误伤这个含 emoji 的标题，v1.2.0 起放宽到
**128 字节 / 64 字符**，微信实测通过；`--strict-title` 可恢复 32 字节口径。

## 上游素材约定（v1.9.0 起 A/B 成对命名）

```
E:\图片\壁纸\<博主>\<帖子ID>-<YYYYMMDD>\
    1_A.jpg  1_B.jpg  2_A.jpg  2_B.jpg ...   （A=桌面展示图，B=同一张壁纸的原图）
    cover.png                                 （可选固定封面，不参与编号）
```

- 兼容旧命名 `1_wallpaper.jpg, 2_wallpaper.jpg, ...`；两种都按数字 + A/B **自然排序**
  （1_A, 1_B, 2_A … 10_A，不是字典序 1, 10, 2）。
- **固定封面额外占 1 张**，默认从素材组取 **9 张**，合计 10 张；`--max-images 0` 取全部，
  总数上限 20（官方 newspic 上限）。`--update` 时默认**替换**原第一张，不重复上传其余素材。
- 根目录默认 `E:\图片\壁纸`，可用 `--base-dir` 或环境变量 `WECHAT_TIETU_WALLPAPER_DIR` 改。
- 原图可能是 `.webp` 或超过官方 10MB 上限：脚本会用 Pillow 自动转 JPEG 压到 10MB 以内，**不改原图**
  （转换产物在系统临时目录，用完即删）。官方支持 `bmp/png/jpeg/jpg/gif`，10MB。

## 首次使用（一次性配置）

1. **拿 AppID / AppSecret**：`developers.weixin.qq.com/platform` → 我的业务与服务 → 公众号 →
   基础信息 → **开发密钥**。管理员扫码生成，AppSecret **只明文显示一次**。
2. **配 API IP 白名单**：同一页把跑脚本机器的**公网出口 IP** 加进去，否则 `40164`。
   跑一次 `--check-only`，`40164` 时脚本会从 errmsg 解析并打印当前出口 IPv4
   （`::ffff:` 是同一地址的 IPv6 映射，不用另加）。官方规则：支持具体 IP 与 IP 段，段仅
   `/8`、`/16`、`/24`，最多 200 条，不支持 `IP:端口`，修改后需等数分钟生效。
   家宽会漂移：保守填当前 IPv4（漂移后重跑 `--check-only` 补），或填 `120.229.0.0/16`
   省事（放宽来源范围，务必保管好 AppSecret）。
3. **写凭证文件**（二选一）：环境变量 `WECHAT_APPID` / `WECHAT_SECRET`，或复制
   `wechat.env.example` 到 `C:\Users\WFL\.workbuddy\wechat.env` 并填值。

   ```ini
   WECHAT_APPID=wxXXXXXXXXXXXXXXXX
   WECHAT_SECRET=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
   ```

   > ⚠️ **安全红线**：AppSecret 是最高权限凭据。不写进代码、不提交 git、不回显、不打印到日志。
   > `.state/` 只存 token 缓存与已投记录，同样不要外传。`assets/` 只放公开封面图。

4. 确认公众号后台能看到「草稿箱」即可。

## 快速开始

`<skill_dir>` = `C:\Users\WFL\.workbuddy\skills\wechat-tietu-draft`

```bash
# -1) 自检连通性（只取 token）
python "<skill_dir>/scripts/tietu_draft.py" --check-only

# 0) 空跑：打印会挑哪些图 + 完整文案，不联网、不上传
python "<skill_dir>/scripts/tietu_draft.py" --dry-run --latest --author hungry777_

# 1) 按固定风格建一条草稿（最常见，不需要任何文案参数）
python "<skill_dir>/scripts/tietu_draft.py" --latest

# 2) 指定帖子目录 / 随机一组未投过的（适合每日一条）
python "<skill_dir>/scripts/tietu_draft.py" --from-dir "E:/图片/壁纸/vexaro.4k/20261108_110501_7694083696076295445"
python "<skill_dir>/scripts/tietu_draft.py" --random-post

# 3) 临时改文案 / 换封面
python "<skill_dir>/scripts/tietu_draft.py" --latest --title "周末壁纸" \
    --content "第一行\n\n第二行" --tags "#壁纸 #锁屏" --cover "E:/图片/新封面.jpg"

# 4) 原地改已有草稿（不新建、不删除、复用已上传素材）
python "<skill_dir>/scripts/tietu_draft.py" --update <draft_media_id>

# 5) 回读校验中文/图片数
python "<skill_dir>/scripts/tietu_draft.py" --verify <draft_media_id>
```

`--update` 的三种组合：
- 只改文案 + 换封面（默认）：复用旧图片，只上传新封面并替换第一张；
- `--update ... --cover-insert`：封面插入为第一张，旧图全部保留（总数 +1，上限 20）；
- `--update ... --rebuild-images --from-dir <DIR>`：连图片一起换掉，重新上传全部。

长文案可用 `--meta`（UTF-8 JSON，支持 `title` / `content` / `tags` / `topics`）：

```json
{
  "title": "今日壁纸",
  "content": "第一行\n\n第二行，随手记两句。",
  "tags": "#4K高清壁纸 #iOS壁纸 #手机壁纸 #锁屏壁纸 #高清壁纸"
}
```

`--out-json <path>` 可把结果落盘，方便定时任务推送通知。**最后一步永远是人工的**。

## 参数

| 参数 | 说明 |
|---|---|
| `--images PATH...` | 显式 1~20 张图片 |
| `--from-dir DIR` | 指定一个帖子目录 |
| `--latest` | 取 mtime 最新的一组（默认） |
| `--random-post` | 随机挑一组未投过的 |
| `--base-dir DIR` / `--author NAME` | 壁纸根目录 / 限定博主 |
| `--max-images N` | 从素材组取几张（默认 9）；固定封面额外占 1 张；`0` = 全部，总上限 20 |
| `--cover PATH` | 指定首图/封面，默认 `assets/cover_tom_jerry.jpg` |
| `--no-cover` | 本次不加固定封面 |
| `--cover-insert` | `--update` 时插入封面而非替换第一张 |
| `--title` / `--content` / `--tags` | 覆盖固定标题 / 正文 / 标签行 |
| `--topics` | 逗号分隔话题，转成官方 `#话题名#` 格式（覆盖默认标签） |
| `--no-tags` | 不追加任何标签 |
| `--meta JSON` | 从 UTF-8 JSON 读 title/content/tags/topics |
| `--strict-title` | 标题恢复 32 字节保守校验（默认 128 字节 / 64 字符） |
| `--update MEDIA_ID` | 原地更新已有草稿（`draft/update`，articles 为对象、index=0） |
| `--rebuild-images` | 配合 `--update`：不复用旧图，重新上传全部 |
| `--verify MEDIA_ID` | 回读草稿，打印标题/正文/图片数/中文编码检查 |
| `--force` | 已投过的组也重投 |
| `--check-only` | 只自检凭证与 IP 白名单 |
| `--dry-run` | 只挑图 + 校验文案，不联网（与 `--update` 组合时不会真的改草稿） |
| `--refresh-token` | 强制刷新 access_token |
| `--square-crop` | 给封面加 1:1 居中裁剪（默认不加） |
| `--no-comment` / `--fans-only-comment` | 默认开评论、所有人可评 |
| `--env PATH` / `--out-json PATH` | 指定凭证文件 / 结果输出 |

## 去重

`.state/used_posts.json` 记录每组图（key = 帖子目录绝对路径，显式图片则为路径列表哈希）：
`draft_media_id` / 时间 / 标题 / 图片数 / 文件名。默认**跳过已投过的组**，`--force` 才重投。
`--update` 不写这份记录（它改的是已有草稿，不是新投一组）。
和上游 `batch_download.py` 的 `.downloaded.json` 是两份独立清单，互不影响。

## 错误码速查

| 错误码 | 处理 |
|---|---|
| `40164` | 调用 IP 不在白名单。脚本会解析并打印「当前出口 IP = x.x.x.x」，加到「开发密钥 → API IP 白名单」后重跑 `--check-only` |
| `40007` | 用了非永久 MediaID。贴图图片必须走 `material/add_material`，**不能**用 `media/uploadimg` 的 URL |
| `40125` / `45166` | 图片消息参数 / content 不合法：检查 `article_type=newspic` 与纯文本正文，别混 HTML/JS |
| `45003` | 标题超长。默认已放宽到 128 字节 / 64 字符；若仍报错就缩短标题 |
| `45004` | 正文为空或超长 |
| `45009` | 频率超限，稍后重试；token 已做本地缓存，不要多实例各自刷新 |
| `48001` | 接口未授权。本脚本不该触发（不调发表接口）；若出现在草稿环节，检查认证状态 |
| `53404/53405/53406` | 带货能力相关，去掉商品信息 |

## 已知边界 / 踩坑记录

- **中文必须 UTF-8 原文发送**：脚本用 `json.dumps(..., ensure_ascii=False).encode("utf-8")` 手工序列化。
  用 `requests.post(json=payload)` 会把中文转成 `\uXXXX`，微信原样存进草稿，后台看全是乱码。
- **话题没有独立字段**：API 层只能在 `content` 里写标签文本。
- **「平台推荐」开关无 API 参数**（微信服务市场官方技术运营答复「不支持」）。后台手动发表时
  可以勾选，API 建的草稿不能显式配置；贴图主要吃公域推荐流量，介意这点的话最后一步人工反而更优。
- **后台「已发表文章一键转贴图」是 2026-08 灰度功能**，无 API，本 skill 不复刻。
- `freepublish` 发表属「未通知」内容，不群发推送粉丝、不占群发次数；贴图本身也不占群发次数。
- `draft/update` 的 `articles` 是**对象**且 `index` 必填（单篇填 0），和 `draft/add` 的
  `articles: []` 数组不同；写错会报参数错误。
- `cover_info.crop_percent_list[].ratio` 对 `newspic` 支持 `1_1` / `16_9` / `2.35_1`。

## 每日定时（可选，需用户明确要求）

用户说「每天定时生成一条贴图草稿」时，再建一条 recurring automation：
提示词写「用 wechat-tietu-draft 从壁纸目录随机取一组未投过的图，按固定风格建贴图草稿，
把结果通知我」，并把 skill 路径、壁纸根目录写进提示词。发表仍由人工完成。

## 给用户的简短说明

跑完一句话：草稿已建好（media_id=xxx，N 张图，首图为汤姆和杰瑞封面），去草稿箱或订阅号助手点发表即可。
不要说「已发布」。
