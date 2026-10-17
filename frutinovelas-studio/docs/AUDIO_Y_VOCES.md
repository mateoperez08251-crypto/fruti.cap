# Voces de personajes y audio por escena

Cada personaje puede guardar una descripción de su voz y un audio de referencia.
Cada escena puede incorporar hasta ocho audios cortos, asociados a un personaje
o a una voz fuera de pantalla, con su segundo de inicio.

El audio de escena entra en el flujo H3 como guía durante la generación. Una muestra
guardada en la biblioteca no genera automáticamente frases nuevas ni se repite en
todas las escenas.

## Uso en Studio

1. Abre la biblioteca del proyecto. Al crear o editar un personaje, añade su
   descripción de voz y, si lo necesitas, una muestra que puedas volver a escuchar.
2. Abre una escena y despliega Audio y voces. Sube el diálogo de esa escena con
   la voz que deseas conservar. Asócialo al personaje y ajusta el segundo de inicio.
3. Revisa la duración de cada audio. Los diálogos deben caber en la escena y sus
   intervalos no deben solaparse.
4. Guarda la escena. El audio y la identidad elegida quedan en esa revisión.
5. Genera mediante la conexión ComfyUI ya configurada. Studio verifica las entradas
   de audio del servidor antes de enviar la inferencia.

Conserva en el prompt el diálogo literal, el personaje que habla y el momento
correspondiente. La dirección adicional derivada de los audios se guarda por
separado del prompt original para dirigir la generación.

La entrada de audio puede orientar palabras, timbre y ritmo; el resultado continúa
siendo generado por H3. La identidad perceptual de la voz y la sincronización labial
deben comprobarse escuchando y viendo un clip real. Esta función no incorpora un
motor de texto a voz ni un servicio de clonación.

## Archivos y tiempos

- Se valida el contenido real del archivo y se conserva su original en el directorio
  de datos, siguiendo el almacenamiento por SHA-256 de las imágenes.
- WAV PCM se puede procesar con la biblioteca estándar. Los formatos comprimidos
  admitidos requieren FFmpeg/ffprobe disponibles en el programa.
- El audio de entrada puede durar hasta 15 segundos y debe caber en la duración
  de la escena. H3 sigue admitiendo escenas de 4 a 15 segundos.
- Studio prepara WAV PCM para subirlo al servidor. Los archivos personales no se
  guardan en el repositorio.
- El tiempo inicial se lleva al fotograma más cercano a 24 fps. La validación tiene
  en cuenta esa posición al comprobar solapamientos y final de la escena.
- Sustituir la muestra de voz de un personaje no modifica una revisión ni un trabajo
  que ya capturó sus referencias.

## Modificación del flujo H3 actual

Se conserva la base I2VA/FL2VA verificada de la conexión. Para cada audio de la escena,
Studio añade al grafo que enviará a ComfyUI:

- LoadAudio, que abre el WAV subido.
- MiniMaxH3AddGuide, que recibe el audio, el audio VAE del nodo 8, el latent
  audiovisual del nodo 9 y el fotograma inicial.
- El condicionamiento positivo pasa por las guías en orden temporal y llega al
  BasicGuider del nodo 15.

El sampler conserva el latent audiovisual original del nodo 9. El audio generado
sale por VAEDecodeAudio y llega a CreateVideo con las imágenes. Por eso la entrada
de audio participa en la inferencia y no se limita a sustituir la pista después.

Los modelos, canvas 576×1024, 24 fps y 20 pasos permanecen en el perfil conectado.
El grafo base publicado sigue verificándose por hash; la incorporación de las guías
se hace a la copia de trabajo con los audios de la revisión solicitada.

Antes de usar audio se consultan las especificaciones de LoadAudio y
MiniMaxH3AddGuide del servidor. Si faltan o son incompatibles, la generación se
rechaza con un motivo concreto. Una escena sin audios mantiene el recorrido previo.

### Fuente primaria de compatibilidad

El kit fija ComfyUI v0.40.0, commit
3541246a9c997f4b8c32f9f88f3c985d02021c79. En ese commit,
[MiniMaxH3AddGuide](https://github.com/Comfy-Org/ComfyUI/blob/3541246a9c997f4b8c32f9f88f3c985d02021c79/comfy_extras/nodes_minimax_h3.py#L166-L240)
admite audio, audio_vae, latent, positive y frame_idx. Devuelve solamente
condicionamiento positivo. Las guías sucesivas se pueden encadenar.

Este uso no agrega MiniMaxH3ReferenceToVideo ni sus etiquetas de referencias de
audio. La asociación con un personaje se expresa en la dirección textual del
trabajo; un character_id por sí solo no es una entrada que interprete H3.

## API y MCP

Subida: POST /api/v1/assets/audio, multipart con el campo file. La respuesta es
un Asset con kind=audio y duration_seconds.

Crear o modificar un personaje admite voice_description y voice_asset_id.
La respuesta incluye voice_asset para escuchar y revisar la muestra guardada.
Omitir los campos de voz en un cliente anterior conserva la voz existente.

Al guardar una escena, parameters.audio_guides contiene una lista con:

| Campo | Significado |
|---|---|
| asset_id | Audio que ya se subió al almacenamiento de Studio. |
| character_id | Personaje del mismo proyecto; null para audio sin personaje asignado. |
| start_seconds | Segundo de inicio dentro de la escena. |

El servidor valida estos valores y añade sus propios metadatos del archivo y del
personaje. No confía en nombres, hashes ni duraciones suministrados por el cliente.
Cada revisión y cada trabajo conservan la selección correspondiente.

La herramienta MCP save_scene_preparation acepta el mismo audio_guides. Omitir
el argumento conserva lo guardado; enviar [] quita los audios de la nueva revisión.
Leer personajes o una escena devuelve también sus voces y audios. Subir un archivo
se realiza desde Studio o mediante el endpoint multipart; preparar una escena por
MCP no inicia una generación.

## Comprobación

Las pruebas nuevas cubren validación de audio, almacenamiento, migración,
conservación de revisiones, asociación de personajes, tiempos, subida al gateway
y enlaces del grafo que se envía. El servidor de inferencia se simula en las pruebas:
su resultado no mide calidad de voz ni rendimiento GPU.

Para la verificación completa del repositorio, seguir los comandos del README.
