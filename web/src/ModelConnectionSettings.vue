<script setup lang="ts">
import { onMounted, ref } from 'vue'

type Connection = { configured: boolean; provider: string | null; model_name: string | null; key_masked: string | null; updated_at: string | null }
const emit = defineEmits<{ (e: 'status', configured: boolean): void }>()
const connection = ref<Connection | null>(null)
const modelName = ref<'deepseek-flash' | 'deepseek-v4-pro'>('deepseek-flash')
const apiKey = ref('')
const busy = ref(false)
const error = ref('')
const notice = ref('')

async function request<T>(path: string, method = 'GET', data?: unknown): Promise<T> {
  const response = await fetch(path, { method, credentials: 'same-origin', headers: data === undefined ? {} : { 'Content-Type': 'application/json' }, body: data === undefined ? undefined : JSON.stringify(data) })
  if (!response.ok) {
    let detail = `请求失败（${response.status}）`
    try { const payload = await response.json() as { detail?: string }; if (payload.detail) detail = payload.detail } catch { /* Keep status. */ }
    throw new Error(detail)
  }
  return response.status === 204 ? undefined as T : await response.json() as T
}

async function run(action: () => Promise<void>) {
  busy.value = true; error.value = ''; notice.value = ''
  try { await action() } catch (cause) { error.value = cause instanceof Error ? cause.message : '操作失败，请重试' }
  finally { busy.value = false }
}

async function loadConnection() {
  connection.value = await request<Connection>('/v1/model-connection')
  if (connection.value.model_name === 'deepseek-v4-pro') modelName.value = 'deepseek-v4-pro'
  emit('status', connection.value.configured)
}

function saveConnection() {
  void run(async () => {
    if (!apiKey.value.trim()) throw new Error('请输入 API Key')
    connection.value = await request<Connection>('/v1/model-connection', 'PUT', { api_key: apiKey.value.trim(), model_name: modelName.value })
    apiKey.value = ''
    emit('status', connection.value.configured)
    notice.value = '已保存'
  })
}

function testConnection() {
  void run(async () => {
    await request('/v1/model-connection/test', 'POST', { ...(apiKey.value.trim() ? { api_key: apiKey.value.trim() } : {}), model_name: modelName.value })
    notice.value = '连接成功'
  })
}

function deleteConnection() {
  if (!window.confirm('删除已保存的模型连接？')) return
  void run(async () => {
    await request<void>('/v1/model-connection', 'DELETE')
    apiKey.value = ''
    await loadConnection()
    notice.value = '已删除'
  })
}

onMounted(() => { void loadConnection().catch(cause => { error.value = cause instanceof Error ? cause.message : '连接状态读取失败' }) })
</script>

<template>
  <div class="model-config">
    <div class="model-config-status">{{ connection?.configured ? `已连接 · ${connection.key_masked || ''}` : '未配置' }}</div>
    <p>问题和相关笔记片段会发送至配置的模型。</p>
    <label>模型<select v-model="modelName"><option value="deepseek-flash">DeepSeek Flash</option><option value="deepseek-v4-pro">DeepSeek V4 Pro</option></select></label>
    <label>API Key<input v-model="apiKey" type="password" autocomplete="off" placeholder="填写 API Key" /></label>
    <div class="model-config-actions"><button class="accent-button" :disabled="busy || !apiKey.trim()" @click="saveConnection">保存</button><button class="quiet-button" :disabled="busy || (!connection?.configured && !apiKey.trim())" @click="testConnection">测试</button><button v-if="connection?.configured" class="danger" :disabled="busy" @click="deleteConnection">删除连接</button></div>
    <p v-if="error" class="model-config-error" role="alert">{{ error }}</p><p v-if="notice" class="model-config-notice" role="status">{{ notice }}</p>
  </div>
</template>
