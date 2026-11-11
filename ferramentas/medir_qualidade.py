"""Mede a qualidade do rosto (S3) com a SUA câmera, a SUA luz e o seu rosto, regra por regra.

    .venv\\Scripts\\python.exe -m ferramentas.medir_qualidade
    .venv\\Scripts\\python.exe -m ferramentas.medir_qualidade --segundos 30

Abre a câmera pelo mesmo caminho do login (aquisição, detecção e recorte do rosto) e mostra, quadro a
quadro, cada medida da S3 ao lado do limite em vigor, em verde (passa) ou vermelho (reprova). A tela do
login mostra só a dica do PRIMEIRO problema; aqui aparecem todos.

No fim, imprime e grava em resultados/qualidade_camera.json (só números, nenhuma imagem):
  - qual arquivo de configuração foi lido e os limites em vigor (confirma se uma edição valeu);
  - para cada medida, a mediana e a faixa (10% a 90%) dos quadros com rosto;
  - em quantos % dos quadros cada regra reprovou, e quantos passariam no login.
Duas medidas a mais, para estudar o critério (não decidem nada): a fração de pixels quase pretos
(sombra sem textura) e o contraste relativo ao brilho do próprio rosto.

Serve para calibrar a S3 com pessoas de tons de pele diferentes: um limite de brilho médio fixo reprova
mais quem tem a pele mais escura, mesmo com a imagem boa.
"""
import argparse
import json
import statistics
import sys
import time
from datetime import datetime

import cv2
import numpy as np

from ecosec.configuracao import carregar
from ecosec.visao.aquisicao import Camera, ErroCamera
from ecosec.visao.pipeline import PipelineVisao
from ecosec.visao.qualidade import ProblemaQualidade

QUASE_PRETO = 25                       # tom (0-255) abaixo do qual o pixel praticamente não tem textura
JANELA = "EcoSecurity - qualidade do rosto (Esc encerra)"
REGRAS = ((ProblemaQualidade.ESCURA, "brilho", ">=", "brilho_minimo"),
          (ProblemaQualidade.CLARA, "brilho", "<=", "brilho_maximo"),
          (ProblemaQualidade.DESFOCADA, "nitidez", ">=", "nitidez_minima"),
          (ProblemaQualidade.SEM_CONTRASTE, "contraste", ">=", "contraste_minimo"),
          (ProblemaQualidade.RUIDOSA, "ruido", "<=", "ruido_maximo"))


def _faixa(valores: list[float]) -> str:
    if not valores:
        return "sem dados"
    ordenados = sorted(valores)
    p10, p90 = ordenados[int(len(ordenados) * 0.1)], ordenados[int(len(ordenados) * 0.9) - 1]
    return f"mediana {statistics.median(ordenados):7.1f}   faixa {p10:6.1f} a {p90:6.1f}"


def medir(segundos: float) -> dict:
    cfg = carregar()
    limites = cfg.secao("qualidade")
    pipeline = PipelineVisao.de_configuracao(cfg)
    quadros, registros = 0, []
    with Camera.de_configuracao(cfg) as camera:
        fim = time.monotonic() + segundos
        while time.monotonic() < fim:
            quadro = camera.ler()
            quadros += 1
            r = pipeline.processar(quadro)
            tela = cv2.flip(quadro, 1)                                    # espelhado, como no app
            linhas = [(f"{fim - time.monotonic():4.0f} s   rostos: {r.quantidade_faces}", (255, 255, 255))]
            if r.medidas is not None and r.recorte_cinza is not None:
                m, recorte = r.medidas, r.recorte_cinza
                registros.append({"brilho": m.brilho, "contraste": m.contraste, "nitidez": m.nitidez,
                                  "ruido": m.ruido, "quase_preto": float(np.mean(recorte <= QUASE_PRETO)),
                                  "contraste_relativo": m.contraste / m.brilho if m.brilho else 0.0,
                                  "problemas": [p.value for p in r.problemas]})
                for problema, medida, sinal, chave in REGRAS:
                    valor = getattr(m, medida)
                    reprova = problema in r.problemas
                    linhas.append((f"{medida:9} {valor:7.1f}  {sinal} {float(limites[chave]):6.1f}  "
                                   f"{'REPROVA' if reprova else 'ok'}", (60, 60, 230) if reprova else (90, 200, 90)))
            for i, (texto, cor) in enumerate(linhas):
                cv2.putText(tela, texto, (12, 28 + 26 * i), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (0, 0, 0), 4)
                cv2.putText(tela, texto, (12, 28 + 26 * i), cv2.FONT_HERSHEY_SIMPLEX, 0.62, cor, 2)
            cv2.imshow(JANELA, tela)
            if cv2.waitKey(1) == 27:
                break
    cv2.destroyAllWindows()
    com_rosto = len(registros)
    reprovacoes = {p.value: (round(100 * sum(1 for x in registros if p.value in x["problemas"]) / com_rosto, 1)
                             if com_rosto else 0.0) for p, *_ in REGRAS}
    return {"momento": datetime.now().isoformat(timespec="seconds"), "config": str(cfg.origem),
            "limites": {k: float(v) for k, v in limites.items()}, "quadros": quadros, "com_rosto": com_rosto,
            "passariam_no_login_pct": round(100 * sum(1 for x in registros if not x["problemas"]) / com_rosto, 1)
            if com_rosto else 0.0, "reprovacao_pct": reprovacoes,
            "medidas": {k: [x[k] for x in registros] for k in ("brilho", "contraste", "nitidez", "ruido",
                                                               "quase_preto", "contraste_relativo")}}


def relatorio(r: dict) -> str:
    linhas = [f"Configuração lida: {r['config']}",
              "Limites em vigor: " + ", ".join(f"{k} = {v:g}" for k, v in r["limites"].items()),
              f"Quadros: {r['quadros']}, com rosto medido: {r['com_rosto']}",
              f"Passariam na qualidade do login: {r['passariam_no_login_pct']}%", "",
              "MEDIDAS (quadros com rosto)"]
    for nome, valores in r["medidas"].items():
        linhas.append(f"  {nome:19} {_faixa([v * 100 for v in valores] if nome == 'quase_preto' else valores)}"
                      + ("  (% de pixels)" if nome == "quase_preto" else ""))
    linhas += ["", "REPROVAÇÃO POR REGRA (% dos quadros com rosto)"]
    linhas += [f"  {regra:14} {pct:5.1f}%" for regra, pct in r["reprovacao_pct"].items()]
    return "\n".join(linhas)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0].strip())
    parser.add_argument("--segundos", type=float, default=15.0, help="duração da medição (padrão: 15)")
    args = parser.parse_args(argv)
    print("Olhe para a câmera como no login, por", int(args.segundos), "segundos. Esc encerra antes.")
    try:
        resultado = medir(args.segundos)
    except ErroCamera as erro:
        print(f"[FALHA] Câmera: {erro}")
        return 2
    texto = relatorio(resultado)
    print("\n" + texto)
    pasta = carregar().caminho("resultados")
    pasta.mkdir(parents=True, exist_ok=True)
    (pasta / "qualidade_camera.json").write_text(json.dumps(resultado, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nNúmeros gravados em {pasta / 'qualidade_camera.json'} (nenhuma imagem). Envie esse arquivo ao grupo.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
