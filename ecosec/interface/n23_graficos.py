"""Gráficos e peças de painel do analítico N2 e N3, desenhados com QPainter.

Regra de visualização: a forma vem da pergunta, a cor vem por último.
  - BarrasH: magnitude por categoria (barras horizontais ordenadas, rótulo direto na ponta). Com dois segmentos,
    é a forma de ênfase: a parte que importa (ex.: casos críticos) na cor de status, o resto em cinza;
  - LinhasAno: evolução no tempo (linha de 2 px, ponto final com anel da superfície, cruz e dica no hover);
  - Halteres: UF × país num mesmo eixo de 0 a 100% (dois pontos e o segmento que os liga);
  - BarraPartes: parte do todo (uma barra 100% com vão de 2 px entre os segmentos e legenda com valor e %);
  - CurvaAcumulada: custo acumulado × redução de risco acumulada (uma linha por critério) com a linha do orçamento.
Especificações fixas: barra de no máximo 20 px com ponta arredondada de 4 px (reta na base), linhas de 2 px, grade
e eixos em linha fina contínua, texto sempre nas cores de texto (nunca na cor da série), um eixo só, nenhum eixo
duplo. A paleta categórica foi conferida quanto à separação para daltonismo e ao contraste, no tema claro e no
escuro (contraste abaixo de 3:1 em dois tons do claro, por isso todo segmento tem rótulo visível).
As cores de risco e de classe vêm de `componentes.simbologia` (fonte única do mapa).

Toda peça tem nome e descrição acessíveis com os valores (a alternativa em texto do gráfico) e dica no hover.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from math import floor, log10

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QToolTip, QVBoxLayout, QWidget

from ecosec.interface.estilo import cor_borda, cor_texto_secundario
from ecosec.interface.fluent import isDarkTheme

# paleta categórica, na ordem fixa dos slots; nunca ciclada
CATEGORICA_CLARO = ("#2a78d6", "#eb6834", "#1baf7a", "#eda100")
CATEGORICA_ESCURO = ("#3987e5", "#d95926", "#199e70", "#c98500")
CINZA_CONTEXTO = ("#C5CCD3", "#4A4F55")          # o resto, na forma de ênfase (claro, escuro)


def categorica(i: int) -> str:
    return (CATEGORICA_ESCURO if isDarkTheme() else CATEGORICA_CLARO)[i]


def cor_contexto() -> str:
    return CINZA_CONTEXTO[1] if isDarkTheme() else CINZA_CONTEXTO[0]


def cor_texto() -> str:
    return "#F2F2F2" if isDarkTheme() else "#1A1A1A"


def cor_grade() -> str:
    return "#3A3A3A" if isDarkTheme() else "#E3E5E8"


def cor_superficie_grafico() -> str:
    return "#272727" if isDarkTheme() else "#FFFFFF"


def fonte(px: int = 11, peso: QFont.Weight = QFont.Weight.Normal) -> QFont:
    f = QFont("Segoe UI")
    f.setPixelSize(px)
    f.setWeight(peso)
    return f


def passo_redondo(maximo: float, alvo: int = 4) -> float:
    """Passo da grade em {1, 2, 5} × 10^k com cerca de `alvo` divisões até `maximo`."""
    if maximo <= 0:
        return 1.0
    bruto = maximo / alvo
    base = 10 ** floor(log10(bruto))
    for m in (1, 2, 5, 10):
        if bruto <= m * base:
            return m * base
    return 10 * base


def numero_br(valor: float, casas: int = 0) -> str:
    return f"{valor:,.{casas}f}".replace(",", "§").replace(".", ",").replace("§", ".")


def _barra(caminho_retangulo: QRectF, raio: float = 4.0, so_ponta: bool = True) -> QPainterPath:
    """Retângulo com a ponta (lado direito) arredondada e a base reta."""
    r = min(raio, caminho_retangulo.height() / 2, caminho_retangulo.width())
    caminho = QPainterPath()
    x0, y0, x1, y1 = (caminho_retangulo.left(), caminho_retangulo.top(), caminho_retangulo.right(),
                      caminho_retangulo.bottom())
    if not so_ponta or r <= 0.5:
        caminho.addRoundedRect(caminho_retangulo, r, r) if not so_ponta else caminho.addRect(caminho_retangulo)
        return caminho
    caminho.moveTo(x0, y0)
    caminho.lineTo(x1 - r, y0)
    caminho.quadTo(x1, y0, x1, y0 + r)
    caminho.lineTo(x1, y1 - r)
    caminho.quadTo(x1, y1, x1 - r, y1)
    caminho.lineTo(x0, y1)
    caminho.closeSubpath()
    return caminho


class _Grafico(QWidget):
    """Base: dica no hover pelas regiões registradas no último desenho e descrição acessível."""

    def __init__(self, nome: str, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setAccessibleName(nome)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._regioes: list[tuple[QRectF, str]] = []

    def definir_descricao(self, linhas):
        self.setAccessibleDescription("; ".join(linhas))
        self.setToolTip("")

    def mouseMoveEvent(self, evento):
        p = evento.position()
        for retangulo, texto in self._regioes:
            if retangulo.contains(p):
                QToolTip.showText(evento.globalPosition().toPoint(), texto, self)
                return
        QToolTip.hideText()

    def leaveEvent(self, evento):
        QToolTip.hideText()


# ================================================================ barras horizontais
@dataclass
class Barra:
    rotulo: str
    segmentos: list                      # [(valor, cor, nome)]; um segmento = barra simples
    texto: str = ""                      # rótulo direto na ponta (valor exato com unidade)
    dica: str = ""
    nota: str = ""                       # segunda linha do rótulo (cinza), opcional

    @property
    def total(self) -> float:
        return sum(v for v, _, _ in self.segmentos)


class BarrasH(_Grafico):
    """Barras horizontais com rótulo à esquerda e valor exato na ponta. Ordem: a de quem chama (ordenada pela
    pergunta). A escala começa em zero e é comum a todas as barras."""
    ESPESSURA, LINHA = 16, 30

    def __init__(self, nome: str, largura_rotulo: int = 190, parent=None):
        super().__init__(nome, parent)
        self.barras: list[Barra] = []
        self.largura_rotulo = largura_rotulo
        self.maximo: float | None = None

    def definir(self, barras, maximo: float | None = None):
        self.barras, self.maximo = list(barras), maximo
        linhas = [f"{b.rotulo}: {b.texto or numero_br(b.total)}" for b in self.barras]
        self.definir_descricao(linhas)
        self.setFixedHeight(max(40, self.LINHA * len(self.barras) + 8))
        self.update()

    def sizeHint(self) -> QSize:
        return QSize(480, self.LINHA * max(1, len(self.barras)) + 8)

    def paintEvent(self, evento):
        if not self.barras:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._regioes = []
        mf, mf_valor = QFontMetrics(fonte(12)), QFontMetrics(fonte(12, QFont.Weight.DemiBold))
        largura_texto = max(mf_valor.horizontalAdvance(b.texto) for b in self.barras) + 10
        x0 = self.largura_rotulo
        x1 = self.width() - largura_texto - 4
        maximo = self.maximo or max((b.total for b in self.barras), default=1) or 1
        escala = max(1.0, x1 - x0) / maximo
        # linha de base (zero)
        p.setPen(QPen(QColor(cor_grade()), 1))
        p.drawLine(QPointF(x0 - 0.5, 2), QPointF(x0 - 0.5, self.LINHA * len(self.barras) + 2))
        for i, b in enumerate(self.barras):
            topo = 4 + i * self.LINHA
            meio = topo + self.LINHA / 2 - 2
            # rótulo (texto primário) e nota (secundário), elididos à largura da coluna
            p.setFont(fonte(12))
            p.setPen(QColor(cor_texto()))
            rotulo = mf.elidedText(b.rotulo, Qt.TextElideMode.ElideRight, self.largura_rotulo - 12)
            p.drawText(QRectF(0, topo, self.largura_rotulo - 10, self.LINHA - 4),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, rotulo)
            x = x0
            y = meio - self.ESPESSURA / 2
            visiveis = [(v, c, n) for v, c, n in b.segmentos if v > 0]
            for j, (valor, cor, nome) in enumerate(visiveis):
                largura = valor * escala
                ultimo = j == len(visiveis) - 1
                retangulo = QRectF(x, y, max(1.0, largura - (0 if ultimo else 2)), self.ESPESSURA)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(cor))
                p.drawPath(_barra(retangulo, 4.0, so_ponta=ultimo) if ultimo else _barra(retangulo, 0, False))
                x += largura
            # valor exato na ponta
            p.setFont(fonte(12, QFont.Weight.DemiBold))
            p.setPen(QColor(cor_texto()))
            p.drawText(QRectF(x + 6, topo, largura_texto, self.LINHA - 4),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, b.texto)
            self._regioes.append((QRectF(0, topo, self.width(), self.LINHA), b.dica or f"{b.rotulo}: {b.texto}"))
        p.end()


# ================================================================ linhas por ano
@dataclass
class Serie:
    nome: str
    valores: dict                        # ano -> valor (None = sem dado)
    cor: str
    area: bool = False                   # véu de 10% sob a linha (só para uma série)


class LinhasAno(_Grafico):
    """Uma a três séries anuais num eixo só. Legenda acima (duas ou mais séries), valor do último ano em rótulo
    direto quando não colide, cruz vertical e dica com todos os valores do ano no hover."""

    def __init__(self, nome: str, unidade: str, altura: int = 200, parent=None):
        super().__init__(nome, parent)
        self.unidade, self.series, self.anos = unidade, [], []
        self.setFixedHeight(altura)
        self._hover_ano = None
        self.formato = lambda v: numero_br(v)

    def definir(self, anos, series, formato=None):
        self.anos, self.series = list(anos), list(series)
        if formato:
            self.formato = formato
        self.definir_descricao([f"{s.nome}: " + ", ".join(f"{a} {self.formato(s.valores[a])}"
                                                          for a in self.anos if s.valores.get(a) is not None)
                                for s in self.series])
        self.update()

    def _geometria(self):
        mf = QFontMetrics(fonte(11))
        maximo = max((v for s in self.series for v in s.valores.values() if v is not None), default=1) or 1
        passo = passo_redondo(maximo)
        topo_eixo = passo * (int(maximo / passo) + (0 if maximo % passo == 0 else 1))
        esquerda = mf.horizontalAdvance(self.formato(topo_eixo)) + 10
        legenda = 22 if len(self.series) > 1 else 6
        direita = 70
        area = QRectF(esquerda, legenda + 26, self.width() - esquerda - direita, self.height() - legenda - 26 - 24)
        return area, passo, topo_eixo

    def _x(self, area, ano):
        if len(self.anos) < 2:
            return area.center().x()
        return area.left() + (ano - self.anos[0]) / (self.anos[-1] - self.anos[0]) * area.width()

    def _y(self, area, valor, topo_eixo):
        return area.bottom() - (valor / topo_eixo) * area.height()

    def paintEvent(self, evento):
        if not self.series or not self.anos:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        area, passo, topo_eixo = self._geometria()
        texto, secundario = QColor(cor_texto()), QColor(cor_texto_secundario())
        # legenda (duas ou mais séries): traço da série + nome em cor de texto
        if len(self.series) > 1:
            x = area.left()
            p.setFont(fonte(11))
            for s in self.series:
                p.setPen(QPen(QColor(s.cor), 2.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                p.drawLine(QPointF(x, 10), QPointF(x + 16, 10))
                p.setPen(texto)
                largura = QFontMetrics(fonte(11)).horizontalAdvance(s.nome)
                p.drawText(QRectF(x + 21, 2, largura + 4, 16), Qt.AlignmentFlag.AlignVCenter, s.nome)
                x += largura + 44
        # unidade do eixo, no topo da escala
        p.setFont(fonte(11))
        p.setPen(secundario)
        p.drawText(QRectF(0, area.top() - 26, area.left() + 200, 14), Qt.AlignmentFlag.AlignLeft, self.unidade)
        # grade horizontal fina e ticks
        valor = 0.0
        while valor <= topo_eixo + 1e-9:
            y = self._y(area, valor, topo_eixo)
            p.setPen(QPen(QColor(cor_grade()), 1))
            p.drawLine(QPointF(area.left(), y), QPointF(area.right(), y))
            p.setPen(secundario)
            p.drawText(QRectF(0, y - 8, area.left() - 6, 16), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                       self.formato(valor))
            valor += passo
        # anos no eixo x: primeiro, último e a cada 5
        p.setPen(secundario)
        for ano in self.anos:
            if ano in (self.anos[0], self.anos[-1]) or ano % 5 == 0:
                x = self._x(area, ano)
                if ano not in (self.anos[0], self.anos[-1]) and (abs(x - self._x(area, self.anos[-1])) < 34
                                                                 or abs(x - self._x(area, self.anos[0])) < 34):
                    continue
                p.drawText(QRectF(x - 24, area.bottom() + 4, 48, 16), Qt.AlignmentFlag.AlignHCenter, str(ano))
        # cruz do hover
        if self._hover_ano is not None:
            x = self._x(area, self._hover_ano)
            p.setPen(QPen(QColor(cor_borda()), 1))
            p.drawLine(QPointF(x, area.top()), QPointF(x, area.bottom()))
        # séries
        finais = []
        for s in self.series:
            pontos = [(a, s.valores.get(a)) for a in self.anos]
            caminho, primeiro = QPainterPath(), True
            for a, v in pontos:
                if v is None:
                    primeiro = True
                    continue
                ponto = QPointF(self._x(area, a), self._y(area, v, topo_eixo))
                if primeiro:
                    caminho.moveTo(ponto)
                    primeiro = False
                else:
                    caminho.lineTo(ponto)
            if s.area and len(self.series) == 1:
                veu = QPainterPath(caminho)
                veu.lineTo(QPointF(self._x(area, self.anos[-1]), area.bottom()))
                veu.lineTo(QPointF(self._x(area, self.anos[0]), area.bottom()))
                veu.closeSubpath()
                cor = QColor(s.cor)
                cor.setAlphaF(0.10)
                p.fillPath(veu, cor)
            p.setPen(QPen(QColor(s.cor), 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(caminho)
            ultimo = next(((a, v) for a, v in reversed(pontos) if v is not None), None)
            if ultimo:
                centro = QPointF(self._x(area, ultimo[0]), self._y(area, ultimo[1], topo_eixo))
                p.setPen(QPen(QColor(cor_superficie_grafico()), 2))
                p.setBrush(QColor(s.cor))
                p.drawEllipse(centro, 4.5, 4.5)
                finais.append((centro.y(), self.formato(ultimo[1]), s))
            if self._hover_ano is not None and s.valores.get(self._hover_ano) is not None:
                centro = QPointF(self._x(area, self._hover_ano), self._y(area, s.valores[self._hover_ano], topo_eixo))
                p.setPen(QPen(QColor(cor_superficie_grafico()), 2))
                p.setBrush(QColor(s.cor))
                p.drawEllipse(centro, 4, 4)
        # rótulo direto do último valor (só se os rótulos não colidem; senão, a legenda e a dica bastam)
        finais.sort(key=lambda f: f[0])
        colide = any(abs(finais[i][0] - finais[i + 1][0]) < 15 for i in range(len(finais) - 1))
        if not colide:
            p.setFont(fonte(11, QFont.Weight.DemiBold))
            p.setPen(texto)
            for y, rotulo, _ in finais:
                p.drawText(QRectF(area.right() + 8, y - 8, 64, 16), Qt.AlignmentFlag.AlignVCenter, rotulo)
        p.end()

    def mouseMoveEvent(self, evento):
        if not self.anos or not self.series:
            return
        area, _, _ = self._geometria()
        x = evento.position().x()
        ano = min(self.anos, key=lambda a: abs(self._x(area, a) - x))
        if ano != self._hover_ano:
            self._hover_ano = ano
            self.update()
        linhas = [str(ano)] + [f"{s.nome}: {self.formato(s.valores[ano])} {self.unidade}"
                               for s in self.series if s.valores.get(ano) is not None]
        QToolTip.showText(evento.globalPosition().toPoint(), "\n".join(linhas), self)

    def leaveEvent(self, evento):
        self._hover_ano = None
        self.update()
        QToolTip.hideText()


# ================================================================ halteres (UF × país)
@dataclass
class Haltere:
    rotulo: str
    valor: float | None                  # da UF, 0 a 100
    referencia: float | None             # do país, 0 a 100 (None = suprimido)
    dica: str = ""


class Halteres(_Grafico):
    """Cada linha: a UF (ponto cheio) e o país (anel) no mesmo eixo de 0 a 100%. O segmento entre os dois mostra a
    diferença; os dois valores ficam escritos ao lado dos pontos."""
    LINHA = 34

    def __init__(self, nome: str, rotulo_valor: str, rotulo_referencia: str, largura_rotulo: int = 200, parent=None):
        super().__init__(nome, parent)
        self.linhas: list[Haltere] = []
        self.rotulo_valor, self.rotulo_referencia = rotulo_valor, rotulo_referencia
        self.largura_rotulo = largura_rotulo

    def definir(self, linhas):
        self.linhas = list(linhas)
        self.definir_descricao([f"{l.rotulo}: {self.rotulo_valor} {self._pct(l.valor)}, {self.rotulo_referencia} "
                                f"{self._pct(l.referencia)}" for l in self.linhas])
        self.setFixedHeight(28 + self.LINHA * len(self.linhas) + 22)
        self.update()

    @staticmethod
    def _pct(v):
        return "SUPRIMIDO" if v is None else f"{numero_br(v, 1)}%"

    def paintEvent(self, evento):
        if not self.linhas:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        texto, secundario = QColor(cor_texto()), QColor(cor_texto_secundario())
        destaque, contexto = QColor(categorica(0)), QColor(cor_texto_secundario())
        x0, x1 = self.largura_rotulo, self.width() - 30
        topo = 28
        # legenda
        p.setFont(fonte(11))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(destaque)
        p.drawEllipse(QPointF(x0 + 5, 10), 5, 5)
        p.setPen(texto)
        largura = QFontMetrics(fonte(11)).horizontalAdvance(self.rotulo_valor)
        p.drawText(QRectF(x0 + 15, 2, largura + 4, 16), Qt.AlignmentFlag.AlignVCenter, self.rotulo_valor)
        xr = x0 + largura + 40
        p.setPen(QPen(contexto, 2))
        p.setBrush(QColor(cor_superficie_grafico()))
        p.drawEllipse(QPointF(xr + 5, 10), 4.5, 4.5)
        p.setPen(texto)
        p.drawText(QRectF(xr + 15, 2, 260, 16), Qt.AlignmentFlag.AlignVCenter, self.rotulo_referencia)
        # grade a cada 25%
        base = topo + self.LINHA * len(self.linhas)
        p.setFont(fonte(11))
        for pct in (0, 25, 50, 75, 100):
            x = x0 + pct / 100 * (x1 - x0)
            p.setPen(QPen(QColor(cor_grade()), 1))
            p.drawLine(QPointF(x, topo), QPointF(x, base))
            p.setPen(secundario)
            p.drawText(QRectF(x - 20, base + 3, 40, 16), Qt.AlignmentFlag.AlignHCenter, f"{pct}%")
        self._regioes = []
        for i, l in enumerate(self.linhas):
            y = topo + i * self.LINHA + self.LINHA / 2
            p.setFont(fonte(12))
            p.setPen(texto)
            p.drawText(QRectF(0, y - 10, x0 - 12, 20), Qt.AlignmentFlag.AlignVCenter, l.rotulo)
            xv = None if l.valor is None else x0 + l.valor / 100 * (x1 - x0)
            xr_ = None if l.referencia is None else x0 + l.referencia / 100 * (x1 - x0)
            if xv is not None and xr_ is not None:
                p.setPen(QPen(QColor(cor_borda()), 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                p.drawLine(QPointF(xv, y), QPointF(xr_, y))
            if xr_ is not None:
                p.setPen(QPen(contexto, 2))
                p.setBrush(QColor(cor_superficie_grafico()))
                p.drawEllipse(QPointF(xr_, y), 5, 5)
            if xv is not None:
                p.setPen(QPen(QColor(cor_superficie_grafico()), 2))
                p.setBrush(destaque)
                p.drawEllipse(QPointF(xv, y), 6, 6)
            # valores escritos: o da UF do lado de fora, o do país do outro lado
            p.setFont(fonte(11, QFont.Weight.DemiBold))
            p.setPen(texto)
            if xv is not None:
                direita = xr_ is None or xv >= xr_
                p.drawText(QRectF(xv + 10 if direita else xv - 70, y - 19, 60, 14),
                           (Qt.AlignmentFlag.AlignLeft if direita else Qt.AlignmentFlag.AlignRight)
                           | Qt.AlignmentFlag.AlignVCenter, self._pct(l.valor))
            if xr_ is not None:
                p.setFont(fonte(11))
                p.setPen(secundario)
                direita = xv is None or xr_ > xv
                p.drawText(QRectF(xr_ + 10 if direita else xr_ - 70, y + 4, 60, 14),
                           (Qt.AlignmentFlag.AlignLeft if direita else Qt.AlignmentFlag.AlignRight)
                           | Qt.AlignmentFlag.AlignVCenter, self._pct(l.referencia))
            self._regioes.append((QRectF(0, y - self.LINHA / 2, self.width(), self.LINHA),
                                  l.dica or f"{l.rotulo}\n{self.rotulo_valor}: {self._pct(l.valor)}\n"
                                            f"{self.rotulo_referencia}: {self._pct(l.referencia)}"))
        p.end()


# ================================================================ parte do todo
class BarraPartes(QWidget):
    """Uma barra 100% (vão de 2 px entre os segmentos) e, abaixo, a legenda com o nome, o valor exato e a fração.
    A soma dos segmentos é o total escrito no título de quem chama."""

    def __init__(self, nome: str, parent=None):
        super().__init__(parent)
        self.setAccessibleName(nome)
        self.partes: list[tuple] = []
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)
        self.barra = _Faixa100(nome)
        v.addWidget(self.barra)
        self.legenda = QWidget()
        self.grade = QVBoxLayout(self.legenda)
        self.grade.setContentsMargins(0, 0, 0, 0)
        self.grade.setSpacing(3)
        v.addWidget(self.legenda)

    def definir(self, partes, formato):
        """partes: [(nome, valor, cor, dica)]."""
        self.partes = [x for x in partes]
        total = sum(v for _, v, _, _ in self.partes) or 1
        self.barra.definir([(v, c, f"{n}: {formato(v)} ({numero_br(100 * v / total, 1)}%)"
                             + (f"\n{d}" if d else "")) for n, v, c, d in self.partes])
        while self.grade.count():
            item = self.grade.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for nome, valor, cor, dica in self.partes:
            linha = QWidget()
            h = QHBoxLayout(linha)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(8)
            amostra = QLabel()
            amostra.setFixedSize(12, 12)
            amostra.setStyleSheet(f"background:{cor}; border-radius:3px;")
            nome_l = QLabel(nome)
            nome_l.setStyleSheet(f"color:{cor_texto()}; font-size:12px;")
            nome_l.setToolTip(dica)
            valor_l = QLabel(f"{formato(valor)}  ·  {numero_br(100 * valor / total, 1)}%")
            valor_l.setStyleSheet(f"color:{cor_texto()}; font-size:12px; font-weight:600;")
            h.addWidget(amostra)
            h.addWidget(nome_l)
            h.addStretch(1)
            h.addWidget(valor_l)
            self.grade.addWidget(linha)
        self.setAccessibleDescription("; ".join(f"{n}: {formato(v)}" for n, v, _, _ in self.partes))


class _Faixa100(_Grafico):
    ALTURA = 22

    def __init__(self, nome, parent=None):
        super().__init__(nome, parent)
        self.segmentos: list[tuple] = []
        self.setFixedHeight(self.ALTURA)

    def definir(self, segmentos):
        self.segmentos = [s for s in segmentos if s[0] > 0]
        self.definir_descricao([d for _, _, d in self.segmentos])
        self.update()

    def paintEvent(self, evento):
        if not self.segmentos:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        total = sum(v for v, _, _ in self.segmentos) or 1
        x, largura_util = 0.0, self.width() - 2 * (len(self.segmentos) - 1)
        self._regioes = []
        for i, (valor, cor, dica) in enumerate(self.segmentos):
            largura = max(1.0, valor / total * largura_util)
            retangulo = QRectF(x, 2, largura, self.ALTURA - 4)
            caminho = QPainterPath()
            primeiro, ultimo = i == 0, i == len(self.segmentos) - 1
            if primeiro and ultimo:
                caminho.addRoundedRect(retangulo, 4, 4)
            elif ultimo:
                caminho = _barra(retangulo, 4.0, True)
            elif primeiro:                            # arredondado à esquerda, reto no vão
                caminho.addRoundedRect(QRectF(retangulo.left(), retangulo.top(), retangulo.width() + 4,
                                              retangulo.height()), 4, 4)
                caminho = caminho.intersected(_retangulo_path(retangulo))
            else:
                caminho.addRect(retangulo)
            p.fillPath(caminho, QColor(cor))
            self._regioes.append((retangulo, dica))
            x += largura + 2
        p.end()


def _retangulo_path(r: QRectF) -> QPainterPath:
    c = QPainterPath()
    c.addRect(r)
    return c


# ================================================================ curva acumulada (priorização)
@dataclass
class Curva:
    nome: str
    pontos: list                          # [(custo acumulado em R$, % do risco eliminado)] na ordem da fila
    cor: str


class CurvaAcumulada(_Grafico):
    """x = custo acumulado (R$ milhões), y = risco eliminado acumulado (% do score dos casos públicos). Uma linha
    por critério; a linha vertical do orçamento e, em cada curva, o ponto onde o orçamento acaba, com o valor."""

    def __init__(self, nome: str, altura: int = 260, parent=None):
        super().__init__(nome, parent)
        self.curvas: list[Curva] = []
        self.orcamento = 0.0
        self.dominio = 0.0               # fim do eixo x em R$ (0 = a fila inteira)
        self.marcas: dict = {}           # nome da curva -> (custo gasto, % eliminado) no orçamento
        self.setMinimumHeight(altura)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._hover_x = None

    def definir(self, curvas, orcamento: float, marcas: dict, dominio: float = 0.0):
        self.curvas, self.orcamento, self.marcas, self.dominio = list(curvas), orcamento, dict(marcas), dominio
        self.definir_descricao([f"{c.nome}: com R$ {numero_br(self.orcamento / 1e6, 2)} mi, "
                                f"{numero_br(self.marcas[c.nome][1], 1)}% do risco eliminado"
                                for c in self.curvas if c.nome in self.marcas])
        self.update()

    def _geometria(self):
        maximo_x = (self.dominio or max((c.pontos[-1][0] for c in self.curvas if c.pontos), default=1)) / 1e6 or 1
        passo_x = passo_redondo(maximo_x, 6)
        topo_x = passo_x * (int(maximo_x / passo_x) + (0 if maximo_x % passo_x == 0 else 1))
        area = QRectF(62, 30, self.width() - 62 - 24, self.height() - 30 - 40)
        return area, passo_x, topo_x

    def paintEvent(self, evento):
        if not self.curvas:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        area, passo_x, topo_x = self._geometria()
        texto, secundario = QColor(cor_texto()), QColor(cor_texto_secundario())

        def px(custo):
            return area.left() + (custo / 1e6) / topo_x * area.width()

        def py(pct):
            return area.bottom() - pct / 100 * area.height()
        # legenda
        x = area.left()
        p.setFont(fonte(11))
        for c in self.curvas:
            p.setPen(QPen(QColor(c.cor), 2.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawLine(QPointF(x, 10), QPointF(x + 16, 10))
            p.setPen(texto)
            largura = QFontMetrics(fonte(11)).horizontalAdvance(c.nome)
            p.drawText(QRectF(x + 21, 2, largura + 4, 16), Qt.AlignmentFlag.AlignVCenter, c.nome)
            x += largura + 44
        # grade
        p.setFont(fonte(11))
        for pct in (0, 25, 50, 75, 100):
            y = py(pct)
            p.setPen(QPen(QColor(cor_grade()), 1))
            p.drawLine(QPointF(area.left(), y), QPointF(area.right(), y))
            p.setPen(secundario)
            p.drawText(QRectF(0, y - 8, area.left() - 6, 16), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                       f"{pct}%")
        valor = 0.0
        while valor <= topo_x + 1e-9:
            xv = area.left() + valor / topo_x * area.width()
            p.setPen(secundario)
            p.drawText(QRectF(xv - 30, area.bottom() + 4, 60, 16), Qt.AlignmentFlag.AlignHCenter,
                       numero_br(valor, 0 if passo_x >= 1 else 1))
            valor += passo_x
        p.drawText(QRectF(area.left(), area.bottom() + 20, area.width(), 16), Qt.AlignmentFlag.AlignHCenter,
                   "custo acumulado na fila (R$ milhões)")
        p.save()
        p.translate(9, area.center().y())
        p.rotate(-90)
        p.drawText(QRectF(-area.height() / 2, -8, area.height(), 16), Qt.AlignmentFlag.AlignHCenter,
                   "risco público eliminado")
        p.restore()
        # orçamento
        xo = px(self.orcamento)
        if area.left() <= xo <= area.right():
            p.setPen(QPen(QColor(cor_texto_secundario()), 1))
            p.drawLine(QPointF(xo, area.top() - 4), QPointF(xo, area.bottom()))
            p.setPen(texto)
            p.drawText(QRectF(xo + 4, area.top() - 4, 200, 14), Qt.AlignmentFlag.AlignLeft,
                       f"orçamento R$ {numero_br(self.orcamento / 1e6, 2)} mi")
        # curvas (cada caso soma o seu custo e o seu score), recortadas no fim do eixo
        p.save()
        p.setClipRect(area.adjusted(-2, -6, 2, 2))
        for c in self.curvas:
            caminho = QPainterPath(QPointF(px(0), py(0)))
            for custo, pct in c.pontos:
                caminho.lineTo(QPointF(px(custo), py(pct)))
            p.setPen(QPen(QColor(c.cor), 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(caminho)
        p.restore()
        # marcas no orçamento
        rotulos = []
        for c in self.curvas:
            if c.nome not in self.marcas:
                continue
            gasto, pct = self.marcas[c.nome]
            centro = QPointF(px(gasto), py(pct))
            p.setPen(QPen(QColor(cor_superficie_grafico()), 2))
            p.setBrush(QColor(c.cor))
            p.drawEllipse(centro, 5, 5)
            rotulos.append((centro, f"{numero_br(pct, 1)}%"))
        rotulos.sort(key=lambda r: r[0].y())
        ultimo_y = -100.0
        p.setFont(fonte(11, QFont.Weight.DemiBold))
        p.setPen(texto)
        for centro, rotulo in rotulos:               # à direita do ponto (o eixo y fica à esquerda)
            y = max(centro.y(), ultimo_y + 15)
            p.drawText(QRectF(centro.x() + 9, y - 8, 54, 16), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       rotulo)
            ultimo_y = y
        if self._hover_x is not None and area.left() <= self._hover_x <= area.right():
            p.setPen(QPen(QColor(cor_borda()), 1))
            p.drawLine(QPointF(self._hover_x, area.top()), QPointF(self._hover_x, area.bottom()))
        p.end()

    def _valor_em(self, curva: Curva, custo: float) -> float:
        pct = 0.0
        for c, v in curva.pontos:
            if c > custo:
                break
            pct = v
        return pct

    def mouseMoveEvent(self, evento):
        if not self.curvas:
            return
        area, _, topo_x = self._geometria()
        x = evento.position().x()
        custo = max(0.0, (x - area.left()) / area.width() * topo_x * 1e6)
        self._hover_x = x
        self.update()
        linhas = [f"Gasto acumulado: R$ {numero_br(custo / 1e6, 2)} mi"]
        linhas += [f"{c.nome}: {numero_br(self._valor_em(c, custo), 1)}% do risco eliminado" for c in self.curvas]
        QToolTip.showText(evento.globalPosition().toPoint(), "\n".join(linhas), self)

    def leaveEvent(self, evento):
        self._hover_x = None
        self.update()
        QToolTip.hideText()


# ================================================================ cartão de valor e cartão de gráfico
class CartaoValor(QWidget):
    """Stat tile: rótulo (frase), valor (semibold, figuras proporcionais) e uma linha de contexto (base,
    comparação). Sem cor de série no texto."""

    def __init__(self, rotulo: str, dica: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("cartaoValor")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"#cartaoValor {{ border:1px solid {cor_borda()}; border-radius:6px; }}")
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 8, 12, 9)
        v.setSpacing(2)
        self.rotulo = QLabel(rotulo)
        self.rotulo.setStyleSheet(f"color:{cor_texto_secundario()}; font-size:12px;")
        self.rotulo.setWordWrap(True)
        self.valor = QLabel("")
        self.valor.setStyleSheet(f"color:{cor_texto()}; font-size:22px; font-weight:600;")
        self.contexto = QLabel("")
        self.contexto.setStyleSheet(f"color:{cor_texto_secundario()}; font-size:11px;")
        self.contexto.setWordWrap(True)
        for w in (self.rotulo, self.valor, self.contexto):
            v.addWidget(w)
        self.setToolTip(dica)
        self.setAccessibleName(rotulo)

    def definir(self, valor: str, contexto: str = ""):
        self.valor.setText(valor)
        self.contexto.setText(contexto)
        self.contexto.setVisible(bool(contexto))
        self.setAccessibleDescription(f"{valor}. {contexto}".strip())


class CartaoGrafico(QWidget):
    """Título descritivo, a pergunta de decisão como subtítulo, o gráfico e o rodapé (fonte, base e corte)."""

    def __init__(self, titulo: str, pergunta: str, corpo: QWidget, parent=None, expandir: bool = False):
        super().__init__(parent)
        self.setObjectName("cartaoGrafico")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"#cartaoGrafico {{ border:1px solid {cor_borda()}; border-radius:6px; }}")
        v = QVBoxLayout(self)
        v.setContentsMargins(14, 10, 14, 10)
        v.setSpacing(4)
        self.titulo = QLabel(titulo)
        self.titulo.setStyleSheet(f"color:{cor_texto()}; font-size:14px; font-weight:600;")
        self.titulo.setWordWrap(True)
        self.pergunta = QLabel(pergunta)
        self.pergunta.setStyleSheet(f"color:{cor_texto_secundario()}; font-size:12px;")
        self.pergunta.setWordWrap(True)
        self.corpo = corpo
        self.rodape = QLabel("")
        self.rodape.setStyleSheet(f"color:{cor_texto_secundario()}; font-size:11px;")
        self.rodape.setWordWrap(True)
        self.rodape.setVisible(False)                 # sem texto, o rodapé não ocupa espaço
        v.addWidget(self.titulo)
        v.addWidget(self.pergunta)
        v.addSpacing(6)
        if expandir:                                  # o corpo (uma tabela) fica com a altura que sobra
            v.addWidget(corpo, 1)
        else:
            v.addWidget(corpo)
            v.addStretch(1)
        v.addWidget(self.rodape)
        self.setAccessibleName(titulo)

    def definir_rodape(self, texto: str):
        self.rodape.setText(texto)
        self.rodape.setVisible(bool(texto))


@dataclass
class Legenda:
    """Itens de legenda para um gráfico com mais de uma cor (ex.: ênfase: críticos × demais)."""
    itens: list = field(default_factory=list)       # [(nome, cor)]


def linha_legenda(itens) -> QWidget:
    """Legenda em uma linha: amostra da cor e o nome (texto em cor de texto)."""
    caixa = QWidget()
    h = QHBoxLayout(caixa)
    h.setContentsMargins(0, 0, 0, 0)
    h.setSpacing(6)
    for nome, cor in itens:
        amostra = QLabel()
        amostra.setFixedSize(12, 12)
        amostra.setStyleSheet(f"background:{cor}; border-radius:3px;")
        rotulo = QLabel(nome)
        rotulo.setStyleSheet(f"color:{cor_texto()}; font-size:11px;")
        h.addWidget(amostra)
        h.addWidget(rotulo)
        h.addSpacing(12)
    h.addStretch(1)
    caixa.setAccessibleName("Legenda: " + ", ".join(n for n, _ in itens))
    return caixa
