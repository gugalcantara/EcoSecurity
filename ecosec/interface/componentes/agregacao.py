"""Agregação de pontos por proximidade NA tela. Puro Python, sem Qt.

Algoritmo guloso por raio, com baldes de grade para achar os vizinhos (custo quase linear; ~2.400 pontos em
poucos milissegundos):
  1. cada ponto recebe uma DENSIDADE aproximada: quantos pontos há nos 3 × 3 baldes de lado raio em volta;
  2. em ordem de densidade decrescente (empate: o índice, para ser determinístico), o primeiro ponto ainda
     livre vira SEMENTE e leva todos os pontos livres a até raio dele;
  3. grupo de um ponto só é ponto solto.

Consequências usadas pelo mapa:
  - duas sementes ficam a mais de raio uma da outra, então símbolos com raio até `raio / 2` não se
    sobrepõem;
  - todo ponto entra em exatamente um grupo: a soma dos tamanhos dos grupos é o número de pontos;
  - as coordenadas são as da cena multiplicadas pela escala (pixels ancorados na origem da cena, não na
    janela): rolar o mapa não muda os grupos, só o zoom muda.
"""
from __future__ import annotations

from collections import defaultdict
from math import floor


def agrupar(coordenadas, raio: float) -> list[list[int]]:
    """Grupos de índices de coordenadas [(x, y) em pixels]; o primeiro índice de cada grupo é a semente.
    raio <= 0: cada ponto sozinho."""
    pontos = [(float(x), float(y)) for x, y in coordenadas]
    if raio <= 0:
        return [[i] for i in range(len(pontos))]
    baldes: dict[tuple[int, int], list[int]] = defaultdict(list)
    celula = [(floor(x / raio), floor(y / raio)) for x, y in pontos]
    for i, c in enumerate(celula):
        baldes[c].append(i)
    ocupacao = {c: len(v) for c, v in baldes.items()}
    densidade = [sum(ocupacao.get((cx + dx, cy + dy), 0) for dx in (-1, 0, 1) for dy in (-1, 0, 1))
                 for cx, cy in celula]
    livres = {c: set(v) for c, v in baldes.items()}
    r2 = raio * raio
    grupos, usado = [], [False] * len(pontos)
    for semente in sorted(range(len(pontos)), key=lambda i: (-densidade[i], i)):
        if usado[semente]:
            continue
        sx, sy = pontos[semente]
        cx, cy = celula[semente]
        grupo = [semente]
        usado[semente] = True
        livres[(cx, cy)].discard(semente)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                balde = livres.get((cx + dx, cy + dy))
                if not balde:
                    continue
                pegos = [j for j in balde if (pontos[j][0] - sx) ** 2 + (pontos[j][1] - sy) ** 2 <= r2]
                for j in sorted(pegos):
                    usado[j] = True
                    balde.discard(j)
                    grupo.append(j)
        grupos.append(grupo)
    return grupos
