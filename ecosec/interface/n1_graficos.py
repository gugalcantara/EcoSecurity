"""Gráficos do painel do N1, desenhados à mão com QPainter.

Por que não QtCharts aqui: o tema do QtCharts põe fundo cinza, borda e legenda em caixa, e a faixa de rótulos e
marcas que este desenho usa (marcas finas, fim de barra arredondado, vão de 2 px entre segmentos,
grade em linha fina, rótulo direto e seletivo, texto sempre na cor de texto e nunca na cor da série) dá mais
trabalho para desligar do que para desenhar. Cada gráfico aqui:

  - responde a uma pergunta (o título e o subtítulo ficam no CartaoGrafico, fora do desenho);
  - tem um só eixo de valor, com passo 1, 2 ou 5 × 10^k e a unidade escrita;
  - mostra None (número suprimido pelo k=3 do N1) como "Suprimido", com hachura a 45°, nunca como 0;
  - tem dica em toda marca (o alvo de mouse é maior que a marca) e emite `clicado(valor)` quando a marca filtra
    (classe ou ano, os dois filtros do N1);
  - tem a tabela equivalente (`tabela()`), que o cartão mostra no lugar do gráfico (acessibilidade);
  - guarda os textos que desenhou (`textos()`) para os testes conferirem o que está visível.

Cores: as três classes com os mesmos matizes de identidade do sistema (azul, laranja, vermelho), em passos
conferidos quanto à separação para daltonismo e ao contraste, no tema claro e no escuro. As duas
medidas de prazo em violeta e água (validadas juntas). Escalas sequenciais de um matiz só. Status (bom e ruim)
só nas setas da variação, sempre com o sinal e o texto.
"""
from __future__ import annotations

from math import ceil, floor, log10

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QFontMetricsF, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QToolTip, QWidget

from ecosec.acervo import formatos
from ecosec.interface.fluent import isDarkTheme

SUPRIMIDO = "Suprimido"
AREA, CLASSE_I, RADIOATIVO = "AREA CONTAMINADA", "CLASSE I NBR 10004", "REJEITO RADIOATIVO CNEN"
CLASSES = (AREA, CLASSE_I, RADIOATIVO)                      # ordem fixa das classes em toda tela do N1

# ---------------------------------------------------------------- paleta (separação para daltonismo e contraste conferidos)
# classes: --pairs all, claro sobre #ffffff e escuro sobre #2b2b2b, todas as verificações aprovadas (o laranja do
# claro fica abaixo de 3:1: por isso todo gráfico com classe tem rótulo visível e tabela)
_CLASSE = {False: {AREA: "#2f6fbd", CLASSE_I: "#e8901a", RADIOATIVO: "#c42e4a"},
           True: {AREA: "#5592e0", CLASSE_I: "#c27a14", RADIOATIVO: "#e8607e"}}
# as duas medidas de prazo (KPI-03 e KPI-03b), validadas juntas nos dois temas
_PRAZO = {False: ("#6250d6", "#1baf7a"), True: ("#9085e9", "#199e70")}
# série única sem identidade de classe (ranking, regiões com todas as classes juntas)
_NEUTRA = {False: "#2a7f8a", True: "#46a1ab"}
# sequencial de um matiz (contagens) e a laranja de "pressão" (a mesma rampa do coroplético)
RAMPA_CONTAGEM = ("#e3f1f2", "#bfe0e3", "#93c9ce", "#62adb5", "#3b8f99", "#24717b", "#15535c")
RAMPA_PRESSAO = ("#FDE8C9", "#FBC17A", "#F59245", "#E0603A", "#B8323B")
# ordinal (faixas de idade, da mais nova à mais velha): --ordinal aprovado nos dois temas
_IDADE = {False: ("#E39B55", "#D98040", "#C9622D", "#AE4724", "#8C321D", "#66231A"),
          True: ("#F6CF9A", "#F0B070", "#E8924E", "#DC7438", "#C85A2C", "#B04A28")}
# status da variação (melhorou / piorou): sempre com seta e texto, nunca só a cor
_STATUS = {False: {"bom": "#0b7a0b", "ruim": "#b8302f", "neutro": "#6b6a66"},
           True: {"bom": "#3fbf5a", "ruim": "#ef6b6b", "neutro": "#a3a29c"}}


def escuro() -> bool:
    return bool(isDarkTheme())


def tokens() -> dict:
    """Tinta e superfícies do tema corrente (texto nunca na cor da série)."""
    if escuro():
        return {"texto": "#F0EFEC", "texto2": "#C3C2B7", "mudo": "#9A9891", "grade": "#3A3A38", "eixo": "#55544F",
                "superficie": "#2B2B2B", "suprimido": "#77766F", "vazio": "#333331", "borda": "#3D3D3A",
                "cartao": "#2B2B2B", "realce": "#F0EFEC"}
    return {"texto": "#1A1A1A", "texto2": "#55534E", "mudo": "#85837C", "grade": "#E7E6E1", "eixo": "#C4C3BC",
            "superficie": "#FFFFFF", "suprimido": "#A9A8A2", "vazio": "#F4F3EF", "borda": "#E3E2DD",
            "cartao": "#FFFFFF", "realce": "#1A1A1A"}


def cor_classe(classe: str) -> str:
    return _CLASSE[escuro()].get(classe, _NEUTRA[escuro()])


def cores_prazo() -> tuple[str, str]:
    """(além do prazo legal, prazo previsto vencido)."""
    return _PRAZO[escuro()]


def cor_neutra() -> str:
    return _NEUTRA[escuro()]


def rampa_idade() -> tuple:
    return _IDADE[escuro()]


def cor_status(tipo: str) -> str:
    return _STATUS[escuro()][tipo]


def cor_rampa(rampa, fracao: float) -> QColor:
    """Interpolação linear na rampa (0 = primeiro passo, 1 = último)."""
    fracao = min(1.0, max(0.0, fracao))
    pos = fracao * (len(rampa) - 1)
    i = min(int(pos), len(rampa) - 2)
    t = pos - i
    a, b = QColor(rampa[i]), QColor(rampa[i + 1])
    return QColor(round(a.red() + (b.red() - a.red()) * t), round(a.green() + (b.green() - a.green()) * t),
                  round(a.blue() + (b.blue() - a.blue()) * t))


def texto_sobre(fundo: QColor) -> QColor:
    """Branco ou quase preto, pelo contraste com o preenchimento (rótulo dentro de célula colorida)."""
    def canal(c):
        c /= 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    lum = 0.2126 * canal(fundo.red()) + 0.7152 * canal(fundo.green()) + 0.0722 * canal(fundo.blue())
    return QColor("#1A1A1A") if lum > 0.36 else QColor("#FFFFFF")


# ---------------------------------------------------------------- escala e formatos
def escala_redonda(maximo: float, intervalos: int = 4, inteiro: bool = True) -> tuple[float, float]:
    """(topo, passo): passo 1, 2 ou 5 × 10^k, topo múltiplo do passo e >= máximo."""
    if maximo is None or maximo <= 0:
        return (4.0, 1.0) if inteiro else (1.0, 0.25)
    bruto = maximo / max(1, intervalos)
    potencia = 10 ** floor(log10(bruto))
    passo = next(m * potencia for m in (1, 2, 5, 10) if m * potencia >= bruto - 1e-12)
    if inteiro:
        passo = max(1.0, round(passo))
    return ceil(maximo / passo - 1e-9) * passo, passo


def fmt_inteiro(v) -> str:
    return SUPRIMIDO if v is None else formatos.inteiro(v)


def fmt_pct(v, casas: int = 1) -> str:
    if v is None:
        return SUPRIMIDO
    return formatos.numero(v, casas) + "%"


def fmt_eixo(v: float, passo: float) -> str:
    if abs(v) >= 1000 and abs(passo) >= 1000:
        return formatos.numero(v / 1000, 0 if passo % 1000 == 0 else 1) + " mil"
    casas = 0 if float(passo).is_integer() else (1 if (passo * 10).is_integer() else 2)
    return formatos.numero(v, casas)


def nota_suprimido(k: int) -> str:
    """A explicação do "Suprimido": o mesmo texto em toda dica do N1 (a regra técnica fica no Glossário)."""
    return "Suprimido: número oculto para proteger poucos casos. Não quer dizer zero."


def _fonte(px: int, peso=QFont.Weight.Normal) -> QFont:
    f = QFont("Segoe UI")
    f.setPixelSize(px)
    f.setWeight(peso)
    return f


# ---------------------------------------------------------------- base
class GraficoN1(QWidget):
    """Base: alvos de mouse com dica, clique que filtra, textos desenhados e tabela equivalente."""
    clicado = Signal(object)
    ALTURA_MINIMA = 160

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)
        self.alvos: list[tuple[QRectF, str, object]] = []
        self._textos: list[str] = []
        self._sobre = None
        self.vazio = ""                                     # texto quando não há dado
        self.setMinimumHeight(self.ALTURA_MINIMA)

    # --- desenho de texto (guardado para os testes)
    def _texto(self, p: QPainter, rect: QRectF, texto: str, cor, alinhamento=Qt.AlignmentFlag.AlignLeft
               | Qt.AlignmentFlag.AlignVCenter, px: int = 12, peso=QFont.Weight.Normal, italico: bool = False):
        fonte = _fonte(px, peso)
        fonte.setItalic(italico)
        p.setFont(fonte)
        p.setPen(QColor(cor))
        p.drawText(rect, int(alinhamento), texto)
        self._textos.append(texto)

    @staticmethod
    def _largura(texto: str, px: int = 12, peso=QFont.Weight.Normal) -> float:
        return QFontMetricsF(_fonte(px, peso)).horizontalAdvance(texto)

    @staticmethod
    def _elidir(texto: str, largura: float, px: int = 12) -> str:
        return QFontMetricsF(_fonte(px)).elidedText(texto, Qt.TextElideMode.ElideRight, largura)

    def _alvo(self, rect: QRectF, dica: str, clique=None):
        self.alvos.append((QRectF(rect), dica, clique))

    def _hachura(self, p: QPainter, rect: QRectF):
        t = tokens()
        p.save()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(t["vazio"]))
        p.drawRoundedRect(rect, 2, 2)
        pincel = QBrush(QColor(t["suprimido"]), Qt.BrushStyle.BDiagPattern)
        p.setBrush(pincel)
        p.drawRoundedRect(rect, 2, 2)
        p.restore()

    # --- contrato
    def textos(self) -> list[str]:
        return list(self._textos)

    def dicas(self) -> list[str]:
        return [d for _, d, _ in self.alvos]

    def tabela(self) -> tuple[list[str], list[list[str]]]:
        return [], []

    def paintEvent(self, evento):                           # noqa: N802
        self.alvos, self._textos = [], []
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        if self.vazio:
            self._texto(p, QRectF(self.rect()), self.vazio, tokens()["mudo"], Qt.AlignmentFlag.AlignCenter)
        else:
            self.desenhar(p, QRectF(self.rect()))
        p.end()

    def desenhar(self, p: QPainter, area: QRectF):
        raise NotImplementedError

    def preparar(self):
        """Calcula os alvos e os textos sem esperar a tela pintar (pinta numa imagem fora da tela; serve também a
        um gráfico rolado para fora da vista)."""
        if self.width() < 50:
            self.resize(max(self.width(), 600), max(self.height(), self.minimumHeight()))
        self.grab()

    # --- mouse
    def _alvo_em(self, ponto: QPointF):
        for rect, dica, clique in reversed(self.alvos):
            if rect.contains(ponto):
                return rect, dica, clique
        return None

    def mouseMoveEvent(self, evento):                       # noqa: N802
        achado = self._alvo_em(evento.position())
        if achado is None:
            QToolTip.hideText()
            self.setCursor(Qt.CursorShape.ArrowCursor)
            if self._sobre is not None:
                self._sobre = None
                self.update()
            return
        rect, dica, clique = achado
        QToolTip.showText(evento.globalPosition().toPoint(), dica, self)
        self.setCursor(Qt.CursorShape.PointingHandCursor if clique is not None else Qt.CursorShape.ArrowCursor)
        chave = (rect.x(), rect.y())
        if chave != self._sobre:
            self._sobre = chave
            self.update()

    def leaveEvent(self, evento):                           # noqa: N802
        QToolTip.hideText()
        self._sobre = None
        self.update()

    def mousePressEvent(self, evento):                      # noqa: N802
        achado = self._alvo_em(evento.position())
        if achado is not None and achado[2] is not None and evento.button() == Qt.MouseButton.LeftButton:
            self.clicado.emit(achado[2])

    def _sob_mouse(self, rect: QRectF) -> bool:
        return self._sobre == (rect.x(), rect.y())


# ---------------------------------------------------------------- barras horizontais (ordenadas, empilhadas)
class BarrasN1(GraficoN1):
    """Barras horizontais de uma grandeza, uma linha por categoria, na ordem de quem chama (ordenada pelo valor,
    com as suprimidas no fim em ordem de nome). Um ou mais segmentos por linha (empilhado por classe), com vão de
    2 px entre eles; rótulo de valor no fim da barra; linhas em `destaque` ficam cheias e as outras atenuadas."""
    ALTURA_LINHA = 24
    ESPESSURA = 13

    def __init__(self, unidade: str = "casos ativos", parent=None):
        super().__init__(parent)
        self.unidade = unidade
        self.linhas: list[dict] = []
        self.legenda: list[tuple[str, str]] = []           # (nome, cor), só com mais de uma série
        self.colunas_tabela: list[str] = []
        self.maximo: float | None = None
        self.inteiro, self.formato_eixo = True, None

    def mostrar(self, linhas: list[dict], legenda=(), maximo: float | None = None, colunas_tabela=(),
                inteiro: bool = True, formato_eixo=None):
        """`linhas`: [{chave, rotulo, segmentos: [(nome, valor ou None, cor, clique)], fim: texto no fim, dica,
        clique, destaque: bool, tabela: [células]}]. Linha com algum segmento None é desenhada como Suprimido."""
        self.linhas, self.legenda, self.maximo = list(linhas), list(legenda), maximo
        self.colunas_tabela = list(colunas_tabela)
        self.inteiro, self.formato_eixo = inteiro, formato_eixo
        topo_legenda = 22 if self.legenda else 0
        self.setMinimumHeight(int(topo_legenda + 30 + self.ALTURA_LINHA * max(1, len(self.linhas))))
        self.vazio = "" if self.linhas else "Sem casos no recorte"
        self.update()

    def sizeHint(self):                                     # noqa: N802
        return QSize(420, self.minimumHeight())

    def tabela(self):
        return self.colunas_tabela, [l.get("tabela", [l["rotulo"], l.get("fim", "")]) for l in self.linhas]

    def desenhar(self, p: QPainter, area: QRectF):
        t = tokens()
        y0 = area.top() + 2
        if self.legenda:
            x = area.left()
            for nome, cor in self.legenda:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(cor))
                p.drawRoundedRect(QRectF(x, y0 + 4, 10, 10), 2, 2)
                largura = self._largura(nome, 11)
                self._texto(p, QRectF(x + 14, y0, largura + 4, 18), nome, t["texto2"], px=11)
                x += largura + 32
            y0 += 22
        largura_rotulo = min(max((self._largura(l["rotulo"]) for l in self.linhas), default=40) + 10,
                             area.width() * 0.42)
        largura_fim = max((self._largura(l.get("fim", ""), 12, QFont.Weight.DemiBold) for l in self.linhas),
                          default=0) + 12
        x0 = area.left() + largura_rotulo
        x1 = area.right() - largura_fim
        plot_h = self.ALTURA_LINHA * len(self.linhas)
        totais = [sum(v for _, v, _, _ in l["segmentos"] if v is not None) for l in self.linhas
                  if all(v is not None for _, v, _, _ in l["segmentos"])]
        topo, passo = escala_redonda(self.maximo if self.maximo is not None else max(totais, default=0), 4,
                                     inteiro=self.inteiro)
        escala = (x1 - x0) / topo if topo else 0
        rotulo_eixo = self.formato_eixo or (lambda valor: fmt_eixo(valor, passo))
        # grade (linhas finas, verticais) e rótulos do eixo embaixo
        v = 0.0
        while v <= topo + 1e-9:
            x = x0 + v * escala
            p.setPen(QPen(QColor(t["grade"] if v else t["eixo"]), 1))
            p.drawLine(QPointF(x, y0), QPointF(x, y0 + plot_h))
            self._texto(p, QRectF(x - 30, y0 + plot_h + 2, 60, 16), rotulo_eixo(v), t["mudo"],
                        Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, px=10)
            v += passo
        self._texto(p, QRectF(x0, y0 + plot_h + 15, x1 - x0, 14), self.unidade, t["mudo"],
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop, px=10)
        realce = any(l.get("destaque") for l in self.linhas)
        for i, l in enumerate(self.linhas):
            ym = y0 + i * self.ALTURA_LINHA + self.ALTURA_LINHA / 2
            linha_rect = QRectF(area.left(), ym - self.ALTURA_LINHA / 2, area.width(), self.ALTURA_LINHA)
            sob = self._sob_mouse(linha_rect)
            forte = (not realce) or l.get("destaque")
            cor_rotulo = t["texto"] if forte or sob else t["mudo"]
            self._texto(p, QRectF(area.left(), ym - 9, largura_rotulo - 8, 18),
                        self._elidir(l["rotulo"], largura_rotulo - 8), cor_rotulo,
                        peso=QFont.Weight.DemiBold if l.get("destaque") else QFont.Weight.Normal)
            suprimida = any(v is None for _, v, _, _ in l["segmentos"])
            if l.get("vazio"):                               # sem dado (ex.: UF sem casos ativos): só o texto
                self._texto(p, QRectF(x0 + 4, ym - 9, 200, 18), l["vazio"], t["mudo"], italico=True)
            elif suprimida:
                caixa = QRectF(x0, ym - self.ESPESSURA / 2, min(70.0, x1 - x0), self.ESPESSURA)
                self._hachura(p, caixa)
                self._texto(p, QRectF(caixa.right() + 6, ym - 9, 120, 18), SUPRIMIDO, t["mudo"], italico=True)
            else:
                x = x0
                segmentos = [s for s in l["segmentos"] if s[1]]
                for j, (nome, valor, cor, clique) in enumerate(segmentos):
                    largura = valor * escala
                    rect = QRectF(x, ym - self.ESPESSURA / 2, max(0.0, largura - (2 if j < len(segmentos) - 1 else 0)),
                                  self.ESPESSURA)
                    c = QColor(cor)
                    if not forte and not sob:
                        c.setAlpha(80)
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(c)
                    caminho = QPainterPath()
                    if j == len(segmentos) - 1 and rect.width() > 4:          # fim arredondado, base reta
                        caminho.addRoundedRect(rect, 3, 3)
                        reto = QPainterPath()
                        reto.addRect(QRectF(rect.left(), rect.top(), max(0.0, rect.width() - 3), rect.height()))
                        caminho = caminho.united(reto)
                    else:
                        caminho.addRect(rect)
                    p.drawPath(caminho)
                    dica_seg = l.get("dicas", {}).get(nome) if isinstance(l.get("dicas"), dict) else None
                    self._alvo(QRectF(rect.left(), linha_rect.top(), max(rect.width(), 6), linha_rect.height()),
                               dica_seg or l.get("dica", ""), clique if clique is not None else l.get("clique"))
                    x += largura
                fim = l.get("fim", "")
                if fim:
                    self._texto(p, QRectF(x + 6, ym - 9, largura_fim + 40, 18), fim,
                                t["texto"] if forte else t["mudo"], px=12, peso=QFont.Weight.DemiBold)
            self._alvo(linha_rect, l.get("dica", ""), l.get("clique"))
        if self.alvos:                                    # alvos das barras por cima dos alvos das linhas
            linhas = [a for a in self.alvos if a[0].left() == area.left() and a[0].width() == area.width()]
            barras = [a for a in self.alvos if a not in linhas]
            self.alvos = linhas + barras


# ---------------------------------------------------------------- halteres (duas medidas no mesmo eixo de %)
class HalteresN1(GraficoN1):
    """Duas porcentagens por categoria no mesmo eixo de 0 a 100% (as duas definições de fora do prazo): dois pontos
    ligados por um traço. Os valores ficam em duas colunas à direita, alinhadas, com o cabeçalho na cor da medida
    (rótulo sem colisão, mesmo quando os pontos quase se tocam). Linha `referencia` (o total) em negrito, separada."""
    ALTURA_LINHA = 24

    def __init__(self, nomes=("Além do prazo legal", "Prazo previsto vencido"), parent=None):
        super().__init__(parent)
        self.nomes = tuple(nomes)
        self.linhas: list[dict] = []
        self.maximo = 100.0
        self.base = 0.0

    def mostrar(self, linhas: list[dict], maximo: float = 100.0):
        """`linhas`: [{chave, rotulo, a, b (% ou None), dica_a, dica_b, clique, referencia: bool, destaque}]."""
        self.linhas, self.maximo = list(linhas), maximo
        self.setMinimumHeight(int(26 + 30 + self.ALTURA_LINHA * max(1, len(self.linhas)) + 8))
        self.vazio = "" if self.linhas else "Sem casos no recorte"
        self.update()

    def tabela(self):
        return (["Grupo", *self.nomes],
                [[l["rotulo"], fmt_pct(l["a"]), fmt_pct(l["b"])] for l in self.linhas])

    def desenhar(self, p: QPainter, area: QRectF):
        t = tokens()
        cores = cores_prazo()
        largura_rotulo = min(max((self._largura(l["rotulo"]) for l in self.linhas), default=40) + 12,
                             area.width() * 0.3)
        coluna = max(self._largura(n, 11, QFont.Weight.DemiBold) for n in self.nomes) + 14
        x0 = area.left() + largura_rotulo
        x1 = area.right() - 2 * coluna - 10
        y0 = area.top() + 24
        # cabeçalho: legenda das medidas sobre as colunas de valor
        for k, nome in enumerate(self.nomes):
            cx = x1 + 10 + k * coluna
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(cores[k]))
            p.drawEllipse(QPointF(cx + 5, area.top() + 10), 4.5, 4.5)
            self._texto(p, QRectF(cx + 13, area.top() + 1, coluna - 13, 18), nome, t["texto2"], px=11,
                        peso=QFont.Weight.DemiBold)
        plot_h = self.ALTURA_LINHA * len(self.linhas)
        topo, passo = escala_redonda(self.maximo, 4, inteiro=True)
        if self.maximo >= 99.999:
            topo, passo = 100.0, 25.0
        # pontos não precisam de base zero: o eixo começa num múltiplo de 10 abaixo do menor valor visível
        menor = min((v for l in self.linhas for v in (l.get("a"), l.get("b")) if v is not None), default=0.0)
        base = max(0.0, floor((menor - 5) / 10) * 10)
        if base > 0:
            passo = 10.0 if topo - base <= 50 else 20.0
            base = floor(base / passo) * passo
        self.base = base
        escala = (x1 - x0) / (topo - base)
        x0 -= base * escala                                   # px(v) = x0 + v * escala continua valendo
        v = base
        while v <= topo + 1e-9:
            x = x0 + v * escala
            p.setPen(QPen(QColor(t["grade"] if v != base else t["eixo"]), 1))
            p.drawLine(QPointF(x, y0), QPointF(x, y0 + plot_h))
            self._texto(p, QRectF(x - 24, y0 + plot_h + 2, 48, 16), fmt_eixo(v, passo) + "%", t["mudo"],
                        Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, px=10)
            v += passo
        self._texto(p, QRectF(area.left(), y0 + plot_h + 15, x1 - area.left(), 14),
                    "% do grupo" + (f" · eixo a partir de {formatos.numero(base, 0)}%" if base else ""),
                    t["mudo"],
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop, px=10)
        realce = any(l.get("destaque") for l in self.linhas)
        for i, l in enumerate(self.linhas):
            ym = y0 + i * self.ALTURA_LINHA + self.ALTURA_LINHA / 2
            linha_rect = QRectF(area.left(), ym - self.ALTURA_LINHA / 2, area.width(), self.ALTURA_LINHA)
            sob = self._sob_mouse(linha_rect)
            forte = (not realce) or l.get("destaque") or sob
            if l.get("referencia") and i > 0:
                p.setPen(QPen(QColor(t["eixo"]), 1))
                p.drawLine(QPointF(area.left(), linha_rect.top()), QPointF(area.right(), linha_rect.top()))
            peso = QFont.Weight.DemiBold if l.get("referencia") or l.get("destaque") else QFont.Weight.Normal
            self._texto(p, QRectF(area.left(), ym - 9, largura_rotulo - 8, 18),
                        self._elidir(l["rotulo"], largura_rotulo - 8), t["texto"] if forte else t["mudo"], peso=peso)
            a, b = l.get("a"), l.get("b")
            if a is None and b is None:
                caixa = QRectF(x0 + self.base * escala, ym - 6, 60, 12)
                self._hachura(p, caixa)
                self._texto(p, QRectF(caixa.right() + 6, ym - 9, 120, 18), SUPRIMIDO, t["mudo"], italico=True)
            else:
                if a is not None and b is not None:
                    p.setPen(QPen(QColor(t["eixo"]), 2))
                    p.drawLine(QPointF(x0 + a * escala, ym), QPointF(x0 + b * escala, ym))
                juntos = a is not None and b is not None and abs(a - b) * escala < 5
                for k, valor in enumerate((a, b)):
                    if valor is None:
                        continue
                    centro = QPointF(x0 + valor * escala, ym)
                    cor = QColor(cores[k])
                    if not forte:
                        cor.setAlpha(90)
                    p.setPen(QPen(QColor(t["cartao"]), 2))
                    p.setBrush(cor)
                    if juntos:                               # pontos coincidentes: meio ponto de cada cor
                        caixa = QRectF(centro.x() - 5.5, ym - 5.5, 11, 11)
                        p.drawPie(caixa, (90 if k == 0 else 270) * 16, 180 * 16)
                    else:
                        p.drawEllipse(centro, 5.5, 5.5)
            for k, (valor, dica) in enumerate(((a, l.get("dica_a", "")), (b, l.get("dica_b", "")))):
                cx = x1 + 10 + k * coluna
                texto = fmt_pct(valor)
                self._texto(p, QRectF(cx + 13, ym - 9, coluna - 13, 18), texto,
                            t["mudo"] if valor is None else (t["texto"] if forte else t["mudo"]),
                            peso=peso if valor is not None else QFont.Weight.Normal, italico=valor is None)
                if valor is not None:
                    self._alvo(QRectF(x0 + valor * escala - 9, ym - 11, 18, 22), dica, l.get("clique"))
            self._alvo(linha_rect, "\n".join(d for d in (l.get("dica_a", ""), l.get("dica_b", "")) if d),
                       l.get("clique"))
        self.alvos.sort(key=lambda a: -a[0].width())          # pontos (menores) por último: ganham o mouse


# ---------------------------------------------------------------- mapa de calor
class MapaCalorN1(GraficoN1):
    """Grade linhas × colunas com a cor na rampa de um matiz (mais escuro = mais). Texto dentro da célula em
    branco ou quase preto, pelo contraste. Margens (coluna e linha de total) sem cor, em negrito. None: célula
    hachurada com "Suprimido"."""
    ALTURA_LINHA = 30

    def __init__(self, rampa=RAMPA_CONTAGEM, parent=None):
        super().__init__(parent)
        self.rampa = rampa
        self.linhas: list[str] = []
        self.colunas: list[tuple[str, object]] = []          # (rótulo, clique)
        self.celulas: list[list[dict]] = []                  # {valor (cor), texto, dica, clique, margem: bool}
        self.legenda_escala = ""
        self.maximo, self.formato = None, None

    def mostrar(self, linhas, colunas, celulas, legenda_escala: str = "", rampa=None, maximo: float | None = None,
                formato=None):
        """`maximo`: o valor da cor mais escura (padrão: o maior visível); `formato`: texto do máximo na legenda."""
        self.linhas, self.colunas, self.celulas = list(linhas), list(colunas), [list(c) for c in celulas]
        self.legenda_escala, self.maximo, self.formato = legenda_escala, maximo, formato
        if rampa is not None:
            self.rampa = rampa
        self.setMinimumHeight(int(34 + self.ALTURA_LINHA * max(1, len(self.linhas)) + 46))
        self.vazio = "" if self.linhas else "Sem casos no recorte"
        self.update()

    def tabela(self):
        return ["", *[c for c, _ in self.colunas]], [[r, *[c["texto"] for c in linha]]
                                                     for r, linha in zip(self.linhas, self.celulas)]

    def desenhar(self, p: QPainter, area: QRectF):
        t = tokens()
        largura_rotulo = min(max((self._largura(r) for r in self.linhas), default=40) + 12, area.width() * 0.46)
        x0 = area.left() + largura_rotulo
        largura = (area.width() - largura_rotulo) / max(1, len(self.colunas))
        y0 = area.top() + 32
        valores = [c["valor"] for linha in self.celulas for c in linha if not c.get("margem") and c["valor"] is not None]
        maximo = self.maximo or max(valores, default=0) or 1
        for j, (rotulo, clique) in enumerate(self.colunas):
            rect = QRectF(x0 + j * largura, area.top(), largura, 30)
            self._texto(p, rect.adjusted(4, 0, -4, 0), rotulo, t["texto2"],
                        Qt.AlignmentFlag.AlignCenter.value | Qt.TextFlag.TextWordWrap.value, px=11, peso=QFont.Weight.DemiBold)
            if clique is not None:
                self._alvo(rect, f"{rotulo}: clique para filtrar por esta classe", clique)
        for i, rotulo in enumerate(self.linhas):
            y = y0 + i * self.ALTURA_LINHA
            self._texto(p, QRectF(area.left(), y, largura_rotulo - 8, self.ALTURA_LINHA),
                        self._elidir(rotulo, largura_rotulo - 8), t["texto"])
            for j, c in enumerate(self.celulas[i]):
                rect = QRectF(x0 + j * largura + 1, y + 1, largura - 2, self.ALTURA_LINHA - 2)
                sob = self._sob_mouse(rect)
                if c["valor"] is None and not c.get("margem"):
                    self._hachura(p, rect)
                    self._texto(p, rect, SUPRIMIDO, t["mudo"], Qt.AlignmentFlag.AlignCenter, px=11, italico=True)
                elif c.get("margem"):
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(QColor(t["vazio"]))
                    p.drawRoundedRect(rect, 2, 2)
                    self._texto(p, rect, c["texto"], t["mudo"] if c["valor"] is None else t["texto"],
                                Qt.AlignmentFlag.AlignCenter, px=12, peso=QFont.Weight.DemiBold,
                                italico=c["valor"] is None)
                else:
                    fundo = cor_rampa(self.rampa, c["valor"] / maximo)
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(fundo)
                    p.drawRoundedRect(rect, 2, 2)
                    self._texto(p, rect, c["texto"], texto_sobre(fundo), Qt.AlignmentFlag.AlignCenter, px=12,
                                peso=QFont.Weight.DemiBold)
                if sob:
                    p.setPen(QPen(QColor(t["realce"]), 1.5))
                    p.setBrush(Qt.BrushStyle.NoBrush)
                    p.drawRoundedRect(rect, 2, 2)
                self._alvo(rect, c.get("dica", ""), c.get("clique"))
        # legenda da escala: rampa contínua com o mínimo e o máximo
        y = y0 + len(self.linhas) * self.ALTURA_LINHA + 10
        largura_barra = min(180.0, area.width() - largura_rotulo)
        for k in range(60):
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(cor_rampa(self.rampa, k / 59))
            p.drawRect(QRectF(x0 + k * largura_barra / 60, y, largura_barra / 60 + 0.5, 8))
        self._texto(p, QRectF(x0, y + 9, 60, 14), "0", t["mudo"], px=10)
        self._texto(p, QRectF(x0 + largura_barra - 80, y + 9, 80, 14),
                    (self.formato or (lambda v: formatos.numero(v, 0)))(maximo), t["mudo"],
                    Qt.AlignmentFlag.AlignRight, px=10)
        self._texto(p, QRectF(x0, y + 22, area.right() - x0, 14), self.legenda_escala, t["mudo"], px=10)
        self.alvos.sort(key=lambda a: -a[0].width() * a[0].height())


# ---------------------------------------------------------------- linhas no tempo (e degraus)
class LinhasN1(GraficoN1):
    """Uma ou mais séries no mesmo eixo (mesma unidade). Eixo X: anos (inteiros) ou anos desde a identificação
    (degraus). Linha de 2 px, legenda acima (com mais de uma série), rótulo do último valor de cada série no fim
    quando não colide, linha do ano escolhido e mira no mouse com a dica de todas as séries daquele ano. None =
    vão na linha e um tracinho cinza no pé ("Suprimido" na dica). Clique escolhe o ano (`clicado(ano)`)."""

    def __init__(self, unidade: str = "casos ativos", degrau: bool = False, parent=None):
        super().__init__(parent)
        self.unidade, self.degrau = unidade, degrau
        self.series: list[dict] = []                          # {chave, nome, cor, pontos: [(x, y ou None)], tracejado}
        self.marcado = None                                   # ano escolhido (linha vertical)
        self.referencia = None                                # (y, rótulo): linha horizontal (ex.: 50%)
        self.maximo_y = None
        self.rotulo_x = "ano"
        self.dica_x = None                                    # x -> texto da dica para aquele x
        self.clicavel = True
        self.parcial_ultimo = False
        self.marcas: list[tuple[float, str]] = []             # (x, rótulo) de pontos anotados (ex.: medianas)
        self.eventos: list[tuple[float, str, str]] = []       # (x, número, dica): marcos regulatórios no topo
        self.rotulos_evento: list[QRectF] = []
        self.setMinimumHeight(240)

    def mostrar(self, series, marcado=None, referencia=None, maximo_y=None, rotulo_x="ano", dica_x=None,
                parcial_ultimo=False, marcas=(), eventos=()):
        self.series = [s for s in series if s["pontos"]]
        self.marcado, self.referencia, self.maximo_y = marcado, referencia, maximo_y
        self.rotulo_x, self.dica_x, self.parcial_ultimo = rotulo_x, dica_x, parcial_ultimo
        self.marcas = list(marcas)
        self.eventos = list(eventos)
        self.vazio = "" if self.series else "Sem dado no recorte"
        self.update()

    def tabela(self):
        xs = sorted({x for s in self.series for x, _ in s["pontos"]})
        if len(xs) > 60:
            return [], []
        unidade = "%" if "%" in self.unidade else ""

        def fmt(v):
            if v is None:
                return SUPRIMIDO
            return fmt_pct(v) if unidade else (formatos.inteiro(v) if float(v).is_integer() else formatos.numero(v, 1))
        valores = {s["nome"]: dict(s["pontos"]) for s in self.series}
        return ([self.rotulo_x, *valores], [[self._fmt_x(x),
                                             *[fmt(valores[n].get(x)) if x in valores[n] else "" for n in valores]]
                                            for x in xs])

    def _xs(self):
        return sorted({x for s in self.series for x, _ in s["pontos"]})

    def desenhar(self, p: QPainter, area: QRectF):
        t = tokens()
        y_topo = area.top() + (22 if len(self.series) > 1 else 0) + 16      # legenda e a linha da unidade
        if len(self.series) > 1:                              # legenda (identidade nunca só pela cor)
            x = area.left() + 44
            for s in self.series:
                p.setPen(QPen(QColor(s["cor"]), 2, Qt.PenStyle.DashLine if s.get("tracejado") else Qt.PenStyle.SolidLine))
                p.drawLine(QPointF(x, area.top() + 10), QPointF(x + 16, area.top() + 10))
                largura = self._largura(s["nome"], 11)
                self._texto(p, QRectF(x + 20, area.top() + 1, largura + 4, 18), s["nome"], t["texto2"], px=11)
                x += largura + 40
        valores = [y for s in self.series for _, y in s["pontos"] if y is not None]
        topo, passo = escala_redonda(self.maximo_y if self.maximo_y is not None else max(valores, default=0) * 1.08,
                                     4, inteiro="%" not in self.unidade)
        if self.maximo_y is not None and self.maximo_y >= 99.999 and "%" in self.unidade:
            topo, passo = 100.0, 25.0
        xs = self._xs()
        x_min, x_max = (xs[0], xs[-1]) if xs else (0, 1)
        if x_max == x_min:
            x_max = x_min + 1
        largura_eixo = max(self._largura(fmt_eixo(topo, passo), 10), 24) + 8
        largura_fim = 0
        if len(self.series) <= 3:
            largura_fim = max((self._largura(self._fmt(s["pontos"][-1][1]), 11, QFont.Weight.DemiBold)
                               for s in self.series), default=0) + 10
        x0, x1 = area.left() + largura_eixo, area.right() - largura_fim - 6
        y1 = area.bottom() - 34
        y0 = y_topo + 6
        self._geo = (x0, x1, y0, y1, x_min, x_max, topo)

        def px_x(x):
            return x0 + (x - x_min) / (x_max - x_min) * (x1 - x0)

        def px_y(y):
            return y1 - (y / topo) * (y1 - y0) if topo else y1
        # grade horizontal e eixo Y
        v = 0.0
        while v <= topo + 1e-9:
            y = px_y(v)
            p.setPen(QPen(QColor(t["grade"] if v else t["eixo"]), 1))
            p.drawLine(QPointF(x0, y), QPointF(x1, y))
            self._texto(p, QRectF(area.left(), y - 8, largura_eixo - 6, 16), fmt_eixo(v, passo), t["mudo"],
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, px=10)
            v += passo
        self._texto(p, QRectF(area.left(), y_topo - 16, 300, 14), self.unidade, t["mudo"], px=10)
        # eixo X: ticks redondos
        _, passo_x = escala_redonda(x_max - x_min, 6, inteiro=True)
        primeiro = ceil(x_min / passo_x) * passo_x
        x = primeiro
        while x <= x_max + 1e-9:
            self._texto(p, QRectF(px_x(x) - 24, y1 + 4, 48, 14), self._fmt_x(x), t["mudo"],
                        Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, px=10)
            x += passo_x
        self._texto(p, QRectF(x0, y1 + 18, x1 - x0, 14), self.rotulo_x, t["mudo"],
                    Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, px=10)
        # referência horizontal
        if self.referencia is not None:
            yr = px_y(self.referencia[0])
            p.setPen(QPen(QColor(t["eixo"]), 1))
            p.drawLine(QPointF(x0, yr), QPointF(x1, yr))
            self._texto(p, QRectF(x1 - 220, yr - 16, 218, 14), self.referencia[1], t["mudo"],
                        Qt.AlignmentFlag.AlignRight, px=10)
        # ano escolhido
        if self.marcado is not None and x_min <= self.marcado <= x_max:
            xm = px_x(self.marcado)
            p.setPen(QPen(QColor(t["texto2"]), 1))
            p.drawLine(QPointF(xm, y0), QPointF(xm, y1))
        # séries
        for s in self.series:
            caneta = QPen(QColor(s["cor"]), 2, Qt.PenStyle.DashLine if s.get("tracejado") else Qt.PenStyle.SolidLine)
            caneta.setCapStyle(Qt.PenCapStyle.RoundCap)
            caneta.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            caminho, aberto, anterior = QPainterPath(), False, None
            for x, y in s["pontos"]:
                if y is None:
                    aberto, anterior = False, None
                    p.setPen(QPen(QColor(t["suprimido"]), 2))
                    p.drawLine(QPointF(px_x(x), y1 - 4), QPointF(px_x(x), y1))
                    continue
                ponto = QPointF(px_x(x), px_y(y))
                if not aberto:
                    caminho.moveTo(ponto)
                    aberto = True
                elif self.degrau and anterior is not None:
                    caminho.lineTo(QPointF(ponto.x(), anterior.y()))
                    caminho.lineTo(ponto)
                else:
                    caminho.lineTo(ponto)
                anterior = ponto
            p.setPen(caneta)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(caminho)
            ultimo = s["pontos"][-1]
            if ultimo[1] is not None:
                fim = QPointF(px_x(ultimo[0]), px_y(ultimo[1]))
                p.setPen(QPen(QColor(t["cartao"]), 2))
                p.setBrush(QColor(t["cartao"]) if self.parcial_ultimo else QColor(s["cor"]))
                if self.parcial_ultimo:
                    p.setPen(QPen(QColor(s["cor"]), 2))
                p.drawEllipse(fim, 4, 4)
        # rótulos de fim (direto, só sem colisão)
        if largura_fim:
            fins = sorted(((px_y(s["pontos"][-1][1]), s) for s in self.series if s["pontos"][-1][1] is not None),
                          key=lambda a: a[0])
            if all(b[0] - a[0] >= 14 for a, b in zip(fins, fins[1:])):
                for y, s in fins:
                    self._texto(p, QRectF(x1 + 8, y - 8, largura_fim + 4, 16), self._fmt(s["pontos"][-1][1]),
                                t["texto"], px=11, peso=QFont.Weight.DemiBold)
        for x, rotulo in self.marcas:                          # anotações (ex.: a mediana de cada classe)
            xm = px_x(x)
            p.setPen(QPen(QColor(t["eixo"]), 1))
            p.drawLine(QPointF(xm, y1), QPointF(xm, y1 - 6))
        # marcos (eventos): número pequeno no topo, um traço fino até o eixo; sem colisão (o seguinte desce uma linha)
        self.rotulos_evento = []
        ultimo_x, nivel = None, 0
        for x, numero, dica in self.eventos:
            if not x_min <= x <= x_max:
                continue
            xe = px_x(x)
            nivel = (nivel + 1) % 2 if ultimo_x is not None and xe - ultimo_x < 14 else 0
            ultimo_x = xe
            caixa = QRectF(xe - 7, y0 + nivel * 13, 14, 13)
            p.setPen(QPen(QColor(t["grade"]), 1))
            p.drawLine(QPointF(xe, caixa.bottom()), QPointF(xe, y1))
            self._texto(p, caixa, numero, t["texto2"], Qt.AlignmentFlag.AlignCenter, px=10, peso=QFont.Weight.DemiBold)
            self.rotulos_evento.append(caixa)
            self._alvo(caixa.adjusted(-3, -2, 3, 2), dica)
        if self.parcial_ultimo and xs:
            self._texto(p, QRectF(px_x(xs[-1]) - 40, y0 - 16, 40, 14), "parcial", t["mudo"],
                        Qt.AlignmentFlag.AlignRight, px=10, italico=True)
        # mira: alvo por x (faixa vertical inteira), com a dica de todas as séries
        if xs:
            for i, x in enumerate(xs):
                esquerda = px_x(xs[i - 1]) if i else x0 - 6
                direita = px_x(xs[i + 1]) if i + 1 < len(xs) else x1 + 6
                faixa = QRectF((esquerda + px_x(x)) / 2, y0, (direita - esquerda) / 2, y1 - y0)
                if self._sob_mouse(faixa):
                    p.setPen(QPen(QColor(t["eixo"]), 1))
                    p.drawLine(QPointF(px_x(x), y0), QPointF(px_x(x), y1))
                    for s in self.series:
                        y = dict(s["pontos"]).get(x)
                        if y is not None:
                            p.setPen(QPen(QColor(t["cartao"]), 2))
                            p.setBrush(QColor(s["cor"]))
                            p.drawEllipse(QPointF(px_x(x), px_y(y)), 4.5, 4.5)
                self._alvo(faixa, self._dica(x), (int(x) if self.clicavel and float(x).is_integer() else None))
            pequenos = [a for a in self.alvos if a[0].width() <= 20]
            self.alvos = [a for a in self.alvos if a[0].width() > 20] + pequenos      # o evento ganha o mouse

    def _fmt_x(self, x) -> str:
        """Ano sem separador de milhar (2026, não 2.026); anos desde a identificação com vírgula."""
        if self.rotulo_x == "ano":
            return str(int(x))
        return formatos.numero(x, 0 if float(x).is_integer() else 1)

    def _fmt(self, v) -> str:
        if v is None:
            return SUPRIMIDO
        if "%" in self.unidade:
            return fmt_pct(v)
        return formatos.inteiro(v) if float(v).is_integer() else formatos.numero(v, 1)

    def _dica(self, x) -> str:
        if self.dica_x is not None:
            return self.dica_x(x)
        linhas = [self._fmt_x(x)]
        for s in self.series:
            pontos = dict(s["pontos"])
            if x in pontos:
                linhas.append(f"{s['nome']}: {self._fmt(pontos[x])}")
        return "\n".join(linhas)


# ---------------------------------------------------------------- colunas por ano (taxa anual)
class ColunasN1(GraficoN1):
    """Uma coluna por ano, uma grandeza (% ao ano). Rótulo só no ano escolhido, no maior e no menor; o ano corrente
    (parcial) em contorno, com "parcial". None: tracinho cinza no pé e "Suprimido" na dica. Clique escolhe o ano."""

    def __init__(self, unidade: str = "% ao ano", parent=None):
        super().__init__(parent)
        self.unidade = unidade
        self.itens: list[dict] = []                          # {x, valor ou None, parcial, dica}
        self.marcado = None
        self.cor = None
        self.setMinimumHeight(240)

    def mostrar(self, itens, marcado=None, cor=None):
        self.itens, self.marcado, self.cor = list(itens), marcado, cor
        self.vazio = "" if self.itens else "Sem dado no recorte"
        self.update()

    def tabela(self):
        return ["ano", self.unidade], [[str(i["x"]), fmt_pct(i["valor"]) + (" (parcial)" if i.get("parcial") and
                                                                            i["valor"] is not None else "")]
                                       for i in self.itens]

    def desenhar(self, p: QPainter, area: QRectF):
        t = tokens()
        cor = QColor(self.cor or cor_neutra())
        valores = [i["valor"] for i in self.itens if i["valor"] is not None]
        topo, passo = escala_redonda(max(valores, default=0) * 1.15, 4, inteiro=False)
        largura_eixo = max(self._largura(fmt_eixo(topo, passo), 10), 24) + 8
        x0, x1 = area.left() + largura_eixo, area.right() - 4
        y0, y1 = area.top() + 22, area.bottom() - 34
        n = max(1, len(self.itens))
        banda = (x1 - x0) / n
        espessura = min(18.0, banda * 0.62)

        def px_y(y):
            return y1 - y / topo * (y1 - y0)
        v = 0.0
        while v <= topo + 1e-9:
            y = px_y(v)
            p.setPen(QPen(QColor(t["grade"] if v else t["eixo"]), 1))
            p.drawLine(QPointF(x0, y), QPointF(x1, y))
            self._texto(p, QRectF(area.left(), y - 8, largura_eixo - 6, 16), fmt_eixo(v, passo), t["mudo"],
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, px=10)
            v += passo
        self._texto(p, QRectF(x0 + 4, y0 - 18, 300, 14), self.unidade, t["mudo"], px=10)
        rotulados = set()
        fechados = [i for i in self.itens if i["valor"] is not None and not i.get("parcial")]
        if fechados:
            rotulados |= {max(fechados, key=lambda i: i["valor"])["x"], min(fechados, key=lambda i: i["valor"])["x"]}
        if self.marcado is not None:
            rotulados.add(self.marcado)
        _, passo_x = escala_redonda(len(self.itens), 6, inteiro=True)
        for k, item in enumerate(self.itens):
            cx = x0 + banda * (k + 0.5)
            faixa = QRectF(x0 + banda * k, y0, banda, y1 - y0)
            sob = self._sob_mouse(faixa)
            if item["valor"] is None:
                p.setPen(QPen(QColor(t["suprimido"]), 2))
                p.drawLine(QPointF(cx - 4, y1 - 1), QPointF(cx + 4, y1 - 1))
            else:
                topo_y = px_y(item["valor"])
                rect = QRectF(cx - espessura / 2, topo_y, espessura, y1 - topo_y)
                c = QColor(cor)
                if self.marcado is not None and item["x"] != self.marcado and not sob:
                    c.setAlpha(150)
                caminho = QPainterPath()
                caminho.addRoundedRect(rect, 3, 3)
                reto = QPainterPath()
                reto.addRect(QRectF(rect.left(), rect.top() + 3, rect.width(), max(0.0, rect.height() - 3)))
                caminho = caminho.united(reto)
                if item.get("parcial"):
                    p.setPen(QPen(cor, 1.5))
                    p.setBrush(QBrush(cor, Qt.BrushStyle.BDiagPattern))
                else:
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(c)
                p.drawPath(caminho)
                if item["x"] in rotulados or item.get("parcial") or sob:
                    texto = fmt_pct(item["valor"])                  # o parcial já está na hachura e na nota
                    largura = self._largura(texto, 10, QFont.Weight.DemiBold)
                    esquerda = min(max(cx - largura / 2 - 2, x0), x1 - largura - 4)
                    self._texto(p, QRectF(esquerda, topo_y - 16, largura + 4, 14), texto, t["texto"],
                                Qt.AlignmentFlag.AlignHCenter, px=10, peso=QFont.Weight.DemiBold)
            if k % int(passo_x) == 0 or k == len(self.itens) - 1:
                self._texto(p, QRectF(cx - 20, y1 + 4, 40, 14), str(item["x"]), t["mudo"],
                            Qt.AlignmentFlag.AlignHCenter, px=10)
            self._alvo(faixa, item.get("dica", ""), item["x"])
        self._texto(p, QRectF(x0, y1 + 18, x1 - x0, 14), "ano", t["mudo"], Qt.AlignmentFlag.AlignHCenter, px=10)


# ---------------------------------------------------------------- barras de 100% (composição ordinal)
class Barras100N1(GraficoN1):
    """Uma barra de 100% por linha, com os segmentos de uma escala ordinal (faixas de idade). O rótulo de % entra no
    segmento só quando cabe; as faixas suprimidas de uma linha viram um segmento hachurado "Suprimido" (a soma delas
    já sai do total menos as visíveis, então juntá-las não revela nada novo)."""
    ALTURA_LINHA = 34

    def __init__(self, parent=None):
        super().__init__(parent)
        self.linhas: list[dict] = []                 # {rotulo, total, partes: [(faixa, n ou None)], clique}
        self.faixas: list[str] = []
        self.rotulos_faixa: dict = {}

    def mostrar(self, faixas, rotulos_faixa: dict, linhas):
        self.faixas, self.rotulos_faixa, self.linhas = list(faixas), dict(rotulos_faixa), list(linhas)
        self.setMinimumHeight(int(30 + self.ALTURA_LINHA * max(1, len(self.linhas)) + 6))
        self.vazio = "" if self.linhas else "Sem casos no recorte"
        self.update()

    def tabela(self):
        return (["", *[self.rotulos_faixa.get(f, f) for f in self.faixas], "Total"],
                [[l["rotulo"], *[fmt_inteiro(n) for _, n in l["partes"]], fmt_inteiro(l["total"])] for l in self.linhas])

    def desenhar(self, p: QPainter, area: QRectF):
        t = tokens()
        rampa = rampa_idade()
        x = area.left()
        for k, f in enumerate(self.faixas):
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(rampa[k % len(rampa)]))
            p.drawRoundedRect(QRectF(x, area.top() + 5, 10, 10), 2, 2)
            nome = self.rotulos_faixa.get(f, f)
            largura = self._largura(nome, 11)
            self._texto(p, QRectF(x + 14, area.top() + 1, largura + 4, 18), nome, t["texto2"], px=11)
            x += largura + 30
        largura_rotulo = min(max((self._largura(l["rotulo"]) for l in self.linhas), default=40) + 12,
                             area.width() * 0.3)
        x0, x1 = area.left() + largura_rotulo, area.right() - 70
        y0 = area.top() + 28
        for i, l in enumerate(self.linhas):
            ym = y0 + i * self.ALTURA_LINHA + self.ALTURA_LINHA / 2
            self._texto(p, QRectF(area.left(), ym - 9, largura_rotulo - 8, 18),
                        self._elidir(l["rotulo"], largura_rotulo - 8), t["texto"])
            total = l["total"]
            if not total:
                self._hachura(p, QRectF(x0, ym - 8, 60, 16))
                self._texto(p, QRectF(x0 + 66, ym - 9, 140, 18), SUPRIMIDO if total is None else "sem casos",
                            t["mudo"], italico=True)
                self._alvo(QRectF(x0, ym - 12, x1 - x0, 24), l.get("dica_total", ""), l.get("clique"))
                continue
            visiveis = sum(n for _, n in l["partes"] if n is not None)
            escondido = total - visiveis
            x = x0
            segmentos = [(f, n) for f, n in l["partes"] if n]
            if any(n is None for _, n in l["partes"]) and escondido > 0:
                segmentos.append((None, escondido))
            for j, (f, n) in enumerate(segmentos):
                largura = (x1 - x0) * n / total
                rect = QRectF(x, ym - 9, max(0.0, largura - (2 if j < len(segmentos) - 1 else 0)), 18)
                if f is None:
                    self._hachura(p, rect)
                    dica = f"{l['rotulo']}: faixas com poucos casos, {formatos.inteiro(n)} casos"
                else:
                    k = self.faixas.index(f)
                    fundo = QColor(rampa[k % len(rampa)])
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(fundo)
                    p.drawRect(rect)
                    pct = 100 * n / total
                    texto = formatos.numero(pct, 0) + "%"
                    if self._largura(texto, 11, QFont.Weight.DemiBold) + 6 <= rect.width():
                        self._texto(p, rect, texto, texto_sobre(fundo), Qt.AlignmentFlag.AlignCenter, px=11,
                                    peso=QFont.Weight.DemiBold)
                    dica = (f"{l['rotulo']} · {self.rotulos_faixa.get(f, f)}: {formatos.inteiro(n)} casos ativos "
                            f"({formatos.numero(pct, 1)}% de {formatos.inteiro(total)})")
                self._alvo(QRectF(rect.left(), ym - 12, max(rect.width(), 4), 24), dica, l.get("clique"))
                x += largura
            ocultas = [self.rotulos_faixa.get(f, f) for f, n in l["partes"] if n is None]
            if ocultas:
                self._textos.append(f"{SUPRIMIDO}: {', '.join(ocultas)}")
            self._texto(p, QRectF(x1 + 8, ym - 9, 62, 18), formatos.inteiro(total), t["texto"], px=12,
                        peso=QFont.Weight.DemiBold)
