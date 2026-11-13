"""Risco de saída h_c(t) de uma pendência ativa (1/ano) e a sua calibração.

Fluxo de saídas μ_c(t) = h_c(t)·N_c(t). A dinâmica esperada dN/dt = λ − h·N tem
solução exata com λ e h constantes dentro de cada ano. A calibração trabalha
sobre essa expectativa (nunca sobre um sorteio), então não depende da semente.

Duas calibrações, as duas necessárias:
  - Metas de forma: razões entre fluxos de saída de anos diferentes;
  - Âncora de nível: fixa h0. Razões dizem quanto o fluxo varia, não se ele supera
    as entradas; sem a âncora, o estoque pode cumprir as razões e nunca cair.
"""
from dataclasses import dataclass, replace
from functools import lru_cache
from math import exp


@dataclass(frozen=True)
class Saida:
    risco_base: float                                    # h0: fração do estoque ativo que sai por ano
    metas: tuple[tuple[int, int, float], ...] = ()       # (ano, relativo a, razão entre fluxos de saída)
    inicio: int = 2006                                   # antes disso ninguém sai
    ancora: tuple = ()                                   # ("FRACAO", de, ate, alvo) ou ("NIVEL", ano, saídas/entradas)
    verificacao: str = "PARAMETRO"                       # CONFIRMADO (conferido na fonte) ou PARAMETRO
    latencia: float = 1 / 12                             # anos de casa antes de poder sair


def saidas_no_ano(estoque: float, entradas: float, h: float) -> float:
    """Saídas esperadas num ano com λ e h constantes (solução exata de dN/dt = λ - hN)."""
    if h <= 0:
        return 0.0
    equilibrio = entradas / h
    return estoque + entradas - (equilibrio + (estoque - equilibrio) * exp(-h))


def calibrar(entradas: dict[int, float], saida: Saida, estoque_inicial: float) -> tuple[dict, dict, dict]:
    """Risco por ano que cumpre as metas. Devolve (h, saídas esperadas, estoque no fim do ano)."""
    metas = {ano: (ref, razao) for ano, ref, razao in saida.metas}
    h, fluxo, estoque, n = {}, {}, {}, estoque_inicial
    for ano in sorted(entradas):
        h[ano] = saida.risco_base if ano >= saida.inicio else 0.0
        if ano in metas and h[ano] > 0:
            ref, razao = metas[ano]
            alvo = razao * fluxo[ref]
            baixo, alto = 0.0, 8.0
            if saidas_no_ano(n, entradas[ano], alto) < alvo:
                raise ValueError(f"meta de {ano} inalcançável: alvo {alvo:.1f}, estoque {n:.1f}")
            for _ in range(60):
                meio = (baixo + alto) / 2
                baixo, alto = (meio, alto) if saidas_no_ano(n, entradas[ano], meio) < alvo else (baixo, meio)
            h[ano] = (baixo + alto) / 2
        fluxo[ano] = saidas_no_ano(n, entradas[ano], h[ano])
        n = n + entradas[ano] - fluxo[ano]
        estoque[ano] = n
    return h, fluxo, estoque


def fracao_encerrada(entradas: dict[int, float], h: dict[int, float], de: int, ate: int) -> float:
    """Fração esperada das entradas de [de, ate] já encerradas no fim de ate (mesmo risco para todo ativo)."""
    vivos = total = 0.0
    for a in range(de, ate + 1):
        k = h[a]
        dentro = (1 - exp(-k)) / k if k > 0 else 1.0     # sobrevivência média de quem entra ao longo do ano
        for b in range(a + 1, ate + 1):
            dentro *= exp(-h[b])
        vivos += entradas[a] * dentro
        total += entradas[a]
    return 1 - vivos / total if total else 0.0


def _bissecao(f, alvo: float, baixo: float = 0.0, alto: float = 0.5, passos: int = 60) -> float:
    """f crescente em [baixo, alto]. O teto 0,5/ano (permanência média de 2 anos) evita a região em que
    a razão saídas/entradas deixa de ser monotônica nas linhas com entradas decrescentes."""
    for _ in range(passos):
        meio = (baixo + alto) / 2
        baixo, alto = (meio, alto) if f(meio) < alvo else (baixo, meio)
    return (baixo + alto) / 2


def calibrar_risco_base(entradas, saida: Saida, estoque_inicial: float) -> Saida:
    """Resolve h0 pela âncora da linha (sem âncora, devolve a mesma Saida)."""
    ancora = saida.ancora
    if not ancora:
        return saida

    def medir(h0: float) -> float:
        h, fluxo, _ = calibrar(entradas, replace(saida, risco_base=h0), estoque_inicial)
        if ancora[0] == "FRACAO":
            _, de, ate, _ = ancora
            return fracao_encerrada(entradas, h, de, ate)
        _, ano, _ = ancora
        return fluxo[ano] / entradas[ano] if entradas[ano] else 0.0
    return replace(saida, risco_base=_bissecao(medir, float(ancora[-1])))


# parâmetros
METAS_AREA = ((2020, 2019, 0.95), (2021, 2019, 0.90), (2022, 2021, 1.19))     # parâmetro de simulação
CHAVES = {"POSTOS": "postos", "AREA": "area", "CLASSE I": "classe_i", "ATERROS": "aterros",
          "MTR SEM BAIXA": "mtr_sem_baixa", "FONTES SELADAS": "fontes_seladas", "NORM": "norm",
          "GARIMPO": "garimpo"}


def _de_secao(s: dict) -> Saida:
    metas = tuple((int(a), int(r), float(x)) for a, r, x in s.get("metas", ()))
    if s.get("anualizar_parcial"):                       # 2024 = 202 em 5 meses, anualizado
        metas = tuple((a, r, 202 * 12 / 5 / 377 if a == 2024 else x) for a, r, x in metas)
    ancora = tuple(s.get("ancora", ()))
    return Saida(float(s.get("risco_base", 0.0)), metas, int(s.get("inicio", 2006)), ancora,
                 str(s.get("verificacao", "PARAMETRO")), float(s.get("latencia", 1 / 12)))


@lru_cache(maxsize=1)
def configuradas() -> dict[str, Saida]:
    """Saída de cada linha de geração, lida de [geracao.saidas] (sem valor padrão no código)."""
    from ecosec.configuracao import carregar
    secao = carregar().secao("geracao")["saidas"]
    return {linha: _de_secao(secao[chave]) for linha, chave in CHAVES.items()}
