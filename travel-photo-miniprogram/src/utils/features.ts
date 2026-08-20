/**
 * 功能特性开关（集中管理）
 *
 * 用途：开发期集中屏蔽/启用某条产品线，避免在每个页面里散落硬编码。
 *
 * 当前策略：所有开关 hardcode false（开发期集中精力做主流程）。
 *
 * ⚠️ 重要：不要用 import.meta.env 读取环境变量！
 *    uni-app 的 Vite 插件在小程序平台下处理 import.meta.env 时，
 *    会导致一些 chunk（如 common/getservice.js）提前 require process.env
 *    而触发 "getRootFactory Not Define Env Error" 编译错误。
 *
 * 后续要开放某条产品线时：
 *   1) 改下面硬编码的常量（true = 启用，false = 屏蔽）
 *   2) 重新 npm run dev:mp-weixin
 *   3) 微信开发者工具 Ctrl+B 重新编译
 */

// ============== 硬编码开关（开发期按需修改） ==============
const FLAG_VIP = false        // 包月会员（VIP 月卡）体系：已下线，仅保留次数套餐包
const FLAG_PACK = true        // 次数套餐包：当前唯一商业化功能，保留并展示
const FLAG_VIP_ORDERS = false // VIP 订单（属包月体系）随 VIP 一起下线
const FLAG_CAPTION = true
const FLAG_HISTORY_SHORTCUT = true  // 历史 tabBar 页面，保留

// 统一导出（保留类型，方便外部按 key 引用）
export const FEATURE_FLAGS = {
  ENABLE_VIP: FLAG_VIP,
  ENABLE_PACK: FLAG_PACK,
  ENABLE_VIP_ORDERS: FLAG_VIP_ORDERS,
  ENABLE_CAPTION: FLAG_CAPTION,
  ENABLE_HISTORY_SHORTCUT: FLAG_HISTORY_SHORTCUT,
} as const

export type FeatureKey = keyof typeof FEATURE_FLAGS

/** 动态覆盖（仅 dev 工具调用，生产构建时仍取 FEATURE_FLAGS） */
const _runtimeOverrides: Partial<Record<FeatureKey, boolean>> = {}
export function setFeature(key: FeatureKey, value: boolean): void {
  _runtimeOverrides[key] = value
}

export function isFeatureEnabled(key: FeatureKey): boolean {
  if (key in _runtimeOverrides) return _runtimeOverrides[key]!
  return FEATURE_FLAGS[key]
}

/** 用于 vue 模板：v-if="feat.vip()" */
export const featureGetters = {
  vip: (): boolean => isFeatureEnabled('ENABLE_VIP'),
  pack: (): boolean => isFeatureEnabled('ENABLE_PACK'),
  vipOrders: (): boolean => isFeatureEnabled('ENABLE_VIP_ORDERS'),
  caption: (): boolean => isFeatureEnabled('ENABLE_CAPTION'),
  historyShortcut: (): boolean => isFeatureEnabled('ENABLE_HISTORY_SHORTCUT'),
}
