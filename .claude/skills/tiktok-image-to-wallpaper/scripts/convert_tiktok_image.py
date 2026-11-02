#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TikTok 图片 -> 手机壁纸 JPEG 转换器（格式通吃版）。

支持两类输入：
  A. TikTok 的 *.image 私有格式（VVC/H.266 编码的 HEIF）：从 HEIF 抽出 VVC 码流，
     用本机 ffmpeg 的 `vvc` 解码器解码，再缩放输出 JPEG。
  B. 普通图片（jpg/png/webp/heic/avif/gif/bmp 等）：直接交给 ffmpeg 转码 + 缩放成 JPEG。

原理（仅 A 类需要）：
  TikTok 保存的 *.image 文件其实是 HEIF 容器，编码项为 vvc1（VVC / H.266），
  普通看图软件没有 VVC 解码器，所以全部“打不开”。本脚本：
    1. 从 HEIF 里解析出 vvcC 配置盒，取出 VPS/SPS/PPS 等参数集 NAL；
    2. 从 mdat 取出编码后的图像 NAL（单帧 IDR）；
    3. 重组成 Annex B 裸 VVC 流；
    4. 用本机 ffmpeg 的 `vvc` 解码器解码，缩放至手机尺寸并输出 JPEG。

前置条件：
  - 需要 ffmpeg（建议 n8.1+，含原生 vvc 解码器）。
  - 检查：ffmpeg -hide_banner -decoders 2>/dev/null | grep -i " vvc "

用法：
  python3 convert_tiktok_image.py <input.file> [output.jpg] [--4k]
  output 省略时，输出到 input 同目录：<stem>_wallpaper.jpg
  --4k：把长边升采样到 3840（4K 尺寸）。源若本就 <4K 则为插值放大，
        仅尺寸到 4K，不会凭空增加细节；真·4K 需 AI 超分（Real-ESRGAN 等）。
"""
import sys
import os
import struct
import subprocess
import tempfile


def box_walk(d, off, end, out=None):
    """递归遍历 ISO BMFF 盒子，返回 {type: [(box_off, box_size), ...]}。"""
    if out is None:
        out = {}
    while off + 8 <= end:
        size = struct.unpack('>I', d[off:off + 4])[0]
        typ = d[off + 4:off + 8].decode('latin1')
        hdr = 8
        if size == 1:
            size = struct.unpack('>Q', d[off + 8:off + 16])[0]
            hdr = 16
        elif size == 0:
            size = end - off
        out.setdefault(typ, []).append((off, size))
        if typ in ('meta', 'moov', 'trak', 'mdia', 'minf', 'stbl',
                   'iprp', 'ipco', 'iinf', 'mvex', 'udta'):
            coff = off + hdr + (4 if typ == 'meta' else 0)
            box_walk(d, coff, off + size, out)
        off += size
    return out


def parse_vvcC_nals(body):
    """解析 VVC Decoder Configuration Record，提取所有参数集 NAL 原始字节。"""
    pos = 0
    pos += 1                      # configurationVersion
    pos += 1                      # profile_space|tier|profile_idc
    pos += 4                      # profile_compatibility_flags
    pos += 6                      # constraint_indicator_flags
    pos += 1                      # level_idc
    pos += 1                      # ptl_frame_only|ptl_multilayer|reserved
    num_sub = body[pos]; pos += 1
    pos += num_sub * 4            # sub_profile_idc[]
    numOfArrays = body[pos]; pos += 1
    nals = []
    for _ in range(numOfArrays):
        pos += 1                  # array_completeness|reserved|NAL_unit_type
        numNalus = struct.unpack('>H', body[pos:pos + 2])[0]; pos += 2
        for _ in range(numNalus):
            ln = struct.unpack('>H', body[pos:pos + 2])[0]; pos += 2
            nals.append(body[pos:pos + ln]); pos += ln
    return nals


def parse_mdat_nals(mdat):
    """mdat 内是一串长度前缀的 NAL。依次尝试 4/2/8 字节前缀，取能完整消费整个 mdat 的。"""
    for plen in (4, 2, 8):
        if len(mdat) < plen:
            continue
        pos = 0
        nals = []
        ok = True
        while pos + plen <= len(mdat):
            L = int.from_bytes(mdat[pos:pos + plen], 'big')
            pos += plen
            if L == 0 or pos + L > len(mdat):
                ok = False
                break
            nals.append(mdat[pos:pos + L])
            pos += L
        if ok and nals:
            return nals
    return []


def is_vvc_heif(d):
    if len(d) < 12 or d[4:8] != b'ftyp':
        return False
    # brand vvic 或配置盒 vvcC 均可判定为 TikTok VVC/HEIF
    return (b'vvcC' in d[:8192]) or (b'vvic' in d[8:24])


def decode_vvc(inp, out, vf):
    with open(inp, 'rb') as f:
        d = f.read()
    boxes = box_walk(d, 0, len(d))
    vvcC = boxes.get('vvcC', [(None, None)])[0]
    if vvcC[0] is None:
        return False, "未找到 vvcC 配置盒（可能不是 TikTok VVC/HEIF）"
    vvcC_off, vvcC_size = vvcC
    cfg_nals = parse_vvcC_nals(d[vvcC_off + 8:vvcC_off + vvcC_size])
    mdat = boxes.get('mdat', [(None, None)])[0]
    if mdat[0] is None:
        return False, "未找到 mdat 数据盒"
    mdat_off, mdat_size = mdat
    pic_nals = parse_mdat_nals(d[mdat_off + 8:mdat_off + mdat_size])
    if not pic_nals:
        return False, "mdat 中未解析出编码图像 NAL"

    annex = b''
    for nal in cfg_nals:
        annex += b'\x00\x00\x00\x01' + nal
    for nal in pic_nals:
        annex += b'\x00\x00\x00\x01' + nal

    tmp = tempfile.NamedTemporaryFile(suffix='.vvc', delete=False)
    tmp.write(annex)
    tmp.close()
    cmd = ['ffmpeg', '-y', '-f', 'vvc', '-i', tmp.name,
           '-vf', vf, '-q:v', '3', '-frames:v', '1', '-update', '1', out]
    r = subprocess.run(cmd, capture_output=True, text=True)
    os.unlink(tmp.name)
    if r.returncode != 0 or not os.path.exists(out):
        return False, "ffmpeg vvc 解码失败（本机 ffmpeg 可能缺 vvc 解码器）\n" + (r.stderr or '')[-1500:]
    return True, None


def transcode_generic(inp, out, vf):
    cmd = ['ffmpeg', '-y', '-i', inp, '-vf', vf,
           '-q:v', '3', '-frames:v', '1', '-update', '1', out]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0 or not os.path.exists(out):
        return False, "ffmpeg 转码失败\n" + (r.stderr or '')[-1500:]
    return True, None


def coerce_jpg(path):
    if not path.lower().endswith(('.jpg', '.jpeg')):
        path = os.path.splitext(path)[0] + '.jpg'
    return path


def build_vf(fourk):
    if fourk:
        # 4K 模式：把长边升采样到 3840（保持比例、取偶数），lanczos 抗锯齿。
        # 注意：源若本就 <4K，这是“插值放大”，尺寸到 4K 但细节不增。
        return "scale='if(gt(iw,ih),3840,-2)':'if(gt(ih,iw),3840,-2)':flags=lanczos"
    # 默认：宽度封顶 1080，绝不放大超过 1080（保持原比例）。
    return "scale=min(1080\\,iw):-1"


def probe_dims(path):
    try:
        r = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0',
                            '-show_entries', 'stream=width,height',
                            '-of', 'csv=p=0', path],
                           capture_output=True, text=True)
        w, h = r.stdout.strip().split(',')
        return int(w), int(h)
    except Exception:
        return None, None


def main():
    args = sys.argv[1:]
    fourk = '--4k' in args
    if fourk:
        args.remove('--4k')
    if len(args) < 1:
        print("usage: convert_tiktok_image.py <input.file> [output.jpg] [--4k]")
        sys.exit(2)

    inp = args[0]
    if not os.path.exists(inp):
        print("ERROR: 输入文件不存在:", inp)
        sys.exit(2)

    out = (args[1] if len(args) > 1
           else os.path.splitext(inp)[0] + '_wallpaper.jpg')
    out = coerce_jpg(out)

    vf = build_vf(fourk)

    with open(inp, 'rb') as f:
        head = f.read(8192)

    if is_vvc_heif(head):
        ok, err = decode_vvc(inp, out, vf)
        tag = "VVC"
    else:
        ok, err = transcode_generic(inp, out, vf)
        tag = "通用"

    if not ok:
        print("ERROR: [" + tag + "] " + (err or "未知错误"))
        sys.exit(4)

    w, h = probe_dims(out)
    dim = (f"{w}x{h} " if w else "")
    mode = "[4K]" if fourk else ""
    print(f"OK [{tag}] {out}  {dim}({os.path.getsize(out)} bytes) {mode}")


if __name__ == '__main__':
    main()
