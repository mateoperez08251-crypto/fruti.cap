# Investigación y decisiones de compatibilidad

Consultado el 15 de octubre de 2026. Se contrastaron documentación de autores, integración
ComfyUI y código de `fruti.cap`. La propuesta se concentra en los perfiles ya declarados.

## Fuentes primarias

| Fuente | Qué se verificó | Aplicación |
|---|---|---|
| [MiniMax H3, ficha del autor](https://huggingface.co/MiniMaxAI/MiniMax-H3) | FL2VA/Ref2VA, audio, duración, módulos alojados | No presentar Context-IR ni regeneración 2K como funciones locales existentes |
| [Guía base MiniMax](https://huggingface.co/MiniMaxAI/MiniMax-H3/blob/main/docs/VIDEO_PROMPT_WRITING_GUIDE_base_en.md) | Anclajes, campos, planos, diálogo y voz en off | Compilador específico I2VA/FL2VA |
| [Skill oficial h3-prompt-writing](https://github.com/MiniMax-AI/MiniMax-H3/blob/main/skills/h3-prompt-writing/SKILL.md) | Skill portable para diferentes modos | Adaptación al modo realmente disponible |
| [Skill oficial 3d-animation-short-generator](https://github.com/MiniMax-AI/MiniMax-H3/blob/main/skills/3d-animation-short-generator/SKILL.md) | Requiere MiniMax Hub y canvas | No copiarla como si ejecutara este proyecto |
| [ComfyUI: guía H3](https://docs.comfy.org/tutorials/video/minimax/minimax-h3) | Integración y muestreo | Conservar el perfil equilibrado de la app |
| [ComfyUI: prompts H3](https://docs.comfy.org/tutorials/video/minimax/minimax-h3-prompt-guide) | Cuantización temporal, BasicGuider y audio | Advertencias sobre negativos, referencias y duración |
| [Comfy-Org: pesos H3](https://huggingface.co/Comfy-Org/MiniMax-H3) | Componentes y precisiones | Contrastar contra el manifiesto local |
| [Qwen-Image-2512](https://huggingface.co/Qwen/Qwen-Image-2512) | Generación, detalle y realismo | Composición y pose inicial |
| [Qwen-Image-Edit-2511](https://huggingface.co/Qwen/Qwen-Image-Edit-2511) | Edición e identidad | Cambios concretos y atributos a preservar |
| [Qwen 2512 Lightning](https://huggingface.co/lightx2v/Qwen-Image-2512-Lightning) | Adaptadores de imagen | Revisar la rama activa del flujo |
| [Qwen Edit 2511 Lightning](https://huggingface.co/lightx2v/Qwen-Image-Edit-2511-Lightning) | LoRA de cuatro pasos y pesos fusionados | No aplicar sus pasos a H3 ni duplicar LoRA |

Se leyeron las skills oficiales mediante GitHub. SHA del archivo `h3-prompt-writing/SKILL.md`:
`b6d9b2839384a588763a9c24315225dd8ce19d56`; SHA de `3d-animation-short-generator/SKILL.md`:
`6ddc1102a8c353b4be4c939444b24f62e5552cde`. Las URLs con `main` pueden cambiar.

## Decisiones

Crear cuatro skills propias: continuidad, imagen, animación H3 y revisión. Orientan la
redacción visual en inglés y mantienen diálogo literal. No copian herramientas de MiniMax
Hub ni instalan modelos adicionales. La estructura H3 sigue el contrato de sus autores.

La estimación de tres palabras por segundo es una **heurística editorial**, no un límite
oficial. Las reglas de actuación, física y revisión son propuestas aplicadas a los fallos
relatados por el usuario. No garantizan identidad, sombras, voces o sincronía perfectas.

## Alcance verificado

Se verifica software y estructura de prompts, no calidad de inferencia. No se ha llamado al
pod, descargado pesos, usado una clave MiniMax/OpenAI ni generado clips en esta entrega.
Los ejemplos son planes para referencias que deben inspeccionarse. La conexión de GitHub
no conecta automáticamente el MCP local a ChatGPT.
