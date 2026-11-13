"""Adaptador Qt do pipeline de documento (3.4.2, passos 3 a 5).

O serviço decide o que vai no documento (campos, hash, conteúdo do QR, texto da marca
visível) e aplica a S9 por último; aqui só se desenha: HTML no QTextDocument, QR e
brasão como recursos, marca visível diagonal, conversão para BGR. A montagem da
aplicação injeta rasterizar no ServicoAcervo, e a camada de serviços continua sem
importar PySide6 (testes/test_arquitetura.py).
"""
import cv2
import numpy as np
from PySide6.QtCore import QRectF, Qt, QUrl
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen, QTextDocument

LARGURA = 1000


def qr(modulos: np.ndarray, escala: int = 4, borda: int = 2) -> QImage:
    """Matriz do QR (0/255, do cv2.QRCodeEncoder) ampliada, com margem branca."""
    imagem = cv2.resize(modulos, None, fx=escala, fy=escala, interpolation=cv2.INTER_NEAREST)
    imagem = cv2.copyMakeBorder(imagem, borda * escala, borda * escala, borda * escala, borda * escala,
                                cv2.BORDER_CONSTANT, value=255)
    rgb = np.ascontiguousarray(cv2.cvtColor(imagem, cv2.COLOR_GRAY2RGB))
    h, w, _ = rgb.shape
    return QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()


def brasao(texto: str, tamanho: int = 128) -> QImage:
    """Brasão FICTÍCIO desenhado na hora: escudo com as iniciais do órgão (nenhum símbolo oficial)."""
    imagem = QImage(tamanho, tamanho, QImage.Format.Format_RGB888)
    imagem.fill(Qt.GlobalColor.white)
    p = QPainter(imagem)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(QPen(QColor("#1f4e79"), 6))
    p.setBrush(QColor("#e8eef5"))
    p.drawEllipse(8, 8, tamanho - 16, tamanho - 16)
    p.setFont(QFont("Segoe UI", tamanho // 5, QFont.Weight.Bold))
    p.setPen(QColor("#1f4e79"))
    iniciais = "".join(palavra[0] for palavra in texto.split() if len(palavra) > 2)[:3]
    p.drawText(imagem.rect(), Qt.AlignmentFlag.AlignCenter, iniciais)
    p.end()
    return imagem


def para_bgr(img: QImage) -> np.ndarray:
    img = img.convertToFormat(QImage.Format.Format_RGB888)
    w, h, passo = img.width(), img.height(), img.bytesPerLine()
    bruto = np.frombuffer(img.constBits(), dtype=np.uint8, count=passo * h).reshape(h, passo)
    return bruto[:, : w * 3].reshape(h, w, 3)[..., ::-1].copy()


def de_bgr(arr: np.ndarray) -> QImage:
    rgb = np.ascontiguousarray(arr[..., ::-1])
    h, w, _ = rgb.shape
    return QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()


def rasterizar(html: str, qr_modulos: np.ndarray, orgao: str, marca: str) -> np.ndarray:
    """Passos 3 a 5: HTML com QR e brasão, marca visível diagonal repetida, imagem BGR (ainda sem a S9)."""
    doc = QTextDocument()
    doc.setDefaultFont(QFont("Segoe UI", 10))
    doc.setDefaultStyleSheet("body, p, div, td, span { color: #1a1a1a; }")   # o tema escuro pintaria de branco
    doc.setTextWidth(LARGURA - 80)
    doc.addResource(QTextDocument.ResourceType.ImageResource, QUrl("qr:documento"), qr(qr_modulos))
    doc.addResource(QTextDocument.ResourceType.ImageResource, QUrl("brasao:orgao"), brasao(orgao))
    doc.setHtml(html)
    imagem = QImage(LARGURA, int(doc.size().height()) + 80, QImage.Format.Format_RGB888)
    imagem.fill(Qt.GlobalColor.white)
    p = QPainter(imagem)
    p.translate(40, 40)
    doc.drawContents(p, QRectF(0, 0, LARGURA - 80, doc.size().height()))
    p.resetTransform()
    p.setPen(QColor(150, 30, 40, 55))
    p.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
    p.translate(imagem.width() / 2, imagem.height() / 2)
    p.rotate(-30)
    for y in range(-imagem.height(), imagem.height(), 140):
        p.drawText(-imagem.width(), y, (marca + "      ") * 3)
    p.end()
    return para_bgr(imagem)
