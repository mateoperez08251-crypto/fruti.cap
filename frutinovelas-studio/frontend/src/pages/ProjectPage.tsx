import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Archive, ChevronRight, FilePlus2, Film, Pencil } from 'lucide-react'
import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api, ApiError } from '../api'
import { ConfirmDialog, PromptDialog } from '../components/Dialogs'
import { useToast } from '../components/Toast'
import { CharacterLibrary } from '../components/CharacterLibrary'

export function ProjectPage({ projectId }: { projectId: string }) {
  const qc = useQueryClient()
  const toast = useToast()
  const navigate = useNavigate()
  const [dialog, setDialog] = useState<'chapter' | 'rename' | 'archive' | null>(null)
  const [showCharacters, setShowCharacters] = useState(false)

  const project = useQuery({ queryKey: ['project', projectId], queryFn: () => api.project(projectId) })
  const chapters = useQuery({ queryKey: ['chapters', projectId], queryFn: () => api.chapters(projectId) })

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['project', projectId] })
    qc.invalidateQueries({ queryKey: ['projects'] })
    qc.invalidateQueries({ queryKey: ['chapters', projectId] })
  }
  const onError = (e: ApiError) => toast.error(e.message)

  const createChapter = useMutation({
    mutationFn: (title: string) => api.createChapter(projectId, title),
    onSuccess: (c) => {
      refresh()
      navigate(`/capitulos/${c.id}`)
    },
    onError,
  })
  const rename = useMutation({
    mutationFn: (name: string) => api.updateProject(projectId, { name }),
    onSuccess: () => {
      refresh()
      toast.ok('Proyecto renombrado')
    },
    onError,
  })
  const archive = useMutation({
    mutationFn: () => api.updateProject(projectId, { archived: true }),
    onSuccess: () => {
      refresh()
      toast.ok('Proyecto archivado')
      navigate('/')
    },
    onError,
  })

  if (project.isError) {
    return (
      <div className="page empty">
        <h2>No se encontró el proyecto</h2>
        <Link className="btn" to="/">
          Volver
        </Link>
      </div>
    )
  }

  const p = project.data
  return (
    <div className="page">
      <header className="page-head">
        <div>
          <div className="eyebrow">
            <Link to="/">Proyectos</Link> <ChevronRight size={12} />
          </div>
          <h1>{p?.name ?? '…'}</h1>
        </div>
        <div className="row" style={{ gap: 8 }}>
          <button className="btn btn-ghost" onClick={() => setDialog('rename')} disabled={!p}>
            <Pencil size={15} /> Renombrar
          </button>
          <button className="btn btn-ghost" onClick={() => setDialog('archive')} disabled={!p}>
            <Archive size={15} /> Archivar
          </button>
          <button id="btn-new-chapter" className="btn btn-primary" onClick={() => setDialog('chapter')}>
            <FilePlus2 size={16} /> Nuevo capítulo
          </button>
        </div>
      </header>

      <details className="card character-library" onToggle={(e) => setShowCharacters(e.currentTarget.open)}>
        <summary>Biblioteca de personajes · referencias para las escenas</summary>
        {showCharacters && <CharacterLibrary projectId={projectId} />}
      </details>

      {chapters.data && chapters.data.length === 0 && (
        <section className="card empty">
          <div className="tile-icon" style={{ width: 56, height: 56 }}>
            <Film size={26} />
          </div>
          <h2>Aún no hay capítulos</h2>
          <p className="muted" style={{ margin: 0 }}>
            Cada capítulo guarda su guion, continuidad y la lista ordenada de escenas.
          </p>
          <button className="btn btn-primary" onClick={() => setDialog('chapter')}>
            <FilePlus2 size={16} /> Crear el primer capítulo
          </button>
        </section>
      )}

      {chapters.data && chapters.data.length > 0 && (
        <div className="grid">
          {chapters.data.map((c) => {
            const pct = c.scene_count ? Math.round((c.ready_count / c.scene_count) * 100) : 0
            return (
              <article
                key={c.id}
                className="card tile"
                tabIndex={0}
                onClick={() => navigate(`/capitulos/${c.id}`)}
                onKeyDown={(e) => e.key === 'Enter' && navigate(`/capitulos/${c.id}`)}
              >
                <div className="row" style={{ justifyContent: 'space-between', alignItems: 'center' }}>
                  <span className="chip chip-plum">#{c.order_index}</span>
                  {c.scene_count > 0 && c.ready_count === c.scene_count && (
                    <span className="chip chip-ready chip-dot">Escenas listas</span>
                  )}
                </div>
                <h3>{c.title}</h3>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginTop: 'auto' }}>
                  <div className="meter" aria-label={`${pct}% de escenas listas`}>
                    <div style={{ width: `${pct}%` }} />
                  </div>
                  <div className="tile-foot" style={{ marginTop: 0 }}>
                    <span>
                      {c.ready_count}/{c.scene_count} escenas listas
                    </span>
                    <span>{c.script_md.trim() ? 'Con guion' : 'Sin guion'}</span>
                  </div>
                </div>
              </article>
            )
          })}
          <button className="card tile tile-new" onClick={() => setDialog('chapter')}>
            <FilePlus2 size={22} /> Nuevo capítulo
          </button>
        </div>
      )}

      {dialog === 'chapter' && (
        <PromptDialog
          title="Nuevo capítulo"
          label="Título"
          initial={`Capítulo ${(chapters.data?.length ?? 0) + 1}`}
          confirmText="Crear capítulo"
          onSubmit={(t) => createChapter.mutateAsync(t)}
          onClose={() => setDialog(null)}
        />
      )}
      {dialog === 'rename' && p && (
        <PromptDialog
          title="Renombrar proyecto"
          label="Nombre"
          initial={p.name}
          onSubmit={(n) => rename.mutateAsync(n)}
          onClose={() => setDialog(null)}
        />
      )}
      {dialog === 'archive' && p && (
        <ConfirmDialog
          title="¿Archivar proyecto?"
          text={`«${p.name}» dejará de aparecer en la lista. No se borra ningún dato.`}
          confirmText="Archivar"
          onConfirm={() => archive.mutateAsync()}
          onClose={() => setDialog(null)}
        />
      )}
    </div>
  )
}
