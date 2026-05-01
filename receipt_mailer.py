#!/usr/bin/env python3
"""
==============================================================================
RECEIPT MAILER — Envío automático de comprobantes de venta por Gmail
El correo incluye el comprobante en HTML + PDF adjunto.
==============================================================================
"""

import os
import smtplib
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from datetime import datetime

log = logging.getLogger(__name__)

# ── Configuración ─────────────────────────────────────────────────────────────
GMAIL_USER     = os.environ["GMAIL_USER"]
GMAIL_APP_PASS = os.environ["GMAIL_APP_PASS"]
STORE_NAME     = os.getenv("STORE_NAME", "Cafetería IPDV")
STORE_SUBTITLE = os.getenv("STORE_SUBTITLE", "Cafetería IPDV")
STORE_SLOGAN   = os.getenv("STORE_SLOGAN", "El Señor guarde tu vida y seas luz y bendición a otros")
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


def _payment_label(payment_type: str | None) -> str:
    labels = {
        "CASH":         "Efectivo",
        "CARD":         "Tarjeta",
        "LOYALTY_CARD": "Tarjeta de fidelidad",
        "OTHER":        "Otro",
        "CUSTOM_1":     "Transferencia pendiente",
        "CUSTOM_2":     "Transferencia pendiente",
        "CUSTOM_3":     "Transferencia pendiente",
    }
    return labels.get((payment_type or "").upper(), payment_type or "—")


def _is_transfer(payment_type: str | None) -> bool:
    return "transferencia" in _payment_label(payment_type).lower()


# ── HTML compartido (email y PDF) ─────────────────────────────────────────────

def _build_receipt_html(receipt: dict, customer_name: str,
                        customer_phone: str = "",
                        for_pdf: bool = False) -> str:
    receipt_number = receipt.get("receipt_number", "—")
    created_at     = _fmt_date(receipt.get("created_at"))
    total          = _fmt_money(receipt.get("total_money"))
    payments       = receipt.get("payments", [])
    line_items     = receipt.get("line_items", [])
    employee_name  = receipt.get("employee_name", "")
    pos_device     = receipt.get("pos_device_name", "")

    has_transfer = any(_is_transfer(p.get("payment_type")) for p in payments)

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
        label    = _payment_label(p.get("payment_type"))
        amount   = _fmt_money(p.get("money_amount"))
        is_trans = _is_transfer(p.get("payment_type"))
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

    # Empleado / TPV
    employee_block = ""
    if employee_name or pos_device:
        parts = []
        if employee_name:
            parts.append(f"Empleado: {employee_name}")
        if pos_device:
            parts.append(f"TPV: {pos_device}")
        employee_block = f"""
        <tr>
          <td colspan="2" style="padding:4px 0 8px;font-size:11px;color:#999;
                                  border-bottom:1px solid #eeeeee;">
            {" &nbsp;|&nbsp; ".join(parts)}
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
          {employee_block}
          {customer_block}
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
      background: #ffffff;
      -webkit-print-color-adjust: exact;
      print-color-adjust: exact;
    }}
  </style>
</head>
<body>{card}</body>
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
        from weasyprint import HTML as WeasyHTML
        html_str  = _build_receipt_html(receipt, customer_name,
                                        customer_phone, for_pdf=True)
        pdf_bytes = WeasyHTML(string=html_str).write_pdf()
        return pdf_bytes
    except ImportError:
        log.warning("WeasyPrint no instalado — se omite el PDF adjunto.")
        return None
    except Exception as e:
        log.error(f"Error generando PDF: {e}")
        return None


# ── Función principal ─────────────────────────────────────────────────────────

def send_receipt_email(receipt: dict, customer_email: str,
                       customer_name: str, customer_phone: str = "") -> bool:
    receipt_number = receipt.get("receipt_number", "comprobante")
    subject = f"Tu comprobante de compra #{receipt_number} — {STORE_NAME}"

    msg            = MIMEMultipart("mixed")
    msg["Subject"] = subject
    msg["From"]    = f"{STORE_NAME} <{GMAIL_USER}>"
    msg["To"]      = customer_email

    # Cuerpo: texto plano + HTML
    alt_part   = MIMEMultipart("alternative")
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
    alt_part.attach(MIMEText(plain_text, "plain", "utf-8"))
    alt_part.attach(MIMEText(
        _build_receipt_html(receipt, customer_name, customer_phone, for_pdf=False),
        "html", "utf-8",
    ))
    msg.attach(alt_part)

    # PDF adjunto
    pdf_bytes = _generate_pdf(receipt, customer_name, customer_phone)
    if pdf_bytes:
        pdf_part = MIMEApplication(pdf_bytes, _subtype="pdf")
        pdf_part.add_header(
            "Content-Disposition",
            "attachment",
            filename=f"comprobante_{receipt_number}.pdf",
        )
        msg.attach(pdf_part)
        log.info(f"PDF generado ({len(pdf_bytes)} bytes) para receipt #{receipt_number}")
    else:
        log.warning(f"Enviando sin PDF para receipt #{receipt_number}")

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_USER, GMAIL_APP_PASS)
            server.sendmail(GMAIL_USER, customer_email, msg.as_string())
        log.info(f"✉️  Comprobante enviado a {customer_email} (receipt #{receipt_number})")
        return True
    except smtplib.SMTPAuthenticationError:
        log.error("Gmail: error de autenticación. Verifica GMAIL_USER y GMAIL_APP_PASS.")
    except smtplib.SMTPException as e:
        log.error(f"Gmail SMTP error: {e}")
    except Exception as e:
        log.error(f"Error inesperado al enviar email: {e}")
    return False
