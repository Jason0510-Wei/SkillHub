#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TikTok .image (VVC/H.266 编码的 HEIF 私有格式) -> 手机壁纸 JPEG 转换器。

原理：
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
  python3 convert_tiktok_image.py <input.image> [output.jpg]
  output 省略时，输出到 input 同目录：<stem>_wallpaper.jpg
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


def main():
    if len(sys.argv) < 2:
        print("usage: convert_tiktok_image.py <input.image> [output.jpg]")
        sys.exit(2)

    inp = sys.argv[1]
    with open(inp, 'rb') as f:
        d = f.read()

    boxes = box_walk(d, 0, len(d))

    vvcC = boxes.get('vvcC', [(None, None)])[0]
    if vvcC[0] is None:
        print("ERROR: 未找到 vvcC 配置盒 —— 这可能不是 TikTok 的 VVC/HEIF .image 文件")
        sys.exit(3)
    vvcC_off, vvcC_size = vvcC
    cfg_nals = parse_vvcC_nals(d[vvcC_off + 8:vvcC_off + vvcC_size])

    mdat = boxes.get('mdat', [(None, None)])[0]
    if mdat[0] is None:
        print("ERROR: 未找到 mdat 数据盒")
        sys.exit(3)
    mdat_off, mdat_size = mdat
    pic_nals = parse_mdat_nals(d[mdat_off + 8:mdat_off + mdat_size])
    if not pic_nals:
        print("ERROR: mdat 中没有解析出编码图像 NAL")
        sys.exit(3)

    # 重组成 Annex B 裸流：参数集在前，图像 NAL 在后
    annex = b''
    for nal in cfg_nals:
        annex += b'\x00\x00\x00\x01' + nal
    for nal in pic_nals:
        annex += b'\x00\x00\x00\x01' + nal

    tmp = tempfile.NamedTemporaryFile(suffix='.vvc', delete=False)
    tmp.write(annex)
    tmp.close()

    out = (sys.argv[2] if len(sys.argv) > 2
           else os.path.splitext(inp)[0] + '_wallpaper.jpg')

    # 缩放至手机尺寸：宽度不超过 1080（9:16 壁纸），保持比例；JPEG 质量 q:v 3（高）
    vf = "scale=min(1080\\,iw):-1"
    cmd = ['ffmpeg', '-y', '-f', 'vvc', '-i', tmp.name,
           '-vf', vf, '-q:v', '3', '-frames:v', '1', '-update', '1', out]
    r = subprocess.run(cmd, capture_output=True, text=True)
    os.unlink(tmp.name)

    if r.returncode != 0 or not os.path.exists(out):
        print("ERROR: ffmpeg 解码失败（可能本机 ffmpeg 没有 vvc 解码器）")
        print(r.stderr[-2000:])
        sys.exit(4)

    print("OK " + out + "  (" + str(os.path.getsize(out)) + " bytes)")


if __name__ == '__main__':
    main()
