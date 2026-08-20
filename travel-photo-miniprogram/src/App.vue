<script setup lang="ts">
// 必须在最顶部：修复 _global / __route__ 错误
import './polyfills'

import { onLaunch, onShow } from '@dcloudio/uni-app'
import { useUserStore } from '@/stores/user'
import { useQuotaStore } from '@/stores/quota'

onLaunch(() => {
  console.log('[App] 图轻松启动')
  // 初始化用户信息
  const userStore = useUserStore()
  const quotaStore = useQuotaStore()
  userStore.initFromStorage()
  quotaStore.fetchQuota()
})

onShow(() => {
  console.log('[App] App Show')
})
</script>

<style lang="scss">
@import '@/uni.scss';

page {
  background-color: $bg-secondary;
  font-family: -apple-system, BlinkMacSystemFont, 'PingFang SC',
    'Helvetica Neue', Helvetica, 'Microsoft YaHei', sans-serif;
  color: $text-primary;
  font-size: $font-size-base;
  line-height: 1.5;
}

view, text, image {
  box-sizing: border-box;
}

/* 通用容器 */
.container {
  min-height: 100vh;
  padding: 0 $spacing-md;
  background-color: $bg-secondary;
}

/* 通用按钮 */
.btn-primary {
  background: linear-gradient(135deg, $primary 0%, $primary-dark 100%);
  color: #fff;
  border-radius: $radius-md;
  font-size: $font-size-md;
  font-weight: 500;
  padding: $spacing-md 0;
  text-align: center;
  box-shadow: $shadow-md;
  border: none;

  &:active {
    opacity: 0.9;
    transform: scale(0.98);
  }

  &.disabled {
    background: $bg-tertiary;
    color: $text-tertiary;
    box-shadow: none;
  }
}

.btn-secondary {
  background: $bg-primary;
  color: $text-primary;
  border: 2rpx solid $border-color;
  border-radius: $radius-md;
  font-size: $font-size-md;
  padding: $spacing-md 0;
  text-align: center;

  &:active {
    background: $bg-secondary;
  }
}

/* 卡片 */
.card {
  background: $bg-primary;
  border-radius: $radius-lg;
  padding: $spacing-lg;
  box-shadow: $shadow-sm;
  margin-bottom: $spacing-md;
}

/* 标签 */
.tag {
  display: inline-block;
  padding: 4rpx 12rpx;
  border-radius: $radius-sm;
  font-size: $font-size-xs;
  background: $bg-tertiary;
  color: $text-secondary;

  &.tag-primary {
    background: rgba($primary, 0.1);
    color: $primary;
  }

  &.tag-success {
    background: rgba($success, 0.1);
    color: $success;
  }

  &.tag-warning {
    background: rgba($warning, 0.1);
    color: $warning;
  }
}
</style>
