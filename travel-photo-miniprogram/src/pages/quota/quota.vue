<template>
  <view class="page-quota">
    <view class="header">
      <text class="back" @click="goBack">‹</text>
      <text class="title">我的额度</text>
      <text class="placeholder" />
    </view>

    <view class="container">
      <!-- 额度概览 -->
      <view class="quota-overview card">
        <text class="overview-label">免费用户额度</text>
        <view class="overview-content">
          <view class="overview-item">
            <text class="item-num">{{ quotaStore.trialRemaining }}</text>
            <text class="item-label">免费试用</text>
            <text class="item-tip">终身1次</text>
          </view>
          <view class="overview-divider" />
          <view class="overview-item">
            <text class="item-num">{{ quotaStore.adRemainingToday }}</text>
            <text class="item-label">广告解锁</text>
            <text class="item-tip">每日2次</text>
          </view>
          <view class="overview-divider" />
          <view class="overview-item">
            <text class="item-num">{{ quotaStore.packBalance }}</text>
            <text class="item-label">次数包</text>
            <text class="item-tip">总剩余</text>
          </view>
        </view>
      </view>


      <!-- 我持有的次数包（免费/付费用户都可能持有） -->
      <view v-if="quotaStore.userPacks.length > 0" class="my-packs card">
        <text class="section-title">我的次数包</text>
        <view
          v-for="p in quotaStore.userPacks"
          :key="p.user_pack_id"
          class="pack-row"
        >
          <view class="pack-row-left">
            <text class="pack-row-name">{{ p.pack_name }}</text>
            <text class="pack-row-sub">
              {{ p.remaining_tasks }}/{{ p.total_tasks }} 次 · {{ p.photos_per_task }}张/次
            </text>
          </view>
          <view class="pack-row-right">
            <text class="pack-row-expire">
              {{ formatExpire(p.expire_in_seconds) }}
            </text>
            <text v-if="p.remaining_tasks === 0" class="pack-row-tag exhausted">已用完</text>
            <text v-else-if="p.expire_in_seconds <= 0" class="pack-row-tag expired">已过期</text>
            <text v-else class="pack-row-tag active">可用</text>
          </view>
        </view>
      </view>

      <!-- 次数套餐包 -->
      <view class="pack-tab">
        <view
          v-for="pack in quotaStore.packs"
          :key="pack.code"
          class="plan-card"
          :class="{ highlight: pack.highlight }"
          @click="onBuyPack(pack.code)"
        >
          <view v-if="pack.badge" class="plan-badge">{{ pack.badge }}</view>
          <text class="plan-name">{{ pack.name }}</text>
          <text class="plan-desc">{{ pack.description }}</text>
          <view class="plan-price">
            <text class="price-symbol">¥</text>
            <text class="price-num">{{ pack.price }}</text>
            <text v-if="pack.original_price" class="price-original">¥{{ pack.original_price }}</text>
          </view>
          <view class="plan-meta">
            <text class="meta-item">{{ pack.task_quota }} 次处理</text>
            <text class="meta-divider">|</text>
            <text class="meta-item">{{ pack.photos_per_task }}张/次</text>
            <text class="meta-divider">|</text>
            <text class="meta-item">{{ pack.max_refine_per_task }}张精修</text>
          </view>
          <view class="plan-features">
            <text v-for="f in pack.features" :key="f" class="feature-item">· {{ f }}</text>
          </view>
          <button class="btn-primary plan-btn">立即购买</button>
        </view>
      </view>

      <!-- 广告解锁区（仅免费用户显示） -->
      <view v-if="!userStore.isVip" class="ad-section card">
        <view class="ad-header">
          <text class="ad-icon">▷</text>
          <view class="ad-info">
            <text class="ad-title">看广告，免费解锁1次</text>
            <text class="ad-desc">观看 15 秒视频广告，立即获得 20 张处理机会</text>
          </view>
        </view>
        <button
          class="btn-primary ad-btn"
          :class="{ disabled: !canWatchAd }"
          :disabled="!canWatchAd"
          @click="watchAd"
        >
          {{ canWatchAd ? '看视频广告' : '今日次数已用完' }}
        </button>
        <text v-if="watchCount > 0" class="ad-progress">
          今日已观看 {{ watchCount }} 次 / 最多 2 次（每次 20 张）
        </text>
      </view>

      <!-- 额度说明 -->
      <view class="rules card">
        <text class="section-title">额度规则</text>
        <view class="rule-item">
          <text class="rule-dot">①</text>
          <text class="rule-text">每个账号<text class="highlight">终身仅有 1 次免费试用</text>，用完即止</text>
        </view>
        <view class="rule-item">
          <text class="rule-dot">②</text>
          <text class="rule-text">试用用完后，可通过<text class="highlight">观看广告</text>每天解锁最多 2 次（每次 20 张）</text>
        </view>
        <view class="rule-item">
          <text class="rule-dot">③</text>
          <text class="rule-text">次数套餐包：<text class="highlight">9.9 元起</text>，1-7 次批量处理，30-100 张/次，过期未用完清零</text>
        </view>

      </view>
    </view>

    <!-- 广告倒计时蒙版 -->
    <view v-if="showAdOverlay" class="ad-overlay" @click.stop>
      <!-- 右上角倒计时 -->
      <view class="ad-overlay-timer">
        <text v-if="adCountdown > 0" class="ad-timer-text">{{ adCountdown }}s</text>
        <text v-else class="ad-timer-text ad-timer-done">✓</text>

      </view>

      <!-- 中央内容 -->
      <view class="ad-overlay-content">
        <template v-if="adCountdown > 0">
          <text class="ad-overlay-icon">▷</text>
          <text class="ad-overlay-title">广告播放中</text>
          <view class="ad-overlay-progress">
            <view class="ad-overlay-progress-bar" :style="{ width: adProgress + '%' }" />
          </view>
          <text class="ad-overlay-hint">请勿关闭，{{ adCountdown }} 秒后可领取奖励</text>
        </template>
        <template v-else>
          <text class="ad-overlay-icon">✓</text>
          <text class="ad-overlay-title">观看完成</text>
          <text class="ad-overlay-hint">已获得 1 次免费处理机会</text>
          <button class="btn-primary ad-overlay-btn" @click="closeAdAndUnlock">领取并返回</button>
        </template>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useQuotaStore } from '@/stores/quota'
import { useUserStore } from '@/stores/user'

const quotaStore = useQuotaStore()
const userStore = useUserStore()

const watchCount = ref(0)

// ---- 广告倒计时 ----
const AD_WATCH_DURATION = 15 // 要求观看 15 秒
const showAdOverlay = ref(false)
const adCountdown = ref(0)
let countdownTimer: ReturnType<typeof setInterval> | null = null
// P0-15 修复：广告实例 + onClose handler 跨页累积内存泄漏
// 原因：onMounted 每次都创建新实例 + onClose 注册新 handler（不覆盖）
// → 用户反复进 quota 页 → 多个实例同时跑 + handler 链累积
// 修复：1) 实例单例化（已存在则复用，只注册一次 onError）
//       2) onClose handler 用 offClose 提前清理
let rewardedVideoAd: any = null
let _adHandlersAttached = false
let _adCloseHandler: ((res: any) => void) | null = null
let _adErrorHandler: ((err: any) => void) | null = null

const adProgress = computed(() => {
  if (AD_WATCH_DURATION === 0) return 0
  return ((AD_WATCH_DURATION - adCountdown.value) / AD_WATCH_DURATION) * 100
})

onMounted(() => {
  // #ifdef MP-WEIXIN
  if (typeof wx !== 'undefined' && wx.createRewardedVideoAd) {
    if (!rewardedVideoAd) {
      rewardedVideoAd = wx.createRewardedVideoAd({
        adUnitId: 'adunit-xxxxxxxxxxxx', // TODO: 替换为真实广告位 ID
      })
    }
    if (!_adHandlersAttached && rewardedVideoAd) {
      _adErrorHandler = (err: any) => {
        console.error('[广告加载失败]', err)
      }
      rewardedVideoAd.onError(_adErrorHandler)
      _adHandlersAttached = true
    }
  }
  // #endif
})

// P0-15 修复：页面卸载时清理广告 handler 引用
onUnmounted(() => {
  if (countdownTimer) {
    clearInterval(countdownTimer)
    countdownTimer = null
  }
  // 注意：rewardedVideoAd 实例本身保留供下次进页复用（避免重复创建）
  // 只清掉 onClose 临时 handler（每次 show 前注册、回调后立即 off）
  // 这里只清错误 handler 引用（实例活着，错误回调仍生效）
  if (rewardedVideoAd && _adErrorHandler) {
    try {
      rewardedVideoAd.offError?.(_adErrorHandler)
    } catch (e) {
      // 微信 API 不支持 offError 时静默忽略
    }
  }
  _adErrorHandler = null
})

const canWatchAd = computed(() => {
  if (userStore.isVip) return false
  return quotaStore.adRemainingToday > 0
})

function formatExpire(secs: number): string {
  if (secs <= 0) return '已过期'
  if (secs < 3600) return `${Math.ceil(secs / 60)} 分钟后过期`
  if (secs < 86400) return `${Math.ceil(secs / 3600)} 小时后过期`
  return `${Math.ceil(secs / 86400)} 天后过期`
}

async function watchAd() {
  if (!canWatchAd.value) return

  // #ifdef MP-WEIXIN
  // 真实微信激励视频广告
  if (rewardedVideoAd) {
    await watchAdReal()
    return
  }
  // #endif

  // 模拟模式：15 秒倒计时
  startAdCountdown()
}

/** 模拟广告：15 秒倒计时 */
function startAdCountdown() {
  showAdOverlay.value = true
  adCountdown.value = AD_WATCH_DURATION

  countdownTimer = setInterval(() => {
    adCountdown.value--
    if (adCountdown.value <= 0) {
      clearAdTimer()
      adCountdown.value = 0
      // 倒计时结束，等待用户点击"领取并返回"
    }
  }, 1000)
}

function clearAdTimer() {
  if (countdownTimer) {
    clearInterval(countdownTimer)
    countdownTimer = null
  }
}

/** 真实微信激励视频广告 */
async function watchAdReal() {
  if (!rewardedVideoAd) return

  uni.showLoading({ title: '广告加载中...', mask: true })
  try {
    await rewardedVideoAd.show()
    uni.hideLoading()
  } catch (err) {
    try {
      await rewardedVideoAd.load()
      await rewardedVideoAd.show()
      uni.hideLoading()
    } catch (err2) {
      uni.hideLoading()
      uni.showToast({ title: '广告加载失败，请稍后重试', icon: 'none' })
      return
    }
  }

  // P0-15 修复：onClose 每次注册前先 offClose 上一个，避免 handler 链累积
  if (_adCloseHandler) {
    try { rewardedVideoAd.offClose?.(_adCloseHandler) } catch (e) {}
  }
  _adCloseHandler = async (res: any) => {
    // 触发一次后立即 off（防止下次调用又叠加 handler）
    try { rewardedVideoAd.offClose?.(_adCloseHandler!) } catch (e) {}
    _adCloseHandler = null
    if (res && res.isEnded) {
      await unlockAfterAd()
    } else {
      uni.showToast({ title: '需看完广告才能解锁', icon: 'none' })
    }
  }
  rewardedVideoAd.onClose(_adCloseHandler)
}

/** 用户点击"领取并返回"：关闭蒙版 + 调用后端解锁 */
async function closeAdAndUnlock() {
  showAdOverlay.value = false
  await unlockAfterAd()
}

/** 广告观看完成后调用后端解锁 */
async function unlockAfterAd() {
  try {
    const result = await quotaStore.watchAdForUnlock({
      ad_type: 'rewarded_video',
      ad_platform: 'wechat',
      watch_duration_seconds: AD_WATCH_DURATION,
      ad_callback_data: { source: rewardedVideoAd ? 'wechat' : 'mock' },
    })
    watchCount.value++
    uni.showToast({
      title: `解锁成功！今日剩余${result.ad_unlock_remaining_today}次`,
      icon: 'success',
    })
  } catch (err: any) {
    uni.showToast({ title: err?.message || '解锁失败', icon: 'none' })
  }
}

async function onBuyPack(code: 'daily' | 'enjoy' | 'unlimited') {
  uni.showModal({
    title: '确认购买',
    content: `确认购买该次数包？支付完成后次数将立即到账。`,
    success: async (res) => {
      if (!res.confirm) return
      uni.showLoading({ title: '下单中...', mask: true })
      try {
        await quotaStore.purchasePack(code)
        uni.hideLoading()
        uni.showToast({ title: '购买成功！', icon: 'success' })
      } catch (err: any) {
        uni.hideLoading()
        uni.showToast({ title: err?.message || '购买失败', icon: 'none' })
      }
    },
  })
}

function goBack() {
  uni.navigateBack()
}

onMounted(() => {
  // 并行拉取：额度 + 次数套餐包
  quotaStore.fetchQuota()
  quotaStore.fetchPacks()
})
</script>

<style lang="scss" scoped>
@import '@/uni.scss';

.page-quota {
  min-height: 100vh;
  background: $bg-secondary;
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

.card {
  background: $bg-primary;
  border-radius: $radius-lg;
  padding: $spacing-lg;
  margin-bottom: $spacing-md;
  box-shadow: $shadow-sm;
}

.quota-overview {
  .overview-label {
    display: block;
    font-size: $font-size-sm;
    color: $text-secondary;
    margin-bottom: $spacing-md;
  }

  .overview-content {
    display: flex;
    align-items: center;
  }

  .overview-item {
    flex: 1;
    text-align: center;
  }

  .item-num {
    display: block;
    font-size: 72rpx;
    font-weight: 700;
    color: $primary;
    line-height: 1;
  }

  .item-label {
    display: block;
    font-size: $font-size-md;
    color: $text-primary;
    margin-top: $spacing-sm;
    font-weight: 500;
  }

  .item-tip {
    display: block;
    font-size: $font-size-xs;
    color: $text-tertiary;
    margin-top: 4rpx;
  }

  .overview-divider {
    width: 1rpx;
    height: 100rpx;
    background: $border-color;
  }
}

.my-packs {
  .pack-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: $spacing-md 0;
    border-bottom: 1rpx solid $border-color;

    &:last-child {
      border-bottom: none;
    }
  }

  .pack-row-left {
    flex: 1;
  }

  .pack-row-name {
    display: block;
    font-size: $font-size-md;
    font-weight: 600;
    color: $text-primary;
  }

  .pack-row-sub {
    display: block;
    font-size: $font-size-sm;
    color: $text-secondary;
    margin-top: 4rpx;
  }

  .pack-row-right {
    text-align: right;
  }

  .pack-row-expire {
    display: block;
    font-size: $font-size-xs;
    color: $text-tertiary;
  }

  .pack-row-tag {
    display: inline-block;
    margin-top: 4rpx;
    padding: 2rpx 12rpx;
    border-radius: $radius-sm;
    font-size: $font-size-xs;

    &.active {
      background: rgba($success, 0.1);
      color: $success;
    }

    &.exhausted {
      background: $bg-tertiary;
      color: $text-tertiary;
    }

    &.expired {
      background: rgba($warning, 0.1);
      color: $warning;
    }
  }
}

.tab-bar {
  display: flex;
  background: $bg-primary;
  border-radius: $radius-lg;
  padding: 8rpx;
  margin-bottom: $spacing-md;
  box-shadow: $shadow-sm;

  .tab-item {
    flex: 1;
    text-align: center;
    padding: 20rpx 0;
    font-size: $font-size-md;
    font-weight: 500;
    color: $text-secondary;
    border-radius: $radius-md;
    transition: all 0.2s;
    position: relative;

    &.active {
      background: linear-gradient(135deg, $primary 0%, $primary-dark 100%);
      color: #fff;
      box-shadow: 0 4rpx 12rpx rgba($primary, 0.3);
    }
  }

  .tab-new {
    display: inline-block;
    margin-left: 8rpx;
    padding: 2rpx 10rpx;
    background: linear-gradient(135deg, $primary 0%, $primary-dark 100%);
    color: #fff;
    font-size: 18rpx;
    font-weight: 700;
    border-radius: 20rpx;
    line-height: 1.2;
    vertical-align: middle;
    transform: scale(0.85);
  }
}

/* 次数包引导 Banner */
.pack-banner {
  display: flex;
  align-items: center;
  gap: $spacing-md;
  padding: $spacing-md $spacing-lg;
  margin-bottom: $spacing-md;
  background: linear-gradient(135deg, $primary-bg 0%, #F1F8E9 100%);
  border: 2rpx solid rgba($primary, 0.2);
  border-radius: $radius-lg;
  box-shadow: $shadow-sm;

  .banner-icon {
    font-size: 56rpx;
    flex-shrink: 0;
  }

  .banner-content {
    flex: 1;
    min-width: 0;
  }

  .banner-title {
    display: block;
    font-size: $font-size-md;
    font-weight: 600;
    color: $text-primary;
    margin-bottom: 4rpx;
  }

  .banner-desc {
    display: block;
    font-size: $font-size-sm;
    color: $text-secondary;
  }

  .banner-arrow {
    font-size: 40rpx;
    color: $primary;
    font-weight: 300;
    flex-shrink: 0;
  }

  &:active {
    transform: scale(0.99);
  }
}

.plan-card {
  position: relative;
  background: $bg-primary;
  border-radius: $radius-lg;
  padding: $spacing-lg;
  margin-bottom: $spacing-md;
  box-shadow: $shadow-sm;

  &.highlight {
    background: linear-gradient(135deg, $primary-bg 0%, #fff 100%);
    border: 2rpx solid $primary;
    box-shadow: 0 4rpx 16rpx rgba($primary, 0.15);
  }

  .plan-badge {
    position: absolute;
    top: 0;
    right: 24rpx;
    background: linear-gradient(135deg, $primary 0%, $primary-dark 100%);
    color: #fff;
    font-size: $font-size-xs;
    padding: 6rpx 16rpx;
    border-radius: 0 0 $radius-md $radius-md;
    font-weight: 500;
  }

  .plan-name {
    display: block;
    font-size: $font-size-lg;
    font-weight: 600;
    color: $text-primary;
    margin-bottom: 4rpx;
  }

  .plan-desc {
    display: block;
    font-size: $font-size-sm;
    color: $text-secondary;
    margin-bottom: $spacing-md;
  }

  .plan-price {
    display: flex;
    align-items: baseline;
    margin-bottom: $spacing-md;
  }

  .price-symbol {
    font-size: $font-size-md;
    color: $primary;
    font-weight: 600;
  }

  .price-num {
    font-size: 64rpx;
    color: $primary;
    font-weight: 700;
    line-height: 1;
    margin-left: 2rpx;
  }

  .price-unit {
    font-size: $font-size-sm;
    color: $text-secondary;
    margin-left: 4rpx;
  }

  .price-original {
    font-size: $font-size-sm;
    color: $text-tertiary;
    text-decoration: line-through;
    margin-left: 12rpx;
  }

  .plan-meta {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 8rpx;
    padding: $spacing-sm 0;
    margin-bottom: $spacing-sm;
    background: rgba($primary, 0.05);
    border-radius: $radius-md;
    padding: 16rpx;

    .meta-item {
      font-size: $font-size-sm;
      color: $primary;
      font-weight: 500;
    }

    .meta-divider {
      color: $border-color;
    }
  }

  .plan-features {
    margin-bottom: $spacing-md;
  }

  .feature-item {
    display: block;
    font-size: $font-size-sm;
    color: $text-primary;
    line-height: 2;
  }

  .plan-btn {
    margin-top: $spacing-sm;
  }
}

.ad-section {
  .ad-header {
    display: flex;
    align-items: center;
    gap: $spacing-md;
    margin-bottom: $spacing-md;
  }

  .ad-icon {
    font-size: 80rpx;
  }

  .ad-info {
    flex: 1;
  }

  .ad-title {
    display: block;
    font-size: $font-size-md;
    font-weight: 600;
    color: $text-primary;
    margin-bottom: 4rpx;
  }

  .ad-desc {
    display: block;
    font-size: $font-size-sm;
    color: $text-secondary;
  }

  .ad-btn {
    margin-bottom: $spacing-sm;
  }

  .ad-progress {
    display: block;
    text-align: center;
    font-size: $font-size-xs;
    color: $text-secondary;
  }
}

.section-title {
  display: block;
  font-size: $font-size-md;
  font-weight: 600;
  color: $text-primary;
  margin-bottom: $spacing-md;
}

.rule-item {
  display: flex;
  gap: $spacing-sm;
  padding: $spacing-sm 0;
  line-height: 1.6;

  .rule-dot {
    flex-shrink: 0;
    width: 36rpx;
    height: 36rpx;
    background: rgba($primary, 0.1);
    color: $primary;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: $font-size-xs;
    font-weight: 600;
  }

  .rule-text {
    flex: 1;
    font-size: $font-size-sm;
    color: $text-primary;

    .highlight {
      color: $primary;
      font-weight: 500;
    }
  }
}

/* 广告倒计时蒙版 */
.ad-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.85);
  z-index: 9999;
  display: flex;
  align-items: center;
  justify-content: center;
}

/* 右上角倒计时 */
.ad-overlay-timer {
  position: absolute;
  top: 120rpx;
  right: 40rpx;
  width: 80rpx;
  height: 80rpx;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.15);
  display: flex;
  align-items: center;
  justify-content: center;
}

.ad-timer-text {
  font-size: $font-size-md;
  color: #fff;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

.ad-timer-done {
  color: #FB8C00;
  font-size: $font-size-lg;
}

/* 中央内容 */
.ad-overlay-content {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 24rpx;
  padding: 0 60rpx;
}

.ad-overlay-icon {
  font-size: 80rpx;
}

.ad-overlay-title {
  font-size: $font-size-lg;
  color: #fff;
  font-weight: 600;
}

.ad-overlay-progress {
  width: 400rpx;
  height: 8rpx;
  background: rgba(255, 255, 255, 0.2);
  border-radius: 4rpx;
  overflow: hidden;
}

.ad-overlay-progress-bar {
  height: 100%;
  background: $primary;
  border-radius: 4rpx;
  transition: width 1s linear;
}

.ad-overlay-hint {
  font-size: $font-size-sm;
  color: rgba(255, 255, 255, 0.6);
  text-align: center;
}

.ad-overlay-btn {
  margin-top: 40rpx;
  min-width: 320rpx;
}
</style>
