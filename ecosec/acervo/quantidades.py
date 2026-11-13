"""Totais de quantidade: nunca somam unidades diferentes.

Área contaminada em m³ de solo, rejeito radioativo em m³, Classe I em t (sinteticos.UNIDADE_DA_CLASSE).
O total é sempre por classe: m³ de solo e m³ de rejeito têm a mesma unidade, mas somá-los daria um número
sem significado. Não há conversão entre t e m³ nos totais: não existe um fator único defensável para todos os
materiais, então cada classe aparece com a sua própria unidade.

Toda soma de quantidade do acervo passa por aqui: relatórios e análises não somam p.quantidade por conta
própria (um teste confere).
"""
from ecosec.acervo.sinteticos import AREA, CLASSE_I, RADIOATIVO, UNIDADE_DA_CLASSE

CLASSES = (CLASSE_I, AREA, RADIOATIVO)
SIGLA = {"TONELADAS": "t", "METROS CUBICOS": "m³"}
DESCRICAO = {CLASSE_I: "de resíduo Classe I", AREA: "de solo em áreas contaminadas",
             RADIOATIVO: "de rejeito radioativo (CNEN)"}


class UnidadesMisturadas(ValueError):
    """Pedido de soma com mais de uma unidade (ou mais de uma classe): recusado, nunca convertido em silêncio."""


def somar(pendencias) -> float:
    """Soma a quantidade de pendências de UMA classe e UMA unidade; recusa a mistura."""
    pendencias = list(pendencias)
    unidades = {p.unidade for p in pendencias}
    classes = {p.classe_risco for p in pendencias}
    if len(unidades) > 1 or len(classes) > 1:
        raise UnidadesMisturadas(f"Soma recusada: {sorted(classes)} em {sorted(unidades)}. Some por classe.")
    return round(sum(p.quantidade for p in pendencias), 2)


def total_da_classe(pendencias, classe: str) -> float:
    return somar(p for p in pendencias if p.classe_risco == classe)


def sigla(classe: str) -> str:
    return SIGLA[UNIDADE_DA_CLASSE[classe]]


def por_classe(pendencias) -> dict[str, float]:
    """{classe: total na unidade da classe}, para as três classes (0 se não houver)."""
    return {c: total_da_classe(pendencias, c) for c in CLASSES}
