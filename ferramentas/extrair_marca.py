r"""Lê a marca d'água de um arquivo exportado e mostra quem exportou e quando.

    .venv\Scripts\python.exe -m ferramentas.extrair_marca CAMINHO\arquivo.png
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
    # marca de um cadastro que não existe é leitura falsa (o CRC de 8 bits deixa passar algumas): nenhum palpite
    usuario = None if marca is None else app.administracao.usuario(marca.usuario_id)
    if usuario is None:
        print("[SEM MARCA] Nenhuma marca d'água do EcoSecurity legível neste arquivo. Nenhum palpite é dado.")
        return 1
    print(f"[ORIGEM] Exportado por {usuario.nome} (matrícula {usuario.matricula}) em "
          f"{marca.momento.astimezone():%d/%m/%Y às %H:%M}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
