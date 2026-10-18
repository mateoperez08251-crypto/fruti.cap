import type { Asset, AudioGuide, AudioGuideInput, Character, VoiceReference } from './api'

export const audioSeconds = (seconds: number) => seconds.toLocaleString('es', { maximumFractionDigits: 3 })

export type AudioDraft = {
  assetId: string
  asset: Asset | null
  characterId: string
  characterName: string
  voiceDescription: string
  start: string
}

export const audioDrafts = (guides: AudioGuide[] = []): AudioDraft[] => guides.map((g) => ({
  assetId: g.asset_id, asset: g.asset ?? null, characterId: g.character_id ?? '',
  characterName: g.character_name ?? '', voiceDescription: g.voice_description ?? '', start: String(g.start_seconds),
}))

export const audioInputs = (guides: AudioDraft[]): AudioGuideInput[] => guides.map((g) => ({
  asset_id: g.assetId, character_id: g.characterId || null, start_seconds: Number(g.start.replace(',', '.')),
}))

// La API usa round() de Python: los empates de medio fotograma van al entero par.
const frameStart = (seconds: number) => {
  const frames = seconds * 24
  const lower = Math.floor(frames)
  const rounded = frames - lower === 0.5 ? lower + lower % 2 : Math.round(frames)
  return rounded / 24
}

export function nextAudioStart(guides: AudioDraft[]): string {
  const lastEnd = guides.reduce((end, g) => {
    const start = Number(g.start.replace(',', '.'))
    return Number.isFinite(start) ? Math.max(end, frameStart(start) + (g.asset?.duration_seconds ?? 0)) : end
  }, 0)
  return String(Number((Math.ceil(lastEnd * 24) / 24).toFixed(3)))
}

export function audioErrors(guides: AudioDraft[], duration: number): string[] {
  const errors: string[] = []
  if (guides.length > 8) errors.push('Esta escena admite hasta 8 audios.')
  const intervals: { start: number; end: number; number: number }[] = []
  guides.forEach((g, i) => {
    const start = Number(g.start.replace(',', '.'))
    const clipDuration = g.asset?.duration_seconds
    if (!g.start.trim() || !Number.isFinite(start) || start < 0) {
      errors.push(`Audio ${i + 1}: introduce un inicio de 0 segundos o más.`)
      return
    }
    if (clipDuration == null || !Number.isFinite(clipDuration) || clipDuration <= 0 || clipDuration > 15) {
      errors.push(`Audio ${i + 1}: vuelve a subir un audio válido de hasta 15 segundos para comprobar su duración.`)
      return
    }
    const adjustedStart = frameStart(start)
    const end = adjustedStart + clipDuration
    if (Number.isFinite(duration) && end > duration + 0.000001) {
      errors.push(`Audio ${i + 1}: termina en ${audioSeconds(end)} s y la escena dura ${audioSeconds(duration)} s. Adelanta su inicio, usa un audio más corto o aumenta la duración de la escena.`)
    }
    intervals.push({ start: adjustedStart, end, number: i + 1 })
  })
  intervals.sort((a, b) => a.start - b.start)
  for (let i = 1; i < intervals.length; i++) {
    const earlier = intervals.slice(0, i).find((previous) => previous.end > intervals[i].start + 0.000001)
    if (earlier) errors.push(`Los audios ${earlier.number} y ${intervals[i].number} se superponen. Ajusta sus inicios para que cada intervención tenga su turno.`)
  }
  return errors
}

export type VoiceDraft = {
  characterId: string
  characterName: string
  voiceDescription: string
  assetId: string
  asset: Asset | null
}

export const voiceDrafts = (ids: string[] = [], references: VoiceReference[] = []): VoiceDraft[] => ids.map((id) => {
  const reference = references.find((voice) => voice.character_id === id)
  return {
    characterId: id, characterName: reference?.character_name ?? 'Personaje guardado',
    voiceDescription: reference?.voice_description ?? '', assetId: reference?.asset_id ?? '', asset: reference?.asset ?? null,
  }
})

export const voiceFromCharacter = (character: Character): VoiceDraft => ({
  characterId: character.id, characterName: character.name, voiceDescription: character.voice_description ?? '',
  assetId: character.voice_asset?.id ?? '', asset: character.voice_asset ?? null,
})

export function voiceSampleError(asset: Asset | null): string | null {
  if (!asset || asset.kind !== 'audio') return 'Añade una muestra de voz en la biblioteca de personajes.'
  const seconds = asset.duration_seconds
  if (seconds == null || !Number.isFinite(seconds) || seconds < 2 || seconds > 15) {
    return 'La muestra de voz debe durar entre 2 y 15 segundos.'
  }
  return null
}

export function voiceErrors(voices: VoiceDraft[]): string[] {
  const errors: string[] = []
  if (voices.length > 3) errors.push('Selecciona como máximo 3 voces para esta escena.')
  let total = 0
  for (const voice of voices) {
    const error = voiceSampleError(voice.asset)
    if (error) errors.push(`${voice.characterName}: ${error}`)
    else total += voice.asset!.duration_seconds!
  }
  if (total > 15 + 0.000001) errors.push(`Las muestras seleccionadas suman ${audioSeconds(total)} s. El máximo conjunto es 15 s: selecciona menos voces o usa muestras más cortas.`)
  return errors
}

