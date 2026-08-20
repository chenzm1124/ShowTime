<template>
  <view class="page-result">
    <view class="header">
      <text class="back" @click="goBack">‹</text>
      <text class="title">精修结果</text>
      <text class="placeholder" @click="goHistory">完成</text>
    </view>

    <view class="container">
      <!-- 顶部说明文案 -->
      <view class="intro-card">
        <text class="intro-text">
          从 <text class="intro-num">{{ totalUploaded }}</text> 张照片中筛选出
          <text class="intro-num">{{ selectedCount }}</text> 张，已完成精修
          <text v-if="hasSkipped">；
            其中 <text class="intro-num">{{ skippedPhotos.length }}</text> 张未入选（聚类去重）
          </text>
          ；可点击照片查看大图并对比原图。
        </text>
      </view>

      <!-- 精修失败提示 + 重试（后端降级为原图 + _retouch_failed 标记） -->
      <view v-if="hasRetouchFailed" class="retry-banner">
        <view class="retry-info">
          <text class="retry-icon">!</text>
          <text class="retry-text">{{ failedPhotos.length }} 张精修失败（已保留原图）</text>
        </view>
        <button class="retry-btn" :disabled="retrying" @click="retryRetouchHandler">
          <text>{{ retrying ? '重试中...' : '重试精修' }}</text>
        </button>
      </view>

      <!-- 分组提示 -->
      <view class="section-title">
        <text class="title-text">精修结果</text>
        <text class="title-tip">已选 {{ selectedForDownload.size }} / {{ displayPhotos.length }} 张</text>
      </view>

      <!-- 照片列表 -->
      <view class="photo-list">
        <view
          v-for="(photo, idx) in displayPhotos"
          :key="photo.photo_id"
          class="photo-row"
          :class="{ checked: selectedForDownload.has(photo.photo_id) }"
        >
          <!-- 左侧多选框：skipped 照片禁用勾选 -->
          <view
            class="checkbox"
            :class="{
              active: selectedForDownload.has(photo.photo_id),
              disabled: photo.status === 'skipped',
            }"
            @click="toggleSelect(photo.photo_id)"
          >
            <text v-if="selectedForDownload.has(photo.photo_id)" class="check-icon">✓</text>
          </view>

          <!-- 缩略图 -->
          <view class="thumb clickable" @click="previewPhoto(photo)">
            <!-- 三态图片：用 <block> 拆开 v-if/v-else-if/v-else 链，规避 uni-app
                 编译 bug "Framework inner error (expect END descriptor with depth 1
                 but get FLOW_ALLOC_NODE_ID)"，导致整页渲染层崩溃白屏。
                 P1：增加 skipped（未入选）分支，显示原图 + 未入选角标。 -->
            <block v-if="photo.status === 'failed' || isRetouchFailed(photo)">
              <image
                class="thumb-image"
                :src="photo.original_url"
                mode="aspectFill"
                @error="onImgError(photo)"
              />
            </block>
            <block v-else-if="photo.status === 'skipped'">
              <image
                class="thumb-image"
                :src="photo.original_url"
                mode="aspectFill"
                @error="onImgError(photo)"
              />
            </block>
            <block v-else>
              <image
                class="thumb-image"
                :src="photo.processed_url || photo.original_url"
                mode="aspectFill"
                @error="onImgError(photo)"
              />
            </block>
            <!-- 图片加载失败占位 -->
            <view v-if="photo._imgError" class="thumb-imgerr">
              <text class="thumb-imgerr-text">图片加载失败</text>
              <text class="thumb-imgerr-sub">请检查「不校验合法域名」设置</text>
            </view>
            <!-- 精修风格标签：仅完成态显示 -->
            <view v-if="photo.status === 'completed' && !isRetouchFailed(photo) && photo.retouch_style_label" class="thumb-style">
              {{ styleEmoji(photo.retouch_style) }} {{ photo.retouch_style_label }}
            </view>
            <!-- 精修失败角标 -->
            <view v-if="photo.status === 'failed' || isRetouchFailed(photo)" class="thumb-failed">
              <text class="thumb-failed-text">精修失败</text>
            </view>
            <!-- 未入选角标（聚类去重） -->
            <view v-if="photo.status === 'skipped'" class="thumb-skipped">
              <text class="thumb-skipped-text">未入选</text>
            </view>
          </view>

          <!-- 右侧元信息 -->
          <view class="meta clickable" @click="previewPhoto(photo)">
            <view class="meta-row1">
              <text class="meta-group">第{{ idx + 1 }}张</text>
              <text v-if="photo.status === 'failed' || isRetouchFailed(photo)" class="meta-status failed">已降级原图</text>
              <text v-else-if="photo.status === 'skipped'" class="meta-status skipped">聚类去重</text>
            </view>
            <view class="meta-row2">
              <text class="meta-tag" :class="photo.type === 'portrait' ? 'pink' : 'green'">
                {{ photo.type === 'portrait' ? '特写' : '场景' }}
              </text>
            </view>
            <text class="meta-hint">{{ photo.status === 'skipped' ? '未入选精修，无法下载' : '点击查看大图/对比原图' }}</text>
          </view>
        </view>

        <!-- 空态 -->
        <view v-if="displayPhotos.length === 0" class="empty">
          <text class="empty-text">暂无精修结果</text>
        </view>
      </view>
    </view>

    <!-- 底部 sticky 操作栏 -->
    <view class="bottom-actions">
      <view class="bottom-bar">
        <view class="select-all" @click="toggleSelectAll">
          <view class="checkbox" :class="{ active: isAllSelected }">
            <text v-if="isAllSelected" class="check-icon">✓</text>
          </view>
          <text class="select-all-text">全选</text>
        </view>

        <button
          v-if="featureGetters.caption()"
          class="btn-caption"
          @click="generateCaptions"
        >
          <text class="btn-icon">✎</text>
          <text>朋友圈文案</text>
        </button>

        <button
          class="btn-save"
          :disabled="selectedForDownload.size === 0"
          @click="saveSelected"
        >
          <text class="btn-icon">↓</text>
          <text>{{ selectedForDownload.size > 0 ? `保存 ${selectedForDownload.size} 张` : '保存到相册' }}</text>
        </button>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
// 页面级 polyfill 兜底（必须在所有 import 之前）
import '@/utils/pagePolyfills'

import { computed, ref } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import { useTaskStore } from '@/stores/task'
import { usePreviewStore } from '@/stores/preview'
import {
  getTaskResult,
  retryRetouch,
  isRetouchFailed,
  type SelectedPhoto,
  type RetouchStyle,
} from '@/api/task'
import { confirmDownload } from '@/api/photo'
import { featureGetters } from '@/utils/features'

// 列表统一展示类型：结果页只展示已完成照片（含降级失败的原图）。
// status 字段保留以兼容 retouching 页写入的 PhotoStatusItem 数据，
// 但结果页本身不再驱动精修流程。
// P1 新增 'skipped'：聚类去重未入选的照片（后端 get_task_result 会补齐），
// 显示原图 + "未入选"角标，不计入精修失败，不允许下载（无精修图可下载）。
interface DisplayPhoto {
  photo_id: string | number
  original_url: string
  processed_url?: string | null
  thumbnail_url?: string | null
  status: 'completed' | 'failed' | 'skipped'
  order_index?: number
  is_retouch_failed?: boolean
  retouch_style?: RetouchStyle
  retouch_style_label?: string
  quality_score?: number
  face_count?: number
  type?: string
  category?: string
  caption?: string
  cluster_group_id?: number
  rank_in_group?: number
  _imgError?: boolean
}

const taskStore = useTaskStore()
const previewStore = usePreviewStore()
const result = computed(() => taskStore.taskResult)

// 顶部文案参数：M=上传总张数，N=筛选后张数
const totalUploaded = ref(0)
const selectedCount = ref(0)
const currentTaskId = ref('')

// 「一键下载」勾选范围：跨页同步到 caption.vue
const selectedForDownload = computed(() => taskStore.selectedForDownload)
const isAllSelected = computed(() => {
  const list = displayPhotos.value
  return list.length > 0 && selectedForDownload.value.size === list.length
})

onLoad(async (options) => {
  totalUploaded.value = Number(options?.total) || 0
  selectedCount.value = Number(options?.selected) || 0
  const taskId = (options?.taskId || options?.task_id) as string | undefined

  if (taskId) {
    currentTaskId.value = taskId
    // 兜底：若 store 中无匹配结果（如从历史记录直接进入、或 retouching 页拉取失败），
    // 主动拉取一次完整结果。
    if (!result.value || result.value.task_id !== taskId) {
      try {
        const r = await getTaskResult(taskId)
        taskStore.setTaskResult(r)
      } catch (e) {
        // 拉取失败：保留空态，用户可返回重试
      }
    }
  }
})

// 展示列表：从 store 的完整结果中取（selected_photos + groups 去重）
// P1：保留后端补齐的 status='skipped'（未入选），不强行覆盖成 failed/completed。
const displayPhotos = computed<DisplayPhoto[]>(() => {
  const fromSelected = result.value?.selected_photos || []
  const fromGroups = (result.value?.groups || []).flatMap((g) => g.photos || [])
  const seen = new Set<string>()
  const out: DisplayPhoto[] = []
  for (const p of [...fromSelected, ...fromGroups]) {
    const id = String(p.photo_id)
    if (!seen.has(id)) {
      seen.add(id)
      // 兼容旧数据：若后端没传 status 字段，根据 _retouch_failed 标记推断
      const hasFailedFlag = isRetouchFailed(p as any)
      const rawStatus = (p as any).status as DisplayPhoto['status'] | undefined
      let status: DisplayPhoto['status']
      if (rawStatus === 'skipped') {
        status = 'skipped'
      } else if (rawStatus === 'failed') {
        status = 'failed'
      } else {
        status = hasFailedFlag ? 'failed' : 'completed'
      }
      out.push({
        ...(p as unknown as DisplayPhoto),
        status,
      })
    }
  }
  return out
})

// 精修失败检测：后端把失败照片降级为「原图 + _retouch_failed 标记」
// 注意：skipped（未入选）不算精修失败，不计入 banner
const failedPhotos = computed(() =>
  displayPhotos.value.filter((p) => p.status === 'failed' || isRetouchFailed(p)),
)
const hasRetouchFailed = computed(() => failedPhotos.value.length > 0)

// P1：未入选照片（聚类去重被丢掉的），用于文案展示
const skippedPhotos = computed(() =>
  displayPhotos.value.filter((p) => p.status === 'skipped'),
)
const hasSkipped = computed(() => skippedPhotos.value.length > 0)
const retrying = ref(false)

async function retryRetouchHandler() {
  if (!currentTaskId.value || retrying.value) return
  retrying.value = true
  try {
    const res = await retryRetouch(currentTaskId.value)
    if (res.retried === 0) {
      uni.showToast({ title: res.message || '没有需要重试的失败照片', icon: 'none' })
      return
    }
    uni.showToast({ title: `已重提交 ${res.retried} 张`, icon: 'success' })
    // 重试后重新拉取完整结果（后端会重新触发精修并更新照片状态）
    // 注意：重试是异步的，这里先刷新一次拿到「重提交中」状态，
    // 用户可手动下拉刷新或等 retouching 流程；简单起见直接重拉结果。
    const r = await getTaskResult(currentTaskId.value)
    taskStore.setTaskResult(r)
  } catch (e: any) {
    uni.showToast({ title: e?.message || '重试失败', icon: 'none' })
  } finally {
    retrying.value = false
  }
}

function toggleSelect(photoId: string | number) {
  // P1：未入选照片没有精修图，禁止勾选保存（避免误把原图当精修图保存）
  const photo = displayPhotos.value.find((p) => String(p.photo_id) === String(photoId))
  if (photo && photo.status === 'skipped') {
    uni.showToast({ title: '该照片未入选精修，无法保存', icon: 'none' })
    return
  }
  taskStore.toggleSelectForDownload(photoId)
}

function toggleSelectAll() {
  if (isAllSelected.value) {
    taskStore.clearSelectForDownload()
  } else {
    taskStore.selectAllForDownload()
  }
}

// 修图风格对应单色字符（科技像素风，无 emoji）
const styleEmojiMap: Record<RetouchStyle, string> = {
  auto:  '◉',
  hk:    '▦',
  cyber: '▩',
  soft:  '○',
  film:  '▣',
  fresh: '◌',
}
function styleEmoji(style?: RetouchStyle): string {
  return style ? (styleEmojiMap[style] || '◈') : '◈'
}

// 图片加载失败（多为小程序合法域名未放行 COS / HTTPS 校验导致）
function onImgError(photo: DisplayPhoto) {
  photo._imgError = true
}

function goBack() {
  uni.reLaunch({ url: '/pages/index/index' })
}

function goHistory() {
  uni.reLaunch({ url: '/pages/history/history' })
}

function previewPhoto(photo: DisplayPhoto) {
  // 进入自定义大图预览页：默认显示精修图，右下角「按住对比原图」按钮可查看原图
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

function generateCaptions() {
  uni.navigateTo({ url: '/pages/caption/caption' })
}

function saveSelected() {
  const ids = selectedForDownload.value
  if (ids.size === 0) {
    uni.showToast({ title: '请先选择要保存的照片', icon: 'none' })
    return
  }
  const targetPhotos = displayPhotos.value.filter((p) => ids.has(String(p.photo_id)))
  if (targetPhotos.length === 0) return

  uni.showLoading({ title: `保存 0/${targetPhotos.length}`, mask: true })

  let done = 0
  let failed = 0
  const tasks = targetPhotos.map((photo: DisplayPhoto) => {
    return new Promise<void>((resolve) => {
      uni.downloadFile({
        url: photo.processed_url || photo.original_url,
        success: (downloadRes) => {
          uni.saveImageToPhotosAlbum({
            filePath: downloadRes.tempFilePath,
            success: () => {
              confirmDownload(photo.photo_id).catch(() => {})
              done++
              uni.showLoading({ title: `保存 ${done}/${targetPhotos.length}`, mask: true })
              resolve()
            },
            fail: (err) => {
              failed++
              if (err && (String(err.errMsg || '').includes('auth deny') || String(err.errMsg || '').includes('authorize:fail'))) {
                _showAuthDenyModal()
              }
              uni.showLoading({ title: `保存 ${done}/${targetPhotos.length}`, mask: true })
              resolve()
            },
          })
        },
        fail: () => {
          failed++
          uni.showLoading({ title: `保存 ${done}/${targetPhotos.length}`, mask: true })
          resolve()
        },
      })
    })
  })

  Promise.all(tasks).then(() => {
    uni.hideLoading()
    if (failed === 0) {
      uni.showToast({ title: `已保存 ${done} 张`, icon: 'success' })
    } else if (done === 0) {
      uni.showToast({ title: `保存失败（${failed} 张）`, icon: 'none' })
    } else {
      uni.showToast({ title: `已保存 ${done} 张，失败 ${failed} 张`, icon: 'none' })
    }
  })
}

// 相册授权拒绝引导
let _hasShownAuthDenyModal = false
function _showAuthDenyModal() {
  if (_hasShownAuthDenyModal) return
  _hasShownAuthDenyModal = true
  uni.showModal({
    title: '需要相册权限',
    content: '保存精修图需要写入相册。请在设置中开启相册权限后重试。',
    confirmText: '去设置',
    cancelText: '稍后',
    success: (res) => {
      if (res.confirm) {
        uni.openSetting({})
      }
    },
  })
}
</script>

<style lang="scss" scoped>
@import '@/uni.scss';

.page-result {
  min-height: 100vh;
  background: $bg-secondary;
  padding-bottom: 200rpx;
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
    font-size: 48rpx;
    color: $text-primary;
  }

  .title {
    font-size: $font-size-lg;
    font-weight: 600;
    color: $text-primary;
  }

  .placeholder {
    width: 80rpx;
    text-align: right;
    font-size: $font-size-md;
    color: $primary;
  }
}

.container {
  padding: $spacing-md;
}

/* ========== 顶部说明文案 ========== */
.intro-card {
  background: $primary-bg;
  border: 1rpx solid rgba($primary, 0.2);
  border-radius: $radius-lg;
  padding: $spacing-md;
  margin-bottom: $spacing-md;

  .intro-text {
    font-size: $font-size-md;
    color: $text-secondary;
    line-height: 1.6;
  }

  .intro-num {
    font-weight: 700;
    color: $primary-dark;
    /* uni-app 小程序中 <text> 内嵌 <text> 不会继承父 font-size，需显式声明，否则数字渲染不出来 */
    font-size: $font-size-md;
  }
}

/* ========== 精修失败横幅 ========== */
.retry-banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: $spacing-sm;
  padding: $spacing-md;
  margin-bottom: $spacing-md;
  background: rgba(#ff7a45, 0.08);
  border: 1rpx solid rgba(#ff7a45, 0.3);
  border-radius: $radius-lg;

  .retry-info {
    display: flex;
    align-items: center;
    gap: 8rpx;
    flex: 1;
    min-width: 0;
  }

  .retry-icon {
    font-size: 32rpx;
  }

  .retry-text {
    font-size: $font-size-sm;
    color: #d4380d;
    font-weight: 500;
  }

  .retry-btn {
    flex-shrink: 0;
    height: 64rpx;
    padding: 0 $spacing-lg;
    border-radius: 32rpx;
    background: linear-gradient(135deg, #ff7a45 0%, #fa541c 100%);
    color: #fff;
    font-size: $font-size-sm;
    font-weight: 600;
    border: none;
    display: flex;
    align-items: center;
    justify-content: center;

    &::after {
      border: none;
    }

    &[disabled] {
      background: $bg-tertiary;
      color: $text-tertiary;
    }
  }
}

.section-title {
  display: flex;
  align-items: baseline;
  gap: $spacing-sm;
  margin-bottom: $spacing-md;

  .title-text {
    font-size: $font-size-lg;
    font-weight: 600;
    color: $text-primary;
  }

  .title-tip {
    font-size: $font-size-sm;
    color: $text-secondary;
  }
}

/* ========== 缩略图失败角标 ========== */
.thumb-failed {
  position: absolute;
  left: 0;
  right: 0;
  top: 0;
  bottom: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(0, 0, 0, 0.45);

  .thumb-failed-text {
    color: #fff;
    font-size: $font-size-sm;
    font-weight: 600;
    padding: 4rpx 12rpx;
    border: 1rpx solid rgba(255, 255, 255, 0.6);
    border-radius: $radius-sm;
  }
}

/* ========== 缩略图未入选角标（聚类去重） ========== */
.thumb-skipped {
  position: absolute;
  left: 0;
  right: 0;
  top: 0;
  bottom: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(0, 0, 0, 0.35);

  .thumb-skipped-text {
    color: #fff;
    font-size: $font-size-sm;
    font-weight: 600;
    padding: 4rpx 12rpx;
    border: 1rpx solid rgba(255, 255, 255, 0.6);
    border-radius: $radius-sm;
  }
}

/* ========== 缩略图竖排列表 ========== */
.photo-list {
  display: flex;
  flex-direction: column;
  gap: $spacing-sm;
}

.photo-row {
  display: flex;
  align-items: center;
  gap: $spacing-md;
  padding: $spacing-sm;
  background: $bg-primary;
  border-radius: $radius-lg;
  box-shadow: $shadow-sm;
  border: 2rpx solid transparent;
  transition: border-color 0.2s ease, background 0.2s ease;

  &.checked {
    background: rgba($primary, 0.04);
    border-color: rgba($primary, 0.25);
  }
}

.checkbox {
  flex-shrink: 0;
  width: 40rpx;
  height: 40rpx;
  border: 2rpx solid $border-color;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  background: $bg-primary;
  transition: all 0.2s ease;

  &.active {
    background: linear-gradient(135deg, $primary 0%, $primary-dark 100%);
    border-color: $primary;

    .check-icon {
      color: #fff;
      font-size: 24rpx;
      font-weight: 700;
      line-height: 1;
    }
  }

  /* P1：未入选照片复选框禁用样式（淡化 + 不可点击） */
  &.disabled {
    background: $bg-tertiary;
    border-color: $border-color;
    opacity: 0.4;
    cursor: not-allowed;
  }
}

.thumb {
  position: relative;
  flex-shrink: 0;
  width: 180rpx;
  height: 180rpx;
  border-radius: $radius-md;
  overflow: hidden;
  background: $bg-tertiary;

  &.clickable {
    cursor: pointer;
  }
}

.thumb-image {
  width: 100%;
  height: 100%;
}

.thumb-style {
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  padding: 4rpx 8rpx;
  background: linear-gradient(180deg, transparent 0%, rgba(0, 0, 0, 0.65) 100%);
  color: #fff;
  font-size: $font-size-xs;
  font-weight: 500;
  text-align: center;
  letter-spacing: 0.5rpx;
}

.thumb-imgerr {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  background: rgba(0, 0, 0, 0.55);
  gap: 6rpx;
  .thumb-imgerr-text {
    color: #ff9a9a;
    font-size: $font-size-sm;
    font-weight: 600;
  }
  .thumb-imgerr-sub {
    color: #bbb;
    font-size: $font-size-xs;
  }
}

.meta {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 8rpx;
  min-width: 0;

  &.clickable {
    cursor: pointer;
  }
}

.meta-row1 {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: $spacing-sm;
}

.meta-group {
  font-size: $font-size-md;
  font-weight: 600;
  color: $primary;
}

.meta-status {
  font-size: $font-size-xs;
  font-weight: 600;
  padding: 2rpx 10rpx;
  border-radius: $radius-sm;
  color: #fff;

  &.failed {
    background: linear-gradient(135deg, #ff7a45 0%, #fa541c 100%);
  }

  &.skipped {
    background: linear-gradient(135deg, #8c8c8c 0%, #595959 100%);
  }
}

.meta-row2 {
  display: flex;
  align-items: center;
  gap: $spacing-sm;
}

.meta-tag {
  font-size: $font-size-xs;
  font-weight: 600;
  padding: 2rpx 10rpx;
  border-radius: $radius-sm;
  color: #fff;

  &.pink {
    background: linear-gradient(135deg, $primary 0%, $primary-dark 100%);
  }

  &.green {
    background: linear-gradient(135deg, $secondary 0%, $secondary-dark 100%);
  }
}

.meta-hint {
  font-size: $font-size-xs;
  color: $text-tertiary;
  margin-top: 2rpx;
}

.empty {
  padding: $spacing-xl $spacing-md;
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

.select-all {
  display: flex;
  align-items: center;
  gap: 6rpx;
  padding: 0 4rpx;
  flex-shrink: 0;

  .checkbox {
    width: 36rpx;
    height: 36rpx;
  }

  .select-all-text {
    font-size: $font-size-sm;
    color: $text-secondary;
    font-weight: 500;
  }
}

.btn-caption,
.btn-save {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6rpx;
  height: 80rpx;
  border-radius: 40rpx;
  font-size: $font-size-md;
  font-weight: 600;
  border: none;
  padding: 0 $spacing-md;
  transition: opacity 0.2s ease, transform 0.1s ease;

  &::after {
    border: none;
  }

  &:active {
    transform: scale(0.97);
  }

  .btn-icon {
    font-size: 28rpx;
  }
}

.btn-caption {
  flex: 0 0 auto;
  background: linear-gradient(135deg, #fff 0%, #fff 100%);
  color: $primary;
  box-shadow: 0 2rpx 8rpx rgba($primary, 0.2);
  border: 1rpx solid rgba($primary, 0.4);
}

.btn-save {
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
