/**
 * 深度验证：用**官方 cordis 运行时**真的把插件加载一次。
 *
 * 与 `dsh-selftest.mjs` 的分工：
 *   · `dsh-selftest.mjs` 用假 ctx 验证**契约**——导出的形状、清单字段、路径解析。
 *     零依赖，CI 每次提交都跑。
 *   · 本文件验证**集成**——把真正的 `@deepseek-ai/cordis` + `@deepseek-ai/dsh-skill`
 *     拉起来，走 `ctx.plugin()` → `ctx.skills.list()` → `ctx.skills.get()` →
 *     `renderSkillContent()`，看模型最终会收到什么。
 *
 * **不进 CI。** 它需要联网装官方运行时，官方包一发新版本就可能改 API——
 * 那是上游的正常演进，不该让本仓库的 CI 变红。需要时手动跑一次。
 *
 * 用法（`cd` 到一个空目录，在那里装依赖，然后从那里运行本脚本）：
 *
 *   npm init -y
 *   npm install @deepseek-ai/cordis@~4.0.4 @deepseek-ai/dsh-skill@0.2.0-rc.2 \
 *               @deepseek-ai/dsh-llm@0.2.0-rc.2 @deepseek-ai/dsh-scope@0.2.0-rc.2
 *   node <本文件的绝对路径> <被验证的包目录>
 *
 * 注意是 `cd` 到**装了依赖**的那个目录，而不是被测包目录——脚本按当前工作目录解析
 * 官方运行时，`<被验证的包目录>` 则作为参数传入。两者可以是同一个目录，也可以不是。
 *
 * 其中 `<被验证的包目录>` 可以是本仓库根目录，也可以是 `npm pack` 解压后的目录。
 */

import { join } from 'node:path'
import { createRequire } from 'node:module'
import { pathToFileURL } from 'node:url'

const PKG = process.argv[2]
if (!PKG) {
  console.error('用法: node tools/dsh-real-load.mjs <包目录>')
  process.exit(2)
}

/**
 * ESM 的 `import` 从**脚本所在目录**向上找 `node_modules`，而 `NODE_PATH` 对它不生效。
 * 本文件住在被测仓库里，官方运行时却装在别处，所以这里显式按**当前工作目录**解析：
 * `cd` 到装了那些 `@deepseek-ai/*` 包的目录再跑即可。
 */
const req = createRequire(join(process.cwd(), '__resolve__.cjs'))
const resolvePkg = (name) => pathToFileURL(req.resolve(name)).href

let Context
let SkillRegistry
let renderSkillContent
try {
  ;({ Context } = await import(resolvePkg('@deepseek-ai/cordis')))
  ;({ default: SkillRegistry, renderSkillContent } = await import(resolvePkg('@deepseek-ai/dsh-skill')))
} catch (e) {
  console.error('加载官方运行时失败——请先按文件头的说明 npm install 那几个 @deepseek-ai/* 包，')
  console.error(`并从装了它们的目录运行本脚本（当前工作目录：${process.cwd()}）。`)
  console.error(String(e?.message ?? e))
  process.exit(2)
}

const mod = await import(pathToFileURL(join(PKG, 'lib', 'index.js')).href)

let fail = 0
const ok = (cond, msg) => {
  console.log((cond ? '  OK   ' : '  FAIL ') + msg)
  if (!cond) fail += 1
}

const ctx = new Context()
// cordis 的 `plugin()` 返回 Fiber（thenable）：必须 await，否则服务还没注册完就往下走了。
await ctx.plugin(SkillRegistry)
await ctx.plugin(mod)

ok(typeof ctx.skills === 'object' && ctx.skills !== null, 'ctx.skills 服务已就绪')
ok(typeof ctx.skills.registerProvider === 'function', 'ctx.skills 暴露了 registerProvider')

const catalog = await ctx.skills.list({ cwd: PKG })
const all = catalog?.skills ?? catalog
const names = (all ?? []).map((s) => s.name)
console.log('  注册表里可见的技能:', JSON.stringify(names))
ok(names.includes('publish-check'), '注册表里能找到 publish-check')

const summary = (all ?? []).find((s) => s.name === 'publish-check')
ok(!!summary, '拿得到 publish-check 的摘要')
if (summary) {
  ok(summary.provider === 'publish-check', `provider = ${summary.provider}`)
  ok(summary.source === 'bundled', `source = ${summary.source}`)
  ok(summary.invocation?.modelInvocable === true, 'modelInvocable 为真')
  ok(summary.invocation?.userInvocable === true, 'userInvocable 为真')
  ok(summary.resourceBase?.kind === 'directory', `resourceBase.kind = ${summary.resourceBase?.kind}`)
  ok(summary.resourceBase?.path === PKG, 'resourceBase.path 指向包根')
}

const def = await ctx.skills.get('publish-check', { cwd: PKG })
ok(!!def, 'ctx.skills.get() 取到技能定义')
if (def) {
  ok(typeof def.content === 'string' && def.content.length > 1000, `正文长度 ${def.content?.length}`)
  ok(!def.content.includes('{skill_base}'), '正文不含 {skill_base} 残留')

  // 渲染成模型真正会看到的那段文本，检查基准目录说明确实注入了
  const rendered = renderSkillContent(def)
  ok(rendered.includes('<skill_content'), '渲染出 <skill_content> 块')
  ok(rendered.includes('Base directory for this skill'), '渲染结果里带基准目录说明')
  ok(rendered.includes(PKG), '基准目录就是包根')
  ok(!rendered.includes('{skill_base}'), '渲染结果里没有不可执行的占位符')
  console.log('  ---- 渲染结果前 380 字符 ----')
  console.log(
    rendered
      .slice(0, 380)
      .split('\n')
      .map((l) => '    ' + l)
      .join('\n'),
  )
}

await ctx.stop?.()
console.log(fail ? `\n失败 ${fail} 项` : '\n真实加载：全部通过')
process.exit(fail ? 1 : 0)
