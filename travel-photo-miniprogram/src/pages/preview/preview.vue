<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { onUnload } from '@dcloudio/uni-app'
import { usePreviewStore } from '@/stores/preview'

const previewStore = usePreviewStore()

const current = ref(previewStore.current)
const showingOriginal = ref(false)
const loadStatus = ref<'loading' | 'loaded' | 'error'>('loading')
const originalLoadStatus = ref<'loading' | 'loaded' | 'error'>('loading')

// 仅当 URL 是合法公网 http(s) 地址时才允许渲染 <image>。
// 后端偶发会把 COS key / 本地临时路径（如 wxfile://、http://tmp/xxx.jpg）当成 url 入库，
// 这类非法 URL 放进 <image src> 在微信开发者工具里会直接让页面 JS 崩溃（白屏）。
// 注意：uni-app 小程序运行时没有 Web 的 `URL` 全局构造函数，必须用纯字符串判断。
function isValidHttpUrl(u: string | null | undefined): u is string {
  if (!u) return false
  if (!u.startsWith('http://') && !u.startsWith('https://')) return false
  // 协议之后到第一个 / 之间的 host 段
  const rest = u.startsWith('http://') ? u.slice(7) : u.slice(8)
  const slash = rest.indexOf('/')
  const host = (slash >= 0 ? rest.slice(0, slash) : rest).split('?')[0].split('#')[0]
  if (!host) return false
  // 排除本地/微信临时路径（host 为 'tmp' / 'usr' / 'localhost' / '127.0.0.1'）
  const low = host.toLowerCase()
  if (low === 'tmp' || low === 'usr' || low === 'localhost' || low === '127.0.0.1') return false
  // 必须是包含 . 的域名或 IP，避免空 host / 单段名
  return low.includes('.') || /^\d{1,3}(\.\d{1,3}){3}$/.test(low)
}

const processedSrc = computed(() =>
  current.value && isValidHttpUrl(current.value.processed_url) ? current.value.processed_url! : ''
)
const originalSrc = computed(() =>
  current.value && isValidHttpUrl(current.value.original_url) ? current.value.original_url! : ''
)

function onProcessedLoad() {
  loadStatus.value = 'loaded'
}
function onProcessedError() {
  loadStatus.value = 'error'
}
function onOriginalLoad() {
  originalLoadStatus.value = 'loaded'
}
function onOriginalError() {
  originalLoadStatus.value = 'error'
}

function back() {
  uni.navigateBack()
}

// 是否缺少预览数据（store 为空）。渲染一个友好的占位页，避免开发者工具偶发 WAService
// 超时时用户看到完全空白页（页面 JS 还没跑起来就已经白屏）。
const missingData = computed(() => !current.value)

onMounted(() => {
  if (missingData.value) {
    uni.showToast({ title: '预览数据丢失，请重试', icon: 'none' })
    setTimeout(() => uni.navigateBack({ delta: 1 }), 600)
  }
})

onUnload(() => {
  previewStore.clear()
})
</script>

<template>
  <view class="preview-page" :class="{ comparing: showingOriginal }">
    <!-- 数据缺失兜底：开发者工具偶发 WAServiceMainContext 超时时，
         整个页面 JS 还没跑起来就白屏。这里渲染一个最小可见的兜底页 -->
    <view v-if="missingData" class="missing-page">
      <text class="missing-text">预览数据丢失</text>
      <view class="missing-back" @tap="back">
        <text class="missing-back-text">返回</text>
      </view>
    </view>

    <block v-else>
    <!-- 顶部栏 -->
    <view class="top-bar">
      <view class="back-btn" @tap="back">
        <text class="back-icon">‹</text>
      </view>
      <view class="top-title">查看大图</view>
      <view class="top-spacer" />
    </view>

    <!-- 图片区域 -->
    <view class="image-stage">
      <!-- 精修图 -->
      <image
        v-if="processedSrc"
        :src="processedSrc"
        class="main-image"
        mode="aspectFit"
        :class="{ hidden: showingOriginal }"
        @load="onProcessedLoad"
        @error="onProcessedError"
      />
      <!-- 原图（按住对比时显示） -->
      <image
        v-if="originalSrc"
        :src="originalSrc"
        class="main-image"
        mode="aspectFit"
        :class="{ hidden: !showingOriginal }"
        @load="onOriginalLoad"
        @error="onOriginalError"
      />

      <!-- 加载占位 -->
      <view v-if="processedSrc && loadStatus === 'loading'" class="img-placeholder">
        <view class="spinner" />
        <text class="placeholder-text">图片加载中…</text>
      </view>
      <view v-if="current && !processedSrc" class="img-placeholder">
        <text class="placeholder-text">精修图地址无效，无法预览</text>
      </view>
      <view v-if="processedSrc && loadStatus === 'error'" class="img-placeholder">
        <text class="placeholder-text">精修图加载失败</text>
      </view>

      <!-- 状态标签 -->
      <view v-if="showingOriginal" class="state-tag original-tag">原图</view>
      <view v-else class="state-tag processed-tag">精修图</view>
    </view>

    <!-- 底部信息 + 对比按钮 -->
    <view class="bottom-bar">
      <view v-if="current" class="photo-meta">
        <text v-if="current.retouch_style_label" class="meta-style">{{ current.retouch_style_label }}</text>
        <text v-if="current.quality_score != null" class="meta-score">评分 {{ current.quality_score }}</text>
      </view>
      <view
        class="compare-btn"
        @touchstart="showingOriginal = true"
        @touchend="showingOriginal = false"
        @touchcancel="showingOriginal = false"
      >
        <text class="compare-text">按住对比原图</text>
      </view>
    </view>
    </block>
  </view>
</template>

<style lang="scss" scoped>
.preview-page {
  position: fixed;
  inset: 0;
  background: #000;
  display: flex;
  flex-direction: column;
}

.missing-page {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 32rpx;
  color: #fff;
  background: #000;
}
.missing-text {
  font-size: 30rpx;
  color: #ccc;
}
.missing-back {
  padding: 16rpx 48rpx;
  border: 1rpx solid rgba(255, 255, 255, 0.4);
  border-radius: 32rpx;
}
.missing-back-text {
  font-size: 28rpx;
  color: #fff;
}

.top-bar {
  height: 88rpx;
  padding-top: env(safe-area-inset-top);
  display: flex;
  align-items: center;
  justify-content: space-between;
  color: #fff;
  background: rgba(0, 0, 0, 0.5);
}
.back-btn {
  width: 80rpx;
  height: 88rpx;
  display: flex;
  align-items: center;
  justify-content: center;
}
.back-icon {
  font-size: 56rpx;
  color: #fff;
  line-height: 1;
}
.top-title {
  font-size: 32rpx;
}
.top-spacer {
  width: 80rpx;
}

.image-stage {
  position: relative;
  flex: 1;
  /* P0 修复：微信小程序的 <image> 在 flex 容器里很容易因父容器高度坍塌（flex:1 高度不传递）
     渲染成 0×0（或非常窄），导致图片被缩成小块、剩余高度大块黑屏。这里强制给一个
     最小高度作为兜底，让 image 一定能拿到可视区域。 */
  min-height: 600rpx;
  /* 修复：去掉 flex 居中布局，改用 absolute 定位让 image 真正撑满容器。
     flex 容器 + align-items: center 会让 image 按"自身声明尺寸居中"渲染，
     width: 100% 失效，导致图片显示成约 200×130 小块、其余大面积黑屏。 */
  overflow: hidden;
  background: #000;
}
.main-image {
  /* P0 修复：原图曾因没显式 mode 走默认 scaleToFill 被严重拉伸成竖长条。
     现统一用 aspectFit + 自适应尺寸，并保证 image 不被强行撑满。
     使用 absolute 定位让 image 真正铺满 .image-stage，aspectFit 缩放原图
     到容器内（保持比例），大图就能显示成大图。 */
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  max-width: 100%;
  max-height: 100%;
  /* 兜底：mode="aspectFit" 失效时仍按原比例缩小 */
  object-fit: contain;
  transition: opacity 0.15s ease;
}
.main-image.hidden {
  opacity: 0;
}

.img-placeholder {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: #888;
}
.spinner {
  width: 56rpx;
  height: 56rpx;
  border: 4rpx solid rgba(255, 255, 255, 0.25);
  border-top-color: #fff;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
  margin-bottom: 16rpx;
}
@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
.placeholder-text {
  font-size: 26rpx;
}

.state-tag {
  position: absolute;
  /* 修复：状态标签原 top: 24rpx 在小程序右上角被开发者工具浮标/胶囊遮挡。
     下移到 96rpx（避开顶部胶囊和浮标高度），同时配合左右内边距让视觉更协调。 */
  top: 96rpx;
  right: 24rpx;
  padding: 6rpx 18rpx;
  border-radius: 24rpx;
  font-size: 24rpx;
  color: #fff;
  z-index: 10;
}
.processed-tag {
  background: rgba(0, 122, 255, 0.85);
}
.original-tag {
  background: rgba(255, 255, 255, 0.25);
}

.bottom-bar {
  padding: 24rpx 32rpx calc(24rpx + env(safe-area-inset-bottom));
  background: rgba(0, 0, 0, 0.6);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 20rpx;
}
.photo-meta {
  display: flex;
  gap: 20rpx;
  align-items: center;
}
.meta-style {
  font-size: 26rpx;
  color: #fff;
  background: rgba(255, 255, 255, 0.15);
  padding: 4rpx 16rpx;
  border-radius: 20rpx;
}
.meta-score {
  font-size: 26rpx;
  color: #ffd60a;
}
.compare-btn {
  width: 100%;
  height: 84rpx;
  border-radius: 42rpx;
  background: rgba(255, 255, 255, 0.15);
  display: flex;
  align-items: center;
  justify-content: center;
  user-select: none;
}
.compare-text {
  font-size: 30rpx;
  color: #fff;
}
</style>
