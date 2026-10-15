import { useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react'

type Props = {
  title: string
  label: string
  initial?: string
  confirmText?: string
  placeholder?: string
  children?: ReactNode
  onSubmit: (value: string) => Promise<unknown> | void
  onClose: () => void
}

/** Diálogo con un campo de texto (crear/renombrar). */
export function PromptDialog({ title, label, initial = '', confirmText = 'Guardar', placeholder, children, onSubmit, onClose }: Props) {
  const [value, setValue] = useState(initial)
  const [busy, setBusy] = useState(false)
  const ref = useRef<HTMLInputElement>(null)

  useEffect(() => {
    ref.current?.focus()
    ref.current?.select()
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (!value.trim()) return
    setBusy(true)
    try {
      await onSubmit(value.trim())
      onClose()
    } catch {
      setBusy(false)
    }
  }

  return (
    <div className="backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <form className="card dialog" onSubmit={submit} role="dialog" aria-modal="true" aria-labelledby="dlg-title">
        <h2 id="dlg-title">{title}</h2>
        {children}
        <div className="field">
          <label htmlFor="dlg-input">{label}</label>
          <input
            id="dlg-input"
            ref={ref}
            className="input"
            value={value}
            maxLength={200}
            placeholder={placeholder}
            onChange={(e) => setValue(e.target.value)}
          />
        </div>
        <div className="dialog-actions">
          <button type="button" className="btn btn-ghost" onClick={onClose}>
            Cancelar
          </button>
          <button id="dlg-confirm" type="submit" className="btn btn-primary" disabled={busy || !value.trim()}>
            {confirmText}
          </button>
        </div>
      </form>
    </div>
  )
}

type ConfirmProps = {
  title: string
  text: ReactNode
  confirmText: string
  danger?: boolean
  onConfirm: () => Promise<unknown> | void
  onClose: () => void
}

export function ConfirmDialog({ title, text, confirmText, danger, onConfirm, onClose }: ConfirmProps) {
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <div className="backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="card dialog" role="alertdialog" aria-modal="true">
        <h2>{title}</h2>
        <div className="muted">{text}</div>
        <div className="dialog-actions">
          <button className="btn btn-ghost" onClick={onClose} autoFocus>
            Cancelar
          </button>
          <button
            className={danger ? 'btn btn-danger' : 'btn btn-primary'}
            disabled={busy}
            onClick={async () => {
              setBusy(true)
              try {
                await onConfirm()
                onClose()
              } catch {
                setBusy(false)
              }
            }}
          >
            {confirmText}
          </button>
        </div>
      </div>
    </div>
  )
}
