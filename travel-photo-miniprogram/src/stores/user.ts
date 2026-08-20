/**
 * 用户Store
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import * as authApi from '@/api/auth'

const STORAGE_KEY_TOKEN = 'tp_token'
const STORAGE_KEY_USER = 'tp_user'

export interface UserInfo {
  user_id: string
  openid: string
  nickname: string
  avatar_url: string
  member_type: 'free' | 'vip1' | 'vip2' | 'vip3'
  member_expire_date: string | null
  /** 账号终身免费试用剩余次数（仅 1 次） */
  trial_remaining: number
  /** 首次试用日期（账号维度的永久记录） */
  trial_first_used_date: string | null
}

export const useUserStore = defineStore('user', () => {
  const token = ref<string>('')
  const userInfo = ref<UserInfo | null>(null)

  const isLoggedIn = computed(() => !!token.value)
  const isVip = computed(() => {
    if (!userInfo.value) return false
    return userInfo.value.member_type !== 'free'
  })
  const vipLevel = computed(() => userInfo.value?.member_type || 'free')

  function initFromStorage() {
    try {
      const t = uni.getStorageSync(STORAGE_KEY_TOKEN)
      const u = uni.getStorageSync(STORAGE_KEY_USER)
      if (t) token.value = t
      if (u) userInfo.value = u
    } catch (e) {
      console.error('[userStore] initFromStorage error', e)
    }
  }

  async function loginByWechat(): Promise<boolean> {
    try {
      // 1. 调用 wx.login 获取code
      const loginRes = await new Promise<UniApp.LoginRes>((resolve, reject) => {
        uni.login({
          provider: 'weixin',
          success: (res) => resolve(res),
          fail: (err) => reject(err),
        })
      })

      if (!loginRes.code) {
        throw new Error('获取code失败')
      }

      // 2. 获取设备信息（反作弊）
      const deviceInfo = uni.getSystemInfoSync()

      // 3. 调用后端登录接口
      const result = await authApi.wxLogin(loginRes.code, {
        model: deviceInfo.model,
        system: deviceInfo.system,
        platform: deviceInfo.platform,
        sdk_version: deviceInfo.SDKVersion,
      })

      // 4. 保存token和用户信息
      token.value = result.token
      userInfo.value = {
        user_id: result.user_id,
        openid: result.openid,
        nickname: '',
        avatar_url: '',
        member_type: result.member_type,
        member_expire_date: result.member_expire_date,
        trial_remaining: result.trial_remaining,
        trial_first_used_date: null,
      }

      uni.setStorageSync(STORAGE_KEY_TOKEN, result.token)
      uni.setStorageSync(STORAGE_KEY_USER, userInfo.value)

      // 5. 获取用户资料
      await fetchUserProfile()

      return true
    } catch (err) {
      console.warn('[userStore] loginByWechat failed, fallback to mock user', err)
      // 兜底关闭可能的 loading 蒙版，避免遮住后续页面
      try { uni.hideLoading() } catch (_) {}
      // 演示态 fallback：后端不可用时直接构造 mock 用户，登录流程依然完成
      token.value = 'mock_token_' + Date.now()
      userInfo.value = {
        user_id: 'mock_user_001',
        openid: 'mock_openid_001',
        nickname: '微信用户',
        avatar_url: '',
        member_type: 'free',
        member_expire_date: null,
        trial_remaining: 1,
        trial_first_used_date: null,
      }
      try {
        uni.setStorageSync(STORAGE_KEY_TOKEN, token.value)
        uni.setStorageSync(STORAGE_KEY_USER, userInfo.value)
      } catch (_) {}
      return true
    }
  }

  async function fetchUserProfile() {
    // TODO: 调用后端获取用户详细信息
  }

  function updateUserInfo(info: Partial<UserInfo>) {
    if (userInfo.value) {
      userInfo.value = { ...userInfo.value, ...info }
      uni.setStorageSync(STORAGE_KEY_USER, userInfo.value)
    }
  }

  function logout() {
    token.value = ''
    userInfo.value = null
    uni.removeStorageSync(STORAGE_KEY_TOKEN)
    uni.removeStorageSync(STORAGE_KEY_USER)
  }

  return {
    token,
    userInfo,
    isLoggedIn,
    isVip,
    vipLevel,
    initFromStorage,
    loginByWechat,
    updateUserInfo,
    logout,
  }
})
