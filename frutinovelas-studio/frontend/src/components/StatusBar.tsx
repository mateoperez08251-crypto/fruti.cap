import { useQuery } from '@tanstack/react-query'
import { Cpu, Film, HardDrive, Server } from 'lucide-react'
import { api } from '../api'

const gb = (bytes: number) => `${(bytes / 1024 ** 3).toFixed(1)} GB`

export function StatusBar() {
  const { data, isError } = useQuery({
    queryKey: ['status'],
    queryFn: ({ signal }) => api.status(signal),
    staleTime: 30_000,
    refetchInterval: 30_000,
    refetchOnWindowFocus: true,
    refetchIntervalInBackground: false,
    retry: 0,
  })

  if (isError) {
    return (
      <footer className="statusbar">
        <span className="item">
          <span className="dot bad" /> Sin conexión con el servidor de FRUTINOVELAS Studio
        </span>
      </footer>
    )
  }

  const comfy = data?.comfyui
  return (
    <footer className="statusbar" aria-label="Estado del sistema">
      <span className="item" title={comfy?.detail ?? comfy?.url}>
        <Server size={13} />
        <span className={`dot ${!data ? '' : comfy?.reachable ? 'ok' : 'bad'}`} />
        ComfyUI{' '}
        {!data
          ? '…'
          : comfy?.reachable
            ? `conectado${comfy.version ? ` · v${comfy.version}` : ''}`
            : `sin conexión (${comfy?.url})`}
      </span>
      <span className="item" title={data?.storage.data_dir}>
        <HardDrive size={13} />
        <span className={`dot ${!data ? '' : data.storage.low_space ? 'warn' : 'ok'}`} />
        {data ? `${gb(data.storage.free_bytes)} libres` : '…'}
      </span>
      <span className="item">
        <Film size={13} />
        <span className={`dot ${!data ? '' : data.ffmpeg ? 'ok' : 'bad'}`} />
        FFmpeg {data ? (data.ffmpeg ? 'listo' : 'no encontrado') : '…'}
      </span>
      <span className="item" style={{ marginLeft: 'auto' }}>
        <Cpu size={13} /> v{data?.app_version ?? '…'}
      </span>
    </footer>
  )
}
