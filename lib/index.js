/**
 * publish-check — DSH 技能提供者：把本包自带的 SKILL.md 挂到 `ctx.skills`。
 *
 * 为什么需要这一层：DeepSeek Harness 的插件市场只收「能用 `dsh plugin add` 装上的包」——
 * 包必须在 package.json 里声明 `dsh.bundle`，并在包根放一份 cordis.patch.yml。而技能正文
 * 只是一份 SKILL.md，它要进入会话的技能目录就需要一个 provider，本文件就是那层很薄的接线。
 *
 * 三条刻意的性质：
 *   · **不复制技能正文** —— 候选与正文都在调用时从 SKILL.md 现读。改 SKILL.md 不必动本文件，
 *     也不会出现「描述与正文两份、各自漂移」。
 *   · **零依赖** —— 只 import `node:` 内置模块，与本项目其余部分同一原则（scripts/spec.py
 *     只用 Python 标准库）。判定逻辑全在 scripts/spec.py，与宿主无关；本文件不重复实现任何
 *     规格判定，只做搬运。
 *   · **不覆盖用户的本地版本** —— 本 provider 报 bundled 秩（600），装了本插件的机器若在
 *     `~/.dsh/skills/publish-check` 放了本地特化版（user-dsh = 400），本地那份仍然优先。
 *
 * @module publish-size-check
 */

import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { resolve } from 'node:path'

/** 包根（lib/ 的上一级）。SKILL.md、scripts/、references/ 都在那里。 */
const ROOT_URL = new URL('..', import.meta.url)
const SKILL_URL = new URL('SKILL.md', ROOT_URL)
const PKG_URL = new URL('package.json', ROOT_URL)

/**
 * 包根的宿主路径。
 *
 * 必须过一道 `resolve()`：`fileURLToPath()` 对以 `/` 结尾的目录 URL 会保留尾分隔符
 * （`D:\...\publish-size-check\`），而 `resourceBase.path` 是交给宿主去拼相对路径的，
 * 带尾分隔符的形态在不同平台上拼接结果不一致。归一成不带尾分隔符的绝对路径。
 */
const ROOT_PATH = resolve(fileURLToPath(ROOT_URL))

/** provider 名，在 `ctx.skills` 注册表里唯一。 */
const PROVIDER_NAME = 'publish-check'

/**
 * bundled 档的秩。DSH 里 `BUNDLED_SKILL_RANK = 600`（本地 provider 的其余档位：
 * project 100/200、custom 300、user-dsh 400、user-agents 500）。
 *
 * 这里写常量而不是 import 那个导出，是为了保持零依赖。秩只在**同名技能**上起作用，
 * 而低秩胜出：装了本插件的机器若同时在 `~/.dsh/skills/publish-check` 放了一份本地特化版
 * （user-dsh = 400），本地那份仍然优先——这是刻意的，插件不该覆盖用户自己的版本。
 */
const RANK = 600

/** 技能名必须匹配 DSH 的 kebab-case 语法，否则注册表会拒收这个候选。 */
const SKILL_NAME_RE = /^[a-z0-9]+(?:-[a-z0-9]+)*$/

/**
 * 去掉 YAML 标量外层成对的引号。
 *
 * 只处理首尾成对的 `"` 或 `'`，不做反转义：本技能的 frontmatter 由本仓库自己维护，
 * 值里不含需要转义的引号（中文正文用的是全角引号）。若将来真的需要转义，这里应当
 * 换成一个真正的 YAML 解析器，而不是继续在正则上打补丁。
 *
 * @param {string} value - 原始标量文本。
 * @returns {string} 去引号后的文本。
 */
function unquote(value) {
  const s = value.trim()
  if (s.length >= 2) {
    const first = s[0]
    const last = s[s.length - 1]
    if ((first === '"' && last === '"') || (first === "'" && last === "'")) {
      return s.slice(1, -1)
    }
  }
  return s
}

/**
 * 读 SKILL.md 的 YAML frontmatter。
 *
 * 只认本技能真正用到的键，因此不需要 YAML 依赖。缩进行（如 `metadata:` 下的
 * `author: ...`）不会被匹配，因为键名必须紧贴行首。
 *
 * @param {string} text - SKILL.md 全文。
 * @returns {{fm: Record<string, string>, body: string}} frontmatter 键值表与去掉它的正文。
 */
export function parseFrontmatter(text) {
  // 去掉可选的 BOM 并把 CRLF 归一为 LF：编辑器编码与 Windows 检出不该改变解析结果。
  const src = String(text).replace(/^\uFEFF/, '').replace(/\r\n/g, '\n')
  if (!src.startsWith('---')) return { fm: {}, body: src }
  const end = src.indexOf('\n---', 3)
  if (end === -1) return { fm: {}, body: src }
  const fm = {}
  for (const line of src.slice(3, end).split('\n')) {
    const m = line.match(/^([A-Za-z0-9_-]+):[ \t]*(.*)$/)
    if (m) fm[m[1]] = unquote(m[2])
  }
  return { fm, body: src.slice(end + 4).replace(/^\n+/, '') }
}

/** 技能名是否合法。 */
export function isSkillName(name) {
  return SKILL_NAME_RE.test(String(name))
}

/**
 * 把技能文本里的 `{skill_base}` 占位符换成 dsh 认的形式。
 *
 * 本仓库是双入口：CodeBuddy / WorkBuddy 形态用 `{skill_base}` 表示技能根目录，宿主在
 * 运行时替换它。**dsh 不认这个占位符** —— 它走另一套机制：provider 报 `resourceBase`，
 * 宿主把基准目录写进 `<skill_resources>`，并要求模型「把技能里提到的相对路径解析到
 * 基准目录下」（见 dsh-skill 的 `renderResourceHint`）。
 *
 * 所以这里把 `{skill_base}/` 削掉，正文里留下的就是 dsh 惯例的裸相对路径
 * （`scripts/spec.py`），与指向包根的 `resourceBase` 配合正好。
 *
 * 用裸相对路径、而不是替换成绝对路径，是因为 Windows 绝对路径带反斜杠，写进
 * ```bash 代码块后在 bash 里会被当成转义字符；相对路径配合宿主的基准目录说明没有这个问题。
 *
 * @param {string} text - 技能描述或正文。
 * @returns {string} 替换后的文本。
 */
function toDshPaths(text) {
  return String(text).replace(/\{skill_base\}\//g, '')
}

/**
 * frontmatter 的调用开关：省略即两处都开。
 *
 * 本技能的默认是两者都开——「寄生自检」这一路触发依赖模型自己能看见这个技能，
 * 而斜杠调用是给用户的入口。没有理由关掉任何一边。
 */
function invocationOf(fm) {
  return {
    modelInvocable: String(fm['disable-model-invocation'] ?? '').toLowerCase() !== 'true',
    userInvocable: String(fm['user-invocable'] ?? '').toLowerCase() !== 'false',
  }
}

/**
 * 取技能描述：优先中文 `description`，回退 `description_en`，最后回退 package.json。
 *
 * 用中文优先是有意的：本技能的大量触发词是中文口语（「这图发小红书会不会糊」），
 * 中文描述进技能目录时路由更准。
 *
 * @param {Record<string, string>} fm - frontmatter 键值表。
 * @returns {Promise<string>} 非空的描述文本。
 */
async function descriptionOf(fm) {
  const own = fm.description || fm.description_en
  if (own) return own
  const pkg = JSON.parse(await readFile(PKG_URL, 'utf8'))
  if (pkg.description) return pkg.description
  throw new Error('SKILL.md 的 frontmatter 缺少 description，且 package.json 也没有 description')
}

/**
 * 读候选：每次调用都重读 SKILL.md，所以正文改完立刻生效，不需要版本号或缓存失效。
 *
 * 读失败**不吞** —— 让 `list()` 拒绝比返回空数组诚实：注册表会把拒绝记成一次不完整的
 * 观测并保留上一次的好目录，而返回空数组等于告诉模型「这个技能被删了」。
 *
 * @returns {Promise<object[]>} 本包只提供一条技能，因此是长度为 1 的数组。
 */
export async function list() {
  const { fm } = parseFrontmatter(await readFile(SKILL_URL, 'utf8'))
  if (!isSkillName(fm.name)) {
    throw new Error(`SKILL.md 的 frontmatter name 不是 kebab-case：${JSON.stringify(fm.name)}`)
  }
  return [
    {
      name: fm.name,
      description: toDshPaths(await descriptionOf(fm)),
      invocation: invocationOf(fm),
      provider: PROVIDER_NAME,
      source: 'bundled',
      // 资源基准指向包根：正文里写的 `scripts/spec.py`、`references/platforms.json`
      // 因此可解析——包根下确实有这两个目录。若改成指向别处，正文里的相对路径会全部失效。
      resourceBase: { kind: 'directory', path: ROOT_PATH },
      path: fileURLToPath(SKILL_URL),
      rank: RANK,
      locator: SKILL_URL,
    },
  ]
}

/**
 * 读正文：frontmatter 已剥离，返回的就是指令正文。
 *
 * @param {object} candidate - `list()` 给出的候选。
 * @returns {Promise<object>} 完整技能定义。
 */
export async function get(candidate) {
  const { fm, body } = parseFrontmatter(await readFile(SKILL_URL, 'utf8'))
  // 正文里的 name 与候选不一致说明两次读之间文件被换过 —— 抛出去让注册表重新发现，
  // 而不是交出一份名不副实的定义。
  if (fm.name !== candidate.name) {
    throw new Error(
      `SKILL.md 的 name 已变为 ${JSON.stringify(fm.name)}，与候选 ${JSON.stringify(candidate.name)} 不符`,
    )
  }
  return {
    name: candidate.name,
    description: toDshPaths(await descriptionOf(fm)),
    invocation: candidate.invocation,
    provider: PROVIDER_NAME,
    source: 'bundled',
    resourceBase: candidate.resourceBase,
    path: candidate.path,
    content: toDshPaths(body),
  }
}

/** 本 provider 的实例（无内部状态：不缓存正文，全部现读）。 */
export const provider = { name: PROVIDER_NAME, list, get }

/** Cordis 插件名（与 cordis.patch.yml 的 `id` 一致）。 */
export const name = PROVIDER_NAME
/** 本插件依赖的服务：技能注册表。 */
export const inject = ['skills']

/**
 * 挂载：把本 provider 注册到 `ctx.skills`。注册是同步的，发现与读正文都在 awaits 里。
 *
 * @param {{skills: {registerProvider: Function}}} ctx - Cordis 上下文。
 * @returns {void}
 */
export function apply(ctx) {
  ctx.skills.registerProvider(() => provider)
}
