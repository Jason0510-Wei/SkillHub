# 自媒体 AI 工具箱 🎬

> 用 Claude Code 帮自媒体博主做**白皮书解读、热点抓取、数据复盘、小红书套图、AI 生图**。
> 零代码基础即可使用，对话就能出选题、出周报、出配图。

## ✨ 能做什么

| Skill | 功能 | 用法 |
|-------|------|------|
| 🧠 **whitepaper** | 白皮书 / 行业报告解读 → 多平台选题 + 自动配图 | 丢 PDF 进 `输入/`，说"解读 xxx.pdf" |
| ✍️ **tri-platform-rewrite** | 一份 PDF / 长文 / 日报 → 头条 + 百家号 + 公众号三平台稿件（差异化改写 + 各平台排版 + 合规与查重自检） | 丢 PDF，说"按三平台洗" |
| 🔥 **hotspot** | 抓今日全网热点 + 按赛道打分 + 自动出封面图 | 说"今天有什么热点" |
| 📊 **review** | 导入平台数据 CSV/XLSX → 周报 + 下周建议 | 说"复盘 xxx.xlsx" |
| 🎨 **xhs-poster** | 小红书 6 图套图生成器（文案 + AI 配图） | 说"做一套小红书图文" |
| 🖼️ **hy-image-generation** | 腾讯云混元生图 3.0，文生图 / 图生图 | 说"用混元画一只猫" |
| 📱 **tiktok-image-to-wallpaper** | TikTok 链接 / `.image`（VVC/HEIF）→ 手机壁纸；默认原图直出、按 `1_A/1_B` 成对归档（A 展示图 / B 原图），支持博主热度分析与批量下载 | 丢链接或 `.image`，说"转成手机壁纸" |
| 📮 **wechat-tietu-draft** | 壁纸图集 → 微信公众号「贴图」草稿（固定封面 + 固定文案，只到草稿箱由人手动发表） | 说"发贴图 / 把壁纸发到公众号" |
| 🗂️ **wallpaper-batch-splitter** | 把一批编号文件夹按「每组 8 张壁纸 + 1 张固定配图」重新分组，多出来的自动新建文件夹往下排号（带备份 / dry-run / 回滚） | 说"每个文件夹只放八张壁纸"或"多出来的往下排号" |
| 🔗 **wallpaper-daily-pipeline** | 把上面三个 skill 串成一条流水线（薄编排，下载与发帖仍互相独立）：筛点赞过万 → 批量下载 → 每组 4 对 A/B + 汤姆和杰瑞封面 → 每次投 4 组进公众号草稿箱 | 说"整合 skill / 下载点赞过万的壁纸 / 每天发 4 组贴图" |

whitepaper / hotspot / review / xhs-poster 四个 Skill 共享一份**账号画像**配置，改一次全部生效。

## 🎁 可选增强：接入图片生成

### 方案 A：Nano Banana MCP（Gemini 2.5 Flash Image，推荐）

装好后，whitepaper / hotspot / xhs-poster 三个 Skill 会**自动生图**，不再只给你 prompt。

1. 去 https://aistudio.google.com/apikey 申请免费 Gemini API key
2. 在终端执行：

```bash
claude mcp add nano-banana --scope user \
  --env GEMINI_API_KEY=你的KEY \
  -- npx -y @willh/nano-banana-mcp
```

3. 重启 Claude Code，MCP 就会自动加载

不装也能用，Skill 会降级为"给你 prompt 让你自己去画图工具生成"。

### 方案 B：腾讯云混元生图 3.0（hy-image-generation Skill）

内置 Skill，无需额外安装 MCP。基于腾讯混元大模型，支持垫图引导和 Prompt 智能改写。

1. 开通 [腾讯云智能图像创作](https://console.cloud.tencent.com/aiart)
2. 获取 [API 密钥](https://console.cloud.tencent.com/cam/capi)
3. 设置环境变量（或让 Claude 帮你配置）：

```bash
# Linux / macOS
export TENCENTCLOUD_SECRET_ID="你的SecretId"
export TENCENTCLOUD_SECRET_KEY="你的SecretKey"

# Windows PowerShell
$env:TENCENTCLOUD_SECRET_ID = "你的SecretId"
$env:TENCENTCLOUD_SECRET_KEY = "你的SecretKey"
```

然后直接说"用混元画一只猫"或"生成图片：xxx"即可。

## 🚀 快速开始

### 1. 装 Claude Code

```bash
# 需要先装 Node.js (https://nodejs.org)
npm install -g @anthropic-ai/claude-code
```

首次使用需要登录 Claude 账号（订阅用户直接登录，**无需 API key**）。

### 2. Clone 仓库

```bash
git clone https://github.com/YOUR_USERNAME/self-media-toolkit.git
cd self-media-toolkit
```

### 3. 填画像（⭐ 必做，最关键的一步）

打开 `配置/账号画像.md`，把模板改成你自己的真实情况。

**画像越详细，AI 给的结果越精准**。重点填：
- 账号定位
- 目标人群
- 核心关键词 TOP 10
- 禁区

不想自己填？直接对 Claude 说：「帮我问着填画像」，它会引导式提问。

### 4. 启动

```bash
claude
```

然后对话：
- `今天有什么热点？` → 触发 hotspot
- `解读 输入/xxx.pdf` → 触发 whitepaper
- `复盘 输入/xxx.xlsx` → 触发 review
- `做一套小红书图文` → 触发 xhs-poster
- `用混元画一只猫` → 触发 hy-image-generation
- `每个文件夹只放八张壁纸，多出来的往下排号` → 触发 wallpaper-batch-splitter
- `发贴图 / 把壁纸发到公众号` → 触发 wechat-tietu-draft
- `整合 skill / 下载点赞过万的壁纸 / 每天发 4 组贴图` → 触发 wallpaper-daily-pipeline

## 📁 目录结构

```
self-media-toolkit/
├── .claude/skills/          # AI Skill（不用管）
│   ├── whitepaper/          # 白皮书解读
│   ├── tri-platform-rewrite/ # 一稿三发（头条/百家号/公众号）
│   ├── hotspot/             # 热点抓取
│   ├── review/              # 数据复盘
│   ├── xhs-poster/          # 小红书套图
│   ├── hy-image-generation/ # 腾讯云混元生图
│   ├── tiktok-image-to-wallpaper/ # TikTok 链接 → 壁纸
│   ├── wallpaper-batch-splitter/  # 壁纸 8+1 分组 + 自动编号
│   ├── wechat-tietu-draft/       # 壁纸 → 公众号贴图草稿
│   └── wallpaper-daily-pipeline/  # 下载 → 8+1 → 草稿箱 编排层
├── 配置/
│   └── 账号画像.md          # ⭐ 先填这个
├── 输入/                    # 放 PDF、数据表（本地，不上传）
├── 输出/                    # AI 生成的报告（本地，不上传）
├── 使用说明.md              # 详细用法
└── README.md
```

## 🔧 多设备同步

```bash
# A 电脑修改了画像 / Skill：
git add . && git commit -m "update" && git push

# B 电脑拉取：
git pull
```

> 默认 `.gitignore` 已忽略 `输入/`、`输出/` 和 `*.backup.md`，
> 保护你本地的数据和个人画像备份不会被推到公网。

## 🤝 使用场景示例

### 每日早间 brief

```
今天有什么热点？只看小红书，重点关注 AI 副业方向。
```

### 读一份报告做一周选题

```
解读 输入/艾瑞2026AI消费报告.pdf，
给我一周 5 条内容的发布节奏。
```

### 周末复盘

```
复盘 输入/抖音_2026-04-15_2026-04-21.xlsx，
对比 输入/抖音_2026-04-08_2026-04-14.xlsx 给我环比分析。
```

### 组合拳

```
先抓今日热点，然后结合 输入/XX白皮书.pdf，
给我出 3 条本周能拍的短视频脚本。
```

### 一份报告，三个平台

```
把 输入/XX行业报告.pdf 洗成三个平台的稿子，
头条和百家号要大白话，公众号保留深度，我检查后自己发。
```

产出：`公众号.html`（可直接粘进微信编辑器）、`头条.md`、`百家号.md`（都带发布元信息头）、`发布说明.md`（标题候选 / 发布时间 / 配图提示词 / 合规清单）。

### AI 生图

```
用混元画一张：夕阳下的咖啡馆，温馨治愈风格
```

```
用混元生成一张竖版封面图，主题是"2026 AI 副业指南"
```

## ❓ FAQ

**Q: 需要 Claude API key 吗？**
A: 不需要。Claude Code 订阅用户直接登录即可。

**Q: 为什么要填画像？**
A: AI 出的选题要匹配你的赛道、人设、禁区，否则给的是通用内容，效果会差。

**Q: Skill 加载失败？**
A: 确认启动 Claude Code 的目录就是仓库根目录（能看到 `.claude/` 文件夹）。

**Q: 想加新的 Skill？**
A: 在 `.claude/skills/` 下新建文件夹，写个 `SKILL.md` 即可，参考现有的 Skill。

## 📄 License

MIT
