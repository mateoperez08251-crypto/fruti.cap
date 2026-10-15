# FRUTINOVELAS en RunPod

Alternativa a Colab: un pod de RunPod con GPU ejecuta ComfyUI y el programa del PC se conecta
a él por el **proxy HTTPS de RunPod** a través del gateway con token. No hace falta Cloudflare.

```
PC: FRUTINOVELAS Studio ──HTTPS + token──▶ https://<POD_ID>-8189.proxy.runpod.net ──▶ gateway :8189 ──▶ ComfyUI 127.0.0.1:8188
```

Libreta: `notebooks/FRUTINOVELAS_ComfyUI_Imagenes_H3_RunPod.ipynb`. Tiene la misma lógica que la de Colab,
generada desde la misma fuente (`scripts/build_colab_notebook.py`).

## 1. Secretos en RunPod (opcional pero recomendado)

En la consola de RunPod → **Secrets** crea:

| Secreto | Valor |
|---|---|
| `hf_token` | Token de lectura de Hugging Face |
| `fruti_gateway_token` | Token largo y aleatorio (≥ 32 caracteres) para el gateway |

Para generar un token en PowerShell:

```powershell
-join ((48..57) + (65..90) + (97..122) | Get-Random -Count 40 | ForEach-Object {[char]$_})
```

Si no defines `fruti_gateway_token`, la libreta genera uno y lo guarda en `/workspace/FRUTINOVELAS/secrets/`.

## 2. Crear el pod

| Ajuste | Valor |
|---|---|
| Plantilla | Oficial **Runpod PyTorch** reciente (CUDA 12.8 o superior), con JupyterLab |
| GPU | Recomendado ≥ 80 GB de VRAM (H100, H200, A100 80 GB, RTX PRO 6000). Requisito real no verificado |
| Disco del contenedor | ≥ 40 GB |
| Disco de volumen (`/workspace`) | ≥ 80 GB solo H3 · ≥ 150 GB con Qwen · ≥ 200 GB con perfil BF16 |
| Expose HTTP Ports | `8888,8189` |
| Expose TCP Ports | ninguno necesario (22 si quieres SSH) |
| Variables de entorno | `HF_TOKEN` = `{{ RUNPOD_SECRET_hf_token }}` |
| | `FRUTI_GATEWAY_TOKEN` = `{{ RUNPOD_SECRET_fruti_gateway_token }}` |

> [!CAUTION]
> **No expongas el puerto 8188.** ComfyUI no tiene autenticación; la libreta lo deja en `127.0.0.1`
> y solo publica el gateway (8189), que exige token. Evita las plantillas de ComfyUI ya hechas que exponen 8188.

Si usas un **volumen de red**, los modelos (≈40 GB) se conservan aunque borres el pod, y puedes usarlos en pods nuevos
del mismo centro de datos.

## 3. Ejecutar la libreta

1. En el pod: **Connect → Jupyter Lab** (puerto 8888).
2. Arrastra `FRUTINOVELAS_ComfyUI_Imagenes_H3_RunPod.ipynb` al explorador de archivos, dentro de `/workspace`.
3. Ábrela y ejecuta las celdas en orden (o *Run → Run All Cells*: las pruebas y la parada vienen desactivadas).
   - Para cambiar el perfil o el modo de acceso, edita las primeras líneas de la celda 1.
4. Celda 8: debe terminar con «Acceso público verificado (sin token → 401, con token → 200)».
5. Celda 9: copia la URL `https://<POD_ID>-8189.proxy.runpod.net`.
6. Celda 9B: pon `MOSTRAR_TOKEN = True`, copia el token y borra la salida.
7. Celda 10: pon `PROBAR_H3_SOLO_INICIO = True` para la primera prueba real (5 s).

## 4. Conectar desde el PC

```powershell
$env:FRUTI_COMFY_TOKEN = "PEGA_AQUI_EL_TOKEN"
uv run python scripts/check_colab_connection.py --url https://IDDELPOD-8189.proxy.runpod.net
Remove-Item Env:FRUTI_COMFY_TOKEN
```

El script funciona igual para Colab y RunPod. Después, en el programa: *Conexiones → ComfyUI* → URL + token →
**Probar conexión** → **Importar flujo**.

## 5. Detener, reanudar y costes

| Acción | Qué se conserva | Qué hacer al volver |
|---|---|---|
| Detener el pod (*Stop*) | Todo `/workspace`: modelos, ComfyUI, token, flujos | Ejecutar celdas 1–9; los paquetes pip se reinstalan solos |
| Borrar el pod (*Terminate*) | Nada, salvo que uses volumen de red | Crear pod nuevo y repetir todo; con volumen de red los modelos ya están |

- Un pod detenido no cobra GPU, pero **el disco de volumen sigue cobrando**.
- La URL del proxy depende del ID del pod: se mantiene al detener y reanudar el mismo pod y cambia si creas otro.
- Antes de parar, ejecuta la celda 11 (copia de la sesión en `/workspace/FRUTINOVELAS/sesiones/`).

## Diferencias con Colab

| | Colab | RunPod |
|---|---|---|
| Acceso público | Cloudflare Quick Tunnel (URL nueva cada sesión) | Proxy de RunPod (URL estable por pod) |
| Persistencia | Google Drive (opcional) | `/workspace` (volumen) |
| Secretos | Panel 🔑 de Colab | Secrets de RunPod como variables de entorno |
| Gateway escucha en | `127.0.0.1` (el túnel conecta en local) | `0.0.0.0` (lo exige el proxy), siempre con token |
| Alternativas | `named` (túnel Cloudflare con nombre) | `quick` o `named` también disponibles en la celda 1 |

## Problemas frecuentes

| Síntoma | Solución |
|---|---|
| Celda 8: «no responde. Expose HTTP Ports…» | *Edit Pod* → añade `8189` a HTTP Ports. El pod se reinicia: vuelve a la celda 1 |
| `RUNPOD_POD_ID no está definido` | No estás en un pod de RunPod: usa `MODO_TUNEL = "quick"` |
| `No existe /workspace` | Crea el pod con disco de volumen o volumen de red |
| Error de memoria en la celda 10 | Usa una GPU con más VRAM |
| 502 al descargar resultados grandes | Repite; el proxy corta peticiones que tardan más de ~100 s sin enviar datos |
| Las variables `HF_TOKEN`/`FRUTI_GATEWAY_TOKEN` no aparecen | Revisa la sintaxis `{{ RUNPOD_SECRET_nombre }}` y reinicia el pod |
