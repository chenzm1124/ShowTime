<template>
  <view class="page-index">
    <!-- 顶部Banner -->
    <view class="hero">
      <view class="hero-bg" />
      <!-- 装饰：白色翅膀花纹（代表梦想，纯 CSS 绘制） -->
      <view class="deco wing wing-left">
        <view class="feather feather-1" />
        <view class="feather feather-2" />
        <view class="feather feather-3" />
      </view>
      <view class="deco wing wing-right">
        <view class="feather feather-1" />
        <view class="feather feather-2" />
        <view class="feather feather-3" />
      </view>
      <!-- 小白点星光点缀（保留原像素风装饰的轻盈感） -->
      <view class="deco star star-1" />
      <view class="deco star star-2" />
      <view class="deco star star-3" />
      <!-- LOGO + 标题 -->
      <view class="hero-content">
        <view class="brand">
          <view class="brand-logo">
            <text class="logo-icon">▣</text>
            <text class="brand-name">图轻松</text>
          </view>
        </view>
        <text class="hero-title">AI 智能出图</text>
        <text class="hero-subtitle">每一次活动，都是一次品牌亮相</text>
      </view>
    </view>

    <!-- 额度指示器 -->
    <view class="quota-section">
      <tp-quota-indicator
        :member-type="quotaStore.memberType"
        :photos-per-task="quotaStore.currentTaskLimit"
        :trial-remaining="quotaStore.trialRemaining"
        :ad-remaining-today="quotaStore.adRemainingToday"
        :pack-balance="quotaStore.packBalance"
        :next-pack-expire-hint="packExpireHint"
        :current-pack-name="currentPackName"
      />
    </view>

    <!-- 主要功能入口 -->
    <view class="action-section">
      <view class="action-card primary" @click="goToUpload">
        <view class="action-icon-wrap">
          <text class="action-icon">▣</text>
        </view>
        <view class="action-info">
          <text class="action-title">开始处理照片</text>
          <text class="action-desc">{{ quotaStore.currentTaskLimit }}张/次，AI一键筛选+精修</text>
        </view>
        <text class="action-arrow">›</text>
      </view>

      <view class="action-grid">
        <view class="action-card mini" @click="goBuyPack">
          <text class="mini-icon">¥</text>
          <text class="mini-title">购买套餐</text>
        </view>
        <view class="action-card mini" @click="goToHistory">
          <text class="mini-icon">≡</text>
          <text class="mini-title">历史记录</text>
        </view>
        <view class="action-card mini" @click="goToQuota">
          <text class="mini-icon">+</text>
          <text class="mini-title">领免费次数</text>
        </view>
      </view>
    </view>

    <!-- 功能介绍 -->
    <view class="features-section">
      <view class="section-title">
        <text class="title-deco">[</text>
        <text class="title-text">3步搞定大片</text>
        <text class="title-deco">]</text>
      </view>
      <view class="feature-list">
        <view class="feature-item">
          <view class="feature-num">1</view>
          <view class="feature-content">
            <text class="feature-name">智能筛选</text>
            <text class="feature-desc">AI 智能识别活动照片内容，自动分类聚类，挑出每组最佳照片</text>
          </view>
        </view>
        <view class="feature-item">
          <view class="feature-num">2</view>
          <view class="feature-content">
            <text class="feature-name">分类精修</text>
            <text class="feature-desc">人物照自然精修不失真，场景照智能调色，保留商务质感</text>
          </view>
        </view>
        <view class="feature-item">
          <view class="feature-num">3</view>
          <view class="feature-content">
            <text class="feature-name">文案生成</text>
            <text class="feature-desc">根据活动主题和照片内容，5 种风格任你选，一键生成品牌朋友圈文案，复制即发</text>
          </view>
        </view>
      </view>
    </view>

    <!-- 底部安全区：避免内容被 tabBar 遮挡（tabBar 高约 100rpx） -->
    <view class="bottom-tabbar-safe" />
  </view>
</template>

<script setup lang="ts">
// 页面级 polyfill 兜底（必须在所有 import 之前）
import '@/utils/pagePolyfills'

import { computed, onMounted } from 'vue'
import { useQuotaStore } from '@/stores/quota'
import { useUserStore } from '@/stores/user'

const quotaStore = useQuotaStore()
const userStore = useUserStore()

/** 套餐包过期提示（如 "30天后过期" / "明天过期"） */
const packExpireHint = computed(() => {
  const pack = quotaStore.nextPack
  if (!pack) return ''
  const seconds = pack.expire_in_seconds
  if (seconds <= 0) return '已过期'
  if (seconds < 86400) return `${Math.ceil(seconds / 3600)}h后过期`
  const days = Math.ceil(seconds / 86400)
  return `${days}天后过期`
})

/** 当前生效的套餐包名称（按购买时间最早的一个），供"当前套餐-XX包"展示 */
const currentPackName = computed(() => quotaStore.nextPack?.pack_name || '')

onMounted(() => {
  quotaStore.fetchQuota()
})

function goToUpload() {
  // 检查登录
  if (!userStore.isLoggedIn) {
    doLogin().then(() => {
      uni.navigateTo({ url: '/pages/upload/upload' })
    })
    return
  }

  // 检查额度
  const check = quotaStore.canProcess(1)
  if (!check.ok) {
    uni.showModal({
      title: '免费次数已用完',
      content: check.reason || '',
      confirmText: '看广告',
      cancelText: '购买次数包',
      success: (res) => {
        if (res.confirm || res.cancel) {
          uni.navigateTo({ url: '/pages/quota/quota' })
        }
      },
    })
    return
  }

  uni.navigateTo({ url: '/pages/upload/upload' })
}

function goToHistory() {
  // history 是 tabBar 页面，必须用 switchTab，不能 navigateTo
  uni.switchTab({ url: '/pages/history/history' })
}

function goToQuota() {
  uni.navigateTo({ url: '/pages/quota/quota' })
}

function goBuyPack() {
  uni.navigateTo({ url: '/pages/quota/quota' })
}

async function doLogin() {
  const success = await userStore.loginByWechat()
  if (success) {
    // P1-01 修复：必须 await，避免 navigateTo 时 quotaStore 还在 fetch
    // 旧逻辑：fire-and-forget → 上传页拿到的 quota 可能仍是上一用户/空
    // 新逻辑：await + 错误吞掉（fetchQuota 失败不应阻塞登录）
    try {
      await quotaStore.fetchQuota()
    } catch (e) {
      console.warn('[index] fetchQuota 失败（不影响登录）:', e)
    }
  }
}
</script>

<style lang="scss" scoped>
@import '@/uni.scss';

.page-index {
  min-height: 100vh;
  padding-bottom: 60rpx;
  background: linear-gradient(180deg, #FFF3E0 0%, $bg-secondary 35%, $bg-secondary 100%);
}

/* Hero */
.hero {
  position: relative;
  height: 460rpx;
  overflow: hidden;
  display: flex;
  align-items: center;
  justify-content: center;
}

.hero-bg {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  // 浅橙渐变 + 暖光晕
  background:
    radial-gradient(circle at 20% 30%, rgba(255,204,128,0.35) 0%, transparent 45%),
    radial-gradient(circle at 85% 70%, rgba(251,140,0,0.25) 0%, transparent 40%),
    linear-gradient(135deg, $primary-light 0%, $primary 45%, $primary-dark 100%);
}

/* ============ 装饰：白色翅膀花纹（代表梦想） ============ */
.deco {
  position: absolute;
  z-index: 1;
  pointer-events: none;
}

/* 翅膀容器：整体淡白色，半透明 */
.wing {
  width: 140rpx;
  height: 200rpx;
  opacity: 0.5;
}

.wing-left {
  top: 22%;
  left: 6%;
  transform: rotate(-15deg);
}

.wing-right {
  top: 22%;
  right: 6%;
  transform: rotate(15deg) scaleX(-1); /* 镜像翻转 = 右翅 */
}

/* 每一根羽毛：椭圆形，向上递进 */
.feather {
  position: absolute;
  background: rgba(255, 255, 255, 0.85);
  border-radius: 50% 50% 50% 50% / 60% 60% 40% 40%;
  box-shadow: 0 2rpx 8rpx rgba(255, 255, 255, 0.4);
}

.feather-1 {
  width: 60rpx;
  height: 100rpx;
  top: 50rpx;
  left: 20rpx;
  transform: rotate(-8deg);
}

.feather-2 {
  width: 56rpx;
  height: 90rpx;
  top: 30rpx;
  left: 50rpx;
  transform: rotate(8deg);
}

.feather-3 {
  width: 50rpx;
  height: 80rpx;
  top: 20rpx;
  left: 78rpx;
  transform: rotate(20deg);
}

/* 小白点星光 */
.star {
  width: 12rpx;
  height: 12rpx;
  background: rgba(255, 255, 255, 0.8);
  border-radius: 50%;
  box-shadow: 0 0 8rpx rgba(255, 255, 255, 0.6);
}

.star-1 { top: 12%; left: 48%; width: 10rpx; height: 10rpx; opacity: 0.7; }
.star-2 { top: 70%; left: 18%; width: 14rpx; height: 14rpx; opacity: 0.5; }
.star-3 { top: 80%; right: 22%; width: 8rpx;  height: 8rpx;  opacity: 0.6; }

.hero-content {
  position: relative;
  z-index: 2;
  text-align: center;
  color: #fff;
  padding: 0 $spacing-lg;
  width: 100%;
  box-sizing: border-box;
}

/* LOGO 区域 */
.brand {
  margin-bottom: $spacing-md;
}

.brand-logo {
  display: inline-flex;
  align-items: center;
  gap: $spacing-sm;
  padding: $spacing-xs $spacing-md;
  background: rgba(255, 255, 255, 0.2);
  border-radius: 60rpx;
  backdrop-filter: blur(10rpx);
  border: 1rpx solid rgba(255, 255, 255, 0.3);
}

.logo-icon {
  font-size: 40rpx;
  line-height: 1;
}

.brand-name {
  font-size: 32rpx;
  font-weight: 800;
  color: #fff;
  letter-spacing: 4rpx;
  line-height: 1.1;
}

.hero-title {
  display: block;
  font-size: 48rpx;
  font-weight: 700;
  margin-bottom: $spacing-sm;
  letter-spacing: 2rpx;
  text-shadow: 0 2rpx 8rpx rgba(0, 0, 0, 0.15);
}

.hero-subtitle {
  display: block;
  font-size: $font-size-md;
  opacity: 0.95;
  letter-spacing: 1rpx;
  text-shadow: 0 1rpx 4rpx rgba(0, 0, 0, 0.1);
}

/* 额度 */
.quota-section {
  margin: -40rpx $spacing-md 0;
  position: relative;
  z-index: 2;
}

/* 主操作区 */
.action-section {
  padding: $spacing-lg $spacing-md 0;
}

.action-card {
  display: flex;
  align-items: center;
  background: $bg-primary;
  border-radius: $radius-lg;
  padding: $spacing-lg;
  box-shadow: $shadow-sm;
  margin-bottom: $spacing-md;
  transition: transform 0.2s;

  &:active {
    transform: scale(0.98);
  }
}

.action-card.primary {
  // 科技绿渐变（亮绿 → 深绿）
  background: linear-gradient(135deg, $primary-light 0%, $primary 50%, $primary-dark 130%);
  color: #fff;
  box-shadow: 0 8rpx 24rpx rgba(255,167,38,0.35);

  .action-icon-wrap {
    background: rgba(255, 255, 255, 0.25);
  }

  .action-title,
  .action-desc {
    color: #fff;
  }

  .action-arrow {
    color: rgba(255, 255, 255, 0.9);
  }
}

.action-icon-wrap {
  width: 88rpx;
  height: 88rpx;
  background: $bg-secondary;
  border-radius: $radius-md;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-right: $spacing-md;
}

.action-icon {
  font-size: 48rpx;
}

.action-info {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 4rpx;
}

.action-title {
  font-size: $font-size-md;
  font-weight: 600;
}

.action-desc {
  font-size: $font-size-sm;
  color: $text-secondary;
}

.action-arrow {
  font-size: 40rpx;
  color: $text-tertiary;
  line-height: 1;
}

.action-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: $spacing-sm;
}

.action-card.mini {
  flex-direction: column;
  align-items: center;
  text-align: center;
  padding: $spacing-md $spacing-sm;

  .mini-icon {
    font-size: 56rpx;
    margin-bottom: $spacing-xs;
  }

  .mini-title {
    font-size: $font-size-sm;
    color: $text-primary;
    font-weight: 500;
  }
}

/* 功能介绍 */
.features-section {
  padding: $spacing-xl $spacing-md 0;
}

.section-title {
  margin-bottom: $spacing-lg;
  text-align: center;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: $spacing-sm;

  .title-deco {
    font-size: 28rpx;
    opacity: 0.7;
  }

  .title-text {
    font-size: $font-size-lg;
    font-weight: 600;
    color: $text-primary;
    position: relative;
    padding: 0 16rpx;
  }
}

.feature-list {
  display: flex;
  flex-direction: column;
  gap: $spacing-md;
}

.feature-item {
  display: flex;
  gap: $spacing-md;
  padding: $spacing-lg;
  background: $bg-primary;
  border-radius: $radius-lg;
  box-shadow: $shadow-sm;
}

.feature-num {
  flex-shrink: 0;
  width: 56rpx;
  height: 56rpx;
  background: linear-gradient(135deg, $primary 0%, $primary-dark 100%);
  color: #fff;
  border-radius: $radius-sm; // 科技像素风：方角化
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: $font-size-lg;
  font-weight: 700;
  box-shadow: 0 4rpx 12rpx rgba(255,167,38,0.35);
}

.feature-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: $spacing-xs;
}

.feature-name {
  font-size: $font-size-md;
  font-weight: 600;
  color: $text-primary;
}

.feature-desc {
  font-size: $font-size-sm;
  color: $text-secondary;
  line-height: 1.6;
}

/* VIP推广 - 科技绿渐变 + 白色描边 */
.vip-promo {
  margin: $spacing-xl $spacing-md 0;
  padding: $spacing-lg $spacing-lg;
  // 科技绿（亮 → 深）水平渐变
  background: linear-gradient(90deg, $primary-light 0%, $primary 45%, $primary-dark 100%);
  border-radius: $radius-lg;
  display: flex;
  align-items: center;
  justify-content: space-between;
  // 白色细描边
  border: 2rpx solid rgba(255, 255, 255, 0.6);
  // 柔光阴影（绿调）
  box-shadow: 0 8rpx 24rpx rgba(255,167,38,0.25);
  position: relative;
  overflow: hidden;
}

.promo-content {
  display: flex;
  flex-direction: column;
  gap: 8rpx;
  flex: 1;
  min-width: 0;
}

.promo-title {
  font-size: $font-size-lg;
  font-weight: 700;
  color: #FFFFFF;
  letter-spacing: 1rpx;
  text-shadow: 0 1rpx 2rpx rgba(0, 0, 0, 0.1);
}

.promo-desc {
  font-size: $font-size-sm;
  color: rgba(255, 255, 255, 0.95);
  font-weight: 500;
  letter-spacing: 1rpx;
}

.promo-action {
  display: flex;
  align-items: center;
  gap: 6rpx;
  flex-shrink: 0;
  padding-left: $spacing-md;

  .action-text {
    font-size: $font-size-base;
    color: #FFFFFF;
    font-weight: 600;
    letter-spacing: 1rpx;
  }

  .action-arrow {
    font-size: 32rpx;
    color: #FFFFFF;
    font-weight: 600;
    line-height: 1;
  }
}

.vip-promo:active {
  transform: scale(0.99);
  transition: transform 0.15s;
}

.bottom-tabbar-safe {
  height: 120rpx;
}
</style>
