#!/usr/bin/env python3
"""
==============================================================================
  WEBHOOK: Servidor HTTP que recibe eventos de PCO en tiempo real
  Railway lo mantiene siempre activo. Cada vez que PCO modifica o crea
  una persona, llama a este endpoint y se sincroniza solo esa persona.
==============================================================================
"""

import os
import json
import logging
from flask import Flask, request, jsonify
from sync_core import (
    log, WEBHOOK_SECRET, EDAD_MINIMA,
    cargar_field_definitions, obtener_persona_pco,
    cumple_condiciones, sincronizar_persona,
    verificar_firma_pco
)

app = Flask(__name__)

# Cargamos las field definitions al iniciar el servidor (no en cada request)
_field_definitions = None

def get_field_definitions():
    global _field_definitions
    if _field_definitions is None:
        _field_definitions = cargar_field_definitions()
    return _field_definitions


@app.route("/health", methods=["GET"])
def health():
    """Endpoint de salud — Railway lo usa para verificar que el servidor está vivo."""
    return jsonify({"status": "ok"}), 200


@app.route("/webhook/pco", methods=["POST"])
def webhook_pco():
    """
    Recibe eventos de PCO People.
    Eventos procesados:
      - people.v2.events.person.created
      - people.v2.events.person.updated
    """
    # 1. Verificar firma de PCO
    raw_body  = request.get_data()
    signature = request.headers.get("X-PCO-Webhooks-Authenticity", "")

    if WEBHOOK_SECRET and not verificar_firma_pco(raw_body, signature):
        log.warning("Webhook rechazado: firma inválida.")
        return jsonify({"error": "Firma inválida"}), 401

    # 2. Parsear el payload
    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        log.warning("Webhook rechazado: JSON inválido.")
        return jsonify({"error": "JSON inválido"}), 400

    # 3. Confirmar inmediatamente a PCO (debe responder en < 30s)
    # El procesamiento real ocurre después
    evento = payload.get("name", "")
    log.info(f"Webhook recibido: {evento}")

    if evento not in ("people.v2.events.person.created",
                      "people.v2.events.person.updated"):
        log.info(f"Evento ignorado: {evento}")
        return jsonify({"status": "ignorado", "evento": evento}), 200

    # 4. Obtener el ID de la persona desde el payload de PCO
    try:
        person_id = (payload["data"][0]["relationships"]["person"]["data"]["id"])
    except (KeyError, IndexError, TypeError):
        log.warning(f"No se pudo extraer person_id del payload: {payload}")
        return jsonify({"error": "person_id no encontrado"}), 400

    log.info(f"Procesando persona PCO ID: {person_id}")

    # 5. Obtener datos completos de la persona desde PCO
    field_defs = get_field_definitions()
    persona    = obtener_persona_pco(person_id, field_defs)

    if not persona:
        log.warning(f"No se encontró la persona {person_id} en PCO.")
        return jsonify({"status": "persona no encontrada"}), 200

    nombre = f"{persona['first_name']} {persona['last_name']}".strip()
    log.info(f"Persona: {nombre} | edad={persona['edad']} | "
             f"RUT={persona.get('rut') or 'N/A'} | email={persona.get('email') or 'N/A'}")

    # 6. Verificar condiciones
    cumple, motivo = cumple_condiciones(persona)
    if not cumple:
        log.info(f"Persona excluida ({motivo}): {nombre}")
        return jsonify({"status": "excluido", "motivo": motivo}), 200

    # 7. Sincronizar con Loyverse
    resultado = sincronizar_persona(persona)
    log.info(f"Resultado para {nombre}: {resultado}")

    return jsonify({
        "status":    resultado,
        "persona":   nombre,
        "pco_id":    person_id,
    }), 200


if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    log.info(f"Iniciando servidor webhook en puerto {port}...")
    app.run(host="0.0.0.0", port=port)
