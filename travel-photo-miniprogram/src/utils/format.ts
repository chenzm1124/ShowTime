/**
 * 格式化工具
 */
export function formatPrice(price: number): string {
  return `¥${price.toFixed(price % 1 === 0 ? 0 : 1)}`
}

export function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes}B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)}KB`
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)}MB`
  return `${(bytes / 1024 / 1024 / 1024).toFixed(2)}GB`
}

export function formatRelativeTime(date: Date | string): string {
  const d = typeof date === 'string' ? new Date(date) : date
  const now = new Date()
  const diff = now.getTime() - d.getTime()
  const minutes = Math.floor(diff / 60000)
  const hours = Math.floor(diff / 3600000)
  const days = Math.floor(diff / 86400000)

  if (minutes < 1) return '刚刚'
  if (minutes < 60) return `${minutes}分钟前`
  if (hours < 24) return `${hours}小时前`
  if (days < 30) return `${days}天前`
  return d.toLocaleDateString('zh-CN')
}

export function truncateText(text: string, maxLen = 50): string {
  if (text.length <= maxLen) return text
  return text.slice(0, maxLen) + '...'
}

export function generateId(): string {
  return Date.now().toString(36) + Math.random().toString(36).slice(2, 8)
}

export function calculateDiscount(monthly: number, yearly: number): number {
  const fullYearMonthly = monthly * 12
  return Math.round((1 - yearly / fullYearMonthly) * 100)
}
