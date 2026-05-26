# CONTEXT.md — loyverse-sync / Estado del proyecto

## ¿Qué es este proyecto?
Servidor Flask corriendo en Railway que integra dos sistemas:
1. **PCO (Planning Center Online) → Loyverse**: sincroniza personas/clientes entre ambas plataformas
2. **Loyverse → Email**: envía comprobantes de venta automáticamente al cliente cuando se registra una venta en el POS

---

## Arquitectura

| Archivo | Rol |
|---|---|
| `sync_core.py` | Lógica compartida: llamadas a APIs de PCO y Loyverse, sincronización de clientes |
| `webhook.py` | Servidor Flask con dos endpoints: `/webhook/pco` y `/webhook/loyverse` |
| `receipt_mailer.py` | Genera el HTML del comprobante y lo envía por email via Gmail API |
| `cron.py` | Sincronización masiva programada (independiente del webhook) |
| `register_webhook.py` | Script de uso único para registrar webhooks en Loyverse vía API |
| `Dockerfile` | Imagen Python 3.12 slim, corre gunicorn |
| `requirements.txt` | Dependencias del proyecto |

---

## Infraestructura

- **Servidor**: Railway — `https://loyverse-sync-production-1f02.up.railway.app`
- **Deploy**: automático al hacer `git push` a la rama principal
- **Repositorio**: `https://github.com/itipdv-afk/loyverse-sync` (privado)

---

## Variables de entorno en Railway

| Variable | Descripción |
|---|---|
| `LOYVERSE_TOKEN` | API token de Loyverse (Integraciones → Fichas de acceso → "Loyverse Sync") |
| `PCO_APP_ID` | Application ID de Planning Center |
| `PCO_SECRET` | Secret de Planning Center |
| `WEBHOOK_SECRET` | Secreto para verificar firma de webhooks de PCO |
| `GMAIL_USER` | Cuenta Gmail para envío (`it.ipdv@gmail.com`) |
| `GOOGLE_CLIENT_ID` | Client ID de Google Cloud OAuth2 |
| `GOOGLE_CLIENT_SECRET` | Client Secret de Google Cloud OAuth2 |
| `GOOGLE_REFRESH_TOKEN` | Refresh token OAuth2 (obtenido con `get_token.py`) |
| `STORE_NAME` | Nombre del negocio (ej: "Cafetería IPDV") |
| `STORE_SUBTITLE` | Subtítulo (ej: "Cafetería IPDV") |
| `STORE_SLOGAN` | Slogan que aparece en el comprobante |
| `STORE_LOGO_URL` | URL pública del logo (Cloudinary) |
| `BANK_NAME` | Nombre del banco (ej: "Banco Estado") |
| `BANK_ACCOUNT` | Cuenta bancaria (ej: "Cuenta corriente 2950413") |
| `BANK_RUT` | RUT del negocio (ej: "RUT: 65020958-3") |
| `BANK_HOLDER` | Titular de la cuenta (ej: "Iglesia IPDV") |

---

## Flujo de comprobantes (webhook/loyverse)

```
Venta pagada en iPad (Loyverse POS)
  → Loyverse llama a POST /webhook/loyverse
  → Se extrae customer_id del receipt
  → Si no hay customer_id → omitir
  → GET /customers/{customer_id} en API de Loyverse
  → Si el cliente no tiene email → omitir
  → send_receipt_email(receipt, email, nombre)
    → Genera HTML del comprobante
    → Envía via Gmail API (OAuth2, no SMTP)
```

### Condiciones para enviar:
1. La venta debe tener un cliente asignado (`customer_id`)
2. El cliente debe existir en Loyverse
3. El cliente debe tener email registrado

---

## Estado actual

### ✅ Funcionando
- Webhook de Loyverse configurado y activo (desde UI: `r.loyverse.com/dashboard/#/webhooks`)
- Evento: "Recibo creado o actualizado"
- El servidor recibe y procesa los receipts correctamente
- Envío de email via Gmail API OAuth2 (Railway bloquea SMTP, la API funciona vía HTTPS)
- Diseño del comprobante fiel al ticket de Loyverse
- Método de pago con label correcto (usa campo `name` del payload, no el `type`)
- "Transf. Pendiente" resaltado en naranja con datos bancarios en fondo amarillo
- Nota del cajero aparece cuando existe

### ❌ Pendiente — PDF adjunto
**Problema**: todas las librerías probadas son incompatibles con Python 3.12 slim en Railway:
- WeasyPrint 62.3: `'super' object has no attribute 'transform'`
- WeasyPrint 60.2: `PDF.__init__() takes 1 positional argument but 3 were given`
- xhtml2pdf 0.2.16: requiere `pycairo` que necesita compilador C (no disponible en imagen slim)
**Solución a evaluar**: usar imagen `python:3.12` (no slim) en Dockerfile para tener gcc disponible, o buscar alternativa que no requiera compilación.

### 🔲 Pendiente — campo "order" del receipt
El campo `order` viene con el nombre del cliente cuando el pedido fue guardado antes de finalizar la venta. Hay que definir la lógica de cuándo mostrarlo. El usuario explicará con un ejemplo concreto.

---

## Diseño del comprobante

Logo: https://res.cloudinary.com/dtbnavw3j/image/upload/v1777608874/Logo_IPDV_k0fstz.png

Estructura visual (fiel al ticket físico de Loyverse):
- Logo + nombre tienda + slogan
- Total destacado grande
- Cliente con teléfono
- Nota del cajero (si existe, en itálica)
- Líneas de productos (nombre, cantidad × precio unitario, total)
- Total
- Método de pago — si es "Transf. Pendiente" → resaltado en naranja
- Datos bancarios (siempre visibles, fondo amarillo si hay transferencia pendiente)
- Fecha y número de comprobante

---

## Notas técnicas importantes

### Gmail API OAuth2
- Proyecto en Google Cloud: `loyverse-sync`
- Pantalla de consentimiento en modo prueba — usuario autorizado: `it.ipdv@gmail.com`
- Si el refresh token expira, correr `get_token.py` localmente para obtener uno nuevo
- Warning cosmético en logs: `file_cache is only supported with oauth2client<4.0.0` — no afecta funcionamiento

### Webhook de Loyverse
- Loyverse desactiva el webhook automáticamente si el servidor no responde (WORKER TIMEOUT)
- Para reactivarlo: `r.loyverse.com/dashboard/#/webhooks` → Editar → Activado → Guardar
- El campo `payment_type` siempre viene como `OTHER` para métodos personalizados
- El campo `name` del payment tiene el nombre real ("Transf. Pendiente", "Transferencia", etc.)

---

## Pendientes futuros

### 🔲 Monitor de estado de servicios
Crear un dashboard que muestre en tiempo real el estado de todos los servicios:
- **Loyverse webhook** — verificar si está activo
- **Loyverse API** — conectividad y autenticación
- **PCO API** — conectividad y autenticación
- **Home Assistant** — conectividad
- **Railway** — estado del servidor

Opciones a evaluar:
- Endpoint `/status` en Flask que consulta cada servicio
- Dashboard web simple accesible desde el navegador
- Alerta automática cuando algún servicio falla

---

## Próximos pasos

1. Definir lógica del campo `order` con ejemplo concreto
2. Resolver PDF adjunto (evaluar imagen no-slim en Dockerfile)
3. Implementar monitor de estado de servicios

---

## Cómo usar este archivo en Claude Code

Al iniciar una sesión nueva en Claude Code, ejecuta:
```
cat CONTEXT.md
```
O simplemente dile a Claude: "Lee el CONTEXT.md y retomemos el proyecto desde ahí."
