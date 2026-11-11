r"""Cria um atalho do EcoSecurity com o ícone próprio (Windows).

    .venv\Scripts\python.exe -m ferramentas.criar_atalho                       (Menu Iniciar)
    .venv\Scripts\python.exe -m ferramentas.criar_atalho --area-de-trabalho    (também na Área de Trabalho)

O atalho abre o programa com o pythonw.exe do .venv (sem janela de console) e
leva a mesma identidade de aplicativo da janela (AppUserModelID). Com ela, o
Windows agrupa a janela aberta com o atalho e, ao fixar na barra de tarefas,
fixa o EcoSecurity, e não o Python.

Por padrão o atalho vai só para o Menu Iniciar: a Área de Trabalho, nesta
máquina, fica dentro do OneDrive (sincronizada).
"""
import argparse
import sys
from pathlib import Path

from ecosec.configuracao import RAIZ_PROJETO
from ecosec.interface.janela import ICONE, ID_APLICATIVO

NOME = "EcoSecurity.lnk"


def criar(destino: Path) -> Path:
    import pythoncom
    from win32com.propsys import propsys, pscon
    from win32com.shell import shell

    link = pythoncom.CoCreateInstance(shell.CLSID_ShellLink, None, pythoncom.CLSCTX_INPROC_SERVER,
                                      shell.IID_IShellLink)
    link.SetPath(str(RAIZ_PROJETO / ".venv" / "Scripts" / "pythonw.exe"))
    link.SetArguments("-m ecosec")
    link.SetWorkingDirectory(str(RAIZ_PROJETO))
    link.SetIconLocation(str(ICONE), 0)
    link.SetDescription("EcoSecurity: controle de acesso multinível por reconhecimento facial")
    propriedades = link.QueryInterface(propsys.IID_IPropertyStore)
    propriedades.SetValue(pscon.PKEY_AppUserModel_ID, propsys.PROPVARIANTType(ID_APLICATIVO, pythoncom.VT_LPWSTR))
    propriedades.Commit()
    arquivo = destino / NOME
    link.QueryInterface(pythoncom.IID_IPersistFile).Save(str(arquivo), 0)
    return arquivo


def main(argv=None) -> int:
    if sys.platform != "win32":
        print("Atalho com ícone: só no Windows.")
        return 1
    args = argparse.ArgumentParser(description="Cria o atalho do EcoSecurity.")
    args.add_argument("--area-de-trabalho", action="store_true", help="cria também na Área de Trabalho")
    opcoes = args.parse_args(argv)
    if not ICONE.exists():
        print(f"[FALHA] Ícone não encontrado ({ICONE}). Ele faz parte do projeto: restaure o arquivo.")
        return 1
    import win32com.client
    pastas = win32com.client.Dispatch("WScript.Shell")
    destinos = [Path(pastas.SpecialFolders("Programs"))]
    if opcoes.area_de_trabalho:
        destinos.append(Path(pastas.SpecialFolders("Desktop")))
    for destino in destinos:
        print(f"[OK] Atalho criado: {criar(destino)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
