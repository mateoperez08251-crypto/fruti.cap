import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, Download, Image as ImageIcon, Loader2, PlugZap, RefreshCw } from 'lucide-react'
import { useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api, type Scene } from '../api'
import { flowApi, type FlowAgentStatus, type FlowJob, type FlowMode, type FlowPlan, type FlowStatus } from '../flow-api'
import { ConfirmDialog } from '../components/Dialogs'
import { useToast } from '../components/Toast'

const terminal = ['completed', 'failed', 'cancelled']
const flowLabels: Record<string, string> = {
  queued: 'Pendiente', submitting: 'Enviando', running: 'En ejecución', downloading: 'Validando archivo',
  awaiting_import: 'Espera tu descarga', awaiting_approval: 'Espera aprobación de imagen',
  unknown: 'Recepción incierta', blocked: 'Requiere intervención', cancel_requested: 'Detención remota sin confirmar',
  completed: 'Completado · archivo verificado', failed: 'Fallido', cancelled: 'Cancelado localmente',
}

function detectionMessage(agent: FlowAgentStatus) {
  if (agent.reachable === false) return {
    title: 'Agente Windows sin conexión',
    next: 'Ejecuta iniciar_flow_agente.cmd en el mismo equipo que Studio y vuelve a detectar. No se pudo comprobar si Userflex está abierto.',
  }
  if (agent.profile_configured === false) return {
    title: 'Agente conectado; falta configurar Userflex',
    next: 'Configura el perfil de la ventana siguiendo la guía de instalación y reinicia el agente. Todavía no se puede comprobar si Userflex está abierto.',
  }
  if (!agent.window_open) return {
    title: 'No se pudo identificar la ventana de Userflex',
    next: 'Abre Userflex con Flow. Si ya está abierto, revisa que el perfil corresponda a esa ventana y que haya una sola coincidencia.',
  }
  if (agent.flow_available !== true) return {
    title: agent.flow_available === false ? 'Ventana encontrada; Flow no detectado' : 'Ventana encontrada; Flow sin verificar',
    next: 'Abre la sección Flow dentro de Userflex y vuelve a detectar. Si continúa igual, revisa los controles del perfil.',
  }
  if (agent.authentication !== 'verified_by_control') return {
    title: 'Ventana y Flow detectados; sesión sin verificar',
    next: 'Comprueba tu sesión en la ventana de Userflex. La detección todavía no confirma que puedas generar.',
  }
  if (!agent.available) return {
    title: 'Ventana y Flow detectados; controlador pendiente',
    next: 'Revisa y verifica el perfil local antes de conectar el controlador Windows.',
  }
  return { title: 'Userflex y Flow detectados', next: 'Pulsa Enfocar ventana para ver la ventana identificada en tu escritorio.' }
}

function FlowResult({ job, scene, refresh }: { job: FlowJob; scene?: Scene; refresh: () => void }) {
  const toast = useToast()
  const [open, setOpen] = useState(false)
  const [resolveOpen, setResolveOpen] = useState(false)
  const retryId = useRef(crypto.randomUUID())
  const detail = useQuery({ queryKey: ['flow-job', job.id], queryFn: () => flowApi.job(job.id), enabled: open })
  const action = useMutation({ mutationFn: (fn: () => Promise<unknown>) => fn(),
    onSuccess: () => { refresh(); toast.ok('Trabajo actualizado') }, onError: (e: Error) => toast.error(e.message) })
  const run = (fn: () => Promise<unknown>) => { if (!action.isPending) action.mutate(fn) }
  return <article className="card flow-job">
    <div className="row flow-between"><strong>{job.title} · {job.kind === 'image' ? 'Imagen' : 'Video'}</strong>
      <span className="flow-state">{flowLabels[job.state] ?? job.state}</span></div>
    <p className="hint">{new Date(job.created_at).toLocaleString()} · Revisión {job.scene_revision} · {job.id.slice(0, 8)}</p>
    {job.error && <p className="notice warn" role="status">{job.error}</p>}
    {job.result_url && <div className="flow-preview">
      {job.kind === 'image' ? <a href={job.result_url} target="_blank" rel="noreferrer"><img src={job.result_url} alt={`Resultado de ${job.title}`} loading="lazy" /></a>
        : <video src={job.result_url} controls muted preload="none" aria-label={`Video de ${job.title}`} />}
      <a className="btn btn-ghost" href={job.result_url} download><Download size={15} /> Descargar original</a>
      {job.result_metadata.duration_seconds != null && <span className="hint">Duración real: {job.result_metadata.duration_seconds.toFixed(2)} s</span>}
    </div>}
    {job.kind === 'image' && job.state === 'completed' && <div className="row">
      {job.approval === 'pending' ? <>
        <button className="btn btn-primary" disabled={action.isPending || !scene} onClick={() => run(() => flowApi.review(job.id, scene!.revision, 'approved'))}><Check size={15} /> Aprobar y usar de inicio</button>
        <button className="btn btn-ghost" disabled={action.isPending || !scene} onClick={() => run(() => flowApi.review(job.id, scene!.revision, 'rejected'))}>Rechazar</button>
      </> : <span className="hint">{job.approval === 'approved' ? 'Imagen aprobada' : 'Imagen rechazada; original conservado'}</span>}
    </div>}
    <div className="row flow-actions">
      <button className="btn btn-ghost" onClick={() => setOpen(!open)}>{open ? 'Ocultar solicitud' : 'Ver prompt y referencias'}</button>
      {!terminal.includes(job.state) && job.state !== 'awaiting_approval' && <label className={`btn ${action.isPending ? 'muted' : ''}`}>
        Importar {job.kind === 'video' ? 'MP4' : 'imagen'}
        <input type="file" className="flow-file" aria-label={`Importar resultado de ${job.title}`} disabled={action.isPending}
          accept={job.kind === 'video' ? 'video/mp4' : 'image/png,image/jpeg,image/webp'}
          onChange={e => { const file = e.target.files?.[0]; if (file) run(() => flowApi.import(job.id, file)); e.target.value = '' }} />
      </label>}
      {!terminal.includes(job.state) && <button className="btn btn-ghost" disabled={action.isPending} onClick={() => run(() => flowApi.cancel(job.id))}>Cancelar localmente</button>}
      {['failed', 'cancelled'].includes(job.state) && job.remote_stopped && <button className="btn" disabled={action.isPending}
        onClick={() => run(() => flowApi.retry(job.id, retryId.current))}><RefreshCw size={14} /> Reintentar</button>}
      {['unknown', 'blocked', 'cancel_requested'].includes(job.state) && <button className="btn btn-ghost" onClick={() => setResolveOpen(true)}>Resolver manualmente</button>}
    </div>
    {open && detail.data?.snapshot && <div className="flow-prompt">
      <p className="hint">Prompt enviado · formato {detail.data.snapshot.aspect_ratio}. Las referencias originales se conservan.</p>
      <pre>{detail.data.snapshot.prompt}</pre>
      <button className="btn" onClick={() => navigator.clipboard.writeText(detail.data!.snapshot!.prompt).then(() => toast.ok('Prompt copiado')).catch(() => toast.error('No se pudo copiar; selecciona el texto.'))}>Copiar prompt</button>
      <div className="row">{detail.data.snapshot.references.map(ref => <img key={ref.asset_id} className="flow-ref" src={`/api/v1/assets/${ref.asset_id}/content`} alt="Referencia guardada" />)}</div>
    </div>}
    {detail.isError && open && <p role="alert">No se pudo leer la solicitud. Vuelve a abrirla.</p>}
    {resolveOpen && <ConfirmDialog title="Verificar el trabajo en Flow" danger confirmText="Confirmo que ya no hay generación remota"
      text="Comprueba la ventana de Flow y su historial. Si existe un resultado, impórtalo. Solo libera esta reserva si confirmaste que la generación terminó o se detuvo. Para UIA, reconcilia también el diario del agente con el comando indicado en la guía."
      onClose={() => setResolveOpen(false)} onConfirm={async () => { await flowApi.resolve(job.id, 'El usuario verificó el estado en la ventana de Flow.'); refresh() }} />}
  </article>
}

function FlowChapter({ projectId, chapterId, connected, mode, durations }: { projectId: string; chapterId: string; connected: boolean; mode: FlowMode; durations: number[] }) {
  const qc = useQueryClient()
  const toast = useToast()
  const scenes = useQuery({ queryKey: ['scenes', chapterId], queryFn: () => api.scenes(chapterId) })
  const jobs = useQuery({ queryKey: ['flow-jobs', projectId, chapterId], queryFn: () => flowApi.jobs(projectId, chapterId),
    refetchInterval: q => q.state.data?.some(j => !terminal.includes(j.state)) ? 5000 : 30000,
    refetchIntervalInBackground: false })
  const [selected, setSelected] = useState<string[]>([])
  const [generationMode, setGenerationMode] = useState<FlowPlan['generation_mode']>('image')
  const [auto, setAuto] = useState(false)
  const [duration, setDuration] = useState('')
  const [prompts, setPrompts] = useState<Record<string, string>>({})
  const [videoPrompts, setVideoPrompts] = useState<Record<string, string>>({})
  const [filter, setFilter] = useState('all')
  const pending = useRef<{ key: string; id: string } | null>(null)
  const refresh = () => { qc.invalidateQueries({ queryKey: ['flow-jobs'] }); qc.invalidateQueries({ queryKey: ['scenes', chapterId] }); qc.invalidateQueries({ queryKey: ['flow-job'] }) }
  const generate = useMutation({ mutationFn: () => {
    const current = scenes.data?.filter(s => selected.includes(s.id)) ?? []
    const payload = { project_id: projectId, chapter_id: chapterId, scene_revisions: Object.fromEntries(current.map(s => [s.id, s.revision])),
      generation_mode: generationMode, automatic_approval: auto,
      prompts: Object.fromEntries(Object.entries(prompts).filter(([id]) => selected.includes(id))),
      video_prompts: Object.fromEntries(Object.entries(videoPrompts).filter(([id]) => selected.includes(id))),
      duration_seconds: duration ? Number(duration) : null }
    const key = JSON.stringify(payload)
    if (!pending.current || pending.current.key !== key) pending.current = { key, id: crypto.randomUUID() }
    return flowApi.generate({ ...payload, request_id: pending.current.id })
  }, onSuccess: data => { pending.current = null; refresh(); toast.ok(`${data.length} trabajos guardados en la cola Flow`) },
  onError: (e: Error) => toast.error(e.message) })
  const visible = jobs.data?.filter(j => filter === 'all' || (filter === 'results' ? j.state === 'completed' : j.state === filter)) ?? []
  return <>
    <section className="card flow-section">
      <div className="row flow-between"><h2>Generación por escenas</h2><Link className="btn btn-ghost" to={`/capitulos/${chapterId}`}>Abrir editor Qwen / H3</Link></div>
      <p className="muted">Flow usa una cola independiente. Cada solicitud conserva el prompt, las referencias y la revisión de la escena.</p>
      <div className="flow-form-grid">
        <div className="field"><label htmlFor="flow-generation">Generar con Flow</label><select className="input" id="flow-generation" value={generationMode} onChange={e => setGenerationMode(e.target.value as FlowPlan['generation_mode'])}>
          <option value="image">Imágenes</option><option value="video">Videos desde imágenes iniciales</option><option value="image_video">Imágenes y después animarlas</option>
        </select></div>
        {generationMode !== 'image' && <div className="field"><label htmlFor="flow-duration">Duración solicitada</label>
          {mode === 'uia' ? <select id="flow-duration" className="input" value={duration} onChange={e => setDuration(e.target.value)}><option value="">Duración guardada por escena</option>{durations.map(d => <option key={d} value={d}>{d} segundos</option>)}</select>
            : <input id="flow-duration" className="input" type="number" min="1" max="60" value={duration} onChange={e => setDuration(e.target.value)} placeholder="Duración guardada por escena" />}
          <span className="hint">Solo se envían opciones compatibles con el perfil verificado. En modo asistido, compruébalas en Flow.</span>
        </div>}
      </div>
      <button className="btn btn-ghost" onClick={() => setSelected(selected.length ? [] : scenes.data?.map(s => s.id) ?? [])}>{selected.length ? 'Quitar selección' : 'Seleccionar todas'}</button>
      <div className="flow-scenes">{scenes.data?.map(scene => <div className="flow-scene" key={scene.id}>
        <label><input type="checkbox" checked={selected.includes(scene.id)} onChange={e => setSelected(e.target.checked ? [...selected, scene.id] : selected.filter(id => id !== scene.id))} /> {scene.order_index}. {scene.title}</label>
        <details><summary>Revisar o adaptar prompts para Flow</summary>
          <p className="hint">La adaptación se guarda solo en esta generación. El prompt original de la escena permanece en su revisión.</p>
          <label>Prompt de imagen<textarea className="textarea" value={prompts[scene.id] ?? scene.parameters.image_prompt ?? ''} onChange={e => setPrompts({ ...prompts, [scene.id]: e.target.value })} /></label>
          <label>Prompt de video para Flow<textarea className="textarea" value={videoPrompts[scene.id] ?? scene.prompt} onChange={e => setVideoPrompts({ ...videoPrompts, [scene.id]: e.target.value })} /></label>
        </details>
      </div>)}</div>
      {scenes.isError && <p role="alert">No se pudieron cargar las escenas.</p>}
      <label className="flow-check"><input type="checkbox" checked={auto} onChange={e => setAuto(e.target.checked)} /> Aprobar imágenes automáticamente para esta solicitud</label>
      {!auto && <p className="hint">Aprobación manual activa. En «Imágenes y después animarlas», los videos esperan tu aprobación.</p>}
      <button className="btn btn-primary" disabled={!connected || !selected.length || generate.isPending} onClick={() => generate.mutate()}>
        {generate.isPending ? <Loader2 size={16} className="spin" /> : <ImageIcon size={16} />} Encolar {selected.length} escenas
      </button>
    </section>
    <section className="flow-section">
      <div className="row flow-between"><h2>Cola, resultados y versiones</h2><select className="input" aria-label="Filtrar trabajos" value={filter} onChange={e => setFilter(e.target.value)}>
        <option value="all">Todos</option><option value="results">Biblioteca de resultados</option>{['queued', 'running', 'awaiting_import', 'awaiting_approval', 'unknown', 'blocked', 'failed', 'cancelled'].map(s => <option key={s} value={s}>{flowLabels[s]}</option>)}
      </select></div>
      <p className="hint">Los MP4 conservan su audio original. Esta sección no sustituye la narración externa del montaje.</p>
      {jobs.isError && <p role="alert">No se pudo actualizar la cola.</p>}
      {!visible.length && <p className="muted">No hay trabajos en esta selección.</p>}
      <div className="flow-results">{visible.map(job => <FlowResult key={job.id} job={job} scene={scenes.data?.find(s => s.id === job.scene_id)} refresh={refresh} />)}</div>
    </section>
  </>
}

export function FlowPage() {
  const [params, setParams] = useSearchParams()
  const projectId = params.get('project_id') ?? ''
  const chapterId = params.get('chapter_id') ?? ''
  const qc = useQueryClient()
  const toast = useToast()
  const [mode, setMode] = useState<FlowMode>('assisted')
  const [authorized, setAuthorized] = useState(false)
  const projects = useQuery({ queryKey: ['projects'], queryFn: () => api.projects() })
  const chapters = useQuery({ queryKey: ['chapters', projectId], queryFn: () => api.chapters(projectId), enabled: !!projectId })
  const status = useQuery({ queryKey: ['flow-status'], queryFn: flowApi.status, refetchInterval: 30000, refetchIntervalInBackground: false, retry: 0 })
  const detection = useMutation({
    mutationFn: async () => ({ agent: await flowApi.detect(), checkedAt: new Date().toISOString() }),
    onSuccess: ({ agent }) => qc.setQueryData<FlowStatus>(['flow-status'], previous => previous ? { ...previous, agent } : previous),
  })
  const agent = detection.isError ? undefined : detection.data?.agent ?? status.data?.agent
  const detectionError = detection.error ?? (!detection.data && status.error)
  const message = detection.isPending ? { title: 'Buscando Userflex y Flow…', next: 'Comprobando el agente y la ventana configurada. Espera unos segundos.' }
    : detectionError ? { title: 'No se pudo completar la detección', next: detectionError.message }
      : agent ? detectionMessage(agent) : { title: 'Comprobando agente local…', next: 'También puedes pulsar Detectar Userflex / Flow.' }
  const connect = useMutation({ mutationFn: () => status.data?.connected ? flowApi.disconnect() : flowApi.connect(mode, authorized),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['flow-status'] }), onError: (e: Error) => toast.error(e.message) })
  return <div className="page flow-page">
    <header className="page-head"><div><div className="eyebrow">PROVEEDOR ADICIONAL</div><h1>Flow Automation</h1><p className="muted">Imágenes, revisión y animación por escena.</p></div></header>
    <section className="card flow-section">
      <div className="row flow-between"><h2><PlugZap size={20} /> Conexión</h2><span className="flow-state">{status.data?.connected ? `Conectado · ${status.data.mode === 'uia' ? 'Control Windows' : 'Modo asistido'}` : 'Desconectado'}</span></div>
      <div className="notice" role={detectionError && !detection.isPending ? 'alert' : 'status'} aria-label="Resultado de detección" aria-busy={detection.isPending}>
        <div><strong>{message.title}</strong><p>{message.next}</p>
          {!detection.isPending && !detectionError && agent && <>
            {agent.window_open && agent.window_title && <p>Ventana identificada: <strong>{agent.window_title}</strong></p>}
            <p className="hint">{agent.detail}</p>
          </>}
          {detection.isSuccess && <p className="hint">Última detección: <time dateTime={detection.data.checkedAt}>{new Date(detection.data.checkedAt).toLocaleTimeString()}</time></p>}
        </div>
      </div>
      {!detection.isPending && agent && <p className="hint">Ventana: {agent.window_open == null ? 'sin comprobar' : agent.window_open ? 'abierta' : 'sin identificar'} · Flow: {agent.flow_available == null ? 'sin verificar' : agent.flow_available ? 'detectado' : 'sin detectar'} · Sesión: {agent.authentication === 'verified_by_control' ? 'verificada por control accesible' : 'sin verificar'}</p>}
      <div className="field"><label htmlFor="flow-mode">Controlador</label><select id="flow-mode" className="input" disabled={status.data?.connected} value={status.data?.connected ? status.data.mode : mode} onChange={e => setMode(e.target.value as FlowMode)}>
        <option value="assisted">Asistido: generar en Flow e importar la descarga</option><option value="uia">Windows UIA: requiere perfil local verificado</option>
      </select></div>
      {!status.data?.connected && <label className="flow-check"><input type="checkbox" checked={authorized} onChange={e => setAuthorized(e.target.checked)} /> Tengo autorización para usar este controlador con mi sesión.</label>}
      <div className="row"><button className="btn btn-primary" disabled={connect.isPending || (!status.data?.connected && !authorized)} onClick={() => connect.mutate()}>{status.data?.connected ? 'Desconectar y pausar cola' : 'Conectar'}</button>
        <button className="btn" disabled={detection.isPending} onClick={() => detection.mutate()}>
          {detection.isPending && <Loader2 size={16} className="spin" />}{detection.isPending ? 'Detectando…' : 'Detectar Userflex / Flow'}</button>
        <button className="btn btn-ghost" disabled={detection.isPending || !agent?.window_open} onClick={() => flowApi.focus().catch((e: Error) => toast.error(e.message))}>Enfocar ventana</button></div>
      <details><summary>Instalación y conexión MCP</summary><p className="muted">Abre <code>iniciar_flow_agente.cmd</code> en Windows. La guía <code>docs/FLOW_AUTOMATION.md</code> explica el diagnóstico, la verificación de controles y la recuperación. El MCP local por stdio incluye Flow; HTTP requiere un token MCP configurado. Sin perfil verificado, utiliza el modo asistido.</p></details>
    </section>
    <section className="card flow-section flow-form-grid">
      <div className="field"><label htmlFor="flow-project">Proyecto</label><select id="flow-project" className="input" value={projectId} onChange={e => setParams(e.target.value ? { project_id: e.target.value } : {})}><option value="">Selecciona un proyecto</option>{projects.data?.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select></div>
      <div className="field"><label htmlFor="flow-chapter">Capítulo</label><select id="flow-chapter" className="input" value={chapterId} disabled={!projectId} onChange={e => setParams({ project_id: projectId, chapter_id: e.target.value })}><option value="">Selecciona un capítulo</option>{chapters.data?.map(c => <option key={c.id} value={c.id}>{c.title}</option>)}</select></div>
    </section>
    {projectId && chapterId && <FlowChapter key={`${projectId}:${chapterId}`} projectId={projectId} chapterId={chapterId}
      connected={!!status.data?.connected} mode={status.data?.mode ?? mode} durations={status.data?.agent.modes.video?.durations ?? []} />}
  </div>
}
