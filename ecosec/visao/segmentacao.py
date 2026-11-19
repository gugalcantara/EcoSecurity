"""Fase 3: Segmentação. Localiza a face e a separa do resto da cena.

A detecção usa o classificador em cascata de Haar (Viola-Jones): uma sequência de classificadores simples
sobre retângulos claros e escuros, rápida em CPU e sem rede neural. O detector varre uma cópia do quadro
reduzida e equalizada pelo histograma, e as coordenadas voltam à escala original.

Entre as detecções, o rastreador KCF acompanha a face. O Haar percorre a imagem inteira em várias escalas
(10 a 15 ms), enquanto o KCF só procura perto da posição anterior (cerca de 2 ms). Com o Haar a cada N
quadros e o KCF nos intermediários, a face fica estável por uma fração do custo.

O KCF segue uma única face e não percebe quem entra na cena. Por isso a contagem de faces (uma pessoa por
vez) é feita nos quadros do Haar, que nunca deixam de acontecer, e as decisões exigem vários quadros
seguidos.
"""
from dataclasses import dataclass

import cv2
import numpy as np

Retangulo = tuple[int, int, int, int]       # x, y, largura, altura


@dataclass(frozen=True)
class ParametrosSegmentacao:
    haar_face: str
    scale_factor: float
    min_neighbors: int
    min_size: tuple[int, int]
    detectar_a_cada: int
    fracao_minima_visivel: float
    escala_deteccao: float = 1.0     # o Haar varre uma cópia reduzida; as coordenadas voltam à escala original

    @classmethod
    def de_configuracao(cls, cfg) -> "ParametrosSegmentacao":
        s = cfg.secao("segmentacao")
        return cls(s["haar_face"], float(s["scale_factor"]), int(s["min_neighbors"]),
                   tuple(s["min_size"]), int(s["detectar_a_cada"]), float(s["fracao_minima_visivel"]),
                   float(s["escala_deteccao"]))


def carregar_cascata(arquivo: str) -> cv2.CascadeClassifier:
    """Carrega um classificador em cascata de Haar que vem com a OpenCV
    (cv2.data.haarcascades), treinado por AdaBoost no método de Viola-Jones."""
    cascata = cv2.CascadeClassifier(cv2.data.haarcascades + arquivo)
    if cascata.empty():
        raise RuntimeError(f"Classificador Haar não carregou: {arquivo}")
    return cascata


class DetectorFaces:
    """Haar sobre a imagem inteira."""

    def __init__(self, p: ParametrosSegmentacao):
        self.p = p
        self._cascata = carregar_cascata(p.haar_face)

    def detectar(self, cinza: np.ndarray) -> list[Retangulo]:
        # equalização global só para detectar (não para reconhecer): o Haar
        # depende de contraste entre regiões e falha em imagem escura
        e = self.p.escala_deteccao
        reduzida = cinza if e == 1.0 else cv2.resize(cinza, None, fx=e, fy=e, interpolation=cv2.INTER_AREA)
        equalizada = cv2.equalizeHist(reduzida)
        minimo = (max(24, int(self.p.min_size[0] * e)), max(24, int(self.p.min_size[1] * e)))
        faces = self._cascata.detectMultiScale(equalizada, scaleFactor=self.p.scale_factor,
                                               minNeighbors=self.p.min_neighbors, minSize=minimo)
        # coordenadas de volta à imagem cheia: o recorte para o LBPH sai da resolução original
        return [tuple(int(round(v / e)) for v in f) for f in faces]


class Segmentador:
    """Haar a cada N quadros, KCF entre eles."""

    def __init__(self, p: ParametrosSegmentacao, detector=None, criar_rastreador=None):
        self.p = p
        self._detector = detector or DetectorFaces(p)
        self._criar_rastreador = criar_rastreador or cv2.TrackerKCF_create
        self._rastreador = None
        self._contador = 0

    def processar(self, quadro_bgr: np.ndarray, cinza: np.ndarray) -> tuple[list[Retangulo], str]:
        """Devolve (faces, fonte), fonte = "HAAR" ou "KCF"."""
        hora_de_detectar = self._contador % self.p.detectar_a_cada == 0
        self._contador += 1
        if self._rastreador is not None and not hora_de_detectar:
            ok, caixa = self._rastreador.update(quadro_bgr)
            if ok:
                return [tuple(int(v) for v in caixa)], "KCF"
            self._rastreador = None              # perdeu a face: volta ao Haar já

        faces = self._detector.detectar(cinza)
        self._rastreador = None
        if len(faces) == 1:                      # só rastreia quando há exatamente uma
            self._rastreador = self._criar_rastreador()
            self._rastreador.init(quadro_bgr, faces[0])
        return faces, "HAAR"

    def reiniciar(self):
        self._rastreador = None
        self._contador = 0


def fracao_visivel(ret: Retangulo, largura_img: int, altura_img: int) -> float:
    """Que fração do retângulo está dentro da imagem (o KCF devolve coordenadas
    negativas quando a face encosta na borda)."""
    x, y, w, h = ret
    if w <= 0 or h <= 0:
        return 0.0
    dentro_w = max(0, min(x + w, largura_img) - max(x, 0))
    dentro_h = max(0, min(y + h, altura_img) - max(y, 0))
    return (dentro_w * dentro_h) / (w * h)


def recortar(imagem: np.ndarray, ret: Retangulo, fracao_minima: float) -> np.ndarray | None:
    """Recorte limitado à imagem; None se pouco da face estiver visível."""
    alt, larg = imagem.shape[:2]
    if fracao_visivel(ret, larg, alt) < fracao_minima:
        return None
    x, y, w, h = ret
    x0, y0 = max(x, 0), max(y, 0)
    x1, y1 = min(x + w, larg), min(y + h, alt)
    return imagem[y0:y1, x0:x1]
