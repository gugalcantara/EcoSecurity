"""Fase 2: Pré-processamento. Deixa toda face comparável a qualquer outra.

Atua antes e depois da segmentação. Antes, converte o quadro para níveis de cinza (cinza()); a cópia
reduzida e equalizada que o detector usa é preparada junto da detecção, em segmentacao.py. Depois, sobre o
recorte da face aprovado no portão de qualidade (qualidade.py), faz a normalização (normalizar()):

    recorte em cinza -> 200x200 -> CLAHE -> suavização gaussiana -> face normalizada

- Cinza: o LBP compara intensidades de pixels vizinhos; a cor não acrescenta informação e triplicaria o
  custo.
- 200x200 antes do CLAHE: os blocos do CLAHE (grade 8x8) cobrem sempre a mesma porção do rosto, perto ou
  longe da câmera.
- CLAHE (equalização adaptativa com limite de contraste): uma luz lateral deixa metade do rosto escura, o
  que a equalização global não corrige e a equalização por blocos corrige. O limite de contraste evita
  amplificar o ruído de regiões lisas, como a testa.
- Suavização gaussiana leve: um único pixel ruidoso altera o código binário do LBP de todos os vizinhos
  dele.
"""
from dataclasses import dataclass

import cv2
import numpy as np


@dataclass(frozen=True)
class ParametrosPreprocessamento:
    clahe_clip_limit: float
    clahe_grade: tuple[int, int]
    ruido_kernel: int
    dimensao_face: tuple[int, int]

    @classmethod
    def de_configuracao(cls, cfg) -> "ParametrosPreprocessamento":
        p = cfg.secao("preprocessamento")
        return cls(float(p["clahe_clip_limit"]), tuple(p["clahe_grade"]), int(p["ruido_kernel"]),
                   tuple(p["dimensao_face"]))


class Preprocessador:
    def __init__(self, parametros: ParametrosPreprocessamento):
        self.p = parametros
        if parametros.ruido_kernel and parametros.ruido_kernel % 2 == 0:
            raise ValueError("ruido_kernel precisa ser ímpar (ou 0 para desligar).")
        self._clahe = cv2.createCLAHE(clipLimit=parametros.clahe_clip_limit,
                                      tileGridSize=parametros.clahe_grade)

    @staticmethod
    def cinza(quadro_bgr: np.ndarray) -> np.ndarray:
        """O OpenCV entrega BGR (não RGB)."""
        if quadro_bgr.ndim == 2:
            return quadro_bgr
        return cv2.cvtColor(quadro_bgr, cv2.COLOR_BGR2GRAY)

    def normalizar(self, recorte_cinza: np.ndarray) -> np.ndarray:
        # INTER_AREA para reduzir (média de pixels, sem serrilhado);
        # INTER_LINEAR para ampliar
        alt, larg = recorte_cinza.shape[:2]
        alvo_larg, alvo_alt = self.p.dimensao_face
        interp = cv2.INTER_AREA if larg > alvo_larg else cv2.INTER_LINEAR
        face = cv2.resize(recorte_cinza, (alvo_larg, alvo_alt), interpolation=interp)
        face = self._clahe.apply(face)
        if self.p.ruido_kernel:
            face = cv2.GaussianBlur(face, (self.p.ruido_kernel, self.p.ruido_kernel), 0)
        return face
