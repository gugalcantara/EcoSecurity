"""Mapa esquemático do Brasil para os relatórios A1-05 e A3-03.

Projeção equirretangular (lon/lat -> pixel por regra de três): suficiente para
o mapa dos pontos do acervo simulado. O contorno é a malha do IBGE em
qualidade mínima: fiel na forma, sem pretensão de precisão cartográfica.

O mapa também desenha as divisas das UFs (malha do IBGE, a mesma do mapa interativo), preenchidas por
uma cor de cada UF (o coroplético do Nível 1) e recortadas no quadro do mapa (o recorte de uma UF no Nível 2).
"""
from PIL import Image, ImageChops, ImageDraw

from ecosec.acervo.desenho import Tela

# Contorno do país: malha oficial do IBGE (qualidade mínima, ~600 vértices), a mesma
# fonte dos polígonos municipais em que os pontos do acervo são sorteados: os pontos
# caem dentro do contorno por construção (ferramentas.baixar_geografia).
def _contorno_ibge() -> tuple[tuple[float, float], ...]:
    from ecosec.acervo.sinteticos import geografia
    return tuple((float(lon), float(lat)) for lon, lat in geografia()[0])


CONTORNO_BRASIL = _contorno_ibge()

# Centro aproximado (lon, lat) de cada UF: só para o rótulo AGREGADO do nível 1 (um total por
# estado, no meio do estado). Não é a posição de nenhuma pendência.
CENTROIDES_UF = {
    "AC": (-70.5, -9.0), "AL": (-36.6, -9.6), "AP": (-51.9, 1.4), "AM": (-64.6, -4.2), "BA": (-41.7, -12.5),
    "CE": (-39.6, -5.1), "DF": (-47.8, -15.8), "ES": (-40.7, -19.6), "GO": (-49.6, -16.0), "MA": (-45.3, -5.1),
    "MT": (-55.9, -12.9), "MS": (-54.8, -20.5), "MG": (-44.6, -18.5), "PA": (-52.3, -4.0), "PB": (-36.8, -7.1),
    "PR": (-51.6, -24.6), "PE": (-37.9, -8.4), "PI": (-42.9, -7.6), "RJ": (-42.7, -22.2), "RN": (-36.6, -5.8),
    "RS": (-53.3, -29.7), "RO": (-62.9, -10.9), "RR": (-61.3, 2.1), "SC": (-50.5, -27.3), "SP": (-48.5, -22.3),
    "SE": (-37.4, -10.6), "TO": (-48.3, -10.2),
}
LON_MIN, LON_MAX, LAT_MIN, LAT_MAX = -75.0, -33.5, -34.5, 6.0


def divisas() -> dict:
    from ecosec.acervo.sinteticos import divisas_uf
    return divisas_uf()


class Mapa:
    def __init__(self, x0: int, y0: int, largura: int, altura: int, limites=None):
        self.x0, self.y0, self.largura, self.altura = int(x0), int(y0), int(largura), int(altura)
        self.lon_min, self.lon_max, self.lat_min, self.lat_max = limites or (LON_MIN, LON_MAX, LAT_MIN, LAT_MAX)

    @classmethod
    def da_uf(cls, uf: str, x0: int, y0: int, largura: int, altura: int, folga: float = 0.08) -> "Mapa":
        """Quadro recortado numa UF (o escopo do Nível 2), com a mesma proporção do quadro: a forma não distorce."""
        aneis = divisas().get(uf)
        if not aneis:
            return cls(x0, y0, largura, altura)
        lons = [float(p[0]) for a in aneis for p in a]
        lats = [float(p[1]) for a in aneis for p in a]
        lo0, lo1, la0, la1 = min(lons), max(lons), min(lats), max(lats)
        dl, da = (lo1 - lo0) * (1 + 2 * folga), (la1 - la0) * (1 + 2 * folga)
        proporcao = largura / altura
        if dl / da < proporcao:
            dl = da * proporcao
        else:
            da = dl / proporcao
        clon, clat = (lo0 + lo1) / 2, (la0 + la1) / 2
        return cls(x0, y0, largura, altura, (clon - dl / 2, clon + dl / 2, clat - da / 2, clat + da / 2))

    def px(self, lon: float, lat: float) -> tuple[float, float]:
        x = self.x0 + (lon - self.lon_min) / (self.lon_max - self.lon_min) * self.largura
        y = self.y0 + (self.lat_max - lat) / (self.lat_max - self.lat_min) * self.altura
        return x, y

    def dentro(self, x: float, y: float, folga: float = 0) -> bool:
        return (self.x0 + folga <= x <= self.x0 + self.largura - folga
                and self.y0 + folga <= y <= self.y0 + self.altura - folga)

    def desenhar_contorno(self, tela: Tela, preenchimento=(238, 243, 238), contorno=(120, 140, 120)):
        tela.poligono([self.px(lon, lat) for lon, lat in CONTORNO_BRASIL], preenchimento, contorno)

    def _local(self, anel) -> list[tuple[float, float]]:
        return [(x - self.x0, y - self.y0) for x, y in (self.px(float(p[0]), float(p[1])) for p in anel)]

    def desenhar_ufs(self, tela: Tela, cores: dict, padrao=(236, 238, 241), contorno=(255, 255, 255),
                     espessura: int = 1, hachura=frozenset(), cor_hachura=(150, 150, 150)):
        """Cada UF preenchida pela sua cor (`cores[uf]`, ou `padrao`), com divisas finas, recortada no quadro do
        mapa (uma camada do tamanho do quadro, colada por cima). `hachura`: UFs riscadas em diagonal (no N1, a UF
        cujo total sai SUPRIMIDO; a hachura não depende só da cor)."""
        camada = Image.new("RGBA", (self.largura, self.altura), (0, 0, 0, 0))
        d = ImageDraw.Draw(camada)
        aneis_hachura = []
        for uf, aneis in divisas().items():
            cor = cores.get(uf, padrao)
            for anel in aneis:
                pontos = self._local(anel)
                if len(pontos) >= 3:
                    d.polygon(pontos, fill=tuple(cor) + (255,))
                    if uf in hachura:
                        aneis_hachura.append(pontos)
        if aneis_hachura:
            mascara = Image.new("L", camada.size, 0)
            dm = ImageDraw.Draw(mascara)
            for pontos in aneis_hachura:
                dm.polygon(pontos, fill=255)
            riscos = Image.new("L", camada.size, 0)
            dr = ImageDraw.Draw(riscos)
            for x in range(-self.altura, self.largura, 7):
                dr.line((x, self.altura, x + self.altura, 0), fill=255, width=1)
            alfa = ImageChops.multiply(riscos, mascara)
            tinta = Image.new("RGBA", camada.size, tuple(cor_hachura) + (255,))
            camada.paste(tinta, (0, 0), alfa)
        for aneis in divisas().values():          # divisas por cima de todos os preenchimentos
            for anel in aneis:
                pontos = self._local(anel)
                if len(pontos) >= 3:
                    d.line(pontos + [pontos[0]], fill=tuple(contorno) + (255,), width=espessura)
        tela.colar(camada, self.x0, self.y0)

    @property
    def caixa(self) -> tuple[int, int, int, int]:
        return self.x0, self.y0, self.x0 + self.largura, self.y0 + self.altura
