# Voces de personajes y audio por escena

## Una muestra, diálogos nuevos

Guarda **una muestra de voz por personaje** en la biblioteca. En cada escena elige
qué voces intervienen y escribe las frases nuevas en el prompt de animación.
H3 Ref2VA utiliza las muestras para orientar el timbre y la identidad vocal mientras
genera el diálogo de la escena. No hace falta grabar cada frase ni volver a subir
la muestra en cada escena.

La muestra se conserva y se reutiliza como contexto en cada generación. Esto no
entrena permanentemente un modelo por personaje. La fidelidad de voz y la
sincronización labial dependen del resultado de H3 y deben revisarse en un clip real.

## Uso en Studio

1. En la biblioteca del proyecto, crea o edita el personaje. Añade su descripción
   de voz y sube una muestra con una sola voz clara. Un fragmento limpio de **3–5
   segundos** es una preparación práctica; evita música y otras voces mezcladas.
2. Guarda el personaje. Puedes escuchar la muestra desde su ficha.
3. Abre una escena y despliega **Audio y voces**. Selecciona las voces de los
   personajes que hablan, incluidos quienes hablan fuera de pantalla.
4. Escribe el diálogo nuevo en el prompt de animación. Identifica al hablante por
   su nombre; si utilizas el formato H3, conserva `(S1)`, `(S2)`, etc., según el orden
   de primera intervención. Por ejemplo:

   ```text
   integrated_multimodal_description:
   [Shot 1] Darío (S1) turns toward Bruno and says, <d>[Spanish] ¿Dónde estabas?</d>
   Bruno (S2) answers, <d>[Spanish] Fui a buscar el coche.</d>

   overall_soundscape:
   Quiet street ambience.

   non_diegetic_music:
   N/A
   ```

5. Selecciona la imagen inicial y, si corresponde, la final. Guarda y genera la
   escena con la conexión de voces activada. Las palabras de la muestra no son
   el diálogo nuevo: el texto guardado determina lo que debe decir cada personaje.

La biblioteca puede contener más personajes. Una generación admite **hasta tres
voces**. Cada muestra debe durar **2–15 segundos** y la suma de las seleccionadas
no puede superar **15 segundos**. Esas duraciones corresponden al contexto de voz:
una muestra puede durar más que la escena. Las escenas siguen admitiendo 4–15
segundos, con la cuantización de frames existente.

## Activar el flujo en el servidor

La base anterior utiliza pesos FL2VA. Las muestras de timbre requieren añadir el
checkpoint **Ref2VA INT8**, de **20.970.379.616 bytes (20,97 GB)**. Se reutilizan el
encoder y los VAEs del perfil H3 seleccionado; no se añade un servicio de texto a
voz ni una API externa de clonación. En el kit por comandos el complemento requiere
activación expresa. La libreta Colab actualizada lo trae activado para iniciar con
las voces solicitadas; muestra el espacio necesario y permite desactivarlo antes
de ejecutar la descarga.

### RunPod / Linux

Reconstruye el kit desde esta versión del repositorio y vuelve a subirlo al pod,
como explica [RUNPOD.md](RUNPOD.md). Después de descomprimirlo sobre el kit anterior:

```bash
fruti models --voces-personajes si
fruti start --voces-personajes si --reexportar
```

Para una instalación nueva se puede usar `fruti setup --voces-personajes si`.
La opción queda guardada. En Studio vuelve a **Guardar y comprobar** la conexión.

### Colab

Abre la libreta actualizada, conserva `ACTIVAR_VOCES_PERSONAJES = True` en la celda 1
y ejecuta las celdas en orden. El plan de modelos incluye Ref2VA y la exportación
publica el flujo de voces. Después vuelve a comprobar la conexión de Studio.

En ambos casos el kit publica `H3_VOZ_PERSONAJES.api.json` y registra su SHA-256 en
la identidad del gateway. El modelo se descarga desde la revisión H3 ya fijada,
`e5eb578a89295337b8ff433a035929ce0279e0b6`, y se verifica su tamaño y SHA-256:

```text
9255f52b6677845ad238f20dfaafa94727053694127ab7f255c048f0f9365779
```

El perfil de voces siempre usa difusión Ref2VA INT8, incluso si el perfil base de
H3 es el opcional de alta precisión. El manifiesto y la exportación no acreditan
que se haya completado una inferencia real con esas voces.

## Qué se guarda y cómo llega al modelo

| Etapa | Contenido y función |
|---|---|
| Biblioteca | Nombre del personaje, descripción de voz y archivo de muestra |
| Revisión de escena | Personajes seleccionados y copia de sus metadatos y muestras en ese momento |
| Trabajo | Revisión, muestras y hashes, prompt original, prompt efectivo, grafo verificado y conexión congelada |
| Ref2VA | Muestras en `ref_audios`, asociación de cada voz con su personaje y texto nuevo en el prompt |
| Salida | Video y audio generados por H3 y unidos mediante la salida audiovisual nativa |

El grafo reemplaza la difusión FL2VA por Ref2VA y el nodo de condición por
`MiniMaxH3ReferenceToVideo`. Conecta el audio VAE existente y carga las muestras
reales en `ref_audios.ref_audio_0` a `ref_audios.ref_audio_2`. Las etiquetas del
prompt son `<Audio 1>`, `<Audio 2>` y `<Audio 3>` en el mismo orden; Studio las asigna.
El prompt efectivo usa los seis campos oficiales de Ref2VA y define las muestras
como referencias de timbre, sin copiar sus palabras ni su ambiente al diálogo nuevo.
El prompt original y sus diálogos se conservan por separado.

Las imágenes entran como `ref_images` y como anclas `MiniMaxH3AddGuide` en los
fotogramas 0 y -1. Sin imagen final se quita la segunda referencia y su ancla de
la copia del trabajo. Se conservan 576×1024, 24 fps, 20 pasos y la fórmula de duración.
La interfaz sigue mostrando I2VA/FL2VA según sus imágenes; la selección de voces
elige internamente la variante Ref2VA.

Antes de encolar, Studio obtiene el flujo publicado, compara identidad y hash y
vuelve a comprobar revisión y conexión después de la lectura remota. Antes de
subir archivos o inferir, verifica las entradas nativas del servidor. Si falta el
flujo o el nodo compatible, falla con una indicación de actualizar el kit y la
conexión. No simula voz a partir de una descripción sin cargar la muestra.

## Conservación de muestras y versiones

Se valida el contenido real del audio y se guarda su original por SHA-256 en el
directorio de datos. Se prepara una copia WAV PCM para ComfyUI, verificando la
integridad del original antes de usarlo. WAV PCM admite procesamiento con la
biblioteca estándar; los formatos comprimidos admitidos requieren FFmpeg/ffprobe.
El límite de carga predeterminado es 40 MB y 15 segundos por archivo. Los archivos
personales y las credenciales permanecen fuera del repositorio.

Cambiar nombre, descripción o muestra en la biblioteca no modifica las referencias
que una escena ya guardó. Para adoptar una muestra nueva en esa escena, **quita la
voz, guarda la retirada y vuelve a seleccionarla**. Quitar y volver a marcar sin
guardar entre ambas acciones conserva la selección anterior. El historial, los
trabajos ya encolados y la duplicación mantienen sus referencias congeladas.

## Alternativa: diálogo ya grabado para una escena

Si ya tienes el audio exacto de una escena, usa el modo de audio preparado. Permite
hasta ocho clips con personaje opcional y segundo de inicio. Cada clip debe caber
en la duración de la escena y no solaparse con los demás. El inicio se redondea al
fotograma más cercano a 24 fps, igual que en el backend.

Esta alternativa conserva FL2VA/I2VA y conecta `LoadAudio` con
`MiniMaxH3AddGuide` en el momento indicado. El condicionamiento llega a
`BasicGuider` y participa en la inferencia. No exige Ref2VA.

Los dos modos son excluyentes: para pasar de muestras reutilizables a audio ya
preparado, o al revés, quita explícitamente la selección anterior. Studio no elimina
audios silenciosamente. Una muestra menor de dos segundos que ya esté guardada
puede seguir usándose como audio preparado, pero no como referencia Ref2VA.

## API y MCP

`POST /api/v1/assets/audio` recibe el archivo multipart y devuelve sus metadatos.
El personaje guarda `voice_asset_id` y `voice_description`. La preparación de escena
selecciona voces mediante:

```json
{
  "parameters": {
    "voice_character_ids": ["id-dario", "id-bruno"],
    "audio_guides": []
  }
}
```

El servidor deriva `voice_references` desde personajes del mismo proyecto y desde
la revisión anterior confiable. No acepta metadatos de voz inventados por el cliente.
Los personajes nuevos seleccionados deben estar activos y tener una muestra válida.

La herramienta MCP `save_scene_preparation` acepta `voice_character_ids`. Omitirlo
conserva las voces y `[]` las quita. `audio_guides` conserva el contrato de la
alternativa manual. Ambas modalidades respetan `expected_revision` y guardar
preparación no inicia GPU. `list_project_characters` permite consultar muestras y
`get_scene_preparation` devuelve la selección conservada. La guía está disponible
como recurso `frutinovelas://guides/voices`.

## Fuentes primarias y alcance de la verificación

- [Modelo oficial MiniMax-H3: límites de referencias](https://huggingface.co/MiniMaxAI/MiniMax-H3/blob/5d9b308a59ab12e67147f191e184baf704185bd1/README.md).
- [Guía oficial de prompts Ref2VA](https://huggingface.co/MiniMaxAI/MiniMax-H3/blob/5d9b308a59ab12e67147f191e184baf704185bd1/docs/VIDEO_PROMPT_WRITING_GUIDE_ref_en.md): timbre referenciado y diálogo nuevo, etiquetas y seis campos.
- [ComfyUI H3 nativo](https://docs.comfy.org/tutorials/video/minimax/minimax-h3-native) y [referencias con anclas de imágenes](https://docs.comfy.org/tutorials/video/minimax/minimax-h3-multiframe).
- [Implementación de nodos fijada](https://github.com/Comfy-Org/ComfyUI/blob/3541246a9c997f4b8c32f9f88f3c985d02021c79/comfy_extras/nodes_minimax_h3.py).
- [Puntero LFS del checkpoint Ref2VA fijado](https://huggingface.co/Comfy-Org/MiniMax-H3/raw/e5eb578a89295337b8ff433a035929ce0279e0b6/diffusion_models/minimax_h3_ref2va_pruned_int8_convrot.safetensors): tamaño y SHA-256.

Las pruebas del repositorio simulan el servidor de inferencia. Cubren conservación
por personaje, límites de muestras, revisiones, selección MCP, grafo, referencias
reales, identidad, errores del servidor y empaquetado del kit. No descargan pesos
ni miden calidad de voz, sincronización labial, memoria o tiempo de GPU.
