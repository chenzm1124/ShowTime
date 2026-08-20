/**
 * 认证API - 微信登录
 */
import { request } from './request'

export interface LoginResult {
  token: string
  user_id: string
  openid: string
  is_new_user: boolean
  member_type: 'free' | 'vip1' | 'vip2' | 'vip3'
  member_expire_date: string | null
  trial_remaining: number
  trial_expire_date: string | null
}

/**
 * 微信登录 - 换取token
 */
export function wxLogin(code: string, deviceInfo?: any): Promise<LoginResult> {
  return request<LoginResult>({
    url: '/api/v1/auth/wx-login',
    method: 'POST',
    data: { code, device_info: deviceInfo },
    showLoading: false,
    silent: true,
  })
}

/**
 * 退出登录
 */
export function logout(): Promise<void> {
  return request<void>({
    url: '/api/v1/auth/logout',
    method: 'POST',
  })
}
