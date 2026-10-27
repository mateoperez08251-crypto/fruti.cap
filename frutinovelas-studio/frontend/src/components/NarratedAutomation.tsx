import { useEffect, useRef, useState } from 'react'
import { api, assetUrl, type NarratedFlowJobStatus, type NarratedVideo, type VisualReference } from '../api'
import { FlowWindowPreview } from './FlowWindowPreview'
import { NarratedQwenControls } from './FlowQwenControls'

type Props = { video: NarratedVideo; dirty: boolean; onUpdate: (video: NarratedVideo) => void }
type JobStatus = NarratedFlowJobStatus
// Clip lengths offered by Flow (Omni 1.1 Flash). Studio never rounds to another length.
const CLIP_SECONDS = [4, 6, 8, 10]
const states: Record<string, string> = {
  queued: 'En cola', awaiting_import: 'Esperando el archivo de Flow', awaiting_approval: 'Espera aprobación de la imagen',
  submitting: 'Enviando', running: 'Generando', downloading: 'Descargando', completed: 'Resultado listo',
  failed: 'Falló', cancelled: 'Cancelado', unknown: 'Estado por comprobar', blocked: 'Requiere intervención',
}

export function NarratedAutomation({ video, dirty, onUpdate }: Props) {
  const [mode, setMode] = useState<'static' | 'animated'>(video.shots[0]?.media_mode ?? 'static')
  const [references, setReferences] = useState<VisualReference[]>(video.shots[0]?.references ?? [])
  const [style, setStyle] = useState(video.shots[0]?.visual_style ?? '')
  const [tool, setTool] = useState<'standard' | 'storyboard_studio'>(video.shots[0]?.flow_tool ?? 'standard')
  const [count, setCount] = useState(Math.min(90, Math.max(1, Math.round(video.audio_duration / 6))))
  const [clipSeconds, setClipSeconds] = useState(6)
  const [automatic, setAutomatic] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [jobs, setJobs] = useState<JobStatus[]>([])
  const pending = useRef<{ signature: string; requestId: string } | null>(null)
  const linked = video.shots.some(shot => shot.flow_scene_id)
  const exporting = video.state === 'queued' || video.state === 'rendering'
  const ready = video.shots.every(shot => shot.image_prompt.trim() &&
    (shot.media_mode !== 'animated' || shot.animation_prompt.trim()))
  const blocked = busy || dirty || exporting

  useEffect(() => {
    if (!linked || dirty || exporting || busy) return
    let active = true
    const refresh = async () => {
      if (document.hidden) return
      try {
        const result = await api.syncNarratedFlow(video.id, video.revision)
        if (!active) return
        setJobs(result.jobs)
        if (result.video.revision !== video.revision) onUpdate(result.video)
      } catch { /* Manual sync displays errors; background polling preserves edits. */ }
    }
    const interval = window.setInterval(() => void refresh(), 5000)
    return () => { active = false; window.clearInterval(interval) }
  }, [video.id, video.revision, linked, dirty, exporting, busy, onUpdate])

  const run = async (action: () => Promise<void>) => {
    setBusy(true); setError('')
    try { await action() }
    catch (e) { setError(e instanceof Error ? e.message : 'No se pudo completar la operación.') }
    finally { setBusy(false) }
  }
  const upload = (file: File | undefined, role: VisualReference['role']) => {
    if (!file) return
    void run(async () => {
      if (references.length >= 3) throw new Error('Se admiten hasta tres referencias en total.')
      const asset = await api.uploadAsset(file)
      if (references.some(ref => ref.asset_id === asset.id)) throw new Error('Esa referencia ya está seleccionada.')
      setReferences(old => [...old, { asset_id: asset.id, role, description: '' }])
    })
  }
  const plan = () => run(async () => {
    const result = await api.planNarratedVideo(video.id, { expected_revision: video.revision,
      media_mode: mode, shot_count: count, visual_style: style, references, flow_tool: tool })
    onUpdate(result)
  })
  const saveOptions = () => run(async () => {
    const result = await api.updateNarratedVideo(video.id, { expected_revision: video.revision,
      shots: video.shots.map(shot => ({ ...shot, references, visual_style: style, media_mode: mode, flow_tool: tool })) })
    onUpdate(result)
  })
  const send = (animate = false) => run(async () => {
    const body = { expected_revision: video.revision, automatic_approval: automatic, clip_seconds: clipSeconds }
    const signature = JSON.stringify({ ...body, animate })
    if (!pending.current || pending.current.signature !== signature) {
      pending.current = { signature, requestId: crypto.randomUUID() }
    }
    const result = await (animate ? api.animateNarratedImages : api.sendNarratedFlow)(video.id, { ...body, request_id: pending.current.requestId })
    onUpdate(result.video)
  })
  const sync = () => run(async () => {
    const result = await api.syncNarratedFlow(video.id, video.revision)
    setJobs(result.jobs)
    if (result.video.revision !== video.revision) onUpdate(result.video)
  })

  return <section className="narration-box" aria-label="Preparación con Qwen y Flow" aria-busy={busy}>
    <h3>Guion, referencias y generación</h3>
    <p className="hint">Qwen prepara los prompts a partir del guion guardado. El audio original determina la duración final.</p>
    {dirty && <p role="status">Guarda los cambios antes de preparar o enviar las tomas.</p>}
    <div className="narration-fields">
      <label>Forma del video<select value={mode} disabled={blocked || linked} onChange={e => setMode(e.target.value as typeof mode)}>
        <option value="static">Imágenes estáticas</option><option value="animated">Imágenes con clips cortos</option>
      </select></label>
      <label>Cantidad de tomas<input type="number" min={1} max={90} value={count} disabled={blocked || linked} onChange={e => setCount(Number(e.target.value))}/></label>
      <label>Herramienta de Flow<select value={tool} disabled={blocked || linked} onChange={e => setTool(e.target.value as typeof tool)}>
        <option value="standard">Generación estándar</option><option value="storyboard_studio">Storyboard Studio</option>
      </select></label>
      <label>Referencia de personaje u objeto<input type="file" accept="image/png,image/jpeg,image/webp" disabled={blocked || linked || references.length >= 3} onChange={e => upload(e.target.files?.[0], 'identity')}/></label>
      <label>Referencia de estilo visual<input type="file" accept="image/png,image/jpeg,image/webp" disabled={blocked || linked || references.length >= 3} onChange={e => upload(e.target.files?.[0], 'style')}/></label>
    </div>
    <label className="narration-field">Estilo visual para preparar con Qwen<textarea value={style} disabled={blocked || linked} rows={3} onChange={e => setStyle(e.target.value)} placeholder="Describe el estilo, la luz, los colores y lo que debe conservarse entre tomas."/></label>
    {references.map((ref, index) => <div className="row" key={ref.asset_id}>
      <img src={assetUrl(ref.asset_id)} alt={`Referencia ${index + 1}`} width={64} height={64} style={{ objectFit: 'contain' }}/>
      <label>Uso de referencia {index + 1}<select value={ref.role} disabled={blocked || linked} onChange={e => setReferences(old => old.map((r, i) => i === index ? { ...r, role: e.target.value as VisualReference['role'] } : r))}>
        <option value="identity">Identidad</option><option value="style">Estilo</option>
      </select></label>
      <label>Descripción de referencia {index + 1}<input value={ref.description} disabled={blocked || linked} onChange={e => setReferences(old => old.map((r, i) => i === index ? { ...r, description: e.target.value } : r))}/></label>
      <button className="btn btn-sm" disabled={blocked || linked} onClick={() => setReferences(old => old.filter((_, i) => i !== index))}>Quitar referencia {index + 1}</button>
    </div>)}
    <p className="hint">Hasta tres referencias. Preparar con Qwen envía el guion y las referencias elegidas a tu servidor configurado. Los tiempos propuestos son estimaciones editables, no alineación automática de palabras.</p>
    <button className="btn" disabled={blocked || linked || !video.transcript.trim() || count < 1 || count > 90} onClick={() => void plan()}>Preparar tomas con Qwen</button>
    <button className="btn" disabled={blocked || linked} onClick={() => void saveOptions()}>Guardar referencias y opciones</button>
    {video.shots.some(shot => shot.media_mode === 'animated') && <label>Segundos por clip corto<select value={clipSeconds} disabled={blocked} onChange={e => setClipSeconds(Number(e.target.value))}>{CLIP_SECONDS.map(s => <option key={s} value={s}>{s} s</option>)}</select></label>}
    <label className="flow-check"><input type="checkbox" checked={automatic} disabled={blocked || linked} onChange={e => setAutomatic(e.target.checked)}/> Aprobar automáticamente las imágenes de este envío y continuar con los clips solicitados</label>
    <div className="row">
      <button className="btn btn-primary" disabled={blocked || linked || !ready} onClick={() => void send()}>Enviar tomas guardadas a Flow</button>
      {linked && video.shots.some(shot => shot.media_mode === 'animated' && !shot.flow_video_job_id) &&
        <button className="btn" disabled={blocked} onClick={() => void send(true)}>Animar tomas con imagen aprobada</button>}
      {linked && <button className="btn" disabled={blocked} onClick={() => void sync()}>Sincronizar resultados de Flow</button>}
      <a className="btn" href={`/flow-automation?project_id=${encodeURIComponent(video.project_id)}${video.flow_chapter_id ? `&chapter_id=${encodeURIComponent(video.flow_chapter_id)}` : ''}`}>Abrir cola Flow</a>
      <FlowWindowPreview />
    </div>
    {linked && <p className="hint">Las tomas están vinculadas a la cola. El controlador activo o Qwen en Cline debe ejecutar los trabajos de Flow. Los resultados completados se sincronizan mientras esta pantalla está visible y no tiene cambios sin guardar.</p>}
    {busy && <p role="status">Procesando la solicitud…</p>}
    {linked && (() => {
      const active = jobs.find(job => ['awaiting_import', 'submitting', 'running', 'downloading', 'unknown', 'blocked', 'cancel_requested'].includes(job.state)) ?? jobs.find(job => job.state === 'queued')
      const firstId = active?.id ?? video.shots.find(shot => shot.flow_image_job_id)?.flow_image_job_id
      return firstId ? <NarratedQwenControls jobId={firstId} onUpdate={() => void sync()}/> : null
    })()}
    {jobs.map(job => <p key={job.id} role="status">Toma {job.shot == null ? '?' : job.shot + 1} · {job.kind === 'image' ? 'Imagen' : 'Clip'} · {states[job.state] ?? job.state}{job.error ? ` · ${job.error}` : ''}</p>)}
    {linked && <ShotVersions video={video} disabled={blocked} onUpdate={onUpdate} onError={setError}/>}
    {error && <p role="alert" className="generation-error">{error}</p>}
  </section>
}

function ShotVersions({ video, disabled, onUpdate, onError }: { video: NarratedVideo; disabled: boolean; onUpdate: (video: NarratedVideo) => void; onError: (message: string) => void }) {
  const [shot, setShot] = useState(0)
  const [versions, setVersions] = useState<JobStatus[] | null>(null)
  const current = video.shots[shot]
  const load = async (index: number) => {
    setShot(index); setVersions(null)
    try { setVersions(await api.narratedShotVersions(video.id, index)) }
    catch (e) { onError(e instanceof Error ? e.message : 'No se pudieron cargar las versiones.') }
  }
  const choose = async (jobId: string | null) => {
    try { onUpdate((await api.selectNarratedVersion(video.id, video.revision, shot, jobId)).video) }
    catch (e) { onError(e instanceof Error ? e.message : 'No se pudo elegir la versión.') }
  }
  return <details className="narration-versions">
    <summary>Versiones de imagen por toma</summary>
    <label>Toma<select value={shot} onChange={e => void load(Number(e.target.value))}>{video.shots.map((s, i) => s.flow_scene_id ? <option key={i} value={i}>Toma {i + 1}</option> : null)}</select></label>
    <button className="btn btn-sm" disabled={disabled} onClick={() => void load(shot)}>Ver versiones</button>
    {current?.selected_image_job_id && <button className="btn btn-sm" disabled={disabled} onClick={() => void choose(null)}>Usar la versión más reciente</button>}
    {versions?.length === 0 && <p className="hint">Sin versiones todavía.</p>}
    <div className="row">{versions?.map((v, i) => <figure key={v.id}>
      {v.result_url ? <img src={v.result_url} alt={`Versión ${i + 1} de la toma ${shot + 1}`} width={72} height={128} style={{ objectFit: 'cover' }}/> : <span className="hint">{states[v.state] ?? v.state}</span>}
      <figcaption>{current?.selected_image_job_id === v.id ? 'Fijada' : current?.image_asset_id && current.image_asset_id === v.result_asset_id ? 'En uso' : `Versión ${i + 1}`}</figcaption>
      {v.state === 'completed' && current?.selected_image_job_id !== v.id && <button className="btn btn-sm" disabled={disabled} onClick={() => void choose(v.id)}>Usar esta versión</button>}
    </figure>)}</div>
  </details>
}
