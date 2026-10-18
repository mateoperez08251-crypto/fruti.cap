# Compatibilidad comprobada en el código

Revisión: 17 de octubre de 2026. Base del cambio de voces: `84af42e4da879cb19796822c5343c51dabe2580f`.
El manifiesto declara archivos; no demuestra que estén cargados en un servidor activo.
No se han descargado pesos ni ejecutado GPU en esta entrega.

| Perfil del repositorio | Función | Preparación de prompt | Ejecución existente |
|---|---|---|---|
| `h3_balanced_default` | H3 FL2VA INT8, encoder NVFP4 AWQ, video VAE INT8, audio FP32 | I2VA o FL2VA | App individual y kit remoto |
| `h3_quality_bf16_optional` | H3 FL2VA BF16, encoder BF16, video VAE FP16, audio FP32 | Misma estructura I2VA/FL2VA | Perfil opcional del kit; requiere recursos y conexión compatibles |
| `h3_voice_references` | Complemento Ref2VA INT8; reutiliza encoder y VAEs del perfil H3 elegido | Convierte el prompt efectivo a seis campos Ref2VA, conservando los diálogos | Kit opcional + app: muestras por personaje y anclas de inicio/final; requiere flujo publicado y hash verificado |
| `qwen2512_t2i` | Qwen-Image-2512 FP8 + LoRA Lightning declarada | Descripción de un fotograma | Kit y app: generación de imágenes desde texto, con flujo publicado y hash verificado |
| `qwen_edit2511_fp8mixed` | Qwen-Image-Edit-2511 FP8 mixed + Lightning | Cambios concretos y atributos a preservar | Kit y app: una o dos referencias de personajes reales |
| `qwen_edit2511_bf16` | Difusión Qwen Edit BF16; conserva encoder FP8 | Mismo prompt de edición | Perfil opcional del kit, no significa que todo el pipeline sea BF16 |

Seleccionar un perfil en un borrador de prompt **no cambia los modelos del servidor**.
El programa sigue usando el workflow de la conexión comprobada. Verificar la identidad
remota y sus archivos antes de atribuir un resultado a un perfil.

## Contrato del flujo H3 actual

- Canvas fijo: 576×1024, 9:16; 24 fps; 20 pasos; `res_multistep` + `simple`.
- Entrada inicial en nodo 1; final opcional en nodo 30; prompt en nodo 9.
- `BasicGuider` tiene una sola condición; `negative_prompt` es `null` en el perfil.
- I2VA elimina el enlace `last_frame` y el nodo 30. FL2VA usa ambos extremos.
- Ref2VA se habilita con el complemento opcional de voces descrito abajo. No se
  cargan ControlNet Union, embeddings ni H3-Regenerate-2K. Un manifiesto no acredita
  que estos modelos estén instalados o que una inferencia haya pasado.
- El encoder Qwen3-VL de H3 no es un chatbot de planificación al que el programa haga preguntas.
  El nuevo compilador organiza instrucciones ya redactadas; no es H3-Context-IR.

## Voz reutilizable por personaje

Con `--voces-personajes si` (Colab: `ACTIVAR_VOCES_PERSONAJES=True`), el kit descarga
`minimax_h3_ref2va_pruned_int8_convrot.safetensors` desde la revisión H3 ya fijada:
20.970.379.616 bytes, SHA-256
`9255f52b6677845ad238f20dfaafa94727053694127ab7f255c048f0f9365779`.
Publica `H3_VOZ_PERSONAJES.api.json` tras validarlo contra el servidor y registra su
hash en la identidad. La variante usa `MiniMaxH3ReferenceToVideo`, el audio VAE
existente y los mismos parámetros de sampling. Incluso con el perfil base de alta
precisión, la difusión de esta variante de voces es **Ref2VA INT8**.

Las muestras van a `ref_audios.ref_audio_0` a `ref_audios.ref_audio_2`, como contexto
de timbre. El prompt indica el diálogo nuevo y asocia cada `<Audio N>` con el
personaje correspondiente. Las imágenes se conectan a `ref_images` y a
`MiniMaxH3AddGuide` en los fotogramas 0 y -1 para conservar los extremos.
Solo inicio elimina la segunda referencia y su ancla de la copia de trabajo.
`Scene.mode` sigue reflejando las imágenes disponibles (I2VA/FL2VA); la selección
de voces determina internamente el grafo Ref2VA.

Límites: hasta tres muestras, 2–15 segundos cada una, suma ≤15 segundos. La muestra
no se coloca en la línea temporal y puede durar más que la escena solicitada.
La biblioteca puede guardar más personajes; cada generación selecciona hasta tres.
El audio sigue siendo generado: las pruebas de código no acreditan fidelidad de voz
ni sincronización labial en GPU. Ver [Voces y audios](AUDIO_Y_VOCES.md), que incluye
las fuentes primarias del contrato y las instrucciones de activación.

## Audio guía por escena (alternativa)

La aplicación puede ampliar la copia de trabajo del flujo H3 con `LoadAudio` y
`MiniMaxH3AddGuide`, disponibles en el commit de ComfyUI fijado por el kit.
Cada guía recibe el audio VAE existente y un tiempo de inicio; su condicionamiento
alimenta `BasicGuider`. Se consultan los nodos del servidor antes de enviar una
inferencia con audio. Los modelos y parámetros del perfil se conservan.

Esto admite audios de diálogo proporcionados para la escena. Se usa de forma
excluyente con las muestras Ref2VA; no incorpora un motor TTS. El prompt literal se conserva, y las
indicaciones temporales del hablante forman parte del prompt efectivo del trabajo.
Ver [Voces y audios](AUDIO_Y_VOCES.md) para el contrato y la fuente primaria.

## Duración real

El código existente y el compilador aplican:

```python
frames = max(5, round(seconds * 24))
frames += (5 - frames % 17) % 17
effective_seconds = frames / 24
```

| Solicitud | Frames | Duración efectiva |
|---|---:|---:|
| 4 s | 107 | 4,4583 s |
| 5 s | 124 | 5,1667 s |
| 10 s | 243 | 10,1250 s |
| 15 s | 362 | 15,0833 s |

Se solicita 4–15 s; la cuantización puede sobrepasar ligeramente ese número. Los beats
del compilador caben en el tiempo solicitado; el tramo extra permite asentamiento. El anclaje
FL2VA usa el efectivo con dos decimales, siguiendo la guía de MiniMax. No modificar fps
para forzar un clip de 3 s: recortar en montaje una generación compatible.

## Imágenes y velocidad

La app conserva originales y prepara copias RGB con ajuste central al canvas. Los recortes
pueden quitar manos o pies: inspeccionarlos antes de inferencia. Preparar los dos extremos
ya en 9:16 reduce ese riesgo. El nodo H3 original trata inicio/final de forma diferente;
por eso conviene entregar copias ya preparadas, no depender de su ajuste interno.

Las LoRAs Lightning del manifiesto corresponden a **Qwen**, no convierten H3 en un modelo
de cuatro pasos. No copiar los 40/50 pasos de ejemplos de Qwen base a un flujo Lightning
sin revisar qué rama está activa. Mantener el workflow exportado y validado.
INT8, FP8 y BF16 describen precisión, no una garantía de identidad o calidad.

Fuentes oficiales y alcance de la investigación: [PROMPT_RESEARCH.md](PROMPT_RESEARCH.md).

La integración Qwen de personajes compone un latent vacío 576×1024 y conecta las referencias reales sin recortarlas. Se conservan los demás parámetros del flujo exportado; ver [contrato y validación](PERSONAJES_Y_ESCENAS.md).
