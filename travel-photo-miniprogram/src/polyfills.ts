/**
 * 全局 polyfill
 * 修复 uni-app + Vite 5 在微信小程序模拟器中的两个常见错误：
 * 1. _global is not defined （vendor.js 中 process.env 等访问）
 * 2. __route__ is not defined （page mock 机制访问 route 失败）
 *
 * 必须在 main.ts 顶部最先 import！
 */

// 1. 兜底 _global（uni-app vendor.js 在某些边界条件访问）
// eslint-disable-next-line @typescript-eslint/no-explicit-any
;(globalThis as any)._global = globalThis
// eslint-disable-next-line @typescript-eslint/no-explicit-any
;(globalThis as any).global = globalThis

// 2. 兜底 __route__ 等 mock 字段
// uni-app 用这些 mock 字段做兜底渲染，当页面缺少 route 时使用
const mockKeys = ['__route__', '__wxExparserNodeId__', '__wxWebviewId__']
mockKeys.forEach((key) => {
  if (typeof (globalThis as any)[key] === 'undefined') {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    ;(globalThis as any)[key] = ''
  }
})

// 3. process.env 兜底
if (typeof (globalThis as any).process === 'undefined') {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  ;(globalThis as any).process = { env: { NODE_ENV: 'development' } }
} else if (typeof (globalThis as any).process.env === 'undefined') {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  ;(globalThis as any).process.env = { NODE_ENV: 'development' }
}

// 4. 兜底微信胶囊按钮/系统信息 API（修复基础库 3.15.3 在 custom 导航页
//    `Cannot read properties of null (reading 'bg')` 的运行时崩溃）。
//    根因：uni-app 框架内部读取 wx.getMenuButtonBoundingClientRect() 返回的
//    .bg 字段做布局，但部分基础库版本会返回 null，导致页面 onReady 崩溃、
//    进而无法打开后续页面（如 upload）。
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const wxRef: any = typeof wx !== 'undefined' ? wx : globalThis

function safeRect(rect: any) {
  const safe = rect && typeof rect === 'object' ? rect : {}
  return {
    width: safe.width ?? 87,
    height: safe.height ?? 32,
    top: safe.top ?? 24,
    right: safe.right ?? 320,
    left: safe.left ?? 233,
    bottom: safe.bottom ?? 56,
    // 关键：框架读取的 bg / statusBarHeight 等不能为 null
    bg: safe.bg ?? '#00000000',
    color: safe.color ?? '#000000',
  }
}

if (wxRef && typeof wxRef.getMenuButtonBoundingClientRect === 'function') {
  const orig = wxRef.getMenuButtonBoundingClientRect
  wxRef.getMenuButtonBoundingClientRect = function () {
    try {
      return safeRect(orig.call(wxRef))
    } catch (_) {
      return safeRect(null)
    }
  }
}

export {}
