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
# Se obtiene al registrar el webhook en PCO y debe guardarse en Railway
WEBHOOK_SECRET          = os.getenv("WEBHOOK_SECRET", "")
WEBHOOK_SECRET_UPDATED  = os.getenv("WEBHOOK_SECRET_UPDATED", "")

# Valores que se tratan como "sin dato"
VALORES_VACIOS = {"N/A", "NA", "NONE", "-", "S/I", ""}

# ══════════════════════════════════════════════════════════════════════════════

PCO_BASE      = "https://api.planningcenteronline.com/people/v2"
LOYVERSE_BASE = "https://api.loyverse.com/v1.0"


# ─── HELPERS ──────────────────────────────────────────────────────────────────

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
    Esto evita hacer una llamada individual por persona (que causa rate limit 429).
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


def obtener_campo_rut_individual(person_id: str, field_definitions: dict):
    """
    Obtiene el RUT de una sola persona. Usado únicamente por el webhook
    (que procesa una persona a la vez, no el bulk del cron).
    """
    rut_field_id = next(
        (fid for fid, fname in field_definitions.items()
         if fname.strip().upper() == PCO_RUT_FIELD_NAME.upper()),
        None
    )
    if not rut_field_id:
        return None
    try:
        data = pco_get(f"/people/{person_id}/field_data")
        for item in data.get("data", []):
            fdef_id = (item.get("relationships", {})
                       .get("field_definition", {})
                       .get("data", {})
                       .get("id"))
            if fdef_id == rut_field_id:
                return item.get("attributes", {}).get("value")
    except Exception as e:
        log.warning(f"No se pudo obtener RUT de persona {person_id}: {e}")
    return None


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

        # Para el webhook usamos lookup individual (solo una persona)
        rut_valor = normalizar(obtener_campo_rut_individual(person_id, field_definitions))
        return _parsear_persona(person, emails_idx, phones_idx, ruts_bulk={person_id: rut_valor} if rut_valor else {})
    except Exception as e:
        log.error(f"Error obteniendo persona {person_id} de PCO: {e}")
        return None


def obtener_personas_pco() -> list:
    """
    Descarga todas las personas ACTIVAS desde PCO. Usado por el cron.
    Carga los RUTs en una sola llamada bulk para evitar rate limit.
    """
    field_definitions = cargar_field_definitions()

    # Cargar TODOS los RUTs de una vez — evita 150+ llamadas individuales
    ruts_bulk = cargar_ruts_bulk(field_definitions)

    personas = []
    offset = 0

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
            p = _parsear_persona(person, emails_idx, phones_idx, ruts_bulk=ruts_bulk)
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
                     ruts_bulk: dict = None) -> dict | None:
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

    # RUT viene del dict bulk (cron) o del dict individual (webhook)
    rut = normalizar((ruts_bulk or {}).get(pid))

    return {
        "pco_id":     pid,
        "first_name": attrs.get("first_name", "").strip(),
        "last_name":  attrs.get("last_name", "").strip(),
        "status":     attrs.get("status", ""),
        "birthdate":  birthdate,
        "edad":       edad,
        "email":      email,
        "phone":      telefono,
        "rut":        rut,
    }


# ─── VALIDACIÓN ───────────────────────────────────────────────────────────────

def cumple_condiciones(persona: dict, emails_en_pco: set = None) -> tuple[bool, str]:
    """
    Verifica si una persona cumple todas las condiciones para ser sincronizada.
    Retorna (True, "") si cumple, o (False, "motivo") si no.
    emails_en_pco: set de emails ya vistos (para detectar duplicados en cron).
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
    Función central usada por cron y webhook.
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
