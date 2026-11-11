"""Fase 2, Pré-processamento: deixar toda face comparável a qualquer outra.

    recorte colorido ─▶ cinza ─▶ 200×200 ─▶ CLAHE ─▶ suavização ─▶ face normalizada

- Cinza: o LBP compara intensidades de vizinhos; a cor não acrescenta nada e
  triplicaria o custo.
- 200×200 ANTES do CLAHE: os blocos do CLAHE (8×8) passam a cobrir sempre a
  mesma porção do rosto, perto ou longe da câmera.
- CLAHE (equalização adaptativa com limite de contraste): uma lâmpada do lado
  esquerdo deixa metade do rosto escura. A equalização global não resolve isso;
  a local, por blocos, sim. O limite (clip) evita amplificar o ruído de regiões
  lisas como a testa.
- Suavização gaussiana leve: o LBP é sensível a ruído de pixel isolado (um único
  pixel ruidoso muda o código binário inteiro daquele vizinho).
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
