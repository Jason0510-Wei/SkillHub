#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把文件/目录移入 Windows 回收站（可还原），不依赖第三方包。

用 Shell32.SHFileOperationW + FOF_ALLOWUNDO 实现。E: 为本地盘，支持回收站；
网络盘 / 部分可移动盘可能不支持 ALLOWUNDO，此时函数会因原路径仍被删除而
返回失败告警，调用方应据此停止后续批次。

也可直接命令行使用：python recycle_bin.py <path> [<path> ...]
"""
import ctypes
import os
import struct
import sys
from ctypes import wintypes

FO_DELETE = 3
FOF_SILENT = 0x0004
FOF_NOCONFIRMATION = 0x0010
FOF_ALLOWUNDO = 0x0040
FOF_NOERRORUI = 0x0400


class SHFILEOPSTRUCTW(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("wFunc", wintypes.UINT),
        ("pFrom", wintypes.LPCWSTR),
        ("pTo", wintypes.LPCWSTR),
        ("fFlags", ctypes.c_uint16),
        ("fAnyOperationsAborted", wintypes.BOOL),
        ("hNameMappings", ctypes.c_void_p),
        ("lpszProgressTitle", wintypes.LPCWSTR),
    ]


def verify_in_recycle_bin(path):
    """扫描目标盘 $RECYCLE.BIN 的 $I 元数据，确认 path（或其子项）确实在回收站。

    光看「原路径消失」不够：万一 FOF_ALLOWUNDO 在该盘失效，会被永久删除。
    回收站 $I 条目格式（Win10+）：version/size/filetime [Q Q Q] + path_len [I]
    + UTF-16LE 原始路径。部分 SID 目录会拒绝访问，跳过即可。
    """
    p = os.path.normcase(os.path.abspath(path))
    drive = os.path.splitdrive(p)[0] + os.sep
    root = os.path.join(drive, "$RECYCLE.BIN")
    if not os.path.isdir(root):
        return False
    try:
        sids = os.listdir(root)
    except OSError:
        return False
    for sid in sids:
        d = os.path.join(root, sid)
        if not os.path.isdir(d):
            continue
        try:
            names = os.listdir(d)
        except OSError:
            continue
        for fn in names:
            if not fn.startswith("$I"):
                continue
            try:
                with open(os.path.join(d, fn), "rb") as fh:
                    raw = fh.read(28 + 8192)
                _ver, _size, _ft, plen = struct.unpack("<QQQI", raw[:28])
                if plen > 4096:
                    continue
                orig = raw[28:28 + plen * 2].decode("utf-16le", "ignore").rstrip("\0")
                o = os.path.normcase(os.path.abspath(orig))
                if o == p or o.startswith(p + os.sep):
                    return True
            except (OSError, struct.error, UnicodeError):
                continue
    return False


def send_to_recycle_bin(path):
    """返回 (ok, message)。以「原路径消失 + 回收站确有条目」为成功判据。

    SHFileOperationW 删除非空目录时可能返回非 0 / fAnyOperationsAborted 被置位，
    但操作其实已完整完成并进了回收站；因此 rc 只作为附加信息，不直接判失败。
    """
    p = os.path.abspath(path)
    if not os.path.exists(p):
        return False, "路径不存在：%s" % p
    op = SHFILEOPSTRUCTW()
    op.hwnd = None
    op.wFunc = FO_DELETE
    op.pFrom = p + "\0"          # SHFileOperationW 要求 pFrom 以双 NUL 结尾
    op.pTo = None
    op.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT | FOF_NOERRORUI
    rc = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    aborted = bool(op.fAnyOperationsAborted)
    if os.path.exists(p):
        return False, "原路径仍在（rc=%s aborted=%s）：%s" % (rc, aborted, p)
    if not verify_in_recycle_bin(p):
        return False, ("原路径已消失，但回收站里没有对应条目，可能是永久删除，请立即检查：%s "
                       "(rc=%s aborted=%s)") % (p, rc, aborted)
    extra = "" if (rc == 0 and not aborted) else "（rc=%s aborted=%s，回收站校验通过）" % (rc, aborted)
    return True, "已移入回收站%s：%s" % (extra, p)


if __name__ == "__main__":
    failed = 0
    for arg in sys.argv[1:]:
        ok, msg = send_to_recycle_bin(arg)
        print(("[OK] " if ok else "[FAIL] ") + msg)
        if not ok:
            failed += 1
    sys.exit(1 if failed else 0)
