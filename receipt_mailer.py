#!/usr/bin/env python3
"""
==============================================================================
RECEIPT MAILER — Envío automático de comprobantes de venta por Gmail API
==============================================================================
"""

import os
import logging
import base64
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request as GoogleRequest
from googleapiclient.discovery import build

log = logging.getLogger(__name__)

# ── Configuración ─────────────────────────────────────────────────────────────
GMAIL_USER           = os.getenv("GMAIL_USER", "it.ipdv@gmail.com")
GOOGLE_CLIENT_ID     = os.environ["GOOGLE_CLIENT_ID"]
GOOGLE_CLIENT_SECRET = os.environ["GOOGLE_CLIENT_SECRET"]
GOOGLE_REFRESH_TOKEN = os.environ["GOOGLE_REFRESH_TOKEN"]
STORE_NAME     = os.getenv("STORE_NAME",     "Cafetería IPDV")
STORE_SUBTITLE = os.getenv("STORE_SUBTITLE", "Iglesia Presbiteriana del Valle de Lonquén")
STORE_SLOGAN   = os.getenv("STORE_SLOGAN",   "El Señor guarde tu vida, seas luz y bendición (Núm. 6:24-25)")
STORE_LOGO_URL = os.getenv("STORE_LOGO_URL", "https://res.cloudinary.com/dtbnavw3j/image/upload/v1777608874/Logo_IPDV_k0fstz.png")

BANK_NAME    = os.getenv("BANK_NAME",    "Banco Estado")
BANK_ACCOUNT = os.getenv("BANK_ACCOUNT", "Cuenta corriente 2950413")
BANK_RUT     = os.getenv("BANK_RUT",     "RUT: 65020958-3")
BANK_HOLDER  = os.getenv("BANK_HOLDER",  "Iglesia IPDV")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fmt_money(amount) -> str:
    try:
        val = float(amount)
        return f"${val:,.0f}".replace(",", ".")
    except (TypeError, ValueError):
        return str(amount) if amount else "$0"


def _fmt_date(iso_str: str | None) -> str:
    if not iso_str:
        return ""
    try:
        dt = datetime.strptime(iso_str[:19], "%Y-%m-%dT%H:%M:%S")
        return dt.strftime("%d-%m-%y %H:%M")
    except ValueError:
        return iso_str


def _payment_label(payment: dict) -> str:
    """Usa el campo 'name' del payment si está disponible, si no el tipo genérico."""
    name = (payment.get("name") or "").strip()
    if name:
        return name
    ptype = (payment.get("type") or payment.get("payment_type") or "").upper()
    labels = {
        "CASH":         "Efectivo",
        "CARD":         "Tarjeta",
        "LOYALTY_CARD": "Tarjeta de fidelidad",
    }
    return labels.get(ptype, ptype or "—")


def _is_transfer(payment: dict) -> bool:
    """Detecta si el pago es transferencia pendiente por el nombre."""
    return "pendiente" in _payment_label(payment).lower()


# ── HTML del comprobante ──────────────────────────────────────────────────────

def _build_receipt_html(receipt: dict, customer_name: str,
                        customer_phone: str = "") -> str:
    receipt_number = receipt.get("receipt_number", "—")
    created_at     = _fmt_date(receipt.get("created_at"))
    total          = _fmt_money(receipt.get("total_money"))
    payments       = receipt.get("payments", [])
    line_items     = receipt.get("line_items", [])
    note           = (receipt.get("note") or "").strip()
    order          = (receipt.get("order") or "").strip()

    has_transfer = any(_is_transfer(p) for p in payments)

    # Filas de productos
    rows_html = ""
    for item in line_items:
        name  = item.get("item_name") or item.get("variant_name") or "Producto"
        qty   = item.get("quantity", 1)
        price = _fmt_money(item.get("total_money"))
        unit  = _fmt_money(item.get("price"))
        rows_html += f"""
        <tr>
          <td style="padding:6px 0;font-size:13px;color:#333;border-bottom:1px solid #eeeeee;">
            {name}<br>
            <span style="font-size:11px;color:#888;">{int(float(qty))} x {unit}</span>
          </td>
          <td style="padding:6px 0;font-size:13px;color:#333;text-align:right;
                     border-bottom:1px solid #eeeeee;vertical-align:top;">{price}</td>
        </tr>"""

    # Filas de pagos
    payments_html = ""
    for p in payments:
        label    = _payment_label(p)
        amount   = _fmt_money(p.get("money_amount"))
        is_trans = _is_transfer(p)
        style    = "font-weight:bold;color:#b45309;" if is_trans else "color:#666;"
        payments_html += f"""
        <tr>
          <td style="padding:3px 0;font-size:12px;{style}">{label}</td>
          <td style="padding:3px 0;font-size:12px;text-align:right;{style}">{amount}</td>
        </tr>"""

    # Datos bancarios
    bank_notice = (
        "<p style='margin:0 0 4px;font-size:11px;color:#b45309;font-weight:bold;'>"
        "Pago pendiente por transferencia</p>"
    ) if has_transfer else ""
    bank_bg     = "#fffbeb" if has_transfer else "#f9f9f9"
    bank_border = "#fcd34d" if has_transfer else "#e5e5e5"
    bank_text   = "font-weight:bold;color:#78350f;" if has_transfer else "color:#555;"

    bank_block = f"""
        <tr>
          <td colspan="2" style="padding-top:14px;">
            <div style="background:{bank_bg};border:1px solid {bank_border};
                        border-radius:6px;padding:10px 12px;">
              {bank_notice}
              <p style="margin:0;font-size:11px;{bank_text}">
                Transferencias a:<br>
                <strong>{BANK_HOLDER}</strong><br>
                {BANK_NAME}<br>
                {BANK_ACCOUNT}<br>
                {BANK_RUT}
              </p>
            </div>
          </td>
        </tr>"""

    # Pedido (order)
    order_block = ""
    if order:
        order_block = f"""
        <tr>
          <td colspan="2" style="padding:4px 0 8px;font-size:11px;color:#999;
                                  border-bottom:1px solid #eeeeee;">
            Pedido: {order}
          </td>
        </tr>"""

    # Cliente
    customer_block = ""
    if customer_name or customer_phone:
        phone_line = (
            f"<br><span style='color:#999;font-size:11px;'>{customer_phone}</span>"
            if customer_phone else ""
        )
        customer_block = f"""
        <tr>
          <td colspan="2" style="padding:6px 0 8px;font-size:12px;color:#333;
                                  border-bottom:1px solid #eeeeee;">
            Cliente: <strong>{customer_name}</strong>{phone_line}
          </td>
        </tr>"""

    # Nota del cajero
    note_block = ""
    if note:
        note_block = f"""
        <tr>
          <td colspan="2" style="padding:6px 0 8px;font-size:11px;color:#666;
                                  font-style:italic;border-bottom:1px solid #eeeeee;">
            {note}
          </td>
        </tr>"""

    card = f"""
    <div style="background:#ffffff;border-radius:8px;border:1px solid #e0e0e0;
                width:360px;max-width:360px;font-family:Arial,sans-serif;overflow:hidden;">

      <div style="padding:20px 28px 14px;text-align:center;border-bottom:1px solid #eeeeee;">
        <img src="{STORE_LOGO_URL}" alt="{STORE_NAME}"
             style="max-height:72px;max-width:140px;object-fit:contain;
                    display:block;margin:0 auto 10px;">
        <p style="margin:0;font-size:14px;font-weight:bold;color:#222;">{STORE_NAME}</p>
        <p style="margin:2px 0 0;font-size:11px;color:#777;">{STORE_SUBTITLE}</p>
        <p style="margin:4px 0 0;font-size:10px;color:#aaa;font-style:italic;">{STORE_SLOGAN}</p>
      </div>

      <div style="padding:18px 28px 14px;text-align:center;border-bottom:1px solid #eeeeee;">
        <p style="margin:0;font-size:34px;font-weight:bold;color:#111;">{total}</p>
        <p style="margin:4px 0 0;font-size:10px;color:#bbb;letter-spacing:1px;
                  text-transform:uppercase;">Total</p>
      </div>

      <div style="padding:14px 28px;">
        <table style="width:100%;border-collapse:collapse;">
          {order_block}
          {customer_block}
          {note_block}
          {rows_html}
          <tr>
            <td style="padding:8px 0 4px;font-size:14px;font-weight:bold;color:#111;">Total</td>
            <td style="padding:8px 0 4px;font-size:14px;font-weight:bold;
                       text-align:right;color:#111;">{total}</td>
          </tr>
          {payments_html}
          {bank_block}
        </table>
      </div>

      <div style="padding:10px 28px 16px;border-top:1px solid #eeeeee;">
        <table style="width:100%;border-collapse:collapse;">
          <tr>
            <td style="font-size:10px;color:#ccc;">{created_at}</td>
            <td style="font-size:10px;color:#ccc;text-align:right;">N&deg; {receipt_number}</td>
          </tr>
        </table>
      </div>

    </div>"""

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
</head>
<body style="margin:0;padding:0;background:#f0f0f0;font-family:Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0"
         style="background:#f0f0f0;padding:28px 0;">
    <tr><td align="center">{card}</td></tr>
  </table>
</body>
</html>"""


# ── Gmail API ─────────────────────────────────────────────────────────────────

def _get_gmail_service():
    """Obtiene el servicio de Gmail API con credenciales OAuth2."""
    creds = Credentials(
        token=None,
        refresh_token=GOOGLE_REFRESH_TOKEN,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
        scopes=["https://www.googleapis.com/auth/gmail.send"],
    )
    creds.refresh(GoogleRequest())
    return build("gmail", "v1", credentials=creds)


# ── Función principal ─────────────────────────────────────────────────────────

def send_receipt_email(receipt: dict, customer_email: str,
                       customer_name: str, customer_phone: str = "") -> bool:
    receipt_number = receipt.get("receipt_number", "comprobante")
    subject        = f"Recibo de {STORE_NAME}"

    total      = _fmt_money(receipt.get("total_money"))
    created_at = _fmt_date(receipt.get("created_at"))
    plain_text = (
        f"Hola {customer_name},\n\n"
        f"Gracias por tu compra en {STORE_NAME}.\n\n"
        f"Comprobante N°: {receipt_number}\n"
        f"Fecha: {created_at}\n"
        f"Total: {total}\n\n"
        f"Transferencias a: {BANK_HOLDER} | {BANK_NAME} | "
        f"{BANK_ACCOUNT} | {BANK_RUT}\n\n"
        f"Este correo fue generado automáticamente."
    )

    msg            = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = f"{STORE_NAME} <{GMAIL_USER}>"
    msg["To"]      = customer_email

    msg.attach(MIMEText(plain_text, "plain", "utf-8"))
    msg.attach(MIMEText(
        _build_receipt_html(receipt, customer_name, customer_phone),
        "html", "utf-8",
    ))

    try:
        service = _get_gmail_service()
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
        service.users().messages().send(
            userId="me",
            body={"raw": raw},
        ).execute()
        log.info(f"✉️  Comprobante enviado a {customer_email} (receipt #{receipt_number})")
        return True
    except Exception as e:
        log.error(f"Error enviando email via Gmail API: {e}")
        return False
