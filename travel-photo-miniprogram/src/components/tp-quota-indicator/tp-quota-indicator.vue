<template>
  <view class="quota-indicator" :class="`level-${memberType}`">
    <view class="quota-content">
      <view class="quota-level">
        <text class="level-icon">{{ levelIcon }}</text>
        <text class="level-name">{{ levelName }}</text>
      </view>
      <!-- 免费用户：按优先级显示当前可用额度来源 -->
      <!-- P1-13 修复（彻底版）：原 <text> 上的 v-if/v-else-if/v-else 链 + 嵌套 <text>
           会触发 uni-app 编译 bug "Framework inner error (expect END descriptor with
           depth 1 but get FLOW_ALLOC_NODE_ID)"，导致引用本组件的 index 页整页渲染层
           崩溃。必须把整条链上每一个分支都用 <block> 包裹（<block> 不渲染真实节点、
           编译器不为其分配 WXML 节点 ID），才能彻底规避该 bug。
           之前的 P1-13 只包了第一个分支、后三个分支仍写 v-else-if/v-else，在某些
           渲染顺序下仍会触发 FLOW_ALLOC_NODE_ID（导致整页空白）。 -->
      <view v-if="memberType === 'free'" class="quota-detail">
        <block v-if="packBalance > 0">
          <text class="detail-text">
            套餐剩余 <text class="highlight">{{ packBalance }}</text> 次
            <text v-if="nextPackExpireHint" class="expire-hint">({{ nextPackExpireHint }})</text>
          </text>
        </block>
        <block v-else-if="trialRemaining > 0">
          <text class="detail-text">
            试用还剩 <text class="highlight">{{ trialRemaining }}</text> 次
          </text>
        </block>
        <block v-else-if="adRemainingToday > 0">
          <text class="detail-text">
            今日广告解锁 <text class="highlight">{{ adRemainingToday }}</text> 次
          </text>
        </block>
        <block v-else>
          <text class="detail-text">免费次数已用完</text>
        </block>
      </view>
      <!-- VIP 用户 -->
      <view v-else class="quota-detail">
        <text class="detail-text">
          每次可处理 <text class="highlight">{{ photosPerTask }}张</text>，{{ dailyLabel }}
        </text>
      </view>
    </view>
    <view class="quota-extra">
      <text class="extra-text">{{ extraText }}</text>
    </view>
  </view>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  memberType: 'free' | 'vip1' | 'vip2' | 'vip3'
  photosPerTask: number
  trialRemaining: number
  adRemainingToday: number
  /** 套餐包剩余总次数（所有有效包相加） */
  packBalance?: number
  /** 最近一个要过期的包的过期提示文字，如 "30天后过期" */
  nextPackExpireHint?: string
  /** 当前生效的套餐包名称（用于 free 用户的"当前套餐-XX包"展示），无包时为空 */
  currentPackName?: string
}>()

const levelName = computed(() => {
  // VIP 用户维持原会员等级文案
  if (props.memberType === 'vip1') return '基础会员'
  if (props.memberType === 'vip2') return '高级会员'
  if (props.memberType === 'vip3') return '旗舰会员'
  // 免费用户：显示当前套餐包名称，无包时显示"暂无套餐"
  return props.currentPackName ? `当前套餐-${props.currentPackName}` : '当前套餐-暂无套餐'
})

const levelIcon = computed(() => {
  const map: Record<string, string> = {
    free: '○',
    vip1: '◇',
    vip2: '◆',
    vip3: '★',
  }
  return map[props.memberType] || '○'
})

const extraText = computed(() => {
  if (props.memberType === 'free') {
    return `${props.photosPerTask}张/次`
  }
  return 'VIP尊享'
})

const dailyLabel = computed(() => {
  const map: Record<string, string> = {
    vip1: '每日 3 次',
    vip2: '每日 5 次',
    vip3: '每日 7 次',
  }
  return map[props.memberType] || ''
})
</script>

<style lang="scss" scoped>
@import '@/uni.scss';

.quota-indicator {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: $spacing-md $spacing-lg;
  border-radius: $radius-lg;
  background: linear-gradient(135deg, $primary-bg 0%, #fff 100%);
  border: 1rpx solid rgba($primary, 0.2);
  box-shadow: $shadow-sm;

  &.level-vip1 {
    background: linear-gradient(135deg, $primary-bg 0%, #fff 100%);
    border-color: rgba($primary, 0.3);
  }

  &.level-vip2 {
    background: linear-gradient(135deg, #C8E6C9 0%, #fff 100%);
    border-color: rgba($primary-dark, 0.35);
  }

  &.level-vip3 {
    background: linear-gradient(135deg, #FFE0B2 0%, #fff 100%);
    border-color: rgba($primary-dark, 0.45);
  }
}

.quota-content {
  flex: 1;
}

.quota-level {
  display: flex;
  align-items: center;
  gap: $spacing-xs;
  margin-bottom: 4rpx;

  .level-icon {
    font-size: 32rpx;
  }

  .level-name {
    font-size: $font-size-md;
    font-weight: 600;
    color: $text-primary;
  }
}

.quota-detail {
  .detail-text {
    font-size: $font-size-sm;
    color: $text-secondary;

    .highlight {
      color: $primary;
      font-weight: 600;
    }

    .expire-hint {
      color: $text-tertiary;
      font-size: $font-size-xs;
      margin-left: 4rpx;
    }
  }
}

.quota-extra {
  padding: 4rpx 16rpx;
  background: rgba($primary, 0.12);
  border-radius: $radius-sm;

  .level-vip1 & {
    background: rgba($primary, 0.15);
  }
  .level-vip2 & {
    background: rgba($primary-dark, 0.18);
  }
  .level-vip3 & {
    background: rgba($primary-dark, 0.22);
  }

  .extra-text {
    font-size: $font-size-xs;
    color: $primary-dark;
    font-weight: 500;

    .level-vip1 & {
      color: $primary;
    }
    .level-vip2 & {
      color: $primary-dark;
    }
    .level-vip3 & {
      color: $text-primary;
    }
  }
}
</style>
