"""O pipeline: as fases 1 a 3 e o portão de qualidade, quadro a quadro.

    quadro BGR ─▶ cinza ─▶ segmentação (Haar/KCF) ─▶ recorte ─▶ qualidade ─▶ normalização
                                                                    │
                                                         reprovado: face_normalizada = None

As fases 4-5 (LBPH) ficam com quem consome o resultado, porque dependem do
CONTEXTO: no login compara-se com o modelo; no cadastro, a face é guardada.

O resultado só traz `face_normalizada` quando há exatamente uma face, visível
por inteiro e aprovada na qualidade. Qualquer outra situação não alimenta o
reconhecimento.
"""
from dataclasses import dataclass, field

import numpy as np

from ecosec.visao.preprocessamento import ParametrosPreprocessamento, Preprocessador
from ecosec.visao.qualidade import MedidasQualidade, ParametrosQualidade, ProblemaQualidade, avaliar, medir
from ecosec.visao.segmentacao import ParametrosSegmentacao, Retangulo, Segmentador, recortar


@dataclass(frozen=True)
class ResultadoQuadro:
    faces: tuple[Retangulo, ...]
    fonte: str                                       # HAAR ou KCF
    largura: int
    altura: int
    medidas: MedidasQualidade | None = None
    problemas: tuple[ProblemaQualidade, ...] = ()
    recorte_cinza: np.ndarray | None = field(default=None, repr=False)     # cru, para a vivacidade
    face_normalizada: np.ndarray | None = field(default=None, repr=False)  # 200×200, para o LBPH

    @property
    def quantidade_faces(self) -> int:
        return len(self.faces)

    @property
    def face_unica(self) -> Retangulo | None:
        return self.faces[0] if len(self.faces) == 1 else None

    @property
    def qualidade_aprovada(self) -> bool:
        return self.face_normalizada is not None

    @property
    def dica(self) -> str | None:
        """A orientação mais útil para quem está diante da câmera, ou None."""
        if not self.faces:
            return "Posicione o rosto no centro da imagem"
        if len(self.faces) > 1:
            return "Apenas uma pessoa por vez diante da câmera"
        if self.recorte_cinza is None:
            return "Afaste-se um pouco: o rosto está saindo do quadro"
        if self.problemas:
            return self.problemas[0].dica
        return None


class PipelineVisao:
    """Uma instância por sessão de vídeo (o rastreador KCF guarda estado)."""

    def __init__(self, p_seg: ParametrosSegmentacao, p_pre: ParametrosPreprocessamento,
                 p_qual: ParametrosQualidade, segmentador=None):
        self.p_seg, self.p_qual = p_seg, p_qual
        self.preprocessador = Preprocessador(p_pre)
        self.segmentador = segmentador or Segmentador(p_seg)

    @classmethod
    def de_configuracao(cls, cfg) -> "PipelineVisao":
        return cls(ParametrosSegmentacao.de_configuracao(cfg),
                   ParametrosPreprocessamento.de_configuracao(cfg),
                   ParametrosQualidade.de_configuracao(cfg))

    def processar(self, quadro_bgr: np.ndarray) -> ResultadoQuadro:
        alt, larg = quadro_bgr.shape[:2]
        cinza = self.preprocessador.cinza(quadro_bgr)
        faces, fonte = self.segmentador.processar(quadro_bgr, cinza)
        base = dict(faces=tuple(faces), fonte=fonte, largura=larg, altura=alt)
        if len(faces) != 1:
            return ResultadoQuadro(**base)

        recorte = recortar(cinza, faces[0], self.p_seg.fracao_minima_visivel)
        if recorte is None or recorte.size == 0:
            return ResultadoQuadro(**base)
        medidas = medir(recorte)
        problemas = avaliar(medidas, self.p_qual)
        normalizada = None if problemas else self.preprocessador.normalizar(recorte)
        return ResultadoQuadro(**base, medidas=medidas, problemas=problemas,
                               recorte_cinza=recorte, face_normalizada=normalizada)
