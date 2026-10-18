import { AudioLines, Loader2, Trash2, Upload } from 'lucide-react'
import { useEffect, useRef, useState, type DragEvent } from 'react'
import { api, ApiError, assetUrl, type Asset } from '../api'
import { audioSeconds } from '../audio'

const ACCEPT = '.wav,.mp3,.m4a,.aac,.flac,.ogg,.opus,.webm,audio/*'

export function AudioPreview({ asset, label }: { asset: Asset; label: string }) {
  return <div className="audio-preview">
    <div className="audio-filename"><strong>{asset.original_name}</strong>
      {asset.duration_seconds != null && <span className="chip">{audioSeconds(asset.duration_seconds)} s</span>}
    </div>
    <audio key={asset.id} controls preload="none" src={assetUrl(asset.id)} aria-label={label} />
  </div>
}

type Props = {
  id: string
  label: string
  asset: Asset | null
  disabled?: boolean
  minDurationSeconds?: number
  onChange: (asset: Asset | null) => void
  onBusyChange: (busy: boolean) => void
}

export function AudioUpload({ id, label, asset, disabled, minDurationSeconds = 0, onChange, onBusyChange }: Props) {
  const input = useRef<HTMLInputElement>(null)
  const uploading = useRef<AbortController | null>(null)
  const [busy, setBusy] = useState(false)
  const [over, setOver] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (disabled) uploading.current?.abort()
    return () => uploading.current?.abort()
  }, [disabled])

  useEffect(() => {
    onBusyChange(busy)
    return () => onBusyChange(false)
  }, [busy, onBusyChange])

  const upload = async (file: File | undefined) => {
    if (!file || disabled || uploading.current) return
    const controller = new AbortController()
    uploading.current = controller
    setError('')
    setBusy(true)
    try {
      const audio = await api.uploadAudio(file, controller.signal)
      if (!controller.signal.aborted) {
        if (minDurationSeconds && (audio.duration_seconds == null || audio.duration_seconds < minDurationSeconds)) {
          setError(`La muestra de voz debe durar entre ${minDurationSeconds} y 15 segundos. Sube una muestra más larga.`)
        } else onChange(audio)
      }
    } catch (e) {
      if (!controller.signal.aborted) setError(e instanceof ApiError ? e.message : 'No se pudo subir el audio. Vuelve a intentarlo.')
    } finally {
      if (uploading.current === controller) uploading.current = null
      setBusy(false)
      if (input.current) input.current.value = ''
    }
  }

  const drop = (e: DragEvent) => {
    e.preventDefault()
    setOver(false)
    void upload(e.dataTransfer.files?.[0])
  }

  return <div id={id} className={`audio-upload ${over ? 'over' : ''}`} aria-busy={busy}
    onDragOver={(e) => { e.preventDefault(); if (!disabled && !busy) setOver(true) }}
    onDragLeave={() => setOver(false)} onDrop={drop}>
    <div className="audio-upload-heading"><span className="label"><AudioLines size={16} /> {label}</span>
      <div className="row" style={{ gap: 8 }}>
        <button type="button" className="btn btn-sm" disabled={disabled || busy} onClick={() => input.current?.click()} aria-label={`${asset ? 'Cambiar' : 'Subir'} ${label.toLowerCase()}`}>
          {busy ? <Loader2 size={14} className="spin" /> : <Upload size={14} />}{asset ? 'Cambiar audio' : 'Subir audio'}
        </button>
        {asset && <button type="button" className="btn btn-ghost btn-sm btn-danger" disabled={disabled || busy}
          aria-label={`Quitar ${label.toLowerCase()}`} onClick={() => { setError(''); onChange(null) }}><Trash2 size={14} /> Quitar</button>}
      </div>
    </div>
    {asset && <AudioPreview asset={asset} label={`Escuchar ${label.toLowerCase()}`} />}
    {!asset && <p className="hint">También puedes arrastrar un archivo aquí. WAV, MP3, M4A, AAC, FLAC, OGG, Opus o WebM · {minDurationSeconds ? `${minDurationSeconds}–15 s` : 'hasta 15 s'}.</p>}
    {busy && <p className="hint" role="status">Subiendo y comprobando el audio…</p>}
    {error && <p className="generation-error" role="alert">{error}</p>}
    <input id={`${id}-file`} ref={input} type="file" accept={ACCEPT} hidden aria-label={label} disabled={disabled || busy}
      onChange={(e) => { void upload(e.target.files?.[0]) }} />
  </div>
}
