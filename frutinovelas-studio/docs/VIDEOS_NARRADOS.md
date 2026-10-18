# Videos narrados con pequeñas animaciones

Modo independiente de los capítulos H3. La narración completa determina la duración del video, hasta cinco minutos. Cada imagen mantiene una animación ligera de zoom o desplazamiento; no se genera un video H3 por cada segundo.

## Desde la interfaz
1. Abre **Videos narrados** en el menú lateral, selecciona proyecto y sube WAV, MP3, M4A u otro audio compatible.
2. Pega opcionalmente una transcripción o un guion (esta primera versión no transcribe ni sintetiza voces automáticamente).
3. Crea el video, divide las tomas, escribe la acción y el prompt visual para cada toma.
4. Asigna imágenes de tu PC o recursos de la biblioteca mediante MCP; elige zoom, paneo o imagen fija.
5. Guarda y pulsa **Exportar MP4**. FFmpeg monta las imágenes y coloca la narración completa como audio principal.

## MCP para ChatGPT / Claude
- list_narrated_videos(project_id): obtiene los videos del proyecto.
- get_narrated_video(video_id): lee la duración y la cronología.
- save_narrated_storyboard(video_id, expected_revision, shots, transcript?): guarda prompts, IDs de imagen, movimientos y marcas de tiempo; no invoca GPU.
- render_narrated_video(video_id, expected_revision): exporta solamente tras petición explícita.

Cada toma contiene start_seconds, end_seconds, text, image_prompt, image_asset_id y motion. Los valores de motion son zoom_in, zoom_out, pan_left, pan_right o still.

Los prompts de imagen no activan su generación automáticamente. Puedes usar la preparación de prompts Qwen y la importación MCP ya disponibles en Studio, y después asignar los IDs reales de las imágenes.

## Alcance técnico
- Hasta 300 segundos y 90 tomas; la cronología completa debe cubrir el audio sin huecos ni solapamientos.
- Se requiere FFmpeg y FFprobe. El tamaño máximo de subida sigue la configuración local.
- Las imágenes se cargan por ID registrado dentro del directorio de datos. No se permiten rutas arbitrarias.
- La exportación es local; el MP4 usa H.264 y AAC. No requiere inferencia H3.
- La alineación es manual o asistida a partir de una transcripción aportada; no se afirma reconocer el contenido hablado a partir del audio.
- El proceso se ejecuta en un hilo local: no garantiza que continúe tras apagar Studio. Ante interrupción, reiniciar la exportación después de recuperar el trabajo.

## Comprobaciones
uv run pytest tests/test_narrated.py
npm --prefix frontend run build
npm --prefix frontend run lint