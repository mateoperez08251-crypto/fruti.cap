# Dirección de animación H3

Leer [dirección visual](../VISUAL_DIRECTION.md),
[compatibilidad](../MODEL_COMPATIBILITY.md) y
[uso y ejemplos](../PROMPT_STUDIO.md) y
[escenas y duración](../GUIA_ESCENAS_Y_DURACION.md).

1. Inspeccionar las referencias. Identificar postura, apoyos, manos ocupadas, profundidad, fuente de luz y emoción inicial. No inventar un nuevo encuadre en el primer fotograma.
2. Confirmar modo por imágenes reales: una inicial = I2VA; inicial y final = FL2VA. Usar solo los dos perfiles H3 del manifiesto, sin inventar Ref2VA, referencias de voz, ControlNet o upscale 2K disponibles.
3. Describir el estado inicial, la anticipación, trayectoria, contacto, transferencia de peso y reacción final. Seleccionar una acción protagonista; dar a ropa, pelo, ojos, objetos y fondo únicamente el movimiento causal que les corresponda.
4. Traducir emoción a ojos, cejas, labios, mandíbula, respiración y postura. Hacer que la mirada alcance primero a su interlocutor y que la cabeza la siga suavemente. Mantener los labios del oyente en reposo entre reacciones.
5. Precisar cámara fija o un movimiento con dirección, amplitud y velocidad. Distinguir cámara fija al coche de cámara fija al mundo. No combinar un plano estático y un travelling en el mismo intervalo.
6. Separar los eventos del guion con intervalos perceptibles. Por ejemplo, golpe → escucha → pregunta → bocina solo si esos eventos existen en la escena; no añadirlos a otra historia. Sincronizar los sonidos con su contacto o causa visible. Los tiempos orientan al modelo; comprobarlos en el resultado.
7. Asignar (S1), (S2) en orden de primera intervención, no por orden de personajes. Mantener IDs entre planos. Conservar literalmente el diálogo en el idioma solicitado y etiquetarlo; por ejemplo, `<d>[Spanish] …</d>` para español. Escribir identidad, voz, acción y entrega fuera. Personajes silenciosos no reciben voz ni ID.
8. Usar una línea de anclaje y los tres campos oficiales con instrucciones visuales en inglés. Preferir el compilador del estudio para la estructura. Poner diálogo en el plano, ambiente físico en `overall_soundscape` y música en `non_diegetic_music`; usar `N/A` en música si no se pide. Ambiente `N/A` solo para silencio total.
9. Mantener instrucciones positivas en H3: BasicGuider no tiene rama negativa. No añadir una lista de defectos al prompt. Registrar riesgos en notas separadas.
10. Alinear FL2VA al tiempo efectivo `frames/24` y al último plano, usando la fórmula existente `17k+5`. Mantener una trayectoria viable y un breve asentamiento final; dividir cambios grandes en clips cuando convenga.

Para compilar, producir JSON `H3Draft`, ejecutar `frutinovelas-prompts h3` o la herramienta
MCP `prepare_h3_prompt`. El compilador conserva diálogos, ordena campos y valida intervalos;
no observa imágenes ni inventa dirección. El JSON no es un workflow de ComfyUI.

Antes de guardar o generar, revisar con `$fruti-prompt-review`. Dejar claro si solo se preparó
texto o si se comprobó un video real. Mantener los prompts anteriores y sus revisiones.
