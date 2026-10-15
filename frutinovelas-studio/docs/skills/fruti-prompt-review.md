# Revisión por evidencia

1. Leer la petición, el prompt guardado, las referencias y la continuidad vigente. Distinguir la intención del resultado observado. Nunca afirmar que se vio un video a partir del prompt únicamente.
2. Ejecutar el comprobador textual del estudio (`/prompts/lint`, CLI o botón **Revisar prompt H3**). Usar además `H3Draft` para validar cronología y hablantes cuando exista un plan estructurado. Un resultado sin errores no certifica calidad visual.
3. Comprobar manualmente: anclajes, perfil real, duración, voz de cada intervención, frase literal, personaje que escucha, manos y objetos, ubicación, orden de sonidos, cámara y luz.
4. Revisar el fotograma antes de animar: ¿la acción ya ocurrió?, ¿hay espacio para moverse?, ¿ambos extremos pertenecen a la misma escena?, ¿se recortará un rostro o una mano? Corregir con Qwen Edit si hace falta.
5. Si existe video, observar inicio, cambios de apoyo, contactos, cortes, intervenciones y final. Escuchar el audio para evaluar palabras, quién habla, silencios, orden y solapamientos. Si no se puede escuchar, dejar ese criterio pendiente.
6. Puntuar 0–2 por identidad, física, expresión, voz/diálogo, audio causal, cámara/luz y continuidad: 0 fallo visible, 1 irregular, 2 conforme. No asignar puntuaciones sin observar. Rechazar un intercambio de voces, identidad u objeto aunque el total sea alto.
7. Cambiar una variable por intento: primero referencia incorrecta, luego sobrecarga de acciones, después voz/audio y cámara. Mantener semilla y configuración cuando sea útil comparar; no prometer reproducción exacta entre hardware/versiones.
8. Conservar original, revisión, parámetros, semilla y observación de cada intento. Repetir solo el plano afectado. No reemplazar modelos ni subir pasos por defecto cuando el problema es un estado inicial contradictorio.

Entregar: errores concretos, corrección propuesta, evidencia observada y pendientes.
Consultar [dirección visual](../VISUAL_DIRECTION.md) y
[matriz de modelos](../MODEL_COMPATIBILITY.md).
