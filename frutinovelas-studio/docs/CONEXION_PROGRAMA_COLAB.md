# Conectar FRUTINOVELAS Studio con ComfyUI en Colab

El programa (API, interfaz, base de datos y MCP) corre en **tu PC**. Colab solo aporta la
GPU con ComfyUI. Se conectan mediante un **gateway con token** y un **túnel Cloudflare**.

```
PC: FRUTINOVELAS Studio ──HTTPS + token──▶ Cloudflare ──▶ Colab: gateway :8189 ──▶ ComfyUI :8188 (127.0.0.1)
```

## 1. Abrir la libreta

1. Sube `notebooks/FRUTINOVELAS_ComfyUI_Imagenes_H3_Colab.ipynb` a Colab
   (*Archivo → Subir cuaderno*), o ábrela desde GitHub si el repositorio está publicado.
2. *Entorno de ejecución → Cambiar tipo de entorno* → **GPU** (A100 80 GB, H100 o G4) y RAM alta.

## 2. Secretos (🔑 en la barra izquierda de Colab)

Todos son opcionales. Activa «Acceso desde el cuaderno» en los que crees.

| Nombre | Para qué |
|---|---|
| `HF_TOKEN` | Token de lectura de Hugging Face (evita límites de descarga) |
| `FRUTI_GATEWAY_TOKEN` | Token fijo del gateway (≥ 16 caracteres). Si falta, se genera uno y se guarda en Drive |
| `CF_TUNNEL_TOKEN` + `CF_TUNNEL_HOSTNAME` | Túnel con nombre de Cloudflare (URL estable). Usa `MODO_TUNEL = named` |

## 3. Ejecutar las celdas en orden

| Celda | Tiempo aproximado | Qué comprobar |
|---|---|---|
| 1 · Configuración | segundos | Autoriza Drive si lo pide |
| 1.1–1.6 · Kit | segundos | «Flujo H3 escrito sin cambios» |
| 2 · Diagnóstico | segundos | Lee los avisos de VRAM/RAM/disco |
| 3 · Instalación | 3–8 min | Commit `3541246…` |
| 4–5 · Modelos | 10–30 min (≈40 GB) | Todos con «SHA-256 correcto» |
| 6 · Flujos | segundos | |
| 7 · ComfyUI | 1–3 min | «ComfyUI ve todos los modelos» |
| 7B · Exportar API | 1 min | `H3_USUARIO_INICIO_FINAL.api.json` y `H3_USUARIO_SOLO_INICIO.api.json` ✅ |
| 8 · Gateway + túnel | 30 s | «Acceso público verificado con token» |
| 9 · Conexión | segundos | Copia la **URL** |
| 9B · Token | segundos | Marca `MOSTRAR_TOKEN`, copia y **borra la salida** |
| 10 · Pruebas | varios minutos | Marca `PROBAR_H3_SOLO_INICIO` (5 s) para la primera prueba real |
| 11 · Cierre | segundos | Guarda en Drive; marca `DETENER_PROCESOS` al terminar |

No uses «Ejecutar todo» la primera vez: así ves cada aviso a tiempo.

## 4. Comprobar desde el PC

En PowerShell, dentro de `frutinovelas-studio`:

```powershell
$env:FRUTI_COMFY_TOKEN = "PEGA_AQUI_EL_TOKEN"
uv run python scripts/check_colab_connection.py --url https://XXXX.trycloudflare.com
Remove-Item Env:FRUTI_COMFY_TOKEN
```

Comprueba que el servidor responde, que **rechaza** peticiones sin token, muestra la GPU y la versión,
y descarga los flujos API a `workflows/api/` verificando su SHA-256 contra la identidad del servidor.

## 5. En el programa

*Conexiones → ComfyUI* → pega URL y token → **Probar conexión** → **Importar flujo**.
El programa guarda el token cifrado localmente y nunca lo escribe en logs ni en exportaciones.

## Si algo falla

| Síntoma | Causa probable | Solución |
|---|---|---|
| `ERROR de red` o 530/1033 | Colab se desconectó o cambió la URL | Repite celdas 1, 7, 8 y 9 y usa la URL nueva |
| `401` con token | Token mal copiado | Repite la celda 9B |
| La celda 7 dice que faltan modelos | Descarga incompleta | Repite la celda 5 |
| Error de memoria en la celda 10 | GPU con poca VRAM | Usa A100 80 GB/H100/G4 o una duración menor |
| La celda 7B da errores de validación | El ComfyUI no coincide con tu flujo | No se publica ese flujo; revisa el detalle mostrado |

## Límites conocidos

- Un *Quick Tunnel* cambia de URL en cada sesión y no admite SSE; el programa usa WebSocket y consulta del historial.
- Las condiciones de Colab restringen en el plan gratuito el uso principal mediante interfaces web remotas y los proxies remotos.
  Se recomienda plan de pago con saldo de cómputo. La libreta no usa trucos anti-inactividad.
- Mientras la celda 10 no termine con éxito, `estado_compatibilidad` es `pendiente_prueba_real`.
