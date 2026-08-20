<template>
  <view class="page-history">
    <!-- tabBar 页面：无独立 header，顶部安全留白 -->
    <view class="header-tabbar-spacer" />

    <view class="container">
      <!-- 空状态 -->
      <view v-if="!loading && historyList.length === 0" class="empty">
        <text class="empty-icon">▢</text>
        <text class="empty-title">还没有处理记录</text>
        <text class="empty-subtitle">处理后的照片会在这里保存</text>
        <button class="btn-primary empty-btn" @click="goIndex">去处理照片</button>
      </view>

      <!-- 列表 -->
      <view v-else class="history-list">
        <view
          v-for="row in itemRows"
          :key="row.item.task_id"
          class="history-item"
          @click="onItemClick(row.item)"
        >
          <!-- 1. 顶部时间 + 状态 -->
          <view class="item-header">
            <text class="item-time">{{ formatTime(row.item.created_at) }}</text>
            <text class="item-status done">已完成</text>
          </view>

          <!-- 2. 数据统计（突出显示） -->
          <view class="item-stats">
            <view class="stat-block">
              <text class="stat-num">{{ row.item.total_photos }}</text>
              <text class="stat-label">上传</text>
            </view>
            <text class="stat-divider">·</text>
            <view class="stat-block highlight">
              <text class="stat-num">{{ row.item.selected_photos.length }}</text>
              <text class="stat-label">精修</text>
            </view>
            <text class="stat-unit">张</text>
          </view>

      <!-- 3. 朋友圈文案（文案功能启用时显示） -->
      <view v-if="featureGetters.caption()" class="item-caption">
        <text class="caption-text">"{{ row.item.caption || generateDemoCaption(row.item) }}"</text>
      </view>

          <!-- 4. 九宫格照片（拆成两个独立 v-for，避免 template v-for + v-if 的 uni-app 编译 bug） -->
          <view class="item-photos">
            <image
              v-for="(cell, idx) in row.photos"
              :key="'p-' + row.item.task_id + '-' + idx"
              class="item-photo"
              :src="cell.url"
              mode="aspectFill"
            />
            <view
              v-for="(cell, idx) in row.stacks"
              :key="'s-' + row.item.task_id + '-' + idx"
              class="item-photo-stack"
            >
              <image
                v-if="cell.previewUrl"
                class="stack-bg"
                :src="cell.previewUrl"
                mode="aspectFill"
              />
              <view class="stack-num">+{{ cell.count }}</view>
            </view>
          </view>
        </view>
      </view>
    </view>

    <!-- 底部 tabBar 安全区 -->
    <view class="tabbar-safe" />
  </view>
</template>

<script setup lang="ts">
// 页面级 polyfill 兜底（必须在所有 import 之前）
import '@/utils/pagePolyfills'

import { ref, computed, onMounted } from 'vue'
import { formatRelativeTime } from '@/utils/format'
import { featureGetters } from '@/utils/features'
import { getHistory, getTaskResult } from '@/api/task'
import type { TaskResult } from '@/api/task'
import { useTaskStore } from '@/stores/task'

const historyList = ref<TaskResult[]>([])
const loading = ref(false)

/**
 * 派生行：把 historyList 每一项的九宫格预算为 photos / stacks 两个独立数组
 * 避免 template v-for + v-if/v-else-if 在 uni-app 编译时的
 * "Framework inner error (expect END descriptor with depth 1 but get FLOW_ALLOC_NODE_ID)" bug
 */
type PhotoCell = { type: 'photo'; url: string }
type StackCell = { type: 'stack'; count: number; previewUrl?: string }
type ItemRow = { item: TaskResult; photos: PhotoCell[]; stacks: StackCell[] }

function buildRows(items: TaskResult[]): ItemRow[] {
  return items.map((item) => {
    const cells = getPhotoGrid(item)
    return {
      item,
      photos: cells.filter((c): c is PhotoCell => c.type === 'photo'),
      stacks: cells.filter((c): c is StackCell => c.type === 'stack'),
    }
  })
}

const itemRows = computed(() => buildRows(historyList.value))

onMounted(() => {
  loadHistory()
})

async function loadHistory() {
  loading.value = true
  try {
    const res = await getHistory(1, 20)
    const items = res.list || []
    // P1-2 修复：原 for 循环串行 N+1 → 改为 Promise.all 并发
    // 20 条历史从 20×RT（约 6s）降到 max(RT)（约 0.3s）
    const settled = await Promise.allSettled(
      items.map((item: any) => getTaskResult(item.task_id))
    )
    const results: TaskResult[] = []
    settled.forEach((sr, idx) => {
      if (sr.status === 'rejected') {
        console.warn('[history] 获取任务结果失败:', items[idx].task_id, sr.reason)
        return
      }
      const result = sr.value
      // 用第一张精修照片的文案作为任务级文案
      if (!result.caption && result.selected_photos?.length > 0) {
        ;(result as any).caption = result.selected_photos[0].caption || ''
      }
      results.push(result)
    })
    historyList.value = results
  } catch (e) {
    console.error('[history] loadHistory error', e)
    historyList.value = []
  } finally {
    loading.value = false
  }
}

/**
 * 生成九宫格数据
 * 规则：
 *  - 精修 1-8 张：前 N 格放精修图，第 N+1 格叠放剩余（未精修）图
 *  - 精修 ≥ 9 张：前 9 格放精修图，第 9 格下方叠放剩余精修 + 未精修
 *  - 精修 0 张：第 1 格叠放全部未精修图
 */
type GridCell =
  | { type: 'photo'; url: string }
  | { type: 'stack'; count: number; previewUrl?: string }

function getPhotoGrid(item: TaskResult): GridCell[] {
  const selected = item.selected_photos || []
  // 推算"未精修"图：原始 total_photos - 精修 selected_photos
  // 但 mock 数据没有保留原始列表，这里用"未精修数 = total_photos - selected_photos.length"估算
  const unretouchedCount = Math.max(0, item.total_photos - selected.length)

  const cells: GridCell[] = []

  if (selected.length === 0) {
    // 情况 3：无精修，第 1 格叠放全部未精修
    cells.push({ type: 'stack', count: unretouchedCount })
    return cells
  }

  if (selected.length >= 9) {
    // 情况 1：精修 ≥9 张，前 8 张放精修，第 9 格叠放剩余精修+未精修
    for (let i = 0; i < 8; i++) {
      cells.push({ type: 'photo', url: selected[i].processed_url })
    }
    const extraRetouched = selected.length - 8
    const stacked = extraRetouched + unretouchedCount
    cells.push({
      type: 'stack',
      count: stacked,
      previewUrl: selected[8].processed_url, // 底层显示第 9 张精修图
    })
  } else {
    // 情况 2：精修 1-8 张，全部展示精修，第 N+1 格叠放未精修
    for (let i = 0; i < selected.length; i++) {
      cells.push({ type: 'photo', url: selected[i].processed_url })
    }
    if (unretouchedCount > 0) {
      cells.push({
        type: 'stack',
        count: unretouchedCount,
        previewUrl: selected[selected.length - 1].processed_url, // 底层显示最后一张精修图
      })
    }
  }

  return cells
}

/** 生成 demo 文案（如 item.caption 不存在时） */
function generateDemoCaption(item: TaskResult): string {
  const fallbacks = [
    '在时光的缝隙里，遇见最美的风景。',
    '今日份快乐，是这些照片给的！',
    '新的一站，新的故事。',
    '岁月悠长，山河无恙。',
  ]
  return fallbacks[item.total_photos % fallbacks.length]
}

function formatTime(date: string): string {
  return formatRelativeTime(new Date(date))
}

function onItemClick(item: TaskResult) {
  // 复用结果页查看详情：先把已加载的结果注入 store，再跳转
  const taskStore = useTaskStore()
  taskStore.setTaskResult(item)
  uni.navigateTo({ url: `/pages/result/result?task_id=${item.task_id}` })
}

function goIndex() {
  uni.reLaunch({ url: '/pages/index/index' })
}

function goBack() {
  // tabBar 页面无法 navigateBack，跳回首页
  uni.reLaunch({ url: '/pages/index/index' })
}
</script>

<style lang="scss" scoped>
@import '@/uni.scss';

.page-history {
  min-height: 100vh;
  background: $bg-secondary;
}

/* tabBar 页面顶部安全留白（避开胶囊 + 状态栏） */
.header-tabbar-spacer {
  height: 30rpx;
  background: $bg-secondary;
}

.container {
  padding: $spacing-md;
}

.empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 200rpx 0;

  .empty-icon {
    font-size: 160rpx;
    margin-bottom: $spacing-lg;
  }

  .empty-title {
    font-size: $font-size-lg;
    color: $text-primary;
    font-weight: 600;
    margin-bottom: $spacing-sm;
  }

  .empty-subtitle {
    font-size: $font-size-sm;
    color: $text-secondary;
    margin-bottom: $spacing-xl;
  }

  .empty-btn {
    padding: 0 $spacing-xl;
  }
}

/* 底部 tabBar 安全区 */
.tabbar-safe {
  height: 120rpx;
}

.history-list {
  display: flex;
  flex-direction: column;
  gap: $spacing-md;
}

.history-item {
  background: $bg-primary;
  border-radius: $radius-lg;
  padding: $spacing-md;
  box-shadow: $shadow-sm;
}

.item-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: $spacing-sm;

  .item-time {
    font-size: $font-size-sm;
    color: $text-secondary;
  }

  .item-status {
    font-size: $font-size-xs;
    padding: 2rpx 12rpx;
    border-radius: $radius-sm;
    background: $bg-tertiary;
    color: $text-secondary;

    &.done {
      background: rgba($success, 0.1);
      color: $success;
    }
  }
}

/* 1. 数据统计（突出显示） */
.item-stats {
  display: flex;
  align-items: baseline;
  gap: 6rpx;
  padding: $spacing-sm 0;
  margin-bottom: $spacing-sm;
  background: linear-gradient(90deg, rgba(255,167,38,0.06) 0%, transparent 100%);
  border-radius: $radius-md;
}

.stat-block {
  display: flex;
  align-items: baseline;
  gap: 4rpx;

  .stat-num {
    font-size: 40rpx;
    font-weight: 800;
    color: $text-primary;
    line-height: 1;
    font-family: -apple-system, 'DIN Alternate', sans-serif;
  }

  .stat-label {
    font-size: $font-size-sm;
    color: $text-secondary;
    font-weight: 500;
  }

  &.highlight .stat-num {
    color: $primary;
    background: linear-gradient(135deg, $primary 0%, $primary-dark 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
  }
}

.stat-divider {
  font-size: $font-size-md;
  color: $text-tertiary;
  margin: 0 8rpx;
}

.stat-unit {
  font-size: $font-size-sm;
  color: $text-secondary;
  margin-left: 4rpx;
}

/* 2. 朋友圈文案 */
.item-caption {
  padding: $spacing-sm $spacing-md;
  margin-bottom: $spacing-sm;
  background: linear-gradient(135deg, rgba(255, 245, 225, 0.4) 0%, rgba(255, 230, 200, 0.2) 100%);
  border-left: 6rpx solid $accent;
  border-radius: 0 $radius-md $radius-md 0;

  .caption-text {
    font-size: $font-size-md;
    color: $text-primary;
    line-height: 1.6;
    font-style: italic;
  }
}

/* 3. 九宫格照片 */
.item-photos {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: $spacing-xs;
  margin-bottom: $spacing-xs;
}

.item-photo {
  width: 100%;
  aspect-ratio: 1;
  border-radius: $radius-sm;
  background: $bg-tertiary;
}

/* 叠放样式（最后一张位置） */
.item-photo-stack {
  position: relative;
  width: 100%;
  aspect-ratio: 1;
  border-radius: $radius-sm;
  background: $bg-tertiary;
  overflow: hidden;
  // 模拟多张叠加的视觉错位
  &::before,
  &::after {
    content: '';
    position: absolute;
    inset: 0;
    border-radius: $radius-sm;
    background: rgba(0, 0, 0, 0.05);
  }
  &::before {
    transform: translate(-6rpx, -6rpx);
    background: rgba(255, 255, 255, 0.6);
    z-index: 0;
  }
  &::after {
    transform: translate(-12rpx, -12rpx);
    background: rgba(255, 255, 255, 0.4);
    z-index: -1;
  }

  .stack-bg {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    z-index: 1;
  }

  .stack-num {
    position: absolute;
    inset: 0;
    z-index: 2;
    display: flex;
    align-items: center;
    justify-content: center;
    color: #fff;
    font-size: 40rpx;
    font-weight: 800;
    text-shadow: 0 2rpx 8rpx rgba(0, 0, 0, 0.4);
    background: rgba(0, 0, 0, 0.25);
    backdrop-filter: blur(2rpx);
  }
}
</style>
