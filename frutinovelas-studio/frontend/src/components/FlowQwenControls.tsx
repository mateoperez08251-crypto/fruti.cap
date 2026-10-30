import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { flowApi, type FlowJob } from '../flow-api'

export function FlowQwenControls({ job, eligible = true, onUpdate }: { job: FlowJob; eligible?: boolean; onUpdate: () => void }) {
  const requestId = useRef(crypto.randomUUID())
  const [authorized, setAuthorized] = useState(false)
  const [notStarted, setNotStarted] = useState(false)
  const browser = job.execution_mode === 'browser' || job.result_metadata.executor === 'browser_qwen'
  const status = useQuery({ queryKey: ['flow-qwen-status'], queryFn: flowApi.qwenStatus, enabled: !browser, retry: 0, refetchInterval: 10000, refetchIntervalInBackground: false })
  const execute = useMutation({ mutationFn: () => flowApi.executeQwen(job.id, requestId.current, authorized, notStarted), onSuccess: onUpdate })
  if (browser) return <section className="flow-section" aria-label="Qwen en Chromium">
    <h3>Qwen en Chromium</h3>
    <p role="status">{job.result_metadata.qwen_message ?? 'Para que Qwen controle las imágenes pendientes, abre iniciar_qwen_chromium.cmd con Studio activo y el bot anterior cerrado.'}</p>
    <p className="hint">Qwen observa esta pestaña y decide las acciones. La descarga se compara con la imagen seleccionada y con las referencias antes de importarla.</p>
    {job.error && <p role="alert">{job.error}</p>}
  </section>
  if (job.result_metadata.executor === 'qwen') return <div className="flow-section">
    <p role="status">Qwen · Paso {job.result_metadata.qwen_step ?? 0} · {job.result_metadata.qwen_message ?? 'Pendiente de ejecución'}</p>
    {job.error && <p role="alert">{job.error}</p>}
  </div>
  if (!['queued', 'awaiting_import'].includes(job.state)) return null
  return <section className="flow-section" aria-label={`Ejecutar ${job.title} con Qwen`}>
    <h3>{job.title} · Control con Qwen</h3>
    <p className="hint">Qwen puede ejecutar esta toma, descargarla e importarla. Durante el control, podrá ver capturas del escritorio mediante tu servidor Qwen en Colab. Mantén UserFLEX abierto y deja libre el ratón mientras trabaja.</p>
    <label className="flow-check"><input type="checkbox" checked={authorized} onChange={event => setAuthorized(event.target.checked)}/> Permito que mi Qwen vea el escritorio y controle UserFLEX para esta toma.</label>
    <label className="flow-check"><input type="checkbox" checked={notStarted} onChange={event => setNotStarted(event.target.checked)}/> Esta toma todavía no se está generando en Flow.</label>
    <button className="btn btn-primary" disabled={execute.isPending || !eligible || !status.data?.configured || status.data?.worker_running === false || !authorized || !notStarted}
      onClick={() => execute.mutate()}>Ejecutar esta toma con Qwen</button>
    {(!status.data?.configured || status.data?.worker_running === false) && <p className="hint">{status.isError ? 'No se pudo consultar el ejecutor. Comprueba que Studio siga abierto y recarga esta página.' : status.data?.detail ?? 'Comprobando conexión Qwen…'}</p>}
    {execute.isError && <p role="alert">{execute.error.message}</p>}
  </section>
}

export function NarratedQwenControls({ jobId, onUpdate }: { jobId: string; onUpdate: () => void }) {
  const section = useRef<HTMLDivElement>(null)
  const detail = useQuery({ queryKey: ['flow-job', jobId], queryFn: () => flowApi.job(jobId),
    refetchInterval: 3000, refetchIntervalInBackground: false })
  const loadedId = detail.data?.id
  useEffect(() => {
    if (loadedId && window.location.hash === '#control-qwen') section.current?.scrollIntoView?.({ block: 'center' })
  }, [loadedId])
  if (detail.isError) return <p role="alert">No se pudo cargar la toma para ejecutar con Qwen.</p>
  if (!detail.data) return <p role="status">Cargando los controles Qwen de la toma…</p>
  return <div ref={section} id="control-qwen"><FlowQwenControls key={jobId} job={detail.data} onUpdate={() => { void detail.refetch(); onUpdate() }}/></div>
}
