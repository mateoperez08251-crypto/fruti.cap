import { Trash2 } from 'lucide-react'
import type { Asset, Character } from '../api'
import type { AudioDraft } from '../audio'
import { AudioPreview, AudioUpload } from './AudioUpload'

type Props = {
  guides: AudioDraft[]
  characters: Character[]
  errors: string[]
  disabled?: boolean
  onUpdate: (index: number, data: Partial<AudioDraft>) => void
  onRemove: (index: number) => void
  onAdd: (asset: Asset) => void
  onBusyChange: (busy: boolean) => void
}

export function SceneAudio({ guides, characters, errors, disabled, onUpdate, onRemove, onAdd, onBusyChange }: Props) {
  return <>
    <p className="hint">Sube el diálogo de esta escena con la voz del personaje. H3 usará el audio como guía de voz y ritmo desde el segundo que indiques. Puedes elegir también a quien habla fuera de cámara.</p>
    <p className="hint">El resultado se genera de nuevo y puede variar. La muestra de la biblioteca no crea ni añade automáticamente los diálogos de la escena.</p>
    <div className="scene-audio-list">{guides.map((g, index) => {
      const character = characters.find((c) => c.id === g.characterId)
      return <div key={index} className="scene-audio-item" aria-label={`Audio ${index + 1}`}>
        <div className="audio-upload-heading"><strong>Audio {index + 1}</strong>
          <button type="button" className="btn btn-ghost btn-sm btn-danger" disabled={disabled}
            aria-label={`Quitar audio ${index + 1}`} onClick={() => onRemove(index)}><Trash2 size={14} /> Quitar</button></div>
        {g.asset && <AudioPreview asset={g.asset} label={`Escuchar audio ${index + 1}`} />}
        <div className="row">
          <div className="field"><label htmlFor={`scene-audio-character-${index}`}>Personaje del audio {index + 1}</label>
            <select id={`scene-audio-character-${index}`} className="select" value={g.characterId} disabled={disabled}
              onChange={(e) => {
                const selected = characters.find((c) => c.id === e.target.value)
                onUpdate(index, { characterId: e.target.value, characterName: selected?.name ?? '', voiceDescription: selected?.voice_description ?? '' })
              }}>
              <option value="">Sin asignar</option>
              {characters.map((c) => <option key={c.id} value={c.id}>
                {c.id === g.characterId && g.characterName && g.characterName !== c.name ? `${g.characterName} · guardado` : c.name}
              </option>)}
              {g.characterId && !character && <option value={g.characterId}>{g.characterName || 'Personaje guardado'} · guardado</option>}
            </select>
          </div>
          <div className="field audio-start"><label htmlFor={`scene-audio-start-${index}`}>Inicio del audio {index + 1} (segundos)</label>
            <input id={`scene-audio-start-${index}`} className="input" inputMode="decimal" value={g.start} disabled={disabled}
              onChange={(e) => onUpdate(index, { start: e.target.value })} />
          </div>
        </div>
        {g.voiceDescription && <p className="hint audio-voice-description">Voz: {g.voiceDescription}</p>}
      </div>
    })}</div>
    <AudioUpload id="scene-audio-upload" label="Diálogo de la escena" asset={null} disabled={disabled || guides.length >= 8}
      onChange={(asset) => { if (asset) onAdd(asset) }} onBusyChange={onBusyChange} />
    <p className="hint">{guides.length}/8 audios · hasta 15 s cada uno y dentro de la duración de la escena. Los inicios se ajustan al fotograma más cercano. Las intervenciones deben ir una después de otra.</p>
    {errors.length > 0 && <div className="notice warn" role="alert"><div>{errors.map((error) => <p key={error} style={{ margin: '4px 0' }}>{error}</p>)}</div></div>}
  </>
}
