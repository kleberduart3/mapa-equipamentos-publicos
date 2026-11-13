"""Linha de comando de contas (no servidor, dentro do container).

    python -m backend.app.acesso.cli criar-admin EMAIL "NOME"
    python -m backend.app.acesso.cli link EMAIL            # novo link de senha (e desbloqueia)
    python -m backend.app.acesso.cli listar
    python -m backend.app.acesso.cli desativar EMAIL

Os links valem por MAPA_CONVITE_VALIDADE_HORAS e uma única vez. Ninguém digita
senha aqui: o próprio usuário define a dele abrindo o link.
"""
from __future__ import annotations

import argparse
import sys

from sqlalchemy import select

from . import credenciais as cr
from .configuracao import cfg
from .modelos import Usuario, iniciar_banco, nova_sessao_db


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m backend.app.acesso.cli", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("criar-admin")
    p.add_argument("email")
    p.add_argument("nome")
    sub.add_parser("listar")
    for nome in ("link", "desativar"):
        sub.add_parser(nome).add_argument("email")
    a = ap.parse_args(argv)

    iniciar_banco(cfg().db_url)
    with nova_sessao_db() as s:
        if a.cmd == "listar":
            for u in s.scalars(select(Usuario).order_by(Usuario.email)):
                print(f"{u.id:4}  {u.email:40} {u.papel:8} {'ativo' if u.ativo else 'INATIVO':8} "
                      f"{'senha ok' if u.senha_hash else 'convite pendente'}")
            return 0
        email = cr.normalizar_email(a.email)
        u = s.scalar(select(Usuario).where(Usuario.email == email))
        if a.cmd == "criar-admin":
            if u is not None:
                print(f"Já existe uma conta {email}. Use 'link' para gerar um novo link de senha.", file=sys.stderr)
                return 1
            u = Usuario(email=email, nome=a.nome.strip(), papel="admin")
            s.add(u)
            s.flush()
            token = cr.criar_convite(s, u, "convite")
            cr.registrar(s, "admin_criado_cli", u.id, detalhe=email)
            s.commit()
            print(f"Administrador {email} criado. Abra o link para definir a senha:\n\n  {cr.link_convite(token)}\n")
            return 0
        if u is None:
            print(f"Conta não encontrada: {email}", file=sys.stderr)
            return 1
        if a.cmd == "link":
            token = cr.criar_convite(s, u, "redefinicao" if u.senha_hash else "convite")
            u.bloqueado_ate, u.falhas_login = None, 0
            cr.registrar(s, "link_gerado_cli", u.id, detalhe=email)
            s.commit()
            print(f"Link para {email}:\n\n  {cr.link_convite(token)}\n")
        elif a.cmd == "desativar":
            u.ativo = False
            cr.encerrar_todas(s, u.id)
            cr.registrar(s, "desativado_cli", u.id, detalhe=email)
            s.commit()
            print(f"{email} desativado e desconectado.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
