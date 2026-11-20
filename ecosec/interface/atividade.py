"""Controle de inatividade do usuário."""
import time

from PySide6.QtCore import QEvent, QObject, Signal
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid

EVENTOS_DE_USO = {QEvent.Type.MouseMove, QEvent.Type.MouseButtonPress, QEvent.Type.Wheel, QEvent.Type.KeyPress,
                  QEvent.Type.TouchBegin}


class VigiaAtividade(QObject):
    atividade = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._ultimo = 0.0
        QApplication.instance().installEventFilter(self)

    def eventFilter(self, objeto, evento) -> bool:
        if evento.type() in EVENTOS_DE_USO:
            agora = time.monotonic()
            if agora - self._ultimo >= 1.0:
                self._ultimo = agora
                self.atividade.emit()
        return False

    def desligar(self):
        QApplication.instance().removeEventFilter(self)


_VIGIA: VigiaAtividade | None = None


def vigia() -> VigiaAtividade:
    """O vigia do programa (criado na primeira chamada; um só por QApplication)."""
    global _VIGIA
    if _VIGIA is None or not isValid(_VIGIA):
        _VIGIA = VigiaAtividade(QApplication.instance())
    return _VIGIA


class PrazoInatividade(QObject):
    """Vence depois de minutos sem atividade. Ao vencer, pergunta ocupado()
    (ex.: câmera ligada) e, se estiver ocupado, recomeça em vez de vencer."""
    vencido = Signal()

    def __init__(self, minutos: float, ocupado=lambda: False, parent=None):
        super().__init__(parent)
        from PySide6.QtCore import Qt, QTimer
        self.ocupado = ocupado
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        # Preciso: no timer padrão ("grosso"), reiniciar dentro da folga de ~5% não empurra o
        # vencimento (medido: o restante seguia caindo a cada reinício), e a atividade não adiaria
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.setInterval(int(minutos * 60_000))
        self._timer.timeout.connect(self._venceu)
        vigia().atividade.connect(self._uso)

    @property
    def ativo(self) -> bool:
        return self._timer.isActive()

    def restante_ms(self) -> int:
        return self._timer.remainingTime() if self._timer.isActive() else -1

    def iniciar(self):
        self._timer.start()

    def parar(self):
        self._timer.stop()

    def _uso(self):
        if self._timer.isActive():
            self._timer.start()

    def _venceu(self):
        if self.ocupado():
            self._timer.start()            # câmera ligada, captura em andamento: não é inatividade
        else:
            self.vencido.emit()
