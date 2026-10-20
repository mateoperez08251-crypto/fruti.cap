import { useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../api'
import { useToast } from './Toast'

export function RecoverQueue() {
  const qc = useQueryClient()
  const toast = useToast()
  const recover = useMutation({
    mutationFn: api.recoverQueue,
    onSuccess: (result) => {
      for (const key of ['generations', 'image-generations', 'chapter-renders']) {
        qc.invalidateQueries({ queryKey: [key] })
      }
      if (result.status === 'busy') toast.ok('El worker está procesando un trabajo. Reintenta en unos segundos.')
      else if (result.status === 'unverified' || result.status === 'connection_changed') toast.error('No se pudo verificar ComfyUI. Guarda y comprueba la conexión antes de reintentar.')
      else toast.ok(result.recovered.length ? 'Registros interrumpidos liberados. Ya puedes reintentar la generación.' : 'Cola comprobada. Los trabajos activos o recientes se conservan.')
    },
    onError: (error: Error) => toast.error(error.message),
  })
  return <button className="btn btn-sm" disabled={recover.isPending} onClick={() => recover.mutate()}>
    {recover.isPending ? 'Comprobando cola…' : 'Recuperar cola'}
  </button>
}
