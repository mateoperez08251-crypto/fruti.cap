import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { BookOpen, FolderPlus, Sparkles } from 'lucide-react'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, ApiError } from '../api'
import { PromptDialog } from '../components/Dialogs'
import { useToast } from '../components/Toast'

const fmtDate = (s: string) => new Date(s).toLocaleDateString('es', { day: 'numeric', month: 'short', year: 'numeric' })

export function ProjectsPage() {
  const qc = useQueryClient()
  const toast = useToast()
  const navigate = useNavigate()
  const [creating, setCreating] = useState(false)
  const { data: projects, isLoading } = useQuery({ queryKey: ['projects'], queryFn: () => api.projects() })

  const create = useMutation({
    mutationFn: (name: string) => api.createProject(name),
    onSuccess: (p) => {
      qc.invalidateQueries({ queryKey: ['projects'] })
      toast.ok(`Proyecto «${p.name}» creado`)
      navigate(`/proyectos/${p.id}`)
    },
    onError: (e: ApiError) => toast.error(e.message),
  })

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <div className="eyebrow">
            <Sparkles size={13} /> Estudio de capítulos
          </div>
          <h1>
            Tus <span className="gradient-text">proyectos</span>
          </h1>
        </div>
        <button id="btn-new-project" className="btn btn-primary" onClick={() => setCreating(true)}>
          <FolderPlus size={16} /> Nuevo proyecto
        </button>
      </header>

      {isLoading && (
        <div className="grid">
          {[0, 1, 2].map((i) => (
            <div key={i} className="skeleton" style={{ height: 160 }} />
          ))}
        </div>
      )}

      {projects && projects.length === 0 && (
        <section className="card empty">
          <img src="/fruti-hero.webp" alt="Darío y Bruno viajando en coche por la costa" />
          <h2>Empieza tu primera frutinovela</h2>
          <p className="muted" style={{ maxWidth: 460, margin: 0 }}>
            Crea un proyecto, añade capítulos y prepara cada escena con su imagen inicial, final opcional, prompt y
            duración.
          </p>
          <button className="btn btn-primary" onClick={() => setCreating(true)}>
            <FolderPlus size={16} /> Crear proyecto
          </button>
        </section>
      )}

      {projects && projects.length > 0 && (
        <div className="grid">
          {projects.map((p) => (
            <article
              key={p.id}
              className="card tile"
              tabIndex={0}
              onClick={() => navigate(`/proyectos/${p.id}`)}
              onKeyDown={(e) => e.key === 'Enter' && navigate(`/proyectos/${p.id}`)}
            >
              <div className="tile-icon">
                <BookOpen size={20} />
              </div>
              <div>
                <h3>{p.name}</h3>
                <div className="subtle" style={{ fontSize: 12, marginTop: 2 }}>
                  {p.language.toUpperCase()} · {p.aspect_ratio}
                </div>
              </div>
              <div className="tile-foot">
                <span>
                  {p.chapter_count} {p.chapter_count === 1 ? 'capítulo' : 'capítulos'}
                </span>
                <span>Editado {fmtDate(p.updated_at)}</span>
              </div>
            </article>
          ))}
          <button className="card tile tile-new" onClick={() => setCreating(true)}>
            <FolderPlus size={22} />
            Nuevo proyecto
          </button>
        </div>
      )}

      {creating && (
        <PromptDialog
          title="Nuevo proyecto"
          label="Nombre del proyecto"
          placeholder="FRUTINOVELAS"
          confirmText="Crear proyecto"
          onSubmit={(name) => create.mutateAsync(name)}
          onClose={() => setCreating(false)}
        />
      )}
    </div>
  )
}
