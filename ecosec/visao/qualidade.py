"""Fase 2: Pré-processamento (portão de qualidade). Decide se o recorte da face serve para o reconhecimento."""
import math
from dataclasses import dataclass
from enum import Enum

import cv2
import numpy as np

_MASCARA_IMMERKAER = np.array([[1, -2, 1], [-2, 4, -2], [1, -2, 1]], dtype=np.float64)
# pixel estourado, em tons de 0 a 255: abaixo de NIVEL_ESCURO é sombra sem textura; acima de NIVEL_CLARO, luz
NIVEL_ESCURO, NIVEL_CLARO = 15, 250
# a nitidez relativa é medida com o recorte reduzido a este lado (o da face normalizada): o Laplaciano olha 3x3
# pixels, e o mesmo rosto, perto da câmera, espalha os detalhes por mais pixels e pareceria borrado
LADO_NITIDEZ = 200


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
    # absolutas: só informativas (a nitidez vira o score guardado com a amostra)
    nitidez: float                   # variância do Laplaciano
    brilho: float                    # média dos tons
    contraste: float                 # desvio-padrão dos tons
    # as que decidem
    ruido: float                     # sigma do ruído do sensor (Immerkær)
    fracao_escura: float             # pixels <= NIVEL_ESCURO
    fracao_clara: float              # pixels >= NIVEL_CLARO
    nitidez_relativa: float          # variância do Laplaciano / variância dos tons
    contraste_relativo: float        # desvio-padrão / média

    @property
    def score(self) -> float:
        """Um número só (0-1) para guardar com a amostra: nitidez normalizada."""
        return min(1.0, self.nitidez / 500.0)


@dataclass(frozen=True)
class ParametrosQualidade:
    nitidez_relativa_minima: float
    escuros_maximo: float            # fração de pixels quase pretos acima da qual a imagem é escura
    claros_maximo: float             # fração de pixels quase brancos acima da qual a imagem é clara
    contraste_relativo_minimo: float
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


def _nitidez_relativa(recorte_cinza: np.ndarray) -> float:
    """Variância do Laplaciano / variância dos tons, com o recorte grande reduzido a LADO_NITIDEZ."""
    lado = max(recorte_cinza.shape[:2])
    if lado > LADO_NITIDEZ:
        k = LADO_NITIDEZ / lado
        recorte_cinza = cv2.resize(recorte_cinza, (max(1, round(recorte_cinza.shape[1] * k)),
                                                   max(1, round(recorte_cinza.shape[0] * k))),
                                   interpolation=cv2.INTER_AREA)
    variancia = float(recorte_cinza.astype(np.float64).var())
    # imagem lisa: proporção 0 (reprova), sem dividir por zero
    return float(cv2.Laplacian(recorte_cinza, cv2.CV_64F).var()) / variancia if variancia > 0 else 0.0


def medir(recorte_cinza: np.ndarray) -> MedidasQualidade:
    nitidez = float(cv2.Laplacian(recorte_cinza, cv2.CV_64F).var())
    brilho, contraste = float(recorte_cinza.mean()), float(recorte_cinza.std())
    return MedidasQualidade(
        nitidez=nitidez, brilho=brilho, contraste=contraste,
        ruido=float(estimar_ruido(recorte_cinza)),
        fracao_escura=float(np.mean(recorte_cinza <= NIVEL_ESCURO)),
        fracao_clara=float(np.mean(recorte_cinza >= NIVEL_CLARO)),
        nitidez_relativa=_nitidez_relativa(recorte_cinza),
        # imagem toda preta: proporção 0 (reprova), sem dividir por zero
        contraste_relativo=contraste / brilho if brilho > 0 else 0.0,
    )


def avaliar(m: MedidasQualidade, p: ParametrosQualidade) -> tuple[ProblemaQualidade, ...]:
    """Problemas encontrados; vazio = aprovada. Falha segura: NaN reprova."""
    problemas = []
    if not (m.fracao_escura <= p.escuros_maximo):
        problemas.append(ProblemaQualidade.ESCURA)
    if not (m.fracao_clara <= p.claros_maximo):
        problemas.append(ProblemaQualidade.CLARA)
    if not (m.nitidez_relativa >= p.nitidez_relativa_minima):
        problemas.append(ProblemaQualidade.DESFOCADA)
    if not (m.contraste_relativo >= p.contraste_relativo_minimo):
        problemas.append(ProblemaQualidade.SEM_CONTRASTE)
    if not (m.ruido <= p.ruido_maximo):
        problemas.append(ProblemaQualidade.RUIDOSA)
    return tuple(problemas)
