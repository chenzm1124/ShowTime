/**
 * 统一请求封装
 */
import { useUserStore } from '@/stores/user'

// 根据编译环境自动切换 BASE_URL
// - DEV 模式（npm run dev:mp-weixin）：连本机后端
// - PROD 模式（npm run build:mp-weixin）：连生产域名
// 注：uni-app 在编译期会注入 process.env.NODE_ENV
//
// 关键：必须用 127.0.0.1 而不是 localhost！
// 微信开发者工具的 webview 默认拒绝 localhost（小程序安全策略），
// 即使勾选了「不校验合法域名」也无效——localhost 根本不在「合法域名」概念里。
// 用 127.0.0.1 才能直接绕过这个限制。
const isDev = (typeof process !== 'undefined' && process.env && process.env.NODE_ENV) !== 'production'

// ⚠️ 生产环境后端地址（发布前必须替换成你的真实公网 HTTPS 域名）
// 该域名需在小程序后台「开发管理 → 开发设置 → 服务器域名」登记为 request 合法域名，
// 且必须是 HTTPS。部署后端后，只需改这一行即可。
export const PROD_BASE_URL = 'https://api.example.com'

export const BASE_URL = isDev ? 'http://127.0.0.1:8000' : PROD_BASE_URL

interface RequestOptions {
  url: string
  method?: 'GET' | 'POST' | 'PUT' | 'DELETE'
  data?: any
  header?: Record<string, string>
  showLoading?: boolean
  loadingText?: string
  silent?: boolean
}

interface ApiResponse<T = any> {
  code: number
  message: string
  data: T
}

const CODE_SUCCESS = 0
const CODE_UNAUTHORIZED = 4001
const CODE_QUOTA_EXCEEDED = 4002

let pendingRequests = 0
let loadingShown = false

export async function request<T = any>(options: RequestOptions): Promise<T> {
  const {
    url,
    method = 'GET',
    data,
    header = {},
    showLoading = false,
    loadingText = '加载中...',
    silent = false,
  } = options

  const userStore = useUserStore()

  // 拼接完整URL
  const fullUrl = url.startsWith('http') ? url : `${BASE_URL}${url}`

  // 设置请求头
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...header,
  }

  if (userStore.token) {
    headers['Authorization'] = `Bearer ${userStore.token}`
  }

  // Loading
  if (showLoading) {
    pendingRequests++
    if (!loadingShown) {
      loadingShown = true
      uni.showLoading({ title: loadingText, mask: true })
    }
  }

  try {
    const res = await new Promise<UniApp.RequestSuccessCallbackResult>(
      (resolve, reject) => {
        uni.request({
          url: fullUrl,
          method,
          data,
          header: headers,
          // 精修相关接口（preview/createTask）后端会同步跑 IQA 评分+分组，
          // 8 张照片实测 40-69s，故超时放宽到 120s，避免前端在后端返回前
          // 主动断开导致 preview failed / 任务创建失败。
          timeout: 120000,
          // 关键：声明响应为文本，避免微信开发者工具在 Network 面板
          // 对响应体做 base64 预览时误调 atob 抛 InvalidCharacterError
          // （该工具 bug 会导致异常请求未正常 settle，进而照片卡在 loading）。
          responseType: 'text',
          success: (response) => resolve(response),
          fail: (error) => reject(error),
        })
      }
    )

    // responseType:'text' 后 res.data 为字符串，需手动解析
    let body: ApiResponse<T>
    if (typeof res.data === 'string') {
      try {
        body = JSON.parse(res.data) as ApiResponse<T>
      } catch (e) {
        // 响应体非 JSON（如 502/网关错误页）：当作请求失败
        console.error('[request] 响应非 JSON', res.statusCode, res.data?.slice?.(0, 200))
        if (!silent) {
          uni.showToast({ title: '服务异常，请重试', icon: 'none' })
        }
        throw new Error('响应解析失败')
      }
    } else {
      body = res.data as ApiResponse<T>
    }

    if (body.code === CODE_SUCCESS) {
      return body.data
    }

    // Token失效
    if (body.code === CODE_UNAUTHORIZED) {
      userStore.logout()
      uni.showToast({ title: '请重新登录', icon: 'none' })
      uni.reLaunch({ url: '/pages/mine/mine' })
      throw new Error('Unauthorized')
    }

    // 额度不足
    if (body.code === CODE_QUOTA_EXCEEDED || body.code >= 4001) {
      throw new QuotaError(body.message, body.code)
    }

    if (!silent) {
      uni.showToast({ title: body.message || '请求失败', icon: 'none' })
    }
    throw new Error(body.message || 'Request failed')
  } catch (err) {
    if (err instanceof QuotaError) throw err
    if (!silent) {
      uni.showToast({ title: '网络错误', icon: 'none' })
    }
    throw err
  } finally {
    if (showLoading) {
      pendingRequests = Math.max(0, pendingRequests - 1)
      if (pendingRequests === 0 && loadingShown) {
        loadingShown = false
        uni.hideLoading()
      }
    }
  }
}

export class QuotaError extends Error {
  code: number
  constructor(message: string, code: number) {
    super(message)
    this.code = code
  }
}
