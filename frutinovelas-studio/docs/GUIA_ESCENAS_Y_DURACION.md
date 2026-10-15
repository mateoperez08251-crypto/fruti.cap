# Guía de escenas: duración, diálogo, cámaras y animación

Guía para ChatGPT y otros directores por MCP. Complementa el núcleo de dirección,
la continuidad del capítulo y la skill de animación H3. El guion cuenta lo que
sucede; el prompt describe cómo representarlo y la duración indica el tiempo
solicitado al flujo. No se calcula la duración por tener una o dos imágenes.

## Estimar y guardar los segundos automáticamente

Cuando el usuario pide que ChatGPT asigne la duración, no volver a pedirle que
la escriba manualmente. Leer el guion y el prompt, e inspeccionar las imágenes
reales de inicio **y final** con `inspect_studio_image`. Si falta una, decirlo y
no inventar lo que muestra. Dos imágenes corresponden a FL2VA: describen los
extremos de la misma escena y no obligan a dividirla.

1. Desglosar los eventos: entrada, escucha, frase, pausa, respuesta, movimiento,
   contacto y asentamiento. Conservar literalmente el diálogo aprobado.
2. Estimar el tiempo de cada intervención según palabras, intención y velocidad
   de habla. Como punto de partida editorial, probar 2–3 palabras por segundo;
   bajar el ritmo para duda, emoción o énfasis. Es una heurística del director,
   no una garantía del sintetizador. No acelerar una frase para llenar un límite.
3. Añadir pausas de escucha, respiración y reacciones necesarias. Superponer
   gestos y habla cuando sea natural; no sumar dos veces actividades simultáneas.
4. Comparar los extremos visuales: distancia recorrida, cambio de apoyo, manos,
   objetos, giro de cabeza y encuadre. Reservar anticipación, desplazamiento y
   asentamiento; evitar llegar al estado final antes de terminar el diálogo.
5. Asignar una duración razonada dentro de **4–15 segundos**, límite del perfil
   actual. No elegir siempre 5 o 15 segundos. Si el contenido no cabe con ritmo
   creíble, explicar el conflicto y proponer un ajuste; no recortar el diálogo,
   sustituir imágenes o dividir la escena automáticamente por tener dos imágenes.
6. Guardar `duration_seconds` junto al prompt H3 usando
   `save_scene_preparation`, con la revisión esperada. Mantener los asset IDs de
   inicio y final elegidos. La duración guardada aparece en el editor y el usuario
   puede cambiarla manualmente. Guardar no inicia inferencia.
7. Compilar/revisar con la duración elegida y alinear los intervalos al tiempo
   efectivo devuelto por el compilador (`frames/24`, ajuste `17k+5`). Actualizar
   la revisión al guardar; no sobrescribir cambios posteriores al análisis.

Por ejemplo, «¿Viniste solo?» → pausa → «Sí, nadie me siguió» necesita tiempo
para dos turnos y sus reacciones. El director podría proponer 7 segundos si el
ritmo y los extremos visuales encajan. Es una propuesta editorial, no una medida
del audio generado. Una acción silenciosa puede requerir más tiempo que una frase.

## Diálogo e intercambio de cámaras

- Asignar cada frase a su personaje; el oyente escucha y reacciona con labios en
  reposo. Mantener voz, identidad, ropa, objetos y lado de pantalla.
- Elegir plano conjunto, primer plano o contraplano según la intención. Un corte
  debe tener un motivo: respuesta, revelación, escucha o reacción.
- Si se pide intercambio de cámaras, delimitar planos y turnos sin cruzar el eje
  de miradas. Mantener posiciones y continuidad de manos, objetos y movimiento.
  No añadir cortes por defecto cuando se haya pedido cámara fija.
- Cada intervalo tiene una instrucción de cámara compatible: fija, giro o
  desplazamiento con dirección y velocidad. Evitar varias órdenes contradictorias.
- Reservar tiempo a la reacción; no convertir cada frase corta en un corte nuevo.
  Los tiempos y cambios de cámara del prompt son objetivos: se revisan en el video.

## Movimiento y continuidad

Describir acciones físicas observables con anticipación, trayectoria, contacto,
peso y recuperación. Las imágenes fijan los estados; el prompt debe hacer viable
la transición. El texto orienta un modelo ya entrenado: no le enseña física nueva.

Para enlazar escenas, comprobar mirada, acción pendiente, objetos, luz, encuadre,
ritmo y sonido del final frente al inicio siguiente. Conservar una acción ya
completada; no reiniciarla en el clip siguiente. Unir archivos no resuelve por sí
solo cambios de voz, identidad, saltos visuales ni frases cortadas.

## Revisión manual y modo automático opcional

La revisión manual es inicial. El director prepara los textos y segundos; la
persona revisa imágenes y aprueba las de inicio/final antes de animar. Si el
usuario activa aprobación automática, usar solo el alcance aprobado: imagen, o
imagen y animación, o capítulo completo. No activar ese modo por iniciativa propia.

El capítulo automático utiliza los prompts y las duraciones ya guardados; no
llama a ChatGPT de nuevo para calcularlos durante la cola. Primero ChatGPT prepara
el plan por MCP. Después el worker ejecuta los trabajos en serie y monta el MP4.
Conservar los finales seleccionados; no eliminarlos por generar un nuevo inicio.
La aprobación automática acepta el resultado técnicamente válido sin evaluar su
calidad visual. Un fallo o cambio de revisión detiene la continuación afectada.

El montaje actual concatena los clips y normaliza audio/video. No inventa una
banda sonora continua ni garantiza sincronización o transiciones invisibles.
Probar y observar una escena real antes de evaluar calidad y velocidad GPU.
