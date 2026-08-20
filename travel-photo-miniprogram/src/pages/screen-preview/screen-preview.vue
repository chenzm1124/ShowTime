<template>
  <view class="page-preview">
    <!-- 顶部导航 -->
    <view class="header">
      <view class="back" @click="goBack">‹</view>
      <text class="title">筛选结果确认</text>
      <view class="placeholder"></view>
    </view>

    <view class="container">
      <!-- 进度条：筛选进行中 -->
      <view v-if="loading" class="screening-card">
        <view class="screening-title">
          <text class="dot"></text>
          <text>AI 正在为你智能筛选照片…</text>
        </view>
        <view class="progress-bar">
          <view class="progress-fill" :style="{ width: progress + '%' }"></view>
        </view>
        <text class="progress-tip">{{ progressTip }}</text>
      </view>

      <!-- 筛选结果（业务级错误不进入结果区，让错误卡片独占） -->
      <block v-else-if="preview && !preview.error">
        <!-- 概述 -->
        <view class="summary-card">
          <view class="summary-item">
            <text class="num">{{ preview.total_photos }}</text>
            <text class="label">已上传</text>
          </view>
          <view class="summary-arrow">→</view>
          <view class="summary-item">
            <text class="num">{{ preview.total_groups }}</text>
            <text class="label">相似分组</text>
          </view>
          <view class="summary-arrow">→</view>
          <view class="summary-item highlight">
            <text class="num">{{ preview.selected_count }}</text>
            <text class="label">精选保留</text>
          </view>
        </view>

        <view v-if="preview.dropped_count > 0" class="destory-tip">
          已自动去除 {{ preview.dropped_count }} 张相似/重复照片（每组仅保留质量最佳的一张），
          为你节省精修次数与等待时间。
        </view>

        <!-- 精选照片网格 -->
        <view class="section-title">
          <text>精选保留（{{ preview.selected_count }} 张）</text>
        </view>
        <view class="photo-grid">
          <view
            v-for="(p, idx) in selectedList"
            :key="p.photo_id"
            class="photo-cell"
          >
            <image
              class="photo-img"
              :src="thumbOf(p)"
              mode="aspectFill"
            />
            <view class="photo-badge">
              <text>第{{ idx + 1 }}张</text>
            </view>
            <view v-if="p.quality_score" class="score-badge">
              <text>质量 {{ Math.round(p.quality_score * 100) }}</text>
            </view>
          </view>
        </view>

        <!-- 被去重照片（可展开） -->
        <view class="dropped-wrap" v-if="preview.dropped_count > 0">
          <view class="dropped-header" @click="showDropped = !showDropped">
            <text>查看被去重的 {{ preview.dropped_count }} 张照片</text>
            <text class="chevron">{{ showDropped ? '▲' : '▼' }}</text>
          </view>
          <view v-if="showDropped" class="photo-grid dropped-grid">
            <view
              v-for="d in droppedList"
              :key="d.photo_id"
              class="photo-cell dropped"
            >
              <image
                class="photo-img"
                :src="thumbOf(d)"
                mode="aspectFill"
              />
              <view class="dropped-mask">
                <text>已去重</text>
              </view>
            </view>
          </view>
        </view>
      </block>

      <!-- 错误态 -->
      <view v-else-if="error" class="error-card">
        <text class="error-text">{{ error }}</text>
      </view>
    </view>

    <!-- 底部确认栏 -->
    <view v-if="preview && !loading" class="footer">
      <button class="btn-secondary" @click="goBack">重新选择</button>
      <button class="btn-primary" :disabled="submitting" @click="confirmRetouch">
        {{ submitting ? '创建中…' : `确认精修（${preview.selected_count} 张）` }}
      </button>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useTaskStore } from '@/stores/task'

const taskStore = useTaskStore()

const loading = ref(true)
const progress = ref(8)
const progressTip = ref('正在下载并分析照片…')
const preview = ref<any>(null)
const error = ref('')
const submitting = ref(false)
const showDropped = ref(false)

// 上传页存入的本地原图信息（index/path/url/size）
const localPhotos = ref<any[]>([])

const selectedList = computed(() => preview.value?.selected_photos || [])
const droppedList = computed(() => preview.value?.dropped_photos || [])

onMounted(() => {
  // mock 进度动画
  const timer = setInterval(() => {
    if (!loading.value) {
      clearInterval(timer)
      return
    }
    progress.value = Math.min(progress.value + Math.floor(Math.random() * 12) + 4, 90)
  }, 300)

  try {
    localPhotos.value = uni.getStorageSync('temp_upload_photos') || []
  } catch (e) {
    localPhotos.value = []
  }

  const stored = uni.getStorageSync('temp_preview_result')
  // 必须 selected_photos 非空且无 error（避免 stale 占位/错误结果被恢复）
  if (stored && stored.selected_photos && !stored.error) {
    // 若已有结果（例如从 storage 恢复），直接展示
    preview.value = stored
    loading.value = false
    progress.value = 100
    clearInterval(timer)
  } else {
    if (stored && stored.error) {
      // 恢复上次错误信息，直接展示
      error.value = stored.error
      preview.value = null
      loading.value = false
      clearInterval(timer)
    } else {
      loadPreview()
    }
  }
})

async function loadPreview() {
  try {
    const stored = uni.getStorageSync('temp_preview_result')
    if (!stored || !stored.photoUrls) {
      error.value = '未找到上传照片，请返回重新上传'
      loading.value = false
      return
    }
    const result = await taskStore.previewScreen({ photo_urls: stored.photoUrls })
    progress.value = 100
    // 业务级错误（如下载全失败 / 网络/COS 问题）：后端 200 + result.error
    if ((result as any)?.error) {
      error.value = (result as any).error
      preview.value = null
      loading.value = false
      uni.showToast({ title: error.value, icon: 'none', duration: 2500 })
      // 清理 stale storage，避免下次进入页面恢复"假成功"残留
      try { uni.removeStorageSync('temp_preview_result') } catch (_) {}
      return
    }
    // 合并原图 url 列表与选项，便于后续回传与确认提交
    preview.value = { ...result, photoUrls: stored.photoUrls, options: stored.options }
    uni.setStorageSync('temp_preview_result', preview.value)
    loading.value = false
  } catch (e: any) {
    error.value = e?.message || '筛选失败，请重试'
    preview.value = null
    loading.value = false
    try { uni.removeStorageSync('temp_preview_result') } catch (_) {}
  }
}

// 根据 photo_id（后端按上传顺序编号 "0","1"…）映射本地缩略图路径
function thumbOf(item: any): string {
  const idx = Number(item.photo_id)
  const local = localPhotos.value.find((p) => p.index === idx)
  // 本地优先用本地缩略图（更快），否则用后端返回的 original_url
  if (local && local.path) return local.path
  return item.original_url || item.thumbnail_url || ''
}

function goBack() {
  uni.navigateBack()
}

async function confirmRetouch() {
  if (submitting.value) return
  submitting.value = true
  uni.showLoading({ title: '创建任务中...' })
  try {
    // 用精选出的照片 url 顺序提交（与后端 selected 顺序一致）
    const photoUrls: string[] = selectedList.value.map((p: any) => {
      const idx = Number(p.photo_id)
      const local = localPhotos.value.find((l) => l.index === idx)
      return local?.url || p.original_url
    })
    const opts = preview.value?.options || { retouch_styles: ['auto'] }
    const taskId = await taskStore.createAndProcess({
      photo_urls: photoUrls,
      options: opts,
    })
    uni.hideLoading()
    // 跳转到精修过渡页：等所有照片精修完成后，由过渡页自动跳到结果页
    const totalUploaded = preview.value?.photoUrls?.length || photoUrls.length
    const selectedCount = preview.value?.selected_count || photoUrls.length
    uni.redirectTo({
      url: `/pages/retouching/retouching?taskId=${taskId}&total=${totalUploaded}&selected=${selectedCount}`,
    })
  } catch (e: any) {
    uni.hideLoading()
    uni.showToast({ title: e?.message || '创建失败', icon: 'none' })
    submitting.value = false
  }
}
</script>

<style lang="scss" scoped>
@import '@/uni.scss';

.page-preview {
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

.screening-card {
  background: $bg-primary;
  border-radius: $radius-lg;
  padding: $spacing-lg;
  box-shadow: $shadow-sm;

  .screening-title {
    display: flex;
    align-items: center;
    font-size: $font-size-md;
    color: $text-primary;
    font-weight: 600;

    .dot {
      width: 16rpx;
      height: 16rpx;
      border-radius: 50%;
      background: $primary;
      margin-right: $spacing-sm;
      animation: blink 1s infinite;
    }
  }
  .progress-bar {
    margin-top: $spacing-md;
    height: 16rpx;
    background: $bg-tertiary;
    border-radius: 8rpx;
    overflow: hidden;

    .progress-fill {
      height: 100%;
      background: linear-gradient(90deg, $primary-light, $primary);
      border-radius: 8rpx;
      transition: width 0.3s ease;
    }
  }
  .progress-tip {
    display: block;
    margin-top: $spacing-xs;
    font-size: $font-size-sm;
    color: $text-tertiary;
  }
}

@keyframes blink {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.3; }
}

.summary-card {
  display: flex;
  align-items: center;
  justify-content: space-around;
  background: $bg-primary;
  border-radius: $radius-lg;
  padding: $spacing-lg $spacing-md;
  box-shadow: $shadow-sm;

  .summary-item {
    display: flex;
    flex-direction: column;
    align-items: center;

    .num {
      font-size: $font-size-xxl;
      font-weight: 700;
      color: $text-primary;
    }
    .label {
      font-size: $font-size-sm;
      color: $text-tertiary;
      margin-top: 4rpx;
    }
    &.highlight .num {
      color: $primary-dark;
    }
  }
  .summary-arrow {
    font-size: $font-size-lg;
    color: $text-tertiary;
  }
}

.destory-tip {
  margin-top: $spacing-md;
  background: $primary-bg;
  color: $text-secondary;
  font-size: $font-size-sm;
  border-radius: $radius-md;
  padding: $spacing-md;
  line-height: 1.5;
}

.section-title {
  margin: $spacing-lg 0 $spacing-sm;
  font-size: $font-size-md;
  font-weight: 600;
  color: $text-primary;
}

.photo-grid {
  display: flex;
  flex-wrap: wrap;
  gap: $spacing-sm;

  .photo-cell {
    position: relative;
    width: calc((100% - #{$spacing-sm} * 2) / 3);
    height: 220rpx;
    border-radius: $radius-md;
    overflow: hidden;
    background: $bg-tertiary;

    .photo-img {
      width: 100%;
      height: 100%;
    }
    .photo-badge {
      position: absolute;
      left: 8rpx;
      bottom: 8rpx;
      background: rgba(0, 0, 0, 0.55);
      color: #fff;
      font-size: $font-size-xs;
      padding: 2rpx 10rpx;
      border-radius: 20rpx;
    }
    .score-badge {
      position: absolute;
      right: 8rpx;
      top: 8rpx;
      background: $primary;
      color: #fff;
      font-size: $font-size-xs;
      padding: 2rpx 10rpx;
      border-radius: 20rpx;
    }
    &.dropped .dropped-mask {
      position: absolute;
      inset: 0;
      display: flex;
      align-items: center;
      justify-content: center;
      background: rgba(0, 0, 0, 0.45);
      color: #fff;
      font-size: $font-size-sm;
    }
  }
}

.dropped-wrap {
  margin-top: $spacing-lg;

  .dropped-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    background: $bg-primary;
    border-radius: $radius-md;
    padding: $spacing-md;
    font-size: $font-size-sm;
    color: $text-secondary;
    box-shadow: $shadow-sm;

    .chevron {
      color: $text-tertiary;
    }
  }
  .dropped-grid {
    margin-top: $spacing-sm;
  }
}

.error-card {
  background: $bg-primary;
  border-radius: $radius-lg;
  padding: $spacing-xl;
  text-align: center;

  .error-text {
    color: $error;
    font-size: $font-size-base;
  }
}

.footer {
  position: fixed;
  left: 0;
  right: 0;
  bottom: 0;
  display: flex;
  gap: $spacing-md;
  padding: $spacing-md $spacing-lg calc(#{$spacing-md} + env(safe-area-inset-bottom));
  background: $bg-primary;
  box-shadow: 0 -2rpx 8rpx rgba(0, 0, 0, 0.06);

  .btn-secondary {
    flex: 0 0 30%;
    background: $bg-secondary;
    color: $text-secondary;
    border-radius: $radius-lg;
    font-size: $font-size-md;
  }
  .btn-primary {
    flex: 1;
    background: linear-gradient(90deg, $primary-light, $primary);
    color: #fff;
    border-radius: $radius-lg;
    font-size: $font-size-md;
    font-weight: 600;

    &[disabled] {
      opacity: 0.6;
    }
  }
}
</style>
