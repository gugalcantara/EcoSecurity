"""Painel analítico do acervo: uma seção por necessidade, conforme o nível.

Sobre os dados que o ServicoAcervo já liberou e registrou na trilha:
  - Painéis temáticos (só o N1): faixa de indicadores e três painéis (passivo por classe,
    passivo por UF com o coroplético e evolução do encerramento), painel_n1.py e paineis_tematicos.py. Só totais,
    já protegidos pelo serviço, e nenhum valor em reais:
    as abas "Painéis temáticos" e "Evolução" SAÍRAM do N3;
  - Painéis da UF (N2, n23_paineis_uf.py): o painel de decisão da UF (o que priorizar, evolução,
    UF × país, custo), sem k;
  - Mapa interativo (N2 da própria UF, N3 nacional): camadas com opacidade, densidade, municípios,
    custódias por tipo, legenda por escala, ficha num painel lateral deslizante (dados técnicos,
    responsáveis e documentos) e, no N3, a lista do ano com os marcos e a árvore custódia → pendência → documento;
  - Glossário (todos): a regra de negócio de cada termo, só do vocabulário
    (acervo/vocabulario.py), sem nenhum dado do acervo;
  - Planilha analítica (N2 e N3): registros individuais, ordenável e paginada,
    com busca e filtros. Exporta só no N2 (no N3 a exportação é bloqueada);
  - RESUMO AGREGADO (todos): totais por UF, atividade, motivo, classe ou faixa,
    calculados no serviço. É a extração do N1 (livre) e do N2 (com rastreio).
Toda exportação grava o SHA-256 do arquivo na trilha.

Filtro único: no N2 e no N3 há um EstadoFiltro, criado aqui e repassado a mapa,
planilha, gráfico de risco, árvore de custódia, resumo e cabeçalho. A BarraFiltros acima das abas mostra os
chips e "N dentro · M fora (de T)". Os combos são vistas do estado: mudá-los chama `estado.definir`, e cada
`estado.mudou` reposiciona todos os combos sem emitir (blockSignals). No N1 o filtro do painel não existe:
o panorama tem a sua própria barra, só com classe e ano (painel_n1.py), e o resumo do N1 não aceita filtro.
"""
from datetime import date, datetime
from pathlib import Path

from PySide6.QtCharts import QBarCategoryAxis, QBarSet, QChart, QChartView, QStackedBarSeries, QValueAxis
from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QImage, QPainter, QPixmap
from PySide6.QtWidgets import (QApplication, QFileDialog, QHBoxLayout, QHeaderView, QLabel, QSizePolicy, QStackedWidget,
                               QToolTip, QVBoxLayout, QWidget)

from ecosec.acervo import analise, formatos, vocabulario
from ecosec.acervo.filtro import CONJUNTOS, SITUACAO_PADRAO, SITUACOES
from ecosec.acervo.sinteticos import AREA, CLASSE_I, RADIOATIVO
from ecosec.dominio.niveis import Nivel
from ecosec.interface.componentes.simbologia import COR_IDENTIDADE, NOME_TEMATICA, TEMATICAS
from ecosec.interface.estado_filtro import EstadoFiltro
from ecosec.interface.estilo import cor_borda, cor_texto_secundario
from ecosec.interface.fluent import (FIF, BodyLabel, CaptionLabel, CheckBox, ComboBox, FlowLayout, InfoBar,
                                     InfoBarPosition, ListWidget, PushButton, ScrollArea, SearchLineEdit,
                                     SegmentedWidget, SimpleCardWidget, SpinBox, StrongBodyLabel, TableView,
                                     isDarkTheme)
from ecosec.interface.n23_custodia import (CustoPorResponsavel, PriorizacaoOrcamento,  # noqa: F401
                                           memoria_html, regras_criterios)

COR_RISCO = COR_IDENTIDADE          # fonte única das cores de risco (componentes.simbologia)
# Os combos mostram o rótulo do vocabulário e filtram pelo código interno (rótulo != valor)
TODAS_UFS, TODOS_RISCOS, TODAS_ATIVIDADES, TODOS_MOTIVOS = ("Todas as UFs", "Todas as faixas de risco",
                                                            "Todas as atividades", "Todos os motivos")
TODAS_ACOES = "Todas as ações"
TODAS_CLASSES, TODAS_ETAPAS, TODOS_MUNICIPIOS = "Todas as classes", "Todas as etapas", "Todos os municípios"
CLASSES = (AREA, CLASSE_I, RADIOATIVO)


# Ativos / Encerrados / Todos (na ordem de SITUACOES), padrão Todos
SITUACOES_PLANILHA = tuple(vocabulario.ROTULO_SITUACAO[s] for s in SITUACOES)
ROTULO_SITUACAO_MAPA = vocabulario.FRASE_SITUACAO
DICA_SITUACAO = (f"{vocabulario.CAMPO_SITUACAO}: qual parte do cadastro o mapa e a planilha mostram.\n"
                 + "\n".join(f"{vocabulario.rotulo(s, 'situacao')}: {vocabulario.definicao(s, 'situacao')}"
                             for s in SITUACOES))
_RECORTE: dict = {}


def recorte(painel, filtro) -> list:
    """As pendências do painel que passam no filtro. Cache de uma entrada: num `estado.mudou`, mapa, planilha,
    barra e árvore pedem o mesmo recorte."""
    if _RECORTE.get("painel") is not painel or _RECORTE.get("filtro") != filtro:
        _RECORTE.clear()
        _RECORTE.update(painel=painel, filtro=filtro,
                        valor=filtro.aplicar(painel.pendencias, painel.hoje, painel.regras))
    return _RECORTE["valor"]


def sem_dimensoes(filtro) -> bool:
    """Nenhuma restrição de conjunto nem busca (só situação e ano)."""
    return not any(getattr(filtro, d) for d in CONJUNTOS) and not filtro.termo


class VistaCombo:
    """Um combo como VISTA de uma dimensão do filtro: `valor()` lê a escolha (conjunto vazio = todos) e
    `mostrar(filtro)` reposiciona o combo sem emitir. Dimensão com mais de um valor aparece como "todos"."""

    def __init__(self, combo, dimensao: str, todos: str, codigo=None, texto=None):
        self.combo, self.dimensao, self.todos = combo, dimensao, todos
        self.codigo = codigo or (lambda t: t)              # texto do item -> valor no filtro
        self.texto = texto or (lambda v: v)                # valor no filtro -> texto do item

    def valor(self) -> frozenset:
        texto = self.combo.currentText()
        valor = None if texto in ("", self.todos) else self.codigo(texto)
        return frozenset() if valor is None else frozenset({valor})

    def mostrar(self, filtro):
        valores = getattr(filtro, self.dimensao)
        texto = self.texto(next(iter(valores))) if len(valores) == 1 else self.todos
        indice = self.combo.findText(texto) if texto else -1
        self.combo.blockSignals(True)
        self.combo.setCurrentIndex(max(0, indice))
        self.combo.blockSignals(False)


def acoes():
    from ecosec.acervo import regras
    return regras.ACOES


POR_PAGINA = 50
# camadas do mapa: a definição (z, opacidade padrão) é a do mapa vetorial (sem cópia aqui)
CAMADAS_N2 = ("pendencias", "densidade", "municipios", "limites", "ufs")
CAMADAS_N3 = ("custodias", "pendencias", "densidade", "municipios", "limites", "ufs")
LIGADAS_N2 = frozenset({"pendencias", "limites", "ufs"})
LIGADAS_N3 = frozenset({"pendencias", "custodias", "limites", "ufs"})


def _janela_verificacao() -> float:
    from ecosec.configuracao import carregar
    return float(carregar()["contexto.verificacao_minutos"])


def _bloquear_captura() -> bool:
    from ecosec.configuracao import carregar
    return bool(carregar()["documentos.bloquear_captura"])


def _para_pixmap(bgr) -> QPixmap:
    rgb = bgr[:, :, ::-1].copy()
    alt, larg, _ = rgb.shape
    return QPixmap.fromImage(QImage(rgb.data, larg, alt, 3 * larg, QImage.Format.Format_RGB888).copy())


def _combo(itens, largura=180) -> ComboBox:
    combo = ComboBox()
    combo.addItems(list(itens))
    combo.setMinimumWidth(largura)
    return combo


def _combo_vocabulario(todos: str, codigos, tipo: str, largura=180) -> ComboBox:
    """Combo com os rótulos do vocabulário (o código interno fica no filtro, não na tela)."""
    return _combo([todos, *(vocabulario.rotulo(c, tipo) for c in codigos)], largura)


def _vista_vocabulario(combo, dimensao: str, todos: str, tipo: str) -> "VistaCombo":
    return VistaCombo(combo, dimensao, todos, codigo=lambda t: vocabulario.codigo(t, tipo) or t,
                      texto=lambda c: vocabulario.rotulo(c, tipo))


def _campo(texto: str, dica: str = "") -> CaptionLabel:
    """Rótulo de um campo de filtro ("Situação do caso"), com a definição na dica."""
    rotulo = CaptionLabel(texto)
    rotulo.setToolTip(dica)
    return rotulo


def _combo_situacao(largura=150) -> ComboBox:
    combo = _combo(SITUACOES_PLANILHA, largura)
    combo.setCurrentIndex(SITUACOES.index(SITUACAO_PADRAO))
    combo.setToolTip(DICA_SITUACAO)
    combo.setAccessibleName(vocabulario.CAMPO_SITUACAO)
    return combo


def _explicacao(texto: str) -> CaptionLabel:
    rotulo = CaptionLabel(texto)
    rotulo.setWordWrap(True)
    rotulo.setStyleSheet(f"color:{cor_texto_secundario()};")
    return rotulo


def _mensagem(erro):
    from ecosec.interface.tela_acervo import _mensagem as mensagem
    return mensagem(erro)


def _caminho_exportacao(pai, extensao: str, sugestao: str) -> Path | None:
    filtro = "Planilha CSV (*.csv)" if extensao == "csv" else "Planilha Excel (*.xlsx)"
    caminho, _ = QFileDialog.getSaveFileName(pai, "Exportar", sugestao, filtro)
    if not caminho:
        return None
    destino = Path(caminho)
    return destino if destino.suffix.lower() == f".{extensao}" else destino.with_name(destino.name + f".{extensao}")


# ================================================================ modelo de tabela (planilha e resumo)
class ModeloTabela(QAbstractTableModel):
    """Linhas ordenáveis; com `paginado`, a tabela mostra uma página de POR_PAGINA por vez."""

    def __init__(self, titulos=(), valor=lambda linha, j: linha[j], paginado=False, parent=None):
        super().__init__(parent)
        self.titulos, self.valor, self.paginado = tuple(titulos), valor, paginado
        self.todas: list = []
        self.pagina = 0
        self.ultima_ordem = None                 # (coluna, ordem) da última ordenação pedida pelo cabeçalho

    def definir(self, linhas, titulos=None):
        self.beginResetModel()
        if titulos is not None and tuple(titulos) != self.titulos:
            self.ultima_ordem = None
        if titulos is not None:
            self.titulos = tuple(titulos)
        self.todas, self.pagina = list(linhas), 0
        self.endResetModel()

    @property
    def paginas(self) -> int:
        return max(1, -(-len(self.todas) // POR_PAGINA)) if self.paginado else 1

    def ir(self, pagina: int):
        self.beginResetModel()
        self.pagina = max(0, min(pagina, self.paginas - 1))
        self.endResetModel()

    def _visiveis(self):
        if not self.paginado:
            return self.todas
        return self.todas[self.pagina * POR_PAGINA:(self.pagina + 1) * POR_PAGINA]

    def rowCount(self, pai=QModelIndex()):
        return 0 if pai.isValid() else len(self._visiveis())

    def columnCount(self, pai=QModelIndex()):
        return 0 if pai.isValid() else len(self.titulos)

    def data(self, indice, papel=Qt.ItemDataRole.DisplayRole):
        if not indice.isValid():
            return None
        linha = self._visiveis()[indice.row()]
        valor = self.valor(linha, indice.column())
        titulo = self.titulos[indice.column()]
        if papel == Qt.ItemDataRole.DisplayRole:
            return self.texto(linha, indice.column())
        if papel == Qt.ItemDataRole.ToolTipRole and isinstance(valor, str) and len(valor) > 24:
            return valor
        if papel == Qt.ItemDataRole.DecorationRole and titulo in ("NIVEL DE RISCO", "FAIXA"):
            return _bolinha(COR_RISCO.get(valor, "#888888"))          # a cor no símbolo; o texto em cor de texto
        if papel == Qt.ItemDataRole.TextAlignmentRole and (isinstance(valor, (int, float))
                                                          or valor == analise.SUPRIMIDO):
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return None

    def texto(self, linha, j: int) -> str:
        """O texto exibido: o formatador único por tipo de coluna e, nas colunas com código (classe, faixa,
        quem paga, ação, etapa, andamento), o rótulo do vocabulário. Ordenação e exportação usam o valor cru."""
        texto = formatos.celula(self.titulos, lambda k: self.valor(linha, k), j,
                                planilha=self.titulos == analise.TITULOS)
        return vocabulario.celula(self.titulos[j], texto)

    def headerData(self, secao, orientacao, papel=Qt.ItemDataRole.DisplayRole):
        if orientacao != Qt.Orientation.Horizontal:
            return None
        if papel == Qt.ItemDataRole.DisplayRole:                  # o título de exibição (o interno vai na exportação)
            return vocabulario.titulo_coluna(self.titulos[secao])
        if papel == Qt.ItemDataRole.ToolTipRole:
            return vocabulario.dica_coluna(self.titulos[secao]) or None
        return None

    def sort(self, coluna, ordem=Qt.SortOrder.AscendingOrder):
        def chave(linha):                    # coluna com data e texto vazio (ENCERRAMENTO): nunca compara os dois
            v = self.valor(linha, coluna)
            return isinstance(v, str), v
        self.ultima_ordem = (coluna, ordem) if coluna >= 0 else None
        self.beginResetModel()
        self.todas.sort(key=chave, reverse=ordem == Qt.SortOrder.DescendingOrder)
        self.pagina = 0
        self.endResetModel()


def _tabela(modelo) -> TableView:
    tabela = TableView()
    tabela.setModel(modelo)
    tabela.setSortingEnabled(True)
    tabela.setSelectionBehavior(TableView.SelectionBehavior.SelectRows)
    tabela.setEditTriggers(TableView.EditTrigger.NoEditTriggers)
    tabela.verticalHeader().hide()
    tabela.setWordWrap(False)
    tabela.verticalHeader().setDefaultSectionSize(32)
    tabela.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    tabela.horizontalHeader().setSortIndicatorShown(True)
    return tabela


# Compatibilidade: a planilha usa as linhas tipadas de analise.LinhaPlanilha
def ModeloPlanilha(parent=None):  # noqa: N802
    return ModeloTabela(analise.TITULOS, lambda l, j: getattr(l, analise.COLUNAS[j]), paginado=True, parent=parent)


# ================================================================ mapa (N2 e N3)
class MapaInterativo(QWidget):
    """Mapa vetorial com camadas e ficha num painel lateral deslizante.

    N2: a própria UF; painel de camadas numa faixa (símbolo, liga/desliga e ordem); ficha com Exportar (cadeado).
    N3: nacional; painel de camadas com opacidade e ordem, filtro por tipo de custódia, legenda por
    escala, a lista do ano com os marcos regulatórios do ano e a árvore Custódia → Pendência → Documento.
    O N3 não exporta."""

    def __init__(self, tela, estado: EstadoFiltro | None = None, parent=None):
        super().__init__(parent)
        from ecosec.dominio.acervo import rotulo
        from ecosec.interface.arvore_custodia import ArvoreCustodia
        from ecosec.interface.componentes.botao_exportar import BotaoExportar
        from ecosec.interface.componentes.painel_camadas import PainelCamadas
        from ecosec.interface.componentes.painel_deslizante import PainelDeslizante
        from ecosec.interface.mapa_vetorial import MapaVetorial
        self.tela, self.painel, self._p_atual = tela, None, None
        self.estado = estado if estado is not None else EstadoFiltro(parent=self)
        self._filtro, self._municipios, self._uf_dos_municipios = None, {}, ""
        self.mapa = MapaVetorial()                      # antes dos painéis de camadas, que conversam com ele
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 8, 0, 0)
        navegacao = QHBoxLayout()
        self.combo_uf = _combo([TODAS_UFS], 150)
        # Municípios e atividades com 200 px (eram 230 e 260; "Todos os municípios" e "Todas as
        # atividades" cabem inteiros): a faixa de listas cabe numa linha em 1500 px
        self.combo_municipio = _combo([TODOS_MUNICIPIOS], 200)
        self.combo_classe = _combo_vocabulario(TODAS_CLASSES, CLASSES, "classe", 190)
        self.combo_risco = _combo_vocabulario(TODOS_RISCOS, analise.CATEGORIAS, "faixa", 190)
        self.combo_atividade = _combo([TODAS_ATIVIDADES], 200)
        self.combo_situacao = _combo_situacao()
        self.combo_situacao.currentIndexChanged.connect(
            lambda indice: self.painel is not None and self.estado.definir(situacao=SITUACOES[max(0, indice)]))
        # combos = vistas do estado (o município é o par (UF da lista, nome))
        self._vista_uf = VistaCombo(self.combo_uf, "ufs", TODAS_UFS)
        self._vista_municipio = VistaCombo(
            self.combo_municipio, "municipios", TODOS_MUNICIPIOS,
            codigo=lambda nome: (self._uf_dos_municipios, nome) if self._uf_dos_municipios else None,
            texto=lambda par: par[1] if par[0] == self._uf_dos_municipios else "")
        self._vista_classe = _vista_vocabulario(self.combo_classe, "classes", TODAS_CLASSES, "classe")
        self._vista_risco = _vista_vocabulario(self.combo_risco, "riscos", TODOS_RISCOS, "faixa")
        self._vista_atividade = VistaCombo(
            self.combo_atividade, "atividades", TODAS_ATIVIDADES,
            codigo=lambda t: self._rotulo_atividade.get(t), texto=lambda c: vocabulario.rotulo(c, "atividade"))
        self._vistas = (self._vista_uf, self._vista_municipio, self._vista_classe, self._vista_risco,
                        self._vista_atividade)
        self._rotulo_atividade = {}
        self.combo_uf.currentIndexChanged.connect(self._uf_escolhida)
        for vista in (self._vista_municipio, self._vista_classe, self._vista_risco, self._vista_atividade):
            vista.combo.currentIndexChanged.connect(lambda *_, vi=vista: self._combo_escolhido(vi))
        # O botão de vista base é "Brasil" no N3 e "UF" no N2 (a UF do diretor); o texto sai em `carregar`
        self.botao_mais, self.botao_menos, self.botao_base = PushButton("+"), PushButton("−"), PushButton("Brasil")
        self.botao_base.setIcon(FIF.HOME)
        self.botao_mais.clicked.connect(lambda *_: self.mapa.aproximar(1.6))
        self.botao_menos.clicked.connect(lambda *_: self.mapa.aproximar(1 / 1.6))
        self.botao_base.clicked.connect(lambda *_: self._vista_base())
        # As listas num FlowLayout, que quebra linha quando a janela é estreita (1366 px) em vez de pôr uma
        # lista por cima da outra; − + e Brasil/UF fixos à direita, na primeira linha
        self.area_listas = QWidget()
        self.area_listas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        fluxo = FlowLayout(self.area_listas)
        fluxo.setContentsMargins(0, 0, 0, 0)
        fluxo.setHorizontalSpacing(6)
        fluxo.setVerticalSpacing(6)
        situacao = QWidget()                            # o rótulo não se separa da lista dele na quebra
        hs = QHBoxLayout(situacao)
        hs.setContentsMargins(0, 0, 8, 0)
        hs.addWidget(_campo(vocabulario.CAMPO_SITUACAO, DICA_SITUACAO))
        hs.addWidget(self.combo_situacao)
        fluxo.addWidget(situacao)
        for w in (self.combo_uf, self.combo_municipio, self.combo_classe, self.combo_risco, self.combo_atividade):
            fluxo.addWidget(w)
        navegacao.addWidget(self.area_listas, 1)
        for w in (self.botao_menos, self.botao_mais, self.botao_base):
            navegacao.addWidget(w, 0, Qt.AlignmentFlag.AlignTop)
        v.addLayout(navegacao)
        # painel de camadas do N2, numa faixa acima do mapa (símbolo, liga/desliga e ordem)
        self.linha_camadas = PainelCamadas(self.mapa, CAMADAS_N2, horizontal=True, titulo="Camadas:")
        self.caixas_n2 = self.linha_camadas.caixas
        self.linha_camadas.definir_ligadas(LIGADAS_N2)
        v.addWidget(self.linha_camadas)
        linha = QHBoxLayout()
        self.contagem = StrongBodyLabel()
        self.zoom = CaptionLabel()
        self.zoom.setStyleSheet(f"color:{cor_texto_secundario()};")
        self.caixa_atenuar = CheckBox("Mostrar fora do filtro (atenuado)")
        self.caixa_atenuar.setToolTip("Os pontos fora do filtro ficam visíveis a 15%, por baixo, sem clique e sem "
                                      "entrar nas contagens.")
        self.caixa_atenuar.stateChanged.connect(lambda *_: self._aplicar_recorte())
        # Agregação por zoom e temática dos pontos
        self.caixa_agrupar = CheckBox("Agrupar pontos")
        self.caixa_agrupar.setChecked(True)
        self.caixa_agrupar.setToolTip("Abaixo da escala de UF, pontos próximos na tela viram um agregado com a "
                                      "contagem; clique nele (ou Enter) para aproximar.")
        self.caixa_agrupar.setAccessibleName("Agrupar pontos próximos")
        self.caixa_agrupar.stateChanged.connect(
            lambda *_: self.mapa.definir_agregacao(self.caixa_agrupar.isChecked()))
        self.combo_simbologia = _combo([NOME_TEMATICA[t] for t in TEMATICAS], 150)
        self.combo_simbologia.setAccessibleName("Simbologia dos pontos")
        self.combo_simbologia.setToolTip("Atributo que define cor e forma dos pontos e o anel dos agregados")
        self.combo_simbologia.currentIndexChanged.connect(self._simbologia_escolhida)
        linha.addWidget(self.contagem)
        linha.addSpacing(12)
        linha.addWidget(self.caixa_atenuar)
        linha.addSpacing(12)
        linha.addWidget(self.caixa_agrupar)
        linha.addSpacing(12)
        linha.addWidget(CaptionLabel("Simbologia"))
        linha.addWidget(self.combo_simbologia)
        linha.addStretch(1)
        linha.addWidget(self.zoom)
        v.addLayout(linha)
        corpo = QHBoxLayout()
        # coluna do N3: opacidade por camada, filtro de custódia e árvore, numa rolagem (em 1366×768 falta altura e
        # o painel de camadas era espremido; em 1500×950 cabe e a barra não aparece)
        self.rolagem_n3 = ScrollArea()
        self.rolagem_n3.setFixedWidth(330)
        self.rolagem_n3.setWidgetResizable(True)
        self.rolagem_n3.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.rolagem_n3.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        self.coluna_n3 = QWidget()
        self.coluna_n3.setObjectName("colunaN3")
        self.coluna_n3.setStyleSheet("#colunaN3 { background: transparent; }")
        cn = QVBoxLayout(self.coluna_n3)
        cn.setContentsMargins(0, 0, 8, 0)
        cn.addWidget(StrongBodyLabel("Camadas"))
        self.painel_camadas = PainelCamadas(self.mapa, CAMADAS_N3, com_opacidade=True)
        self.caixas_n3, self.opacidades = self.painel_camadas.caixas, self.painel_camadas.opacidades
        self.painel_camadas.definir_ligadas(LIGADAS_N3)
        cn.addWidget(self.painel_camadas)
        cn.addWidget(CaptionLabel("Tipos de custódia"))
        tipos = QHBoxLayout()
        self.caixas_custodia = {}
        for tipo, simbolo in (("DEFINITIVO", "◇"), ("INTERMEDIARIO", "□"), ("NORM", "△"), ("INICIAL", "○")):
            caixa = CheckBox(simbolo)
            caixa.setToolTip(tipo)
            caixa.setChecked(True)
            caixa.stateChanged.connect(lambda *_: self._filtrar_custodias())
            self.caixas_custodia[tipo] = caixa
            tipos.addWidget(caixa)
        cn.addLayout(tipos)
        cn.addWidget(StrongBodyLabel("Custódia → caso → documento"))
        self.arvore = ArvoreCustodia(tela)
        self.arvore.focar.connect(self._focar_no)
        self.arvore.abrir_documento.connect(self.abrir_documento)
        cn.addWidget(self.arvore, 1)
        self.rolagem_n3.setWidget(self.coluna_n3)
        self.rolagem_n3.viewport().setStyleSheet("background: transparent;")
        corpo.addWidget(self.rolagem_n3)
        # o mapa, com o painel lateral sobreposto (não é coluna: o mapa mantém a largura)
        self.area_mapa = QWidget()
        am = QVBoxLayout(self.area_mapa)
        am.setContentsMargins(0, 0, 0, 0)
        self.mapa.setMinimumHeight(270)                    # em 1366×768 o espaço do mapa é de 279 a 291 px
        self.mapa.pendencia_escolhida.connect(self.mostrar_ficha)
        self._texto_contagem, self._n_no_mapa = "", 0
        self.mapa.na_vista_mudou.connect(self._mostrar_contagem)
        self.mapa.zoom_mudou.connect(lambda z: self.zoom.setText(
            f"zoom {z:.1f}× · escala {self.mapa.escala.lower()} · "
            + ("municípios e nomes" if z >= 14 else "municípios" if z >= 6 else "role a roda do mouse para aproximar")))
        am.addWidget(self.mapa)
        corpo.addWidget(self.area_mapa, 1)
        v.addLayout(corpo, 1)
        self.ficha = PainelDeslizante(self.area_mapa, 430)
        # aba Dados técnicos: blocos com hierarquia (n23_ficha.FichaTecnica) numa rolagem
        from ecosec.interface.n23_ficha import FichaTecnica
        aba_dados = QWidget()
        vd = QVBoxLayout(aba_dados)
        vd.setContentsMargins(0, 6, 0, 0)
        rolagem = ScrollArea()
        rolagem.setWidgetResizable(True)
        rolagem.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        rolagem.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        self.ficha_tecnica = FichaTecnica()
        self.ficha_tecnica.setObjectName("fichaTecnica")
        self.ficha_tecnica.setStyleSheet("#fichaTecnica { background: transparent; }")
        rolagem.setWidget(self.ficha_tecnica)
        rolagem.viewport().setStyleSheet("background: transparent;")
        vd.addWidget(rolagem, 1)
        # compatibilidade: o título (começa pelo código) e o selo de risco ficam acessíveis pelo mapa
        self.ficha_titulo, self.selo_risco = self.ficha_tecnica.titulo, self.ficha_tecnica.selo_risco
        cor = "#F2F2F2" if isDarkTheme() else "#1A1A1A"
        self.botao_exportar_ficha = BotaoExportar("Exportar ficha (CSV)", None, _janela_verificacao())
        self.botao_exportar_ficha.clicked.connect(lambda *_: self.exportar_ficha())
        vd.addWidget(self.botao_exportar_ficha)
        self.ficha.adicionar_aba("dados", "Dados técnicos", aba_dados)
        self.ficha_responsaveis = QLabel()
        self.ficha_responsaveis.setWordWrap(True)
        self.ficha_responsaveis.setTextFormat(Qt.TextFormat.RichText)
        self.ficha_responsaveis.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.ficha_responsaveis.setStyleSheet(f"color:{cor}; font-size:13px;")
        self.ficha.adicionar_aba("responsaveis", "Responsáveis", self.ficha_responsaveis)
        aba_docs = QWidget()
        vdoc = QVBoxLayout(aba_docs)
        vdoc.setContentsMargins(0, 6, 0, 0)
        self.lista_documentos = ListWidget()
        self.lista_documentos.itemDoubleClicked.connect(lambda *_: self._abrir_documento_da_lista())
        self.aviso_documentos = CaptionLabel()
        self.aviso_documentos.setWordWrap(True)
        self.botao_abrir_documento = PushButton("Abrir documento")
        self.botao_abrir_documento.setIcon(FIF.DOCUMENT)
        self.botao_abrir_documento.clicked.connect(lambda *_: self._abrir_documento_da_lista())
        vdoc.addWidget(self.lista_documentos, 1)
        vdoc.addWidget(self.aviso_documentos)
        vdoc.addWidget(self.botao_abrir_documento)
        self.ficha.adicionar_aba("documentos", "Documentos", aba_docs)
        # ano (N3): a data de corte numa lista, como os outros filtros ("Todos" = a situação atual); à direita,
        # na mesma linha, os marcos regulatórios do ano escolhido, só quando há marco (C-2). Os rótulos dos marcos
        # ficam como no acervo, em maiúsculas: a exibição é
        self.linha_tempo = QWidget()
        lt = QHBoxLayout(self.linha_tempo)
        lt.setContentsMargins(0, 4, 0, 0)
        self.combo_ano = ComboBox()
        self.combo_ano.addItem(vocabulario.TODOS_OS_ANOS)
        self.combo_ano.setMinimumWidth(130)
        self.combo_ano.currentIndexChanged.connect(self._ano_escolhido)
        self.marcos_do_ano = CaptionLabel()
        self.marcos_do_ano.setWordWrap(True)
        self.marcos_do_ano.hide()
        lt.addWidget(_campo(vocabulario.CAMPO_ANO, "A data de corte: a situação dos casos em 31/12 do ano escolhido."))
        lt.addWidget(self.combo_ano)
        lt.addSpacing(12)
        lt.addWidget(self.marcos_do_ano, 1)
        lt.addStretch(1)
        v.addWidget(self.linha_tempo)
        self._ano, self._eventos = None, []
        self.estado.mudou.connect(self._filtro_mudou)

    # ------------------------------------------------------------ carga
    def carregar(self, painel):
        from ecosec.acervo import regras, sinteticos
        self.painel, self._filtro = None, None
        n3 = painel.nivel is Nivel.N3
        pais, municipios = sinteticos.geografia()
        r = painel.regras or regras.ParametrosRegras.padrao()
        rotulos = {c: vocabulario.rotulo(c, "atividade") for c in painel.atividades}
        self.mapa.montar(pais, sinteticos.divisas_uf(), municipios, painel.pendencias,
                         lambda p: regras.categoria(p, painel.hoje), sinteticos.CUSTODIAS if n3 else (), rotulos)
        u = self.tela.usuario
        selo = "SECRETO" if n3 else "RESERVADO"
        self.mapa.marca_dagua = f"{selo} · {u.matricula} · {datetime.now():%d/%m/%Y %H:%M}" if u else selo
        self._municipios = {uf: sorted({p.municipio for p in painel.pendencias if p.uf == uf})
                            for uf in {p.uf for p in painel.pendencias}}
        if len(self._municipios) == 1:                      # N2: a vista base é a UF do diretor
            uf = next(iter(self._municipios))
            self.botao_base.setText("UF")
            self.botao_base.setToolTip(f"Volta o mapa a {uf}, a vista inicial; o filtro continua.")
        else:
            self.botao_base.setText("Brasil")
            self.botao_base.setToolTip("Volta o mapa ao Brasil inteiro; o filtro continua.")
        self._regras = r
        self._rotulo_atividade = {vocabulario.rotulo(c, "atividade"): c for c in painel.atividades}
        for combo, todos, itens in ((self.combo_uf, TODAS_UFS, sorted(self._municipios)),
                                    (self.combo_atividade, TODAS_ATIVIDADES, sorted(self._rotulo_atividade))):
            combo.blockSignals(True)
            combo.clear()
            combo.addItems([todos, *itens])
            combo.blockSignals(False)
        self.linha_camadas.setVisible(not n3)
        self.rolagem_n3.setVisible(n3)
        self.linha_tempo.setVisible(n3)
        self.botao_exportar_ficha.setVisible(painel.exporta)
        self.botao_exportar_ficha.definir_sessao(self.tela.sessao)
        # o mapa recém-montado volta às camadas e à ordem padrão: os painéis acompanham
        self.linha_camadas.definir_ligadas(LIGADAS_N2)
        self.painel_camadas.definir_ligadas(LIGADAS_N3)
        for caixa in (*self.caixas_custodia.values(), self.caixa_atenuar, self.caixa_agrupar):
            caixa.blockSignals(True)
            caixa.setChecked(caixa is not self.caixa_atenuar)
            caixa.blockSignals(False)
        self.combo_simbologia.blockSignals(True)            # o mapa recém-montado volta à faixa de risco
        self.combo_simbologia.setCurrentIndex(TEMATICAS.index(self.mapa.tematica))
        self.combo_simbologia.blockSignals(False)
        self.ficha.fechar()
        self.painel, self._ano = painel, None
        if n3:
            self._eventos = sorted(self.tela.app.acervo.eventos(), key=lambda e: e.data_evento)
            inicio = max(2006, min(p.data_identificacao.year for p in painel.pendencias))
            self.combo_ano.blockSignals(True)
            self.combo_ano.clear()                              # uma nova carga não duplica os itens
            self.combo_ano.addItems(vocabulario.itens_ano(inicio, painel.hoje))
            self.combo_ano.blockSignals(False)
        self._preencher_municipios("")
        self._filtro_mudou(self.estado.filtro)          # o recorte vem antes da navegação (N2: já abre na UF)

    def _simbologia_escolhida(self, indice: int):
        if 0 <= indice < len(TEMATICAS):
            self.mapa.definir_tematica(TEMATICAS[indice])

    def _tipos_custodia(self) -> set:
        return {t for t, caixa in self.caixas_custodia.items() if caixa.isChecked()}

    def _alternar_camada(self, chave: str, ligada: bool):
        self.mapa.definir_camada_visivel(chave, ligada)

    def _filtrar_custodias(self):
        self.mapa.filtrar_custodias(self._tipos_custodia())
        if self.painel is not None and self.painel.nivel is Nivel.N3:
            self.arvore.montar(self.painel, self._ano, self._tipos_custodia(), self._recorte_arvore())

    def definir_ano(self, ano: int):
        """Lista do ano (N3): escreve o ano no filtro único (o ano corrente = sem chip, corte em hoje). Mapa,
        planilha, resumo e árvore seguem pelo `estado.mudou`."""
        if self.painel is None:
            return
        self.estado.definir(ano=None if int(ano) >= self.painel.hoje.year else int(ano))

    def _ano_escolhido(self, indice: int):
        """Lista "Ano": "Todos" tira o ano do filtro (sem chip, corte em hoje); um ano, o corte em 31/12 dele."""
        if self.painel is not None and indice >= 0:
            self.definir_ano(self.painel.hoje.year if indice == 0 else int(self.combo_ano.itemText(indice)))

    def _mostrar_ano(self, ano: int | None):
        """A lista acompanha o filtro (chip removido, outra aba) sem disparar o próprio sinal; os marcos do ano
        aparecem à direita só quando há marco ("Todos" e ano sem marco: a linha some, sem ocupar espaço)."""
        self.combo_ano.blockSignals(True)
        self.combo_ano.setCurrentText(vocabulario.TODOS_OS_ANOS if ano is None else str(ano))
        self.combo_ano.blockSignals(False)
        self.combo_ano.setToolTip(vocabulario.dica_ano(ano, self.painel.hoje))
        marcos = [e.rotulo for e in self._eventos if ano is not None and e.data_evento.year == ano]
        self.marcos_do_ano.setText(f"Marcos regulatórios em {ano}: " + "; ".join(marcos) if marcos else "")
        self.marcos_do_ano.setVisible(bool(marcos))

    # ------------------------------------------------------------ filtro único
    def _uf_da_lista(self, filtro) -> str:
        """UF cujos municípios o combo lista: a UF filtrada, a dos municípios filtrados ou a única do painel."""
        if len(filtro.ufs) == 1:
            return next(iter(filtro.ufs))
        ufs_municipios = {uf for uf, _ in filtro.municipios}
        if not filtro.ufs and len(ufs_municipios) == 1:
            return next(iter(ufs_municipios))
        return next(iter(self._municipios)) if len(self._municipios) == 1 else ""

    def _preencher_municipios(self, uf: str):
        self._uf_dos_municipios = uf          # no N2 o combo de UF fica em "todas", mas a lista é da UF dele
        self.combo_municipio.blockSignals(True)
        self.combo_municipio.clear()
        self.combo_municipio.addItems([TODOS_MUNICIPIOS, *self._municipios.get(uf, [])])
        self.combo_municipio.setEnabled(bool(uf))
        self.combo_municipio.blockSignals(False)

    def _uf_escolhida(self, *_):
        """Combo de UF: define o filtro de UF (os municípios de outra UF saem) e, pelo `estado.mudou`, enquadra."""
        if self.painel is None:
            return
        uf = self._vista_uf.valor()
        self.estado.definir(ufs=uf, municipios=frozenset(m for m in self.estado.filtro.municipios
                                                         if uf and m[0] in uf))

    def _combo_escolhido(self, vista: VistaCombo):
        if self.painel is not None:
            self.estado.definir(**{vista.dimensao: vista.valor()})

    def _voltar_ao_brasil(self):
        """Botão Brasil: só a VISTA volta ao país inteiro; o filtro continua (o chip de UF tira o recorte)."""
        self.mapa.ir_para_brasil()

    def _vista_base(self):
        """Botão "Brasil" (N3) ou "UF" (N2) e chip de UF removido: só a VISTA volta à base; o filtro continua."""
        if len(self._municipios) == 1:                      # N2: a base é a própria UF
            self.mapa.ir_para_uf(next(iter(self._municipios)))
        else:
            self.mapa.ir_para_brasil()

    def aplicar_filtros(self, *_):
        """Lê todos os combos do mapa para o filtro único (os demais filtros ficam como estão)."""
        if self.painel is None:
            return
        self.estado.definir(**{vista.dimensao: vista.valor() for vista in self._vistas})

    def _filtro_mudou(self, filtro):
        if self.painel is None:
            return
        anterior, self._filtro = self._filtro, filtro
        uf_lista = self._uf_da_lista(filtro)
        if uf_lista != self._uf_dos_municipios:
            self._preencher_municipios(uf_lista)
        for vista in self._vistas:
            vista.mostrar(filtro)
        self.combo_situacao.blockSignals(True)
        self.combo_situacao.setCurrentIndex(SITUACOES.index(filtro.situacao))
        self.combo_situacao.blockSignals(False)
        painel = self.painel
        corte = filtro.corte(painel.hoje)
        n3 = painel.nivel is Nivel.N3
        if n3:
            self._mostrar_ano(filtro.ano)
            if corte.year != self._ano:                     # custódias com a ocupação daquele ano
                ocupacoes = self.tela.app.acervo.custodias(painel, self.tela.usuario, corte.year)
                self.mapa.atualizar_custodias({c.nome: o for c, o in ocupacoes})
        self._ano = corte.year
        self.mapa.definir_ano(corte, so_ativas=filtro.situacao == "ATIVAS")
        self._aplicar_recorte()
        if n3:
            self.arvore.montar(painel, self._ano, self._tipos_custodia(), self._recorte_arvore())
        self._navegar(anterior, filtro)

    def _aplicar_recorte(self):
        """Pontos do recorte (modo esconder ou atenuar) e a contagem; fecha a ficha que saiu do recorte."""
        filtro = self._filtro
        if self.painel is None or filtro is None:
            return
        dentro = None
        if not sem_dimensoes(filtro) or filtro.situacao == "ENCERRADAS":
            dentro = frozenset(p.codigo for p in recorte(self.painel, filtro))
        n = self.mapa.aplicar_recorte(dentro, "atenuar" if self.caixa_atenuar.isChecked() else "esconder")
        self._n_no_mapa = n
        self._texto_contagem = (f"{vocabulario.casos(n)} no mapa "
                                f"({vocabulario.ADJETIVO_SITUACAO[filtro.situacao]} em {self._ano})")
        self._mostrar_contagem()
        if self.ficha.aberto and self._p_atual is not None and not any(
                pt.conta and pt.pendencia.codigo == self._p_atual.codigo for pt in self.mapa.pontos):
            self.ficha.fechar()

    def _mostrar_contagem(self, *_):
        """Casos no mapa (o recorte inteiro) e, quando parte deles está fora do enquadramento, quantos estão na
        vista: é o número do título da legenda, e sem isso os dois pareciam divergir (309 contra 308)."""
        na_vista = self.mapa.contagens["na_vista"]
        extra = f"; {formatos.inteiro(na_vista)} na vista" if 0 < na_vista < self._n_no_mapa else ""
        self.contagem.setText(self._texto_contagem + extra)

    def _recorte_arvore(self) -> frozenset | None:
        """A árvore segue as dimensões do filtro; a situação é a dela (custódia: ativas ou já recolhidas até o
        fim do ano; in situ: ativas no ano)."""
        if self._filtro is None or sem_dimensoes(self._filtro):
            return None
        return frozenset(p.codigo for p in recorte(self.painel, self._filtro.com(situacao="TODAS", ano=None)))

    def _navegar(self, anterior, filtro):
        """Vista separada do recorte: muda só quando a UF ou o município do filtro mudam. Um município ou uma
        UF: enquadra; sem nenhum (o chip foi removido): volta à base (Brasil; no N2, a própria UF)."""
        mudou_uf = anterior is None or anterior.ufs != filtro.ufs
        mudou_municipio = anterior is None or anterior.municipios != filtro.municipios
        if mudou_municipio and len(filtro.municipios) == 1:
            self.mapa.ir_para_municipio(*next(iter(filtro.municipios)))
        elif mudou_uf or mudou_municipio:
            if len(filtro.ufs) == 1:
                self.mapa.ir_para_uf(next(iter(filtro.ufs)))
            elif anterior is not None or len(self._municipios) == 1:
                self._vista_base()

    # ------------------------------------------------------------ ficha (painel lateral)
    def mostrar_ficha(self, p):
        """Ficha do caso (N2 e N3), em blocos (n23_ficha.FichaTecnica): cabeçalho com classe, risco e
        score; situação e prazos; local; origem e causa; contaminação e uso; custo com a memória recolhível;
        histórico de etapas. Tudo derivado (acervo/ficha.py, regras.py). O custo do CASO aparece no N2 e no N3, como
        antes; custo por responsável nomeado continua só no N3, na seção própria, e nunca entra na
        ficha. Responsáveis (aba própria) vêm do serviço já filtrados pelo nível (o N2 não recebe pessoa física)."""
        self._p_atual = p
        self.ficha.titulo.setText(f"{p.codigo} · {vocabulario.rotulo(p.situacao, 'situacao_caso')}")
        self.ficha_tecnica.mostrar(p, self.painel, self._regras)
        self._carregar_responsaveis(p)
        self._carregar_documentos(p)
        self.ficha.mostrar_aba("dados")
        self.botao_exportar_ficha.atualizar()
        self.ficha.abrir()

    def texto_ficha(self) -> str:
        """Todo o texto visível da aba Dados técnicos (para leitura e testes)."""
        return self.ficha_tecnica.texto()

    def _carregar_responsaveis(self, p):
        try:
            lista = self.tela.app.acervo.responsaveis_da_pendencia(self.painel, self.tela.usuario, p.codigo)
        except Exception as erro:  # noqa: BLE001
            self.ficha_responsaveis.setText(f"<i>{_mensagem(erro)}</i>")
            return
        if not lista:
            self.ficha_responsaveis.setText("<i>Nenhum responsável visível no seu nível.</i>")
            return
        aviso = ("<p><i>Pessoas físicas não fazem parte deste acesso.</i></p>" if self.painel.nivel is Nivel.N2
                 else "")
        cinza = cor_texto_secundario()
        self.ficha_responsaveis.setText(aviso + "".join(
            f"<p><b>{vocabulario.ROTULO_VINCULO.get(r.vinculo, r.vinculo)}</b><br>{r.nome}<br>"
            f"<span style='color:{cinza}'>situação cadastral "
            f"{vocabulario.ROTULO_SITUACAO_CADASTRAL.get(r.situacao_cadastral, r.situacao_cadastral)}</span></p>"
            for r in lista))

    def _carregar_documentos(self, p):
        self.lista_documentos.clear()
        self._documentos = []
        try:
            self._documentos = self.tela.app.acervo.documentos(self.painel, self.tela.usuario, p.codigo)
        except Exception as erro:  # noqa: BLE001
            self.aviso_documentos.setText(_mensagem(erro))
        for d in self._documentos:
            self.lista_documentos.addItem(f"{d.data:%d/%m/%Y} · {d.tipo} Nº {d.numero} · {d.situacao}")
        n3 = self.painel.nivel is Nivel.N3
        self.botao_abrir_documento.setVisible(n3)
        self.aviso_documentos.setText(
            "Duplo clique abre o documento, só para leitura." if n3 else
            "Só os metadados: o conteúdo dos documentos não faz parte deste acesso.")

    def _abrir_documento_da_lista(self):
        linha = self.lista_documentos.currentRow()
        if self._p_atual is None or not (0 <= linha < len(self._documentos)):
            return
        self.abrir_documento(self._p_atual.codigo, self._documentos[linha].id)

    def abrir_documento(self, codigo: str, documento_id: int):
        from ecosec.interface.documentos import JanelaDocumento
        try:
            entrega = self.tela.app.acervo.abrir_documento(self.painel, self.tela.usuario, codigo, documento_id)
        except Exception as erro:  # noqa: BLE001
            InfoBar.error("Documento indisponível", _mensagem(erro), duration=6000, position=InfoBarPosition.TOP,
                          parent=self.tela)
            return None
        self.janela_documento = JanelaDocumento(entrega, self, _bloquear_captura())
        self.janela_documento.show()
        return entrega

    def _focar_no(self, tipo: str, objeto):
        if tipo == "PENDENCIA":
            self.mostrar_ficha(objeto)                              # a ficha abre mesmo se o enquadramento falhar
            self.mapa.ir_para_ponto(objeto.longitude, objeto.latitude)
        elif tipo == "CUSTODIA":
            self.mapa.ir_para_ponto(objeto.longitude, objeto.latitude, 400)
        elif tipo == "UF":
            self.mapa.ir_para_uf(objeto)

    def exportar_ficha(self):
        """N2: a ficha sai como CSV de uma linha (a linha da planilha mais os campos novos da ficha, crus), pelo
        mesmo caminho da planilha (matriz + step-up + trilha)."""
        p = self._p_atual
        if self.painel is None or p is None:
            return
        destino = _caminho_exportacao(self, "csv", f"FICHA_{p.codigo}_{date.today():%Y%m%d}.csv")
        if destino is None:
            return
        try:
            resumo = self.tela.exportar_com_verificacao(
                lambda verificado_em: self.tela.app.acervo.exportar_ficha(
                    self.painel, self.tela.usuario, p.codigo, destino, risco=self.tela.risco,
                    verificado_em=verificado_em))
        except Exception as erro:  # noqa: BLE001
            InfoBar.error("Exportação recusada", _mensagem(erro), duration=6000, position=InfoBarPosition.TOP,
                          parent=self.tela)
            return
        self.botao_exportar_ficha.atualizar()
        if resumo:
            InfoBar.success("Ficha exportada", f"{destino.name}: SHA-256 {resumo[:12]}… registrado na trilha.",
                            duration=6000, position=InfoBarPosition.TOP, parent=self.tela)


# ================================================================ priorização e custo por responsável (N3)
# As duas abas de decisão nacional do N3 moram em n23_custodia.py (padrão de precisão: base, corte,
# totais que fecham, curva custo × risco). PriorizacaoOrcamento, CustoPorResponsavel e memoria_html continuam
# importáveis daqui (import no topo do módulo).

# ================================================================ planilha (N2 e N3)
# A grade mostra só as 9 colunas de decisão, na ordem de quem decide (o caso e o risco, onde, em que
# pé está, o porquê e o que fazer). O score vai na dica da faixa e a faixa ordena por ele. Substância,
# quantidade, datas, atraso, andamento, atividade, quem paga, custo, endereço e coordenadas ficam nos detalhes do
# caso (a ficha numa gaveta sobre a grade, com Enter ou duplo clique na linha) e na exportação, que continua
# com as 29 colunas cruas de analise.TITULOS. "Dias além do prazo legal" vale também para os encerrados (o atraso
# que ficou registrado), como na exportação.
COLUNAS_PLANILHA = ("CODIGO", "NIVEL_DE_RISCO", "CLASSE_DE_RISCO", "UF", "MUNICIPIO", "ETAPA_ATUAL",
                    "DIAS_ALEM_DO_PRAZO_LIMITE", "ACAO_RECOMENDADA", "MOTIVO")
TITULOS_PLANILHA = tuple(c.replace("_", " ") for c in COLUNAS_PLANILHA)
MINIMO_MOTIVO = 180                  # px da última coluna (motivo, com a sobra); abaixo disso a grade rola
LARGURA_INDICADOR = 28               # px da faixa de "mais colunas à direita"
LARGURA_GAVETA = 430                 # px dos detalhes do caso, a mesma largura da ficha no mapa
_BOLINHAS: dict = {}


def _bolinha(cor: str) -> QPixmap:
    """Marca da faixa de risco na célula (o texto fica na cor de texto; a cor fica no símbolo)."""
    if cor not in _BOLINHAS:
        pixmap = QPixmap(12, 12)
        pixmap.fill(Qt.GlobalColor.transparent)
        p = QPainter(pixmap)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(cor))
        p.drawEllipse(1, 1, 10, 10)
        p.end()
        _BOLINHAS[cor] = pixmap
    return _BOLINHAS[cor]


class ModeloPlanilhaVista(ModeloTabela):
    """As linhas tipadas de analise.LinhaPlanilha mostradas em TITULOS_PLANILHA (a ordem e o recorte de colunas da
    tela). Ordenação pelo valor cru (a faixa, pelo score); texto pelo formatador único e pelo vocabulário."""

    def __init__(self, parent=None):
        super().__init__(TITULOS_PLANILHA, lambda linha, j: getattr(linha, COLUNAS_PLANILHA[j]), paginado=True,
                         parent=parent)

    def texto(self, linha, j: int) -> str:
        k = analise.COLUNAS.index(COLUNAS_PLANILHA[j])    # o contexto da célula vem da linha inteira
        texto = formatos.celula(analise.TITULOS, lambda i: getattr(linha, analise.COLUNAS[i]), k, planilha=True)
        return vocabulario.celula(self.titulos[j], texto)

    def data(self, indice, papel=Qt.ItemDataRole.DisplayRole):
        if (papel == Qt.ItemDataRole.ToolTipRole and indice.isValid()
                and COLUNAS_PLANILHA[indice.column()] == "NIVEL_DE_RISCO"):   # o score só na dica
            linha = self._visiveis()[indice.row()]
            return (f"{vocabulario.rotulo(linha.NIVEL_DE_RISCO, 'faixa')} · score de risco "
                    f"{formatos.numero(linha.CRITICIDADE, 2)}")
        return super().data(indice, papel)

    def sort(self, coluna, ordem=Qt.SortOrder.AscendingOrder):
        """A faixa ordena pelo score (a ordem do risco); o código da faixa em ordem alfabética não é."""
        if not 0 <= coluna < len(COLUNAS_PLANILHA) or COLUNAS_PLANILHA[coluna] != "NIVEL_DE_RISCO":
            return super().sort(coluna, ordem)
        self.ultima_ordem = (coluna, ordem)
        self.beginResetModel()
        self.todas.sort(key=lambda l: l.CRITICIDADE, reverse=ordem == Qt.SortOrder.DescendingOrder)
        self.pagina = 0
        self.endResetModel()



def ModeloPlanilha(parent=None):  # noqa: N802
    return ModeloPlanilhaVista(parent)


def _coluna_campo(texto: str, widget, dica: str = "") -> QVBoxLayout:
    """Um campo de filtro: o rótulo acima do controle, com a definição na dica."""
    coluna = QVBoxLayout()
    coluna.setSpacing(2)
    coluna.addWidget(_campo(texto, dica))
    coluna.addWidget(widget)
    widget.setAccessibleName(texto)
    if dica and not widget.toolTip():
        widget.setToolTip(dica)
    return coluna


def _grupo_filtros(titulo: str, campos) -> QWidget:
    """Um grupo de filtros ("Onde", "O quê", "Por quê"): título e os campos lado a lado, cada um com o rótulo
    acima."""
    caixa = QWidget()
    caixa.setObjectName("grupoFiltro")
    caixa.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    caixa.setStyleSheet(f"#grupoFiltro {{ border:1px solid {cor_borda()}; border-radius:6px; }}")
    caixa.setAccessibleName(f"Filtros: {titulo}")
    v = QVBoxLayout(caixa)
    v.setContentsMargins(10, 5, 10, 8)
    v.setSpacing(3)
    rotulo = QLabel(titulo)
    rotulo.setStyleSheet(f"color:{'#F2F2F2' if isDarkTheme() else '#1A1A1A'}; font-size:12px; font-weight:600;")
    v.addWidget(rotulo)
    h = QHBoxLayout()
    h.setSpacing(8)
    for texto, widget, dica in campos:
        h.addLayout(_coluna_campo(texto, widget, dica))
    v.addLayout(h)
    caixa.titulo = rotulo
    return caixa


class _IndicadorDireita(QWidget):
    """Faixa na borda direita da tabela enquanto há colunas além da borda (a barra do Fluent só aparece com o mouse
    em cima): degradê até o fundo e uma seta. Não pega o mouse; some no fim da rolagem."""

    def __init__(self, tabela):
        super().__init__(tabela)
        self.tabela = tabela
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAccessibleName("Há mais colunas à direita")
        barra = tabela.horizontalScrollBar()
        barra.rangeChanged.connect(self.atualizar)
        barra.valueChanged.connect(self.atualizar)
        tabela.viewport().installEventFilter(self)
        self.hide()

    def eventFilter(self, objeto, evento):
        if evento.type() == evento.Type.Resize:
            self.atualizar()
        return False

    def atualizar(self, *_):
        area = self.tabela.viewport().geometry()           # do topo do cabeçalho ao fim das linhas
        self.setGeometry(area.right() - LARGURA_INDICADOR + 1, 0, LARGURA_INDICADOR, area.bottom() + 1)
        barra = self.tabela.horizontalScrollBar()
        self.setVisible(barra.value() < barra.maximum())
        self.raise_()

    def paintEvent(self, _):
        from PySide6.QtCore import QRect
        from PySide6.QtGui import QLinearGradient
        fundo = QColor("#2A2A2A" if isDarkTheme() else "#FAFAFA")    # o fundo do cartão da tabela
        transparente = QColor(fundo)
        transparente.setAlpha(0)
        degrade = QLinearGradient(0, 0, self.width(), 0)
        degrade.setColorAt(0, transparente)
        degrade.setColorAt(0.6, fundo)
        degrade.setColorAt(1, fundo)
        p = QPainter(self)
        p.fillRect(self.rect(), degrade)
        lado = 16
        FIF.CHEVRON_RIGHT_MED.render(p, QRect(self.width() - lado - 4, (self.height() - lado) // 2, lado, lado))
        p.end()


class PlanilhaAnalitica(QWidget):
    """Os casos um a um (N2: a própria UF; N3: o país). Filtros com rótulo de campo: busca e
    situação numa linha de topo, fora dos grupos (são o recorte geral, que vale também para o mapa); depois os
    grupos Onde (UF, município), o quê (classe, faixa de risco, atividade, etapa) e Por quê (motivo, ação). Os
    combos são vistas do filtro único: o mapa e a barra de chips acompanham, e "Limpar filtros" fica só
    na barra (um botão para a sessão inteira). A grade mostra as 9 colunas de decisão; Enter ou duplo
    clique na linha abre os detalhes do caso, com o resto, numa gaveta sobre a grade, e "Abrir no mapa"
    leva o caso ao mapa."""
    exportada = Signal(str)                                # SHA-256 do arquivo gravado
    abrir_caso = Signal(object)                            # pendência da gaveta (o contêiner abre a ficha no mapa)
    GRUPOS = ("Onde", "O quê", "Por quê")

    def __init__(self, tela, estado: EstadoFiltro | None = None, parent=None):
        super().__init__(parent)
        self.tela, self.painel, self._p_atual = tela, None, None
        self.estado = estado if estado is not None else EstadoFiltro(parent=self)
        self._base: list[analise.LinhaPlanilha] = []
        self._cod_atividade, self._cod_motivo = {}, {}
        self._municipios, self._uf_dos_municipios = {}, ""
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 8, 0, 0)
        v.setSpacing(8)
        self.busca = SearchLineEdit()
        self.busca.setPlaceholderText("Código, substância, classe, município, bairro, CEP…")
        self.busca.setMinimumWidth(300)
        self.busca.textChanged.connect(lambda texto: self.painel is not None and self.estado.definir(busca=texto))
        self.combo_uf = _combo([TODAS_UFS], 120)
        self.combo_municipio = _combo([TODOS_MUNICIPIOS], 200)
        self.combo_classe = _combo_vocabulario(TODAS_CLASSES, CLASSES, "classe", 180)
        self.combo_risco = _combo_vocabulario(TODOS_RISCOS, analise.CATEGORIAS, "faixa", 190)
        self.combo_atividade = _combo([TODAS_ATIVIDADES], 230)
        self.combo_motivo = _combo([TODOS_MOTIVOS], 240)
        self.combo_acao = _combo([TODAS_ACOES], 220)
        self.combo_etapa = _combo([TODAS_ETAPAS], 190)
        self.combo_situacao = _combo_situacao()
        self._vista_municipio = VistaCombo(
            self.combo_municipio, "municipios", TODOS_MUNICIPIOS,
            codigo=lambda nome: (self._uf_dos_municipios, nome) if self._uf_dos_municipios else None,
            texto=lambda par: par[1] if par[0] == self._uf_dos_municipios else "")
        self._vistas = (
            VistaCombo(self.combo_uf, "ufs", TODAS_UFS),
            self._vista_municipio,
            _vista_vocabulario(self.combo_classe, "classes", TODAS_CLASSES, "classe"),
            _vista_vocabulario(self.combo_risco, "riscos", TODOS_RISCOS, "faixa"),
            VistaCombo(self.combo_atividade, "atividades", TODAS_ATIVIDADES, codigo=self._cod_atividade.get,
                       texto=lambda c: vocabulario.rotulo(c, "atividade")),
            VistaCombo(self.combo_motivo, "motivos", TODOS_MOTIVOS, codigo=self._cod_motivo.get,
                       texto=lambda c: vocabulario.rotulo(c, "motivo")),
            _vista_vocabulario(self.combo_acao, "acoes", TODAS_ACOES, "acao"),
            _vista_vocabulario(self.combo_etapa, "etapas", TODAS_ETAPAS, "etapa"))
        self.combo_uf.currentIndexChanged.connect(self._uf_escolhida)
        for vista in self._vistas[1:]:
            vista.combo.currentIndexChanged.connect(
                lambda *_, vi=vista: self.painel is not None and self.estado.definir(**{vi.dimensao: vi.valor()}))
        self.combo_situacao.currentIndexChanged.connect(
            lambda indice: self.painel is not None and self.estado.definir(situacao=SITUACOES[max(0, indice)]))
        campo = vocabulario.titulo_coluna
        # etapa em "O quê" (em que pé está o caso) e ação em "Por quê" (a resposta ao motivo):
        self.grupos = {
            "Onde": _grupo_filtros("Onde", (
                ("UF", self.combo_uf, "A unidade da federação do caso."),
                ("Município", self.combo_municipio, "Escolha uma UF para listar os municípios dela."))),
            "O quê": _grupo_filtros("O quê", (
                (campo("CLASSE DE RISCO"), self.combo_classe, vocabulario.dica_coluna("CLASSE DE RISCO")),
                (campo("NIVEL DE RISCO"), self.combo_risco, vocabulario.dica_coluna("NIVEL DE RISCO")),
                (campo("ATIVIDADE"), self.combo_atividade, vocabulario.dica_coluna("ATIVIDADE")),
                (campo("ETAPA ATUAL"), self.combo_etapa, vocabulario.dica_coluna("ETAPA ATUAL")))),
            "Por quê": _grupo_filtros("Por quê", (
                (campo("MOTIVO"), self.combo_motivo, vocabulario.dica_coluna("MOTIVO")),
                (campo("ACAO RECOMENDADA"), self.combo_acao, "A providência que o caso exige agora."))),
        }
        from ecosec.interface.componentes.botao_exportar import BotaoExportar
        self.botao_csv = BotaoExportar("Exportar CSV", None, _janela_verificacao())
        self.botao_xlsx = BotaoExportar("Exportar XLSX", None, _janela_verificacao())
        for botao, extensao in ((self.botao_csv, "csv"), (self.botao_xlsx, "xlsx")):
            botao.clicked.connect(lambda *_, e=extensao: self.exportar(e))
        topo = QHBoxLayout()
        topo.setSpacing(10)
        topo.addLayout(_coluna_campo("Buscar", self.busca, "Procura o texto no código, na substância, na classe, no "
                                                           "município, no bairro, no logradouro e no CEP."))
        topo.addLayout(_coluna_campo(vocabulario.CAMPO_SITUACAO, self.combo_situacao, DICA_SITUACAO))
        topo.addStretch(1)
        for botao in (self.botao_csv, self.botao_xlsx):
            topo.addWidget(botao, 0, Qt.AlignmentFlag.AlignBottom)
        v.addLayout(topo)
        self.aviso = CaptionLabel()
        self.aviso.setWordWrap(True)
        # os três grupos lado a lado não cabem em 1500 px sem espremer os combos: "Por quê" desce;
        # o aviso de exportação fica com a sobra à direita dele, sem linha própria
        for nomes in (("Onde", "O quê"), ("Por quê",)):
            linha = QHBoxLayout()
            linha.setSpacing(10)
            for nome in nomes:
                linha.addWidget(self.grupos[nome])
            if nomes == ("Por quê",):
                linha.addSpacing(6)
                linha.addWidget(self.aviso, 1, Qt.AlignmentFlag.AlignVCenter)
            else:
                linha.addStretch(1)
            v.addLayout(linha)
        self.modelo = ModeloPlanilha(self)
        self.tabela = _tabela(self.modelo)
        self.tabela.setIconSize(QSize(12, 12))
        self.tabela.activated.connect(self._mostrar_detalhes)     # Enter ou duplo clique na linha
        self.tabela.selectionModel().currentRowChanged.connect(self._acompanhar)
        self.tabela.viewport().installEventFilter(self)      # o motivo acompanha a largura
        self.indicador_direita = _IndicadorDireita(self.tabela)
        # a tabela numa área própria: a gaveta dos detalhes fica sobreposta a ela (não é coluna: a grade mantém a
        # largura e as 9 colunas, e os filtros continuam à vista)
        self.area_tabela = QWidget()
        at = QVBoxLayout(self.area_tabela)
        at.setContentsMargins(0, 0, 0, 0)
        at.addWidget(self.tabela)
        v.addWidget(self.area_tabela, 1)
        self._montar_gaveta()
        rodape = QHBoxLayout()
        self.total = CaptionLabel()
        self.anterior, self.proxima = PushButton("Anterior"), PushButton("Próxima")
        self.anterior.setIcon(FIF.LEFT_ARROW)
        self.proxima.setIcon(FIF.RIGHT_ARROW)
        self.anterior.clicked.connect(lambda *_: self._ir(-1))
        self.proxima.clicked.connect(lambda *_: self._ir(+1))
        self.rotulo_pagina = BodyLabel()
        rodape.addWidget(self.total)
        rodape.addStretch(1)
        for w in (self.anterior, self.rotulo_pagina, self.proxima):
            rodape.addWidget(w)
        v.addLayout(rodape)
        self.estado.mudou.connect(self._filtro_mudou)

    def _montar_gaveta(self):
        """Detalhes do caso: a mesma ficha do mapa (n23_ficha.FichaTecnica, outra instância, sem estado em
        comum) numa gaveta sobre a grade, com "Abrir no mapa" no cabeçalho, ao lado do ✕. Fecha com Esc ou com o ✕.
        Aqui o bloco Local vem primeiro, para o endereço aparecer sem rolar (a grade
        já mostra etapa, prazo e ação); a ficha do mapa mantém a ordem dela."""
        from ecosec.interface.componentes.painel_deslizante import PainelDeslizante
        from ecosec.interface.n23_ficha import FichaTecnica
        self.gaveta = PainelDeslizante(self.area_tabela, LARGURA_GAVETA)
        self.gaveta.titulo.setText("Detalhes do caso")
        self.gaveta.abas.hide()                              # uma página só: sem abas
        self.gaveta.fechado.connect(lambda: self.tabela.setFocus())    # o teclado volta à grade
        self.botao_abrir_no_mapa = PushButton("Abrir no mapa")
        self.botao_abrir_no_mapa.setIcon(FIF.GLOBE)
        self.botao_abrir_no_mapa.setToolTip("Abre a aba do mapa com a ficha deste caso e enquadra o ponto.")
        self.botao_abrir_no_mapa.clicked.connect(
            lambda *_: self._p_atual is not None and self.abrir_caso.emit(self._p_atual))
        cabeca = next(item.layout() for item in (self.gaveta.layout().itemAt(i)
                                                 for i in range(self.gaveta.layout().count()))
                      if item.layout() is not None and item.layout().indexOf(self.gaveta.botao_fechar) >= 0)
        cabeca.insertWidget(cabeca.indexOf(self.gaveta.botao_fechar), self.botao_abrir_no_mapa)
        rolagem = ScrollArea()
        rolagem.setWidgetResizable(True)
        rolagem.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        rolagem.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        self.ficha_tecnica = FichaTecnica()
        self.ficha_tecnica.setObjectName("fichaTecnica")
        self.ficha_tecnica.setStyleSheet("#fichaTecnica { background: transparent; }")
        blocos = self.ficha_tecnica.layout()
        local = self.ficha_tecnica.blocos["local"]
        blocos.removeWidget(local)
        blocos.insertWidget(blocos.indexOf(self.ficha_tecnica.blocos["situacao"]), local)
        rolagem.setWidget(self.ficha_tecnica)
        rolagem.viewport().setStyleSheet("background: transparent;")
        self.gaveta.adicionar_aba("dados", "Detalhes do caso", rolagem)

    def _preencher(self, combo, todos, itens):
        combo.blockSignals(True)
        combo.clear()
        combo.addItems([todos, *itens])
        combo.blockSignals(False)

    def carregar(self, painel):
        self.painel, self._p_atual = None, None
        self.gaveta.fechar()                                 # o caso da sessão anterior não fica aberto
        self._base = analise.linhas(painel.pendencias, painel.hoje, painel.regras, painel.atividades, painel.motivos)
        self._cod_atividade.clear()
        self._cod_atividade.update({vocabulario.rotulo(c, "atividade"): c for c in sorted(painel.atividades)})
        self._cod_motivo.clear()
        self._cod_motivo.update({vocabulario.rotulo(c, "motivo"): c for c in sorted(painel.motivos)})
        self._municipios = {uf: sorted({p.municipio for p in painel.pendencias if p.uf == uf})
                            for uf in {p.uf for p in painel.pendencias}}
        self._preencher(self.combo_uf, TODAS_UFS, sorted(self._municipios))
        self._preencher(self.combo_atividade, TODAS_ATIVIDADES, list(self._cod_atividade))    # na ordem do código
        self._preencher(self.combo_motivo, TODOS_MOTIVOS, list(self._cod_motivo))
        etapas = {p.etapa_atual for p in painel.pendencias}
        self._preencher(self.combo_etapa, TODAS_ETAPAS, [vocabulario.rotulo(e, "etapa") for e in sorted(etapas)])
        for botao in (self.botao_csv, self.botao_xlsx):
            botao.definir_sessao(self.tela.sessao)
        self._preencher(self.combo_acao, TODAS_ACOES, [vocabulario.rotulo(a, "acao") for a in acoes()
                                                       if a in {l.ACAO_RECOMENDADA for l in self._base}])
        for botao in (self.botao_csv, self.botao_xlsx):
            botao.setVisible(painel.exporta)
        self.aviso.setText(
            "Exportação: CSV ou XLSX dos casos filtrados (todas as páginas), com as colunas completas. O SHA-256 do "
            "arquivo fica na trilha." if painel.exporta else
            "Só visualização: este acesso não exporta.")
        self.aviso.setStyleSheet(f"color:{cor_texto_secundario() if painel.exporta else '#D2384F'};")
        self._uf_dos_municipios = None
        self.painel = painel
        self._filtro_mudou(self.estado.filtro)

    # ------------------------------------------------------------ município (o par UF, nome), como no mapa
    def _uf_da_lista(self, filtro) -> str:
        if len(filtro.ufs) == 1:
            return next(iter(filtro.ufs))
        ufs_municipios = {uf for uf, _ in filtro.municipios}
        if not filtro.ufs and len(ufs_municipios) == 1:
            return next(iter(ufs_municipios))
        return next(iter(self._municipios)) if len(self._municipios) == 1 else ""

    def _preencher_municipios(self, uf: str):
        self._uf_dos_municipios = uf
        self._preencher(self.combo_municipio, TODOS_MUNICIPIOS, self._municipios.get(uf, []))
        self.combo_municipio.setEnabled(bool(uf))

    def _uf_escolhida(self, *_):
        if self.painel is None:
            return
        uf = self._vistas[0].valor()
        self.estado.definir(ufs=uf, municipios=frozenset(m for m in self.estado.filtro.municipios
                                                         if uf and m[0] in uf))

    def limpar_filtros(self, *_):
        self.estado.limpar()

    def filtrar_por(self, risco: str | None = None, atividade: str | None = None):
        """Atalho do gráfico: ACRESCENTA a faixa (e a atividade) ao filtro único, sem apagar os outros filtros."""
        mudancas = {}
        if risco:
            mudancas["riscos"] = {risco}
        if atividade:
            mudancas["atividades"] = {atividade}
        if mudancas:
            self.estado.definir(**mudancas)

    def _descricao_filtros(self) -> str:
        painel = self.painel
        return "; ".join(r for _, _, r in self.estado.filtro.chips(painel.atividades if painel else None,
                                                                  painel.motivos if painel else None))

    def filtrar(self, *_):
        """Lê todos os combos e a busca da planilha para o filtro único (o resto do filtro fica como está)."""
        if self.painel is None:
            return
        mudancas = {vista.dimensao: vista.valor() for vista in self._vistas}
        self.estado.definir(**mudancas, situacao=SITUACOES[max(0, self.combo_situacao.currentIndex())],
                            busca=self.busca.text())

    def _filtro_mudou(self, filtro):
        if self.painel is None:
            return
        uf_lista = self._uf_da_lista(filtro)
        if uf_lista != self._uf_dos_municipios:
            self._preencher_municipios(uf_lista)
        for vista in self._vistas:
            vista.mostrar(filtro)
        self.combo_situacao.blockSignals(True)
        self.combo_situacao.setCurrentIndex(SITUACOES.index(filtro.situacao))
        self.combo_situacao.blockSignals(False)
        if self.busca.text() != filtro.busca:
            self.busca.blockSignals(True)
            self.busca.setText(filtro.busca)
            self.busca.blockSignals(False)
        codigos = {p.codigo for p in recorte(self.painel, filtro)}
        self.modelo.definir([l for l in self._base if l.CODIGO in codigos])
        if self.modelo.ultima_ordem:                         # a ordenação escolhida sobrevive ao filtro
            self.modelo.sort(*self.modelo.ultima_ordem)
        self.tabela.resizeColumnsToContents()
        self._ajustar_motivo()
        self._atualizar_rodape()

    def eventFilter(self, objeto, evento):
        if objeto is self.tabela.viewport() and evento.type() == evento.Type.Resize:
            self._ajustar_motivo()
        return False

    def _ajustar_motivo(self):
        """A última coluna (motivo) fica com a sobra da largura, até a borda; abaixo de MINIMO_MOTIVO a grade rola e
        o texto cortado fica inteiro na dica."""
        cabecalho = self.tabela.horizontalHeader()
        j = cabecalho.count() - 1
        if j > 0:
            outras = sum(cabecalho.sectionSize(k) for k in range(j))
            cabecalho.resizeSection(j, max(MINIMO_MOTIVO, self.tabela.viewport().width() - outras))

    def _mostrar_detalhes(self, indice):
        """Enter ou duplo clique na linha: a gaveta com a ficha do caso, sem sair da planilha (o
        duplo clique levava ao mapa, que agora fica no botão "Abrir no mapa")."""
        from ecosec.acervo import regras
        if self.painel is None or not indice.isValid():
            return
        codigo = self.modelo._visiveis()[indice.row()].CODIGO
        if self.gaveta.aberto and self._p_atual is not None and self._p_atual.codigo == codigo:
            return                                           # o duplo clique depois do clique: o caso já está aqui
        self._p_atual = next(p for p in self.painel.pendencias if p.codigo == codigo)
        self.ficha_tecnica.mostrar(self._p_atual, self.painel, self.painel.regras or regras.ParametrosRegras.padrao())
        if not self.gaveta.aberto:
            self.gaveta.abrir()                              # abrir leva o foco à gaveta; aberta, o foco fica na grade

    def _acompanhar(self, atual, _anterior):
        """Com a gaveta aberta, o clique (ou a seta) em outra linha troca o caso, como num painel lateral; com ela
        fechada, a linha só fica selecionada."""
        if self.gaveta.aberto:
            self._mostrar_detalhes(atual)

    def _ir(self, passo: int):
        self.modelo.ir(self.modelo.pagina + passo)
        self._atualizar_rodape()

    def _atualizar_rodape(self):
        n = len(self.modelo.todas)
        situacao = vocabulario.ADJETIVO_SITUACAO[self.estado.filtro.situacao]
        self.total.setText(f"{vocabulario.casos(n, situacao)}"
                           + (f" de {formatos.inteiro(len(self._base))} no cadastro" if n != len(self._base) else "")
                           + f" · corte {self.estado.filtro.corte(self.painel.hoje):%d/%m/%Y}" if self.painel else "")
        self.rotulo_pagina.setText(f"Página {self.modelo.pagina + 1} de {self.modelo.paginas}")
        self.anterior.setEnabled(self.modelo.pagina > 0)
        self.proxima.setEnabled(self.modelo.pagina < self.modelo.paginas - 1)
        for botao in (self.botao_csv, self.botao_xlsx):
            botao.setEnabled(n > 0)
            botao.atualizar()

    def exportar(self, extensao: str):
        if self.painel is None or not self.modelo.todas:
            return
        destino = _caminho_exportacao(self, extensao,
                                      f"PLANILHA_{self.tela.usuario.matricula}_{date.today():%Y%m%d}.{extensao}")
        if destino is None:
            return
        codigos, filtros = [l.CODIGO for l in self.modelo.todas], self._descricao_filtros()
        try:
            resumo = self.tela.exportar_com_verificacao(
                lambda verificado_em: self.tela.app.acervo.exportar_planilha(
                    self.painel, self.tela.usuario, codigos, destino, filtros, risco=self.tela.risco,
                    verificado_em=verificado_em))
        except Exception as erro:  # noqa: BLE001
            InfoBar.error("Exportação recusada", _mensagem(erro), duration=6000, position=InfoBarPosition.TOP,
                          parent=self.tela)
            return
        if resumo is None:
            InfoBar.warning("Exportação cancelada", "Sem a conferência do rosto, o arquivo não sai.", duration=5000,
                            position=InfoBarPosition.TOP, parent=self.tela)
            return
        InfoBar.success("Planilha exportada", f"{destino.name}: SHA-256 {resumo[:12]}… registrado na trilha.",
                        duration=6000, position=InfoBarPosition.TOP, parent=self.tela)
        for botao in (self.botao_csv, self.botao_xlsx):
            botao.atualizar()
        self.exportada.emit(resumo)


# ================================================================ resumo agregado (todos os níveis)
def filtro_do_resumo(filtro):
    """O recorte que o resumo pede ao serviço. O resumo é ESTOQUE, como os indicadores: com a situação Todos
    (o padrão) ele conta os casos ATIVOS do recorte, porque as medidas dele (prazo vencido,
    além do prazo legal, críticos, atraso, custo) são definidas sobre os ativos. Com Encerrados, os encerrados
    (como antes). Sem nenhuma outra restrição, None: o resumo inteiro dos ativos."""
    from ecosec.acervo.filtro import Filtro
    efetivo = filtro if filtro.situacao == "ENCERRADAS" else filtro.com(situacao="ATIVAS")
    return None if efetivo == Filtro(situacao="ATIVAS") else efetivo


TOTAL = "Total"
_SOMAVEIS = ("PENDENCIAS", analise.FORA_DA_PREVISAO, analise.CRITICAS, *analise.COLUNA_DA_CLASSE.values(),
             analise.ALEM_DO_PRAZO, "CUSTO ESTIMADO")


def linha_total(titulos, linhas) -> list | None:
    """A linha "Total" do resumo do N2 e do N3 (sem k): contagens, quantidades e custo somados das linhas do serviço;
    percentuais refeitos das somas (nunca média de percentuais); atraso médio dos vencidos ponderado pelos vencidos
    de cada grupo. Com algum SUPRIMIDO (N1) não há total: a soma das linhas visíveis não é o total protegido."""
    if not linhas or any(v == analise.SUPRIMIDO for l in linhas for v in l):
        return None
    titulos = list(titulos)
    n_chaves = titulos.index("PENDENCIAS")
    total = [TOTAL] + [""] * (n_chaves - 1)
    soma = {t: sum(l[titulos.index(t)] for l in linhas) for t in _SOMAVEIS if t in titulos}
    for t in titulos[n_chaves:]:
        if t in soma:
            total.append(round(soma[t], 2) if isinstance(soma[t], float) else soma[t])
        elif t == analise.PERCENTUAL_FORA_DA_PREVISAO:
            total.append(round(100 * soma[analise.FORA_DA_PREVISAO] / soma["PENDENCIAS"], 1) if soma["PENDENCIAS"]
                         else 0.0)
        elif t == analise.PERCENTUAL_ALEM_DO_PRAZO:
            total.append(round(100 * soma[analise.ALEM_DO_PRAZO] / soma["PENDENCIAS"], 1) if soma["PENDENCIAS"]
                         else 0.0)
        elif t == analise.ATRASO_FORA_DA_PREVISAO:
            i_f, i_a = titulos.index(analise.FORA_DA_PREVISAO), titulos.index(t)
            vencidos = sum(l[i_f] for l in linhas)
            total.append(round(sum(l[i_a] * l[i_f] for l in linhas) / vencidos) if vencidos else 0)
        else:
            total.append("")
    return total


class ModeloResumo(ModeloTabela):
    """As linhas do serviço e, no N2 e no N3, a linha Total fixa no fim (fora da ordenação), em negrito."""

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.total = None

    def definir(self, linhas, titulos=None, total=None):
        self.total = total
        super().definir(linhas, titulos)

    def rowCount(self, pai=QModelIndex()):
        return 0 if pai.isValid() else len(self._visiveis()) + (1 if self.total else 0)

    def _linha(self, i: int):
        visiveis = self._visiveis()
        return visiveis[i] if i < len(visiveis) else self.total

    def data(self, indice, papel=Qt.ItemDataRole.DisplayRole):
        if not indice.isValid():
            return None
        if indice.row() < len(self._visiveis()):
            return super().data(indice, papel)
        linha, j = self.total, indice.column()
        if papel == Qt.ItemDataRole.DisplayRole:
            return self.texto(linha, j)
        if papel == Qt.ItemDataRole.FontRole:
            f = QFont()
            f.setBold(True)
            return f
        if papel == Qt.ItemDataRole.TextAlignmentRole and isinstance(linha[j], (int, float)):
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if papel == Qt.ItemDataRole.ToolTipRole:
            return ("Total do recorte: soma das linhas; percentuais refeitos das somas; atraso médio ponderado pelos "
                    "vencidos de cada grupo (cada média de grupo vem arredondada ao dia).")
        return None

    def texto(self, linha, j: int) -> str:
        if linha is self.total and linha is not None:
            valor = linha[j]
            if valor == "" or (j == 0 and valor == TOTAL):
                return valor
            return formatos.exibir(self.titulos[j], valor)
        return super().texto(linha, j)


class ResumoAgregado(QWidget):
    def __init__(self, tela, parent=None):
        super().__init__(parent)
        self.tela, self.resumo = tela, None
        self._codigos: tuple = ()
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 8, 0, 0)
        linha = QHBoxLayout()
        self.combo = _combo([], 280)
        self.combo.setAccessibleName("Agrupamento")
        self.combo.currentIndexChanged.connect(self.mostrar)
        linha.addWidget(_campo("Agrupamento", "Como os casos são agrupados nas linhas da tabela."))
        linha.addWidget(self.combo)
        linha.addSpacing(12)
        linha.addStretch(1)
        self.botao_csv = PushButton("Exportar CSV")
        self.botao_xlsx = PushButton("Exportar XLSX")
        for botao, extensao in ((self.botao_csv, "csv"), (self.botao_xlsx, "xlsx")):
            botao.setIcon(FIF.SAVE)
            botao.clicked.connect(lambda *_, e=extensao: self.exportar(e))
            linha.addWidget(botao)
        v.addLayout(linha)
        self.aviso = CaptionLabel()
        self.aviso.setWordWrap(True)
        v.addWidget(self.aviso)
        self.aviso_filtro = CaptionLabel()
        self.aviso_filtro.setWordWrap(True)
        self.aviso_filtro.setStyleSheet(f"color:{cor_texto_secundario()};")
        self.aviso_filtro.hide()
        v.addWidget(self.aviso_filtro)
        self.modelo = ModeloResumo()
        self.tabela = _tabela(self.modelo)
        v.addWidget(self.tabela, 1)
        self.total = CaptionLabel()
        v.addWidget(self.total)
        self._filtro = None

    @property
    def agrupamento(self) -> str:
        """O código do agrupamento escolhido (o combo mostra o rótulo do vocabulário)."""
        i = self.combo.currentIndex()
        return self._codigos[i] if 0 <= i < len(self._codigos) else ""

    def carregar(self, resumo, filtro=None):
        """`filtro`: o recorte com que o serviço agregou (N2 e N3). O N1 nunca recebe filtro: o aviso diz."""
        self.resumo, self._filtro = resumo, filtro
        if resumo.nivel is Nivel.N1:
            self.aviso_filtro.setText("Totais sem filtro; números muito pequenos ficam ocultos para proteger poucos "
                                      "casos.")
        elif filtro is not None and filtro.situacao == "ENCERRADAS":
            self.aviso_filtro.setText("Resumo dos casos encerrados do recorte filtrado: os totais seguem os filtros "
                                      "acima.")
        elif filtro is not None and not filtro.vazio():
            self.aviso_filtro.setText("Resumo dos casos ativos do recorte filtrado: os totais seguem os filtros "
                                      "acima (com a situação Todos, o resumo conta os ativos, como os indicadores).")
        else:
            self.aviso_filtro.setText("Resumo dos casos ativos (como os indicadores).")
        self.aviso_filtro.setVisible(bool(self.aviso_filtro.text()))
        for botao in (self.botao_csv, self.botao_xlsx):
            botao.setVisible(resumo.exporta)
        self.aviso.setText(
            ("Totais por grupo, sem nenhum registro individual nem localização. " +
             ("Exportação livre (nível 1); o SHA-256 do arquivo fica na trilha." if resumo.nivel is Nivel.N1 else
              "Exportação com rastreio: quem, quando e o SHA-256 do arquivo ficam na trilha." if resumo.exporta else
              "Só visualização: este acesso não exporta.")))
        self.aviso.setStyleSheet(f"color:{cor_texto_secundario() if resumo.exporta else '#D2384F'};")
        self._preencher_agrupamentos(resumo)
        self.mostrar()

    def agrupamentos(self, resumo) -> tuple:
        """No N2 (uma UF só), POR UF e POR REGIAO sairiam com uma linha: não são oferecidos."""
        if resumo.nivel is Nivel.N2:
            return tuple(g for g in analise.AGRUPAMENTOS if g not in ("POR UF", "POR REGIAO"))
        return analise.AGRUPAMENTOS

    def _preencher_agrupamentos(self, resumo):
        itens = self.agrupamentos(resumo)
        if itens == self._codigos:
            return
        atual = self.agrupamento
        self.combo.blockSignals(True)
        self.combo.clear()
        self.combo.addItems([vocabulario.ROTULO_AGRUPAMENTO.get(g, g) for g in itens])
        self._codigos = tuple(itens)
        self.combo.setCurrentIndex(itens.index(atual) if atual in itens else 0)
        self.combo.blockSignals(False)

    def mostrar(self, *_):
        if self.resumo is None or self.agrupamento not in self.resumo.tabelas:
            return
        titulos, linhas = self.resumo.tabelas[self.agrupamento]
        total = None if self.resumo.nivel is Nivel.N1 else linha_total(titulos, linhas)
        self.modelo.definir(linhas, titulos, total)
        self.tabela.resizeColumnsToContents()
        # o cabeçalho nunca fica cortado: a coluna cabe o título inteiro e o indicador de ordenação
        cabecalho = self.tabela.horizontalHeader()
        medida = cabecalho.fontMetrics()
        for j, titulo in enumerate(titulos):
            minimo = medida.horizontalAdvance(vocabulario.titulo_coluna(titulo)) + 44
            if cabecalho.sectionSize(j) < minimo:
                cabecalho.resizeSection(j, minimo)
        contagens = [l[titulos.index("PENDENCIAS")] for l in linhas]
        n = sum(v for v in contagens if isinstance(v, int))
        tapadas = sum(not isinstance(v, int) for v in contagens)
        aviso = f" · {tapadas} grupos ocultos para proteger poucos casos" if tapadas else ""
        self.total.setText(f"{len(linhas)} grupos · {formatos.inteiro(n)} casos nos grupos visíveis · escopo "
                           f"{self.resumo.escopo}{aviso}")


    def exportar(self, extensao: str):
        if self.resumo is None:
            return
        agrupamento = self.agrupamento
        nome = agrupamento.replace(" ", "_")
        destino = _caminho_exportacao(self, extensao, f"RESUMO_{nome}_{date.today():%Y%m%d}.{extensao}")
        if destino is None:
            return
        try:
            resumo = self.tela.exportar_com_verificacao(
                lambda verificado_em: self.tela.app.acervo.exportar_resumo(
                    self.resumo, self.tela.usuario, agrupamento, destino, risco=self.tela.risco,
                    verificado_em=verificado_em))
        except Exception as erro:  # noqa: BLE001
            InfoBar.error("Exportação recusada", _mensagem(erro), duration=6000, position=InfoBarPosition.TOP,
                          parent=self.tela)
            return
        if resumo is None:
            return
        InfoBar.success("Resumo exportado", f"{destino.name}: SHA-256 {resumo[:12]}… registrado na trilha.",
                        duration=6000, position=InfoBarPosition.TOP, parent=self.tela)


# ================================================================ contêiner
class PainelAnalitico(QWidget):
    """As seções de cada nível: N1 = panorama, resumo e glossário; N2 = mapa da UF, painéis da UF, planilha,
    resumo e glossário; N3 = mapa, priorização, custo por responsável, planilha, resumo e glossário. No N2 e no
    N3, um filtro único (EstadoFiltro) e a barra de chips acima das abas que o seguem (mapa, planilha e resumo).
    "Painéis temáticos" e "Evolução" saíram do N3; o Glossário entrou em todos os
    níveis (17.4); o panorama do N1 não tem custo (17.5)."""

    SECOES = (("panorama", "Painéis temáticos"), ("mapa", "Mapa interativo"), ("paineis_uf", "Painéis da UF"),
              ("orcamento", "Priorização"), ("responsaveis", "Custo por responsável"),
              ("planilha", "Planilha analítica"), ("agregado", "Resumo agregado"), ("glossario", "Glossário"))
    # /: o N2 tem os Painéis da UF (n23_paineis_uf: decisão na própria UF, sem k)
    DO_NIVEL = {Nivel.N1: ("panorama", "agregado", "glossario"),
                Nivel.N2: ("mapa", "paineis_uf", "planilha", "agregado", "glossario"),
                Nivel.N3: ("mapa", "orcamento", "responsaveis", "planilha", "agregado", "glossario")}
    SEGUEM_O_FILTRO = ("mapa", "planilha", "agregado")                 # a barra aparece só nestas abas
    PAINEIS_N1 = ("classe", "uf", "encerramento")                      # sem "custo": N1 sem dado financeiro
    ESPERA_RESUMO_MS = 350                                             # debounce da recarga do resumo

    def __init__(self, tela, parent=None):
        super().__init__(parent)
        from ecosec.interface.componentes.barra_filtros import BarraFiltros
        self.tela = tela
        self.painel = self.resumo = None
        self.estado = EstadoFiltro(parent=self)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        cabeca = QHBoxLayout()
        self.titulo = StrongBodyLabel()
        cabeca.addWidget(self.titulo)
        cabeca.addStretch(1)
        self.abas = SegmentedWidget()
        cabeca.addWidget(self.abas)
        v.addLayout(cabeca)
        self.barra = BarraFiltros(self.estado)
        v.addWidget(self.barra)
        self.pilha = QStackedWidget()
        from ecosec.interface.glossario import PainelGlossario
        from ecosec.interface.n1_painel import PainelN1
        self.panorama = PainelN1(tela)                     # O painel por perguntas do N1 (sem custo)
        from ecosec.interface.n23_paineis_uf import PaineisUF
        self.paineis_uf = PaineisUF(tela)                  # O painel de decisão da UF (N2)
        self.paineis_uf.abrir_caso.connect(self._abrir_caso_no_mapa)
        self.mapa = MapaInterativo(tela, self.estado)
        self.orcamento = PriorizacaoOrcamento(tela)
        self.planilha, self.agregado = PlanilhaAnalitica(tela, self.estado), ResumoAgregado(tela)
        self.planilha.abrir_caso.connect(self._abrir_caso_no_mapa)
        self.responsaveis = CustoPorResponsavel(tela)
        self.glossario = PainelGlossario(tela.nivel)
        self.paginas = {"panorama": self.panorama, "mapa": self.mapa, "paineis_uf": self.paineis_uf,
                        "orcamento": self.orcamento, "responsaveis": self.responsaveis, "planilha": self.planilha,
                        "agregado": self.agregado, "glossario": self.glossario}
        for widget in self.paginas.values():
            cartao = SimpleCardWidget()
            vc = QVBoxLayout(cartao)
            vc.setContentsMargins(14, 10, 14, 12)
            vc.addWidget(widget)
            self.pilha.addWidget(cartao)
            widget.setProperty("cartao", cartao)
        v.addWidget(self.pilha, 1)
        self._espera_resumo = QTimer(self)
        self._espera_resumo.setSingleShot(True)
        self._espera_resumo.setInterval(self.ESPERA_RESUMO_MS)
        self._espera_resumo.timeout.connect(self._recarregar_resumo)
        self.estado.mudou.connect(self._filtro_mudou)        # depois das vistas: elas já se atualizaram

    @property
    def carregado(self) -> bool:
        return self.resumo is not None

    def _reiniciar_filtro(self):
        """Sessão nova: filtro vazio, sem avisar as vistas (cada `carregar` lê o estado)."""
        self._espera_resumo.stop()
        self.estado.blockSignals(True)
        self.estado.limpar()
        self.estado.blockSignals(False)
        self.barra.sincronizar()

    def carregar(self):
        """Pede os dados ao serviço (cada consulta fica na trilha) e prepara as seções do nível."""
        nivel = self.tela.nivel
        self.painel = None
        self._reiniciar_filtro()
        self.resumo = self.tela.app.acervo.resumo_agregado(self.tela.usuario, nivel)
        self.agregado.carregar(self.resumo)
        if "panorama" in self.DO_NIVEL[nivel]:
            self.panorama.carregar()
        if nivel >= Nivel.N2:
            self.painel = self.tela.app.acervo.painel(self.tela.usuario, nivel)
            self.barra.definir_catalogos(self.painel.atividades, self.painel.motivos)
            self.planilha.carregar(self.painel)
            self.mapa.carregar(self.painel)
            if "paineis_uf" in self.DO_NIVEL[nivel]:
                self.paineis_uf.carregar(self.painel, self.resumo)
            if nivel is Nivel.N3:
                self.orcamento.carregar(self.painel)
                self.responsaveis.carregar(self.painel)
            self._atualizar_contagem(self.estado.filtro)
        else:
            # no N1 não há registros individuais: o total vem do resumo (coluna PENDENCIAS do agrupamento por
            # UF); linha SUPRIMIDO (k=3) não entra na soma
            ativas = sum(l[1] for l in self.resumo.tabelas["POR UF"][1] if isinstance(l[1], int))
            self.titulo.setText(f"Casos ativos em {self.resumo.hoje:%d/%m/%Y}: {formatos.inteiro(ativas)} · "
                                f"escopo {self.resumo.escopo}")
        self.abas.clear()
        secoes = [(c, t) for c, t in self.SECOES if c in self.DO_NIVEL[nivel]]
        for chave, texto in secoes:
            self.abas.addItem(chave, texto, onClick=lambda *_, c=chave: self.mostrar(c))   # o clique passa "checked"
        self.abas.setVisible(len(secoes) > 1)
        self.mostrar(secoes[0][0])

    # ------------------------------------------------------------ filtro único
    def _filtro_mudou(self, filtro):
        if self.painel is None:
            return
        self._atualizar_contagem(filtro)
        self._espera_resumo.start()                         # o resumo é uma consulta ao serviço: com espera

    def _atualizar_contagem(self, filtro):
        """Barra: N dentro · M fora (de T registros do painel). Cabeçalho: só o estoque ativo na data do
        corte do filtro, sem misturar com o cadastro acumulado."""
        painel = self.painel
        corte = filtro.corte(painel.hoje)
        # "fora" no mesmo universo que o mapa e a planilha mostram: a situação e o corte do filtro (ex.: as
        # ativas na data). Contar contra o cadastro inteiro dava dois "fora" diferentes na mesma tela.
        from ecosec.acervo.filtro import Filtro
        universo = len(Filtro(situacao=filtro.situacao, ano=filtro.ano).aplicar(painel.pendencias, painel.hoje,
                                                                                painel.regras))
        dentro = len(recorte(painel, filtro))
        self.barra.definir_contagem(dentro, universo - dentro, universo)
        self.barra.definir_texto_contagem(
            f"{dentro:,} dentro · {universo - dentro:,} fora (de {universo:,} "
            f"{vocabulario.FRASE_SITUACAO[filtro.situacao]} em {corte:%d/%m/%Y})".replace(",", "."))
        ativas = sum(p.ativa(corte) for p in painel.pendencias)    # o cabeçalho é sempre o estoque ativo (KPIs)
        self.titulo.setText(f"Casos ativos em {corte:%d/%m/%Y}: {formatos.inteiro(ativas)} · escopo {painel.escopo}")

    def _recarregar_resumo(self):
        """Resumo do N2 e do N3 com o filtro corrente, pelo serviço (que agrega e registra os chips na trilha).
        O N1 não passa por aqui: o resumo dele não aceita filtro."""
        self._espera_resumo.stop()
        if self.painel is None or self.tela.nivel is Nivel.N1:
            return
        filtro = self.estado.filtro
        try:
            self.resumo = self.tela.app.acervo.resumo_agregado(self.tela.usuario, self.tela.nivel,
                                                               filtro=filtro_do_resumo(filtro))
        except Exception as erro:  # noqa: BLE001
            InfoBar.error("Resumo indisponível", _mensagem(erro), duration=5000, position=InfoBarPosition.TOP,
                          parent=self.tela)
            return
        self.agregado.carregar(self.resumo, filtro)

    def mostrar(self, chave: str):
        if chave not in self.DO_NIVEL[self.tela.nivel]:
            # seção que o nível não tem: a página não abre. No custo por responsável, a tentativa vai ao serviço,
            # que nega pela matriz e a registra na trilha (a tela reforça; quem decide é o serviço)
            if chave == "responsaveis" and self.painel is not None:
                self.responsaveis.carregar(self.painel)
            InfoBar.error("Seção indisponível", "Esta seção não existe no seu nível de acesso.", duration=4000,
                          position=InfoBarPosition.TOP, parent=self.tela)
            return
        self.pilha.setCurrentWidget(self.paginas[chave].property("cartao"))
        self.abas.setCurrentItem(chave)
        self.barra.setVisible(self.painel is not None and chave in self.SEGUEM_O_FILTRO)

    def _abrir_caso_no_mapa(self, p):
        """Painéis da UF (duplo clique num caso) e planilha ("Abrir no mapa" da gaveta): a aba do mapa com a ficha e
        o ponto enquadrado."""
        self.mostrar("mapa")
        self.mapa.mostrar_ficha(p)
        self.mapa.mapa.ir_para_ponto(p.longitude, p.latitude)

    def limpar(self):
        self.painel = self.resumo = None
        self._reiniciar_filtro()
        self.planilha.modelo.definir([])
        self.agregado.modelo.definir([])
