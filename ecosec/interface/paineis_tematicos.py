"""Painéis temáticos do N1, do N3 e da UF do N2 (padrão SINIR+).

Em vez de um dashboard só, quatro painéis navegáveis sobre os mesmos filtros (classe e ano):
  - Passivo por classe: um cartão por classe (ativas e quantidade na unidade da classe; unidades nunca se
    somam) e o KPI-04 em small multiples (um gráfico por classe, faixas de idade no eixo X);
  - Passivo por UF: o coroplético com a legenda de quintis (painel_n1.py) e, ao lado, KPI-03 e KPI-03b
    pareados por UF no mesmo eixo de 0 a 100%;
  - Custo do passivo: KPI-05 em barras empilhadas por categoria EEA, por classe ou por rota, e os quatro
    cartões de responsabilidade financeira que somam o total;
  - Evolução do encerramento: KPI-01 em degraus por classe, KPI-02 por ano (o ano corrente marcado parcial)
    e o estoque ativo (GraficoEstoque).

Os títulos dizem o NOME do indicador (acervo/vocabulario.py); o código KPI-xx fica só na
dica. O N1 não tem o painel de custo nem o cartão de custo (N1 sem dado financeiro); o N2 continua com eles.

A tela só MOSTRA o que o serviço devolve. None é número suprimido pelo k do N1 (primária ou complementar):
aparece SUPRIMIDO, nunca 0 e nunca recalculado aqui a partir de outros números. As dicas explicam o número
em linguagem simples, sem fonte, nível nem corte.
Cada gráfico tem um eixo vertical, eixo de valor com unidade e ticks redondos (eixo_redondo).
"""
from PySide6.QtCharts import (QBarCategoryAxis, QBarSeries, QBarSet, QChart, QChartView, QHorizontalBarSeries,
                              QHorizontalStackedBarSeries, QLineSeries, QStackedBarSeries, QValueAxis)
from PySide6.QtCore import QMargins, QPointF, Qt, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QPainter, QPen
from PySide6.QtWidgets import QGraphicsSimpleTextItem, QHBoxLayout, QToolTip, QVBoxLayout, QWidget

from ecosec.acervo import custos, formatos, regras, vocabulario
from ecosec.interface.componentes.grafico_estoque import COR_SAIDAS, CORES, eixo_redondo
from ecosec.interface.componentes.simbologia import COR_IDENTIDADE
from ecosec.interface.estilo import COR_DESTAQUE, cor_texto_secundario
from ecosec.interface.fluent import CaptionLabel, SegmentedWidget, SimpleCardWidget, StrongBodyLabel, isDarkTheme

SUPRIMIDO = "SUPRIMIDO"
NAO_ATINGIDO = "não atingido"
TODAS = "TODAS"                                       # analise.TODAS: a curva de todas as classes
CLASSES = ("AREA CONTAMINADA", "CLASSE I NBR 10004", "REJEITO RADIOATIVO CNEN")
ROTULO_CLASSE = {**vocabulario.ROTULO_CLASSE, TODAS: "Todas as classes"}
NOME_KPI = vocabulario.ROTULO_KPI                     # "KPI-03" -> "Casos além do prazo legal"
PAINEIS = ("classe", "uf", "custo", "encerramento")
TITULO_PAINEL = {"classe": "Passivo por classe", "uf": "Passivo por UF", "custo": "Custo do passivo",
                 "encerramento": "Evolução do encerramento"}
KPIS_DO_PAINEL = {"classe": ("KPI-04",), "uf": ("KPI-03", "KPI-03b"), "custo": ("KPI-05",),
                  "encerramento": ("KPI-01", "KPI-02")}
CATEGORIAS = tuple(custos.CATEGORIAS_EEA)
ROTULO_CATEGORIA = vocabulario.ROTULO_CATEGORIA_CUSTO
# a paleta dos gráficos (Tableau 10): as três primeiras são as classes (CORES); as categorias seguem a sequência
COR_CATEGORIA = {"INVESTIGACAO": "#76b7b2", "REMEDIACAO": "#59a14f", "MONITORAMENTO": "#edc948",
                 "DISPOSICAO": "#b07aa1"}
RESPONSABILIDADES = (regras.COBRAVEL, regras.PUBLICO, regras.INFRAESTRUTURA, regras.FISCALIZACAO)
ROTULO_RESPONSABILIDADE = vocabulario.ROTULO_RESPONSABILIDADE
COR_KPI03, COR_KPI03B = COR_IDENTIDADE["ALTO"], COR_IDENTIDADE["MEDIO"]   # as de ALTO e MEDIO do gráfico de risco
COR_SUPRIMIDO = "#9E9E9E"


# ---------------------------------------------------------------- textos
def contagem(n) -> str:
    return SUPRIMIDO if n is None else formatos.inteiro(n)


def _ativas(n) -> str:
    """Valor de cartão: "1.055 ativas", ou só SUPRIMIDO (nunca "0 ativas")."""
    return SUPRIMIDO if n is None else f"{formatos.inteiro(n)} ativas"


def anos(valor, ausente: str = NAO_ATINGIDO) -> str:
    return ausente if valor is None else f"{formatos.numero(valor, 1)} anos"


def texto_valor(valor, unidade: str, observacao: str = "") -> str:
    """Valor de um KPI com a unidade (formatos.py). None: SUPRIMIDO, ou "não atingido" quando o serviço diz."""
    if valor is None:
        return NAO_ATINGIDO if NAO_ATINGIDO in observacao else SUPRIMIDO
    if unidade == "anos":
        return anos(valor)
    if unidade == "%":
        return formatos.percentual(valor)
    if unidade == "R$":
        return formatos.custo(valor)
    return formatos.inteiro(valor)


def dica_fonte(fonte: str, nivel_minimo: int, corte, observacao: str = "") -> str:
    """A dica de um gráfico: só a explicação para quem lê. A origem técnica (função, nível, corte) não aparece mais
    na tela."""
    return observacao.strip()


def dica_kpi(kpi) -> str:
    """O nome, a definição e a conta do vocabulário, e a observação do cartão."""
    return "\n".join(x for x in (vocabulario.dica(kpi.id, "kpi"), kpi.observacao) if x)


def _nota_k(k: int) -> str:
    return f". Totais pequenos ficam ocultos ({SUPRIMIDO}) para proteger poucos casos" if k else ""


# ---------------------------------------------------------------- cartões
class CartaoValor(SimpleCardWidget):
    """Um número: rótulo em cima, valor, detalhe embaixo. A dica vale para o cartão inteiro."""

    def __init__(self, rotulo: str = "", cor: str | None = None, parent=None):
        super().__init__(parent)
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 10, 0)
        h.setSpacing(8)
        self.faixa = QWidget()                                 # cor da classe, ou o destaque do painel aberto
        self.faixa.setFixedWidth(4)
        h.addWidget(self.faixa)
        v = QVBoxLayout()
        v.setContentsMargins(0, 7, 0, 7)
        v.setSpacing(1)
        self.rotulo = CaptionLabel(rotulo)
        self.rotulo.setWordWrap(True)
        self.rotulo.setStyleSheet(f"color:{cor_texto_secundario()}; font-weight:600;")
        self.valor = StrongBodyLabel()
        fonte = self.valor.font()
        fonte.setPixelSize(18)
        self.valor.setFont(fonte)
        self.detalhe = CaptionLabel()
        self.detalhe.setWordWrap(True)
        self.detalhe.setStyleSheet(f"color:{cor_texto_secundario()};")
        self.detalhe.hide()
        v.addWidget(self.rotulo)
        v.addWidget(self.valor)
        v.addWidget(self.detalhe)
        h.addLayout(v, 1)
        self.cor = cor
        self.destacado = False
        self._pintar_faixa()

    def definir(self, valor: str, detalhe: str = "", dica: str = ""):
        self.valor.setText(valor)
        self.valor.setTextColor(QColor(COR_SUPRIMIDO if valor == SUPRIMIDO else "#1A1A1A"),
                                QColor(COR_SUPRIMIDO if valor == SUPRIMIDO else "#FFFFFF"))
        self.detalhe.setText(detalhe)
        self.detalhe.setVisible(bool(detalhe))
        self.setToolTip(dica)

    def destacar(self, ligado: bool):
        self.destacado = ligado
        self._pintar_faixa()

    def _pintar_faixa(self):
        cor = COR_DESTAQUE if self.destacado else (self.cor or "transparent")
        self.faixa.setStyleSheet(f"background:{cor}; border-radius:2px;")

    def textos(self) -> list[str]:
        return [self.rotulo.text(), self.valor.text(), self.detalhe.text()]


class CartaoKPI(CartaoValor):
    def __init__(self, kpi_id: str, parent=None):
        super().__init__(NOME_KPI.get(kpi_id, kpi_id), parent=parent)
        self.kpi_id, self.kpi = kpi_id, None

    def definir_kpi(self, kpi):
        self.kpi = kpi
        self.rotulo.setText(NOME_KPI.get(kpi.id, kpi.nome))           # o nome; o código vai na dica
        self.definir(texto_valor(kpi.valor, kpi.unidade, kpi.observacao), dica=dica_kpi(kpi))


class FaixaKPIs(QWidget):
    """Um cartão por KPI do catálogo, no topo da área de painéis; os do painel aberto ficam destacados. Sem
    `financeiro` (o N1), não há o cartão de custo (KPI-05)."""
    IDS = ("KPI-01", "KPI-02", "KPI-03", "KPI-03b", "KPI-04", "KPI-05")
    IDS_SEM_CUSTO = IDS[:-1]

    def __init__(self, financeiro: bool = True, parent=None):
        super().__init__(parent)
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)
        self.cartoes = {i: CartaoKPI(i) for i in (self.IDS if financeiro else self.IDS_SEM_CUSTO)}
        for cartao in self.cartoes.values():
            h.addWidget(cartao, 1)
        self.destacados: set[str] = set()
        self.kpis: list = []

    def definir(self, kpis):
        self.kpis = list(kpis)
        for kpi in self.kpis:
            if kpi.id in self.cartoes:
                self.cartoes[kpi.id].definir_kpi(kpi)

    def destacar(self, ids):
        self.destacados = set(ids)
        for i, cartao in self.cartoes.items():
            cartao.destacar(i in self.destacados)


# ---------------------------------------------------------------- gráficos
def _tema(ch: QChart, titulo: str):
    ch.removeAllSeries()
    for eixo in ch.axes():
        ch.removeAxis(eixo)
    ch.setTheme(QChart.ChartTheme.ChartThemeDark if isDarkTheme() else QChart.ChartTheme.ChartThemeLight)
    ch.setBackgroundVisible(False)
    ch.setMargins(QMargins(6, 6, 6, 6))
    ch.setTitle(titulo)


def _mostrar_dica(dentro: bool, texto: str):
    if dentro and texto:
        QToolTip.showText(QCursor.pos(), texto)
    else:
        QToolTip.hideText()


class GraficoBarras(QChartView):
    """Barras de uma grandeza: um eixo de categorias e um eixo de valor (unidade no título, passo redondo).
    Horizontal ou vertical, agrupado ou empilhado. None = SUPRIMIDO: nada é desenhado no lugar (a barra fica
    vazia) e o rótulo da categoria diz SUPRIMIDO. Na horizontal, a primeira categoria fica em cima."""

    def __init__(self, horizontal: bool = False, empilhado: bool = False, parent=None):
        super().__init__(QChart(), parent)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.chart().legend().setAlignment(Qt.AlignmentFlag.AlignBottom)
        self.horizontal, self.empilhado = horizontal, empilhado
        self.categorias: list[str] = []                 # na ordem de quem chamou
        self.valores: dict[str, list] = {}              # série -> valores (None = suprimido), na mesma ordem
        self.conjuntos: dict[str, QBarSet] = {}
        self.textos_rotulo: list = []                   # (texto, âncora) ou None, por categoria
        self.textos_barra: dict = {}                    # (categoria, série) -> texto no lugar da barra (SUPRIMIDO)
        self.nomes: list[str] = []
        self.largura = 0.7
        self.rotulos: list[QGraphicsSimpleTextItem] = []
        self.dica_barra = None                          # (índice da categoria, nome da série) -> texto
        self._serie = None
        self.chart().plotAreaChanged.connect(self._posicionar)

    def _interno(self, i: int) -> int:
        """Índice no eixo (na horizontal o Qt desenha a primeira categoria embaixo: a ordem é invertida)."""
        return len(self.categorias) - 1 - i if self.horizontal else i

    def mostrar(self, titulo: str, categorias, series, eixo: str, *, maximo: float | None = None,
                intervalos: int = 5, inteiro: bool = True, rotulos=None, titulo_categorias: str = "",
                legenda: bool = True, largura: float = 0.7, rotulos_categoria=None, rotulos_barra=None,
                angulo: int = 0, fonte_categorias: int | None = None):
        """`series`: [(nome, cor, [valor ou None por categoria])]; `rotulos`: [(texto, valor onde ancorar) ou None]
        por categoria; `rotulos_barra`: {(categoria, série): texto} escrito no lugar da barra (barras agrupadas: a
        barra suprimida que não foi desenhada); `rotulos_categoria`: o texto no eixo (padrão: as categorias)."""
        self.categorias = list(categorias)
        self.valores = {nome: list(valores) for nome, _, valores in series}
        self.nomes, self.largura = [nome for nome, _, _ in series], largura
        self.textos_rotulo = list(rotulos) if rotulos is not None else [None] * len(self.categorias)
        self.textos_barra = dict(rotulos_barra or {})
        ch = self.chart()
        _tema(ch, titulo)
        classe = ((QHorizontalStackedBarSeries if self.empilhado else QHorizontalBarSeries) if self.horizontal
                  else (QStackedBarSeries if self.empilhado else QBarSeries))
        serie = classe()
        ordem = list(range(len(self.categorias)))
        if self.horizontal:
            ordem.reverse()
        self.conjuntos = {}
        for nome, cor, valores in series:
            conjunto = QBarSet(nome)
            conjunto.append([0.0 if valores[i] is None else float(valores[i]) for i in ordem])
            serie.append(conjunto)
            self.conjuntos[nome] = conjunto
        serie.setBarWidth(largura)
        ch.addSeries(serie)                             # antes dos eixos: o tema não repinta as cores depois
        for nome, cor, _ in series:
            self.conjuntos[nome].setColor(QColor(cor))
            self.conjuntos[nome].setBorderColor(QColor(cor))
        eixo_cat, eixo_val = QBarCategoryAxis(), QValueAxis()
        textos = list(rotulos_categoria) if rotulos_categoria is not None else self.categorias
        eixo_cat.append([textos[i] for i in ordem])
        if titulo_categorias:
            eixo_cat.setTitleText(titulo_categorias)
        if angulo:
            eixo_cat.setLabelsAngle(angulo)
        if fonte_categorias:
            eixo_cat.setLabelsFont(QFont("Segoe UI", fonte_categorias))
        eixo_val.setTitleText(eixo)
        if maximo is None:
            if self.empilhado:
                topos = [sum(v[i] or 0 for v in self.valores.values()) for i in range(len(self.categorias))]
            else:
                topos = [v or 0 for vs in self.valores.values() for v in vs]
            maximo = max(topos, default=0) * 1.18
        eixo_redondo(eixo_val, 0, maximo or 1, intervalos=intervalos, inteiro=inteiro)
        ch.addAxis(eixo_cat, Qt.AlignmentFlag.AlignLeft if self.horizontal else Qt.AlignmentFlag.AlignBottom)
        ch.addAxis(eixo_val, Qt.AlignmentFlag.AlignBottom if self.horizontal else Qt.AlignmentFlag.AlignLeft)
        serie.attachAxis(eixo_cat)
        serie.attachAxis(eixo_val)
        ch.legend().setVisible(legenda and len(series) > 1)
        serie.hovered.connect(lambda dentro, i, conjunto: _mostrar_dica(dentro, self.dica(self._interno(i),
                                                                                         conjunto.label())))
        self._serie = serie
        self._posicionar()

    def dica(self, i: int, nome: str) -> str:
        if self.dica_barra is None or not 0 <= i < len(self.categorias):
            return ""
        return self.dica_barra(i, nome)

    def _posicionar(self, *_):
        cena = self.scene()
        for r in self.rotulos:
            if r.scene() is cena:
                cena.removeItem(r)
        self.rotulos = []
        ch = self.chart()
        area = ch.plotArea()
        if self._serie is None or area.width() <= 0:
            return
        escuro = isDarkTheme()
        n = max(1, len(self.categorias))
        largura_cat = area.width() / n if not self.horizontal else area.height() / n
        for i, rotulo in enumerate(self.textos_rotulo):
            if rotulo is None:
                continue
            texto, ancora = rotulo
            j = self._interno(i)
            ponto = ch.mapToPosition(QPointF(ancora, j) if self.horizontal else QPointF(j, ancora), self._serie)
            r = QGraphicsSimpleTextItem(texto)
            r.setFont(QFont("Segoe UI", 8, QFont.Weight.DemiBold))
            r.setBrush(QColor(COR_SUPRIMIDO) if texto == SUPRIMIDO else QColor("#F2F2F2" if escuro else "#1a1a1a"))
            caixa = r.boundingRect()
            if self.horizontal:
                x = ponto.x() + 4
                if x + caixa.width() > area.right():                     # barra longa: o texto entra na barra
                    x = ponto.x() - caixa.width() - 4
                    r.setBrush(QColor("#FFFFFF"))
                r.setPos(max(area.left() + 2, x), ponto.y() - caixa.height() / 2)
            elif caixa.width() + 2 > largura_cat:                       # coluna estreita: o texto sobe na vertical
                r.setRotation(-90)
                y = ponto.y() - 3
                if y - caixa.width() < area.top():
                    y = area.top() + caixa.width() + 2
                r.setPos(ponto.x() - caixa.height() / 2, y)
            else:
                y = ponto.y() - caixa.height() - 2
                if y < area.top():
                    y = ponto.y() + 2
                r.setPos(ponto.x() - caixa.width() / 2, y)
            r.setZValue(5)
            cena.addItem(r)
            self.rotulos.append(r)
        m = max(1, len(self.nomes))
        for (i, nome), texto in self.textos_barra.items():
            if nome not in self.nomes:
                continue
            j = self._interno(i)
            deslocamento = (-self.largura / 2 + self.largura / m * (self.nomes.index(nome) + 0.5)
                            if not self.empilhado else 0.0)
            ponto = ch.mapToPosition(QPointF(0, j + deslocamento) if self.horizontal
                                     else QPointF(j + deslocamento, 0), self._serie)
            r = QGraphicsSimpleTextItem(texto)
            r.setFont(QFont("Segoe UI", 7, QFont.Weight.DemiBold))
            r.setBrush(QColor(COR_SUPRIMIDO))
            caixa = r.boundingRect()
            if self.horizontal:
                r.setPos(area.left() + 3, ponto.y() - caixa.height() / 2)
            else:
                r.setRotation(-90)
                r.setPos(ponto.x() - caixa.height() / 2, area.bottom() - 3)
            r.setZValue(5)
            cena.addItem(r)
            self.rotulos.append(r)


class GraficoCurva(QChartView):
    """KPI-01: fração ainda ativa (%) por anos desde a identificação, uma curva em DEGRAUS por classe."""

    def __init__(self, parent=None):
        super().__init__(QChart(), parent)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.chart().legend().setAlignment(Qt.AlignmentFlag.AlignBottom)
        self.linhas: dict[str, QLineSeries] = {}
        self.pontos: dict[str, list] = {}

    def mostrar(self, titulo: str, curvas: dict):
        ch = self.chart()
        _tema(ch, titulo)
        self.linhas, self.pontos = {}, {}
        fim = 1.0
        for chave in [c for c in CLASSES if c in curvas] + ([TODAS] if TODAS in curvas else []):
            curva = curvas[chave]
            if not curva.pontos:
                continue
            degraus = [(curva.pontos[0][0], 100 * curva.pontos[0][1])]
            for t, s in curva.pontos[1:]:
                degraus.append((t, degraus[-1][1]))                     # fica no nível até o próximo t
                degraus.append((t, 100 * s))                            # e cai
            linha = QLineSeries()
            linha.setName(ROTULO_CLASSE[chave])
            for t, y in degraus:
                linha.append(t, y)
            ch.addSeries(linha)
            cor = QColor(CORES.get(chave, "#BDBDBD" if isDarkTheme() else "#555555"))
            caneta = QPen(cor, 2.0 if chave != TODAS else 1.6)
            if chave == TODAS:
                caneta.setStyle(Qt.PenStyle.DashLine)
            linha.setPen(caneta)
            linha.hovered.connect(lambda ponto, dentro, c=chave: _mostrar_dica(dentro, self.dica(c, ponto.x())))
            self.linhas[chave], self.pontos[chave] = linha, degraus
            fim = max(fim, degraus[-1][0])
        eixo_x, eixo_y = QValueAxis(), QValueAxis()
        eixo_x.setTitleText("anos desde a identificação")
        eixo_y.setTitleText("fração ainda ativa (%)")
        eixo_redondo(eixo_x, 0, fim, intervalos=6)
        eixo_redondo(eixo_y, 0, 100, intervalos=5)
        ch.addAxis(eixo_x, Qt.AlignmentFlag.AlignBottom)
        ch.addAxis(eixo_y, Qt.AlignmentFlag.AlignLeft)
        for linha in self.linhas.values():
            linha.attachAxis(eixo_x)
            linha.attachAxis(eixo_y)
        ch.legend().setVisible(True)

    def dica(self, chave: str, t: float) -> str:
        degraus = self.pontos.get(chave) or []
        nivel = next((y for x, y in reversed(degraus) if x <= t + 1e-9), None)
        if nivel is None:
            return ""
        return f"{ROTULO_CLASSE[chave]}: {formatos.numero(max(0.0, t), 1)} anos desde a identificação · " \
               f"{formatos.percentual(nivel)} ainda ativas"


# ---------------------------------------------------------------- painéis
class PainelTematico(QWidget):
    chave = ""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName(f"painel_{self.chave}")
        self.setStyleSheet(f"#painel_{self.chave} {{ background: transparent; }}")
        self.KPIS = KPIS_DO_PAINEL[self.chave]
        self.dados = None

    def graficos(self) -> list:
        return []

    def cartoes(self) -> list:
        return []

    @staticmethod
    def _explicacao(texto: str) -> CaptionLabel:
        rotulo = CaptionLabel(texto)
        rotulo.setWordWrap(True)
        rotulo.setStyleSheet(f"color:{cor_texto_secundario()};")
        return rotulo


class PainelPorClasse(PainelTematico):
    """Cartões por classe (ativas e quantidade na unidade da classe) e o KPI-04 em small multiples."""
    chave = "classe"

    def __init__(self, parent=None):
        super().__init__(parent)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 4, 8, 4)
        v.setSpacing(8)
        linha = QHBoxLayout()
        linha.setSpacing(8)
        self.cartao_total = CartaoValor("TODAS AS CLASSES")
        linha.addWidget(self.cartao_total, 1)
        self.cartoes_classe = {c: CartaoValor(ROTULO_CLASSE[c], CORES[c]) for c in CLASSES}
        for cartao in self.cartoes_classe.values():
            linha.addWidget(cartao, 1)
        v.addLayout(linha)
        grade = QHBoxLayout()
        grade.setSpacing(6)
        self.multiplos = {c: GraficoBarras() for c in CLASSES}
        for grafico in self.multiplos.values():
            grafico.setMinimumHeight(290)
            grade.addWidget(grafico, 1)
        v.addLayout(grade, 1)
        v.addWidget(self._explicacao(
            "Quantidade na unidade de cada classe (t ou m³): as unidades não se somam, por isso o cartão de todas as "
            f"classes traz só a contagem. {NOME_KPI['KPI-04']}: casos ativos por faixa de idade (anos desde a "
            "identificação no corte), um gráfico por classe, cada um na sua escala."))

    def cartoes(self) -> list:
        return [self.cartao_total, *self.cartoes_classe.values()]

    def graficos(self) -> list:
        return [g for g in self.multiplos.values() if not g.isHidden()]

    def mostrar(self, p):
        self.dados = p
        k = _nota_k(p.supressao_minima)
        self.cartao_total.definir(_ativas(p.total_ativas),
                                  f"idade mediana {anos(p.idade_mediana_total, SUPRIMIDO)}",
                                  dica_fonte("analise.proteger_cubo", 1, p.corte,
                                             f"Sem quantidade: toneladas e metros cúbicos não se somam{k}."))
        linhas = {l.classe: l for l in p.linhas}
        for c in CLASSES:
            l = linhas.get(c)
            self.cartoes_classe[c].setVisible(l is not None)
            self.multiplos[c].setVisible(l is not None)
            if l is None:
                continue
            quantidade = SUPRIMIDO if l.quantidade is None else formatos.quantidade(l.quantidade, c)
            self.cartoes_classe[c].definir(
                _ativas(l.ativas), f"{quantidade} · idade mediana {anos(l.idade_mediana, SUPRIMIDO)}",
                dica_fonte("analise.proteger_cubo", 1, p.corte,
                           f"Quantidade em {l.unidade}, só desta classe{k}."))
            valores = [l.envelhecimento.get(f) for f in p.faixas]
            grafico = self.multiplos[c]
            grafico.mostrar(f"IDADE DOS CASOS EM ABERTO · {ROTULO_CLASSE[c].upper()} · {p.ano}", list(p.faixas),
                            [(ROTULO_CLASSE[c], CORES[c], valores)], "casos ativos (contagem)",
                            titulo_categorias="anos desde a identificação", legenda=False, largura=0.6,
                            rotulos=[(contagem(n), n or 0) for n in valores],
                            rotulos_categoria=[f.replace("<", "&lt;") for f in p.faixas])   # rótulo é texto rico
            grafico.dica_barra = lambda i, _nome, c=c, valores=valores, faixas=p.faixas: (
                f"{ROTULO_CLASSE[c]} · {faixas[i]} anos: " + (f"{SUPRIMIDO}: oculto para proteger poucos casos"
                                                             if valores[i] is None
                                                             else f"{contagem(valores[i])} ativas"))
            grafico.setToolTip(dica_fonte("analise.envelhecimento", 1, p.corte,
                                          f"Casos ativos por faixa de idade{k}."))


class PainelPorUF(PainelTematico):
    """O coroplético (com a legenda de quintis e o combo de indicador, de painel_n1.py) e, ao lado, KPI-03 e
    KPI-03b pareados por UF no mesmo eixo de 0 a 100%. As barras por classe ficam abaixo."""
    chave = "uf"

    def __init__(self, mapa, legenda, combo_indicador, barras, explica, parent=None):
        super().__init__(parent)
        self.mapa, self.legenda, self.combo_indicador, self.barras = mapa, legenda, combo_indicador, barras
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 4, 8, 4)
        v.setSpacing(6)
        topo = QHBoxLayout()
        topo.addWidget(CaptionLabel("Indicador do mapa"))
        topo.addWidget(combo_indicador)
        topo.addStretch(1)
        v.addLayout(topo)
        corpo = QHBoxLayout()
        coluna = QVBoxLayout()
        coluna.addWidget(mapa, 1)
        coluna.addWidget(legenda)
        corpo.addLayout(coluna, 3)
        self.pareadas = GraficoBarras(horizontal=True)
        self.pareadas.setMinimumHeight(820)
        self.pareadas.setMinimumWidth(330)
        corpo.addWidget(self.pareadas, 2)
        v.addLayout(corpo, 1)
        barras.setMinimumHeight(230)
        v.addWidget(barras)
        v.addWidget(explica)

    def graficos(self) -> list:
        return [self.mapa, self.pareadas, self.barras]

    @staticmethod
    def percentual(parte, linha):
        """% da UF: só com a parte e as ativas visíveis (None em qualquer uma = SUPRIMIDO, nunca recalculado)."""
        if linha.suprimida or parte is None or linha.ativas is None:
            return None
        return 100 * parte / linha.ativas if linha.ativas else 0.0

    def mostrar(self, p):
        self.dados = p
        k = _nota_k(p.supressao_minima)
        ufs = [l.uf for l in p.linhas]
        alem = [self.percentual(l.alem_do_prazo, l) for l in p.linhas]
        fora = [self.percentual(l.fora_da_previsao, l) for l in p.linhas]
        nomes = ("% além do prazo legal", "% com prazo previsto vencido")
        # as duas barras suprimidas (a UF inteira, em geral): um SUPRIMIDO na linha; só uma: no lugar dela
        rotulos = [(SUPRIMIDO, 0) if a is None and f is None else
                   ("sem ativas", 0) if not l.suprimida and l.ativas == 0 else None
                   for l, a, f in zip(p.linhas, alem, fora)]
        faltam = {(i, nome): SUPRIMIDO for i, (a, f) in enumerate(zip(alem, fora)) if (a is None) != (f is None)
                  for nome, v in zip(nomes, (a, f)) if v is None}
        self.pareadas.mostrar(f"CASOS FORA DO PRAZO POR UF · {p.ano}", ufs,
                              [(nomes[0], COR_KPI03, alem), (nomes[1], COR_KPI03B, fora)], "% dos casos ativos da UF",
                              maximo=100, rotulos=rotulos, rotulos_barra=faltam, largura=0.86, fonte_categorias=8)

        def dica(i, nome):
            l = p.linhas[i]
            parte = l.alem_do_prazo if nome == nomes[0] else l.fora_da_previsao
            pct = (alem if nome == nomes[0] else fora)[i]
            if pct is None:
                return f"{l.uf} · {nome}: {SUPRIMIDO}, oculto para proteger poucos casos"
            return f"{l.uf} · {nome}: {formatos.percentual(pct)} ({contagem(parte)} de {contagem(l.ativas)} ativas)"
        self.pareadas.dica_barra = dica
        self.pareadas.setToolTip(dica_fonte(
            "analise.proteger_cubo", 1, p.corte, f"{NOME_KPI['KPI-03']}: passou do prazo legal da classe. "
            f"{NOME_KPI['KPI-03b']}: o prazo previsto do caso venceu. As duas barras usam a mesma escala (% dos casos "
            f"ativos da UF){k}."))


class PainelCusto(PainelTematico):
    """KPI-05: barras empilhadas por categoria EEA, por classe ou por rota de tratamento, e as quatro
    responsabilidades financeiras que somam o total."""
    chave = "custo"
    agrupamento_mudou = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 4, 8, 4)
        v.setSpacing(8)
        topo = QHBoxLayout()
        topo.addWidget(CaptionLabel("Agrupar"))
        self.agrupamento = SegmentedWidget()
        self.agrupamento.addItem("classe", "Por classe", onClick=lambda *_: self._escolher("classe"))
        self.agrupamento.addItem("rota", "Por rota de tratamento", onClick=lambda *_: self._escolher("rota"))
        self.agrupamento.setCurrentItem("classe")
        topo.addWidget(self.agrupamento)
        topo.addStretch(1)
        v.addLayout(topo)
        self.por = "classe"
        self.cartao_total = CartaoValor(NOME_KPI["KPI-05"].upper(), COR_DESTAQUE)
        linha_total = QHBoxLayout()
        linha_total.addWidget(self.cartao_total, 1)
        linha_total.addStretch(3)
        v.addLayout(linha_total)
        linha = QHBoxLayout()
        linha.setSpacing(8)
        self.cartoes_resp = {g: CartaoValor(ROTULO_RESPONSABILIDADE[g].upper()) for g in RESPONSABILIDADES}
        for cartao in self.cartoes_resp.values():
            linha.addWidget(cartao, 1)
        v.addLayout(linha)
        self.grafico = GraficoBarras(horizontal=True, empilhado=True)
        self.grafico.setMinimumHeight(330)
        v.addWidget(self.grafico, 1)
        self.nota = self._explicacao("")
        v.addWidget(self.nota)

    def _escolher(self, por: str):
        self.agrupamento.setCurrentItem(por)
        if por != self.por:
            self.por = por
            self.agrupamento_mudou.emit(por)

    def cartoes(self) -> list:
        return [self.cartao_total, *self.cartoes_resp.values()]

    def graficos(self) -> list:
        return [self.grafico]

    def memoria(self, p) -> str:
        """Memória agregada do recorte: R$ por categoria de custo."""
        partes = [f"{ROTULO_CATEGORIA[c]} " + (SUPRIMIDO if p.por_categoria.get(c) is None
                                                 else formatos.custo(p.por_categoria[c])) for c in CATEGORIAS]
        return "; ".join(partes) + "."

    def mostrar(self, p):
        self.dados = p
        k = _nota_k(p.supressao_minima)
        memoria = self.memoria(p)
        self.cartao_total.definir(SUPRIMIDO if p.total is None else formatos.custo(p.total),
                                  "custo estimado dos casos ativos",
                                  dica_fonte("analise.custo_do_passivo", 1, p.corte, f"{memoria}{k}"))
        for g, cartao in self.cartoes_resp.items():
            valor = p.por_responsabilidade.get(g)
            parte = (f"{formatos.percentual(100 * valor / p.total)} do total"
                     if valor is not None and p.total else "")
            cartao.definir(SUPRIMIDO if valor is None else formatos.custo(valor), parte,
                           dica_fonte("analise.custo_do_passivo", 1, p.corte,
                                      f"{ROTULO_RESPONSABILIDADE[g]}. As quatro responsabilidades somam o "
                                      f"total{k}."))
        grupos = [l.grupo for l in p.linhas]
        rotulos_eixo = [ROTULO_CLASSE.get(g, g) for g in grupos]
        series = [(ROTULO_CATEGORIA[c], COR_CATEGORIA[c],
                   [None if l.custo is None or l.por_categoria.get(c) is None else l.por_categoria[c] / 1e6
                    for l in p.linhas]) for c in CATEGORIAS]
        rotulos = []
        for l in p.linhas:
            if l.custo is None:
                rotulos.append((SUPRIMIDO, 0))
            else:
                parcial = any(l.por_categoria.get(c) is None for c in CATEGORIAS)
                visivel = sum(l.por_categoria.get(c) or 0 for c in CATEGORIAS) / 1e6
                rotulos.append((formatos.custo(l.custo) + (" (categoria suprimida)" if parcial else ""), visivel))
        agrupado = "CLASSE" if p.por == "classe" else "ROTA DE TRATAMENTO"
        self.grafico.mostrar(f"CUSTO ESTIMADO POR {agrupado} E CATEGORIA · {p.ano}", grupos, series, "custo (R$ mi)",
                             inteiro=False, rotulos=rotulos, rotulos_categoria=rotulos_eixo, largura=0.6)

        def dica(i, nome):
            l = p.linhas[i]
            if l.custo is None:
                return f"{rotulos_eixo[i]}: {SUPRIMIDO}, oculto para proteger poucos casos"
            c = next(c for c in CATEGORIAS if ROTULO_CATEGORIA[c] == nome)
            v = l.por_categoria.get(c)
            return (f"{rotulos_eixo[i]} · {nome}: {SUPRIMIDO if v is None else formatos.custo(v)} de "
                    f"{formatos.custo(l.custo)} · {contagem(l.pendencias)} casos")
        self.grafico.dica_barra = dica
        self.grafico.setToolTip(dica_fonte("analise.custo_do_passivo", 1, p.corte,
                                           f"Custo por categoria: {memoria}{k}"))
        self.nota.setText("Valores somados em milhões de reais. As quatro responsabilidades financeiras somam o total.")


class PainelEncerramento(PainelTematico):
    """KPI-01 em degraus por classe, KPI-02 por ano (o corrente parcial) e o estoque ativo (GraficoEstoque)."""
    chave = "encerramento"
    AVISO = "Cada degrau junta anos até somar 3 encerramentos, para proteger poucos casos."

    def __init__(self, combo_grafico, estoque, parent=None):
        super().__init__(parent)
        self.combo_grafico, self.estoque = combo_grafico, estoque
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 4, 8, 4)
        v.setSpacing(8)
        linha = QHBoxLayout()
        linha.setSpacing(8)
        self.cartoes_curva = {c: CartaoValor(ROTULO_CLASSE[c], CORES.get(c)) for c in (*CLASSES, TODAS)}
        for cartao in self.cartoes_curva.values():
            linha.addWidget(cartao, 1)
        v.addLayout(linha)
        self.aviso = CaptionLabel(self.AVISO)
        self.aviso.setWordWrap(True)
        self.aviso.setStyleSheet("color:#D99A1E; font-weight:600;")
        v.addWidget(self.aviso)
        graficos = QHBoxLayout()
        graficos.setSpacing(6)
        self.curva = GraficoCurva()
        self.taxa = GraficoBarras(empilhado=True)
        for g in (self.curva, self.taxa):
            g.setMinimumHeight(360)
            graficos.addWidget(g, 1)
        v.addLayout(graficos)
        linha_estoque = QHBoxLayout()
        linha_estoque.addWidget(CaptionLabel("Gráfico do estoque"))
        linha_estoque.addWidget(combo_grafico)
        linha_estoque.addStretch(1)
        v.addLayout(linha_estoque)
        v.addWidget(estoque, 1)

    def cartoes(self) -> list:
        return [c for c in self.cartoes_curva.values() if not c.isHidden()]

    def graficos(self) -> list:
        return [self.curva, self.taxa, *self.estoque.vistas_visiveis()]

    def mostrar(self, p):
        self.dados = p
        k = _nota_k(p.supressao_minima)
        fonte = "analise.tempo_ate_encerramento" if p.exata else "analise.tabua_de_vida"
        self.aviso.setVisible(not p.exata)
        for chave, cartao in self.cartoes_curva.items():
            curva = p.curvas.get(chave)
            cartao.setVisible(curva is not None)
            if curva is None:
                continue
            cartao.definir(f"mediana {anos(curva.mediana)}", f"P90 {anos(curva.p90)}",
                           dica_fonte(fonte, 1, p.corte,
                                      "KPI-01: anos até o encerramento, contando também os casos ainda ativos. "
                                      "Mediana: tempo em que metade encerra; P90: tempo em que 90% encerram; não "
                                      "atingido: a curva ainda não chegou lá" + k))
        sufixo = f" · {ROTULO_CLASSE[p.classe]}" if p.classe else ""
        self.curva.mostrar("TEMPO ATÉ O ENCERRAMENTO · FRAÇÃO AINDA ATIVA" + sufixo.upper(), p.curvas)
        self.curva.setToolTip(dica_fonte(fonte, 1, p.corte, "KPI-01: fração dos casos ainda ativos a cada ano depois "
                                         "da identificação" + ("" if p.exata else ". " + self.AVISO)))
        taxas = list(p.taxa_anual)
        anos_ = [t.ano for t in taxas]
        fechados = [None if t.percentual is None else (0.0 if t.parcial else t.percentual) for t in taxas]
        corrente = [None if t.percentual is None else (t.percentual if t.parcial else 0.0) for t in taxas]
        parcial = QColor(COR_SAIDAS)
        parcial.setAlpha(110)
        rotulos = [("parcial", t.percentual) if t.parcial and t.percentual is not None else None for t in taxas]
        self.taxa.mostrar("TAXA ANUAL DE ENCERRAMENTO" + sufixo.upper(), [str(a) for a in anos_],
                          [("anos fechados", COR_SAIDAS, fechados), ("ano corrente (parcial)", parcial, corrente)],
                          "taxa (% ao ano)", inteiro=False, rotulos=rotulos,
                          rotulos_barra={(i, "anos fechados"): SUPRIMIDO for i, t in enumerate(taxas)
                                         if t.percentual is None},
                          titulo_categorias="ano", largura=0.75, angulo=-90)

        def dica(i, _nome):
            t = taxas[i]
            if t.percentual is None:
                return f"{t.ano}: {SUPRIMIDO}, oculto para proteger poucos casos"
            return (f"{t.ano}: {formatos.percentual(t.percentual)} ({contagem(t.saidas)} saídas de "
                    f"{contagem(t.ativas_1_jan)} ativas em 1º de janeiro)"
                    + (" · parcial: ano corrente, sem anualização" if t.parcial else ""))
        self.taxa.dica_barra = dica
        self.taxa.setToolTip(dica_fonte("analise.taxa_anual_encerramento", 1, p.corte,
                                        f"KPI-02: saídas no ano sobre as ativas em 1º de janeiro; o ano corrente é "
                                        f"parcial{k}"))
