import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, thumbUrl, type Asset, type Character, type CharacterInput } from '../api'
import { AudioUpload } from './AudioUpload'
import { ImageDrop, Lightbox } from './ImageDrop'
import { useToast } from './Toast'

export function CharacterLibrary({ projectId }: { projectId: string }) {
  const qc = useQueryClient()
  const toast = useToast()
  const [editing, setEditing] = useState<Character | null>(null)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [asset, setAsset] = useState<Asset | null>(null)
  const [voiceDescription, setVoiceDescription] = useState('')
  const [voiceAsset, setVoiceAsset] = useState<Asset | null>(null)
  const [imageBusy, setImageBusy] = useState(false)
  const [audioBusy, setAudioBusy] = useState(false)
  const busy = imageBusy || audioBusy
  const [zoom, setZoom] = useState<Asset | null>(null)
  const characters = useQuery({ queryKey: ['characters', projectId], queryFn: ({ signal }) => api.characters(projectId, signal) })
  const save = useMutation({
    mutationFn: () => {
      const data: CharacterInput = { name: name.trim(), description, reference_asset_id: asset!.id }
      if (voiceDescription !== (editing?.voice_description ?? '')) data.voice_description = voiceDescription
      if (voiceAsset?.id !== editing?.voice_asset?.id) data.voice_asset_id = voiceAsset?.id ?? null
      return editing ? api.updateCharacter(editing.id, { ...data, expected_revision: editing.revision }) : api.createCharacter(projectId, data)
    },
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['characters', projectId] }); setEditing(null); setName(''); setDescription(''); setAsset(null); setVoiceDescription(''); setVoiceAsset(null); toast.ok('Personaje guardado') },
    onError: (e) => toast.error(e.message),
  })
  return <section aria-label="Biblioteca de personajes">
    <p className="subtle">Guarda la imagen, el nombre y la voz de cada personaje. Luego podrás elegirlo en las escenas de este proyecto.</p>
    {characters.isError && <p role="alert">No se pudieron cargar los personajes. <button className="btn btn-sm" onClick={() => characters.refetch()}>Reintentar</button></p>}
    <div className="character-grid">{characters.data?.map((c) => <button key={c.id} disabled={save.isPending || busy} className="character-card" onClick={() => { setEditing(c); setName(c.name); setDescription(c.description); setAsset(c.reference_asset); setVoiceDescription(c.voice_description ?? ''); setVoiceAsset(c.voice_asset ?? null) }}>
      <img src={thumbUrl(c.reference_asset.id, 256)} alt={c.name} loading="lazy" /><strong>{c.name}</strong><span className="subtle">{c.voice_asset ? 'Referencia y voz guardadas' : 'Editar referencia y voz'}</span>
    </button>)}</div>
    <form className="character-form" onSubmit={(e) => { e.preventDefault(); if (name.trim() && asset && !busy && !save.isPending) save.mutate() }}>
      <h3>{editing ? `Editar ${editing.name}` : 'Añadir personaje'}</h3>
      <div className="field"><label htmlFor="character-name">Nombre del personaje</label><input id="character-name" className="input" value={name} maxLength={200} required disabled={save.isPending} onChange={(e) => setName(e.target.value)} placeholder="Darío" /></div>
      <div className="field"><label htmlFor="character-description">Rasgos que deben conservarse</label><textarea id="character-description" className="textarea" value={description} maxLength={10000} disabled={save.isPending} onChange={(e) => setDescription(e.target.value)} /></div>
      <ImageDrop id="character-reference" label="Referencia del personaje" asset={asset} disabled={save.isPending} onChange={setAsset} onZoom={setZoom} onBusyChange={setImageBusy} />
      <div className="field character-voice"><label htmlFor="character-voice-description">Voz del personaje</label>
        <textarea id="character-voice-description" className="textarea" value={voiceDescription} maxLength={4000} disabled={save.isPending}
          onChange={(e) => setVoiceDescription(e.target.value)} placeholder="Por ejemplo: voz grave y cálida, acento mexicano, ritmo pausado." />
        <p className="hint">Describe su timbre, acento y forma de hablar para conservarlos entre escenas.</p>
      </div>
      <AudioUpload id="character-voice" label="Muestra de voz del personaje" asset={voiceAsset} disabled={save.isPending}
        onChange={setVoiceAsset} onBusyChange={setAudioBusy} />
      <p className="hint">La muestra permite escuchar su voz. Para cada escena, sube un audio con el diálogo que debe decir: guardar una muestra no genera frases nuevas ni las añade automáticamente.</p>
      <p className="hint">Los cambios de biblioteca no reemplazan las referencias ni las voces guardadas en escenas anteriores.</p>
      <div className="row"><button className="btn btn-primary" disabled={!name.trim() || !asset || busy || save.isPending}>Guardar personaje</button>
        {editing && <button type="button" className="btn" disabled={save.isPending || busy} onClick={() => { setEditing(null); setName(''); setDescription(''); setAsset(null); setVoiceDescription(''); setVoiceAsset(null) }}>Nuevo personaje</button>}</div>
    </form>
    {zoom && <Lightbox asset={zoom} onClose={() => setZoom(null)} />}
  </section>
}
