import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Trash2 } from 'lucide-react'
import { memo, useEffect, useRef, useState } from 'react'
import { api, thumbUrl, type Scene } from '../api'
import { useToast } from './Toast'

const terminal = new Set(['completed', 'failed', 'cancelled'])
export const SceneImagePanel = memo(function SceneImagePanel({ scene, dirty, onApplied }: { scene: Scene; dirty: boolean; onApplied: (scene: Scene) => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const [count, setCount] = useState(3)
  const jobs = useQuery({ queryKey: ['image-generations', scene.id], queryFn: ({ signal }) => api.imageGenerations(scene.id, signal),
    refetchInterval: (q) => q.state.status === 'error' ? 30_000 : q.state.data?.some((j) => !terminal.has(j.state) || j.auto_finish_done === false)
      ? (q.state.data.some((j) => j.state === 'unknown') ? 15_000 : 2500) : 30_000,
    refetchIntervalInBackground: false, refetchOnWindowFocus: true })
  const refreshed = useRef(new Set<string>())
  useEffect(() => {
    for (const job of jobs.data ?? []) {
      if (job.state === 'completed' && job.auto_finish_done !== false && !refreshed.current.has(job.id)) {
        refreshed.current.add(job.id)
        qc.invalidateQueries({ queryKey: ['scenes', scene.chapter_id] })
        qc.invalidateQueries({ queryKey: ['generations', scene.id] })
      }
    }
  }, [jobs.data, qc, scene.chapter_id, scene.id])
  const active = jobs.data?.some((j) => !terminal.has(j.state) || j.auto_finish_done === false)
  const generate = useMutation({ mutationFn: (animate: boolean) => api.generateSceneImage(scene.id, scene.revision, crypto.randomUUID(), animate),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['image-generations', scene.id] }); toast.ok('Imagen añadida a la cola Qwen') },
    onError: (e) => { qc.invalidateQueries({ queryKey: ['image-generations', scene.id] }); toast.error(e.message) } })
  const approve = useMutation({ mutationFn: ({ id, role }: { id: string; role: 'start' | 'end' }) => api.approveSceneImage(id, scene.revision, role),
    onSuccess: (s) => { onApplied(s); qc.invalidateQueries({ queryKey: ['generations', scene.id] }); toast.ok('Imagen aprobada y asignada a la escena') },
    onError: (e) => toast.error(e.message) })
  const abandon = useMutation({ mutationFn: api.abandonGeneration,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['image-generations', scene.id] }), onError: (e) => toast.error(e.message) })
  const stop = useMutation({ mutationFn: api.stopGeneration,
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['image-generations', scene.id] }); toast.ok('Solicitud de detener enviada') },
    onError: (e: Error) => toast.error(e.message),
  })
  const discard = useMutation({ mutationFn: api.discardGenerationOutput,
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['image-generations', scene.id] }); toast.ok('Imagen descartada de Studio') },
    onError: (e: Error) => toast.error(e.message) })
  return <section aria-label="Imágenes Qwen de esta escena" className="scene-images">
    <p className="hint">{scene.parameters.cast?.length ? 'Qwen recibirá las referencias de los personajes en el orden guardado.' : 'Sin personajes seleccionados se utiliza Qwen desde texto.'} El nuevo perfil Qwen 2.1 prepara imágenes de 1152×2048. Los servidores con perfiles anteriores conservan 576×1024. Para animar se prepara una copia al tamaño de H3.</p>
    <button className="btn btn-primary" id="btn-generate-image" disabled={dirty || !scene.parameters.image_prompt?.trim() || active || generate.isPending || jobs.isPending || jobs.isError} onClick={() => generate.mutate(false)}>{active ? 'Imagen en generación' : 'Generar imagen con Qwen'}</button>
    {scene.parameters.image_approval === 'automatic' && <button className="btn" disabled={dirty || !scene.parameters.image_prompt?.trim() || !scene.prompt.trim() || active || generate.isPending || jobs.isPending || jobs.isError} onClick={() => generate.mutate(true)}>Generar imagen y después animar</button>}
    {dirty && <p className="hint">Guarda la escena antes de generar o asignar una imagen.</p>}
    {jobs.isError && <p role="alert">No se pudieron consultar las imágenes. <button className="btn btn-sm" onClick={() => jobs.refetch()}>Reintentar</button></p>}
    <div className="character-grid">{jobs.data?.slice(0, count).map((j) => <article key={j.id} className="image-result">
      <p>{j.state === 'completed' ? (j.approval_mode === 'automatic' && j.auto_finish_done ? 'Imagen procesada automáticamente' : 'Imagen lista para revisar') : j.state === 'failed' ? 'Generación fallida' : 'En cola o generando'} · r{j.revision_number}</p>
      {j.error && <p role="alert">{j.error}</p>}
      <p className="hint">{j.references.map((r, i) => `${i + 1}: ${r.name}`).join(' · ')}</p>
      {j.result_asset_id && <><a href={j.result_url!} target="_blank" rel="noreferrer"><img src={thumbUrl(j.result_asset_id, 512)} alt="Resultado Qwen para revisar" loading="lazy" /></a>
        <button className="btn btn-sm" disabled={dirty || approve.isPending} onClick={() => approve.mutate({ id: j.id, role: 'start' })}>Aprobar y usar de inicio</button>
        <button className="btn btn-sm" disabled={dirty || approve.isPending || !scene.start_asset} onClick={() => approve.mutate({ id: j.id, role: 'end' })}>Aprobar y usar de final</button>
        <button className="btn btn-sm" disabled={discard.isPending} onClick={() => {
          if (window.confirm('Eliminar esta imagen generada? Las imagenes usadas como referencia se conservan.')) discard.mutate(j.id)
        }}><Trash2 size={14}/> Descartar imagen</button></>}
      {(j.state === 'queued' || j.state === 'waiting' || j.state === 'running') && <button className="btn btn-sm" disabled={stop.isPending} onClick={() => {
        if (window.confirm('¿Detener esta generación Qwen? Solo se cancelará este trabajo.')) stop.mutate(j.id)
      }}>Detener generación</button>}
      {(j.state === 'queued' || j.state === 'unknown') && <button className="btn btn-sm" disabled={abandon.isPending} onClick={() => { if (window.confirm('Comprueba primero la cola remota. Cerrar este registro no detiene una generación ya enviada. ¿Cerrar?')) abandon.mutate(j.id) }}>Cerrar registro</button>}
    </article>)}</div>
    {jobs.data && jobs.data.length > count && <button className="btn btn-sm" onClick={() => setCount(count + 5)}>Ver imágenes anteriores</button>}
  </section>
})
