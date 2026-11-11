"""S8 Tarja: "O que pode ver?"

Cada item do acervo tem regiões sensíveis (retângulos com rótulo e nível
mínimo). Antes de a imagem chegar à tela, toda região acima do nível de quem
consulta é suprimida.

Princípios:
1. Supressão NA ORIGEM, numa cópia. A interface recebe pixels já tratados;
   nunca recebe o original "com um retângulo desenhado por cima": um
   retângulo sobreposto se remove com um clique; o pixel apagado, não.
2. Irreversível. Filtro gaussiano de núcleo grande, várias passadas: o texto
   vira mancha e não há operação que o reconstitua.
3. Borrar não esconde posição. O gaussiano preserva o centroide de uma
   mancha: num mapa borrado, medir o resíduo de cor ainda aponta onde o ponto
   estava. Rótulos cuja informação é a posição (coordenada, distribuição
   geográfica) recebem supressão sólida: sem estrutura nenhuma de onde inferir.
4. Falha segura também no conteúdo: item cujas regiões ainda não foram
   revisadas é tratado como totalmente sensível: abaixo do nível 3, a imagem
   inteira é suprimida.

É processamento de imagem pura (numpy/OpenCV): não conhece banco nem tela.
"""
from dataclasses import dataclass

import cv2
import numpy as np

from ecosec.dominio.acervo import RegiaoSensivel
from ecosec.dominio.camadas import CamadaSeguranca
from ecosec.dominio.niveis import Nivel

CAMADA = CamadaSeguranca.S8_TARJA
METODOS = ("gaussiano", "pixelizacao", "solido")


# a região é do domínio: o relatório a produz ao desenhar, a tarja a consome
Regiao = RegiaoSensivel


@dataclass(frozen=True)
class ParametrosTarja:
    metodo: str
    kernel_gaussiano: int
    passadas_gaussiano: int
    bloco_pixelizacao: int
    rotulos_supressao_total: frozenset

    def __post_init__(self):
        if self.metodo not in METODOS:
            raise ValueError(f"[tarja] metodo deve ser um de {METODOS}.")
        if self.kernel_gaussiano % 2 == 0:
            raise ValueError("[tarja] kernel_gaussiano precisa ser ímpar.")

    @classmethod
    def de_configuracao(cls, cfg) -> "ParametrosTarja":
        t = cfg.secao("s8_tarja")
        return cls(t["metodo"], int(t["kernel_gaussiano"]), int(t["passadas_gaussiano"]),
                   int(t["bloco_pixelizacao"]), frozenset(t["rotulos_supressao_total"]))


@dataclass(frozen=True)
class ResultadoTarja:
    imagem: np.ndarray               # Sempre uma cópia nova
    suprimidas: tuple                # regiões efetivamente tratadas (para a trilha e a tela)
    item_inteiro: bool = False       # True = item não revisado, suprimido por inteiro


def _recorte_valido(r: Regiao, larg: int, alt: int):
    x0, y0 = max(0, r.x), max(0, r.y)
    x1, y1 = min(larg, r.x + r.largura), min(alt, r.y + r.altura)
    return (x0, y0, x1, y1) if x1 > x0 and y1 > y0 else None


def _suprimir(area: np.ndarray, metodo: str, p: ParametrosTarja) -> np.ndarray:
    if metodo == "solido":
        # cor média da área: discreta na tela, e variância zero, nenhuma estrutura sobra
        media = area.mean(axis=(0, 1)).astype(area.dtype)
        return np.broadcast_to(media, area.shape).copy()
    if metodo == "pixelizacao":
        alt, larg = area.shape[:2]
        pequeno = cv2.resize(area, (max(1, larg // p.bloco_pixelizacao), max(1, alt // p.bloco_pixelizacao)),
                             interpolation=cv2.INTER_AREA)
        return cv2.resize(pequeno, (larg, alt), interpolation=cv2.INTER_NEAREST)
    k = p.kernel_gaussiano
    for _ in range(p.passadas_gaussiano):
        area = cv2.GaussianBlur(area, (k, k), 0, borderType=cv2.BORDER_REPLICATE)
    return area


def aplicar(imagem: np.ndarray, regioes, nivel: Nivel, p: ParametrosTarja,
            regioes_revisadas: bool) -> ResultadoTarja:
    """Devolve uma CÓPIA com as regiões acima do nível suprimidas."""
    nivel = Nivel(nivel)
    saida = imagem.copy()
    alt, larg = saida.shape[:2]
    if not regioes_revisadas and nivel is not Nivel.N3:
        inteira = Regiao(0, 0, larg, alt, "NAO_REVISADO", 3)
        saida[:] = _suprimir(saida, "solido", p)
        return ResultadoTarja(saida, (inteira,), item_inteiro=True)

    suprimidas = []

    def metodo_de(r):
        return "solido" if r.rotulo in p.rotulos_supressao_total else p.metodo

    # Ordem: primeiro as borradas; depois as sólidas, da menor para a maior. A
    # maior sólida é pintada por último e cobre por igual tudo o que está dentro
    # dela. Na ordem inversa, uma região menor que sai parcialmente da maior seria
    # pintada depois com a média da própria área (que inclui pixels de fora) e
    # deixaria um retângulo de outro tom dentro da maior: entregando a posição.
    for r in sorted(regioes, key=lambda r: (metodo_de(r) == "solido", r.largura * r.altura)):
        if nivel >= r.nivel_minimo:
            continue
        recorte = _recorte_valido(r, larg, alt)
        if recorte is None:
            continue
        x0, y0, x1, y1 = recorte
        metodo = metodo_de(r)
        saida[y0:y1, x0:x1] = _suprimir(saida[y0:y1, x0:x1].copy(), metodo, p)
        suprimidas.append(r)
    return ResultadoTarja(saida, tuple(suprimidas))
