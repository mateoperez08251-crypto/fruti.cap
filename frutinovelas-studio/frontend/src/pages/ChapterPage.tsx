import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { BookText, ChevronRight, Clapperboard, ListOrdered, Loader2, Pencil, Plus, Save, Sparkles } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useBlocker, useSearchParams } from 'react-router-dom'
import { api, ApiError, type Chapter, type Scene } from '../api'
import { ChapterAutoRender } from '../components/ChapterAutoRender'
import { ChapterImagesGallery } from '../components/ChapterImagesGallery'
import { PromptDialog } from '../components/Dialogs'
import { SceneEditor } from '../components/SceneEditor'
import { SceneList } from '../components/SceneList'
import { useToast } from '../components/Toast'

type Tab = 'escenas' | 'guion' | 'continuidad'

function DocEditor({ chapter, field, title, hint, onDirtyChange }: { chapter: Chapter; field: 'script_md' | 'continuity_md'; title: string; hint: string; onDirtyChange: (dirty: boolean) => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const [text, setText] = useState(chapter[field])
  const [rev, setRev] = useState(chapter.revision)
  const [saved, setSaved] = useState(chapter[field])
  const dirty = text !== saved

  const save = useMutation({
    mutationFn: () => api.updateChapter(chapter.id, { expected_revision: rev, [field]: text }),
    onSuccess: (c) => {
      setRev(c.revision)
      setSaved(c[field])
      qc.setQueryData(['chapter', chapter.id], c)
      qc.invalidateQueries({ queryKey: ['chapters', chapter.project_id] })
      toast.ok(`${title} guardado`)
    },
    onError: (e: ApiError) => toast.error(e.message),
  })

  useEffect(() => onDirtyChange(dirty || save.isPending), [dirty, save.isPending, onDirtyChange])

  // Otra parte del programa guardó el capítulo (p. ej. renombrar). Si ESTE documento no cambió en
  // el servidor se adopta la nueva revisión; si cambió, se conserva la antigua para que guardar dé 409.
  const [seenRev, setSeenRev] = useState(chapter.revision)
  if (chapter.revision !== seenRev) {
    setSeenRev(chapter.revision)
    if (chapter.revision > rev && chapter[field] === saved) {
      setRev(chapter.revision)
    } else if (chapter.revision > rev && !dirty) {
      setRev(chapter.revision)
      setText(chapter[field])
      setSaved(chapter[field])
    }
  }

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
        e.preventDefault()
        if (dirty && !save.isPending) save.mutate()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [dirty, save])

  return (
    <section className="card doc-editor">
      <div className="row" style={{ justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <h3>{title}</h3>
          <div className="hint">{hint}</div>
        </div>
        <div className="row" style={{ gap: 8, alignItems: 'center' }}>
          <span className="hint">{dirty ? 'Cambios sin guardar · Ctrl+S' : 'Guardado'}</span>
          <button className="btn btn-primary" disabled={!dirty || save.isPending} onClick={() => save.mutate()} id={`btn-save-${field}`}>
            {save.isPending ? <Loader2 size={15} className="spin" /> : <Save size={15} />} Guardar
          </button>
        </div>
      </div>
      <textarea
        id={`doc-${field}`}
        className="textarea"
        value={text}
        spellCheck={false}
        onChange={(e) => setText(e.target.value)}
        placeholder="Escribe o pega aquí el Markdown…"
      />
    </section>
  )
}

export function ChapterPage({ chapterId }: { chapterId: string }) {
  const qc = useQueryClient()
  const toast = useToast()
  const [params, setParams] = useSearchParams()
  const [tab, setTab] = useState<Tab>('escenas')
  const [renaming, setRenaming] = useState(false)
  const dirtyRef = useRef(false)
  const [editingDirty, setEditingDirty] = useState(false)
  const [pinnedId, setPinnedId] = useState<string | null>(null)
  const blocker = useBlocker(({ currentLocation, nextLocation }) =>
    (currentLocation.pathname !== nextLocation.pathname || currentLocation.search !== nextLocation.search) && dirtyRef.current)

  useEffect(() => {
    if (blocker.state === 'blocked') {
      if (window.confirm('Hay cambios sin guardar o una operación en curso. ¿Salir de este capítulo?')) blocker.proceed()
      else blocker.reset()
    }
  }, [blocker])

  const changeTab = (next: Tab) => {
    if (next === tab) return
    if (dirtyRef.current && !window.confirm('Hay cambios sin guardar o una operación en curso. ¿Cambiar de pestaña y descartar el borrador?')) return
    dirtyRef.current = false
    setEditingDirty(false)
    setTab(next)
  }

  const chapter = useQuery({ queryKey: ['chapter', chapterId], queryFn: () => api.chapter(chapterId) })
  const project = useQuery({
    queryKey: ['project', chapter.data?.project_id],
    queryFn: () => api.project(chapter.data!.project_id),
    enabled: !!chapter.data,
  })
  const scenes = useQuery({ queryKey: ['scenes', chapterId], queryFn: () => api.scenes(chapterId) })

  const requestedId = params.get('escena') ?? pinnedId
  const selectedId = scenes.data?.some((s) => s.id === requestedId) ? requestedId : scenes.data?.[0]?.id ?? null
  const selectedIndex = scenes.data?.findIndex((s) => s.id === selectedId) ?? -1
  const selected = selectedIndex >= 0 ? scenes.data![selectedIndex] : null

  const select = useCallback(
    (id: string | null, force = false) => {
      if (id === selectedId) return
      if (!force && dirtyRef.current && !window.confirm('Hay cambios sin guardar en esta escena. ¿Descartarlos?')) return
      dirtyRef.current = false
      setEditingDirty(false)
      setPinnedId(id)
      setParams(id ? { escena: id } : {}, { replace: true })
    },
    [setParams, selectedId],
  )

  useEffect(() => {
    const warn = (e: BeforeUnloadEvent) => {
      if (dirtyRef.current) {
        e.preventDefault()
        e.returnValue = ''
      }
    }
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [])

  const onError = (e: ApiError) => toast.error(e.message)

  const create = useMutation({
    mutationFn: () => api.createScene(chapterId, {}),
    onSuccess: (s) => {
      qc.setQueryData<Scene[]>(['scenes', chapterId], (xs) => [...(xs ?? []), s])
      qc.invalidateQueries({ queryKey: ['chapters'] })
      select(s.id)
    },
    onError,
  })

  const reorder = useMutation({
    mutationFn: (ids: string[]) => api.reorderScenes(chapterId, ids),
    onMutate: async (ids) => {
      setPinnedId(selectedId)
      await qc.cancelQueries({ queryKey: ['scenes', chapterId] })
      const prev = qc.getQueryData<Scene[]>(['scenes', chapterId])
      if (prev) {
        const byId = new Map(prev.map((s) => [s.id, s]))
        qc.setQueryData(['scenes', chapterId], ids.map((id) => byId.get(id)!))
      }
      return { prev }
    },
    onError: (e: ApiError, _ids, ctx) => {
      if (ctx?.prev) qc.setQueryData(['scenes', chapterId], ctx.prev)
      onError(e)
    },
    onSuccess: (list) => qc.setQueryData(['scenes', chapterId], list),
  })

  const rename = useMutation({
    mutationFn: (title: string) => api.updateChapter(chapterId, { expected_revision: chapter.data!.revision, title }),
    onSuccess: (c) => {
      qc.setQueryData(['chapter', chapterId], c)
      qc.invalidateQueries({ queryKey: ['chapters', c.project_id] })
      toast.ok('Capítulo renombrado')
    },
    onError,
  })

  const onDirtyChange = useCallback((d: boolean) => {
    dirtyRef.current = d
    setEditingDirty(d)
  }, [])

  if (chapter.isError) {
    return (
      <div className="page empty">
        <h2>No se encontró el capítulo</h2>
        <Link className="btn" to="/">
          Volver
        </Link>
      </div>
    )
  }

  const c = chapter.data
  const list = scenes.data ?? []
  const ready = list.filter((s) => s.status === 'lista').length
  const total = list.reduce((acc, s) => acc + s.duration_seconds, 0)

  return (
    <div className="page" style={{ maxWidth: 1480 }}>
      <header className="page-head">
        <div>
          <div className="eyebrow">
            <Link to="/">Proyectos</Link> <ChevronRight size={12} />
            {c && <Link to={`/proyectos/${c.project_id}`}>{project.data?.name ?? '…'}</Link>}
            <ChevronRight size={12} />
          </div>
          <h1 style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            {c?.title ?? '…'}
            {c && (
              <button className="btn btn-ghost btn-icon btn-sm" onClick={() => setRenaming(true)} aria-label="Renombrar capítulo">
                <Pencil size={14} />
              </button>
            )}
          </h1>
          <div className="row" style={{ gap: 8, marginTop: 10 }}>
            <span className="chip">{list.length} escenas</span>
            <span className={`chip chip-dot ${ready === list.length && list.length ? 'chip-ready' : 'chip-warn'}`}>
              {ready} listas
            </span>
            <span className="chip">≈ {total.toLocaleString('es', { maximumFractionDigits: 1 })} s solicitados</span>
          </div>
        </div>
        <nav className="tabs" aria-label="Secciones del capítulo">
          <button className={`tab ${tab === 'escenas' ? 'active' : ''}`} onClick={() => changeTab('escenas')} id="tab-escenas">
            <Clapperboard size={15} /> Escenas
          </button>
          <button className={`tab ${tab === 'guion' ? 'active' : ''}`} onClick={() => changeTab('guion')} id="tab-guion">
            <BookText size={15} /> Guion
          </button>
          <button
            className={`tab ${tab === 'continuidad' ? 'active' : ''}`}
            onClick={() => changeTab('continuidad')}
            id="tab-continuidad"
          >
            <ListOrdered size={15} /> Continuidad
          </button>
        </nav>
      </header>

      {tab === 'guion' && c && (
        <DocEditor key="script_md" onDirtyChange={onDirtyChange} chapter={c} field="script_md" title="Guion" hint="Markdown del guion del capítulo. Es contexto: no crea escenas automáticamente." />
      )}
      {tab === 'continuidad' && c && (
        <DocEditor
          key="continuity_md"
          onDirtyChange={onDirtyChange}
          chapter={c}
          field="continuity_md"
          title="Continuidad"
          hint="Personajes, ropa, asientos, objetos y luz que deben mantenerse entre escenas."
        />
      )}

      {c && scenes.data && <ChapterAutoRender chapter={c} scenes={list} dirty={editingDirty} />}

      {tab === 'escenas' && (
        <>
          {list.length > 0 && <ChapterImagesGallery scenes={list} />}
          {scenes.isError && <p className="notice warn" role="alert">No se pudieron cargar las escenas. <button className="btn btn-sm" onClick={() => scenes.refetch()}>Reintentar</button></p>}
          {scenes.isLoading && <div className="skeleton" style={{ height: 300 }} />}

          {scenes.data && list.length === 0 && (
            <section className="card empty">
              <div className="tile-icon" style={{ width: 56, height: 56 }}>
                <Sparkles size={26} />
              </div>
              <h2>Añade la primera escena</h2>
              <p className="muted" style={{ margin: 0, maxWidth: 480 }}>
                Cada escena tiene su imagen de inicio, una imagen final opcional, su prompt y su duración.
              </p>
              <button className="btn btn-primary" onClick={() => create.mutate()} disabled={create.isPending} id="btn-first-scene">
                <Plus size={16} /> Nueva escena
              </button>
            </section>
          )}

          {list.length > 0 && (
            <div className="workspace">
              <div className="scene-list">
                <div className="scene-list-head">
                  <span className="label">Orden del montaje</span>
                  <button className="btn btn-sm" onClick={() => create.mutate()} disabled={create.isPending} id="btn-new-scene">
                    <Plus size={14} /> Nueva escena
                  </button>
                </div>
                <SceneList scenes={list} selectedId={selectedId} onSelect={select} reordering={reorder.isPending} onReorder={(ids) => { if (!reorder.isPending) reorder.mutate(ids) }} />
              </div>
              {selected && (
                <SceneEditor
                  key={selected.id}
                  scene={selected}
                  projectId={c?.project_id}
                  index={selectedIndex}
                  onDirtyChange={onDirtyChange}
                  onDuplicated={(s) => select(s.id, true)}
                  onDeleted={() => {
                    const next = list[selectedIndex + 1] ?? list[selectedIndex - 1]
                    select(next && next.id !== selected.id ? next.id : null, true)
                  }}
                />
              )}
            </div>
          )}
        </>
      )}

      {renaming && c && (
        <PromptDialog
          title="Renombrar capítulo"
          label="Título"
          initial={c.title}
          onSubmit={(t) => rename.mutateAsync(t)}
          onClose={() => setRenaming(false)}
        />
      )}
    </div>
  )
}
