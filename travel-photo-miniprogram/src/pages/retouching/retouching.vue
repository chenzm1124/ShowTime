<template>
  <view class="page-retouching">
    <view class="header">
      <text class="back" @click="goBack">‹</text>
      <text class="title">精修处理中</text>
      <text class="placeholder"></text>
    </view>

    <view class="container">
      <!-- 顶部说明 -->
      <view class="intro-card">
        <view class="intro-title">
          <view class="dot"></view>
          <text>AI 正在精修你的照片…</text>
        </view>
        <text class="intro-sub">
          共 {{ totalToProcess }} 张，已完成 {{ doneCount }} 张。
          精修完成后将自动跳转到结果页，请保持页面打开。
        </text>

        <!-- 整体进度条 -->
        <view class="progress-bar">
          <view class="progress-fill" :style="{ width: progressPercent + '%' }"></view>
        </view>
        <text class="progress-tip">{{ progressTip }}</text>
      </view>

      <!-- 精修失败提示 + 重试（后端降级为原图 + _retouch_failed 标记） -->
      <view v-if="hasRetouchFailed" class="retry-banner">
        <view class="retry-info">
          <text class="retry-icon">!</text>
          <text class="retry-text">{{ failedCount }} 张精修失败（已保留原图）</text>
        </view>
        <button class="retry-btn" :disabled="retrying" @click="retryRetouchHandler">
          <text>{{ retrying ? '重试中...' : '重试精修' }}</text>
        </button>
      </view>

      <!-- 照片网格：处理中骨架 + 已完成照片混排，让用户看到「先好先显示」 -->
      <view class="section-title">
        <text class="title-text">精修进度</text>
        <text class="title-tip">{{ doneCount }} / {{ totalToProcess }} 张</text>
      </view>

      <view class="photo-grid">
        <!-- 真实照片：处理中骨架 / 已完成 / 失败 三态混排。
             注意：uni-app 编译 bug 会在 v-for 内连续的 v-if/v-else-if/v-else 链上
             触发 "Framework inner error (expect END descriptor with depth 1
             but get FLOW_ALLOC_NODE_ID)"，导致整页渲染层崩溃白屏。
             修复：用 <block> 包外层条件分支（<block> 不渲染真实节点，编译器
             不为其分配 WXML 节点 ID），彻底规避该 bug。 -->
        <view
          v-for="(photo, idx) in displayPhotos"
          :key="photo.photo_id"
          class="photo-cell"
          :class="{
            completed: photo.status === 'completed',
            failed: photo.status === 'failed',
          }"
        >
          <!-- 三态图片：用 <block> 拆开 v-if/v-else-if/v-else 链 -->
          <block v-if="photo.status === 'completed' && photo.processed_url">
            <image class="photo-img" :src="photo.processed_url" mode="aspectFill" />
          </block>
          <block v-else-if="photo.status === 'failed'">
            <image class="photo-img" :src="photo.original_url" mode="aspectFill" />
          </block>
          <block v-else>
            <image class="photo-img" :src="localThumbOf(photo)" mode="aspectFill" />
          </block>

          <!-- 序号角标 -->
          <view class="photo-badge">
            <text>第{{ idx + 1 }}张</text>
          </view>

          <!-- 状态角标：用 <block> 拆开条件链，避免触发 wxml 渲染层 bug。
               注意：原版用 v-if + v-else-if 但缺 v-else 收尾，是触发 FLOW_ALLOC_NODE_ID 的关键。 -->
          <block v-if="photo.status === 'completed'">
            <view class="status-tag done">
              <text>✓</text>
            </view>
          </block>
          <block v-else-if="photo.status === 'failed'">
            <view class="status-tag fail">
              <text>失败</text>
            </view>
          </block>

          <!-- 处理中蒙版 + loading -->
          <view v-if="photo.status !== 'completed'" class="cell-mask">
            <view class="spinner"></view>
            <text class="cell-mask-text">{{ photo.status === 'failed' ? '已降级' : '精修中' }}</text>
          </view>
        </view>

        <!-- skeleton：第一轮 status 还没回来前用骨架占位，避免空网格 -->
        <view
          v-for="i in skeletonCells"
          :key="`skeleton-${i}`"
          class="photo-cell skeleton"
        >
          <view class="cell-mask">
            <view class="spinner"></view>
            <text class="cell-mask-text">准备中</text>
          </view>
        </view>
      </view>

      <!-- 任务失败态：整任务失败（如筛选下载全失败） -->
      <view v-if="taskFailed" class="error-card">
        <text class="error-text">{{ failedMsg || '精修任务失败，请返回重试' }}</text>
        <button class="btn-retry" @click="goBack">返回重试</button>
      </view>
    </view>

    <!-- 底部操作：仅展示「取消」让用户能退出，完成后自动跳转无需手动 -->
    <view class="bottom-actions">
      <view class="bottom-bar">
        <button class="btn-cancel" @click="onCancel">取消精修</button>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
// 页面级 polyfill 兜底（必须在所有 import 之前）
import '@/utils/pagePolyfills'

import { computed, ref } from 'vue'
import { onLoad, onUnload } from '@dcloudio/uni-app'
import { useTaskStore } from '@/stores/task'
import {
  getTaskResult,
  getTaskStatus,
  retryRetouch,
  isRetouchFailed,
  type PhotoStatusItem,
  type RetouchStyle,
} from '@/api/task'
import { BASE_URL } from '@/api/request'

// 与 result.vue 一致的展示类型（精修过渡页只用 PhotoStatusItem + status）
interface DisplayPhoto {
  photo_id: string | number
  original_url: string
  processed_url?: string | null
  thumbnail_url?: string | null
  status: 'processing' | 'completed' | 'failed'
  order_index: number
  is_retouch_failed?: boolean
  retouch_style?: RetouchStyle
  retouch_style_label?: string
  quality_score?: number
}

const taskStore = useTaskStore()

const currentTaskId = ref('')
// 上传总张数 / 筛选后精修张数（来自 screen-preview 跳转参数，用于初始骨架与文案）
const totalUploaded = ref(0)
const totalToProcess = ref(0)

// 实时照片状态（WS + 轮询驱动）
const livePhotos = ref<PhotoStatusItem[]>([])
const taskFailed = ref(false)
const failedMsg = ref('')

// --- 实时推送（WebSocket）：后端每完成一张推 photo_done，全部完成推 task_completed ---
const wsConnected = ref(false)
const wsCompleted = ref(false) // 收到 task_completed 后置 true，重连可提前退出
const MAX_RECONNECT_ATTEMPTS = 6
const RECONNECT_BASE_DELAY = 1000
const RECONNECT_MAX_DELAY = 8000
let reconnectAttempts = 0
let reconnectTimer: ReturnType<typeof setTimeout> | null = null
let connectTimeoutTimer: ReturnType<typeof setTimeout> | null = null
let wsManuallyClosed = false

// 安全轮询兜底：WS 消息可能丢失，低频轮询保证最终一致性
let statusPollTimer: ReturnType<typeof setInterval> | null = null

let handlersBound = false
let wsOnMessageHandler: ((res: { data: string | ArrayBuffer }) => void) | null = null
let wsOnOpenHandler: (() => void) | null = null
let wsOnErrorHandler: (() => void) | null = null
let wsOnCloseHandler: (() => void) | null = null

// 防止完成后多次跳转
let redirected = false

function buildWsUrl(taskId: string): string {
  const base = (BASE_URL || '').replace(/^http/, 'ws')
  return `${base}/api/v1/ws/tasks/${taskId}`
}

function clearConnectTimeout() {
  if (connectTimeoutTimer) {
    clearTimeout(connectTimeoutTimer)
    connectTimeoutTimer = null
  }
}

function clearReconnectTimer() {
  if (reconnectTimer) {
    clearTimeout(reconnectTimer)
    reconnectTimer = null
  }
}

function scheduleReconnect(taskId: string) {
  if (wsManuallyClosed || wsCompleted.value) return
  if (reconnectAttempts >= MAX_RECONNECT_ATTEMPTS) {
    if (!wsCompleted.value) fallbackFetchOnce(taskId)
    return
  }
  const delay = Math.min(
    RECONNECT_BASE_DELAY * Math.pow(2, reconnectAttempts),
    RECONNECT_MAX_DELAY,
  )
  reconnectAttempts += 1
  clearReconnectTimer()
  reconnectTimer = setTimeout(() => {
    doConnectWs(taskId)
  }, delay)
}

function doConnectWs(taskId: string) {
  if (wsManuallyClosed || wsCompleted.value) return
  const url = buildWsUrl(taskId)
  clearConnectTimeout()
  connectTimeoutTimer = setTimeout(() => {
    if (!wsConnected.value && !wsCompleted.value) {
      wsConnected.value = false
      fallbackFetchOnce(taskId)
      scheduleReconnect(taskId)
    }
  }, 4000)
  try {
    uni.connectSocket({ url })
  } catch (e) {
    clearConnectTimeout()
    if (!wsCompleted.value) fallbackFetchOnce(taskId)
    scheduleReconnect(taskId)
  }
}

function applyPhotoDone(payload: any) {
  const id = String(payload.photo_id)
  const idx = livePhotos.value.findIndex((p) => String(p.photo_id) === id)
  const item: PhotoStatusItem = {
    photo_id: id,
    status: 'completed',
    original_url: payload.original_url,
    processed_url: payload.processed_url,
    thumbnail_url: payload.thumbnail_url,
    retouch_style: payload.retouch_style,
    retouch_style_label: payload.retouch_style_label,
  }
  if (idx >= 0) {
    livePhotos.value[idx] = { ...livePhotos.value[idx], ...item }
  } else {
    livePhotos.value.push(item)
  }
}

function applyTaskCompleted(payload: any) {
  const list: PhotoStatusItem[] = (payload.photos || []).map((p: any) => ({
    photo_id: String(p.photo_id),
    status: p.status === 'failed' ? 'failed' : 'completed',
    original_url: p.original_url,
    processed_url: p.processed_url,
    thumbnail_url: p.thumbnail_url,
  }))
  if (list.length) livePhotos.value = list
  wsCompleted.value = true
  // 收到总完成信号：停止一切重连与兜底
  wsConnected.value = false
  clearReconnectTimer()
  clearConnectTimeout()
  stopStatusPolling()
  reconnectAttempts = 0
  // 拉完整结果写入 store，再跳结果页
  finishAndRedirect()
}

function connectRetouchWs(taskId: string) {
  if (!taskId) return
  wsManuallyClosed = false
  reconnectAttempts = 0
  if (!handlersBound) {
    wsOnOpenHandler = () => {
      wsConnected.value = true
      reconnectAttempts = 0
      clearConnectTimeout()
      fallbackFetchOnce(taskId)
    }
    wsOnErrorHandler = () => {
      wsConnected.value = false
      clearConnectTimeout()
      if (!wsCompleted.value) fallbackFetchOnce(taskId)
      scheduleReconnect(taskId)
    }
    wsOnCloseHandler = () => {
      wsConnected.value = false
      clearConnectTimeout()
      if (!wsCompleted.value) {
        fallbackFetchOnce(taskId)
        scheduleReconnect(taskId)
      }
    }
    wsOnMessageHandler = (res) => {
      try {
        const msg = typeof res.data === 'string' ? JSON.parse(res.data) : res.data
        if (msg.type === 'photo_done') applyPhotoDone(msg)
        else if (msg.type === 'task_completed') applyTaskCompleted(msg)
      } catch (e) { /* 忽略非 JSON */ }
    }
    uni.onSocketOpen(wsOnOpenHandler)
    uni.onSocketError(wsOnErrorHandler)
    uni.onSocketClose(wsOnCloseHandler)
    uni.onSocketMessage(wsOnMessageHandler)
    handlersBound = true
  }
  doConnectWs(taskId)
}

function closeRetouchWs() {
  wsManuallyClosed = true
  clearReconnectTimer()
  clearConnectTimeout()
  stopStatusPolling()
  try { uni.closeSocket() } catch (e) { /* ignore */ }
  wsConnected.value = false
}

// 补偿拉取：仅在 WebSocket 不可用时触发一次
async function fallbackFetchOnce(taskId: string) {
  if (wsCompleted.value) return
  try {
    const st = await getTaskStatus(taskId)
    livePhotos.value = (st.photos || []).slice().sort((a, b) => a.order_index - b.order_index)
    if (st.status === 'completed' || st.status === 'failed') {
      wsCompleted.value = true
      stopStatusPolling()
      clearReconnectTimer()
      clearConnectTimeout()
      if (st.status === 'failed') {
        taskFailed.value = true
        failedMsg.value = st.error_msg || ''
      }
      finishAndRedirect()
    }
  } catch (e) {
    // 单次兜底失败：保持现状，等 WS 后续消息
  }
}

// 安全轮询兜底：周期性拉取任务状态
async function pollStatusOnce(taskId: string) {
  if (wsCompleted.value) return
  try {
    const st = await getTaskStatus(taskId)
    const list = (st.photos || []).slice().sort((a, b) => a.order_index - b.order_index)
    if (list.length) livePhotos.value = list
    if (st.status === 'completed' || st.status === 'failed') {
      wsCompleted.value = true
      stopStatusPolling()
      clearReconnectTimer()
      clearConnectTimeout()
      if (st.status === 'failed') {
        taskFailed.value = true
        failedMsg.value = st.error_msg || ''
      }
      finishAndRedirect()
    }
  } catch (e) {
    // 拉取失败：保持现状，下一轮重试
  }
}

function startStatusPolling(taskId: string) {
  if (!taskId) return
  stopStatusPolling()
  statusPollTimer = setInterval(() => {
    if (wsCompleted.value) {
      stopStatusPolling()
      return
    }
    pollStatusOnce(taskId)
  }, 3000)
}

function stopStatusPolling() {
  if (statusPollTimer) {
    clearInterval(statusPollTimer)
    statusPollTimer = null
  }
}

// 全部完成 → 拉完整结果 → redirectTo 结果页
async function finishAndRedirect() {
  if (redirected) return
  redirected = true
  closeRetouchWs()
  try {
    const r = await getTaskResult(currentTaskId.value)
    taskStore.setTaskResult(r)
  } catch (e) {
    // 拉结果失败：仍跳结果页，由结果页兜底显示空态
  }
  // 用 redirectTo 替换当前页，避免返回键回到精修页
  uni.redirectTo({
    url: `/pages/result/result?taskId=${currentTaskId.value}&total=${totalUploaded.value}&selected=${totalToProcess.value}`,
  })
}

// 展示列表：livePhotos（按 order_index 排序）
const displayPhotos = computed<DisplayPhoto[]>(() => {
  return livePhotos.value.slice().sort((a, b) => a.order_index - b.order_index) as DisplayPhoto[]
})

const doneCount = computed(() =>
  displayPhotos.value.filter((p) => p.status === 'completed').length,
)
const failedCount = computed(() =>
  displayPhotos.value.filter((p) => p.status === 'failed' || isRetouchFailed(p)).length,
)
const hasRetouchFailed = computed(() => failedCount.value > 0)
const retrying = ref(false)

const progressPercent = computed(() => {
  const total = totalToProcess.value || displayPhotos.value.length || 1
  const done = doneCount.value
  return Math.min(100, Math.round((done / total) * 100))
})

const progressTip = computed(() => {
  if (taskFailed.value) return '精修任务失败'
  if (wsCompleted.value) return '精修完成，正在跳转…'
  if (doneCount.value === 0) return '正在上传并启动精修…'
  if (doneCount.value < totalToProcess.value) {
    return `已完成 ${doneCount.value} / ${totalToProcess.value} 张，继续中…`
  }
  return '即将跳转到结果页…'
})

// 第一轮 status 还没回来前的骨架占位格数
const skeletonCells = computed(() => {
  // 已有真实数据后不再显示骨架
  if (displayPhotos.value.length > 0) return 0
  const n = totalToProcess.value || totalUploaded.value || 3
  return Math.max(1, Math.min(n, 12))
})

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
    // 重置完成标记，重新进入精修等待
    wsCompleted.value = false
    taskFailed.value = false
    redirected = false
    if (!wsConnected.value) {
      connectRetouchWs(currentTaskId.value)
    }
    startStatusPolling(currentTaskId.value)
    await fallbackFetchOnce(currentTaskId.value)
  } catch (e: any) {
    uni.showToast({ title: e?.message || '重试失败', icon: 'none' })
  } finally {
    retrying.value = false
  }
}

// 本地原图缩略图（处理中占位用），优先用上传页暂存的本地路径
function localThumbOf(photo: DisplayPhoto): string {
  const localPhotos = uni.getStorageSync('temp_upload_photos') || []
  const idx = Number(photo.order_index ?? photo.photo_id)
  const local = localPhotos.find((p: any) => p.index === idx)
  return local?.path || photo.original_url || photo.thumbnail_url || ''
}

function goBack() {
  uni.navigateBack()
}

function onCancel() {
  uni.showModal({
    title: '取消精修',
    content: '取消后已精修的照片不会保存，确定要取消吗？',
    confirmText: '确定取消',
    cancelText: '继续等待',
    success: (res) => {
      if (res.confirm) {
        goBack()
      }
    },
  })
}

onLoad((options) => {
  totalUploaded.value = Number(options?.total) || 0
  totalToProcess.value = Number(options?.selected) || 0
  const taskId = (options?.taskId || options?.task_id) as string | undefined
  if (!taskId) {
    uni.showToast({ title: '任务参数缺失', icon: 'none' })
    setTimeout(() => goBack(), 800)
    return
  }
  currentTaskId.value = taskId
  connectRetouchWs(taskId)
  startStatusPolling(taskId)
})

onUnload(() => {
  closeRetouchWs()
})
</script>

<style lang="scss" scoped>
@import '@/uni.scss';

.page-retouching {
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
    width: 60rpx;
  }
}

.container {
  padding: $spacing-md;
}

/* ========== 顶部说明 + 进度 ========== */
.intro-card {
  background: $primary-bg;
  border: 1rpx solid rgba($primary, 0.2);
  border-radius: $radius-lg;
  padding: $spacing-md;
  margin-bottom: $spacing-md;

  .intro-title {
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

  .intro-sub {
    display: block;
    margin-top: $spacing-xs;
    font-size: $font-size-sm;
    color: $text-secondary;
    line-height: 1.5;
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
      transition: width 0.4s ease;
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

/* ========== 照片网格 ========== */
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

    .status-tag {
      position: absolute;
      right: 8rpx;
      top: 8rpx;
      padding: 2rpx 10rpx;
      border-radius: 20rpx;
      font-size: $font-size-xs;
      font-weight: 600;
      color: #fff;

      &.done {
        background: $primary;
      }
      &.fail {
        background: linear-gradient(135deg, #ff7a45 0%, #fa541c 100%);
      }
    }

    .cell-mask {
      position: absolute;
      inset: 0;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      background: rgba(0, 0, 0, 0.5);
      gap: 8rpx;

      .spinner {
        width: 44rpx;
        height: 44rpx;
        border: 4rpx solid rgba(255, 255, 255, 0.3);
        border-top-color: #fff;
        border-radius: 50%;
        animation: spin 0.8s linear infinite;
      }

      .cell-mask-text {
        color: #fff;
        font-size: $font-size-xs;
      }
    }

    &.completed .cell-mask {
      display: none;
    }

    &.skeleton {
      background: $bg-tertiary;
    }
  }
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* ========== 失败态卡片 ========== */
.error-card {
  margin-top: $spacing-lg;
  background: $bg-primary;
  border-radius: $radius-lg;
  padding: $spacing-xl;
  text-align: center;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: $spacing-md;

  .error-text {
    color: $error;
    font-size: $font-size-base;
  }

  .btn-retry {
    background: $primary;
    color: #fff;
    border-radius: $radius-lg;
    font-size: $font-size-md;
    padding: 0 $spacing-lg;
    height: 72rpx;
    display: flex;
    align-items: center;
    justify-content: center;
    border: none;

    &::after {
      border: none;
    }
  }
}

/* ========== 底部操作栏 ========== */
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

.btn-cancel {
  flex: 1;
  height: 80rpx;
  border-radius: 40rpx;
  background: $bg-secondary;
  color: $text-secondary;
  font-size: $font-size-md;
  font-weight: 500;
  border: 1rpx solid $border-color;
  display: flex;
  align-items: center;
  justify-content: center;

  &::after {
    border: none;
  }
}
</style>
