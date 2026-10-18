import { useQuery } from '@tanstack/react-query'
import { Clapperboard, FolderOpen, Home, MessagesSquare, PlugZap } from 'lucide-react'
import { useCallback, useRef, useState, type RefObject } from 'react'
import { NavLink, Route, Routes, useParams } from 'react-router-dom'
import { api } from './api'
import { StatusBar } from './components/StatusBar'
import { ChapterPage } from './pages/ChapterPage'
import { ProjectPage } from './pages/ProjectPage'
import { ProjectsPage } from './pages/ProjectsPage'
import { ConnectionPage } from './pages/ConnectionPage'
import { McpConnectionDialog } from './components/McpConnectionDialog'

function Sidebar({ onMcpOpen, mcpButton, mcpOpen }: { onMcpOpen: () => void; mcpButton: RefObject<HTMLButtonElement | null>; mcpOpen: boolean }) {
  const { data: projects } = useQuery({ queryKey: ['projects'], queryFn: () => api.projects() })
  return (
    <aside className="sidebar" aria-label="Navegación">
      <div className="brand">
        <div className="brand-mark">
          <Clapperboard size={20} strokeWidth={2.4} />
        </div>
        <div>
          <div className="brand-name">FRUTINOVELAS</div>
          <div className="brand-sub">Studio</div>
        </div>
      </div>
      <NavLink to="/" end className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`} id="nav-home">
        <Home size={16} /> <span>Proyectos</span>
      </NavLink>
      <NavLink to="/conexion" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
        <PlugZap size={16} /> <span>Conexión ComfyUI</span>
      </NavLink>
      <button id="nav-mcp" ref={mcpButton} type="button" className="nav-item nav-mcp" onClick={onMcpOpen}
        aria-haspopup="dialog" aria-expanded={mcpOpen} aria-controls={mcpOpen ? 'mcp-connection-dialog' : undefined}>
        <MessagesSquare size={16} aria-hidden="true" />
        <span><strong>Conexión MCP</strong><small>ChatGPT · Claude</small></span>
      </button>
      {projects && projects.length > 0 && <div className="nav-label">Tus proyectos</div>}
      {projects?.map((p) => (
        <NavLink
          key={p.id}
          to={`/proyectos/${p.id}`}
          className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}
          title={p.name}
        >
          <FolderOpen size={16} /> <span>{p.name}</span>
        </NavLink>
      ))}
    </aside>
  )
}

function ChapterRoute() {
  const { chapterId } = useParams()
  return <ChapterPage key={chapterId} chapterId={chapterId!} />
}

function ProjectRoute() {
  const { projectId } = useParams()
  return <ProjectPage key={projectId} projectId={projectId!} />
}

export default function App() {
  const [mcpOpen, setMcpOpen] = useState(false)
  const mcpButton = useRef<HTMLButtonElement>(null)
  const closeMcp = useCallback(() => setMcpOpen(false), [])
  return (
    <>
    <div className="app" inert={mcpOpen}>
      <Sidebar onMcpOpen={() => setMcpOpen(true)} mcpButton={mcpButton} mcpOpen={mcpOpen} />
      <main className="main">
        <Routes>
          <Route path="/" element={<ProjectsPage />} />
          <Route path="/conexion" element={<ConnectionPage />} />
          <Route path="/proyectos/:projectId" element={<ProjectRoute />} />
          <Route path="/capitulos/:chapterId" element={<ChapterRoute />} />
          <Route
            path="*"
            element={
              <div className="page empty">
                <h2>Página no encontrada</h2>
                <NavLink className="btn" to="/">
                  Volver a proyectos
                </NavLink>
              </div>
            }
          />
        </Routes>
      </main>
      <StatusBar />
    </div>
    {mcpOpen && <McpConnectionDialog onClose={closeMcp} returnFocus={mcpButton} />}
    </>
  )
}
