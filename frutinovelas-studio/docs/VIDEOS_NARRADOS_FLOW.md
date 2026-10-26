# Videos narrados con Qwen, Flow y Colab

## Recorrido en Studio

1. Abre **Videos narrados**, elige proyecto y sube el audio (máximo cinco minutos).
   Añade guion o transcripción. El archivo de voz permanece intacto.
2. Elige imágenes estáticas o clips cortos, cantidad de tomas y herramienta
   Storyboard Studio o generación estándar. Añade hasta tres imágenes de
   referencia, con función de identidad o estilo y descripción.
3. **Preparar tomas con Qwen** envía guion y referencias al proveedor guardado
   mediante `conectar_qwen_flow.cmd`. Esta acción redacta prompts, sin generar
   imágenes. También puedes guardar opciones y prompts sin consultar Qwen.
4. Guarda y pulsa **Enviar tomas guardadas a Flow**. La cola congela literalmente
   prompts, referencias, formato y herramienta. Ante una respuesta perdida la
   interfaz reutiliza el identificador; reintenta fallos definitivos desde la cola.
5. El controlador activo o Qwen en Cline ejecuta los trabajos. En modo asistido,
   descarga e importa cada resultado en su trabajo. Seleccionar Storyboard Studio
   no certifica que los controles de esa herramienta estén verificados.
6. **Sincronizar resultados** asocia resultados completados y sus reintentos a
   las tomas. También se consulta cada cinco segundos mientras esta pantalla esté
   visible y no tenga cambios sin guardar.
7. Para animar una imagen después: apruébala en la cola, cambia su toma a clip,
   guarda y pulsa **Animar tomas con imagen aprobada**. No se regenera la imagen.
   La aprobación es manual salvo que elijas automatizarla para el envío completo.
8. Conecta el montador de abajo y pulsa **Exportar MP4**. Studio descarga el
   resultado; conserva originales y audio. URL y clave se guardan cifradas.

## Colab de montaje sin GPU ni ComfyUI

Abre `notebooks/FRUTINOVELAS_Montaje_Colab.ipynb` en Colab, selecciona CPU y ejecuta
sus tres celdas en orden. Instala FFmpeg, Pillow y aiohttp; incluye el servidor y
abre un túnel HTTPS. No descarga modelos generativos.

En Studio despliega **Conectar Colab para unir el video**, copia la URL y clave
de la tercera celda y pulsa **Guardar y comprobar**. No añadas `/v1`: corresponde
a Qwen, no al montador. Mantén Colab abierto hasta descargar el MP4. No compartas
la libreta ejecutada con su clave visible. Los archivos temporales desaparecen
cuando termina el entorno de Colab.

El montaje usa solicitudes normales, sin SSE. Un entorno nuevo cambia la identidad;
guarda y comprueba otra vez antes de enviar o borrar. Sin montador independiente,
se usa la conexión ComfyUI existente con el gateway de montaje actualizado.

En Linux propio, con FFmpeg, FFprobe, Pillow y aiohttp instalados:

```sh
export FRUTINOVELAS_NARRATION_TOKEN='UNA_CLAVE_PRIVADA_DE_AL_MENOS_24_CARACTERES'
python scripts/narrated_server.py --root /ruta/privada/montaje --port 8199
```

Escucha en localhost; un túnel HTTPS permite conectarlo. Todas las rutas exigen
clave. Los recursos se identifican por hash, sin aceptar rutas arbitrarias.

## Sincronización y comprobaciones

### Ver la ventana mientras genera

En Videos narrados y Flow Automation aparece **Ver ventana de Flow**. Abre el
modal, pulsa **Elegir ventana**, selecciona UserFLEX en la pestaña de ventanas
del selector y confirma. Mantén esa ventana abierta, sin minimizarla. El modal
muestra la ventana elegida en vivo; no inicia generaciones ni controla sus botones.
Puedes cerrar el modal y seguir usando el programa sin detener Flow.

La captura se reproduce únicamente en el navegador de esta PC: no se graba ni
se envía a Qwen o al servidor. Al cerrar el modal o abandonar la página se paran
sus pistas. Si cancelas el selector no se inicia la captura. Un permiso que llegue
después de cerrar el modal también se libera inmediatamente.

El selector requiere una acción del usuario en cada nueva captura, según la
[API de captura de pantalla del navegador](https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/getDisplayMedia).
Si no está disponible, abre Studio en Chrome o Edge en esta PC. La captura real
depende del navegador y de la ventana seleccionada; las pruebas automatizadas
comprueban su ciclo de vida con una fuente simulada.

El enlace **Abrir cola Flow** ahora selecciona tanto el proyecto como el capítulo
de las tomas enviadas; evita abrir una selección vacía aunque los trabajos existan.

### Tiempos y montaje

El audio determina la duración final. Los tiempos propuestos por Qwen son
estimaciones, no reconocimiento de voz ni alineación de palabras. Escucha el audio
y ajusta **Corte al segundo**: mueve el final de una toma y el inicio de la
siguiente sin huecos. Las tomas vinculadas a Flow no se dividen ni unen para
conservar su historial.

Un clip se recorta al tiempo de su toma o mantiene su último fotograma si termina
antes; su audio se omite. Las imágenes pueden permanecer quietas o usar movimientos
suaves. Exportación: 24 fps, vertical 576×1024 u horizontal 1024×576. El montaje
admite imágenes y clips mezclados; cada primer lote Flow usa un mismo modo.

Una prueba con FFmpeg real mezcló una imagen y un clip corto con otra pista de
sonido: el resultado conservó duración y audio maestro. Las pruebas también cubren
referencias, persistencia, envío atómico, reintentos, permisos MCP y cifrado.
No se ejecutaron generaciones de pago para comprobar estas funciones.

Falta verificar el recorrido completo en la conversación real Qwen/Cline y
UserFLEX: abrir Storyboard Studio, generar, descargar e importar. El control
nativo pudo leer controles, pero falló al obtener geometría/capturas actuales;
no se inventó un perfil UIA. Instalar MCP no crea por sí solo un worker autónomo.

MCP autenticado de Flow añade `plan_narrated_video`, `send_narrated_to_flow`,
`sync_narrated_flow` y `animate_narrated_images`. El ejecutor literal continúa
exigiendo prompts explícitos, sin redactarlos ni modificarlos con Qwen.

Consulta [Qwen/Cline](CLINE_QWEN_DESKTOP.md) y
[cola, estados y recuperación](FLOW_AUTOMATION.md).
