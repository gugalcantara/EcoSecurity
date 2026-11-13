"""A "tela" onde os relatórios são desenhados: e que anota o que é sensível.

O ponto central: todo texto sensível é desenhado já com o seu rótulo de
proteção, por exemplo

    tela.texto(x, y, pendencia.endereco, sensivel=("ENDERECO", 2))

A região a esconder é registrada no mesmo gesto de desenhar o dado. Não há
como desenhar um endereço e "esquecer" de marcá-lo: o erro clássico da
marcação manual de retângulos, que além disso desalinha quando o layout muda.

Pillow (e não o putText do OpenCV) porque os relatórios são em português: o
putText não desenha "ç" nem "ã".
"""
import math
from dataclasses import dataclass
from functools import lru_cache

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from ecosec.dominio.acervo import RegiaoSensivel

TINTA = (34, 34, 34)
CINZA = (110, 110, 110)
LINHA = (210, 210, 210)
VERMELHO = (190, 40, 55)
FOLGA = 3                     # px em volta do texto sensível: a tarja cobre também a borda das letras

# marca d'água visível: cinza, porque nos relatórios o vermelho quer dizer "crítico";
# 22% é a opacidade da marca dos documentos do N3 (interface/rasterizar_documento.py)
COR_MARCA = (120, 120, 120)
OPACIDADE_MARCA = 0.22
ANGULO_MARCA = 30             # graus, subindo da esquerda para a direita, como nos documentos
PASSO_MARCA = 260             # px entre duas linhas da marca
TAMANHO_MARCA = 20


@dataclass(frozen=True)
class Fontes:
    regular: str
    negrito: str

    @classmethod
    def de_configuracao(cls, cfg) -> "Fontes":
        return cls(cfg["acervo.fonte_regular"], cfg["acervo.fonte_negrito"])


@lru_cache(maxsize=64)
def _fonte(arquivo: str, tamanho: int) -> ImageFont.ImageFont:
    try:
        return ImageFont.truetype(arquivo, tamanho)
    except OSError:                      # fonte ausente na máquina: segue com a padrão
        return ImageFont.load_default(tamanho)


class Tela:
    def __init__(self, largura: int, altura: int, fontes: Fontes):
        self.largura, self.altura = largura, altura
        self.fontes = fontes
        self.img = Image.new("RGB", (largura, altura), (255, 255, 255))
        self.d = ImageDraw.Draw(self.img)
        self.regioes: list[RegiaoSensivel] = []
        self.fundo = 0                     # maior y já desenhado

    def fonte(self, tamanho: int, negrito: bool = False):
        return _fonte(self.fontes.negrito if negrito else self.fontes.regular, tamanho)

    # regiões
    def marcar(self, x0, y0, x1, y1, rotulo: str, nivel_minimo: int) -> None:
        self.regioes.append(RegiaoSensivel(int(x0) - FOLGA, int(y0) - FOLGA, int(x1 - x0) + 2 * FOLGA,
                                           int(y1 - y0) + 2 * FOLGA, rotulo, nivel_minimo))

    # desenho
    def texto(self, x, y, conteudo: str, tamanho: int = 15, negrito: bool = False, cor=TINTA,
              sensivel: tuple[str, int] | None = None, largura_max: int | None = None) -> int:
        """Desenha (quebrando linhas se largura_max) e devolve a altura ocupada."""
        fonte = self.fonte(tamanho, negrito)
        linhas = self._quebrar(str(conteudo), fonte, largura_max) if largura_max else [str(conteudo)]
        altura_linha = int(tamanho * 1.35)
        x1 = x
        for i, linha in enumerate(linhas):
            self.d.text((x, y + i * altura_linha), linha, font=fonte, fill=cor)
            x1 = max(x1, x + self.d.textlength(linha, font=fonte))
        total = altura_linha * len(linhas)
        self.fundo = max(self.fundo, y + total)
        if sensivel:
            self.marcar(x, y, x1, y + total, *sensivel)
        return total

    def _quebrar(self, conteudo, fonte, largura_max):
        linhas, atual = [], ""
        for palavra in conteudo.split():
            tentativa = f"{atual} {palavra}".strip()
            if self.d.textlength(tentativa, font=fonte) <= largura_max or not atual:
                atual = tentativa
            else:
                linhas.append(atual)
                atual = palavra
        return linhas + ([atual] if atual else [])

    def retangulo(self, x0, y0, x1, y1, preenchimento=None, contorno=None, espessura=1, raio=0):
        self.d.rounded_rectangle((x0, y0, x1, y1), radius=raio, fill=preenchimento, outline=contorno,
                                 width=espessura)
        self.fundo = max(self.fundo, y1)

    def linha(self, x0, y0, x1, y1, cor=LINHA, espessura=1):
        self.d.line((x0, y0, x1, y1), fill=cor, width=espessura)

    def circulo(self, x, y, raio, cor, contorno=None):
        self.d.ellipse((x - raio, y - raio, x + raio, y + raio), fill=cor, outline=contorno)

    def poligono(self, pontos, preenchimento=None, contorno=None):
        self.d.polygon(pontos, fill=preenchimento, outline=contorno)
        self.fundo = max(self.fundo, max(y for _, y in pontos))

    def barra(self, x, y, largura_max, valor, maximo, altura=14, cor=(52, 120, 180)):
        largura = 0 if maximo <= 0 else max(2, int(largura_max * valor / maximo))
        self.retangulo(x, y, x + largura, y + altura, preenchimento=cor, raio=3)
        return largura

    def colar(self, camada: Image.Image, x: int, y: int) -> None:
        """Cola uma camada RGBA (mapa recortado, calor) respeitando a transparência dela."""
        self.img.paste(camada, (int(x), int(y)), camada)
        self.fundo = max(self.fundo, int(y) + camada.height)

    def cortar(self, altura: int) -> None:
        """Encerra a página em altura (sem sobra em branco)."""
        altura = int(min(max(altura, 200), self.img.height))
        self.img = self.img.crop((0, 0, self.largura, altura))
        self.d = ImageDraw.Draw(self.img)
        self.altura = altura

    def para_bgr(self) -> np.ndarray:
        """O OpenCV (tarja, marca d'água) trabalha em BGR."""
        return np.ascontiguousarray(np.asarray(self.img)[:, :, ::-1])


def desenhar_marca_visivel(imagem: np.ndarray, texto: str, fonte: str = "segoeuib.ttf") -> np.ndarray:
    """Marca d'água visível: texto em diagonal, repetido pela página inteira, cinza a 22%. Devolve uma cópia (BGR).

    Trabalha sobre a imagem pronta, fora da Tela: a marca não é conteúdo do relatório (não vira região sensível nem
    entra na conferência de sobreposição). Vem depois da tarja (S8) e antes da S9: pintar depois da S9 degradaria os
    coeficientes da marca invisível. Dissuade quem vê; quem prova a origem continua sendo a S9."""
    altura, largura = imagem.shape[:2]
    lado = int(math.hypot(largura, altura)) + 2 * PASSO_MARCA      # cobre a página em qualquer ângulo
    mascara = Image.new("L", (lado, lado), 0)
    d = ImageDraw.Draw(mascara)
    letra = _fonte(fonte, TAMANHO_MARCA)
    vao = "      "
    passo_texto = d.textlength(texto + vao, font=letra)
    faixa = vao.join([texto] * (int(lado / passo_texto) + 2))
    for i, y in enumerate(range(0, lado, PASSO_MARCA)):
        d.text((-(i % 2) * passo_texto / 2, y), faixa, font=letra, fill=255)   # linhas alternadas, desencontradas
    mascara = mascara.rotate(ANGULO_MARCA, resample=Image.Resampling.BILINEAR)
    x0, y0 = (lado - largura) // 2, (lado - altura) // 2
    mascara = mascara.crop((x0, y0, x0 + largura, y0 + altura)).point(lambda v: round(v * OPACIDADE_MARCA))
    base = Image.fromarray(np.ascontiguousarray(imagem[:, :, ::-1]))
    marcada = Image.composite(Image.new("RGB", (largura, altura), COR_MARCA), base, mascara)
    return np.ascontiguousarray(np.asarray(marcada)[:, :, ::-1])


@dataclass(frozen=True)
class Documento:
    imagem: np.ndarray                    # BGR, com TODO o conteúdo: nunca sai do servidor assim
    regioes: tuple[RegiaoSensivel, ...]
