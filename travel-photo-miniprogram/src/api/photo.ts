/**
 * 照片上传API
 */
import { request } from './request'

export interface StsCredential {
  tmp_secret_id: string
  tmp_secret_key: string
  session_token: string
  expired_time: number
  start_time: number
  bucket: string
  region: string
  upload_host: string
  upload_dir: string
  file_path: string
  url_prefix: string
  presigned_url: string
  object_key: string
}

export interface UploadedPhoto {
  file_id: string
  url: string
  thumbnail_url: string
  size: number
  width: number
  height: number
}

/**
 * 申请上传凭证（STS）
 */
export function getUploadCredential(fileCount: number): Promise<StsCredential> {
  return request<StsCredential>({
    url: `/api/v1/photos/sts?file_count=${fileCount}`,
    method: 'GET',
  })
}

/**
 * 获取预签名上传 URL
 */
export function getPresignedUrl(objectKey: string): Promise<{
  presigned_url: string
  object_key: string
  access_url: string
}> {
  return request({
    url: '/api/v1/photos/presign',
    method: 'POST',
    data: { object_key: objectKey },
  })
}

/**
 * 上传完成后回传文件信息
 */
export function confirmUpload(payload: {
  file_id: string
  url: string
  size: number
  width?: number
  height?: number
}): Promise<UploadedPhoto> {
  return request<UploadedPhoto>({
    url: '/api/v1/photos/confirm',
    method: 'POST',
    data: payload,
  })
}

/**
 * 确认下载（保存）精修图
 *
 * 用户把精修图保存到相册后调用，后端据此立即删除 COS 中的原图，
 * 以支持「先看原图/精修图对比，再清理原图」的存储策略。幂等。
 */
export function confirmDownload(photoId: string): Promise<{
  photo_id: string
  original_deleted: boolean
}> {
  return request({
    url: `/api/v1/photos/${photoId}/download`,
    method: 'POST',
  })
}
