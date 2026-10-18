import { useEffect, useState } from 'react'
import { api, ApiError, assetUrl, type NarratedVideo, type NarratedShot } from '../api'
import { Film, Plus, Save, Upload, WandSparkles, Play, Music2 } from 'lucide-react'

const motions: NarratedShot['motion'][] = ['zoom_in', 'zoom_out', 'pan_left', 'pan_right', 'still']
const labels: Record<NarratedShot['motion'], string> = {
  zoom_in: 'Acercamiento suave', zoom_out: 'Alejamiento suave',
  pan_left: 'Desplazar izquierda', pan_right: 'Desplazar derecha', still: 'Imagen fija',
}
const time = (n: number) => n.toFixed(2)
const blank = (start: number, end: number): NarratedShot => ({
  start_seconds: start, end_seconds: end, text: '', image_prompt: '', animation_prompt: '', image_asset_id: null, motion: 'zoom_in',
})

export function NarratedPage() {
  const [projects, setProjects] = useState<{ id: string; name: string }[]>([])
  const [projectId, setProjectId] = useState('')
  const [videos, setVideos] = useState<NarratedVideo[]>([])
  const [current, setCurrent] = useState<NarratedVideo | null>(null)
  const [draft, setDraft] = useState<NarratedVideo | null>(null)
  const [newTitle, setNewTitle] = useState('Mi video narrado')
  const [file, setFile] = useState<File | null>(null)
  const [newTranscript, setNewTranscript] = useState('')
  const [ratio, setRatio] = useState<'9:16' | '16:9'>('9:16')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  useEffect(() => { void api.projects().then(p => { setProjects(p); if (p[0]) setProjectId(p[0].id) }).catch(() => setError('No se pudieron abrir los proyectos.')) }, [])
  useEffect(() => {
    if (!projectId) return
    void api.narratedVideos(projectId).then(setVideos).catch(() => setError('No se pudieron cargar los videos.'))
    setCurrent(null); setDraft(null)
  }, [projectId])
  useEffect(() => {
    if (!current || !['queued', 'rendering'].includes(current.state)) return
    const poll = window.setInterval(() => { void api.narratedVideo(current.id).then(v => {
      setCurrent(v)
      setDraft(d => d && d.id === v.id ? { ...d, state: v.state, progress: v.progress, error: v.error, result_url: v.result_url } : v)
    }).catch(() => {}) }, 3000)
    return () => window.clearInterval(poll)
  }, [current])
  const choose = (v: NarratedVideo) => { setCurrent(v); setDraft(structuredClone(v)); setError(''); setNotice('') }
  const edit = (change: Partial<NarratedVideo>) => setDraft(v => v ? { ...v, ...change } : v)
  const changeShot = (i: number, change: Partial<NarratedShot>) => {
    if (!draft) return
    edit({ shots: draft.shots.map((s, j) => j === i ? { ...s, ...change } : s) })
  }
  const fail = (e: unknown) => setError(e instanceof ApiError ? e.message : 'No se pudo completar la operación.')
  const create = async () => {
    if (!projectId || !file || !newTitle.trim()) { setError('Selecciona un proyecto, un título y un audio.'); return }
    setBusy(true); setError(''); setNotice('')
    try {
      const audio = await api.uploadNarration(file)
      const v = await api.createNarratedVideo(projectId, { title: newTitle.trim(), audio_asset_id: audio.id, transcript: newTranscript, aspect_ratio: ratio })
      setVideos(old => [v, ...old]); choose(v); setFile(null)
    } catch (e) { fail(e) } finally { setBusy(false) }
  }
  const save = async () => {
    if (!draft) return
    setBusy(true); setError(''); setNotice('')
    try {
      const v = await api.updateNarratedVideo(draft.id, { expected_revision: draft.revision, title: draft.title, transcript: draft.transcript, shots: draft.shots, aspect_ratio: draft.aspect_ratio })
      choose(v); setNotice('Guion visual guardado.')
    } catch (e) { fail(e) } finally { setBusy(false) }
  }
  const render = async () => {
    if (!draft || !current) return
    if (JSON.stringify(draft.shots) !== JSON.stringify(current.shots) || draft.transcript !== current.transcript || draft.title !== current.title || draft.aspect_ratio !== current.aspect_ratio) {
      setError('Guarda los cambios antes de exportar.'); return
    }
    setBusy(true); setError(''); setNotice('')
    try { const v = await api.renderNarratedVideo(draft.id, draft.revision); choose(v); setNotice('Montaje iniciado. Conservaremos el audio original.') }
    catch (e) { fail(e) } finally { setBusy(false) }
  }
  const split = (i: number) => {
    if (!draft) return
    const s = draft.shots[i], mid = Number(((s.start_seconds+s.end_seconds)/2).toFixed(3))
    if (s.end_seconds-s.start_seconds < 1) { setError('La toma debe durar por lo menos un segundo para dividirse.'); return }
    const copy = [...draft.shots]
    copy.splice(i, 1, {...s, end_seconds: mid}, blank(mid, s.end_seconds))
    edit({shots: copy}); setError('')
  }
  const join = (i: number) => {
    if (!draft || i < 1) return
    const copy = [...draft.shots]; copy[i - 1] = {...copy[i-1], end_seconds: copy[i].end_seconds}
    copy.splice(i, 1); edit({shots: copy})
  }
  const image = async (i: number, f: File | undefined) => {
    if (!f) return
    setBusy(true); setError('')
    try { const asset = await api.uploadAsset(f); changeShot(i, {image_asset_id: asset.id}) }
    catch (e) { fail(e) } finally { setBusy(false) }
  }

  return <div className="page narration-page">
    <header className="page-head"><div><div className="eyebrow"><Film size={14}/> Nuevo modo creativo</div>
      <h1>Videos <span className="gradient-text">narrados</span></h1>
      <p className="muted">Una voz completa y pequeñas animaciones visuales sincronizadas. Hasta 5 minutos.</p>
    </div></header>
    <section className="card narration-box">
      <h3><Music2 size={17}/> 1. Audio de la historia</h3>
      <p className="hint">Sube WAV, MP3, M4A o audio compatible. Este modo usa la narración como pista principal; no modifica las voces.</p>
      <div className="narration-fields">
        <label>Proyecto<select value={projectId} onChange={e => setProjectId(e.target.value)}>{projects.map(p=><option key={p.id} value={p.id}>{p.name}</option>)}</select></label>
        <label>Título<input value={newTitle} onChange={e=>setNewTitle(e.target.value)}/></label>
        <label>Formato<select value={ratio} onChange={e=>setRatio(e.target.value as '9:16'|'16:9')}><option value="9:16">Vertical 9:16</option><option value="16:9">Horizontal 16:9</option></select></label>
        <label>Audio completo<input type="file" accept="audio/*,.mp3,.wav,.m4a,.flac,.ogg,.webm" onChange={e=>setFile(e.target.files?.[0] || null)}/></label>
      </div>
      <label className="narration-field">Transcripción o guion (opcional al crear; útil para ChatGPT)<textarea rows={3} value={newTranscript} onChange={e=>setNewTranscript(e.target.value)} placeholder="Escribe lo que cuenta la voz. ChatGPT puede convertir este texto en escenas y prompts visuales."/></label>
      <button className="btn btn-primary" disabled={busy || !projectId} onClick={() => void create()}><Plus size={15}/> Crear video narrado</button>
    </section>
    {videos.length > 0 && <section className="card narration-box"><h3>Mis videos</h3><div className="narration-list">{videos.map(v=><button className="btn" key={v.id} onClick={() => choose(v)}>{v.title} · {Math.round(v.audio_duration)} s</button>)}</div></section>}
    {draft && <section className="card narration-box">
      <div className="narration-head"><div><h3><WandSparkles size={17}/> 2. Guion visual y movimientos</h3>
        <span className="hint">{time(draft.audio_duration)} segundos · {draft.shots.length} tomas · estado: {draft.state}</span></div>
        <div className="row"><button className="btn" disabled={busy || draft.state==='rendering' || draft.state==='queued'} onClick={()=>void save()}><Save size={15}/> Guardar</button>
        <button className="btn btn-primary" disabled={busy || draft.state==='queued' || draft.state==='rendering'} onClick={()=>void render()}><Play size={15}/> Exportar MP4</button></div>
      </div>
      <audio controls src={assetUrl(draft.audio_asset_id)} style={{width:'100%',margin:'12px 0'}}/>
      <label className="narration-field">Texto o transcripción<textarea rows={5} value={draft.transcript} onChange={e=>edit({transcript:e.target.value})}/></label>
      <p className="hint">Divide el audio en tomas; escribe qué ocurre y pega el prompt de imagen de ChatGPT. La imagen puede subirse desde tu PC o asignarse por ID con MCP.</p>
      <div className="narration-shots">{draft.shots.map((s,i)=><article className="narration-shot" key={i}>
        <div className="narration-shot-head"><strong>Toma {i+1} · {time(s.start_seconds)}–{time(s.end_seconds)} s</strong><div className="row">
          <button className="btn btn-sm" disabled={draft.shots.length>=90} onClick={()=>split(i)}>Dividir</button>
          {i>0 && <button className="btn btn-sm" onClick={()=>join(i)}>Unir anterior</button>}</div></div>
        <div className="narration-fields">
          <label>Movimiento<select value={s.motion} onChange={e=>changeShot(i,{motion:e.target.value as NarratedShot['motion']})}>{motions.map(m=><option key={m} value={m}>{labels[m]}</option>)}</select></label>
          <label>Imagen para la toma<input type="file" accept="image/png,image/jpeg,image/webp" disabled={busy} onChange={e=>void image(i,e.target.files?.[0])}/></label>
        </div>
        {s.image_asset_id && <img className="narration-image" src={assetUrl(s.image_asset_id)} alt={'Imagen de la toma '+(i+1)}/>}
        <label className="narration-field">Qué se cuenta<textarea rows={2} value={s.text} onChange={e=>changeShot(i,{text:e.target.value})}/></label>
        <label className="narration-field">Prompt de imagen (ChatGPT)<textarea rows={3} value={s.image_prompt} onChange={e=>changeShot(i,{image_prompt:e.target.value})}/></label>
        <label className="narration-field">Prompt de animación / movimiento (ChatGPT)<textarea rows={3} value={s.animation_prompt || ""} onChange={e=>changeShot(i,{animation_prompt:e.target.value})}/></label>
      </article>)}</div>
      {draft.state==='rendering'||draft.state==='queued' ? <p role="status">Exportando: {draft.progress}%</p> : null}
      {draft.error && <p className="generation-error" role="alert">{draft.error}</p>}
      {draft.result_url && <div className="narration-result"><h3>Video terminado</h3><video controls src={draft.result_url}/><a className="btn btn-primary" href={draft.result_url} download><Upload size={15}/> Descargar MP4</a></div>}
    </section>}
    {error && <p className="generation-error" role="alert">{error}</p>}
    {notice && <p role="status">{notice}</p>}
  </div>
}
