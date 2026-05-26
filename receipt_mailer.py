#!/usr/bin/env python3
"""
==============================================================================
RECEIPT MAILER — Envío automático de comprobantes de venta por Gmail
El correo incluye el comprobante en HTML + PDF adjunto.
==============================================================================
"""

import os
import logging
import base64
import requests as http_requests
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from datetime import datetime
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request as GoogleRequest
from googleapiclient.discovery import build

log = logging.getLogger(__name__)

# ── Configuración ─────────────────────────────────────────────────────────────
GMAIL_USER      = os.getenv("GMAIL_USER", "it.ipdv@gmail.com")
GOOGLE_CLIENT_ID     = os.environ["GOOGLE_CLIENT_ID"]
GOOGLE_CLIENT_SECRET = os.environ["GOOGLE_CLIENT_SECRET"]
GOOGLE_REFRESH_TOKEN = os.environ["GOOGLE_REFRESH_TOKEN"]
STORE_NAME     = os.getenv("STORE_NAME", "Cafetería IPDV")
STORE_SUBTITLE = os.getenv("STORE_SUBTITLE", "Iglesia Presbiteriana del Valle de Lonquén")
STORE_SLOGAN   = os.getenv("STORE_SLOGAN", "El Señor guarde tu vida, seas luz y bendición (Núm. 6:24-25)")
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
    label = _payment_label(payment).lower()
    return "pendiente" in label


# ── HTML compartido (email y PDF) ─────────────────────────────────────────────

def _build_receipt_html(receipt: dict, customer_name: str,
                        customer_phone: str = "",
                        for_pdf: bool = False) -> str:
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
                width:360px;max-width:360px;font-family:Arial,sans-serif;overflow:hidden;
                {'margin:0 auto;' if for_pdf else ''}">

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

    if for_pdf:
        return f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <style>
    @page {{
      size: 90mm 220mm;
      margin: 5mm;
    }}
    body {{
      margin: 0;
      padding: 0;
      font-family: Arial, sans-serif;
      font-size: 12px;
      color: #333;
    }}
    .card {{
      width: 100%;
    }}
    .header {{
      text-align: center;
      border-bottom: 1px solid #eee;
      padding-bottom: 8px;
      margin-bottom: 8px;
    }}
    .logo {{
      max-height: 60px;
      max-width: 120px;
    }}
    .store-name {{
      font-size: 13px;
      font-weight: bold;
      margin: 4px 0 0;
    }}
    .slogan {{
      font-size: 9px;
      color: #aaa;
      font-style: italic;
    }}
    .total-block {{
      text-align: center;
      border-bottom: 1px solid #eee;
      padding: 8px 0;
      margin-bottom: 8px;
    }}
    .total-amount {{
      font-size: 28px;
      font-weight: bold;
    }}
    .total-label {{
      font-size: 9px;
      color: #bbb;
      text-transform: uppercase;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
    }}
    td {{
      padding: 4px 0;
      vertical-align: top;
    }}
    .meta {{
      font-size: 10px;
      color: #999;
      border-bottom: 1px solid #eee;
    }}
    .item-name {{
      font-size: 12px;
    }}
    .item-qty {{
      font-size: 10px;
      color: #888;
    }}
    .divider td {{
      border-bottom: 1px solid #eee;
      padding: 0;
      height: 1px;
    }}
    .total-row td {{
      font-weight: bold;
      font-size: 13px;
      padding-top: 6px;
    }}
    .bank-box {{
      background: {bank_bg};
      border: 1px solid {bank_border};
      padding: 6px 8px;
      margin-top: 8px;
      font-size: 10px;
    }}
    .bank-alert {{
      color: #b45309;
      font-weight: bold;
      margin-bottom: 3px;
    }}
    .transfer {{
      color: #b45309;
      font-weight: bold;
    }}
    .footer {{
      border-top: 1px solid #eee;
      margin-top: 8px;
      padding-top: 4px;
      font-size: 9px;
      color: #ccc;
    }}
    .footer-right {{
      text-align: right;
    }}
  </style>
</head>
<body>
<div class="card">

  <div class="header">
    <img src="{STORE_LOGO_URL}" class="logo" alt="{STORE_NAME}">
    <p class="store-name">{STORE_NAME}</p>
    <p class="slogan">{STORE_SLOGAN}</p>
  </div>

  <div class="total-block">
    <div class="total-amount">{total}</div>
    <div class="total-label">Total</div>
  </div>

  <table>
    {'<tr><td colspan="2" class="meta">' + " &nbsp;|&nbsp; ".join(([f"Empleado: {employee_name}"] if employee_name else []) + ([f"TPV: {pos_device}"] if pos_device else [])) + '</td></tr>' if employee_name or pos_device else ''}
    {'<tr><td colspan="2" style="font-size:11px;padding:4px 0;border-bottom:1px solid #eee;">Cliente: <b>' + customer_name + '</b>' + (f'<br/><span style="color:#999">{customer_phone}</span>' if customer_phone else '') + '</td></tr>' if customer_name else ''}
    {rows_html}
    <tr class="total-row">
      <td>Total</td>
      <td style="text-align:right">{total}</td>
    </tr>
    {payments_html}
  </table>

  <div class="bank-box">
    {'<div class="bank-alert">Pago pendiente por transferencia</div>' if has_transfer else ''}
    <div style="{'font-weight:bold;color:#78350f' if has_transfer else ''}">
      Transferencias a:<br/>
      <b>{BANK_HOLDER}</b><br/>
      {BANK_NAME}<br/>
      {BANK_ACCOUNT}<br/>
      {BANK_RUT}
    </div>
  </div>

  <table class="footer">
    <tr>
      <td>{created_at}</td>
      <td class="footer-right">N&deg; {receipt_number}</td>
    </tr>
  </table>

</div>
</body>
</html>"""
    else:
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


# ── Generador de PDF ──────────────────────────────────────────────────────────

def _generate_pdf(receipt: dict, customer_name: str,
                  customer_phone: str = "") -> bytes | None:
    try:
        from io import BytesIO
        from xhtml2pdf import pisa
        html_str = _build_receipt_html(receipt, customer_name,
                                       customer_phone, for_pdf=True)
        buf = BytesIO()
        result = pisa.CreatePDF(html_str, dest=buf)
        if result.err:
            log.error(f"xhtml2pdf error: {result.err}")
            return None
        return buf.getvalue()
    except ImportError:
        log.warning("xhtml2pdf no instalado — se omite el PDF adjunto.")
        return None
    except Exception as e:
        log.error(f"Error generando PDF: {e}")
        return None


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
    subject = f"Tu comprobante de compra #{receipt_number} — {STORE_NAME}"

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

    msg            = MIMEMultipart("mixed")
    msg["Subject"] = subject
    msg["From"]    = f"{STORE_NAME} <{GMAIL_USER}>"
    msg["To"]      = customer_email

    alt_part = MIMEMultipart("alternative")
    alt_part.attach(MIMEText(plain_text, "plain", "utf-8"))
    alt_part.attach(MIMEText(
        _build_receipt_html(receipt, customer_name, customer_phone, for_pdf=False),
        "html", "utf-8",
    ))
    msg.attach(alt_part)

    # PDF adjunto (opcional)
    pdf_bytes = _generate_pdf(receipt, customer_name, customer_phone)
    if pdf_bytes:
        pdf_part = MIMEApplication(pdf_bytes, _subtype="pdf")
        pdf_part.add_header(
            "Content-Disposition", "attachment",
            filename=f"comprobante_{receipt_number}.pdf",
        )
        msg.attach(pdf_part)
        log.info(f"PDF generado ({len(pdf_bytes)} bytes) para receipt #{receipt_number}")
    else:
        log.warning(f"Enviando sin PDF para receipt #{receipt_number}")

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
