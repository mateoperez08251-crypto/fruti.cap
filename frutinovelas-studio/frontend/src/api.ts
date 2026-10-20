// Cliente de la API v1 de FRUTINOVELAS Studio.

export type NarratedShot = {
  start_seconds: number
  end_seconds: number
  text: string
  image_prompt: string
  animation_prompt: string
  image_asset_id: string | null
  motion: 'zoom_in' | 'zoom_out' | 'pan_left' | 'pan_right' | 'still'
}
export type NarratedVideo = {
  id: string
  project_id: string
  title: string
  audio_asset_id: string
  audio_duration: number
  transcript: string
  aspect_ratio: '9:16' | '16:9'
  shots: NarratedShot[]
  revision: number
  state: 'draft' | 'queued' | 'rendering' | 'completed' | 'failed'
  progress: number
  error: string
  result_url: string | null
}

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
  duration_seconds?: number | null
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
  image_approval?: 'manual' | 'automatic'
  image_prompt?: string
  character_ids?: string[]
  cast?: CharacterReference[]
  audio_guides?: AudioGuide[]
  voice_character_ids?: string[]
  voice_references?: VoiceReference[]
  seed_mode?: 'random' | 'fixed'
  seed?: number | null
  [k: string]: unknown
}

export type CharacterReference = { character_id: string; name: string; description: string; asset_id: string; sha256: string }
export type AudioGuideInput = { asset_id: string; character_id: string | null; start_seconds: number }
export type AudioGuide = AudioGuideInput & { asset?: Asset; character_name?: string | null; voice_description?: string }
export type VoiceReference = { character_id: string; character_name: string; voice_description: string; asset_id: string; asset: Asset }
export type Character = { id: string; project_id: string; name: string; description: string; revision: number; archived: boolean; reference_asset: Asset; voice_description?: string; voice_asset?: Asset | null }
export type CharacterInput = { name: string; description: string; reference_asset_id: string; voice_description?: string; voice_asset_id?: string | null }
export type ChapterRender = { id: string; chapter_id: string; state: string; error: string; scenes: { scene_id: string; title: string }[]; result_url: string | null }
export type ImageGeneration = { id: string; scene_id: string; kind: 'image'; auto_finish_done?: boolean; approval_mode?: 'manual' | 'automatic'; state: Generation['state']; error: string;
  revision_number: number; seed: number; references: CharacterReference[]; result_asset_id: string | null; result_url: string | null; created_at: string }

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

export type McpConnectionInfo = {
  local_url: string
  host: string
  port: number
  authentication: 'none'
  shell: 'PowerShell' | 'Terminal'
  http_command: string
  stdio_command: string
  claude_desktop_config: { mcpServers: Record<string, { command: string; args: string[]; env: Record<string, string> }> }
  claude_config_path: string | null
  api_token_configured: boolean
}

export type McpConnectionStatus = {
  state: 'ready' | 'unreachable' | 'incompatible'
  detail: string
  server_name: string | null
  tools_count: number | null
  local_url: string
  checked_at: string
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
  state: 'queued' | 'uploading' | 'submitting' | 'waiting' | 'running' | 'downloading' | 'unknown' | 'completed' | 'failed' | 'cancelled'
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
  } catch (error) {
    if (init.signal?.aborted) throw error
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
  deleteNarratedOutput: (id: string) => request<NarratedVideo>('/narrated-videos/' + id + '/output', { method: 'DELETE' }),
  stopGeneration: (id: string) => request<{ id: string; state: string }>('/generations/' + id + '/stop', { method: 'POST' }),
  recoverQueue: () => request<{ status: string; recovered: string[] }>('/comfy/queue/recover', { method: 'POST' }),
  stopChapterRender: (id: string) => request<{ stopped: boolean; pending_jobs: string[] }>('/chapter-renders/' + id + '/stop', { method: 'POST' }),
  comfyQueue: () => request<{ status: string; server: { available: boolean; code: string; message: string }; running: unknown[]; pending: unknown[]; local_jobs: unknown[] }>('/comfy/queue'),
  discardGenerationOutput: (id: string) => request<{discarded: boolean; remote_copy: string}>('/generations/' + id + '/output', { method: 'DELETE' }),
  narratedVideos: (projectId: string) => request<NarratedVideo[]>('/projects/' + projectId + '/narrated-videos'),
  narratedVideo: (id: string) => request<NarratedVideo>('/narrated-videos/' + id),
  uploadNarration: (file: File) => {
    const fd = new FormData()
    fd.append('file', file)
    return request<Asset>('/assets/narration', { method: 'POST', body: fd })
  },
  createNarratedVideo: (projectId: string, data: { title: string; audio_asset_id: string; transcript: string; aspect_ratio: '9:16' | '16:9' }) =>
    request<NarratedVideo>('/projects/' + projectId + '/narrated-videos', json('POST', data)),
  updateNarratedVideo: (id: string, data: { expected_revision: number; title?: string; transcript?: string; shots?: NarratedShot[]; aspect_ratio?: '9:16' | '16:9' }) =>
    request<NarratedVideo>('/narrated-videos/' + id, json('PATCH', data)),
  renderNarratedVideo: (id: string, expected_revision: number) =>
    request<NarratedVideo>('/narrated-videos/' + id + '/render', json('POST', { expected_revision })),
  chapterRenders: (id: string, signal?: AbortSignal) => request<ChapterRender[]>(`/chapters/${id}/renders`, { signal }),
  renderChapter: (id: string, revision: number, scenes: Record<string, number>, requestId: string) => request<ChapterRender>(`/chapters/${id}/render`, json('POST', { expected_revision: revision, scene_revisions: scenes, request_id: requestId, automatic_approval: true })),
  characters: (projectId: string, signal?: AbortSignal) => request<Character[]>(`/projects/${projectId}/characters`, { signal }),
  createCharacter: (projectId: string, data: CharacterInput) => request<Character>(`/projects/${projectId}/characters`, json('POST', data)),
  updateCharacter: (id: string, data: CharacterInput & { expected_revision: number; archived?: boolean }) => request<Character>(`/characters/${id}`, json('PUT', data)),
  imageGenerations: (sceneId: string, signal?: AbortSignal) => request<ImageGeneration[]>(`/scenes/${sceneId}/image-generations`, { signal }),
  generateSceneImage: (sceneId: string, revision: number, requestId: string, autoAnimate = false) => request<ImageGeneration>(`/scenes/${sceneId}/generate-image`, json('POST', { expected_revision: revision, request_id: requestId, auto_animate: autoAnimate })),
  approveSceneImage: (jobId: string, revision: number, role: 'start' | 'end') => request<Scene>(`/image-generations/${jobId}/approve`, json('POST', { expected_revision: revision, role })),
  checkPrompt: (data: PromptCheckInput) => request<PromptIssue[]>('/prompts/lint', json('POST', data)),
  status: (signal?: AbortSignal) => request<SystemStatus>('/system/status', { signal }),
  mcpConnection: (signal?: AbortSignal) => request<McpConnectionInfo>('/mcp/connection', { signal }),
  mcpStatus: (signal?: AbortSignal) => request<McpConnectionStatus>('/mcp/status', { signal }),
  comfyConnection: () => request<ComfyConnection>('/comfy/connection'),
  saveComfyConnection: (url: string, token: string) =>
    request<ComfyConnection>('/comfy/connection', json('PUT', { url, token })),
  generations: (sceneId: string, signal?: AbortSignal) => request<Generation[]>(`/scenes/${sceneId}/generations`, { signal }),
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
  revisions: (sceneId: string, signal?: AbortSignal) => request<SceneRevision[]>(`/scenes/${sceneId}/revisions`, { signal }),

  uploadAsset: (file: File, signal?: AbortSignal) => {
    const fd = new FormData()
    fd.append('file', file)
    return request<Asset>('/assets', { method: 'POST', body: fd, signal })
  },
  uploadAudio: (file: File, signal?: AbortSignal) => {
    const fd = new FormData()
    fd.append('file', file)
    return request<Asset>('/assets/audio', { method: 'POST', body: fd, signal })
  },
}

export const assetUrl = (id: string) => `${BASE}/assets/${id}/content`
export const thumbUrl = (id: string, size = 320) => `${BASE}/assets/${id}/thumb?size=${size}`
