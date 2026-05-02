# ipdv-hub-integration

Hub central de integraciones de **Iglesia IPDV**.

Conecta los sistemas de la iglesia usando **Planning Center Online (PCO) como fuente de verdad**, propagando los datos hacia los demás servicios de forma automática y confiable.

---

## Principio fundamental

> **PCO es la única fuente de verdad.**
>
> Ningún sistema externo modifica datos de personas directamente.
> Todo cambio se origina en PCO y se propaga automáticamente hacia los demás sistemas a través de este hub.

Esto significa:
- Si una persona es agregada, editada o desactivada en PCO → el hub lo propaga.
- Si un campo personalizado cambia en PCO (ej. "Acceso al portón") → el hub actualiza los sistemas afectados.
- Los sistemas destino (Loyverse, Home Assistant, etc.) son consumidores de datos, nunca productores.

---

## Integraciones activas

| Integración | Dirección | Descripción |
|---|---|---|
| PCO → Loyverse | unidireccional | Sincroniza miembros activos como clientes en el punto de venta |
| PCO → Home Assistant | unidireccional | Gestiona la lista de autorizados para el portón de acceso |
| Loyverse → Email | unidireccional | Envía comprobantes de venta automáticamente por email |

---

## Arquitectura

```
PCO (fuente de verdad)
  │
  ├── Webhook (person.created / person.updated)
  │     │
  │     ├──► Loyverse        — crear/actualizar cliente
  │     └──► Home Assistant  — actualizar lista portón
  │
  └── Cron (sincronización periódica completa)
        │
        ├──► Loyverse        — reconciliación masiva
        └──► Home Assistant  — reconciliación masiva (pendiente)

Loyverse
  └── Webhook (receipt.created)
        └──► Email           — envío de comprobante

Home Assistant
  └── Webhook entrante desde Tasker (S10+)
        └──► Relé WiFi       — pulso de apertura al motor del portón
```

---

## Estructura del proyecto

```
ipdv-hub-integration/
├── sync_core.py          # Lógica compartida: PCO, Loyverse, HA, helpers
├── webhook.py            # Servidor Flask: recibe eventos en tiempo real
├── cron.py               # Sincronización periódica completa
├── receipt_mailer.py     # Envío de comprobantes por email
├── ha_porton.yaml        # Configuración de Home Assistant para el portón
├── MIGRACION.md          # Instrucciones de migración y setup
└── README.md             # Este archivo
```

---

## Variables de entorno

### PCO
| Variable | Requerida | Descripción |
|---|---|---|
| `PCO_APP_ID` | sí | Application ID de PCO |
| `PCO_SECRET` | sí | Secret de la aplicación PCO |
| `WEBHOOK_SECRET` | sí | Secret para verificar firma de webhooks PCO |
| `WEBHOOK_SECRET_UPDATED` | no | Secret alternativo durante rotación |
| `PCO_RUT_FIELD_NAME` | no | Nombre del campo RUT en PCO (default: `RUT`) |
| `PCO_CAMPO_PORTON` | no | Nombre del campo de portón en PCO (default: `Acceso al portón`) |
| `PCO_VALOR_PORTON` | no | Valor que significa autorizado (default: `Llamado`) |

### Loyverse
| Variable | Requerida | Descripción |
|---|---|---|
| `LOYVERSE_TOKEN` | sí | Token Bearer de la API de Loyverse |

### Home Assistant
| Variable | Requerida | Descripción |
|---|---|---|
| `HA_URL` | sí* | URL base de HA, ej. `http://192.168.1.100:8123` |
| `HA_TOKEN` | sí* | Long-lived access token generado en HA |

*Requeridas solo si la integración de portón está activa. Si no están configuradas, el sistema las saltea silenciosamente y loguea un aviso.

### Comportamiento
| Variable | Default | Descripción |
|---|---|---|
| `DRY_RUN` | `false` | Si `true`, simula sin escribir en ningún sistema |
| `EDAD_MINIMA` | `18` | Edad mínima para sincronizar en Loyverse |
| `DELAY_ENTRE_LLAMADAS` | `0.5` | Segundos entre llamadas a la API (cron) |
| `PCO_PAGE_SIZE` | `100` | Personas por página al consultar PCO |

---

## Cómo agregar una nueva integración

1. Agregar el cliente HTTP en `sync_core.py` siguiendo el patrón de `loyverse_get/post` o `ha_get/ha_post`.
2. Crear la función `sincronizar_<sistema>(persona)` en `sync_core.py`.
3. Llamarla desde `webhook.py` después del bloque de Loyverse.
4. Si aplica, llamarla también desde `cron.py` en el loop principal.
5. Documentar las variables de entorno nuevas en este README.

El principio se mantiene: PCO dispara, el hub propaga, los sistemas destino reciben.

---

## Despliegue

El proyecto corre en **Railway**. Cada push a `main` despliega automáticamente.

- Webhook disponible en: `https://<tu-dominio>.railway.app/webhook/pco`
- Health check en: `https://<tu-dominio>.railway.app/health`
