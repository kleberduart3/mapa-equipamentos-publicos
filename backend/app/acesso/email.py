"""Envio de e-mail (opcional, via SMTP). Sem SMTP configurado, nada é enviado e
o administrador repassa os links de convite à mão."""
from __future__ import annotations

import logging
import smtplib
import ssl
from email.message import EmailMessage

from .configuracao import cfg

log = logging.getLogger(__name__)


def enviar(para: str, assunto: str, texto: str) -> bool:
    c = cfg()
    if not c.tem_email:
        return False
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = c.smtp_remetente, para, assunto
    msg.set_content(texto)
    try:
        with smtplib.SMTP(c.smtp_host, c.smtp_porta, timeout=20) as s:
            s.starttls(context=ssl.create_default_context())
            if c.smtp_usuario:
                s.login(c.smtp_usuario, c.smtp_senha or "")
            s.send_message(msg)
        return True
    except (smtplib.SMTPException, OSError):
        log.exception("falha ao enviar e-mail para %s", para)
        return False


def texto_convite(nome: str, link: str, motivo: str) -> tuple[str, str]:
    h = cfg().convite_validade_horas
    if motivo == "redefinicao":
        return ("Redefinição de senha – Mapa de Equipamentos Públicos",
                f"Olá, {nome}.\n\nPara criar uma nova senha, abra o link abaixo (vale por {h:.0f} horas e uma única vez):\n\n"
                f"{link}\n\nSe você não pediu, ignore este e-mail: sua senha atual continua valendo.\n")
    return ("Seu acesso ao Mapa de Equipamentos Públicos",
            f"Olá, {nome}.\n\nVocê recebeu acesso ao Mapa de Equipamentos Públicos. Para criar sua senha, "
            f"abra o link abaixo (vale por {h:.0f} horas e uma única vez):\n\n{link}\n")
