// 页面级 polyfill 兜底：修复 uni-app 3.0.0-40606 + 微信开发者工具 3.15.2 兼容性问题
// 背景：uni-app 编译出的 vendor.js 在 WAWorker 容器中访问 _global / global / process.env /
//      __route__ 等全局变量默认是 undefined。每个页面 JSContext 独立，main.ts 的 polyfills 不会
//      自动继承，因此每个"首次被加载"的页面都会触发 ReferenceError。
// 解决：在每个页面的 <script setup> 顶部 import 本模块，注入兜底字段。
// 副作用：无（覆盖已存在的字段会被忽略）

globalThis._global = globalThis._global || globalThis
globalThis.__global = globalThis.__global || globalThis
globalThis.global = globalThis.global || globalThis

const mockKeys = ['__route__', '__wxExparserNodeId__', '__wxWebviewId__']
mockKeys.forEach(function (key) {
  if (typeof globalThis[key] === 'undefined') {
    globalThis[key] = ''
  }
})

if (typeof globalThis.process === 'undefined') {
  globalThis.process = { env: { NODE_ENV: 'development' } }
} else if (typeof globalThis.process !== 'undefined' && typeof globalThis.process.env === 'undefined') {
  globalThis.process.env = { NODE_ENV: 'development' }
}

export {}
