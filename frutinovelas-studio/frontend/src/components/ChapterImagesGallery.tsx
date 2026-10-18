import { useMutation, useQueries, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, thumbUrl, type Scene } from '../api'
import { useToast } from './Toast'

type Props = { scenes: Scene[] }
const terminal = new Set(['completed', 'failed'])

export function ChapterImagesGallery({ scenes }: Props) {
  const [open, setOpen] = useState(true)
  const qc = useQueryClient()
  const toast = useToast()
  const jobs = useQueries({
    queries: scenes.map((scene) => ({
      queryKey: ['image-generations', scene.id],
      queryFn: ({ signal }: { signal: AbortSignal }) => api.imageGenerations(scene.id, signal),
      enabled: open,
      staleTime: 4000,
      refetchInterval: (query: { state: { data?: { state: string }[] } }) =>
        query.state.data?.some((job) => !terminal.has(job.state)) ? 3000 : 30_000,
      refetchIntervalInBackground: false,
    })),
  })
  const approve = useMutation({
    mutationFn: ({ scene, jobId }: { scene: Scene; jobId: string }) =>
      api.approveSceneImage(jobId, scene.revision, 'start'),
    onSuccess: (scene) => {
      qc.setQueryData<Scene[]>(['scenes', scene.chapter_id], (all) =>
        all?.map((s) => s.id === scene.id ? scene : s))
      qc.invalidateQueries({ queryKey: ['chapters'] })
      qc.invalidateQueries({ queryKey: ['image-generations', scene.id] })
      toast.ok('Imagen asignada a la escena')
    },
    onError: (error: Error) => toast.error(error.message),
  })
  const completed = jobs.filter((q) => q.data?.some((j) => j.state === 'completed' && j.result_asset_id)).length
  const pendingReview = scenes.filter((scene, i) =>
    !scene.start_asset && jobs[i]?.data?.some((j) => j.state === 'completed' && j.result_asset_id)).length
  const loading = jobs.some((q) => q.isPending && open)
  return <details className="card chapter-image-gallery" open={open}
    onToggle={(e) => setOpen(e.currentTarget.open)}>
    <summary>Galería de imágenes Qwen · {completed}/{scenes.length} generadas
      {pendingReview > 0 ? ` · ${pendingReview} por revisar` : ''}
    </summary>
    {open && <div className="chapter-image-gallery-body">
      <p className="hint">Estas son las imágenes guardadas tras generar con Qwen. Las imágenes pendientes de revisión aparecen aquí aunque las escenas indiquen «Sin imagen». Se asignan como inicio solo cuando las apruebas.</p>
      {loading && <p role="status">Cargando los resultados del capítulo…</p>}
      <div className="chapter-image-grid">
        {scenes.map((scene, i) => {
          const query = jobs[i]
          const latest = query?.data?.[0]
          const imageJob = query?.data?.find((j) => j.state === 'completed' && j.result_asset_id)
          return <article className="chapter-image-card" key={scene.id}>
            <p><strong>{scene.order_index}. {scene.title}</strong></p>
            {imageJob?.result_asset_id ? <>
              <a href={imageJob.result_url ?? `/api/v1/assets/${imageJob.result_asset_id}/content`}
                target="_blank" rel="noreferrer" aria-label={`Ampliar imagen de ${scene.title}`}>
                <img src={thumbUrl(imageJob.result_asset_id, 512)} alt={`Imagen generada de ${scene.title}`} loading="lazy" />
              </a>
              <p className="hint">{scene.start_asset ? 'Escena con imagen inicial asignada' : 'Generada · pendiente de aprobación'}</p>
              {!scene.start_asset && <button className="btn btn-sm"
                disabled={approve.isPending}
                onClick={() => approve.mutate({ scene, jobId: imageJob.id })}>Aprobar imagen desde galería</button>}
            </> : <p className="hint">{query?.isError ? 'Error al leer resultado · vuelve a abrir la galería'
              : latest?.state === 'failed' ? `Generación fallida: ${latest.error || 'sin detalle'}`
              : latest ? 'Generando o en cola' : query?.isPending ? 'Cargando…' : 'Sin generación'}</p>}
          </article>
        })}
      </div>
    </div>}
  </details>
}
