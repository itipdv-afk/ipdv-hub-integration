#!/usr/bin/env python3
"""
==============================================================================
REGISTER WEBHOOK — Registra el webhook de receipts en Loyverse (ejecutar 1 vez)

Uso:
    python register_webhook.py            → lista webhooks existentes
    python register_webhook.py --register → registra el webhook de receipts
    python register_webhook.py --delete <id> → elimina un webhook por ID
==============================================================================
"""

import os
import sys
import json
import requests
from dotenv import load_dotenv

load_dotenv()

LOYVERSE_TOKEN = os.environ["LOYVERSE_TOKEN"]
RAILWAY_URL    = os.getenv("RAILWAY_URL", "https://loyverse-sync-production-1f02.up.railway.app")
LOYVERSE_BASE  = "https://api.loyverse.com/v1.0"

HEADERS = {
    "Authorization": f"Bearer {LOYVERSE_TOKEN}",
    "Content-Type": "application/json",
}

WEBHOOK_ENDPOINT = f"{RAILWAY_URL}/webhook/loyverse"


def list_webhooks():
    resp = requests.get(f"{LOYVERSE_BASE}/webhooks", headers=HEADERS, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    hooks = data.get("webhooks", [])
    if not hooks:
        print("No hay webhooks registrados.")
        return
    print(f"\n{'ID':<36}  {'Evento':<30}  URL")
    print("-" * 100)
    for h in hooks:
        print(f"{h['id']:<36}  {h['topic']:<30}  {h['callback_url']}")
    print()


def register_webhook():
    # Verificar si ya existe uno para receipts hacia nuestra URL
    resp = requests.get(f"{LOYVERSE_BASE}/webhooks", headers=HEADERS, timeout=30)
    resp.raise_for_status()
    existing = resp.json().get("webhooks", [])
    for h in existing:
        if h.get("topic") == "receipts" and h.get("callback_url") == WEBHOOK_ENDPOINT:
            print(f"✅ El webhook ya existe con ID: {h['id']}")
            print(f"   URL: {h['callback_url']}")
            return

    # Registrar nuevo webhook
    payload = {
        "topic":        "receipts",
        "callback_url": WEBHOOK_ENDPOINT,
        "format":       "JSON",
    }
    resp = requests.post(
        f"{LOYVERSE_BASE}/webhooks",
        headers=HEADERS,
        json=payload,
        timeout=30,
    )

    if resp.status_code in (200, 201):
        data = resp.json()
        print(f"✅ Webhook registrado correctamente.")
        print(f"   ID:    {data.get('id')}")
        print(f"   Topic: {data.get('topic')}")
        print(f"   URL:   {data.get('callback_url')}")
    else:
        print(f"❌ Error al registrar webhook: {resp.status_code}")
        print(resp.text)


def delete_webhook(webhook_id: str):
    resp = requests.delete(
        f"{LOYVERSE_BASE}/webhooks/{webhook_id}",
        headers=HEADERS,
        timeout=30,
    )
    if resp.status_code in (200, 204):
        print(f"✅ Webhook {webhook_id} eliminado.")
    else:
        print(f"❌ Error al eliminar: {resp.status_code} — {resp.text}")


if __name__ == "__main__":
    args = sys.argv[1:]

    if not args:
        print("Webhooks actuales en Loyverse:")
        list_webhooks()
        print("Uso:")
        print("  python register_webhook.py --register        → registrar webhook de receipts")
        print("  python register_webhook.py --delete <id>     → eliminar webhook por ID")

    elif args[0] == "--register":
        print(f"Registrando webhook hacia: {WEBHOOK_ENDPOINT}")
        register_webhook()

    elif args[0] == "--delete" and len(args) > 1:
        delete_webhook(args[1])

    else:
        print("Uso:")
        print("  python register_webhook.py")
        print("  python register_webhook.py --register")
        print("  python register_webhook.py --delete <webhook_id>")
