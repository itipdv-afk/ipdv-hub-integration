#!/usr/bin/env python3
"""
==============================================================================
  SINCRONIZACIÓN: Planning Center Online People → Loyverse POS Customers
==============================================================================
  Descripción:
    - Lee personas desde Planning Center Online (PCO) People API
    - Filtra solo mayores de 18 años que se encuentren activos
    - Crea o actualiza clientes en Loyverse POS
    - El RUT queda en el campo "customer_code" y en "note" del cliente
    - Datos traspasados: Nombre, Apellidos, Teléfono principal,
      Email principal, RUT

  Configuración:
    Definir las variables de entorno listadas abajo (archivo .env localmente,
    o variables en el panel de Railway en producción).
==============================================================================
"""

import os
import sys
import time
import logging
import requests
from datetime import date, datetime
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
#  CONFIGURACIÓN — todas las variables vienen de variables de entorno
# ══════════════════════════════════════════════════════════════════════════════

PCO_APP_ID          = os.environ["PCO_APP_ID"]       # Application ID de PCO
PCO_SECRET          = os.environ["PCO_SECRET"]       # Secret de PCO
LOYVERSE_TOKEN      = os.environ["LOYVERSE_TOKEN"]   # Token de Loyverse

PCO_RUT_FIELD_NAME  = os.getenv("PCO_RUT_FIELD_NAME", "RUT")
EDAD_MINIMA         = int(os.getenv("EDAD_MINIMA", "18"))
DRY_RUN             = os.getenv("DRY_RUN", "false").lower() == "true"
DELAY_ENTRE_LLAMADAS = float(os.getenv("DELAY_ENTRE_LLAMADAS", "0.5"))
PCO_PAGE_SIZE       = int(os.getenv("PCO_PAGE_SIZE", "100"))

# ══════════════════════════════════════════════════════════════════════════════


PCO_BASE      = "https://api.planningcenteronline.com/people/v2"
LOYVERSE_BASE = "https://api.loyverse.com/v1.0"


# ─── HELPERS HTTP ─────────────────────────────────────────────────────────────

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


def loyverse_patch(path: str, body: dict) -> dict:
    url = LOYVERSE_BASE + path
    headers = {"Authorization": f"Bearer {LOYVERSE_TOKEN}", "Content-Type": "application/json"}
    resp = requests.patch(url, headers=headers, json=body, timeout=30)
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
    definitions = {}
    offset = 0
    while True:
        data = pco_get("/field_definitions", params={"per_page": 100, "offset": offset})
        items = data.get("data", [])
        if not items:
            break
        for item in items:
            definitions[item["id"]] = item.get("attributes", {}).get("name", "")
        meta = data.get("meta", {})
        total = meta.get("total_count", 0)
        offset += len(items)
        if offset >= total:
            break
    log.info(f"Cargadas {len(definitions)} definiciones de campos de PCO.")
    return definitions


def obtener_campo_rut(person_id: str, field_definitions: dict):
    if not field_definitions:
        return None
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


def obtener_personas_pco() -> list:
    field_definitions = cargar_field_definitions()
    personas = []
    offset = 0

    while True:
        params = {
            "per_page": PCO_PAGE_SIZE, 
            "offset": offset, 
            "include": "emails,phone_numbers",
            "where[status]": "active"
        }
        log.info(f"PCO: descargando personas offset={offset}...")
        data = pco_get("/people", params=params)

        items = data.get("data", [])
        if not items:
            break

        included   = data.get("included", [])
        emails_idx = {i["id"]: i for i in included if i["type"] == "Email"}
        phones_idx = {i["id"]: i for i in included if i["type"] == "PhoneNumber"}

        for person in items:
            attrs = person.get("attributes", {})
            pid   = person["id"]

            birthdate = attrs.get("birthdate")
            edad = calcular_edad(birthdate)

            email_principal = None
            for erel in person.get("relationships", {}).get("emails", {}).get("data", []):
                e = emails_idx.get(erel["id"])
                if e:
                    e_attrs = e.get("attributes", {})
                    if e_attrs.get("primary") or email_principal is None:
                        email_principal = e_attrs.get("address")
                    if e_attrs.get("primary"):
                        break

            telefono_principal = None
            for prel in person.get("relationships", {}).get("phone_numbers", {}).get("data", []):
                p = phones_idx.get(prel["id"])
                if p:
                    p_attrs = p.get("attributes", {})
                    if p_attrs.get("primary") or telefono_principal is None:
                        telefono_principal = p_attrs.get("number")
                    if p_attrs.get("primary"):
                        break

            rut = obtener_campo_rut(pid, field_definitions)

            personas.append({
                "pco_id":     pid,
                "first_name": attrs.get("first_name", "").strip(),
                "last_name":  attrs.get("last_name", "").strip(),
                "birthdate":  birthdate,
                "edad":       edad,
                "email":      email_principal,
                "phone":      telefono_principal,
                "rut":        rut,
            })

        meta  = data.get("meta", {})
        total = meta.get("total_count", 0)
        offset += len(items)
        log.info(f"PCO: {offset}/{total} personas descargadas.")
        if offset >= total:
            break

    log.info(f"PCO: total personas obtenidas = {len(personas)}")
    return personas


# ─── LOYVERSE ─────────────────────────────────────────────────────────────────

def buscar_cliente_por_email(email: str):
    if not email:
        return None
    try:
        resp = loyverse_get("/customers", params={"email": email, "limit": 1})
        customers = resp.get("customers", [])
        return customers[0] if customers else None
    except Exception as e:
        log.warning(f"Error buscando cliente por email {email}: {e}")
        return None


def construir_payload(persona: dict) -> dict:
    nombre = f"{persona['first_name']} {persona['last_name']}".strip()
    rut    = persona.get("rut") or ""
    return {
        "name":          nombre or "Sin nombre",
        "email":         persona.get("email") or "",
        "phone_number":  persona.get("phone") or "",
        "customer_code": rut,
        "note":          f"RUT: {rut}" if rut else "",
    }


def crear_o_actualizar_cliente(persona: dict) -> str:
    payload  = construir_payload(persona)
    existing = buscar_cliente_por_email(persona.get("email"))

    if DRY_RUN:
        accion = "ACTUALIZAR" if existing else "CREAR"
        log.info(f"[DRY RUN] {accion}: {payload}")
        return "simulado"

    try:
        if existing:
            loyverse_patch(f"/customers/{existing['id']}", payload)
            return "actualizado"
        else:
            loyverse_post("/customers", payload)
            return "creado"
    except requests.HTTPError as e:
        log.error(f"Error HTTP al procesar {payload.get('name')}: {e.response.text}")
        return "error"
    except Exception as e:
        log.error(f"Error inesperado al procesar {payload.get('name')}: {e}")
        return "error"


# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    log.info("=" * 60)
    log.info("  INICIO SINCRONIZACIÓN PCO People → Loyverse Customers")
    log.info("=" * 60)

    if DRY_RUN:
        log.warning("⚠️  MODO DRY RUN: No se escribirá nada en Loyverse.")

    todas = obtener_personas_pco()
    adultos   = [p for p in todas if p["edad"] is not None and p["edad"] >= EDAD_MINIMA]
    sin_edad  = [p for p in todas if p["edad"] is None]

    log.info(f"Personas totales en PCO:              {len(todas)}")
    log.info(f"Sin fecha de nacimiento (excluidos):  {len(sin_edad)}")
    log.info(f"Menores de {EDAD_MINIMA} años (excluidos):    {len(todas) - len(adultos) - len(sin_edad)}")
    log.info(f"Adultos a sincronizar (≥{EDAD_MINIMA} años):  {len(adultos)}")

    if not adultos:
        log.warning("No hay adultos para sincronizar. Fin.")
        return

    stats = {"creado": 0, "actualizado": 0, "simulado": 0, "error": 0}

    for i, persona in enumerate(adultos, 1):
        nombre = f"{persona['first_name']} {persona['last_name']}".strip()
        log.info(f"[{i}/{len(adultos)}] {nombre} (edad={persona['edad']}, RUT={persona.get('rut') or 'N/A'})")
        resultado = crear_o_actualizar_cliente(persona)
        stats[resultado] = stats.get(resultado, 0) + 1
        time.sleep(DELAY_ENTRE_LLAMADAS)

    log.info("")
    log.info("─" * 60)
    log.info("  RESUMEN FINAL")
    log.info(f"  Creados:      {stats.get('creado', 0)}")
    log.info(f"  Actualizados: {stats.get('actualizado', 0)}")
    log.info(f"  Simulados:    {stats.get('simulado', 0)}")
    log.info(f"  Errores:      {stats.get('error', 0)}")
    log.info("─" * 60)
    log.info("  Sincronización completada.")


if __name__ == "__main__":
    main()
