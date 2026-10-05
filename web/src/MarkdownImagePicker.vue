<script setup lang="ts">
import { nextTick, onMounted, ref } from 'vue'
import AppIcon from './AppIcon.vue'

type ImageNote = { id: string; title: string; file: { filename: string; extension: string } | null }
type ImagePage = { items: ImageNote[]; next_cursor: string | null }

const emit = defineEmits<{
  (event: 'close'): void
  (event: 'select', image: ImageNote): void
  (event: 'url'): void
}>()

const searchInput = ref<HTMLInputElement | null>(null)
const query = ref('')
const appliedQuery = ref('')
const images = ref<ImageNote[]>([])
const nextCursor = ref<string | null>(null)
const loading = ref(false)
const error = ref('')
let requestSequence = 0

async function loadImages(append = false) {
  if (loading.value && append) return
  const sequence = ++requestSequence
  loading.value = true
  error.value = ''
  const params = new URLSearchParams({ limit: '12', file_type: 'image' })
  if (appliedQuery.value) {
    params.set('q', appliedQuery.value)
    params.set('q_scope', 'title')
  }
  if (append && nextCursor.value) params.set('cursor', nextCursor.value)
  try {
    const response = await fetch(`/v1/notes?${params}`, { credentials: 'same-origin' })
    if (!response.ok) throw new Error(`加载图片失败（${response.status}）`)
    const page = await response.json() as ImagePage
    if (sequence !== requestSequence) return
    images.value = append ? [...images.value, ...page.items] : page.items
    nextCursor.value = page.next_cursor
  } catch (cause) {
    if (sequence === requestSequence) error.value = cause instanceof Error ? cause.message : '加载图片失败'
  } finally {
    if (sequence === requestSequence) loading.value = false
  }
}

function searchImages() {
  appliedQuery.value = query.value.trim()
  nextCursor.value = null
  images.value = []
  void loadImages()
}

onMounted(async () => {
  void loadImages()
  await nextTick()
  searchInput.value?.focus()
})
</script>

<template>
  <div class="image-picker-backdrop" @click.self="emit('close')">
    <section class="image-picker" role="dialog" aria-modal="true" aria-labelledby="image-picker-title" @keydown.esc.stop.prevent="emit('close')">
      <header class="image-picker-head">
        <div><h2 id="image-picker-title">插入图片</h2><p>选择知识库中已上传的图片，插入到当前 Markdown 笔记。</p></div>
        <button type="button" class="icon-button" aria-label="关闭图片选择" @click="emit('close')"><AppIcon name="close" /></button>
      </header>
      <form class="image-picker-search" @submit.prevent="searchImages">
        <input ref="searchInput" v-model="query" maxlength="150" aria-label="按标题搜索图片" placeholder="按图片标题搜索" />
        <button type="submit" class="quiet-button">搜索</button>
      </form>
      <div class="image-picker-body">
        <p v-if="error" class="image-picker-status" role="alert">{{ error }} <button type="button" class="text-link" @click="loadImages()">重试</button></p>
        <div v-if="images.length" class="image-picker-grid">
          <button v-for="image in images" :key="image.id" type="button" class="image-picker-item" :aria-label="`插入图片：${image.title || image.file?.filename || '无标题图片'}`" @click="emit('select', image)">
            <span class="image-picker-thumb"><img :src="`/v1/notes/${image.id}/file`" :alt="image.title || image.file?.filename || '图片'" loading="lazy" /></span>
            <strong :title="image.title || image.file?.filename">{{ image.title || image.file?.filename || '无标题图片' }}</strong>
            <small :title="image.file?.filename">{{ image.file?.filename }}</small>
          </button>
        </div>
        <p v-else-if="!loading && !error" class="image-picker-status">{{ appliedQuery ? '没有匹配的图片' : '知识库中还没有图片' }}</p>
        <p v-if="loading" class="image-picker-status">正在加载图片…</p>
        <button v-if="nextCursor && !loading" type="button" class="image-picker-more" @click="loadImages(true)">加载更多</button>
      </div>
      <footer class="image-picker-foot"><span>图片被删除或永久清除后，笔记中的引用将无法显示。</span><button type="button" class="text-link" @click="emit('url')">使用图片网址</button></footer>
    </section>
  </div>
</template>

<style scoped>
.image-picker-backdrop{position:fixed;z-index:40;inset:0;display:grid;place-items:center;padding:20px;background:#2d201b66}
.image-picker{display:flex;width:min(860px,100%);height:min(690px,calc(100dvh - 40px));flex-direction:column;overflow:hidden;border:1px solid var(--line);border-radius:16px;background:var(--page);box-shadow:0 24px 70px #2d201b33}
.image-picker-head{display:flex;align-items:flex-start;justify-content:space-between;gap:20px;padding:21px 24px 17px;border-bottom:1px solid var(--line)}
.image-picker-head h2{margin:0;font:400 24px 'Songti SC','Noto Serif CJK SC',serif}
.image-picker-head p{margin:7px 0 0;color:var(--muted);font-size:12px}
.image-picker-search{display:flex;gap:8px;padding:16px 24px;border-bottom:1px solid var(--line)}
.image-picker-search input{flex:1;min-width:0;height:37px;padding:0 11px;border:1px solid var(--line);border-radius:8px;background:white;color:var(--ink);font-size:12px}
.image-picker-body{min-height:0;flex:1;overflow:auto;padding:20px 24px}
.image-picker-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:13px}
.image-picker-item{display:flex;min-width:0;flex-direction:column;gap:5px;padding:8px;border:1px solid var(--line);border-radius:10px;background:white;color:var(--ink);text-align:left}
.image-picker-item:hover{border-color:var(--accent);background:#fffaf6}
.image-picker-thumb{display:grid;width:100%;height:130px;place-items:center;overflow:hidden;border-radius:6px;background:#f3eee9}
.image-picker-thumb img{width:100%;height:100%;object-fit:contain}
.image-picker-item strong,.image-picker-item small{width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.image-picker-item strong{font-size:12px}.image-picker-item small{color:var(--muted);font-size:10px}
.image-picker-status{margin:24px 0;color:var(--muted);font-size:12px;text-align:center}
.image-picker-more{display:block;min-height:35px;margin:20px auto 0;padding:0 16px;border:1px solid var(--line);border-radius:8px;background:white;color:var(--accent);font-size:12px}
.image-picker-foot{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:12px 24px;border-top:1px solid var(--line);color:var(--muted);font-size:11px}
@media(max-width:700px){.image-picker-grid{grid-template-columns:repeat(3,minmax(0,1fr))}.image-picker-thumb{height:110px}}
@media(max-width:480px){.image-picker-backdrop{padding:10px}.image-picker{height:calc(100dvh - 20px)}.image-picker-head,.image-picker-search,.image-picker-body,.image-picker-foot{padding-right:14px;padding-left:14px}.image-picker-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
</style>
