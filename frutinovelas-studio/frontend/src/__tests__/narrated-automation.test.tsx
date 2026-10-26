// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { api, type NarratedVideo } from '../api'
import { NarratedAutomation } from '../components/NarratedAutomation'

const video: NarratedVideo = {
  id: 'video', project_id: 'project', title: 'Historia', audio_asset_id: 'audio', audio_duration: 12,
  transcript: 'La fruta mira el cielo.', aspect_ratio: '9:16', revision: 1,
  state: 'draft', progress: 0, error: '', result_url: null,
  shots: [{ start_seconds: 0, end_seconds: 12, text: '', image_prompt: 'Imagen literal', animation_prompt: '',
    image_asset_id: null, motion: 'still', media_mode: 'static',
    references: [{ asset_id: 'style', role: 'style', description: 'Acuarela' }], visual_style: 'Luz cálida' }],
}

afterEach(() => { cleanup(); vi.restoreAllMocks() })

it('opens the chapter containing the narrated jobs instead of an empty selection', () => {
  render(<NarratedAutomation video={{ ...video, flow_chapter_id: 'narrated-chapter' }} dirty={false} onUpdate={vi.fn()}/> )
  expect(screen.getByRole('link', { name: 'Abrir cola Flow' }).getAttribute('href')).toBe('/flow-automation?project_id=project&chapter_id=narrated-chapter')
})

it('sends selected references and mode to Qwen without dispatching Flow', async () => {
  const plan = vi.spyOn(api, 'planNarratedVideo').mockResolvedValue(video)
  const send = vi.spyOn(api, 'sendNarratedFlow').mockResolvedValue({ video, jobs: [] })
  const update = vi.fn()
  render(<NarratedAutomation video={video} dirty={false} onUpdate={update}/> )
  fireEvent.change(screen.getByLabelText('Forma del video'), { target: { value: 'animated' } })
  fireEvent.click(screen.getByText('Preparar tomas con Qwen'))
  await waitFor(() => expect(update).toHaveBeenCalledWith(video))
  expect(plan.mock.calls[0][1]).toMatchObject({ media_mode: 'animated', visual_style: 'Luz cálida', references: video.shots[0].references })
  expect(send).not.toHaveBeenCalled()
})

it('reuses dispatch ID after a lost response and defaults to manual approval', async () => {
  const send = vi.spyOn(api, 'sendNarratedFlow').mockRejectedValue(new Error('Respuesta perdida'))
  render(<NarratedAutomation video={video} dirty={false} onUpdate={vi.fn()}/> )
  fireEvent.click(screen.getByText('Enviar tomas guardadas a Flow'))
  await screen.findByText('Respuesta perdida')
  fireEvent.click(screen.getByText('Enviar tomas guardadas a Flow'))
  await waitFor(() => expect(send).toHaveBeenCalledTimes(2))
  expect(send.mock.calls[0][1].request_id).toBe(send.mock.calls[1][1].request_id)
  expect(send.mock.calls[0][1].automatic_approval).toBe(false)
})

it('does not plan or dispatch an unsaved draft', () => {
  render(<NarratedAutomation video={video} dirty onUpdate={vi.fn()}/> )
  expect((screen.getByText('Preparar tomas con Qwen') as HTMLButtonElement).disabled).toBe(true)
  expect((screen.getByText('Enviar tomas guardadas a Flow') as HTMLButtonElement).disabled).toBe(true)
})

it('persists reference roles without requiring Qwen inference', async () => {
  const save = vi.spyOn(api, 'updateNarratedVideo').mockResolvedValue(video)
  const plan = vi.spyOn(api, 'planNarratedVideo')
  render(<NarratedAutomation video={video} dirty={false} onUpdate={vi.fn()}/> )
  fireEvent.click(screen.getByText('Guardar referencias y opciones'))
  await waitFor(() => expect(save).toHaveBeenCalledTimes(1))
  expect(save.mock.calls[0][1].shots?.[0].references).toEqual(video.shots[0].references)
  expect(plan).not.toHaveBeenCalled()
})
