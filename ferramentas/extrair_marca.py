"""Rastreia um arquivo vazado: lê a marca d'água (S9) e diz quem exportou e quando.

    .venv\\Scripts\\python.exe -m ferramentas.extrair_marca CAMINHO\\arquivo.png

Usa a CHAVE_MARCA do .env: sem ela, ninguém sabe onde a marca está, nem para
ler, nem para apagar seletivamente. Se a marca não for legível (arquivo sem
marca, recortado, muito degradado), a resposta é "sem marca": nunca um palpite,
porque um palpite errado acusaria um inocente.

Também disponível no painel: Administração > Relatórios do sistema > "Rastrear arquivo vazado".
"""
import sys
from pathlib import Path

import cv2
import numpy as np

from ecosec.aplicacao import ErroAbertura, montar


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print(__doc__)
        return 2
    caminho = Path(argv[0])
    if not caminho.exists():
        print(f"[FALHA] Arquivo não encontrado: {caminho}")
        return 2
    imagem = cv2.imdecode(np.frombuffer(caminho.read_bytes(), np.uint8), cv2.IMREAD_COLOR)
    if imagem is None:
        print("[FALHA] Não é uma imagem legível.")
        return 2
    try:
        app = montar()
    except ErroAbertura as erro:
        print(f"[FALHA] {erro}")
        return 2
    marca = app.acervo.identificar_marca(imagem)
    if marca is None:
        print("[SEM MARCA] Nenhuma marca d'água do EcoSecurity legível neste arquivo. Nenhum palpite é dado.")
        return 1
    usuario = app.administracao.usuario(marca.usuario_id)
    quem = f"{usuario.nome} (matrícula {usuario.matricula})" if usuario else f"usuário nº {marca.usuario_id}"
    print(f"[ORIGEM] Exportado por {quem} em {marca.momento.astimezone():%d/%m/%Y às %H:%M}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
