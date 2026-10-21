import { useMutation, useQuery } from '@tanstack/react-query'
import { Check, Copy, Download, ExternalLink, Loader2, RefreshCw, X } from 'lucide-react'
import { useEffect, useRef, useState, type KeyboardEvent, type RefObject } from 'react'
import { api, type McpConnectionInfo } from '../api'

type Client = 'chatgpt' | 'claude-desktop' | 'claude-web' | 'public-test'
type Props = { onClose: () => void; returnFocus: RefObject<HTMLButtonElement | null> }

const readingTest = 'Usa las herramientas de FRUTINOVELAS. Llama a get_directing_guidance con task="animation", preset="frutinovelas" e include_example_story=false. Resume las reglas de movimiento, sombras, expresiones y diálogo. No guardes cambios ni generes un video.'

function CopyBlock({ id, label, value, rows = 3 }: { id: string; label: string; value: string; rows?: number }) {
  const field = useRef<HTMLTextAreaElement>(null)
  const [result, setResult] = useState<{ value: string; state: 'copying' | 'copied' | 'error' } | null>(null)
  const state = result?.value === value ? result.state : null
  const copy = async () => {
    setResult({ value, state: 'copying' })
    try {
      if (!navigator.clipboard?.writeText) throw new Error('Clipboard unavailable')
      await navigator.clipboard.writeText(value)
      setResult({ value, state: 'copied' })
    } catch {
      setResult({ value, state: 'error' })
      field.current?.focus()
      field.current?.select()
    }
  }
  return <div className="field mcp-copy-block">
    <div className="mcp-copy-heading">
      <label htmlFor={id}>{label}</label>
      <button type="button" className="btn btn-sm" aria-label={`Copiar ${label}`} disabled={state === 'copying'} onClick={() => void copy()}>
        {state === 'copied' ? <Check size={14} aria-hidden="true" /> : state === 'copying' ? <Loader2 size={14} className="spin" aria-hidden="true" /> : <Copy size={14} aria-hidden="true" />}
        {state === 'copied' ? 'Copiado' : 'Copiar'}
      </button>
    </div>
    <textarea id={id} ref={field} className="textarea mcp-code" readOnly value={value} rows={rows} wrap="off" spellCheck={false}
      onFocus={(event) => event.currentTarget.select()} />
    {state === 'copied' && <span className="hint" role="status">Copiado al portapapeles.</span>}
    {state === 'error' && <p className="generation-error" role="alert">No se pudo copiar. El texto sigue disponible: selecciónalo y usa Ctrl+C o ⌘C.</p>}
  </div>
}

function ClientInstructions({ client, info }: { client: Client; info: McpConnectionInfo }) {
  const config = JSON.stringify(info.claude_desktop_config, null, 2)
  if (client === 'public-test') return <section className="mcp-instructions" aria-label="Prueba pública del MCP">
    <h3>Prueba pública · URL HTTPS temporal</h3>
    <p>Esto permite conectarse mediante una URL externa sin pertenecer a tu organización de OpenAI. <strong>Sin autenticación, cualquier persona que conozca el enlace puede leer proyectos, modificar escenas o solicitar generaciones.</strong> Usa únicamente proyectos de prueba y detén el túnel cuando termines.</p>
    <ol className="mcp-steps">
      <li>Instala <code>cloudflared</code> desde Cloudflare si no está instalado. En Windows puedes usar <code>winget install --id Cloudflare.cloudflared</code>.</li>
      <li>Abre <strong>CMD</strong> en la carpeta <code>frutinovelas-studio</code>, con Studio encendido. Ejecuta el archivo indicado abajo; escribe <strong>PUBLICAR</strong> cuando solicite confirmación.</li>
      <li>La consola mostrará una URL <code>https://…trycloudflare.com/mcp</code>. Copia esa URL completa; <strong>no uses localhost ni selecciones Tunnel de OpenAI</strong>.</li>
      <li>En tu cliente ChatGPT o Claude, agrega un servidor MCP <strong>remoto / por URL</strong>, pega el HTTPS generado y elige <strong>sin autenticación</strong> cuando el cliente lo permita. Esa cuenta debe tener habilitada la conexión de MCP personalizados.</li>
      <li>Prueba <code>get_directing_guidance</code> y comprueba la llamada real. Presiona <strong>Ctrl+C</strong> en la consola pública para cortar el acceso.</li>
    </ol>
    <CopyBlock id="mcp-public-test-cmd" label="Comando de prueba pública · CMD (desde frutinovelas-studio)" value="publicar_mcp_prueba.cmd" rows={1} />
    <p className="hint">La URL se crea al iniciar Cloudflare Quick Tunnel y puede cambiar en cada ejecución. Studio no puede inventarla ni comprobar el acceso de una cuenta externa.</p>
    <a className="mcp-doc-link" href="https://github.com/mateoperez08251-crypto/fruti.cap/blob/main/frutinovelas-studio/docs/MCP_PUBLICO_PRUEBA.md" target="_blank" rel="noreferrer">Manual de prueba pública <ExternalLink size={14} aria-hidden="true" /></a>
  </section>

  if (client === 'claude-web') return <section className="mcp-instructions" aria-label="Configurar Claude web">
    <h3>Claude web necesita un servidor remoto</h3>
    <p>Claude web requiere una URL HTTPS accesible desde su nube y un despliegue con protección y autenticación adecuadas. Ese despliegue todavía no está incluido en Studio.</p>
    <p>La dirección localhost de tu equipo y el túnel privado de OpenAI no son direcciones utilizables para esta opción. Puedes usar la configuración local de Claude Desktop en este equipo.</p>
    <a className="mcp-doc-link" href="https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp" target="_blank" rel="noreferrer">
      Guía oficial de conectores remotos de Claude <ExternalLink size={14} aria-hidden="true" />
    </a>
  </section>

  if (client === 'claude-desktop') return <section className="mcp-instructions" aria-label="Configurar Claude Desktop">
    <h3>Claude Desktop · conexión local</h3>
    <p>En este mismo equipo, Claude Desktop inicia el MCP automáticamente mediante stdio. Mantén Studio abierto para consultar tus proyectos y escenas.</p>
    <ol className="mcp-steps">
      <li>Abre <strong>Settings → Developer → Edit Config</strong> en Claude Desktop.</li>
      <li>Añade la entrada <code>frutinovelas</code> dentro de <code>mcpServers</code>. Conserva las entradas de los demás servidores; integra este ejemplo en tu configuración existente.</li>
      <li>Guarda el archivo, sal por completo de Claude Desktop y vuelve a abrirlo.</li>
      <li>Revisa el servidor y sus herramientas en Claude y ejecuta la prueba de lectura de abajo.</li>
    </ol>
    {info.claude_config_path && <CopyBlock id="mcp-claude-path" label="Archivo de configuración de Claude" value={info.claude_config_path} rows={2} />}
    <CopyBlock id="mcp-claude-config" label="Configuración de Claude Desktop" value={config} rows={11} />
    <a className="btn btn-sm mcp-download" href={`data:application/json;charset=utf-8,${encodeURIComponent(config + '\n')}`} download="frutinovelas-mcp.json">
      <Download size={14} aria-hidden="true" /> Descargar frutinovelas-mcp.json
    </a>
    <p className="hint">La descarga es un archivo de ejemplo para integrar. No sustituye ni instala automáticamente la configuración de Claude.</p>
    <a className="mcp-doc-link" href="https://modelcontextprotocol.io/docs/develop/connect-local-servers" target="_blank" rel="noreferrer">
      Guía oficial de servidores locales en Claude Desktop <ExternalLink size={14} aria-hidden="true" />
    </a>
  </section>

  return <section className="mcp-instructions" aria-label="Configurar ChatGPT">
    <h3>ChatGPT · tu túnel privado de OpenAI</h3>
    <ol className="mcp-steps">
      <li>Si el MCP no está iniciado, ejecuta el comando siguiente en <strong>{info.shell}</strong> de este equipo y mantén la terminal abierta.</li>
      <li>Inicia tu cliente de túnel de OpenAI y apunta al MCP local. Reutiliza el mismo túnel y, si ya lo tienes, el perfil <code>fruti-local</code>.</li>
      <li>En ChatGPT, abre <strong>Plugins → + → Add custom MCP server</strong>. Selecciona <strong>Connection: Tunnel</strong> y elige ese túnel.</li>
      <li>{info.authentication === 'bearer' ? <>Configura tu cliente o túnel para enviar el token MCP mediante la cabecera <strong>Authorization: Bearer</strong>. Si tu cliente no admite este método, utiliza Claude Desktop por stdio para Flow.</> : <>Para este MCP elige <strong>No authentication</strong>, crea el plugin con <strong>Create as a plugin</strong> e instálalo. En un chat nuevo, selecciónalo con <strong>@</strong> y ejecuta la prueba de lectura. Flow requiere stdio o HTTP autenticado.</>}</li>
    </ol>
    <CopyBlock id="mcp-http-command" label={`Comando MCP HTTP · ${info.shell}`} value={info.http_command} rows={3} />
    <CopyBlock id="mcp-local-url" label="URL local del MCP para el túnel" value={info.local_url} rows={1} />
    <p className="hint">Esta URL conecta tunnel-client con el MCP de tu equipo. En ChatGPT se selecciona el túnel; localhost no es una URL pública.</p>
    <p className="hint">{info.authentication === 'bearer' ? 'El token MCP se conserva en la configuración local y no se muestra en este panel.' : '«No authentication» corresponde a este servidor MCP. El cliente de túnel utiliza su propia configuración privada de OpenAI.'}</p>
    <div className="mcp-doc-links">
      <a className="mcp-doc-link" href="https://chatgpt.com/plugins" target="_blank" rel="noreferrer">Abrir Plugins de ChatGPT <ExternalLink size={14} aria-hidden="true" /></a>
      <a className="mcp-doc-link" href="https://platform.openai.com/settings/organization/tunnels" target="_blank" rel="noreferrer">Abrir mis túneles de OpenAI <ExternalLink size={14} aria-hidden="true" /></a>
      <a className="mcp-doc-link" href="https://developers.openai.com/api/docs/guides/secure-mcp-tunnels" target="_blank" rel="noreferrer">Guía oficial del túnel <ExternalLink size={14} aria-hidden="true" /></a>
      <a className="mcp-doc-link" href="https://developers.openai.com/api/docs/guides/custom-mcp-server" target="_blank" rel="noreferrer">Guía oficial de conexión con ChatGPT <ExternalLink size={14} aria-hidden="true" /></a>
    </div>
  </section>
}

export function McpConnectionDialog({ onClose, returnFocus }: Props) {
  const dialog = useRef<HTMLDivElement>(null)
  const title = useRef<HTMLHeadingElement>(null)
  const checkController = useRef<AbortController | null>(null)
  const [client, setClient] = useState<Client>('chatgpt')
  const connection = useQuery({ queryKey: ['mcp-connection'], queryFn: ({ signal }) => api.mcpConnection(signal),
    retry: false, staleTime: 0, refetchOnMount: 'always', refetchOnWindowFocus: false, refetchOnReconnect: false })
  const check = useMutation({ mutationFn: () => {
    checkController.current?.abort()
    const controller = new AbortController()
    checkController.current = controller
    return api.mcpStatus(controller.signal)
  }, retry: false })

  useEffect(() => {
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null
    const opener = returnFocus.current ?? previousFocus
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    title.current?.focus()
    const keepFocus = (event: FocusEvent) => {
      if (event.target instanceof Node && !dialog.current?.contains(event.target)) title.current?.focus()
    }
    document.addEventListener('focusin', keepFocus)
    return () => {
      document.removeEventListener('focusin', keepFocus)
      document.body.style.overflow = previousOverflow
      checkController.current?.abort()
      if (opener?.isConnected) opener.focus()
    }
  }, [returnFocus])

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    // El editor conserva sus borradores y atajos, pero no debe guardar desde este modal.
    event.stopPropagation()
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') event.preventDefault()
    if (event.key === 'Escape') {
      event.preventDefault()
      onClose()
    }
    if (event.key !== 'Tab') return
    const focusable = [...(dialog.current?.querySelectorAll<HTMLElement>('button:not([disabled]), a[href], textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])') ?? [])]
      .filter((element) => element.tabIndex >= 0 && !element.closest('[hidden], [inert]'))
    const first = focusable[0]
    const last = focusable[focusable.length - 1]
    if (!first || !last) {
      event.preventDefault()
      title.current?.focus()
    } else if (event.shiftKey && (document.activeElement === first || document.activeElement === title.current)) {
      event.preventDefault()
      last.focus()
    } else if (!event.shiftKey && (document.activeElement === last || document.activeElement === title.current)) {
      event.preventDefault()
      first.focus()
    }
  }

  const info = connection.data
  const statusLabels = { ready: 'MCP local responde', unreachable: 'MCP local no responde', incompatible: 'El servicio local no es compatible con este MCP' }
  return <div className="backdrop mcp-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose() }}>
    <div id="mcp-connection-dialog" ref={dialog} className="card dialog mcp-dialog" role="dialog" aria-modal="true"
      aria-labelledby="mcp-dialog-title" aria-describedby="mcp-dialog-description" onKeyDown={onKeyDown}>
      <header className="mcp-dialog-heading">
        <div><h2 id="mcp-dialog-title" ref={title} tabIndex={-1}>Conectar ChatGPT o Claude</h2>
          <p id="mcp-dialog-description" className="hint">Elige tu cliente y configura su acceso a las herramientas de Studio. Tus escenas permanecen abiertas.</p></div>
        <button type="button" className="btn btn-ghost btn-icon" aria-label="Cerrar conexión MCP" onClick={onClose}><X size={18} aria-hidden="true" /></button>
      </header>
      <div className="mcp-clients" role="group" aria-label="Cliente MCP">
        {([['chatgpt', 'ChatGPT'], ['claude-desktop', 'Claude Desktop'], ['claude-web', 'Claude web'], ['public-test', 'Prueba pública HTTPS']] as const).map(([value, label]) =>
          <button key={value} type="button" className={`btn ${client === value ? 'btn-primary' : ''}`} aria-pressed={client === value} onClick={() => setClient(value)}>{label}</button>)}
      </div>
      {connection.isPending && <p className="hint" role="status"><Loader2 size={16} className="spin" aria-hidden="true" /> Cargando configuración local…</p>}
      {connection.isError && <div className="notice warn" role="alert"><div>
        <p>No se pudo cargar la configuración MCP. {connection.error.message}</p>
        <button type="button" className="btn btn-sm" disabled={connection.isFetching} onClick={() => void connection.refetch()}>Reintentar configuración</button>
      </div></div>}
      {info && <>
        <ClientInstructions key={client} client={client} info={info} />
        {info.api_token_configured && <p className="notice">La API de Studio usa un token local. El MCP debe leer esa misma configuración local; los comandos y el JSON no incluyen el secreto.</p>}
        {client !== 'claude-web' && <section className="mcp-diagnostic" aria-labelledby="mcp-check-title">
          <h3 id="mcp-check-title">Diagnóstico del MCP local</h3>
          <p className="hint">Comprueba el protocolo y las herramientas del servidor HTTP local. No inicia generaciones y no confirma que ChatGPT o Claude se hayan conectado.</p>
          {client === 'claude-desktop' && <p className="hint">Claude Desktop usa stdio: puede funcionar aunque el servidor HTTP de este diagnóstico esté apagado.</p>}
          <button type="button" className="btn" disabled={check.isPending} onClick={() => check.mutate()}>
            {check.isPending ? <Loader2 size={15} className="spin" aria-hidden="true" /> : <RefreshCw size={15} aria-hidden="true" />} Comprobar MCP local
          </button>
          {check.isPending && <p className="hint" role="status">Comprobando MCP local…</p>}
          {check.isError && <p className="generation-error" role="alert">No se pudo completar el diagnóstico local. {check.error.message} Puedes volver a comprobarlo.</p>}
          {check.data && !check.isPending && <div className={`mcp-check-result ${check.data.state === 'ready' ? 'ready' : 'warn'}`} role="status">
            <strong>{statusLabels[check.data.state]}</strong>
            <p>{check.data.detail}</p>
            {check.data.server_name && <p className="hint">Servidor: {check.data.server_name}{check.data.tools_count != null ? ` · ${check.data.tools_count} herramientas` : ''}</p>}
            <p className="hint">URL comprobada: <code>{check.data.local_url}</code></p>
            <p className="hint">La conexión del cliente se verifica ejecutando una herramienta desde ChatGPT o Claude.</p>
          </div>}
        </section>}
        {client !== 'claude-web' && <section className="mcp-reading-test" aria-label="Prueba desde el cliente">
          <h3>Prueba desde ChatGPT o Claude</h3>
          <p className="hint">Después de configurar el cliente, envía esta petición allí y revisa que la herramienta devuelva las guías.</p>
          <CopyBlock id="mcp-reading-test" label="Prueba de lectura para el cliente" value={readingTest} rows={4} />
        </section>}
      </>}
      <div className="dialog-actions"><button type="button" className="btn" onClick={onClose}>Cerrar</button></div>
    </div>
  </div>
}
