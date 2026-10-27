import { request } from './api'

export type FlowMode = 'assisted' | 'uia' | 'browser'
export type FlowAgentStatus = {
  reachable?: boolean; profile_configured?: boolean | null; window_title?: string | null
  available: boolean; window_open: boolean | null; flow_available: boolean | null; authentication: string
  detail: string; modes: Record<string, { aspect_ratios: string[]; durations: number[]; reference_count: number }>
}
export type FlowStatus = {
  connected: boolean
  mode: FlowMode
  agent: FlowAgentStatus
}
export type FlowJob = {
  id: string; batch_id: string; project_id: string; chapter_id: string; scene_id: string; title: string
  kind: 'image' | 'video'; state: string; approval: string; error: string; scene_revision: number
  cancel_requested: boolean; remote_stopped: boolean; dependency_id: string | null
  result_asset_id: string | null; result_url: string | null; created_at: string
  requested_duration: number | null
  result_metadata: { duration_seconds?: number; has_audio?: boolean; executor?: string; qwen_step?: number; qwen_message?: string }
  snapshot?: { prompt: string; original_prompt: string; references: { asset_id: string; sha256: string }[]; aspect_ratio: string }
}
export type FlowPlan = {
  request_id: string; project_id: string; chapter_id: string; scene_revisions: Record<string, number>
  generation_mode: 'image' | 'video' | 'image_video'; automatic_approval: boolean
  prompts: Record<string, string>; video_prompts: Record<string, string>; duration_seconds: number | null
}
export type QwenStatus = { configured: boolean; worker_running?: boolean; model: string; base_url?: string; detail: string }
const json = (data: unknown): RequestInit => ({ method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) })
export const flowApi = {
  status: () => request<FlowStatus>('/flow/status'),
  detect: async () => {
    const controller = new AbortController()
    const timeout = window.setTimeout(() => controller.abort(), 20000)
    try {
      const agent = await request<FlowAgentStatus>('/flow/detect', { signal: controller.signal })
      if (controller.signal.aborted || !agent || typeof agent.available !== 'boolean'
        || ![true, false, null].includes(agent.window_open) || typeof agent.detail !== 'string'
        || !agent.modes || typeof agent.modes !== 'object') {
        throw new Error('La detección devolvió una respuesta incompleta. Reinicia Studio y el agente para volver a comprobarla.')
      }
      return agent
    } catch (error) {
      if (controller.signal.aborted) throw new Error('La detección tardó demasiado. Comprueba que Studio y el agente estén abiertos y vuelve a detectar.', { cause: error })
      throw error
    } finally {
      window.clearTimeout(timeout)
    }
  },
  connect: (mode: FlowMode, authorized: boolean) => request('/flow/connect', json({ mode, authorized })),
  disconnect: () => request('/flow/disconnect', json({})),
  focus: () => request('/flow/focus', json({})),
  generate: (plan: FlowPlan) => request<FlowJob[]>('/flow/generate', json(plan)),
  jobs: (project: string, chapter: string) => request<FlowJob[]>(`/flow/jobs?project_id=${encodeURIComponent(project)}&chapter_id=${encodeURIComponent(chapter)}`),
  job: (id: string) => request<FlowJob>(`/flow/jobs/${id}`),
  cancel: (id: string) => request<FlowJob>(`/flow/jobs/${id}/cancel`, json({})),
  retry: (id: string, request_id: string) => request<FlowJob>(`/flow/jobs/${id}/retry`, json({ request_id })),
  review: (id: string, expected_revision: number, decision: 'approved' | 'rejected') =>
    request<FlowJob>(`/flow/jobs/${id}/review`, json({ expected_revision, decision })),
  resolve: (id: string, note: string) => request<FlowJob>(`/flow/jobs/${id}/resolve`, json({ confirmed_no_remote_work: true, note })),
  import: (id: string, file: File) => {
    const data = new FormData(); data.append('file', file)
    return request<FlowJob>(`/flow/jobs/${id}/import`, { method: 'POST', body: data })
  },
  qwenStatus: () => request<QwenStatus>('/flow/qwen/status'),
  executeQwen: (id: string, request_id: string, authorized: boolean, confirmed_not_started: boolean) =>
    request<FlowJob>(`/flow/jobs/${id}/execute-qwen`, json({ request_id, authorized, confirmed_not_started })),
}
