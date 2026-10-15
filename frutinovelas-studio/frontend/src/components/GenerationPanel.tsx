import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Download, Film, Loader2, RefreshCw } from 'lucide-react'
import { Link } from 'react-router-dom'
import { api, ApiError, type Generation, type Scene } from '../api'
import { useToast } from './Toast'

const terminal = new Set(['completed', 'failed'])
const labels: Record<Generation['state'], string> = {
  queued: 'En cola local', uploading: 'Preparando y subiendo imágenes', submitting: 'Enviando a ComfyUI',
  waiting: 'En cola de ComfyUI', running: 'Generando en la GPU', downloading: 'Descargando video',
  unknown: 'Comprobando recepción', completed: 'Video disponible', failed: 'Interrumpido o fallido',
}

export function GenerationPanel({ scene, dirty }: { scene: Scene; dirty: boolean }) {
  const qc = useQueryClient()
  const toast = useToast()
  const connection = useQuery({ queryKey: ['comfy-connection'], queryFn: api.comfyConnection })
  const jobs = useQuery({ queryKey: ['generations', scene.id], queryFn: () => api.generations(scene.id),
    refetchInterval: (q) => q.state.data?.some((j) => !terminal.has(j.state)) ? 2500 : 10_000 })
  const active = jobs.data?.find((j) => !terminal.has(j.state))
  const durationOk = scene.duration_seconds >= 4 && scene.duration_seconds <= 15
  const ready = !dirty && !!scene.start_asset && !!scene.prompt.trim() && durationOk && connection.data?.configured && !connection.isError && !jobs.isError && !active
  const generate = useMutation({
    mutationFn: () => api.generateScene(scene.id, scene.revision, crypto.randomUUID()),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['generations', scene.id] }); toast.ok('Escena añadida a la cola de generación') },
    onError: (error: ApiError) => { qc.invalidateQueries({ queryKey: ['generations', scene.id] }); toast.error(error.message) },
  })
  const abandon = useMutation({
    mutationFn: api.abandonGeneration,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['generations', scene.id] }),
    onError: (error: ApiError) => toast.error(error.message),
  })
  return <section className="scene-generation" aria-label="Generación de esta escena">
    <div className="generation-heading"><h3><Film size={18} /> Animación de esta escena</h3>
      <button className="btn btn-ghost btn-sm" onClick={() => jobs.refetch()} aria-label="Actualizar generaciones"><RefreshCw size={14} /></button></div>
    <p className="subtle">H3 · 9:16 · 20 pasos · {scene.end_asset ? 'inicio y final' : 'imagen inicial'} · las versiones anteriores se conservan.</p>
    {connection.isError && <p className="notice warn" role="alert">No se pudo consultar la configuración de ComfyUI. <button className="btn btn-sm" onClick={() => connection.refetch()}>Reintentar</button></p>}
    {connection.data && !connection.data.configured && <p className="notice warn"><Link to="/conexion">Configura la conexión con RunPod</Link> antes de generar.</p>}
    {dirty && <p className="subtle">Guarda los cambios con «Guardar» antes de generar.</p>}
    {!durationOk && <p className="notice warn">Para H3 selecciona entre 4 y 15 segundos; usa 5 s para esta prueba.</p>}
    <button id="btn-generate-scene" className="btn btn-primary" disabled={!ready || generate.isPending || jobs.isLoading}
      onClick={() => generate.mutate()}>{generate.isPending || active ? <Loader2 size={16} className="spin" /> : <Film size={16} />}
      {active ? 'Generación en curso' : 'Generar esta escena'}</button>
    <p className="subtle">Se utiliza la revisión guardada. Las referencias se ajustan al centro para cubrir 576×1024, conservando los originales.</p>
    {jobs.isError && <p role="alert">No se pudo consultar el progreso. Pulsa actualizar cuando vuelva la conexión.</p>}
    <div className="generation-list" aria-live="polite">{jobs.data?.map((job) => <article className="generation-item" key={job.id}>
      <div className="generation-heading"><strong>{labels[job.state]}</strong><span className="chip">r{job.revision_number}</span></div>
      <p className="subtle">{job.duration_seconds} s solicitados · {job.frames} frames · {job.effective_seconds.toFixed(2)} s efectivos · semilla {job.seed}</p>
      {job.revision_number !== scene.revision_number && <p className="subtle">Esta versión usa una revisión anterior de la escena.</p>}
      {job.error && <p className="generation-error">{job.error}</p>}
      {(job.state === 'unknown' || job.state === 'queued') && <button className="btn btn-ghost btn-sm" disabled={abandon.isPending} onClick={() => {
        if (window.confirm('Comprueba primero la cola de RunPod. Cerrar este registro no detiene una inferencia remota. ¿Ya comprobaste que puedes cerrar el trabajo?')) abandon.mutate(job.id)
      }}>{job.state === 'queued' ? 'Cancelar envío pendiente' : 'Marcar como interrumpida'}</button>}
      {job.result_url && <><video className="generation-video" src={job.result_url} controls preload="metadata" />
        <a className="btn btn-sm" href={job.result_url + '?download=true'}><Download size={14} /> Descargar video</a></>}
    </article>)}</div>
  </section>
}
