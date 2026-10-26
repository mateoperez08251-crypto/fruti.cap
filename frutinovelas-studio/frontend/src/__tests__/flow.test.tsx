// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { api, type Chapter, type Project, type Scene } from '../api'
import { flowApi, type FlowAgentStatus, type FlowJob } from '../flow-api'
import { FlowPage } from '../pages/FlowPage'
import { ToastProvider } from '../components/Toast'

const scene: Scene = { id: 'scene', chapter_id: 'chapter', order_index: 1, title: 'Fruta al balcón', external_key: null,
  description: '', revision: 1, revision_number: 1, prompt: 'Mira la lluvia.', duration_seconds: 5,
  parameters: { image_prompt: 'Fruta en un balcón.' }, start_asset: null, end_asset: null, mode: null, status: 'sin_imagen', updated_at: '2026-01-01' }
const project: Project = { id: 'project', name: 'Novela', language: 'es', aspect_ratio: '9:16', archived: false, chapter_count: 1, created_at: '', updated_at: '' }
const chapter: Chapter = { id: 'chapter', project_id: 'project', title: 'Lluvia', order_index: 1, script_md: '', continuity_md: '', revision: 1,
  archived: false, scene_count: 1, ready_count: 0, created_at: '', updated_at: '' }
const job: FlowJob = { id: 'job', batch_id: 'batch', project_id: 'project', chapter_id: 'chapter', scene_id: 'scene', title: scene.title,
  kind: 'image', state: 'unknown', approval: 'pending', error: 'El proveedor no confirmó el envío.', scene_revision: 1,
  cancel_requested: false, remote_stopped: false, dependency_id: null, result_asset_id: null, result_url: null,
  created_at: '2026-01-01', requested_duration: null, result_metadata: {} }

beforeEach(() => {
  vi.spyOn(api, 'projects').mockResolvedValue([project])
  vi.spyOn(api, 'chapters').mockResolvedValue([chapter])
  vi.spyOn(api, 'scenes').mockResolvedValue([scene])
  vi.spyOn(flowApi, 'status').mockResolvedValue({ connected: true, mode: 'assisted', agent: {
    available: false, window_open: false, flow_available: null, authentication: 'unknown', modes: {}, detail: 'Sin perfil verificado.' } })
  vi.spyOn(flowApi, 'jobs').mockResolvedValue([])
})
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.useRealTimers() })

function show() {
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <MemoryRouter initialEntries={['/flow-automation?project_id=project&chapter_id=chapter']}><ToastProvider><FlowPage /></ToastProvider></MemoryRouter>
  </QueryClientProvider>)
}

it('starts with manual approval and sends only selected scene revisions', async () => {
  const generate = vi.spyOn(flowApi, 'generate').mockResolvedValue([job])
  show()
  fireEvent.click(await screen.findByText('1. Fruta al balcón'))
  fireEvent.change(screen.getByLabelText('Generar con Flow'), { target: { value: 'image_video' } })
  fireEvent.click(screen.getByText('Encolar 1 escenas'))
  await waitFor(() => expect(generate).toHaveBeenCalledTimes(1))
  expect(generate.mock.calls[0][0]).toMatchObject({ project_id: 'project', chapter_id: 'chapter',
    scene_revisions: { scene: 1 }, generation_mode: 'image_video', automatic_approval: false })
})

it('reuses request_id when a response is lost', async () => {
  const generate = vi.spyOn(flowApi, 'generate').mockRejectedValue(new Error('Desconectado'))
  show()
  fireEvent.click(await screen.findByText('1. Fruta al balcón'))
  fireEvent.click(screen.getByText('Encolar 1 escenas'))
  await screen.findByText('Desconectado')
  fireEvent.click(screen.getByText('Encolar 1 escenas'))
  await waitFor(() => expect(generate).toHaveBeenCalledTimes(2))
  expect(generate.mock.calls[0][0].request_id).toBe(generate.mock.calls[1][0].request_id)
})

it('shows uncertain work without offering an unsafe retry or claiming completion', async () => {
  vi.mocked(flowApi.jobs).mockResolvedValue([job])
  show()
  await screen.findByText(job.error)
  expect(screen.queryByText('Reintentar')).toBeNull()
  expect(screen.queryByText('Completado · archivo verificado')).toBeNull()
  expect(screen.getByRole('button', { name: 'Cancelar localmente' })).toBeTruthy()
})

it('never approves a completed image until the user clicks approval', async () => {
  vi.mocked(flowApi.jobs).mockResolvedValue([{ ...job, state: 'completed', error: '' }])
  const review = vi.spyOn(flowApi, 'review').mockResolvedValue({ ...job, approval: 'approved' })
  show()
  const approve = await screen.findByText('Aprobar y usar de inicio')
  expect(review).not.toHaveBeenCalled()
  await waitFor(() => expect((approve as HTMLButtonElement).disabled).toBe(false))
  fireEvent.click(approve)
  await waitFor(() => expect(review).toHaveBeenCalledWith('job', 1, 'approved'))
})

const foundAgent: FlowAgentStatus = { reachable: true, profile_configured: true, available: true,
  window_open: true, window_title: 'Userflex — Flow — Capítulo de prueba', flow_available: true,
  authentication: 'verified_by_control', modes: {}, detail: 'Controles verificados.' }

it('shows progress, prevents double clicks, and explains an unreachable agent without claiming Userflex is closed', async () => {
  let complete!: (agent: FlowAgentStatus) => void
  const detect = vi.spyOn(flowApi, 'detect').mockImplementation(() => new Promise(resolve => { complete = resolve }))
  show()
  fireEvent.click(screen.getByRole('button', { name: 'Detectar Userflex / Flow' }))
  const pending = await screen.findByRole('button', { name: 'Detectando…' })
  expect((pending as HTMLButtonElement).disabled).toBe(true)
  fireEvent.click(pending)
  expect(detect).toHaveBeenCalledTimes(1)
  expect(within(screen.getByRole('status', { name: 'Resultado de detección' })).getByText('Buscando Userflex y Flow…')).toBeTruthy()
  complete({ ...foundAgent, reachable: false, profile_configured: null, available: false, window_open: null,
    window_title: null, flow_available: null, authentication: 'unknown', detail: 'No se pudo consultar el agente.' })
  await screen.findByText('Agente Windows sin conexión')
  const result = screen.getByRole('status', { name: 'Resultado de detección' })
  expect(within(result).getByText(/Ejecuta iniciar_flow_agente.cmd/).textContent).toContain('No se pudo comprobar si Userflex está abierto.')
  expect(within(result).getByText(/Última detección:/)).toBeTruthy()
  expect((screen.getByRole('button', { name: 'Enfocar ventana' }) as HTMLButtonElement).disabled).toBe(true)
})

it.each([
  [{ profile_configured: false, window_open: null, available: false, flow_available: null }, 'Agente conectado; falta configurar Userflex'],
  [{ window_open: false, available: false, flow_available: null }, 'No se pudo identificar la ventana de Userflex'],
  [{ flow_available: false, available: false }, 'Ventana encontrada; Flow no detectado'],
  [{ flow_available: null, available: false }, 'Ventana encontrada; Flow sin verificar'],
  [{ authentication: 'unknown', available: false }, 'Ventana y Flow detectados; sesión sin verificar'],
  [{ available: false }, 'Ventana y Flow detectados; controlador pendiente'],
  [{}, 'Userflex y Flow detectados'],
] as [Partial<FlowAgentStatus>, string][])('reports the actual detection outcome %j', async (overrides, title) => {
  vi.spyOn(flowApi, 'detect').mockResolvedValue({ ...foundAgent, ...overrides })
  show()
  fireEvent.click(screen.getByRole('button', { name: 'Detectar Userflex / Flow' }))
  expect(await screen.findByText(title)).toBeTruthy()
  expect(screen.getByText(/Última detección:/)).toBeTruthy()
})

it('reports every click even when the result is unchanged, replaces stale success on error, and lets the user retry', async () => {
  const detect = vi.spyOn(flowApi, 'detect').mockResolvedValue(foundAgent)
  const focus = vi.spyOn(flowApi, 'focus').mockResolvedValue({ focused: true })
  show()
  const button = screen.getByRole('button', { name: 'Detectar Userflex / Flow' })
  fireEvent.click(button)
  await screen.findByText('Userflex y Flow detectados')
  expect(screen.getByText(foundAgent.window_title!)).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: 'Enfocar ventana' }))
  await waitFor(() => expect(focus).toHaveBeenCalledTimes(1))
  fireEvent.click(button)
  await waitFor(() => expect(detect).toHaveBeenCalledTimes(2))
  await waitFor(() => expect((button as HTMLButtonElement).disabled).toBe(false))
  detect.mockRejectedValueOnce(new Error('No hay conexión con Studio.'))
  fireEvent.click(button)
  const failure = await screen.findByRole('alert', { name: 'Resultado de detección' })
  expect(within(failure).getByText('No hay conexión con Studio.')).toBeTruthy()
  expect(screen.queryByText(foundAgent.window_title!)).toBeNull()
  expect((screen.getByRole('button', { name: 'Enfocar ventana' }) as HTMLButtonElement).disabled).toBe(true)
  fireEvent.click(button)
  await screen.findByText('Userflex y Flow detectados')
  expect(detect).toHaveBeenCalledTimes(4)
})

it('allows manual detection to recover after the initial status request fails', async () => {
  vi.mocked(flowApi.status).mockRejectedValue(new Error('Studio no responde.'))
  vi.spyOn(flowApi, 'detect').mockResolvedValue(foundAgent)
  show()
  await screen.findByText('Studio no responde.')
  fireEvent.click(screen.getByRole('button', { name: 'Detectar Userflex / Flow' }))
  await screen.findByText('Userflex y Flow detectados')
  expect(screen.queryByRole('alert', { name: 'Resultado de detección' })).toBeNull()
})

it('bounds a stalled detection request and reports a useful timeout', async () => {
  vi.useFakeTimers()
  vi.spyOn(globalThis, 'fetch').mockImplementation((_url, init) => new Promise((_resolve, reject) => {
    init?.signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))
  }))
  const result = expect(flowApi.detect()).rejects.toThrow('La detección tardó demasiado.')
  await vi.advanceTimersByTimeAsync(20000)
  await result
})

it.each([null, { available: false }])('reports malformed detection responses instead of rendering an empty result: %j', async result => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify(result), {
    status: 200, headers: { 'Content-Type': 'application/json' },
  }))
  await expect(flowApi.detect()).rejects.toThrow('La detección devolvió una respuesta incompleta.')
})
