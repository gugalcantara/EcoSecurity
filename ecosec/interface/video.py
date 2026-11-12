"""Vídeo na interface: a thread que alimenta a tela e o visor que desenha.

TrabalhadorVideo (QThread): roda a câmera e o pipeline fora da thread da
interface, e entrega cada quadro por sinal. A tela nunca chama camera.read():
se chamasse, congelaria 30-50 ms a cada quadro. Também chama, na mesma thread,
o processamento de quem consome (autenticação ou coleta do cadastro).

VisorVideo, desenha o quadro espelhado (como um espelho: levantar a mão
direita levanta a mão do lado direito da tela), a moldura-guia e o retângulo
da face: verde quando a imagem serve, âmbar quando não.
"""
import logging

import cv2
import numpy as np
from PySide6.QtCore import QRectF, Qt, QThread, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from ecosec.interface.estilo import AMBAR, VERDE, cor_superficie, cor_texto_secundario, qcor
from ecosec.visao.aquisicao import ErroCamera

log = logging.getLogger(__name__)


def para_qimage(bgr: np.ndarray) -> QImage:
    rgb = cv2.cvtColor(cv2.flip(bgr, 1), cv2.COLOR_BGR2RGB)      # espelhado para a tela
    alt, larg, _ = rgb.shape
    # .copy(): o QImage só aponta para o buffer do numpy, que será reaproveitado
    return QImage(rgb.data, larg, alt, 3 * larg, QImage.Format.Format_RGB888).copy()


class TrabalhadorVideo(QThread):
    quadro = Signal(object, object, object)          # QImage, ResultadoQuadro, retorno do processamento
    falhou = Signal(str)

    def __init__(self, camera, pipeline, processar=None, parent=None):
        super().__init__(parent)
        self.camera, self.pipeline = camera, pipeline
        self.processar = processar                    # pode ser trocado em andamento

    def run(self):                                    # thread SECUNDÁRIA
        try:
            self.camera.iniciar()
        except ErroCamera as erro:
            self.falhou.emit(str(erro))
            return
        try:
            while not self.isInterruptionRequested():
                bgr = self.camera.ler()
                resultado = self.pipeline.processar(bgr)
                retorno = self.processar(resultado) if self.processar else None
                self.quadro.emit(para_qimage(bgr), resultado, retorno)
        except ErroCamera as erro:
            self.falhou.emit(str(erro))
        except Exception:                             # noqa: BLE001, nada pode derrubar a tela
            log.exception("Falha no processamento do vídeo")
            self.falhou.emit("Falha inesperada no processamento do vídeo. O acesso foi interrompido.")
        finally:
            self.camera.parar()

    def parar(self):
        self.requestInterruption()
        self.wait(4000)


class VisorVideo(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(320, 240)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._imagem: QImage | None = None
        self._faces: tuple = ()
        self._boa = False
        self._largura_original = 640
        self.texto_vazio = "Câmera desligada"

    def mostrar(self, imagem: QImage, resultado=None):
        self._imagem = imagem
        if resultado is not None:
            self._faces, self._boa = resultado.faces, resultado.qualidade_aprovada
            self._largura_original = resultado.largura
        self.update()

    def limpar(self, texto: str = "Câmera desligada"):
        self._imagem, self._faces, self.texto_vazio = None, (), texto
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        area = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        moldura = QPainterPath()
        moldura.addRoundedRect(area, 12, 12)
        p.fillPath(moldura, QColor(cor_superficie()))

        if self._imagem is None:
            fonte = self.font()
            fonte.setPointSizeF(fonte.pointSizeF() * 1.25)
            p.setFont(fonte)
            p.setPen(QColor(cor_texto_secundario()))
            p.drawText(area, Qt.AlignmentFlag.AlignCenter, self.texto_vazio)
            return

        # encaixa mantendo a proporção
        escala = min(area.width() / self._imagem.width(), area.height() / self._imagem.height())
        larg, alt = self._imagem.width() * escala, self._imagem.height() * escala
        alvo = QRectF(area.center().x() - larg / 2, area.center().y() - alt / 2, larg, alt)
        recorte = QPainterPath()
        recorte.addRoundedRect(alvo, 12, 12)
        p.setClipPath(recorte)
        p.drawImage(alvo, self._imagem)

        # moldura-guia: onde o rosto deve ficar
        guia = QRectF(0, 0, alvo.width() * 0.36, alvo.height() * 0.62)
        guia.moveCenter(alvo.center())
        p.setPen(QPen(qcor("#FFFFFF", 110), 2, Qt.PenStyle.DashLine))
        p.drawEllipse(guia)

        # retângulos das faces (coordenadas da imagem bruta -> espelhadas)
        fator = alvo.width() / self._largura_original
        cor = VERDE if (self._boa and len(self._faces) == 1) else AMBAR
        p.setPen(QPen(QColor(cor), 3))
        for x, y, w, h in self._faces:
            x_espelhado = self._largura_original - x - w
            p.drawRoundedRect(QRectF(alvo.left() + x_espelhado * fator, alvo.top() + y * fator,
                                     w * fator, h * fator), 8, 8)
