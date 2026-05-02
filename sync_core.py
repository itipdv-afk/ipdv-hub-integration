#!/usr/bin/env python3
"""
==============================================================================
  LÓGICA COMPARTIDA — usada por cron.py y webhook.py
==============================================================================
"""

import re
import os
import sys
import time
import hmac
import hashlib
import logging
import requests
from datetime import date, datetime
from collections import Counter
from dateutil.relativedelta import relativedelta

# ─── LOGGING ─────────────────────────────────────────────────────────────────
os.makedirs("/app/logs", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("/app/logs/sync_log.txt", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
#  CONFIGURACIÓN
# ══════════════════════════════════════════════════════════════════════════════

PCO_APP_ID           = os.environ["PCO_APP_ID"]
PCO_SECRET           = os.environ["PCO_SECRET"]
LOYVERSE_TOKEN       = os.environ["LOYVERSE_TOKEN"]

PCO_RUT_FILTER       = os.getenv("PCO_RUT_FILTER", "").strip() or None
PCO_RUT_FIELD_NAME   = os.getenv("PCO_RUT_FIELD_NAME", "RUT")
EDAD_MINIMA          = int(os.getenv("EDAD_MINIMA", "18"))
DRY_RUN              = os.getenv("DRY_RUN", "false").lower() == "true"
DELAY_ENTRE_LLAMADAS = float(os.getenv("DELAY_ENTRE_LLAMADAS", "0.5"))
PCO_PAGE_SIZE        = int(os.getenv("PCO_PAGE_SIZE", "100"))

# Secret para verificar firma de webhooks de PCO
WEBHOOK_SECRET          = os.getenv("WEBHOOK_SECRET", "")
WEBHOOK_SECRET_UPDATED  = os.getenv("WEBHOOK_SECRET_UPDATED", "")

# ── Home Assistant ────────────────────────────────────────────────────────────
# URL base interna de HA (sin barra final). Ej: http://192.168.1.100:8123
HA_URL              = os.getenv("HA_URL", "").rstrip("/")
# Long-lived access token generado en HA → Perfil → Tokens de larga duración
HA_TOKEN            = os.getenv("HA_TOKEN", "")
# Nombre del campo personalizado en PCO que controla el acceso al portón
PCO_CAMPO_PORTON    = os.getenv("PCO_CAMPO_PORTON", "Acceso al portón")
# Valor del campo que significa "autorizado"
PCO_VALOR_PORTON    = os.getenv("PCO_VALOR_PORTON", "Llamado")

# Valores que se tratan como "sin dato"
VALORES_VACIOS = {"N/A", "NA", "NONE", "-", "S/I", ""}

# ══════════════════════════════════════════════════════════════════════════════

PCO_BASE      = "https://api.planningcenteronline.com/people/v2"
LOYVERSE_BASE = "https://api.loyverse.com/v1.0"


# ─── HELPERS GENÉRICOS ────────────────────────────────────────────────────────

def normalizar(valor) -> str | None:
    if not valor:
        return None
    limpio = str(valor).strip()
    if limpio.upper() in VALORES_VACIOS:
        return None
    return limpio


def formatear_telefono(telefono: str) -> str:
    if not telefono:
        return ""
    limpio = re.sub(r"[^\d+]", "", telefono)
    if limpio.startswith("+"):
        return limpio
    if limpio.startswith("56"):
        return f"+{limpio}"
    if limpio.startswith("9") and len(limpio) == 9:
        return f"+56{limpio}"
    return f"+56{limpio}"


def verificar_firma_pco(payload_bytes: bytes, signature_header: str) -> bool:
    if not WEBHOOK_SECRET and not WEBHOOK_SECRET_UPDATED:
        log.warning("WEBHOOK_SECRET no configurado — omitiendo verificación.")
        return True
    sig = signature_header or ""
    log.info(f"Verificando firma. Header recibido: '{sig[:30]}'")
    for secret in filter(None, [WEBHOOK_SECRET, WEBHOOK_SECRET_UPDATED]):
        try:
            expected = hmac.new(
                secret.encode(),
                payload_bytes,
                hashlib.sha256
            ).hexdigest()
            log.info(f"Expected: '{expected[:30]}'")
            if hmac.compare_digest(expected, sig):
                return True
        except Exception as e:
            log.error(f"Error verificando firma: {e}")
    return False


# ─── HTTP HELPERS ─────────────────────────────────────────────────────────────

def pco_get(path: str, params: dict = None) -> dict:
    url = PCO_BASE + path
    resp = requests.get(url, auth=(PCO_APP_ID, PCO_SECRET), params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def loyverse_get(path: str, params: dict = None) -> dict:
    url = LOYVERSE_BASE + path
    headers = {"Authorization": f"Bearer {LOYVERSE_TOKEN}"}
    resp = requests.get(url, headers=headers, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def loyverse_post(path: str, body: dict) -> dict:
    url = LOYVERSE_BASE + path
    headers = {"Authorization": f"Bearer {LOYVERSE_TOKEN}", "Content-Type": "application/json"}
    resp = requests.post(url, headers=headers, json=body, timeout=30)
    resp.raise_for_status()
    return resp.json()


# ─── HOME ASSISTANT HTTP HELPERS ──────────────────────────────────────────────

def _ha_headers() -> dict:
    return {
        "Authorization": f"Bearer {HA_TOKEN}",
        "Content-Type":  "application/json",
    }


def ha_get(path: str) -> dict | None:
    """GET a la API REST de Home Assistant. Retorna None si falla."""
    if not HA_URL or not HA_TOKEN:
        log.warning("HA_URL o HA_TOKEN no configurados — salteando llamada a HA.")
        return None
    try:
        resp = requests.get(f"{HA_URL}/api{path}", headers=_ha_headers(), timeout=10)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        log.error(f"Error GET HA {path}: {e}")
        return None


def ha_post(path: str, body: dict) -> dict | None:
    """POST a la API REST de Home Assistant. Retorna None si falla."""
    if not HA_URL or not HA_TOKEN:
        log.warning("HA_URL o HA_TOKEN no configurados — salteando llamada a HA.")
        return None
    try:
        resp = requests.post(
            f"{HA_URL}/api{path}",
            headers=_ha_headers(),
            json=body,
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        log.error(f"Error POST HA {path}: {e}")
        return None


# ─── FECHA ────────────────────────────────────────────────────────────────────

def calcular_edad(birthdate_str: str):
    if not birthdate_str:
        return None
    try:
        bdate = datetime.strptime(birthdate_str[:10], "%Y-%m-%d").date()
        return relativedelta(date.today(), bdate).years
    except ValueError:
        return None


# ─── PLANNING CENTER ──────────────────────────────────────────────────────────

def cargar_field_definitions() -> dict:
    """Retorna dict {field_def_id -> nombre_campo}"""
    definitions = {}
    offset = 0
    while True:
        data = pco_get("/field_definitions", params={"per_page": 100, "offset": offset})
        items = data.get("data", [])
        if not items:
            break
        for item in items:
            definitions[item["id"]] = item.get("attributes", {}).get("name", "")
        total = data.get("meta", {}).get("total_count", 0)
        offset += len(items)
        if offset >= total:
            break
    log.info(f"Cargadas {len(definitions)} definiciones de campos de PCO.")
    return definitions


def cargar_ruts_bulk(field_definitions: dict) -> dict:
    """
    Carga TODOS los valores del campo RUT en una sola pasada paginada.
    Retorna dict {person_id -> rut_value}.
    """
    rut_field_id = next(
        (fid for fid, fname in field_definitions.items()
         if fname.strip().upper() == PCO_RUT_FIELD_NAME.upper()),
        None
    )
    if not rut_field_id:
        log.warning(f"Campo '{PCO_RUT_FIELD_NAME}' no encontrado en field_definitions.")
        return {}

    ruts = {}
    offset = 0
    while True:
        data = pco_get("/field_data", params={
            "per_page":                    100,
            "offset":                      offset,
            "filter":                      "no_dates",
            "where[field_definition_id]":  rut_field_id,
        })
        items = data.get("data", [])
        if not items:
            break
        for item in items:
            person_id = (item.get("relationships", {})
                         .get("customizable", {})
                         .get("data", {})
                         .get("id"))
            value = item.get("attributes", {}).get("value")
            if person_id and value:
                ruts[person_id] = value
        total = data.get("meta", {}).get("total_count", 0)
        offset += len(items)
        if offset >= total:
            break

    log.info(f"RUTs cargados en bulk: {len(ruts)} registros.")
    return ruts


def cargar_campos_personalizados_bulk(field_definitions: dict) -> dict:
    """
    Carga TODOS los campos personalizados en una sola pasada paginada.
    Retorna dict {person_id -> {nombre_campo -> valor}}.
    Usado por el cron para no hacer llamadas individuales.
    """
    campos = {}
    offset = 0
    while True:
        data = pco_get("/field_data", params={
            "per_page": 100,
            "offset":   offset,
            "filter":   "no_dates",
        })
        items = data.get("data", [])
        if not items:
            break
        for item in items:
            person_id = (item.get("relationships", {})
                         .get("customizable", {})
                         .get("data", {})
                         .get("id"))
            fdef_id   = (item.get("relationships", {})
                         .get("field_definition", {})
                         .get("data", {})
                         .get("id"))
            value     = item.get("attributes", {}).get("value")
            if person_id and fdef_id and value:
                nombre_campo = field_definitions.get(fdef_id, fdef_id)
                campos.setdefault(person_id, {})[nombre_campo] = value
        total = data.get("meta", {}).get("total_count", 0)
        offset += len(items)
        if offset >= total:
            break

    log.info(f"Campos personalizados cargados en bulk: {len(campos)} personas con campos.")
    return campos


def obtener_campos_individuales(person_id: str, field_definitions: dict) -> dict:
    """
    Obtiene todos los campos personalizados de UNA persona.
    Usado por el webhook (procesa una persona a la vez).
    Retorna {nombre_campo -> valor}.
    """
    campos = {}
    try:
        data = pco_get(f"/people/{person_id}/field_data")
        for item in data.get("data", []):
            fdef_id = (item.get("relationships", {})
                       .get("field_definition", {})
                       .get("data", {})
                       .get("id"))
            value = item.get("attributes", {}).get("value")
            if fdef_id and value:
                nombre_campo = field_definitions.get(fdef_id, fdef_id)
                campos[nombre_campo] = value
    except Exception as e:
        log.warning(f"No se pudieron obtener campos de persona {person_id}: {e}")
    return campos


def obtener_campo_rut_individual(person_id: str, field_definitions: dict):
    """
    Obtiene solo el RUT de una persona. Compatibilidad con código existente.
    Preferir obtener_campos_individuales() que ya trae todos los campos.
    """
    campos = obtener_campos_individuales(person_id, field_definitions)
    return campos.get(PCO_RUT_FIELD_NAME)


def obtener_persona_pco(person_id: str, field_definitions: dict) -> dict | None:
    """
    Obtiene una sola persona desde PCO por su ID.
    Usado por el webhook para procesar una persona específica.
    """
    try:
        data = pco_get(f"/people/{person_id}", params={"include": "emails,phone_numbers"})
        person = data.get("data")
        if not person:
            return None

        included   = data.get("included", [])
        emails_idx = {i["id"]: i for i in included if i["type"] == "Email"}
        phones_idx = {i["id"]: i for i in included if i["type"] == "PhoneNumber"}

        # Una sola llamada trae RUT, portón y cualquier otro campo personalizado
        campos = obtener_campos_individuales(person_id, field_definitions)
        rut_valor = normalizar(campos.get(PCO_RUT_FIELD_NAME))

        return _parsear_persona(
            person,
            emails_idx,
            phones_idx,
            ruts_bulk={person_id: rut_valor} if rut_valor else {},
            campos_bulk={person_id: campos},
        )
    except Exception as e:
        log.error(f"Error obteniendo persona {person_id} de PCO: {e}")
        return None


def obtener_personas_pco() -> list:
    """
    Descarga todas las personas ACTIVAS desde PCO. Usado por el cron.
    """
    field_definitions = cargar_field_definitions()
    ruts_bulk   = cargar_ruts_bulk(field_definitions)
    campos_bulk = cargar_campos_personalizados_bulk(field_definitions)

    personas = []
    offset   = 0

    while True:
        params = {
            "per_page":      PCO_PAGE_SIZE,
            "offset":        offset,
            "include":       "emails,phone_numbers",
            "where[status]": "active",
        }
        log.info(f"PCO: descargando personas activas offset={offset}...")
        data = pco_get("/people", params=params)

        items = data.get("data", [])
        if not items:
            break

        included   = data.get("included", [])
        emails_idx = {i["id"]: i for i in included if i["type"] == "Email"}
        phones_idx = {i["id"]: i for i in included if i["type"] == "PhoneNumber"}

        for person in items:
            p = _parsear_persona(
                person, emails_idx, phones_idx,
                ruts_bulk=ruts_bulk,
                campos_bulk=campos_bulk,
            )
            if p:
                personas.append(p)

        total = data.get("meta", {}).get("total_count", 0)
        offset += len(items)
        log.info(f"PCO: {offset}/{total} personas activas descargadas.")
        if offset >= total:
            break

    log.info(f"PCO: total personas activas obtenidas = {len(personas)}")
    return personas


def _parsear_persona(person: dict, emails_idx: dict, phones_idx: dict,
                     ruts_bulk: dict = None, campos_bulk: dict = None) -> dict | None:
    """Extrae y normaliza los datos de una persona desde la respuesta de PCO."""
    attrs = person.get("attributes", {})
    pid   = person["id"]

    birthdate = attrs.get("birthdate")
    edad = calcular_edad(birthdate)

    email_raw = None
    for erel in person.get("relationships", {}).get("emails", {}).get("data", []):
        e = emails_idx.get(erel["id"])
        if e:
            e_attrs = e.get("attributes", {})
            if e_attrs.get("primary") or email_raw is None:
                email_raw = e_attrs.get("address")
            if e_attrs.get("primary"):
                break
    email = normalizar(email_raw)

    telefono_raw = None
    for prel in person.get("relationships", {}).get("phone_numbers", {}).get("data", []):
        p = phones_idx.get(prel["id"])
        if p:
            p_attrs = p.get("attributes", {})
            if p_attrs.get("primary") or telefono_raw is None:
                telefono_raw = p_attrs.get("number")
            if p_attrs.get("primary"):
                break
    telefono = normalizar(telefono_raw)

    rut = normalizar((ruts_bulk or {}).get(pid))

    # Campos personalizados de esta persona (dict nombre->valor)
    campos = (campos_bulk or {}).get(pid, {})

    # Campo portón: normalizado a minúsculas para comparación robusta
    acceso_porton = normalizar(campos.get(PCO_CAMPO_PORTON))

    return {
        "pco_id":         pid,
        "first_name":     attrs.get("first_name", "").strip(),
        "last_name":      attrs.get("last_name", "").strip(),
        "status":         attrs.get("status", ""),
        "birthdate":      birthdate,
        "edad":           edad,
        "email":          email,
        "phone":          telefono,
        "rut":            rut,
        "acceso_porton":  acceso_porton,   # ej. "Llamado", None, "No"
        "campos_pco":     campos,           # todos los campos personalizados
    }


# ─── VALIDACIÓN (Loyverse) ────────────────────────────────────────────────────

def cumple_condiciones(persona: dict, emails_en_pco: set = None) -> tuple[bool, str]:
    """
    Verifica si una persona cumple condiciones para ser sincronizada en Loyverse.
    Retorna (True, "") si cumple, o (False, "motivo") si no.
    """
    if persona.get("status") and persona["status"] != "active":
        return False, "inactiva"
    if persona["edad"] is None:
        return False, "sin fecha de nacimiento"
    if persona["edad"] < EDAD_MINIMA:
        return False, f"menor de {EDAD_MINIMA} años"
    if not persona.get("rut"):
        return False, "sin RUT"
    if not persona.get("email"):
        return False, "sin email"
    if emails_en_pco and persona["email"].lower() in emails_en_pco:
        return False, "email duplicado en PCO"
    return True, ""


def califica_porton(persona: dict) -> bool:
    """
    Retorna True si la persona debe tener acceso al portón.
    Compara sin distinción de mayúsculas/minúsculas ni espacios extra.
    """
    acceso = (persona.get("acceso_porton") or "").strip().lower()
    return acceso == PCO_VALOR_PORTON.strip().lower()


# ─── LOYVERSE ─────────────────────────────────────────────────────────────────

def buscar_cliente_por_email(email: str):
    if not email:
        return None
    try:
        resp = loyverse_get("/customers", params={"email": email, "limit": 50})
        customers = resp.get("customers", [])
        for cliente in customers:
            if cliente.get("email", "").lower() == email.lower():
                return cliente
        return None
    except Exception as e:
        log.warning(f"Error buscando cliente por email {email}: {e}")
        return None


def construir_payload(persona: dict) -> dict:
    nombre = f"{persona['first_name']} {persona['last_name']}".strip()
    rut    = persona.get("rut") or ""
    payload = {
        "name":          nombre or "Sin nombre",
        "email":         persona.get("email") or "",
        "customer_code": rut,
        "note":          f"RUT: {rut}" if rut else "",
    }
    telefono = formatear_telefono(persona.get("phone") or "")
    if telefono:
        payload["phone_number"] = telefono
    return payload


def sincronizar_persona(persona: dict) -> str:
    """
    Crea o actualiza un cliente en Loyverse.
    Retorna: 'creado', 'actualizado', 'simulado' o 'error'.
    """
    existing = buscar_cliente_por_email(persona.get("email"))
    payload  = construir_payload(persona)

    if DRY_RUN:
        accion = "ACTUALIZAR" if existing else "CREAR"
        log.info(f"[DRY RUN] {accion}: {payload}")
        return "simulado"

    try:
        if existing:
            payload["id"] = existing["id"]
            loyverse_post("/customers", payload)
            return "actualizado"
        else:
            loyverse_post("/customers", payload)
            return "creado"
    except requests.HTTPError as e:
        log.error(f"HTTP ERROR: {e}")
        log.error(f"RESPONSE BODY: {e.response.text}")
        return "error"
    except requests.RequestException as e:
        log.error(f"REQUEST ERROR: {e}")
        return "error"
    except Exception as e:
        log.error(f"ERROR GENERAL: {e}")
        return "error"


# ─── HOME ASSISTANT — PORTÓN ──────────────────────────────────────────────────

def sincronizar_porton_ha(persona: dict) -> str:
    """
    Sincroniza el acceso al portón de UNA persona con Home Assistant.

    HA almacena la lista en /config/porton_autorizados.json como:
    { "<telefono>": { "nombre": ..., "pco_id": ..., "expira": null } }

    Railway lee el archivo actual via sensor.porton_autorizados,
    lo modifica y lo escribe de vuelta via shell_command.actualizar_porton.

    Retorna: 'agregado' | 'actualizado' | 'eliminado' | 'omitido' |
             'error_ha' | 'sin_telefono'
    """
    if not HA_URL or not HA_TOKEN:
        log.info("HA no configurado — salteando sync portón.")
        return "omitido"

    telefono = formatear_telefono(persona.get("phone") or "")
    if not telefono:
        log.info(f"Persona {persona.get('pco_id')} sin teléfono — no puede acceder al portón.")
        return "sin_telefono"

    nombre   = f"{persona['first_name']} {persona['last_name']}".strip()
    califica = califica_porton(persona)

    # ── Leer lista actual desde el sensor de HA ───────────────────────────────
    estado = ha_get("/states/sensor.porton_autorizados")
    if estado is None:
        return "error_ha"

    try:
        import json
        # El sensor expone el JSON como atributos
        autorizados: dict = estado.get("attributes", {})
        # Filtrar atributos propios del sensor que no son teléfonos
        autorizados = {
            k: v for k, v in autorizados.items()
            if k.startswith("+") and isinstance(v, dict)
        }
    except Exception as e:
        log.error(f"Error leyendo autorizados desde HA: {e}")
        autorizados = {}

    if califica:
        es_nuevo = telefono not in autorizados
        autorizados[telefono] = {
            "nombre": nombre,
            "pco_id": persona["pco_id"],
            "expira": None,
        }
        resultado = "agregado" if es_nuevo else "actualizado"
    else:
        if telefono in autorizados:
            del autorizados[telefono]
            resultado = "eliminado"
        else:
            return "omitido"

    # ── Escribir lista actualizada via shell_command ──────────────────────────
    import json
    ok = ha_post("/services/shell_command/actualizar_porton", {
        "autorizados": json.dumps(autorizados, ensure_ascii=False),
    })
    if ok is None:
        return "error_ha"

    log.info(f"Portón HA [{resultado}]: {nombre} ({telefono})")
    return resultado