import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Download, Film, Loader2, RefreshCw, Trash2 } from 'lucide-react'
import { memo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, ApiError, type Generation, type Scene } from '../api'
import { useToast } from './Toast'
import { RecoverQueue } from './RecoverQueue'

const terminal = new Set(['completed', 'failed', 'cancelled'])
const labels: Record<Generation['state'], string> = {
  queued: 'En cola local', uploading: 'Preparando y subiendo referencias', submitting: 'Enviando a ComfyUI',
  waiting: 'En cola de ComfyUI', running: 'Generando en la GPU', downloading: 'Descargando video',
  unknown: 'Comprobando recepción', completed: 'Video disponible', failed: 'Interrumpido o fallido', cancelled: 'Detenido manualmente',
}

export const GenerationPanel = memo(function GenerationPanel({ scene, dirty }: { scene: Scene; dirty: boolean }) {
  const qc = useQueryClient()
  const toast = useToast()
  const [visibleCount, setVisibleCount] = useState(3)
  const connection = useQuery({ queryKey: ['comfy-connection'], queryFn: api.comfyConnection })
  const jobs = useQuery({ queryKey: ['generations', scene.id],
    queryFn: ({ signal }) => api.generations(scene.id, signal),
    refetchInterval: (q) => {
      if (q.state.status === 'error') return 30_000
      const active = q.state.data?.find((j) => !terminal.has(j.state))
      return active ? (active.state === 'unknown' ? 15_000 : 2500) : 30_000
    },
    refetchOnWindowFocus: true,
    refetchIntervalInBackground: false,
  })
  const active = jobs.data?.find((j) => !terminal.has(j.state))
  const durationOk = scene.duration_seconds >= 4 && scene.duration_seconds <= 15
  const ready = !dirty && !!scene.start_asset && !!scene.prompt.trim() && durationOk && connection.data?.configured && !connection.isError && !jobs.isError && !active
  const generate = useMutation({
    mutationFn: () => api.generateScene(scene.id, scene.revision, crypto.randomUUID()),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['generations', scene.id] }); toast.ok('Escena añadida a la cola de generación') },
    onError: (error: ApiError) => { qc.invalidateQueries({ queryKey: ['generations', scene.id] }); toast.error(error.message) },
  })
  const stop = useMutation({ mutationFn: api.stopGeneration,
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['generations', scene.id] }); toast.ok('Solicitud de detener enviada') },
    onError: (error: ApiError) => toast.error(error.message),
  })
  const discard = useMutation({
    mutationFn: api.discardGenerationOutput,
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['generations', scene.id] }); toast.ok('Archivo descartado del almacenamiento de Studio') },
    onError: (e: Error) => toast.error(e.message),
  })
  return <section className="scene-generation" aria-label="Generación de esta escena">
    <div className="generation-heading"><h3><Film size={18} /> Animación de esta escena</h3>
      <button className="btn btn-ghost btn-sm" onClick={() => jobs.refetch()} aria-label="Actualizar generaciones"><RefreshCw size={14} /></button></div>
    <p className="subtle">H3 · 9:16 · 20 pasos · {scene.end_asset ? 'inicio y final' : 'imagen inicial'}{scene.parameters.voice_character_ids?.length ? ' · voces de los personajes' : scene.parameters.audio_guides?.length ? ' · audio preparado' : ''} · las versiones anteriores se conservan.</p>
    {connection.isError && <p className="notice warn" role="alert">No se pudo consultar la configuración de ComfyUI. <button className="btn btn-sm" onClick={() => connection.refetch()}>Reintentar</button></p>}
    {connection.data && !connection.data.configured && <p className="notice warn"><Link to="/conexion">Configura la conexión con RunPod</Link> antes de generar.</p>}
    {dirty && <p className="subtle">Guarda los cambios con «Guardar» antes de generar.</p>}
    {!durationOk && <p className="notice warn">Para H3 selecciona entre 4 y 15 segundos; usa 5 s para esta prueba.</p>}
    <button id="btn-generate-scene" className="btn btn-primary" disabled={!ready || generate.isPending || jobs.isLoading}
      onClick={() => generate.mutate()}>{generate.isPending || active ? <Loader2 size={16} className="spin" /> : <Film size={16} />}
      {active ? 'Generación en curso' : 'Generar esta escena'}</button>
    <p className="subtle">Se utiliza la revisión guardada. Las imágenes se ajustan al centro para cubrir 576×1024, conservando los originales.</p>
    {jobs.isError && <p role="alert">No se pudo consultar el progreso. Pulsa actualizar cuando vuelva la conexión.</p>}
    <RecoverQueue />
    <div className="generation-list" aria-live="polite">{jobs.data?.slice(0, visibleCount).map((job) => <article className="generation-item" key={job.id}>
      <div className="generation-heading"><strong>{labels[job.state]}</strong><span className="chip">r{job.revision_number}</span></div>
      <p className="subtle">{job.duration_seconds} s solicitados · {job.frames} frames · {job.effective_seconds.toFixed(2)} s efectivos · semilla {job.seed}</p>
      {job.revision_number !== scene.revision_number && <p className="subtle">Esta versión usa una revisión anterior de la escena.</p>}
      {job.error && <p className="generation-error">{job.error}</p>}
      {(job.state === 'failed' || job.state === 'cancelled') && <button className="btn btn-sm" disabled={!ready || generate.isPending} onClick={() => generate.mutate()}>Reintentar escena guardada</button>}
      {(job.state === 'queued' || job.state === 'uploading' || job.state === 'waiting' || job.state === 'running') && <button className="btn btn-ghost btn-sm" disabled={stop.isPending} onClick={() => {
        if (window.confirm('¿Detener esta generación? Solo se actuará sobre su trabajo; no se vaciará la cola completa.')) stop.mutate(job.id)
      }}>Detener generación</button>}
      {job.result_url && <><video className="generation-video" src={job.result_url} controls preload="none" />
        <a className="btn btn-sm" href={job.result_url + '?download=true'}><Download size={14} /> Descargar video</a>
        <button className="btn btn-ghost btn-sm" disabled={discard.isPending} onClick={() => {
          if (window.confirm('Eliminar esta version del video de Studio? La copia de ComfyUI no se borrara aun.')) discard.mutate(job.id)
        }}><Trash2 size={14} /> Descartar version</button></>}
    </article>)}</div>
    {jobs.data && jobs.data.length > visibleCount && <button className="btn btn-ghost btn-sm"
      onClick={() => setVisibleCount((count) => count + 5)}>Ver versiones anteriores ({jobs.data.length - visibleCount})</button>}
  </section>
})
