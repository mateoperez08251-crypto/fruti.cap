// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { focusManager, QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, expect, test, vi } from 'vitest'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'
import App from '../App'
import { api, type Asset, type Chapter, type Generation, type Project, type Scene } from '../api'
import { ToastProvider } from '../components/Toast'

const asset: Asset = { id: 'a1', kind: 'image', sha256: 'abc', size_bytes: 1, mime: 'image/png', width: 576, height: 1024, original_name: 'start.png', created_at: '2026-01-01' }
const project: Project = { id: 'p1', name: 'Test', language: 'es', aspect_ratio: '9:16', archived: false, created_at: '2026-01-01', updated_at: '2026-01-01', chapter_count: 1 }
const chapter: Chapter = { id: 'c1', project_id: 'p1', title: 'Capítulo', order_index: 0, script_md: 'Guion guardado', continuity_md: 'Continuidad guardada', revision: 1, archived: false, created_at: '2026-01-01', updated_at: '2026-01-01', scene_count: 2, ready_count: 2 }
const originals: Scene[] = ['Primera', 'Segunda'].map((title, i) => ({ id: `s${i + 1}`, chapter_id: 'c1', order_index: i, external_key: null, title, description: '', revision: 1, revision_number: 1, prompt: i ? 'Original dos' : 'Original uno', duration_seconds: 5, parameters: {}, start_asset: asset, end_asset: null, mode: 'I2VA', status: 'lista', updated_at: '2026-01-01' }))
const originalApi = { ...api }
let qc: QueryClient
let router: ReturnType<typeof createMemoryRouter>

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => { resolve = done })
  return { promise, resolve }
}

function setup(overrides: Partial<typeof api> = {}) {
  let scenes = structuredClone(originals)
  const mocks: Partial<typeof api> = {
    projects: async () => [project], project: async () => project, chapter: async () => chapter,
    chapters: async () => [chapter], scenes: async () => scenes,
    status: async () => ({ app_version: 'test', comfyui: { url: 'http://comfy', reachable: true, version: '1', detail: null }, storage: { data_dir: '/tmp', free_bytes: 999999999, low_space: false }, ffmpeg: true }),
    comfyConnection: async () => ({ url: 'http://comfy', configured: true, has_token: false, identity: {} }),
    generations: async () => [], revisions: async () => [],
    reorderScenes: async (_id, ids) => {
      scenes = ids.map((id, i) => ({ ...scenes.find((s) => s.id === id)!, order_index: i }))
      return scenes
    },
    ...overrides,
  }
  Object.assign(api, mocks)
  vi.spyOn(window, 'confirm').mockReturnValue(false)
  qc = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity }, mutations: { retry: false } } })
  router = createMemoryRouter([{ path: '*', element: <ToastProvider><App /></ToastProvider> }], { initialEntries: ['/capitulos/c1'] })
  render(<QueryClientProvider client={qc}><RouterProvider router={router} /></QueryClientProvider>)
}

const control = (id: string) => document.getElementById(id) as HTMLInputElement
const click = (id: string) => fireEvent.click(control(id))
const edit = (id: string, value: string) => fireEvent.change(control(id), { target: { value } })
const settle = () => act(async () => { await Promise.resolve() })

afterEach(() => {
  cleanup()
  qc?.clear()
  router?.dispose()
  Object.assign(api, originalApi)
  vi.restoreAllMocks()
  vi.useRealTimers()
  focusManager.setFocused(undefined)
})

test('reordering retains the implicitly selected scene and its literal draft', async () => {
  setup()
  await screen.findByDisplayValue('Original uno')
  edit('scene-prompt', 'Borrador literal á <d>sí</d>')
  fireEvent.click(screen.getAllByLabelText('Bajar escena')[0])
  await waitFor(() => expect(document.getElementById('scene-card-2')?.getAttribute('aria-current')).toBe('true'))
  expect(control('scene-title').value).toBe('Primera')
  expect(control('scene-prompt').value).toBe('Borrador literal á <d>sí</d>')
  expect(control('btn-duplicate-scene').disabled).toBe(true)
})

test('scene tabs and sidebar navigation protect an unsaved prompt', async () => {
  setup()
  await screen.findByDisplayValue('Original uno')
  edit('scene-prompt', 'Sin guardar')
  click('tab-guion')
  expect(control('scene-prompt').value).toBe('Sin guardar')
  click('nav-home')
  await settle()
  expect(router.state.location.pathname).toBe('/capitulos/c1')
  expect(control('scene-prompt').value).toBe('Sin guardar')
  vi.mocked(window.confirm).mockReturnValue(true)
  click('tab-guion')
  await screen.findByDisplayValue('Guion guardado')
})

test('document drafts protect both tab switches and sidebar navigation', async () => {
  setup()
  await screen.findByDisplayValue('Original uno')
  click('tab-guion')
  edit('doc-script_md', 'Guion nuevo exacto')
  click('tab-continuidad')
  expect(control('doc-script_md').value).toBe('Guion nuevo exacto')
  click('nav-home')
  await settle()
  expect(router.state.location.pathname).toBe('/capitulos/c1')
  vi.mocked(window.confirm).mockReturnValue(true)
  click('tab-continuidad')
  await screen.findByDisplayValue('Continuidad guardada')
})

test('a save response preserves text entered while the request was pending', async () => {
  const pending = deferred<Scene>()
  const update = vi.fn<typeof api.updateScene>(() => pending.promise)
  setup({ updateScene: update })
  await screen.findByDisplayValue('Original uno')
  edit('scene-prompt', 'Enviado literal')
  click('btn-save-scene')
  await waitFor(() => expect(update).toHaveBeenCalledOnce())
  edit('scene-prompt', 'Texto nuevo durante guardado')
  await act(async () => pending.resolve({ ...originals[0], prompt: 'Enviado literal', revision: 2, revision_number: 2 }))
  expect(control('scene-prompt').value).toBe('Texto nuevo durante guardado')
  await waitFor(() => expect(control('btn-save-scene').disabled).toBe(false))
  expect(update.mock.calls[0][1]).toEqual({ expected_revision: 1, prompt: 'Enviado literal' })
  click('btn-save-scene')
  await waitFor(() => expect(update).toHaveBeenCalledTimes(2))
  expect(update.mock.calls[1][1]).toEqual({ expected_revision: 2, prompt: 'Texto nuevo durante guardado' })
})

test('fixed seeds exceeding integer precision cannot be saved', async () => {
  setup()
  await screen.findByDisplayValue('Original uno')
  edit('scene-seed-mode', 'fixed')
  edit('scene-seed', '9007199254740992')
  expect(control('btn-save-scene').disabled).toBe(true)
  edit('scene-seed', '9007199254740991')
  await waitFor(() => expect(control('btn-save-scene').disabled).toBe(false))
})

test('a late final-image upload cannot restore a reference after initial-image removal', async () => {
  const pending = deferred<Asset>()
  const upload = vi.fn<typeof api.uploadAsset>(() => pending.promise)
  setup({ uploadAsset: upload })
  await screen.findByDisplayValue('Original uno')
  fireEvent.change(document.querySelector('#drop-end input')!, { target: { files: [new File(['png'], 'end.png', { type: 'image/png' })] } })
  await waitFor(() => expect(upload).toHaveBeenCalledOnce())
  expect(control('btn-save-scene').disabled).toBe(true)
  fireEvent.click(screen.getAllByLabelText('Quitar imagen')[0])
  await settle()
  expect(upload.mock.calls[0][1]?.aborted).toBe(true)
  await act(async () => pending.resolve({ ...asset, id: 'a2' }))
  expect(document.querySelector('#drop-end img')).toBeNull()
  expect(document.querySelector('#drop-start img')).toBeNull()
})

test('a failed progress query cannot enable an accidental duplicate generation', async () => {
  setup({ generations: async () => { throw new Error('offline') } })
  await screen.findByText('No se pudo consultar el progreso. Pulsa actualizar cuando vuelva la conexión.')
  expect(control('btn-generate-scene').disabled).toBe(true)
})

test('navigation to a different scene query protects the active draft', async () => {
  setup()
  await screen.findByDisplayValue('Original uno')
  edit('scene-prompt', 'Conservar al cambiar query')
  await act(async () => { await router.navigate('/capitulos/c1?escena=s2') })
  expect(control('scene-prompt').value).toBe('Conservar al cambiar query')
  expect(router.state.location.search).toBe('')
  vi.mocked(window.confirm).mockReturnValue(true)
  await act(async () => { await router.navigate('/capitulos/c1?escena=s2') })
  await screen.findByDisplayValue('Original dos')
})

const job = (id: string, state: Generation['state']): Generation => ({
  id, scene_id: 's1', state, error: '', revision_number: 1, duration_seconds: 5,
  frames: 124, effective_seconds: 124 / 24, seed: 1, created_at: '2026-01-01',
  result_url: state === 'completed' ? `/api/v1/generations/${id}/content` : null,
})
const advance = (ms: number) => act(async () => { await vi.advanceTimersByTimeAsync(ms) })

test('idle polling stays slow, pauses while hidden and does not start generations', async () => {
  vi.useFakeTimers()
  focusManager.setFocused(true)
  const generations = vi.fn<typeof api.generations>(async () => [])
  const generate = vi.fn<typeof api.generateScene>()
  setup({ generations, generateScene: generate })
  await advance(50)
  expect(generations).toHaveBeenCalledOnce()
  await advance(20_000)
  expect(generations).toHaveBeenCalledOnce()
  await advance(10_000)
  expect(generations).toHaveBeenCalledTimes(2)
  act(() => focusManager.setFocused(false))
  await advance(60_000)
  expect(generations).toHaveBeenCalledTimes(2)
  act(() => focusManager.setFocused(true))
  await advance(30_000)
  expect(generations.mock.calls.length).toBeGreaterThan(2)
  expect(generate).not.toHaveBeenCalled()
})

test('progress polls active jobs promptly and slows after completion', async () => {
  vi.useFakeTimers()
  focusManager.setFocused(true)
  const generations = vi.fn<typeof api.generations>()
    .mockResolvedValueOnce([job('v1', 'running')])
    .mockResolvedValue([job('v1', 'completed')])
  setup({ generations })
  await advance(50)
  expect(generations).toHaveBeenCalledOnce()
  await advance(2500)
  expect(generations).toHaveBeenCalledTimes(2)
  expect(screen.getByText('Video disponible')).toBeTruthy()
  await advance(10_000)
  expect(generations).toHaveBeenCalledTimes(2)
  await advance(20_000)
  expect(generations).toHaveBeenCalledTimes(3)
})

test('uncertain submissions are checked less frequently without resending', async () => {
  vi.useFakeTimers()
  focusManager.setFocused(true)
  const generations = vi.fn<typeof api.generations>(async () => [job('v1', 'unknown')])
  const generate = vi.fn<typeof api.generateScene>()
  setup({ generations, generateScene: generate })
  await advance(50)
  await advance(10_000)
  expect(generations).toHaveBeenCalledOnce()
  await advance(5000)
  expect(generations).toHaveBeenCalledTimes(2)
  expect(generate).not.toHaveBeenCalled()
})

test('leaving the scene cancels its pending progress read', async () => {
  const pending = deferred<Generation[]>()
  const generations = vi.fn<typeof api.generations>(() => pending.promise)
  setup({ generations })
  await screen.findByDisplayValue('Original uno')
  await waitFor(() => expect(generations).toHaveBeenCalledOnce())
  const signal = generations.mock.calls[0][1]
  expect(signal?.aborted).toBe(false)
  click('tab-guion')
  await screen.findByDisplayValue('Guion guardado')
  expect(signal?.aborted).toBe(true)
  await act(async () => pending.resolve([]))
})

test('old video players mount on demand and never preload their media', async () => {
  setup({ generations: async () => Array.from({ length: 12 }, (_, i) => job(`v${i}`, 'completed')) })
  await screen.findAllByText('Video disponible')
  expect(document.querySelectorAll('video')).toHaveLength(3)
  fireEvent.click(screen.getByText('Ver versiones anteriores (9)'))
  expect(document.querySelectorAll('video')).toHaveLength(8)
  fireEvent.click(screen.getByText('Ver versiones anteriores (4)'))
  const videos = document.querySelectorAll('video')
  expect(videos).toHaveLength(12)
  for (const video of videos) expect(video.preload).toBe('none')
})

test('opening connection settings does not add a second system polling timer', async () => {
  vi.useFakeTimers()
  const status = vi.fn<typeof api.status>(async () => ({ app_version: 'test',
    comfyui: { url: 'http://comfy', reachable: true, version: '1', detail: null },
    storage: { data_dir: '/tmp', free_bytes: 999999999, low_space: false }, ffmpeg: true }))
  setup({ status })
  await advance(50)
  expect(status).toHaveBeenCalledOnce()
  await advance(3000)
  await act(async () => { await router.navigate('/conexion') })
  await advance(20_000)
  expect(status).toHaveBeenCalledOnce()
  await advance(10_000)
  expect(status).toHaveBeenCalledTimes(2)
})
