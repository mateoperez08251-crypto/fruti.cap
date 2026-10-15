import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, thumbUrl, type Asset, type Character } from '../api'
import { ImageDrop, Lightbox } from './ImageDrop'
import { useToast } from './Toast'

export function CharacterLibrary({ projectId }: { projectId: string }) {
  const qc = useQueryClient()
  const toast = useToast()
  const [editing, setEditing] = useState<Character | null>(null)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [asset, setAsset] = useState<Asset | null>(null)
  const [busy, setBusy] = useState(false)
  const [zoom, setZoom] = useState<Asset | null>(null)
  const characters = useQuery({ queryKey: ['characters', projectId], queryFn: ({ signal }) => api.characters(projectId, signal) })
  const save = useMutation({
    mutationFn: () => {
      const data = { name: name.trim(), description, reference_asset_id: asset!.id }
      return editing ? api.updateCharacter(editing.id, { ...data, expected_revision: editing.revision }) : api.createCharacter(projectId, data)
    },
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['characters', projectId] }); setEditing(null); setName(''); setDescription(''); setAsset(null); toast.ok('Personaje guardado') },
    onError: (e) => toast.error(e.message),
  })
  return <section aria-label="Biblioteca de personajes">
    <p className="subtle">Sube la referencia de cada personaje y ponle un nombre. Luego podrás elegirlo en las escenas de este proyecto.</p>
    {characters.isError && <p role="alert">No se pudieron cargar los personajes. <button className="btn btn-sm" onClick={() => characters.refetch()}>Reintentar</button></p>}
    <div className="character-grid">{characters.data?.map((c) => <button key={c.id} disabled={save.isPending || busy} className="character-card" onClick={() => { setEditing(c); setName(c.name); setDescription(c.description); setAsset(c.reference_asset) }}>
      <img src={thumbUrl(c.reference_asset.id, 256)} alt={c.name} loading="lazy" /><strong>{c.name}</strong><span className="subtle">Editar referencia</span>
    </button>)}</div>
    <form className="character-form" onSubmit={(e) => { e.preventDefault(); if (name.trim() && asset && !busy && !save.isPending) save.mutate() }}>
      <h3>{editing ? `Editar ${editing.name}` : 'Añadir personaje'}</h3>
      <div className="field"><label htmlFor="character-name">Nombre del personaje</label><input id="character-name" className="input" value={name} maxLength={200} required disabled={save.isPending} onChange={(e) => setName(e.target.value)} placeholder="Darío" /></div>
      <div className="field"><label htmlFor="character-description">Rasgos que deben conservarse</label><textarea id="character-description" className="textarea" value={description} maxLength={10000} disabled={save.isPending} onChange={(e) => setDescription(e.target.value)} /></div>
      <ImageDrop id="character-reference" label="Referencia del personaje" asset={asset} disabled={save.isPending} onChange={setAsset} onZoom={setZoom} onBusyChange={setBusy} />
      <p className="hint">Los cambios de biblioteca no reemplazan las referencias guardadas en escenas anteriores.</p>
      <div className="row"><button className="btn btn-primary" disabled={!name.trim() || !asset || busy || save.isPending}>Guardar personaje</button>
        {editing && <button type="button" className="btn" disabled={save.isPending || busy} onClick={() => { setEditing(null); setName(''); setDescription(''); setAsset(null) }}>Nuevo personaje</button>}</div>
    </form>
    {zoom && <Lightbox asset={zoom} onClose={() => setZoom(null)} />}
  </section>
}
