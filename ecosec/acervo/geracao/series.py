"""Intensidade de entradas λ_c(t): novas pendências por ano em cada linha de geração.

Só a FORMA da curva importa: o volume de cada linha vem da composição do acervo
(peso da atividade × UF), e λ distribui esse volume no tempo. As formas são
modeladas, não medidas.
"""
from dataclasses import dataclass
from math import exp

INICIO_SERIE = 2006                   # primeira entrada no cadastro (antes disso, só estoque herdado)
INICIO_HERDADO = 1990                 # estoque herdado: identificado entre 1990 e 2005


@dataclass(frozen=True)
class Linha:
    base: float                                          # novas pendências/ano em INICIO_SERIE
    tendencia: float = 0.0                               # crescimento exponencial ao ano
    degraus: tuple[tuple[int, float], ...] = ()          # (ano, multiplicador a partir dele)
    pulsos: tuple[tuple[int, int, float], ...] = ()      # (ano inicial, ano final, multiplicador)
    inicio: int = INICIO_SERIE                           # antes disso λ = 0 (ex.: MTR = 2021)
    herdado: float = 0.0                                 # fração do volume da linha que já existia em 2006


def intensidade(linha: Linha, ano: float) -> float:
    if ano < linha.inicio:
        return 0.0
    valor = linha.base * exp(linha.tendencia * (ano - INICIO_SERIE))
    for a, m in linha.degraus:
        valor *= m if ano >= a else 1.0
    for a0, a1, m in linha.pulsos:
        valor *= m if a0 <= ano < a1 + 1 else 1.0          # o pulso cobre os anos inteiros de a0 a a1
    return valor


# Linhas de geração
LINHAS = {
    "POSTOS": Linha(base=28, tendencia=-0.07, herdado=0.30),                       # CONAMA 273/2000: onda inicial
    "AREA": Linha(base=30, herdado=0.35),                                          # demais áreas contaminadas
    "CLASSE I": Linha(base=20, tendencia=0.01, degraus=((2011, 1.15),),            # PNRS (Lei 12.305/2010)
                      pulsos=((2020, 2020, 0.85),), herdado=0.25),                 # pandemia (parâmetro)
    "ATERROS": Linha(base=5, degraus=((2022, 1.04 * 0.9952),),                     # proxy ABRELPE (A CONFIRMAR)
                     pulsos=((2020, 2021, 1.04),), herdado=0.10),
    "MTR SEM BAIXA": Linha(base=10, tendencia=-0.25, pulsos=((2021, 2022, 2.0),), inicio=2021),
    "FONTES SELADAS": Linha(base=4, tendencia=0.06, degraus=((2022, 1.3),), herdado=0.05),  # Res. CNEN 293/2022
    "NORM": Linha(base=1, herdado=0.60),                                           # legado minerário: estável
    "GARIMPO": Linha(base=2, tendencia=0.06, pulsos=((2019, 2022, 1.5),), herdado=0.10),
}


def linha_de(atividade: str, classe: str, motivo: str) -> str:
    """A linha de geração de uma pendência (decide a forma de entrada e o risco de saída)."""
    from ecosec.acervo.sinteticos import AREA, RADIOATIVO
    if motivo == "MP-08":
        return "MTR SEM BAIXA"
    if atividade == "AG-13":
        return "GARIMPO"
    if atividade == "AG-08":
        return "FONTES SELADAS"
    if classe == RADIOATIVO:
        return "NORM"
    if classe == AREA:
        return "POSTOS" if atividade == "AG-01" else "AREA"
    return "ATERROS" if atividade == "AG-05" else "CLASSE I"
