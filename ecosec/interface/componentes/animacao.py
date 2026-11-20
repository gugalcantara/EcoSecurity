"""Zoom e deslocamento animados do mapa."""
from functools import lru_cache
from math import exp, log

from PySide6.QtCore import QAbstractAnimation, QEasingCurve, QPointF, QRectF, Qt, QVariantAnimation
from shiboken6 import isValid


@lru_cache(maxsize=1)
def animacoes_ligadas() -> bool:
    try:
        from ecosec.configuracao import carregar
        return bool(carregar()["interface.animacoes"])
    except Exception:  # noqa: BLE001, sem configuração, sem animação (falha segura e silenciosa)
        return False


def _animacao_da_vista(vista) -> QVariantAnimation:
    """A animação da vista (filha dela: morre junto). Recriada só se o objeto C++ sumiu."""
    anim = getattr(vista, "_animacao_enquadramento", None)
    if anim is not None and isValid(anim):
        return anim
    anim = QVariantAnimation(vista)
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.setEasingCurve(QEasingCurve.Type.InOutCubic)
    # passo e fim do enquadramento atual; trocados a cada chamada, sem reconectar sinais
    vista._enquadramento_atual = (None, None)
    anim.valueChanged.connect(lambda t: vista._enquadramento_atual[0] and vista._enquadramento_atual[0](t))
    anim.finished.connect(lambda: vista._enquadramento_atual[1] and vista._enquadramento_atual[1]())
    vista._animacao_enquadramento = anim
    return anim


def parar_enquadramento(vista) -> None:
    """Interrompe o enquadramento em curso (se houver), sem chamar o ao_terminar dele."""
    anim = getattr(vista, "_animacao_enquadramento", None)
    if anim is not None and isValid(anim) and anim.state() != QAbstractAnimation.State.Stopped:
        anim.stop()


def animar_enquadramento(vista, destino: QRectF, ms: int = 380, ao_terminar=None, ao_passo=None):
    """Leva a vista até destino. Devolve a animação (ou None, se as animações estão desligadas)."""
    parar_enquadramento(vista)                    # um enquadramento novo sempre vence o anterior
    origem = vista.mapToScene(vista.viewport().rect()).boundingRect()
    if not animacoes_ligadas() or origem.width() <= 0 or destino.width() <= 0 or not vista.isVisible():
        vista.fitInView(destino, Qt.AspectRatioMode.KeepAspectRatio)
        if ao_terminar:
            ao_terminar()
        return None
    c0, c1 = origem.center(), destino.center()
    l0, l1 = log(origem.width()), log(destino.width())
    razao = destino.height() / destino.width()

    def passo(t):
        t = float(t)
        largura = exp(l0 + (l1 - l0) * t)
        centro = QPointF(c0.x() + (c1.x() - c0.x()) * t, c0.y() + (c1.y() - c0.y()) * t)
        r = QRectF(0, 0, largura, largura * razao)
        r.moveCenter(centro)
        vista.fitInView(r, Qt.AspectRatioMode.KeepAspectRatio)
        if ao_passo:
            ao_passo()

    anim = _animacao_da_vista(vista)
    vista._enquadramento_atual = (passo, ao_terminar)
    anim.setDuration(ms)
    anim.start()
    return anim
