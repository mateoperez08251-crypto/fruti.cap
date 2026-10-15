import type { Scene } from './api'

export const STATUS_LABEL: Record<Scene['status'], string> = {
  sin_imagen: 'Falta imagen',
  sin_prompt: 'Falta prompt',
  lista: 'Lista',
}
