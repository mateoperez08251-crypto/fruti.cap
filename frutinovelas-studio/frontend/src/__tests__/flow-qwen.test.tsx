// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, expect, it, vi } from 'vitest'
import { FlowResult } from '../pages/FlowPage'
import { ToastProvider } from '../components/Toast'
import { flowApi, type FlowJob } from '../flow-api'

const job: FlowJob = { id: 'job', batch_id: 'batch', project_id: 'project', chapter_id: 'chapter', scene_id: 'scene',
  title: 'Toma 1', kind: 'image', state: 'awaiting_import', approval: 'pending', error: '', scene_revision: 1,
  cancel_requested: false, remote_stopped: false, dependency_id: null, result_asset_id: null, result_url: null,
  created_at: '2026-10-23T00:00:00', requested_duration: null, result_metadata: {} }

afterEach(() => { cleanup(); vi.restoreAllMocks() })

it('uses Chromium instructions without invoking the old desktop endpoint', () => {
  const status = vi.spyOn(flowApi, 'qwenStatus')
  show({ ...job, execution_mode: 'browser', state: 'queued' })
  expect(screen.getByText('Qwen en Chromium')).toBeTruthy()
  expect(screen.getByText(/iniciar_qwen_chromium.cmd/)).toBeTruthy()
  expect(screen.queryByRole('button', { name: 'Ejecutar esta toma con Qwen' })).toBeNull()
  expect(status).not.toHaveBeenCalled()
})
function show(value = job) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={client}><ToastProvider><FlowResult job={value} refresh={vi.fn()}/></ToastProvider></QueryClientProvider>)
}

it('requires specific desktop authorization and an unstarted generation, then reuses its intent after a lost response', async () => {
  vi.spyOn(flowApi, 'qwenStatus').mockResolvedValue({ configured: true, model: 'qwen', detail: 'ready' })
  const execute = vi.spyOn(flowApi, 'executeQwen').mockRejectedValue(new Error('Respuesta perdida'))
  show()
  const button = screen.getByRole('button', { name: 'Ejecutar esta toma con Qwen' }) as HTMLButtonElement
  expect(button.disabled).toBe(true)
  fireEvent.click(screen.getByRole('checkbox', { name: 'Permito que mi Qwen vea el escritorio y controle UserFLEX para esta toma.' }))
  expect(button.disabled).toBe(true)
  fireEvent.click(screen.getByRole('checkbox', { name: 'Esta toma todavía no se está generando en Flow.' }))
  await waitFor(() => expect(button.disabled).toBe(false))
  fireEvent.click(button)
  await screen.findByText('Respuesta perdida')
  await waitFor(() => expect(button.disabled).toBe(false))
  fireEvent.click(button)
  await waitFor(() => expect(execute).toHaveBeenCalledTimes(2))
  expect(execute.mock.calls[0]).toEqual(['job', expect.any(String), true, true])
  expect(execute.mock.calls[1][1]).toBe(execute.mock.calls[0][1])
})

it('shows the actual executor step without offering a second start', () => {
  vi.spyOn(flowApi, 'qwenStatus').mockResolvedValue({ configured: true, model: 'qwen', detail: 'ready' })
  show({ ...job, state: 'running', result_metadata: { executor: 'qwen', qwen_step: 5, qwen_message: 'Esperando el resultado de Flow.' } })
  expect(screen.getByText('Qwen · Paso 5 · Esperando el resultado de Flow.')).toBeTruthy()
  expect(screen.queryByText('Ejecutar esta toma con Qwen')).toBeNull()
})

it('does not queue a desktop task when the local worker is not running', async () => {
  vi.spyOn(flowApi, 'qwenStatus').mockResolvedValue({ configured: true, worker_running: false, model: 'qwen', detail: 'Reinicia Studio para activar el ejecutor.' })
  show()
  fireEvent.click(screen.getByRole('checkbox', { name: 'Permito que mi Qwen vea el escritorio y controle UserFLEX para esta toma.' }))
  fireEvent.click(screen.getByRole('checkbox', { name: 'Esta toma todavía no se está generando en Flow.' }))
  await screen.findByText('Reinicia Studio para activar el ejecutor.')
  expect((screen.getByText('Ejecutar esta toma con Qwen') as HTMLButtonElement).disabled).toBe(true)
})
