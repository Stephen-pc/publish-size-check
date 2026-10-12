# 更新日志

本项目遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [2.2.0] - 2026-10-12

### 新增
- **可装成 CodeBuddy / WorkBuddy 插件。** 仓库同时是插件市场，一条命令即可安装：
  ```bash
  /plugin marketplace add Stephen-pc/publish-size-check
  /plugin install publish-check@publish-size-check
  ```
  - `.codebuddy-plugin/marketplace.json` —— 市场清单
  - `plugins/publish-check/.codebuddy-plugin/plugin.json` —— 插件清单（`skills` 指向 `./skills/publish-check`）
  - `plugins/publish-check/skills/publish-check/` —— 插件形态的技能本体
- 打包成插件后自动获得**版本管理与团队分发**：`/plugin update` 升级、写进 `.codebuddy/settings.json` 让协作者自动获得。

### 变更
- **`demo.py` 支持两种安装形态。** 新增 `_find_skill_root()` 探测技能根目录——插件会被复制进版本化 cache，`demo.py` 不再总是与 `scripts/` 同级。仓库形态与插件形态下均可直接运行。
- CI 新增 `plugin` 任务：校验两处技能文件逐字节一致、市场与插件清单字段合法、插件形态下冒烟测试通过。

### 说明
- 根目录仍保留完整技能形态，`cp -r` 即可用于不支持插件的环境。两处副本内容必须一致，由 CI 强制。

## [2.1.1] - 2026-10-12

### 修复
- **Windows 上输出中文直接崩溃。** Windows 的 Python 默认按控制台代码页（cp1252 / cp936）编码 stdout，而本工具的输出全是中文，一运行就抛 `UnicodeEncodeError` 退出。Linux / macOS 默认 UTF-8，所以这个 bug 在开发机上完全看不到——是 CI 的 Windows 任务抓出来的。
  - 修法：启动时强制 stdout / stderr 用 UTF-8，三重兜底（`reconfigure` → 重建 `TextIOWrapper` → 放弃但不抛异常）。
  - 加了 3 项回归测试（cp1252 / cp936 / ascii 各跑一遍），并新增一条专门的 CI 任务守住。

## [2.1.0] - 2026-10-12

### 新增
- **寄生入口协议**：出图流程结束后（有文件落盘 + 用户提到发布目标），自动跑一次体检并用一句话带过结论。汇报分级——通过就一句话，有问题才展开并给替代方案。附带完整的协作边界（不改图 / 不抢活 / 不阻断出图）。
- `_find_spec_path()`：规格库路径容错，兼容源码运行、pip 安装、扁平安装三种布局；支持 `PUBLISH_SIZE_CHECK_SPEC` 环境变量覆盖。
- `pyproject.toml`：可 `pip install .`，提供 `publish-size-check` 命令。
- GitHub Actions CI：跨平台 × 多 Python 版本测试，外加一条**零依赖守卫**（拦住任何第三方 import）。

### 变更
- 触发声明（`description`）明确写入两种触发模式，寄生模式标注"不要等用户开口问"。
- 触发词设计新增 **E 类：寄生模式**——这一类没有触发词，触发条件是流程状态而非措辞。
- 文档整理为独立仓库形态（README / CONTRIBUTING / CHANGELOG / LICENSE）。

## [2.0.0] - 2026-10-12

### 变更
- **收窄定位**：`display_name` 由「发布前体检」改为「发布尺寸检查」——原名承诺了它做不到的事。
- 新增「查什么 / 不查什么」对照表，把"不查内容合规"放在最显眼处；`metadata.scope` 明确为"仅几何参数"。
- 去掉小红书 `notes` 中一条无来源依据的断言（"文字占比超 20% 降权"，核实后搜不到任何官方或第二方来源）。

### 新增
- **多图一致性检查**：
  - `check_multi_image()` —— 张数上限 + 尺寸一致性，三档规则（超上限报错 / 要求统一才报错 / 只要求宽度则降级为提醒）
  - `multi_verdict_hint()` —— 组级结论**指出少数派是哪一张**，而非"三张都不一致"
  - `--json` 输出新增 `multi_image` 字段
  - `platforms.json` 为小红书 / 微博 / 公众号增加 `multi_image` 配置
- 回归测试由 36 项增至 46 项。

### 修复
- `solo_failed` 的键名与消费方不一致导致 `KeyError`。
- 少数派识别第一版把多数派也列出来，措辞误导，改为只列少数派。

## [1.1.0] - 2026-10-12

### 新增
- **物理尺寸判定**：新增 `physical_width_mm` 字段与 `PHYSICAL_TOO_SMALL` 规则，按 `像素数 ÷ dpi × 25.4` 计算实际印刷宽度。**修掉一个根本性设计缺陷**——原实现只比 dpi 数值，会放行 `800×600 @300dpi`（实际仅 68mm 宽）这类印不出来的图。
- 厂商栏宽数据：Nature 88/180mm、Science 57/121mm、Cell 85/174mm。
- `choose_hint`：脚本无法判断的槽位（如照片图 vs 线条图）交由用户选择，而不是并列报矛盾结论。
- 微信视频号平台。
- `--validate` 自检，退出码 1 可接 CI。
- `scripts/test_spec.py` 回归测试。

### 变更
- **单点裁决**：`pick_slots` 改为永远只把最匹配的槽位当主结论，其余降为一行提点。根治"把 640px 的图缩到 200px"这类有害建议。
- `remedy()`：输出一句行动结论（能否直接发、救不救得了），取代纯问题清单。
- 扫描模式默认只扫 `social_cn` 类，专业场景需显式指定；通过项保留为一行摘要。
- schema 1.0.0 → 1.1.0；`confidence` 改为 verified / community / experience，且 verified 必须填 `source`。

### 修复
**据实修正 5 处数据错误：**
- 微信公众号正文配图 `1080` → **`900`**（官方口径；原值会让合规图被误报过小）
- 哔哩哔哩封面体积上限 `5MB` → **`2MB`**；且 1146×717 是"不小于"而非精确值
- 微博配图补上主比例 **1080×1350 (4:5)**
- 知乎配图去掉无依据的"宽 1440"，改为 1:1 的 1080×1080
- 抖音标注修正：9:16 为视频封面主规格，3:4 属图文内容

## [1.0.0] - 2026-10-12

### 新增
- 首个版本。10 个平台 / 20 个槽位 / 46 个可解析名称。
- 纯标准库图片头解析（PNG `pHYs` / JPEG `JFIF APP0` 与 `SOF` / GIF / TIFF），无需 Pillow。
- CLI：`--list` / `--spec` / `--check` / `--target` / `--json`。
- 平台参数支持 id、中文名、别名与模糊匹配。

### 修复
- PNG `pHYs` 解析错位：`IHDR` 分支读完 13 字节未跳过 4 字节 CRC，导致后续块偏移全错，600dpi 合格图被误判为"无法读取 dpi"。
