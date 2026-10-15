import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CheckCircle2, Loader2, PlugZap } from 'lucide-react'
import { useState } from 'react'
import { api, ApiError } from '../api'
import { useToast } from '../components/Toast'

export function ConnectionPage() {
  const qc = useQueryClient()
  const toast = useToast()
  const connection = useQuery({ queryKey: ['comfy-connection'], queryFn: api.comfyConnection })
  const status = useQuery({ queryKey: ['status'], queryFn: api.status, refetchInterval: 10_000, retry: 0 })
  const [url, setUrl] = useState<string | null>(null)
  const [token, setToken] = useState('')
  const save = useMutation({
    mutationFn: () => api.saveComfyConnection((url ?? connection.data?.url ?? '').trim(), token.trim()),
    onSuccess: (data) => {
      qc.setQueryData(['comfy-connection'], data)
      qc.invalidateQueries({ queryKey: ['status'] })
      setToken('')
      toast.ok('RunPod conectado. El flujo H3 está comprobado.')
    },
    onError: (error: ApiError) => toast.error(error.message),
  })
  return (
    <div className="page">
      <header className="page-head"><div><div className="eyebrow">MOTOR DE GENERACIÓN</div><h1>Conexión ComfyUI</h1></div></header>
      <section className="card connection-card">
        <h2><PlugZap size={22} /> Conecta tu GPU remota</h2>
        <p className="muted">Copia la URL que muestra <code>fruti status</code> y el token de <code>fruti token --mostrar</code> en RunPod.</p>
        <form onSubmit={(event) => { event.preventDefault(); if (!save.isPending) save.mutate() }}>
          <div className="field"><label htmlFor="comfy-url">URL del gateway</label>
            <input id="comfy-url" className="input" type="url" disabled={save.isPending} required value={url ?? connection.data?.url ?? ''}
              onChange={(e) => setUrl(e.target.value)} placeholder="https://…-8189.proxy.runpod.net" autoComplete="off" /></div>
          <div className="field"><label htmlFor="comfy-token">Token del gateway</label>
            <input id="comfy-token" className="input" type="password" disabled={save.isPending} autoComplete="new-password" value={token}
              onChange={(e) => setToken(e.target.value)} placeholder={connection.data?.has_token ? 'Guardado. Déjalo vacío para conservarlo con la misma URL.' : 'Pega el token completo'} /></div>
          <p className="subtle">El token se guarda cifrado en este PC. Nunca se incluye en el historial de escenas ni en las respuestas de la API.</p>
          <button id="btn-check-comfy" className="btn btn-primary" disabled={save.isPending || connection.isLoading}>
            {save.isPending ? <Loader2 size={16} className="spin" /> : <PlugZap size={16} />}
            {save.isPending ? 'Comprobando RunPod…' : 'Guardar y comprobar'}
          </button>
        </form>
        {connection.data?.configured && <div className="notice connection-ready"><CheckCircle2 size={18} /><span>
          Conexión guardada · ComfyUI {connection.data.identity.comfyui_version ?? ''}<br />
          H3 inicio/final · 576×1024 · 20 pasos. Puedes generar desde el editor de cada escena.
        </span></div>}
        {connection.data?.configured && status.data && !status.isError && !status.data.comfyui.reachable && <p className="notice warn" role="status">
          La conexión está guardada, pero ComfyUI no responde ahora. Activa ComfyUI y comprueba la URL y el gateway; el estado se actualiza automáticamente.
        </p>}
        {connection.isError && <p role="alert">No se pudo leer la configuración. Comprueba que la API esté abierta.</p>}
      </section>
    </div>
  )
}
