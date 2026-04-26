#!/usr/bin/env python3
"""
==============================================================================
  CRON: Sincronización completa PCO People → Loyverse
  Se ejecuta de forma programada (domingos 03:00 AM hora Chile).
  También puede ejecutarse manualmente: python cron.py
==============================================================================
"""

import time
import logging
from collections import Counter
from sync_core import (
    log, DRY_RUN, PCO_RUT_FILTER, EDAD_MINIMA, DELAY_ENTRE_LLAMADAS,
    obtener_personas_pco, cumple_condiciones, sincronizar_persona
)


def main():
    log.info("=" * 60)
    log.info("  INICIO SINCRONIZACIÓN COMPLETA PCO → Loyverse (CRON)")
    log.info("=" * 60)

    if DRY_RUN:
        log.warning("⚠️  MODO DRY RUN: No se escribirá nada en Loyverse.")

    # 1. Obtener personas activas desde PCO
    todas = obtener_personas_pco()

    # Filtro de prueba por RUT individual
    if PCO_RUT_FILTER:
        log.warning(f"⚠️  FILTRO ACTIVO: procesando solo RUT {PCO_RUT_FILTER}")
        todas = [p for p in todas if p.get("rut") == PCO_RUT_FILTER]

    # 2. Clasificar exclusiones
    sin_edad  = [p for p in todas if p["edad"] is None]
    menores   = [p for p in todas if p["edad"] is not None and p["edad"] < EDAD_MINIMA]
    sin_rut   = [p for p in todas if p["edad"] is not None and p["edad"] >= EDAD_MINIMA
                 and not p.get("rut")]
    sin_email = [p for p in todas if p["edad"] is not None and p["edad"] >= EDAD_MINIMA
                 and p.get("rut") and not p.get("email")]

    candidatos = [p for p in todas
                  if p["edad"] is not None and p["edad"] >= EDAD_MINIMA
                  and p.get("rut") and p.get("email")]

    # 3. Detectar emails duplicados en PCO
    conteo_emails     = Counter(p["email"].lower() for p in candidatos)
    emails_duplicados = {e for e, c in conteo_emails.items() if c > 1}
    email_dup         = [p for p in candidatos if p["email"].lower() in emails_duplicados]
    a_sincronizar     = [p for p in candidatos if p["email"].lower() not in emails_duplicados]

    # 4. Resumen de exclusiones
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

    if not a_sincronizar:
        log.warning("No hay personas que cumplan todos los requisitos. Fin.")
        return

    # 5. Sincronizar con Loyverse
    log.info("")
    stats = {"creado": 0, "actualizado": 0, "simulado": 0, "error": 0}

    for i, persona in enumerate(a_sincronizar, 1):
        nombre = f"{persona['first_name']} {persona['last_name']}".strip()
        log.info(f"[{i}/{len(a_sincronizar)}] {nombre} "
                 f"(edad={persona['edad']}, RUT={persona['rut']}, email={persona['email']})")

        resultado = sincronizar_persona(persona)
        stats[resultado] = stats.get(resultado, 0) + 1
        time.sleep(DELAY_ENTRE_LLAMADAS)

    # 6. Resumen final
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
