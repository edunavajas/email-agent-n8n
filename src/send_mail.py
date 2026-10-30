# Envía la respuesta por SMTP en el mismo hilo (In-Reply-To y References).
#
# El nodo "Send Email" de n8n 2.10.2 no deja poner esas cabeceras, así que el
# envío lo hace un Code node de Python con la biblioteca estándar (smtplib).
# Corre en el contenedor de task runners. El servidor y la contraseña salen de
# sus variables SMTP_*, nunca del flujo: ver runners/n8n-task-runners.json.
#
# Este fichero lo copia scripts/build_workflows.py dentro de los nodos.
# scripts/check_mail.py lo prueba sin red.

import re
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

ADDRESS = re.compile(r"[^\s@,;:<>()\[\]\"'\\]+@[^\s@,;:<>()\[\]\"'\\]+\.[^\s@,;:<>()\[\]\"'\\]+")
MESSAGE_ID = re.compile(r"<[^<>\s]{3,250}>")


def one_line(value, limit=998):
    """Quita saltos de línea: un valor del correo no puede abrir otra cabecera."""
    return re.sub(r"[\r\n\t]+", " ", str(value or "")).strip()[:limit]


def thread_headers(message_id, references):
    """In-Reply-To y References para contestar a message_id.

    Si el correo no traía Message-ID (lo generó el flujo 01: generado-..., largo-...),
    no se inventa: se devuelve ("", "") y el correo sale sin hilo de cabeceras.
    """
    own = one_line(message_id, 300)
    if not own or own.startswith("generado-") or own.startswith("largo-"):
        return "", ""
    if not own.startswith("<"):
        own = "<" + own + ">"
    if not MESSAGE_ID.fullmatch(own):
        return "", ""
    chain = [item for item in MESSAGE_ID.findall(one_line(references, 4000)) if item != own]
    return own, " ".join(chain[-9:] + [own])


def build_reply(mail, sender, automatic):
    """Monta el EmailMessage. Lanza ValueError si falta algo o algo no cuadra."""
    to = one_line(mail.get("to"), 254).lower()
    if not ADDRESS.fullmatch(to):
        raise ValueError("dirección de destino no válida")
    sender = one_line(sender, 254).lower()
    if not ADDRESS.fullmatch(sender):
        raise ValueError("support_address no es una dirección válida")
    body = str(mail.get("body") or "").strip()
    if not body:
        raise ValueError("la respuesta está vacía")

    message = EmailMessage()
    message["From"] = sender
    message["To"] = to
    message["Reply-To"] = sender
    # Asunto vacío: "Re:" a secas. Con "Re: (sin asunto)" Gmail abre otro hilo.
    message["Subject"] = one_line(mail.get("subject")) or "Re:"
    message["Date"] = formatdate(usegmt=True)
    message["Message-ID"] = make_msgid(domain=sender.split("@", 1)[1])
    in_reply_to, references = thread_headers(mail.get("message_id"), mail.get("references"))
    if in_reply_to:
        message["In-Reply-To"] = in_reply_to
        message["References"] = references
    if automatic:
        # RFC 3834: otra autorespuesta no debe contestar a esta.
        message["Auto-Submitted"] = "auto-replied"
    message.set_content(body)
    return message


def smtp_settings(env):
    host = str(env.get("SMTP_HOST") or "").strip()
    if not host:
        raise ValueError("falta SMTP_HOST en el contenedor de task runners")
    port = int(str(env.get("SMTP_PORT") or "465").strip())
    security = str(env.get("SMTP_SECURITY") or ("ssl" if port == 465 else "starttls")).strip().lower()
    if security not in ("ssl", "starttls", "none"):
        raise ValueError("SMTP_SECURITY tiene que ser ssl, starttls o none")
    return {
        "host": host,
        "port": port,
        "security": security,
        "user": str(env.get("SMTP_USER") or "").strip(),
        "password": str(env.get("SMTP_PASSWORD") or ""),
    }


def deliver(message, smtp, timeout=30):
    """Envía por SMTP. Devuelve el diccionario de destinatarios rechazados."""
    context = ssl.create_default_context()
    if smtp["security"] == "ssl":
        client = smtplib.SMTP_SSL(smtp["host"], smtp["port"], timeout=timeout, context=context)
    else:
        client = smtplib.SMTP(smtp["host"], smtp["port"], timeout=timeout)
    try:
        if smtp["security"] == "starttls":
            client.starttls(context=context)
        if smtp["user"]:
            client.login(smtp["user"], smtp["password"])
        return client.send_message(message)
    finally:
        try:
            client.quit()
        except Exception:
            pass


def send_reply(mail, sender, automatic, env):
    """Lo que hace el nodo. Nunca lanza: devuelve sent y, si falla, el motivo."""
    try:
        message = build_reply(mail, sender, automatic)
        refused = deliver(message, smtp_settings(env))
        if refused:
            return {"sent": False, "reply_message_id": "", "smtp_error": "destinatario rechazado"}
        return {"sent": True, "reply_message_id": message["Message-ID"], "smtp_error": ""}
    except Exception as error:
        return {"sent": False, "reply_message_id": "", "smtp_error": one_line(error, 500) or "error SMTP"}
