<template>
  <div class="space-y-6">
    <!-- Hero:标题 + 统计 + 大搜索框(独立形态);后台内嵌形态更紧凑 -->
    <div :class="embedded ? 'space-y-4' : 'space-y-5'">
      <div v-if="!embedded" class="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 class="text-2xl font-bold tracking-tight text-gray-900 dark:text-white sm:text-3xl">
            {{ t('modelPlaza.title') }}
          </h1>
          <p class="mt-1.5 text-sm text-gray-500 dark:text-dark-400">{{ t('modelPlaza.description') }}</p>
        </div>
        <!-- 统计:模型数 / 分组数 / 平台数 -->
        <div class="flex gap-6">
          <div v-for="s in stats" :key="s.label" class="text-right">
            <p class="text-2xl font-bold tabular-nums text-gray-900 dark:text-white">{{ s.value }}</p>
            <p class="text-xs text-gray-400 dark:text-dark-500">{{ s.label }}</p>
          </div>
        </div>
      </div>

      <!-- 全局价格说明(管理员配置,Markdown) -->
      <div
        v-if="descriptionHtml"
        class="plaza-description rounded-2xl border border-gray-100 bg-white px-5 py-4 text-sm shadow-card dark:border-dark-700/50 dark:bg-dark-800/50"
        v-html="descriptionHtml"
      ></div>

      <!-- 搜索 + 视图切换 -->
      <div class="flex flex-col gap-3 sm:flex-row sm:items-center">
        <div class="relative flex-1 sm:max-w-md">
          <Icon
            name="search"
            size="md"
            class="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-gray-400 dark:text-dark-500"
          />
          <input
            v-model="searchQuery"
            type="text"
            :placeholder="t('modelPlaza.filters.searchPlaceholder')"
            class="input py-2.5 pl-11 pr-10"
          />
          <button
            v-if="searchQuery"
            type="button"
            class="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 transition-colors hover:text-gray-600 dark:text-dark-500 dark:hover:text-gray-300"
            :aria-label="t('common.close')"
            @click="searchQuery = ''"
          >
            <Icon name="x" size="xs" class="h-4 w-4" />
          </button>
        </div>
        <div class="tabs flex-shrink-0 self-start sm:self-auto">
          <button type="button" class="tab" :class="{ 'tab-active': view === 'cards' }" @click="view = 'cards'">
            {{ t('modelPlaza.view.cards') }}
          </button>
          <button type="button" class="tab" :class="{ 'tab-active': view === 'table' }" @click="view = 'table'">
            {{ t('modelPlaza.view.table') }}
          </button>
        </div>
      </div>

      <!-- 平台筛选 chips(卡片视图与表格视图共用) -->
      <div class="flex flex-wrap items-center gap-2">
        <button
          v-for="p in ['all', ...platforms]"
          :key="`pf-${p}`"
          type="button"
          class="inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-40 disabled:grayscale"
          :class="platformChipClass(p)"
          :style="p === 'all' ? undefined : { '--chip-accent': platformAccentColor(p) }"
          @click="selectedPlatform = p"
        >
          <PlatformIcon v-if="p !== 'all'" :platform="p as GroupPlatform" size="xs" />
          {{ p === 'all' ? t('modelPlaza.filters.all') : platformLabel(p) }}
        </button>
      </div>

      <!-- 未登录提示 -->
      <p v-if="!isAuthenticated" class="flex items-center gap-1.5 text-xs text-gray-400 dark:text-dark-500">
        <Icon name="infoCircle" size="xs" class="h-3.5 w-3.5" />
        {{ t('modelPlaza.anonymousHint') }}
      </p>
    </div>

    <!-- 加载/错误/空 -->
    <div v-if="loading" class="flex min-h-[240px] items-center justify-center">
      <div class="h-8 w-8 animate-spin rounded-full border-2 border-primary-600/25 border-t-primary-600 dark:border-primary-400/25 dark:border-t-primary-400"></div>
    </div>
    <div
      v-else-if="error"
      class="rounded-2xl border border-red-200 bg-red-50 px-5 py-8 text-center text-sm text-red-600 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300"
    >
      {{ t('modelPlaza.loadFailed') }}
    </div>
    <template v-else>
      <!-- 卡片视图:全部模型平铺 -->
      <div v-if="view === 'cards'">
        <PlazaModelGrid v-if="filteredGroups.some((g) => g.models.length > 0)" :groups="filteredGroups" />
        <div
          v-else
          class="rounded-2xl border border-dashed border-gray-300 px-5 py-12 text-center text-sm text-gray-500 dark:border-dark-600 dark:text-dark-400"
        >
          {{ searchActive ? t('modelPlaza.noSearchResult') : t('modelPlaza.empty') }}
        </div>
      </div>

      <!-- 表格视图:分组分节的价格明细(原版) -->
      <template v-else>
        <div v-if="filteredGroups.length > 0" class="space-y-5">
          <PlazaGroupSection v-for="g in filteredGroups" :key="g.id" :group="g" />
        </div>
        <div
          v-else
          class="rounded-2xl border border-dashed border-gray-300 px-5 py-12 text-center text-sm text-gray-500 dark:border-dark-600 dark:text-dark-400"
        >
          {{ searchActive ? t('modelPlaza.noSearchResult') : t('modelPlaza.empty') }}
        </div>
      </template>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import Icon from '@/components/icons/Icon.vue'
import PlatformIcon from '@/components/common/PlatformIcon.vue'
import PlazaModelGrid from './PlazaModelGrid.vue'
import PlazaGroupSection from './PlazaGroupSection.vue'
import type { ModelPlazaResponse } from '@/api/modelPlaza'
import { platformAccentColor, platformLabel } from '@/utils/platformColors'
import type { GroupPlatform } from '@/types'
import { useAuthStore } from '@/stores/auth'

const props = defineProps<{
  response: ModelPlazaResponse | null
  loading: boolean
  error?: boolean
  /** 后台内嵌形态(AppLayout 内):隐藏页头与统计。 */
  embedded?: boolean
}>()

const { t } = useI18n()
const authStore = useAuthStore()
const isAuthenticated = computed(() => authStore.isAuthenticated)

const selectedPlatform = ref<string>('all')
const searchQuery = ref('')
const view = ref<'cards' | 'table'>('cards')

const searchActive = computed(() => searchQuery.value.trim() !== '')

const descriptionHtml = computed(() => {
  const md = props.response?.description?.trim()
  if (!md) return ''
  return DOMPurify.sanitize(marked.parse(md) as string)
})

const platforms = computed(() =>
  [...new Set((props.response?.groups ?? []).map((g) => g.platform).filter(Boolean))].sort()
)

const stats = computed(() => {
  const groups = props.response?.groups ?? []
  const modelNames = new Set<string>()
  let total = 0
  for (const g of groups) {
    for (const m of g.models) {
      total += 1
      modelNames.add(`${m.platform}:${m.name}`)
    }
  }
  return [
    { label: t('modelPlaza.stats.models'), value: modelNames.size },
    { label: t('modelPlaza.stats.groups'), value: groups.length },
    { label: t('modelPlaza.stats.platforms'), value: platforms.value.length }
  ]
})

function platformChipClass(p: string): string {
  if (p === 'all') {
    return selectedPlatform.value === 'all'
      ? 'bg-gradient-to-r from-primary-500 to-primary-600 text-white shadow-sm shadow-primary-500/30'
      : 'bg-white text-gray-600 ring-1 ring-inset ring-gray-200 hover:bg-gray-50 hover:text-gray-900 hover:ring-gray-300 dark:bg-dark-800/60 dark:text-dark-300 dark:ring-dark-700 dark:hover:bg-dark-800 dark:hover:text-white'
  }
  return selectedPlatform.value === p ? 'chip-tinted-active' : 'chip-tinted'
}

const filteredGroups = computed(() => {
  let groups = props.response?.groups ?? []
  if (selectedPlatform.value !== 'all') {
    groups = groups.filter((g) => g.platform === selectedPlatform.value)
  }
  // 模型名搜索:分组内只留命中的模型,整组无命中则隐藏该分组。
  const q = searchQuery.value.trim().toLowerCase()
  if (q) {
    groups = groups
      .map((g) => ({ ...g, models: g.models.filter((m) => m.name.toLowerCase().includes(q)) }))
      .filter((g) => g.models.length > 0)
  }
  return groups
})
</script>

<style scoped>
.chip-tinted {
  color: color-mix(in srgb, var(--chip-accent) 78%, black);
  background-color: color-mix(in srgb, var(--chip-accent) 9%, transparent);
  box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--chip-accent) 25%, transparent);
}

.chip-tinted:not(:disabled):hover {
  background-color: color-mix(in srgb, var(--chip-accent) 16%, transparent);
}

.dark .chip-tinted {
  color: color-mix(in srgb, var(--chip-accent) 72%, white);
  background-color: color-mix(in srgb, var(--chip-accent) 12%, transparent);
  box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--chip-accent) 30%, transparent);
}

.dark .chip-tinted:not(:disabled):hover {
  background-color: color-mix(in srgb, var(--chip-accent) 18%, transparent);
}

.chip-tinted-active {
  color: #fff;
  background-color: color-mix(in srgb, var(--chip-accent) 85%, black);
  box-shadow: 0 1px 2px 0 color-mix(in srgb, var(--chip-accent) 35%, transparent);
}

.chip-tinted-active:not(:disabled):hover {
  background-color: color-mix(in srgb, var(--chip-accent) 75%, black);
}

.dark .chip-tinted-active {
  background-color: color-mix(in srgb, var(--chip-accent) 80%, transparent);
}

.dark .chip-tinted-active:not(:disabled):hover {
  background-color: var(--chip-accent);
}

.plaza-description {
  line-height: 1.7;
  overflow-wrap: anywhere;
}

.plaza-description :deep(h1),
.plaza-description :deep(h2),
.plaza-description :deep(h3) {
  @apply mb-2 mt-3 font-semibold text-gray-900 first:mt-0 dark:text-white;
}

.plaza-description :deep(p) {
  @apply mb-2 text-gray-700 last:mb-0 dark:text-dark-200;
}

.plaza-description :deep(a) {
  @apply text-primary-600 underline underline-offset-4 hover:text-primary-700 dark:text-primary-300;
}

.plaza-description :deep(ul) {
  @apply mb-2 list-disc pl-5;
}

.plaza-description :deep(ol) {
  @apply mb-2 list-decimal pl-5;
}

.plaza-description :deep(li) {
  @apply mb-0.5 text-gray-700 dark:text-dark-200;
}

.plaza-description :deep(code) {
  @apply rounded bg-gray-100 px-1.5 py-0.5 font-mono text-xs dark:bg-dark-800;
}

.plaza-description :deep(blockquote) {
  @apply my-2 border-l-4 border-gray-300 pl-3 text-gray-600 dark:border-dark-600 dark:text-dark-300;
}
</style>
