#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
三平台稿件自检
------------------------------------------------------------
用法：
  python check_output.py <输出目录>            # 常规检查
  python check_output.py <输出目录> --strict   # WARN 也算失败

检查项：
  1. 元信息完整性（标题/字数/发布时间/声明；百家号另需分类/标签）
  2. 标题字数（头条 15-30，百家号 ≤40，公众号 ≤64）
  3. 正文字数区间
  4. Markdown 残留（头条/百家号正文出现 ** ## - > 会原样显示）
  5. 外链（百家号禁止一切 http/https）
  6. 标题禁用词、敏感操作词
  7. 未标注的传闻句
  8. HTML 结构（<style> 标签、flex/grid、标签配对）
  9. 反搬运：三份稿件的标题、开头是否雷同

退出码：0 全部通过 / 1 有 FAIL（或 --strict 下有 WARN）
"""
import sys, re, os
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

C_OK, C_WARN, C_FAIL = "[ OK ]", "[WARN]", "[FAIL]"
issues = {"fail": 0, "warn": 0}


def emit(level, where, msg):
    print(f"{level} {where}: {msg}")
    if level == C_FAIL:
        issues["fail"] += 1
    elif level == C_WARN:
        issues["warn"] += 1


def strip_ws(s):
    return re.sub(r"\s", "", s)


# ---------- 词表 ----------
TITLE_BANNED = ["震惊", "吓哭", "必看", "速看", "删前", "不看后悔", "不转后悔", "99%的人不知道",
                "千万人不知", "紧急通知", "刚刚曝光", "重磅"]
# 极限词：标题里出现即高风险（广告法口径）
TITLE_EXTREME = ["第一", "唯一", "独家", "顶级", "国家级", "世界级", "极致",
                 "根治", "特效", "必好", "防癌", "100%", "史上"]
# 极限词：正文里也该清掉的强命中项（"最"太宽泛，不扫正文）
BODY_EXTREME = ["根治", "特效", "包治", "100%", "史上最", "唯一", "世界级"]
RISKY_OPS = ["反代", "中转站", "过风控", "封号率", "账号池", "指纹浏览器", "KYC", "虚拟卡",
             "批量注册", "去授权", "破解", "薅秃", "套利窗口", "绕过检测", "改时区"]
HEDGE_WORDS = ["据传", "网传", "消息称", "据说", "有爆料", "内部人士"]
HEDGE_MARK = "传闻"


def read(p):
    return p.read_text(encoding="utf-8", errors="replace")


def head_field(text, key):
    """取元信息头里 '键：值' 的值"""
    m = re.search(rf"^{re.escape(key)}\s*[：:]\s*(.+)$", text, re.M)
    return m.group(1).strip() if m else None


TUWEI_LINE = re.compile(r"^\s*(?:【图位\d.*|画面[:：].*|色调[:：].*|尺寸[:：].*|"
                        r"提示词[:：].*|注意[:：].*|[⚠💡].*|🖼.*|"
                        r"[A-Za-z ,.\-]{40,})\s*$", re.M)


def strip_tuwei(text):
    """去掉配图图位说明块——它不是正文，不该算字数、也不该参与查重"""
    text = re.sub(r"<[^>]+>", "", text)          # HTML 先脱标签
    lines = [ln for ln in text.splitlines() if not TUWEI_LINE.match(ln)]
    return "\n".join(lines)


def body_of(text):
    """取元信息头之后的正文"""
    for sep in ("以下为正文", "【正文】", "【导语】"):
        i = text.find(sep)
        if i >= 0:
            b = text[i + len(sep):]
            b = re.sub(r"^[^\n]*\n", "", b, count=1)     # 去掉分隔符所在行的尾巴
            return strip_tuwei(b.lstrip("\n-─ "))
    return strip_tuwei(text)


# ---------- 各平台规则 ----------
PLATFORMS = {
    "头条.md": {"title_max": 30, "title_min": 15, "body": (1100, 2100),
                "need": ["标题", "字数", "发布时间", "声明"], "links": "warn"},
    "百家号.md": {"title_max": 40, "title_min": 15, "body": (1300, 2400),
                  "need": ["标题", "字数", "发布时间", "声明", "分类", "标签"], "links": "fail"},
}


def check_plain(p: Path, rule: dict):
    txt = read(p)
    name = p.name

    # 元信息
    for key in rule["need"]:
        if not head_field(txt, key):
            emit(C_FAIL, name, f"元信息缺少「{key}：」")

    title = head_field(txt, "标题") or ""
    if title:
        n = len(title)
        if n > rule["title_max"]:
            emit(C_FAIL, name, f"标题 {n} 字，超过上限 {rule['title_max']}")
        elif n < rule["title_min"]:
            emit(C_WARN, name, f"标题仅 {n} 字，偏短（建议 {rule['title_min']}-{rule['title_max']}）")
    else:
        emit(C_FAIL, name, "找不到标题行")

    body = body_of(txt)
    n = len(strip_ws(body))
    lo, hi = rule["body"]
    if n < lo:
        emit(C_WARN, name, f"正文 {n} 字，低于建议下限 {lo}")
    elif n > hi:
        emit(C_WARN, name, f"正文 {n} 字，超过建议上限 {hi}（考虑拆条）")
    else:
        print(f"{C_OK} {name}: 正文 {n} 字")

    # Markdown 残留
    md = []
    if "**" in body:
        md.append("**")
    if re.search(r"^#{1,6}\s", body, re.M):
        md.append("##")
    if re.search(r"^\s*[-*]\s+", body, re.M):
        md.append("- 列表")
    if re.search(r"^\s*>\s", body, re.M):
        md.append("> 引用")
    if md:
        emit(C_FAIL, name, f"正文残留 Markdown 符号（粘贴后会原样显示）：{'、'.join(md)}")

    # 外链
    urls = re.findall(r"https?://[^\s)\]】）]+", body)
    if urls:
        lv = C_FAIL if rule["links"] == "fail" else C_WARN
        emit(lv, name, f"正文含 {len(urls)} 个外链：{urls[0][:50]}")

    # 标题禁用词
    for w in TITLE_BANNED:
        if w in title:
            emit(C_FAIL, name, f"标题含标题党词「{w}」")
    for w in TITLE_EXTREME:
        if w in title:
            emit(C_FAIL, name, f"标题含极限词「{w}」（见 extreme-words.md）")

    # 正文极限词
    hits = [w for w in BODY_EXTREME if w in body]
    if hits:
        emit(C_WARN, name, f"正文含极限词：{'、'.join(hits)}（能换就换）")

    # 「第一是」误判坑
    seq = re.findall(r"^\s*第[一二三四五](?:是|[，、])", body, re.M)
    if seq:
        emit(C_WARN, name, f"含 {len(seq)} 处「第N，」序号写法，机器审核可能误判为极限词，建议改「一是／二是」")

    # 图位说明块残留（用全文检测，因为 body 已洗净）
    marks = len(re.findall(r"【图位\d", txt))
    if marks:
        emit(C_WARN, name, f"仍有 {marks} 个【图位N】说明块，发布前请整块删掉换成图片")

    # 加粗配额（只算 ≥15 字的整句加粗）
    emph = [m for m in re.findall(r"\*\*(.+?)\*\*", body, re.S) if len(m.strip()) >= 15]
    if len(emph) > 15:
        emit(C_WARN, name, f"整句加粗 {len(emph)} 处，偏多（公众号长文建议每小节 ≤2 处、总 ≤15）")

    # 敏感操作词
    hits = [w for w in RISKY_OPS if w in body]
    if hits:
        emit(C_FAIL, name, f"含规避平台风控类表述：{'、'.join(hits)}（见 compliance.md）")

    # 未标注传闻
    for sent in re.split(r"[。！？\n]", body):
        if any(h in sent for h in HEDGE_WORDS) and HEDGE_MARK not in sent:
            emit(C_WARN, name, f"疑似未标注源级别的表述：…{sent.strip()[:40]}…")


def check_html(p: Path):
    txt = read(p)
    name = p.name
    before_f, before_w = issues["fail"], issues["warn"]

    if re.search(r"<style[\s>]", txt, re.I):
        emit(C_FAIL, name, "含 <style> 标签，微信编辑器会过滤，必须改为 inline style")
    if re.search(r"display\s*:\s*(flex|grid)", txt, re.I):
        emit(C_WARN, name, "含 flex/grid 布局，部分微信客户端会失效（建议改 inline-block 或普通块）")

    for tag in ("section", "p", "span"):
        o = len(re.findall(rf"<{tag}[\s>]", txt))
        c = len(re.findall(rf"</{tag}>", txt))
        if o != c:
            emit(C_FAIL, name, f"<{tag}> 标签不配对：开 {o} 关 {c}")

    if "{{" in txt:
        emit(C_WARN, name, "模板占位符 {{…}} 未替换")

    if re.search(r"https?://", txt):
        emit(C_WARN, name, "含外链，公众号正文只能引用公众号文章")

    # 只统计"整句加粗"（≥15 字），关键词高亮属排版手段不计入
    emph = [m for m in re.findall(r"<strong[^>]*>(.*?)</strong>", txt, re.S)
            if len(re.sub(r"<[^>]+>", "", m).strip()) >= 15]
    if len(emph) > 15:
        emit(C_WARN, name, f"整句加粗 {len(emph)} 处，偏多（公众号长文建议每小节 ≤2 处、总 ≤15）")

    if re.search(r"图位\s*\d", txt):
        emit(C_WARN, name, "HTML 里仍有图位说明块，发布前请整块替换为图片")

    if not re.search(r"max-width\s*:\s*677px", txt):
        emit(C_WARN, name, "根容器未见 max-width:677px，微信正文宽度可能溢出")

    hit = re.search(r"<h1[\s>]", txt, re.I)
    if hit:
        emit(C_WARN, name, "含 <h1>，微信会覆写成怪异样式，建议用带样式的 section 模拟标题")

    if issues["fail"] == before_f and issues["warn"] == before_w:
        print(f"{C_OK} {name}: HTML 结构检查完成")


HEAD_PAT = re.compile(r"^\s*(?:【\s*[一二三四五六七八九十]+\s*】|"
                      r"[一二三四五六七八九十]+\s*[、.．]|"
                      r"[（(]\s*[一二三四五六七八九十]+\s*[）)])\s*(.*)$")
# 公众号 HTML 的小标题是 19px 加粗 span
HTML_HEAD_PAT = re.compile(r"font-size:19px;font-weight:700[^>]*>([^<]{2,30})<")


def extract_headings(text, is_html=False):
    """抽出小标题文字（不含序号）。小标题雷同比长段重复更容易被判搬运。"""
    if is_html:
        return [h.strip() for h in HTML_HEAD_PAT.findall(text) if 2 <= len(h.strip()) <= 30]
    out = []
    for ln in text.splitlines():
        m = HEAD_PAT.match(ln)
        if not m:
            continue
        h = re.sub(r"[：:，,。\s]+$", "", m.group(1).strip())
        if 2 <= len(h) <= 30:
            out.append(h)
    return out


def check_duplication(files):
    """反搬运：标题、开头必须不同；长共同子串过多则告警"""
    got = {}
    for p in files:
        txt = read(p)
        title = head_field(txt, "标题") or ""
        body = body_of(txt) if p.suffix == ".md" else re.sub(r"<[^>]+>", "", txt)
        body = strip_ws(body)
        heads = extract_headings(txt, is_html=(p.suffix == ".html"))
        got[p.name] = (title, body, heads)

    before_f, before_w = issues["fail"], issues["warn"]
    names = list(got)
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a, b = names[i], names[j]
            ta, ba, ha_ = got[a]
            tb, bb, hb_ = got[b]
            if ta and ta == tb:
                emit(C_FAIL, "反搬运", f"{a} 与 {b} 标题完全相同")
            ha, hb = ba[:60], bb[:60]
            if ha and ha == hb:
                emit(C_FAIL, "反搬运", f"{a} 与 {b} 开头 60 字完全相同")
            # 最长公共子串（二分 + 子串集合，2000 字内可接受）
            common = _longest_common(ba[:2000], bb[:2000])
            if common >= 45:
                emit(C_WARN, "反搬运", f"{a} 与 {b} 有 {common} 字连续重复，建议改写")

            # 小标题雷同（短文本，长段阈值抓不到，必须单独比）
            for x in ha_:
                for y in hb_:
                    if x == y:
                        emit(C_FAIL, "反搬运", f"{a} 与 {b} 小标题完全相同：「{x}」")
                    elif _ratio(x, y) >= 0.75:
                        emit(C_WARN, "反搬运",
                             f"{a} 与 {b} 小标题高度相似：「{x}」/「{y}」")

    if issues["fail"] == before_f and issues["warn"] == before_w:
        print(f"{C_OK} 反搬运: 比对完成（{len(names)} 份）")


def _ratio(a, b):
    """两段短文本的相似度（0-1）"""
    import difflib
    return difflib.SequenceMatcher(None, a, b).ratio()


def _longest_common(a, b):
    """后缀自动机太重，用滚动集合求最长公共子串长度（n<=1500 可接受）"""
    best = 0
    lo, hi = 10, min(len(a), len(b))
    while lo <= hi:
        mid = (lo + hi) // 2
        seen = {a[i:i + mid] for i in range(len(a) - mid + 1)}
        if any(b[i:i + mid] in seen for i in range(len(b) - mid + 1)):
            best, lo = mid, mid + 1
        else:
            hi = mid - 1
    return best


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    strict = "--strict" in sys.argv
    if not args:
        print("用法: python check_output.py <输出目录> [--strict]")
        sys.exit(2)

    d = Path(args[0])
    if not d.is_dir():
        print(f"目录不存在: {d}")
        sys.exit(2)

    print(f"检查目录: {d}\n" + "-" * 60)

    plain = []
    for fname, rule in PLATFORMS.items():
        p = d / fname
        if p.exists():
            check_plain(p, rule)
            plain.append(p)
        else:
            emit(C_WARN, fname, "文件不存在（跳过）")

    htmls = list(d.glob("*.html"))
    if not htmls:
        emit(C_WARN, "公众号", "未找到 .html 文件（跳过）")
    for h in htmls:
        check_html(h)

    allf = [p for p in (d / "头条.md", d / "百家号.md", d / "公众号.md") if p.exists()]
    if len(allf) >= 2:
        check_duplication(allf)
    else:
        emit(C_WARN, "反搬运", "公众号.md 缺失，无法三向比对")

    print("-" * 60)
    print(f"结果：FAIL {issues['fail']} 项，WARN {issues['warn']} 项")
    if issues["fail"]:
        print("存在 FAIL，请修正后再交付。")
        sys.exit(1)
    if strict and issues["warn"]:
        print("strict 模式下 WARN 视为失败。")
        sys.exit(1)
    print("通过。WARN 项请人工判断，并在发布说明里写明结论。")


if __name__ == "__main__":
    main()
