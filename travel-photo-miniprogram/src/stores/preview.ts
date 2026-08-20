/**
 * 预览Store - 大图预览时临时存放当前照片
 *
 * 为什么用 store 而不是直接拼 URL 参数：
 * 精修图/原图都是带签名的长 URL，拼在 navigateTo 的 url 里既不安全也易超长。
 * 这里用 store 在跳转前暂存，预览页 onLoad 时读取。
 */
import { defineStore } from 'pinia'
import { ref } from 'vue'

export interface PreviewPhoto {
  photo_id: string
  original_url: string
  processed_url: string
  thumbnail_url?: string
  retouch_style_label?: string
  quality_score?: number
}

export const usePreviewStore = defineStore('preview', () => {
  const current = ref<PreviewPhoto | null>(null)

  function setPreview(photo: PreviewPhoto) {
    current.value = photo
  }

  function clear() {
    current.value = null
  }

  return {
    current,
    setPreview,
    clear,
  }
})
