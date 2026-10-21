// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { api, type Chapter, type Project, type Scene } from '../api'
import { flowApi, type FlowJob } from '../flow-api'
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
afterEach(() => { cleanup(); vi.restoreAllMocks() })

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
