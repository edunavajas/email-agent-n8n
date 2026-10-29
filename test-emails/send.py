#!/usr/bin/env python3
"""Envía los .eml de esta carpeta al buzón del agente.

Lee el .env de la raíz del repo. No imprime contraseñas ni direcciones.

Si hay CLIENT_EMAIL y CLIENT_PASSWORD, manda desde ese buzón cliente
(CLIENT_SMTP_HOST, CLIENT_SMTP_PORT). Si no, usa SMTP_* como antes.
Reescribe To (IMAP_USER) y From (nombre del .eml + buzón que envía). Gmail
reescribe el From si no es de la cuenta; así queda explícito.

Cada envío lleva un Message-ID nuevo: Gmail descarta en silencio un correo
cuyo Message-ID ya tiene. Los ids se guardan en .ultimo-envio.json.
Con --resend 01 se reutiliza el id de ese último envío (prueba de duplicados).
--dry-run monta los mensajes y dice qué enviaría, sin conectarse.
"""

import argparse
import json
import secrets
import smtplib
import ssl
import sys
import time
from email import policy
from email.parser import Parser
from email.utils import formataddr, parseaddr
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FOLDER = Path(__file__).resolve().parent
LAST = FOLDER / ".ultimo-envio.json"


def load_env(path: Path) -> dict:
    values = {}
    if not path.exists():
        sys.exit(f"Falta {path}. Copia .env.example a .env.")
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def load_last() -> dict:
    if LAST.exists():
        try:
            return json.loads(LAST.read_text(encoding="utf-8"))
        except ValueError:
            return {}
    return {}


def build(path: Path, target: str, sender: str, message_id: str) -> tuple:
    """Devuelve (mensaje en bytes, Message-ID) con To, From y Message-ID reescritos.

    Solo se tocan las tres cabeceras. El resto del .eml sale tal cual.
    """
    raw = path.read_text(encoding="utf-8")
    head, separator, body = raw.partition("\n\n")
    message = Parser(policy=policy.default).parsestr(head + "\n\n")
    name, _ = parseaddr(str(message["from"] or ""))
    lines = []
    for line in head.splitlines():
        if line.lower().startswith(("to:", "from:", "message-id:")):
            continue
        lines.append(line)
    lines += [
        f"From: {formataddr((name, sender), charset='utf-8')}",
        f"To: {target}",
        f"Message-ID: {message_id}",
    ]
    text = "\r\n".join(lines) + "\r\n\r\n" + body.replace("\n", "\r\n")
    return text.encode("utf-8"), message_id


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--resend", help="Prefijo del fichero que se reenvía con el mismo Message-ID, por ejemplo 01")
    parser.add_argument("--only", help="Prefijo de un solo correo")
    parser.add_argument("--dry-run", action="store_true", help="Monta los mensajes y no se conecta")
    args = parser.parse_args()
    env = load_env(ROOT / ".env")

    target = env["IMAP_USER"]
    if env.get("CLIENT_EMAIL") and env.get("CLIENT_PASSWORD"):
        user = sender = env["CLIENT_EMAIL"]
        password = env["CLIENT_PASSWORD"]
        host = env.get("CLIENT_SMTP_HOST", "smtp.gmail.com")
        port = int(env.get("CLIENT_SMTP_PORT", "465"))
    else:
        host = env["SMTP_HOST"]
        port = int(env.get("SMTP_PORT", "465"))
        user = sender = env["SMTP_USER"]
        password = env["SMTP_PASSWORD"]
    domain = sender.rsplit("@", 1)[-1]

    files = sorted(FOLDER.glob("*.eml"))
    if args.only:
        files = [path for path in files if path.name.startswith(args.only)]
    if args.resend:
        files = [path for path in files if path.name.startswith(args.resend)]
    if not files:
        sys.exit("No hay correos que enviar.")

    last = load_last()
    stamp = f"{int(time.time())}.{secrets.token_hex(3)}"
    plan = []
    for path in files:
        if args.resend:
            message_id = last.get(path.name)
            if not message_id:
                sys.exit(f"No hay un envío anterior de {path.name} en {LAST.name}.")
        else:
            message_id = f"<{path.stem}.{stamp}@{domain}>"
        plan.append((path, *build(path, target, sender, message_id)))

    if args.dry_run:
        for path, raw, message_id in plan:
            print(f"enviaría {path.name} (Message-ID {message_id}), {len(raw)} bytes")
        print("dry-run: no se ha conectado a nada ni se ha escrito .ultimo-envio.json")
        return

    context = ssl.create_default_context()
    if port == 465:
        server = smtplib.SMTP_SSL(host, port, context=context, timeout=30)
    else:
        server = smtplib.SMTP(host, port, timeout=30)
        server.starttls(context=context)
    try:
        server.login(user, password)
        for path, raw, message_id in plan:
            server.sendmail(sender, [target], raw)
            last[path.name] = message_id
            LAST.write_text(json.dumps(last, indent=2), encoding="utf-8")
            print(f"enviado {path.name} (Message-ID {message_id})")
    finally:
        server.quit()


if __name__ == "__main__":
    main()
