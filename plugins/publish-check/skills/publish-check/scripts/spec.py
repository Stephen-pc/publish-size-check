#!/usr/bin/env python3
"""
publish-check —— 发布前体检

纯标准库实现：不依赖 Pillow / numpy，开箱即跑。
原件只读：本脚本永不修改、移动、删除任何输入文件。

用法:
  spec.py --list                         列出规格库全部平台
  spec.py --spec 小红书                   查某平台的发布规格
  spec.py --check a.png b.jpg            体检文件（自动推断平台）
  spec.py --check a.png --target 小红书    按指定平台体检
  spec.py --check a.png --json           输出 JSON 供程序消费
"""

import argparse
import json
import os
import struct
import sys
from pathlib import Path


def _force_utf8_stdout():
    """强制标准输出用 UTF-8。

    本工具的输出全是中文。Windows 上 Python 默认按控制台代码页（常见 cp1252 /
    cp936）编码，一输出中文就抛 UnicodeEncodeError 直接崩掉——而 Windows 恰恰
    是重要受众。Linux / macOS 默认就是 UTF-8，所以这个坑在开发机上根本看不到。

    设计要点（都是踩过坑才加的）：
    - 幂等：已经是 UTF-8 就直接返回，避免重复包装流。多个入口（spec.py /
      demo.py / test_spec.py）会各自调用一次，重复 reconfigure 会出问题。
    - 不碰 buffer 重建：只在 reconfigure 不可用时才退化处理，且不重新包装
      已有的 TextIOWrapper——那会让旧缓冲丢失甚至阻塞。
    - 失败不抛异常：输出编码不该成为程序跑不起来的原因。
    """
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream is None:
            continue
        # 幂等保护：已经是 UTF-8 就不用管了。
        enc = (getattr(stream, "encoding", None) or "").lower().replace("-", "")
        if enc in ("utf8", "utf8mb4"):
            continue
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
                continue
            except (AttributeError, ValueError, OSError):
                pass
        # 退化路径：Python 3.6 及更早没有 reconfigure。此时才重建包装，
        # 并确保先冲刷旧缓冲，否则可能丢输出。
        try:
            import io
            buf = getattr(stream, "buffer", None)
            if buf is not None:
                try:
                    stream.flush()
                except (ValueError, OSError):
                    pass
                setattr(sys, stream_name,
                        io.TextIOWrapper(buf, encoding="utf-8",
                                         errors="replace", line_buffering=True))
        except (AttributeError, ValueError, OSError):
            pass


# 只在被直接执行或首次导入时调一次；函数本身幂等，重复调用无害。
_force_utf8_stdout()


def _find_spec_path():
    """定位 platforms.json，兼容三种使用方式。

    1. 仓库源码运行（scripts/spec.py → ../references/platforms.json）
    2. pip 安装后调用（规格库随包安装在同一目录旁的 references/）
    3. 环境变量 PUBLISH_SIZE_CHECK_SPEC 显式指定

    之所以要容错，是因为「零依赖、随处可跑」是本项目的核心承诺：
    路径写死会让 pip 安装的版本直接崩掉。
    """
    env = os.environ.get("PUBLISH_SIZE_CHECK_SPEC")
    if env:
        return Path(env)

    here = Path(__file__).resolve().parent
    candidates = [
        here.parent / "references" / "platforms.json",   # 源码仓库
        here / "references" / "platforms.json",          # 打包安装
        here / "platforms.json",                         # 扁平安装
        here.parent / "share" / "publish-size-check" / "platforms.json",
        Path.cwd() / "references" / "platforms.json",     # 在仓库根目录下运行
    ]
    for c in candidates:
        if c.is_file():
            return c
    return candidates[0]


SPEC_PATH = _find_spec_path()


# ---------- 规格库 ----------

def load_spec(path=SPEC_PATH):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        die(f"规格库缺失：{path}")
    except json.JSONDecodeError as e:
        die(f"规格库 JSON 解析失败：{e}")


def resolve_platform(spec, query):
    """按 id / 名称 / 别名解析平台，命中返回 (platform, 命中方式)。"""
    if not query:
        return None, None
    q = query.strip().lower()
    for p in spec["platforms"]:
        if p["id"].lower() == q:
            return p, "id"
    for p in spec["platforms"]:
        names = [p["name"]] + p.get("aliases", [])
        for n in names:
            if n.lower() == q:
                return p, "exact"
    for p in spec["platforms"]:
        names = [p["name"]] + p.get("aliases", [])
        for n in names:
            if q in n.lower() or n.lower() in q:
                return p, "fuzzy"
    return None, None


# ---------- 图片头部解析（纯标准库） ----------

def read_image_meta(path):
    """读取位图尺寸与 dpi。返回 dict 或 None（非支持的位图）。"""
    try:
        with open(path, "rb") as f:
            head = f.read(32)
            if head[:8] == b"\x89PNG\r\n\x1a\n":
                return _png_meta(path)
            if head[:2] == b"\xff\xd8":
                return _jpeg_meta(path)
            if head[:6] in (b"GIF87a", b"GIF89a"):
                return _gif_meta(path)
            if head[:2] in (b"II", b"MM"):
                return _tiff_meta(path)
    except OSError as e:
        return {"error": str(e), "format": "unreadable"}
    return None


def _png_meta(path):
    with open(path, "rb") as f:
        f.read(8)
        w = h = None
        dpi = None
        bd = ct = None
        while True:
            raw = f.read(8)
            if len(raw) < 8:
                break
            (length,) = struct.unpack(">I", raw[:4])
            ctype = raw[4:8]
            # 统一读满数据区再跳过 4 字节 CRC，保证下一块偏移正确
            data = f.read(length)
            f.seek(4, 1)
            if ctype == b"IHDR":
                w, h, bd, ct = struct.unpack(">IIBB", data[:10])
            elif ctype == b"pHYs":
                px, py, unit = struct.unpack(">IIB", data[:9])
                if unit == 1:
                    dpi = round(px * 0.0254)
            elif ctype == b"IDAT":
                break
        has_alpha = ct == 6 or (ct == 3)
        return {"format": "png", "w": w, "h": h, "dpi": dpi,
                "bit_depth": bd, "has_alpha": has_alpha,
                "lossless": True, "vector": False}


def _jpeg_meta(path):
    with open(path, "rb") as f:
        f.read(2)
        w = h = dpi = None
        while True:
            b = f.read(1)
            if not b:
                break
            if b != b"\xff":
                continue
            marker = f.read(1)
            while marker == b"\xff":
                marker = f.read(1)
            if marker in (b"\xd8", b"\xd9") or not marker:
                continue
            try:
                (seglen,) = struct.unpack(">H", f.read(2))
            except struct.error:
                break
            if marker in (b"\xc0", b"\xc1", b"\xc2", b"\xc3",
                          b"\xc5", b"\xc6", b"\xc7",
                          b"\xc9", b"\xca", b"\xcb",
                          b"\xcd", b"\xce", b"\xcf"):
                data = f.read(5)
                _, h, w = struct.unpack(">BHH", data)
                f.seek(seglen - 7, 1)
            elif marker == b"\xe0":
                data = f.read(seglen - 2)
                if data[:5] == b"JFIF\x00":
                    try:
                        unit = data[7]
                        xd = struct.unpack(">H", data[8:10])[0]
                        if unit == 1:
                            dpi = xd
                        elif unit == 2:
                            dpi = round(xd * 2.54, 1)
                    except (struct.error, IndexError):
                        pass
            else:
                f.seek(seglen - 2, 1)
            if w:
                break
        return {"format": "jpeg", "w": w, "h": h, "dpi": dpi,
                "has_alpha": False, "lossless": False, "vector": False}


def _gif_meta(path):
    with open(path, "rb") as f:
        f.read(6)
        w, h = struct.unpack("<HH", f.read(4))
        return {"format": "gif", "w": w, "h": h, "dpi": None,
                "has_alpha": True, "lossless": False, "vector": False}


def _tiff_meta(path):
    return {"format": "tiff", "w": None, "h": None, "dpi": None,
            "has_alpha": None, "lossless": True, "vector": False,
            "note": "TIFF 尺寸解析未实现，请用其他工具确认 dpi"}


VECTOR_EXT = {".pdf", ".svg", ".eps", ".ai", ".cdr"}
EDITABLE_EXT = {".psd", ".ai", ".svg", ".pptx", ".xlsx", ".docx", ".fig", ".sketch"}


def examine_file(path):
    """产出单文件的事实卡片。"""
    p = Path(path)
    ext = p.suffix.lower()
    info = {
        "path": str(p.resolve()),
        "name": p.name,
        "ext": ext.lstrip("."),
        "bytes": p.stat().st_size if p.exists() else 0,
        "exists": p.exists(),
        "vector": ext in VECTOR_EXT,
        "editable_source": ext in EDITABLE_EXT,
    }
    if not info["exists"]:
        info["error"] = "文件不存在"
        return info
    info["mb"] = round(info["bytes"] / 1048576, 2)
    meta = read_image_meta(path)
    if meta:
        info.update({k: v for k, v in meta.items() if k != "error"})
    elif ext in VECTOR_EXT:
        info["lossless"] = True
    elif ext in EDITABLE_EXT:
        info["vector"] = ext in {".svg", ".ai", ".eps", ".cdr"}
        info["lossless"] = True
    else:
        info["format"] = ext.lstrip(".") or "unknown"
    return info


# ---------- 体检规则 ----------

def check_against(info, slot, platform):
    """把文件事实对到某槽位规格，返回问题列表。"""
    issues = []
    c = slot.get("canvas") or {}

    # 1. 格式
    accepted = slot.get("accepted_formats") or []
    if accepted and info["ext"] and info["ext"] not in accepted \
            and not (info["ext"] == "jpeg" and "jpg" in accepted):
        if info["ext"] not in ("jpeg",) or "jpg" not in accepted:
            issues.append({
                "level": "error", "code": "FORMAT",
                "msg": f"格式 .{info['ext']} 不在接受列表 {'/'.join(accepted)} 内",
                "fix": f"另存为 {accepted[0]} 格式后重新提交",
            })

    # 2. 体积
    mb = slot.get("max_bytes")
    if mb and info["bytes"] > mb:
        issues.append({
            "level": "error", "code": "SIZE",
            "msg": f"体积 {info['mb']}MB 超出上限 {round(mb/1048576,2)}MB",
            "fix": "压缩或降采样；平台超限会自动压缩，细密文字会糊",
        })
    elif mb and info["bytes"] > mb * 0.85:
        issues.append({
            "level": "warn", "code": "SIZE_NEAR",
            "msg": f"体积 {info['mb']}MB 接近上限 {round(mb/1048576,2)}MB，余量不足",
            "fix": "建议留出余量，避免平台侧二次压缩",
        })

    # 3. 画布尺寸（支持 gte 语义与 alt 备选规格）
    tw, th = c.get("w"), c.get("h")
    iw, ih = info.get("w"), info.get("h")
    is_gte = c.get("tolerance") == "gte"
    alts = c.get("alt") or []

    if iw and tw:
        if iw < tw:
            issues.append({
                "level": "error", "code": "CANVAS_SMALL",
                "msg": f"宽度 {iw}px 小于要求 {tw}px" + ("（要求为不小于）" if is_gte else ""),
                "fix": f"重新导出为 ≥{tw}px 宽（放大现有图片无法恢复清晰度）",
            })
        elif iw > tw:
            if is_gte:
                # 要求是「不小于」，超一点是允许的；只有明显超出才提示
                biggest = max([a["w"] for a in alts], default=tw)
                if iw > biggest * 2:
                    issues.append({
                        "level": "warn", "code": "CANVAS_OVERSIZE",
                        "msg": f"宽度 {iw}px 远超建议的 {tw}px，可能触发平台二次压缩",
                        "fix": f"控制在 {tw}~{biggest}px 之间更稳妥",
                    })
            else:
                alt_hit = next((a for a in alts if a["w"] == iw), None)
                if alt_hit:
                    issues.append({
                        "level": "info", "code": "CANVAS_ALT",
                        "msg": f"宽度 {iw}px 属于该平台同样被广泛使用的取值之一",
                        "fix": "无需处理",
                    })
                else:
                    issues.append({
                        "level": "warn", "code": "CANVAS_WIDE",
                        "msg": f"宽度 {iw}px 大于建议的 {tw}px，平台会下采样",
                        "fix": f"缩至 {tw}px 可减小体积且画质无损",
                    })

    # 比例判定：有 alt 时命中任一即通过
    if iw and ih:
        ir = iw / ih
        candidates = []
        if tw and th:
            candidates.append((tw, th))
        candidates += [(a["w"], a["h"]) for a in alts if a.get("h")]
        if candidates:
            best = min(candidates, key=lambda p: abs(ir - p[0] / p[1]) / (p[0] / p[1]))
            tr = best[0] / best[1]
            if abs(ir - tr) / tr > 0.02:
                issues.append({
                    "level": "error", "code": "ASPECT",
                    "msg": f"比例 {ir:.2f}:1 与要求 {tr:.2f}:1 不符，发布后会被裁切或留白",
                    "fix": f"按 {slot.get('aspect')} 重新构图，核心信息放在安全区内",
                })

    # 4. dpi（印刷/投稿）
    min_dpi = slot.get("min_dpi")
    if min_dpi:
        d = info.get("dpi")
        if info.get("vector"):
            pass
        elif d is None:
            issues.append({
                "level": "warn", "code": "DPI_UNKNOWN",
                "msg": f"无法读取 dpi，要求 ≥{min_dpi}",
                "fix": "用图像工具确认实际 dpi 后再提交",
            })
        elif d < min_dpi:
            need = min_dpi / d if d else 0
            issues.append({
                "level": "error", "code": "DPI_LOW",
                "msg": f"dpi={d} 低于要求 {min_dpi}",
                "fix": f"位图无法靠放大提升 dpi。需按 {need:.1f} 倍比例重新导出原图，"
                       f"或改用矢量输出（{ '/'.join(slot.get('accepted_formats', [])) }）",
            })

    # 4b. 物理尺寸（印刷/投稿的真正判据）
    # dpi 达标不等于可用：800×600 @300dpi 只印 68mm 宽，不够单栏 88mm。
    # 必须用「像素 ÷ dpi」算实际印刷宽度，否则会放行实际不合格的文件。
    pwm = slot.get("physical_width_mm")
    if pwm and not info.get("vector"):
        d = info.get("dpi")
        iw = info.get("w")
        if d and iw:
            mm = iw / d * 25.4
            need_mm = pwm.get("min")
            if need_mm and mm < need_mm:
                need_px = int(need_mm / 25.4 * d)
                issues.append({
                    "level": "error", "code": "PHYSICAL_TOO_SMALL",
                    "msg": (f"在 {d}dpi 下实际只印 {mm:.0f}mm 宽，"
                            f"低于最小栏宽 {need_mm}mm"),
                    "fix": (f"这不是改 dpi 数字能解决的——需要至少 {need_px}px 宽的图，"
                            f"须从源文件按更高分辨率重新导出。"
                            f"改 dpi 元数据不会增加实际像素。"),
                })
            else:
                common = pwm.get("common") or []
                near = min(common, key=lambda c: abs(c - mm)) if common else None
                issues.append({
                    "level": "info", "code": "PHYSICAL_WIDTH",
                    "msg": (f"在 {d}dpi 下实际印刷宽度 {mm:.0f}mm"
                            + (f"，最接近的常用栏宽是 {near}mm" if near else "")),
                    "fix": "排版时按实际印刷宽度对齐栏宽，避免缩放导致字号失真",
                })

    # 5. 矢量偏好
    vr = slot.get("vector_required_for") or []
    if vr and not info.get("vector"):
        issues.append({
            "level": "warn", "code": "VECTOR_PREFERRED",
            "msg": f"此类内容（{'/'.join(vr)}）建议矢量输出，当前是位图",
            "fix": "从源文件重新导出 PDF/SVG；位图放大审查时会被要求重做",
        })

    # 6. 可编辑性
    if slot["slot"] == "editable_asset" and not info.get("editable_source"):
        issues.append({
            "level": "error", "code": "NOT_EDITABLE",
            "msg": "不是可编辑源文件，甲方最常见的退回理由",
            "fix": "交付 psd/ai/svg/pptx 等源文件，并附字体清单",
        })

    # 7. 透明通道
    if info.get("has_alpha") and info["format"] == "png" and "png" in (accepted or []):
        issues.append({
            "level": "info", "code": "ALPHA",
            "msg": "含透明通道，部分平台转 JPG 时透明区会变黑或变白",
            "fix": "如遇发黑，先垫底色再导出",
        })

    return issues


def pick_slots(platform, info):
    """挑出该文件最适合的槽位（单点裁决 + 次级候选）。

    设计原则：**永远只把最匹配的槽位当作主结论**。
    早期版本形状不匹配时会把全部槽位并列报出，结果一张 1920×1080 的横图
    会收到「缩到 200px」这种建议——那张图根本不该投次条封面，
    这种结论比没有结论更糟。改为：主结论唯一，其余降为一行提点。
    """
    slots = platform["slots"]
    if len(slots) == 1:
        return slots, []

    iw, ih = info.get("w"), info.get("h")
    if not (iw and ih):
        return slots, []

    file_ratio = iw / ih
    scored = []
    for s in slots:
        c = s.get("canvas") or {}
        if not c.get("w") or not c.get("h"):
            # 形状不限的槽位（正文图/内页）总是兼容，给一个中性偏差值
            scored.append((0.20, s))
            continue
        ratios = [c["w"] / c["h"]]
        for a in c.get("alt") or []:
            if a.get("h"):
                ratios.append(a["w"] / a["h"])
        diff = min(abs(file_ratio - r) / r for r in ratios)
        scored.append((diff, s))

    scored.sort(key=lambda x: x[0])
    primary = scored[0][1]
    # 偏差 ≤5% 视为形状真正匹配，算作确定的次级候选
    others = [s for d, s in scored[1:] if d <= 0.05]
    return [primary], others


# ---------- 输出 ----------

def die(msg, code=2):
    print(json.dumps({"ok": False, "error": msg}, ensure_ascii=False), file=sys.stderr)
    sys.exit(code)


ICON = {"error": "[X]", "warn": "[!]", "info": "[i]"}


def cmd_list(spec):
    print(f"规格库 v{spec['schema_version']}  核验于 {spec['verified_at']}  "
          f"(超过 {spec['stale_after_days']} 天需复核)\n")
    CONF_LABEL = {"verified": "已交叉印证", "community": "社区共识",
                  "experience": "经验值"}
    for p in spec["platforms"]:
        slots = "、".join(s["label"] for s in p["slots"])
        conf = CONF_LABEL.get(p.get("confidence"), p.get("confidence", "?"))
        print(f"  {p['name']:<8} [{p['id']}]  可信度:{conf}")
        print(f"      别名: {'、'.join(p.get('aliases', [])) or '—'}")
        print(f"      槽位: {slots}")
        if p.get("ambiguity_note"):
            print(f"      [!] {p['ambiguity_note']}")
    print(f"\n  通用兜底: {spec['universal_fallback']['label']}")


def cmd_validate(spec_path=SPEC_PATH):
    """规格库自检：让改数据的人改错立刻知道。"""
    errors, warns, infos = [], [], []

    if not spec_path.exists():
        print(f"[X] 规格库文件不存在：{spec_path}")
        return 1
    try:
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"[X] JSON 语法错误，第 {e.lineno} 行第 {e.colno} 列：{e.msg}")
        return 1

    # 顶层字段
    for k in ("schema_version", "verified_at", "stale_after_days",
              "platforms", "universal_fallback"):
        if k not in spec:
            errors.append(f"缺少顶层字段：{k}")

    # 时效
    try:
        from datetime import date, datetime
        vd = datetime.strptime(spec["verified_at"], "%Y-%m-%d").date()
        age = (date.today() - vd).days
        if age > spec.get("stale_after_days", 180):
            warns.append(f"规格库已 {age} 天未复核，超过 {spec['stale_after_days']} 天阈值，建议重新核实")
        else:
            infos.append(f"规格库核验于 {spec['verified_at']}，{age} 天前，在有效期内")
    except (KeyError, ValueError) as e:
        errors.append(f"verified_at 格式应為 YYYY-MM-DD：{e}")

    seen_ids, seen_alias = {}, {}
    CONF_OK = {"verified", "community", "experience"}

    for pi, p in enumerate(spec.get("platforms", [])):
        tag = p.get("id") or f"#{pi}"
        for k in ("id", "name", "slots", "confidence"):
            if k not in p:
                errors.append(f"[{tag}] 缺少字段：{k}")
        if p.get("confidence") not in CONF_OK:
            errors.append(f"[{tag}] confidence 取值非法：{p.get('confidence')}，"
                          f"应为 {'/'.join(sorted(CONF_OK))}")

        # id 与别名唯一性
        if p.get("id") in seen_ids:
            errors.append(f"[{tag}] id 与平台 {seen_ids[p['id']]} 重复")
        seen_ids[p.get("id")] = tag
        for a in [p.get("name")] + p.get("aliases", []):
            if not a:
                continue
            low = a.lower()
            if low in seen_alias and seen_alias[low] != tag:
                errors.append(f"[{tag}] 名称/别名『{a}』与 {seen_alias[low]} 冲突，会导致解析歧义")
            seen_alias[low] = tag

        if not p.get("slots"):
            errors.append(f"[{tag}] 没有任何槽位")

        seen_slot = set()
        for s in p.get("slots", []):
            st = f"{tag}/{s.get('slot', '?')}"
            if s.get("slot") in seen_slot:
                errors.append(f"[{st}] 槽位名在平台内重复")
            seen_slot.add(s.get("slot"))
            for k in ("slot", "label", "canvas", "accepted_formats"):
                if k not in s:
                    errors.append(f"[{st}] 缺少字段：{k}")

            c = s.get("canvas") or {}
            if not isinstance(c, dict):
                errors.append(f"[{st}] canvas 必须是对象")
            elif c.get("w") is None and c.get("h") is None and not c.get("rule"):
                errors.append(f"[{st}] canvas 既无 w/h 也无 rule，无法判定")
            if c.get("tolerance") not in (None, "gte"):
                errors.append(f"[{st}] canvas.tolerance 仅支持 'gte'")
            for ai, a in enumerate(c.get("alt") or []):
                if not isinstance(a, dict) or "w" not in a:
                    errors.append(f"[{st}] canvas.alt[{ai}] 缺 w")
                elif a.get("w") == c.get("w") and a.get("h") == c.get("h"):
                    warns.append(f"[{st}] canvas.alt[{ai}] 与主规格完全相同，冗余")

            # 比例自洽性
            asp = s.get("aspect")
            if asp and asp not in ("free",) and c.get("w") and c.get("h"):
                try:
                    aw, ah = (float(x) for x in asp.split(":"))
                    declared = aw / ah
                    actual = c["w"] / c["h"]
                    if abs(declared - actual) / actual > 0.03:
                        errors.append(
                            f"[{st}] aspect={asp} 与 canvas {c['w']}×{c['h']} "
                            f"（实际 {actual:.2f}:1）不自洽")
                except ValueError:
                    errors.append(f"[{st}] aspect 格式应为 'a:b'，当前 {asp!r}")

            if not s.get("source"):
                warns.append(f"[{st}] 缺 source 来源标注，数值不可追溯")
            if p.get("confidence") == "verified" and "source" not in s:
                errors.append(f"[{st}] 标为已交叉印证但无 source，违反 evidence_policy")
            if not s.get("notes"):
                warns.append(f"[{st}] 缺 notes，用户看不到使用要点")

            sa = s.get("safe_area_pct")
            if sa:
                for k in ("top", "bottom", "left", "right"):
                    if k not in sa:
                        errors.append(f"[{st}] safe_area_pct 缺 {k}")
                if sa.get("top", 0) + sa.get("bottom", 0) >= 100:
                    errors.append(f"[{st}] safe_area_pct 上下和 ≥100%，安全区为空")

            mb = s.get("max_bytes")
            if mb is not None and (not isinstance(mb, int) or mb <= 0):
                errors.append(f"[{st}] max_bytes 应为正整数（字节），当前 {mb!r}")

    # 兜底规格
    uf = spec.get("universal_fallback", {})
    for k in ("canvas", "aspect", "max_bytes", "accepted_formats"):
        if k not in uf:
            errors.append(f"[universal_fallback] 缺少字段：{k}")

    # 输出
    w = sum(len(p.get("slots", [])) for p in spec.get("platforms", []))
    print(f"规格库自检：{SPEC_PATH.name}  v{spec.get('schema_version')}")
    print(f"  {len(spec.get('platforms', []))} 个平台 / {w} 个槽位 / {len(seen_alias)} 个可解析名称\n")
    for i in infos:
        print(f"  [i] {i}")
    for x in warns:
        print(f"  [!] {x}")
    for e in errors:
        print(f"  [X] {e}")
    print()
    if errors:
        print(f"结果：不通过（{len(errors)} 个错误，{len(warns)} 个警告）")
        return 1
    if warns:
        print(f"结果：通过，但有 {len(warns)} 个警告")
        return 0
    print("结果：全部通过")
    return 0


def cmd_spec(spec, query):
    p, how = resolve_platform(spec, query)
    if not p:
        print(f"规格库中未找到「{query}」，以下为通用安全规格：\n")
        p = {"name": spec["universal_fallback"]["label"], "id": "fallback",
             "slots": [dict(spec["universal_fallback"], slot="generic", label="通用"),
                       ], "confidence": "low"}
        how = "fallback"
    tag = {"id": "", "exact": "", "fuzzy": "（模糊匹配，请确认）", "fallback": "（兜底）"}
    print(f"# {p['name']}  可信度:{p.get('confidence','?')} {tag.get(how,'')}\n")
    for s in p["slots"]:
        c = s.get("canvas") or {}
        dim = f"{c.get('w')}×{c.get('h')}" if c.get("h") else f"宽 {c.get('w')}px 高不限"
        if not c.get("w") and c.get("rule"):
            dim = f"按规则：{c['rule']}"
        print(f"  【{s.get('label')}】{dim}  比例 {s.get('aspect')}")
        if s.get("max_bytes"):
            print(f"      体积上限: {round(s['max_bytes']/1048576,1)}MB")
        print(f"      接受格式: {'/'.join(s.get('accepted_formats', [])) or '—'}")
        if s.get("min_dpi"):
            print(f"      dpi 要求: ≥{s['min_dpi']}"
                  + (f"（首选 {s['preferred_dpi']}）" if s.get("preferred_dpi") else ""))
        if s.get("safe_area_pct"):
            sa = s["safe_area_pct"]
            print(f"      安全区: 上{sa['top']}% 下{sa['bottom']}% 左{sa['left']}% 右{sa['right']}%")
        if s.get("notes"):
            print(f"      要点: {s['notes']}")
        print()
    if p.get("reject_reasons"):
        print("  常见退回原因：")
        for r in p["reject_reasons"]:
            print(f"    - {r}")


def relevant(info, slot):
    """形状相关性预筛：判断这个槽位是否值得对当前文件报结论。

    白名单策略：只有比例接近、或槽位本身形状不限时才参与。
    目的是让全平台扫描聚焦，而不是把印刷/甲方交付等语义无关的槽位也报一遍。
    """
    c = slot.get("canvas") or {}
    # 形状不限的槽位（正文图、内页、按规则）一律相关
    if not c.get("w") or not c.get("h"):
        return True
    iw, ih = info.get("w"), info.get("h")
    if not (iw and ih):
        return False
    fr = iw / ih
    ratios = [c["w"] / c["h"]]
    for a in c.get("alt") or []:
        if a.get("h"):
            ratios.append(a["w"] / a["h"])
    best = min(abs(fr - r) / r for r in ratios)
    return best <= 0.15


def check_multi_image(platform, infos):
    """多图连发的一致性检查。

    真实发布经常一次发多张（小红书最多 18 图、微博九宫格）。
    尺寸混排会让页面跳动或留白，这是单图检查覆盖不到的缺口。
    """
    mi = platform.get("multi_image")
    if not mi or len(infos) < 2:
        return []

    issues = []
    n = len(infos)
    if mi.get("max_count") and n > mi["max_count"]:
        issues.append({
            "level": "error", "code": "MULTI_COUNT",
            "msg": f"共 {n} 张，超过该平台单次上限 {mi['max_count']} 张",
            "fix": f"拆成多次发布，或删减到 {mi['max_count']} 张以内",
        })

    dims = {}
    for i in infos:
        if i.get("w") and i.get("h"):
            dims.setdefault((i["w"], i["h"]), []).append(i["name"])

    if len(dims) > 1:
        detail = "、".join(f"{w}×{h}({len(v)}张)" for (w, h), v in
                          sorted(dims.items(), key=lambda x: -len(x[1])))
        if mi.get("require_uniform"):
            note = f" 该平台要求：{mi['notes']}" if mi.get("notes") else ""
            issues.append({
                "level": "error", "code": "MULTI_UNIFORM",
                "msg": f"尺寸不统一：{detail}",
                "fix": ("全套按同一尺寸重新导出。混排会导致页面跳动或九宫格留白。"
                        + note),
            })
        else:
            issues.append({
                "level": "warn", "code": "MULTI_WIDTH",
                "msg": f"尺寸不一致（仅宽度建议统一）：{detail}",
                "fix": "统一宽度可让正文排版对齐；高度不同通常可接受",
            })
    return issues


def multi_verdict_hint(platform_name, mi_issues, solo_failed, outlier_names=None):
    """多图语境下的一句话结论。

    同一个文件同时被单图段和多图段报出来会让用户觉得啰嗦，
    这里把两处合成一句：真正要做的动作只有一个。

    solo_failed 是「单图判定为不能发」的文件列表，每项形如 {"file": ..., "slot": ...}。
    outlier_names 是少数派尺寸的文件名——点它比点「全部」有用得多。
    """
    if not mi_issues:
        return None
    codes = {i["code"] for i in mi_issues}
    if "MULTI_COUNT" in codes:
        return "拆成多次发布这一组发不下"
    if "MULTI_UNIFORM" in codes:
        if outlier_names:
            names = "、".join(outlier_names[:3])
            more = f" 等 {len(outlier_names)} 张" if len(outlier_names) > 3 else ""
            return (f"这一组的主因是{names}{more}的尺寸和其余不一致，"
                    f"不是清晰度不够。统一按同一规格重导一遍即可，不用逐张处理。")
        return "这一组的主要问题是尺寸不统一。统一按同一规格重导一遍即可。"
    if "MULTI_WIDTH" in codes:
        return "宽度建议统一，否则正文排版会参差；高度不同通常可接受。"
    return None


def remedy(issues):
    """给出最关键的一句行动建议：这张图能不能救、要做什么。

    用户真正要的不是问题清单，而是「我现在该干什么」。
    """
    if not issues:
        return None
    codes = {i["code"] for i in issues}
    errs = [i for i in issues if i["level"] == "error"]
    if not errs:
        return "可以直接发，建议项可忽略"

    # 致命：尺寸/像素不足 —— 不可通过后处理补救
    if {"CANVAS_SMALL", "PHYSICAL_TOO_SMALL"} & codes:
        if "ASPECT" in codes:
            return "救不了：尺寸和比例都不对，只能按目标规格重新出图"
        return "救不了：像素不足，必须从源文件按更大尺寸重新导出（放大无效）"
    if "DPI_LOW" in codes:
        return "救不了：需要更多像素或改用矢量，改 dpi 数字无用"
    if "NOT_EDITABLE" in codes:
        return "需换交付物：要给可编辑源文件，不能只给扁平图片"
    if "FORMAT" in codes:
        return "能救：转换格式即可，画质不受影响"
    if "SIZE" in codes:
        return "能救：压缩体积即可"
    return "需处理，具体见上"


def format_fact(info):
    fs = []
    if info.get("w"):
        fs.append(f"{info['w']}×{info['h']}px")
    else:
        fs.append(f".{info.get('ext','?')}")
    if info.get("mb") is not None:
        fs.append(f"{info['mb']}MB")
    if info.get("dpi"):
        fs.append(f"{info['dpi']}dpi")
    if info.get("vector"):
        fs.append("矢量")
    elif info.get("lossless"):
        fs.append("无损")
    return " · ".join(fs)


def verdict(issues):
    """给出总判定：能否直接发布。"""
    if any(i["level"] == "error" for i in issues):
        return "no", "不能发布"
    if any(i["level"] == "warn" for i in issues):
        return "risky", "可以发，但有风险"
    return "yes", "可以直接发布"


LEVEL_ORDER = {"error": 0, "warn": 1, "info": 2}
VERDICT_TAG = {
    "yes": "[OK]",
    "risky": "[!] ",
    "no": "[X] ",
}


def cmd_check(spec, files, target, as_json):
    platform, how = (None, None)
    if target:
        platform, how = resolve_platform(spec, target)
        if not platform:
            print(f"[i] 规格库未收录「{target}」，改用通用安全规格体检。")
            print(f"    （这是兜底值，不是该平台的真实要求，请以平台后台为准）\n")
            platform = {"id": "fallback",
                        "name": spec["universal_fallback"]["label"],
                        "slots": [dict(spec["universal_fallback"], slot="generic",
                                       label="通用", source="兜底值")],
                        "confidence": "experience"}
            how = "fallback"
        elif how == "fuzzy":
            print(f"[i] 「{target}」按模糊匹配解析为「{platform['name']}」，如不对请用准确名称。\n")
        if platform.get("ambiguity_note") and how != "fallback":
            print(f"[!] 注意：{platform['ambiguity_note']}\n")
    else:
        omitted = [p["name"] for p in spec["platforms"] if p.get("kind") != "social_cn"]
        if omitted:
            print(f"[i] 未指定平台，默认只扫社媒发布类；以下专业场景未参与："
                  f"{'、'.join(omitted)}")
            print(f"    需要时请指定：--target 投稿 / --target 印刷 / --target 甲方\n")

    results = []
    for f in files:
        info = examine_file(f)
        if not info["exists"]:
            print(f"[X] {f} —— 文件不存在\n")
            results.append({"file": f, "exists": False,
                            "issues": [{"level": "error", "code": "MISSING",
                                        "msg": "文件不存在"}]})
            continue

        if target:
            plats = [platform]
        else:
            # 未指定平台时的默认扫描范围：只扫『社媒发布』类。
            # 印刷 CMYK、甲方要 psd 这类结论对「发个社交媒体」的用户是噪音，
            # 只在用户明确指定时才参与。
            plats = [p for p in spec["platforms"] if p.get("kind") == "social_cn"]
        entry = {"file": info["name"], "path": info["path"], "fact": info, "targets": []}
        skipped = []
        for p in plats:
            prim, others = pick_slots(p, info)
            if others:
                entry.setdefault("alt_slots", []).extend(
                    {"platform": p["name"], "slot": s.get("label")} for s in others)
            for slot in prim:
                # 未指定平台时，先做形状相关性预筛：
                # 一张 3:4 竖图不必去听「印刷要 CMYK」这类无关结论，否则报告会被淹没。
                if not target and not relevant(info, slot):
                    skipped.append(f"{p['name']}/{slot.get('label')}")
                    continue
                issues = sorted(check_against(info, slot, p),
                                key=lambda i: LEVEL_ORDER.get(i["level"], 9))
                entry["targets"].append({
                    "platform": p["name"], "platform_id": p["id"],
                    "slot": slot.get("label"), "slot_key": slot.get("slot"),
                    "issues": issues,
                    "verdict": verdict(issues)[0],
                    "choose_hint": slot.get("choose_hint"),
                })
        entry["skipped"] = skipped
        results.append(entry)

        # ---- 呈现 ----
        print(f"### {info['name']}")
        print(f"    {format_fact(info)}")
        if info.get("editable_source"):
            print("    （可编辑源文件）")
        print()

        if skipped:
            print(f"    [i] 已跳过 {len(skipped)} 个形状不相关的槽位"
                  f"（{skipped[0]} 等）。想看全部请用 --target 指定平台。\n")

        multi = len(entry["targets"]) > 1
        hints = [t for t in entry["targets"] if t.get("choose_hint")]
        if hints:
            seen = []
            for h in hints:
                if h["choose_hint"] not in seen:
                    seen.append(h["choose_hint"])
            for h in seen:
                print(f"    [i] {h}")
            print()

        # 次级候选：形状也能用但非首选的槽位，一句话带过
        for a in entry.get("alt_slots", []):
            print(f"    [i] 「{a['slot']}」形状也能用，需要时请明确指出")
        if entry.get("alt_slots"):
            print()
        shown = 0
        # 扫描模式：先报问题的，通过的收成一行摘要
        passed = []
        for t in entry["targets"]:
            crit = [i for i in t["issues"] if i["level"] == "error"]
            if not target and multi and not crit:
                passed.append(t)
                continue
            shown += 1
            vtag = VERDICT_TAG[t["verdict"]]
            vtxt = verdict(t["issues"])[1]
            print(f"    {vtag} {t['platform']} / {t['slot']} —— {vtxt}")
            act = remedy(t["issues"])
            if act:
                print(f"         结论: {act}")
            if not t["issues"]:
                print("         该槽位无问题")
            for i in t["issues"]:
                print(f"         {ICON.get(i['level'],'[?]')} {i['msg']}")
                if i.get("fix"):
                    print(f"             修法: {i['fix']}")
            print()

        if passed:
            names = "、".join(f"{t['platform']}/{t['slot']}" for t in passed)
            print(f"    [OK] 另有以下槽位直接通过，无需处理：{names}\n")

        if not target and multi and shown == 0 and not passed:
            print("    [OK] 全部平台均已通过，可直接发布\n")

    # ---- 多图一致性（跨文件，按平台汇总）----
    ok_infos = [r["fact"] for r in results if r.get("fact", {}).get("exists")]
    multi_blocks = []
    if len(ok_infos) >= 2:
        if target:
            cands = [platform]
        else:
            cands = [p for p in spec["platforms"] if p.get("kind") == "social_cn"]
        for p in cands:
            if not p.get("multi_image"):
                continue
            mi_issues = check_multi_image(p, ok_infos)
            if mi_issues:
                # 少数派尺寸：3 张里 2 张一致、1 张不同，该点出那 1 张而不是全部 3 张
                dims = {}
                for i in ok_infos:
                    if i.get("w") and i.get("h"):
                        dims.setdefault((i["w"], i["h"]), []).append(i["name"])
                outliers = []
                if len(dims) > 1:
                    majority = max(dims.values(), key=len)
                    for v in dims.values():
                        if v is not majority:
                            outliers.extend(v)
                multi_blocks.append({
                    "platform": p["name"], "issues": mi_issues,
                    "outliers": outliers,
                    "hint": multi_verdict_hint(p["name"], mi_issues, None, outliers),
                })

    if multi_blocks and not as_json:
        print("=" * 60)
        print(f"多图一致性检查（共 {len(ok_infos)} 张）")
        print(f"{len(ok_infos)} 张图一起发时，'整组是否整齐'和'单张是否达标'是两件事。\n")
        for b in multi_blocks:
            iss = b["issues"]
            v = verdict(iss)
            print(f"  {VERDICT_TAG[v[0]]} {b['platform']} —— {v[1]}")
            for i in iss:
                print(f"        {ICON.get(i['level'],'[?]')} {i['msg']}")
            if b.get("hint"):
                print(f"        >> 结论: {b['hint']}")
            for i in iss:
                if i.get("fix"):
                    print(f"           修法: {i['fix']}")
            print()

    if as_json:
        print(json.dumps({"ok": True, "results": results,
                          "multi_image": multi_blocks},
                         ensure_ascii=False, indent=2))
    return results



def main():
    ap = argparse.ArgumentParser(description="发布前体检：对照平台规格检查文件")
    ap.add_argument("files", nargs="*", help="待体检文件")
    ap.add_argument("--list", action="store_true", help="列出规格库全部平台")
    ap.add_argument("--spec", metavar="平台", help="查询某平台发布规格")
    ap.add_argument("--check", action="store_true", help="执行体检")
    ap.add_argument("--validate", action="store_true",
                    help="自检规格库（改完 platforms.json 后跑一次）")
    ap.add_argument("--spec-path", metavar="路径", help="指定规格库文件，配合 --validate")
    ap.add_argument("--target", "-t", metavar="平台", help="指定目标平台")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    args = ap.parse_args()

    if args.validate:
        sys.exit(cmd_validate(Path(args.spec_path) if args.spec_path else SPEC_PATH))

    spec = load_spec(Path(args.spec_path) if args.spec_path else SPEC_PATH)

    if args.list:
        cmd_list(spec)
        return
    if args.spec:
        cmd_spec(spec, args.spec)
        return
    if args.check or args.files:
        if not args.files:
            die("需要至少一个待体检文件，例如：spec.py --check a.png")
        cmd_check(spec, args.files, args.target, args.json)
        return
    ap.print_help()


if __name__ == "__main__":
    main()
