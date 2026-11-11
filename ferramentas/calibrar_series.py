"""Confere a calibração das séries do acervo.

Para cada linha de geração, imprime o risco de saída calibrado, as metas de forma e
o desvio entre o esperado e o realizado; depois confere as metas de encerramento e
de queda do estoque. Termina com código 1 se alguma meta falhar.

    python -m ferramentas.calibrar_series
"""
import sys
from collections import Counter, defaultdict
from datetime import date

from ecosec.acervo import sinteticos
from ecosec.acervo.geracao import saidas, series

TOLERANCIA_RAZAO = 0.15                  # ±15% nas razões, com o volume padrão
FAIXA_ENCERRADAS = (0.30, 0.60)


def _estoque(pendencias, ano: int) -> int:
    corte = min(date(ano, 12, 31), sinteticos.DATA_BASE)
    return sum(p.ativa(corte) for p in pendencias)


def conferir(pendencias=None, imprimir=print) -> list[str]:
    """Devolve a lista de falhas (vazia = tudo calibrado)."""
    pendencias = pendencias if pendencias is not None else sinteticos.gerar()[0]
    falhas = []
    por_linha = defaultdict(list)
    for p in pendencias:
        por_linha[series.linha_de(p.atividade, p.classe_risco, p.motivo)].append(p)
    configuradas = saidas.configuradas()
    imprimir(f"{'LINHA':16s} {'N':>5s} {'H0 / ANCORA':>18s}  METAS (alvo -> realizado)")
    saidas_por_linha = {}
    for nome in sorted(por_linha):
        ps = por_linha[nome]
        fluxo = Counter(p.data_encerramento.year for p in ps if p.data_encerramento)
        saidas_por_linha[nome] = fluxo
        cfg = configuradas[nome]
        textos = []
        for ano, ref, razao in cfg.metas:
            realizado = fluxo[ano] / fluxo[ref] if fluxo[ref] else 0.0
            textos.append(f"{ano}/{ref} {razao:.2f}->{realizado:.2f}")
        nivel = " ".join(map(str, cfg.ancora)) if cfg.ancora else f"{cfg.risco_base:.3f}"
        imprimir(f"{nome:16s} {len(ps):5d} {nivel:>18s}  {'; '.join(textos) or '-'}"
                 f"{'  [' + cfg.verificacao + ']' if cfg.verificacao != 'PARAMETRO' else ''}")
    # razões das metas da classe AREA (postos + demais), no realizado
    area = saidas_por_linha.get("AREA", Counter()) + saidas_por_linha.get("POSTOS", Counter())
    for ano, ref, razao in saidas.METAS_AREA[1:]:
        realizado = area[ano] / area[ref] if area[ref] else 0.0
        if abs(realizado - razao) > TOLERANCIA_RAZAO * razao:
            falhas.append(f"AREA: razão {ano}/{ref} realizada {realizado:.2f}, alvo {razao:.2f}")
    fontes = saidas_por_linha.get("FONTES SELADAS", Counter())
    if fontes[2023] <= fontes[2022]:
        falhas.append("FONTES SELADAS: sem pico de recolhimento em 2023")
    fracao = sum(1 for p in pendencias if p.data_encerramento) / len(pendencias)
    if not FAIXA_ENCERRADAS[0] <= fracao <= FAIXA_ENCERRADAS[1]:
        falhas.append(f"fração encerrada {fracao:.2f} fora de {FAIXA_ENCERRADAS}")
    postos = [p for p in pendencias if p.atividade == "AG-01" and 2006 <= p.data_identificacao.year <= 2019]
    fr_postos = sum(1 for p in postos if p.data_encerramento and p.data_encerramento.year <= 2019) / max(1, len(postos))
    if abs(fr_postos - 0.28) > 0.05:
        falhas.append(f"postos encerrados até 2019: {fr_postos:.2f} (âncora Borges: 0,28 ± 0,05)")
    anos = range(2006, sinteticos.DATA_BASE.year + 1)
    total = {a: _estoque(pendencias, a) for a in anos}
    quedas = [a for a in anos if a > anos[0] and total[a] < total[a - 1]]
    area_ps = [p for p in pendencias if p.classe_risco == sinteticos.AREA]
    fontes_ps = por_linha.get("FONTES SELADAS", [])
    imprimir(f"\nfração encerrada {fracao:.3f} · postos até 2019 {fr_postos:.3f} · estoque total cai em "
             f"{', '.join(map(str, quedas)) or 'NENHUM ANO'}")
    if not quedas:
        falhas.append("o estoque ativo total não cai em nenhum ano (curva monotônica)")
    if not _estoque(area_ps, 2022) < _estoque(area_ps, 2021):
        falhas.append("o estoque de AREA CONTAMINADA não cai em 2022")
    if not _estoque(fontes_ps, 2023) < _estoque(fontes_ps, 2022):
        falhas.append("o estoque de fontes seladas não cai em 2023")
    return falhas


def main():
    falhas = conferir()
    if falhas:
        print("\n[FALHA] " + "\n[FALHA] ".join(falhas))
        sys.exit(1)
    print("\n[OK] Todas as metas de calibração foram atingidas.")


if __name__ == "__main__":
    main()
