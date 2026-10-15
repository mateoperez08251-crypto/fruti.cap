import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowRight, ChevronRight, Copy, History, Info, Loader2, RotateCcw, Save, Trash2, TriangleAlert } from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { api, ApiError, type Asset, type Scene } from '../api'
import { STATUS_LABEL } from '../labels'
import { ConfirmDialog } from './Dialogs'
import { ImageDrop, Lightbox } from './ImageDrop'
import { useToast } from './Toast'

type Draft = {
  title: string
  description: string
  prompt: string
  duration: string
  start: Asset | null
  end: Asset | null
  seedMode: 'random' | 'fixed'
  seed: string
}

const fromScene = (s: Scene): Draft => ({
  title: s.title,
  description: s.description,
  prompt: s.prompt,
  duration: String(s.duration_seconds),
  start: s.start_asset,
  end: s.end_asset,
  seedMode: s.parameters.seed_mode === 'fixed' ? 'fixed' : 'random',
  seed: s.parameters.seed != null ? String(s.parameters.seed) : '',
})

const ratio = (a: Asset | null) => (a?.width && a?.height ? a.width / a.height : null)

type Props = {
  scene: Scene
  index: number
  onDirtyChange: (dirty: boolean) => void
  onDuplicated: (s: Scene) => void
  onDeleted: () => void
}

export function SceneEditor({ scene, index, onDirtyChange, onDuplicated, onDeleted }: Props) {
  const qc = useQueryClient()
  const toast = useToast()
  const [draft, setDraft] = useState<Draft>(() => fromScene(scene))
  const [base, setBase] = useState<Scene>(scene)
  const [zoom, setZoom] = useState<Asset | null>(null)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [showHistory, setShowHistory] = useState(false)

  // Si la escena cambia desde fuera (otro guardado, MCP) y no hay cambios locales, sincroniza.
  // Con cambios locales se conserva la revisión base, así el guardado responde 409 en vez de sobrescribir.
  const clean = useMemo(() => fromScene(base), [base])
  const dirty = JSON.stringify(draft) !== JSON.stringify(clean)
  const [seenRevision, setSeenRevision] = useState(scene.revision)
  if (scene.revision !== seenRevision) {
    setSeenRevision(scene.revision)
    if (scene.revision > base.revision && !dirty) {
      setBase(scene)
      setDraft(fromScene(scene))
    }
  }
  useEffect(() => onDirtyChange(dirty), [dirty, onDirtyChange])

  const set = <K extends keyof Draft>(k: K, v: Draft[K]) => setDraft((d) => ({ ...d, [k]: v }))

  const duration = Number(draft.duration.replace(',', '.'))
  const durationOk = Number.isFinite(duration) && duration >= 0.5 && duration <= 60
  const seedOk = draft.seedMode === 'random' || /^\d+$/.test(draft.seed)
  const mode = draft.start ? (draft.end ? 'FL2VA' : 'I2VA') : null
  const ratioMismatch = draft.start && draft.end && Math.abs((ratio(draft.start) ?? 0) - (ratio(draft.end) ?? 0)) > 0.01
  const hasPicture2 = /<\s*picture\s*2\s*>/i.test(draft.prompt)

  const history = useQuery({
    queryKey: ['revisions', scene.id, base.revision_number],
    queryFn: () => api.revisions(scene.id),
    enabled: showHistory,
  })

  const save = useMutation({
    mutationFn: () => {
      const payload: Record<string, unknown> = { expected_revision: base.revision }
      if (draft.title !== clean.title) payload.title = draft.title
      if (draft.description !== clean.description) payload.description = draft.description
      if (draft.prompt !== clean.prompt) payload.prompt = draft.prompt
      if (duration !== base.duration_seconds) payload.duration_seconds = duration
      if (draft.start?.id !== clean.start?.id) payload.start_asset_id = draft.start?.id ?? null
      if (draft.end?.id !== clean.end?.id) payload.end_asset_id = draft.end?.id ?? null
      if (draft.seedMode !== clean.seedMode || draft.seed !== clean.seed) {
        payload.parameters = {
          ...base.parameters,
          seed_mode: draft.seedMode,
          seed: draft.seedMode === 'fixed' ? Number(draft.seed) : null,
        }
      }
      return api.updateScene(scene.id, payload as { expected_revision: number })
    },
    onSuccess: (s) => {
      setBase(s)
      setDraft(fromScene(s))
      qc.setQueryData<Scene[]>(['scenes', s.chapter_id], (xs) => xs?.map((x) => (x.id === s.id ? s : x)))
      qc.invalidateQueries({ queryKey: ['chapters'] })
      toast.ok(s.revision_number > base.revision_number ? `Guardado · revisión ${s.revision_number}` : 'Guardado')
    },
    onError: (e: ApiError) => toast.error(e.message),
  })

  const canSave = dirty && durationOk && seedOk && !save.isPending && !(draft.end && !draft.start)

  const doSave = useCallback(() => {
    if (canSave) save.mutate()
  }, [canSave, save])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
        e.preventDefault()
        doSave()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [doSave])

  const duplicate = useMutation({
    mutationFn: () => api.duplicateScene(scene.id),
    onSuccess: (s) => {
      qc.invalidateQueries({ queryKey: ['scenes', scene.chapter_id] })
      toast.ok('Escena duplicada')
      onDuplicated(s)
    },
    onError: (e: ApiError) => toast.error(e.message),
  })

  const remove = useMutation({
    mutationFn: () => api.deleteScene(scene.id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['scenes', scene.chapter_id] })
      qc.invalidateQueries({ queryKey: ['chapters'] })
      toast.ok('Escena eliminada')
      onDeleted()
    },
    onError: (e: ApiError) => toast.error(e.message),
  })

  return (
    <section className="card editor" aria-label={`Editor de la escena ${index + 1}`}>
      <div className="editor-head">
        <span className="scene-num" style={{ background: 'var(--grad)', color: 'hsl(262 45% 8%)' }}>
          {index + 1}
        </span>
        <input
          id="scene-title"
          className="title-input"
          value={draft.title}
          maxLength={200}
          placeholder={`Escena ${index + 1}`}
          onChange={(e) => set('title', e.target.value)}
          aria-label="Título de la escena"
        />
        <span className={`chip chip-dot ${base.status === 'lista' ? 'chip-ready' : 'chip-warn'}`}>
          {STATUS_LABEL[base.status]}
        </span>
        {mode && <span className="chip chip-mode">{mode}</span>}
      </div>

      <div className="refs">
        <ImageDrop
          id="drop-start"
          label="Inicio"
          asset={draft.start}
          onChange={(a) => setDraft((d) => ({ ...d, start: a, end: a ? d.end : null }))}
          onZoom={setZoom}
        />
        <div className="refs-arrow">
          <ArrowRight size={20} />
          <span>{mode ?? '—'}</span>
        </div>
        <ImageDrop
          id="drop-end"
          label="Final"
          optional
          asset={draft.end}
          disabled={!draft.start}
          disabledHint="Primero añade la imagen de inicio"
          onChange={(a) => set('end', a)}
          onZoom={setZoom}
        />
      </div>

      {ratioMismatch && (
        <div className="notice warn">
          <TriangleAlert size={16} />
          <span>
            Inicio ({draft.start?.width}×{draft.start?.height}) y final ({draft.end?.width}×{draft.end?.height}) tienen
            proporciones distintas. No se recortarán automáticamente; conviene preparar ambas con el mismo formato.
          </span>
        </div>
      )}

      <div className="field">
        <label htmlFor="scene-prompt">Prompt</label>
        <textarea
          id="scene-prompt"
          className="textarea prompt-box"
          value={draft.prompt}
          spellCheck={false}
          placeholder={'Descripción visual en inglés; diálogos en español dentro de <d>…</d>.'}
          onChange={(e) => set('prompt', e.target.value)}
        />
        <div className="row" style={{ justifyContent: 'space-between' }}>
          <span className="hint">Se guarda literalmente: etiquetas, saltos de línea y acentos se conservan.</span>
          <span className="hint">{draft.prompt.length.toLocaleString('es')} caracteres</span>
        </div>
      </div>

      {hasPicture2 && !draft.end && (
        <div className="notice warn">
          <TriangleAlert size={16} />
          <span>
            El prompt menciona <code>&lt;Picture 2&gt;</code> pero la escena no tiene imagen final.
          </span>
        </div>
      )}

      <div className="row">
        <div className="field">
          <label htmlFor="scene-duration">Duración solicitada (segundos)</label>
          <input
            id="scene-duration"
            className="input"
            inputMode="decimal"
            value={draft.duration}
            onChange={(e) => set('duration', e.target.value)}
            aria-invalid={!durationOk}
            style={!durationOk ? { borderColor: 'var(--danger)' } : undefined}
          />
          <span className="hint">{durationOk ? 'Entre 0,5 y 60 s.' : 'Introduce un valor entre 0,5 y 60.'}</span>
        </div>
        <div className="field">
          <label htmlFor="scene-seed-mode">Semilla</label>
          <select
            id="scene-seed-mode"
            className="select"
            value={draft.seedMode}
            onChange={(e) => set('seedMode', e.target.value as Draft['seedMode'])}
          >
            <option value="random">Aleatoria en cada generación</option>
            <option value="fixed">Fija</option>
          </select>
        </div>
        {draft.seedMode === 'fixed' && (
          <div className="field">
            <label htmlFor="scene-seed">Valor de la semilla</label>
            <input
              id="scene-seed"
              className="input mono"
              inputMode="numeric"
              value={draft.seed}
              onChange={(e) => set('seed', e.target.value.replace(/\D/g, ''))}
              aria-invalid={!seedOk}
            />
          </div>
        )}
      </div>

      <div className="notice">
        <Info size={16} />
        <span>
          La duración real depende de cómo el flujo de ComfyUI cuantiza los frames; se calculará y mostrará al conectar
          y validar el perfil del flujo.
        </span>
      </div>

      <details className="advanced">
        <summary>
          <ChevronRight size={15} /> Notas internas de la escena
        </summary>
        <div className="adv-body">
          <textarea
            id="scene-description"
            className="textarea"
            style={{ minHeight: 90 }}
            value={draft.description}
            placeholder="Descripción, intención o continuidad específica de esta escena (no se envía a ComfyUI)."
            onChange={(e) => set('description', e.target.value)}
          />
        </div>
      </details>

      <details className="advanced" onToggle={(e) => setShowHistory((e.target as HTMLDetailsElement).open)}>
        <summary>
          <History size={15} /> Historial de revisiones ({base.revision_number})
        </summary>
        <div className="adv-body">
          {history.isLoading && <Loader2 className="spin" size={18} />}
          <div className="history">
            {history.data?.map((r) => (
              <div key={r.id} className="history-item">
                <span className="chip chip-plum">r{r.number}</span>
                <div style={{ minWidth: 0 }}>
                  <div className="subtle" style={{ marginBottom: 4 }}>
                    {new Date(r.created_at + (r.created_at.endsWith('Z') ? '' : 'Z')).toLocaleString('es')} ·{' '}
                    {r.duration_seconds} s · {r.end_asset_id ? 'FL2VA' : r.start_asset_id ? 'I2VA' : 'sin imagen'} ·{' '}
                    {r.author.toUpperCase()}
                  </div>
                  <pre>{r.prompt || '(sin prompt)'}</pre>
                </div>
                <button
                  className="btn btn-ghost btn-sm"
                  title="Copiar este prompt al editor"
                  disabled={r.prompt === draft.prompt}
                  onClick={() => set('prompt', r.prompt)}
                >
                  <RotateCcw size={13} /> Usar
                </button>
              </div>
            ))}
          </div>
        </div>
      </details>

      <div className="savebar">
        <div className="left">
          {dirty ? (
            <>
              <span className="dot warn" /> Cambios sin guardar · Ctrl+S
            </>
          ) : (
            <>
              <span className="dot ok" /> Guardado · revisión {base.revision_number}
            </>
          )}
        </div>
        <div className="right">
          <button className="btn btn-ghost btn-danger" onClick={() => setConfirmDelete(true)} id="btn-delete-scene">
            <Trash2 size={15} /> Eliminar
          </button>
          <button className="btn" onClick={() => duplicate.mutate()} disabled={duplicate.isPending} id="btn-duplicate-scene">
            <Copy size={15} /> Duplicar
          </button>
          {dirty && (
            <button className="btn btn-ghost" onClick={() => setDraft(clean)}>
              Descartar
            </button>
          )}
          <button id="btn-save-scene" className="btn btn-primary" onClick={doSave} disabled={!canSave}>
            {save.isPending ? <Loader2 size={15} className="spin" /> : <Save size={15} />} Guardar
          </button>
        </div>
      </div>

      {zoom && <Lightbox asset={zoom} onClose={() => setZoom(null)} />}
      {confirmDelete && (
        <ConfirmDialog
          title="¿Eliminar esta escena?"
          text={`Se eliminará «${base.title || `Escena ${index + 1}`}» con su historial de revisiones. Las imágenes subidas se conservan en el almacenamiento.`}
          confirmText="Eliminar escena"
          danger
          onConfirm={() => remove.mutateAsync()}
          onClose={() => setConfirmDelete(false)}
        />
      )}
    </section>
  )
}
