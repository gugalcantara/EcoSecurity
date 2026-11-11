"""Portão de qualidade: medir se o recorte da face serve para decidir.

As medidas são feitas no recorte cru, antes do CLAHE. O realce existe para
salvar imagens medianas; aplicado antes da medição, ele faria uma imagem quase
preta parecer aceitável: e é justamente essa que o portão precisa barrar.

Medidas:
- Nitidez: variância do Laplaciano. O Laplaciano realça bordas; numa imagem
  borrada (movimento, foco) quase não há bordas, e a variância despenca.
- Brilho: média dos tons. Escura demais esconde textura; clara demais estoura.
- Contraste: desvio-padrão dos tons. Baixo = imagem "lavada", sem textura.
- Ruído: método de Immerkær (1996). Convolui com uma máscara que anula
  regiões lisas e bordas lineares, sobrando essencialmente o ruído do sensor.

Cada problema traz uma dica com a ação a tomar ("acenda uma luz à sua frente"),
não o diagnóstico ("imagem escura"): é isso que a pessoa consegue corrigir.
"""
import math
from dataclasses import dataclass
from enum import Enum

import cv2
import numpy as np

_MASCARA_IMMERKAER = np.array([[1, -2, 1], [-2, 4, -2], [1, -2, 1]], dtype=np.float64)


class ProblemaQualidade(str, Enum):
    ESCURA = "ESCURA"
    CLARA = "CLARA"
    DESFOCADA = "DESFOCADA"
    SEM_CONTRASTE = "SEM_CONTRASTE"
    RUIDOSA = "RUIDOSA"

    @property
    def dica(self) -> str:
        return {
            ProblemaQualidade.ESCURA: "Acenda uma luz à sua frente",
            ProblemaQualidade.CLARA: "Afaste-se da luz forte ou da janela",
            ProblemaQualidade.DESFOCADA: "Fique parado por um instante",
            ProblemaQualidade.SEM_CONTRASTE: "Evite luz por trás de você",
            ProblemaQualidade.RUIDOSA: "Aumente a iluminação do ambiente",
        }[self]


@dataclass(frozen=True)
class MedidasQualidade:
    nitidez: float
    brilho: float
    contraste: float
    ruido: float

    @property
    def score(self) -> float:
        """Um número só (0-1) para guardar com a amostra: nitidez normalizada."""
        return min(1.0, self.nitidez / 500.0)


@dataclass(frozen=True)
class ParametrosQualidade:
    nitidez_minima: float
    brilho_minimo: float
    brilho_maximo: float
    contraste_minimo: float
    ruido_maximo: float

    @classmethod
    def de_configuracao(cls, cfg) -> "ParametrosQualidade":
        return cls(**{k: float(v) for k, v in cfg.secao("qualidade").items()})


def estimar_ruido(cinza: np.ndarray) -> float:
    alt, larg = cinza.shape[:2]
    if alt < 3 or larg < 3:
        return 0.0
    resposta = cv2.filter2D(cinza.astype(np.float64), -1, _MASCARA_IMMERKAER)[1:-1, 1:-1]
    return math.sqrt(math.pi / 2) * np.abs(resposta).sum() / (6 * (larg - 2) * (alt - 2))


def medir(recorte_cinza: np.ndarray) -> MedidasQualidade:
    return MedidasQualidade(
        nitidez=float(cv2.Laplacian(recorte_cinza, cv2.CV_64F).var()),
        brilho=float(recorte_cinza.mean()),
        contraste=float(recorte_cinza.std()),
        ruido=float(estimar_ruido(recorte_cinza)),
    )


def avaliar(m: MedidasQualidade, p: ParametrosQualidade) -> tuple[ProblemaQualidade, ...]:
    """Problemas encontrados; vazio = aprovada. Falha segura: NaN reprova."""
    problemas = []
    if not (m.brilho >= p.brilho_minimo):
        problemas.append(ProblemaQualidade.ESCURA)
    if not (m.brilho <= p.brilho_maximo):
        problemas.append(ProblemaQualidade.CLARA)
    if not (m.nitidez >= p.nitidez_minima):
        problemas.append(ProblemaQualidade.DESFOCADA)
    if not (m.contraste >= p.contraste_minimo):
        problemas.append(ProblemaQualidade.SEM_CONTRASTE)
    if not (m.ruido <= p.ruido_maximo):
        problemas.append(ProblemaQualidade.RUIDOSA)
    return tuple(problemas)
