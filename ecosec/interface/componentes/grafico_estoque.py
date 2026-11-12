"""Estoque ATIVO por classe, com os eventos numerados (3.1.3, valores desentrelaçados).

Três modos, cada grandeza no seu eixo (nenhum gráfico tem dois eixos verticais):
  - Estoque ativo por classe: áreas empilhadas (a borda de cima é o total, que aparece no título e no
    rótulo do ano; nenhuma linha de total por cima das áreas);
  - SALDO ANUAL: dois gráficos com o mesmo eixo X. Em cima, entradas para cima e saídas para baixo,
    num eixo simétrico com o 0 marcado; embaixo, o saldo (entradas menos saídas) em barras positivas e
    negativas, na escala dele. Num estoque de ~1.000 pendências uma queda de poucas unidades some; no saldo,
    todo ano negativo aparece;
  - Por classe (SMALL MULTIPLES): um gráfico pequeno por classe, cada um com o seu eixo Y: a classe
    pequena (rejeito) deixa de ser uma faixa ilegível no topo da pilha.
Eventos: linha vertical pontilhada e um número no topo, dentro da área do gráfico e sem colisão; o
texto vai para a dica e para a legenda de eventos abaixo. Eixos de valor com passo redondo, 1, 2 ou 5 vezes 10^k.
"""
import math

from PySide6.QtCharts import (QAreaSeries, QBarCategoryAxis, QBarSet, QChart, QChartView, QLineSeries,
                              QStackedBarSeries, QValueAxis)
from PySide6.QtCore import QMargins, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QCursor, QFont, QFontMetricsF, QPainter, QPen
from PySide6.QtWidgets import (QGraphicsLineItem, QGraphicsSimpleTextItem, QGridLayout, QLabel, QToolTip,
                               QVBoxLayout, QWidget)

from ecosec.acervo.vocabulario import rotulo as _rotulo
from ecosec.interface.componentes.simbologia import COR_IDENTIDADE_CLASSE
from ecosec.interface.fluent import isDarkTheme

CORES = dict(COR_IDENTIDADE_CLASSE)          # fonte única das cores de classe (o mapa temático usa as mesmas)
COR_ENTRADAS, COR_SAIDAS = "#7FA7D6", "#2EA36B"
MODOS = ("ESTOQUE ATIVO POR CLASSE", "SALDO ANUAL (ENTRADAS - SAIDAS)", "POR CLASSE (SMALL MULTIPLES)")
MESES = ("jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez")
TODAS = "Todas as classes"
SUPRIMIDO = "SUPRIMIDO"


# ---------------------------------------------------------------- eixos redondos
def passo_redondo(bruto: float) -> float:
    """O menor passo 1, 2 ou 5 vezes 10^k que seja >= `bruto`."""
    if bruto <= 0:
        return 1.0
    k = math.floor(math.log10(bruto))
    for m in (1, 2, 5, 10):
        if m * 10 ** k >= bruto * (1 - 1e-9):
            return float(m * 10 ** k)
    return float(10 ** (k + 1))


def eixo_redondo(eixo: QValueAxis, minimo: float, maximo: float, intervalos: int = 6, inteiro: bool = True,
                 simetrico: bool = False, ancora: float = 0.0) -> float:
    """Faixa e ticks em múltiplos de um passo redondo, com tick na âncora (0 por padrão). Devolve o passo."""
    if simetrico:
        m = max(abs(minimo), abs(maximo)) or 1
        minimo, maximo = -m, m
    passo = passo_redondo(((maximo - minimo) or 1) / max(1, intervalos))
    if inteiro:
        passo = max(1.0, passo)
    inferior = ancora + math.floor((minimo - ancora) / passo + 1e-9) * passo
    superior = ancora + math.ceil((maximo - ancora) / passo - 1e-9) * passo
    if superior <= inferior:
        superior = inferior + passo
    eixo.setRange(inferior, superior)
    eixo.setTickType(QValueAxis.TickType.TicksDynamic)
    eixo.setTickAnchor(ancora)
    eixo.setTickInterval(passo)
    casas = 0 if passo >= 1 else -math.floor(math.log10(passo))
    eixo.setLabelFormat(f"%.{casas}f")
    return passo


def eixo_anos(eixo: QValueAxis, primeiro: int, ultimo: int, passo: int):
    eixo.setRange(primeiro, ultimo)
    eixo.setTickType(QValueAxis.TickType.TicksDynamic)
    eixo.setTickAnchor(float(primeiro if passo <= 2 else passo * math.ceil(primeiro / passo)))
    eixo.setTickInterval(float(passo))
    eixo.setLabelFormat("%.0f")
    eixo.setTitleText("ano")


def _numero(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def _contagem(n) -> str:
    """Contagem para título, rótulo ou dica: None (suprimido pelo k) sai SUPRIMIDO, nunca 0."""
    return SUPRIMIDO if n is None else _numero(n)


def segmentos(pontos) -> list[list]:
    """Quebra uma sequência em trechos contíguos sem None (o vão de uma célula suprimida)."""
    trechos, atual = [], []
    for p in pontos:
        if p is None:
            if atual:
                trechos.append(atual)
            atual = []
        else:
            atual.append(p)
    if atual:
        trechos.append(atual)
    return trechos


def _sinal(n: int) -> str:
    return f"+{_numero(n)}" if n > 0 else ("-" + _numero(-n) if n < 0 else "0")


def _data(d) -> str:
    return f"{MESES[d.month - 1]}/{d.year}"


# ---------------------------------------------------------------- um gráfico com a camada de anotações
class VistaEstoque(QChartView):
    """Um QChart com eventos numerados, o marcador do ano e (opcional) a linha do zero desenhados na cena."""

    def __init__(self, parent=None):
        super().__init__(QChart(), parent)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.chart().legend().setAlignment(Qt.AlignmentFlag.AlignBottom)
        self._itens: list = []
        self._vivas: list = []          # QAreaSeries não assume a posse das linhas: sem referência, o Python
        self.rotulos_evento: list = []  # as coleta e o gráfico acessa memória liberada (access violation)
        self.eventos: list = []         # (x no eixo, número, evento)
        self.marca = None               # (x no eixo, texto) do ano escolhido
        self.zero = False               # linha do zero (fluxos e saldo)
        self.chart().plotAreaChanged.connect(self.posicionar)

    def limpar(self, titulo: str):
        ch = self.chart()
        ch.removeAllSeries()
        for eixo in ch.axes():
            ch.removeAxis(eixo)
        self._vivas = []
        ch.setTheme(QChart.ChartTheme.ChartThemeDark if isDarkTheme() else QChart.ChartTheme.ChartThemeLight)
        ch.setBackgroundVisible(False)
        ch.setTitle(titulo)
        ch.setMargins(QMargins(6, 6, 6, 6))
        ch.legend().setVisible(True)
        self.eventos, self.marca, self.zero = [], None, False

    def anexar(self, serie, eixo_x, eixo_y):
        self.chart().addSeries(serie)
        serie.attachAxis(eixo_x)
        serie.attachAxis(eixo_y)

    def posicionar(self, *_):
        cena = self.scene()
        for item in self._itens:
            if item.scene() is cena:
                cena.removeItem(item)
        self._itens, self.rotulos_evento = [], []
        ch = self.chart()
        area = ch.plotArea()
        if area.width() <= 0 or not ch.series():
            return
        escuro = isDarkTheme()
        if self.zero:
            y = ch.mapToPosition(QPointF(0, 0)).y()
            if area.top() <= y <= area.bottom():
                self._linha(area.left(), y, area.right(), y, QPen(QColor("#E0E0E0" if escuro else "#1a1a1a"), 1.2))
        # números dos eventos: no topo, linha a linha até não colidir, sempre dentro da plotArea
        cor = QColor("#D0D0D0" if escuro else "#333333")
        ocupados: list[QRectF] = []
        fundo_faixa = area.top()
        for x, numero, e in self.eventos:
            px = ch.mapToPosition(QPointF(x, 0)).x()
            if not area.left() <= px <= area.right():
                continue
            r = QGraphicsSimpleTextItem(str(numero))
            fonte = QFont("Segoe UI", 7, QFont.Weight.DemiBold)
            r.setFont(fonte)
            r.setBrush(cor)
            caixa = r.boundingRect()
            esquerda = min(max(px - caixa.width() / 2, area.left() + 1), area.right() - caixa.width() - 1)
            topo = area.top() + 1
            retangulo = QRectF(esquerda - 1, topo, caixa.width() + 2, caixa.height())
            while any(retangulo.intersects(o) for o in ocupados) and retangulo.bottom() + caixa.height() < area.bottom():
                retangulo.translate(0, caixa.height())
            ocupados.append(retangulo)
            r.setPos(esquerda, retangulo.top())
            r.setToolTip(f"{numero} · {e.rotulo} ({_data(e.data_evento)})\n{e.descricao}")
            r.setZValue(5)
            cena.addItem(r)
            self._itens.append(r)
            self.rotulos_evento.append(r)
            fundo_faixa = max(fundo_faixa, retangulo.bottom())
            self._linha(px, retangulo.bottom(), px, area.bottom(), QPen(QColor("#777777"), 1, Qt.PenStyle.DotLine))
        if self.marca is not None:
            x, texto = self.marca
            px = ch.mapToPosition(QPointF(x, 0)).x()
            if area.left() - 0.5 <= px <= area.right() + 0.5:
                self._linha(px, area.top(), px, area.bottom(), QPen(QColor("#2E86DE"), 1.6))
                if texto:
                    valor = QGraphicsSimpleTextItem(texto)
                    valor.setFont(QFont("Segoe UI", 8, QFont.Weight.DemiBold))
                    valor.setBrush(QColor("#2E86DE"))
                    largura = valor.boundingRect().width()
                    xr = px + 4 if px + 4 + largura < area.right() else px - 4 - largura      # sem corte
                    valor.setPos(max(area.left() + 1, xr), fundo_faixa + 2)
                    valor.setZValue(6)
                    cena.addItem(valor)
                    self._itens.append(valor)

    def _linha(self, x1, y1, x2, y2, caneta):
        linha = QGraphicsLineItem(x1, y1, x2, y2)
        linha.setPen(caneta)
        self.scene().addItem(linha)
        self._itens.append(linha)


# ---------------------------------------------------------------- o componente
class GraficoEstoque(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(2)
        self._grade = QGridLayout()
        self._grade.setContentsMargins(0, 0, 0, 0)
        self._grade.setSpacing(4)
        v.addLayout(self._grade, 1)
        self.vistas = [VistaEstoque(self) for _ in range(3)]
        for vista in self.vistas:
            vista.hide()
        self.legenda_eventos = QLabel()
        self.legenda_eventos.setWordWrap(True)
        self.legenda_eventos.setTextFormat(Qt.TextFormat.RichText)
        self.legenda_eventos.setStyleSheet("font-size:11px; color:%s;" % ("#BDBDBD" if isDarkTheme() else "#555555"))
        v.addWidget(self.legenda_eventos)
        self._serie, self._eventos, self._classe = None, [], None
        self._ano, self.total, self.saldo = None, {}, {}
        self.suprimidas, self._saldo_suprimido, self.dica_fonte = [], set(), ""
        self.modo = MODOS[0]

    def definir_dica(self, texto: str):
        """A dica do gráfico, em cada vista."""
        self.dica_fonte = texto
        for vista in self.vistas:
            vista.setToolTip(texto)

    # compatibilidade: o gráfico principal (o único nos modos de um gráfico)
    def chart(self) -> QChart:
        return self.vistas[0].chart()

    def charts(self) -> list[QChart]:
        return [v.chart() for v in self.vistas if not v.isHidden()]

    def vistas_visiveis(self) -> list[VistaEstoque]:
        return [v for v in self.vistas if not v.isHidden()]

    # ------------------------------------------------------------ entrada
    def mostrar(self, serie: dict, eventos=(), ano: int | None = None, modo: str | None = None,
                classe: str | None = None):
        """`serie` = analise.serie_estoque(...) (já no recorte de `classe`). `modo`: um de MODOS."""
        self.modo = modo or self.modo
        self._serie, self._ano = serie, ano
        self._classe = classe or (next(iter(serie.get("ativas", {}))) if len(serie.get("ativas", {})) == 1 else None)
        anos = serie.get("anos") or []
        ordenados = sorted((e for e in eventos if anos and anos[0] <= e.data_evento.year <= anos[-1]),
                           key=lambda e: e.data_evento)
        self._eventos = [(e.data_evento.year + (e.data_evento.timetuple().tm_yday - 1) / 365, i, e)
                         for i, e in enumerate(ordenados, 1)]
        self.total = {a: self._total_do_ano(serie, a) for a in anos}
        # células do estoque suprimidas pelo k no N1 (None): não se desenham nem se deduzem
        self.suprimidas = sorted((c, a) for c, d in serie.get("ativas", {}).items() for a in anos if d[a] is None)
        # fluxo suprimido (None, k=3 no N1): o saldo vem da variação do estoque, quando ele é visível
        self.saldo = {a: (serie["entradas"][a] - serie["saidas"][a]) if serie["entradas"][a] is not None
                      else (self.total[a] - self.total[anos[i - 1]]
                            if i and self.total[a] is not None and self.total[anos[i - 1]] is not None else None)
                      for i, a in enumerate(anos)} if anos else {}
        self._saldo_suprimido = {a for a, v in self.saldo.items() if v is None}   # 1º ano sem estoque anterior
        self.saldo = {a: v or 0 for a, v in self.saldo.items()}
        if self.modo == MODOS[1]:
            self._arrumar(2, colunas=False)
            self._mostrar_saldo()
        elif self.modo == MODOS[2]:
            self._arrumar(max(1, len(serie.get("ativas", {}))), colunas=True)
            self._mostrar_multiplos()
        else:
            self._arrumar(1, colunas=False)
            self._mostrar_estoque()
        self._legenda_eventos()
        for vista in self.vistas_visiveis():
            vista.posicionar()

    def marcar_ano(self, ano: int | None):
        if self._serie is not None:
            self.mostrar(self._serie, [e for _, _, e in self._eventos], ano=ano, classe=self._classe)

    def _arrumar(self, n: int, colunas: bool):
        for vista in self.vistas:
            self._grade.removeWidget(vista)
            vista.hide()
        for i in range(3):
            self._grade.setRowStretch(i, 0)
            self._grade.setColumnStretch(i, 0)
        altura = {MODOS[1]: 220, MODOS[2]: 260}.get(self.modo, 300)        # O título do eixo Y cabe
        for i, vista in enumerate(self.vistas[:n]):
            linha, coluna = (0, i) if colunas else (i, 0)
            self._grade.addWidget(vista, linha, coluna)
            self._grade.setRowStretch(linha, 1)
            self._grade.setColumnStretch(coluna, 1)
            vista.setMinimumHeight(altura)
            vista.chart().setMargins(QMargins(6, 6, 6, 6))
            vista.show()

    @staticmethod
    def _total_do_ano(serie: dict, ano: int):
        """Soma das classes; com alguma classe suprimida, o total do ano que o serviço mandou (estoque_total,
        travado no cubo) quando a série tem todas as classes; senão None (nunca recalculado por diferença)."""
        valores = [d[ano] for d in serie.get("ativas", {}).values()]
        if all(v is not None for v in valores):
            return sum(valores)
        if len(valores) > 1:
            return serie.get("estoque_total", {}).get(ano)
        return None

    def _rotulo_classe(self) -> str:
        return _rotulo(self._classe) if self._classe else TODAS

    def _marca_texto(self) -> str:
        if self._ano in self.total:
            return f"{self._ano}: {_contagem(self.total[self._ano])}"
        return ""

    def _ano_titulo(self) -> int | None:
        anos = self._serie.get("anos") or []
        return self._ano if self._ano in self.total else (anos[-1] if anos else None)

    # ------------------------------------------------------------ estoque (áreas empilhadas, sem linha de total)
    def _mostrar_estoque(self):
        vista, serie = self.vistas[0], self._serie
        ano_t = self._ano_titulo()
        cabeca = f"ESTOQUE ATIVO · {_rotulo(self._classe).upper()}" if self._classe else "ESTOQUE ATIVO POR CLASSE"
        total_t = self.total.get(ano_t)
        vista.limpar(cabeca + (f" · {ano_t}: {_contagem(total_t)}" + (" ATIVAS" if total_t is not None else "")
                               if ano_t is not None else ""))
        anos = serie.get("anos") or []
        if not anos:
            return
        eixo_x, eixo_y = QValueAxis(), QValueAxis()
        eixo_anos(eixo_x, anos[0], anos[-1], 2)
        eixo_y.setTitleText("ativas")
        vista.chart().addAxis(eixo_x, Qt.AlignmentFlag.AlignBottom)
        vista.chart().addAxis(eixo_y, Qt.AlignmentFlag.AlignLeft)
        # pilha: uma célula suprimida (None) deixa um vão na sua classe e nas de cima (a base delas é desconhecida);
        # nada é desenhado no lugar, nem deduzido do total
        base = {a: 0 for a in anos}
        for classe in sorted(serie["ativas"]):
            valores, pontos = serie["ativas"][classe], []
            for a in anos:
                if base[a] is None or valores[a] is None:
                    base[a] = None
                    pontos.append(None)
                else:
                    pontos.append((a, base[a], base[a] + valores[a]))
                    base[a] += valores[a]
            for i, trecho in enumerate(segmentos(pontos)):
                inferior, superior = QLineSeries(), QLineSeries()
                if len(trecho) == 1:                         # ano isolado entre dois vãos: uma faixa estreita
                    a, baixo, alto = trecho[0]
                    trecho = [(a - 0.3, baixo, alto), (a + 0.3, baixo, alto)]
                for x, baixo, alto in trecho:
                    inferior.append(x, baixo)
                    superior.append(x, alto)
                vista._vivas += [superior, inferior]
                area = self._area(vista, superior, inferior, classe, eixo_x, eixo_y, 170)
                if i:                                         # um nome por classe na legenda
                    for marcador in vista.chart().legend().markers(area):
                        marcador.setVisible(False)
        alto = max([v for v in base.values() if v is not None] + [v for v in self.total.values() if v is not None]
                   or [0])
        eixo_redondo(eixo_y, 0, alto * 1.3 or 5, intervalos=7)
        vista.eventos = list(self._eventos)
        vista.marca = (self._ano, self._marca_texto()) if self._ano in self.total else None

    def _area(self, vista, superior, inferior, classe, eixo_x, eixo_y, alfa):
        area = QAreaSeries(superior, inferior) if inferior is not None else QAreaSeries(superior)
        area.setName(_rotulo(classe))                       # o rótulo do vocabulário
        cor = QColor(CORES.get(classe, "#888888"))
        cor.setAlpha(alfa)
        area.setBrush(cor)
        area.setPen(QPen(Qt.PenStyle.NoPen) if inferior is not None else QPen(QColor(CORES.get(classe, "#888")), 1.4))
        area.hovered.connect(lambda ponto, dentro, c=classe: self._mostrar_dica(dentro, self.dica_estoque(
            round(ponto.x()), c)))
        vista.anexar(area, eixo_x, eixo_y)
        return area

    # ------------------------------------------------------------ small multiples
    def _mostrar_multiplos(self):
        serie = self._serie
        anos = serie.get("anos") or []
        ano_t = self._ano_titulo()
        classes = sorted(serie.get("ativas", {})) or [None]
        for vista, classe in zip(self.vistas, classes):
            n = serie["ativas"][classe][ano_t] if classe and ano_t is not None else 0
            vista.limpar(f"{_rotulo(classe).upper() if classe else 'SEM DADOS'}"
                         + (f" · {ano_t}: {_contagem(n)}" if classe else ""))
            vista.chart().legend().setVisible(False)          # o título já diz a classe
            if not anos or classe is None:
                continue
            eixo_x, eixo_y = QValueAxis(), QValueAxis()
            eixo_anos(eixo_x, anos[0], anos[-1], 5)
            eixo_y.setTitleText("ativas")
            vista.chart().addAxis(eixo_x, Qt.AlignmentFlag.AlignBottom)
            vista.chart().addAxis(eixo_y, Qt.AlignmentFlag.AlignLeft)
            valores = serie["ativas"][classe]
            for trecho in segmentos([(a, valores[a]) if valores[a] is not None else None for a in anos]):
                if len(trecho) == 1:                         # ano isolado entre dois vãos
                    a, v = trecho[0]
                    trecho = [(a - 0.3, v), (a + 0.3, v)]
                superior = QLineSeries()
                for x, v in trecho:
                    superior.append(x, v)
                vista._vivas.append(superior)
                self._area(vista, superior, None, classe, eixo_x, eixo_y, 150)
            visiveis = [v for v in valores.values() if v is not None]
            eixo_redondo(eixo_y, 0, max(visiveis, default=0) * 1.35 or 5, intervalos=5)
            vista.eventos = list(self._eventos)
            if self._ano in self.total:
                vista.marca = (self._ano, f"{self._ano}: {_contagem(valores[self._ano])}")

    # ------------------------------------------------------------ saldo: fluxos e saldo em dois gráficos
    def _mostrar_saldo(self):
        serie = self._serie
        anos = serie.get("anos") or []
        fluxos, liquido = self.vistas[0], self.vistas[1]
        sufixo = f" · {_rotulo(self._classe).upper()}" if self._classe else ""
        fluxos.limpar("ENTRADAS E SAIDAS POR ANO" + sufixo)
        liquido.limpar("SALDO ANUAL (ENTRADAS - SAIDAS)" + sufixo)
        if not anos:
            return
        x0 = anos[0]
        rotulos = [str(a) if (a - x0) % 2 == 0 else " " * (a - x0) for a in anos]      # categorias distintas
        # (a) fluxos: entradas para cima, saídas para baixo, eixo simétrico com tick no 0
        entradas, saidas = QBarSet("ENTRADAS"), QBarSet("SAIDAS")
        entradas.append([serie["entradas"][a] or 0 for a in anos])         # suprimido: sem barra (dica explica)
        saidas.append([-(serie["saidas"][a] or 0) for a in anos])
        barras = QStackedBarSeries()
        barras.append(entradas)
        barras.append(saidas)
        eixo_x, eixo_y = QBarCategoryAxis(), QValueAxis()
        eixo_x.append(rotulos)
        eixo_y.setTitleText("pendências por ano")
        fluxos.chart().addSeries(barras)            # antes dos eixos: o tema não repinta as cores depois
        fluxos.chart().addAxis(eixo_x, Qt.AlignmentFlag.AlignBottom)
        fluxos.chart().addAxis(eixo_y, Qt.AlignmentFlag.AlignLeft)
        barras.attachAxis(eixo_x)
        barras.attachAxis(eixo_y)
        entradas.setColor(QColor(COR_ENTRADAS))
        saidas.setColor(QColor(COR_SAIDAS))
        alto = max([v for v in list(serie["entradas"].values()) + list(serie["saidas"].values()) if v] or [1])
        eixo_redondo(eixo_y, -alto * 1.3, alto * 1.3, intervalos=6, simetrico=True)
        barras.hovered.connect(lambda dentro, i, conjunto: self._mostrar_dica(
            dentro, self.dica_fluxo(anos[i], conjunto.label()) if 0 <= i < len(anos) else ""))
        # (b) saldo, na escala dele
        sobe, cai = QBarSet("SALDO POSITIVO (ESTOQUE SOBE)"), QBarSet("SALDO NEGATIVO (ESTOQUE CAI)")
        sobe.append([max(0, self.saldo[a]) for a in anos])
        cai.append([min(0, self.saldo[a]) for a in anos])
        barras_s = QStackedBarSeries()
        barras_s.append(sobe)
        barras_s.append(cai)
        eixo_xs, eixo_ys = QBarCategoryAxis(), QValueAxis()
        eixo_xs.append(rotulos)
        eixo_ys.setTitleText("saldo por ano")
        liquido.chart().addSeries(barras_s)
        liquido.chart().addAxis(eixo_xs, Qt.AlignmentFlag.AlignBottom)
        liquido.chart().addAxis(eixo_ys, Qt.AlignmentFlag.AlignLeft)
        barras_s.attachAxis(eixo_xs)
        barras_s.attachAxis(eixo_ys)
        sobe.setColor(QColor(COR_ENTRADAS))
        cai.setColor(QColor(COR_SAIDAS))
        menor, maior = min(0, *self.saldo.values()), max(0, *self.saldo.values())
        folga = max(1, (maior - menor) * 0.3)
        eixo_redondo(eixo_ys, menor - (folga if menor < 0 else 0), maior + folga, intervalos=5)
        barras_s.hovered.connect(lambda dentro, i, _c: self._mostrar_dica(
            dentro, self.dica_saldo(anos[i]) if 0 <= i < len(anos) else ""))
        # eventos e ano: x no eixo de categorias = índice do ano (o ano ocupa de i - 0,5 a i + 0,5)
        for vista in (fluxos, liquido):
            vista.zero = True
            vista.eventos = [(x - x0 - 0.5, n, e) for x, n, e in self._eventos]
            if self._ano is not None and anos[0] <= self._ano <= anos[-1]:
                vista.marca = (self._ano - x0, "")
        if fluxos.marca is not None:
            a = self._ano
            fluxos.marca = (fluxos.marca[0], f"{a}: {_contagem(serie['entradas'][a])} entradas, "
                                             f"{_contagem(serie['saidas'][a])} saídas")
            liquido.marca = (liquido.marca[0], f"{a}: saldo " + (SUPRIMIDO if a in self._saldo_suprimido
                                                                 else _sinal(self.saldo[a])))
        self._alinhar([fluxos, liquido], [eixo_y, eixo_ys])

    @staticmethod
    def _alinhar(vistas, eixos):
        """Mesma margem à esquerda nos dois gráficos (rótulos de largura diferente): o eixo X fica alinhado."""
        larguras = []
        for eixo in eixos:
            metrica = QFontMetricsF(eixo.labelsFont())
            passo, valor, maior = eixo.tickInterval(), eixo.min(), 0.0
            while valor <= eixo.max() + 1e-9:
                maior = max(maior, metrica.horizontalAdvance(eixo.labelFormat() % valor))
                valor += passo
            larguras.append(maior)
        topo = max(larguras)
        for vista, largura in zip(vistas, larguras):
            vista.chart().setMargins(QMargins(6 + round(topo - largura), 6, 6, 6))

    # ------------------------------------------------------------ dicas
    def dica_estoque(self, ano: int, classe: str) -> str:
        if not self._serie or ano not in self.total or classe not in self._serie["ativas"]:
            return ""
        n, total = self._serie["ativas"][classe][ano], self.total[ano]
        nome = _rotulo(classe)
        if n is None:
            return f"{ano} · {nome}: Suprimido, oculto para proteger poucos casos"
        if total is None:
            return f"{ano} · {nome}: {_numero(n)} ativas"
        return f"{ano} · {nome}: {_numero(n)} ativas ({100 * n / total:.0f}% do estoque de {_numero(total)})" \
            if total else f"{ano} · {nome}: 0 ativas"

    def dica_fluxo(self, ano: int, rotulo: str) -> str:
        chave = "entradas" if rotulo.startswith("ENTRADAS") else "saidas"
        n, estoque = self._serie[chave][ano], self.total.get(ano) or 0
        if n is None:
            return f"{ano} · {self._rotulo_classe()} · {rotulo}: Suprimido, oculto para proteger poucos casos"
        pct = f" ({100 * n / estoque:.0f}% do estoque ativo no fim do ano)" if estoque else ""
        return f"{ano} · {self._rotulo_classe()} · {rotulo}: {_numero(n)}{pct}"

    def dica_saldo(self, ano: int) -> str:
        anterior = self.total.get(ano - 1)
        caminho = f" (estoque {_numero(anterior)} para {_numero(self.total[ano])})" \
            if anterior is not None and self.total.get(ano) is not None else ""
        if ano in getattr(self, "_saldo_suprimido", ()):
            return f"{ano} · {self._rotulo_classe()} · saldo suprimido, oculto para proteger poucos casos"
        return f"{ano} · {self._rotulo_classe()} · saldo {_sinal(self.saldo[ano])}{caminho}"

    def _mostrar_dica(self, dentro: bool, texto: str):
        if dentro and texto:
            QToolTip.showText(QCursor.pos(), texto)
        else:
            QToolTip.hideText()

    # ------------------------------------------------------------ legenda de eventos
    def texto_suprimidas(self) -> str:
        """As células do estoque que o k escondeu, por classe, em faixas de anos (o gráfico deixa o vão)."""
        if not self.suprimidas or self.modo == MODOS[1]:
            return ""
        por_classe: dict[str, list[int]] = {}
        for classe, ano in self.suprimidas:
            por_classe.setdefault(classe, []).append(ano)
        partes = []
        for classe, anos in por_classe.items():
            faixas, inicio, anterior = [], anos[0], anos[0]
            for atual in anos[1:] + [None]:
                if atual is None or atual != anterior + 1:
                    faixas.append(str(inicio) if inicio == anterior else f"{inicio} a {anterior}")
                    inicio = atual
                anterior = atual
            partes.append(f"{_rotulo(classe)} em {', '.join(faixas)}")
        return "Estoque oculto para proteger poucos casos, sem desenho: " + "; ".join(partes)

    def _legenda_eventos(self):
        from html import escape
        suprimidas = self.texto_suprimidas()
        if not self._eventos and not suprimidas:
            self.legenda_eventos.setText("")
            self.legenda_eventos.hide()
            return
        partes = []
        for _, n, e in self._eventos:
            texto = f"<b>{n}</b> {escape(e.rotulo)} ({_data(e.data_evento)})"
            partes.append(texto)
        linhas = (["Eventos: " + " · ".join(partes)] if partes else []) + ([escape(suprimidas)] if suprimidas else [])
        self.legenda_eventos.setText("<br>".join(linhas))
        self.legenda_eventos.show()
