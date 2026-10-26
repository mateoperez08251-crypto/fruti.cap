// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, expect, it, vi } from 'vitest'
import { NarratedPage } from '../pages/NarratedPage'
import { api, type NarratedVideo } from '../api'
import { flowApi, type FlowJob } from '../flow-api'

afterEach(() => { cleanup(); vi.restoreAllMocks() })

it('opens the saved video from its URL and shows desktop consent beside the narrated takes', async () => {
  const video: NarratedVideo = { id: 'video', project_id: 'project', title: 'Historia guardada', audio_asset_id: 'audio', audio_duration: 12,
    transcript: 'Guion guardado', aspect_ratio: '9:16', revision: 2, state: 'draft', progress: 0, error: '', result_url: null,
    shots: [{ start_seconds: 0, end_seconds: 12, text: 'Una toma', image_prompt: 'Imagen literal', animation_prompt: '', image_asset_id: null,
      motion: 'still', media_mode: 'static', flow_scene_id: 'scene', flow_image_job_id: 'job' }] }
  const job: FlowJob = { id: 'job', batch_id: 'batch', project_id: 'project', chapter_id: 'chapter', scene_id: 'scene', title: 'Toma 1',
    kind: 'image', state: 'awaiting_import', approval: 'pending', error: '', scene_revision: 1, cancel_requested: false,
    remote_stopped: false, dependency_id: null, result_asset_id: null, result_url: null, created_at: '2026-10-23T00:00:00', requested_duration: null, result_metadata: {} }
  vi.spyOn(api, 'projects').mockResolvedValue([{ id: 'project', name: 'Historia', language: 'es', aspect_ratio: '9:16', archived: false,
    created_at: '', updated_at: '', chapter_count: 1 }])
  const get = vi.spyOn(api, 'narratedVideo').mockResolvedValue(video)
  vi.spyOn(api, 'narratedVideos').mockResolvedValue([video])
  vi.spyOn(api, 'narratedRenderer').mockResolvedValue({ configured: false, url: '' })
  vi.spyOn(flowApi, 'job').mockResolvedValue(job)
  vi.spyOn(flowApi, 'qwenStatus').mockResolvedValue({ configured: true, worker_running: true, model: 'qwen', detail: 'ready' })
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={client}><MemoryRouter initialEntries={['/videos-narrados?project_id=project&video_id=video']}><NarratedPage/></MemoryRouter></QueryClientProvider>)
  await screen.findByRole('checkbox', { name: 'Permito que mi Qwen vea el escritorio y controle UserFLEX para esta toma.' })
  expect(get).toHaveBeenCalledWith('video')
  expect((screen.getByLabelText('Proyecto') as HTMLSelectElement).value).toBe('project')
  expect(screen.getByText('Toma 1 · Control con Qwen')).toBeTruthy()
  expect(screen.getByRole('button', { name: 'Ejecutar esta toma con Qwen' })).toBeTruthy()
})
