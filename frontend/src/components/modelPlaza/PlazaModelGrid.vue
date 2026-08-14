<template>
  <div>
    <!-- 模型卡片网格:一卡一模型,同名模型跨分组合并为一张卡(卡内列出各分组价格) -->
    <div class="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
      <button
        v-for="card in cards"
        :key="card.key"
        type="button"
        class="plaza-model-card group flex flex-col rounded-2xl border bg-white p-4 text-left shadow-card transition-all duration-200 ease-out-quart hover:-translate-y-0.5 hover:shadow-card-hover dark:bg-dark-800/60"
        :style="{ '--card-accent': platformAccentColor(card.platform) }"
        @click="openDetail(card)"
      >
        <!-- 头部:模型名(等宽)+ 平台图标 -->
        <div class="flex items-start justify-between gap-2">
          <div class="min-w-0 flex-1">
            <p class="truncate font-mono text-sm font-semibold text-gray-900 dark:text-white" :title="card.name">
              {{ card.name }}
            </p>
            <div class="mt-1 flex flex-wrap items-center gap-1.5">
              <span :class="['inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[11px] font-medium', platformBadgeLightClass(card.platform)]">
                <PlatformIcon :platform="card.platform as GroupPlatform" size="xs" />
                {{ platformLabel(card.platform) }}
              </span>
              <span
                v-if="card.billingMode !== 'token'"
                class="rounded-md bg-gray-100 px-1.5 py-0.5 text-[11px] font-medium text-gray-500 dark:bg-dark-700/70 dark:text-dark-300"
              >
                {{ card.billingMode === 'image' ? t('modelPlaza.table.perImage') : t('modelPlaza.table.perRequest') }}
              </span>
            </div>
          </div>
          <span class="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-xl text-[11px] font-bold tabular-nums text-white shadow-sm" :style="{ backgroundColor: platformAccentColor(card.platform) }">
            {{ card.rate }}x
          </span>
        </div>

        <!-- 价格区:最低输入/输出(跨分组取最优) -->
        <div class="mt-3 grid grid-cols-2 gap-2">
          <div class="rounded-lg bg-gray-50 px-2.5 py-2 dark:bg-dark-900/50">
            <p class="text-[10px] font-medium uppercase tracking-wide text-gray-400 dark:text-dark-500">{{ t('modelPlaza.table.input') }}</p>
            <p class="mt-0.5 truncate font-mono text-sm font-semibold tabular-nums text-gray-900 dark:text-gray-50">
              {{ card.inputLabel }}
            </p>
          </div>
          <div class="rounded-lg bg-gray-50 px-2.5 py-2 dark:bg-dark-900/50">
            <p class="text-[10px] font-medium uppercase tracking-wide text-gray-400 dark:text-dark-500">{{ t('modelPlaza.table.output') }}</p>
            <p class="mt-0.5 truncate font-mono text-sm font-semibold tabular-nums text-gray-900 dark:text-gray-50">
              {{ card.outputLabel }}
            </p>
          </div>
        </div>

        <!-- 底部:分组来源数量提示 -->
        <div class="mt-3 flex items-center justify-between border-t border-gray-100 pt-2.5 text-[11px] dark:border-dark-700/60">
          <span v-if="card.entries.length > 1" class="text-gray-400 dark:text-dark-500">
            {{ t('modelPlaza.card.groupsCount', { count: card.entries.length }) }}
          </span>
          <span v-else class="truncate text-gray-400 dark:text-dark-500">{{ card.entries[0].groupName }}</span>
          <span class="inline-flex items-center gap-0.5 text-gray-400 transition-colors group-hover:text-primary-500 dark:text-dark-500 dark:group-hover:text-primary-400">
            {{ t('modelPlaza.card.detail') }}
            <Icon name="chevronRight" size="xs" class="h-3 w-3 transition-transform group-hover:translate-x-0.5" />
          </span>
        </div>
      </button>
    </div>

    <!-- 详情弹层:该模型在全部可用分组下的完整价格 -->
    <transition name="modal">
      <div v-if="detailCard" class="modal-overlay" @click.self="closeDetail">
        <div class="modal-content max-w-2xl">
          <div class="modal-header">
            <div class="flex min-w-0 items-center gap-2.5">
              <PlatformIcon :platform="detailCard.platform as GroupPlatform" size="sm" />
              <h3 class="modal-title truncate font-mono">{{ detailCard.name }}</h3>
            </div>
            <button type="button" class="btn btn-ghost btn-icon" :aria-label="t('common.close')" @click="closeDetail">
              <Icon name="x" size="md" />
            </button>
          </div>
          <div class="modal-body space-y-3">
            <div
              v-for="entry in detailCard.entries"
              :key="entry.groupId"
              class="rounded-xl border border-gray-100 p-4 dark:border-dark-700/60"
            >
              <div class="flex flex-wrap items-center gap-2">
                <span class="text-sm font-semibold text-gray-900 dark:text-white">{{ entry.groupName }}</span>
                <span class="rounded-md bg-primary-50 px-1.5 py-0.5 font-mono text-[11px] font-semibold text-primary-600 dark:bg-primary-900/30 dark:text-primary-400">
                  {{ entry.effectiveRate }}x
                </span>
                <span
                  v-if="entry.isExclusive"
                  class="rounded-md bg-purple-50 px-1.5 py-0.5 text-[11px] font-medium text-purple-600 dark:bg-purple-900/20 dark:text-purple-400"
                >
                  {{ t('modelPlaza.badges.exclusive') }}
                </span>
              </div>
              <div class="mt-3 grid grid-cols-2 gap-x-4 gap-y-2 sm:grid-cols-3">
                <div>
                  <p class="text-[10px] font-medium uppercase tracking-wide text-gray-400 dark:text-dark-500">{{ t('modelPlaza.table.input') }}</p>
                  <p class="font-mono text-sm font-semibold tabular-nums text-gray-900 dark:text-gray-50">{{ entry.inputLabel }}</p>
                </div>
                <div>
                  <p class="text-[10px] font-medium uppercase tracking-wide text-gray-400 dark:text-dark-500">{{ t('modelPlaza.table.output') }}</p>
                  <p class="font-mono text-sm font-semibold tabular-nums text-gray-900 dark:text-gray-50">{{ entry.outputLabel }}</p>
                </div>
                <div v-if="entry.cacheWriteLabel || entry.cacheReadLabel">
                  <p class="text-[10px] font-medium uppercase tracking-wide text-gray-400 dark:text-dark-500">{{ t('modelPlaza.table.cache') }}</p>
                  <p class="font-mono text-xs tabular-nums text-gray-700 dark:text-gray-300">
                    <template v-if="entry.cacheWriteLabel">{{ t('modelPlaza.table.cacheWrite') }} {{ entry.cacheWriteLabel }}</template>
                    <template v-if="entry.cacheWriteLabel && entry.cacheReadLabel"> · </template>
                    <template v-if="entry.cacheReadLabel">{{ t('modelPlaza.table.cacheRead') }} {{ entry.cacheReadLabel }}</template>
                  </p>
                </div>
              </div>
              <!-- 官方参考价 -->
              <div v-if="entry.hasOfficial" class="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-dashed border-gray-200 pt-2 text-[11px] text-gray-400 dark:border-dark-700 dark:text-dark-500">
                <span>
                  {{ t('modelPlaza.table.officialPrice') }}:
                  <span class="font-mono">{{ entry.officialInputLabel }}</span> /
                  <span class="font-mono">{{ entry.officialOutputLabel }}</span>
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </transition>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import Icon from '@/components/icons/Icon.vue'
import PlatformIcon from '@/components/common/PlatformIcon.vue'
import { platformAccentColor, platformBadgeLightClass, platformLabel } from '@/utils/platformColors'
import { formatScaled } from '@/utils/pricing'
import { BILLING_MODE_TOKEN } from '@/constants/channel'
import type { ModelPlazaGroup } from '@/api/modelPlaza'
import type { GroupPlatform } from '@/types'

const props = defineProps<{
  groups: ModelPlazaGroup[]
}>()

const { t } = useI18n()

const PER_MILLION = 1_000_000
const MIN_DECIMALS = 2

interface ModelCardEntry {
  groupId: number
  groupName: string
  platform: string
  effectiveRate: number
  isExclusive: boolean
  inputLabel: string
  outputLabel: string
  cacheWriteLabel: string
  cacheReadLabel: string
  hasOfficial: boolean
  officialInputLabel: string
  officialOutputLabel: string
}

interface ModelCard {
  key: string
  name: string
  platform: string
  billingMode: string
  /** 跨分组最优(最低)倍率,卡片右上角徽章展示。 */
  rate: number
  inputLabel: string
  outputLabel: string
  entries: ModelCardEntry[]
}

function effectiveRate(g: ModelPlazaGroup): number {
  return g.user_rate_multiplier ?? g.rate_multiplier
}

function perMillion(value: number | null | undefined, rate: number): string {
  if (value == null) return '-'
  return formatScaled(value * rate, PER_MILLION, MIN_DECIMALS)
}

/** 展平分组 → 模型卡。同名模型跨分组合并,倍率升序(最优在前)。 */
const cards = computed<ModelCard[]>(() => {
  const map = new Map<string, ModelCard>()
  for (const g of props.groups) {
    const rate = effectiveRate(g)
    for (const m of g.models) {
      const billingMode = m.pricing?.billing_mode || 'token'
      const entry: ModelCardEntry = {
        groupId: g.id,
        groupName: g.name,
        platform: m.platform || g.platform,
        effectiveRate: rate,
        isExclusive: g.is_exclusive,
        inputLabel:
          billingMode === BILLING_MODE_TOKEN
            ? perMillion(m.pricing?.input_price, rate)
            : m.pricing?.per_request_price != null
              ? formatScaled(m.pricing.per_request_price * rate, 1, MIN_DECIMALS)
              : '-',
        outputLabel: billingMode === BILLING_MODE_TOKEN ? perMillion(m.pricing?.output_price, rate) : '-',
        cacheWriteLabel: perMillion(m.pricing?.cache_write_price, rate),
        cacheReadLabel: perMillion(m.pricing?.cache_read_price, rate),
        hasOfficial:
          m.official_pricing?.input_price != null || m.official_pricing?.output_price != null,
        officialInputLabel:
          m.official_pricing?.input_price != null
            ? formatScaled(m.official_pricing.input_price, PER_MILLION, MIN_DECIMALS)
            : '-',
        officialOutputLabel:
          m.official_pricing?.output_price != null
            ? formatScaled(m.official_pricing.output_price, PER_MILLION, MIN_DECIMALS)
            : '-'
      }
      const key = `${m.platform}:${m.name}`
      const existing = map.get(key)
      if (existing) {
        existing.entries.push(entry)
      } else {
        map.set(key, {
          key,
          name: m.name,
          platform: m.platform || g.platform,
          billingMode,
          rate,
          inputLabel: entry.inputLabel,
          outputLabel: entry.outputLabel,
          entries: [entry]
        })
      }
    }
  }
  const list = [...map.values()]
  for (const card of list) {
    // 跨分组取最优(最低)倍率与该倍率下的价格作为卡片摘要
    card.entries.sort((a, b) => a.effectiveRate - b.effectiveRate || a.groupName.localeCompare(b.groupName))
    const best = card.entries[0]
    card.rate = best.effectiveRate
    card.inputLabel = best.inputLabel
    card.outputLabel = best.outputLabel
  }
  list.sort((a, b) => a.name.localeCompare(b.name))
  return list
})

const detailCard = ref<ModelCard | null>(null)

function openDetail(card: ModelCard) {
  detailCard.value = card
  document.body.classList.add('modal-open')
}

function closeDetail() {
  detailCard.value = null
  document.body.classList.remove('modal-open')
}
</script>

<style scoped>
/* 卡片左侧的细色条按平台主色着色,悬停时显现——平台识别不靠猜 */
.plaza-model-card {
  border-color: color-mix(in srgb, var(--card-accent) 22%, transparent);
  position: relative;
  overflow: hidden;
}

.plaza-model-card::before {
  content: '';
  position: absolute;
  left: 0;
  top: 12%;
  bottom: 12%;
  width: 3px;
  border-radius: 0 999px 999px 0;
  background-color: var(--card-accent);
  opacity: 0.55;
  transition: opacity 200ms ease;
}

.plaza-model-card:hover::before {
  opacity: 1;
}

.plaza-model-card:hover {
  border-color: color-mix(in srgb, var(--card-accent) 45%, transparent);
}
</style>
