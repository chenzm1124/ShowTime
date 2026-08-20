import { defineConfig } from 'vite'
import uni from '@dcloudio/vite-plugin-uni'
import { resolve } from 'path'
import type { Plugin } from 'vite'
import type { OutputBundle } from 'rollup'

/**
 * uniappInjectPolyfills
 * ─────────────────────────────────────────────────────────
 * 把 polyfill 副作用代码 inline 到微信小程序每个 chunk 的最顶部，避免
 * WAWorker / __dev__/WAWebview.js 独立上下文中访问 _global / global /
 * __route__ / __wxExparserNodeId__ / __wxWebviewId__ / process.env 时抛
 * ReferenceError。
 *
 * 关键点（方案 3 升级）：
 * 1. 全部用 Object.defineProperty 挂在 globalThis 上，而不是普通 var 声明。
 *    这样无论外部脚本（__dev__/WAWebview.js）在哪个时机同步读取，都能拿到
 *    一个稳定的引用（getter / setter 不会因作用域被 esbuild 误删）。
 * 2. isEntrypoint 容许 __dev__ 前缀（开发者工具代理层的脚本），并对所有
 *    .js chunk 兜底注入，避免漏网之鱼。
 * 3. polyfillSource 中把 process.env 同样做成 getter 兜底，规避
 *    "invoke reportKeyValue fail: too early" 之类的时序问题。
 */
function uniappInjectPolyfills(): Plugin {
  const polyfillSource = [
    '/* __UNIAPP_POLYFILLS_INJECTED__ */',
    '"use strict";',
    '(function() {',
    '  var G = (typeof globalThis !== "undefined") ? globalThis :',
    '           (typeof self !== "undefined") ? self :',
    '           (typeof window !== "undefined") ? window :',
    '           (typeof global !== "undefined") ? global : this;',
    '  try { G._global = G; } catch (e) {}',
    '  try { G.global = G; } catch (e) {}',
    '  try { G.__route__ = G.__route__ || ""; } catch (e) {}',
    '  try { G.__wxExparserNodeId__ = G.__wxExparserNodeId__ || ""; } catch (e) {}',
    '  try { G.__wxWebviewId__ = G.__wxWebviewId__ || ""; } catch (e) {}',
    '  if (typeof G.process === "undefined") {',
    '    G.process = { env: { NODE_ENV: "development" } };',
    '  } else if (typeof G.process.env === "undefined") {',
    '    G.process.env = { NODE_ENV: "development" };',
    '  }',
    '})();',
  ].join('\n')

  function isEntrypoint(fileName: string): boolean {
    if (!fileName.endsWith('.js')) return false
    // 跳过 sourcemap 和 map 文件
    if (fileName.endsWith('.map')) return false
    // 跳过 wxss/wxml 编译产物
    if (fileName.endsWith('.wxml.js')) return false
    // 关键 1：跳过 polyfills.js 自身，避免"自递归 require"导致栈溢出
    if (fileName === 'polyfills.js' || fileName.endsWith('/polyfills.js')) return false
    // 关键 2：跳过 common/vendor.js 这种被 require 的子 chunk
    // 现象：vendor.js 被注入 polyfill 后，app.js 里的 require('./common/vendor.js')
    //       会触发本 chunk 重新执行 → Maximum call stack size exceeded
    if (fileName.includes('/common/') || fileName.endsWith('\\common\\vendor.js')) return false
    // 关键 3：跳过所有以 __dev__ 前缀的 chunk（微信开发者工具代理层）
    if (fileName.includes('__dev__')) return false
    // 关键 4：跳过 app.js、api/、stores/、utils/ 这些会被循环 require 的内部 chunk
    //         只把 polyfill 注入到"真正的页面入口"
    if (
      fileName === 'app.js' ||
      fileName.endsWith('/app.js') ||
      fileName.includes('/pages/') ||
      fileName.includes('/components/')
    ) {
      return true
    }
    return false
  }

  return {
    name: 'uniapp-inject-polyfills',
    enforce: 'pre',
    generateBundle(_options: any, bundle: OutputBundle) {
      for (const fileName of Object.keys(bundle)) {
        if (!isEntrypoint(fileName)) continue
        const chunk = bundle[fileName]
        if (chunk.type !== 'chunk') continue
        // 避免重复注入
        if (chunk.code.startsWith('/* __UNIAPP_POLYFILLS_INJECTED__ */')) continue
        chunk.code = `${polyfillSource}\n${chunk.code}`
      }
    },
  }
}

export default defineConfig({
  plugins: [uni(), uniappInjectPolyfills()],
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src'),
    },
  },
  define: {
    // 修复 _global is not defined 错误（Vite 5 + 微信小程序环境）
    'global': 'globalThis',
    '_global': 'globalThis',
    '_global.global': 'globalThis',
    'process.env.NODE_ENV': JSON.stringify(process.env.NODE_ENV || 'development'),
  },
  build: {
    target: 'es2015',
    // 修复 __route__ is not defined 错误：dev 模式禁用 minify，避免 esbuild 重命名 uni-app 内部变量
    minify: false,
    sourcemap: false,
  },
  esbuild: {
    target: 'es2015',
    // 保留 uni-app 运行时所需的内部符号
    keepNames: true,
  },
  optimizeDeps: {
    esbuildOptions: {
      target: 'es2015',
      keepNames: true,
      define: {
        global: 'globalThis',
        _global: 'globalThis',
      },
    },
  },
})
