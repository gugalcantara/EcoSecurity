"""Legenda dinâmica do mapa, sobreposta à vista.

Uma seção por camada visível, na ordem de desenho (a camada de cima primeiro), cada entrada com o mesmo
símbolo do mapa (cor, tamanho e anel vêm de `simbologia`, que o ponto também usa). O texto é sempre na cor
de texto (17:1 sobre o branco), nunca na cor da faixa (2,44:1).

É um QWidget filho da QGraphicsView (não da viewport, que rola junto com a cena): transparente ao mouse,
sem foco, com nome e descrição acessíveis (a descrição lista as entradas, para o leitor de tela).
"""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QAccessible, QAccessibleEvent, QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QWidget

from ecosec.interface.componentes.simbologia import COR_TEXTO, COR_TEXTO_SECUNDARIO, Simbolo, desenhar

ALTURA_LINHA = 16
LARGURA_SIMBOLO = 26
MARGEM = 8


@dataclass(frozen=True)
class Entrada:
    camada: str                    # chave da camada no mapa ("" = cabeçalho geral)
    chave: str                     # rótulo estável (compatível com `linhas_legenda`, ex.: "● CRITICO")
    rotulo: str                    # texto desenhado
    valor: str = ""
    simbolo: Simbolo | None = None
    titulo: bool = False


def _fonte(negrito: bool = False) -> QFont:
    fonte = QFont("Segoe UI")
    fonte.setPixelSize(11)
    if negrito:
        fonte.setWeight(QFont.Weight.DemiBold)
    return fonte


class LegendaMapa(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.entradas: list[Entrada] = []
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAccessibleName("Legenda do mapa")
        self.setVisible(False)

    def definir(self, entradas: list[Entrada]):
        self.entradas = list(entradas)
        descricao = "; ".join(f"{e.rotulo}: {e.valor}" if e.valor else e.rotulo for e in self.entradas)
        if descricao != self.accessibleDescription():
            self.setAccessibleDescription(descricao)
            try:
                QAccessible.updateAccessibility(QAccessibleEvent(self, QAccessible.Event.DescriptionChanged))
            except Exception:  # noqa: BLE001, sem leitor de tela ativo, nada a avisar
                pass
        normal, negrito = QFontMetrics(_fonte()), QFontMetrics(_fonte(True))
        largura = 0
        for e in self.entradas:
            medida = negrito if e.titulo else normal
            texto = medida.horizontalAdvance(e.rotulo) + (0 if e.titulo and not e.simbolo else LARGURA_SIMBOLO + 6)
            valor = normal.horizontalAdvance(e.valor) + 14 if e.valor else 0
            largura = max(largura, texto + valor)
        self.resize(max(180, largura + 2 * MARGEM), ALTURA_LINHA * len(self.entradas) + 2 * MARGEM - 4)
        self.setVisible(bool(self.entradas))
        self.update()

    def paintEvent(self, evento):
        if not self.entradas:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        caixa = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.setPen(QPen(QColor(0, 0, 0, 70)))
        painter.setBrush(QColor(255, 255, 255, 230))
        painter.drawRoundedRect(caixa, 4, 4)
        for i, e in enumerate(self.entradas):
            topo = MARGEM - 2 + i * ALTURA_LINHA
            linha = QRectF(MARGEM, topo, self.width() - 2 * MARGEM, ALTURA_LINHA)
            x_texto = linha.left()
            if e.simbolo is not None:
                desenhar(painter, e.simbolo, QRectF(linha.left(), topo + 1, LARGURA_SIMBOLO, ALTURA_LINHA - 2))
                x_texto += LARGURA_SIMBOLO + 6
            elif not e.titulo:
                x_texto += LARGURA_SIMBOLO + 6
            painter.setFont(_fonte(e.titulo))
            painter.setPen(QColor(COR_TEXTO))
            painter.drawText(QRectF(x_texto, topo, linha.right() - x_texto, ALTURA_LINHA),
                             Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, e.rotulo)
            if e.valor:
                painter.setFont(_fonte())
                painter.setPen(QColor(COR_TEXTO if not e.titulo else COR_TEXTO_SECUNDARIO))
                painter.drawText(linha, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, e.valor)
        painter.end()

    def posicionar(self, area: QRectF):
        """Canto inferior esquerdo da área útil (a viewport, em coordenadas da vista)."""
        self.move(round(area.left() + 10), round(max(area.top() + 4, area.bottom() - self.height() - 10)))

    def ponto_do_simbolo(self, indice: int) -> QPointF:
        """Centro do símbolo da entrada `indice` (em coordenadas do widget), para conferência nos testes."""
        topo = MARGEM - 2 + indice * ALTURA_LINHA
        return QPointF(MARGEM + LARGURA_SIMBOLO / 2, topo + ALTURA_LINHA / 2)
