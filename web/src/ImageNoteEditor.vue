<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'

const props = defineProps<{ noteId: string; version: number }>()
const imageSrc = ref('')
const imageWidth = ref(0)
const zoom = ref(100)
const loading = ref(true)
const loaded = ref(false)
const error = ref('')

function load() {
  loading.value = true
  loaded.value = false
  imageWidth.value = 0
  zoom.value = 100
  error.value = ''
  imageSrc.value = `/v1/notes/${props.noteId}/file?v=${Date.now()}`
}

function handleImageLoad(event: Event) {
  const image = event.currentTarget as HTMLImageElement
  imageWidth.value = image.naturalWidth
  loading.value = false
  loaded.value = true
}

function handleImageError() {
  loading.value = false
  loaded.value = false
  error.value = '图片加载失败，请检查文件是否可读取后刷新重试'
}

function changeZoom(amount: number) {
  zoom.value = Math.min(300, Math.max(25, zoom.value + amount))
}

onMounted(load)
watch(() => [props.noteId, props.version], load)
</script>

<template>
  <div class="image-note-viewer">
    <div class="image-view-toolbar" role="toolbar" aria-label="图片预览控制">
      <button class="zoom-button" type="button" :disabled="zoom <= 25" aria-label="缩小图片" title="缩小" @click="changeZoom(-10)">−</button>
      <input
        v-model.number="zoom"
        class="zoom-slider"
        type="range"
        min="25"
        max="300"
        step="5"
        aria-label="图片缩放比例"
        :disabled="!loaded"
      >
      <button class="zoom-button" type="button" :disabled="zoom >= 300" aria-label="放大图片" title="放大" @click="changeZoom(10)">+</button>
      <output class="zoom-value" aria-live="polite">{{ zoom }}%</output>
      <button class="zoom-reset" type="button" :disabled="!loaded || zoom === 100" @click="zoom = 100">重置</button>
    </div>
    <p v-if="error" class="image-view-error" role="alert">{{ error }}</p>
    <div class="image-preview-wrap">
      <p v-if="loading" class="image-view-status">正在加载图片…</p>
      <p v-else-if="!loaded" class="image-view-status">请检查上方提示，修复后重新打开图片</p>
      <img
        v-if="imageSrc"
        v-show="loaded"
        :src="imageSrc"
        class="image-preview"
        :style="{ width: `${Math.round(imageWidth * zoom / 100)}px` }"
        alt="图片预览"
        draggable="false"
        @load="handleImageLoad"
        @error="handleImageError"
      >
    </div>
  </div>
</template>

<style scoped>
.image-note-viewer{height:100%;min-height:0;display:flex;flex-direction:column;background:var(--editor-paper,#fff8ef)}
.image-view-toolbar{display:flex;align-items:center;justify-content:center;gap:10px;min-height:52px;padding:6px 16px;border-bottom:1px solid var(--line,#e5e5e2);color:var(--ink,#393633)}
.zoom-button,.zoom-reset{height:32px;border:1px solid var(--line,#ded8d0);border-radius:7px;background:#fffdf9;color:inherit;font:inherit;cursor:pointer}
.zoom-button{width:32px;font-size:19px;line-height:1}
.zoom-reset{padding:0 10px;font-size:12px}
.zoom-button:disabled,.zoom-reset:disabled{opacity:.4;cursor:default}
.zoom-slider{width:min(240px,32vw);accent-color:var(--accent,#276d5e);cursor:pointer}
.zoom-value{min-width:48px;color:#625b55;font-size:12px;font-variant-numeric:tabular-nums;text-align:right}
.image-preview-wrap{flex:1;min-height:0;overflow:auto;display:flex;align-items:flex-start;justify-content:center;padding:20px;background:#f2f2ef}
.image-preview{display:block;flex:none;height:auto;max-width:none;box-shadow:0 4px 20px #0002;background:white;user-select:none}
.image-view-error{margin:6px 18px;color:#a33}
.image-view-status{margin:0;padding:24px;color:#766c65;text-align:center}
@media(max-width:600px){.image-view-toolbar{gap:7px;padding-right:12px;padding-left:12px}.zoom-slider{width:min(180px,35vw)}.image-preview-wrap{justify-content:flex-start;padding:12px}}
</style>
