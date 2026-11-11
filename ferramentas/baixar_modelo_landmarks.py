r"""Baixa o modelo de landmarks faciais (FacemarkLBF) usado na piscada da S6.

    .venv\Scripts\python.exe -m ferramentas.baixar_modelo_landmarks

Origem: o modelo de referência da documentação do OpenCV (repositório
kurnianggoro/GSOC2017, ~54 MB). O arquivo vai para modelo/ (fora do git) e só
é aceito se o SHA-256 bater com o do config: um modelo trocado poderia fazer
qualquer imagem "piscar". Se já existir e conferir, nada é baixado.
"""
import hashlib
import sys
import urllib.request
from pathlib import Path

from ecosec.configuracao import RAIZ_PROJETO, carregar

URL = "https://raw.githubusercontent.com/kurnianggoro/GSOC2017/master/data/lbfmodel.yaml"


def sha256(arquivo: Path) -> str:
    resumo = hashlib.sha256()
    with arquivo.open("rb") as f:
        for bloco in iter(lambda: f.read(1 << 20), b""):
            resumo.update(bloco)
    return resumo.hexdigest()


def main() -> int:
    cfg = carregar()
    destino = RAIZ_PROJETO / cfg["s6_vivacidade.modelo_landmarks"]
    esperado = str(cfg["s6_vivacidade.modelo_landmarks_sha256"]).lower()
    if destino.exists() and sha256(destino) == esperado:
        print(f"[OK] O modelo já está em {destino} e confere.")
        return 0
    destino.parent.mkdir(parents=True, exist_ok=True)
    parcial = destino.with_suffix(".parcial")
    print(f"Baixando {URL}\n  para {destino} (~54 MB)...")
    urllib.request.urlretrieve(URL, parcial)
    obtido = sha256(parcial)
    if obtido != esperado:
        parcial.unlink(missing_ok=True)
        print(f"[FALHA] O arquivo baixado não confere.\n  esperado {esperado}\n  obtido   {obtido}")
        return 1
    parcial.replace(destino)
    print(f"[OK] Modelo baixado e conferido: {destino}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
