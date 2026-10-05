<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'

const props = defineProps<{ noteId: string; extension: string }>()
const message = ref('正在连接文档编辑服务…')
const usePdfFallback = ref(false)
const config = ref<Record<string, any> | null>(null)
let editor: { destroyEditor?: () => void } | null = null
let script: HTMLScriptElement | null = null

declare global {
  interface Window { DocsAPI?: { DocEditor: new (id: string, config: Record<string, any>) => { destroyEditor?: () => void } } }
}

onMounted(async () => {
  try {
    const response = await fetch(`/v1/notes/${props.noteId}/editor-config`, { credentials: 'same-origin' })
    const data = await response.json()
    if (!response.ok) throw new Error(data.detail || '无法获取编辑器配置')
    if (!data.available) {
      message.value = data.message
      usePdfFallback.value = props.extension === 'pdf'
      return
    }
    config.value = data
    script = document.createElement('script')
    script.src = data.api_url
    script.onload = () => {
      if (!window.DocsAPI) { message.value = '文档编辑器脚本加载失败'; return }
      const { api_url: _url, available: _available, ...editorConfig } = data
      editorConfig.events = {
        onAppReady: () => { message.value = '正在载入文件…' },
        onDocumentReady: () => { message.value = '' },
        onError: (event: { data?: { errorCode?: number; errorDescription?: string } }) => {
          const code = event.data?.errorCode
          const detail = event.data?.errorDescription
          message.value = `文档无法显示${code ? `（错误码 ${code}）` : ''}${detail ? `：${detail}` : '，请检查文件后重试'}`
          if (props.extension === 'pdf') {
            editor?.destroyEditor?.()
            editor = null
            usePdfFallback.value = true
          }
        },
      }
      message.value = '正在载入文件…'
      editor = new window.DocsAPI.DocEditor('onlyoffice-note-editor', { ...editorConfig, width: '100%', height: '100%' })
    }
    script.onerror = () => {
      message.value = '文档编辑服务暂不可用，请下载后编辑并重新上传'
      usePdfFallback.value = props.extension === 'pdf'
    }
    document.head.appendChild(script)
  } catch (error) {
    message.value = error instanceof Error ? error.message : '文档编辑器不可用'
    usePdfFallback.value = props.extension === 'pdf'
  }
})

onBeforeUnmount(() => { editor?.destroyEditor?.(); script?.remove() })
</script>

<template>
  <div class="office-note-editor">
    <div v-if="!usePdfFallback" class="onlyoffice-frame">
      <div id="onlyoffice-note-editor"></div>
      <p v-if="message" class="file-editor-message" role="status" aria-live="polite">{{ message }}</p>
    </div>
    <iframe v-else class="pdf-fallback" :src="`/v1/notes/${noteId}/file`" title="PDF 文件预览"></iframe>
  </div>
</template>

<style scoped>
.office-note-editor{width:100%;height:100%;min-height:0;display:flex;flex-direction:column}.onlyoffice-frame{position:relative;flex:1;min-height:0;overflow:hidden}.onlyoffice-frame>div:first-child{width:100%;height:100%}.file-editor-message{position:absolute;inset:0;display:grid;place-items:center;margin:0;padding:24px;background:#fff8eff2;color:#625d54;text-align:center;pointer-events:none}
.pdf-fallback{flex:1;width:100%;min-height:0;border:0;background:#eee}
</style>
