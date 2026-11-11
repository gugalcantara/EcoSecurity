"""Verifica a integridade da trilha de auditoria (S10) no banco real e cuida da âncora fora do banco.

    .venv\\Scripts\\python.exe -m ferramentas.verificar_trilha
    .venv\\Scripts\\python.exe -m ferramentas.verificar_trilha --ancorar [--arquivo ancoras.txt]
    .venv\\Scripts\\python.exe -m ferramentas.verificar_trilha --conferir "ECOSEC-TRILHA <id> <hash> <momento>"
    .venv\\Scripts\\python.exe -m ferramentas.verificar_trilha --conferir-arquivo ancoras.txt

Roteiro da demonstração na banca:
  1. use o sistema (alguns logins, um cadastro);
  2. rode esta ferramenta: "Trilha íntegra";
  3. no MySQL Workbench, como root, altere uma linha de log_acesso
     (ex.: troque um NEGADO por CONCEDIDO);
  4. rode de novo: a ferramenta aponta o id exato da adulteração.

A conta da aplicação não conseguiria fazer o passo 3: ela não tem UPDATE na
trilha. Só o root consegue: e mesmo ele não passa despercebido.

Âncora: a corrente sozinha não percebe quando o root apaga as últimas linhas ou
recalcula a cauda inteira. Por isso, periodicamente (por exemplo, ao fim de cada
dia de uso ou na revisão de acessos), `--ancorar` imprime uma linha com o id e o
hash do último registro, para guardar FORA do banco: impressa em ata, ou enviada
a outro computador. `--arquivo` também acrescenta a linha num arquivo de texto
(que deve ser copiado para fora desta máquina). Depois, `--conferir` ou
`--conferir-arquivo` prova que a trilha continua igual até cada registro ancorado.

Códigos de saída: 0 íntegra; 1 adulterada ou âncora que não confere; 2 o
sistema não abriu; 3 linha de âncora inválida ou trilha vazia.
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
    parser = argparse.ArgumentParser(description="Verifica a trilha de auditoria e cuida da âncora fora do banco.")
    grupo = parser.add_mutually_exclusive_group()
    grupo.add_argument("--ancorar", action="store_true", help="imprime a âncora do último registro")
    grupo.add_argument("--conferir", metavar="LINHA", help="confere uma linha de âncora")
    grupo.add_argument("--conferir-arquivo", metavar="ARQ", type=Path, help="confere todas as âncoras de um arquivo")
    parser.add_argument("--arquivo", type=Path, help="com --ancorar, acrescenta a linha neste arquivo")
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
    if not resultado.integra:
        return 1
    if args.ancorar:
        ancorada = adm.ancora_trilha()
        if ancorada is None:
            print("[FALHA] A trilha está vazia: não há o que ancorar.")
            return 3
        print("Guarde esta linha FORA do banco (em ata ou em outro computador):")
        print(ancorada.texto())
        if args.arquivo:
            with args.arquivo.open("a", encoding="utf-8") as saida:
                saida.write(ancorada.texto() + "\n")
            print(f"Linha acrescentada em {args.arquivo}. Copie o arquivo para fora desta máquina.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
