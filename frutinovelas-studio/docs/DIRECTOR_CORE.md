# Núcleo de dirección para cualquier escena

Estas reglas sirven para frutas, personas, animales, objetos y otros personajes, con el estilo
visual solicitado. No fijan una trama, nombres, lugares, gestos ni una emoción obligatoria.
El formato de prompts y las restricciones técnicas siguen dependiendo del modelo conectado.

## Seleccionar contexto

1. Leer la petición actual, las imágenes accesibles y las últimas correcciones explícitas.
2. Elegir `frutinovelas` para las preferencias habituales del proyecto; elegir `general` para
   otros sujetos o estilos. Un preset es un punto de partida y admite cambios expresos.
3. Cargar la continuidad de la historia correspondiente. La heladería de Darío, Bruno y
   Cocardo es un ejemplo opcional: no trasladar sus nombres, objetos o eventos a otras escenas.
4. Separar requisitos universales de dirección, preferencias de producción y hechos del
   capítulo. No convertir una corrección puntual en una regla para todas las novelas.

## Dirección transferible

- Leer el estado inicial real: apoyos, manos ocupadas, orientación, fuentes de luz y profundidad.
- Describir emoción con ojos, cejas, boca, respiración y postura observables.
- Planificar una acción principal con anticipación, trayectoria, contacto, peso y asentamiento.
- Dar a sombras, reflejos, ropa y fondo movimientos derivados de sus causas físicas.
- Mantener sujetos, materiales, escala, voz, objetos y posiciones durante el plano.
- Elegir cámara y ritmo para que la acción sea legible. Dividir cambios incompatibles en planos.
- Preservar literalmente el diálogo aprobado. Separar turnos, escucha, sonidos y música.
- Comprobar imagen, texto y video por separado. No afirmar que una revisión de texto demuestra
  calidad visual, identidad perfecta, sincronía exacta ni un render exitoso.

## Uso por asistentes MCP

Al iniciar una tarea de dirección, consultar `get_directing_guidance` con `task` y `preset`.
Usar `include_example_story=true` únicamente para retomar el arco documentado de la heladería.
Las guías son instrucciones consultables, no entrenamiento ni memoria automática. Este servidor
no registra preferencias nuevas: guardar una preferencia requiere una actualización explícita
del documento correspondiente. El cliente decide si carga recursos, prompts e instrucciones.

Para otros modelos, conservar la dirección creativa y comprobar su sintaxis y capacidades antes
de compilar. El compilador actual solo admite los perfiles H3/Qwen declarados en el repositorio.
