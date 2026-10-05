import { ref } from 'vue'

type DialogBase = {
  message?: string
  title?: string
  confirmLabel?: string
  cancelLabel?: string
  danger?: boolean
}

export type ConfirmationOptions = DialogBase
export type InputDialogOptions = DialogBase & {
  initialValue?: string
  placeholder?: string
  multiline?: boolean
  required?: boolean
}
export type ActiveDialog = (DialogBase & { kind: 'confirm' }) | (InputDialogOptions & { kind: 'input'; value: string })

export const activeConfirmation = ref<ActiveDialog | null>(null)

let settleDialog: ((result: boolean | string | null) => void) | null = null

export function askForConfirmation(options: ConfirmationOptions): Promise<boolean> {
  return askForDialog({ ...options, kind: 'confirm' }) as Promise<boolean>
}

export function askForInput(options: InputDialogOptions): Promise<string | null> {
  return askForDialog({ ...options, kind: 'input', value: options.initialValue || '' }) as Promise<string | null>
}

function askForDialog(options: ActiveDialog): Promise<boolean | string | null> {
  if (settleDialog) settleDialog(options.kind === 'confirm' ? false : null)
  activeConfirmation.value = options
  return new Promise(resolve => { settleDialog = resolve })
}

export function resolveDialog(result: boolean | string | null) {
  const settle = settleDialog
  settleDialog = null
  activeConfirmation.value = null
  settle?.(result)
}

export function resolveConfirmation(confirmed: boolean) {
  resolveDialog(confirmed)
}
