/**
 * 任务管理API
 */
import { request } from './request'

/**
 * 修图风格（前端"流行风格"选择）
 * - 'auto'        智能配风格（AI根据照片特征自动选最合适的）
 * - 'natural'     自然商务
 * - 'clean'       清透干净
 * - 'warm'        暖色调
 * - 'film'        胶片风
 * - 'fresh'       小清新
 */
export type RetouchStyle =
  | 'auto'
  | 'natural'
  | 'clean'
  | 'warm'
  | 'film'
  | 'fresh'

export interface TaskCreateOptions {
  /** 修图风格列表（前端可选 1-3 种） */
  retouch_styles: RetouchStyle[]
  /** 拍摄地点（让文案更精准） */
  location?: string
}

export interface CreateTaskPayload {
  photo_urls: string[]
  options: TaskCreateOptions
}

export interface CreateTaskResult {
  task_id: string
  status: 'pending' | 'processing' | 'completed' | 'failed'
  estimated_time: number
  quota_used: number
  quota_remaining: number | string
}

export interface PhotoStatusItem {
  photo_id: string
  original_url: string
  processed_url?: string | null
  thumbnail_url?: string | null
  status: 'processing' | 'completed' | 'failed'
  order_index: number
  is_retouch_failed?: boolean
}

export interface TaskStatus {
  task_id: string
  status: 'pending' | 'processing' | 'completed' | 'failed'
  progress: number
  current_stage: 'uploading' | 'screening' | 'retouching' | 'captioning' | 'completed'
  estimated_remaining_time: number
  processed_photos: number
  total_photos: number
  photos: PhotoStatusItem[]
  /** 任务失败时的用户可见错误信息（如筛选下载全部失败） */
  error_msg?: string | null
}

export interface PhotoGroup {
  group_id: number
  photos: SelectedPhoto[]
  group_type: 'portrait' // 仅人像类，不再区分风景
}

export interface SelectedPhoto {
  photo_id: string
  original_url: string
  processed_url: string
  thumbnail_url: string
  quality_score: number
  face_count: number
  type: 'portrait' // 该照片的分类（仅人像类，不再区分风景）
  /** 该照片实际应用的修图风格（auto 时由后端决策） */
  retouch_style?: RetouchStyle
  /** 修图风格中文标签（便于前端直接展示） */
  retouch_style_label?: string
  caption?: string
  cluster_group_id?: number
  rank_in_group?: number
}

export interface TaskResult {
  task_id: string
  status: string
  total_photos: number
  total_groups: number
  selected_photos: SelectedPhoto[]
  groups: PhotoGroup[]
  created_at: string
}

export interface PreviewDroppedPhoto {
  photo_id: string
  original_url: string
  order_index: number
}

export interface PreviewResult {
  total_photos: number
  total_groups: number
  selected_count: number
  dropped_count: number
  selected_photos: SelectedPhoto[]
  groups: PhotoGroup[]
  dropped_photos: PreviewDroppedPhoto[]
  /** 业务级可读错误（如筛选下载全失败）。存在时其它字段为空，前端应直接展示。 */
  error?: string | null
}

export interface PreviewPayload {
  photo_urls: string[]
}

/**
 * 创建处理任务
 */
export function createTask(payload: CreateTaskPayload): Promise<CreateTaskResult> {
  return request<CreateTaskResult>({
    url: '/api/v1/tasks',
    method: 'POST',
    data: payload,
    showLoading: true,
    loadingText: '创建任务...',
  })
}

/**
 * 筛选预览（先筛选、再确认流程）
 * 只做智能筛选（分组 + 评分排序），不精修、不扣额度
 */
export function previewScreen(payload: PreviewPayload): Promise<PreviewResult> {
  return request<PreviewResult>({
    url: '/api/v1/tasks/preview',
    method: 'POST',
    data: payload,
    showLoading: true,
    loadingText: '智能筛选中...',
  })
}

/**
 * 查询任务状态
 */
export function getTaskStatus(taskId: string): Promise<TaskStatus> {
  return request<TaskStatus>({
    url: `/api/v1/tasks/${taskId}/status`,
    method: 'GET',
  })
}

/**
 * 获取处理结果
 */
export function getTaskResult(taskId: string): Promise<TaskResult> {
  return request<TaskResult>({
    url: `/api/v1/tasks/${taskId}/result`,
    method: 'GET',
  })
}

export interface TaskHistoryItem {
  task_id: string
  status: string
  total_photos: number
  total_groups: number
  created_at: string
  thumbnail_url: string | null
}

/**
 * 获取处理历史
 */
export function getHistory(page = 1, pageSize = 20): Promise<{
  total: number
  list: TaskHistoryItem[]
}> {
  return request({
    url: `/api/v1/tasks?page=${page}&page_size=${pageSize}`,
    method: 'GET',
  })
}

/**
 * 重试精修：仅重跑任务中「精修失败」的照片（带 _retouch_failed 标记）。
 * 用于回调隧道抖动 / 美图限频导致的 callback_timeout 降级。
 */
export function retryRetouch(taskId: string): Promise<{
  retried: number
  message: string
}> {
  return request({
    url: `/api/v1/tasks/${taskId}/retry-retouch`,
    method: 'POST',
    showLoading: true,
    loadingText: '重新提交精修...',
  })
}

/**
 * 判断某张精修照片是否失败（后端降级为原图 + _retouch_failed 标记）。
 */
export function isRetouchFailed(photo: { processed_url?: string | null }): boolean {
  return !!photo.processed_url && photo.processed_url.includes('_retouch_failed=')
}

/**
 * 从 _retouch_failed=<reason> 中提取失败原因码
 */
export function retouchFailedReason(photo: { processed_url?: string | null }): string {
  const url = photo.processed_url || ''
  const idx = url.indexOf('_retouch_failed=')
  return idx >= 0 ? url.slice(idx + '_retouch_failed='.length).split('&')[0] : ''
}
