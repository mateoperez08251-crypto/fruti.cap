import { useQuery } from '@tanstack/react-query'
import { Clapperboard, FolderOpen, Home, PlugZap } from 'lucide-react'
import { NavLink, Route, Routes, useParams } from 'react-router-dom'
import { api } from './api'
import { StatusBar } from './components/StatusBar'
import { ChapterPage } from './pages/ChapterPage'
import { ProjectPage } from './pages/ProjectPage'
import { ProjectsPage } from './pages/ProjectsPage'
import { ConnectionPage } from './pages/ConnectionPage'

function Sidebar() {
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
  return (
    <div className="app">
      <Sidebar />
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
  )
}
