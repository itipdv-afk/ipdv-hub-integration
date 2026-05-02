# ipdv-hub — Migración a control de portón con HA

## Renombrar el repositorio

En GitHub: **Settings → Repository name → `ipdv-hub`** (o el nombre que prefieras).
Luego actualizar el remote local:

```bash
git remote set-url origin https://github.com/TU_ORG/ipdv-hub.git
```

---

## Variables de entorno nuevas (agregar en Railway)

| Variable | Ejemplo | Descripción |
|---|---|---|
| `HA_URL` | `http://192.168.1.100:8123` | URL interna de Home Assistant |
| `HA_TOKEN` | `eyJ0...` | Long-lived token de HA |
| `PCO_CAMPO_PORTON` | `Acceso al portón` | Nombre exacto del campo en PCO |
| `PCO_VALOR_PORTON` | `Llamado` | Valor que significa "autorizado" |

**Cómo obtener el token de HA:**
HA → tu usuario (esquina inferior izquierda) → Tokens de larga duración → Crear token.

---

## Configuración de Home Assistant

1. Copiar el contenido de `ha_porton.yaml` a tu `configuration.yaml`
   (o a los archivos split si usás esa estructura).

2. Cambiar `switch.rele_porton` por el entity_id real de tu relé WiFi.

3. Cambiar el `webhook_id: "porton_llamada_entrante"` por un string secreto tuyo
   (tratalo como una contraseña — es lo que Tasker enviará).

4. Recargar configuración: HA → Herramientas del desarrollador → Reiniciar / Recargar YAML.

5. Verificar que `input_text.porton_autorizados` apareció en el panel.

---

## Cambio en Tasker

En el perfil que hoy llama a HA cuando detecta una llamada autorizada,
reemplazar la tarea HTTP por:

```
Acción HTTP POST
URL:     http://TU_HA:8123/api/webhook/porton_llamada_entrante
Headers: Content-Type: application/json
Body:    {"telefono": "%CNUM"}   ← %CNUM es la variable de Tasker con el número entrante
```

**Ya no necesita consultar la agenda de Google Contacts.**
HA hace toda la validación internamente.

---

## Flujo completo tras la migración

```
PCO (admin marca campo)
  └─► webhook.py (Railway)
        ├─► Loyverse: crear/actualizar cliente  [sin cambios]
        └─► HA API: actualizar input_text.porton_autorizados

Llamada entrante al S10+
  └─► Tasker detecta llamada
        └─► POST /api/webhook/porton_llamada_entrante  { "telefono": "+569..." }
              └─► HA automation verifica lista + expiración
                    ├─► autorizado → script.porton_pulso → relé → portón abre
                    └─► no autorizado → log "acceso denegado"
```

---

## Agregar un acceso temporal (sin pasar por PCO)

Desde HA → Herramientas del desarrollador → Estados → `input_text.porton_autorizados`:

```json
{
  "+56912345678": { "nombre": "Ana García", "pco_id": "123", "expira": null },
  "+56911111111": { "nombre": "Visita temporal", "pco_id": null, "expira": "2026-05-10T18:00:00" }
}
```

Los accesos con `"expira": null` son permanentes (vienen de PCO).
Los accesos con fecha expiran automáticamente — la automation de las 03:00 los limpia.

---

## Verificar que funciona

```bash
# Desde la misma red que HA, simular una llamada autorizada:
curl -X POST http://TU_HA:8123/api/webhook/porton_llamada_entrante \
  -H "Content-Type: application/json" \
  -d '{"telefono": "+56912345678"}'

# Ver el log de accesos:
# HA → Logbook → filtrar por "Portón"
```
