#!/usr/bin/env python3
"""
==============================================================================
WEBHOOK: Servidor HTTP que recibe eventos de PCO, Loyverse y HA en tiempo real
==============================================================================
"""

import os
import json
import logging
from flask import Flask, request, jsonify
from sync_core import (
    log, WEBHOOK_SECRET, WEBHOOK_SECRET_UPDATED,
    cargar_field_definitions, obtener_persona_pco,
    cumple_condiciones, sincronizar_persona,
    verificar_firma_pco, loyverse_get,
    sincronizar_porton_ha,
)
from receipt_mailer import send_receipt_email

app = Flask(__name__)

_field_definitions = None


def get_field_definitions():
    global _field_definitions
    if _field_definitions is None:
        _field_definitions = cargar_field_definitions()
    return _field_definitions


# ── Health check ──────────────────────────────────────────────────────────────

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200


@app.route("/debug/tailscale", methods=["GET"])
def debug_tailscale():
    import subprocess
    result = subprocess.run(["tailscale", "status"], capture_output=True, text=True)
    return jsonify({"output": result.stdout, "error": result.stderr})
    
    
# ── Webhook PCO ───────────────────────────────────────────────────────────────

@app.route("/webhook/pco", methods=["POST"])
def webhook_pco():
    raw_body  = request.get_data()
    signature = request.headers.get("X-Pco-Webhooks-Authenticity", "")

    if not verificar_firma_pco(raw_body, signature):
        log.warning("Webhook PCO rechazado: firma inválida.")
        return jsonify({"error": "Firma inválida"}), 401

    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        log.warning("Webhook PCO rechazado: JSON inválido.")
        return jsonify({"error": "JSON inválido"}), 400

    try:
        evento_data = payload["data"][0]
        evento      = evento_data["attributes"]["name"]
        persona_raw = json.loads(evento_data["attributes"]["payload"])
        person_id   = persona_raw["data"]["id"]
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as e:
        log.warning(f"No se pudo parsear el payload de PCO: {e}")
        return jsonify({"error": "Payload inválido"}), 400

    log.info(f"Webhook PCO recibido: {evento} | person_id: {person_id}")

    if evento not in ("people.v2.events.person.created",
                      "people.v2.events.person.updated"):
        log.info(f"Evento PCO ignorado: {evento}")
        return jsonify({"status": "ignorado", "evento": evento}), 200

    field_defs = get_field_definitions()
    persona    = obtener_persona_pco(person_id, field_defs)

    if not persona:
        log.warning(f"No se encontró la persona {person_id} en PCO.")
        return jsonify({"status": "persona no encontrada"}), 200

    nombre = f"{persona['first_name']} {persona['last_name']}".strip()
    log.info(
        f"Persona: {nombre} | edad={persona['edad']} | "
        f"RUT={persona.get('rut') or 'N/A'} | "
        f"email={persona.get('email') or 'N/A'} | "
        f"portón={persona.get('acceso_porton') or 'N/A'}"
    )

    # ── Sincronización Loyverse ───────────────────────────────────────────────
    cumple, motivo = cumple_condiciones(persona)
    if cumple:
        resultado_loyverse = sincronizar_persona(persona)
        log.info(f"Loyverse [{resultado_loyverse}]: {nombre}")
    else:
        resultado_loyverse = f"excluido ({motivo})"
        log.info(f"Loyverse excluido ({motivo}): {nombre}")

    # ── Sincronización portón → Home Assistant ────────────────────────────────
    resultado_porton = sincronizar_porton_ha(persona)
    log.info(f"Portón HA [{resultado_porton}]: {nombre}")

    return jsonify({
        "status":          "ok",
        "persona":         nombre,
        "pco_id":          person_id,
        "loyverse":        resultado_loyverse,
        "porton_ha":       resultado_porton,
        "acceso_porton":   persona.get("acceso_porton"),
    }), 200


# ── Webhook Loyverse (comprobantes) ───────────────────────────────────────────

@app.route("/webhook/loyverse", methods=["POST"])
def webhook_loyverse():
    """
    Recibe eventos de receipts desde Loyverse.
    Si la venta tiene un cliente con email, envía el comprobante automáticamente.
    """
    try:
        payload = request.get_json(force=True, silent=True)
        if not payload:
            log.warning("Webhook Loyverse: payload vacío o JSON inválido.")
            return jsonify({"error": "JSON inválido"}), 400
    except Exception as e:
        log.warning(f"Webhook Loyverse: error parseando JSON: {e}")
        return jsonify({"error": "JSON inválido"}), 400

    receipts = payload.get("receipts") if isinstance(payload, dict) else None
    if receipts is None:
        receipts = [payload]

    processed = 0
    skipped   = 0

    for receipt in receipts:
        receipt_number = receipt.get("receipt_number", "—")
        customer_id    = receipt.get("customer_id")

        log.info(f"Loyverse receipt recibido: #{receipt_number} | customer_id: {customer_id or 'ninguno'}")

        if not customer_id:
            log.info(f"Receipt #{receipt_number}: sin cliente, se omite.")
            skipped += 1
            continue

        try:
            customer_data  = loyverse_get(f"/customers/{customer_id}")
            customer_email = customer_data.get("email") or ""
            customer_name  = customer_data.get("name") or "Cliente"
        except Exception as e:
            log.error(f"Error obteniendo cliente {customer_id}: {e}")
            skipped += 1
            continue

        if not customer_email.strip():
            log.info(f"Receipt #{receipt_number}: cliente '{customer_name}' sin email, se omite.")
            skipped += 1
            continue

        ok = send_receipt_email(receipt, customer_email.strip(), customer_name)
        if ok:
            processed += 1
        else:
            skipped += 1

    return jsonify({
        "status":   "ok",
        "enviados": processed,
        "omitidos": skipped,
    }), 200


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    log.info(f"Iniciando servidor webhook en puerto {port}...")
    app.run(host="0.0.0.0", port=port)
