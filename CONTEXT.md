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
| `receipt_mailer.py` | Genera el HTML/PDF del comprobante y lo envía por email |
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
| `GMAIL_USER` | Cuenta Gmail para envío de correos |
| `GMAIL_APP_PASS` | App Password de Google (16 caracteres) |
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
    → Genera PDF adjunto
    → Envía por Gmail SMTP
```

### Condiciones para enviar:
1. La venta debe tener un cliente asignado (`customer_id`)
2. El cliente debe existir en Loyverse
3. El cliente debe tener email registrado

---

## Estado actual de los problemas

### ✅ Resuelto
- Webhook de Loyverse configurado y activo (desde UI: `r.loyverse.com/dashboard/#/webhooks`)
- Evento: "Recibo creado o actualizado"
- El servidor recibe y procesa los receipts correctamente
- Lógica de comprobante HTML funciona (diseño fiel al ticket de Loyverse)
- Detección de "Transferencia pendiente" con alerta visual en amarillo

### ❌ Pendiente — PRIORIDAD 1: Envío de email
**Problema**: Railway bloquea conexiones SMTP salientes (puertos 465 y 587).
**Solución acordada**: reemplazar `smtplib` por **Resend** (resend.com).
- Resend funciona vía HTTPS (no SMTP), Railway no lo bloquea
- Plan gratuito: 3.000 emails/mes (suficiente para ~40 ventas/día con cliente)
- Requiere crear cuenta en resend.com y obtener API key (`re_...`)
- Cambio en código: reemplazar el bloque `smtplib.SMTP` en `receipt_mailer.py`

### ❌ Pendiente — PRIORIDAD 2: PDF adjunto
**Problema**: WeasyPrint es incompatible con Python 3.12 en Railway.
- Error: `'super' object has no attribute 'transform'` (WeasyPrint 62.3)
- Error: `PDF.__init__() takes 1 positional argument but 3 were given` (WeasyPrint 60.2)
**Solución a evaluar**: probar `xhtml2pdf` como reemplazo (más liviano, sin dependencias del sistema).
- Ya se intentó pero se descartó temporalmente para resolver primero el email

---

## Diseño del comprobante

Logo: https://res.cloudinary.com/dtbnavw3j/image/upload/v1777608874/Logo_IPDV_k0fstz.png

Estructura visual (fiel al ticket físico de Loyverse):
- Logo + nombre tienda + slogan
- Total destacado grande
- Empleado y TPV
- Cliente con teléfono
- Líneas de productos (nombre, cantidad × precio unitario, total)
- Total
- Método de pago (si es "Transferencia pendiente" → resaltado en naranjo)
- Datos bancarios (siempre visibles, fondo amarillo si hay transferencia pendiente)
- Fecha y número de comprobante

---

## Próximos pasos

1. Crear cuenta en **resend.com** y obtener API key
2. Agregar variable `RESEND_API_KEY` en Railway
3. Actualizar `receipt_mailer.py`: reemplazar bloque SMTP por llamada HTTP a Resend
4. Actualizar `requirements.txt`: agregar `resend` o usar `requests` (ya instalado)
5. Hacer push y probar con venta real
6. Una vez funcionando el email, resolver el PDF con `xhtml2pdf`

---

## Cómo usar este archivo en Claude Code

Al iniciar una sesión nueva en Claude Code, ejecuta:
```
cat CONTEXT.md
```
O simplemente dile a Claude: "Lee el CONTEXT.md y retomemos el proyecto desde ahí."
