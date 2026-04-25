#!/usr/bin/env python3
"""
==============================================================================
  SINCRONIZACIÓN: Planning Center Online People → Loyverse POS Customers
==============================================================================
  Reglas de sincronización:
    - Solo personas ACTIVAS en PCO
    - Solo personas con fecha de nacimiento y edad >= 18 años
    - Solo personas que tengan RUT y email (ambos obligatorios)
    - Búsqueda en Loyverse: primero por RUT (customer_code), luego por email
    - El RUT queda en customer_code y en note del cliente Loyverse
    - Datos traspasados: Nombre, Apellidos, Teléfono principal,
      Email principal, RUT

  Configuración:
    Definir las variables de entorno del archivo .env.example
==============================================================================
"""

import re
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

PCO_APP_ID           = os.environ["PCO_APP_ID"]
PCO_SECRET           = os.environ["PCO_SECRET"]
LOYVERSE_TOKEN       = os.environ["LOYVERSE_TOKEN"]

PCO_RUT_FILTER       = os.getenv("PCO_RUT_FILTER", "").strip() or None
PCO_RUT_FIELD_NAME   = os.getenv("PCO_RUT_FIELD_NAME", "RUT")
EDAD_MINIMA          = int(os.getenv("EDAD_MINIMA", "18"))
DRY_RUN              = os.getenv("DRY_RUN", "false").lower() == "true"
DELAY_ENTRE_LLAMADAS = float(os.getenv("DELAY_ENTRE_LLAMADAS", "0.5"))
PCO_PAGE_SIZE        = int(os.getenv("PCO_PAGE_SIZE", "100"))

# Valores que se tratan como "sin dato" independiente de mayúsculas
VALORES_VACIOS = {"N/A", "NA", "NONE", "-", "S/I", ""}


# ══════════════════════════════════════════════════════════════════════════════

PCO_BASE      = "https://api.planningcenteronline.com/people/v2"
LOYVERSE_BASE = "https://api.loyverse.com/v1.0"


# ─── HELPERS ──────────────────────────────────────────────────────────────────

def normalizar(valor) -> str | None:
    """
    Normaliza cualquier valor recibido desde la API:
      - None, vacío, "N/A", "NA", "NONE", "-", "S/I" → retorna None
      - Cualquier otro string → retorna el valor sin espacios extra
    """
    if not valor:
        return None
    limpio = str(valor).strip()
    if limpio.upper() in VALORES_VACIOS:
        return None
    return limpio


def formatear_telefono(telefono: str) -> str:
    """
    Formatea el teléfono al formato internacional requerido por Loyverse.
    Ejemplos:
      "9 9018 2697"   → "+56999182697"
      "+56 9 9018 2697" → "+56999182697"
      "56912345678"   → "+56912345678"
    """
    if not telefono:
        return ""
    # Eliminar todo excepto dígitos y el signo +
    limpio = re.sub(r"[^\d+]", "", telefono)
    # Si ya tiene código de país, dejarlo como está
    if limpio.startswith("+"):
        return limpio
    # Si empieza con 56 (código Chile), agregar +
    if limpio.startswith("56"):
        return f"+{limpio}"
    # Si empieza con 9 (celular chileno sin código), agregar +56
    if limpio.startswith("9") and len(limpio) == 9:
        return f"+56{limpio}"
    # Cualquier otro caso, agregar +56
    return f"+56{limpio}"


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


def loyverse_put(path: str, body: dict) -> dict:
    url = LOYVERSE_BASE + path
    headers = {"Authorization": f"Bearer {LOYVERSE_TOKEN}", "Content-Type": "application/json"}
    resp = requests.put(url, headers=headers, json=body, timeout=30)
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
    """Carga todas las definiciones de campos personalizados de PCO."""
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


def obtener_campo_rut(person_id: str, field_definitions: dict):
    """Busca el valor crudo del campo RUT en los datos personalizados de una persona."""
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
    """
    Descarga todas las personas ACTIVAS desde PCO.
    Todos los campos de texto se normalizan: vacío/"N/A"/similares → None.
    """
    field_definitions = cargar_field_definitions()
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
            attrs = person.get("attributes", {})
            pid   = person["id"]

            # ── Edad ──────────────────────────────────────────────────────────
            birthdate = attrs.get("birthdate")
            edad = calcular_edad(birthdate)

            # ── Email: PRIMERO leer valor crudo, LUEGO normalizar ─────────────
            email_raw = None
            for erel in person.get("relationships", {}).get("emails", {}).get("data", []):
                e = emails_idx.get(erel["id"])
                if e:
                    e_attrs = e.get("attributes", {})
                    if e_attrs.get("primary") or email_raw is None:
                        email_raw = e_attrs.get("address")
                    if e_attrs.get("primary"):
                        break
            email = normalizar(email_raw)  # ← normalización DESPUÉS de leer

            # ── Teléfono: PRIMERO leer valor crudo, LUEGO normalizar ──────────
            telefono_raw = None
            for prel in person.get("relationships", {}).get("phone_numbers", {}).get("data", []):
                p = phones_idx.get(prel["id"])
                if p:
                    p_attrs = p.get("attributes", {})
                    if p_attrs.get("primary") or telefono_raw is None:
                        telefono_raw = p_attrs.get("number")
                    if p_attrs.get("primary"):
                        break
            telefono = normalizar(telefono_raw)  # ← normalización DESPUÉS de leer

            # ── RUT: PRIMERO leer valor crudo, LUEGO normalizar ───────────────
            rut = normalizar(obtener_campo_rut(pid, field_definitions))

            personas.append({
                "pco_id":     pid,
                "first_name": attrs.get("first_name", "").strip(),
                "last_name":  attrs.get("last_name", "").strip(),
                "birthdate":  birthdate,
                "edad":       edad,
                "email":      email,
                "phone":      telefono,
                "rut":        rut,
            })

        total = data.get("meta", {}).get("total_count", 0)
        offset += len(items)
        log.info(f"PCO: {offset}/{total} personas activas descargadas.")
        if offset >= total:
            break

    log.info(f"PCO: total personas activas obtenidas = {len(personas)}")
    return personas


# ─── LOYVERSE ─────────────────────────────────────────────────────────────────

def buscar_cliente_por_rut(rut: str):
    """Busca cliente en Loyverse por customer_code (RUT). Criterio principal."""
    if not rut:
        return None
    try:
        resp = loyverse_get("/customers", params={"customer_code": rut, "limit": 1})
        customers = resp.get("customers", [])
        return customers[0] if customers else None
    except Exception as e:
        log.warning(f"Error buscando cliente por RUT {rut}: {e}")
        return None


def buscar_cliente_por_email(email: str):
    """Busca cliente en Loyverse por email. Fallback cuando no hay RUT."""
    if not email:
        return None
    try:
        resp = loyverse_get("/customers", params={"email": email, "limit": 1})
        customers = resp.get("customers", [])
        return customers[0] if customers else None
    except Exception as e:
        log.warning(f"Error buscando cliente por email {email}: {e}")
        return None


def buscar_cliente_existente(persona: dict):
    """
    Estrategia de búsqueda en orden de confiabilidad:
    1. RUT (customer_code) — identificador único e inequívoco
    2. Email              — fallback secundario
    """
    cliente = buscar_cliente_por_rut(persona.get("rut"))
    if cliente:
        log.debug(f"Match por RUT: {persona.get('rut')}")
        return cliente

    cliente = buscar_cliente_por_email(persona.get("email"))
    if cliente:
        log.debug(f"Match por email (fallback): {persona.get('email')}")
        return cliente

    return None


def construir_payload(persona: dict) -> dict:
    """Construye el body para crear/actualizar un cliente en Loyverse."""
    nombre = f"{persona['first_name']} {persona['last_name']}".strip()
    rut    = persona.get("rut") or ""
    return {
        "name":          nombre or "Sin nombre",
        "email":         persona.get("email") or "",
        "phone_number":  formatear_telefono(persona.get("phone") or ""),
        "customer_code": rut,
        "note":          f"RUT: {rut}" if rut else "",
    }


def crear_o_actualizar_cliente(persona: dict) -> str:
    """Crea o actualiza un cliente en Loyverse. Retorna el resultado."""
    payload  = construir_payload(persona)
    existing = buscar_cliente_existente(persona)

    if DRY_RUN:
        accion = "ACTUALIZAR" if existing else "CREAR"
        log.info(f"[DRY RUN] {accion}: {payload}")
        return "simulado"

    try:
        if existing:
            payload["id"] = existing["id"]
            log.info(f"PAYLOAD FINAL: {payload}")      
            log.info(f"EXISTING ID: {existing['id']}") 
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
        log.error(f"REQUEST ERROR (red/conexión): {e}")
        return "error"
    except Exception as e:
        log.error(f"ERROR GENERAL: {e}")
        return "error"

# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    log.info("=" * 60)
    log.info("  INICIO SINCRONIZACIÓN PCO People → Loyverse Customers")
    log.info("=" * 60)

    if DRY_RUN:
        log.warning("⚠️  MODO DRY RUN: No se escribirá nada en Loyverse.")

    # 1. Obtener personas activas desde PCO
    todas = obtener_personas_pco()

    # Filtro de prueba: si se define PCO_RUT_FILTER, procesar solo esa persona
    if PCO_RUT_FILTER:
        log.warning(f"⚠️  FILTRO ACTIVO: procesando solo RUT {PCO_RUT_FILTER}")
        todas = [p for p in todas if p.get("rut") == PCO_RUT_FILTER]

    # 2. Clasificar exclusiones en orden de prioridad
    sin_edad  = [p for p in todas
                 if p["edad"] is None]

    menores   = [p for p in todas
                 if p["edad"] is not None
                 and p["edad"] < EDAD_MINIMA]

    sin_rut   = [p for p in todas
                 if p["edad"] is not None and p["edad"] >= EDAD_MINIMA
                 and not p.get("rut")]

    sin_email = [p for p in todas
                 if p["edad"] is not None and p["edad"] >= EDAD_MINIMA
                 and p.get("rut")
                 and not p.get("email")]

    a_sincronizar = [p for p in todas
                     if p["edad"] is not None
                     and p["edad"] >= EDAD_MINIMA
                     and p.get("rut")
                     and p.get("email")]

    # 3. Resumen de exclusiones
    log.info("")
    log.info("─" * 60)
    log.info("  ANÁLISIS DE PERSONAS ACTIVAS EN PCO")
    log.info("─" * 60)
    log.info(f"  Total personas activas:              {len(todas)}")
    log.info(f"  Sin fecha de nacimiento (excluidos): {len(sin_edad)}")
    log.info(f"  Menores de {EDAD_MINIMA} años (excluidos):       {len(menores)}")
    log.info(f"  Sin RUT (excluidos):                 {len(sin_rut)}")
    log.info(f"  Sin email (excluidos):               {len(sin_email)}")
    log.info(f"  A sincronizar con Loyverse:          {len(a_sincronizar)}")
    log.info("─" * 60)

    if sin_rut:
        log.warning("  Personas sin RUT (completar en PCO):")
        for p in sin_rut:
            log.warning(f"    - {p['first_name']} {p['last_name']} | email: {p.get('email') or 'N/A'}")

    if sin_email:
        log.warning("  Personas sin email (completar en PCO):")
        for p in sin_email:
            log.warning(f"    - {p['first_name']} {p['last_name']} | RUT: {p.get('rut') or 'N/A'}")

    if not a_sincronizar:
        log.warning("No hay personas que cumplan todos los requisitos. Fin.")
        return

    # 4. Sincronizar con Loyverse
    log.info("")
    stats = {"creado": 0, "actualizado": 0, "simulado": 0, "error": 0}

    for i, persona in enumerate(a_sincronizar, 1):
        nombre = f"{persona['first_name']} {persona['last_name']}".strip()
        log.info(f"[{i}/{len(a_sincronizar)}] {nombre} "
                 f"(edad={persona['edad']}, RUT={persona['rut']}, email={persona['email']})")

        resultado = crear_o_actualizar_cliente(persona)
        stats[resultado] = stats.get(resultado, 0) + 1
        time.sleep(DELAY_ENTRE_LLAMADAS)

    # 5. Resumen final
    log.info("")
    log.info("─" * 60)
    log.info("  RESUMEN FINAL")
    log.info("─" * 60)
    log.info(f"  Clientes creados:      {stats.get('creado', 0)}")
    log.info(f"  Clientes actualizados: {stats.get('actualizado', 0)}")
    log.info(f"  Simulados (dry run):   {stats.get('simulado', 0)}")
    log.info(f"  Errores:               {stats.get('error', 0)}")
    log.info("─" * 60)
    log.info("  Sincronización completada.")


if __name__ == "__main__":
    main()
