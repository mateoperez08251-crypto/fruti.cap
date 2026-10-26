import { useEffect, useState } from 'react'
import { api, ApiError } from '../api'

export function NarratedRenderer() {
  const [url, setUrl] = useState('')
  const [token, setToken] = useState('')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  useEffect(() => { void api.narratedRenderer().then(v => {
    setUrl(v.url); if (v.configured) setMessage('Montador configurado. Colab debe permanecer abierto para exportar.')
  }).catch(() => setMessage('No se pudo consultar la conexión del montador.')) }, [])
  const connect = async () => {
    setBusy(true); setMessage('Comprobando conexión…')
    try {
      await api.connectNarratedRenderer(url, token)
      setToken(''); setMessage('Conexión comprobada y guardada cifrada.')
    } catch (e) { setMessage(e instanceof ApiError ? e.message : 'No se pudo conectar con el montador.') }
    finally { setBusy(false) }
  }
  return <details className="card">
    <summary>Conectar Colab para unir el video</summary>
    <p className="muted">Ejecuta la libreta FRUTINOVELAS_Montaje_Colab y copia su URL y clave. No necesita GPU. Si no configuras este montador, se usará la conexión ComfyUI existente.</p>
    <label>URL del montador<input value={url} onChange={e => setUrl(e.target.value)} placeholder="https://…trycloudflare.com" disabled={busy} /></label>
    <label>Clave del montador<input type="password" autoComplete="off" value={token} onChange={e => setToken(e.target.value)} disabled={busy} /></label>
    <button className="btn" onClick={() => void connect()} disabled={busy || !url.trim() || token.length < 24}>Guardar y comprobar</button>
    <p role="status">{message}</p>
  </details>
}
