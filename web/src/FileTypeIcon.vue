<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import AppIcon from './AppIcon.vue'

const props = defineProps<{ extension?: string | null }>()
const failed = ref(false)
const icons: Record<string, string> = {
  md: 'file_type_markdown.svg',
  markdown: 'file_type_markdown.svg',
  doc: 'file_type_word.svg',
  docx: 'file_type_word.svg',
  xls: 'file_type_excel.svg',
  xlsx: 'file_type_excel.svg',
  pdf: 'file_type_pdf.svg',
  png: 'file_type_image.svg',
  jpg: 'file_type_image.svg',
  jpeg: 'file_type_image.svg',
  gif: 'file_type_image.svg',
  bmp: 'file_type_image.svg',
  webp: 'file_type_image.svg',
  tif: 'file_type_image.svg',
  tiff: 'file_type_image.svg',
  ico: 'file_type_image.svg',
}
const source = computed(() => {
  const filename = icons[props.extension?.toLowerCase() || '']
  return filename ? `/file-icons/${filename}` : ''
})
watch(source, () => { failed.value = false })
</script>

<template>
  <img v-if="source && !failed" class="file-type-icon" :src="source" alt="" aria-hidden="true" @error="failed = true" />
  <AppIcon v-else name="note" />
</template>
