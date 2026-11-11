"""Panorama agregado por UF: o painel do N1 (e a visão nacional do N3).

Só totais chegam aqui (ServicoAcervo.panorama): nenhum ponto, nenhum registro (RF-20).
  - coroplético por UF, colorido por quintil do indicador; dica composta com o Índice de Pressão;
  - legenda de quintis: passar o mouse realça as UFs do quintil, clicar fixa a seleção;
  - barras por classe que seguem o mapa (UF sob o mouse ou seleção); clicar numa barra recolore o mapa só
    para aquela classe;
  - linha do tempo com marcadores de evento: refaz índice, coroplético e barras para o fim daquele ano;
  - estoque ativo por classe (área empilhada; o total no título e no rótulo do ano), saldo anual ou um gráfico
    por classe, com os eventos numerados. A série vem do serviço já no recorte da classe.

Mapa, legenda, barras, gráfico e linha do tempo não se chamam: todos observam um EstadoN1 (mediador), e
isso elimina ciclos de sinal ("o mapa atualiza as barras, que atualizam o mapa...").

Painéis temáticos (padrão SINIR+): a área abaixo do filtro tem a faixa de KPIs e quatro
painéis navegáveis (paineis_tematicos.py): passivo por classe, passivo por UF (o mapa, a legenda, o combo de
indicador, agora com KPI-03 e KPI-03b, e as barras por classe), custo do passivo e evolução do encerramento (com
o gráfico de estoque). Todos leem o mesmo EstadoN1; trocar de painel não mexe no filtro nem nas escolhas locais.
O N3 usa os mesmos quatro; o N2 usa classe, custo e encerramento na própria UF.

Só o N1 usa este panorama no PainelAnalitico (saiu do N3), sem dado financeiro: sem o
painel de custo, sem o cartão de custo, sem o indicador "custo" no mapa e sem reais na dica da UF
(`financeiro=False`). A UF do N2 (Painéis da UF) continua com o custo. Rótulos de classe e de indicador vêm de
acervo/vocabulario.py.

Filtro: classe e ano do EstadoN1 aparecem numa BarraFiltros, por um EstadoFiltro ligado
nos dois sentidos. Só essas duas dimensões (as que o cubo protegido do serviço conhece): qualquer outra que
chegue ao estado é descartada, para não reabrir dedução por diferença. A contagem vem dos
totais agregados do panorama, nunca de registros.
"""
from datetime import date

from PySide6.QtCharts import (QBarCategoryAxis, QBarSet, QChart, QChartView, QHorizontalStackedBarSeries,
                              QValueAxis)
from PySide6.QtCore import QObject, QPointF, Qt, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QPainter
from PySide6.QtWidgets import (QGraphicsSimpleTextItem, QHBoxLayout, QStackedWidget, QToolTip, QVBoxLayout,
                               QWidget)

from ecosec.acervo import formatos, vocabulario
from ecosec.acervo.filtro import Filtro
from ecosec.interface.componentes.barra_filtros import BarraFiltros
from ecosec.interface.componentes.grafico_estoque import CORES, MODOS, GraficoEstoque, eixo_redondo
from ecosec.interface.componentes.legenda_quantis import (COR_SEM_ATIVAS, COR_SUPRIMIDA, RAMPA, LegendaQuantis,
                                                          quintis)
from ecosec.interface.componentes.slider_eventos import SliderEventos
from ecosec.interface.estado_filtro import EstadoFiltro
from ecosec.interface.estilo import cor_texto_secundario
from ecosec.interface.fluent import CaptionLabel, ComboBox, ScrollArea, SegmentedWidget, StrongBodyLabel, isDarkTheme
from ecosec.interface.paineis_tematicos import (KPIS_DO_PAINEL, PAINEIS, TITULO_PAINEL, FaixaKPIs, PainelCusto,
                                                PainelEncerramento, PainelPorClasse, PainelPorUF, dica_fonte)

# o texto do combo é o nome do indicador (vocabulário); o código KPI-xx fica na dica do mapa
PRESSAO, ATIVAS, CRITICAS, CUSTO = ("Índice de pressão", "Casos ativos", "Casos críticos", "Custo estimado (R$)")
INDICADORES_KPI = (vocabulario.ROTULO_KPI["KPI-03"], vocabulario.ROTULO_KPI["KPI-03b"])
INDICADORES = (PRESSAO, ATIVAS, CRITICAS, CUSTO, *INDICADORES_KPI)
INDICADORES_SEM_CUSTO = tuple(i for i in INDICADORES if i != CUSTO)          # N1
TODAS_CLASSES = "Todas as classes"
CLASSES = ("AREA CONTAMINADA", "CLASSE I NBR 10004", "REJEITO RADIOATIVO CNEN")
ROTULOS_CLASSE = tuple(vocabulario.ROTULO_CLASSE[c] for c in CLASSES)
TITULO_INDICADOR = {PRESSAO: "Índice de pressão (0 a 1)", ATIVAS: "Casos ativos (contagem)",
                    CRITICAS: "Casos críticos (contagem)", CUSTO: "Custo estimado (R$)",
                    INDICADORES_KPI[0]: f"{INDICADORES_KPI[0]} (% dos casos ativos)",
                    INDICADORES_KPI[1]: f"{INDICADORES_KPI[1]} (% dos casos ativos)"}


def dinheiro(valor: float) -> str:
    """R$ abreviado em mil, mi ou bi, com vírgula decimal (pt-BR)."""
    for limite, sufixo in ((1e9, "BI"), (1e6, "MI"), (1e3, "MIL")):
        if valor >= limite:
            return f"R$ {valor / limite:.1f} {sufixo}".replace(".", ",")
    return f"R$ {valor:.0f}"


def dinheiro_fino(valor: float) -> str:
    """Como `dinheiro`, sem o R$ e com duas casas (legenda, quando uma casa faz dois quintis se tocarem)."""
    for limite, sufixo in ((1e9, "BI"), (1e6, "MI"), (1e3, "MIL")):
        if valor >= limite:
            return f"{valor / limite:.2f} {sufixo}".replace(".", ",")
    return f"{valor:.0f}"


def dica_uf(item, total_ufs: int, supressao_minima: int = 3, financeiro: bool = True) -> str:
    indice = f"ÍNDICE DE PRESSÃO {item.indice:.2f}".replace(".", ",") + f" ({item.posto}º/{total_ufs})"
    if item.suprimida:
        return f"{item.uf} · SUPRIMIDO (MENOS DE {supressao_minima} CASOS ATIVOS OU COMPLEMENTAR)"
    if not item.ativas:
        return f"{item.uf} · NENHUM CASO ATIVO"
    # subcontagem com menos de k, ou com menos de k fora dela, ou complementar: o número não sai
    criticas = "CRÍTICAS SUPRIMIDAS" if item.criticas is None else f"{item.criticas} CRÍTICAS"
    custo = f" · {dinheiro(item.custo)}" if financeiro and item.custo is not None else ""
    return f"{item.uf} · {item.ativas} CASOS ATIVOS · {criticas}{custo} · {indice}"


class EstadoN1(QObject):
    foco_mudou = Signal(object)              # UF sob o mouse, ou None
    selecao_mudou = Signal(frozenset)        # UFs fixadas por clique ou pela legenda
    classe_mudou = Signal(object)            # classe escolhida nas barras, ou None (todas)
    ano_mudou = Signal(int)
    SINAIS = {"foco": "foco_mudou", "selecao": "selecao_mudou", "classe": "classe_mudou", "ano": "ano_mudou"}

    def __init__(self):
        super().__init__()
        self.foco, self.selecao, self.classe, self.ano = None, frozenset(), None, 2026

    def definir(self, **mudancas):
        for nome, valor in mudancas.items():
            if getattr(self, nome) != valor:                    # só emite quando muda (sem eco)
                setattr(self, nome, valor)
                getattr(self, self.SINAIS[nome]).emit(valor)


class BarrasClasse(QChartView):
    """Ativas por classe: cada barra na cor da classe (CORES), eixo com unidade e dica. Classe
    suprimida não desenha 0: a barra fica vazia e o rótulo diz SUPRIMIDO."""
    classe_clicada = Signal(str)

    def __init__(self, parent=None):
        super().__init__(QChart(), parent)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setMinimumWidth(320)
        self.chart().legend().hide()
        self.valores: dict[str, int] = {}
        self.suprimidas: set[str] = set()
        self.fora: set[str] = set()
        self.conjuntos: dict[str, QBarSet] = {}
        self.rotulos: list[QGraphicsSimpleTextItem] = []
        self._serie = None
        self.chart().plotAreaChanged.connect(self._posicionar)

    def mostrar(self, valores: dict[str, int], titulo: str, destaque: str | None = None, suprimidas=(), fora=()):
        """`suprimidas`: classes com o número escondido; `fora`: classes fora do filtro de classe."""
        self.valores = {c: n for c, n in valores.items() if c not in suprimidas}
        self.suprimidas, self.fora = set(suprimidas), set(fora) - set(suprimidas)
        ch = self.chart()
        ch.removeAllSeries()
        for eixo in ch.axes():
            ch.removeAxis(eixo)
        ch.setTheme(QChart.ChartTheme.ChartThemeDark if isDarkTheme() else QChart.ChartTheme.ChartThemeLight)
        ch.setBackgroundVisible(False)
        ch.setTitle(titulo)
        serie = QHorizontalStackedBarSeries()           # um conjunto por classe: cada barra com a sua cor
        self.conjuntos = {}
        for i, classe in enumerate(CLASSES):
            conjunto = QBarSet(vocabulario.rotulo(classe))
            n = self.valores.get(classe, 0) if classe not in self.suprimidas | self.fora else 0
            conjunto.append([n if j == i else 0 for j in range(len(CLASSES))])
            serie.append(conjunto)
            self.conjuntos[classe] = conjunto
        serie.setBarWidth(0.6)
        serie.clicked.connect(lambda indice, _c: self.classe_clicada.emit(CLASSES[indice]))
        serie.hovered.connect(lambda dentro, indice, _c: QToolTip.showText(QCursor.pos(), self.dica(indice))
                              if dentro else QToolTip.hideText())
        ch.addSeries(serie)
        self._serie = serie
        eixo_y = QBarCategoryAxis()
        eixo_y.append(list(ROTULOS_CLASSE))
        eixo_x = QValueAxis()
        eixo_x.setTitleText("casos ativos (contagem)")
        eixo_redondo(eixo_x, 0, max(5, max(self.valores.values(), default=0) * 1.18), intervalos=5)
        ch.addAxis(eixo_y, Qt.AlignmentFlag.AlignLeft)
        ch.addAxis(eixo_x, Qt.AlignmentFlag.AlignBottom)
        serie.attachAxis(eixo_y)
        serie.attachAxis(eixo_x)
        for classe, conjunto in self.conjuntos.items():
            cor = QColor(CORES[classe])
            if destaque and classe != destaque:
                cor.setAlpha(90)
            conjunto.setColor(cor)
            conjunto.setBorderColor(QColor("#1a1a1a") if classe == destaque else cor)
        self._posicionar()

    def dica(self, indice: int) -> str:
        if not 0 <= indice < len(CLASSES):
            return ""
        classe = CLASSES[indice]
        if classe in self.suprimidas:
            return f"{vocabulario.rotulo(classe)} · Suprimido, oculto para proteger poucos casos"
        if classe in self.fora:
            return f"{vocabulario.rotulo(classe)} · fora do filtro de classe"
        n, total = self.valores.get(classe, 0), sum(self.valores.values())
        pct = f" ({100 * n / total:.0f}% dos casos ativos mostrados)" if total else ""
        return f"{vocabulario.rotulo(classe)} · {vocabulario.casos(n, 'ativos')}" + pct

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
        for i, classe in enumerate(CLASSES):
            if classe in self.suprimidas:
                texto, cor = "SUPRIMIDO", QColor("#9E9E9E")
            elif classe in self.fora:
                texto, cor = "fora do filtro", QColor("#9E9E9E")
            else:
                texto, cor = f"{self.valores.get(classe, 0):,}".replace(",", "."), QColor(
                    "#F2F2F2" if escuro else "#1a1a1a")
            n = self.valores.get(classe, 0) if texto[0].isdigit() else 0
            ponto = ch.mapToPosition(QPointF(n, i), self._serie)
            r = QGraphicsSimpleTextItem(texto)
            r.setFont(QFont("Segoe UI", 8, QFont.Weight.DemiBold))
            r.setBrush(cor)
            caixa = r.boundingRect()
            x = ponto.x() + 4
            if x + caixa.width() > area.right():                     # barra longa: o número entra na barra
                x = ponto.x() - caixa.width() - 4
                r.setBrush(QColor("#FFFFFF"))
            r.setPos(max(area.left() + 2, x), ponto.y() - caixa.height() / 2)
            r.setToolTip(self.dica(i))
            cena.addItem(r)
            self.rotulos.append(r)


class PainelPanorama(QWidget):
    """Filtro (classe e ano), faixa de KPIs e os painéis temáticos (paineis_tematicos.py), todos sobre o mesmo
    EstadoN1. No N1, classe, UF e encerramento, sem custo (`financeiro=False`); na UF do N2,
    classe, custo e encerramento."""

    def __init__(self, tela, paineis=PAINEIS, parent=None, financeiro: bool = True):
        super().__init__(parent)
        self.tela, self.panorama, self._hoje = tela, None, None
        self.financeiro = financeiro
        paineis = tuple(p for p in paineis if financeiro or p != "custo")
        self.chaves_paineis = tuple(paineis)
        self.estado = EstadoN1()
        self.estado_filtro = EstadoFiltro(parent=self)          # espelho do EstadoN1: só classe e ano
        self._quintil_de: dict[str, int] = {}
        self.dados: dict = {}                                   # o que o serviço devolveu para cada painel
        externo = QVBoxLayout(self)
        externo.setContentsMargins(0, 8, 0, 0)
        externo.setSpacing(6)
        self.barra = BarraFiltros(self.estado_filtro)
        externo.addWidget(self.barra)
        topo = QHBoxLayout()
        self.combo_classe = ComboBox()
        self.combo_classe.addItems([TODAS_CLASSES, *ROTULOS_CLASSE])        # rótulo na tela, código no filtro
        self.combo_classe.setMinimumWidth(220)
        self.slider = SliderEventos()
        self.slider.setMinimumWidth(320)
        self.rotulo_ano = StrongBodyLabel()
        topo.addWidget(CaptionLabel("Classe"))
        topo.addWidget(self.combo_classe)
        topo.addSpacing(10)
        topo.addWidget(CaptionLabel("Ano"))
        topo.addWidget(self.slider, 1)
        topo.addWidget(self.rotulo_ano)
        externo.addLayout(topo)
        self.faixa_kpis = FaixaKPIs(financeiro)
        externo.addWidget(self.faixa_kpis)
        linha_abas = QHBoxLayout()
        self.abas_paineis = SegmentedWidget()
        linha_abas.addWidget(self.abas_paineis)
        linha_abas.addStretch(1)
        externo.addLayout(linha_abas)
        self.pilha_paineis = QStackedWidget()
        externo.addWidget(self.pilha_paineis, 1)
        # os componentes do panorama, cada um no seu painel
        self.combo_indicador = ComboBox()
        self.combo_indicador.addItems(list(INDICADORES if financeiro else INDICADORES_SEM_CUSTO))
        self.combo_indicador.setMinimumWidth(290)
        self.mapa = self.legenda = self.barras = None
        if "uf" in self.chaves_paineis:
            from ecosec.interface.mapa_vetorial import MapaVetorial
            self.mapa = MapaVetorial()
            self.mapa.setMinimumHeight(300)
            self.mapa.setDragMode(self.mapa.DragMode.NoDrag)
            self.legenda = LegendaQuantis()
            self.barras = BarrasClasse()
        self.combo_grafico = ComboBox()
        self.combo_grafico.addItems(list(MODOS))
        self.combo_grafico.setMinimumWidth(300)
        self.combo_grafico.currentIndexChanged.connect(
            lambda *_: self.panorama and self.estoque.mostrar(self.panorama.serie, self.panorama.eventos,
                                                              ano=self.panorama.ano, classe=self.panorama.classe,
                                                              modo=self.combo_grafico.currentText()))
        self.estoque = GraficoEstoque()                 # a altura mínima vem do modo (um, dois ou três gráficos)
        explica = CaptionLabel(
            "Índice de pressão: posição relativa da UF entre as 27, de 0 a 1 (volume de casos ativos 30%, fração "
            "crítica 30%, posição no custo estimado 20%, fração além do prazo legal 20%; nenhum valor em reais). "
            "Passe o mouse "
            "numa UF para a dica e as barras; clique para fixar. Na legenda, passe o mouse para realçar um quintil "
            "e clique para selecioná-lo. Clicar numa barra recolore o mapa só para a classe.")
        explica.setWordWrap(True)
        explica.setStyleSheet(f"color:{cor_texto_secundario()};")
        construtores = {
            "classe": PainelPorClasse,
            "uf": lambda: PainelPorUF(self.mapa, self.legenda, self.combo_indicador, self.barras, explica),
            "custo": PainelCusto,
            "encerramento": lambda: PainelEncerramento(self.combo_grafico, self.estoque)}
        self.paineis: dict = {}
        self._rolagens: dict = {}
        for chave in self.chaves_paineis:
            painel = construtores[chave]()
            rolagem = ScrollArea()                     # cada painel rola sozinho: o filtro e os KPIs ficam à vista
            rolagem.setWidgetResizable(True)
            rolagem.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            rolagem.setStyleSheet("QScrollArea { background: transparent; border: none; }")
            rolagem.setWidget(painel)
            self.pilha_paineis.addWidget(rolagem)
            self.paineis[chave], self._rolagens[chave] = painel, rolagem
            self.abas_paineis.addItem(chave, TITULO_PAINEL[chave], onClick=lambda *_, c=chave: self.mostrar_painel(c))
        self.painel_atual = None
        self.mostrar_painel(self.chaves_paineis[0])
        if "custo" in self.paineis:
            self.paineis["custo"].agrupamento_mudou.connect(lambda *_: self._carregar_custo())
        # ligações (mediador)
        self.combo_indicador.currentIndexChanged.connect(lambda *_: self._colorir())
        self.combo_classe.currentIndexChanged.connect(
            lambda *_: self.estado.definir(classe=None if self.combo_classe.currentIndex() == 0
                                           else CLASSES[self.combo_classe.currentIndex() - 1]))
        self.slider.ano_escolhido.connect(lambda ano: self.estado.definir(ano=ano))
        if self.mapa is not None:
            self.mapa.uf_em_foco.connect(lambda uf: self.estado.definir(foco=uf))
            self.mapa.uf_clicada.connect(self._alternar_uf)
            self.legenda.passou.connect(self._realcar_quintil)
            self.legenda.escolhido.connect(self._selecionar_quintil)
            self.barras.classe_clicada.connect(
                lambda c: self.estado.definir(classe=None if self.estado.classe == c else c))
        self.estado.foco_mudou.connect(lambda *_: self._atualizar_barras())
        self.estado.selecao_mudou.connect(self._selecao_mudou)
        self.estado.classe_mudou.connect(self._classe_mudou)
        self.estado.ano_mudou.connect(lambda *_: self._recarregar())
        # EstadoN1 <-> EstadoFiltro (os dois só emitem quando mudam: sem eco)
        self.estado.classe_mudou.connect(
            lambda c: self.estado_filtro.definir(classes=frozenset({c}) if c else frozenset()))
        self.estado.ano_mudou.connect(self._ano_para_filtro)
        self.estado_filtro.mudou.connect(self._filtro_mudou)

    # ------------------------------------------------------------ navegação entre os painéis
    def mostrar_painel(self, chave: str):
        """Troca o painel à vista. O filtro (EstadoN1) e as escolhas de cada painel ficam como estavam."""
        if chave not in self.paineis:
            return
        self.pilha_paineis.setCurrentWidget(self._rolagens[chave])
        self.abas_paineis.setCurrentItem(chave)
        self.faixa_kpis.destacar(KPIS_DO_PAINEL[chave])
        self.painel_atual = chave

    # ------------------------------------------------------------ filtro (só classe e ano)
    def _ano_corrente(self) -> int:
        return self._hoje.year if self._hoje else self.estado.ano

    def _ano_para_filtro(self, ano: int):
        self.estado_filtro.definir(ano=None if ano >= self._ano_corrente() else ano)

    def _filtro_mudou(self, filtro):
        restrito = Filtro(classes=filtro.classes if len(filtro.classes) <= 1 else frozenset(), ano=filtro.ano)
        if restrito != filtro:                              # outra dimensão no N1: descartada
            self.estado_filtro.substituir(restrito)
            return
        self.estado.definir(classe=next(iter(filtro.classes), None), ano=filtro.ano or self._ano_corrente())

    def _atualizar_contagem(self):
        """N ativas no recorte (soma dos totais por classe do panorama, já protegidos) de T (estoque do ano na
        série agregada). No N1 não existe "fora" por registro."""
        p = self.panorama
        visiveis = [n for n in p.totais_classe.values() if isinstance(n, int)]
        total = p.serie.get("estoque_total", {}).get(p.ano)            # todas as classes (a série segue a
        if total is None:                                               # classe; o "de T" não)
            total = sum(serie.get(p.ano) or 0 for serie in p.serie.get("ativas", {}).values())
        numero = lambda n: f"{n:,}".replace(",", ".")      # noqa: E731
        texto = f"{numero(sum(visiveis))} casos ativos no recorte (de {numero(total)})"
        if len(visiveis) < len(p.totais_classe):
            texto += f" · classe com menos de {p.supressao_minima}: suprimida"
        self.barra.definir_texto_contagem(texto)

    # ------------------------------------------------------------ dados
    def carregar(self):
        from ecosec.acervo import sinteticos
        hoje = self.tela.app.acervo.hoje()
        self._hoje = hoje
        self.estado.blockSignals(True)
        self.estado.foco, self.estado.selecao, self.estado.classe, self.estado.ano = None, frozenset(), None, hoje.year
        self.estado.blockSignals(False)
        self.estado_filtro.blockSignals(True)
        self.estado_filtro.limpar()
        self.estado_filtro.blockSignals(False)
        self.barra.sincronizar()
        self.combo_classe.blockSignals(True)
        self.combo_classe.setCurrentIndex(0)
        self.combo_classe.blockSignals(False)
        self._recarregar(primeira=True)
        if self.mapa is not None:
            pais, _ = sinteticos.geografia()
            self.mapa.coropletico(pais, sinteticos.divisas_uf(), {}, {})
        self._colorir()

    def _recarregar(self, primeira: bool = False):
        acervo = self.tela.app.acervo
        self.panorama = acervo.panorama(self.tela.usuario, self.tela.nivel, self.estado.ano, self.estado.classe)
        p = self.panorama
        if primeira:
            anos = p.serie["anos"] or [p.hoje.year]
            self.slider.definir_eventos([(e.data_evento.year + (e.data_evento.month - 1) / 12, e.rotulo)
                                         for e in p.eventos], anos[0], anos[-1])
        self.slider.blockSignals(True)                      # o ano pode ter vindo do chip removido
        self.slider.setValue(p.ano)
        self.slider.blockSignals(False)
        self.rotulo_ano.setText(str(p.ano))
        self._atualizar_contagem()
        self.estoque.mostrar(p.serie, p.eventos, ano=p.ano, classe=p.classe)
        self.estoque.definir_dica(dica_fonte(
            "analise.serie_estoque", 1, min(date(p.ano, 12, 31), p.hoje),
            "Casos ativos no fim de cada ano, entradas e saídas."
            + (" Totais pequenos ficam ocultos, sem desenho." if p.supressao_minima else "")))
        self._carregar_paineis()
        if not primeira:
            self._colorir()

    def _carregar_paineis(self):
        """Os KPIs e os painéis do recorte (classe e ano do EstadoN1), cada um pedido ao serviço (que aplica o
        nível e o k e registra na trilha). A escolha local de cada painel (agrupamento do custo, indicador do
        mapa, modo do estoque) não muda."""
        acervo, usuario, nivel = self.tela.app.acervo, self.tela.usuario, self.tela.nivel
        ano, classe = self.panorama.ano, self.panorama.classe
        self.dados["kpis"] = acervo.kpis(usuario, nivel, ano, classe)
        self.faixa_kpis.definir(self.dados["kpis"])
        if "classe" in self.paineis:
            self.dados["classe"] = acervo.painel_classe(usuario, nivel, ano, classe)
            self.paineis["classe"].mostrar(self.dados["classe"])
        if "uf" in self.paineis:
            self.dados["uf"] = acervo.painel_uf(usuario, nivel, ano, classe)
            self.paineis["uf"].mostrar(self.dados["uf"])
        if "custo" in self.paineis:
            self._carregar_custo()
        if "encerramento" in self.paineis:
            self.dados["encerramento"] = acervo.painel_encerramento(usuario, nivel, classe)
            self.paineis["encerramento"].mostrar(self.dados["encerramento"])

    def _carregar_custo(self):
        if self.panorama is None:
            return
        painel = self.paineis["custo"]
        self.dados["custo"] = self.tela.app.acervo.painel_custo(self.tela.usuario, self.tela.nivel, self.panorama.ano,
                                                                self.panorama.classe, por=painel.por)
        painel.mostrar(self.dados["custo"])

    # ------------------------------------------------------------ coroplético
    def _valor(self, uf: str, item) -> float | None:
        indicador = self.combo_indicador.currentText()
        if indicador in INDICADORES_KPI:                # KPI-03 e KPI-03b: do painel por UF (o mesmo cubo)
            linha = self._linhas_uf().get(uf)
            if linha is None:
                return None
            parte = linha.alem_do_prazo if indicador == INDICADORES_KPI[0] else linha.fora_da_previsao
            return PainelPorUF.percentual(parte, linha)
        return {PRESSAO: item.indice, ATIVAS: item.ativas, CRITICAS: item.criticas, CUSTO: item.custo}[indicador]

    def _linhas_uf(self) -> dict:
        dados = self.dados.get("uf")
        return {l.uf: l for l in dados.linhas} if dados is not None else {}

    def _dica_indicador(self, uf: str, item) -> str:
        indicador = self.combo_indicador.currentText()
        if indicador not in INDICADORES_KPI or item.suprimida or not item.ativas:
            return ""
        valor = self._valor(uf, item)
        nome = TITULO_INDICADOR[indicador].split(" (")[0]
        return f" · {nome}: " + ("SUPRIMIDO" if valor is None else formatos.percentual(valor))

    def _colorir(self):
        if self.panorama is None or self.mapa is None:
            return
        pressao = self.panorama.pressao
        # subcontagem suprimida (CRITICAS = None no N1) fica fora dos quintis, como a UF suprimida
        valores = {uf: float(self._valor(uf, item)) for uf, item in pressao.items()
                   if not item.suprimida and self._valor(uf, item) is not None}
        limites, self._quintil_de = quintis(valores)
        cores = {uf: QColor(RAMPA[k]) for uf, k in self._quintil_de.items()}
        for uf, item in pressao.items():
            if item.suprimida or self._valor(uf, item) is None:
                cores[uf] = QColor(COR_SUPRIMIDA)      # fora dos quintis: a cor não pode revelar o número
            elif not item.ativas:
                cores[uf] = QColor(COR_SEM_ATIVAS)
        dicas = {uf: dica_uf(item, len(pressao), self.panorama.supressao_minima, self.financeiro)
                 + self._dica_indicador(uf, item)
                 for uf, item in pressao.items()}
        self.mapa.pintar_ufs(cores, dicas)
        indicador = self.combo_indicador.currentText()
        corte = min(date(self.panorama.ano, 12, 31), self.panorama.hoje)
        fonte = "analise.proteger_cubo" if indicador in INDICADORES_KPI else "analise.indice_pressao"
        codigo = {INDICADORES_KPI[0]: " (KPI-03)", INDICADORES_KPI[1]: " (KPI-03b)"}.get(indicador, "")
        dica_mapa = dica_fonte(fonte, 1, corte, f"{TITULO_INDICADOR[indicador]}, em cinco faixas entre as UFs."
                               + (" UF com poucos casos fica oculta, fora das faixas."
                                  if self.panorama.supressao_minima else ""))
        self.mapa.setToolTip(dica_mapa)
        self.legenda.setToolTip(dica_mapa)
        formato = ((lambda v: dinheiro(v).removeprefix("R$ ")) if indicador == CUSTO else  # R$ no título
                   (lambda v: f"{v:.2f}".replace(".", ",")) if indicador == PRESSAO else
                   (lambda v: f"{v:.0f}%") if indicador in INDICADORES_KPI else
                   (lambda v: f"{v:.0f}"))
        inferiores = [min((valores[uf] for uf, q in self._quintil_de.items() if q == k), default=None)
                      for k in range(5)]
        contagens = [sum(q == k for q in self._quintil_de.values()) for k in range(5)]
        fino = (dinheiro_fino if indicador == CUSTO else                                # se dois quintis
                (lambda v: f"{v:.3f}".replace(".", ",")) if indicador == PRESSAO else             # se tocam
                (lambda v: f"{v:.1f}%".replace(".", ",")) if indicador in INDICADORES_KPI else None)
        self.legenda.definir(limites, formato, TITULO_INDICADOR[indicador], inferiores, contagens,
                             self.panorama.supressao_minima, fino)
        self._atualizar_barras()
        self.mapa.realcar_ufs(set(self.estado.selecao) or None)

    def _realcar_quintil(self, k: int):
        if self.mapa is None:
            return
        if k < 0:
            self.mapa.realcar_ufs(set(self.estado.selecao) or None)
        else:
            self.mapa.realcar_ufs({uf for uf, q in self._quintil_de.items() if q == k})

    def _selecionar_quintil(self, k: int):
        self.estado.definir(selecao=frozenset() if k < 0 else
                            frozenset(uf for uf, q in self._quintil_de.items() if q == k))

    def _alternar_uf(self, uf: str):
        self.estado.definir(selecao=self.estado.selecao ^ {uf})

    def _selecao_mudou(self, selecao):
        if self.mapa is not None:
            self.mapa.realcar_ufs(set(selecao) or None)
        self._atualizar_barras()

    def _classe_mudou(self, classe):
        self.combo_classe.blockSignals(True)
        self.combo_classe.setCurrentIndex(CLASSES.index(classe) + 1 if classe in CLASSES else 0)
        self.combo_classe.blockSignals(False)
        self._recarregar()

    # ------------------------------------------------------------ barras (seguem o mapa)
    def _atualizar_barras(self):
        if self.panorama is None or self.barras is None:
            return
        p = self.panorama
        if self.estado.foco:
            ufs, titulo = [self.estado.foco], f"CASOS ATIVOS POR CLASSE · {self.estado.foco}"
        elif self.estado.selecao:
            ufs = sorted(self.estado.selecao)
            titulo = "CASOS ATIVOS POR CLASSE · " + (", ".join(ufs) if len(ufs) <= 4 else f"{len(ufs)} UFS SELECIONADAS")
        else:
            ufs, titulo = None, f"CASOS ATIVOS POR CLASSE · {p.escopo}"
        tapada, tapadas = False, set()
        if ufs is None:
            valores = {c: n for c, n in p.totais_classe.items() if n is not None}
            tapadas = {c for c, n in p.totais_classe.items() if n is None}
            tapada = bool(tapadas)
        else:
            valores, tapadas = {}, set()
            for uf in ufs:
                for classe, n in p.por_classe.get(uf, {}).items():
                    if n is None:                      # célula suprimida: a soma da classe na seleção também
                        tapadas.add(classe)
                    else:
                        valores[classe] = valores.get(classe, 0) + n
            valores = {c: n for c, n in valores.items() if c not in tapadas}
            tapada = bool(tapadas)
        suprimidas = [uf for uf in (ufs or []) if p.pressao.get(uf) and p.pressao[uf].suprimida]
        if ufs and len(suprimidas) == len(ufs):             # só UF suprimida: nenhuma classe mostra número
            tapadas = set(CLASSES) - ({c for c in CLASSES if c != p.classe} if p.classe else set())
            valores = {}
        if suprimidas or tapada:
            titulo += " (MENOS DE %d: SUPRIMIDO)" % p.supressao_minima
        fora = {c for c in CLASSES if p.classe and c != p.classe}
        self.barras.mostrar(valores, titulo + f" · {p.ano}", self.estado.classe, suprimidas=tapadas, fora=fora)
        self.barras.setToolTip(dica_fonte("analise.proteger_cubo", 1, min(date(p.ano, 12, 31), p.hoje),
                                          "Casos ativos por classe na UF sob o mouse ou na seleção."
                                          + (" Totais pequenos ficam ocultos." if p.supressao_minima else "")))
