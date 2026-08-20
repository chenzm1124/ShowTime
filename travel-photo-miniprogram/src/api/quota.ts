/**
 * 额度管理API
 */
import { request } from './request'

export interface QuotaInfo {
  member_type: 'free' | 'vip1' | 'vip2' | 'vip3'
  /** 账号终身免费试用剩余次数（仅 1 次） */
  trial_remaining: number
  /** 首次试用日期（用于展示"已使用"状态） */
  trial_first_used_date: string | null
  /** 当日看广告解锁剩余次数（每天 2 次，次日 0 点刷新） */
  ad_unlock_remaining_today: number
  /** 广告解锁当日已观看次数（用于判断是否到达 2 次上限） */
  ad_unlock_watched_today: number
  /** 当日日期（YYYY-MM-DD），跨天时重置计数 */
  ad_unlock_date: string
  vip_expire_date: string | null
  /** VIP 当日已使用次数（vip1=3/vip2=5/vip3=7，跨天重置） */
  vip_daily_used: number
  /** VIP 当日日期（YYYY-MM-DD，跨天重置 vip_daily_used） */
  vip_daily_date: string
  current_quota: {
    photos_per_task: number
    photos_per_task_label: string
  }
  monthly_used: number
  /** 用户持有的次数包（VIP 不计在内；多个时按 expire_at 升序） */
  user_packs?: UserPackBrief[]
}

export interface UserPackBrief {
  user_pack_id: number
  pack_code: 'daily' | 'enjoy' | 'unlimited'
  pack_name: string
  remaining_tasks: number
  total_tasks: number
  /** 单次张数（购买时的快照，可能与定义不同） */
  photos_per_task: number
  /** 单次精修张数（购买时的快照） */
  max_refine_per_task: number
  /** 购买时间（ISO），按购买先后顺序消耗 */
  purchased_at: string
  /** 过期时间（ISO） */
  expire_at: string
  /** 距过期秒数（< 0 已过期，UI 不显示） */
  expire_in_seconds: number
}

export interface VipPlan {
  level: 'vip1' | 'vip2' | 'vip3'
  name: string
  price_monthly: number
  price_yearly: number
  photos_per_task: number
  /** 每日次数上限：vip1=3, vip2=5, vip3=7 */
  daily_limit: number
  features: string[]
  badge?: string
  highlight?: boolean
}

export interface QuotaPack {
  code: 'daily' | 'enjoy' | 'unlimited'
  name: string
  description: string
  /** 售价（元） */
  price: number
  original_price: number
  task_quota: number
  photos_per_task: number
  max_refine_per_task: number
  valid_days: number
  features: string[]
  badge?: string
  highlight?: boolean
}

export interface AdUnlockResult {
  unlocked_count: number
  /** 当日解锁次数（仅当日有效） */
  ad_unlock_remaining_today: number
  /** 当日解锁次数上限（固定 2） */
  ad_unlock_daily_limit: number
}

/**
 * 查询用户额度
 */
export function getQuota(): Promise<QuotaInfo> {
  return request<QuotaInfo>({
    url: '/api/v1/user/quota',
    method: 'GET',
    silent: true,
  })
}

/**
 * 广告解锁处理次数
 */
export function adUnlock(payload: {
  ad_type: string
  ad_platform: string
  watch_duration_seconds: number
  ad_callback_data: any
}): Promise<AdUnlockResult> {
  return request<AdUnlockResult>({
    url: '/api/v1/quota/ad-unlock',
    method: 'POST',
    data: payload,
  })
}

/**
 * 获取VIP套餐列表
 */
export function getVipPlans(): Promise<VipPlan[]> {
  return request<VipPlan[]>({
    url: '/api/v1/vip/plans',
    method: 'GET',
    silent: true,
  })
}

/**
 * 获取次数套餐包列表
 */
export function getQuotaPacks(): Promise<QuotaPack[]> {
  return request<QuotaPack[]>({
    url: '/api/v1/packs',
    method: 'GET',
    silent: true,
  })
}

/**
 * 购买次数包（创建订单 → 调微信支付 → 支付回调后 user_packs 自动写入）
 */
export function purchasePack(payload: {
  pack_code: 'daily' | 'enjoy' | 'unlimited'
  pay_channel?: 'wechat' | 'alipay'
}): Promise<{
  order_no: string
  pack: QuotaPack
  /** 0 元订单直接 success，已支付走 prepay_id 走微信支付 */
  pay_params?: Record<string, string>
}> {
  return request({
    url: '/api/v1/packs/purchase',
    method: 'POST',
    data: payload,
  })
}
