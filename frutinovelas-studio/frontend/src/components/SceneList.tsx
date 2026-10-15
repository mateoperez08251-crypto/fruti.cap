import {
  closestCenter,
  DndContext,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
} from '@dnd-kit/core'
import {
  arrayMove,
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { ArrowRight, ChevronDown, ChevronUp, GripVertical, ImageOff } from 'lucide-react'
import { thumbUrl, type Scene } from '../api'
import { STATUS_LABEL } from '../labels'

function Thumb({ id }: { id: string | undefined }) {
  if (!id)
    return (
      <span className="thumb empty">
        <ImageOff size={12} />
      </span>
    )
  return <img className="thumb" src={thumbUrl(id, 128)} alt="" loading="lazy" draggable={false} />
}

type CardProps = {
  scene: Scene
  index: number
  total: number
  selected: boolean
  onSelect: () => void
  onMove: (delta: -1 | 1) => void
}

function SceneCard({ scene, index, total, selected, onSelect, onMove }: CardProps) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id: scene.id })
  const style = { transform: CSS.Transform.toString(transform), transition }

  return (
    <div
      ref={setNodeRef}
      style={style}
      className={`scene-card ${selected ? 'selected' : ''} ${isDragging ? 'dragging' : ''}`}
      onClick={onSelect}
      onKeyDown={(e) => e.key === 'Enter' && e.target === e.currentTarget && onSelect()}
      tabIndex={0}
      aria-current={selected}
      id={`scene-card-${index + 1}`}
    >
      <button
        className="drag-handle"
        {...attributes}
        {...listeners}
        aria-label={`Arrastrar escena ${index + 1} para reordenar`}
        onClick={(e) => e.stopPropagation()}
      >
        <GripVertical size={16} />
      </button>
      <span className="scene-num">{index + 1}</span>
      <div className="scene-info">
        <span className="scene-title">{scene.title || `Escena ${index + 1}`}</span>
        <div className="scene-meta">
          <span className={`chip chip-dot ${scene.status === 'lista' ? 'chip-ready' : 'chip-warn'}`}>
            {STATUS_LABEL[scene.status]}
          </span>
          <span className="chip">{scene.duration_seconds.toLocaleString('es')} s</span>
          {scene.mode && <span className="chip chip-mode">{scene.mode}</span>}
        </div>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <div className="thumbs">
          <Thumb id={scene.start_asset?.id} />
          {scene.end_asset && (
            <>
              <ArrowRight size={10} className="arrow" />
              <Thumb id={scene.end_asset.id} />
            </>
          )}
        </div>
        <div style={{ display: 'flex', flexDirection: 'column' }}>
          <button
            className="btn btn-ghost btn-icon btn-sm"
            style={{ width: 22, height: 22 }}
            disabled={index === 0}
            aria-label="Subir escena"
            title="Subir"
            onClick={(e) => {
              e.stopPropagation()
              onMove(-1)
            }}
          >
            <ChevronUp size={14} />
          </button>
          <button
            className="btn btn-ghost btn-icon btn-sm"
            style={{ width: 22, height: 22 }}
            disabled={index === total - 1}
            aria-label="Bajar escena"
            title="Bajar"
            onClick={(e) => {
              e.stopPropagation()
              onMove(1)
            }}
          >
            <ChevronDown size={14} />
          </button>
        </div>
      </div>
    </div>
  )
}

type ListProps = {
  scenes: Scene[]
  selectedId: string | null
  onSelect: (id: string) => void
  onReorder: (ids: string[]) => void
}

export function SceneList({ scenes, selectedId, onSelect, onReorder }: ListProps) {
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  )
  const ids = scenes.map((s) => s.id)

  const onDragEnd = ({ active, over }: DragEndEvent) => {
    if (!over || active.id === over.id) return
    const from = ids.indexOf(String(active.id))
    const to = ids.indexOf(String(over.id))
    onReorder(arrayMove(ids, from, to))
  }

  const move = (index: number, delta: -1 | 1) => onReorder(arrayMove(ids, index, index + delta))

  return (
    <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={onDragEnd}>
      <SortableContext items={ids} strategy={verticalListSortingStrategy}>
        {scenes.map((s, i) => (
          <SceneCard
            key={s.id}
            scene={s}
            index={i}
            total={scenes.length}
            selected={s.id === selectedId}
            onSelect={() => onSelect(s.id)}
            onMove={(d) => move(i, d)}
          />
        ))}
      </SortableContext>
    </DndContext>
  )
}
