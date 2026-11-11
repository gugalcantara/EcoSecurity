"""Linha do tempo com marcadores de evento.

Triângulos vermelhos nos anos dos eventos regulatórios; passar o mouse perto de
um marcador mostra o(s) evento(s) com o ano. Marcadores que ficariam sobrepostos
(menos de LARGURA px entre si) viram um só, um pouco maior, e a dica lista todos.
O mapa só é refeito ao soltar o controle (ou com as setas do teclado): arrastar
não reconstrói a cena a cada passo.
"""
from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPolygonF
from PySide6.QtWidgets import QSlider, QStyle, QStyleOptionSlider, QToolTip

LARGURA = 8.0                                           # base do triângulo, em px


class SliderEventos(QSlider):
    ano_escolhido = Signal(int)                       # emitido ao soltar (ou pelo teclado)

    def __init__(self, eventos=(), inicio: int = 2006, fim: int = 2026, parent=None):
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.setRange(inicio, fim)
        self.setValue(fim)
        self.setMinimumHeight(36)
        self.setMouseTracking(True)
        self.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.setTickInterval(1)
        self.setPageStep(1)
        self._eventos = list(eventos)                 # (ano, rótulo)
        self.sliderReleased.connect(lambda: self.ano_escolhido.emit(self.value()))
        self.valueChanged.connect(lambda v: None if self.isSliderDown() else self.ano_escolhido.emit(v))

    def definir_eventos(self, eventos, inicio: int, fim: int):
        self._eventos = list(eventos)
        self.blockSignals(True)
        self.setRange(inicio, fim)
        self.setValue(fim)
        self.blockSignals(False)
        self.update()

    def x_do_valor(self, valor: float) -> float:
        op = QStyleOptionSlider()
        self.initStyleOption(op)
        sulco = self.style().subControlRect(QStyle.ComplexControl.CC_Slider, op,
                                            QStyle.SubControl.SC_SliderGroove, self)
        alca = self.style().subControlRect(QStyle.ComplexControl.CC_Slider, op,
                                           QStyle.SubControl.SC_SliderHandle, self)
        util = max(1, sulco.width() - alca.width())
        inteiro = int(valor)
        x = sulco.x() + alca.width() / 2 + QStyle.sliderPositionFromValue(self.minimum(), self.maximum(),
                                                                           inteiro, util)
        passo = util / max(1, self.maximum() - self.minimum())
        return x + (valor - inteiro) * passo

    def marcadores(self) -> list[tuple[float, list[tuple[float, str]]]]:
        """[(x do marcador, [(ano, rótulo), ...])]: eventos a menos de LARGURA px entre si viram um marcador."""
        grupos: list[list] = []
        for ano, rotulo in sorted((e for e in self._eventos if self.minimum() <= e[0] <= self.maximum()),
                                  key=lambda e: e[0]):
            x = self.x_do_valor(ano)
            if grupos and x - grupos[-1][-1][0] < LARGURA + 1:
                grupos[-1].append((x, ano, rotulo))
            else:
                grupos.append([(x, ano, rotulo)])
        return [(sum(x for x, _, _ in g) / len(g), [(a, r) for _, a, r in g]) for g in grupos]

    def paintEvent(self, evento):
        super().paintEvent(evento)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#c0392b"))
        for x, grupo in self.marcadores():
            meia = LARGURA / 2 + (1.5 if len(grupo) > 1 else 0)
            p.drawPolygon(QPolygonF([QPointF(x - meia, 0), QPointF(x + meia, 0), QPointF(x, 7 + (len(grupo) > 1))]))
        p.end()

    def eventos_perto(self, x: float, tolerancia: float = 6.0) -> list[str]:
        return [f"{int(a)} · {r}" for mx, grupo in self.marcadores() if abs(mx - x) <= tolerancia + LARGURA / 2 * (
            len(grupo) > 1) for a, r in grupo]

    def mouseMoveEvent(self, evento):
        perto = self.eventos_perto(evento.position().x())
        if perto:
            QToolTip.showText(evento.globalPosition().toPoint(), "\n".join(perto), self)
        else:
            QToolTip.hideText()
        super().mouseMoveEvent(evento)
