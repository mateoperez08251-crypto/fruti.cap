# Qwen-Image-2.1 BF16 en Studio y Colab

El perfil predeterminado de imágenes es `qwen21_bf16`. Comparte pesos para texto a
imagen y composición de escenas con una o dos referencias de personajes.

- Difusión: `qwen_image_2.1_bf16.safetensors`.
- Encoder: `qwen3vl_8b_bf16.safetensors`.
- VAE: `qwen_image_2.1_vae_bf16.safetensors`.
- 1152×2048, 9:16 exacto, batch 1; 40 pasos, CFG 1, Euler, scheduler simple,
  denoise 1. Sin Lightning ni reescritura automática del prompt.
- Las referencias se codifican con presupuesto de aproximadamente 1024² píxeles
  por imagen. Son fuentes de identidad para una escena nueva, no un canvas de edición
  local. El latent vacío usa el nodo nativo `EmptyLatentImage` de la plantilla oficial.
- Salida RGB: el alpha del VAE se separa antes de guardar. La imagen maestra queda
  guardada; H3 utiliza su copia preparada a 576×1024 y conserva sus parámetros.

Los tres pesos suman 32.440.124.920 bytes (32,44 GB de disco), además de H3.
El tamaño de archivos no equivale al pico de VRAM. El perfil está orientado a la
RTX PRO 6000 Blackwell de 96 GB; calidad, memoria y tiempo requieren prueba real.
ComfyUI puede descargar modelos de VRAM entre trabajos en la cola serial.

## Actualizar

1. Actualiza Studio con `actualizar.cmd` y reinicia `iniciar.cmd` y el MCP.
2. Abre la libreta actualizada del repositorio. `ACTIVAR_QWEN_21_BF16=True`
   viene seleccionado; ejecuta las celdas en orden. Los pesos anteriores no se borran.
3. Comprueba que se publican `QWEN_21_T2I.api.json` y `QWEN_21_EDIT.api.json`.
4. En Studio, vuelve a **Guardar y comprobar** la conexión ComfyUI.
5. Genera una imagen nueva y revísala. Las imágenes y trabajos anteriores no se
   regeneran. La prueba opcional `PROBAR_QWEN` consume GPU solo si se activa.

RunPod/Linux, con el kit nuevo:

```sh
fruti models --qwen21 si
fruti start --qwen21 si --reexportar
```

El programa prefiere el workflow 2.1 publicado por el servidor. Si no se publica,
admite los flujos 2512/2511 anteriores. Si el hash del flujo 2.1 es incorrecto,
falla sin recurrir silenciosamente al anterior. Los trabajos encolados conservan
el grafo original de su snapshot.

## Regresar al perfil anterior

En Colab desactiva `ACTIVAR_QWEN_21_BF16`, activa `ACTIVAR_QWEN_2512_T2I`
y elige `QWEN_EDIT_2511="fp8mixed"` o `"bf16"`; vuelve a ejecutar desde configuración.
En RunPod usa `fruti models --qwen21 no --qwen-t2i si --qwen-edit fp8mixed`,
y `fruti start --qwen21 no --qwen-t2i si --qwen-edit fp8mixed --reexportar`.
Reconecta Studio. No se requiere migración de base de datos ni borrar pesos o assets.

## Procedencia y límites

Revisión de pesos `Comfy-Org/Qwen-Image-2.1`:
`a8342359c61979b06a8dafb1a47991fe1f30e994`. Los tamaños y SHA-256 LFS se
consultaron el 18 de octubre de 2026 y están fijados en el manifiesto.
Se mantiene ComfyUI v0.40.0, commit `3541246a9c997f4b8c32f9f88f3c985d02021c79`:
su código ya contiene `TextEncodeQwenImage21`, `QwenImage21Cache` y el VAE/modelo.
El constructor compartido evita depender de placeholders, subgrafos de interfaz
o pesos de un ampliador de prompts que no se utiliza.

Fuentes: [modelo Qwen](https://huggingface.co/Qwen/Qwen-Image-2.1),
[pesos ComfyUI](https://huggingface.co/Comfy-Org/Qwen-Image-2.1),
[guía oficial](https://docs.comfy.org/tutorials/image/qwen/qwen-image-2-1),
[plantilla de referencia fijada](https://github.com/Comfy-Org/workflow_templates/blob/59a3b48bf369c5a15f29a1308bae3e279fa15505/templates/image_qwen_image_2_1_image_edit.json).
Licencia de los pesos: Qwen Research; no asumir las condiciones Apache de modelos previos.
Las pruebas automatizadas verifican contratos y cola con un servidor simulado;
no demuestran identidad visual, calidad generativa ni consumo real de GPU.
