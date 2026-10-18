// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, expect, test, vi } from 'vitest'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'
import App from '../App'
import { api, ApiError, type Asset, type Chapter, type McpConnectionInfo, type McpConnectionStatus, type Project, type Scene } from '../api'
import { ToastProvider } from '../components/Toast'

const asset: Asset = { id: 'a1', kind: 'image', sha256: 'abc', size_bytes: 1, mime: 'image/png', width: 576, height: 1024, original_name: 'start.png', created_at: '2026-01-01' }
const project: Project = { id: 'p1', name: 'Proyecto', language: 'es', aspect_ratio: '9:16', archived: false, created_at: '2026-01-01', updated_at: '2026-01-01', chapter_count: 1 }
const chapter: Chapter = { id: 'c1', project_id: 'p1', title: 'Capítulo', order_index: 0, script_md: '', continuity_md: '', revision: 1, archived: false, created_at: '2026-01-01', updated_at: '2026-01-01', scene_count: 1, ready_count: 1 }
const scene: Scene = { id: 's1', chapter_id: 'c1', order_index: 0, external_key: null, title: 'Escena', description: '', revision: 1, revision_number: 1, prompt: 'Texto original', duration_seconds: 5, parameters: {}, start_asset: asset, end_asset: null, mode: 'I2VA', status: 'lista', updated_at: '2026-01-01' }
const info: McpConnectionInfo = {
  local_url: 'http://127.0.0.1:8766/mcp', host: '127.0.0.1', port: 8766, authentication: 'none', shell: 'PowerShell',
  http_command: "& 'C:\\Fruti Studio\\python.exe' -m frutinovelas.mcp_server --directory 'C:\\Fruti Studio' --transport streamable-http --host 127.0.0.1 --port 8766",
  stdio_command: "& 'C:\\Fruti Studio\\python.exe' -m frutinovelas.mcp_server --directory 'C:\\Fruti Studio' --transport stdio",
  claude_desktop_config: { mcpServers: { frutinovelas: {
    command: 'C:\\Fruti Studio\\python.exe', args: ['-m', 'frutinovelas.mcp_server', '--directory', 'C:\\Fruti Studio', '--transport', 'stdio'],
    env: { FRUTINOVELAS_API_PORT: '8765' },
  } } },
  claude_config_path: 'C:\\Users\\User\\AppData\\Roaming\\Claude\\claude_desktop_config.json', api_token_configured: false,
}
const ready: McpConnectionStatus = { state: 'ready', detail: 'El servidor MCP local responde y anuncia las herramientas de Studio.', server_name: 'FRUTINOVELAS Prompts', tools_count: 16, local_url: info.local_url, checked_at: '2026-10-18T12:00:00Z' }
const originalApi = { ...api }
const originalClipboard = Object.getOwnPropertyDescriptor(navigator, 'clipboard')
let qc: QueryClient
let router: ReturnType<typeof createMemoryRouter>

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => { resolve = done })
  return { promise, resolve }
}

function setup(overrides: Partial<typeof api> = {}) {
  Object.assign(api, {
    projects: async () => [project], project: async () => project, chapter: async () => chapter,
    chapters: async () => [chapter], scenes: async () => [scene],
    status: async () => ({ app_version: 'test', comfyui: { url: 'http://comfy', reachable: false, version: null, detail: null }, storage: { data_dir: '/tmp', free_bytes: 999999999, low_space: false }, ffmpeg: true }),
    comfyConnection: async () => ({ url: '', configured: false, has_token: false, identity: {} }),
    generations: async () => [], revisions: async () => [], characters: async () => [], imageGenerations: async () => [], chapterRenders: async () => [],
    mcpConnection: async () => info, mcpStatus: async () => ready,
    ...overrides,
  } satisfies Partial<typeof api>)
  vi.spyOn(window, 'confirm').mockReturnValue(false)
  qc = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity }, mutations: { retry: false } } })
  router = createMemoryRouter([{ path: '*', element: <ToastProvider><App /></ToastProvider> }], { initialEntries: ['/capitulos/c1'] })
  render(<QueryClientProvider client={qc}><RouterProvider router={router} /></QueryClientProvider>)
}

async function openMcp() {
  const button = await screen.findByRole('button', { name: /Conexión MCP/ })
  button.focus()
  fireEvent.click(button)
  return screen.findByRole('dialog', { name: 'Conectar ChatGPT o Claude' })
}

function mockClipboard(writeText: (text: string) => Promise<void>) {
  Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } })
}

afterEach(() => {
  cleanup()
  qc?.clear()
  router?.dispose()
  Object.assign(api, originalApi)
  if (originalClipboard) Object.defineProperty(navigator, 'clipboard', originalClipboard)
  else Reflect.deleteProperty(navigator, 'clipboard')
  vi.restoreAllMocks()
})

test('the sidebar modal loads on demand and preserves the active scene draft, route and focus', async () => {
  const connection = vi.fn<typeof api.mcpConnection>(async () => info)
  const status = vi.fn<typeof api.mcpStatus>(async () => ready)
  const update = vi.fn<typeof api.updateScene>()
  setup({ mcpConnection: connection, mcpStatus: status, updateScene: update })
  const prompt = await screen.findByDisplayValue('Texto original') as HTMLTextAreaElement
  fireEvent.change(prompt, { target: { value: 'Borrador literal: ¡Sí, mamá!\n<d>Ánimo.</d>' } })
  expect(connection).not.toHaveBeenCalled()
  expect(status).not.toHaveBeenCalled()
  const dialog = await openMcp()
  await screen.findByLabelText('Comando MCP HTTP · PowerShell')
  expect(connection).toHaveBeenCalledOnce()
  expect(status).not.toHaveBeenCalled()
  expect(router.state.location.pathname).toBe('/capitulos/c1')
  expect(prompt.value).toBe('Borrador literal: ¡Sí, mamá!\n<d>Ánimo.</d>')
  expect(document.querySelector('.app')?.hasAttribute('inert')).toBe(true)
  expect(document.activeElement?.id).toBe('mcp-dialog-title')
  expect(fireEvent.keyDown(dialog, { key: 's', ctrlKey: true })).toBe(false)
  await act(async () => { await Promise.resolve() })
  expect(update).not.toHaveBeenCalled()
  fireEvent.keyDown(dialog, { key: 'Escape' })
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  expect(document.activeElement?.id).toBe('nav-mcp')
  expect(document.querySelector('.app')?.hasAttribute('inert')).toBe(false)
  expect(prompt.value).toBe('Borrador literal: ¡Sí, mamá!\n<d>Ánimo.</d>')
  expect(window.confirm).not.toHaveBeenCalled()
})

test('keyboard focus stays in the modal and clicking its backdrop closes it', async () => {
  setup()
  const dialog = await openMcp()
  await screen.findByLabelText('Comando MCP HTTP · PowerShell')
  const first = screen.getByRole('button', { name: 'Cerrar conexión MCP' })
  const last = screen.getByRole('button', { name: 'Cerrar', exact: true })
  fireEvent.keyDown(document.activeElement!, { key: 'Tab', shiftKey: true })
  expect(document.activeElement).toBe(last)
  fireEvent.keyDown(last, { key: 'Tab' })
  expect(document.activeElement).toBe(first)
  fireEvent.keyDown(first, { key: 'Tab', shiftKey: true })
  expect(document.activeElement).toBe(last)
  ;(document.getElementById('scene-prompt') as HTMLTextAreaElement).focus()
  expect(document.activeElement?.id).toBe('mcp-dialog-title')
  fireEvent.mouseDown(dialog)
  expect(screen.getByRole('dialog')).toBe(dialog)
  fireEvent.mouseDown(dialog.parentElement!)
  expect(screen.queryByRole('dialog')).toBeNull()
  expect(document.activeElement?.id).toBe('nav-mcp')
})

test('Claude Desktop copies the exact local configuration and downloads a separate example file', async () => {
  const writeText = vi.fn<(text: string) => Promise<void>>().mockResolvedValue(undefined)
  mockClipboard(writeText)
  setup({ mcpConnection: async () => ({ ...info, api_token_configured: true }) })
  await openMcp()
  fireEvent.click(screen.getByRole('button', { name: 'Claude Desktop', exact: true }))
  const config = await screen.findByLabelText('Configuración de Claude Desktop') as HTMLTextAreaElement
  expect(JSON.parse(config.value)).toEqual(info.claude_desktop_config)
  expect((screen.getByLabelText('Archivo de configuración de Claude') as HTMLTextAreaElement).value).toBe(info.claude_config_path)
  expect(screen.getByText(/Settings → Developer → Edit Config/)).toBeTruthy()
  expect(screen.getByText(/Conserva las entradas de los demás servidores/)).toBeTruthy()
  expect(screen.getByText(/La API de Studio usa un token local/)).toBeTruthy()
  expect(config.value).not.toContain('FRUTINOVELAS_API_TOKEN')
  fireEvent.click(screen.getByRole('button', { name: 'Copiar Configuración de Claude Desktop' }))
  await waitFor(() => expect(writeText).toHaveBeenCalledWith(JSON.stringify(info.claude_desktop_config, null, 2)))
  await screen.findByText('Copiado al portapapeles.')
  const download = screen.getByRole('link', { name: /Descargar frutinovelas-mcp.json/ }) as HTMLAnchorElement
  expect(download.download).toBe('frutinovelas-mcp.json')
  expect(JSON.parse(decodeURIComponent(download.getAttribute('href')!.split(',')[1]))).toEqual(info.claude_desktop_config)
})

test('a clipboard failure keeps the URL selectable and an explicit retry can succeed', async () => {
  const writeText = vi.fn<(text: string) => Promise<void>>()
    .mockRejectedValueOnce(new DOMException('Not allowed', 'NotAllowedError'))
    .mockResolvedValue(undefined)
  mockClipboard(writeText)
  setup()
  await openMcp()
  const field = await screen.findByLabelText('URL local del MCP para el túnel') as HTMLTextAreaElement
  const copy = screen.getByRole('button', { name: 'Copiar URL local del MCP para el túnel' })
  fireEvent.click(copy)
  await screen.findByText(/No se pudo copiar. El texto sigue disponible/)
  expect(field.value).toBe(info.local_url)
  expect(document.activeElement).toBe(field)
  expect(field.selectionStart).toBe(0)
  expect(field.selectionEnd).toBe(info.local_url.length)
  expect(screen.queryByText('Copiado al portapapeles.')).toBeNull()
  fireEvent.click(copy)
  await screen.findByText('Copiado al portapapeles.')
  expect(writeText).toHaveBeenCalledTimes(2)
  expect(writeText).toHaveBeenLastCalledWith(info.local_url)
})

test('diagnostics run only on request and distinguish network failures, local unreachability and local readiness', async () => {
  const status = vi.fn<typeof api.mcpStatus>()
    .mockRejectedValueOnce(new ApiError(503, 'La API local no está disponible.'))
    .mockResolvedValueOnce({ ...ready, state: 'unreachable', detail: 'No hay respuesta en el puerto del MCP.', server_name: null, tools_count: null })
    .mockResolvedValue(ready)
  const generate = vi.fn<typeof api.generateScene>()
  setup({ mcpStatus: status, generateScene: generate })
  await openMcp()
  const check = await screen.findByRole('button', { name: 'Comprobar MCP local' })
  expect(status).not.toHaveBeenCalled()
  fireEvent.click(check)
  await screen.findByText(/No se pudo completar el diagnóstico local/)
  fireEvent.click(check)
  await screen.findByText('MCP local no responde')
  fireEvent.click(check)
  await screen.findByText('MCP local responde')
  expect(status).toHaveBeenCalledTimes(3)
  expect(status.mock.calls[0][0]).toBeInstanceOf(AbortSignal)
  expect(screen.getByText(/La conexión del cliente se verifica ejecutando una herramienta/)).toBeTruthy()
  expect(screen.queryByText(/^ChatGPT conectado$/)).toBeNull()
  expect(screen.queryByText(/^Claude conectado$/)).toBeNull()
  expect(generate).not.toHaveBeenCalled()
})

test('closing the modal aborts an outstanding local diagnosis', async () => {
  const pending = deferred<McpConnectionStatus>()
  const status = vi.fn<typeof api.mcpStatus>(() => pending.promise)
  setup({ mcpStatus: status })
  const dialog = await openMcp()
  const button = await screen.findByRole('button', { name: 'Comprobar MCP local' }) as HTMLButtonElement
  fireEvent.click(button)
  await waitFor(() => expect(status).toHaveBeenCalledOnce())
  expect(button.disabled).toBe(true)
  fireEvent.keyDown(dialog, { key: 'Escape' })
  expect(status.mock.calls[0][0]?.aborted).toBe(true)
  await act(async () => pending.resolve(ready))
  expect(screen.queryByRole('dialog')).toBeNull()
  expect(screen.queryByText('MCP local responde')).toBeNull()
})

test('configuration errors remain actionable and do not invent a command or connection', async () => {
  const connection = vi.fn<typeof api.mcpConnection>()
    .mockRejectedValueOnce(new ApiError(503, 'Vuelve a abrir Studio.'))
    .mockResolvedValue(info)
  const status = vi.fn<typeof api.mcpStatus>()
  setup({ mcpConnection: connection, mcpStatus: status })
  await openMcp()
  await screen.findByText(/No se pudo cargar la configuración MCP/)
  expect(connection).toHaveBeenCalledOnce()
  expect(screen.queryByLabelText('Comando MCP HTTP · PowerShell')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: 'Reintentar configuración' }))
  const command = await screen.findByLabelText('Comando MCP HTTP · PowerShell') as HTMLTextAreaElement
  expect(command.value).toBe(info.http_command)
  expect(status).not.toHaveBeenCalled()
})

test('Claude web explains its remote requirement without offering localhost or an OpenAI tunnel connection', async () => {
  const status = vi.fn<typeof api.mcpStatus>()
  setup({ mcpStatus: status })
  await openMcp()
  fireEvent.click(screen.getByRole('button', { name: 'Claude web', exact: true }))
  await screen.findByText('Claude web necesita un servidor remoto')
  expect(screen.getByText(/Ese despliegue todavía no está incluido en Studio/)).toBeTruthy()
  expect(screen.queryByLabelText('URL local del MCP para el túnel')).toBeNull()
  expect(screen.queryByLabelText('Configuración de Claude Desktop')).toBeNull()
  expect(screen.queryByRole('button', { name: 'Comprobar MCP local' })).toBeNull()
  expect(status).not.toHaveBeenCalled()
})
