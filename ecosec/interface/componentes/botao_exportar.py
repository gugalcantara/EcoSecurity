"""Botão Exportar com cadeado: informa se a exportação vai pedir o rosto de novo.

A interface nunca decide permissão: o cadeado é só informativo. Quem decide é o
serviço (matriz de autorização + step-up). `janela_min` vem de
[contexto] verificacao_minutos, a mesma chave do serviço, para os dois não divergirem.

A biblioteca Fluent instalada não tem FluentIcon.LOCK: o ícone vem do glifo da
fonte do sistema (Segoe Fluent Icons no Windows 11, Segoe MDL2 Assets no 10).
"""
from datetime import datetime, timedelta

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontDatabase, QIcon, QPainter, QPixmap

from ecosec.interface.fluent import PushButton

TRAVA, DESTRAVA = "", ""          # Lock e Unlock nas fontes de ícones do Windows


def icone_glifo(glifo: str, cor: str = "#5c5c5c", tamanho: int = 16) -> QIcon:
    familia = next((f for f in ("Segoe Fluent Icons", "Segoe MDL2 Assets") if f in QFontDatabase.families()), None)
    pix = QPixmap(tamanho * 2, tamanho * 2)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setPen(QColor(cor))
    if familia:
        p.setFont(QFont(familia, tamanho))
        p.drawText(pix.rect(), Qt.AlignmentFlag.AlignCenter, glifo)
    else:                                     # sem a fonte de ícones: um cadeado desenhado à mão
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(QColor(cor))
        p.drawRoundedRect(8, 14, 16, 13, 2, 2)
        p.setBrush(Qt.BrushStyle.NoBrush)
        pen = p.pen()
        pen.setWidth(3)
        p.setPen(pen)
        p.drawArc(10, 4, 12, 16, 0, 180 * 16 if glifo == TRAVA else 100 * 16)
    p.end()
    pix.setDevicePixelRatio(2)
    return QIcon(pix)


class BotaoExportar(PushButton):
    """`sessao` precisa ter `verificacao.momento` (SessaoAplicacao). Sem sessão: cadeado fechado."""

    def __init__(self, texto: str = "", sessao=None, janela_min: float = 5.0, relogio=datetime.now, parent=None):
        # o PushButton do Fluent sobrecarrega __init__ (singledispatch): a versão com texto chama de volta
        # self.__init__(parent=...). Usar só a versão por pai e pôr o texto depois evita a reentrada.
        super().__init__(parent)
        self.setText(texto)
        self._sessao, self._janela, self._relogio = sessao, timedelta(minutes=janela_min), relogio
        self._timer = QTimer(self)
        self._timer.setInterval(10_000)
        self._timer.timeout.connect(self.atualizar)
        self._timer.start()
        self.livre = False
        self.atualizar()

    def definir_sessao(self, sessao):
        self._sessao = sessao
        self.atualizar()

    def atualizar(self):
        verificacao = getattr(self._sessao, "verificacao", None)
        if verificacao is None:
            self.livre, minutos = False, None
        else:
            idade = self._relogio() - verificacao.momento
            minutos = max(0, int(idade.total_seconds() // 60))
            self.livre = idade <= self._janela
        self.setIcon(icone_glifo(DESTRAVA if self.livre else TRAVA, "#2e7d32" if self.livre else "#b26a00"))
        if minutos is None:
            self.setToolTip("EXPORTAR VAI PEDIR O ROSTO")
        elif self.livre:
            self.setToolTip(f"ROSTO CONFERIDO HA {minutos} MIN · EXPORTACAO LIBERADA")
        else:
            self.setToolTip(f"ULTIMA CONFERENCIA HA {minutos} MIN · EXPORTAR VAI PEDIR O ROSTO")
