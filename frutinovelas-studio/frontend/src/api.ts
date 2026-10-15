// Cliente de la API v1 de FRUTINOVELAS Studio.

export type Project = {
  id: string
  name: string
  language: string
  aspect_ratio: string
  archived: boolean
  created_at: string
  updated_at: string
  chapter_count: number
}

export type Chapter = {
  id: string
  project_id: string
  title: string
  order_index: number
  script_md: string
  continuity_md: string
  revision: number
  archived: boolean
  created_at: string
  updated_at: string
  scene_count: number
  ready_count: number
}

export type Asset = {
  id: string
  kind: string
  sha256: string
  size_bytes: number
  mime: string
  width: number | null
  height: number | null
  original_name: string
  created_at: string
}

export type SceneStatus = 'sin_imagen' | 'sin_prompt' | 'lista'

export type PromptIssue = {
  severity: 'error' | 'warning' | 'info'
  code: string
  message: string
}

export type PromptCheckInput = {
  prompt: string
  duration_seconds: number
  has_start_image: boolean
  has_end_image: boolean
}

export type SceneParameters = {
  seed_mode?: 'random' | 'fixed'
  seed?: number | null
  [k: string]: unknown
}

export type Scene = {
  id: string
  chapter_id: string
  order_index: number
  external_key: string | null
  title: string
  description: string
  revision: number
  revision_number: number
  prompt: string
  duration_seconds: number
  parameters: SceneParameters
  start_asset: Asset | null
  end_asset: Asset | null
  mode: 'I2VA' | 'FL2VA' | null
  status: SceneStatus
  updated_at: string
}

export type SceneRevision = {
  id: string
  number: number
  prompt: string
  start_asset_id: string | null
  end_asset_id: string | null
  duration_seconds: number
  parameters: SceneParameters
  author: string
  created_at: string
}

export type SystemStatus = {
  app_version: string
  comfyui: { url: string; reachable: boolean; version: string | null; detail: string | null }
  storage: { data_dir: string; free_bytes: number; low_space: boolean }
  ffmpeg: boolean
}

export type ComfyConnection = {
  url: string
  configured: boolean
  has_token: boolean
  identity: { comfyui_version?: string; perfil_video?: string; estado_compatibilidad?: string }
}

export type Generation = {
  id: string
  scene_id: string
  state: 'queued' | 'uploading' | 'submitting' | 'waiting' | 'running' | 'downloading' | 'unknown' | 'completed' | 'failed'
  error: string
  revision_number: number
  duration_seconds: number
  frames: number
  effective_seconds: number
  seed: number
  created_at: string
  result_url: string | null
}

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

const BASE = '/api/v1'

function describe(detail: unknown): string {
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    return detail
      .map((d) => (typeof d === 'object' && d && 'msg' in d ? String((d as { msg: unknown }).msg) : String(d)))
      .join(' · ')
  }
  return 'Error inesperado del servidor.'
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  let res: Response
  try {
    res = await fetch(BASE + path, init)
  } catch {
    throw new ApiError(0, 'No hay conexión con el servidor de FRUTINOVELAS Studio.')
  }
  if (res.status === 204) return undefined as T
  const body = await res.json().catch(() => null)
  if (!res.ok) throw new ApiError(res.status, describe(body?.detail))
  return body as T
}

const json = (method: string, data: unknown): RequestInit => ({
  method,
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(data),
})

export const api = {
  checkPrompt: (data: PromptCheckInput) => request<PromptIssue[]>('/prompts/lint', json('POST', data)),
  status: () => request<SystemStatus>('/system/status'),
  comfyConnection: () => request<ComfyConnection>('/comfy/connection'),
  saveComfyConnection: (url: string, token: string) =>
    request<ComfyConnection>('/comfy/connection', json('PUT', { url, token })),
  generations: (sceneId: string) => request<Generation[]>(`/scenes/${sceneId}/generations`),
  generateScene: (sceneId: string, expectedRevision: number, requestId: string) =>
    request<Generation>(`/scenes/${sceneId}/generate`, json('POST', { expected_revision: expectedRevision, request_id: requestId })),
  abandonGeneration: (id: string) => request<Generation>(`/generations/${id}/abandon`, { method: 'POST' }),

  projects: (archived = false) => request<Project[]>(`/projects?archived=${archived}`),
  project: (id: string) => request<Project>(`/projects/${id}`),
  createProject: (name: string) => request<Project>('/projects', json('POST', { name })),
  updateProject: (id: string, data: Partial<Pick<Project, 'name' | 'archived' | 'aspect_ratio'>>) =>
    request<Project>(`/projects/${id}`, json('PATCH', data)),

  chapters: (projectId: string) => request<Chapter[]>(`/projects/${projectId}/chapters`),
  chapter: (id: string) => request<Chapter>(`/chapters/${id}`),
  createChapter: (projectId: string, title: string) =>
    request<Chapter>(`/projects/${projectId}/chapters`, json('POST', { title })),
  updateChapter: (
    id: string,
    data: { expected_revision: number } & Partial<Pick<Chapter, 'title' | 'script_md' | 'continuity_md' | 'archived'>>,
  ) => request<Chapter>(`/chapters/${id}`, json('PATCH', data)),

  scenes: (chapterId: string) => request<Scene[]>(`/chapters/${chapterId}/scenes`),
  createScene: (chapterId: string, data: Record<string, unknown> = {}) =>
    request<Scene>(`/chapters/${chapterId}/scenes`, json('POST', data)),
  updateScene: (id: string, data: { expected_revision: number } & Record<string, unknown>) =>
    request<Scene>(`/scenes/${id}`, json('PATCH', data)),
  duplicateScene: (id: string) => request<Scene>(`/scenes/${id}/duplicate`, { method: 'POST' }),
  deleteScene: (id: string) => request<void>(`/scenes/${id}`, { method: 'DELETE' }),
  reorderScenes: (chapterId: string, sceneIds: string[]) =>
    request<Scene[]>(`/chapters/${chapterId}/scene-order`, json('PUT', { scene_ids: sceneIds })),
  revisions: (sceneId: string) => request<SceneRevision[]>(`/scenes/${sceneId}/revisions`),

  uploadAsset: (file: File) => {
    const fd = new FormData()
    fd.append('file', file)
    return request<Asset>('/assets', { method: 'POST', body: fd })
  },
}

export const assetUrl = (id: string) => `${BASE}/assets/${id}/content`
export const thumbUrl = (id: string, size = 320) => `${BASE}/assets/${id}/thumb?size=${size}`
