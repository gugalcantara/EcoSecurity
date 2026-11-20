r"""Verifica a integridade da trilha de auditoria e confere as âncoras guardadas fora do banco.

    .venv\Scripts\python.exe -m ferramentas.verificar_trilha
    .venv\Scripts\python.exe -m ferramentas.verificar_trilha --conferir "ECOSEC-TRILHA <id> <hash> <momento>"
    .venv\Scripts\python.exe -m ferramentas.verificar_trilha --conferir-arquivo ancoras.txt
"""
import argparse
import sys
from pathlib import Path

from ecosec.aplicacao import ErroAbertura, montar
from ecosec.seguranca.evidencia.s10_trilha import PREFIXO_ANCORA, Ancora


def linhas_de_ancora(texto: str) -> list[str]:
    """As linhas de âncora de um arquivo, ignorando linhas vazias e anotações."""
    return [linha.strip() for linha in texto.splitlines() if linha.strip().startswith(PREFIXO_ANCORA)]


def main(argv=None, app=None) -> int:
    parser = argparse.ArgumentParser(description="Verifica a trilha de auditoria e confere as âncoras guardadas "
                                                 "fora do banco. A âncora é gerada no painel administrativo.")
    grupo = parser.add_mutually_exclusive_group()
    grupo.add_argument("--conferir", metavar="LINHA", help="confere uma linha de âncora")
    grupo.add_argument("--conferir-arquivo", metavar="ARQ", type=Path, help="confere todas as âncoras de um arquivo")
    args = parser.parse_args(argv)

    if app is None:
        try:
            app = montar()
        except ErroAbertura as erro:
            print(f"[FALHA] {erro}")
            return 2
    adm = app.administracao

    if args.conferir or args.conferir_arquivo:
        if args.conferir:
            linhas = [args.conferir]
        else:
            linhas = linhas_de_ancora(args.conferir_arquivo.read_text(encoding="utf-8"))
            if not linhas:
                print(f"[FALHA] Nenhuma linha de âncora em {args.conferir_arquivo}.")
                return 3
        pior = 0
        for linha in linhas:
            try:
                ancorada = Ancora.de_texto(linha)
            except ValueError as erro:
                print(f"[FALHA] {erro}")
                return 3
            conferencia = adm.conferir_ancora_trilha(ancorada)
            print(("[ OK ] " if conferencia.valida else "[ADULTERADA] ") + f"registro {ancorada.id}: {conferencia}")
            pior = max(pior, 0 if conferencia.valida else 1)
        return pior

    resultado = adm.verificar_trilha()
    print(("[ OK ] " if resultado.integra else "[ADULTERADA] ") + str(resultado))
    return 0 if resultado.integra else 1


if __name__ == "__main__":
    sys.exit(main())
