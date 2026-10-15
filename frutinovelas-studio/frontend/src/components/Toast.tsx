import { CheckCircle2, AlertTriangle, X } from 'lucide-react'
import { createContext, useCallback, useContext, useState, type ReactNode } from 'react'

type Toast = { id: number; kind: 'ok' | 'error'; text: string }
type ToastApi = { ok: (text: string) => void; error: (text: string) => void }

const Ctx = createContext<ToastApi | null>(null)

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<Toast[]>([])

  const remove = useCallback((id: number) => setItems((xs) => xs.filter((t) => t.id !== id)), [])
  const push = useCallback(
    (kind: Toast['kind'], text: string) => {
      const id = Date.now() + Math.random()
      setItems((xs) => [...xs.slice(-3), { id, kind, text }])
      window.setTimeout(() => remove(id), kind === 'error' ? 7000 : 3200)
    },
    [remove],
  )

  const api: ToastApi = {
    ok: (t) => push('ok', t),
    error: (t) => push('error', t),
  }

  return (
    <Ctx.Provider value={api}>
      {children}
      <div className="toasts" role="status" aria-live="polite">
        {items.map((t) => (
          <div key={t.id} className={`toast ${t.kind}`}>
            {t.kind === 'ok' ? <CheckCircle2 size={18} /> : <AlertTriangle size={18} />}
            <div style={{ flex: 1 }}>{t.text}</div>
            <button className="btn btn-ghost btn-icon btn-sm" onClick={() => remove(t.id)} aria-label="Cerrar aviso">
              <X size={14} />
            </button>
          </div>
        ))}
      </div>
    </Ctx.Provider>
  )
}

// eslint-disable-next-line react-refresh/only-export-components
export function useToast(): ToastApi {
  const ctx = useContext(Ctx)
  if (!ctx) throw new Error('useToast fuera de ToastProvider')
  return ctx
}
