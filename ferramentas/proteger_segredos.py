"""Protege os segredos do .env com o Windows (DPAPI) e faz o backup lacrado deles.

    .venv\\Scripts\\python.exe -m ferramentas.proteger_segredos
        converte os valores ainda em texto puro (idempotente: rodar de novo não muda nada)

    .venv\\Scripts\\python.exe -m ferramentas.proteger_segredos --backup E:\\ecosec_segredos.bak
        grava um backup cifrado por uma FRASE-SENHA (pedida duas vezes, não guardada)

    .venv\\Scripts\\python.exe -m ferramentas.proteger_segredos --restaurar E:\\ecosec_segredos.bak
        devolve os segredos ao .env desta máquina (protegidos de novo pelo Windows dela)

O backup é necessário porque, com o DPAPI, o .env só abre nesta conta do Windows,
neste computador. Reinstalar o Windows torna o arquivo ilegível também para
nós, e sem a chave de cifragem o modelo facial não abre mais. Guarde o backup
fora do computador (num pen drive em lugar seguro, por exemplo), com a
frase-senha anotada em outro lugar. Fazer de novo a cada segredo novo
(por exemplo, depois de rodar o preparar_banco pela primeira vez).
"""
import argparse
import getpass
import sys
from pathlib import Path

from ecosec import segredos


def _converter() -> int:
    if not segredos.dpapi_disponivel():
        print("[FALHA] O DPAPI só existe no Windows (e precisa do pywin32 do requirements.txt).")
        return 2
    convertidos = segredos.proteger_existentes()
    total = len(segredos.nomes())
    print(f"[ OK ] {convertidos} segredo(s) convertido(s); {total} no .env, todos protegidos pelo Windows.")
    if convertidos:
        print("Agora faça o backup:  .venv\\Scripts\\python.exe -m ferramentas.proteger_segredos --backup ARQUIVO")
    return 0


def _backup(destino: Path) -> int:
    if destino.exists():
        print(f"[FALHA] {destino} já existe: escolha outro nome (o backup anterior não é sobrescrito).")
        return 2
    frase = getpass.getpass(f"Frase-senha do backup (mínimo {segredos.FRASE_MINIMA} caracteres): ")
    if frase != getpass.getpass("Repita a frase-senha: "):
        print("[FALHA] As frases não conferem. Nada foi gravado.")
        return 2
    destino.write_bytes(segredos.exportar_backup(frase))
    print(f"[ OK ] Backup de {len(segredos.nomes())} segredo(s) gravado em {destino}.")
    print("Guarde o arquivo fora deste computador e a frase-senha em outro lugar.")
    return 0


def _restaurar(origem: Path, sobrescrever: bool) -> int:
    valores = segredos.importar_backup(origem.read_bytes(), getpass.getpass("Frase-senha do backup: "))
    conflitos = [n for n, v in valores.items() if (atual := _ler_ou_none(n)) is not None and atual != v]
    if conflitos and not sobrescrever:
        print("[FALHA] O .env já tem valores diferentes para: " + ", ".join(conflitos) + ".\n"
              "Nada foi alterado. Se tiver certeza, rode de novo com --sobrescrever.")
        return 2
    for nome, valor in valores.items():
        segredos.gravar(nome, valor)
    print(f"[ OK ] {len(valores)} segredo(s) restaurado(s) no .env desta máquina.")
    return 0


def _ler_ou_none(nome: str) -> str | None:
    try:
        return segredos.ler(nome)
    except segredos.ErroSegredo:
        return None                                   # ilegível aqui: é justamente o que se quer restaurar


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0].strip())
    grupo = parser.add_mutually_exclusive_group()
    grupo.add_argument("--backup", type=Path, metavar="ARQUIVO", help="grava o backup cifrado por frase-senha")
    grupo.add_argument("--restaurar", type=Path, metavar="ARQUIVO", help="restaura os segredos de um backup")
    parser.add_argument("--sobrescrever", action="store_true", help="com --restaurar: troca valores diferentes")
    args = parser.parse_args(argv)
    try:
        if args.backup:
            return _backup(args.backup)
        if args.restaurar:
            return _restaurar(args.restaurar, args.sobrescrever)
        return _converter()
    except segredos.ErroSegredo as erro:
        print(f"[FALHA] {erro}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
