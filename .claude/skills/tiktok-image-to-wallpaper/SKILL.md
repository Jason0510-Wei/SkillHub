---
name: tiktok-image-to-wallpaper
description: >-
  将 TikTok 保存的 .image 文件（VVC/H.266 编码的 HEIF 私有格式，普通看图软件打不开）转换为手机壁纸 JPEG。当用户丢来 .image 文件、说“tiktok 图片打不开”、“转成手机壁纸”、“转换为壁纸”、“TikTok image 转 jpg”、“.image 文件”时使用。自动从 HEIF 抽取 VVC 码流并用 ffmpeg 的 vvc 解码器解码，输出缩放至手机尺寸（宽度 ≤1080）的 JPG。
agent_created: true
version: 1.0.0
display_name: "TikTok图片转手机壁纸"
display_name_en: "TikTok .image to Phone Wallpaper"
description_zh: "将 TikTok 的 VVC/HEIF .image 私有格式图片解码并转换为手机壁纸 JPEG。"
description_en: "Decode TikTok's VVC/HEIF .image file and convert it to a phone-sized JPEG wallpaper."
visibility: "user"
---

# TikTok .image → 手机壁纸 JPEG

> ⚠️ **前置依赖**：这套流程依赖本机 ffmpeg 带 `vvc` 解码器（你这台已具备）；换机器先跑 `ffmpeg -decoders | grep vvc` 自检，没有就换带 VVC 解码的 ffmpeg 版本。

## 这是什么

TikTok 保存的 `*.image` 文件其实是 **VVC（H.266）编码的 HEIF 容器**（文件头 brand 为 `vvic`，编码项 `vvc1`）。
几乎没有任何看图软件内置 VVC 解码器，所以会“打不开”。本 skill 用 ffmpeg 的原生 `vvc` 解码器把它还原成普通 JPEG。

## 前置条件

- 本机需安装 **ffmpeg（建议 n8.1+，含原生 `vvc` 解码器）**。
- 自检命令（解码器列表里应有 `vvc`）：

```bash
ffmpeg -hide_banner -decoders 2>/dev/null | grep -i " vvc "
```

若无 `vvc` 解码器，本流程无法进行，需更换带 VVC 解码的 ffmpeg。

## 使用流程

1. 用户给出 `.image` 文件路径（绝对路径）。
2. 运行转换脚本（脚本自带 HEIF 解析 + ffmpeg 解码 + 缩放 + 转 JPEG，无需手动分步）：

```bash
python3 "<skill_dir>/scripts/convert_tiktok_image.py" "C:/path/to/xxx.image"
```

- 第二个参数可指定输出 JPG 路径；省略时输出到输入同目录，名为 `<原名>_wallpaper.jpg`。
- 输出规格：JPEG，宽度 ≤1080（9:16 手机壁纸比例，保持原比例，不放大），质量 `-q:v 3`（高）。

3. 转换成功会打印 `OK <输出路径> (<字节数> bytes`。
4. 用 `present_files` 把生成的 JPG 直接展示给用户。

## 异常处理

- 未找到 `vvcC` 盒 / `mdat` 盒 → 提示“可能不是 TikTok 的 VVC/HEIF .image 文件”，不要硬转。
- ffmpeg 返回非 0 或输出文件不存在 → 提示本机 ffmpeg 可能缺 `vvc` 解码器，给出自检命令。
- 若解码出来画面花屏/异常，说明该文件可能用了不同封装变体，可回退到手动解析 iloc 定位数据（参考脚本注释）。

## 给用户的简短说明

完成后用一句话告诉用户：原文件是 TikTok 私有 VVC 格式所以打不开，已转成可直接使用的手机壁纸 JPG，并给出文件路径。
