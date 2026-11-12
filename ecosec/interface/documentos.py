"""Visualizador de documento do N3: zoom, marca d'água, sem exportação.

  - a imagem recebida já traz a marca visível diagonal e a S9 nos pixels: o zoom não as remove e uma
    captura as contém;
  - uma segunda marca, em coordenadas da janela (drawForeground), cobre recortes ampliados;
  - sem menu de contexto e sem os atalhos de copiar, salvar e imprimir;
  - opcional ([documentos] bloquear_captura): a janela sai preta em capturas de tela (Windows 10 2004+).
    Defesa adicional, não garantia: uma foto da tela continua possível, por isso a marca visível leva o
    hash da consulta, que está na trilha.
"""
import ctypes
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QKeySequence, QPixmap
from PySide6.QtWidgets import QDialog, QGraphicsScene, QGraphicsView, QHBoxLayout, QVBoxLayout

from ecosec.interface.fluent import FIF, CaptionLabel, PushButton, StrongBodyLabel

BLOQUEADAS = (QKeySequence.StandardKey.Copy, QKeySequence.StandardKey.Save, QKeySequence.StandardKey.SaveAs,
              QKeySequence.StandardKey.Print)


class VisualizadorDocumento(QGraphicsView):
    """Mostra a imagem já marcada (visível + S9). Sem exportar, copiar, salvar ou imprimir."""

    def __init__(self, imagem, marca_tela: str, parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.scene().addPixmap(QPixmap.fromImage(imagem))
        self._marca = marca_tela
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self.setBackgroundBrush(QColor("#5A5A5A"))

    def ampliar(self, fator: float) -> bool:
        if 0.25 <= self.transform().m11() * fator <= 6.0:
            self.scale(fator, fator)
            return True
        return False

    def wheelEvent(self, evento):
        self.ampliar(1.25 if evento.angleDelta().y() > 0 else 0.8)

    def keyPressEvent(self, evento):
        if any(evento.matches(k) for k in BLOQUEADAS):
            evento.accept()
            return
        super().keyPressEvent(evento)

    def drawForeground(self, painter, _retangulo):
        """Segunda marca, em coordenadas da janela: um recorte ampliado nunca fica sem marca."""
        painter.save()
        painter.resetTransform()
        painter.setPen(QColor(150, 30, 40, 45))
        painter.setFont(QFont("Segoe UI", 11, QFont.Weight.DemiBold))
        r = self.viewport().rect()
        painter.translate(r.center())
        painter.rotate(-30)
        for y in range(-r.height(), r.height(), 110):
            painter.drawText(-r.width(), y, (self._marca + "      ") * 4)
        painter.restore()


def excluir_de_captura(janela) -> bool:
    """Windows 10 2004+: a janela sai preta em capturas e compartilhamentos de tela."""
    if sys.platform != "win32":
        return False
    wda_excluir_da_captura = 0x11
    try:
        return bool(ctypes.windll.user32.SetWindowDisplayAffinity(int(janela.window().winId()),
                                                                  wda_excluir_da_captura))
    except Exception:  # noqa: BLE001, sem a API (Windows antigo): segue sem a proteção extra
        return False


class JanelaDocumento(QDialog):
    """Diálogo do documento: título, zoom e o visualizador. Nenhum botão de exportar (a matriz nega)."""

    def __init__(self, entrega, parent=None, bloquear_captura: bool = False):
        super().__init__(parent)
        from ecosec.interface.rasterizar_documento import de_bgr
        doc = entrega.documento
        self.setWindowTitle(f"{doc.tipo} {doc.numero}")
        self.resize(980, 760)
        v = QVBoxLayout(self)
        cabeca = QHBoxLayout()
        titulo = StrongBodyLabel(f"{doc.tipo} Nº {doc.numero} · {doc.pendencia_codigo}")
        cabeca.addWidget(titulo, 1)
        self.botao_menos, self.botao_mais = PushButton("−"), PushButton("+")
        self.botao_mais.clicked.connect(lambda *_: self.visualizador.ampliar(1.25))
        self.botao_menos.clicked.connect(lambda *_: self.visualizador.ampliar(0.8))
        cabeca.addWidget(self.botao_menos)
        cabeca.addWidget(self.botao_mais)
        v.addLayout(cabeca)
        self.visualizador = VisualizadorDocumento(de_bgr(entrega.imagem), entrega.marca_visivel, self)
        v.addWidget(self.visualizador, 1)
        aviso = CaptionLabel("Somente visualização. A consulta é registrada.")
        aviso.setWordWrap(True)
        v.addWidget(aviso)
        fechar = PushButton("Fechar")
        fechar.setIcon(FIF.CLOSE)
        fechar.clicked.connect(lambda *_: self.accept())
        v.addWidget(fechar, 0, Qt.AlignmentFlag.AlignRight)
        self.captura_bloqueada = excluir_de_captura(self) if bloquear_captura else False
