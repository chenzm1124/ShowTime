<template>
  <view class="page-mine">
    <!-- 顶部装饰背景 -->
    <view class="header-bg">
      <!-- 白色翅膀花纹装饰（代表梦想） -->
      <view class="wing wing-left">
        <view class="feather feather-1" />
        <view class="feather feather-2" />
        <view class="feather feather-3" />
      </view>
      <view class="wing wing-right">
        <view class="feather feather-1" />
        <view class="feather feather-2" />
        <view class="feather feather-3" />
      </view>
    </view>

    <!-- 用户卡片 -->
    <view class="user-card">
      <view class="avatar-section">
        <view class="avatar">
          <text class="avatar-text">{{ avatarText }}</text>
        </view>
        <view class="user-info">
          <text class="user-name">{{ userStore.userInfo?.nickname || '微信用户' }}</text>
          <text class="user-level">
            <text class="level-icon">{{ levelIcon }}</text>
            <text>{{ levelName }}</text>
          </text>
        </view>
      </view>

      <!-- 登录 / 退出按钮 -->
      <view v-if="!userStore.isLoggedIn" class="login-btn" @click="onLogin">
        <text>微信一键登录</text>
      </view>
      <view v-else class="logout-btn" @click="onLogout">
        <text>退出登录</text>
      </view>
    </view>

    <view class="container">
    <!-- 额度概览卡 -->
      <view class="quota-card card">
        <view class="quota-header">
          <text class="quota-title">我的额度</text>
          <text class="quota-action" @click="goQuota">管理 →</text>
        </view>
        <view v-if="isVipUser" class="quota-row">
          <view class="quota-stat">
            <text class="stat-num">{{ quotaStore.dailyRemaining }}</text>
            <text class="stat-label">今日剩余</text>
          </view>
          <view class="quota-divider" />
          <view class="quota-stat">
            <text class="stat-num">{{ quotaStore.dailyUsed }}</text>
            <text class="stat-label">今日已用</text>
          </view>
          <view class="quota-divider" />
          <view class="quota-stat">
            <text class="stat-num">{{ quotaStore.currentTaskLimit }}</text>
            <text class="stat-label">单次上限</text>
          </view>
        </view>
        <view v-else class="quota-row">
          <!-- 有套餐包时显示套餐剩余（优先级最高） -->
          <template v-if="quotaStore.packBalance > 0">
            <view class="quota-stat">
              <text class="stat-num">{{ quotaStore.packBalance }}</text>
              <text class="stat-label">套餐剩余</text>
            </view>
            <view class="quota-divider" />
            <view class="quota-stat">
              <text class="stat-num">{{ packExpireHint }}</text>
              <text class="stat-label">{{ packNameHint }}</text>
            </view>
            <view class="quota-divider" />
            <view class="quota-stat">
              <text class="stat-num">{{ quotaStore.currentTaskLimit }}</text>
              <text class="stat-label">单次上限</text>
            </view>
          </template>
          <!-- 无套餐包时显示试用/广告 -->
          <template v-else>
            <view class="quota-stat">
              <text class="stat-num">{{ quotaStore.trialRemaining }}</text>
              <text class="stat-label">试用剩余</text>
            </view>
            <view class="quota-divider" />
            <view class="quota-stat">
              <text class="stat-num">{{ quotaStore.adRemainingToday }}</text>
              <text class="stat-label">广告解锁</text>
            </view>
            <view class="quota-divider" />
            <view class="quota-stat">
              <text class="stat-num">{{ quotaStore.currentTaskLimit }}</text>
              <text class="stat-label">单次上限</text>
            </view>
          </template>
        </view>
      </view>

      <!-- 我的订单/记录 -->
      <view class="menu-card card">
        <view class="menu-item" @click="goHistory">
          <text class="menu-icon">≡</text>
          <view class="menu-content">
            <text class="menu-text">出图历史</text>
            <text class="menu-desc">查看所有处理过的照片</text>
          </view>
          <text class="menu-arrow">›</text>
        </view>
        <!-- 免费次数管理 -->
        <view class="menu-item" @click="goQuota">
          <text class="menu-icon">+</text>
          <view class="menu-content">
            <text class="menu-text">免费次数管理</text>
            <text class="menu-desc">看广告解锁 / 试用查询</text>
          </view>
          <text class="menu-arrow">›</text>
        </view>
      </view>

      <!-- 其他 -->
      <view class="menu-card card">
        <view class="menu-item" @click="onContactService">
          <text class="menu-icon">◐</text>
          <view class="menu-content">
            <text class="menu-text">联系客服</text>
          </view>
          <text class="menu-arrow">›</text>
        </view>
        <view class="menu-item" @click="onFeedback">
          <text class="menu-icon">✎</text>
          <view class="menu-content">
            <text class="menu-text">意见反馈</text>
          </view>
          <text class="menu-arrow">›</text>
        </view>
        <view class="menu-item" @click="onAbout">
          <text class="menu-icon">i</text>
          <view class="menu-content">
            <text class="menu-text">关于我们</text>
          </view>
          <text class="menu-arrow">›</text>
        </view>
      </view>

      <view class="version-text">图轻松 v0.3.0 · 轻松搞定朋友圈图文</view>
    </view>

    <!-- 底部 tabBar 安全区 -->
    <view class="tabbar-safe" />
  </view>
</template>

<script setup lang="ts">
// 页面级 polyfill 兜底：vendor.js 已通过 vite 插件注入，无需重复
import { computed, onMounted } from 'vue'
import { useUserStore } from '@/stores/user'
import { useQuotaStore } from '@/stores/quota'

const userStore = useUserStore()
const quotaStore = useQuotaStore()

const avatarText = computed(() => {
  const n = userStore.userInfo?.nickname || '游'
  return n.charAt(0)
})

const levelName = computed(() => {
  const map: Record<string, string> = {
    free: '免费用户',
    vip1: '基础会员',
    vip2: '高级会员',
    vip3: '旗舰会员',
  }
  return map[userStore.vipLevel] || '免费用户'
})

const isVipUser = computed(() => userStore.vipLevel !== 'free')

/** 套餐包过期提示 */
const packExpireHint = computed(() => {
  const pack = quotaStore.nextPack
  if (!pack) return ''
  const seconds = pack.expire_in_seconds
  if (seconds <= 0) return '已过期'
  if (seconds < 86400) return `${Math.ceil(seconds / 3600)}h`
  return `${Math.ceil(seconds / 86400)}天`
})

/** 套餐包名称提示（如 "尽兴包·3次"） */
const packNameHint = computed(() => {
  const pack = quotaStore.nextPack
  if (!pack) return ''
  return `${pack.pack_name}·${pack.remaining_tasks}次`
})

const levelIcon = computed(() => {
  const map: Record<string, string> = {
    free: '○',
    vip1: '💡',
    vip2: '✨',
    vip3: '★',
  }
  return map[userStore.vipLevel] || '○'
})

const expireDate = computed(() => {
  const d = userStore.userInfo?.member_expire_date
  if (!d) return ''
  return d.split('T')[0]
})

onMounted(() => {
  // P1-05 修复：去掉未登录自动 mock 登录
  // - 旧逻辑：未登录就静默自动 mock 登录 → 用户看到"假"的"已登录"UI
  //   → 测试/演示场景很有用，但生产环境会让用户以为已登录
  // - 新逻辑：未登录就保持未登录 UI，让用户主动点登录按钮
  //   若需演示自动登录，请在 config 中显式开启（开发期可用 ENABLE_AUTO_MOCK_LOGIN）
  if (userStore.isLoggedIn) {
    quotaStore.fetchQuota().catch(() => {})
  }
})

function onLogin() {
  uni.showLoading({ title: '登录中...', mask: true })
  userStore.loginByWechat().then((ok) => {
    uni.hideLoading()
    if (ok) {
      quotaStore.fetchQuota()
      uni.showToast({ title: '登录成功', icon: 'success' })
    } else {
      uni.showToast({ title: '登录失败，请重试', icon: 'none' })
    }
  })
}

function onLogout() {
  uni.showModal({
    title: '确认退出',
    content: '退出后将无法查看订单和 VIP 权益，确定退出吗？',
    success: (res) => {
      if (res.confirm) {
        userStore.logout()
        uni.showToast({ title: '已退出登录', icon: 'success' })
      }
    },
  })
}

function goHistory() {
  uni.switchTab({ url: '/pages/history/history' })
}

function goQuota() {
  uni.navigateTo({ url: '/pages/quota/quota' })
}

function onContactService() {
  uni.showModal({ title: '客服', content: '客服微信：travel-ai-support', showCancel: false })
}

function onFeedback() {
  uni.showModal({ title: '意见反馈', content: '请发送至 feedback@travelphotoai.com', showCancel: false })
}

function onAbout() {
  uni.showModal({
    title: '关于图轻松',
    content: '图轻松 v0.3.0\n轻松搞定朋友圈图文，就用图轻松\n© 2026 tu-song.com',
    showCancel: false,
  })
}
</script>

<style lang="scss" scoped>
@import '@/uni.scss';

.page-mine {
  min-height: 100vh;
  background: $bg-secondary;
}

.header-bg {
  position: relative;
  height: 320rpx;
  // 顶部渐变背景：浅橙
  background:
    radial-gradient(circle at 20% 30%, rgba(255,204,128,0.35) 0%, transparent 50%),
    radial-gradient(circle at 85% 70%, rgba(251,140,0,0.30) 0%, transparent 50%),
    linear-gradient(135deg, $primary-light 0%, $primary 45%, $primary-dark 100%);
  overflow: hidden;
}

/* ============ 装饰：白色翅膀花纹（代表梦想） ============ */
.wing {
  position: absolute;
  width: 110rpx;
  height: 160rpx;
  opacity: 0.45;
  pointer-events: none;
}

.wing-left {
  top: 30%;
  left: 8%;
  transform: rotate(-15deg);
}

.wing-right {
  top: 30%;
  right: 8%;
  transform: rotate(15deg) scaleX(-1);
}

.feather {
  position: absolute;
  background: rgba(255, 255, 255, 0.85);
  border-radius: 50% 50% 50% 50% / 60% 60% 40% 40%;
  box-shadow: 0 2rpx 6rpx rgba(255, 255, 255, 0.4);
}

.feather-1 { width: 48rpx; height: 80rpx; top: 40rpx; left: 16rpx; transform: rotate(-8deg); }
.feather-2 { width: 44rpx; height: 72rpx; top: 24rpx; left: 40rpx; transform: rotate(8deg); }
.feather-3 { width: 40rpx; height: 64rpx; top: 16rpx; left: 62rpx; transform: rotate(20deg); }

/* 用户卡片：悬浮在 header-bg 之上 */
.user-card {
  position: relative;
  margin: -180rpx $spacing-md $spacing-md;
  padding: $spacing-lg;
  background: $bg-primary;
  border-radius: $radius-lg;
  box-shadow: $shadow-md;
  z-index: 2;
}

.avatar-section {
  display: flex;
  align-items: center;
  gap: $spacing-md;
  margin-bottom: $spacing-md;
}

.avatar {
  width: 120rpx;
  height: 120rpx;
  border-radius: 50%;
  background: linear-gradient(135deg, $primary 0%, $secondary 100%);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  box-shadow: 0 4rpx 12rpx rgba(255,167,38,0.35);
}

.avatar-text {
  font-size: 48rpx;
  color: #fff;
  font-weight: 600;
}

.user-info {
  flex: 1;
  min-width: 0;
}

.user-name {
  display: block;
  font-size: $font-size-lg;
  font-weight: 600;
  color: $text-primary;
  margin-bottom: 6rpx;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.user-level {
  display: inline-flex;
  align-items: center;
  gap: 4rpx;
  padding: 4rpx 14rpx;
  background: rgba($primary, 0.1);
  color: $primary;
  font-size: $font-size-sm;
  border-radius: $radius-sm;
  font-weight: 500;

  .level-icon {
    font-size: $font-size-sm;
  }
}

/* 登录 / 退出 按钮 */
.login-btn,
.logout-btn {
  padding: $spacing-sm 0;
  text-align: center;
  border-radius: $radius-md;
  font-size: $font-size-md;
  font-weight: 500;
  letter-spacing: 1rpx;
}

.login-btn {
  background: linear-gradient(135deg, $primary 0%, $primary-dark 100%);
  color: #fff;
  box-shadow: 0 4rpx 12rpx rgba(255,167,38,0.3);

  &:active {
    opacity: 0.9;
  }
}

.logout-btn {
  background: $bg-secondary;
  color: $text-secondary;
  border: 1rpx solid $border-color;

  &:active {
    background: $bg-tertiary;
  }
}

.container {
  padding: 0 $spacing-md;
}

/* VIP 状态卡（高亮） */
.vip-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: $spacing-md $spacing-lg;
  border-radius: $radius-lg;
  margin-bottom: $spacing-md;
  box-shadow: $shadow-sm;
  position: relative;
  overflow: hidden;

  &.is-vip {
    background: linear-gradient(135deg, $primary 0%, $primary-dark 100%);
    color: #fff;
  }

  &.is-free {
    background: linear-gradient(135deg, $primary-bg 0%, #F1F8E9 100%);
    color: $text-primary;
  }
}

.vip-left {
  display: flex;
  align-items: center;
  gap: $spacing-md;
  flex: 1;
  min-width: 0;
}

.vip-crown {
  font-size: 56rpx;
  line-height: 1;
}

.vip-info {
  display: flex;
  flex-direction: column;
  gap: 4rpx;
  min-width: 0;
}

.vip-title {
  font-size: $font-size-lg;
  font-weight: 700;
}

.vip-subtitle {
  font-size: $font-size-sm;
  opacity: 0.85;
}

.vip-right {
  display: flex;
  align-items: center;
  gap: 4rpx;
  flex-shrink: 0;
}

.vip-action {
  font-size: $font-size-sm;
  font-weight: 500;
  opacity: 0.95;
}

.vip-arrow {
  font-size: 36rpx;
  line-height: 1;
  opacity: 0.9;
}

/* 通用卡片 */
.card {
  background: $bg-primary;
  border-radius: $radius-lg;
  padding: $spacing-md;
  margin-bottom: $spacing-md;
  box-shadow: $shadow-sm;
}

/* 额度卡 */
.quota-card {
  .quota-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: $spacing-sm;
  }

  .quota-title {
    font-size: $font-size-md;
    font-weight: 600;
    color: $text-primary;
  }

  .quota-action {
    font-size: $font-size-sm;
    color: $primary;
  }

  .quota-row {
    display: flex;
    align-items: center;
    justify-content: space-around;
    padding: $spacing-sm 0;
  }

  .quota-stat {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 4rpx;
    flex: 1;
  }

  .quota-divider {
    width: 1rpx;
    height: 60rpx;
    background: $border-color;
  }

  .stat-num {
    font-size: 40rpx;
    font-weight: 700;
    color: $primary;
    line-height: 1;
  }

  .stat-label {
    font-size: $font-size-xs;
    color: $text-secondary;
  }
}

/* 菜单卡 */
.menu-card {
  padding: 0;
}

.menu-item {
  display: flex;
  align-items: center;
  gap: $spacing-sm;
  padding: $spacing-md $spacing-lg;
  border-bottom: 1rpx solid $border-color;

  &:last-child {
    border-bottom: none;
  }

  &:active {
    background: $bg-secondary;
  }

  .menu-icon {
    font-size: 40rpx;
    width: 56rpx;
    flex-shrink: 0;
    text-align: center;
  }

  .menu-content {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 4rpx;
  }

  .menu-text {
    font-size: $font-size-md;
    color: $text-primary;
    font-weight: 500;
  }

  .menu-desc {
    font-size: $font-size-xs;
    color: $text-secondary;
  }

  .menu-arrow {
    font-size: 36rpx;
    color: $text-tertiary;
    line-height: 1;
  }
}

.version-text {
  text-align: center;
  font-size: $font-size-xs;
  color: $text-tertiary;
  padding: $spacing-md 0;
}

/* 底部 tabBar 安全区 */
.tabbar-safe {
  height: 120rpx;
}
</style>
