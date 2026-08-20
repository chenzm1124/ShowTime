/**
 * 任务Store - 当前正在进行的任务
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type {
  TaskStatus,
  TaskResult,
  CreateTaskPayload,
} from '@/api/task'
import * as taskApi from '@/api/task'
import { useQuotaStore } from './quota'

export const useTaskStore = defineStore('task', () => {
  const quotaStore = useQuotaStore()

  const currentTaskId = ref<string>('')
  const taskStatus = ref<TaskStatus | null>(null)
  const taskResult = ref<TaskResult | null>(null)
  const isProcessing = computed(() =>
    taskStatus.value?.status === 'pending' ||
    taskStatus.value?.status === 'processing'
  )
  const progress = computed(() => taskStatus.value?.progress || 0)

  /**
   * 「一键下载」勾选范围：photo_id 字符串集合
   *
   * 业务约定：
   * - 来自结果页（result.vue）多选框，跨页同步到朋友圈文案页（caption.vue）
   * - 默认全选所有精修照片
   * - 切换任务 / 重置时由 setTaskResult 兜底
   *
   * 使用 Set 是为了 O(1) 查找 + 不可变性（替换整个 set 触发响应式）
   */
  const selectedForDownload = ref<Set<string>>(new Set())

  // P0-6 修复：createAndProcess 重入锁
  // 用户在"开始 AI 处理"按钮连点/网络慢重复点时，会触发多次 createTask
  // → 重复扣额度、currentTaskId 被覆盖、多个 processTask 并发轮询同一个 task
  // 用 _creating 锁守住 createAndProcess 的入口即可
  let _creating = false

  function syncSelectedForDownloadToAll() {
    if (!taskResult.value) {
      selectedForDownload.value = new Set()
      return
    }
    selectedForDownload.value = new Set(
      (taskResult.value.selected_photos || []).map((p) => String(p.photo_id))
    )
  }

  function toggleSelectForDownload(photoId: string | number) {
    const id = String(photoId)
    const next = new Set(selectedForDownload.value)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    selectedForDownload.value = next
  }

  function selectAllForDownload() {
    syncSelectedForDownloadToAll()
  }

  function clearSelectForDownload() {
    selectedForDownload.value = new Set()
  }

  async function createAndProcess(payload: CreateTaskPayload): Promise<string> {
    // P0-6 修复：重入锁 - 连点/重复触发时第二次开始直接 return
    if (_creating) {
      console.warn('[taskStore] createAndProcess 已在进行中，拒绝重复触发')
      throw new Error('任务创建中，请稍候')
    }
    _creating = true
    try {
      return await _createAndProcessImpl(payload)
    } finally {
      _creating = false
    }
  }

  /**
   * 筛选预览（先筛选、再确认流程）
   * 调用 POST /tasks/preview，真实执行分组+评分去重，返回结果供确认页展示。
   * 不创建任务、不扣额度。
   */
  async function previewScreen(payload: { photo_urls: string[] }) {
    return await taskApi.previewScreen(payload)
  }

  async function _createAndProcessImpl(payload: CreateTaskPayload): Promise<string> {
    // 1. 创建任务（后端会原子扣减额度）
    const result = await taskApi.createTask(payload)
    const taskId = result.task_id
    currentTaskId.value = taskId

    // 2. 启动处理（捕获异常，避免未处理的 Promise Rejection）
    processTask(taskId).catch((err) => {
      console.error('[taskStore] processTask error', err)
      taskStatus.value = {
        task_id: taskId,
        status: 'failed',
        progress: taskStatus.value?.progress || 0,
        current_stage: 'screening',
        estimated_remaining_time: 0,
        processed_photos: 0,
        total_photos: 0,
      }
    })

    return taskId
  }

  /**
   * 处理任务 - 轮询后端状态
   *
   * 美图云修 Pro 回调可能很慢（实测 5-25 分钟），
   * 轮询上限 600 次 × 3s = 30 分钟；超时后不报错，
   * 让用户跳到历史记录页继续等待（回调到达后历史记录会刷新）。
   *
   * 修复：原 200×3s=10分钟 → 600×3s=30分钟
   * 原因：真实任务 50 跑了 24+ 分钟还没完，前端提前超时跳走
   */
  async function processTask(taskId: string) {
    let pollCount = 0
    const maxPoll = 600 // 30分钟（美图云修 Pro 实测 5-25分钟，加余量）
    let consecutiveErrors = 0
    const maxConsecutiveErrors = 5 // 连续失败5次才终止（容许网络抖动）

    while (pollCount < maxPoll) {
      try {
        const status = await taskApi.getTaskStatus(taskId)
        taskStatus.value = status
        consecutiveErrors = 0 // 成功后重置

        if (status.status === 'completed') {
          const result = await taskApi.getTaskResult(taskId)
          // 走 setTaskResult 路径 → 自动同步勾选范围为「全选」
          setTaskResult(result)
          // 后端创建任务时已原子扣减额度，这里只需刷新额度展示，避免前端重复扣减
          quotaStore.fetchQuota().catch(() => {})
          break
        }

        if (status.status === 'failed') {
          // 透传后端用户可见错误；无则回退通用文案
          const msg =
            (status as any)?.error_msg ||
            '图片批量处理筛选失败：无法正常筛选照片。'
          throw new Error(msg)
        }
} catch (err: any) {
      const errMsg = String(err?.message || err || '')
      console.error('[taskStore] poll error', err)

      // P1-XX 修复：识别「任务不存在 / 404」
      //
      // 典型触发场景：小程序 wx.login 失败 → userStore fallback 到 mock token
      // → 后端 ENABLE_MOCK_MODE 分支选 is_test=True 的第一个用户（id=1），
      // 但 task 实际是另一个 user_id（如 8）创建的 → /status 返回 404。
      //
      // 旧行为：连续 5 次 404 后 throw → catch 把 taskStatus=failed
      // → 用户在 processing 页卡住，看不到已完成的结果，体验差。
      //
      // 新行为：首次识别到 404 立即终止轮询、把 taskStatus 标记为 failed
      // → processing.vue 的 failed 分支统一引导用户去「历史记录」看结果
      // （数据是完整的，只是当前身份看不到）。
      if (errMsg.includes('任务不存在') || errMsg.includes('404')) {
        console.warn('[taskStore] task 不可访问（疑似 token/用户漂移），终止轮询')
        taskStatus.value = {
          ...(taskStatus.value || ({} as any)),
          task_id: taskId,
          status: 'failed' as const,
          progress: taskStatus.value?.progress || 0,
          current_stage: taskStatus.value?.current_stage || 'screening',
          estimated_remaining_time: 0,
          processed_photos: taskStatus.value?.processed_photos || 0,
          total_photos: taskStatus.value?.total_photos || 0,
        }
        return
      }

      consecutiveErrors++
      if (consecutiveErrors >= maxConsecutiveErrors) {
        throw err
      }
      await new Promise((r) => setTimeout(r, 5000))
      continue
    }

      pollCount++
      await new Promise((r) => setTimeout(r, 3000))
    }

    if (pollCount >= maxPoll) {
      // 不再 throw：让用户跳转到历史记录页，后端回调到达后历史记录会自动刷新
      console.warn('[taskStore] 轮询超时，跳转到历史记录继续等待')
      // 标记为"处理中"以便历史记录页做轮询
      taskStatus.value = {
        ...(taskStatus.value || ({} as any)),
        task_id: taskId,
        status: 'processing' as const,
        progress: taskStatus.value?.progress || 50,
        current_stage: 'retouching' as const,
        estimated_remaining_time: 0,
        processed_photos: taskStatus.value?.processed_photos || 0,
        total_photos: taskStatus.value?.total_photos || 0,
      }
    }
  }

  /**
   * 直接设置任务结果（用于历史记录复用结果页查看详情）
   *
   * 同时重置勾选范围：默认全选所有精修照片。
   */
  function setTaskResult(result: TaskResult) {
    currentTaskId.value = result.task_id
    taskResult.value = result
    taskStatus.value = null
    syncSelectedForDownloadToAll()
  }

  function reset() {
    currentTaskId.value = ''
    taskStatus.value = null
    taskResult.value = null
    selectedForDownload.value = new Set()
  }

  return {
    currentTaskId,
    taskStatus,
    taskResult,
    isProcessing,
    progress,
    selectedForDownload,
    createAndProcess,
    previewScreen,
    processTask,
    setTaskResult,
    reset,
    toggleSelectForDownload,
    selectAllForDownload,
    clearSelectForDownload,
  }
})
