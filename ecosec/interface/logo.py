"""O logo do EcoSecurity: um cadeado com o símbolo de radiação no corpo.

O cadeado diz "acesso controlado"; o trifólio de radiação diz o que está
guardado (um cadastro de passivos perigosos). Não é uma digital nem um rosto:
o sistema não coleta digitais, e o logo não deve sugerir que coleta.

Desenhado em código (QPainter), em qualquer tamanho: é a origem do arquivo
.ico e serve de reserva se ele faltar.
O trifólio segue as proporções da ISO 361: disco de raio R, pás de 1,5R a 5R,
de 60° cada.
"""
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap

FUNDO_CLARO, FUNDO_ESCURO = "#12503A", "#0A2A20"
ARGOLA, CORPO, SIMBOLO = "#5FE0A8", "#FFFFFF", "#0A2A20"


def _trifolio(cx: float, cy: float, r: float) -> QPainterPath:
    R = r / 5
    caminho = QPainterPath()
    externo = QRectF(cx - r, cy - r, 2 * r, 2 * r)
    interno = QRectF(cx - 1.5 * R, cy - 1.5 * R, 3 * R, 3 * R)
    for meio in (30, 150, 270):                         # pás: superior direita, superior esquerda, inferior
        pa = QPainterPath()
        pa.arcMoveTo(externo, meio - 30)
        pa.arcTo(externo, meio - 30, 60)
        pa.arcTo(interno, meio + 30, -60)
        pa.closeSubpath()
        caminho.addPath(pa)
    caminho.addEllipse(QPointF(cx, cy), R, R)
    return caminho


def desenhar_logo(p: QPainter, lado: float) -> None:
    """Desenha o logo no quadrado (0, 0, lado, lado) do pintor."""
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    s, cx = lado, lado / 2
    fundo = QPainterPath()
    fundo.addRoundedRect(QRectF(0, 0, s, s), s * 0.23, s * 0.23)
    gradiente = QLinearGradient(0, 0, s, s)
    gradiente.setColorAt(0, QColor(FUNDO_CLARO))
    gradiente.setColorAt(1, QColor(FUNDO_ESCURO))
    p.fillPath(fundo, gradiente)

    # cadeado: corpo na parte de baixo, argola em arco por cima
    topo, largura, altura = s * 0.15, s * 0.24, s * 0.70
    corpo = QPainterPath()
    corpo.addRoundedRect(QRectF(cx - largura, topo + altura * 0.42, 2 * largura, altura * 0.58),
                         largura * 0.22, largura * 0.22)
    raio = largura * 0.62
    argola = QPainterPath(QPointF(cx - raio, topo + altura * 0.46))
    argola.lineTo(cx - raio, topo + raio)
    argola.arcTo(QRectF(cx - raio, topo, 2 * raio, 2 * raio), 180, -180)
    argola.lineTo(cx + raio, topo + altura * 0.46)
    # traço com piso de 1,6 px: em 16 px a argola fina se diluía no fundo e o cadeado virava um quadrado
    p.setPen(QPen(QColor(ARGOLA), max(s * 0.065, 1.6), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                  Qt.PenJoinStyle.RoundJoin))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(argola)
    p.fillPath(corpo, QColor(CORPO))
    p.fillPath(_trifolio(cx, s * 0.65, s * 0.15), QColor(SIMBOLO))


def imagem_logo(lado: int) -> QImage:
    imagem = QImage(lado, lado, QImage.Format.Format_ARGB32)
    imagem.fill(Qt.GlobalColor.transparent)
    pintor = QPainter(imagem)
    desenhar_logo(pintor, lado)
    pintor.end()
    return imagem


def pixmap_logo(lado: int) -> QPixmap:
    return QPixmap.fromImage(imagem_logo(lado))
