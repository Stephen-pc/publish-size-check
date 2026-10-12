#!/usr/bin/env python3
"""
一键演示：用临时生成的图片展示 publish-size-check 的几类典型结论。

    python demo.py

跑完自动清理，不留任何文件。不需要任何第三方包。
"""

import shutil
import struct
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPEC = HERE / "scripts" / "spec.py"

# 复用 spec.py 的 UTF-8 输出兜底。Windows 的 Python 默认按控制台代码页编码，
# 输出中文会崩——demo 里全是中文提示，同样需要这层保护。
sys.path.insert(0, str(HERE / "scripts"))
try:
    import spec as _spec
    _spec._force_utf8_stdout()
except ImportError:
    pass


def make_png(path, w, h, dpi=None):
    """生成一张内容无关、但头部信息真实的 PNG。"""
    def chunk(t, d):
        c = t + d
        return struct.pack(">I", len(d)) + c + struct.pack(">I", zlib.crc32(c) & 0xffffffff)

    raw = b"".join(b"\x00" + bytes([(x * 7 + y * 3) % 256 for x in range(w * 3)])
                   for y in range(h))
    out = b"\x89PNG\r\n\x1a\n"
    out += chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
    if dpi:
        ppm = int(dpi / 0.0254)
        out += chunk(b"pHYs", struct.pack(">IIB", ppm, ppm, 1))
    out += chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b"")
    path.write_bytes(out)


def run(label, files, target=None):
    print("\n" + "=" * 62)
    print(f"  {label}")
    print("=" * 62)
    cmd = [sys.executable, str(SPEC), "--check", *[str(f) for f in files]]
    if target:
        cmd += ["--target", target]
    subprocess.run(cmd)


def main():
    tmp = Path(tempfile.mkdtemp(prefix="psc-demo-"))
    try:
        # 1. AI 出图最常见的两种尺寸，投小红书
        a = tmp / "ai-square.png"
        b = tmp / "ai-portrait.png"
        make_png(a, 1024, 1024)
        make_png(b, 1024, 1536)
        run("场景 1：AI 出图 1024×1024 投小红书 —— 差一点点就过不了", [a], "小红书")
        run("场景 2：AI 出图 1024×1536 投小红书 —— 尺寸和比例都不对", [b], "小红书")

        # 3. dpi 达标但实际印不出来（本工具最独特的能力）
        trap = tmp / "journal.png"
        make_png(trap, 800, 600, dpi=300)
        run("场景 3：800×600 @300dpi 投稿 —— dpi 字段达标，但只印得出 68mm",
            [trap], "投稿")

        # 4. 合规文件应当静默通过
        ok = tmp / "ok.png"
        make_png(ok, 1242, 1660)
        run("场景 4：1242×1660 投小红书 —— 可以直接发", [ok], "小红书")

        # 5. 多图连发，指出该改哪一张
        c = tmp / "set-a.png"
        d = tmp / "set-b.png"
        make_png(c, 1242, 1660)
        make_png(d, 1080, 1440)
        run("场景 5：三张连发，其中一张尺寸不搭 —— 指出改哪一张",
            [ok, c, d], "小红书")

    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        print("\n" + "=" * 62)
        print("  演示结束，临时文件已清理。")
        print("=" * 62)


if __name__ == "__main__":
    main()
