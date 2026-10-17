import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowRight, ChevronRight, Copy, History, Info, Loader2, RotateCcw, Save, Trash2, TriangleAlert } from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, ApiError, thumbUrl, type Asset, type Scene } from '../api'
import { STATUS_LABEL } from '../labels'
import { ConfirmDialog } from './Dialogs'
import { ImageDrop, Lightbox } from './ImageDrop'
import { useToast } from './Toast'
import { GenerationPanel } from './GenerationPanel'
import { PromptCheck } from './PromptCheck'
import { SceneImagePanel } from './SceneImagePanel'
import { audioDrafts, audioErrors, audioInputs, nextAudioStart, type AudioDraft } from '../audio'
import { SceneAudio } from './SceneAudio'

type Draft = {
  title: string
  description: string
  prompt: string
  duration: string
  start: Asset | null
  end: Asset | null
  seedMode: 'random' | 'fixed'
  seed: string
  imagePrompt: string
  characterIds: string[]
  imageApproval: 'manual' | 'automatic'
  audioGuides: AudioDraft[]
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
  imagePrompt: s.parameters.image_prompt ?? '',
  characterIds: s.parameters.character_ids ?? [],
  imageApproval: s.parameters.image_approval ?? 'manual',
  audioGuides: audioDrafts(s.parameters.audio_guides),
})

const ratio = (a: Asset | null) => (a?.width && a?.height ? a.width / a.height : null)

type Props = {
  projectId?: string
  scene: Scene
  index: number
  onDirtyChange: (dirty: boolean) => void
  onDuplicated: (s: Scene) => void
  onDeleted: () => void
}

export function SceneEditor({ scene, projectId, index, onDirtyChange, onDuplicated, onDeleted }: Props) {
  const qc = useQueryClient()
  const toast = useToast()
  const [draft, setDraft] = useState<Draft>(() => fromScene(scene))
  const [base, setBase] = useState<Scene>(scene)
  const [zoom, setZoom] = useState<Asset | null>(null)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [showHistory, setShowHistory] = useState(false)
  const [startUploading, setStartUploading] = useState(false)
  const [endUploading, setEndUploading] = useState(false)
  const [audioUploading, setAudioUploading] = useState(false)
  const [showImages, setShowImages] = useState(false)
  const [showAudio, setShowAudio] = useState(false)
  const characters = useQuery({ queryKey: ['characters', projectId],
    queryFn: ({ signal }) => api.characters(projectId!, signal), enabled: !!projectId && (showImages || showAudio) })
  const uploading = startUploading || endUploading || audioUploading

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

  const set = <K extends keyof Draft>(k: K, v: Draft[K]) => setDraft((d) => ({ ...d, [k]: v }))

  const duration = Number(draft.duration.replace(',', '.'))
  const durationOk = Number.isFinite(duration) && duration >= 0.5 && duration <= 60
  const seedOk = draft.seedMode === 'random' || (/^\d+$/.test(draft.seed) && Number.isSafeInteger(Number(draft.seed)))
  const audioValidation = audioErrors(draft.audioGuides, duration)
  const mode = draft.start ? (draft.end ? 'FL2VA' : 'I2VA') : null
  const ratioMismatch = draft.start && draft.end && Math.abs((ratio(draft.start) ?? 0) - (ratio(draft.end) ?? 0)) > 0.01
  const hasPicture2 = /<\s*picture\s*2\s*>/i.test(draft.prompt)

  const history = useQuery({
    queryKey: ['revisions', scene.id, base.revision_number],
    queryFn: ({ signal }) => api.revisions(scene.id, signal),
    enabled: showHistory,
  })

  const save = useMutation({
    mutationFn: (submitted: Draft) => {
      const draft = submitted
      const duration = Number(draft.duration.replace(',', '.'))
      const payload: Record<string, unknown> = { expected_revision: base.revision }
      if (draft.title !== clean.title) payload.title = draft.title
      if (draft.description !== clean.description) payload.description = draft.description
      if (draft.prompt !== clean.prompt) payload.prompt = draft.prompt
      if (duration !== base.duration_seconds) payload.duration_seconds = duration
      if (draft.start?.id !== clean.start?.id) payload.start_asset_id = draft.start?.id ?? null
      if (draft.end?.id !== clean.end?.id) payload.end_asset_id = draft.end?.id ?? null
      const audioChanged = JSON.stringify(draft.audioGuides) !== JSON.stringify(clean.audioGuides)
      if (draft.seedMode !== clean.seedMode || draft.seed !== clean.seed || draft.imagePrompt !== clean.imagePrompt || draft.imageApproval !== clean.imageApproval || JSON.stringify(draft.characterIds) !== JSON.stringify(clean.characterIds) || audioChanged) {
        payload.parameters = {
          ...base.parameters,
          seed_mode: draft.seedMode,
          seed: draft.seedMode === 'fixed' ? Number(draft.seed) : null,
          image_prompt: draft.imagePrompt,
          character_ids: draft.characterIds,
          image_approval: draft.imageApproval,
          ...(audioChanged ? { audio_guides: audioInputs(draft.audioGuides) } : {}),
        }
      }
      return api.updateScene(scene.id, payload as { expected_revision: number })
    },
    onSuccess: (s, submitted) => {
      setBase(s)
      // El usuario puede seguir escribiendo mientras se guarda. Conserva los campos
      // que cambiaron desde el envío, en vez de reemplazarlos por la respuesta anterior.
      setDraft((current) => {
        const saved = fromScene(s)
        const merged = { ...current }
        for (const key of Object.keys(saved) as (keyof Draft)[]) {
          if (JSON.stringify(current[key]) === JSON.stringify(submitted[key])) {
            Object.assign(merged, { [key]: saved[key] })
          }
        }
        return merged
      })
      qc.setQueryData<Scene[]>(['scenes', s.chapter_id], (xs) => xs?.map((x) => (x.id === s.id ? s : x)))
      qc.invalidateQueries({ queryKey: ['chapters'] })
      toast.ok(s.revision_number > base.revision_number ? `Guardado · revisión ${s.revision_number}` : 'Guardado')
    },
    onError: (e: ApiError) => toast.error(e.message),
  })

  useEffect(() => onDirtyChange(dirty || save.isPending || uploading), [dirty, save.isPending, uploading, onDirtyChange])

  const canSave = dirty && durationOk && seedOk && !audioValidation.length && !uploading && !save.isPending && !(draft.end && !draft.start)
  const onImageApplied = useCallback((s: Scene) => {
    setBase(s)
    setDraft((current) => {
      const saved = fromScene(s)
      const merged = { ...current }
      for (const key of Object.keys(saved) as (keyof Draft)[]) {
        if (JSON.stringify(current[key]) === JSON.stringify(clean[key])) Object.assign(merged, { [key]: saved[key] })
      }
      return merged
    })
    qc.setQueryData<Scene[]>(['scenes', s.chapter_id], (xs) => xs?.map((x) => x.id === s.id ? s : x))
    qc.invalidateQueries({ queryKey: ['chapters'] })
  }, [clean, qc])

  const doSave = useCallback(() => {
    if (canSave) save.mutate(draft)
  }, [canSave, save, draft])

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

      <details className="advanced scene-preparation" onToggle={(e) => setShowImages(e.currentTarget.open)}>
        <summary>1 · Personajes y prompt para crear la imagen</summary>
        {showImages && <div className="adv-body">
          <p className="hint">Marca quién aparece en esta escena. El orden indica qué personaje es la referencia 1 y cuál la 2.</p>
          {projectId && <Link to={`/proyectos/${projectId}`}>Abrir biblioteca de personajes del proyecto</Link>}
          {characters.isError && <p role="alert">No se pudieron cargar los personajes. <button className="btn btn-sm" onClick={() => characters.refetch()}>Reintentar</button></p>}
          <div className="character-grid">{characters.data?.map((c) => {
            const selected = draft.characterIds.includes(c.id)
            const saved = base.parameters.cast?.find((r) => r.character_id === c.id)
            return <label className={`character-card ${selected ? 'selected' : ''}`} key={c.id}>
              <input type="checkbox" checked={selected} disabled={!selected && draft.characterIds.length >= 2}
                onChange={() => set('characterIds', selected ? draft.characterIds.filter((id) => id !== c.id) : [...draft.characterIds, c.id])} />
              <img src={thumbUrl(selected && saved ? saved.asset_id : c.reference_asset.id, 128)} alt={c.name} loading="lazy" />
              <span>{selected ? `${draft.characterIds.indexOf(c.id) + 1} · ` : ''}{c.name}</span>
            </label>
          })}</div>
          {base.parameters.cast?.filter((r) => !characters.data?.some((c) => c.id === r.character_id)).map((r) => <label key={r.character_id} className="hint">
            <input type="checkbox" checked={draft.characterIds.includes(r.character_id)} onChange={() => set('characterIds', draft.characterIds.filter((id) => id !== r.character_id))} /> Referencia guardada: {r.name}
          </label>)}
          <p className="hint">Este flujo admite hasta dos referencias. Las selecciones guardadas conservan su imagen original aunque cambie la biblioteca.</p>
          <div className="field"><label htmlFor="scene-image-prompt">Prompt de imagen · Qwen</label>
            <textarea id="scene-image-prompt" className="textarea" value={draft.imagePrompt} maxLength={30000} spellCheck={false}
              onChange={(e) => set('imagePrompt', e.target.value)} placeholder="Composición, personajes, pose, escenario y luz. En inglés." /></div>
          <p className="hint">El guion aporta lo que sucede. Este prompt prepara el fotograma; el de animación se guarda aparte.</p>
          <div className="field"><label htmlFor="scene-image-approval">Revisión de imágenes</label>
            <select id="scene-image-approval" className="select" value={draft.imageApproval} onChange={(e) => set('imageApproval', e.target.value as Draft['imageApproval'])}>
              <option value="manual">Manual · revisar antes de usar</option><option value="automatic">Automática · usar como inicio sin revisar</option>
            </select><p className="hint">La opción automática asigna la imagen generada. No evalúa su calidad visual.</p></div>
          <SceneImagePanel scene={base} dirty={dirty || save.isPending || uploading} onApplied={onImageApplied} />
        </div>}
      </details>

      <div className="refs">
        <ImageDrop
          id="drop-start"
          onBusyChange={setStartUploading}
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
          onBusyChange={setEndUploading}
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
            proporciones distintas. Al generar se ajustan al centro a 576×1024; prepara ambas en 9:16 para evitar perder detalles importantes.
          </span>
        </div>
      )}

      <div className="field">
        <label htmlFor="scene-prompt">2 · Prompt de animación · H3</label>
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

      <PromptCheck input={{ prompt: draft.prompt, duration_seconds: duration,
        has_start_image: Boolean(draft.start), has_end_image: Boolean(draft.end) }} />

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
          <span className="hint">{durationOk ? 'Puedes ajustar los segundos manualmente o pedir a ChatGPT que los estime según el prompt, el diálogo y las imágenes de inicio/final. Este flujo H3 genera 4–15 s (guardado: 0,5–60 s).' : 'Introduce un valor entre 0,5 y 60.'}</span>
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
            {!seedOk && <span className="hint">Usa un entero entre 0 y 9007199254740991.</span>}
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

      <details className="advanced scene-audio" onToggle={(e) => setShowAudio(e.currentTarget.open)}>
        <summary>3 · Audio y voces{draft.audioGuides.length ? ` (${draft.audioGuides.length})` : ' · opcional'}{audioValidation.length ? ' · revisar' : ''}</summary>
        <div className="adv-body">
          {projectId && <Link to={`/proyectos/${projectId}`}>Abrir las voces de la biblioteca de personajes</Link>}
          {showAudio && characters.isError && <p role="alert">No se pudieron cargar las voces de los personajes. <button className="btn btn-sm" onClick={() => characters.refetch()}>Reintentar</button></p>}
          <SceneAudio guides={draft.audioGuides} characters={characters.data ?? []} errors={audioValidation}
            onUpdate={(index, data) => setDraft((d) => ({ ...d, audioGuides: d.audioGuides.map((g, i) => i === index ? { ...g, ...data } : g) }))}
            onRemove={(index) => setDraft((d) => ({ ...d, audioGuides: d.audioGuides.filter((_g, i) => i !== index) }))}
            onAdd={(asset) => setDraft((d) => d.audioGuides.length >= 8 ? d : ({ ...d, audioGuides: [...d.audioGuides, {
              assetId: asset.id, asset, characterId: '', characterName: '', voiceDescription: '', start: nextAudioStart(d.audioGuides),
            }] }))}
            onBusyChange={setAudioUploading} />
        </div>
      </details>

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
          {history.isError && <p role="alert">No se pudo cargar el historial. <button className="btn btn-sm" onClick={() => history.refetch()}>Reintentar</button></p>}
          {history.isLoading && <Loader2 className="spin" size={18} />}
          <div className="history">
            {history.data?.map((r) => (
              <div key={r.id} className="history-item">
                <span className="chip chip-plum">r{r.number}</span>
                <div style={{ minWidth: 0 }}>
                  <div className="subtle" style={{ marginBottom: 4 }}>
                    {new Date(r.created_at + (r.created_at.endsWith('Z') ? '' : 'Z')).toLocaleString('es')} ·{' '}
                    {r.duration_seconds} s · {r.end_asset_id ? 'FL2VA' : r.start_asset_id ? 'I2VA' : 'sin imagen'} ·{' '}
                    {r.author.toUpperCase()}{r.parameters.audio_guides?.length ? ` · ${r.parameters.audio_guides.length} audio${r.parameters.audio_guides.length === 1 ? '' : 's'}` : ''}
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
          <button className="btn btn-ghost btn-danger" onClick={() => setConfirmDelete(true)} disabled={save.isPending || uploading} id="btn-delete-scene">
            <Trash2 size={15} /> Eliminar
          </button>
          <button className="btn" onClick={() => duplicate.mutate()} disabled={dirty || uploading || save.isPending || duplicate.isPending} title={dirty ? 'Guarda los cambios antes de duplicar' : undefined} id="btn-duplicate-scene">
            <Copy size={15} /> Duplicar
          </button>
          {dirty && (
            <button className="btn btn-ghost" disabled={save.isPending || uploading} onClick={() => setDraft(clean)}>
              Descartar
            </button>
          )}
          <button id="btn-save-scene" className="btn btn-primary" onClick={doSave} disabled={!canSave}>
            {save.isPending ? <Loader2 size={15} className="spin" /> : <Save size={15} />} Guardar
          </button>
        </div>
      </div>

      <GenerationPanel scene={base} dirty={dirty || save.isPending || uploading} />
      {zoom && <Lightbox asset={zoom} onClose={() => setZoom(null)} />}
      {confirmDelete && (
        <ConfirmDialog
          title="¿Eliminar esta escena?"
          text={`Se eliminará «${base.title || `Escena ${index + 1}`}» con su historial de revisiones. Las imágenes y los audios subidos se conservan en el almacenamiento.`}
          confirmText="Eliminar escena"
          danger
          onConfirm={() => remove.mutateAsync()}
          onClose={() => setConfirmDelete(false)}
        />
      )}
    </section>
  )
}
