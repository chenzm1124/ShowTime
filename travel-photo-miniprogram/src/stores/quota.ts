/**
 * 额度Store
 *
 * 处理路径优先级（产品决策）：
 *   1. VIP 会员（vip1/vip2/vip3）按日限速
 *   2. 次数套餐包（user_packs 中 ACTIVE 且未过期）
 *   3. 账号终身 1 次免费试用
 *   4. 当日 2 次看广告解锁
 *   5. 都没有 → 引导购买
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import * as quotaApi from '@/api/quota'
import type { QuotaInfo, VipPlan, QuotaPack, UserPackBrief } from '@/api/quota'
import { useUserStore } from './user'

export const useQuotaStore = defineStore('quota', () => {
  const userStore = useUserStore()

  const quota = ref<QuotaInfo | null>(null)
  const vipPlans = ref<VipPlan[]>([])
  const packs = ref<QuotaPack[]>([])
  const loading = ref(false)

  const memberType = computed(() => quota.value?.member_type || 'free')

  /** 跨天重置副作用：把 QuotaInfo 内的日期字段拨到今天 */
  function applyDailyReset() {
    if (!quota.value) return
    const today = new Date().toISOString().split('T')[0]
    if (quota.value.ad_unlock_date !== today) {
      quota.value.ad_unlock_date = today
      quota.value.ad_unlock_remaining_today = 2
      quota.value.ad_unlock_watched_today = 0
    }
    if (quota.value.vip_daily_date !== today) {
      quota.value.vip_daily_date = today
      quota.value.vip_daily_used = 0
    }
  }

  /** 试用剩余（账号终身 1 次） */
  const trialRemaining = computed(() => quota.value?.trial_remaining || 0)

  /** 广告解锁当日剩余（自动跨天重置） */
  const adRemainingToday = computed(() => {
    if (!quota.value) return 0
    applyDailyReset()
    return quota.value.ad_unlock_remaining_today
  })

  /** VIP 各等级每日次数上限 */
  const dailyLimit = computed(() => {
    if (memberType.value === 'vip1') return 3
    if (memberType.value === 'vip2') return 5
    if (memberType.value === 'vip3') return 7
    return 0
  })

  /** VIP 当日已使用次数（跨天重置） */
  const dailyUsed = computed(() => {
    if (!quota.value) return 0
    applyDailyReset()
    return quota.value.vip_daily_used
  })

  /** VIP 当日剩余次数 */
  const dailyRemaining = computed(() => Math.max(0, dailyLimit.value - dailyUsed.value))

  /** 用户持有的所有有效包（含 ACTIVE+EXHAUSTED，UI 可决定是否显示"已用完"） */
  const userPacks = computed<UserPackBrief[]>(() => quota.value?.user_packs || [])

  /** 可用的包（status=active + 未过期 + 剩余次数 > 0），按 expire_at 升序 */
  const activePacks = computed<UserPackBrief[]>(() => {
    const now = Date.now()
    return userPacks.value
      .filter((p) => p.remaining_tasks > 0 && p.expire_in_seconds > 0 && new Date(p.expire_at).getTime() > now)
      .sort((a, b) => new Date(a.purchased_at).getTime() - new Date(b.purchased_at).getTime())
  })

  /** 最近一个要过期 / 剩余次数最少的包（扣减优先用这个，避免到期浪费） */
  const nextPack = computed<UserPackBrief | null>(() => activePacks.value[0] || null)

  /** 包剩余总次数（所有有效包相加） */
  const packBalance = computed(() => activePacks.value.reduce((sum, p) => sum + p.remaining_tasks, 0))

  /**
   * 当前路径下单次可处理的最大照片数（优先级：VIP > Pack > 试用/广告）
   * - vip1=50 / vip2=80 / vip3=150
   * - 有可用 pack 时，按 pack 的 photos_per_task 算（可叠加多个包时取最大值）
   * - 都没有（试用/广告）：固定 20
   */
  const currentTaskLimit = computed(() => {
    if (memberType.value === 'vip1') return 50
    if (memberType.value === 'vip2') return 80
    if (memberType.value === 'vip3') return 150
    // 免费用户：取所有有效包中张数上限最大的那个
    if (activePacks.value.length > 0) {
      return Math.max(...activePacks.value.map((p) => p.photos_per_task))
    }
    return 20
  })

  /** 当前生效的"处理配额来源"（用于 UI 展示和扣减路径） */
  const currentQuotaSource = computed<'vip' | 'pack' | 'trial' | 'ad' | 'none'>(() => {
    if (memberType.value !== 'free') return 'vip'
    if (activePacks.value.length > 0) return 'pack'
    if (trialRemaining.value > 0) return 'trial'
    if (adRemainingToday.value > 0) return 'ad'
    return 'none'
  })

  /** 是否还有可用次数 */
  const hasAvailableQuota = computed(() => currentQuotaSource.value !== 'none')

  /** 总剩余次数（粗略） */
  const totalRemaining = computed(() => {
    if (memberType.value !== 'free') return Infinity
    return packBalance.value + trialRemaining.value + adRemainingToday.value
  })

  async function fetchQuota() {
    if (!userStore.token) {
      quota.value = getDefaultQuota()
      return
    }
    loading.value = true
    try {
      quota.value = await quotaApi.getQuota()
      applyDailyReset()
    } catch (err) {
      console.warn('[quotaStore] fetchQuota error, use default', err)
      quota.value = getDefaultQuota()
    } finally {
      loading.value = false
    }
  }

  async function fetchVipPlans() {
    try {
      vipPlans.value = await quotaApi.getVipPlans()
    } catch (err) {
      console.warn('[quotaStore] fetchVipPlans error', err)
      vipPlans.value = getDefaultVipPlans()
    }
  }

  async function fetchPacks() {
    try {
      packs.value = await quotaApi.getQuotaPacks()
    } catch (err) {
      console.warn('[quotaStore] fetchPacks error', err)
      packs.value = getDefaultPacks()
    }
  }

  async function purchasePack(pack_code: 'daily' | 'enjoy' | 'unlimited') {
    const result = await quotaApi.purchasePack({ pack_code })
    // 购买成功后刷新（让 user_packs 拿到新记录）
    await fetchQuota()
    return result
  }

  async function watchAdForUnlock(payload: {
    ad_type: string
    ad_platform: string
    watch_duration_seconds: number
    ad_callback_data: any
  }) {
    const result = await quotaApi.adUnlock(payload)
    await fetchQuota()
    return result
  }

  /**
   * 检查 N 张照片是否可处理
   * 规则：
   * - 张数 <= currentTaskLimit
   * - VIP：dailyRemaining > 0
   * - 包：nextPack.remaining_tasks > 0
   * - 否则：trial / ad 至少一个有剩余
   */
  function canProcess(photoCount: number): { ok: boolean; reason?: string; needVip?: boolean; needPack?: boolean } {
    if (photoCount > currentTaskLimit.value) {
      return {
        ok: false,
        reason: `当前等级单次最多${currentTaskLimit.value}张，升级VIP或购买次数包可处理更多`,
        needVip: true,
        needPack: true,
      }
    }

    // VIP：校验当日次数
    if (memberType.value !== 'free') {
      if (dailyRemaining.value <= 0) {
        return { ok: false, reason: `今日VIP次数已用完（${dailyLimit.value}次/天），明天再来` }
      }
      return { ok: true }
    }

    // 免费用户：优先用包
    if (activePacks.value.length > 0) {
      // 张数校验：必须 <= 当前所有包中张数上限最大那个（已在 currentTaskLimit 保证）
      // 还要校验：nextPack 单次精修上限（如果有精修功能时再校验）
      return { ok: true }
    }

    if (trialRemaining.value > 0) return { ok: true }
    if (adRemainingToday.value > 0) return { ok: true }

    return { ok: false, reason: '免费次数已用完，请看广告、购买次数包或升级VIP' }
  }

  /**
   * 扣减一次（处理成功后）
   * reason='auto' 时按 currentQuotaSource 顺序自动决定（默认行为）
   * 业务方也可以显式指定 trial / ad / vip / pack
   */
  function consumeOne(reason?: 'trial' | 'ad' | 'vip' | 'pack' | 'auto') {
    if (!quota.value) return
    const actualReason = reason === 'auto' || !reason ? currentQuotaSource.value : reason

    if (actualReason === 'trial' && trialRemaining.value > 0) {
      quota.value.trial_remaining -= 1
      if (!quota.value.trial_first_used_date) {
        quota.value.trial_first_used_date = new Date().toISOString().split('T')[0]
      }
    } else if (actualReason === 'ad' && adRemainingToday.value > 0) {
      quota.value.ad_unlock_remaining_today -= 1
      quota.value.ad_unlock_watched_today += 1
    } else if (actualReason === 'vip' && memberType.value !== 'free') {
      // 触发 dailyUsed 的跨天重置副作用
      applyDailyReset()
      if (quota.value.vip_daily_used < dailyLimit.value) {
        quota.value.vip_daily_used += 1
      }
    } else if (actualReason === 'pack') {
      // 包的扣减需要后端配合（防本地脏数据导致的不一致），这里只做乐观扣减
      // 实际生产中建议 task 创建成功后由后端原子扣减 user_packs.remaining_tasks
      const target = nextPack.value
      if (target && target.remaining_tasks > 0) {
        target.remaining_tasks -= 1
      }
    }
  }

  return {
    // state
    quota,
    vipPlans,
    packs,
    loading,
    // getters
    memberType,
    currentTaskLimit,
    currentQuotaSource,
    trialRemaining,
    adRemainingToday,
    dailyLimit,
    dailyUsed,
    dailyRemaining,
    userPacks,
    activePacks,
    nextPack,
    packBalance,
    hasAvailableQuota,
    totalRemaining,
    // actions
    fetchQuota,
    fetchVipPlans,
    fetchPacks,
    purchasePack,
    watchAdForUnlock,
    canProcess,
    consumeOne,
  }
})

function getDefaultQuota(): QuotaInfo {
  return {
    member_type: 'free',
    trial_remaining: 1,
    trial_first_used_date: null,
    ad_unlock_remaining_today: 2,
    ad_unlock_watched_today: 0,
    ad_unlock_date: new Date().toISOString().split('T')[0],
    vip_expire_date: null,
    vip_daily_used: 0,
    vip_daily_date: new Date().toISOString().split('T')[0],
    current_quota: {
      photos_per_task: 20,
      photos_per_task_label: '20张/次',
    },
    monthly_used: 0,
    user_packs: [],
  }
}

function getDefaultVipPlans(): VipPlan[] {
  return [
    {
      level: 'vip1',
      name: '基础会员',
      price_monthly: 19.9,
      price_yearly: 199,
      photos_per_task: 50,
      daily_limit: 3,
      features: ['50张/次', '3次/天', '去水印', '在线客服'],
    },
    {
      level: 'vip2',
      name: '高级会员',
      price_monthly: 39.9,
      price_yearly: 399,
      photos_per_task: 80,
      daily_limit: 5,
      features: ['80张/次', '5次/天', '去水印', '优先客服', '加速50%'],
      highlight: true,
      badge: '推荐',
    },
    {
      level: 'vip3',
      name: '旗舰会员',
      price_monthly: 69.9,
      price_yearly: 699,
      photos_per_task: 150,
      daily_limit: 7,
      features: ['150张/次', '7次/天', '去水印', '专属客服', '加速100%', '永久历史'],
    },
  ]
}

function getDefaultPacks(): QuotaPack[] {
  return [
    {
      code: 'daily',
      name: '单次体验',
      description: '单次活动，1 次批量处理',
      price: 9.9,
      original_price: 14.9,
      task_quota: 1,
      photos_per_task: 30,
      max_refine_per_task: 6,
      valid_days: 30,
      features: ['1次批量处理', '30张/次', '6张精修', '30天有效'],
    },
    {
      code: 'enjoy',
      name: '月度畅用',
      description: '月度畅用，3 次批量处理',
      price: 19.9,
      original_price: 29.9,
      task_quota: 3,
      photos_per_task: 50,
      max_refine_per_task: 9,
      valid_days: 60,
      features: ['3次批量处理', '50张/次', '9张精修', '60天有效'],
      highlight: true,
      badge: '推荐',
    },
    {
      code: 'unlimited',
      name: '季度专属',
      description: '季度畅享，7 次批量处理',
      price: 39.9,
      original_price: 59.9,
      task_quota: 7,
      photos_per_task: 100,
      max_refine_per_task: 18,
      valid_days: 90,
      features: ['7次批量处理', '100张/次', '18张精修', '90天有效'],
      badge: '热销',
    },
  ]
}
