import { useMutation } from '@tanstack/react-query'
import { Loader2, ScanText } from 'lucide-react'
import { api, type PromptCheckInput } from '../api'

export function PromptCheck({ input }: { input: PromptCheckInput }) {
  const check = useMutation({
    mutationFn: async (snapshot: PromptCheckInput) => ({
      fingerprint: JSON.stringify(snapshot),
      issues: await api.checkPrompt(snapshot),
    }),
  })
  const current = JSON.stringify(input)
  const fresh = check.data?.fingerprint === current
  const validDuration = Number.isFinite(input.duration_seconds) && input.duration_seconds >= 0.5 && input.duration_seconds <= 60
  return (
    <div className="prompt-review">
      <button type="button" className="btn btn-sm" disabled={check.isPending || !validDuration}
        onClick={() => check.mutate({ ...input })}>
        {check.isPending ? <Loader2 size={15} className="spin" /> : <ScanText size={15} />}
        Revisar prompt H3
      </button>
      <p className="hint">Comprueba estructura, referencias y duración. Conserva tu texto y no genera video.</p>
      <div aria-live="polite">
        {check.error && <p className="notice warn">{check.error.message}</p>}
        {check.data && !fresh && <p className="hint">El borrador cambió. Vuelve a revisarlo.</p>}
        {fresh && check.data?.issues.map((issue, i) => (
          <p key={`${issue.code}-${i}`} className={`notice ${issue.severity === 'info' ? '' : 'warn'}`}>
            <span><strong>{issue.severity === 'error' ? 'Corregir' : issue.severity === 'warning' ? 'Revisar' : 'Nota'}:</strong> {issue.message}</span>
          </p>
        ))}
      </div>
    </div>
  )
}
