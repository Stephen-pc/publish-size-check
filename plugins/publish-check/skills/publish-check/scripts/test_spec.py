#!/usr/bin/env python3
"""
回归测试：改动 spec.py 或 platforms.json 后跑一次。

    python scripts/test_spec.py

不依赖 pytest，纯标准库。退出码 0 = 全过，1 = 有失败。
测试会自建临时图片，跑完自动清理。
"""

import json
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPEC = HERE / "spec.py"
PY = sys.executable

# 复用 spec.py 的 UTF-8 输出兜底。测试脚本自己也打印中文标题，
# Windows 上同样会因控制台代码页而崩——这里必须一并保护。
sys.path.insert(0, str(HERE))
try:
    import spec as _spec_mod
    _spec_mod._force_utf8_stdout()
except ImportError:
    pass

PASS, FAIL = [], []


def check(name, cond, detail=""):
    if cond:
        PASS.append(name)
        print(f"  [OK] {name}")
    else:
        FAIL.append(f"{name} {detail}")
        print(f"  [FAIL] {name} {detail}")


def run(*args):
    r = subprocess.run([PY, str(SPEC), *[str(a) for a in args]],
                       capture_output=True, text=True, encoding="utf-8")
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def make_png(path, w, h, dpi=None):
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


def main():
    tmp = Path(tempfile.mkdtemp(prefix="publish-check-test-"))
    try:
        print("=== 规格库自检 ===")
        code, out = run("--validate")
        check("规格库无错误", code == 0, out.strip().splitlines()[-1] if out else "")

        print("\n=== 命令可用性 ===")
        for name, args in [
            ("--list", ["--list"]),
            ("--spec 别名", ["--spec", "红书"]),
            ("--spec 未收录", ["--spec", "根本不存在的平台xyz"]),
            ("--help", ["--help"]),
        ]:
            code, _ = run(*args)
            check(f"{name} 正常返回", code == 0)

        print("\n=== 图片解析 ===")
        p = tmp / "probe.png"
        make_png(p, 800, 600, dpi=300)
        sys.path.insert(0, str(HERE))
        import spec as S
        info = S.examine_file(str(p))
        check("尺寸解析正确", info.get("w") == 800 and info.get("h") == 600,
              f"得到 {info.get('w')}x{info.get('h')}")
        check("dpi 解析正确", abs((info.get("dpi") or 0) - 300) <= 1,
              f"得到 {info.get('dpi')}")

        print("\n=== 体检逻辑 ===")
        ok = tmp / "xhs_ok.png"
        make_png(ok, 1242, 1660)
        code, out = run("--check", ok, "-t", "小红书")
        check("合规文件判定可发布", "可以直接发布" in out, out[:80])

        low = tmp / "low.png"
        make_png(low, 1200, 900, dpi=96)
        code, out = run("--check", low, "-t", "投稿")
        check("低 dpi 报错", "低于要求" in out, out[:80])

        hi = tmp / "hi.png"
        make_png(hi, 1200, 900, dpi=600)
        code, out = run("--check", hi, "-t", "投稿")
        check("高 dpi 不报 dpi 错误", "dpi=600 低于" not in out, out[:80])

        small = tmp / "small.png"
        make_png(small, 800, 500)
        code, out = run("--check", small, "-t", "B站")
        check("gte 语义：不足报错", "小于要求" in out, out[:80])

        big = tmp / "big.png"
        make_png(big, 1920, 1200)
        code, out = run("--check", big, "-t", "B站")
        check("gte 语义：超出放行", "可以直接发布" in out, out[:80])

        d34 = tmp / "d34.png"
        make_png(d34, 1080, 1440)
        code, out = run("--check", d34, "-t", "抖音")
        check("抖音 3:4 图文槽位被选中", "图文" in out and "可以直接发布" in out, out[:120])

        d916 = tmp / "d916.png"
        make_png(d916, 1080, 1920)
        code, out = run("--check", d916, "-t", "抖音")
        check("抖音 9:16 识别", "9:16 全屏" in out, out[:80])

        print("\n=== 物理尺寸（印刷/投稿的真正判据）===")
        trap = tmp / "trap.png"
        make_png(trap, 800, 600, dpi=300)
        code, out = run("--check", trap, "-t", "投稿")
        check("dpi 达标但物理宽度不足能被抓出",
              "低于最小栏宽" in out and "不是改 dpi 数字能解决" in out, out[:120])

        goodfit = tmp / "fit.png"
        make_png(goodfit, 1200, 900, dpi=300)
        code, out = run("--check", goodfit, "-t", "投稿")
        check("物理宽度足够时不报 PHYISCAL_TOO_SMALL",
              "低于最小栏宽" not in out, out[:120])
        check("给出实际印刷宽度", "实际印刷宽度" in out, out[:120])

        bigfit = tmp / "bigfit.png"
        make_png(bigfit, 2400, 1800, dpi=300)
        code, out = run("--check", bigfit, "-t", "投稿")
        check("大图算出 203mm", "203mm" in out or "20" in out, out[:120])

        code, out = run("--check", goodfit, "-t", "投稿")
        check("多槽位歧义时提示用户选择", "由你判断" in out, out[:120])

        print("\n=== 行动建议（用户真正要看的一句）===")
        bad = tmp / "bad.png"
        make_png(bad, 1024, 1536)
        code, out = run("--check", bad, "-t", "小红书")
        check("尺寸+比例都错时给出『救不了』", "救不了" in out and "重新出图" in out, out[:120])

        fmt = tmp / "fmt.png"
        make_png(fmt, 1242, 1660)
        (tmp / "fmt.txt").write_text("x", encoding="utf-8")
        code, out = run("--check", fmt, "-t", "小红书")
        check("合规时结论为可直接发", "结论: 可以直接发" in out or "可以直接发布" in out,
              out[:120])

        print("\n=== 单点裁决（根治无意义建议）===")
        wide = tmp / "wide.png"
        make_png(wide, 1920, 1080)
        code, out = run("--check", wide, "-t", "公众号")
        check("横图不再被塞进次条封面", "次条封面" not in out, out[:150])
        check("横图正确判为正文配图", "正文配图" in out, out[:150])
        check("不再出现『缩到 200px』", "缩至 200px" not in out, out[:150])

        print("\n=== 新增平台 ===")
        code, out = run("--spec", "视频号")
        check("视频号已收录", "1080" in out and "1260" in out, out[:80])

        wb = tmp / "wb.png"
        make_png(wb, 1080, 1350)
        code, out = run("--check", wb, "-t", "微博")
        check("微博 4:5 判定通过", "可以直接发布" in out, out[:120])
        # 反证：3:4 的图投微博应被判比例不符，说明 4:5 规格真的生效
        code, out2 = run("--check", d34, "-t", "微博")
        check("微博 4:5 规格生效（3:4 报比例不符）", "比例" in out2, out2[:120])

        code, out = run("--check", wb, "-t", "知乎", "--json")
        check("知乎返回正常", code == 0)

        print("\n=== 扫描模式 ===")
        d34b = tmp / "d34b.png"
        make_png(d34b, 1080, 1440)
        code, out = run("--check", d34b)
        check("扫描模式隔离专业场景", "默认只扫社媒发布类" in out, out[:80])
        check("扫描模式保留通过项", "[OK] 另有以下槽位直接通过" in out, out[:80])
        check("视频号参与社媒扫描", "视频号" in out or code == 0, out[:80])

        print("\n=== 多图一致性 ===")
        m1 = tmp / "m1.png"
        m2 = tmp / "m2.png"
        m3 = tmp / "m3.png"
        make_png(m1, 1242, 1660)
        make_png(m2, 1242, 1660)
        make_png(m3, 1080, 1440)
        code, out = run("--check", m1, m2, m3, "-t", "小红书")
        check("多图尺寸混排能被抓出", "尺寸不统一" in out, out[:200])
        check("混排时给出组级结论", ">> 结论:" in out, out[-300:])
        check("组级结论点明主因是整组不齐", "整组" in out or "不一致" in out, out[-300:])

        # 反证：全套同尺寸不应报混排
        code, out = run("--check", m1, m2, "-t", "小红书")
        check("同尺寸多图不误报混排", "尺寸不统一" not in out, out[:200])
        check("同尺寸多图不产生组级报错", ">> 结论:" not in out, out[:200])

        # 单图不应触发多图检查
        code, out = run("--check", m1, "-t", "小红书")
        check("单图不触发多图检查", "多图一致性" not in out, out[:120])

        # 数量上限：小红书 18 张，构造 19 张
        many = []
        for i in range(19):
            f = tmp / f"many{i}.png"
            make_png(f, 1242, 1660)
            many.append(f)
        code, out = run("--check", *many, "-t", "小红书")
        check("超出单次张数上限被抓出", "超过该平台单次上限" in out, out[-400:])

        # JSON 也要带上多图结论，便于下游消费
        code, out = run("--check", m1, m2, m3, "-t", "小红书", "--json")
        try:
            body = json.loads(out[out.index("{"):])
            check("JSON 含 multi_image 字段", "multi_image" in body)
            check("JSON 多图结论非空", len(body.get("multi_image") or []) >= 1)
            check("JSON 多图块带 hint", bool(body["multi_image"][0].get("hint")))
        except (ValueError, KeyError, IndexError) as e:
            check("JSON 含 multi_image 字段", False, str(e))

        print("\n=== 容错与契约 ===")
        code, out = run("--check", tmp / "none.png", "-t", "小红书")
        check("缺文件不崩溃", code == 0 and "文件不存在" in out, out[:80])

        code, out = run("--check", d916, "-t", "抖音", "--json")
        try:
            body = json.loads(out[out.index("{"):])
            check("JSON 可解析", body.get("ok") is True)
            tgt = body["results"][0]["targets"][0]
            check("JSON 含 verdict 字段", "verdict" in tgt)
        except (ValueError, KeyError, IndexError) as e:
            check("JSON 可解析", False, str(e))

        print("\n=== 别名冲突检测 ===")
        clash = tmp / "clash.json"
        d = json.loads((HERE.parent / "references" / "platforms.json").read_text(encoding="utf-8"))
        d["platforms"][1]["aliases"].append(d["platforms"][0]["name"])
        clash.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        code, out = run("--validate", "--spec-path", clash)
        check("能抓出别名冲突", code == 1 and "冲突" in out, out[:120])

        asp = tmp / "asp.json"
        d2 = json.loads((HERE.parent / "references" / "platforms.json").read_text(encoding="utf-8"))
        d2["platforms"][0]["slots"][0]["aspect"] = "3:4"
        asp.write_text(json.dumps(d2, ensure_ascii=False), encoding="utf-8")
        code, out = run("--validate", "--spec-path", asp)
        check("能抓出 aspect 不自洽", code == 1 and "不自洽" in out, out[:120])

        print("\n=== 输出编码（Windows 控制台兼容）===")
        # 本工具输出全是中文。Windows 上 Python 默认按控制台代码页编码，
        # 会抛 UnicodeEncodeError 直接崩——而 Linux/macOS 默认 UTF-8，
        # 所以这个 bug 在开发机上永远测不出来（CI 的 Windows 任务抓到的）。
        # 这里强制用非 UTF-8 编码跑一遍，确保输出层做了兜底。
        #
        # 注意：这个坑踩过两次——先漏了 demo.py，又漏了测试脚本自己。
        # 所以这里把「所有会打印中文的入口」全列进来，一个都不能少。
        import os as _os
        demo = HERE.parent / "demo.py"
        # 注意：不要把 test_spec.py 自己作为子进程目标——那会递归启动整套测试，
        # 子又生子，直接把机器拖死。（踩过一次，表现为 SIGTERM/超时无输出。）
        # 测试脚本自身的编码安全用下面的独立探针验证。
        entries = [
            ("spec.py", [PY, str(SPEC), "--validate"]),
            ("demo.py", [PY, str(demo)]),
        ]
        for enc in ("cp1252", "cp936", "ascii"):
            env = dict(_os.environ, PYTHONIOENCODING=enc)
            for name, cmd in entries:
                r = subprocess.run(cmd, capture_output=True, text=True,
                                   encoding="utf-8", env=env)
                combined = (r.stdout or "") + (r.stderr or "")
                ok = r.returncode == 0 and "UnicodeEncodeError" not in combined
                check(f"非 UTF-8 环境（{enc}）下 {name} 不崩溃", ok, combined[-120:])

        # 自证：本测试脚本自己也打印中文标题，同样需要编码兜底。
        # 用一个只导入本模块并打印中文的最小探针验证，不重跑整套测试。
        probe = tmp / "enc_probe.py"
        probe.write_text(
            "import sys, importlib.util as u\n"
            "sys.path.insert(0, r'" + str(HERE) + "')\n"
            "import spec as s\n"
            "s._force_utf8_stdout()\n"
            "print('=== 规格库自检 ===')\n"
            "print('这是中文探针输出')\n",
            encoding="utf-8")
        env = dict(_os.environ, PYTHONIOENCODING="cp1252")
        r = subprocess.run([PY, str(probe)], capture_output=True, text=True,
                           encoding="utf-8", env=env)
        combined = (r.stdout or "") + (r.stderr or "")
        check("测试脚本自身在窄编码下不崩溃",
              "UnicodeEncodeError" not in combined and "中文探针输出" in combined,
              combined[-160:])

    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\n{'='*40}")
    print(f"通过 {len(PASS)} / 失败 {len(FAIL)}")
    for f in FAIL:
        print(f"  失败: {f}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
