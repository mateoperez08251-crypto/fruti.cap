import { ImagePlus, Loader2, Maximize2, RefreshCw, Trash2 } from 'lucide-react'
import { useRef, useState, type DragEvent } from 'react'
import { api, ApiError, assetUrl, thumbUrl, type Asset } from '../api'
import { useToast } from './Toast'

const ACCEPT = 'image/png,image/jpeg,image/webp'

type Props = {
  id: string
  label: string
  optional?: boolean
  asset: Asset | null
  disabled?: boolean
  disabledHint?: string
  onChange: (asset: Asset | null) => void
  onZoom: (asset: Asset) => void
}

export function ImageDrop({ id, label, optional, asset, disabled, disabledHint, onChange, onZoom }: Props) {
  const toast = useToast()
  const input = useRef<HTMLInputElement>(null)
  const [over, setOver] = useState(false)
  const [busy, setBusy] = useState(false)

  const upload = async (file: File | undefined) => {
    if (!file || disabled) return
    setBusy(true)
    try {
      const a = await api.uploadAsset(file)
      onChange(a)
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : 'No se pudo subir la imagen.')
    } finally {
      setBusy(false)
      if (input.current) input.current.value = ''
    }
  }

  const onDrop = (e: DragEvent) => {
    e.preventDefault()
    setOver(false)
    upload(e.dataTransfer.files?.[0])
  }

  return (
    <div
      id={id}
      className={`drop ${over ? 'over' : ''} ${asset ? 'filled' : ''}`}
      role="button"
      tabIndex={disabled ? -1 : 0}
      aria-label={`${label}: ${asset ? 'cambiar imagen' : 'subir imagen'}`}
      aria-disabled={disabled}
      style={disabled ? { opacity: 0.5, cursor: 'not-allowed' } : undefined}
      onClick={() => !asset && !disabled && input.current?.click()}
      onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && !disabled && input.current?.click()}
      onDragOver={(e) => {
        e.preventDefault()
        if (!disabled) setOver(true)
      }}
      onDragLeave={() => setOver(false)}
      onDrop={onDrop}
    >
      <span className={`chip drop-label ${asset ? 'chip-ready' : optional ? '' : 'chip-warn'}`}>
        {label}
        {optional ? ' · opcional' : ''}
      </span>

      {asset ? (
        <>
          <img src={thumbUrl(asset.id, 720)} alt={`${label} (${asset.original_name})`} draggable={false} />
          <span className="drop-info">
            {asset.width}×{asset.height}
          </span>
          <div className="drop-actions">
            <button
              type="button"
              className="btn btn-sm btn-icon"
              title="Ver ampliada"
              aria-label="Ver ampliada"
              onClick={(e) => {
                e.stopPropagation()
                onZoom(asset)
              }}
            >
              <Maximize2 size={14} />
            </button>
            <button
              type="button"
              className="btn btn-sm btn-icon"
              title="Reemplazar"
              aria-label="Reemplazar imagen"
              onClick={(e) => {
                e.stopPropagation()
                input.current?.click()
              }}
            >
              <RefreshCw size={14} />
            </button>
            <button
              type="button"
              className="btn btn-sm btn-icon btn-danger"
              title="Quitar"
              aria-label="Quitar imagen"
              onClick={(e) => {
                e.stopPropagation()
                onChange(null)
              }}
            >
              <Trash2 size={14} />
            </button>
          </div>
        </>
      ) : (
        <div className="drop-empty">
          <ImagePlus size={28} />
          <strong>{disabled ? 'No disponible' : 'Arrastra una imagen'}</strong>
          <span>{disabled ? disabledHint : 'o haz clic · PNG, JPEG o WebP'}</span>
        </div>
      )}

      {busy && (
        <div className="drop-busy">
          <Loader2 className="spin" size={28} />
        </div>
      )}
      <input ref={input} type="file" accept={ACCEPT} hidden onChange={(e) => upload(e.target.files?.[0])} />
    </div>
  )
}

export function Lightbox({ asset, onClose }: { asset: Asset; onClose: () => void }) {
  return (
    <div className="lightbox" onClick={onClose} role="dialog" aria-label="Imagen ampliada">
      <img src={assetUrl(asset.id)} alt={asset.original_name} />
    </div>
  )
}
