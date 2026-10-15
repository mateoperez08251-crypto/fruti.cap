import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, type Chapter, type Scene } from '../api'
import { useToast } from './Toast'

const terminal = new Set(['completed', 'failed'])
const labels: Record<string, string> = { queued: 'En cola', generating: 'Generando escenas', assembling: 'Montando capítulo', completed: 'Capítulo listo', failed: 'Necesita revisión' }

export function ChapterAutoRender({ chapter, scenes, dirty }: { chapter: Chapter; scenes: Scene[]; dirty: boolean }) {
  const [open, setOpen] = useState(false)
  return <details className="card" onToggle={(e) => setOpen(e.currentTarget.open)}>
    <summary>Capítulo automático · imágenes, animación y montaje</summary>
    {open && <RenderPanel chapter={chapter} scenes={scenes} dirty={dirty} />}
  </details>
}

function RenderPanel({ chapter, scenes, dirty }: { chapter: Chapter; scenes: Scene[]; dirty: boolean }) {
  const qc = useQueryClient()
  const toast = useToast()
  const [automatic, setAutomatic] = useState(false)
  const [count, setCount] = useState(3)
  const runs = useQuery({ queryKey: ['chapter-renders', chapter.id], queryFn: ({ signal }) => api.chapterRenders(chapter.id, signal),
    refetchInterval: (q) => q.state.status !== 'error' && q.state.data?.some((r) => !terminal.has(r.state)) ? 5000 : 30_000,
    refetchIntervalInBackground: false })
  const active = runs.data?.some((r) => !terminal.has(r.state))
  const prepared = scenes.length > 0 && scenes.length <= 60 && scenes.every((s) => s.prompt.trim() && s.parameters.image_prompt?.trim() && s.duration_seconds >= 4 && s.duration_seconds <= 15)
  const start = useMutation({ mutationFn: () => api.renderChapter(chapter.id, chapter.revision, Object.fromEntries(scenes.map((s) => [s.id, s.revision])), crypto.randomUUID()),
    onSuccess: () => { setAutomatic(false); qc.invalidateQueries({ queryKey: ['chapter-renders', chapter.id] }); toast.ok('Capítulo añadido a la cola automática') },
    onError: (e) => { qc.invalidateQueries({ queryKey: ['chapter-renders', chapter.id] }); toast.error(e.message) } })
  return <section aria-label="Generación automática del capítulo">
    <p>Primero guarda el reparto y los dos prompts de cada escena. Este proceso usa esos textos: genera una imagen, la asigna como inicio, anima el clip y continúa con la siguiente escena. Al terminar, une los clips en un MP4 con FFmpeg.</p>
    <label><input type="checkbox" checked={automatic} onChange={(e) => setAutomatic(e.target.checked)} /> Aprobar automáticamente las imágenes de este proceso y generar los videos</label>
    <p className="hint">Consume la GPU conectada. La aprobación automática no revisa la calidad; los cortes y el sonido dependen de los clips y sus prompts. Los originales se conservan. Si una escena cambia o falla una generación, el proceso se detiene para revisión.</p>
    {!prepared && <p className="hint">Prepara ambos prompts y una duración de 4–15 segundos en cada escena (máximo 60).</p>}
    {dirty && <p className="hint">Guarda los cambios antes de iniciar el capítulo.</p>}
    <button className="btn btn-primary" disabled={!automatic || !prepared || dirty || active || start.isPending || runs.isPending || runs.isError} onClick={() => start.mutate()}>Generar capítulo completo</button>
    {runs.isError && <p role="alert">No se pudo consultar el capítulo. <button className="btn btn-sm" onClick={() => runs.refetch()}>Reintentar</button></p>}
    {runs.data?.slice(0, count).map((r) => <article key={r.id} className="image-result">
      <p>{labels[r.state] ?? r.state} · {r.scenes.length} escenas</p>
      {r.error && <p role="alert">{r.error}</p>}
      {r.result_url && <><video controls preload="none" src={r.result_url} style={{ maxWidth: '100%', maxHeight: 480 }} /><p><a href={r.result_url} download>Descargar capítulo</a></p></>}
    </article>)}
    {runs.data && runs.data.length > count && <button className="btn btn-sm" onClick={() => setCount(count + 5)}>Ver montajes anteriores</button>}
  </section>
}
