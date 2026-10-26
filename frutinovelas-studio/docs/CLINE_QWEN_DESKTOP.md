# Qwen en Cline: escritorio Windows y Studio

Configuración preparada el 23 de octubre de 2026. El modelo sigue alojado en Colab;
Cline ejecuta las herramientas en Windows y envía al proveedor los resultados que
incluya en sus consultas. No se publica el escritorio mediante Cloudflare.

## Conectar

Ejecuta `conectar_qwen_escritorio.cmd` desde la carpeta de Studio. El instalador:

1. Comprueba por MCP stdio el catálogo de Windows-MCP 0.8.5 y el de Studio.
2. Añade `windows-desktop-qwen` y `frutinovelas-studio` al archivo MCP de Cline.
3. Conserva otras entradas, crea una copia del archivo anterior y rechaza colisiones.
4. Mantiene proveedor, clave, modelo y preferencias de aprobación de Cline.

La ruta predeterminada es `~/.cline/data/settings/cline_mcp_settings.json`.
Para otra ruta, ejecuta `scripts/configurar_qwen_escritorio.py --settings RUTA --install`
con el Python del entorno de Studio. El botón **Configure MCP Servers** de Cline
permite comprobar el archivo que usa una instalación concreta. Recarga sus servidores
después de guardar la configuración.

Windows-MCP se habilita con su catálogo completo por petición explícita del usuario:
incluye teclado, ratón, capturas, archivos, consola, procesos y registro. No queda
aislado a UserFLEX. No se añade aprobación automática de herramientas. Se desactiva
la telemetría del conector y se fija su versión; no se modifican las dependencias
ni los modelos de ComfyUI, H3 o Qwen-Image.

## Primer recorrido con Flow y Storyboard Studio

### Puente local para el error SSE de Quick Tunnel

Se añadió a Studio un puente OpenAI compatible:
`http://127.0.0.1:8765/api/v1/qwen/v1`. Cline usa esa URL, la misma clave Qwen y
el modelo exacto `qwen38-cline:latest`. Mantén Studio abierto. El puente consulta
el túnel sin streaming y entrega la respuesta terminada como eventos SSE locales;
no muestra tokens en tiempo real, no cambia texto ni ejecuta llamadas a herramientas.
No abre el escritorio ni la API en Internet.

`conectar_qwen_puente.cmd` actualiza únicamente el proveedor Qwen existente y los
IDs de modelo de sus modos Plan/Act, con copias previas y comprobación de cambios
concurrentes. No reemplaza otro proveedor ni modifica claves. En esta sesión se
actualizaron las dos configuraciones y se comprobó HTTP 200 del catálogo local.
Las pruebas del adaptador cubren texto literal, llamadas a herramientas, uso,
autenticación y errores sin reintento. Falta la conversación real desde Cline.

Recarga el proveedor en Cline. Cuando cambie la URL pública de Colab, actualiza la
conexión cifrada mediante `conectar_qwen_flow.cmd`; Cline puede conservar la URL
local. Si Studio usa un token API global adicional, configura ese token como
clave de Cline y envía la clave Qwen con su cabecera personalizada `X-Qwen-Key`.

### Ejecutar los trabajos

Mantén la API de Studio abierta para usar sus herramientas de proyectos y cola.
En Cline, pide a Qwen observar primero UserFLEX, identificar la pantalla y localizar
**Storyboard Studio**. Confirmar la existencia de la herramienta en la interfaz es
distinto de haber probado su generación, animación o descarga.

Para trabajar sobre prompts ya preparados:

- Obtén proyecto, capítulo, escena y revisión reales desde Studio.
- Encola con las herramientas `flow_*`, enviando el texto explícito y literal.
- En modo asistido, conserva el trabajo en `awaiting_import` mientras se realiza
  la generación externa. El agente UIA solo puede usarse con perfil verificado.
- Observa una pantalla actual antes de actuar y comprueba cada cambio de modo.
  Las coordenadas de una imagen antigua no son posiciones actuales del escritorio.
- Pega el prompt original del trabajo; no lo reconstruyas mediante la visión.
- Comprueba modo imagen/video, referencias, duración y herramienta antes del envío.
- Una respuesta perdida o un estado incierto exige comprobar el historial de Flow;
  no vuelvas a pulsar Generar para averiguar si el primer envío funcionó.
- Descarga e importa en el trabajo correspondiente. Reintenta desde Studio cuando
  el intento anterior esté definitivamente terminado, conservando su historial.
- La aprobación de una imagen y el paso a animación siguen la decisión del usuario.

Las acciones de Windows-MCP no se escriben automáticamente en el diario de Flow.
Qwen/Cline debe coordinarse con los trabajos de Studio; instalar los conectores
no convierte todavía ese recorrido en un worker autónomo y durable.

Studio dispone ahora, por separado, del botón **Ejecutar esta toma con Qwen**.
Ese ejecutor sí coordina la toma guardada, el control MCP y la importación con
estado persistente. No depende de una conversación en Cline. Consulta
[ejecución directa, autorización y límites](FLOW_AUTOMATION.md#ejecutar-una-toma-directamente-con-qwen).
Todavía requiere comprobar la primera generación real en la ventana del usuario.

Para el modo **guion y audio**, el usuario sí ha solicitado que Qwen redacte
los prompts desde el guion. Esa autorización pertenece a ese modo; no cambia el
contrato literal del ejecutor MCP. Videos narrados enlaza preparación con Qwen,
cola Flow, sincronización de resultados y montaje remoto. El controlador/Cline
todavía debe ejecutar los botones reales de Flow.
Consulta [el recorrido y la libreta CPU](VIDEOS_NARRADOS_FLOW.md).

## Alcance comprobado

- Instalación de Windows-MCP 0.8.5 y conexión stdio: 20 herramientas publicadas.
- MCP de Studio por stdio: 69 herramientas comprobadas, incluidas cuatro para
  videos narrados.
- Configuración Cline guardada con copia anterior; pruebas de mezcla y conservación.
- No se invocaron herramientas de escritorio durante esa comprobación de catálogos.
- Falta comprobar desde la conversación real de Cline que Qwen use los conectores,
  abra Storyboard Studio y complete generación, reintento, animación e importación.

Fuentes: [Windows-MCP](https://github.com/CursorTouch/Windows-MCP),
[configuración MCP de Cline](https://github.com/cline/cline/blob/main/docs/mcp/mcp-overview.mdx).
