<template>
  <view class="photo-uploader">
    <!-- 已选照片网格 -->
    <view v-if="selectedPhotos.length > 0" class="photo-grid">
      <view
        v-for="(photo, index) in selectedPhotos"
        :key="index"
        class="photo-item"
      >
        <image
          class="photo-image"
          :src="photo.path"
          mode="aspectFill"
        />
        <view
          v-if="photo.uploading"
          class="photo-uploading"
        >
          <view class="loading-spinner" />
          <text class="uploading-text">{{ photo.progress }}%</text>
        </view>
        <view
          v-else-if="photo.failed"
          class="photo-failed"
          @click="onRetryOne(photo)"
        >
          <text class="fail-icon">!</text>
          <text class="retry-hint">点击重试</text>
        </view>
        <view
          v-else
          class="photo-success"
        >
          <text class="check-icon">✓</text>
        </view>
        <view
          class="photo-remove"
          @click="removePhoto(index)"
        >
          <text class="remove-icon">×</text>
        </view>
      </view>

      <!-- 添加按钮 -->
      <view
        v-if="!reachedLimit"
        class="photo-add"
        @click="handleAdd"
      >
        <text class="add-icon">+</text>
        <text class="add-text">添加</text>
        <text class="add-count">{{ selectedPhotos.length }}/{{ maxCount }}</text>
      </view>
    </view>

    <!-- 空状态 -->
    <view
      v-else
      class="empty-state"
      @click="handleAdd"
    >
      <view class="empty-icon">▣</view>
      <text class="empty-title">点击选择活动照片</text>
      <text class="empty-subtitle">支持选择 {{ maxCount }} 张，AI智能筛选+精修</text>
      <view class="empty-action">
        <text>从相册选择</text>
      </view>
    </view>

    <!-- 进度条 -->
    <view v-if="uploading" class="progress-section">
      <view class="progress-header">
        <text class="progress-label">上传中</text>
        <text class="progress-text">{{ uploadedCount }}/{{ selectedPhotos.length }}</text>
      </view>
      <view class="progress-bar">
        <view
          class="progress-fill"
          :style="{ width: `${uploadProgress}%` }"
        />
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { choosePhotos, batchUploadPhotos } from '@/utils/upload'

interface PhotoItem {
  path: string
  size: number
  uploading?: boolean
  failed?: boolean
  progress?: number
  url?: string
}

const props = defineProps<{
  maxCount: number
  modelValue: PhotoItem[]
}>()

const emit = defineEmits<{
  'update:modelValue': [photos: PhotoItem[]]
  'change': [photos: PhotoItem[]]
  'uploaded': [photos: PhotoItem[]]
}>()

const selectedPhotos = ref<PhotoItem[]>(props.modelValue || [])
const uploading = ref(false)
const uploadedCount = ref(0)

const reachedLimit = computed(() => selectedPhotos.value.length >= props.maxCount)
const uploadProgress = computed(() => {
  if (selectedPhotos.value.length === 0) return 0
  return Math.floor((uploadedCount.value / selectedPhotos.value.length) * 100)
})

watch(
  () => props.modelValue,
  (val) => {
    selectedPhotos.value = val || []
  },
  { deep: true }
)

async function handleAdd() {
  try {
    const remaining = props.maxCount - selectedPhotos.value.length
    const files = await choosePhotos(remaining)
    addPhotos(files)
  } catch (err) {
    console.warn('[PhotoUploader] choosePhotos error', err)
  }
}

function addPhotos(files: Array<{ path: string; size: number }>) {
  const newPhotos: PhotoItem[] = files.map((f) => ({
    path: f.path,
    size: f.size,
    uploading: true,
    progress: 0,
  }))
  selectedPhotos.value = [...selectedPhotos.value, ...newPhotos]
  emitChange()
  startUpload()
}

function removePhoto(index: number) {
  selectedPhotos.value.splice(index, 1)
  emitChange()
}

function emitChange() {
  emit('update:modelValue', selectedPhotos.value)
  emit('change', selectedPhotos.value)
}

async function startUpload() {
  if (selectedPhotos.value.length === 0) return
  uploading.value = true
  uploadedCount.value = 0

  try {
    const filesToUpload = selectedPhotos.value
      .filter((p) => p.uploading)
      .map((p) => ({ path: p.path, size: p.size }))

    await batchUploadPhotos(filesToUpload, {
      maxConcurrent: 3,
      onProgress: (progress) => {
        uploadedCount.value = progress.uploaded
      },
      onFileComplete: (file, result) => {
        const target = selectedPhotos.value.find((p) => p.path === file.path)
        if (target) {
          target.uploading = false
          target.progress = 100
          target.url = result.url
        } else {
          // 防御：极端情况下 path 不匹配（例如上传过程中用户移除照片），
          // 避免静默失败导致照片永远 loading
          console.warn('[PhotoUploader] onFileComplete 未找到目标照片', file.path)
        }
      },
      onFileError: (file) => {
        const target = selectedPhotos.value.find((p) => p.path === file.path)
        if (target) {
          target.uploading = false
          target.failed = true
        } else {
          console.warn('[PhotoUploader] onFileError 未找到目标照片', file.path)
        }
      },
    })

    const allUploaded = selectedPhotos.value
      .filter((p) => !p.failed)
      .map((p) => p.path)

    emit('uploaded', selectedPhotos.value)
  } catch (err) {
    console.error('[PhotoUploader] upload error', err)
    uni.showToast({ title: '上传失败，请重试', icon: 'none' })
  } finally {
    uploading.value = false
  }
}

defineExpose({
  getPhotos: () => selectedPhotos.value,
  retryFailed,
})

function retryFailed() {
  const failed = selectedPhotos.value.filter((p) => p.failed)
  if (failed.length === 0) return
  failed.forEach((p) => {
    p.failed = false
    p.uploading = true
  })
  emitChange()
  // P1-03 修复：重试后自动重新触发上传
  uni.showToast({ title: `正在重试 ${failed.length} 张`, icon: 'none' })
  startUpload()
}

// P1-03 修复：单张照片点击重试
function onRetryOne(photo: PhotoItem) {
  photo.failed = false
  photo.uploading = true
  photo.progress = 0
  emitChange()
  startUpload()
}

</script>

<style lang="scss" scoped>
@import '@/uni.scss';

.photo-uploader {
  width: 100%;
}

.photo-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: $spacing-sm;
}

.photo-item {
  position: relative;
  aspect-ratio: 1;
  border-radius: $radius-md;
  overflow: hidden;
  background: $bg-tertiary;

  .photo-image {
    width: 100%;
    height: 100%;
  }

  .photo-uploading,
  .photo-failed,
  .photo-success {
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    background: rgba(0, 0, 0, 0.5);
  }

  .photo-uploading {
    flex-direction: column;
    gap: $spacing-xs;
  }

  .loading-spinner {
    width: 40rpx;
    height: 40rpx;
    border: 4rpx solid rgba(255, 255, 255, 0.3);
    border-top-color: #fff;
    border-radius: 50%;
    animation: spin 1s linear infinite;
  }

  @keyframes spin {
    to { transform: rotate(360deg); }
  }

  .uploading-text,
  .fail-icon,
  .check-icon {
    color: #fff;
    font-size: $font-size-sm;
    font-weight: 600;
  }

  .check-icon {
    color: $success;
    font-size: 60rpx;
  }

  .fail-icon {
    color: #fff;
    font-size: 60rpx;
    background: $error;
    width: 60rpx;
    height: 60rpx;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
  }

  .photo-remove {
    position: absolute;
    top: 6rpx;
    right: 6rpx;
    width: 36rpx;
    height: 36rpx;
    background: rgba(0, 0, 0, 0.6);
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
  }

  .remove-icon {
    color: #fff;
    font-size: 28rpx;
    line-height: 1;
  }
}

.photo-add {
  aspect-ratio: 1;
  border: 2rpx dashed $border-color;
  border-radius: $radius-md;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  background: $bg-primary;
  gap: 4rpx;

  .add-icon {
    font-size: 60rpx;
    color: $primary;
    line-height: 1;
  }

  .add-text {
    font-size: $font-size-sm;
    color: $text-secondary;
  }

  .add-count {
    font-size: $font-size-xs;
    color: $text-tertiary;
  }
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 80rpx 0;
  background: $bg-primary;
  border-radius: $radius-lg;
  border: 2rpx dashed $border-color;

  .empty-icon {
    font-size: 100rpx;
    margin-bottom: $spacing-md;
  }

  .empty-title {
    font-size: $font-size-md;
    color: $text-primary;
    font-weight: 500;
    margin-bottom: $spacing-xs;
  }

  .empty-subtitle {
    font-size: $font-size-sm;
    color: $text-secondary;
    margin-bottom: $spacing-lg;
  }

  .empty-action {
    padding: $spacing-sm $spacing-xl;
    background: linear-gradient(135deg, $primary 0%, $primary-dark 100%);
    color: #fff;
    border-radius: $radius-md;
    font-size: $font-size-sm;
  }
}

.progress-section {
  margin-top: $spacing-md;
  padding: $spacing-md;
  background: $bg-primary;
  border-radius: $radius-md;

  .progress-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: $spacing-sm;
  }

  .progress-label {
    font-size: $font-size-sm;
    color: $text-secondary;
  }

  .progress-text {
    font-size: $font-size-sm;
    color: $primary;
    font-weight: 500;
  }

  .progress-bar {
    height: 8rpx;
    background: $bg-tertiary;
    border-radius: 4rpx;
    overflow: hidden;
  }

  .progress-fill {
    height: 100%;
    background: linear-gradient(90deg, $primary 0%, $secondary 100%);
    transition: width 0.3s ease;
  }
}
</style>
