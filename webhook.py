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
    raw_body  = request.get_data()
    signature = request.headers.get("X-PCO-Webhooks-Authenticity", "")

    # Log de todo lo que llega — para diagnóstico
    log.info(f"=== WEBHOOK RECIBIDO ===")
    log.info(f"Headers: {dict(request.headers)}")
    log.info(f"Body: {raw_body[:500]}")
    log.info(f"Firma: {signature[:30] if signature else 'NINGUNA'}")

    # Verificación desactivada temporalmente
    # if WEBHOOK_SECRET and not verificar_firma_pco(raw_body, signature):
    #     return jsonify({"error": "Firma inválida"}), 401

    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        log.warning("JSON inválido.")
        return jsonify({"error": "JSON inválido"}), 400

    evento = payload.get("name", "")
    log.info(f"Evento: {evento}")

    return jsonify({"status": "recibido"}), 200


if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    log.info(f"Iniciando servidor webhook en puerto {port}...")
    app.run(host="0.0.0.0", port=port)
