/**
 * 照片上传工具 - 微信小程序环境
 *
 * 方案：前端获取后端预签名 PUT URL，用 wx.uploadFile 直接上传到 COS
 * 无需前端计算签名，最简单可靠
 *
 * 流程：
 * 1. 向后端获取上传目录信息（/photos/sts）
 * 2. 为每张图生成唯一 object_key
 * 3. 向后端请求该 key 的预签名 PUT URL（/photos/presign）
 * 4. 小程序用 readFile + request PUT 上传到 COS（wx.uploadFile 固定 POST 不支持 PUT）
 * 5. 返回公网可访问的图片 URL
 */

import { getUploadCredential, getPresignedUrl } from '@/api/photo'
import type { StsCredential } from '@/api/photo'

interface UploadFileItem {
  path: string
  size: number
}

interface UploadProgress {
  total: number
  uploaded: number
  failed: number
  current: string
}

interface UploadOptions {
  maxConcurrent?: number
  onProgress?: (progress: UploadProgress) => void
  onFileComplete?: (file: UploadFileItem, result: { url: string }) => void
  onFileError?: (file: UploadFileItem, error: any) => void
}

/**
 * 批量上传照片到 COS
 *
 * 稳定性修复（解决「20 张时 11 张卡 loading」）：
 * - 每张照片独立任务 + Promise.allSettled，单张失败不传染其他
 * - callback (onProgress/onFileComplete/onFileError) 包 try/catch，
 *   防止回调异常中断整批任务
 * - 不再用共享 worker + queue.shift 模式（避免 while 因异常中断导致剩余卡死）
 * - 信号量控制并发上限
 */
export async function batchUploadPhotos(
  files: UploadFileItem[],
  options: UploadOptions = {}
): Promise<Array<{ file: UploadFileItem; url: string }>> {
  const { maxConcurrent = 2, onProgress, onFileComplete, onFileError } = options

  const results: Array<{ file: UploadFileItem; url: string }> = []
  const total = files.length
  let done = 0

  // 预取一次上传凭证
  let credential: StsCredential | null = null
  try {
    credential = await getUploadCredential(total)
  } catch (e) {
    console.error('[upload] 获取上传凭证失败', e)
  }

  // 信号量：maxConcurrent 个并发上限
  let active = 0
  const waiters: Array<() => void> = []
  function acquire(): Promise<void> {
    if (active < maxConcurrent) {
      active++
      return Promise.resolve()
    }
    return new Promise<void>((resolve) => {
      waiters.push(() => {
        active++
        resolve()
      })
    })
  }
  function release(): void {
    active--
    const next = waiters.shift()
    if (next) next()
  }

  // 每张图独立任务，失败不传染
  const tasks = files.map((file) =>
    (async () => {
      await acquire()
      try {
        const result = await uploadSinglePhoto(file, credential)
        results.push({ file, url: result.url })
        try {
          onFileComplete?.(file, result)
        } catch (e) {
          console.warn('[upload] onFileComplete 回调异常', e)
        }
      } catch (err) {
        try {
          onFileError?.(file, err)
        } catch (e) {
          console.warn('[upload] onFileError 回调异常', e)
        }
      } finally {
        done++
        release()
        try {
          onProgress?.({
            total,
            uploaded: results.length,
            failed: done - results.length,
            current: file.path,
          })
        } catch (e) {
          console.warn('[upload] onProgress 回调异常', e)
        }
      }
    })(),
  )

  // allSettled：单个失败不阻断整批等待
  await Promise.allSettled(tasks)
  return results
}

/**
 * 通用 Promise 超时包装：在 timeoutMs 内未 settle 则 reject
 */
function withTimeout<T>(
  p: Promise<T>,
  timeoutMs: number,
  timeoutMsg: string,
): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    let settled = false
    const timer = setTimeout(() => {
      if (settled) return
      settled = true
      reject(new Error(timeoutMsg))
    }, timeoutMs)
    p.then(
      (v) => {
        if (settled) return
        settled = true
        clearTimeout(timer)
        resolve(v)
      },
      (e) => {
        if (settled) return
        settled = true
        clearTimeout(timer)
        reject(e)
      },
    )
  })
}

/**
 * 请求预签名 URL（带独立超时，避免 presign 挂起导致永久卡 loading）
 */
async function requestPresignedUrl(
  cred: StsCredential,
  objectKey: string,
): Promise<{ presignedUrl: string; accessUrl: string }> {
  const resp = await withTimeout(
    getPresignedUrl(objectKey),
    10_000,
    '获取预签名URL超时(10s)',
  )
  const presignedUrl = resp.presigned_url
  const accessUrl = resp.access_url
  if (!presignedUrl) throw new Error('获取预签名URL失败')
  return { presignedUrl, accessUrl }
}

/**
 * 读取本地文件为 ArrayBuffer（带独立超时）
 */
function readFileToBuffer(
  path: string,
  timeoutMs = 15_000,
): Promise<ArrayBuffer> {
  return withTimeout(
    new Promise<ArrayBuffer>((resolve, reject) => {
      uni.getFileSystemManager().readFile({
        filePath: path,
        success: (r) => resolve(r.data as ArrayBuffer),
        fail: (err) => reject(new Error(`读取文件失败: ${err?.errMsg || ''}`)),
      })
    }),
    timeoutMs,
    '读取文件超时(15s)',
  )
}

/**
 * 单张照片上传到 COS
 *
 * 稳定性修复（解决「20 张时最后一张卡 loading 几分钟」）：
 * - 微信小程序下用 uni.request PUT 直传，加显式 timeout (30s) + 失败自动重试 2 次
 * - 外层 60s 保底总超时闸门（用户明确要求）：超过 60s 仍未结束 → 强制 reject，
 *   上层 onFileError 把照片标记为 failed 并提供「点击重试」，不再永久挂起
 * - presign / readFile 各自加独立超时（10s / 15s），避免任一步骤挂起拖死并发队列
 * - 每次重试重新生成 key + 重新请求 presign + 重新读取文件，避免签名重放
 */
async function uploadSinglePhoto(
  file: UploadFileItem,
  credential?: StsCredential | null
): Promise<{ url: string }> {
  // 1. 获取上传目录信息
  let cred = credential
  if (!cred) {
    cred = await getUploadCredential(1)
  }

  // Mock 模式：模拟上传，直接返回本地路径
  if (cred.tmp_secret_id === 'mock_tmp_secret_id') {
    await new Promise((r) => setTimeout(r, 300 + Math.random() * 500))
    return { url: file.path }
  }

  // 60s 保底总超时闸门：覆盖「presign 挂起 + PUT 重试」的任意组合
  const HARD_TIMEOUT_MS = 60_000
  return withTimeout(
    doUploadWithRetry(file, cred),
    HARD_TIMEOUT_MS,
    '上传总超时(60s)',
  )
}

// #ifdef MP-WEIXIN
/**
 * 微信小程序：uni.request PUT 直传 + 重试
 */
async function doUploadWithRetry(
  file: UploadFileItem,
  cred: StsCredential,
): Promise<{ url: string }> {
  const MAX_RETRY = 2
  let lastErr: Error | null = null
  for (let attempt = 0; attempt <= MAX_RETRY; attempt++) {
    try {
      const ext = (file.path.split('.').pop() || 'jpg').toLowerCase()
      const filename = `${Date.now()}_a${attempt}_${Math.random().toString(36).slice(2, 8)}.${ext}`
      const objectKey = `${cred.upload_dir}/${filename}`

      const { presignedUrl, accessUrl } = await requestPresignedUrl(cred, objectKey)
      const data = await readFileToBuffer(file.path)
      await putToCosWithTimeout(presignedUrl, data, 30_000)
      return { url: accessUrl }
    } catch (e) {
      lastErr = e instanceof Error ? e : new Error(String(e))
      console.warn(
        `[upload] 上传失败(尝试 ${attempt + 1}/${MAX_RETRY + 1}) ${file.path}`,
        lastErr.message,
      )
      if (attempt < MAX_RETRY) {
        await new Promise((r) => setTimeout(r, 800 * (attempt + 1)))
      }
    }
  }
  throw lastErr || new Error('上传失败')
}
// #endif

// #ifndef MP-WEIXIN
/**
 * 非微信环境：保留原 uni.uploadFile POST 直传路径
 * 注意：presignedUrl / accessUrl 需在本分支内重新获取（编译后外部变量不存在）
 */
async function doUploadWithRetry(
  file: UploadFileItem,
  cred: StsCredential,
): Promise<{ url: string }> {
  const ext = (file.path.split('.').pop() || 'jpg').toLowerCase()
  const filename = `${Date.now()}_${Math.random().toString(36).slice(2, 8)}.${ext}`
  const objectKey = `${cred.upload_dir}/${filename}`
  const { presignedUrl, accessUrl } = await requestPresignedUrl(cred, objectKey)
  await new Promise<void>((resolve, reject) => {
    uni.uploadFile({
      url: presignedUrl,
      filePath: file.path,
      name: 'file',
      header: { 'Content-Type': 'image/jpeg' },
      success: (res) => {
        if (res.statusCode === 200 || res.statusCode === 204) {
          resolve()
        } else {
          console.error('[upload] COS 上传失败', res.statusCode, res.data)
          reject(new Error(`上传失败: ${res.statusCode}`))
        }
      },
      fail: (err) => {
        console.error('[upload] wx.uploadFile 失败', err)
        reject(err)
      },
    })
  })
  return { url: accessUrl }
}
// #endif

/**
 * uni.request PUT 封装：显式超时 + Promise 安全收尾
 * （保留 devtools 对 PUT + ArrayBuffer 同步异常的 try/catch 兜底）
 */
function putToCosWithTimeout(
  presignedUrl: string,
  data: ArrayBuffer,
  timeoutMs: number,
): Promise<void> {
  return new Promise((resolve, reject) => {
    let settled = false
    const ok = () => {
      if (settled) return
      settled = true
      clearTimeout(timer)
      resolve()
    }
    const fail = (e: any) => {
      if (settled) return
      settled = true
      clearTimeout(timer)
      const err: Error =
        e instanceof Error
          ? e
          : new Error(
              typeof e === 'string' ? e : e?.errMsg || JSON.stringify(e) || 'upload failed',
            )
      reject(err)
    }
    const timer = setTimeout(
      () => fail(new Error(`上传超时(${Math.round(timeoutMs / 1000)}s)`)),
      timeoutMs,
    )
    try {
      uni.request({
        url: presignedUrl,
        method: 'PUT',
        data,
        header: { 'Content-Type': 'image/jpeg' },
        timeout: timeoutMs,
        // 声明响应为文本：避免微信开发者工具在 Network 面板对 PUT 响应做
        // base64 预览时误调 atob 抛 InvalidCharacterError（coverRes 注入代码
        // 未 catch → 该异常会打断回调分发，导致此照片的 Promise 永不 settle、
        // 一直卡在 loading；且控制台报 atob 红字）。
        responseType: 'text',
        success: (res) => {
          if (res.statusCode === 200 || res.statusCode === 204) {
            ok()
          } else {
            fail(new Error(`上传失败 status=${res.statusCode}`))
          }
        },
        fail: (err) => fail(err),
      })
    } catch (e) {
      // 兜底：devtools 偶发同步抛 atob InvalidCharacterError
      fail(e)
    }
  })
}

/**
 * 选择照片
 */
export function choosePhotos(maxCount: number): Promise<UploadFileItem[]> {
  return new Promise((resolve, reject) => {
    // #ifdef MP-WEIXIN
    // chooseMedia 在真机可用，但在微信开发者工具模拟器常返回 uploadFile 无法识别的临时路径
    // 统一用 chooseImage，模拟器和真机都稳定
    uni.chooseImage({
      count: maxCount,
      sizeType: ['compressed', 'original'],
      sourceType: ['album', 'camera'],
      success: (res) => {
        const files = res.tempFilePaths.map((path, i) => ({
          path,
          size: res.tempFiles?.[i]?.size || 1024 * 1024,
        }))
        resolve(files)
      },
      fail: (err) => {
        if (err?.errMsg?.includes('cancel')) {
          resolve([])
        } else {
          reject(err)
        }
      },
    })
    // #endif
    // #ifndef MP-WEIXIN
    uni.chooseImage({
      count: maxCount,
      sizeType: ['compressed'],
      sourceType: ['album', 'camera'],
      success: (res) => {
        const files = res.tempFilePaths.map((path, i) => ({
          path,
          size: res.tempFiles?.[i]?.size || 1024 * 1024,
        }))
        resolve(files)
      },
      fail: (err) => reject(err),
    })
    // #endif
  })
}

/**
 * 压缩照片
 */
export function compressImage(path: string, quality = 80): Promise<string> {
  return new Promise((resolve, reject) => {
    uni.compressImage({
      src: path,
      quality: quality as any,
      success: (res) => resolve(res.tempFilePath),
      fail: (err) => reject(err),
    })
  })
}

/**
 * 保存图片到相册
 */
export function saveImageToAlbum(url: string): Promise<void> {
  return new Promise((resolve, reject) => {
    uni.downloadFile({
      url,
      success: (downloadRes) => {
        uni.saveImageToPhotosAlbum({
          filePath: downloadRes.tempFilePath,
          success: () => resolve(),
          fail: reject,
        })
      },
      fail: reject,
    })
  })
}
