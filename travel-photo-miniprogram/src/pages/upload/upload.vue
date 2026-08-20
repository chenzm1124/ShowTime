<template>
  <view class="page-upload">
    <view class="header">
      <text class="back" @click="goBack">‹</text>
      <text class="title">上传照片</text>
      <text class="placeholder" />
    </view>

    <view class="container">
      <!-- 步骤提示 -->
      <view class="steps">
        <view class="step active">
          <text class="step-num">1</text>
          <text class="step-text">选择照片</text>
        </view>
        <view class="step-divider" />
        <view class="step">
          <text class="step-num">2</text>
          <text class="step-text">AI处理</text>
        </view>
        <view class="step-divider" />
        <view class="step">
          <text class="step-num">3</text>
          <text class="step-text">生成文案</text>
        </view>
      </view>

      <!-- 额度提示 -->
      <view class="quota-tip">
        <text class="tip-icon">💡</text>
        <text class="tip-text">
          本次可上传 <text class="highlight">{{ maxCount }}</text> 张照片
        </text>
      </view>

      <!-- 照片上传组件 -->
      <tp-photo-uploader
        v-model="photos"
        :max-count="maxCount"
        @uploaded="onUploaded"
      />

      <!-- 修图风格与拍摄地点 UI 已移除（默认使用 "auto" + 空地点） -->
    </view>

    <!-- 底部操作栏 -->
    <view class="footer">
      <view class="footer-info">
        <text class="info-text">已选 {{ photos.length }}/{{ maxCount }} 张</text>
        <text v-if="estimatedTime" class="info-time">预计 {{ estimatedTime }} 秒</text>
      </view>
      <button
        class="btn-primary submit-btn"
        :class="{ disabled: !canSubmit }"
        :disabled="!canSubmit"
        @click="handleSubmit"
      >
        {{ canSubmit ? '开始AI处理' : '请选择照片' }}
      </button>
    </view>
  </view>
</template>

<script setup lang="ts">
// 页面级 polyfill 兜底（必须在所有 import 之前）
import '@/utils/pagePolyfills'

import { ref, computed } from 'vue'
import { useQuotaStore } from '@/stores/quota'
import { useTaskStore } from '@/stores/task'
import type { RetouchStyle } from '@/api/task'
import TpPhotoUploader from '@/components/tp-photo-uploader/tp-photo-uploader.vue'

const quotaStore = useQuotaStore()
const taskStore = useTaskStore()

interface PhotoItem {
  path: string
  size: number
  uploading?: boolean
  failed?: boolean
  progress?: number
  url?: string
}

const photos = ref<PhotoItem[]>([])
// 默认选中"智能配风格"
const selectedStyle = ref<RetouchStyle>('auto')
const location = ref('')

const maxCount = computed(() => quotaStore.currentTaskLimit)

const canSubmit = computed(() => {
  return (
    photos.value.length > 0 &&
    photos.value.every((p) => !p.uploading && !p.failed) &&
    !!selectedStyle.value
  )
})

const estimatedTime = computed(() => {
  const n = photos.value.length
  if (n === 0) return ''
  // 估算：每张约3秒
  return Math.max(15, n * 3)
})

// 5+1 种流行修图风格（"智能配"为默认推荐项）
// 修图风格 UI 已移除，保留默认 'auto'
// 拍摄地点 UI 已移除，保留 location 默认空

function goBack() {
  uni.navigateBack()
}

function onUploaded() {
  console.log('[upload] photos uploaded', photos.value.length)
}

async function handleSubmit() {
  if (!canSubmit.value) return

  try {
    // 1. 二次校验额度
    const check = quotaStore.canProcess(photos.value.length)
    if (!check.ok) {
      uni.showModal({
        title: '提示',
        content: check.reason || '',
        showCancel: false,
      })
      return
    }

    // 2. 准备URL列表（mock 模式下 url 可能为空，fallback 到 path）
    const photoUrls = photos.value
      .filter((p) => p && p.path)
      .map((p) => p.url || p.path)

    if (photoUrls.length === 0) {
      uni.showToast({ title: '没有可处理的照片', icon: 'none' })
      return
    }

    // 2.1 把已选照片存入 storage，供预览/处理页显示真实缩略图与回传映射
    const previewData = photos.value
      .filter((p) => p && p.path)
      .map((p, i) => ({
        index: i,
        path: p.path,
        url: p.url || p.path,
        size: p.size,
      }))
    uni.setStorageSync('temp_upload_photos', previewData)

    // 2.2 调用筛选预览接口（真实执行分组+评分去重，不扣额度），
    //     把结果传给 preview 确认页，用户确认后再创建任务扣额度。
    uni.showLoading({ title: '智能筛选中...' })
    try {
      const preview = await taskStore.previewScreen({ photo_urls: photoUrls })
      uni.hideLoading()
      uni.setStorageSync('temp_preview_result', {
        ...preview,
        options: {
          retouch_styles: [selectedStyle.value],
          location: location.value || undefined,
        },
        photoUrls,
      })
      uni.redirectTo({ url: '/pages/screen-preview/screen-preview' })
    } catch (e: any) {
      uni.hideLoading()
      // 预览失败不阻断：降级为直接创建任务（保留原行为）
      console.error('[upload] preview failed, fallback to create', e)
      const taskId = await taskStore.createAndProcess({
        photo_urls: photoUrls,
        options: {
          retouch_styles: [selectedStyle.value],
          location: location.value || undefined,
        },
      })
      // 筛选预览失败降级：直接创建任务，走精修过渡页（与正常流程一致）
      uni.redirectTo({
        url: `/pages/retouching/retouching?taskId=${taskId}&total=${photoUrls.length}&selected=${photoUrls.length}`,
      })
    }
  } catch (err: any) {
    uni.hideLoading()
    console.error('[upload] handleSubmit error', err)
    // 任务失败（如筛选下载全失败）后端已返还额度 → 刷新额度展示
    quotaStore.fetchQuota().catch(() => {})
    uni.showToast({ title: err.message || '处理失败，请重试', icon: 'none' })
  }
}
</script>

<style lang="scss" scoped>
@import '@/uni.scss';

.page-upload {
  min-height: 100vh;
  padding-bottom: 200rpx;
  background: $bg-secondary;
}

.header {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 90rpx $spacing-md $spacing-md;
  background: $bg-primary;

  .back {
    width: 60rpx;
    height: 60rpx;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 48rpx;
    color: $text-primary;
  }

  .title {
    font-size: $font-size-lg;
    font-weight: 600;
    color: $text-primary;
  }

  .placeholder {
    width: 60rpx;
  }
}

.container {
  padding: $spacing-md;
}

.steps {
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: $spacing-lg;
  padding: $spacing-md;
  background: $bg-primary;
  border-radius: $radius-md;

  .step {
    display: flex;
    align-items: center;
    gap: $spacing-xs;
    opacity: 0.5;

    &.active {
      opacity: 1;

      .step-num {
        background: linear-gradient(135deg, $primary 0%, $primary-dark 100%);
        color: #fff;
      }

      .step-text {
        color: $primary;
        font-weight: 600;
      }
    }
  }

  .step-num {
    width: 40rpx;
    height: 40rpx;
    background: $bg-tertiary;
    color: $text-secondary;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: $font-size-sm;
    font-weight: 600;
  }

  .step-text {
    font-size: $font-size-sm;
    color: $text-secondary;
  }

  .step-divider {
    width: 60rpx;
    height: 2rpx;
    background: $border-color;
    margin: 0 $spacing-sm;
  }
}

.quota-tip {
  display: flex;
  align-items: center;
  gap: $spacing-xs;
  padding: $spacing-md;
  background: rgba($secondary, 0.08);
  border-radius: $radius-md;
  margin-bottom: $spacing-md;

  .tip-icon {
    font-size: $font-size-md;
  }

  .tip-text {
    flex: 1;
    font-size: $font-size-sm;
    color: $text-primary;

    .highlight {
      color: $primary;
      font-weight: 600;
    }
  }

  .tip-action {
    font-size: $font-size-sm;
    color: $primary;
    font-weight: 500;
  }
}

.retouch-style-section {
  margin-top: $spacing-lg;
  padding: $spacing-md;
  background: $bg-primary;
  border-radius: $radius-md;

  .section-label-row {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    margin-bottom: $spacing-sm;
  }

  .section-label {
    font-size: $font-size-sm;
    color: $text-primary;
    font-weight: 500;
  }

  .section-hint {
    font-size: $font-size-xs;
    color: $text-tertiary;
  }
}

.style-grid {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: $spacing-sm;
}

.style-item {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4rpx;
  padding: $spacing-sm 0;
  background: $bg-secondary;
  border-radius: $radius-sm;
  border: 2rpx solid transparent;
  transition: all 0.2s;

  &.active {
    background: rgba($primary, 0.08);
    border-color: $primary;
  }

  .style-emoji {
    font-size: 36rpx;
  }

  .style-name {
    font-size: $font-size-xs;
    color: $text-primary;
  }

  .style-badge {
    position: absolute;
    top: -6rpx;
    right: -6rpx;
    padding: 2rpx 10rpx;
    background: linear-gradient(135deg, $primary 0%, $primary-dark 100%);
    color: #fff;
    font-size: 18rpx;
    font-weight: 600;
    border-radius: 20rpx;
    line-height: 1.2;
    box-shadow: 0 2rpx 4rpx rgba(255,167,38,0.3);
  }
}

.location-section {
  margin-top: $spacing-md;
  padding: $spacing-md;
  background: $bg-primary;
  border-radius: $radius-md;

  .section-label {
    display: block;
    font-size: $font-size-sm;
    color: $text-secondary;
    margin-bottom: $spacing-sm;
  }

  .location-input {
    width: 100%;
    height: 72rpx;
    padding: 0 $spacing-md;
    background: $bg-secondary;
    border-radius: $radius-sm;
    font-size: $font-size-md;
    color: $text-primary;
  }
}

.footer {
  position: fixed;
  left: 0;
  right: 0;
  bottom: 0;
  background: $bg-primary;
  padding: $spacing-md;
  border-top: 1rpx solid $border-color;
  box-shadow: 0 -4rpx 16rpx rgba(0, 0, 0, 0.04);
  padding-bottom: calc(#{$spacing-md} + env(safe-area-inset-bottom));

  .footer-info {
    display: flex;
    justify-content: space-between;
    margin-bottom: $spacing-sm;

    .info-text {
      font-size: $font-size-sm;
      color: $text-primary;
    }

    .info-time {
      font-size: $font-size-sm;
      color: $primary;
      font-weight: 500;
    }
  }

  .submit-btn {
    width: 100%;
  }
}
</style>
