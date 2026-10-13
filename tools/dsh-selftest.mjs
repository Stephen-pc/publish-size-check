/**
 * DSH 插件形态自检。
 *
 * 为什么要有这个文件：`package.json` 里声明了 `dsh.bundle` 只能证明「这个包声称自己是
 * DSH 插件」，证明不了「它真的能被加载」。插件清单写错时，用户在 `dsh plugin add`
 * 那一步才会发现，而那是离作者最远、最难反馈的位置。
 *
 * 这里用一个假的 `ctx` 把 `apply()` 跑一遍，再走完 `list()` → `get()` 这条真实路径，
 * 并把 SKILL.md 正文里引用的相对路径逐个落到磁盘上验证。
 *
 * **两种用法**（同一份断言，换个被测目录）：
 *
 *   node tools/dsh-selftest.mjs
 *     → 测当前仓库。CI 每次提交都跑。
 *
 *   node tools/dsh-selftest.mjs /tmp/sim/node_modules/publish-size-check
 *     → 测一个**打包解压后**的目录。CI 在 `npm pack` + 解压之后跑这一步，
 *       用来抓 `files` 字段漏文件这类只有用户才会撞上的错。
 *
 * 零依赖：只 import `node:` 内置模块。
 */

import { access, readFile } from 'node:fs/promises'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { dirname, join, resolve } from 'node:path'

const SCRIPT_DIR = dirname(fileURLToPath(import.meta.url))

/** 被测包根：默认是当前仓库；也可由命令行指定一个已安装/已解压的包目录。 */
const ROOT = resolve(process.argv[2] ?? join(SCRIPT_DIR, '..'))
const TESTING_INSTALLED = process.argv[2] !== undefined

// 动态 import：被测的 lib/index.js 可能不在本脚本所在的仓库里。
const mod = await import(pathToFileURL(join(ROOT, 'lib', 'index.js')).href)
const { apply, get, inject, isSkillName, list, name: pluginName, parseFrontmatter, provider } = mod

let passed = 0
const failures = []

/**
 * 断言。
 * @param {boolean} cond - 条件。
 * @param {string} label - 描述。
 * @param {string} [detail] - 失败时附加信息。
 */
function ok(cond, label, detail) {
  if (cond) {
    passed += 1
    return
  }
  failures.push(detail ? `${label} — ${detail}` : label)
}

/** 断言文件存在。 */
async function exists(p) {
  try {
    await access(p)
    return true
  } catch {
    return false
  }
}

console.log(`被测包根：${ROOT}${TESTING_INSTALLED ? '（安装形态）' : '（仓库形态）'}`)

/** 1. 插件导出的形状 */
ok(pluginName === 'publish-check', 'export const name 应为 publish-check', `实际 ${pluginName}`)
ok(Array.isArray(inject) && inject.includes('skills'), 'inject 应包含 skills', JSON.stringify(inject))
ok(provider?.name === 'publish-check', 'provider.name 应为 publish-check', String(provider?.name))
ok(typeof provider?.list === 'function', 'provider.list 应是函数')
ok(typeof provider?.get === 'function', 'provider.get 应是函数')

/** 2. apply() 能把自己注册进 ctx.skills */
let registered = null
let registeredCount = 0
apply({
  skills: {
    registerProvider(factory) {
      registeredCount += 1
      registered = factory()
    },
  },
})
ok(registeredCount === 1, 'apply() 应恰好注册一次 provider', `实际 ${registeredCount} 次`)
ok(registered?.name === 'publish-check', '注册的 provider 名不符', String(registered?.name))

/** 3. cordis.patch.yml 的 id/name 必须与代码和 package.json 对得上 */
const patch = await readFile(join(ROOT, 'cordis.patch.yml'), 'utf8')
const pkg = JSON.parse(await readFile(join(ROOT, 'package.json'), 'utf8'))
const idMatch = patch.match(/^\s*-\s*id:\s*(\S+)\s*$/m)
const nameMatch = patch.match(/^\s*name:\s*['"]?([^'"\s]+)['"]?\s*$/m)
ok(idMatch?.[1] === pluginName, 'cordis.patch.yml 的 id 应等于 lib 导出的 name', `patch=${idMatch?.[1]} code=${pluginName}`)
ok(
  nameMatch?.[1] === pkg.name,
  'cordis.patch.yml 的 name 应等于 package.json 的 name',
  `patch=${nameMatch?.[1]} package.json=${pkg.name}`,
)
ok(pkg.dsh?.bundle?.patch === './cordis.patch.yml', 'package.json 的 dsh.bundle.patch 应指向 ./cordis.patch.yml', String(pkg.dsh?.bundle?.patch))
ok(pkg.type === 'module', 'package.json 的 type 应为 module')

/** 4. list() 返回的候选要满足注册表的契约 */
const candidates = await list()
ok(Array.isArray(candidates) && candidates.length === 1, 'list() 应返回 1 条候选', `实际 ${candidates?.length}`)
const cand = candidates[0] ?? {}
ok(isSkillName(cand.name), '候选 name 应是 kebab-case', String(cand.name))
ok(cand.name === pluginName, '候选 name 应与插件名一致', `${cand.name} vs ${pluginName}`)
ok(typeof cand.description === 'string' && cand.description.length > 0, '候选 description 不应为空')
ok(typeof cand.rank === 'number', '候选 rank 应是数字', String(cand.rank))
ok(cand.source === 'bundled', '候选 source 应为 bundled', String(cand.source))
ok(cand.provider === 'publish-check', '候选 provider 应为 publish-check', String(cand.provider))
ok(cand.invocation?.modelInvocable === true, '默认应允许模型调用')
ok(cand.invocation?.userInvocable === true, '默认应允许用户调用')
ok(cand.resourceBase?.kind === 'directory', 'resourceBase 应是 directory', String(cand.resourceBase?.kind))
ok(cand.resourceBase?.path === ROOT, 'resourceBase 应指向包根', `实际 ${cand.resourceBase?.path}，期望 ${ROOT}`)
ok(
  !cand.resourceBase?.path?.endsWith('/') && !cand.resourceBase?.path?.endsWith('\\'),
  'resourceBase 不应带尾分隔符（宿主拼接相对路径时会不一致）',
)

/** 5. get() 返回完整正文，且 frontmatter 已被剥离 */
const def = await get(cand)
ok(typeof def?.content === 'string' && def.content.length > 0, 'get() 的 content 不应为空')
ok(!def.content.startsWith('---'), 'get() 的 content 不应仍带 frontmatter')
ok(def.content.includes('# 发布尺寸检查'), 'content 应是 SKILL.md 正文', def.content.slice(0, 40))

/**
 * `{skill_base}` 是 CodeBuddy / WorkBuddy 形态的占位符，dsh 不认它 —— dsh 走的是
 * provider 的 `resourceBase` + 「把相对路径解析到基准目录」这套。残留占位符意味着
 * 模型会拿到一条执行不了的命令，所以这里守死。
 */
ok(!def.content.includes('{skill_base}'), 'get() 的 content 不应残留 {skill_base} 占位符')
ok(!String(cand.description).includes('{skill_base}'), '候选 description 不应残留 {skill_base} 占位符')

/** 6. SKILL.md 正文里引用的相对路径，必须真的落在包根下 */
const refRe = /(?:^|[\s`'"(])((?:scripts|references)\/[A-Za-z0-9_./-]+)/gm
const refs = [...new Set([...def.content.matchAll(refRe)].map((m) => m[1]))]
ok(refs.length > 0, 'SKILL.md 正文应至少引用一个相对资源路径（否则说明解析或正文变了）')
// 削掉 `{skill_base}/` 之后，脚本路径才成为裸相对路径、才会被上面的正则认出来。
// 这里显式点名，是为了让「占位符替换失效」表现成一条明确的失败，而不是被静默跳过。
ok(
  refs.some((r) => r.startsWith('scripts/')),
  '削掉 {skill_base} 后应能识别出 scripts/ 下的脚本引用',
  `实际识别到：${refs.join(', ') || '(空)'}`,
)
for (const rel of refs) {
  ok(await exists(join(ROOT, rel)), `正文引用的资源不存在：${rel}`)
}

/** 7. frontmatter 解析的边界情况 */
ok(parseFrontmatter('---\nname: a-b\n---\nbody').fm.name === 'a-b', '应能解析基本 frontmatter')
ok(parseFrontmatter('\uFEFF---\r\nname: a-b\r\n---\r\nbody').fm.name === 'a-b', '应能处理 BOM 与 CRLF')
ok(parseFrontmatter('---\ndescription: "含: 冒号"\n---\nb').fm.description === '含: 冒号', '应能处理带冒号的带引号值')
ok(parseFrontmatter("---\ndescription: '单引号'\n---\nb").fm.description === '单引号', '应能处理单引号值')
ok(parseFrontmatter('---\nmetadata:\n  author: x\n---\nb').fm.author === undefined, '缩进子键不应被当成顶层键')
ok(parseFrontmatter('no frontmatter').body === 'no frontmatter', '无 frontmatter 时应原样返回')
ok(!isSkillName('Bad_Name') && !isSkillName('-x') && isSkillName('publish-check'), 'isSkillName 应只放行 kebab-case')

/** 8. 只在安装形态下检查：npm 的 files 字段必须把技能运行需要的东西都带上 */
if (TESTING_INSTALLED) {
  for (const rel of ['SKILL.md', 'lib/index.js', 'cordis.patch.yml', 'scripts/spec.py', 'references/platforms.json', 'package.json']) {
    ok(await exists(join(ROOT, rel)), `安装后缺少必需文件：${rel}（检查 package.json 的 files 字段）`)
  }
}

/** 汇总 */
if (failures.length) {
  console.error(`DSH 自检失败 ${failures.length} 项（通过 ${passed} 项）：`)
  for (const f of failures) console.error('  ✗ ' + f)
  process.exit(1)
}
console.log(`OK：DSH 插件形态自检通过（${passed} 项）`)
