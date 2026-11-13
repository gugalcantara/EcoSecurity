"""Painéis da UF (N2): o painel de decisão do diretor da UF.

Uma página só, de cima para baixo, cada visual com a sua pergunta de decisão escrita como subtítulo e, quando
ajuda, um rodapé curto:

  Cartões             casos ativos, críticos, além do prazo legal, prazo previsto vencido e custo para resolver,
                      cada um com a comparação (fim do ano anterior ou Brasil)
  O que fazer agora   até três frases: a ação mais urgente com casos, o caso mais atrasado e a distância do Brasil
                      (frase sem dado não aparece; as seguintes sobem)
  Onde agir primeiro  casos ativos por ação recomendada, na ordem de urgência, com os críticos em destaque (ênfase)
  Casos para agir já  os casos críticos além do prazo legal, dos mais atrasados (duplo clique abre a ficha no mapa)
  Evolução da UF      casos ativos no fim de cada ano e, abaixo, no mesmo eixo de anos, entradas e saídas
  UF × país           o veredito por indicador (melhor ou pior, no sentido de cada um) e os halteres de 0 a 100%
  Custo na UF         custo por ação recomendada e a divisão nas quatro categorias de custo

Fontes (todas pelo serviço, matriz e trilha): kpis e painel_custo (UF do diretor, sem k), panorama (série
da UF), resumo_agregado (por ação recomendada e por faixa de risco, o mesmo do Resumo agregado) e
referencia_nacional (a linha NACIONAL do cubo protegido com o k do N1: o país, nunca outra UF individualmente).
A lista de casos usa os registros do painel do N2 (a própria UF), como a planilha. Nenhuma pessoa física, nenhum
custo por responsável. O custo da UF fica (só o N1 fica sem dado financeiro).
"""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QGridLayout, QHBoxLayout, QHeaderView, QLabel, QTableWidgetItem, QVBoxLayout,
                               QWidget)

from ecosec.acervo import analise, formatos, regras, vocabulario
from ecosec.interface.componentes.simbologia import COR_IDENTIDADE
from ecosec.interface.estilo import cor_texto_secundario
from ecosec.interface.fluent import ScrollArea, TableWidget
from ecosec.interface.n23_graficos import (Barra, BarraPartes, BarrasH, CartaoGrafico, CartaoValor, Haltere, Halteres,
                                           LinhasAno, Serie, categorica, cor_contexto, cor_texto, linha_legenda)

SECOES = ("prioridade", "casos", "evolucao", "comparacao", "custo")
MAX_CASOS = 10
LARGURA_MUNICIPIO = 150        # px; nome mais longo fica cortado com a dica inteira, para a ação caber sem corte
SEM_ATIVOS, SEM_CRITICOS, SEM_ATRASO = ("Nenhum caso ativo nesta UF", "Nenhum caso crítico nesta UF",
                                        "Nenhum caso crítico além do prazo legal")


def _pct(parte, total) -> float | None:
    return None if parte is None or not total else 100 * parte / total


def _pct_txt(valor) -> str:
    return "sem dado" if valor is None else formatos.percentual(valor)


def _mi(valor: float) -> str:
    return formatos.custo(valor)


@dataclass(frozen=True)
class Comparacao:
    """Um indicador da UF contra o Brasil, em %. maior_e_melhor: a taxa de encerramento (quanto mais encerra,
    melhor); nos demais (críticos, além do prazo legal, prazo previsto vencido), menor é melhor."""
    rotulo: str
    valor: float | None
    referencia: float | None
    maior_e_melhor: bool

    @property
    def diferenca(self) -> float | None:
        """Distância da UF ao Brasil, em pontos percentuais (sem sinal), com uma casa."""
        if self.valor is None or self.referencia is None:
            return None
        return round(abs(self.valor - self.referencia), 1)

    @property
    def veredito(self) -> str | None:
        """"melhor", "pior" ou "igual" (a mesma casa decimal da tela); None quando falta um dos lados."""
        if not self.diferenca:
            return None if self.diferenca is None else "igual"
        return "melhor" if (self.valor > self.referencia) == self.maior_e_melhor else "pior"

    def frase(self) -> str:
        """Ex.: "Taxa anual de encerramento (2025): 5,2% (Brasil 7,8%, 2,6 p.p. pior)"."""
        if self.veredito is None:
            juizo = "sem comparação"
        elif self.veredito == "igual":
            juizo = "<b>igual</b>"
        else:
            juizo = f"<b>{formatos.numero(self.diferenca, 1)} p.p. {self.veredito}</b>"
        return f"{self.rotulo}: {_pct_txt(self.valor)} (Brasil {_pct_txt(self.referencia)}, {juizo})"


def _lista(partes: list[str]) -> str:
    return partes[0] if len(partes) == 1 else f"{', '.join(partes[:-1])} e {partes[-1]}"


class PaineisUF(QWidget):
    """A página "Painéis da UF". `carregar(painel, resumo)` pede ao serviço o que falta e monta tudo."""
    abrir_caso = Signal(object)                # pendência escolhida na lista (o contêiner abre a ficha no mapa)

    def __init__(self, tela, parent=None):
        super().__init__(parent)
        self.tela, self.painel = tela, None
        self.dados: dict = {}
        externo = QVBoxLayout(self)
        externo.setContentsMargins(0, 0, 0, 0)
        self.rolagem = ScrollArea()
        self.rolagem.setWidgetResizable(True)
        self.rolagem.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.rolagem.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        conteudo = QWidget()
        conteudo.setStyleSheet("background: transparent;")
        v = QVBoxLayout(conteudo)
        v.setContentsMargins(0, 4, 8, 4)
        v.setSpacing(12)
        self.cabecalho = QLabel()
        self.cabecalho.setStyleSheet(f"color:{cor_texto_secundario()}; font-size:12px;")
        self.cabecalho.setWordWrap(True)
        v.addWidget(self.cabecalho)
        # cartões
        linha = QHBoxLayout()
        linha.setSpacing(10)
        self.cartoes = {
            "ativos": CartaoValor("Casos ativos", vocabulario.definicao("ATIVAS", "situacao")),
            "criticos": CartaoValor("Casos críticos", vocabulario.dica("CRITICO", "faixa")),
            "alem": CartaoValor(vocabulario.rotulo("KPI-03"), vocabulario.dica("KPI-03")),
            "vencidos": CartaoValor(vocabulario.rotulo("KPI-03b"), vocabulario.dica("KPI-03b")),
            "custo": CartaoValor(vocabulario.rotulo("KPI-05"), vocabulario.dica("KPI-05")),
        }
        for cartao in self.cartoes.values():
            linha.addWidget(cartao, 1)
        v.addLayout(linha)
        # o que fazer agora (fora de paineis: fica sempre no topo, logo abaixo dos cartões)
        self.texto_agora = QLabel()
        self.texto_agora.setWordWrap(True)
        self.texto_agora.setTextFormat(Qt.TextFormat.RichText)
        self.texto_agora.setStyleSheet(f"color:{cor_texto()}; font-size:13px;")
        self.agora = CartaoGrafico("O que fazer agora", "", self.texto_agora)
        self.agora.pergunta.hide()
        self.agora.rodape.hide()                       # a ordem das frases fica na dica (cabe acima da dobra)
        self.frases_agora: list[str] = []
        v.addWidget(self.agora)
        grade = QGridLayout()
        grade.setHorizontalSpacing(12)
        grade.setVerticalSpacing(12)
        # 1. onde agir primeiro
        self.barras_acao = BarrasH("Casos ativos por ação recomendada", largura_rotulo=210)
        corpo = QWidget()
        cv = QVBoxLayout(corpo)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.setSpacing(6)
        cv.addWidget(linha_legenda([("Críticos", COR_IDENTIDADE["CRITICO"]), ("Demais faixas", cor_contexto())]))
        cv.addWidget(self.barras_acao)
        self.prioridade = CartaoGrafico("Onde agir primeiro: casos ativos por ação recomendada",
                                        "Que providência a UF precisa tomar, para quantos casos, e quantos deles são "
                                        "críticos? As ações estão na ordem de urgência.", corpo)
        # 2. casos para agir já
        self.tabela_casos = TableWidget()
        self.tabela_casos.setColumnCount(5)
        self.tabela_casos.setHorizontalHeaderLabels(["Código", "Município", "Classe", "Ação recomendada",
                                                     "Além do prazo legal"])
        self.tabela_casos.verticalHeader().hide()
        self.tabela_casos.setEditTriggers(TableWidget.EditTrigger.NoEditTriggers)
        self.tabela_casos.setSelectionBehavior(TableWidget.SelectionBehavior.SelectRows)
        self.tabela_casos.setWordWrap(False)
        self.tabela_casos.verticalHeader().setDefaultSectionSize(30)
        self.tabela_casos.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.tabela_casos.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        self.tabela_casos.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.tabela_casos.cellDoubleClicked.connect(self._caso_escolhido)
        self.tabela_casos.setMinimumHeight(30 * (MAX_CASOS + 1) + 8)
        self.lista_vazia = QLabel()                    # no lugar da tabela, quando não há caso para listar
        self.lista_vazia.setStyleSheet(f"color:{cor_texto()}; font-size:13px;")
        self.lista_vazia.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lista_vazia.setMinimumHeight(80)
        self.lista_vazia.hide()
        corpo = QWidget()
        cv = QVBoxLayout(corpo)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.addWidget(self.tabela_casos)
        cv.addWidget(self.lista_vazia)
        self.casos = CartaoGrafico("Casos para agir já: críticos além do prazo legal",
                                   "Quais casos críticos já passaram do prazo legal da classe? Dos mais atrasados "
                                   "para os menos. Duplo clique abre a ficha no mapa.", corpo)
        # 3. evolução
        self.linha_estoque = LinhasAno("Casos ativos no fim de cada ano", "casos ativos", 230)
        self.linha_fluxos = LinhasAno("Entradas e saídas por ano", "casos por ano", 230)
        corpo = QWidget()
        cv = QVBoxLayout(corpo)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.setSpacing(4)
        self.texto_evolucao = QLabel()
        self.texto_evolucao.setWordWrap(True)
        self.texto_evolucao.setStyleSheet(f"color:{cor_texto()}; font-size:12px;")
        cv.addWidget(self.texto_evolucao)
        cv.addWidget(self.linha_estoque)
        cv.addWidget(self.linha_fluxos)
        self.evolucao = CartaoGrafico("Evolução da UF: o estoque e o que entra e sai",
                                      "Casos que entraram no cadastro e casos encerrados, por ano.", corpo)
        # 4. UF × país
        self.texto_comparacao = QLabel()
        self.texto_comparacao.setWordWrap(True)
        self.texto_comparacao.setTextFormat(Qt.TextFormat.RichText)
        self.texto_comparacao.setStyleSheet(f"color:{cor_texto()}; font-size:12px;")
        self.halteres = Halteres("Indicadores da UF e do país", "UF", "Brasil", largura_rotulo=230)
        corpo = QWidget()
        cv = QVBoxLayout(corpo)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.setSpacing(6)
        cv.addWidget(self.texto_comparacao)
        cv.addWidget(self.halteres)
        self.comparacao = CartaoGrafico("UF × país nos indicadores de prazo e risco",
                                        "Na taxa de encerramento, maior é melhor; nos demais, menor é melhor. "
                                        "Cada linha mostra a UF e o país no "
                                        "mesmo eixo, de 0 a 100%.", corpo)
        self.comparacoes: list[Comparacao] = []
        # 5. custo
        self.barras_custo = BarrasH("Custo estimado por ação recomendada", largura_rotulo=210)
        self.partes_custo = BarraPartes("Custo estimado por categoria")
        corpo = QWidget()
        cv = QVBoxLayout(corpo)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.setSpacing(8)
        cv.addWidget(self.barras_custo)
        self.titulo_partes = QLabel("Divisão do custo nas quatro categorias")
        self.titulo_partes.setStyleSheet(f"color:{cor_texto()}; font-size:12px; font-weight:600;")
        cv.addWidget(self.titulo_partes)
        cv.addWidget(self.partes_custo)
        self.custo = CartaoGrafico("Custo estimado para resolver os casos ativos da UF",
                                   "Quanto custa resolver e em que tipo de providência está o dinheiro?", corpo)
        grade.addWidget(self.prioridade, 0, 0)
        grade.addWidget(self.casos, 0, 1)
        grade.addWidget(self.evolucao, 1, 0, 2, 1)
        grade.addWidget(self.comparacao, 1, 1)
        grade.addWidget(self.custo, 2, 1)
        grade.setColumnStretch(0, 5)                   # a coluna da lista um pouco mais larga: a ação cabe inteira
        grade.setColumnStretch(1, 6)
        v.addLayout(grade)
        v.addStretch(1)
        self.rolagem.setWidget(conteudo)
        externo.addWidget(self.rolagem)
        self.paineis = {"prioridade": self.prioridade, "casos": self.casos, "evolucao": self.evolucao,
                        "comparacao": self.comparacao, "custo": self.custo}
        self._casos: list = []
        self._candidatos: list = []                    # (dias além do prazo legal, pendência), todos, já ordenados

    def mostrar_painel(self, chave: str):
        """Leva a seção à vista (a página é uma só; compatível com a navegação por painel)."""
        if chave in self.paineis:
            self.rolagem.ensureWidgetVisible(self.paineis[chave])

    # dados
    def carregar(self, painel, resumo=None):
        """Pede ao serviço os números da UF (cada consulta fica na trilha) e monta a página."""
        servico, usuario, nivel = self.tela.app.acervo, self.tela.usuario, painel.nivel
        self.painel = painel
        if resumo is None or resumo.nivel is not nivel:
            resumo = servico.resumo_agregado(usuario, nivel)
        kpis = {k.id: k for k in servico.kpis(usuario, nivel)}
        custo = servico.painel_custo(usuario, nivel, por="classe")
        panorama = servico.panorama(usuario, nivel)
        referencia = servico.referencia_nacional(usuario)
        self.dados = {"resumo": resumo, "kpis": kpis, "custo": custo, "panorama": panorama,
                      "referencia": referencia}
        self._montar()

    def _tabela(self, agrupamento):
        titulos, linhas = self.dados["resumo"].tabelas[agrupamento]
        return list(titulos), linhas

    def _montar(self):
        painel, d = self.painel, self.dados
        hoje = painel.hoje
        corte = f"{hoje:%d/%m/%Y}"
        uf = painel.escopo.replace("UF ", "")
        titulos, por_acao = self._tabela("POR ACAO RECOMENDADA")
        i_n, i_c = titulos.index("PENDENCIAS"), titulos.index(analise.CRITICAS)
        i_alem = titulos.index(analise.ALEM_DO_PRAZO)
        ativos = sum(l[i_n] for l in por_acao)
        criticos = sum(l[i_c] for l in por_acao)
        alem = sum(l[i_alem] for l in por_acao)
        encerrados = sum(1 for p in painel.pendencias if not p.ativa(hoje))
        k, ref = d["kpis"], d["referencia"]
        self.cabecalho.setText(
            f"UF {uf} · {vocabulario.casos(ativos, 'ativos')} em {corte} · "
            f"{vocabulario.casos(encerrados, 'encerrados')} no histórico.")
        estoque = d["panorama"].serie["estoque_total"]
        anterior = estoque.get(hoje.year - 1)
        contexto = "sem o ano anterior para comparar"
        if anterior is not None:
            diferenca = ativos - anterior
            contexto = (f"{'+' if diferenca > 0 else ''}{formatos.inteiro(diferenca)} desde o fim de {hoje.year - 1} "
                        f"({formatos.inteiro(anterior)}) · {contexto}")
        self.cartoes["ativos"].definir(formatos.inteiro(ativos), contexto)
        self.cartoes["criticos"].definir(formatos.inteiro(criticos),
                                         f"{formatos.percentual(_pct(criticos, ativos) or 0)} dos ativos · Brasil "
                                         f"{_pct_txt(_pct(ref.criticas, ref.ativas))}")
        self.cartoes["alem"].definir(formatos.percentual(k["KPI-03"].valor) if k["KPI-03"].valor is not None
                                     else "SUPRIMIDO", f"{vocabulario.casos(alem)} de {formatos.inteiro(ativos)} · "
                                     f"Brasil {_pct_txt(_pct(ref.alem_do_prazo, ref.ativas))}")
        vencidos = sum(l[titulos.index(analise.FORA_DA_PREVISAO)] for l in por_acao)
        self.cartoes["vencidos"].definir(formatos.percentual(k["KPI-03b"].valor) if k["KPI-03b"].valor is not None
                                         else "SUPRIMIDO", f"{vocabulario.casos(vencidos)} de "
                                         f"{formatos.inteiro(ativos)} · Brasil "
                                         f"{_pct_txt(_pct(ref.fora_da_previsao, ref.ativas))}")
        c = d["custo"]
        self.cartoes["custo"].definir(_mi(c.total or 0), "para resolver os casos ativos")
        for chave, kpi in (("alem", "KPI-03"), ("vencidos", "KPI-03b"), ("custo", "KPI-05")):
            self.cartoes[chave].setToolTip(vocabulario.dica(kpi))
        self._prioridade(por_acao, titulos, ativos, uf, corte)
        self._casos_ja(hoje)
        self._evolucao(uf, corte)
        self._comparacao(ativos, criticos, alem, vencidos, uf)
        self._custo(por_acao, titulos, uf, corte)
        self._proximo_passo(por_acao, titulos, self._candidatos, self.comparacoes, corte)

    def _proximo_passo(self, por_acao, titulos, candidatos, comparacoes, corte):
        """Até três frases, nesta ordem: a ação mais urgente com casos, o caso mais atrasado e a distância do
        Brasil. Frase sem dado não aparece (nada de "Comece por:" vazio); as seguintes sobem."""
        i_n, i_c = titulos.index("PENDENCIAS"), titulos.index(analise.CRITICAS)
        frases = []
        primeira = next((l for l in por_acao if l[i_n]), None)        # por_acao já vem na ordem de urgência
        if primeira is not None:
            n, c = primeira[i_n], primeira[i_c]
            frases.append(f"Comece por <b>{vocabulario.rotulo(primeira[0], 'acao')}</b>: {vocabulario.casos(n)}, "
                          f"{formatos.inteiro(c)} {'crítico' if c == 1 else 'críticos'} (a ação mais urgente com "
                          "casos na UF).")
        if candidatos:
            alem, p = candidatos[0]
            acao = regras.acao_recomendada(p, self.painel.hoje, self.painel.regras)
            frases.append(f"Caso mais atrasado: <b>{p.codigo}</b>, "
                          f"{vocabulario.rotulo(p.classe_risco, 'classe').lower()}, "
                          f"{formatos.numero(alem / formatos.DIAS_POR_ANO, 1)} anos além do prazo legal; ação "
                          f"recomendada: {vocabulario.rotulo(acao, 'acao').lower()}.")
        comparaveis = [cp for cp in comparacoes if cp.veredito is not None]
        piores = [cp for cp in comparaveis if cp.veredito == "pior"]
        if piores:
            cp = max(piores, key=lambda cp: cp.diferenca)
            frases.append(f"Maior distância do Brasil: <b>{cp.rotulo}</b>, {formatos.numero(cp.diferenca, 1)} p.p. "
                          f"pior (UF {_pct_txt(cp.valor)}, Brasil {_pct_txt(cp.referencia)}).")
        elif comparaveis:
            cp = min(comparaveis, key=lambda cp: cp.diferenca)
            frases.append(f"A UF está melhor ou igual ao Brasil nos {len(comparaveis)} indicadores comparados; a "
                          f"menor folga é em <b>{cp.rotulo}</b> ({formatos.numero(cp.diferenca, 1)} p.p.).")
        self.frases_agora = frases
        if frases:
            self.texto_agora.setText("<br>".join(f"{i}. {f}" for i, f in enumerate(frases, 1)))
        else:
            self.texto_agora.setText("Sem casos ativos e sem comparação com o Brasil: nada a priorizar.")
        self.agora.setToolTip("Ordem: a ação mais urgente com casos, o caso mais atrasado e a maior distância do "
                              "Brasil, a partir dos números desta página.")

    def _prioridade(self, por_acao, titulos, ativos, uf, corte):
        i_n, i_c, i_alem = titulos.index("PENDENCIAS"), titulos.index(analise.CRITICAS), titulos.index(analise.ALEM_DO_PRAZO)
        barras = []
        for l in por_acao:                                  # já na ordem de urgência (regras.ACOES)
            n, c, a = l[i_n], l[i_c], l[i_alem]
            rotulo = vocabulario.rotulo(l[0], "acao")
            barras.append(Barra(rotulo, [(c, COR_IDENTIDADE["CRITICO"], "Críticos"), (n - c, cor_contexto(), "Demais")],
                                f"{vocabulario.casos(n)}, {formatos.inteiro(c)} {'crítico' if c == 1 else 'críticos'}",
                                f"{rotulo}\n{vocabulario.casos(n, 'ativos')}, {formatos.inteiro(c)} críticos, "
                                f"{formatos.inteiro(a)} além do prazo legal\n{vocabulario.definicao(l[0], 'acao')}"))
        self.barras_acao.definir(barras)
        self.prioridade.definir_rodape(f"As barras somam os {vocabulario.casos(ativos, 'ativos')} da UF {uf}.")

    def _casos_ja(self, hoje):
        r = self.painel.regras
        candidatos, ativos, criticos = [], 0, 0
        for p in self.painel.pendencias:
            if not p.ativa(hoje):
                continue
            ativos += 1
            if regras.categoria(p, hoje) != "CRITICO":
                continue
            criticos += 1
            alem = regras.dias_alem_do_prazo_limite(p, hoje, r)
            if alem > 0:
                candidatos.append((alem, p))
        candidatos.sort(key=lambda x: (-x[0], x[1].codigo))
        self._candidatos = candidatos
        self._casos = [p for _, p in candidatos[:MAX_CASOS]]
        self.tabela_casos.setRowCount(len(self._casos))
        for i, (alem, p) in enumerate(candidatos[:MAX_CASOS]):
            acao = regras.acao_recomendada(p, hoje, r)
            valores = (p.codigo, p.municipio, vocabulario.rotulo(p.classe_risco, "classe"),
                       vocabulario.rotulo(acao, "acao"), f"{formatos.numero(alem / formatos.DIAS_POR_ANO, 1)} anos")
            dicas = ("", f"{p.municipio}/{p.uf}", "", f"{valores[3]}\n{vocabulario.definicao(acao, 'acao')}",
                     f"{formatos.inteiro(alem)} dias além do prazo legal")
            for j, (texto, dica) in enumerate(zip(valores, dicas)):
                item = QTableWidgetItem(texto)
                if j == 4:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                if dica:
                    item.setToolTip(dica)
                self.tabela_casos.setItem(i, j, item)
        self.tabela_casos.resizeColumnToContents(1)        # município estreito: a ação recomendada cabe inteira
        self.tabela_casos.setColumnWidth(1, min(self.tabela_casos.columnWidth(1), LARGURA_MUNICIPIO))
        total = len(candidatos)
        vazia = SEM_ATIVOS if not ativos else SEM_CRITICOS if not criticos else SEM_ATRASO if not total else ""
        self.lista_vazia.setText(vazia)
        self.lista_vazia.setVisible(bool(vazia))
        self.tabela_casos.setVisible(not vazia)
        if vazia:
            self.casos.definir_rodape(f"{vazia}.")
        else:
            self.casos.definir_rodape(f"Mostrando {min(total, MAX_CASOS)} de {vocabulario.casos(total)} críticos além "
                                      "do prazo legal na UF. A lista completa está na Planilha analítica, com o filtro "
                                      "Faixa de risco em Crítico.")

    def _caso_escolhido(self, linha: int, _coluna: int):
        if 0 <= linha < len(self._casos):
            self.abrir_caso.emit(self._casos[linha])

    def _evolucao(self, uf, corte):
        serie = self.dados["panorama"].serie
        anos = serie["anos"]
        estoque = {a: serie["estoque_total"][a] for a in anos}
        self.linha_estoque.definir(anos, [Serie("Casos ativos", estoque, categorica(0), area=True)],
                                   formato=formatos.inteiro)
        self.linha_fluxos.definir(anos, [Serie("Entradas", serie["entradas"], categorica(0)),
                                         Serie("Saídas (encerrados)", serie["saidas"], categorica(1))],
                                  formato=formatos.inteiro)
        ultimo, base = anos[-1], anos[-1] - 5
        texto = f"<b>{formatos.inteiro(estoque[ultimo])}</b> casos ativos em {corte}"
        if base in estoque and estoque[base]:
            variacao = 100 * (estoque[ultimo] - estoque[base]) / estoque[base]
            sinal = "+" if variacao > 0 else ""
            texto += (f", contra {formatos.inteiro(estoque[base])} no fim de {base} "
                      f"(<b>{sinal}{formatos.numero(variacao, 1)}%</b> em 5 anos)")
        cinco = [a for a in anos if a > ultimo - 5]
        entradas = sum(serie["entradas"][a] or 0 for a in cinco)
        saidas = sum(serie["saidas"][a] or 0 for a in cinco)
        texto += (f". Nos últimos cinco anos ({cinco[0]} a {ultimo}), entraram {formatos.inteiro(entradas)} e "
                  f"saíram {formatos.inteiro(saidas)}.")
        self.texto_evolucao.setText(texto)
        self.evolucao.definir_rodape(f"{ultimo} ainda está em andamento.")

    def _comparacao(self, ativos, criticos, alem, vencidos, uf):
        ref, k = self.dados["referencia"], self.dados["kpis"]
        taxa = k["KPI-02"]
        self.comparacoes = [
            Comparacao("Casos críticos", _pct(criticos, ativos), _pct(ref.criticas, ref.ativas), False),
            Comparacao(vocabulario.rotulo("KPI-03"), _pct(alem, ativos), _pct(ref.alem_do_prazo, ref.ativas), False),
            Comparacao(vocabulario.rotulo("KPI-03b"), _pct(vencidos, ativos), _pct(ref.fora_da_previsao, ref.ativas),
                       False),
            Comparacao(f"{vocabulario.rotulo('KPI-02')} ({ref.ano_taxa})", taxa.valor, ref.taxa_encerramento, True),
        ]
        self.halteres.rotulo_valor = f"UF {uf}"
        self.halteres.definir([Haltere(cp.rotulo, cp.valor, cp.referencia) for cp in self.comparacoes])
        contagem = {v: sum(cp.veredito == v for cp in self.comparacoes) for v in ("melhor", "pior", "igual")}
        partes = [f"{v} em {n}" for v, n in contagem.items() if n]
        resumo = (f"<b>UF {uf} × Brasil:</b> {_lista(partes)} dos {len(self.comparacoes)} indicadores."
                  if partes else f"<b>UF {uf} × Brasil:</b> sem comparação.")
        self.texto_comparacao.setText(resumo + "<br>" + "<br>".join(cp.frase() for cp in self.comparacoes))
        self.comparacao.definir_rodape("p.p. = pontos percentuais. Taxa de encerramento: casos encerrados no ano "
                                       "sobre os ativos em 1º de janeiro.")
        self.comparacao.setToolTip("Os totais do Brasil escondem números muito pequenos, para proteger poucos casos.")

    def _custo(self, por_acao, titulos, uf, corte):
        c = self.dados["custo"]
        i_custo, i_n = titulos.index("CUSTO ESTIMADO"), titulos.index("PENDENCIAS")
        ordenadas = sorted(por_acao, key=lambda l: -l[i_custo])
        barras = [Barra(vocabulario.rotulo(l[0], "acao"), [(l[i_custo], categorica(0), "Custo")], _mi(l[i_custo]),
                        f"{vocabulario.rotulo(l[0], 'acao')}: R$ {formatos.numero(l[i_custo], 2)} "
                        f"({vocabulario.casos(l[i_n])})") for l in ordenadas]
        self.barras_custo.definir(barras)
        partes = [(vocabulario.rotulo(cat, "categoria_custo"), c.por_categoria.get(cat) or 0.0, categorica(i),
                   vocabulario.definicao(cat, "categoria_custo"))
                  for i, cat in enumerate(("INVESTIGACAO", "REMEDIACAO", "MONITORAMENTO", "DISPOSICAO"))]
        self.partes_custo.definir(partes, _mi)
        self.custo.definir_rodape(f"Total: {_mi(c.total or 0)} (R$ {formatos.numero(c.total or 0, 2)}) nos casos ativos "
                                  f"da UF {uf}. As barras e as categorias somam o total.")
