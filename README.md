# publish-size-check

[![CI](https://github.com/Stephen-pc/publish-size-check/actions/workflows/ci.yml/badge.svg)](https://github.com/Stephen-pc/publish-size-check/actions/workflows/ci.yml)
[![Python 3.8+](https://img.shields.io/badge/python-3.8%2B-blue.svg)](https://www.python.org/downloads/)
[![Zero dependencies](https://img.shields.io/badge/dependencies-0-brightgreen.svg)](#为什么需要它)
[![License: MIT](https://img.shields.io/badge/license-MIT-yellow.svg)](LICENSE)

> 发布尺寸检查 —— 对照目标平台的几何规格，告诉你这张图**能不能发、是哪一项过不了**。

零依赖（纯标准库，不需要 Pillow）、原件只读、结果确定。

```console
$ python scripts/spec.py --check cover.png --target 小红书

### cover.png
    1024×1024px · 0.6MB · 无损

    [X]  小红书 / 笔记封面（方版） —— 不能发布
         结论: 救不了：像素不足，必须从源文件按更大尺寸重新导出（放大无效）
         [X] 宽度 1024px 小于要求 1080px
             修法: 重新导出为 ≥1080px 宽（放大现有图片无法恢复清晰度）
```

---

## 为什么需要它

**AI 出图的默认尺寸，基本都过不了主流平台。**

实测三种最常见的 AI 出图尺寸投小红书封面：

| 产出尺寸 | 结果 |
|---|---|
| 1024×1024 | ✗ 宽度差 56px |
| 1024×1536 | ✗ 宽度不足 + 比例不对 |
| 1536×1024 | ✗ 比例完全不对 |

这不是边界情况，是**主流工作流的默认产出**。而平台的报错往往只说"图片不符合要求"，不告诉你差多少、差在哪一项。

更隐蔽的一类：**dpi 字段达标，但实际印不出来**。

一张 `800×600 @300dpi` 的图，dpi 元数据完全合格，但按 300dpi 印出来只有 **68mm 宽**，达不到期刊单栏 88mm 的要求。**改 dpi 数字不会增加一个像素**——这类图必须从源文件重新导出。多数工具只比 dpi 数值，会直接放行。

本工具按 `像素数 ÷ dpi × 25.4 = 实际印刷宽度(mm)` 判定，能抓出这一类。

---

## 快速开始

```bash
git clone https://github.com/Stephen-pc/publish-size-check.git
cd publish-size-check

# 一键看效果：跑五种典型场景，自动清理临时文件
python demo.py

# 体检一个文件（指定平台）
python scripts/spec.py --check cover.png --target 小红书

# 先看看某平台到底要什么
python scripts/spec.py --spec 小红书

# 不确定发哪，扫全部社媒平台
python scripts/spec.py --check cover.png

# 多图连发（≥2 个文件会自动追加「整组是否整齐」检查）
python scripts/spec.py --check 1.png 2.png 3.png --target 小红书

# 程序化消费
python scripts/spec.py --check cover.png --target 小红书 --json

# 列出规格库收录的平台
python scripts/spec.py --list
```

需要 Python 3.8+，**不需要安装任何第三方包**。

### 也可以当命令行工具装

```bash
pip install .
publish-size-check --check cover.png --target 小红书
```

装完后规格库会随包一起装好，路径自动定位；也可以用环境变量 `PUBLISH_SIZE_CHECK_SPEC` 指定自己的规格库。

---

## 支持的平台

| 平台 | 槽位 | 可信度 |
|---|---|---|
| 微信公众号 | 头条封面 / 次条封面 / 正文配图 | 已交叉印证 |
| 小红书 | 笔记封面（竖版）/ 笔记封面（方版）/ 笔记内页 | 已交叉印证 |
| 哔哩哔哩 | 视频封面 | 已交叉印证 |
| 知乎 | 回答/想法配图 / 文章封面 | 社区共识 |
| 微博 | 博文配图 / 头条文章头图 | 社区共识 |
| 抖音 | 视频封面（9:16）/ 图文封面（3:4） | 社区共识 |
| 微信视频号 | 视频封面 / 视频画面 | 社区共识 |
| 学术投稿 | 连续色调图 / 线条图 | 社区共识 |
| 印刷交付 | 胶印数码印刷 / 大幅喷绘 | 社区共识 |
| 甲方交付 | 可编辑源文件 | 经验值 |

共 **10 个平台 / 20 个槽位 / 46 个可解析名称**。平台参数支持 id、中文名、别名，模糊匹配也能命中（`红书` → 小红书、`投个稿` → 学术投稿）。

**可信度三级**，写在数据里，不藏：

- `verified` 已交叉印证 —— ≥2 个独立来源，且必须填 `source`（自检强制检查）
- `community` 社区共识 —— 无官方统一口径，存在多种写法
- `experience` 经验值 —— 需复核

---

## 输出长什么样

每条问题分三级（`[X] 错误` / `[!] 警告` / `[i] 提示`），每条带**具体修法**，最后给一句**行动结论**——因为用户真正要的不是问题清单，而是"我现在该干什么"：

```
结论: 救不了：尺寸和比例都不对，只能按目标规格重新出图
结论: 救不了：像素不足，必须从源文件按更大尺寸重新导出（放大无效）
结论: 能救：转换格式即可，画质不受影响
```

### 多图连发：指出改哪一张

一次传多张时（小红书最多 18 图、微博九宫格），**单张全达标但整组不整齐**是最常见的翻车方式。本工具会做一次跨文件的组级检查，并且**点出少数派是哪一张**，而不是甩一句"三张都不一致"：

```
============================================================
多图一致性检查（共 3 张）

  [X]  小红书 —— 不能发布
        [X] 尺寸不统一：1242×1660(2张)、1080×1440(1张)
        >> 结论: 这一组的主因是 cover3.png 的尺寸和其余不一致……
                 统一按同一规格重导一遍即可，不用逐张处理。
```

问题清单不值钱，**指出改哪一张才值钱**。

---

## 作为 Agent Skill 使用

本仓库同时是一个可用的 Agent Skill（适配 WorkBuddy / Claude 等支持 `SKILL.md` 的平台）。

```bash
# 安装到用户级 skills 目录
cp -r . ~/.workbuddy-ai/skills/publish-size-check/
```

装好后有两种触发方式：

**① 直接问** —— 用户给了文件并问到发布尺寸：

> 「这图发小红书会不会糊」「平台要多大尺寸」「dpi 够吗」「投稿插图够不够清晰」「被退回来说分辨率不够」

**② 寄生自检（覆盖面最大的用法）** —— 出图流程结束后自动跑，用户不需要知道这个技能存在：

```
用户: 帮我做一张小红书封面
  ↓
[出图技能] 生成封面文件
  ↓
★ 有文件落盘 + 用户提到了发布平台 → 自动体检
  ↓
"封面已生成：1242×1660。顺带确认过小红书规格，可以直接发。"
```

汇报是**分级**的：通过就一句话带过，有问题才展开细节并**给出替代方案**（"要我按规格重新出一版吗？"）。用户没要求体检时，不会甩一份 30 行诊断打断体验。

`SKILL.md` 里有完整的触发协议、协作边界和扩展指南。

---

## 作为 CodeBuddy / WorkBuddy 插件安装

本仓库同时是一个**插件市场（marketplace）**，可以一条命令装进 CodeBuddy / WorkBuddy：

```bash
# 1. 添加本仓库作为插件市场
/plugin marketplace add Stephen-pc/publish-size-check

# 2. 安装插件
/plugin install publish-check@publish-size-check

# 3. 立即生效，无需重启
/reload-plugins
```

装好后技能即刻可用，触发方式和上面的 Agent Skill 完全一致。

### 与「直接复制 skill」的区别

| | 复制 SKILL.md | 装成插件 |
|---|---|---|
| 升级 | 手动重拷 | `/plugin update publish-check@publish-size-check` |
| 团队分发 | 各自拷贝 | 写进 `.codebuddy/settings.json`，协作者自动获得 |
| 组件命名空间 | 无 | `publish-check:publish-check` |
| 适用场景 | 单人、临时试 | 长期使用、团队统一 |

### 本地开发 / 不联网安装

```bash
/plugin marketplace add ./publish-size-check
/plugin install publish-check@publish-size-check
```

### 仓库结构（双入口）

```
publish-size-check/
├── .codebuddy-plugin/
│   └── marketplace.json          # 市场清单：声明本仓库提供哪些插件
├── plugins/
│   └── publish-check/            # 插件包（会被复制进版本化 cache）
│       ├── .codebuddy-plugin/
│       │   └── plugin.json       # 插件清单
│       ├── LICENSE
│       └── skills/
│           └── publish-check/    # ← 技能本体，与仓库根目录内容一致
│               ├── SKILL.md
│               ├── demo.py
│               ├── scripts/
│               └── references/
├── SKILL.md                      # 仓库根目录 = 直接可用的技能形态
├── scripts/
├── references/
└── demo.py
```

根目录保留技能形态，是为了**不装插件的人也能直接 `cp -r` 使用**；`plugins/publish-check/` 是插件形态。两处的技能文件**内容逐字节相同**（CI 会校验），改完记得同步：

```bash
cp SKILL.md demo.py plugins/publish-check/skills/publish-check/
cp scripts/*.py plugins/publish-check/skills/publish-check/scripts/
cp references/platforms.json plugins/publish-check/skills/publish-check/references/
```

### 为什么没有做成完整插件市场里的「原生插件」

插件还能挂 `commands/`、`agents/`、`hooks/`、MCP server。本工具**故意不挂**：

- 不需要 hook —— 寄生自检靠 `SKILL.md` 里的触发协议，装了插件就自动生效，不需要在用户机器上跑钩子。
- 不需要 MCP server —— 那要求常驻进程和 stdio 协议，与「零依赖、跑完就退出」的设计冲突。
- 不需要 command —— 技能本身就能被自然语言触发，多一个斜杠命令只是多一个要维护的入口。

**能少挂一个组件就少挂一个** —— 每挂一个，用户装之前的信任成本就高一档。

---

## 作为 DeepSeek Harness（dsh）插件安装

本仓库同时是一个 **dsh 插件包**，可以直接装进 [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness)：

```bash
dsh plugin --profile web add github:Stephen-pc/publish-size-check
```

装好后 `publish-check` 会出现在技能目录里，触发方式和上面的 Agent Skill 完全一致。

也可以从 [dsh-market](https://github.com/dsh-market/dsh-market) 一键安装 —— 它内置的插件列表 [awesome-dsh-plugin](https://github.com/awesome-dsh-plugin/awesome-dsh-plugin) 收录了本插件。

### 它长什么样

```
publish-size-check/
├── package.json          # 声明 dsh.bundle
├── cordis.patch.yml      # bundle patch 层：往 profile 树插一条 loader entry
├── lib/index.js          # 技能 provider：把 SKILL.md 挂到 ctx.skills
├── tools/dsh-selftest.mjs
└── SKILL.md              # ← 与仓库根是同一份
```

`lib/index.js` 是一层**很薄的接线**，不是第二个实现：

- **零依赖** —— 只 import `node:fs/promises` / `node:url` / `node:path`，与 `scripts/spec.py` 只用 Python 标准库是同一个原则。
- **不复制正文** —— 候选和正文都在调用时从 `SKILL.md` 现读，改正文不必动这个文件，也不会出现「描述与正文两份、各自漂移」。
- **不覆盖本地版本** —— 它报 `bundled` 秩（600），你在 `~/.dsh/skills/publish-check` 放的本地特化版（`user-dsh` = 400）仍然优先。

判定逻辑始终只有一份，在 `scripts/spec.py`。

### 一个容易踩的坑：`{skill_base}`

`SKILL.md` 正文里写的是 `python {skill_base}/scripts/spec.py` —— `{skill_base}` 是 CodeBuddy / WorkBuddy 形态的占位符，宿主会在运行时替换它。

**dsh 不认这个占位符。** 它走的是另一套机制：provider 报一个 `resourceBase`，宿主把基准目录写进 `<skill_resources>`，并要求模型「把技能里提到的相对路径解析到基准目录下」。

所以 provider 在 `get()` 时把 `{skill_base}/` 削掉，正文里留下的是 dsh 惯例的裸相对路径（基准目录 = 包根）：

```bash
python scripts/spec.py --check cover.png
```

不这么做的话，模型会拿到一条执行不了的命令。削成相对路径、而不是替换成绝对路径，是因为 Windows 绝对路径带反斜杠，写进代码块后在 bash 里会被当成转义字符。

### 自检

```bash
node tools/dsh-selftest.mjs
```

用一个假 `ctx` 走完 `apply()` → `list()` → `get()`，并验证正文引用的相对路径真的落在包根下。CI 还会 `npm pack` 解压后**按安装形态再跑一遍** —— 抓的是 `files` 字段漏文件这类只有用户才会撞上的错。

---

## 这个工具**不**做什么（重要）

**只查几何参数。不查内容合规。**

| 查 | 不查 |
|---|---|
| 像素尺寸、宽高比 | ❌ 内容是否违规 |
| dpi、实际印刷宽度 | ❌ 是否含二维码/联系方式（平台限流项） |
| 文件体积、格式 | ❌ 文字占画面比例 |
| 色彩模式要求 | ❌ 字体版权、图片版权、商标 |
| 多图尺寸一致性 | ❌ 医疗/金融等特殊行业资质标识 |

**不查的那些不是不重要，是本工具做不到。** 范围窄是刻意的——正因如此才能做到零依赖、结果确定、不误判内容。

其它边界：

- **原件只读**。永不修改、移动、重命名、删除任何输入文件。只诊断，不代改。
- **不给有害建议**。绝不说"把 640px 的图缩到 200px"——尺寸不足只能重做，放大无法恢复清晰度。
- **不猜图类型**。判断不了的事（如投稿图是照片还是线条图）会让你选，而不是并列报一堆矛盾结论。
- **不猜规格**。规格库没有的平台用通用兜底值，并**明确标注这是兜底、不是该平台的真实要求**。

---

## 维护规格库

平台会改版。规格库带时效字段，**超过 180 天需复核**：

```bash
python scripts/spec.py --validate
#   [i] 规格库核验于 2026-10-12，0 天前，在有效期内
```

### 改完一定要跑自检和测试

```bash
python scripts/spec.py --validate   # 抓 schema / 别名冲突 / 数值不自洽，有错退出码 1
python scripts/test_spec.py         # 46 项回归测试
```

`--validate` 会检查：schema 缺失、confidence 非法、**verified 却没填 source**、别名冲突、aspect 与 canvas 不自洽、`tolerance`/`alt` 用法错误、安全区不完整、体积类型错。**退出码 1，可以直接接 CI。**

### 加一个平台

在 `references/platforms.json` 的 `platforms` 数组里加一项：

```json
{
  "id": "your-platform",
  "name": "平台名",
  "aliases": ["别名1", "别名2"],
  "kind": "social_cn",
  "confidence": "community",
  "source": "来源链接或说明",
  "slots": [
    {
      "slot": "cover",
      "label": "封面",
      "canvas": { "w": 1080, "h": 1440 },
      "aspect": "3:4",
      "max_bytes": 20971520,
      "formats": ["jpg", "png"],
      "safe_area_pct": { "top": 6, "bottom": 12, "left": 6, "right": 6 }
    }
  ]
}
```

`canvas` 支持三种写法：

- `{ "w": 1080, "h": 1440 }` —— 精确值
- `{ "w": 1146, "h": 717, "tolerance": "gte" }` —— 不小于（B 站封面就是这类）
- `{ "w": 1242, "h": 1660, "alt": [{ "w": 1242, "h": 1656 }] }` —— 多备选取值

### 发现规格有分歧时怎么办

**不要挑一个值写死。** 用 `alt` 记录多个取值，在 `notes` 里说明分歧——真实世界的规格分歧本身就是有价值的信息。抖音的 9:16 / 3:4 就是典型（取决于上传入口）。

### 一条纪律

**运营经验帖不能当规则写。** 网上大量"据说某平台……"的说法没有任何官方或第二方来源。写进规格库前，请确认至少有一个可追溯的来源；拿不准就标 `experience` 并在 `notes` 里写清楚，不要冒充权威。

---

## 测试

```bash
python scripts/test_spec.py
```

**46 项回归测试，纯标准库，不依赖 pytest。** 自建临时图片、跑完自动清理，退出码 0 / 1 可接 CI。

覆盖：规格库自检、图片头解析（PNG/JPEG/GIF/TIFF）、dpi 与物理宽度、`gte` 与 `alt` 语义、单点裁决、行动结论、多图一致性、JSON 契约、别名冲突检测。

---

## License

MIT
