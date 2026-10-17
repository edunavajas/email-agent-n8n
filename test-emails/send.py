#!/usr/bin/env python3
"""Envía los .eml de esta carpeta por SMTP.

Lee el .env de la raíz del repo. No imprime contraseñas.
Con --resend 01 vuelve a mandar ese fichero con el mismo Message-ID.
"""

import argparse
import smtplib
import ssl
import sys
from email import policy
from email.parser import Parser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FOLDER = Path(__file__).resolve().parent


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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--resend", help="Prefijo del fichero que se reenvía, por ejemplo 01")
    parser.add_argument("--only", help="Prefijo de un solo correo")
    args = parser.parse_args()
    env = load_env(ROOT / ".env")
    host = env["SMTP_HOST"]
    port = int(env.get("SMTP_PORT", "465"))
    user = env["SMTP_USER"]
    password = env["SMTP_PASSWORD"]
    sender = env.get("SMTP_FROM", user)

    files = sorted(FOLDER.glob("*.eml"))
    if args.only:
        files = [path for path in files if path.name.startswith(args.only)]
    if args.resend:
        files = [path for path in files if path.name.startswith(args.resend)]
    if not files:
        sys.exit("No hay correos que enviar.")

    context = ssl.create_default_context()
    if port == 465:
        server = smtplib.SMTP_SSL(host, port, context=context, timeout=30)
    else:
        server = smtplib.SMTP(host, port, timeout=30)
        server.starttls(context=context)
    try:
        server.login(user, password)
        for path in files:
            raw = path.read_text(encoding="utf-8")
            message = Parser(policy=policy.default).parsestr(raw)
            recipient = message["to"]
            server.sendmail(sender, [recipient], raw.encode("utf-8"))
            print(f"enviado {path.name} -> {recipient}")
    finally:
        server.quit()


if __name__ == "__main__":
    main()
