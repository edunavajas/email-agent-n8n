#!/usr/bin/env python3
"""Prueba src/send_mail.py sin red: un SMTP falso recoge lo que se enviaría."""

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("send_mail", ROOT / "src" / "send_mail.py")
send_mail = importlib.util.module_from_spec(spec)
spec.loader.exec_module(send_mail)

SENT = []


class FakeSMTP:
    def __init__(self, host, port, timeout=None, context=None):
        self.calls = [("connect", host, port, context is not None)]

    def starttls(self, context=None):
        self.calls.append(("starttls",))

    def login(self, user, password):
        self.calls.append(("login", user))

    def send_message(self, message):
        SENT.append((message, self.calls))
        return {}

    def quit(self):
        pass


send_mail.smtplib.SMTP = FakeSMTP
send_mail.smtplib.SMTP_SSL = FakeSMTP

ENV = {"SMTP_HOST": "smtp.tudominio.com", "SMTP_PORT": "465", "SMTP_USER": "soporte@tudominio.com", "SMTP_PASSWORD": "x"}
MAIL = {
    "to": "ana@cliente.example",
    "subject": "Re: Horario de soporte",
    "body": "Atendemos de lunes a viernes de 9:00 a 18:00.",
    "message_id": "ep3-01-consulta-clara@cliente.example",
    "references": "<a1@cliente.example> <a2@cliente.example>",
}

# Hilo: In-Reply-To es el Message-ID del cliente y References acaba en él.
result = send_mail.send_reply(MAIL, "soporte@tudominio.com", True, ENV)
assert result["sent"], result
message, calls = SENT[-1]
assert message["In-Reply-To"] == "<ep3-01-consulta-clara@cliente.example>", message["In-Reply-To"]
assert message["References"].split() == ["<a1@cliente.example>", "<a2@cliente.example>", "<ep3-01-consulta-clara@cliente.example>"]
assert message["Auto-Submitted"] == "auto-replied"
assert message["Message-ID"].endswith("@tudominio.com>") and message["Message-ID"] == result["reply_message_id"]
assert calls[0][3] is True and ("login", "soporte@tudominio.com") in calls, calls  # 465 = SSL implícito

# Respuesta aprobada por una persona: sin Auto-Submitted. STARTTLS en 587.
result = send_mail.send_reply(MAIL, "soporte@tudominio.com", False, {**ENV, "SMTP_PORT": "587"})
message, calls = SENT[-1]
assert result["sent"] and message["Auto-Submitted"] is None
assert ("starttls",) in calls, calls

# Sin Message-ID real (lo generó el flujo 01): sin cabeceras de hilo, pero sale.
result = send_mail.send_reply({**MAIL, "message_id": "generado-abc", "references": ""}, "soporte@tudominio.com", True, ENV)
message, _ = SENT[-1]
assert result["sent"] and message["In-Reply-To"] is None and message["References"] is None

# Cabeceras del cliente con saltos de línea: no abren cabeceras nuevas.
result = send_mail.send_reply({**MAIL, "subject": "Re: hola\r\nBcc: victima@otro.example", "references": "<x@y.example>\r\nBcc: victima@otro.example"}, "soporte@tudominio.com", True, ENV)
message, _ = SENT[-1]
assert result["sent"] and message["Bcc"] is None, message.as_string()
assert "victima" not in message["References"]

# Asunto vacío: "Re:" a secas, para que Gmail lo meta en el hilo. Un "Re:" que ya venía se conserva.
for subject in ("", None, " \r\n "):
    result = send_mail.send_reply({**MAIL, "subject": subject}, "soporte@tudominio.com", True, ENV)
    message, _ = SENT[-1]
    assert result["sent"] and message["Subject"] == "Re:", repr(message["Subject"])
result = send_mail.send_reply(MAIL, "soporte@tudominio.com", True, ENV)
assert SENT[-1][0]["Subject"] == "Re: Horario de soporte", SENT[-1][0]["Subject"]

# Un To con dos direcciones no sale.
before = len(SENT)
result = send_mail.send_reply({**MAIL, "to": "ana@cliente.example, otra@tercero.example"}, "soporte@tudominio.com", True, ENV)
assert not result["sent"] and "destino" in result["smtp_error"] and len(SENT) == before

# Cuerpo vacío o sin SMTP_HOST: no se envía y se dice por qué.
assert "vacía" in send_mail.send_reply({**MAIL, "body": "  "}, "soporte@tudominio.com", True, ENV)["smtp_error"]
assert "SMTP_HOST" in send_mail.send_reply(MAIL, "soporte@tudominio.com", True, {})["smtp_error"]

# Un fallo del servidor no revienta el nodo: vuelve como smtp_error.
class BrokenSMTP(FakeSMTP):
    def login(self, user, password):
        raise send_mail.smtplib.SMTPAuthenticationError(535, b"5.7.8 Error: authentication failed")


send_mail.smtplib.SMTP_SSL = BrokenSMTP
result = send_mail.send_reply(MAIL, "soporte@tudominio.com", True, ENV)
assert not result["sent"] and "535" in result["smtp_error"] and "x" != result["smtp_error"], result

print("check_mail ok")
sys.exit(0)
