<script setup lang="ts">
import { nextTick, onUnmounted, watch } from 'vue'
import { activeConfirmation, resolveConfirmation, resolveDialog } from './confirmation'

let previousFocus: HTMLElement | null = null

watch(activeConfirmation, async confirmation => {
  if (confirmation) {
    previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null
    await nextTick()
    document.querySelector<HTMLElement>('.centered-dialog__input, .confirmation-dialog__confirm')?.focus()
  } else {
    previousFocus?.focus()
    previousFocus = null
  }
})

function handleKeydown(event: KeyboardEvent) {
  if (event.key === 'Tab' && activeConfirmation.value) {
    const dialog = event.currentTarget as HTMLElement
    const controls = [...dialog.querySelectorAll<HTMLElement>('input:not([disabled]), textarea:not([disabled]), button:not([disabled])')]
    const first = controls[0]
    const last = controls[controls.length - 1]
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault()
      last?.focus()
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault()
      first?.focus()
    }
    return
  }
  if (event.key === 'Escape' && activeConfirmation.value) {
    event.stopPropagation()
    cancelActiveDialog()
  }
}

function cancelActiveDialog() {
  if (activeConfirmation.value?.kind === 'input') resolveDialog(null)
  else resolveConfirmation(false)
}

function submitActiveDialog() {
  const dialog = activeConfirmation.value
  if (dialog?.kind === 'input' && (!dialog.required || dialog.value.trim())) resolveDialog(dialog.value)
}

onUnmounted(() => { previousFocus = null })
</script>

<template>
  <Teleport to="body">
    <div v-if="activeConfirmation" class="confirmation-backdrop" @click.self="cancelActiveDialog" @keydown="handleKeydown">
      <section class="confirmation-dialog" :role="activeConfirmation.kind === 'confirm' ? 'alertdialog' : 'dialog'" aria-modal="true" aria-labelledby="confirmation-title" :aria-describedby="activeConfirmation.message ? 'confirmation-message' : undefined">
        <h2 id="confirmation-title">{{ activeConfirmation.title || '请确认' }}</h2>
        <p v-if="activeConfirmation.message" id="confirmation-message">{{ activeConfirmation.message }}</p>
        <form v-if="activeConfirmation.kind === 'input'" class="confirmation-dialog__form" @submit.prevent="submitActiveDialog">
          <textarea v-if="activeConfirmation.multiline" v-model="activeConfirmation.value" class="centered-dialog__input" :placeholder="activeConfirmation.placeholder" rows="8" @keydown.ctrl.enter.prevent="submitActiveDialog" @keydown.meta.enter.prevent="submitActiveDialog"></textarea>
          <input v-else v-model="activeConfirmation.value" class="centered-dialog__input" type="text" :placeholder="activeConfirmation.placeholder" @keydown.enter.prevent="submitActiveDialog" />
          <div class="confirmation-dialog__actions">
            <button class="confirmation-dialog__cancel" type="button" @click="cancelActiveDialog">{{ activeConfirmation.cancelLabel || '取消' }}</button>
            <button class="confirmation-dialog__confirm" :disabled="activeConfirmation.required && !activeConfirmation.value.trim()" type="submit">{{ activeConfirmation.confirmLabel || '确定' }}</button>
          </div>
        </form>
        <div v-else class="confirmation-dialog__actions">
          <button class="confirmation-dialog__cancel" type="button" @click="resolveConfirmation(false)">{{ activeConfirmation.cancelLabel || '取消' }}</button>
          <button class="confirmation-dialog__confirm" :class="{ danger: activeConfirmation.danger }" type="button" @click="resolveConfirmation(true)">{{ activeConfirmation.confirmLabel || '确定' }}</button>
        </div>
      </section>
    </div>
  </Teleport>
</template>

<style>
.confirmation-backdrop {
  position: fixed;
  z-index: 3000;
  inset: 0;
  display: grid;
  place-items: center;
  padding: 24px;
  background: rgb(20 24 32 / 38%);
  backdrop-filter: blur(3px);
}

.confirmation-dialog {
  width: min(100%, 440px);
  max-height: calc(100vh - 48px);
  padding: 28px;
  border: 1px solid var(--line, #e7e8eb);
  border-radius: 18px;
  background: var(--card, #fffefc);
  color: var(--ink, #3c322e);
  box-shadow: 0 24px 80px rgb(20 24 32 / 24%);
  overflow-y: auto;
}

.confirmation-dialog h2 {
  margin: 0;
  font-size: 19px;
  font-weight: 650;
}

.confirmation-dialog p {
  margin: 14px 0 26px;
  color: var(--muted, #6f625b);
  font-size: 15px;
  line-height: 1.7;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.confirmation-dialog__form {
  display: grid;
  gap: 20px;
}

.confirmation-dialog__form .centered-dialog__input {
  width: 100%;
  min-height: 42px;
  padding: 10px 12px;
  border: 1px solid var(--line, #e9dfd7);
  border-radius: 9px;
  background: var(--page, #fcfaf7);
  color: var(--ink, #3c322e);
  font: inherit;
  font-size: 14px;
  line-height: 1.6;
}

.confirmation-dialog__form textarea.centered-dialog__input {
  min-height: 190px;
  resize: vertical;
}

.confirmation-dialog__actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}

.confirmation-dialog__actions button {
  min-width: 88px;
  min-height: 40px;
  padding: 0 17px;
  border: 1px solid var(--line, #e9dfd7);
  border-radius: 10px;
  background: var(--card, #fffefc);
  color: var(--ink, #3c322e);
  font: inherit;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
}

.confirmation-dialog__actions .confirmation-dialog__confirm {
  border-color: var(--accent, #965540);
  background: var(--accent, #965540);
  color: #fff;
}

.confirmation-dialog__actions .confirmation-dialog__confirm.danger {
  border-color: #c94b4b;
  background: #c94b4b;
}

.confirmation-dialog__actions button:focus-visible {
  outline: 3px solid rgb(79 103 220 / 28%);
  outline-offset: 2px;
}

.confirmation-dialog__actions button:disabled {
  cursor: not-allowed;
  opacity: .5;
}
</style>
