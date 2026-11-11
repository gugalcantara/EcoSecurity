"""Página "Camadas de segurança": as dez camadas, a pergunta de cada uma
e o estado de cada uma. Serve à apresentação.

Todas as dez estão implementadas e testadas. A S7 (regra dos dois) pode ser
desligada na configuração; desligada, o cartão diz isso em vez de "Implementada".
"""
from PySide6.QtWidgets import QGridLayout, QVBoxLayout, QWidget

from ecosec.dominio.camadas import Anel, CamadaSeguranca, camadas_do_anel
from ecosec.interface.estilo import AMBAR, VERDE
from ecosec.interface.fluent import (BodyLabel, CaptionLabel, ScrollArea, SimpleCardWidget,
                                     StrongBodyLabel, SubtitleLabel, TitleLabel)

# camadas que a configuração pode desligar (a S7, regra dos dois)
DESLIGAVEIS = frozenset({CamadaSeguranca.S7_CUSTODIA})
IMPLEMENTADA = "Implementada"
DESLIGADA = "Implementada · desligada por configuração"


class PaginaCamadas(ScrollArea):
    def __init__(self, parent=None, desligadas=frozenset()):
        super().__init__(parent)
        self.desligadas = frozenset(desligadas) & DESLIGAVEIS
        self.setObjectName("paginaCamadas")
        self.setWidgetResizable(True)
        self.setViewportMargins(0, 0, 0, 0)
        self.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        conteudo = QWidget()
        conteudo.setStyleSheet("background: transparent;")
        v = QVBoxLayout(conteudo)
        v.setContentsMargins(36, 28, 36, 28)
        v.setSpacing(10)
        v.addWidget(TitleLabel("Camadas de segurança"))
        intro = BodyLabel("Cada camada responde a uma única pergunta. No Anel 1 a numeração é também a "
                          "ordem de avaliação: a câmera nem é aberta para quem errou a senha.")
        intro.setWordWrap(True)
        v.addWidget(intro)
        for anel in Anel:
            v.addSpacing(10)
            v.addWidget(SubtitleLabel(f"Anel {list(Anel).index(anel) + 1}: {anel.value}"))
            grade = QGridLayout()
            grade.setSpacing(12)
            for i, camada in enumerate(camadas_do_anel(anel)):
                grade.addWidget(self._cartao(camada), i // 3, i % 3)
            v.addLayout(grade)
        v.addStretch(1)
        self.setWidget(conteudo)

    def _cartao(self, camada: CamadaSeguranca):
        cartao = SimpleCardWidget()
        c = QVBoxLayout(cartao)
        c.setContentsMargins(18, 14, 18, 14)
        c.addWidget(StrongBodyLabel(f"{camada.codigo}  {camada.nome}"))
        pergunta = BodyLabel(camada.pergunta)
        pergunta.setWordWrap(True)
        c.addWidget(pergunta)
        texto, cor = (DESLIGADA, AMBAR) if camada in self.desligadas else (IMPLEMENTADA, VERDE)
        estado = CaptionLabel(texto)
        estado.setStyleSheet(f"color:{cor};")
        c.addWidget(estado)
        return cartao
