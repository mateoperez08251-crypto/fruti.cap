// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterAll, afterEach, beforeAll, expect, it, vi } from 'vitest'
import { FlowWindowPreview } from '../components/FlowWindowPreview'

const show = Object.getOwnPropertyDescriptor(HTMLDialogElement.prototype, 'showModal')
const close = Object.getOwnPropertyDescriptor(HTMLDialogElement.prototype, 'close')
beforeAll(() => {
  Object.defineProperty(HTMLDialogElement.prototype, 'showModal', { configurable: true, value() { this.setAttribute('open', '') } })
  Object.defineProperty(HTMLDialogElement.prototype, 'close', { configurable: true, value() { this.removeAttribute('open') } })
})
afterAll(() => {
  if (show) Object.defineProperty(HTMLDialogElement.prototype, 'showModal', show)
  else Reflect.deleteProperty(HTMLDialogElement.prototype, 'showModal')
  if (close) Object.defineProperty(HTMLDialogElement.prototype, 'close', close)
  else Reflect.deleteProperty(HTMLDialogElement.prototype, 'close')
})
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks() })

function media() {
  const track = new EventTarget()
  const stop = vi.fn()
  const stream = { getVideoTracks: () => [track], getTracks: () => [{ stop }] }
  return { track, stop, stream }
}

it('captures only on user request, attaches the chosen stream and stops it on close', async () => {
  const source = media()
  const choose = vi.fn().mockResolvedValue(source.stream)
  vi.stubGlobal('navigator', { mediaDevices: { getDisplayMedia: choose } })
  render(<FlowWindowPreview />)
  const trigger = screen.getByRole('button', { name: 'Ver ventana de Flow' })
  fireEvent.click(trigger)
  expect(choose).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: 'Elegir ventana' }))
  await screen.findByText('Vista en vivo de la ventana elegida. La generación sigue en Chromium.')
  expect(choose.mock.calls[0][0].audio).toBe(false)
  expect((screen.getByLabelText('Vista de la ventana compartida') as HTMLVideoElement).srcObject).toBe(source.stream)
  fireEvent.click(screen.getByRole('button', { name: 'Cerrar vista' }))
  expect(source.stop).toHaveBeenCalledTimes(1)
  expect(screen.queryByRole('dialog')).toBeNull()
  expect(document.activeElement).toBe(trigger)
})

it('stops a stream returned after the user has closed the modal', async () => {
  const source = media()
  let resolve: (value: unknown) => void = () => {}
  vi.stubGlobal('navigator', { mediaDevices: { getDisplayMedia: () => new Promise(r => { resolve = r }) } })
  render(<FlowWindowPreview />)
  fireEvent.click(screen.getByText('Ver ventana de Flow'))
  fireEvent.click(screen.getByText('Elegir ventana'))
  fireEvent.click(screen.getByText('Cerrar vista'))
  await act(async () => resolve(source.stream))
  expect(source.stop).toHaveBeenCalledTimes(1)
})

it('clears the preview when sharing ends externally', async () => {
  const source = media()
  vi.stubGlobal('navigator', { mediaDevices: { getDisplayMedia: async () => source.stream } })
  render(<FlowWindowPreview />)
  fireEvent.click(screen.getByText('Ver ventana de Flow'))
  fireEvent.click(screen.getByText('Elegir ventana'))
  await screen.findByText('Cambiar ventana')
  act(() => source.track.dispatchEvent(new Event('ended')))
  await screen.findByText('La vista se detuvo. Puedes volver a elegir la ventana de Flow.')
  expect((screen.getByLabelText('Vista de la ventana compartida') as HTMLVideoElement).srcObject).toBeNull()
  expect(source.stop).toHaveBeenCalledTimes(1)
})

it('handles permission denial and lets the user select again', async () => {
  const choose = vi.fn().mockRejectedValue(new DOMException('Denied', 'NotAllowedError'))
  vi.stubGlobal('navigator', { mediaDevices: { getDisplayMedia: choose } })
  render(<FlowWindowPreview />)
  fireEvent.click(screen.getByText('Ver ventana de Flow'))
  fireEvent.click(screen.getByText('Elegir ventana'))
  await screen.findByText('No se compartió ninguna ventana. Pulsa Elegir ventana y selecciona Chromium si quieres verla.')
  await waitFor(() => expect((screen.getByText('Elegir ventana') as HTMLButtonElement).disabled).toBe(false))
  expect(choose).toHaveBeenCalledTimes(1)
})
