# Fotogramas preparados para animar

Leer [compatibilidad](../MODEL_COMPATIBILITY.md) y
[dirección visual](../VISUAL_DIRECTION.md).
Abrir la imagen antes de afirmar qué contiene; si no es accesible, describir requisitos pendientes.

1. Usar `qwen2512_t2i` para una imagen nueva. Usar `qwen_edit2511_fp8mixed` o el perfil BF16 ya declarado para editar una referencia existente. No usar etiquetas H3 en Qwen.
2. Escribir sujeto y ubicación, encuadre, distancia, profundidad, pose inicial, expresión observable, luz y materiales. Mantener el estilo solicitado; en el preset frutinovelas, personajes 3D estilizados con un entorno de perspectiva y materiales creíbles.
3. Elegir una fuente principal motivada: ventana, sol o lámpara. Describir dirección, dureza, color, relleno y superficies que reciben sombra. Mantener sombra de contacto bajo zapatos, objetos y manos apoyadas.
4. Preparar el estado anterior a la acción: cono aún en la mano del vendedor si va a entregarlo; palma cerca del volante si va a tocar bocina; apoyo visible para un paso. Dejar espacio para la trayectoria.
5. Diferenciar emoción de pose: una preocupación requiere cejas internas elevadas/tensas, labios contenidos y mirada evasiva; una sonrisa nerviosa tiene asimetría y tensión, sin ojos de alegría. No añadir sudor salvo que corresponda al guion.
6. En EDIT, enumerar cambios y atributos que se preservan. Corregir lo mínimo; contrastar el resultado con la referencia. No garantizar identidad perfecta por usar la misma semilla.
7. Preparar inicio y final en el mismo canvas. Con el perfil actual, revisar el recorte 576×1024 y proteger rostro, manos, pies y objetos; conservar originales. La resolución de Qwen no cambia automáticamente la salida H3.
8. En imágenes nuevas, mantener superficies sin rótulos si no hay texto solicitado. En edición, preservar los rótulos existentes salvo cambio expreso. Si hay texto solicitado, copiar cada cadena exacta por separado.

Entregar prompt positivo, cambios/preservaciones en edición y lista breve de comprobaciones visuales.
Para salida estructurada, usar `ImageDraft` de `src/frutinovelas/prompts.py` y el ejemplo
`examples/prompts/qwen_edit_cocardo.json` del estudio. Preparar el prompt no ejecuta Qwen en la app.
No cambiar pasos, CFG, LoRAs o cuantización sin inspeccionar el flujo realmente cargado.
