<template>
  <view class="page-caption">
    <view class="header">
      <text class="back" @click="onHomeClick">🏠</text>
      <text class="title">朋友圈文案</text>
      <view class="placeholder" />
    </view>

    <view class="container">
      <!-- 紧凑表单卡片：地点 + 风格 + 生成按钮 -->
      <view class="form-card">
        <view class="form-row">
          <text class="form-label">◎ 地点</text>
          <input
            v-model="location"
            class="form-input"
            placeholder="可选，如：XX城市·XX空间"
            placeholder-style="color: #BDC3C7"
            maxlength="30"
          />
        </view>

        <view class="form-divider" />

        <view class="form-row">
          <text class="form-label">✦ 活动名称</text>
          <input
            v-model="eventName"
            class="form-input"
            placeholder="可选，如：第6期·创业沙龙"
            placeholder-style="color: #BDC3C7"
            maxlength="30"
          />
        </view>

        <view class="form-divider" />

        <view class="form-row style-row">
          <text class="form-label">✨ 风格</text>
          <view class="style-chips">
            <view
              v-for="style in styles"
              :key="style.code"
              class="style-chip"
              :class="{
                active: selectedStyle === style.code,
                locked: styleLocked,
              }"
              @click="toggleStyle(style.code)"
            >
              <text class="chip-emoji">{{ style.emoji }}</text>
              <text class="chip-name">{{ style.name }}</text>
            </view>
          </view>
          <text v-if="styleLocked" class="style-locked-tip">已生成文案，不可改选风格</text>
        </view>

        <button
          class="btn-generate"
          :class="{ disabled: generating || !selectedStyle }"
          :disabled="generating || !selectedStyle"
          @click="onGenerate"
        >
          {{ generating ? 'AI 创作中...' : (groups.length > 0 ? '✨ 重新生成' : '✨ 生成文案') }}
        </button>
      </view>

      <!-- ===== 上方：生成结果 ===== -->
      <view v-if="groups.length > 0" class="result-section">
        <view class="result-header">
          <text class="result-title">生成结果</text>
          <text class="result-tip">点击文案可复制 · 多次点击切换</text>
        </view>

        <view
          v-for="group in groups"
          :key="group.style"
          class="group-block"
        >
          <view class="group-title">
            <text class="group-emoji">{{ group.emoji }}</text>
            <text class="group-name">{{ group.style_label }}</text>
          </view>
          <view
            v-for="item in group.captions"
            :key="item.id"
            class="caption-card"
            @click="copyCaption(item.text)"
          >
            <text class="caption-text">{{ item.text }}</text>
            <text class="caption-copy-icon">📋</text>
          </view>
        </view>
      </view>

      <!-- 空结果占位（未生成时） -->
      <view v-else class="empty-result">
        <text class="empty-icon">✨</text>
        <text class="empty-text">选择风格后点击「生成文案」</text>
        <text class="empty-sub">下方照片为精修参考图</text>
      </view>

      <!-- ===== 下方：九宫格精修照片（继承 result.vue 勾选范围） ===== -->
      <view v-if="selectedPhotos.length > 0" class="photos-section">
        <view class="photos-header">
          <text class="photos-title">精修照片</text>
          <text class="photos-tip">
            已选 {{ taskStore.selectedForDownload.size }} / {{ selectedPhotos.length }} 张
          </text>
        </view>

        <view class="photo-grid">
          <view
            v-for="(photo, idx) in selectedPhotos"
            :key="photo.photo_id"
            class="grid-item"
            :class="{ unchecked: !taskStore.selectedForDownload.has(photo.photo_id) }"
            @click="toggleSelectOnPhoto(photo)"
            @longpress="previewPhoto(photo)"
          >
            <image class="grid-image" :src="photo.processed_url" mode="aspectFill" />
            <view
              v-if="taskStore.selectedForDownload.has(photo.photo_id)"
              class="grid-check"
            >
              <text class="check-icon">✓</text>
            </view>
            <view v-else class="grid-check unchecked-check" />
            <view class="grid-rank">{{ idx + 1 }}</view>
          </view>
        </view>

        <text class="photos-hint">
          💡 点击切换勾选，点击照片中间区域查看大图
        </text>
      </view>

      <view v-else class="empty-photos">
        <text class="empty-text">暂无精修照片</text>
      </view>
    </view>

    <!-- ===== 底部 sticky：复制全部 + 一键下载 ===== -->
    <view v-if="groups.length > 0 || selectedPhotos.length > 0" class="bottom-actions">
      <view class="bottom-bar">
        <button
          v-if="allCaptionsText"
          class="btn-copy-all"
          @click="copyAllCaptions"
        >
          <text class="btn-icon">📋</text>
          <text>复制全部</text>
        </button>

        <button
          class="btn-download"
          :disabled="taskStore.selectedForDownload.size === 0"
          @click="saveSelected"
        >
          <text class="btn-icon">↓</text>
          <text>
            {{ taskStore.selectedForDownload.size > 0
              ? `下载 ${taskStore.selectedForDownload.size} 张`
              : '下载到相册' }}
          </text>
        </button>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
// 页面级 polyfill 兜底（必须在所有 import 之前）
import '@/utils/pagePolyfills'

import { computed, ref, onMounted } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import { generateCaptions, getCaptionStyles } from '@/api/caption'
import type { CaptionStyle, CaptionGroup } from '@/api/caption'
import { useTaskStore } from '@/stores/task'
import { usePreviewStore } from '@/stores/preview'
import { confirmDownload } from '@/api/photo'
import type { SelectedPhoto } from '@/api/task'

const taskStore = useTaskStore()
const previewStore = usePreviewStore()

const location = ref('')
// 活动名称：与 location 一起作为 LLM 提示词输入；可空
const eventName = ref('')
// 风格改为单选：selectedStyle 是当前选中的唯一风格 code（或空串）
const selectedStyle = ref<string>('literary')
// 风格锁定：首次生成成功后置 true，之后 toggleStyle/onGenerate 都不允许改风格
const styleLocked = ref(false)
const styles = ref<CaptionStyle[]>([])
const groups = ref<CaptionGroup[]>([])
const generating = ref(false)
const compressing = ref(false)

onLoad(() => {
  // store 已有勾选范围 → 直接用（继承 result.vue）
  // store 为空时（如直接进 caption 页），不动，由 saveSelected 兜底
})

onMounted(() => {
  loadStyles()
})

/**
 * 九宫格只展示「被勾选 / 全部精修照片」—— 沿用 result.vue 勾选范围
 *
 * 业务约定：
 * - 九宫格 = selected_photos 扁平化去重
 * - 默认全选（task store 在 setTaskResult 时已全选）
 * - 在 caption 页点击单张照片 = 切换勾选 + 可看大图
 */
const selectedPhotos = computed<SelectedPhoto[]>(() => {
  const fromSelected = taskStore.taskResult?.selected_photos || []
  const fromGroups = (taskStore.taskResult?.groups || []).flatMap((g) => g.photos || [])
  const seen = new Set<string>()
  const out: SelectedPhoto[] = []
  for (const p of [...fromSelected, ...fromGroups]) {
    const id = String(p.photo_id)
    if (!seen.has(id)) {
      seen.add(id)
      out.push(p)
    }
  }
  return out
})

/** 全部文案拼接（用于「复制全部」）*/
const allCaptionsText = computed(() => {
  const list: string[] = []
  for (const g of groups.value) {
    for (const c of g.captions) list.push(c.text)
  }
  return list.join('\n\n')
})

async function loadStyles() {
  try {
    styles.value = await getCaptionStyles()
  } catch (e) {
    styles.value = [
      { code: 'professional', name: '专业干练', description: '干练专业，简洁有力', emoji: '💼' },
      { code: 'energetic', name: '积极正能量', description: '积极向上，充满正能量', emoji: '✨' },
      { code: 'warm', name: '温暖有温度', description: '温暖真诚，有温度', emoji: '🤝' },
      { code: 'minimal', name: '简约高级', description: '极简留白，高级感十足', emoji: '○' },
      { code: 'reflective', name: '深度思考', description: '深度思考，启发共鸣', emoji: '💡' },
    ]
  }
}

function toggleStyle(code: string) {
  // 已锁定：首次生成成功后不允许改选
  if (styleLocked.value) {
    uni.showToast({ title: '已生成文案，不可改选风格', icon: 'none' })
    return
  }
  // 单选互斥：点同一个取消选中，点不同的替换
  if (selectedStyle.value === code) {
    selectedStyle.value = ''
  } else {
    selectedStyle.value = code
  }
}

/**
 * 压缩图片：远程 URL → 本地临时文件 + 压缩
 * 微信小程序 uni.compressImage 仅支持本地临时文件路径
 */
async function compressPhotos(urls: string[]): Promise<string[]> {
  if (urls.length === 0) return []
  compressing.value = true
  try {
    const compressed: string[] = []
    for (const url of urls.slice(0, 6)) {
      try {
        const dl = await new Promise<UniApp.DownloadSuccessCallbackResult>((resolve, reject) => {
          uni.downloadFile({ url, success: resolve, fail: reject })
        })
        const cp = await new Promise<string>((resolve, reject) => {
          uni.compressImage({
            src: dl.tempFilePath,
            quality: 80,
            // @ts-ignore
            compressedWidth: 1024,
            success: (res) => resolve(res.tempFilePath),
            fail: reject,
          })
        }).catch(() => dl.tempFilePath)
        compressed.push(cp)
      } catch (e) {
        console.warn('[caption] 压缩单张失败', e)
      }
    }
    return compressed
  } finally {
    compressing.value = false
  }
}

async function onGenerate() {
  if (generating.value) return
  if (selectedPhotos.value.length === 0) {
    uni.showToast({ title: '请先上传照片', icon: 'none' })
    return
  }
  if (!selectedStyle.value) {
    uni.showToast({ title: '请选择一种风格', icon: 'none' })
    return
  }

  generating.value = true
  groups.value = []
  try {
    const urls = selectedPhotos.value.map((p) => p.processed_url)
    const compressedUrls = await compressPhotos(urls)
    const finalUrls = compressedUrls.length > 0 ? compressedUrls : urls

    const result = await generateCaptions({
      photo_urls: finalUrls,
      location: location.value || undefined,
      event_name: eventName.value || undefined,
      styles: [selectedStyle.value],
      count: 3,
    })
    groups.value = result
    if (result.length === 0 || result.every((g) => g.captions.length === 0)) {
      uni.showToast({ title: '暂无文案，请重试', icon: 'none' })
    } else {
      // 首次生成成功 → 锁定风格，后续重新生成只能用同风格
      styleLocked.value = true
    }
  } catch (e: any) {
    uni.showToast({ title: e.message || '生成失败', icon: 'none' })
  } finally {
    generating.value = false
  }
}

function copyCaption(text: string) {
  uni.setClipboardData({
    data: text,
    success: () => uni.showToast({ title: '已复制', icon: 'success' }),
  })
}

function copyAllCaptions() {
  if (!allCaptionsText.value) {
    uni.showToast({ title: '暂无文案', icon: 'none' })
    return
  }
  uni.setClipboardData({
    data: allCaptionsText.value,
    success: () => uni.showToast({ title: `已复制 ${groups.value.reduce((n, g) => n + g.captions.length, 0)} 条`, icon: 'success' }),
  })
}

/**
 * 九宫格点击交互：
 * - 单击：切换勾选（带视觉反馈 + 全局同步到 result.vue）
 * - 长按：打开大图预览页（避免单击频繁跳页干扰批量勾选）
 */
function toggleSelectOnPhoto(photo: SelectedPhoto) {
  taskStore.toggleSelectForDownload(photo.photo_id)
}

function previewPhoto(photo: SelectedPhoto) {
  previewStore.setPreview({
    photo_id: photo.photo_id,
    original_url: photo.original_url,
    processed_url: photo.processed_url,
    thumbnail_url: photo.thumbnail_url,
    retouch_style_label: photo.retouch_style_label,
    quality_score: photo.quality_score,
  })
  uni.navigateTo({ url: '/pages/preview/preview' })
}

/**
 * 一键下载：按 store 中 selectedForDownload 集合
 * - 0 张 → 按钮 disabled 兜底
 * - 1+ 张 → 逐张下载+存相册，loading 实时显示进度
 */
function saveSelected() {
  const ids = taskStore.selectedForDownload
  if (ids.size === 0) {
    uni.showToast({ title: '请先勾选要下载的照片', icon: 'none' })
    return
  }
  const targetPhotos = selectedPhotos.value.filter((p) => ids.has(String(p.photo_id)))
  if (targetPhotos.length === 0) return

  uni.showLoading({ title: `下载 0/${targetPhotos.length}`, mask: true })

  let done = 0
  const tasks = targetPhotos.map((photo) => {
    return new Promise<void>((resolve) => {
      uni.downloadFile({
        url: photo.processed_url,
        success: (downloadRes) => {
          uni.saveImageToPhotosAlbum({
            filePath: downloadRes.tempFilePath,
            success: () => {
              confirmDownload(photo.photo_id).catch(() => {})
              done++
              uni.showLoading({ title: `下载 ${done}/${targetPhotos.length}`, mask: true })
              resolve()
            },
            fail: () => {
              done++
              uni.showLoading({ title: `下载 ${done}/${targetPhotos.length}`, mask: true })
              resolve()
            },
          })
        },
        fail: () => {
          done++
          uni.showLoading({ title: `下载 ${done}/${targetPhotos.length}`, mask: true })
          resolve()
        },
      })
    })
  })

  Promise.all(tasks).then(() => {
    uni.hideLoading()
    uni.showToast({
      title: `已下载 ${targetPhotos.length} 张`,
      icon: 'success',
    })
  })
}

function onHomeClick() {
  uni.showModal({
    title: '提示',
    content: '精修照片将会在精修记录页面保留3天，请及时下载保存。',
    confirmText: '确定',
    cancelText: '取消',
    success: (res) => {
      if (res.confirm) {
        uni.reLaunch({ url: '/pages/index/index' })
      }
      // res.cancel → 留在当前页，无需处理
    },
  })
}
</script>

<style lang="scss" scoped>
@import '@/uni.scss';

.page-caption {
  min-height: 100vh;
  background: $bg-secondary;
  // 给底部 sticky 操作栏留出空间
  padding-bottom: 220rpx;
}

.header {
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
    font-size: 40rpx;
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

/* ========== 紧凑表单卡片 ========== */
.form-card {
  background: $bg-primary;
  border-radius: $radius-lg;
  padding: $spacing-md;
  margin-bottom: $spacing-md;
  box-shadow: $shadow-sm;
}

.form-row {
  display: flex;
  align-items: center;
  gap: $spacing-sm;
  padding: $spacing-xs 0;
}

.form-label {
  flex-shrink: 0;
  font-size: $font-size-sm;
  color: $text-secondary;
  font-weight: 500;
  width: 100rpx;
}

.form-input {
  flex: 1;
  height: 60rpx;
  padding: 0 $spacing-sm;
  background: $bg-secondary;
  border-radius: $radius-sm;
  font-size: $font-size-md;
  color: $text-primary;
}

.form-divider {
  height: 1rpx;
  background: $border-color;
  margin: $spacing-sm 0;
}

.style-row {
  align-items: flex-start;
  flex-wrap: wrap;
}

.style-chips {
  flex: 1;
  display: flex;
  flex-wrap: wrap;
  gap: 8rpx;
}

.style-chip {
  display: flex;
  align-items: center;
  gap: 4rpx;
  padding: 6rpx 14rpx;
  background: $bg-secondary;
  border: 1rpx solid transparent;
  border-radius: 30rpx;
  transition: all 0.15s;

  &.active {
    background: rgba($primary, 0.12);
    border-color: $primary;
  }

  // 锁定后：未选中的 chip 视觉弱化 + 不可点击感
  &.locked:not(.active) {
    opacity: 0.4;
  }
  // 锁定后：选中的 chip 加锁标记
  &.locked.active {
    opacity: 0.85;
  }

  .chip-emoji {
    font-size: 22rpx;
  }

  .chip-name {
    font-size: $font-size-xs;
    color: $text-primary;
    font-weight: 500;
  }
}

.style-locked-tip {
  display: block;
  width: 100%;
  margin-top: 6rpx;
  font-size: $font-size-xs;
  color: $text-tertiary;
}

.btn-generate {
  width: 100%;
  margin-top: $spacing-sm;
  height: 80rpx;
  border-radius: 40rpx;
  background: linear-gradient(135deg, $primary 0%, $primary-dark 100%);
  color: #fff;
  font-size: $font-size-md;
  font-weight: 600;
  border: none;
  box-shadow: 0 4rpx 12rpx rgba($primary, 0.35);

  &::after { border: none; }

  &.disabled {
    opacity: 0.6;
    box-shadow: none;
  }
}

/* ========== 上方：生成结果 ========== */
.result-section {
  margin-bottom: $spacing-lg;
}

.result-header {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  margin-bottom: $spacing-sm;

  .result-title {
    font-size: $font-size-md;
    font-weight: 700;
    color: $text-primary;
  }

  .result-tip {
    font-size: $font-size-xs;
    color: $text-tertiary;
  }
}

.group-block {
  margin-bottom: $spacing-md;
}

.group-title {
  display: flex;
  align-items: center;
  gap: $spacing-xs;
  margin-bottom: $spacing-sm;
  padding: $spacing-xs $spacing-sm;
  background: rgba($primary, 0.06);
  border-radius: $radius-sm;
  border-left: 6rpx solid $primary;

  .group-emoji {
    font-size: $font-size-md;
  }

  .group-name {
    font-size: $font-size-sm;
    font-weight: 600;
    color: $primary;
  }
}

.caption-card {
  position: relative;
  padding: $spacing-md $spacing-lg;
  padding-right: 100rpx;
  background: $bg-primary;
  border-radius: $radius-md;
  margin-bottom: $spacing-sm;
  box-shadow: $shadow-sm;
  transition: all 0.15s;

  &:active {
    background: $bg-secondary;
    transform: scale(0.99);
  }

  .caption-copy-icon {
    position: absolute;
    top: 50%;
    right: $spacing-md;
    transform: translateY(-50%);
    font-size: 36rpx;
    opacity: 0.4;
  }
}

.caption-text {
  display: block;
  font-size: $font-size-md;
  color: $text-primary;
  line-height: 1.7;
}

/* 空结果占位 */
.empty-result {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: $spacing-xl $spacing-md;
  background: $bg-primary;
  border-radius: $radius-lg;
  margin-bottom: $spacing-lg;

  .empty-icon {
    font-size: 64rpx;
    margin-bottom: $spacing-sm;
  }

  .empty-text {
    font-size: $font-size-md;
    color: $text-primary;
    font-weight: 500;
    margin-bottom: 4rpx;
  }

  .empty-sub {
    font-size: $font-size-xs;
    color: $text-tertiary;
  }
}

/* ========== 下方：九宫格照片 ========== */
.photos-section {
  margin-bottom: $spacing-md;
}

.photos-header {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  margin-bottom: $spacing-sm;

  .photos-title {
    font-size: $font-size-md;
    font-weight: 700;
    color: $text-primary;
  }

  .photos-tip {
    font-size: $font-size-xs;
    color: $text-secondary;
  }
}

.photo-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8rpx;
  background: $bg-primary;
  border-radius: $radius-md;
  padding: 8rpx;
}

.grid-item {
  position: relative;
  aspect-ratio: 1;
  border-radius: $radius-sm;
  overflow: hidden;
  background: $bg-tertiary;
  transition: opacity 0.2s;

  &.unchecked {
    opacity: 0.4;
  }
}

.grid-image {
  width: 100%;
  height: 100%;
}

.grid-check {
  position: absolute;
  top: 6rpx;
  right: 6rpx;
  width: 36rpx;
  height: 36rpx;
  border-radius: 50%;
  background: linear-gradient(135deg, $primary 0%, $primary-dark 100%);
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 2rpx 6rpx rgba(0, 0, 0, 0.25);

  &.unchecked-check {
    background: rgba(0, 0, 0, 0.4);
    border: 2rpx solid #fff;
  }

  .check-icon {
    color: #fff;
    font-size: 22rpx;
    font-weight: 700;
    line-height: 1;
  }
}

.grid-rank {
  position: absolute;
  bottom: 6rpx;
  left: 6rpx;
  padding: 2rpx 8rpx;
  background: rgba(0, 0, 0, 0.6);
  color: #fff;
  font-size: $font-size-xs;
  font-weight: 600;
  border-radius: $radius-sm;
}

.photos-hint {
  display: block;
  margin-top: $spacing-sm;
  text-align: center;
  font-size: $font-size-xs;
  color: $text-tertiary;
}

.empty-photos {
  padding: $spacing-xl $spacing-md;
  background: $bg-primary;
  border-radius: $radius-lg;
  text-align: center;

  .empty-text {
    color: $text-secondary;
    font-size: $font-size-md;
  }
}

/* ========== 底部 sticky 操作栏 ========== */
.bottom-actions {
  position: fixed;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba($bg-primary, 0.96);
  backdrop-filter: blur(12rpx);
  border-top: 1rpx solid $border-color;
  z-index: 100;
  padding: $spacing-sm $spacing-md calc(#{$spacing-md} + env(safe-area-inset-bottom));
}

.bottom-bar {
  display: flex;
  align-items: center;
  gap: $spacing-sm;
}

.btn-copy-all,
.btn-download {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6rpx;
  height: 80rpx;
  border-radius: 40rpx;
  font-size: $font-size-md;
  font-weight: 600;
  border: none;
  transition: opacity 0.2s ease, transform 0.1s ease;

  &::after { border: none; }

  &:active { transform: scale(0.97); }

  .btn-icon { font-size: 28rpx; }
}

.btn-copy-all {
  flex: 0 0 auto;
  background: #fff;
  color: $primary;
  box-shadow: 0 2rpx 8rpx rgba($primary, 0.2);
  border: 1rpx solid rgba($primary, 0.4);
  padding: 0 $spacing-md;
}

.btn-download {
  flex: 1;
  background: linear-gradient(135deg, $primary 0%, $primary-dark 100%);
  color: #fff;
  box-shadow: 0 4rpx 12rpx rgba($primary, 0.35);

  &[disabled] {
    background: $bg-tertiary;
    color: $text-tertiary;
    box-shadow: none;
  }
}
</style>