/**
 * Mock数据服务 - 用于无后端时的本地演示
 * 模拟AI筛选、精修、文案生成的完整流程
 */

import type {
  TaskStatus,
  TaskResult,
  SelectedPhoto,
  PhotoGroup,
  RetouchStyle,
} from '@/api/task'

class MockService {
  private photoCounter = 0
  private captionBank: Record<string, string[]> = {
    professional: [
      '站上台的那一刻，所有准备都值得。',
      '分享的本质不是输出，是点燃。',
      '把专业讲清楚，是对听众最大的尊重。',
      '每一页 PPT 背后，都是十年功。',
      '一个人的分享，一群人的成长。',
      '今天在台上，我把最好的自己交出去了。',
    ],
    energetic: [
      '今天现场的能量，隔着屏幕都能感受到！✨',
      '一场好的分享，是所有人一起发光。',
      '看到大家认真记笔记的样子，一切都值了。',
      '今天的分享会，是我这个月最期待的一天！',
      '在座的每一个人，都是这个领域的行动派。',
      '原来有这么多人，和我关心一样的事。',
    ],
    warm: [
      '关上门，每个人都是彼此的老师。',
      '私董会结束，我带着三个答案和一群朋友离开。',
      '最深的链接，往往发生在最真诚的时刻。',
      '一群人，放下手机，认真听一个人讲他的故事。',
      '谢谢你愿意把困惑说出来，我们都懂。',
      '今天之后，我们都是彼此的智囊团。',
    ],
    minimal: [
      '会场。',
      '准备就绪。',
      '记录此刻。',
      '此刻，现场。',
      '…',
    ],
    reflective: [
      '一场分享下来，最大的收获是重新认识了自己。',
      '有些问题，要经历过才知道答案。',
      '在别人的故事里，读到了自己的影子。',
      '原来最好的部分，是分享结束后大家不走。',
      '如果这场活动会说话，它会先说什么？',
      '每一场活动，都是写给未来的自己。',
    ],
  }

  generateTaskId(): string {
    return 'task_' + Date.now() + '_' + Math.random().toString(36).slice(2, 8)
  }

  generatePhotoId(): string {
    return 'photo_' + (++this.photoCounter) + '_' + Date.now()
  }

  delay(ms: number): Promise<void> {
    return new Promise((r) => setTimeout(r, ms))
  }

  /**
   * 模拟AI处理流程
   * 1. 筛选（3秒）
   * 2. 精修（5秒）
   * 3. 文案（2秒）
   */
  async simulateProcessing(
    taskId: string,
    photoUrls: string[],
    onStatus: (status: TaskStatus) => void,
    onResult: (result: TaskResult) => void,
    retouchStyles: RetouchStyle[] = ['auto']
  ) {
    const stages: Array<{
      stage: TaskStatus['current_stage']
      duration: number
      progressStart: number
      progressEnd: number
    }> = [
      { stage: 'screening', duration: 3000, progressStart: 5, progressEnd: 40 },
      { stage: 'retouching', duration: 5000, progressStart: 40, progressEnd: 85 },
      { stage: 'captioning', duration: 2000, progressStart: 85, progressEnd: 100 },
    ]

    // 使用实际传入的照片数（不再硬编码 20）
    const totalPhotos = Math.max(1, photoUrls?.length || 0)

    // 初始状态
    onStatus({
      task_id: taskId,
      status: 'processing',
      progress: 0,
      current_stage: 'screening',
      estimated_remaining_time: 10,
      processed_photos: 0,
      total_photos: totalPhotos,
    })

    await this.delay(500)

    // 逐阶段处理
    for (const stage of stages) {
      const steps = 10
      const stepDuration = stage.duration / steps
      for (let i = 0; i < steps; i++) {
        const progress = stage.progressStart + (stage.progressEnd - stage.progressStart) * (i + 1) / steps
        const processed = Math.floor((progress / 100) * totalPhotos)
        onStatus({
          task_id: taskId,
          status: 'processing',
          progress: Math.floor(progress),
          current_stage: stage.stage,
          estimated_remaining_time: Math.floor((100 - progress) / 10),
          processed_photos: processed,
          total_photos: totalPhotos,
        })
        await this.delay(stepDuration)
      }
    }

    // 生成模拟结果（按 photoUrls 真实聚类 + 评分选 Top2 + 应用 retouch_styles）
    const result = this.generateMockResult(taskId, photoUrls, totalPhotos, retouchStyles)
    onResult(result)

    onStatus({
      task_id: taskId,
      status: 'completed',
      progress: 100,
      current_stage: 'completed',
      estimated_remaining_time: 0,
      processed_photos: totalPhotos,
      total_photos: totalPhotos,
    })
  }

  /**
   * 修图风格的中文标签映射
   */
  private readonly styleLabels: Record<RetouchStyle, string> = {
    auto:  '智能配',
    natural: '自然商务',
    clean:   '清透干净',
    warm:    '暖色调',
    film:    '胶片风',
    fresh:   '小清新',
  }

  /**
   * 智能配风格：依据照片类型自动选最合适风格
   * - 人物照 → 自然商务
   */
  private autoPickStyle(type: 'portrait'): RetouchStyle {
    return 'natural'
  }

  /**
   * 5 种修图风格的 SVG 滤镜效果（mock 用）
   * 真实实现应调用美图/醒图 API 对应模板
   */
  private applyRetouchStyle(
    baseUrl: string,
    style: RetouchStyle,
    index: number,
    type: 'portrait' = 'portrait'
  ): string {
    const styleConfig: Record<
      Exclude<RetouchStyle, 'auto'>,
      { filter: string; overlay: string; emoji: string; label: string }
    > = {
      natural: { filter: 'brightness(1.05) contrast(1.0) saturate(1.02)',  overlay: '#f5f5f5', emoji: '💼', label: '自然商务' },
      clean:   { filter: 'brightness(1.08) contrast(1.02) saturate(1.0)',  overlay: '#ffffff', emoji: '✨', label: '清透干净' },
      warm:    { filter: 'brightness(1.05) saturate(1.1) hue-rotate(5deg)', overlay: '#fff8ee', emoji: '🤝', label: '暖色调' },
      film:    { filter: 'contrast(1.15) saturate(0.85) sepia(0.1)',       overlay: '#f0e6d2', emoji: '🎞️', label: '胶片风' },
      fresh:   { filter: 'brightness(1.05) saturate(1.25) hue-rotate(-5deg)', overlay: '#e8f5e9', emoji: '🌸', label: '小清新' },
    }
    const cfg = styleConfig[style as Exclude<RetouchStyle, 'auto'>] || styleConfig.fresh
    // 为每张图叠加风格标签 + emoji + 滤镜色（用 SVG 模拟滤镜）
    const w = type === 'portrait' ? 600 : 800
    const h = type === 'portrait' ? 800 : 600
    const colorIndex = index % 8
    const baseColor = ['FF6B6B', '4ECDC4', 'FFE66D', '95E1D3', 'F38181', 'AA96DA', 'FCBAD3', 'FFFFD2'][colorIndex]
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}">
      <defs>
        <linearGradient id="g${index}${style}" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" style="stop-color:#${baseColor};stop-opacity:0.7"/>
          <stop offset="100%" style="stop-color:#${baseColor};stop-opacity:0.3"/>
        </linearGradient>
        <filter id="ft${index}${style}">
          <feColorMatrix type="matrix" values="${
            style === 'hk'    ? '1.3 0   0   0 0.1  0 1.3 0   0 0.1  0 0 1.3 0   0 0.1  0 0 0 1 0' :
            style === 'cyber' ? '1.2 0.1 0   0 0.05 0 1.1 0.1 0 0.05 0.1 0 1.3 0 0.05  0 0 0 1 0' :
            style === 'soft'  ? '1.05 0 0 0 0.05  0 1.05 0 0 0.05  0 0 1.05 0 0.05  0 0 0 1 0' :
            style === 'film'  ? '1.1 0 0 0 0.05  0 1.1 0 0 0.05  0 0 0.9 0 0.1  0 0 0 1 0' :
                                 '1.05 0 0 0 0  0 1.05 0 0 0  0 0 1.2 0 0  0 0 0 1 0'
          }"/>
        </filter>
      </defs>
      <rect width="100%" height="100%" fill="url(#g${index}${style})" filter="url(#ft${index}${style})"/>
      <text x="50%" y="30%" text-anchor="middle" font-size="${Math.min(w, h) * 0.28}" fill="white" opacity="0.85">${type === 'portrait' ? '👤' : '🏞️'}</text>
      <text x="50%" y="55%" text-anchor="middle" font-size="${Math.min(w, h) * 0.08}" fill="white" font-family="sans-serif" font-weight="600">${cfg.label}</text>
      <text x="50%" y="68%" text-anchor="middle" font-size="${Math.min(w, h) * 0.05}" fill="white" font-family="sans-serif" opacity="0.85">${cfg.emoji} ${cfg.label} · 已精修</text>
    </svg>`
    return `data:image/svg+xml;utf8,${encodeURIComponent(svg)}`
  }

  /**
   * 生成模拟处理结果
   * 流程：
   *  1. 对每张图片做"人脸检测"（mock 模拟）→ 标记 isPortrait
   *  2. 分别对人像、风景按内容相似度聚类
   *  3. 每组按综合质量评分（人像侧重表情动作，风景侧重构图光线）取 Top 1
   *  4. 按用户选择的 retouch_styles 决定精修风格（auto 时自动匹配）
   *  5. 输出：人像组 + 风景组混合显示
   */
  generateMockResult(
    taskId: string,
    photoUrls: string[],
    totalPhotos: number,
    retouchStyles: RetouchStyle[] = ['auto']
  ): TaskResult {
    // ---------- 1. 人脸检测（mock 模拟） ----------
    // 真实实现：RetinaFace / MTCNN 检测人脸数量
    // mock 简化：用 URL hash 模拟，~60% 概率含人脸
    const photoMeta = photoUrls.map((url, idx) => {
      let hash = 0
      for (let i = 0; i < url.length; i++) {
        hash = (hash * 17 + url.charCodeAt(i)) | 0
      }
      const faceCount = Math.abs(hash) % 3 === 0 ? 0 : (Math.abs(hash) % 3) + 1
      return { idx, url, faceCount }
    })

    // 统一按人像处理，不再区分风景
    const allPhotos = photoMeta

    // ---------- 2. 聚类 ----------
    const allFeatures = allPhotos.map((p) => this.urlToMockFeature(p.url))
    const allClusters = this.clusterByFeature(allFeatures, 0.85)

    // ---------- 3. 每组评分取 Top 1 ----------
    const groups: PhotoGroup[] = []
    const selected_photos: SelectedPhoto[] = []
    let groupIdx = 0

    // 统一按人像组处理
    allClusters.forEach((cluster) => {
      const group = this.buildGroup(
        cluster,
        allPhotos,
        photoUrls,
        groupIdx,
        retouchStyles
      )
      groups.push(group.group)
      selected_photos.push(...group.photos)
      groupIdx++
    })

    return {
      task_id: taskId,
      status: 'completed',
      total_photos: totalPhotos,
      total_groups: groups.length,
      selected_photos,
      groups,
      created_at: new Date().toISOString(),
    }
  }

  /**
   * 构建一个聚类组：对 cluster 内的图片评分，取 Top 2，
   * 并按 retouchStyles 决定每张图的实际修图风格
   */
  private buildGroup(
    cluster: number[],
    photos: Array<{ idx: number; url: string; faceCount: number }>,
    allUrls: string[],
    groupIdx: number,
    retouchStyles: RetouchStyle[] = ['auto']
  ): { group: PhotoGroup; photos: SelectedPhoto[] } {
    // 评分（人像侧重表情/动作，风景侧重构图/光线）
    const scored = cluster
      .map((localIdx) => {
        const photo = photos[localIdx]
        const quality = this.computeQualityScore(photo.url, photo.idx, type)
        return { ...photo, quality }
      })
      .sort((a, b) => b.quality - a.quality)
      .slice(0, 2)

    // 决定该组中每张图要用的修图风格
    const resolveStyle = (rankInGroup: number): RetouchStyle => {
      // auto 单独出现 → 自动匹配自然商务
      if (retouchStyles.length === 1 && retouchStyles[0] === 'auto') {
        return this.autoPickStyle('portrait')
      }
      // auto 与其它风格一起 → auto 占 1 份，其它按顺序补足
      if (retouchStyles.includes('auto')) {
        const nonAuto = retouchStyles.filter((s) => s !== 'auto')
        if (rankInGroup === 0 && retouchStyles[0] === 'auto') {
          return this.autoPickStyle('portrait')
        }
        return nonAuto[(rankInGroup - 1) % nonAuto.length] || this.autoPickStyle('portrait')
      }
      // 全部非 auto → 按 rank 循环
      return retouchStyles[rankInGroup % retouchStyles.length]
    }

    const groupPhotos: SelectedPhoto[] = scored.map((p, rankInGroup) => {
      const style = resolveStyle(rankInGroup)
      const label = this.styleLabels[style]
      return {
        photo_id: this.generatePhotoId(),
        original_url: p.url,
        // 真实环境会调用对应风格模板；mock 模式生成风格化 SVG
        processed_url:
          style === 'auto'
            ? p.url
            : this.applyRetouchStyle(p.url, style, p.idx, 'portrait'),
        thumbnail_url: p.url,
        quality_score: p.quality,
        face_count: p.faceCount,
        type: 'portrait' as const,
        retouch_style: style,
        retouch_style_label: label,
        caption: this.getRandomCaption('professional'),
        cluster_group_id: groupIdx,
        rank_in_group: rankInGroup + 1,
      }
    })

    return {
      group: {
        group_id: groupIdx,
        photos: groupPhotos,
        group_type: 'portrait' as const,
      },
      photos: groupPhotos,
    }
  }

  /**
   * Mock 特征向量：URL hash → 8 维归一化向量（模拟 CLIP 512 维）
   * 真实实现：CLIP ViT-B/32 → 512 维 embedding
   */
  private urlToMockFeature(url: string): number[] {
    let hash = 0
    for (let i = 0; i < url.length; i++) {
      hash = (hash * 31 + url.charCodeAt(i)) | 0
    }
    // 生成 8 维向量，每维度 [0, 1)
    const vec: number[] = []
    let h = Math.abs(hash) || 1
    for (let i = 0; i < 8; i++) {
      h = (h * 9301 + 49297) % 233280
      vec.push(h / 233280)
    }
    // L2 归一化
    const norm = Math.sqrt(vec.reduce((s, v) => s + v * v, 0)) || 1
    return vec.map((v) => v / norm)
  }

  /**
   * 按内容相似度聚类（并查集 + 阈值）
   * 两两计算余弦相似度，>= threshold 合并到同一组
   */
  private clusterByFeature(features: number[][], threshold: number): number[][] {
    const n = features.length
    if (n === 0) return []

    // 并查集
    const parent = new Array(n).fill(0).map((_, i) => i)
    const find = (x: number): number => {
      while (parent[x] !== x) {
        parent[x] = parent[parent[x]] // 路径压缩
        x = parent[x]
      }
      return x
    }
    const union = (x: number, y: number) => {
      const px = find(x),
        py = find(y)
      if (px !== py) parent[px] = py
    }

    // 两两计算相似度
    for (let i = 0; i < n; i++) {
      for (let j = i + 1; j < n; j++) {
        const sim = this.cosineSimilarity(features[i], features[j])
        if (sim >= threshold) union(i, j)
      }
    }

    // 收集每个 root 下的成员
    const groups: Record<number, number[]> = {}
    for (let i = 0; i < n; i++) {
      const root = find(i)
      if (!groups[root]) groups[root] = []
      groups[root].push(i)
    }

    return Object.values(groups)
  }

  /** 余弦相似度 */
  private cosineSimilarity(a: number[], b: number[]): number {
    let dot = 0,
      na = 0,
      nb = 0
    for (let i = 0; i < a.length; i++) {
      dot += a[i] * b[i]
      na += a[i] * a[i]
      nb += b[i] * b[i]
    }
    return dot / (Math.sqrt(na) * Math.sqrt(nb) + 1e-10)
  }

  /**
   * 综合质量评分（0-100）
   * 照片质量评估：清晰度+曝光+构图+表情+动作
   * 真实实现：拉普拉斯方差、直方图、FER 情绪识别、姿态估计等
   * mock 简化：URL hash 派生稳定分
   */
  private computeQualityScore(
    url: string,
    index: number,
    type: 'portrait' | 'landscape' = 'portrait'
  ): number {
    let hash = 0
    for (let i = 0; i < url.length; i++) {
      hash = (hash * 17 + url.charCodeAt(i)) | 0
    }
    // 基础分 60-95
    const base = 60 + (Math.abs(hash) % 36)
    const noise = Math.floor(Math.random() * 5) - 2
    return Math.max(50, Math.min(99, base + noise))
  }

  /**
   * 生成5个不同风格的候选文案
   */
  generateCaptionSuggestions(): Array<{
    id: string
    text: string
    style: string
    style_label: string
    emoji: string
  }> {
    const styles: Array<{ code: string; label: string; emoji: string }> = [
      { code: 'professional', label: '专业干练', emoji: '💼' },
      { code: 'energetic', label: '积极正能量', emoji: '✨' },
      { code: 'warm', label: '温暖有温度', emoji: '🤝' },
      { code: 'minimal', label: '简约高级', emoji: '⚪' },
      { code: 'reflective', label: '深度思考', emoji: '💡' },
    ]

    return styles.map((s) => ({
      id: 'cap_' + s.code,
      text: this.getRandomCaption(s.code),
      style: s.code,
      style_label: s.label,
      emoji: s.emoji,
    }))
  }

  private getRandomCaption(style: string): string {
    const bank = this.captionBank[style] || this.captionBank.professional
    return bank[Math.floor(Math.random() * bank.length)]
  }

  /**
   * 生成mock照片URL（使用本地SVG数据URI，避免模拟器跨域/域名白名单问题）
   * 注意：实际开发中应使用uni.chooseImage返回的本地临时路径
   */
  private getMockPhotoUrl(index: number, type: 'portrait' = 'portrait', retouched = false): string {
    const w = 600
    const h = 800
    const colors = ['FF6B6B', '4ECDC4', 'FFE66D', '95E1D3', 'F38181', 'AA96DA', 'FCBAD3', 'FFFFD2']
    const color = colors[index % colors.length]
    const emoji = '👤'
    const label = `照片 ${index + 1}`
    const suffix = retouched ? ' · 已精修' : ''
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}">
      <defs>
        <linearGradient id="g${index}" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" style="stop-color:#${color};stop-opacity:0.7"/>
          <stop offset="100%" style="stop-color:#${color};stop-opacity:0.3"/>
        </linearGradient>
      </defs>
      <rect width="100%" height="100%" fill="url(#g${index})"/>
      <text x="50%" y="35%" text-anchor="middle" font-size="${Math.min(w, h) * 0.3}" fill="white">${emoji}</text>
      <text x="50%" y="65%" text-anchor="middle" font-size="${Math.min(w, h) * 0.06}" fill="white" font-family="sans-serif">${label}${suffix}</text>
    </svg>`
    return `data:image/svg+xml;utf8,${encodeURIComponent(svg)}`
  }
}

export const mockService = new MockService()
