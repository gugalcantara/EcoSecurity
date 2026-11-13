"""Legenda clicável dos quintis do coroplético.

Passar o mouse num quintil realça as UFs dele (as demais ficam a 25%); clicar
fixa a seleção (clicar de novo limpa). A legenda só emite sinais: quem reage é o
estado compartilhado do painel (mediador).

Título com o indicador e a unidade; rótulos "a a b" com o menor e o maior valor reais de cada quintil (os
intervalos não se sobrepõem: o primeiro começa no mínimo observado, não em 0); a largura de
cada caixa vem da fonte (nada cortado); as entradas SUPRIMIDA e sem ativas mostram os cinzas usados no mapa; a
dica diz quantas UFs há no quintil.

Teclado: Tab percorre as caixas; o foco realça as UFs do quintil, como o mouse; Espaço ou
Enter fixam (de novo, limpam); o foco aparece como borda azul. Cada caixa tem nome e descrição acessíveis.
"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAccessible, QAccessibleEvent
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ecosec.interface.fluent import CaptionLabel

RAMPA = ("#FDE8C9", "#FBC17A", "#F59245", "#E0603A", "#B8323B")      # do menor ao maior quintil
COR_SUPRIMIDA, COR_SEM_ATIVAS = "#BDBDBD", "#E4E4E4"                   # as mesmas do mapa
FOLGA = 14                                                           # px de respiro dentro da caixa
COR_FOCO = "#0063B1"                                                 # borda do foco do teclado


def quintis(valores: dict[str, float]) -> tuple[list[float], dict[str, int]]:
    """(limites superiores dos 5 quintis, {chave: quintil 0..4}). Chaves com valor 0 ficam no quintil 0."""
    ordenados = sorted(valores.values())
    if not ordenados:
        return [0.0] * 5, {}
    limites = [ordenados[min(len(ordenados) - 1, round((k + 1) * len(ordenados) / 5) - 1)] for k in range(5)]
    classe = {}
    for chave, v in valores.items():
        classe[chave] = next((k for k, lim in enumerate(limites) if v <= lim), 4)
    return limites, classe


def _fonte() -> QFont:
    fonte = QFont("Segoe UI")
    fonte.setPixelSize(11)
    return fonte


class _Caixa(QLabel):
    def __init__(self, indice: int, legenda):
        super().__init__()
        self.indice, self.legenda = indice, legenda
        self.setFont(_fonte())
        self.setFixedHeight(24)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleDescription("Passe o mouse ou dê foco para realçar as UFs do quintil; clique, Espaço ou "
                                      "Enter para selecionar")

    def setText(self, texto: str):                                    # noqa: N802, largura pela fonte
        super().setText(texto)
        self.setFixedWidth(self.fontMetrics().horizontalAdvance(texto) + FOLGA + 4)

    def enterEvent(self, evento):
        self.legenda.passou.emit(self.indice)
        super().enterEvent(evento)

    def leaveEvent(self, evento):
        self.legenda.passou.emit(-1)
        super().leaveEvent(evento)

    def mousePressEvent(self, evento):
        if evento.button() == Qt.MouseButton.LeftButton:
            self.legenda.alternar(self.indice)
        super().mousePressEvent(evento)

    def focusInEvent(self, evento):
        super().focusInEvent(evento)
        self.legenda.passou.emit(self.indice)
        self.legenda._pintar()

    def focusOutEvent(self, evento):
        super().focusOutEvent(evento)
        self.legenda.passou.emit(-1)
        self.legenda._pintar()

    def keyPressEvent(self, evento):
        if evento.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.legenda.alternar(self.indice)
            evento.accept()
            return
        super().keyPressEvent(evento)


class _Cinza(QLabel):
    """Entrada fixa (não é quintil, não se clica)."""

    def __init__(self, texto: str, cor: str, dica: str):
        super().__init__()
        self.setFont(_fonte())
        self.setFixedHeight(24)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet(f"background:{cor}; color:#1a1a1a; border:1px solid #9a9a9a; border-radius:3px;")
        self.setToolTip(dica)
        self.definir(texto)

    def definir(self, texto: str):
        self.setText(texto)
        self.setFixedWidth(self.fontMetrics().horizontalAdvance(texto) + FOLGA + 4)


class LegendaQuantis(QWidget):
    passou = Signal(int)                      # quintil sob o mouse (-1 = nenhum)
    escolhido = Signal(int)                   # quintil fixado (-1 = limpou)

    def __init__(self, parent=None):
        super().__init__(parent)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(3)
        topo = QHBoxLayout()
        topo.setSpacing(4)
        self.titulo = CaptionLabel("Legenda")
        topo.addWidget(self.titulo)
        topo.addStretch(1)
        self.suprimida = _Cinza("SUPRIMIDA", COR_SUPRIMIDA, "UF com poucos casos: valor oculto")
        self.sem_ativas = _Cinza("SEM ATIVAS", COR_SEM_ATIVAS, "UF sem nenhuma pendência ativa no ano")
        topo.addWidget(self.suprimida)
        topo.addWidget(self.sem_ativas)
        v.addLayout(topo)
        h = QHBoxLayout()
        h.setSpacing(4)
        self.caixas = [_Caixa(k, self) for k in range(5)]
        for c in self.caixas:
            h.addWidget(c)
        h.addStretch(1)
        v.addLayout(h)
        self.ativo = -1
        self.intervalos: list[tuple[float | None, float | None]] = []
        self.definir([0.0] * 5)

    def definir(self, limites: list[float], formato=lambda v: f"{v:.2f}".replace(".", ","), titulo: str = "",
                inferiores: list[float | None] | None = None, contagens: list[int] | None = None,
                supressao_minima: int = 3, formato_fino=None):
        """limites: o maior valor de cada quintil; inferiores: o menor (None = quintil vazio); contagens:
        UFs por quintil. Sem inferiores, o rótulo usa o limite anterior (compatível com a versão antiga).
        formato_fino (mais casas) entra quando o arredondamento faria dois quintis vizinhos se tocarem."""
        if titulo:
            self.titulo.setText(f"Legenda: {titulo}")
        self.suprimida.definir("SUPRIMIDA")
        self.suprimida.setVisible(supressao_minima > 0)
        if inferiores is not None and formato_fino is not None:
            tocam = any(inferiores[k] is not None and formato(inferiores[k]) == formato(limites[k - 1])
                        for k in range(1, len(limites)))
            formato = formato_fino if tocam else formato
        self.intervalos = []
        for k, (caixa, lim) in enumerate(zip(self.caixas, limites)):
            baixo = inferiores[k] if inferiores is not None else (limites[k - 1] if k else None)
            vazio = inferiores is not None and baixo is None
            if vazio:
                texto = "nenhuma UF"
            elif baixo is None:                      # sem os mínimos (versão antiga): só o limite do 1º quintil
                texto = f"≤ {formato(lim)}" if k == 0 else formato(lim)
            elif formato(baixo) == formato(lim):
                texto = formato(lim)
            else:
                texto = f"{formato(baixo)} a {formato(lim)}"
            caixa.setText(texto)
            # o 1º quintil começa no mínimo real; sem inferiores, fica aberto embaixo
            self.intervalos.append((baixo if (k == 0 and inferiores is not None) or k else None,
                                    None if vazio else lim))
            nome = f"Quintil {k + 1}: {texto}"
            if contagens is not None:
                n = contagens[k]
                nome += f", {n} UF{'s' if n != 1 else ''}"
                caixa.setToolTip(f"Quintil {k + 1}: {n} UF{'s' if n != 1 else ''} ({texto}). "
                                 "Passe o mouse ou dê foco (Tab) para realçar; clique, Espaço ou Enter para "
                                 "selecionar.")
            if caixa.accessibleName() != nome:
                caixa.setAccessibleName(nome)
                try:
                    QAccessible.updateAccessibility(QAccessibleEvent(caixa, QAccessible.Event.NameChanged))
                except Exception:  # noqa: BLE001, sem leitor de tela ativo, nada a avisar
                    pass
        self.setAccessibleName(self.titulo.text())
        self._pintar()

    def alternar(self, indice: int):
        self.ativo = -1 if self.ativo == indice else indice
        self._pintar()
        self.escolhido.emit(self.ativo)

    def _pintar(self):
        for k, caixa in enumerate(self.caixas):
            borda = ("2px solid " + COR_FOCO if caixa.hasFocus() else
                     "2px solid #1a1a1a" if k == self.ativo else "1px solid #9a9a9a")
            texto = "#FFFFFF" if k >= 3 else "#1a1a1a"
            caixa.setStyleSheet(f"background:{RAMPA[k]}; color:{texto}; border:{borda}; border-radius:3px;")
