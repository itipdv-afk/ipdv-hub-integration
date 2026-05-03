#!/usr/bin/env python3
"""
==============================================================================
  CRON: Sincronización completa PCO → Loyverse + Home Assistant (portón)
  Se ejecuta de forma programada (domingos 03:00 AM hora Chile).
  También puede ejecutarse manualmente: python cron.py
==============================================================================
"""

import time
import logging
from collections import Counter
from sync_core import (
    log, DRY_RUN, PCO_RUT_FILTER, EDAD_MINIMA, DELAY_ENTRE_LLAMADAS,
    obtener_personas_pco, cumple_condiciones, sincronizar_persona,
    sincronizar_porton_ha,
)


def main():
    log.info("=" * 60)
    log.info("  INICIO SINCRONIZACIÓN COMPLETA PCO → Loyverse + HA (CRON)")
    log.info("=" * 60)

    if DRY_RUN:
        log.warning("⚠️  MODO DRY RUN: No se escribirá nada en Loyverse.")

    # ── 1. Obtener personas activas desde PCO ─────────────────────────────────
    todas = obtener_personas_pco()

    if PCO_RUT_FILTER:
        log.warning(f"⚠️  FILTRO ACTIVO: procesando solo RUT {PCO_RUT_FILTER}")
        todas = [p for p in todas if p.get("rut") == PCO_RUT_FILTER]

    # ── 2. Clasificar para Loyverse ───────────────────────────────────────────
    sin_edad  = [p for p in todas if p["edad"] is None]
    menores   = [p for p in todas if p["edad"] is not None and p["edad"] < EDAD_MINIMA]
    sin_rut   = [p for p in todas if p["edad"] is not None and p["edad"] >= EDAD_MINIMA
                 and not p.get("rut")]
    sin_email = [p for p in todas if p["edad"] is not None and p["edad"] >= EDAD_MINIMA
                 and p.get("rut") and not p.get("email")]

    candidatos = [p for p in todas
                  if p["edad"] is not None and p["edad"] >= EDAD_MINIMA
                  and p.get("rut") and p.get("email")]

    conteo_emails     = Counter(p["email"].lower() for p in candidatos)
    emails_duplicados = {e for e, c in conteo_emails.items() if c > 1}
    email_dup         = [p for p in candidatos if p["email"].lower() in emails_duplicados]
    a_sincronizar     = [p for p in candidatos if p["email"].lower() not in emails_duplicados]

    # ── 3. Resumen de exclusiones Loyverse ────────────────────────────────────
    log.info("")
    log.info("─" * 60)
    log.info("  ANÁLISIS DE PERSONAS ACTIVAS EN PCO")
    log.info("─" * 60)
    log.info(f"  Total personas activas:               {len(todas)}")
    log.info(f"  Sin fecha de nacimiento (excluidos):  {len(sin_edad)}")
    log.info(f"  Menores de {EDAD_MINIMA} años (excluidos):        {len(menores)}")
    log.info(f"  Sin RUT (excluidos):                  {len(sin_rut)}")
    log.info(f"  Sin email (excluidos):                {len(sin_email)}")
    log.info(f"  Email duplicado en PCO (excluidos):   {len(email_dup)}")
    log.info(f"  A sincronizar con Loyverse:           {len(a_sincronizar)}")
    log.info("─" * 60)

    if sin_rut:
        log.warning("  Personas sin RUT (completar en PCO):")
        for p in sin_rut:
            log.warning(f"    - {p['first_name']} {p['last_name']} | email: {p.get('email') or 'N/A'}")

    if sin_email:
        log.warning("  Personas sin email (completar en PCO):")
        for p in sin_email:
            log.warning(f"    - {p['first_name']} {p['last_name']} | RUT: {p.get('rut') or 'N/A'}")

    if email_dup:
        log.warning("  Personas con email duplicado en PCO (corregir en PCO):")
        for p in email_dup:
            log.warning(f"    - {p['first_name']} {p['last_name']} | email: {p['email']} | RUT: {p['rut']}")

    # ── 4. Sincronizar Loyverse ───────────────────────────────────────────────
    log.info("")
    log.info("─" * 60)
    log.info("  SINCRONIZACIÓN → LOYVERSE")
    log.info("─" * 60)

    stats_loyverse = {"creado": 0, "actualizado": 0, "simulado": 0, "error": 0}

    if not a_sincronizar:
        log.warning("No hay personas que cumplan todos los requisitos para Loyverse.")
    else:
        for i, persona in enumerate(a_sincronizar, 1):
            nombre = f"{persona['first_name']} {persona['last_name']}".strip()
            log.info(f"[{i}/{len(a_sincronizar)}] {nombre} "
                     f"(edad={persona['edad']}, RUT={persona['rut']}, email={persona['email']})")

            resultado = sincronizar_persona(persona)
            stats_loyverse[resultado] = stats_loyverse.get(resultado, 0) + 1
            time.sleep(DELAY_ENTRE_LLAMADAS)

    # ── 5. Sincronizar portón → Home Assistant ────────────────────────────────
    log.info("")
    log.info("─" * 60)
    log.info("  SINCRONIZACIÓN → HOME ASSISTANT (PORTÓN)")
    log.info("─" * 60)
    log.info(f"  Procesando {len(todas)} personas activas...")

    stats_porton = {
        "agregado":    0,
        "eliminado":   0,
        "omitido":     0,
        "sin_telefono": 0,
        "error_ha":    0,
    }

    for i, persona in enumerate(todas, 1):
        nombre = f"{persona['first_name']} {persona['last_name']}".strip()
        acceso = persona.get("acceso_porton")
        log.info(f"[{i}/{len(todas)}] {nombre} | portón={acceso}")

        resultado = sincronizar_porton_ha(persona)
        stats_porton[resultado] = stats_porton.get(resultado, 0) + 1
        time.sleep(DELAY_ENTRE_LLAMADAS)

    # ── 6. Resumen final ──────────────────────────────────────────────────────
    log.info("")
    log.info("─" * 60)
    log.info("  RESUMEN FINAL")
    log.info("─" * 60)
    log.info("  Loyverse:")
    log.info(f"    Creados:      {stats_loyverse.get('creado', 0)}")
    log.info(f"    Actualizados: {stats_loyverse.get('actualizado', 0)}")
    log.info(f"    Simulados:    {stats_loyverse.get('simulado', 0)}")
    log.info(f"    Errores:      {stats_loyverse.get('error', 0)}")
    log.info("  Portón HA:")
    log.info(f"    Agregados:    {stats_porton.get('agregado', 0)}")
    log.info(f"    Eliminados:   {stats_porton.get('eliminado', 0)}")
    log.info(f"    Sin teléfono: {stats_porton.get('sin_telefono', 0)}")
    log.info(f"    Omitidos:     {stats_porton.get('omitido', 0)}")
    log.info(f"    Errores HA:   {stats_porton.get('error_ha', 0)}")
    log.info("─" * 60)
    log.info("  Sincronización completada.")


if __name__ == "__main__":
    main()
