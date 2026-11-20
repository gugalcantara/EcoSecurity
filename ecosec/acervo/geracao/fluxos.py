"""Quantos casos entram e saem a cada ano, e quais."""
from collections import defaultdict
from math import exp


def contagens_sistematicas(esperado: dict[int, float], rng) -> dict[int, int]:
    """Arredondamento sistemático: cada ano fica a menos de 1 do esperado e a soma bate com o total."""
    deslocamento, acumulado, anterior, contagem = rng.random(), 0.0, 0, {}
    for ano in sorted(esperado):
        acumulado += esperado[ano]
        atual = int(acumulado + deslocamento)
        contagem[ano], anterior = atual - anterior, atual
    return contagem


def contagens_poisson(esperado: dict[int, float], rng) -> dict[int, int]:
    """Contagens independentes de Poisson (algoritmo de Knuth; os valores aqui são pequenos)."""
    contagem = {}
    for ano, media in sorted(esperado.items()):
        limite, k, p = exp(-media), 0, rng.random()
        while p > limite:
            k += 1
            p *= rng.random()
        contagem[ano] = k
    return contagem


def contagens(esperado: dict[int, float], rng, modo: str) -> dict[int, int]:
    return contagens_poisson(esperado, rng) if modo == "poisson" else contagens_sistematicas(esperado, rng)


def sortear_saidas(registros, saidas_por_ano: dict[int, int], rng, data_base: float,
                   latencia: float = 1 / 12) -> int:
    """Escolhe quem sai em cada ano entre os ativos com pelo menos `latencia` anos de casa e grava r.saida.
    Devolve quantas saídas pedidas não acharam ninguém elegível."""
    por_ano = defaultdict(list)
    for r in registros:
        por_ano[int(r.entrada)].append(r)
    ativos, faltaram = [], 0
    for ano in sorted(set(por_ano) | set(saidas_por_ano)):
        ativos.extend(por_ano.get(ano, ()))
        alvo, feitas = saidas_por_ano.get(ano, 0), 0
        for r in rng.sample(ativos, len(ativos)):               # ordem aleatória, sem repetição
            if feitas == alvo:
                break
            inicio, fim = max(float(ano), r.entrada + latencia), min(ano + 1.0, data_base)
            if inicio < fim:                                    # ainda sem a latência: não sai neste ano
                r.saida = rng.uniform(inicio, fim)
                ativos.remove(r)
                feitas += 1
        faltaram += alvo - feitas
    return faltaram
