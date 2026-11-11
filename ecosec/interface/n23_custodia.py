"""Abas de decisão nacional do N3: Priorização e Custo por responsável, no padrão de precisão
da camada: valor exato com unidade, base (n), data de corte, totais que fecham e comparação.

Priorização (o orçamento público nacional): cartões com o que o orçamento compra (casos, gasto, risco eliminado, o
que fica na fila), a curva custo acumulado × risco eliminado acumulado dos dois critérios de fila (a pergunta: com
o mesmo dinheiro, qual fila tira mais risco?) e a fila com o acumulado em reais e em % do risco público. Tudo pelo
serviço (`ServicoAcervo.priorizacao`, só N3).

Custo por responsável (só N3, matriz SOMAR_POR_RESPONSAVEL, sem exportação): cartões com a base (responsáveis,
casos cobráveis distintos, passivo cobrável sem dupla contagem, soma das linhas e a concentração nos 10 maiores),
o passivo cobrável nas quatro categorias de custo (fecha com o cartão do passivo), as barras dos 10 maiores
empilhadas nas mesmas categorias e a memória de cálculo do responsável escolhido, com o subtotal por categoria.

Todo total diz de onde vem (o serviço consultado e a data), no rodapé do bloco e na dica do cartão; o
cabeçalho fica sem fonte. As categorias são as quatro do modelo de custos (EEA): transporte e
tratamento fora do local estão dentro de Disposição.

A Priorização tem duas visões, num seletor à esquerda da linha de controles. "Por urgência" (padrão) lista
os 20 casos ativos do país que pedem ação primeiro (CasosParaAgir); "Pelo orçamento público" é a fila acima.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from html import escape

from PySide6.QtCore import QIdentityProxyModel, Qt
from PySide6.QtWidgets import QHBoxLayout, QHeaderView, QLabel, QStackedWidget, QVBoxLayout, QWidget

from ecosec.acervo import custos, formatos, regras, vocabulario
from ecosec.interface.estilo import cor_borda, cor_texto_secundario
from ecosec.interface.fluent import CaptionLabel, ComboBox, FlowLayout, SegmentedWidget, SpinBox, StrongBodyLabel
from ecosec.interface.n23_graficos import (Barra, BarraPartes, BarrasH, CartaoGrafico, CartaoValor, Curva,
                                           CurvaAcumulada, categorica, cor_texto, linha_legenda)


def _milhoes(valor: float) -> str:
    """Dinheiro no texto da priorização: sempre "R$ x,xx mi" (duas casas: o orçamento é decidido ao centavo de
    milhão)."""
    return f"R$ {formatos.numero(valor / 1e6, 2)} mi"


def _reais(valor: float) -> str:
    return f"R$ {formatos.numero(valor, 2)}"


def _explicacao(texto: str) -> CaptionLabel:
    rotulo = CaptionLabel(texto)
    rotulo.setWordWrap(True)
    rotulo.setStyleSheet(f"color:{cor_texto_secundario()};")
    return rotulo


def rotulos_categorias() -> list[tuple[str, str]]:
    """(rótulo, cor) das quatro categorias de custo, na ordem de custos.CATEGORIAS_EEA (a mesma cor da ficha)."""
    return [(vocabulario.rotulo(c, "categoria_custo"), categorica(i)) for i, c in enumerate(custos.CATEGORIAS_EEA)]


class FaixaPassivo(QWidget):
    """O passivo cobrável nas quatro categorias de custo, em faixa compacta (a tabela ao
    lado não pode perder linhas): título e pergunta numa linha, a barra 100% (BarraPartes sem a legenda vertical),
    a legenda com "R$ x,xx mi" e o rodapé. O valor exato e a fração ficam na dica. A legenda ocupa uma linha
    e, quando a coluna é estreita, quebra para a seguinte em vez de cortar os valores."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("faixaPassivo")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"#faixaPassivo {{ border:1px solid {cor_borda()}; border-radius:6px; }}")
        v = QVBoxLayout(self)
        v.setContentsMargins(14, 8, 14, 8)
        v.setSpacing(4)
        cabeca = QHBoxLayout()
        cabeca.setSpacing(10)
        self.titulo = QLabel("Passivo cobrável por categoria de custo")
        self.titulo.setStyleSheet(f"color:{cor_texto()}; font-size:14px; font-weight:600;")
        self.pergunta = QLabel("Em que parte da solução está o dinheiro a cobrar?")
        self.pergunta.setStyleSheet(f"color:{cor_texto_secundario()}; font-size:12px;")
        cabeca.addWidget(self.titulo)
        cabeca.addWidget(self.pergunta)
        cabeca.addStretch(1)
        v.addLayout(cabeca)
        self.partes = BarraPartes(self.titulo.text())
        self.partes.legenda.hide()                        # a legenda vertical (4 linhas) dá lugar à de uma linha
        v.addWidget(self.partes)
        self.legenda = QWidget()
        self._itens = FlowLayout(self.legenda)
        self._itens.setContentsMargins(0, 0, 0, 0)
        self._itens.setHorizontalSpacing(20)
        self._itens.setVerticalSpacing(4)
        v.addWidget(self.legenda)
        self.rodape = QLabel("")
        self.rodape.setStyleSheet(f"color:{cor_texto_secundario()}; font-size:11px;")
        self.rodape.setWordWrap(True)
        v.addWidget(self.rodape)
        self.setAccessibleName(self.titulo.text())

    def definir(self, partes):
        """partes: [(nome, valor, cor, definição)], na ordem das categorias."""
        self.partes.definir(partes, _reais)
        while self._itens.count():
            antigo = self._itens.takeAt(0)
            antigo.setParent(None)                        # sai da árvore já, não só no próximo ciclo de eventos
            antigo.deleteLater()
        total = sum(v for _, v, _, _ in partes) or 1
        for nome, valor, cor, definicao in partes:
            item = QWidget()                              # amostra e rótulo quebram de linha juntos
            h = QHBoxLayout(item)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(6)
            amostra = QLabel()
            amostra.setFixedSize(12, 12)
            amostra.setStyleSheet(f"background:{cor}; border-radius:3px;")
            rotulo = QLabel(f"{escape(nome)} <b>{_milhoes(valor)}</b>")
            rotulo.setStyleSheet(f"color:{cor_texto()}; font-size:12px;")
            dica = (f"{nome}: {_reais(valor)} ({formatos.numero(100 * valor / total, 1)}% do passivo cobrável)"
                    + (f"\n{definicao}" if definicao else ""))
            for w in (amostra, rotulo):
                w.setToolTip(dica)
            h.addWidget(amostra)
            h.addWidget(rotulo)
            self._itens.addWidget(item)

    def definir_rodape(self, texto: str):
        self.rodape.setText(texto)
        self.rodape.setVisible(bool(texto))


def custo_por_categoria(pendencias, r) -> dict[str, float]:
    """{categoria: R$} somado nas pendências, pelos componentes da memória de cálculo (a soma das categorias é a
    soma dos custos estimados, sem arredondar categoria por categoria)."""
    soma = dict.fromkeys(custos.CATEGORIAS_EEA, 0.0)
    for p in pendencias:
        for componente in regras.memoria_de_calculo(p, r):
            soma[componente.categoria] += componente.valor
    return soma


# ================================================================ casos para agir, por urgência (N3)
N_CASOS_PARA_AGIR = 20
# os quatro grupos de urgência, na ordem (o índice é o `grupo` de LinhaUrgencia)
GRUPOS_URGENCIA = ("Crítico e além do prazo legal", "Crítico, dentro do prazo legal",
                   "Além do prazo legal, não crítico", "Demais casos ativos")


@dataclass(frozen=True)
class LinhaUrgencia:
    """Um caso ativo na lista por urgência, com o que a tabela mostra (o score só serve à ordem e à dica)."""
    grupo: int                              # índice em GRUPOS_URGENCIA
    caso: object                            # Pendencia
    score: float
    faixa: str
    dias_alem: int                          # dias além do prazo legal da classe (0: dentro do prazo)
    acao: str
    quem_paga: str
    custo: float


def casos_por_urgencia(pendencias, hoje, r) -> list[LinhaUrgencia]:
    """Todos os casos ativos em `hoje`, do mais urgente ao menos: crítico e além do prazo legal, crítico, além do
    prazo legal, demais; no empate, o maior score e depois o código. Função pura (as regras de regras.py)."""
    linhas = []
    for p in pendencias:
        if not p.ativa(hoje):
            continue
        score = regras.criticidade(p, hoje)
        faixa = regras.faixa_do_score(score)
        alem = regras.dias_alem_do_prazo_limite(p, hoje, r)
        critico = faixa == "CRITICO"
        grupo = 0 if critico and alem else 1 if critico else 2 if alem else 3
        linhas.append(LinhaUrgencia(grupo, p, score, faixa, alem, regras.acao_recomendada(p, hoje, r),
                                    regras.responsabilidade(p), regras.custo_estimado(p, r)))
    linhas.sort(key=lambda l: (l.grupo, -l.score, l.caso.codigo))
    return linhas


# quem paga, no meio da frase de resumo ("todos de material radioativo com responsabilidade pública")
QUEM_PAGA_NA_FRASE = {regras.PUBLICO: "com responsabilidade pública", regras.COBRAVEL: "cobráveis do responsável",
                      regras.INFRAESTRUTURA: "à espera de destino técnico", regras.FISCALIZACAO: "com carga a rastrear"}


def resumo_do_topo(linhas) -> str:
    """A leitura do bloco mostrado, numa frase: a classe e quem paga dominantes e a faixa de score. Não muda a
    ordem (o topo homogêneo é o dado; a frase só o identifica). Sem linhas, ""."""
    if not linhas:
        return ""
    n = len(linhas)
    classe, n_classe = Counter(l.caso.classe_risco for l in linhas).most_common(1)[0]
    paga, n_paga = Counter(l.quem_paga for l in linhas).most_common(1)[0]
    nome_classe = vocabulario.rotulo(classe, "classe").lower()
    nome_paga = QUEM_PAGA_NA_FRASE.get(paga, vocabulario.rotulo(paga, "responsabilidade").lower())
    scores = [l.score for l in linhas]
    faixa = f"score entre {formatos.numero(min(scores), 1)} e {formatos.numero(max(scores), 1)}"
    if n_classe == n_paga == n:
        return f"Os {n} primeiros casos são todos de {nome_classe} {nome_paga}; {faixa}."
    return f"Nos {n} primeiros casos, {n_classe} são de {nome_classe} e {n_paga} {nome_paga}; {faixa}."


class _DicasPorCelula(QIdentityProxyModel):
    """A tabela de origem com uma dica por célula (o ModeloTabela só dá dica ao texto cru longo, que aqui seria o
    código da ação): o rótulo com a definição, o score, a data do prazo legal."""

    def __init__(self, origem, parent=None):
        super().__init__(parent)
        self.setSourceModel(origem)
        self.dicas: list = []

    def data(self, indice, papel=Qt.ItemDataRole.DisplayRole):
        if papel == Qt.ItemDataRole.ToolTipRole:
            linha, coluna = indice.row(), indice.column()
            return (self.dicas[linha][coluna] or None) if 0 <= linha < len(self.dicas) else None
        return super().data(indice, papel)


class CasosParaAgir(QWidget):
    """Que casos o país precisa atacar primeiro? Os 20 casos ativos mais urgentes do país inteiro (a aba não segue o
    filtro), na ordem de `casos_por_urgencia`. A ordem é a decisão: a tabela não se reordena pelo cabeçalho.
    O score não aparece na tabela: só na dica da faixa."""
    TITULOS = ("CODIGO", "FAIXA", "CLASSE DE RISCO", "UF", "MUNICIPIO", "DIAS ALEM DO PRAZO LIMITE",
               "ACAO RECOMENDADA", "RESPONSABILIDADE", "CUSTO (R$)")
    VAZIA = "Nenhum caso ativo na data de corte"
    LARGURA_MUNICIPIO = 200                               # nome maior corta com reticências (o inteiro na dica)
    ORDEM = ("A ordem da lista: primeiro os casos críticos já além do prazo legal da classe, depois os críticos "
             "dentro do prazo, depois os além do prazo que não são críticos e, por fim, os demais casos ativos. "
             "No empate, o maior score de risco e depois o código.")

    def __init__(self, tela, parent=None):
        super().__init__(parent)
        from ecosec.interface.painel_analitico import ModeloTabela, _tabela
        self.tela, self.painel = tela, None
        self.linhas: list[LinhaUrgencia] = []             # as mostradas (até N_CASOS_PARA_AGIR)
        self.total = 0                                    # todos os casos ativos ordenados
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)
        self.modelo = ModeloTabela(self.TITULOS)
        self.dicas = _DicasPorCelula(self.modelo, self)
        self.tabela = _tabela(self.dicas)
        self.tabela.setSortingEnabled(False)              # A ordem é a urgência
        self.tabela.horizontalHeader().setSortIndicatorShown(False)
        self.tabela.horizontalHeader().setSectionsClickable(False)
        self.lista_vazia = QLabel(self.VAZIA)             # no lugar da tabela, quando não há caso ativo
        self.lista_vazia.setStyleSheet(f"color:{cor_texto()}; font-size:13px;")
        self.lista_vazia.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lista_vazia.hide()
        self.resumo = QLabel()                            # a leitura do bloco, antes das linhas
        self.resumo.setStyleSheet(f"color:{cor_texto()}; font-size:13px; font-weight:600;")
        self.resumo.setWordWrap(True)
        caixa = QWidget()
        cv = QVBoxLayout(caixa)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.setSpacing(6)
        cv.addWidget(self.resumo)
        cv.addWidget(self.tabela, 1)
        cv.addWidget(self.lista_vazia, 1)
        self.cartao = CartaoGrafico("Casos para agir, por urgência",
                                    "Que casos o país precisa atacar primeiro? Críticos além do prazo legal no topo; "
                                    "a ação recomendada diz o que fazer e quem paga.", caixa, expandir=True)
        v.addWidget(self.cartao, 1)

    def carregar(self, painel):
        self.painel = painel
        hoje, r = painel.hoje, painel.regras
        todos = casos_por_urgencia(painel.pendencias, hoje, r)
        self.total, self.linhas = len(todos), todos[:N_CASOS_PARA_AGIR]
        self.dicas.dicas = [self._dicas(l, r) for l in self.linhas]
        self.modelo.definir([[l.caso.codigo, l.faixa, l.caso.classe_risco, l.caso.uf, l.caso.municipio, l.dias_alem,
                              l.acao, l.quem_paga, round(float(l.custo), 2)] for l in self.linhas])
        self._larguras()
        vazia = not self.linhas
        self.resumo.setText(resumo_do_topo(self.linhas))
        self.resumo.setVisible(not vazia)
        self.lista_vazia.setVisible(vazia)
        self.tabela.setVisible(not vazia)
        if vazia:
            self.cartao.definir_rodape(f"{self.VAZIA}.")
        else:
            n = Counter(l.grupo for l in todos)
            self.cartao.definir_rodape(
                f"Mostrando {len(self.linhas)} de {vocabulario.casos(self.total, 'ativos')} no país: "
                f"{formatos.inteiro(n[0])} críticos além do prazo legal, {formatos.inteiro(n[1])} críticos dentro do "
                f"prazo, {formatos.inteiro(n[2])} além do prazo sem ser críticos e {formatos.inteiro(n[3])} demais. "
                "A lista completa está na Planilha analítica.")
        self.cartao.setToolTip(self.ORDEM)

    def _dicas(self, l: LinhaUrgencia, r) -> tuple:
        p = l.caso
        prazo = f"{regras.prazo_limite(p, r):%d/%m/%Y}"
        dias = (f"{formatos.inteiro(l.dias_alem)} dias além do prazo legal (venceu em {prazo})" if l.dias_alem
                else f"Dentro do prazo legal (até {prazo})")
        acao, paga = vocabulario.rotulo(l.acao, "acao"), vocabulario.rotulo(l.quem_paga, "responsabilidade")
        return (GRUPOS_URGENCIA[l.grupo],
                f"{vocabulario.rotulo(l.faixa, 'faixa')} · score de risco {formatos.numero(l.score, 2)}",
                "", "", f"{p.municipio}/{p.uf}", dias,
                f"{acao}\n{vocabulario.definicao(l.acao, 'acao')}",
                f"{paga}\n{vocabulario.definicao(l.quem_paga, 'responsabilidade')}",
                _reais(l.custo))

    def _larguras(self):
        """Todas as colunas à vista: cada uma no tamanho do conteúdo, o município com teto e a ação recomendada
        com o que sobra (se faltar, corta com reticências; o texto inteiro está na dica)."""
        cabecalho = self.tabela.horizontalHeader()
        cabecalho.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.tabela.resizeColumnsToContents()
        municipio, acao = self.TITULOS.index("MUNICIPIO"), self.TITULOS.index("ACAO RECOMENDADA")
        cabecalho.resizeSection(municipio, min(cabecalho.sectionSize(municipio), self.LARGURA_MUNICIPIO))
        cabecalho.setSectionResizeMode(acao, QHeaderView.ResizeMode.Stretch)


# ================================================================ priorização orçamentária (N3)
class PriorizacaoOrcamento(QWidget):
    """Com um orçamento público, quais casos resolver primeiro? A regra de negócio que vira decisão.

    A aba tem duas visões, no seletor à esquerda da linha de controles (sem linha a mais: a fila não perde
    altura). "Por urgência" (CasosParaAgir, padrão) traz a própria base; em "Pelo orçamento público" a linha mostra
    o orçamento, o critério e a base da fila. As duas carregam juntas, qualquer que seja a visão aberta."""
    VISOES = (("urgencia", "Por urgência"), ("orcamento", "Pelo orçamento público"))
    TITULOS = ("ORDEM", "CODIGO", "NIVEL DE RISCO", "SCORE", "CLASSE DE RISCO", "SUBSTANCIA", "MUNICIPIO", "UF",
               "CUSTO (R$)", "ACUMULADO NA FILA (R$)", "RISCO ELIMINADO ACUMULADO (%)")
    # o que cada cartão mede (a dica; a fonte e o corte entram em `atualizar`)
    DICAS = {"casos": "Casos que a fila leva com o orçamento escolhido, sobre todos os casos ativos pagos pelo poder "
                      "público.",
             "gasto": "Soma do custo estimado dos casos da fila. Nunca passa do orçamento.",
             "risco": vocabulario.dica("SCORE", "risco"),
             "fila": "Casos pagos pelo poder público que o orçamento não alcança e o score que continua no país.",
             "zerar": "Soma do custo estimado de todos os casos pagos pelo poder público: o que a fila inteira custa, "
                      "qualquer que seja o critério."}

    def __init__(self, tela, parent=None):
        super().__init__(parent)
        from ecosec.interface.painel_analitico import ModeloTabela, _tabela
        self.tela, self.painel = tela, None
        self.filas: dict = {}
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 8, 0, 0)
        v.setSpacing(8)
        linha = QHBoxLayout()
        self.visoes = SegmentedWidget()
        for chave, texto in self.VISOES:                  # o clique passa "checked": a chave vai pelo default
            self.visoes.addItem(chave, texto, onClick=lambda *_, c=chave: self.mostrar_visao(c))
        linha.addWidget(self.visoes)
        linha.addSpacing(12)
        self.controles = QWidget()                        # orçamento e critério: só na visão do orçamento
        controles = QHBoxLayout(self.controles)
        controles.setContentsMargins(0, 0, 0, 0)
        self.orcamento = SpinBox()
        self.orcamento.setRange(1, 500)
        self.orcamento.setSuffix(" milhões de R$")
        self.orcamento.setMinimumWidth(200)
        self.orcamento.setAccessibleName("Orçamento público")
        self.orcamento.valueChanged.connect(self.atualizar)
        self.criterio = ComboBox()
        self.criterio.addItems([vocabulario.ROTULO_CRITERIO[c] for c in regras.CRITERIOS])
        self.criterio.setMinimumWidth(280)
        self.criterio.setAccessibleName("Critério da fila")
        self.criterio.setToolTip("\n".join(f"{vocabulario.ROTULO_CRITERIO[c]}: {vocabulario.DEFINICAO_CRITERIO[c]}"
                                           for c in regras.CRITERIOS))
        self.criterio.currentIndexChanged.connect(self.atualizar)
        for w in (CaptionLabel("Orçamento"), self.orcamento, CaptionLabel("Critério da fila"), self.criterio):
            controles.addWidget(w)
        linha.addWidget(self.controles)
        linha.addStretch(1)
        v.addLayout(linha)
        self.pilha = QStackedWidget()
        self.urgencia = CasosParaAgir(tela)
        self.pilha.addWidget(self.urgencia)
        self.pagina_orcamento = QWidget()                 # a fila do orçamento, inteira
        self.pilha.addWidget(self.pagina_orcamento)
        v.addWidget(self.pilha, 1)
        v = QVBoxLayout(self.pagina_orcamento)            # daqui em diante, a página do orçamento
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)
        self.resultado = StrongBodyLabel()
        self.resultado.setWordWrap(True)
        v.addWidget(self.resultado)
        cartoes = QHBoxLayout()
        cartoes.setSpacing(10)
        self.cartoes = {"casos": CartaoValor("Casos resolvidos com o orçamento"),
                        "gasto": CartaoValor("Gasto"),
                        "risco": CartaoValor("Risco público eliminado", vocabulario.dica("SCORE", "risco")),
                        "fila": CartaoValor("Ficam na fila"),
                        "zerar": CartaoValor("Custo para resolver toda a fila")}
        for cartao in self.cartoes.values():
            cartoes.addWidget(cartao, 1)
        v.addLayout(cartoes)
        corpo = QHBoxLayout()
        corpo.setSpacing(12)
        self.curva = CurvaAcumulada("Custo acumulado e risco eliminado, por critério", 250)
        self.cartao_curva = CartaoGrafico(
            "Quanto risco cada real tira: custo acumulado × risco eliminado",
            "Com o mesmo dinheiro, qual fila tira mais risco? Cada linha percorre a fila inteira de um critério; o "
            "ponto marca onde o orçamento acaba.", self.curva, expandir=True)
        corpo.addWidget(self.cartao_curva, 2)
        self.modelo = ModeloTabela(self.TITULOS)
        self.tabela = _tabela(self.modelo)
        # O acumulado só tem sentido na ORDEM da fila; a tabela não se reordena pelo cabeçalho
        self.tabela.setSortingEnabled(False)
        self.tabela.horizontalHeader().setSortIndicatorShown(False)
        self.tabela.horizontalHeader().setSectionsClickable(False)
        caixa = QWidget()
        cv = QVBoxLayout(caixa)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.addWidget(self.tabela, 1)
        self.cartao_fila = CartaoGrafico("A fila do orçamento, na ordem de execução",
                                         "Quais casos entram, quanto custa cada um e quanto do risco público sai até "
                                         "ele.", caixa, expandir=True)
        corpo.addWidget(self.cartao_fila, 3)
        v.addLayout(corpo, 1)
        v.addWidget(_explicacao(
            "Concorrem só os casos ativos que o poder público paga (material órfão ou contaminação descoberta depois: "
            "não há a quem cobrar). A fila percorre os casos na ordem do critério e leva tudo o que ainda cabe no "
            "orçamento."))
        self.mostrar_visao(self.VISOES[0][0])             # "Por urgência" abre primeiro

    @property
    def visao_atual(self) -> str:
        return "urgencia" if self.pilha.currentWidget() is self.urgencia else "orcamento"

    def mostrar_visao(self, chave: str):
        orcamento = chave == "orcamento"
        self.pilha.setCurrentWidget(self.pagina_orcamento if orcamento else self.urgencia)
        self.visoes.setCurrentItem(chave)
        self.controles.setVisible(orcamento)

    @property
    def criterio_atual(self) -> str:
        return regras.CRITERIOS[max(0, self.criterio.currentIndex())]

    def carregar(self, painel):
        self.urgencia.carregar(painel)
        self.painel = None
        self.orcamento.setValue(max(1, round(painel.regras.orcamento_publico / 1e6)))
        self.painel = painel
        # as filas completas (orçamento sem teto) dos dois critérios: a curva e o "custo para zerar a fila"
        servico = self.tela.app.acervo
        self.filas = {c: servico.priorizacao(painel, self.tela.usuario, float("inf"), c) for c in regras.CRITERIOS}
        self.atualizar()

    def atualizar(self, *_):
        if self.painel is None:
            return
        servico, criterio = self.tela.app.acervo, self.criterio_atual
        orcamento = self.orcamento.value() * 1e6
        fila = servico.priorizacao(self.painel, self.tela.usuario, orcamento, criterio)
        total_score = fila.score_publico or 1
        acumulado, score, linhas = 0.0, 0.0, []
        for ordem, (p, custo, s) in enumerate(fila.selecionadas, 1):
            acumulado += custo
            score += s
            linhas.append([ordem, p.codigo, regras.faixa_do_score(s), round(s, 2), p.classe_risco, p.substancia,
                           p.municipio, p.uf, round(float(custo), 2), round(acumulado, 2),
                           round(100 * score / total_score, 2)])           # dinheiro: float, um formato só
        self.modelo.definir(linhas)
        self.tabela.resizeColumnsToContents()
        n, candidatas = len(fila.selecionadas), fila.candidatas
        completa = self.filas.get(criterio) or fila
        self.resultado.setText(
            f"Com {_milhoes(orcamento)}: {n} de {vocabulario.casos(candidatas, 'públicos')} resolvidos "
            f"({_milhoes(fila.custo_total)} gastos), {formatos.numero(fila.percentual_reduzido, 1)}% do risco "
            f"público eliminado. Ficam {vocabulario.casos(candidatas - n)} na fila.")
        self.cartoes["casos"].definir(f"{formatos.inteiro(n)} de {formatos.inteiro(candidatas)}",
                                      f"{formatos.numero(100 * n / candidatas if candidatas else 0, 1)}% dos casos "
                                      "públicos")
        self.cartoes["gasto"].definir(_milhoes(fila.custo_total),
                                      f"{formatos.numero(100 * fila.custo_total / orcamento, 1)}% do orçamento "
                                      f"({_reais(fila.custo_total)})")
        self.cartoes["risco"].definir(f"{formatos.numero(fila.percentual_reduzido, 1)}%",
                                      f"score {formatos.numero(fila.score_reduzido, 1)} de "
                                      f"{formatos.numero(fila.score_publico, 1)}")
        self.cartoes["fila"].definir(formatos.inteiro(candidatas - n),
                                     f"score restante {formatos.numero(fila.score_publico - fila.score_reduzido, 1)}")
        self.cartoes["zerar"].definir(_milhoes(completa.custo_total),
                                      f"{vocabulario.casos(completa.candidatas, 'públicos')}, qualquer critério")
        for chave, cartao in self.cartoes.items():
            cartao.setToolTip(self.DICAS[chave])
        curvas, marcas = [], {}
        for i, c in enumerate(regras.CRITERIOS):            # a cor segue o critério, nunca a posição
            completa_c = self.filas.get(c)
            if completa_c is None:
                continue
            pontos, gasto, s_acum = [], 0.0, 0.0
            for _, custo, s in completa_c.selecionadas:
                gasto += custo
                s_acum += s
                pontos.append((gasto, 100 * s_acum / (completa_c.score_publico or 1)))
            nome = vocabulario.ROTULO_CRITERIO[c]
            curvas.append(Curva(nome, pontos, categorica(i)))
            no_orcamento = (fila if c == criterio
                            else servico.priorizacao(self.painel, self.tela.usuario, orcamento, c))
            marcas[nome] = (no_orcamento.custo_total, no_orcamento.percentual_reduzido)
        # o eixo x vai até 4 × o orçamento (no mínimo R$ 10 mi), onde a decisão acontece; a fila inteira está no
        # cartão "Custo para resolver toda a fila"
        dominio = min(max(4 * orcamento, 10e6), max((c.pontos[-1][0] for c in curvas if c.pontos), default=orcamento))
        self.curva.definir(curvas, orcamento, marcas, dominio)


def regras_criterios():
    return regras.CRITERIOS


# ================================================================ custo por responsável (N3)
class CustoPorResponsavel(QWidget):
    """Custo do passivo ativo e cobrável por responsável nomeado, com a memória de cálculo de cada um. Só no N3:
    a tela só existe nas seções do N3, e o serviço (matriz, operação SOMAR_POR_RESPONSAVEL) nega e registra
    qualquer outra tentativa. Não há exportação."""
    TITULOS = ("ORDEM", "RESPONSAVEL", "VINCULOS", "PENDENCIAS", "CUSTO ATIVO COBRAVEL (R$)")
    DICAS = {"responsaveis": "Responsáveis nomeados (empresas e pessoas físicas) que aparecem como gerador original, "
                             "sucessor ou proprietário atual em pelo menos um caso ativo e cobrável.",
             "casos": "Casos ativos e cobráveis com pelo menos um responsável nomeado, cada caso contado uma vez.",
             "passivo": "Soma do custo estimado desses casos, cada caso uma vez só. É o total que a divisão por "
                        "categoria fecha.",
             "soma": "Soma da coluna de custo: o mesmo caso entra em cada corresponsável (responsabilidade "
                     "solidária), então passa do passivo.",
             "concentracao": "Parte do passivo cobrável nos casos dos 10 maiores responsáveis, cada caso uma vez só."}
    # a regra da aba: na dica da linha de topo (para a tabela não perder linhas)
    EXPLICACAO = ("Soma do custo estimado dos casos ATIVOS e COBRÁVEIS em que o responsável aparece como gerador "
                  "original, sucessor ou proprietário atual. A responsabilidade é solidária: o mesmo caso entra na "
                  "soma de cada corresponsável, então a soma das linhas é maior que o passivo. Só no Nível 3, sem "
                  "exportação; cada consulta fica na trilha. Selecione uma linha para ver a memória de cálculo.")

    def __init__(self, tela, parent=None):
        super().__init__(parent)
        from ecosec.interface.fluent import TextBrowser
        from ecosec.interface.painel_analitico import ModeloTabela, _tabela
        self.tela, self.painel, self.linhas = tela, None, []
        self.categorias: dict = {}                        # nome -> {categoria: R$}, dos 10 maiores
        self.passivo_categorias: dict = {}                # {categoria: R$} do passivo sem dupla contagem
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 8, 0, 0)
        v.setSpacing(8)
        self.aviso = StrongBodyLabel()
        self.aviso.setWordWrap(True)
        self.aviso.setToolTip(self.EXPLICACAO)
        v.addWidget(self.aviso)
        cartoes = QHBoxLayout()
        cartoes.setSpacing(10)
        self.cartoes = {"responsaveis": CartaoValor("Responsáveis com passivo cobrável"),
                        "casos": CartaoValor("Casos cobráveis ativos (distintos)"),
                        "passivo": CartaoValor("Passivo cobrável, sem dupla contagem"),
                        "soma": CartaoValor("Soma das linhas (solidária)"),
                        "concentracao": CartaoValor("Concentração nos 10 maiores")}
        for cartao in self.cartoes.values():
            cartoes.addWidget(cartao, 1)
        v.addLayout(cartoes)
        corpo = QHBoxLayout()
        # coluna da lista: o passivo por categoria acima da tabela (na coluna da direita, a memória sumiria)
        esquerda = QWidget()
        ev = QVBoxLayout(esquerda)
        ev.setContentsMargins(0, 0, 0, 0)
        ev.setSpacing(8)
        self.cartao_partes = FaixaPassivo()
        self.partes = self.cartao_partes.partes
        ev.addWidget(self.cartao_partes)
        self.modelo = ModeloTabela(self.TITULOS)
        self.tabela = _tabela(self.modelo)
        self.tabela.clicked.connect(lambda indice: self.mostrar_memoria(indice.row()))
        ev.addWidget(self.tabela, 1)
        corpo.addWidget(esquerda, 3)                      # Lista 3, memória 2 (todas as colunas à vista)
        direita = QWidget()
        direita.setMinimumWidth(460)
        dv = QVBoxLayout(direita)
        dv.setContentsMargins(0, 0, 0, 0)
        dv.setSpacing(8)
        self.barras = BarrasH("Os 10 maiores responsáveis por custo ativo cobrável", largura_rotulo=230)
        caixa_barras = QWidget()
        bv = QVBoxLayout(caixa_barras)
        bv.setContentsMargins(0, 0, 0, 0)
        bv.setSpacing(6)
        bv.addWidget(linha_legenda(rotulos_categorias()))  # 4 cores: a legenda sempre presente (dataviz)
        bv.addWidget(self.barras)
        self.cartao_barras = CartaoGrafico("Os 10 maiores responsáveis por custo cobrável",
                                           "Em quem a cobrança rende mais, e em que parte da solução?", caixa_barras)
        dv.addWidget(self.cartao_barras)
        self.memoria = TextBrowser()
        self.memoria.setMinimumWidth(460)
        self.memoria.setPlaceholderText("Selecione um responsável na tabela para ver a memória de cálculo.")
        dv.addWidget(self.memoria, 1)
        corpo.addWidget(direita, 2)
        v.addLayout(corpo, 1)

    def carregar(self, painel) -> bool:
        """Pede a soma ao serviço. Fora do N3 o serviço recusa e registra a tentativa; a tela fica vazia."""
        self.painel, self.linhas = painel, []
        self.categorias, self.passivo_categorias = {}, {}
        self.modelo.definir([])
        self.memoria.clear()
        self.barras.definir([])
        self.cartao_partes.definir([])
        try:
            self.linhas = self.tela.app.acervo.custo_por_responsavel(painel, self.tela.usuario)
        except Exception as erro:  # noqa: BLE001, ErroAcervo: a matriz negou (e a trilha já registrou)
            from ecosec.interface.painel_analitico import _mensagem
            self.aviso.setText(_mensagem(erro))
            return False
        self.modelo.definir([[i, l.nome, ", ".join(vocabulario.ROTULO_VINCULO.get(x, x) for x in l.vinculos),
                              l.pendencias, l.custo] for i, l in enumerate(self.linhas, 1)])
        self.tabela.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.tabela.resizeColumnsToContents()
        # o nome ocupa o que sobra (e corta com reticências, com a dica completa): nenhuma coluna fica fora
        cabecalho = self.tabela.horizontalHeader()
        for coluna in (0, 2, 3, 4):                       # folga para o indicador de ordenação do cabeçalho
            cabecalho.setSectionResizeMode(coluna, QHeaderView.ResizeMode.Fixed)
            cabecalho.resizeSection(coluna, cabecalho.sectionSize(coluna) + (26 if coluna == 0 else 8))
        cabecalho.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._resumir(painel)
        return True

    def _resumir(self, painel):
        """Cartões e barras: base, totais sem dupla contagem e concentração (só com os dados do N3 já entregues)."""
        por_codigo = {p.codigo: p for p in painel.pendencias}
        distintos = set().union(*(set(l.codigos) for l in self.linhas)) if self.linhas else set()
        passivo = sum(regras.custo_estimado(por_codigo[c], painel.regras) for c in distintos)
        soma = sum(l.custo for l in self.linhas)
        dez = set().union(*(set(l.codigos) for l in self.linhas[:10])) if self.linhas else set()
        passivo_dez = sum(regras.custo_estimado(por_codigo[c], painel.regras) for c in dez)
        self.aviso.setText(f"{formatos.inteiro(len(self.linhas))} responsáveis com passivo ativo cobrável.")
        self.cartoes["responsaveis"].definir(formatos.inteiro(len(self.linhas)), "com passivo ativo cobrável")
        self.cartoes["casos"].definir(formatos.inteiro(len(distintos)), "ativos, de quem cabe cobrar")
        self.cartoes["passivo"].definir(_milhoes(passivo), _reais(passivo))
        self.cartoes["soma"].definir(_milhoes(soma), f"{formatos.numero(soma / passivo if passivo else 0, 2)} × o "
                                                     "passivo (solidariedade)")
        self.cartoes["concentracao"].definir(f"{formatos.numero(100 * passivo_dez / passivo if passivo else 0, 1)}%",
                                             f"do passivo cobrável ({_milhoes(passivo_dez)}, "
                                             f"{vocabulario.casos(len(dez))})")
        for chave, cartao in self.cartoes.items():
            cartao.setToolTip(self.DICAS[chave])
        # as quatro categorias: do passivo (cada caso uma vez) e de cada um dos 10 maiores (solidário)
        rotulos = rotulos_categorias()
        self.passivo_categorias = custo_por_categoria([por_codigo[c] for c in sorted(distintos)], painel.regras)
        self.cartao_partes.definir([(nome, self.passivo_categorias[cat], cor,
                                     vocabulario.definicao(cat, "categoria_custo"))
                                    for cat, (nome, cor) in zip(custos.CATEGORIAS_EEA, rotulos)])
        self.cartao_partes.definir_rodape(f"As quatro categorias somam {_milhoes(passivo)}, igual ao passivo "
                                          "cobrável.")
        self.cartao_partes.setToolTip(f"O passivo cobrável sem dupla contagem ({_reais(passivo)}; cada caso "
                                      "uma vez só), nas quatro categorias de custo. Transporte e tratamento fora do "
                                      "local estão em Disposição.")
        barras = []
        for l in self.linhas[:10]:
            por_cat = custo_por_categoria([por_codigo[c] for c in l.codigos], painel.regras)
            self.categorias[l.nome] = por_cat
            partes = "\n".join(f"{nome}: {_reais(por_cat[cat])}" for cat, (nome, _) in zip(custos.CATEGORIAS_EEA,
                                                                                           rotulos))
            barras.append(Barra(l.nome, [(por_cat[cat], cor, nome) for cat, (nome, cor) in
                                         zip(custos.CATEGORIAS_EEA, rotulos)], _milhoes(l.custo),
                                f"{l.nome}\n{_reais(l.custo)} · {vocabulario.casos(l.pendencias)} · "
                                + ", ".join(vocabulario.ROTULO_VINCULO.get(x, x) for x in l.vinculos)
                                + f"\n{partes}"))
        self.barras.definir(barras)
        self.cartao_barras.setToolTip("Custo dos casos de cada responsável (solidário), por categoria de custo. "
                                      "Passe o mouse numa barra para ver os valores.")

    def mostrar_memoria(self, linha: int):
        visiveis = self.modelo._visiveis()
        if not 0 <= linha < len(visiveis):
            return
        resp = self.linhas[visiveis[linha][0] - 1]          # pela ORDEM: a tabela pode ter sido reordenada
        try:
            itens = self.tela.app.acervo.memoria_por_responsavel(self.painel, self.tela.usuario, resp.nome)
        except Exception as erro:  # noqa: BLE001
            from ecosec.interface.painel_analitico import _mensagem
            self.memoria.setHtml(f"<i>{_mensagem(erro)}</i>")
            return
        self.memoria.setHtml(memoria_html(resp, itens))


def memoria_html(resp, itens) -> str:
    """Memória de cálculo de um responsável: o subtotal por categoria de custo (soma o custo do responsável) e,
    por caso, a rota e cada componente (quantidade × unitário = valor). Os totais dos casos somam o custo do
    responsável."""
    secundaria = cor_texto_secundario()
    vinculos = ", ".join(vocabulario.ROTULO_VINCULO.get(x, x) for x in resp.vinculos)
    partes = [f"<p style='margin-bottom:4px'><b style='font-size:14px'>{escape(resp.nome)}</b><br>"
              f"<span style='color:{secundaria}'>{escape(vinculos)} · {vocabulario.casos(len(itens))}</span><br>"
              f"Custo ativo cobrável: <b>{_reais(resp.custo).replace(' ', '&nbsp;')}</b></p>"]
    por_categoria = dict.fromkeys(custos.CATEGORIAS_EEA, 0.0)
    for item in itens:
        for c in item.componentes:
            por_categoria[c.categoria] += c.valor
    soma = sum(por_categoria.values())
    partes.append("<p style='margin-top:8px; margin-bottom:2px'><b>Por categoria de custo</b></p>"
                  "<table cellspacing='0' cellpadding='2' width='100%'>")
    for cat, valor in por_categoria.items():
        percentual = formatos.numero(100 * valor / soma if soma else 0, 1)
        partes.append(f"<tr><td>{escape(vocabulario.rotulo(cat, 'categoria_custo'))}</td>"
                      f"<td align='right' style='white-space:nowrap'>{_reais(valor).replace(' ', '&nbsp;')}</td>"
                      f"<td align='right' style='color:{secundaria}; white-space:nowrap'>{percentual}%</td></tr>")
    partes.append(f"<tr><td><b>Soma das categorias</b></td><td align='right' style='white-space:nowrap'>"
                  f"<b>{_reais(soma).replace(' ', '&nbsp;')}</b></td><td></td></tr></table>")
    for item in itens:
        partes.append(f"<p style='margin-top:10px; margin-bottom:2px'><b>{escape(item.codigo)}</b> · "
                      f"{escape(vocabulario.frase(item.substancia))}<br><span style='color:{secundaria}'>"
                      f"{escape(vocabulario.rotulo(item.classe, 'classe'))} · rota: "
                      f"{escape(vocabulario.frase(item.rota))}</span></p>"
                      "<table cellspacing='0' cellpadding='2' width='100%'>")
        for c in item.componentes:
            casas = 0 if float(c.quantidade).is_integer() else 2
            unidade = vocabulario.rotulo_unidade(c.unidade)
            if unidade == "caso" and float(c.quantidade) != 1:
                unidade = "casos"
            base = f"{formatos.numero(c.quantidade, casas)} {escape(unidade)} × {_reais(c.unitario)}"
            partes.append(f"<tr><td>{escape(vocabulario.frase(c.nome))}</td>"
                          f"<td align='right' style='color:{secundaria}; white-space:nowrap'>"
                          f"{base.replace(' ', '&nbsp;')}</td>"
                          f"<td align='right' style='white-space:nowrap'>{_reais(c.valor).replace(' ', '&nbsp;')}</td>"
                          "</tr>")
        partes.append(f"<tr><td colspan='2'><b>Total do caso</b></td><td align='right' style='white-space:nowrap'>"
                      f"<b>{_reais(item.total).replace(' ', '&nbsp;')}</b></td><td></td></tr></table>")
    return "".join(partes)
