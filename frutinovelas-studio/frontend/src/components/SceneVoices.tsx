import type { Character } from '../api'
import { audioSeconds, voiceFromCharacter, voiceSampleError, type VoiceDraft } from '../audio'
import { AudioPreview } from './AudioUpload'

type Props = {
  voices: VoiceDraft[]
  available: Character[]
  savedVoices: VoiceDraft[]
  errors: string[]
  disabled?: boolean
  hasPreparedAudio: boolean
  loading: boolean
  onToggle: (voice: VoiceDraft) => void
  onClearAudio: () => void
}

export function SceneVoices({ voices, available, savedVoices, errors, disabled, hasPreparedAudio, loading, onToggle, onClearAudio }: Props) {
  const candidates = available.map((character) => voices.find((voice) => voice.characterId === character.id)
    ?? savedVoices.find((voice) => voice.characterId === character.id) ?? voiceFromCharacter(character))
  const missing = [...voices, ...savedVoices.filter((voice) => !voices.some((selected) => selected.characterId === voice.characterId))]
    .filter((voice) => !available.some((character) => character.id === voice.characterId))
  return <section className="scene-voices" aria-label="Voces de los personajes">
    <h3>Voces de los personajes</h3>
    <p className="hint">Sube una muestra de 2–15 segundos una sola vez por personaje en la biblioteca. Selecciona aquí sus voces y escribe los nuevos diálogos en el prompt de animación. H3 usará las muestras para generar lo que dicen en esta escena.</p>
    <p className="hint">Puedes seleccionar también a quien habla fuera de cámara. Las muestras se reutilizan como referencia en cada generación; no entrenan permanentemente una voz y el resultado puede variar.</p>
    {hasPreparedAudio && <div className="notice"><div>
      <p style={{ marginTop: 0 }}>Esta escena tiene audios preparados. Quita esos audios para elegir voces de la biblioteca.</p>
      <button type="button" className="btn btn-sm" disabled={disabled} onClick={onClearAudio}>Quitar audios preparados para elegir voces</button>
    </div></div>}
    {loading && <p className="hint" role="status">Cargando voces de la biblioteca…</p>}
    {!loading && !available.length && !voices.length && <p className="hint">Añade personajes con su muestra de voz en la biblioteca del proyecto.</p>}
    <div className="voice-grid">{[...candidates, ...missing].map((voice) => {
      const selected = voices.some((chosen) => chosen.characterId === voice.characterId)
      const error = voiceSampleError(voice.asset)
      const currentName = available.find((character) => character.id === voice.characterId)?.name
      const saved = selected && (!currentName || voice.characterName !== currentName)
      return <article key={voice.characterId} className={`voice-card ${selected ? 'selected' : ''}`}>
        <label className="voice-choice">
          <input type="checkbox" checked={selected} aria-label={`Usar voz de ${voice.characterName}`}
            disabled={disabled || (!selected && (hasPreparedAudio || voices.length >= 3 || Boolean(error)))} onChange={() => onToggle(voice)} />
          <strong>{voice.characterName}{saved ? ' · guardado' : ''}</strong>
          {voice.asset?.duration_seconds != null && <span className="chip">{audioSeconds(voice.asset.duration_seconds)} s</span>}
        </label>
        {error && <p className="hint generation-error">{error}</p>}
        {selected && voice.asset && <AudioPreview asset={voice.asset} label={`Escuchar muestra de ${voice.characterName}`} />}
        {selected && voice.voiceDescription && <p className="hint audio-voice-description">Voz: {voice.voiceDescription}</p>}
      </article>
    })}</div>
    <p className="hint">{voices.length}/3 voces · cada muestra debe durar de 2 a 15 s y todas juntas, como máximo 15 s. La duración de las muestras es independiente de la duración de la escena.</p>
    {savedVoices.length > 0 && <p className="hint">Las voces guardadas conservan su muestra aunque cambie la biblioteca. Para actualizar una muestra en esta escena, quita esa voz, guarda y vuelve a seleccionarla.</p>}
    {errors.length > 0 && <div className="notice warn" role="alert"><div>{errors.map((error) => <p key={error} style={{ margin: '4px 0' }}>{error}</p>)}</div></div>}
  </section>
}
