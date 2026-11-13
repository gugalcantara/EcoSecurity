"""Painel lateral que entra deslizando sobre o mapa.

Sobreposto ao mapa, não uma coluna fixa: o mapa mantém a largura inteira. Abre
com o clique num ponto; fecha com Esc ou com o botão ✕. As abas usam
SegmentedWidget com `lambda *_, c=chave` (o onClick passa checked).
"""
from PySide6.QtCore import QEasingCurve, QEvent, QPoint, QPropertyAnimation, Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QStackedWidget, QVBoxLayout

from ecosec.interface.componentes.animacao import animacoes_ligadas
from ecosec.interface.fluent import FIF, SegmentedWidget, StrongBodyLabel, TransparentToolButton, isDarkTheme


class PainelDeslizante(QFrame):
    fechado = Signal()

    def __init__(self, parent, largura: int = 380):
        super().__init__(parent)
        self._largura, self._aberto = largura, False
        self.setFixedWidth(largura)
        self.setObjectName("painelDeslizante")
        fundo, borda = ("#272727", "#3a3a3a") if isDarkTheme() else ("#FBFBFB", "#D6D6D6")
        self.setStyleSheet(f"#painelDeslizante {{ background:{fundo}; border-left:1px solid {borda}; }}")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 10, 12, 10)
        cabeca = QHBoxLayout()
        self.titulo = StrongBodyLabel()
        self.titulo.setWordWrap(True)
        self.botao_fechar = TransparentToolButton(FIF.CLOSE)
        self.botao_fechar.clicked.connect(lambda *_: self.fechar())
        cabeca.addWidget(self.titulo, 1)
        cabeca.addWidget(self.botao_fechar)
        v.addLayout(cabeca)
        self.abas = SegmentedWidget()
        v.addWidget(self.abas)
        self.pilha = QStackedWidget()
        v.addWidget(self.pilha, 1)
        self._paginas = {}
        self._anim = QPropertyAnimation(self, b"pos", self)
        self._anim.setDuration(260)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.finished.connect(self._ao_terminar)
        parent.installEventFilter(self)
        self.hide()

    @property
    def aberto(self) -> bool:
        return self._aberto

    def adicionar_aba(self, chave: str, texto: str, widget):
        self._paginas[chave] = widget
        self.pilha.addWidget(widget)
        self.abas.addItem(chave, texto, onClick=lambda *_, c=chave: self.mostrar_aba(c))   # o clique passa "checked"
        if len(self._paginas) == 1:
            self.mostrar_aba(chave)

    def mostrar_aba(self, chave: str):
        self.pilha.setCurrentWidget(self._paginas[chave])
        self.abas.setCurrentItem(chave)

    def _posicoes(self) -> tuple[QPoint, QPoint]:
        w = self.parentWidget().width()
        return QPoint(w, 0), QPoint(w - self._largura, 0)

    def _ir(self, abrir: bool):
        fora, dentro = self._posicoes()
        self._aberto = abrir
        self.setFixedHeight(self.parentWidget().height())
        if abrir and not self.isVisible():
            self.move(fora)
            self.show()
            self.raise_()
        if abrir:
            self.setFocus()
        self._anim.stop()
        if not animacoes_ligadas():
            self.move(dentro if abrir else fora)
            self._ao_terminar()
            return
        self._anim.setStartValue(self.pos())
        self._anim.setEndValue(dentro if abrir else fora)
        self._anim.start()

    def _ao_terminar(self):
        self.setVisible(self._aberto)
        if not self._aberto:
            self.fechado.emit()

    def abrir(self):
        self._ir(True)

    def fechar(self):
        if self._aberto:
            self._ir(False)

    def eventFilter(self, obj, evento):
        if obj is self.parentWidget() and evento.type() == QEvent.Type.Resize and self._aberto:
            self.setFixedHeight(obj.height())
            self.move(self._posicoes()[1])
        return False

    def keyPressEvent(self, evento):
        if evento.key() == Qt.Key.Key_Escape:
            self.fechar()
        else:
            super().keyPressEvent(evento)
