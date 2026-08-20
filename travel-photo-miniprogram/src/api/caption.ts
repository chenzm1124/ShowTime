/**
 * 文案生成API
 *
 * 业务约定（2026-07 调整）：
 * - 一次请求最多 2 种风格，每风格 3 条文案
 * - 不消耗套餐次数（鼓励分享）
 */
import { request } from './request'

export interface CaptionStyle {
  code: 'literary' | 'humor' | 'minimal' | 'emotional' | 'checkin'
  name: string
  description: string
  emoji?: string
}

export interface GenerateCaptionPayload {
  photo_urls: string[]
  location?: string
  /** 活动名称（可选），与 location 一起作为提示词传入 LLM */
  event_name?: string
  /** 1~2 种风格 */
  styles: string[]
  /** 每风格生成条数，默认 3 */
  count?: number
}

export interface GeneratedCaption {
  id: string
  text: string
  style: string
  style_label: string
  emoji: string
}

/** 按风格分组的生成结果 */
export interface CaptionGroup {
  style: string
  style_label: string
  emoji: string
  captions: GeneratedCaption[]
}

/**
 * 生成文案（多风格，按风格分组返回）
 */
export function generateCaptions(
  payload: GenerateCaptionPayload
): Promise<CaptionGroup[]> {
  return request<CaptionGroup[]>({
    url: '/api/v1/captions/generate',
    method: 'POST',
    data: payload,
    showLoading: true,
    loadingText: 'AI创作中...',
  })
}

/**
 * 获取文案风格列表
 */
export function getCaptionStyles(): Promise<CaptionStyle[]> {
  return request<CaptionStyle[]>({
    url: '/api/v1/captions/styles',
    method: 'GET',
  })
}
