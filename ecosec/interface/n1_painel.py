"""Painel analítico do N1: um painel executivo organizado por PERGUNTAS.

O N1 precisa ter cara de painel profissional: sem informação comprometedora, mas sem ser
infantilizado com gráfico limitado. Política da camada: dados internos, sem dado
financeiro, sem CNPJ, nome, endereço ou coordenada; só agregados, com k=3 e supressão complementar.

Estrutura (de cima para baixo):
  - filtro do N1 (classe e ano) numa BarraFiltros ligada ao EstadoN1, como antes;
  - faixa de indicadores: nome do vocabulário, valor, variação contra o ano anterior (seta e texto), base,
    corte e linha de tendência; o código (KPI-xx) só na dica;
  - cinco seções, cada uma com o nome da pergunta que responde:
      1. Onde estão os casos?        coroplético por UF + ranking das 27 UFs no mesmo indicador + regiões;
      2. Que tipo de passivo?         as três classes + atividade de origem + região × classe;
      3. Por que continuam abertos?   motivos da permanência + composição de cada classe por motivo;
      4. Estão sendo resolvidos?      estoque, entradas × saídas, taxa anual, tempo até o encerramento, idade;
      5. Quanto está fora do prazo?   as duas definições de prazo por região, por classe e por UF + região × classe.

Todo número vem do serviço (panorama, painel_classe, painel_uf, painel_encerramento e painel_n1), que aplica o
nível, o k e a trilha. A tela só divide parte por total quando os dois vêm visíveis (percentuais), e None aparece
"Suprimido", nunca 0. Clicar numa classe (barra, célula, cartão) filtra por ela; clicar num ano (linha ou
coluna) escolhe o ano; passar o mouse numa UF (mapa ou ranking) realça a UF nas duas vistas.
"""
from __future__ import annotations

from datetime import date

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QHeaderView, QStackedWidget, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from ecosec.acervo import analise, formatos, vocabulario
from ecosec.acervo.filtro import Filtro
from ecosec.interface import n1_graficos as g
from ecosec.interface.componentes.barra_filtros import BarraFiltros
from ecosec.interface.componentes.legenda_quantis import (COR_SEM_ATIVAS, COR_SUPRIMIDA, RAMPA, LegendaQuantis,
                                                          quintis)
from ecosec.interface.estado_filtro import EstadoFiltro
from ecosec.interface.fluent import (FIF, CaptionLabel, ComboBox, PushButton, ScrollArea, SegmentedWidget,
                                     StrongBodyLabel, TransparentPushButton)
from ecosec.interface.painel_n1 import EstadoN1

CLASSES = g.CLASSES
TODAS_CLASSES = "Todas as classes"
ROTULO_CLASSE = {c: vocabulario.rotulo(c, "classe") for c in CLASSES}

# ---------------------------------------------------------------- seções (o nome visível é a pergunta)
SECOES = (("onde", "Onde estão os casos?"), ("tipo", "Que tipo de passivo?"),
          ("motivos", "Por que continuam abertos?"), ("resolucao", "Estão sendo resolvidos?"),
          ("prazo", "Quanto está fora do prazo?"))
TITULO_SECAO = dict(SECOES)
LEGENDA_SECAO = {
    "onde": "Distribuição dos casos ativos pelo território, no mesmo indicador no mapa e no ranking.",
    "tipo": "Composição do passivo: classe, atividade que deu origem ao caso e a mistura de classes em cada região.",
    "motivos": "O que impede a solução: o motivo registrado para cada caso continuar aberto.",
    "resolucao": "Ritmo de solução: o estoque ao longo do tempo, o que entra e o que sai, a taxa anual, quanto "
                 "tempo um caso costuma levar e há quanto tempo os casos abertos esperam.",
    "prazo": "Duas medidas de atraso: além do prazo legal (passou do tempo máximo que a norma tolera para a classe) "
             "e prazo previsto vencido (o prazo combinado para o caso passou).",
}

# ---------------------------------------------------------------- indicadores do mapa e do ranking
PRESSAO, ATIVOS = "Índice de pressão", "Casos ativos"
CRITICOS = f"Casos em {vocabulario.rotulo_longo('CRITICO', 'faixa').lower()}"
ALEM, FORA = vocabulario.ROTULO_KPI["KPI-03"], vocabulario.ROTULO_KPI["KPI-03b"]
INDICADORES = (PRESSAO, ATIVOS, CRITICOS, ALEM, FORA)
UNIDADE_INDICADOR = {PRESSAO: "índice de 0 a 1, posição entre as UFs", ATIVOS: "casos ativos",
                     CRITICOS: "% dos casos ativos da UF", ALEM: "% dos casos ativos da UF",
                     FORA: "% dos casos ativos da UF"}
NOME_COMPONENTE = {"volume": "volume de casos ativos", "severidade": "fração em risco crítico",
                   "atraso": "fração além do prazo legal", "custo": "custo estimado"}
FAIXAS_IDADE = {"<1": "menos de 1 ano", "1-3": "1 a 3 anos", "3-5": "3 a 5 anos", "5-10": "5 a 10 anos",
                "10-20": "10 a 20 anos", "≥20": "20 anos ou mais"}


def dica_fonte(fonte: str, nivel_minimo: int, corte, observacao: str = "") -> str:
    """A dica de um gráfico: só a explicação para quem lê. A origem técnica (função, nível, corte) não aparece mais
    na tela; os parâmetros ficam para quem chama documentar."""
    return observacao.strip()


def pct(parte, total):
    """% de parte sobre total só com os dois visíveis (None em qualquer um: Suprimido, nunca recalculado)."""
    if parte is None or total is None or not total:
        return None
    return 100 * parte / total


def formula_pressao(pesos) -> str:
    """A conta do Índice de pressão do nível, com os pesos que o serviço usou."""
    termos = " + ".join(f"{formatos.numero(peso, 3).rstrip('0').rstrip(',')} × posição na {NOME_COMPONENTE[k]}"
                        .replace("posição na volume", "posição no volume") for k, peso in pesos)
    sem_custo = all(k != "custo" for k, _ in pesos)
    return (f"Índice de pressão{' (Nível 1, sem custo)' if sem_custo else ''} = {termos}. Posição = percentil da UF "
            "entre as 27, de 0 (menor) a 1 (maior); o índice compara UFs, não é escala física"
            + (". Nenhum valor em reais entra na conta." if sem_custo else "."))


def _rotular(rotulo: CaptionLabel, texto: str, secundario: bool = True):
    rotulo.setText(texto)
    rotulo.setWordWrap(True)
    rotulo.setStyleSheet(f"color:{g.tokens()['texto2' if secundario else 'texto']};")


# ---------------------------------------------------------------- cartões
class Tendencia(QWidget):
    """Linha de tendência (12+ pontos) do cartão de indicador: o histórico atenuado e o ano do corte em destaque."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pontos: list = []
        self.setFixedSize(84, 26)

    def definir(self, pontos):
        self.pontos = [(a, v) for a, v in pontos if v is not None]
        self.setVisible(len(self.pontos) >= 3)
        self.update()

    def paintEvent(self, evento):                           # noqa: N802
        if len(self.pontos) < 3:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        ys = [v for _, v in self.pontos]
        menor, maior = min(ys), max(ys)
        faixa = (maior - menor) or 1
        n = len(self.pontos) - 1

        def ponto(i, v):
            return QPointF(3 + i / n * (self.width() - 8), self.height() - 4 - (v - menor) / faixa * (self.height() - 8))
        caminho = QPainterPath(ponto(0, ys[0]))
        for i, v in enumerate(ys[1:], 1):
            caminho.lineTo(ponto(i, v))
        p.setPen(QPen(QColor(g.tokens()["suprimido"]), 1.5))
        p.drawPath(caminho)
        p.setPen(QPen(QColor(g.tokens()["cartao"]), 1.5))
        p.setBrush(QColor(g.cor_neutra()))
        p.drawEllipse(ponto(n, ys[-1]), 3.2, 3.2)
        p.end()


class CartaoIndicador(QFrame):
    """Um indicador: nome (vocabulário), valor, variação contra o ano anterior (seta + texto, cor pela direção
    boa) e a base. A dica traz a definição e a conta, sem fonte nem corte."""

    def __init__(self, id_: str, parent=None):
        super().__init__(parent)
        self.id, self.indicador = id_, None
        self.setObjectName("cartao_indicador")
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 9, 10, 9)
        v.setSpacing(2)
        self.nome = CaptionLabel()
        self.valor = StrongBodyLabel()
        fonte = self.valor.font()
        fonte.setPixelSize(24)
        fonte.setWeight(QFont.Weight.DemiBold)
        self.valor.setFont(fonte)
        self.tendencia = Tendencia()
        linha = QHBoxLayout()
        linha.setContentsMargins(0, 0, 0, 0)
        linha.addWidget(self.valor)
        linha.addStretch(1)
        linha.addWidget(self.tendencia, 0, Qt.AlignmentFlag.AlignBottom)
        self.variacao = CaptionLabel()
        self.base = CaptionLabel()
        v.addWidget(self.nome)
        v.addLayout(linha)
        v.addWidget(self.variacao)
        v.addWidget(self.base)
        self._estilo()

    def _estilo(self):
        t = g.tokens()
        self.setStyleSheet(f"#cartao_indicador {{ background:{t['cartao']}; border:1px solid {t['borda']}; "
                           "border-radius:6px; }")
        self.nome.setStyleSheet(f"color:{t['texto2']}; font-weight:600;")
        self.base.setStyleSheet(f"color:{t['mudo']};")

    def definir(self, ind, k: int):
        self.indicador = ind
        self._estilo()
        self.nome.setText(ind.nome)
        self.nome.setWordWrap(True)
        self.valor.setText(self.texto_valor(ind))
        cor = g.tokens()["mudo"] if ind.valor is None else g.tokens()["texto"]
        self.valor.setTextColor(QColor(cor), QColor(cor))
        texto, tipo = self.texto_variacao(ind)
        self.variacao.setText(texto)
        self.variacao.setStyleSheet(f"color:{g.cor_status(tipo)}; font-weight:600;")
        self.base.setText(ind.base)
        self.base.setWordWrap(True)
        self.tendencia.definir(ind.serie if ind.valor is not None else ())
        definicao = vocabulario.dica(ind.id, "kpi") if ind.id.startswith("KPI") else {
            "ATIVOS": "Casos ativos: identificados até a data de corte e ainda sem solução nessa data.",
            "CRITICOS": f"{ind.nome}: {vocabulario.definicao('CRITICO', 'faixa')} Unidade: % dos casos ativos."}[ind.id]
        extra = g.nota_suprimido(k) if (ind.valor is None and "não atingido" not in ind.observacao and k) else ""
        if ind.ano_anterior is not None and ind.variacao is None:
            extra += ("\n" if extra else "") + (f"Sem variação: o valor de {ind.ano_anterior} ou o atual está "
                                                "suprimido (ou não atingido).")
        self.setToolTip("\n".join(x for x in (definicao, dica_fonte(ind.fonte, ind.nivel_minimo, ind.corte,
                                                                    ind.observacao), extra) if x))

    @staticmethod
    def texto_valor(ind) -> str:
        if ind.valor is None:
            return "não atingido" if "não atingido" in ind.observacao else g.SUPRIMIDO
        if ind.unidade == "casos":
            return formatos.inteiro(ind.valor)
        if ind.unidade.startswith("%"):
            return g.fmt_pct(ind.valor)
        return f"{formatos.numero(ind.valor, 1)} anos"

    @staticmethod
    def texto_variacao(ind) -> tuple[str, str]:
        """("▲ +0,9 p.p. em relação a 2025", "ruim"). Sem ano anterior ou com um dos dois suprimido: neutro."""
        if ind.ano_anterior is None:
            return "sem ano anterior na série", "neutro"
        if ind.variacao is None:
            return f"sem comparação com {ind.ano_anterior}", "neutro"
        if abs(ind.variacao) < 1e-9:
            return f"= estável em relação a {ind.ano_anterior}", "neutro"
        sinal = "+" if ind.variacao > 0 else "-"
        modulo = abs(ind.variacao)
        if ind.unidade.startswith("%"):
            quanto = f"{formatos.numero(modulo, 1)} p.p."
        elif ind.unidade == "casos":
            quanto = vocabulario.casos(round(modulo))
        else:
            quanto = f"{formatos.numero(modulo, 1)} {'ano' if modulo < 2 else 'anos'}"
        subiu = ind.variacao > 0
        bom = subiu == (ind.melhor == "maior")
        return f"{'▲' if subiu else '▼'} {sinal}{quanto} em relação a {ind.ano_anterior}", "bom" if bom else "ruim"


class CartaoGrafico(QFrame):
    """Moldura de um gráfico: título (afirmação descritiva), subtítulo (unidade, base, corte), o gráfico ou a sua
    tabela (botão "Ver tabela") e a nota de rodapé. A dica do título explica o gráfico. Os controles ficam à direita
    do título ou, com `controles_abaixo` (o cartão do mapa), numa linha própria abaixo do subtítulo."""

    def __init__(self, titulo: str, grafico: QWidget, controles: QWidget | None = None, parent=None,
                 controles_abaixo: bool = False):
        super().__init__(parent)
        self.setObjectName("cartao_grafico")
        self.grafico, self.dica = grafico, ""
        v = QVBoxLayout(self)
        v.setContentsMargins(14, 10, 14, 10)
        v.setSpacing(4)
        topo = QHBoxLayout()
        topo.setSpacing(8)
        cabeca = QVBoxLayout()
        cabeca.setSpacing(0)
        self.titulo = StrongBodyLabel(titulo)
        self.titulo.setWordWrap(True)
        self.subtitulo = CaptionLabel()
        cabeca.addWidget(self.titulo)
        cabeca.addWidget(self.subtitulo)
        topo.addLayout(cabeca, 1)
        if controles is not None and controles_abaixo:
            cabeca.addSpacing(6)
            cabeca.addWidget(controles)
        elif controles is not None:
            topo.addWidget(controles, 0, Qt.AlignmentFlag.AlignTop)
        self.botao_tabela = TransparentPushButton("Ver tabela")
        self.botao_tabela.setToolTip("Mostra os mesmos números em tabela (sem depender de cor)")
        self.botao_tabela.clicked.connect(self.alternar_tabela)
        topo.addWidget(self.botao_tabela, 0, Qt.AlignmentFlag.AlignTop)
        v.addLayout(topo)
        self.pilha = QStackedWidget()
        self.pilha.addWidget(grafico)
        self.tabela = QTableWidget()
        self.tabela.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.tabela.verticalHeader().hide()
        self.tabela.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.pilha.addWidget(self.tabela)
        v.addWidget(self.pilha, 1)
        self.nota = CaptionLabel()
        self.nota.setWordWrap(True)
        v.addWidget(self.nota)
        self._estilo()

    def _estilo(self):
        t = g.tokens()
        self.setStyleSheet(f"#cartao_grafico {{ background:{t['cartao']}; border:1px solid {t['borda']}; "
                           "border-radius:6px; }")
        self.subtitulo.setStyleSheet(f"color:{t['texto2']};")
        self.nota.setStyleSheet(f"color:{t['mudo']};")

    def definir(self, subtitulo: str, dica: str, nota: str = "", titulo: str | None = None):
        self._estilo()
        if titulo is not None:
            self.titulo.setText(titulo)
        self.subtitulo.setText(subtitulo)
        self.subtitulo.setWordWrap(True)
        self.dica = dica
        self.titulo.setToolTip(dica)
        self.subtitulo.setToolTip(dica)
        self.nota.setText(nota)
        self.nota.setVisible(bool(nota))
        if self.pilha.currentWidget() is self.tabela:
            self._preencher_tabela()

    def alternar_tabela(self):
        if self.pilha.currentWidget() is self.tabela:
            self.pilha.setCurrentWidget(self.grafico)
            self.botao_tabela.setText("Ver tabela")
        else:
            self._preencher_tabela()
            self.pilha.setCurrentWidget(self.tabela)
            self.botao_tabela.setText("Ver gráfico")

    def _preencher_tabela(self):
        titulos, linhas = self.grafico.tabela() if hasattr(self.grafico, "tabela") else ([], [])
        self.tabela.clear()
        self.tabela.setColumnCount(len(titulos))
        self.tabela.setRowCount(len(linhas))
        self.tabela.setHorizontalHeaderLabels(titulos)
        for i, linha in enumerate(linhas):
            for j, celula in enumerate(linha):
                self.tabela.setItem(i, j, QTableWidgetItem(str(celula)))
        self.tabela.setMinimumHeight(min(520, 34 + 26 * len(linhas)))


class CartaoClasse(QFrame):
    """Uma classe na seção "Que tipo de passivo?": casos ativos, parte do total (barra fina), quantidade na unidade
    da classe e idade mediana. Clicar filtra pela classe (clicar de novo tira o filtro)."""
    clicado = Signal(str)

    def __init__(self, classe: str, parent=None):
        super().__init__(parent)
        self.classe = classe
        self.setObjectName("cartao_classe")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        v = QVBoxLayout(self)
        v.setContentsMargins(14, 10, 14, 10)
        v.setSpacing(3)
        self.nome = StrongBodyLabel(ROTULO_CLASSE[classe])
        self.valor = StrongBodyLabel()
        fonte = self.valor.font()
        fonte.setPixelSize(22)
        fonte.setWeight(QFont.Weight.DemiBold)
        self.valor.setFont(fonte)
        self.parte = _BarraParte()
        self.detalhe = CaptionLabel()
        self.detalhe.setWordWrap(True)
        for w in (self.nome, self.valor, self.parte, self.detalhe):
            v.addWidget(w)
        self.selecionada = False

    def definir(self, linha, total, k: int, corte, selecionada: bool):
        t = g.tokens()
        self.selecionada = selecionada
        borda = g.cor_classe(self.classe)
        self.setStyleSheet(f"#cartao_classe {{ background:{t['cartao']}; border:1px solid "
                           f"{borda if selecionada else t['borda']}; border-left:4px solid {borda}; "
                           "border-radius:6px; }")
        n = linha.ativas if linha is not None else None
        parte = pct(n, total)
        self.valor.setText(g.SUPRIMIDO if n is None else vocabulario.casos(n, "ativos"))
        cor = t["mudo"] if n is None else t["texto"]
        self.valor.setTextColor(QColor(cor), QColor(cor))
        self.parte.definir(parte, borda)
        quantidade = (g.SUPRIMIDO if linha is None or linha.quantidade is None
                      else formatos.quantidade(linha.quantidade, self.classe))
        idade = (g.SUPRIMIDO if linha is None or linha.idade_mediana is None
                 else f"{formatos.numero(linha.idade_mediana, 1)} anos")
        partes = ([f"{g.fmt_pct(parte, 0)} dos casos ativos"] if parte is not None else []) + [
            f"quantidade {quantidade}", f"idade mediana {idade}"]
        self.detalhe.setText(" · ".join(partes))
        self.detalhe.setStyleSheet(f"color:{t['texto2']};")
        self.setToolTip(f"{vocabulario.dica(self.classe, 'classe')}\n"
                        + dica_fonte("analise.proteger_cubo", 1, corte, "A quantidade é só desta classe: "
                                     "toneladas e metros cúbicos não se somam.")
                        + (f"\n{g.nota_suprimido(k)}" if n is None and k else "")
                        + "\nClique para filtrar por esta classe.")

    def mousePressEvent(self, evento):                      # noqa: N802
        if evento.button() == Qt.MouseButton.LeftButton:
            self.clicado.emit(self.classe)


class _BarraParte(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.fracao, self.cor = None, "#888888"
        self.setFixedHeight(6)

    def definir(self, percentual, cor):
        self.fracao, self.cor = (None if percentual is None else percentual / 100), cor
        self.update()

    def paintEvent(self, evento):                           # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(g.tokens()["vazio"]))
        p.drawRoundedRect(QRectF(0, 0, self.width(), 6), 3, 3)
        if self.fracao:
            p.setBrush(QColor(self.cor))
            p.drawRoundedRect(QRectF(0, 0, max(6.0, self.width() * self.fracao), 6), 3, 3)
        p.end()


class Secao(QWidget):
    """Uma pergunta: título, uma linha de contexto e a grade de cartões."""

    def __init__(self, chave: str, parent=None):
        super().__init__(parent)
        self.chave = chave
        self.setObjectName(f"secao_{chave}")
        self.setStyleSheet(f"#secao_{chave} {{ background: transparent; }}")
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 4, 10, 12)
        v.setSpacing(8)
        self.titulo = StrongBodyLabel(TITULO_SECAO[chave])
        fonte = self.titulo.font()
        fonte.setPixelSize(18)
        self.titulo.setFont(fonte)
        self.legenda = CaptionLabel()
        _rotular(self.legenda, LEGENDA_SECAO[chave])
        v.addWidget(self.titulo)
        v.addWidget(self.legenda)
        self.grade = QGridLayout()
        self.grade.setHorizontalSpacing(10)
        self.grade.setVerticalSpacing(10)
        v.addLayout(self.grade)
        v.addStretch(1)
        self.cartoes: dict[str, CartaoGrafico] = {}

    def adicionar(self, chave: str, cartao: QWidget, linha: int, coluna: int, colunas: int = 1, peso: int = 1):
        self.grade.addWidget(cartao, linha, coluna, 1, colunas)
        self.grade.setColumnStretch(coluna, max(self.grade.columnStretch(coluna), peso))
        if isinstance(cartao, CartaoGrafico):
            self.cartoes[chave] = cartao

    def graficos(self) -> list:
        return [c.grafico for c in self.cartoes.values()]


# ---------------------------------------------------------------- o painel
class PainelN1(QWidget):
    """O painel analítico do N1. Mesmo EstadoN1 (classe, ano, UF em foco e seleção) para todas as seções; a
    BarraFiltros mostra só classe e ano (as dimensões que o cubo protegido do serviço conhece)."""

    def __init__(self, tela, parent=None):
        super().__init__(parent)
        self.tela, self.panorama, self._hoje = tela, None, None
        self.estado = EstadoN1()
        self.estado_filtro = EstadoFiltro(parent=self)
        self.dados: dict = {}
        self._quintil_de: dict[str, int] = {}
        externo = QVBoxLayout(self)
        externo.setContentsMargins(0, 6, 0, 0)
        externo.setSpacing(6)
        # filtro: classe e ano
        topo = QHBoxLayout()
        self.combo_classe = ComboBox()
        self.combo_classe.addItems([TODAS_CLASSES, *[ROTULO_CLASSE[c] for c in CLASSES]])
        self.combo_classe.setMinimumWidth(210)
        # O ano (data de corte) numa lista, como a classe: "Todos" (a situação atual) e os anos anteriores;
        # os itens entram na primeira carga, com a série do serviço. Os marcos ficam em "Estão sendo resolvidos?"
        self.combo_ano = ComboBox()
        self.combo_ano.addItem(vocabulario.TODOS_OS_ANOS)
        self.combo_ano.setMinimumWidth(130)
        topo.addWidget(CaptionLabel("Classe"))
        topo.addWidget(self.combo_classe)
        topo.addSpacing(12)
        topo.addWidget(CaptionLabel(vocabulario.CAMPO_ANO))
        topo.addWidget(self.combo_ano)
        topo.addStretch(1)
        externo.addLayout(topo)
        self.barra = BarraFiltros(self.estado_filtro)
        externo.addWidget(self.barra)
        # faixa de indicadores
        self.faixa = QHBoxLayout()
        self.faixa.setSpacing(8)
        self.cartoes = {i: CartaoIndicador(i) for i in ("ATIVOS", "KPI-03", "KPI-03b", "CRITICOS", "KPI-02",
                                                         "KPI-01", "KPI-04")}
        for c in self.cartoes.values():
            self.faixa.addWidget(c, 1)
        externo.addLayout(self.faixa)
        # navegação por perguntas
        nav = QHBoxLayout()
        self.abas_secoes = SegmentedWidget()
        nav.addWidget(self.abas_secoes)
        nav.addStretch(1)
        externo.addLayout(nav)
        # o aviso fica numa linha própria, abaixo das abas: na mesma linha, em janela estreita, ele era
        # espremido e ficava por baixo das abas
        self.aviso = CaptionLabel()
        self.aviso.setWordWrap(True)
        externo.addWidget(self.aviso)
        self.pilha = QStackedWidget()
        externo.addWidget(self.pilha, 1)
        self.secoes: dict[str, Secao] = {}
        self._rolagens: dict = {}
        self._montar_secoes()
        for chave, titulo in SECOES:
            rolagem = ScrollArea()
            rolagem.setWidgetResizable(True)
            rolagem.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            rolagem.setStyleSheet("QScrollArea { background: transparent; border: none; }")
            rolagem.setWidget(self.secoes[chave])
            self.pilha.addWidget(rolagem)
            self._rolagens[chave] = rolagem
            self.abas_secoes.addItem(chave, titulo, onClick=lambda *_, c=chave: self.mostrar_secao(c))
        self.secao_atual = None
        self.mostrar_secao("onde")
        # ligações (mediador: ninguém chama ninguém, todos observam o estado)
        self.combo_classe.currentIndexChanged.connect(
            lambda *_: self.estado.definir(classe=None if self.combo_classe.currentIndex() == 0
                                           else CLASSES[self.combo_classe.currentIndex() - 1]))
        self.combo_ano.currentIndexChanged.connect(self._ano_escolhido)
        self.mapa.uf_em_foco.connect(lambda uf: self.estado.definir(foco=uf))
        self.mapa.uf_clicada.connect(self._alternar_uf)
        self.legenda.passou.connect(self._realcar_quintil)
        self.legenda.escolhido.connect(self._selecionar_quintil)
        self.combo_indicador.currentIndexChanged.connect(lambda *_: self._mostrar_onde())
        self.estado.foco_mudou.connect(lambda *_: self._realce_uf())
        self.estado.selecao_mudou.connect(lambda *_: self._realce_uf())
        self.estado.classe_mudou.connect(self._classe_mudou)
        self.estado.ano_mudou.connect(lambda *_: self._recarregar())
        self.estado.classe_mudou.connect(
            lambda c: self.estado_filtro.definir(classes=frozenset({c}) if c else frozenset()))
        self.estado.ano_mudou.connect(self._ano_para_filtro)
        self.estado_filtro.mudou.connect(self._filtro_mudou)

    # ------------------------------------------------------------ montagem
    def _cartao(self, secao: Secao, chave: str, titulo: str, grafico, linha, coluna, colunas=1, peso=1,
                controles=None, controles_abaixo=False) -> CartaoGrafico:
        cartao = CartaoGrafico(titulo, grafico, controles, controles_abaixo=controles_abaixo)
        secao.adicionar(chave, cartao, linha, coluna, colunas, peso)
        if hasattr(grafico, "clicado"):
            grafico.clicado.connect(self._clique)
        return cartao

    def _montar_secoes(self):
        from ecosec.interface.mapa_vetorial import FATOR_ZOOM_TECLADO, MapaVetorial
        s = self.secoes
        # 1. Onde estão os casos?
        s["onde"] = Secao("onde")
        self.mapa = MapaVetorial()
        self.mapa.setMinimumHeight(430)
        self.mapa.zoom_com_ctrl = True              # No meio da página que rola, a roda sozinha rola a página
        self.legenda = LegendaQuantis()
        self.combo_indicador = ComboBox()
        self.combo_indicador.addItems(list(INDICADORES))
        self.combo_indicador.setMinimumWidth(260)
        caixa_mapa = QWidget()
        vm = QVBoxLayout(caixa_mapa)
        vm.setContentsMargins(0, 0, 0, 0)
        vm.addWidget(self.mapa, 1)
        vm.addWidget(self.legenda)
        caixa_mapa.tabela = self._tabela_mapa
        controles = QWidget()
        hc = QHBoxLayout(controles)
        hc.setContentsMargins(0, 0, 0, 0)
        hc.addWidget(CaptionLabel("Indicador"))
        hc.addWidget(self.combo_indicador)
        # − + e Brasil, na ordem do N2 e do N3; Brasil volta à vista base (o país inteiro)
        self.botao_menos, self.botao_mais, self.botao_brasil = PushButton("−"), PushButton("+"), PushButton("Brasil")
        self.botao_brasil.setIcon(FIF.HOME)
        self.botao_brasil.setToolTip("Volta o mapa ao Brasil inteiro; a escolha de UF continua.")
        self.botao_mais.clicked.connect(lambda *_: self.mapa.aproximar(FATOR_ZOOM_TECLADO))
        self.botao_menos.clicked.connect(lambda *_: self.mapa.aproximar(1 / FATOR_ZOOM_TECLADO))
        self.botao_brasil.clicked.connect(lambda *_: self.mapa.ir_para_brasil())
        hc.addSpacing(8)
        for botao in (self.botao_menos, self.botao_mais, self.botao_brasil):
            hc.addWidget(botao)
        hc.addStretch(1)                            # Numa linha própria, os controles ficam compactos
        self._cartao(s["onde"], "mapa", "Casos por UF", caixa_mapa, 0, 0, peso=3, controles=controles,
                     controles_abaixo=True)
        self.ranking = g.BarrasN1()
        self._cartao(s["onde"], "ranking", "Ranking das UFs", self.ranking, 0, 1, peso=2)
        self.regioes = g.BarrasN1()
        self._cartao(s["onde"], "regioes", "Casos ativos por região", self.regioes, 1, 0, colunas=2)
        # 2. Que tipo de passivo?
        s["tipo"] = Secao("tipo")
        faixa = QWidget()
        hf = QHBoxLayout(faixa)
        hf.setContentsMargins(0, 0, 0, 0)
        hf.setSpacing(10)
        self.cartoes_classe = {c: CartaoClasse(c) for c in CLASSES}
        for c in self.cartoes_classe.values():
            hf.addWidget(c, 1)
            c.clicado.connect(self._clique)
        s["tipo"].adicionar("classes", faixa, 0, 0, colunas=2)
        self.atividades = g.BarrasN1()
        self._cartao(s["tipo"], "atividades", "Casos ativos por atividade de origem", self.atividades, 1, 0, peso=3)
        self.regiao_classe = g.MapaCalorN1(g.RAMPA_CONTAGEM)
        self._cartao(s["tipo"], "regiao_classe", "Classes em cada região", self.regiao_classe, 1, 1, peso=2)
        # 3. Por que continuam abertos?
        s["motivos"] = Secao("motivos")
        self.motivos = g.BarrasN1()
        self._cartao(s["motivos"], "motivos", "Casos ativos por motivo da permanência", self.motivos, 0, 0, peso=3)
        self.motivo_classe = g.MapaCalorN1(g.RAMPA_CONTAGEM)
        self._cartao(s["motivos"], "motivo_classe", "O que segura cada classe", self.motivo_classe, 0, 1, peso=2)
        # 4. Estão sendo resolvidos?
        s["resolucao"] = Secao("resolucao")
        self.estoque = g.LinhasN1("casos ativos no fim do ano")
        self._cartao(s["resolucao"], "estoque", "Estoque de casos ativos", self.estoque, 0, 0)
        self.fluxos = g.LinhasN1("casos no ano")
        self._cartao(s["resolucao"], "fluxos", "Casos que entram e que saem a cada ano", self.fluxos, 0, 1)
        self.taxa = g.ColunasN1("% ao ano")
        self._cartao(s["resolucao"], "taxa", vocabulario.ROTULO_KPI["KPI-02"], self.taxa, 1, 0)
        self.curva = g.LinhasN1("% ainda ativos", degrau=True)
        self.curva.clicavel = False
        self._cartao(s["resolucao"], "curva", vocabulario.ROTULO_KPI["KPI-01"], self.curva, 1, 1)
        self.idade = g.Barras100N1()
        self._cartao(s["resolucao"], "idade", vocabulario.ROTULO_KPI["KPI-04"], self.idade, 2, 0, colunas=2)
        # 5. Quanto está fora do prazo?
        s["prazo"] = Secao("prazo")
        nomes = (ALEM.removeprefix("Casos ").capitalize(), FORA.removeprefix("Casos com ").capitalize())
        self.prazo_regiao = g.HalteresN1(nomes)
        self._cartao(s["prazo"], "prazo_regiao", "Fora do prazo por região", self.prazo_regiao, 0, 1)
        self.prazo_classe = g.HalteresN1(nomes)
        self._cartao(s["prazo"], "prazo_classe", "Fora do prazo por classe", self.prazo_classe, 0, 0)
        self.prazo_uf = g.HalteresN1(nomes)
        self._cartao(s["prazo"], "prazo_uf", "Fora do prazo por UF", self.prazo_uf, 1, 0)
        self.prazo_calor = g.MapaCalorN1(g.RAMPA_PRESSAO)
        self._cartao(s["prazo"], "prazo_calor", f"{ALEM}: região × classe", self.prazo_calor, 1, 1)
        for chave in ("ranking", "regioes"):
            s["onde"].grade.setAlignment(s["onde"].cartoes[chave], Qt.AlignmentFlag.AlignTop)

    # ------------------------------------------------------------ navegação
    def mostrar_secao(self, chave: str):
        if chave not in self.secoes:
            return
        self.pilha.setCurrentWidget(self._rolagens[chave])
        self.abas_secoes.setCurrentItem(chave)
        self.secao_atual = chave

    def graficos(self) -> list:
        return [gr for s in self.secoes.values() for gr in s.graficos()]

    # ------------------------------------------------------------ filtro (só classe e ano)
    def _ano_corrente(self) -> int:
        return self._hoje.year if self._hoje else self.estado.ano

    def _ano_para_filtro(self, ano: int):
        self.estado_filtro.definir(ano=None if ano >= self._ano_corrente() else ano)

    def _ano_escolhido(self, indice: int):
        """Lista "Ano": "Todos" é o ano corrente no estado (sem chip, corte em hoje; o EstadoN1 não aceita None);
        um ano, o corte em 31/12 dele."""
        if indice >= 0:
            self.estado.definir(ano=self._ano_corrente() if indice == 0 else int(self.combo_ano.itemText(indice)))

    def _preencher_anos(self, inicio: int):
        self.combo_ano.blockSignals(True)
        self.combo_ano.clear()                              # uma nova carga não duplica os itens
        self.combo_ano.addItems(vocabulario.itens_ano(inicio, self._hoje))
        self.combo_ano.blockSignals(False)

    def _mostrar_ano(self, ano: int):
        """A lista acompanha o estado (clique num ano do gráfico, chip removido) sem disparar o próprio sinal."""
        corrente = ano >= self._ano_corrente()
        self.combo_ano.blockSignals(True)
        self.combo_ano.setCurrentText(vocabulario.TODOS_OS_ANOS if corrente else str(ano))
        self.combo_ano.blockSignals(False)
        self.combo_ano.setToolTip(vocabulario.dica_ano(None if corrente else ano, self._hoje))

    def _filtro_mudou(self, filtro):
        restrito = Filtro(classes=filtro.classes if len(filtro.classes) <= 1 else frozenset(), ano=filtro.ano)
        if restrito != filtro:                              # outra dimensão no N1: descartada
            self.estado_filtro.substituir(restrito)
            return
        self.estado.definir(classe=next(iter(filtro.classes), None), ano=filtro.ano or self._ano_corrente())

    def _clique(self, valor):
        """Clique numa marca: classe -> filtra (de novo, tira); ano -> escolhe o ano; UF -> realça; região ->
        seleciona as UFs dela."""
        if valor in CLASSES:
            self.estado.definir(classe=None if self.estado.classe == valor else valor)
        elif isinstance(valor, int):
            self.estado.definir(ano=valor)
        elif isinstance(valor, tuple) and valor[0] == "UF":
            self._alternar_uf(valor[1])
        elif isinstance(valor, tuple) and valor[0] == "REGIAO":
            ufs = frozenset(analise.REGIOES.get(valor[1], ()))
            self.estado.definir(selecao=frozenset() if self.estado.selecao == ufs else ufs)

    def _classe_mudou(self, classe):
        self.combo_classe.blockSignals(True)
        self.combo_classe.setCurrentIndex(CLASSES.index(classe) + 1 if classe in CLASSES else 0)
        self.combo_classe.blockSignals(False)
        self._recarregar()

    def _alternar_uf(self, uf: str):
        self.estado.definir(selecao=self.estado.selecao ^ {uf})

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
        pais, _ = sinteticos.geografia()
        self.mapa.coropletico(pais, sinteticos.divisas_uf(), {}, {})
        self._recarregar(primeira=True)

    def _recarregar(self, primeira: bool = False):
        acervo, usuario, nivel = self.tela.app.acervo, self.tela.usuario, self.tela.nivel
        ano, classe = self.estado.ano, self.estado.classe
        self.panorama = acervo.panorama(usuario, nivel, ano, classe)
        p = self.panorama
        ano = p.ano
        self.dados = {"panorama": p, "n1": acervo.painel_n1(usuario, nivel, ano, classe),
                      "classe": acervo.painel_classe(usuario, nivel, ano, classe),
                      "uf": acervo.painel_uf(usuario, nivel, ano, classe),
                      "encerramento": acervo.painel_encerramento(usuario, nivel, classe)}
        if primeira:                                        # carregar(): os anos da série do serviço
            self._preencher_anos((p.serie["anos"] or [p.hoje.year])[0])
        self._mostrar_ano(p.ano)
        self._atualizar_contagem()
        k = p.supressao_minima
        self.aviso.setText("Totais agregados, sem valores em reais. Totais muito pequenos ficam ocultos."
                           if k else "Totais agregados")
        self.aviso.setStyleSheet(f"color:{g.tokens()['mudo']};")
        for ind in self.dados["n1"].indicadores:
            if ind.id in self.cartoes:
                self.cartoes[ind.id].definir(ind, k)
        self._mostrar_onde()
        self._mostrar_tipo()
        self._mostrar_motivos()
        self._mostrar_resolucao()
        self._mostrar_prazo()

    def _atualizar_contagem(self):
        p = self.panorama
        visiveis = [n for n in p.totais_classe.values() if isinstance(n, int)]
        total = p.serie.get("estoque_total", {}).get(p.ano)
        if total is None:
            total = sum(serie.get(p.ano) or 0 for serie in p.serie.get("ativas", {}).values())
        texto = f"{formatos.inteiro(sum(visiveis))} casos ativos no recorte (de {formatos.inteiro(total)})"
        if len(visiveis) < len(p.totais_classe):
            texto += " · classe com poucos casos: suprimida"
        self.barra.definir_texto_contagem(texto)

    # ------------------------------------------------------------ comum
    @property
    def k(self) -> int:
        return self.panorama.supressao_minima if self.panorama else 0

    def _classes(self) -> list[str]:
        return [self.estado.classe] if self.estado.classe else list(CLASSES)

    def _recorte(self) -> str:
        p = self.panorama
        return (ROTULO_CLASSE[p.classe] if p.classe else TODAS_CLASSES) + f" · {p.ano}"

    def _nota_k(self) -> str:
        return g.nota_suprimido(self.k) if self.k else ""

    def _segmentos(self, por_classe: dict, dicas_base: str = "") -> list:
        return [(ROTULO_CLASSE[c], por_classe.get(c), g.cor_classe(c), c) for c in self._classes()]

    def _ordenar(self, linhas: list[dict], valor) -> list[dict]:
        """Visíveis pelo valor (maior primeiro); suprimidas no fim em ordem de nome (a ordem entre elas revelaria
        quem é maior)."""
        visiveis = sorted((l for l in linhas if valor(l) is not None), key=lambda l: (-valor(l), l["rotulo"]))
        return visiveis + sorted((l for l in linhas if valor(l) is None), key=lambda l: l["rotulo"])

    def _linha_composta(self, chave, rotulo, ativas, por_classe, total, clique=None, unidade="casos ativos") -> dict:
        parte = pct(ativas, total)
        fim = "" if ativas is None else formatos.inteiro(ativas) + (f" · {g.fmt_pct(parte, 0)}" if parte is not None
                                                                     else "")
        segs = self._segmentos(por_classe)
        if ativas is None:
            segs = [(n, None, c, cl) for n, _, c, cl in segs]
        elif any(v is None for _, v, _, _ in segs):
            # uma classe escondida na linha: a barra mostra só o total (sem segmento), a dica diz quais
            segs = [("Todas as classes", ativas, g.cor_neutra(), None)]
        detalhes = [f"{ROTULO_CLASSE[c]}: {g.fmt_inteiro(por_classe.get(c))}" for c in self._classes()]
        dica = (f"{rotulo}: {g.fmt_inteiro(ativas)} {unidade}"
                + (f" ({g.fmt_pct(parte)} do total)" if parte is not None else "")
                + ("\n" + "\n".join(detalhes) if len(self._classes()) > 1 else "")
                + (f"\n{self._nota_k()}" if (ativas is None or any(por_classe.get(c) is None for c in self._classes()))
                   and self.k else ""))
        dicas = {ROTULO_CLASSE[c]: f"{rotulo} · {ROTULO_CLASSE[c]}: {g.fmt_inteiro(por_classe.get(c))} {unidade}"
                                   + (f" ({g.fmt_pct(pct(por_classe.get(c), ativas))} do grupo)"
                                      if pct(por_classe.get(c), ativas) is not None else "")
                                   + "\nClique para filtrar por esta classe." for c in self._classes()}
        return {"chave": chave, "rotulo": rotulo, "segmentos": segs, "fim": fim, "dica": dica, "dicas": dicas,
                "clique": clique, "valor": ativas,
                "tabela": [rotulo, *[g.fmt_inteiro(por_classe.get(c)) for c in self._classes()],
                           g.fmt_inteiro(ativas), g.fmt_pct(parte)]}

    def _legenda_classes(self):
        return [(ROTULO_CLASSE[c], g.cor_classe(c)) for c in self._classes()] if len(self._classes()) > 1 else []

    def _colunas_composta(self, primeira: str) -> list[str]:
        return [primeira, *[ROTULO_CLASSE[c] for c in self._classes()], "Total", "% do total"]

    # ------------------------------------------------------------ 1. Onde estão os casos?
    def _valor_uf(self, uf: str, indicador: str | None = None):
        indicador = indicador or self.combo_indicador.currentText()
        item = self.panorama.pressao.get(uf)
        if item is None or item.suprimida:
            return None
        if indicador == PRESSAO:
            return item.indice
        if indicador == ATIVOS:
            return item.ativas
        if indicador == CRITICOS:
            return pct(item.criticas, item.ativas)
        linha = {l.uf: l for l in self.dados["uf"].linhas}.get(uf)
        if linha is None or linha.suprimida:
            return None
        return pct(linha.alem_do_prazo if indicador == ALEM else linha.fora_da_previsao, linha.ativas)

    def _fmt_indicador(self, v, indicador: str | None = None) -> str:
        indicador = indicador or self.combo_indicador.currentText()
        if v is None:
            return g.SUPRIMIDO
        if indicador == PRESSAO:
            return formatos.numero(v, 2)
        if indicador == ATIVOS:
            return formatos.inteiro(v)
        return g.fmt_pct(v)

    def _dica_uf(self, uf: str) -> str:
        p, item = self.panorama, self.panorama.pressao.get(uf)
        if item is None:
            return uf
        if item.suprimida:
            return f"{uf} · {g.SUPRIMIDO}\n{self._nota_k()}"
        if not item.ativas:
            return f"{uf} · nenhum caso ativo"
        linhas = [f"{uf} · {vocabulario.casos(item.ativas, 'ativos')}"]
        for ind in (CRITICOS, ALEM, FORA):
            linhas.append(f"{ind}: {self._fmt_indicador(self._valor_uf(uf, ind), ind)}")
        linhas.append(f"Índice de pressão: {formatos.numero(item.indice, 2)} ({item.posto}º de {len(p.pressao)})")
        return "\n".join(linhas)

    def _mostrar_onde(self):
        if self.panorama is None:
            return
        p, indicador = self.panorama, self.combo_indicador.currentText()
        valores = {uf: self._valor_uf(uf) for uf in p.pressao}
        # coroplético: quintis só das UFs visíveis; suprimida e sem ativas em cinza (a cor não revela o número)
        numericos = {uf: float(v) for uf, v in valores.items() if v is not None and p.pressao[uf].ativas}
        limites, self._quintil_de = quintis(numericos)
        cores = {uf: QColor(RAMPA[q]) for uf, q in self._quintil_de.items()}
        for uf, item in p.pressao.items():
            if item.suprimida or valores[uf] is None:
                cores[uf] = QColor(COR_SUPRIMIDA)
            elif not item.ativas:
                cores[uf] = QColor(COR_SEM_ATIVAS)
        self.mapa.pintar_ufs(cores, {uf: self._dica_uf(uf) for uf in p.pressao})
        formato = ((lambda v: formatos.numero(v, 2)) if indicador == PRESSAO else
                   (lambda v: formatos.inteiro(v)) if indicador == ATIVOS else (lambda v: f"{v:.0f}%"))
        fino = ((lambda v: formatos.numero(v, 3)) if indicador == PRESSAO else None if indicador == ATIVOS else
                (lambda v: formatos.numero(v, 1) + "%"))
        inferiores = [min((numericos[uf] for uf, q in self._quintil_de.items() if q == k), default=None)
                      for k in range(5)]
        contagens = [sum(q == k for q in self._quintil_de.values()) for k in range(5)]
        titulo = f"{indicador} ({UNIDADE_INDICADOR[indicador]})"
        self.legenda.definir(limites, formato, titulo, inferiores, contagens, p.supressao_minima, fino)
        corte = min(date(p.ano, 12, 31), p.hoje)
        explica = formula_pressao(p.pesos) if indicador == PRESSAO else vocabulario.dica(
            {ALEM: "KPI-03", FORA: "KPI-03b"}.get(indicador, ""), "kpi") or UNIDADE_INDICADOR[indicador]
        fonte = "analise.indice_pressao" if indicador == PRESSAO else "analise.proteger_cubo"
        dica = dica_fonte(fonte, 1, corte, explica + (f"\n{self._nota_k()}" if self.k else ""))
        self.mapa.setToolTip(dica)
        self.legenda.setToolTip(dica)
        cartao = self.secoes["onde"].cartoes["mapa"]
        cartao.definir(f"{titulo} · {self._recorte()} · quintis entre as UFs visíveis", dica,
                       "Passe o mouse numa UF para ver os números; clique para fixar."
                       + (" Cinza: oculto (poucos casos) ou sem casos ativos." if self.k else ""),
                       titulo=f"{indicador} por UF")
        self.combo_indicador.setToolTip(dica)
        self._mostrar_ranking(valores, dica)
        self._mostrar_regioes()
        self._realce_uf()

    def _mostrar_ranking(self, valores, dica):
        indicador = self.combo_indicador.currentText()
        cor = g.cor_classe(self.estado.classe) if self.estado.classe else g.cor_neutra()
        linhas, sem_casos = [], []
        for uf, v in valores.items():
            item = self.panorama.pressao[uf]
            linha = {"chave": uf, "rotulo": uf, "segmentos": [(indicador, v, cor, None)],
                     "fim": "" if v is None else self._fmt_indicador(v), "dica": self._dica_uf(uf)
                     + "\nClique para realçar a UF no mapa.", "clique": ("UF", uf), "valor": v,
                     "tabela": [uf, self._fmt_indicador(v)]}
            if not item.suprimida and not item.ativas:          # nenhum caso ativo: nem posição nem barra
                linha.update(vazio="sem casos ativos", valor=None, tabela=[uf, "sem casos ativos"])
                sem_casos.append(linha)
            else:
                linhas.append(linha)
        linhas = self._ordenar(linhas, lambda l: l["valor"])
        n_visiveis = len([l for l in linhas if l["valor"] is not None])
        linhas[n_visiveis:n_visiveis] = sorted(sem_casos, key=lambda l: l["rotulo"])
        for posicao, l in enumerate(linhas, 1):
            if l["valor"] is not None:
                l["rotulo"] = f"{posicao}º {l['chave']}"
        maximo = 1.0 if indicador == PRESSAO else (100.0 if indicador not in (ATIVOS,) else None)
        self.ranking.mostrar(linhas, maximo=maximo, colunas_tabela=["UF", indicador],
                             inteiro=indicador == ATIVOS,
                             formato_eixo=(lambda v: formatos.numero(v, 2)) if indicador == PRESSAO else
                             (lambda v: formatos.numero(v, 0) + "%") if indicador != ATIVOS else None)
        self.ranking.unidade = UNIDADE_INDICADOR[indicador]
        self.secoes["onde"].cartoes["ranking"].definir(
            f"{UNIDADE_INDICADOR[indicador][0].upper()}{UNIDADE_INDICADOR[indicador][1:]} · {self._recorte()} · "
            "da maior para a menor", dica,
            "UFs suprimidas ficam no fim, em ordem alfabética.",
            titulo=f"Ranking das UFs: {indicador.lower()}")

    def _mostrar_regioes(self):
        d = self.dados["n1"]
        total = d.nacional.ativas
        linhas = [self._linha_composta(r.chave, r.nome, r.ativas, r.por_classe, total, ("REGIAO", r.chave))
                  for r in d.regioes]
        for l in linhas:
            l["dica"] += "\nClique para selecionar as UFs da região no mapa."
        self.regioes.mostrar(self._ordenar(linhas, lambda l: l["valor"]), self._legenda_classes(),
                             colunas_tabela=self._colunas_composta("Região"))
        self.regioes.unidade = "casos ativos"
        self.secoes["onde"].cartoes["regioes"].definir(
            f"Casos ativos, por classe · {self._recorte()} · total {g.fmt_inteiro(total)}",
            dica_fonte("analise.proteger_cubo", 1, d.corte, self._nota_k()),
            "Clique numa região para realçar as UFs dela; clique numa cor para filtrar pela classe.")

    def _realce_uf(self):
        if self.panorama is None:
            return
        foco, selecao = self.estado.foco, set(self.estado.selecao)
        alvo = ({foco} if foco else set()) | selecao
        self.mapa.realcar_ufs(alvo or None)
        for l in self.ranking.linhas:
            l["destaque"] = l["chave"] in alvo
        self.ranking.update()

    def _realcar_quintil(self, k: int):
        if k < 0:
            self._realce_uf()
        else:
            self.mapa.realcar_ufs({uf for uf, q in self._quintil_de.items() if q == k})

    def _selecionar_quintil(self, k: int):
        self.estado.definir(selecao=frozenset() if k < 0 else
                            frozenset(uf for uf, q in self._quintil_de.items() if q == k))

    def _tabela_mapa(self):
        indicador = self.combo_indicador.currentText()
        return (["UF", indicador, "Quintil"],
                [[uf, self._fmt_indicador(self._valor_uf(uf)),
                  str(self._quintil_de[uf] + 1) if uf in self._quintil_de else ""]
                 for uf in sorted(self.panorama.pressao)] if self.panorama else [])

    # ------------------------------------------------------------ 2. Que tipo de passivo?
    def _mostrar_tipo(self):
        d, pc = self.dados["n1"], self.dados["classe"]
        linhas = {l.classe: l for l in pc.linhas}
        total = pc.total_ativas if not pc.classe else d.nacional.ativas
        for c, cartao in self.cartoes_classe.items():
            cartao.setVisible(c in linhas)
            if c in linhas:
                cartao.definir(linhas[c], d.nacional.ativas if pc.classe else pc.total_ativas, self.k, pc.corte,
                               self.estado.classe == c)
        total = d.nacional.ativas
        ativ = [self._linha_composta(a.chave, a.nome, a.ativas, a.por_classe, total) for a in d.atividades]
        ativ = [l for l in ativ if l["valor"] != 0]
        self.atividades.mostrar(self._ordenar(ativ, lambda l: l["valor"]), self._legenda_classes(),
                                colunas_tabela=self._colunas_composta("Atividade de origem"))
        fonte = dica_fonte("analise.proteger_cubo", 1, d.corte, self._nota_k())
        self.secoes["tipo"].cartoes["atividades"].definir(
            f"Casos ativos, por classe · {self._recorte()} · atividades sem caso ativo não aparecem", fonte,
            "A atividade de origem é o tipo de empreendimento que gerou o passivo (vocabulário no Glossário).")
        # região × classe (contagens), com a coluna e a linha de total sem cor
        classes = self._classes()
        colunas = [(ROTULO_CLASSE[c], c) for c in classes] + ([("Total", None)] if len(classes) > 1 else [])
        celulas, rotulos = [], []
        for r in (*d.regioes, d.nacional):
            rotulos.append(r.nome)
            linha = []
            for c in classes:
                v = r.por_classe.get(c)
                linha.append({"valor": v, "texto": g.fmt_inteiro(v), "margem": r is d.nacional,
                              "dica": f"{r.nome} · {ROTULO_CLASSE[c]}: {g.fmt_inteiro(v)} casos ativos"
                                      + (f" ({g.fmt_pct(pct(v, r.ativas))} da região)" if pct(v, r.ativas) is not None
                                         and r is not d.nacional else "")
                                      + (f"\n{self._nota_k()}" if v is None and self.k else "")
                                      + "\nClique para filtrar por esta classe.", "clique": c})
            if len(classes) > 1:
                linha.append({"valor": r.ativas, "texto": g.fmt_inteiro(r.ativas), "margem": True,
                              "dica": f"{r.nome}: {g.fmt_inteiro(r.ativas)} casos ativos"})
            celulas.append(linha)
        self.regiao_classe.mostrar(rotulos, colunas, celulas, "casos ativos na célula", formato=g.fmt_inteiro)
        self.secoes["tipo"].cartoes["regiao_classe"].definir(
            f"Casos ativos · {self._recorte()} · cor mais escura = mais casos", fonte,
            "Total e Brasil sem cor: são as margens da tabela.")

    # ------------------------------------------------------------ 3. Por que continuam abertos?
    def _mostrar_motivos(self):
        d = self.dados["n1"]
        total = d.nacional.ativas
        linhas = [self._linha_composta(m.chave, m.nome, m.ativas, m.por_classe, total) for m in d.motivos]
        linhas = self._ordenar([l for l in linhas if l["valor"] != 0], lambda l: l["valor"])
        self.motivos.mostrar(linhas, self._legenda_classes(), colunas_tabela=self._colunas_composta("Motivo"))
        fonte = dica_fonte("analise.proteger_grade_n1", 1, d.corte, self._nota_k())
        self.secoes["motivos"].cartoes["motivos"].definir(
            f"Casos ativos, por classe · {self._recorte()}", fonte,
            "O motivo da permanência é registrado em cada caso (definições no Glossário).")
        # composição de cada classe por motivo (% da coluna)
        classes = self._classes()
        totais = {g_.chave: g_.ativas for g_ in d.classes}
        por_motivo = {m.chave: m for m in d.motivos}
        rotulos, celulas = [], []
        for l in linhas:
            m = por_motivo[l["chave"]]
            rotulos.append(m.nome)
            linha = []
            for c in classes:
                v, base = m.por_classe.get(c), totais.get(c)
                parte = pct(v, base)
                texto = g.SUPRIMIDO if v is None else (g.fmt_pct(parte, 0) if parte is not None else
                                                      g.fmt_inteiro(v))
                linha.append({"valor": parte if parte is not None else (None if v is None else 0), "texto": texto,
                              "dica": f"{m.nome} · {ROTULO_CLASSE[c]}: {g.fmt_inteiro(v)} casos ativos"
                                      + (f" ({g.fmt_pct(parte)} dos casos da classe)" if parte is not None else "")
                                      + (f"\n{self._nota_k()}" if v is None and self.k else "")
                                      + "\nClique para filtrar por esta classe.", "clique": c})
            celulas.append(linha)
        self.motivo_classe.mostrar(rotulos, [(ROTULO_CLASSE[c], c) for c in classes], celulas,
                                   "% dos casos ativos da classe", maximo=None, formato=lambda v: g.fmt_pct(v, 0))
        self.secoes["motivos"].cartoes["motivo_classe"].definir(
            f"% dos casos ativos de cada classe · {self._recorte()} · cada coluna soma 100%", fonte,
            "Peso de cada motivo dentro da classe.")

    # ------------------------------------------------------------ 4. Estão sendo resolvidos?
    def _mostrar_resolucao(self):
        p, enc, pc = self.panorama, self.dados["encerramento"], self.dados["classe"]
        corte = min(date(p.ano, 12, 31), p.hoje)
        nota_k = f"\n{self._nota_k()}" if self.k else ""
        anos = p.serie["anos"]
        series = [{"chave": c, "nome": ROTULO_CLASSE[c], "cor": g.cor_classe(c),
                   "pontos": [(a, p.serie["ativas"][c].get(a)) for a in anos]}
                  for c in CLASSES if c in p.serie["ativas"]]
        eventos, legenda = [], []
        meses = ("jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez")
        for n, e in enumerate(sorted(p.eventos, key=lambda e: e.data_evento), 1):
            quando = f"{meses[e.data_evento.month - 1]}/{e.data_evento.year}"
            eventos.append((e.data_evento.year + (e.data_evento.month - 1) / 12, str(n),
                            f"{n}. {e.rotulo} ({quando})\n{e.descricao}"))
            legenda.append(f"{n} {e.rotulo} ({quando})")
        self.estoque.mostrar(series, marcado=p.ano, eventos=eventos)
        total = p.serie.get("estoque_total", {}).get(p.ano)
        self.secoes["resolucao"].cartoes["estoque"].definir(
            f"Casos ativos no fim de cada ano, por classe · {anos[0]} a {anos[-1]} · "
            f"{g.fmt_inteiro(total)} casos ativos em {p.ano} (todas as classes)",
            dica_fonte("analise.serie_estoque", 1, corte, nota_k),
            "Marcos: " + " · ".join(legenda) + ". Clique num ano para mudar o corte do painel.")
        cinza = g.tokens()["texto2"]
        fluxos = [{"chave": "entradas", "nome": "Entram (identificados no ano)", "cor": cinza,
                   "pontos": [(a, p.serie["entradas"].get(a)) for a in anos]},
                  {"chave": "saidas", "nome": "Saem (encerrados no ano)", "cor": g.cor_neutra(),
                   "pontos": [(a, p.serie["saidas"].get(a)) for a in anos]}]
        self.fluxos.mostrar(fluxos, marcado=p.ano, parcial_ultimo=anos[-1] == p.hoje.year)
        self.secoes["resolucao"].cartoes["fluxos"].definir(
            f"Casos por ano · {self._recorte().split(' · ')[0]} · quando a linha cinza fica acima, o estoque cresce",
            dica_fonte("analise.proteger_fluxos", 1, corte, "Quando a entrada ou a saída de um ano é pequena, as duas "
                       "ficam ocultas juntas." + nota_k),
            f"{p.hoje.year} é parcial (até {p.hoje:%d/%m/%Y}). Clique num ano para mudar o corte.")
        fechado = p.ano if p.ano < p.hoje.year else p.ano - 1
        itens = [{"x": t.ano, "valor": t.percentual, "parcial": t.parcial,
                  "dica": f"{t.ano}: " + (f"{g.SUPRIMIDO}{nota_k}" if t.percentual is None else
                                         f"{g.fmt_pct(t.percentual)} ({g.fmt_inteiro(t.saidas)} encerrados de "
                                         f"{g.fmt_inteiro(t.ativas_1_jan)} ativos em 1º de janeiro)"
                                         + (" · parcial: ano corrente, sem anualização" if t.parcial else ""))
                  + "\nClique para mudar o corte do painel."} for t in enc.taxa_anual]
        self.taxa.mostrar(itens, marcado=fechado, cor=g.cor_classe(p.classe) if p.classe else g.cor_neutra())
        self.secoes["resolucao"].cartoes["taxa"].definir(
            f"Encerrados no ano ÷ ativos em 1º de janeiro · {self._recorte().split(' · ')[0]} · rótulo no maior, no "
            "menor e no ano do corte",
            dica_fonte("analise.taxa_anual_encerramento", 1, enc.corte, vocabulario.dica("KPI-02", "kpi") + nota_k),
            f"O ano corrente ({p.hoje.year}) aparece hachurado: é parcial, sem anualização.")
        curvas = enc.curvas
        series, marcas = [], []
        for c in [*CLASSES, analise.TODAS]:
            curva = curvas.get(c)
            if curva is None or not curva.pontos:
                continue
            nome = ROTULO_CLASSE.get(c, TODAS_CLASSES)
            series.append({"chave": c, "nome": nome, "cor": g.cor_classe(c) if c in CLASSES else g.tokens()["mudo"],
                           "tracejado": c == analise.TODAS,
                           "pontos": [(t_, 100 * s_) for t_, s_ in curva.pontos]})
            if curva.mediana is not None:
                marcas.append((curva.mediana, nome))

        def dica_curva(x):
            linhas = [f"{formatos.numero(x, 1)} anos desde a identificação"]
            for s in series:
                nivel = next((y for xx, y in reversed(s["pontos"]) if xx <= x + 1e-9), None)
                if nivel is not None:
                    linhas.append(f"{s['nome']}: {g.fmt_pct(nivel, 0)} ainda ativos")
            for c in [*CLASSES, analise.TODAS]:
                curva = curvas.get(c)
                if curva is not None:
                    linhas.append(f"Mediana {ROTULO_CLASSE.get(c, TODAS_CLASSES).lower()}: "
                                  + ("não atingida" if curva.mediana is None else
                                     f"{formatos.numero(curva.mediana, 1)} anos"))
            return "\n".join(linhas)
        self.curva.mostrar(series, referencia=(50, "metade encerrada (mediana)"), maximo_y=100,
                           rotulo_x="anos desde a identificação", dica_x=dica_curva, marcas=marcas)
        medianas = " · ".join(f"{ROTULO_CLASSE.get(c, TODAS_CLASSES)}: "
                              + ("não atingida" if curvas[c].mediana is None else
                                 f"{formatos.numero(curvas[c].mediana, 1)} anos")
                              for c in [*CLASSES, analise.TODAS] if c in curvas)
        self.secoes["resolucao"].cartoes["curva"].definir(
            f"% dos casos ainda ativos t anos depois da identificação · mediana: {medianas}",
            dica_fonte("analise.tempo_ate_encerramento" if enc.exata else "analise.tabua_de_vida", 1, enc.corte,
                       vocabulario.dica("KPI-01", "kpi") + nota_k),
            "" if enc.exata else "Anos com poucos encerramentos aparecem agrupados.")
        # idade dos casos em aberto (100% por classe, mais o total do recorte)
        linhas = []
        for l in sorted(pc.linhas, key=lambda l: CLASSES.index(l.classe)):
            linhas.append({"rotulo": ROTULO_CLASSE[l.classe], "total": l.ativas, "clique": l.classe,
                           "partes": [(f, l.envelhecimento.get(f)) for f in pc.faixas],
                           "dica_total": f"{ROTULO_CLASSE[l.classe]}: {g.SUPRIMIDO}{nota_k}"})
        if not pc.classe:
            linhas.append({"rotulo": TODAS_CLASSES, "total": pc.total_ativas, "clique": None,
                           "partes": [(f, pc.envelhecimento_total.get(f)) for f in pc.faixas],
                           "dica_total": f"{TODAS_CLASSES}: {g.SUPRIMIDO}{nota_k}"})
        self.idade.mostrar(pc.faixas, FAIXAS_IDADE, linhas)
        mediana = ("" if pc.idade_mediana_total is None else
                   f" · idade mediana {formatos.numero(pc.idade_mediana_total, 1)} anos")
        self.secoes["resolucao"].cartoes["idade"].definir(
            f"Distribuição dos casos ativos por tempo desde a identificação · {self._recorte()}{mediana}",
            dica_fonte("analise.envelhecimento", 1, pc.corte, vocabulario.dica("KPI-04", "kpi") + nota_k),
            "Faixas com poucos casos aparecem juntas, hachuradas.")

    # ------------------------------------------------------------ 5. Quanto está fora do prazo?
    def _linha_prazo(self, chave, rotulo, ativas, alem, fora, clique=None, referencia=False) -> dict:
        a, b = pct(alem, ativas), pct(fora, ativas)
        nota = f"\n{self._nota_k()}" if self.k and (a is None or b is None) else ""
        return {"chave": chave, "rotulo": rotulo, "a": a, "b": b, "clique": clique, "referencia": referencia,
                "dica_a": f"{rotulo} · {ALEM}: " + (g.SUPRIMIDO if a is None else
                                                    f"{g.fmt_pct(a)} ({g.fmt_inteiro(alem)} de {g.fmt_inteiro(ativas)} "
                                                    "casos ativos)") + nota,
                "dica_b": f"{rotulo} · {FORA}: " + (g.SUPRIMIDO if b is None else
                                                    f"{g.fmt_pct(b)} ({g.fmt_inteiro(fora)} de {g.fmt_inteiro(ativas)} "
                                                    "casos ativos)") + nota}

    def _mostrar_prazo(self):
        d, pu = self.dados["n1"], self.dados["uf"]
        nota_k = f"\n{self._nota_k()}" if self.k else ""
        definicoes = f"{vocabulario.dica('KPI-03', 'kpi')}\n{vocabulario.dica('KPI-03b', 'kpi')}"
        fonte = dica_fonte("analise.proteger_cubo", 1, d.corte, definicoes + nota_k)
        nac = d.nacional
        brasil = self._linha_prazo("BR", nac.nome, nac.ativas, nac.alem_do_prazo, nac.fora_da_previsao, referencia=True)
        regioes = [self._linha_prazo(r.chave, r.nome, r.ativas, r.alem_do_prazo, r.fora_da_previsao,
                                     ("REGIAO", r.chave)) for r in d.regioes]
        regioes = self._ordenar(regioes, lambda l: l["a"])
        self.prazo_regiao.mostrar([*regioes, brasil])
        self.secoes["prazo"].cartoes["prazo_regiao"].definir(
            f"% dos casos ativos da região · {self._recorte()} · ordenado pelo prazo legal", fonte,
            "Cada ponto é uma das duas medidas de atraso.")
        ordem = {c: i for i, c in enumerate(CLASSES)}
        classes = [self._linha_prazo(c.chave, c.nome, c.ativas, c.alem_do_prazo, c.fora_da_previsao, c.chave)
                   for c in sorted(d.classes, key=lambda c: ordem[c.chave])]
        self.prazo_classe.mostrar([*classes, brasil] if len(classes) > 1 else classes)
        self.secoes["prazo"].cartoes["prazo_classe"].definir(
            f"% dos casos ativos da classe · {self.panorama.ano} · clique numa classe para filtrar", fonte,
            "Cada classe tem o seu prazo legal (Glossário, \"Prazo legal\").")
        ufs = [self._linha_prazo(l.uf, l.uf, l.ativas, l.alem_do_prazo, l.fora_da_previsao, ("UF", l.uf))
               for l in pu.linhas if not l.suprimida]
        suprimidas = [self._linha_prazo(l.uf, l.uf, None, None, None, ("UF", l.uf)) for l in pu.linhas if l.suprimida]
        visiveis = [l for l in ufs if l["a"] is not None]
        parciais = [l for l in ufs if l["a"] is None]
        self.prazo_uf.mostrar(sorted(visiveis, key=lambda l: (-l["a"], l["rotulo"]))
                              + sorted(parciais + suprimidas, key=lambda l: l["rotulo"]))
        self.secoes["prazo"].cartoes["prazo_uf"].definir(
            f"% dos casos ativos da UF · {self._recorte()} · ordenado pelo prazo legal", fonte,
            "UFs com a medida suprimida ficam no fim, em ordem alfabética.")
        classes_r = self._classes()
        colunas = [(ROTULO_CLASSE[c], c) for c in classes_r] + ([("Todas", None)] if len(classes_r) > 1 else [])
        rotulos, celulas = [], []
        for r in (*d.regioes, nac):
            rotulos.append(r.nome)
            linha = []
            for c in classes_r:
                v = pct(r.alem_por_classe.get(c), r.por_classe.get(c))
                linha.append({"valor": v, "texto": g.fmt_pct(v, 0), "margem": r is nac,
                              "dica": f"{r.nome} · {ROTULO_CLASSE[c]}: " + (
                                  g.SUPRIMIDO + nota_k if v is None else
                                  f"{g.fmt_pct(v)} além do prazo legal ({g.fmt_inteiro(r.alem_por_classe.get(c))} de "
                                  f"{g.fmt_inteiro(r.por_classe.get(c))})") + "\nClique para filtrar por esta classe.",
                              "clique": c})
            if len(classes_r) > 1:
                v = pct(r.alem_do_prazo, r.ativas)
                linha.append({"valor": v, "texto": g.fmt_pct(v, 0), "margem": True,
                              "dica": f"{r.nome}: {g.fmt_pct(v)} além do prazo legal"})
            celulas.append(linha)
        self.prazo_calor.mostrar(rotulos, colunas, celulas, "% além do prazo legal", maximo=100.0,
                                 formato=lambda v: g.fmt_pct(v, 0))
        self.secoes["prazo"].cartoes["prazo_calor"].definir(
            f"% dos casos ativos da célula · {self.panorama.ano} · cor mais escura = maior atraso", fonte,
            "Células com poucos casos ficam ocultas.")
