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
| `STORE_SUBTITLE` | Subtítulo (ej: "Iglesia Presbiteriana del Valle de Lonquén") |
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
    → Detecta si es SALE o REFUND
    → Genera HTML del comprobante según tipo
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
- Nota del cajero aparece cuando existe (en itálica)
- Asunto del correo: "Recibo de Cafetería IPDV"
- Reembolsos (`receipt_type: REFUND`) tratados diferente:
  - Asunto: "Reembolso de Cafetería IPDV"
  - Banner rojo con número del comprobante original (`refund_for`)
  - Etiqueta del monto dice "Reembolso" en lugar de "Total"
  - Sin bloque de datos bancarios
- PDF eliminado del flujo (incompatible con Python 3.12 slim, descartado)

### 🔲 Pendiente — campo "order" del receipt
El campo `order` viene con el nombre del cliente cuando el pedido fue guardado antes de finalizar la venta. Hay que definir la lógica de cuándo mostrarlo. El usuario explicará con un ejemplo concreto.

---

## Diseño del comprobante

Logo: https://res.cloudinary.com/dtbnavw3j/image/upload/v1777608874/Logo_IPDV_k0fstz.png

### Venta normal (SALE)
- Logo + nombre tienda + subtítulo + slogan
- Total destacado grande
- Cliente con teléfono
- Nota del cajero (si existe, en itálica)
- Líneas de productos (nombre, cantidad × precio unitario, total)
- Total
- Método de pago — si es "Transf. Pendiente" → resaltado en naranja
- Datos bancarios (fondo amarillo si hay transferencia pendiente, gris si no)
- Fecha y número de comprobante

### Reembolso (REFUND)
- Igual que venta normal pero:
- Banner rojo: "Reembolso — Anulación del comprobante N° X"
- Etiqueta del monto: "Reembolso"
- Sin datos bancarios

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
- El campo `receipt_type` puede ser `SALE` o `REFUND`
- El campo `refund_for` contiene el número del comprobante original cuando es reembolso

---

## Pendientes futuros

### 🔲 Panel de administración web (PRIORIDAD)
Interfaz simple accesible desde el navegador para:
- Editar datos de la tienda (nombre, slogan, logo)
- Editar datos bancarios (banco, cuenta, RUT, titular)
- Ver estado de los servicios (Loyverse webhook, APIs, Railway)
- Ver log de últimos comprobantes enviados

### 🔲 Monitor de estado de servicios
- **Loyverse webhook** — verificar si está activo
- **Loyverse API** — conectividad y autenticación
- **PCO API** — conectividad y autenticación
- **Home Assistant** — conectividad
- **Railway** — estado del servidor

### 🔲 Campo "order" del receipt
Definir lógica de cuándo mostrar el campo `order` con ejemplo concreto.

---

## Próximos pasos

1. **Panel de administración web** (PRIORIDAD)
2. Definir lógica del campo `order` con ejemplo concreto
3. Implementar monitor de estado de servicios

---

## Cómo usar este archivo en Claude Code

Al iniciar una sesión nueva en Claude Code, ejecuta:
```
cat CONTEXT.md
```
O simplemente dile a Claude: "Lee el CONTEXT.md y retomemos el proyecto desde ahí."
