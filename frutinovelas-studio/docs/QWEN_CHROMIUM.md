# Qwen controla Chromium para generar imágenes

Qwen recibe una captura actual de la pestaña Flow y sus elementos DOM numerados.
Decide cada clic, selección, carga de referencias, escritura del prompt y descarga.
Playwright ejecuta sus decisiones; no se usa la secuencia fija de controles del bot
anterior ni Windows-MCP. Studio conserva la cola, los prompts y la importación.
La conexión API de Qwen existente se reutiliza; su clave permanece en Studio.

## Arranque

1. Reinicia Studio con `iniciar.cmd` para cargar la API y la interfaz actualizadas.
2. Conserva tu conexión Qwen configurada con `conectar_qwen_flow.cmd` y su servidor
   activo. El modelo debe aceptar imágenes y llamadas a herramientas.
3. En Flow selecciona **Navegador: Chromium (Qwen o bot)** y conecta.
4. Cierra el bot anterior. Abre `iniciar_qwen_chromium.cmd`. Usa el mismo Chromium
   y perfil persistente preparado por My Content, con el mismo bloqueo exclusivo.
   Iniciar este comando autoriza enviar capturas de la pestaña y prompts a tu Qwen.
5. Encola las imágenes guardadas desde Studio. Qwen procesará las imágenes pendientes.
   Para limitarlo a una acción de cola: `iniciar_qwen_chromium.cmd --once`.
6. Si Flow pide acceso, completa el inicio de sesión manualmente. No se automatizan
   contraseñas. Ante estado incierto, revisa el proyecto y concilia en Studio antes
   de reintentar. No borres el diario ni el archivo de bloqueo de un proceso activo.

Esta primera integración controla **imágenes**. Ante un video pendiente se detiene;
los clips conservan su ejecutor existente. No cambia modelos, manifiestos ni H3.
Los botones antiguos de UserFLEX no son el arranque de este recorrido.

## Evitar importar una referencia como resultado

- Antes del envío se registra el inventario de imágenes de la página, incluidas
  las referencias subidas. Qwen debe seleccionar una imagen nueva posterior.
- Qwen ve el resultado y el prompt para decidir cuál descargar. No se elige la
  primera imagen por tamaño ni se confía solamente en una URL nueva.
- La API compara el archivo descargado con la vista seleccionada y con todas las
  referencias. Rechaza una descarga distinta o una copia similar de una referencia,
  incluso redimensionada o recodificada. Conserva el intento para revisión.
- Esta comparación es conservadora, basada en píxeles normalizados: no demuestra
  calidad artística ni correspondencia semántica perfecta. Recortes o superposiciones
  en la miniatura pueden causar rechazos; no se importan automáticamente para evitarlos.

El diario persiste la intención antes de pulsar Generar. Un envío incierto no se
repite. Tras un envío registrado se retoma observación/descarga, nunca generación.
El agente dispone de 100 acciones por recorrido y no ejecuta código inventado por
el modelo. Controla la pestaña Flow, no otros programas del escritorio.

## Verificación

Las pruebas usan decisiones Qwen simuladas, navegador simulado y API real mediante
TestClient. Comprueban prompt literal, importación, rechazo de referencias, descarga
equivocada, credenciales y ausencia de reenvío. Hace falta comprobar una toma real
con el Qwen y la sesión Flow del usuario; los tests no miden calidad ni rendimiento.
