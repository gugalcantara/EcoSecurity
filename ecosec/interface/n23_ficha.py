"""Ficha do caso, aba "Dados técnicos" do mapa interativo (N2 e N3).

Blocos com hierarquia, do que decide para o que detalha:
  cabeçalho      código e substância, selos de classe e de risco, score de risco, andamento e fase
  Situação e prazos   etapa atual, identificado em, prazo previsto, prazo legal, encerrado em, ação, quem paga
  Local          município/UF, endereço e coordenadas (o N2 e o N3 veem o endereço; o N1 não tem ficha)
  Origem e causa atividade de origem, motivo da permanência e base legal
  Contaminação e uso  classe, quantidade, contaminante, meio afetado, restrição de uso, usos anterior e pretendido
  Custo estimado total, rota, divisão nas quatro categorias e a memória de cálculo recolhível
  Histórico de etapas linha do tempo
Rótulos e textos de exibição pelo vocabulário (`acervo/vocabulario.py`): textos de catálogo do acervo passam por
vocabulario.frase (grafia de frase, siglas preservadas). Tudo derivado de `acervo/ficha.py` e `acervo/regras.py`
sobre o caso que o serviço já entregou no painel do nível; a exportação continua crua (ServicoAcervo.exportar_ficha).

Regras de nível: a ficha nunca mostra responsável nomeado nem custo por responsável (só o N3, na aba
própria); o custo estimado do CASO aparece no N2 e no N3, como antes.
"""
from __future__ import annotations

from html import escape

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from ecosec.acervo import fase as fases
from ecosec.acervo import formatos, vocabulario
from ecosec.interface.componentes.simbologia import COR_IDENTIDADE, COR_IDENTIDADE_CLASSE
from ecosec.interface.estilo import cor_borda, cor_texto_secundario
from ecosec.interface.n23_graficos import BarraPartes, categorica, cor_texto, fonte

ROTULO_BLOCO = {"situacao": "Situação e prazos", "local": "Local", "origem": "Origem e causa",
                "contaminacao": "Contaminação e uso", "custo": "Custo estimado", "historico": "Histórico de etapas"}
BLOCOS = tuple(ROTULO_BLOCO)
CATEGORIAS_CUSTO = ("INVESTIGACAO", "REMEDIACAO", "MONITORAMENTO", "DISPOSICAO")


def _reais(valor: float, casas: int = 2) -> str:
    return f"R$&nbsp;{formatos.numero(valor, casas)}"


def _destaque(texto: str) -> str:
    return f"<b>{texto}</b>"


class _Bloco(QWidget):
    """Um bloco da ficha: título (frase, semibold) e linhas chave -> valor numa grade de duas colunas."""

    def __init__(self, chave: str, parent=None):
        super().__init__(parent)
        self.chave = chave
        self.setObjectName("blocoFicha")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"#blocoFicha {{ border-top:1px solid {cor_borda()}; }}")
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 10, 0, 4)
        v.setSpacing(6)
        self.titulo = QLabel(ROTULO_BLOCO[chave])
        self.titulo.setStyleSheet(f"color:{cor_texto()}; font-size:13px; font-weight:600;")
        self.titulo.setAccessibleName(ROTULO_BLOCO[chave])
        v.addWidget(self.titulo)
        self.grade = QGridLayout()
        self.grade.setContentsMargins(0, 0, 0, 0)
        self.grade.setHorizontalSpacing(10)
        self.grade.setVerticalSpacing(5)
        self.grade.setColumnStretch(1, 1)
        v.addLayout(self.grade)
        self.extra = QVBoxLayout()
        self.extra.setContentsMargins(0, 2, 0, 0)
        self.extra.setSpacing(6)
        v.addLayout(self.extra)
        self.linhas: list[tuple[str, str]] = []        # (chave, valor em texto puro), para leitura e testes

    def limpar(self):
        for layout in (self.grade, self.extra):
            while layout.count():
                item = layout.takeAt(0)
                if item.widget():
                    item.widget().hide()
                    item.widget().deleteLater()
        self.linhas = []

    def linha(self, chave: str, valor_html: str, dica: str = ""):
        r = self.grade.rowCount()
        k = QLabel(chave)
        k.setStyleSheet(f"color:{cor_texto_secundario()}; font-size:12px;")
        k.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        k.setMinimumWidth(118)
        k.setMaximumWidth(118)
        k.setWordWrap(True)
        valor = QLabel(valor_html)
        valor.setTextFormat(Qt.TextFormat.RichText)
        valor.setWordWrap(True)
        valor.setStyleSheet(f"color:{cor_texto()}; font-size:13px;")
        valor.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        valor.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        if dica:
            k.setToolTip(dica)
            valor.setToolTip(dica)
        self.grade.addWidget(k, r, 0)
        self.grade.addWidget(valor, r, 1)
        self.linhas.append((chave, _texto_puro(valor_html)))
        return valor

    def texto(self) -> str:
        return "\n".join(f"{c}: {v}" for c, v in self.linhas)


def _texto_puro(html: str) -> str:
    from PySide6.QtGui import QTextDocument
    d = QTextDocument()
    d.setHtml(html)
    return d.toPlainText().replace(" ", "\n").replace("\xa0", " ")


class LinhaDoTempo(QWidget):
    """Etapas do caso numa linha vertical: data, etapa (rótulo do vocabulário) e o tempo até a etapa seguinte.
    A etapa atual tem o ponto cheio na cor de destaque; as anteriores, ponto cinza; o encerramento, anel."""
    LINHA = 24

    def __init__(self, parent=None):
        super().__init__(parent)
        self.etapas: list[tuple] = []          # (data, rótulo, duração em texto, atual)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAccessibleName("Histórico de etapas")

    def definir(self, etapas):
        self.etapas = list(etapas)
        self.setFixedHeight(self.LINHA * len(self.etapas) + 6)
        self.setAccessibleDescription("; ".join(f"{d:%d/%m/%Y} {r}" for d, r, _, _ in self.etapas))
        self.update()

    def sizeHint(self) -> QSize:
        return QSize(300, self.LINHA * max(1, len(self.etapas)) + 6)

    def paintEvent(self, evento):
        if not self.etapas:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        x = 8
        primeiro_y = self.LINHA / 2 + 2
        ultimo_y = self.LINHA * (len(self.etapas) - 1) + self.LINHA / 2 + 2
        p.setPen(QPen(QColor(cor_borda()), 2))
        p.drawLine(QPointF(x, primeiro_y), QPointF(x, ultimo_y))
        mf = QFontMetrics(fonte(12))
        largura_data = mf.horizontalAdvance("00/00/0000") + 12
        for i, (data, rotulo, duracao, atual) in enumerate(self.etapas):
            y = self.LINHA * i + self.LINHA / 2 + 2
            if atual:
                p.setPen(QPen(QColor("#FFFFFF"), 2))
                p.setBrush(QColor(categorica(0)))
                p.drawEllipse(QPointF(x, y), 6, 6)
            else:
                p.setPen(QPen(QColor(cor_texto_secundario()), 1.5))
                p.setBrush(QColor(cor_texto_secundario()))
                p.drawEllipse(QPointF(x, y), 3.5, 3.5)
            p.setFont(fonte(12))
            p.setPen(QColor(cor_texto_secundario()))
            p.drawText(QRectF(x + 14, y - 10, largura_data, 20), Qt.AlignmentFlag.AlignVCenter, f"{data:%d/%m/%Y}")
            p.setFont(fonte(12, QFont.Weight.DemiBold if atual else QFont.Weight.Normal))
            p.setPen(QColor(cor_texto()))
            resto = self.width() - (x + 14 + largura_data) - 70
            p.drawText(QRectF(x + 14 + largura_data, y - 10, resto, 20), Qt.AlignmentFlag.AlignVCenter,
                       mf.elidedText(rotulo, Qt.TextElideMode.ElideRight, int(resto)))
            if duracao:
                p.setFont(fonte(11))
                p.setPen(QColor(cor_texto_secundario()))
                p.drawText(QRectF(self.width() - 70, y - 10, 68, 20),
                           Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, duracao)
        p.end()


def _duracao(dias: int) -> str:
    if dias < 60:
        return f"{dias} {'dia' if dias == 1 else 'dias'}"
    if dias < 365:
        return f"{round(dias / 30.44)} meses"
    anos = round(dias / formatos.DIAS_POR_ANO, 1)
    return f"{formatos.numero(anos, 0 if anos.is_integer() else 1)} {'ano' if anos == 1 else 'anos'}"


class FichaTecnica(QWidget):
    """O conteúdo da aba "Dados técnicos". `mostrar(p, painel, regras)` monta os blocos do caso p."""

    def __init__(self, parent=None):
        super().__init__(parent)
        from ecosec.interface.componentes import Selo
        v = QVBoxLayout(self)
        v.setContentsMargins(2, 2, 2, 2)
        v.setSpacing(4)
        self.titulo = QLabel("Clique num ponto")
        self.titulo.setWordWrap(True)
        self.titulo.setStyleSheet(f"color:{cor_texto()}; font-size:16px; font-weight:600;")
        self.titulo.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.subtitulo = QLabel("A ficha do caso aparece aqui.")
        self.subtitulo.setWordWrap(True)
        self.subtitulo.setStyleSheet(f"color:{cor_texto_secundario()}; font-size:12px;")
        selos = QHBoxLayout()
        selos.setContentsMargins(0, 4, 0, 2)
        selos.setSpacing(6)
        self.selo_classe = Selo("", COR_IDENTIDADE_CLASSE[next(iter(COR_IDENTIDADE_CLASSE))])
        self.selo_classe.setAccessibleName("Classe")
        self.selo_risco = Selo("", COR_IDENTIDADE["BAIXO"], solido=True)
        self.selo_risco.setAccessibleName("Faixa de risco")
        self.score = QLabel()
        self.score.setStyleSheet(f"color:{cor_texto()}; font-size:12px;")
        self.score.setToolTip(vocabulario.dica("SCORE", "risco"))
        for w in (self.selo_classe, self.selo_risco, self.score):
            selos.addWidget(w)
        selos.addStretch(1)
        for w in (self.selo_classe, self.selo_risco, self.score):
            w.hide()
        v.addWidget(self.titulo)
        v.addLayout(selos)
        v.addWidget(self.subtitulo)
        self.blocos = {chave: _Bloco(chave) for chave in BLOCOS}
        for bloco in self.blocos.values():
            v.addWidget(bloco)
            bloco.hide()
        v.addStretch(1)
        self.memoria = QLabel()                    # memória de cálculo (recolhível, dentro do bloco Custo)
        self.botao_memoria = None

    # montagem
    def mostrar(self, p, painel, r):
        from ecosec.acervo import ficha, regras
        hoje = painel.hoje
        faixa = regras.categoria(p, hoje)
        a = ficha.atributos(p, r.custos)
        self.titulo.setText(f"{p.codigo} · {vocabulario.frase(p.substancia)}")
        self.titulo.setAccessibleName(f"Caso {p.codigo}")
        self.selo_classe.definir(vocabulario.rotulo(p.classe_risco, "classe"), COR_IDENTIDADE_CLASSE[p.classe_risco])
        self.selo_classe.setToolTip(vocabulario.dica(p.classe_risco, "classe"))
        self.selo_risco.definir(vocabulario.rotulo_longo(faixa, "faixa"), COR_IDENTIDADE[faixa])
        self.selo_risco.setAccessibleDescription(f"Faixa de risco {vocabulario.rotulo(faixa, 'faixa')}")
        self.selo_risco.setToolTip(vocabulario.dica(faixa, "faixa"))
        self.score.setText(f"Score de risco <b>{formatos.numero(regras.criticidade(p, hoje), 1)}</b>")
        for w in (self.selo_classe, self.selo_risco, self.score):
            w.show()
        andamento = vocabulario.rotulo(p.situacao, "situacao_caso")
        encerrado = not p.ativa(hoje)
        self.subtitulo.setText(f"{'Encerrado' if encerrado else 'Ativo'} · {andamento} · fase "
                               f"{vocabulario.rotulo(a.fase, 'fase').lower()}")
        for bloco in self.blocos.values():
            bloco.limpar()
            bloco.show()
        self._situacao(p, painel, r, a, encerrado)
        self._local(p)
        self._origem(p, painel)
        self._contaminacao(p, a)
        self._custo(a)
        self._historico(p, hoje)

    def _situacao(self, p, painel, r, a, encerrado):
        from ecosec.acervo import regras
        hoje, b = painel.hoje, self.blocos["situacao"]
        b.linha("Etapa atual", vocabulario.rotulo(p.etapa_atual, "etapa"), vocabulario.dica(p.etapa_atual, "etapa"))
        b.linha(vocabulario.rotulo("IDENTIFICACAO", "campo"), f"{p.data_identificacao:%d/%m/%Y}",
                vocabulario.dica("IDENTIFICACAO", "campo"))
        previsto = f"{p.prazo_coleta:%d/%m/%Y}"
        if p.vencida(hoje):
            previsto += f"<br>{_destaque(f'vencido há {formatos.inteiro(p.dias_de_atraso(hoje))} dias')}"
        b.linha(vocabulario.rotulo("PRAZO_COLETA", "prazo"), previsto, vocabulario.dica("PRAZO_COLETA", "prazo"))
        limite = regras.prazo_limite(p, r)
        alem = regras.dias_alem_do_prazo_limite(p, hoje, r)
        texto_limite = f"{limite:%d/%m/%Y}"
        if alem and p.ativa(hoje):
            texto_limite += f"<br>{_destaque(f'além do prazo legal há {formatos.inteiro(alem)} dias')}"
        b.linha(vocabulario.rotulo("PRAZO_LIMITE", "prazo"), texto_limite, vocabulario.dica("PRAZO_LIMITE", "prazo"))
        if p.data_encerramento:
            b.linha("Encerrado em", _destaque(f"{p.data_encerramento:%d/%m/%Y}"))
        acao = regras.acao_recomendada(p, hoje, r)
        b.linha(vocabulario.titulo_coluna("ACAO RECOMENDADA"), _destaque(vocabulario.rotulo(acao, "acao")),
                vocabulario.dica(acao, "acao"))
        resp = regras.responsabilidade(p)
        b.linha(vocabulario.titulo_coluna("RESPONSABILIDADE"), vocabulario.rotulo(resp, "responsabilidade"),
                vocabulario.dica(resp, "responsabilidade"))

    def _local(self, p):
        b = self.blocos["local"]
        b.linha("Município", f"{escape(p.municipio)}/{p.uf}")
        b.linha("Endereço", escape(p.endereco))
        b.linha("Coordenadas", f"{formatos.numero(p.latitude, 5)}; {formatos.numero(p.longitude, 5)}",
                "Latitude; longitude em graus decimais (SIRGAS 2000)")

    def _origem(self, p, painel):
        b = self.blocos["origem"]
        ag, mp = painel.atividades.get(p.atividade), painel.motivos.get(p.motivo)

        def com_definicao(codigo, tipo, item):
            definicao = vocabulario.definicao(codigo, tipo)
            texto = _destaque(escape(vocabulario.rotulo(codigo, tipo)))
            if definicao:
                texto += f"<br><span style='color:{cor_texto_secundario()}'>{escape(definicao)}</span>"
            dica = vocabulario.frase(item.descricao_operacional) if item and item.descricao_operacional else ""
            return texto, dica
        texto, dica = com_definicao(p.atividade, "atividade", ag)
        b.linha(vocabulario.rotulo("ATIVIDADE", "campo"), texto, dica)
        texto, dica = com_definicao(p.motivo, "motivo", mp)
        b.linha(vocabulario.rotulo("MOTIVO", "campo"), texto, dica)
        base = vocabulario.BASE_LEGAL.get(p.motivo) or (vocabulario.frase(mp.base_legal) if mp and mp.base_legal
                                                         else "")
        if base:
            b.linha("Base legal", f"<i>{escape(base)}</i>")

    def _contaminacao(self, p, a):
        b = self.blocos["contaminacao"]
        sigla = vocabulario.rotulo_unidade(p.unidade)
        b.linha(vocabulario.rotulo("QUANTIDADE", "campo"), f"{formatos.numero(p.quantidade, 2)}&nbsp;{sigla}",
                vocabulario.dica("QUANTIDADE", "campo"))
        b.linha(vocabulario.rotulo("CONTAMINANTE", "campo"), escape(vocabulario.frase(a.grupo_contaminante)),
                vocabulario.dica("CONTAMINANTE", "campo"))
        b.linha(vocabulario.rotulo("MEIO", "campo"), escape(vocabulario.frase(a.meio)), vocabulario.dica("MEIO", "campo"))
        b.linha(vocabulario.rotulo("RESTRICAO", "campo"), escape(vocabulario.frase(a.restricao)),
                vocabulario.dica("RESTRICAO", "campo"))
        b.linha(vocabulario.rotulo("USO_ANTERIOR", "campo"), escape(vocabulario.frase(a.uso_anterior)),
                vocabulario.dica("USO_ANTERIOR", "campo"))
        pretendido = (a.uso_pretendido if a.uso_pretendido == formatos.NAO_SE_APLICA
                      else escape(vocabulario.frase(a.uso_pretendido)))
        b.linha(vocabulario.rotulo("USO_PRETENDIDO", "campo"), pretendido, vocabulario.dica("USO_PRETENDIDO", "campo"))

    def _custo(self, a):
        from ecosec.interface.fluent import FIF, TransparentPushButton
        m, b = a.memoria, self.blocos["custo"]
        total = b.linha("Total", f"<span style='font-size:16px; font-weight:600'>{_reais(m.total, 0)}</span>",
                        vocabulario.dica("CUSTO_ESTIMADO", "campo"))
        total.setAccessibleName("Custo estimado do caso")
        b.linha(vocabulario.rotulo("ROTA", "campo"), escape(vocabulario.frase(m.rota)), vocabulario.dica("ROTA", "campo"))
        partes = BarraPartes("Custo por categoria")
        partes.definir([(vocabulario.rotulo(cat.nome, "categoria_custo"), cat.total, categorica(i),
                         vocabulario.definicao(cat.nome, "categoria_custo"))
                        for i, cat in enumerate(m.categorias)], lambda v: f"R$ {formatos.numero(v, 0)}")
        b.extra.addWidget(partes)
        self.botao_memoria = TransparentPushButton(FIF.CHEVRON_RIGHT_MED, "Ver memória de cálculo")
        self.botao_memoria.setToolTip(vocabulario.dica("MEMORIA", "campo"))
        self.botao_memoria.setAccessibleName("Mostrar ou esconder a memória de cálculo")
        self.botao_memoria.setCheckable(True)
        self.memoria = QLabel(self._html_memoria(m))
        self.memoria.setTextFormat(Qt.TextFormat.RichText)
        self.memoria.setWordWrap(True)
        self.memoria.setStyleSheet(f"color:{cor_texto()}; font-size:12px;")
        self.memoria.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.memoria.hide()
        self.botao_memoria.toggled.connect(self._alternar_memoria)
        b.extra.addWidget(self.botao_memoria, 0, Qt.AlignmentFlag.AlignLeft)
        b.extra.addWidget(self.memoria)

    def _alternar_memoria(self, aberta: bool):
        from ecosec.interface.fluent import FIF
        self.memoria.setVisible(aberta)
        self.botao_memoria.setText("Esconder memória de cálculo" if aberta else "Ver memória de cálculo")
        self.botao_memoria.setIcon(FIF.CHEVRON_DOWN_MED if aberta else FIF.CHEVRON_RIGHT_MED)

    @staticmethod
    def _html_memoria(m) -> str:
        """Por categoria: o subtotal e cada componente como quantidade × custo unitário = valor (centavos, as
        parcelas somam o total)."""
        secundaria = cor_texto_secundario()
        linhas = ["<table width='100%' cellspacing='0' cellpadding='2'>"]
        for cat in m.categorias:
            linhas.append(f"<tr><td colspan='2' style='padding-top:6px'><b>{vocabulario.rotulo(cat.nome, 'categoria_custo')}"
                          f"</b></td><td align='right' style='padding-top:6px'><b>{_reais(cat.total)}</b></td></tr>")
            if not cat.componentes:
                linhas.append(f"<tr><td colspan='3' style='color:{secundaria}'>sem componente nesta rota</td></tr>")
            for x in cat.componentes:
                casas = 0 if float(x.quantidade).is_integer() else 2
                unidade = vocabulario.rotulo_unidade(x.unidade)
                if unidade == "caso":
                    unidade = "caso" if float(x.quantidade) == 1 else "casos"
                linhas.append(f"<tr><td style='color:{secundaria}'>{escape(vocabulario.frase(x.nome))}</td>"
                              f"<td style='color:{secundaria}; white-space:nowrap' align='right'>"
                              f"{formatos.numero(x.quantidade, casas)}&nbsp;{unidade} × {_reais(x.unitario)}</td>"
                              f"<td align='right' style='white-space:nowrap'>{_reais(x.valor)}</td></tr>")
        linhas.append(f"<tr><td colspan='2' style='padding-top:6px'><b>Total (soma das categorias)</b></td>"
                      f"<td align='right' style='padding-top:6px'><b>{_reais(m.total)}</b></td></tr></table>")
        return "".join(linhas)

    def _historico(self, p, hoje):
        etapas = list(p.etapas)
        linhas = []
        for i, (nome, data) in enumerate(etapas):
            fim = etapas[i + 1][1] if i + 1 < len(etapas) else (p.data_encerramento or hoje)
            atual = i == len(etapas) - 1
            final = atual and fases.FASE_DA_ETAPA.get(nome) == fases.ENCERRADA
            duracao = "" if final else _duracao(max(0, (fim - data).days))
            linhas.append((data, vocabulario.rotulo(nome, "etapa") + (" (atual)" if atual and not final else ""),
                           duracao, atual))
        linha = LinhaDoTempo()
        linha.definir(linhas)
        linha.setToolTip("Data em que cada etapa foi cumprida e quanto tempo o caso ficou nela.")
        self.blocos["historico"].extra.addWidget(linha)
        self.blocos["historico"].linhas.extend((f"{d:%d/%m/%Y}", r) for d, r, _, _ in linhas)

    # leitura (testes e acessibilidade)
    def texto(self) -> str:
        """Todo o texto visível da ficha, bloco a bloco (rótulos de exibição)."""
        partes = [self.titulo.text(), self.selo_classe.text(), self.selo_risco.text(),
                  _texto_puro(self.score.text()), self.subtitulo.text()]
        for chave, bloco in self.blocos.items():
            if bloco.isVisibleTo(self):
                partes.append(ROTULO_BLOCO[chave])
                partes.append(bloco.texto())
        return "\n".join(partes)
