import { useCallback, useEffect, useId, useRef, useState, type RefObject } from 'react'
import { createPortal } from 'react-dom'
import { Monitor, X } from 'lucide-react'

function PreviewDialog({ onClose, trigger }: { onClose: () => void; trigger: RefObject<HTMLButtonElement | null> }) {
  const titleId = useId()
  const descriptionId = useId()
  const dialog = useRef<HTMLDialogElement>(null)
  const video = useRef<HTMLVideoElement>(null)
  const stream = useRef<MediaStream | null>(null)
  const mounted = useRef(false)
  const pending = useRef(false)
  const [busy, setBusy] = useState(false)
  const [live, setLive] = useState(false)
  const [message, setMessage] = useState('Selecciona la ventana donde tienes abierto Flow para verla aquí.')

  const stop = useCallback(() => {
    const current = stream.current
    stream.current = null
    current?.getTracks().forEach(track => track.stop())
    if (video.current) video.current.srcObject = null
  }, [])

  useEffect(() => {
    mounted.current = true
    const element = dialog.current
    const returnTo = trigger.current
    element?.showModal()
    return () => {
      mounted.current = false
      stop()
      element?.close()
      returnTo?.focus()
    }
  }, [stop, trigger])

  const chooseWindow = async () => {
    if (pending.current) return
    if (!navigator.mediaDevices?.getDisplayMedia) {
      setMessage('Este navegador no permite mostrar ventanas. Abre Studio en Chrome o Edge desde esta misma PC.')
      return
    }
    pending.current = true
    setBusy(true)
    try {
      const selected = await navigator.mediaDevices.getDisplayMedia({
        video: { displaySurface: 'window', frameRate: { ideal: 10, max: 15 } }, audio: false,
      })
      if (!mounted.current) {
        selected.getTracks().forEach(track => track.stop())
        return
      }
      const track = selected.getVideoTracks()[0]
      if (!track) {
        selected.getTracks().forEach(item => item.stop())
        throw new Error('No video track')
      }
      stop()
      stream.current = selected
      if (video.current) video.current.srcObject = selected
      track.addEventListener('ended', () => {
        if (stream.current !== selected) return
        stop()
        if (mounted.current) {
          setLive(false)
          setMessage('La vista se detuvo. Puedes volver a elegir la ventana de Flow.')
        }
      }, { once: true })
      setLive(true)
      setMessage('Vista en vivo de la ventana elegida. La generación sigue en UserFLEX.')
    } catch (error) {
      if (mounted.current) setMessage(error instanceof DOMException && error.name === 'NotAllowedError'
        ? 'No se compartió ninguna ventana. Pulsa Elegir ventana y selecciona UserFLEX si quieres verla.'
        : 'No se pudo mostrar la ventana. Comprueba que UserFLEX esté abierto e inténtalo otra vez.')
    } finally {
      pending.current = false
      if (mounted.current) setBusy(false)
    }
  }

  return createPortal(<dialog ref={dialog} className="card dialog flow-window-dialog" aria-labelledby={titleId} aria-describedby={descriptionId}
    onCancel={event => { event.preventDefault(); onClose() }}>
    <div className="row flow-between">
      <h2 id={titleId}>Ventana de Flow</h2>
      <button type="button" className="btn btn-ghost" aria-label="Cerrar vista de Flow" onClick={onClose} autoFocus><X size={18} aria-hidden="true"/></button>
    </div>
    <p id={descriptionId} className="hint">Elige la ventana de UserFLEX en el selector del navegador. Esta vista permanece en tu PC, sin grabarse ni enviarse a Qwen. Para manejar Flow, usa UserFLEX o tu controlador.</p>
    <video ref={video} className="flow-window-video" aria-label="Vista de la ventana compartida" autoPlay muted playsInline controls hidden={!live}/>
    {!live && <div className="flow-window-empty"><Monitor size={36} aria-hidden="true"/><span>Aquí verás la generación de imágenes y clips.</span></div>}
    <p role="status">{message}</p>
    <div className="dialog-actions">
      <button type="button" className="btn btn-primary" disabled={busy} onClick={() => void chooseWindow()}>{busy ? 'Esperando selección…' : live ? 'Cambiar ventana' : 'Elegir ventana'}</button>
      <button type="button" className="btn" onClick={onClose}>Cerrar vista</button>
    </div>
    <p className="hint">Cerrar esta vista no cancela trabajos ni detiene la generación en Flow.</p>
  </dialog>, document.body)
}

export function FlowWindowPreview() {
  const [open, setOpen] = useState(false)
  const trigger = useRef<HTMLButtonElement>(null)
  const close = useCallback(() => setOpen(false), [])
  return <>
    <button type="button" className="btn" ref={trigger} onClick={() => setOpen(true)}><Monitor size={16} aria-hidden="true"/> Ver ventana de Flow</button>
    {open && <PreviewDialog onClose={close} trigger={trigger}/>}
  </>
}
