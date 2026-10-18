// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { focusManager, QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, expect, test, vi } from 'vitest'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'
import App from '../App'
import { api, ApiError, type Asset, type Chapter, type Character, type Generation, type ImageGeneration, type Project, type Scene, type VoiceReference } from '../api'
import { audioDrafts, audioErrors, voiceDrafts, voiceErrors, voiceFromCharacter } from '../audio'
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
    generations: async () => [], revisions: async () => [], characters: async () => [], imageGenerations: async () => [], chapterRenders: async () => [],
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

async function openImagePreparation() {
  const details = screen.getByText('1 · Personajes y prompt para crear la imagen').closest('details')!
  details.open = true
  fireEvent(details, new Event('toggle'))
  await screen.findByLabelText('Prompt de imagen · Qwen')
}

const characters: Character[] = ['Darío', 'Bruno', 'Cocardo'].map((name, i) => ({
  id: `character-${i}`, project_id: 'p1', name, description: '', revision: 1, archived: false,
  reference_asset: { ...asset, id: `reference-${i}` },
}))

test('scene references and the image prompt save separately from the animation prompt', async () => {
  const update = vi.fn<typeof api.updateScene>(async (_id, data) => ({ ...originals[0], revision: 2, revision_number: 2, parameters: data.parameters as Scene['parameters'] }))
  const generate = vi.fn<typeof api.generateSceneImage>()
  setup({ characters: async () => characters, updateScene: update, generateSceneImage: generate })
  await screen.findByDisplayValue('Original uno')
  await openImagePreparation()
  fireEvent.click(await screen.findByRole('checkbox', { name: /Darío/ }))
  fireEvent.click(screen.getByRole('checkbox', { name: /Bruno/ }))
  expect((screen.getByRole('checkbox', { name: /Cocardo/ }) as HTMLInputElement).disabled).toBe(true)
  edit('scene-image-prompt', 'Image literal ñ\nComposition.')
  expect(control('scene-prompt').value).toBe('Original uno')
  expect(control('btn-generate-image').disabled).toBe(true)
  click('btn-save-scene')
  await waitFor(() => expect(update).toHaveBeenCalledOnce())
  const data = update.mock.calls[0][1]
  expect(data.prompt).toBeUndefined()
  expect(data.parameters).toMatchObject({ character_ids: ['character-0', 'character-1'], image_prompt: 'Image literal ñ\nComposition.' })
  expect(generate).not.toHaveBeenCalled()
})

test('image history is read only when its preparation panel is opened', async () => {
  const images = vi.fn<typeof api.imageGenerations>(async () => [])
  const refs = vi.fn<typeof api.characters>(async () => characters)
  setup({ imageGenerations: images, characters: refs })
  await screen.findByDisplayValue('Original uno')
  expect(images).not.toHaveBeenCalled()
  expect(refs).not.toHaveBeenCalled()
  await openImagePreparation()
  await waitFor(() => expect(images).toHaveBeenCalledOnce())
  expect(refs).toHaveBeenCalledOnce()
})

test('approving an image preserves animation text typed while approval is pending', async () => {
  const pending = deferred<Scene>()
  const approve = vi.fn<typeof api.approveSceneImage>(() => pending.promise)
  const result: ImageGeneration = { id: 'image-job', scene_id: 's1', kind: 'image', state: 'completed', error: '', revision_number: 1, seed: 1, references: [], result_asset_id: 'a2', result_url: '/image.png', created_at: '2026-01-01' }
  setup({ imageGenerations: async () => [result], approveSceneImage: approve })
  await screen.findByDisplayValue('Original uno')
  await openImagePreparation()
  fireEvent.click(await screen.findByText('Aprobar y usar de inicio'))
  await waitFor(() => expect(approve).toHaveBeenCalledOnce())
  edit('scene-prompt', 'New text during approval')
  await act(async () => pending.resolve({ ...originals[0], revision: 2, revision_number: 2, start_asset: { ...asset, id: 'a2' } }))
  expect(control('scene-prompt').value).toBe('New text during approval')
  expect(document.querySelector('#drop-start img')?.getAttribute('src')).toContain('/assets/a2/')
  expect(control('btn-save-scene').disabled).toBe(false)
})

test('a project character can be named, uploaded and saved without starting a generation', async () => {
  const upload = vi.fn<typeof api.uploadAsset>(async () => asset)
  const create = vi.fn<typeof api.createCharacter>(async () => characters[0])
  const generate = vi.fn<typeof api.generateSceneImage>()
  setup({ uploadAsset: upload, createCharacter: create, generateSceneImage: generate })
  await screen.findByDisplayValue('Original uno')
  await act(async () => { await router.navigate('/proyectos/p1') })
  const details = screen.getByText('Biblioteca de personajes · referencias para las escenas').closest('details')!
  details.open = true
  fireEvent(details, new Event('toggle'))
  fireEvent.change(await screen.findByLabelText('Nombre del personaje'), { target: { value: 'Darío' } })
  fireEvent.change(document.querySelector('#character-reference input')!, { target: { files: [new File(['png'], 'Dario.png', { type: 'image/png' })] } })
  await waitFor(() => expect(upload).toHaveBeenCalledOnce())
  await waitFor(() => expect((screen.getByText('Guardar personaje') as HTMLButtonElement).disabled).toBe(false))
  fireEvent.click(screen.getByText('Guardar personaje'))
  await waitFor(() => expect(create).toHaveBeenCalledOnce())
  expect(create).toHaveBeenCalledWith('p1', { name: 'Darío', description: '', reference_asset_id: 'a1' })
  expect(generate).not.toHaveBeenCalled()
})


test('automatic image approval is optional and saving its preference never generates', async () => {
  const update = vi.fn<typeof api.updateScene>(async (_id, data) => ({ ...originals[0], revision: 2, revision_number: 2, parameters: data.parameters as Scene['parameters'] }))
  const generate = vi.fn<typeof api.generateSceneImage>()
  setup({ updateScene: update, generateSceneImage: generate })
  await screen.findByDisplayValue('Original uno')
  await openImagePreparation()
  expect((screen.getByLabelText('Revisión de imágenes') as HTMLSelectElement).value).toBe('manual')
  fireEvent.change(screen.getByLabelText('Revisión de imágenes'), { target: { value: 'automatic' } })
  click('btn-save-scene')
  await waitFor(() => expect(update).toHaveBeenCalledOnce())
  expect(update.mock.calls[0][1].parameters).toMatchObject({ image_approval: 'automatic' })
  expect(generate).not.toHaveBeenCalled()
})

test('chapter generation requires explicit automatic approval and the saved revision plan', async () => {
  const prepared = originals.map((s) => ({ ...s, parameters: { image_prompt: `Image for ${s.title}` } }))
  const generate = vi.fn<typeof api.renderChapter>(async () => ({ id: 'run1', chapter_id: 'c1', state: 'queued', error: '', scenes: [], result_url: null }))
  const reads = vi.fn<typeof api.chapterRenders>(async () => [])
  setup({ scenes: async () => prepared, renderChapter: generate, chapterRenders: reads })
  await screen.findByDisplayValue('Original uno')
  expect(reads).not.toHaveBeenCalled()
  const details = screen.getByText('Capítulo automático · imágenes, animación y montaje').closest('details')!
  details.open = true
  fireEvent(details, new Event('toggle'))
  const button = await screen.findByText('Generar capítulo completo') as HTMLButtonElement
  await waitFor(() => expect(reads).toHaveBeenCalledOnce())
  expect(button.disabled).toBe(true)
  expect(generate).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('checkbox', { name: /Aprobar automáticamente las imágenes de este proceso/ }))
  await waitFor(() => expect(button.disabled).toBe(false))
  fireEvent.click(button)
  await waitFor(() => expect(generate).toHaveBeenCalledOnce())
  expect(generate).toHaveBeenCalledWith('c1', 1, { s1: 1, s2: 1 }, expect.any(String))
})

const dialogue: Asset = { ...asset, id: 'audio-1', kind: 'audio', mime: 'audio/wav', width: null, height: null, duration_seconds: 2, original_name: 'dialogo.wav' }
const guide = (start = 0, characterId: string | null = null) => ({ asset_id: dialogue.id, asset: dialogue, character_id: characterId, character_name: characterId ? 'Cocardo' : null, voice_description: characterId ? 'Voz grave, ritmo pausado.' : '', start_seconds: start })
const audioFile = () => new File(['wave'], 'dialogo.wav', { type: 'audio/wav' })
const voicedCharacters: Character[] = characters.map((c, i) => ({ ...c, voice_asset: { ...dialogue, id: `sample-${i}` }, voice_description: `Voz de ${c.name}.` }))
const voiceReference = (c: Character): VoiceReference => ({ character_id: c.id, character_name: c.name,
  voice_description: c.voice_description ?? '', asset_id: c.voice_asset!.id, asset: c.voice_asset! })

async function openAudioPreparation() {
  const details = screen.getByText(/^3 · Audio y voces/).closest('details')!
  details.open = true
  fireEvent(details, new Event('toggle'))
  await screen.findByLabelText('Diálogo de la escena')
}

test('scene dialogue uses the audio endpoint, allows an offscreen character and saves only explicit clips', async () => {
  const prepared = { ...originals[0], parameters: { character_ids: ['character-0', 'character-1'], custom_setting: 'conservar' } }
  const upload = vi.fn<typeof api.uploadAudio>(async () => dialogue)
  const update = vi.fn<typeof api.updateScene>(async (_id, data) => ({ ...prepared, revision: 2, revision_number: 2, parameters: { ...data.parameters as Scene['parameters'], audio_guides: [guide(1, 'character-2')] } }))
  const generate = vi.fn<typeof api.generateScene>()
  const cast = characters.map((c) => ({ ...c, voice_asset: { ...dialogue, id: `sample-${c.id}` }, voice_description: 'Voz grave, ritmo pausado.' }))
  setup({ scenes: async () => [prepared, originals[1]], characters: async () => cast, uploadAudio: upload, updateScene: update, generateScene: generate })
  await screen.findByDisplayValue('Original uno')
  await openAudioPreparation()
  expect(document.querySelectorAll('audio')).toHaveLength(0)
  expect(control('btn-save-scene').disabled).toBe(true)
  fireEvent.change(control('scene-audio-upload-file'), { target: { files: [audioFile()] } })
  await screen.findByLabelText('Personaje del audio 1')
  await screen.findByRole('option', { name: 'Cocardo' })
  edit('scene-audio-character-0', 'character-2')
  edit('scene-audio-start-0', '1')
  await waitFor(() => expect(control('btn-save-scene').disabled).toBe(false))
  click('btn-save-scene')
  await waitFor(() => expect(update).toHaveBeenCalledOnce())
  expect(upload).toHaveBeenCalledWith(expect.any(File), expect.any(AbortSignal))
  expect(update.mock.calls[0][1]).toMatchObject({ expected_revision: 1, parameters: {
    character_ids: ['character-0', 'character-1'], custom_setting: 'conservar',
    audio_guides: [{ asset_id: dialogue.id, character_id: 'character-2', start_seconds: 1 }],
  } })
  expect((update.mock.calls[0][1].parameters as Scene['parameters']).audio_guides?.[0].asset).toBeUndefined()
  expect(update.mock.calls[0][1].prompt).toBeUndefined()
  expect(document.querySelector('audio')?.preload).toBe('none')
  expect(generate).not.toHaveBeenCalled()
})

test('an audio save retains timing edits made while pending and preserves the base revision on external changes', async () => {
  const initial = { ...originals[0], parameters: { audio_guides: [guide()] } }
  const pending = deferred<Scene>()
  const update = vi.fn<typeof api.updateScene>(() => pending.promise)
  setup({ scenes: async () => [initial, originals[1]], updateScene: update })
  await screen.findByDisplayValue('Original uno')
  await openAudioPreparation()
  edit('scene-audio-start-0', '0,5')
  click('tab-guion')
  expect(control('scene-audio-start-0').value).toBe('0,5')
  act(() => qc.setQueryData(['scenes', 'c1'], [{ ...initial, revision: 2, revision_number: 2, prompt: 'Cambio externo' }, originals[1]]))
  click('btn-save-scene')
  await waitFor(() => expect(update).toHaveBeenCalledOnce())
  expect(update.mock.calls[0][1].expected_revision).toBe(1)
  edit('scene-audio-start-0', '1')
  await act(async () => pending.resolve({ ...initial, revision: 3, revision_number: 3, parameters: { audio_guides: [guide(0.5)] } }))
  expect(control('scene-audio-start-0').value).toBe('1')
  await waitFor(() => expect(control('btn-save-scene').disabled).toBe(false))
  click('btn-save-scene')
  await waitFor(() => expect(update).toHaveBeenCalledTimes(2))
  expect(update.mock.calls[1][1]).toMatchObject({ expected_revision: 3, parameters: { audio_guides: [{ asset_id: dialogue.id, character_id: null, start_seconds: 1 }] } })
})

test('overlapping dialogue and clips outside the scene produce actionable errors and block saving', async () => {
  const initial = { ...originals[0], parameters: { audio_guides: [guide(), guide(2)] } }
  setup({ scenes: async () => [initial, originals[1]] })
  await screen.findByDisplayValue('Original uno')
  await openAudioPreparation()
  edit('scene-audio-start-1', '1,5')
  expect(screen.getByText(/Los audios 1 y 2 se superponen/)).toBeTruthy()
  expect(control('btn-save-scene').disabled).toBe(true)
  edit('scene-audio-start-1', '4')
  expect(screen.getByText(/termina en 6 s y la escena dura 5 s/)).toBeTruthy()
  expect(control('btn-save-scene').disabled).toBe(true)
  edit('scene-duration', '6')
  expect(control('btn-save-scene').disabled).toBe(false)
  edit('scene-audio-start-0', '')
  expect(screen.getByText(/introduce un inicio de 0 segundos o más/)).toBeTruthy()
  expect(control('btn-save-scene').disabled).toBe(true)
})

test('audio timing accepts the same half-frame boundary as the server', () => {
  const halfFrame = [{ ...guide(1 / 48), asset: { ...dialogue, duration_seconds: 4 } }]
  expect(audioErrors(audioDrafts(halfFrame), 4)).toEqual([])
  expect(audioErrors(audioDrafts([{ ...halfFrame[0], start_seconds: 3 / 48 }]), 4)).toHaveLength(1)
})

test('a saved dialogue displays its frozen speaker name and voice after library changes', async () => {
  const initial = { ...originals[0], parameters: { audio_guides: [guide(0, 'character-2')] } }
  const renamed = characters.map((c) => c.id === 'character-2' ? { ...c, name: 'Cocardo actualizado', voice_description: 'Otra voz' } : c)
  setup({ scenes: async () => [initial, originals[1]], characters: async () => renamed })
  await screen.findByDisplayValue('Original uno')
  await openAudioPreparation()
  await screen.findByRole('option', { name: 'Cocardo · guardado' })
  const selected = document.getElementById('scene-audio-character-0') as HTMLSelectElement
  expect(selected.selectedOptions[0].textContent).toBe('Cocardo · guardado')
  expect(screen.getByText('Voz: Voz grave, ritmo pausado.')).toBeTruthy()
  edit('scene-audio-start-0', '1')
  expect(selected.value).toBe('character-2')
  expect(selected.selectedOptions[0].textContent).toBe('Cocardo · guardado')
})

test('a failed audio upload preserves the prompt and lets the same file be retried', async () => {
  const upload = vi.fn<typeof api.uploadAudio>()
    .mockRejectedValueOnce(new ApiError(400, 'El audio supera los 15 segundos. Recórtalo y vuelve a subirlo.'))
    .mockResolvedValue(dialogue)
  setup({ uploadAudio: upload })
  await screen.findByDisplayValue('Original uno')
  edit('scene-prompt', 'Diálogo literal: ¡Sí, mamá!')
  await openAudioPreparation()
  const file = audioFile()
  fireEvent.change(control('scene-audio-upload-file'), { target: { files: [file] } })
  await screen.findByText('El audio supera los 15 segundos. Recórtalo y vuelve a subirlo.')
  expect(control('scene-prompt').value).toBe('Diálogo literal: ¡Sí, mamá!')
  expect(document.querySelectorAll('.scene-audio-item')).toHaveLength(0)
  fireEvent.change(control('scene-audio-upload-file'), { target: { files: [file] } })
  await screen.findByLabelText('Personaje del audio 1')
  expect(upload).toHaveBeenCalledTimes(2)
  expect(screen.queryByText('El audio supera los 15 segundos. Recórtalo y vuelve a subirlo.')).toBeNull()
  expect(control('scene-prompt').value).toBe('Diálogo literal: ¡Sí, mamá!')
})

test('pending audio protects navigation and a late upload never attaches to a different scene', async () => {
  const pending = deferred<Asset>()
  const upload = vi.fn<typeof api.uploadAudio>(() => pending.promise)
  setup({ uploadAudio: upload })
  await screen.findByDisplayValue('Original uno')
  await openAudioPreparation()
  fireEvent.change(control('scene-audio-upload-file'), { target: { files: [audioFile()] } })
  await waitFor(() => expect(upload).toHaveBeenCalledOnce())
  click('tab-guion')
  expect(control('scene-prompt').value).toBe('Original uno')
  expect(control('btn-save-scene').disabled).toBe(true)
  vi.mocked(window.confirm).mockReturnValue(true)
  await act(async () => { await router.navigate('/capitulos/c1?escena=s2') })
  await screen.findByDisplayValue('Original dos')
  expect(upload.mock.calls[0][1]?.aborted).toBe(true)
  await act(async () => pending.resolve(dialogue))
  expect(document.querySelectorAll('.scene-audio-item')).toHaveLength(0)
})

test('removing a saved audio clip sends an explicit empty list and keeps other scene parameters', async () => {
  const initial = { ...originals[0], parameters: { audio_guides: [guide()], image_prompt: 'Imagen literal', custom_setting: 'conservar' } }
  const update = vi.fn<typeof api.updateScene>(async (_id, data) => ({ ...initial, revision: 2, revision_number: 2, parameters: data.parameters as Scene['parameters'] }))
  setup({ scenes: async () => [initial, originals[1]], updateScene: update })
  await screen.findByDisplayValue('Original uno')
  await openAudioPreparation()
  fireEvent.click(screen.getByLabelText('Quitar audio 1'))
  click('btn-save-scene')
  await waitFor(() => expect(update).toHaveBeenCalledOnce())
  expect(update.mock.calls[0][1].parameters).toMatchObject({ audio_guides: [], image_prompt: 'Imagen literal', custom_setting: 'conservar' })
})

test('editing a character preserves its saved voice until explicitly removed', async () => {
  const voiced = { ...characters[0], voice_description: 'Voz cálida, acento peruano.', voice_asset: dialogue }
  const update = vi.fn<typeof api.updateCharacter>(async () => voiced)
  setup({ characters: async () => [voiced], updateCharacter: update })
  await screen.findByDisplayValue('Original uno')
  await act(async () => { await router.navigate('/proyectos/p1') })
  const details = screen.getByText('Biblioteca de personajes · referencias para las escenas').closest('details')!
  details.open = true
  fireEvent(details, new Event('toggle'))
  fireEvent.click(await screen.findByRole('button', { name: /Darío/ }))
  expect(control('character-voice-description').value).toBe('Voz cálida, acento peruano.')
  expect(document.querySelector('#character-voice audio')?.getAttribute('src')).toContain('/assets/audio-1/content')
  edit('character-description', 'Rasgos visuales actualizados')
  fireEvent.click(screen.getByText('Guardar personaje'))
  await waitFor(() => expect(update).toHaveBeenCalledOnce())
  expect(update.mock.calls[0][1]).not.toHaveProperty('voice_asset_id')
  expect(update.mock.calls[0][1]).not.toHaveProperty('voice_description')
  await waitFor(() => expect(control('character-name').value).toBe(''))
  fireEvent.click(screen.getByRole('button', { name: /Darío/ }))
  fireEvent.click(screen.getByLabelText('Quitar muestra de voz del personaje'))
  fireEvent.click(screen.getByText('Guardar personaje'))
  await waitFor(() => expect(update).toHaveBeenCalledTimes(2))
  expect(update.mock.calls[1][1]).toMatchObject({ expected_revision: 1, voice_asset_id: null })
  expect(update.mock.calls[1][1]).not.toHaveProperty('voice_description')
})

test('a character sample and voice description are saved together after the upload completes', async () => {
  const pending = deferred<Asset>()
  const upload = vi.fn<typeof api.uploadAudio>(() => pending.promise)
  const update = vi.fn<typeof api.updateCharacter>(async () => ({ ...characters[0], voice_asset: dialogue, voice_description: 'Voz propia y pausada.' }))
  setup({ characters: async () => characters, uploadAudio: upload, updateCharacter: update })
  await screen.findByDisplayValue('Original uno')
  await act(async () => { await router.navigate('/proyectos/p1') })
  const details = screen.getByText('Biblioteca de personajes · referencias para las escenas').closest('details')!
  details.open = true
  fireEvent(details, new Event('toggle'))
  fireEvent.click(await screen.findByRole('button', { name: /Darío/ }))
  edit('character-voice-description', 'Voz propia y pausada.')
  fireEvent.change(control('character-voice-file'), { target: { files: [audioFile()] } })
  await waitFor(() => expect(upload).toHaveBeenCalledOnce())
  expect((screen.getByText('Guardar personaje') as HTMLButtonElement).disabled).toBe(true)
  await act(async () => pending.resolve(dialogue))
  await waitFor(() => expect((screen.getByText('Guardar personaje') as HTMLButtonElement).disabled).toBe(false))
  expect(document.querySelector('#character-voice audio')?.getAttribute('preload')).toBe('none')
  fireEvent.click(screen.getByText('Guardar personaje'))
  await waitFor(() => expect(update).toHaveBeenCalledOnce())
  expect(update.mock.calls[0][1]).toMatchObject({ expected_revision: 1, voice_description: 'Voz propia y pausada.', voice_asset_id: dialogue.id })
})

test('audio upload uses a multipart request to the dedicated asset route', async () => {
  const fetcher = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify(dialogue), { status: 200 }))
  const file = audioFile()
  const controller = new AbortController()
  expect(await api.uploadAudio(file, controller.signal)).toEqual(dialogue)
  expect(fetcher).toHaveBeenCalledWith('/api/v1/assets/audio', { method: 'POST', body: expect.any(FormData), signal: controller.signal })
  const form = fetcher.mock.calls[0][1]?.body as FormData
  expect(form.get('file')).toEqual(file)
})

test('library voices generate new dialogue without uploading clips and include offscreen characters', async () => {
  const cast = [...voicedCharacters.map((c, i) => ({ ...c, voice_asset: { ...c.voice_asset!, duration_seconds: i === 2 ? 8 : 2 } })),
    { ...voicedCharacters[0], id: 'character-3', name: 'Narradora' }]
  const prepared: Scene = { ...originals[0], end_asset: { ...asset, id: 'end-image' }, mode: 'FL2VA',
    prompt: 'Cocardo speaks: <d>¡Sí, mamá! ¿Vienes?</d>',
    parameters: { character_ids: ['character-0', 'character-1'], custom_setting: 'conservar' } }
  const upload = vi.fn<typeof api.uploadAudio>()
  const generate = vi.fn<typeof api.generateScene>()
  const update = vi.fn<typeof api.updateScene>(async (_id, data) => ({ ...prepared, revision: 2, revision_number: 2,
    parameters: { ...data.parameters as Scene['parameters'], voice_references: ((data.parameters as Scene['parameters']).voice_character_ids ?? []).map((id) => voiceReference(cast.find((c) => c.id === id)!)) } }))
  setup({ scenes: async () => [prepared, originals[1]], characters: async () => cast, updateScene: update, uploadAudio: upload, generateScene: generate })
  await screen.findByDisplayValue(prepared.prompt)
  await openAudioPreparation()
  fireEvent.click(await screen.findByRole('checkbox', { name: 'Usar voz de Cocardo' }))
  expect(control('btn-save-scene').disabled).toBe(false)
  fireEvent.click(screen.getByRole('checkbox', { name: 'Usar voz de Darío' }))
  fireEvent.click(screen.getByRole('checkbox', { name: 'Usar voz de Bruno' }))
  expect((screen.getByRole('checkbox', { name: 'Usar voz de Narradora' }) as HTMLInputElement).disabled).toBe(true)
  expect(control('scene-audio-upload-file').disabled).toBe(true)
  expect(control('btn-generate-scene').disabled).toBe(true)
  click('btn-save-scene')
  await waitFor(() => expect(update).toHaveBeenCalledOnce())
  expect(update.mock.calls[0][1]).toMatchObject({ expected_revision: 1, parameters: {
    voice_character_ids: ['character-2', 'character-0', 'character-1'], character_ids: ['character-0', 'character-1'], custom_setting: 'conservar',
  } })
  expect(update.mock.calls[0][1].parameters).not.toHaveProperty('audio_guides')
  expect(update.mock.calls[0][1].parameters).not.toHaveProperty('voice_references')
  expect(update.mock.calls[0][1]).not.toHaveProperty('end_asset_id')
  expect(update.mock.calls[0][1]).not.toHaveProperty('prompt')
  expect(control('scene-prompt').value).toBe(prepared.prompt)
  expect(upload).not.toHaveBeenCalled()
  expect(generate).not.toHaveBeenCalled()
})

test('switching prepared dialogue to library voices requires explicitly removing the saved clips', async () => {
  const initial = { ...originals[0], parameters: { audio_guides: [guide()], custom_setting: 'conservar' } }
  const update = vi.fn<typeof api.updateScene>(async (_id, data) => ({ ...initial, revision: 2, revision_number: 2,
    parameters: { ...data.parameters as Scene['parameters'], voice_references: [voiceReference(voicedCharacters[0])] } }))
  setup({ scenes: async () => [initial, originals[1]], characters: async () => voicedCharacters, updateScene: update })
  await screen.findByDisplayValue('Original uno')
  await openAudioPreparation()
  const choice = await screen.findByRole('checkbox', { name: 'Usar voz de Darío' }) as HTMLInputElement
  expect(choice.disabled).toBe(true)
  fireEvent.click(choice)
  expect(document.querySelectorAll('.scene-audio-item')).toHaveLength(1)
  expect(control('btn-save-scene').disabled).toBe(true)
  fireEvent.click(screen.getByRole('button', { name: 'Quitar audios preparados para elegir voces' }))
  expect(document.querySelectorAll('.scene-audio-item')).toHaveLength(0)
  expect(choice.disabled).toBe(false)
  fireEvent.click(choice)
  click('btn-save-scene')
  await waitFor(() => expect(update).toHaveBeenCalledOnce())
  expect(update.mock.calls[0][1].parameters).toMatchObject({ audio_guides: [], voice_character_ids: ['character-0'], custom_setting: 'conservar' })
})

test('switching saved voices to a prepared clip sends an explicit empty voice selection', async () => {
  const initial = { ...originals[0], parameters: { voice_character_ids: ['character-0'], voice_references: [voiceReference(voicedCharacters[0])] } }
  const upload = vi.fn<typeof api.uploadAudio>(async () => dialogue)
  const update = vi.fn<typeof api.updateScene>(async (_id, data) => ({ ...initial, revision: 2, revision_number: 2,
    parameters: { ...data.parameters as Scene['parameters'], voice_references: [], audio_guides: [guide()] } }))
  setup({ scenes: async () => [initial, originals[1]], characters: async () => voicedCharacters, uploadAudio: upload, updateScene: update })
  await screen.findByDisplayValue('Original uno')
  await openAudioPreparation()
  expect(control('scene-audio-upload-file').disabled).toBe(true)
  fireEvent.change(control('scene-audio-upload-file'), { target: { files: [audioFile()] } })
  expect(upload).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: 'Quitar voces para usar audio preparado' }))
  expect(control('scene-audio-upload-file').disabled).toBe(false)
  fireEvent.change(control('scene-audio-upload-file'), { target: { files: [audioFile()] } })
  await screen.findByLabelText('Personaje del audio 1')
  await waitFor(() => expect(control('btn-save-scene').disabled).toBe(false))
  click('btn-save-scene')
  await waitFor(() => expect(update).toHaveBeenCalledOnce())
  expect(update.mock.calls[0][1].parameters).toMatchObject({ voice_character_ids: [], audio_guides: [{ asset_id: dialogue.id, character_id: null, start_seconds: 0 }] })
})

test('a voice selection preserves its draft, revision and changes made during a pending save', async () => {
  const initial = { ...originals[0], parameters: { voice_character_ids: ['character-0'], voice_references: [voiceReference(voicedCharacters[0])] } }
  const pending = deferred<Scene>()
  const update = vi.fn<typeof api.updateScene>(() => pending.promise)
  setup({ scenes: async () => [initial, originals[1]], characters: async () => voicedCharacters, updateScene: update })
  await screen.findByDisplayValue('Original uno')
  await openAudioPreparation()
  fireEvent.click(await screen.findByRole('checkbox', { name: 'Usar voz de Bruno' }))
  click('tab-guion')
  expect(control('scene-prompt').value).toBe('Original uno')
  act(() => qc.setQueryData(['scenes', 'c1'], [{ ...initial, revision: 2, revision_number: 2, prompt: 'Cambio externo' }, originals[1]]))
  click('btn-save-scene')
  await waitFor(() => expect(update).toHaveBeenCalledOnce())
  expect(update.mock.calls[0][1]).toMatchObject({ expected_revision: 1, parameters: { voice_character_ids: ['character-0', 'character-1'] } })
  fireEvent.click(screen.getByRole('checkbox', { name: 'Usar voz de Darío' }))
  fireEvent.click(screen.getByRole('checkbox', { name: 'Usar voz de Cocardo' }))
  await act(async () => pending.resolve({ ...initial, revision: 3, revision_number: 3, parameters: {
    voice_character_ids: ['character-0', 'character-1'], voice_references: voicedCharacters.slice(0, 2).map(voiceReference),
  } }))
  expect((screen.getByRole('checkbox', { name: 'Usar voz de Darío' }) as HTMLInputElement).checked).toBe(false)
  expect((screen.getByRole('checkbox', { name: 'Usar voz de Bruno' }) as HTMLInputElement).checked).toBe(true)
  expect((screen.getByRole('checkbox', { name: 'Usar voz de Cocardo' }) as HTMLInputElement).checked).toBe(true)
  await waitFor(() => expect(control('btn-save-scene').disabled).toBe(false))
  click('btn-save-scene')
  await waitFor(() => expect(update).toHaveBeenCalledTimes(2))
  expect(update.mock.calls[1][1]).toMatchObject({ expected_revision: 3, parameters: { voice_character_ids: ['character-1', 'character-2'] } })
})

test('saved voices keep their sample and name after library changes and temporary deselection', async () => {
  const saved = { ...voicedCharacters[0], voice_asset: { ...dialogue, id: 'original-sample', duration_seconds: 8 } }
  const renamed = { ...saved, name: 'Darío actualizado', voice_description: 'Otra voz.', voice_asset: { ...dialogue, id: 'new-sample', duration_seconds: 15 } }
  const initial = { ...originals[0], parameters: { voice_character_ids: ['character-0'], voice_references: [voiceReference(saved)] } }
  const update = vi.fn<typeof api.updateScene>(async (_id, data) => ({ ...initial, revision: 2, revision_number: 2,
    parameters: { ...data.parameters as Scene['parameters'], voice_references: [voiceReference(saved), voiceReference(voicedCharacters[1])] } }))
  setup({ scenes: async () => [initial, originals[1]], characters: async () => [renamed, voicedCharacters[1]], updateScene: update })
  await screen.findByDisplayValue('Original uno')
  await openAudioPreparation()
  await screen.findByRole('checkbox', { name: 'Usar voz de Bruno' })
  expect(screen.getByText('Darío · guardado')).toBeTruthy()
  expect(screen.getByLabelText('Escuchar muestra de Darío').getAttribute('src')).toContain('/assets/original-sample/content')
  fireEvent.click(screen.getByRole('checkbox', { name: 'Usar voz de Darío' }))
  fireEvent.click(screen.getByRole('checkbox', { name: 'Usar voz de Darío' }))
  expect(control('btn-save-scene').disabled).toBe(true)
  fireEvent.click(screen.getByRole('checkbox', { name: 'Usar voz de Bruno' }))
  expect(screen.queryByText(/Las muestras seleccionadas suman/)).toBeNull()
  expect(control('btn-save-scene').disabled).toBe(false)
  expect(screen.getByLabelText('Escuchar muestra de Darío').getAttribute('src')).toContain('/assets/original-sample/content')
  click('btn-save-scene')
  await waitFor(() => expect(update).toHaveBeenCalledOnce())
  expect((update.mock.calls[0][1].parameters as Scene['parameters']).voice_character_ids).toEqual(['character-0', 'character-1'])
})

test('missing and short voice samples are unavailable and combined samples above 15 seconds block saving', async () => {
  const cast = [
    { ...voicedCharacters[0], voice_asset: { ...dialogue, id: 'long-a', duration_seconds: 8 } },
    { ...voicedCharacters[1], voice_asset: { ...dialogue, id: 'long-b', duration_seconds: 8 } },
    { ...voicedCharacters[2], voice_asset: { ...dialogue, id: 'short-sample', duration_seconds: 1.5 } },
    { ...characters[0], id: 'no-sample', name: 'Narradora' },
  ]
  setup({ characters: async () => cast })
  await screen.findByDisplayValue('Original uno')
  await openAudioPreparation()
  expect((await screen.findByRole('checkbox', { name: 'Usar voz de Cocardo' }) as HTMLInputElement).disabled).toBe(true)
  expect((screen.getByRole('checkbox', { name: 'Usar voz de Narradora' }) as HTMLInputElement).disabled).toBe(true)
  expect(screen.getByText('La muestra de voz debe durar entre 2 y 15 segundos.')).toBeTruthy()
  fireEvent.click(screen.getByRole('checkbox', { name: 'Usar voz de Darío' }))
  expect(control('btn-save-scene').disabled).toBe(false)
  fireEvent.click(screen.getByRole('checkbox', { name: 'Usar voz de Bruno' }))
  expect(screen.getByText(/Las muestras seleccionadas suman 16 s/)).toBeTruthy()
  expect(control('btn-save-scene').disabled).toBe(true)
  fireEvent.click(screen.getByRole('checkbox', { name: 'Usar voz de Bruno' }))
  expect(control('btn-save-scene').disabled).toBe(false)
})

test('voice duration boundaries and missing snapshots agree with the native model contract', () => {
  const durations = (seconds: number[]) => seconds.map((duration, i) => voiceFromCharacter({ ...voicedCharacters[i % 3],
    voice_asset: { ...dialogue, id: `sample-${i}`, duration_seconds: duration } }))
  expect(voiceErrors(durations([2, 5, 8]))).toEqual([])
  expect(voiceErrors(durations([15]))).toEqual([])
  expect(voiceErrors(durations([1.99]))).toHaveLength(1)
  expect(voiceErrors(durations([15.01]))).toHaveLength(1)
  expect(voiceErrors(durations([8, 8]))).toHaveLength(1)
  expect(voiceErrors(voiceDrafts(['missing'], []))).toHaveLength(1)
  expect(voiceErrors(durations([2, 2, 2, 2]))).toHaveLength(1)
})

test('uploading a voice sample shorter than two seconds preserves the saved sample', async () => {
  const voiced = voicedCharacters[0]
  const upload = vi.fn<typeof api.uploadAudio>(async () => ({ ...dialogue, id: 'too-short', duration_seconds: 1 }))
  const update = vi.fn<typeof api.updateCharacter>(async () => voiced)
  setup({ characters: async () => [voiced], uploadAudio: upload, updateCharacter: update })
  await screen.findByDisplayValue('Original uno')
  await act(async () => { await router.navigate('/proyectos/p1') })
  const details = screen.getByText('Biblioteca de personajes · referencias para las escenas').closest('details')!
  details.open = true
  fireEvent(details, new Event('toggle'))
  fireEvent.click(await screen.findByRole('button', { name: /Darío/ }))
  fireEvent.change(control('character-voice-file'), { target: { files: [audioFile()] } })
  await screen.findByText('La muestra de voz debe durar entre 2 y 15 segundos. Sube una muestra más larga.')
  expect(document.querySelector('#character-voice audio')?.getAttribute('src')).toContain('/assets/sample-0/content')
  edit('character-description', 'Conservar voz anterior')
  await waitFor(() => expect((screen.getByText('Guardar personaje') as HTMLButtonElement).disabled).toBe(false))
  fireEvent.click(screen.getByText('Guardar personaje'))
  await waitFor(() => expect(update).toHaveBeenCalledOnce())
  expect(update.mock.calls[0][1]).not.toHaveProperty('voice_asset_id')
})
