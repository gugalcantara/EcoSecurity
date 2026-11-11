"""As abas de custódia do N3 (n23_custodia), Priorização e Custo por responsável, no padrão
de precisão da camada.

Números por extenso ("1.055 casos", não "~1k"); o custo
por responsável nas quatro categorias do modelo de custos (Investigação, Remediação, Monitoramento e Disposição;
transporte e tratamento fora do local estão em Disposição): barras empilhadas nos 10 maiores, o passivo cobrável
por categoria que fecha com o passivo sem dupla contagem e o subtotal por categoria na memória; nenhuma coluna nova
na tabela; pessoa física só no N3. A faixa do passivo é compacta (legenda
numa linha, "R$ x,xx mi" à vista, o valor exato na dica) e a explicação da aba foi para a dica, para a tabela não
perder linhas.

Os textos não trazem a fonte, a base, o corte nem a menção a valores simulados, e os testes conferem que nada
disso volta.

Os testes de números que fecham com o serviço (fila, curva, passivo) estão em test_analitico.py, e o da
largura das colunas em test_graficos.py. A lista "Casos para agir" por urgência está em TestCasosParaAgir.
"""
import re
from collections import Counter
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace

import pytest

from ecosec.acervo import custos, formatos, regras, sinteticos, vocabulario
from ecosec.dominio.entidades import Usuario
from ecosec.dominio.niveis import Nivel
from ecosec.interface.n23_custodia import N_CASOS_PARA_AGIR, casos_por_urgencia, resumo_do_topo
from ecosec.interface.n23_graficos import categorica

BIA_N2 = Usuario(matricula="BIA", nome="Bia", nivel=2, uf="SP", senha_hash="$2b$x", id=2)
CAIO_N3 = Usuario(matricula="CAIO", nome="Caio", nivel=3, senha_hash="$2b$x", id=3)
# o que a tela não diz mais: de onde vem o número, o corte e a simulação
ORIGEM = re.compile(r"[Ff]onte|consultado em|corte \d|[Bb]ase:|PARAMETRO|simula|k=\d|nível mínimo")
CATEGORIAS = [vocabulario.rotulo(c, "categoria_custo") for c in custos.CATEGORIAS_EEA]


@pytest.fixture
def tela(qt, tmp_path):
    from ecosec.aplicacao import montar
    from ecosec.interface.tela_acervo import TelaAcervo
    app = montar(caminho_env=tmp_path / ".env", modo="memoria")
    t = TelaAcervo(app)
    t.resize(1500, 950)
    t.show()
    yield t
    t.encerrar()
    t.deleteLater()


def _abrir(tela, qt, aba, usuario=CAIO_N3, nivel=Nivel.N3):
    tela.iniciar(usuario, nivel)
    tela.mostrar_modo("painel")
    pa = tela.painel_analitico
    pa.mostrar(aba)
    qt.processEvents()
    return pa


@pytest.fixture
def orcamento(tela, qt):
    return _abrir(tela, qt, "orcamento").orcamento


@pytest.fixture
def custo(tela, qt):
    return _abrir(tela, qt, "responsaveis").responsaveis


def _reais(valor) -> str:
    return f"R$ {formatos.numero(valor, 2)}"


def _passivo_por_categoria(painel, linhas) -> tuple[float, dict]:
    """O passivo cobrável sem dupla contagem e a sua divisão, recalculados por fora da tela (custos.por_categoria)."""
    por_codigo = {p.codigo: p for p in painel.pendencias}
    distintos = set().union(*(set(l.codigos) for l in linhas))
    passivo = sum(regras.custo_estimado(por_codigo[c], painel.regras) for c in distintos)
    divisao = dict.fromkeys(custos.CATEGORIAS_EEA, 0.0)
    for c in distintos:
        for cat, valor in custos.por_categoria(por_codigo[c], painel.regras.custos).items():
            divisao[cat] += valor
    return passivo, divisao


# ================================================================ resumo com precisão
class TestResumoComPrecisao:
    def test_cartoes_da_priorizacao_sem_fonte_nem_simulacao(self, orcamento):
        for chave, cartao in orcamento.cartoes.items():
            assert cartao.toolTip() and not ORIGEM.search(cartao.toolTip()), chave
        assert vocabulario.dica("SCORE", "risco") in orcamento.cartoes["risco"].toolTip()   # a definição ficou

    def test_cartoes_do_custo_sem_fonte_nem_simulacao(self, custo):
        for chave, cartao in custo.cartoes.items():
            assert cartao.toolTip() and not ORIGEM.search(cartao.toolTip()), chave
        for grafico in (custo.cartao_partes, custo.cartao_barras):              # os gráficos de dinheiro também
            assert not ORIGEM.search(grafico.toolTip())

    def test_graficos_sem_rodape_de_origem(self, tela, qt):
        pa = _abrir(tela, qt, "orcamento")
        o = pa.orcamento
        pa.mostrar("responsaveis")
        qt.processEvents()
        r = pa.responsaveis
        for cartao in (o.cartao_curva, o.cartao_fila, r.cartao_barras):
            assert cartao.rodape.text() == "" and not cartao.rodape.isVisibleTo(cartao)
        assert not ORIGEM.search(r.cartao_partes.rodape.text() + o.resultado.text() + r.aviso.text())
        assert not hasattr(o, "base")                                                   # o topo sem "Base: ..."

    def test_numeros_por_extenso_sem_abreviacao(self, tela, qt):
        pa = _abrir(tela, qt, "orcamento")
        o = pa.orcamento
        pa.mostrar("responsaveis")
        qt.processEvents()
        r = pa.responsaveis
        textos = [o.resultado.text(), r.aviso.text(), r.cartao_partes.rodape.text()]
        textos += [c.valor.text() + " " + c.contexto.text() for c in (*o.cartoes.values(), *r.cartoes.values())]
        for texto in textos:
            assert not re.search(r"~|≈|\d\s?k\b|\bmil\b", texto), texto                  # nada de "~1k"
            assert not re.search(r"(?<![\d.,/])\d{4,}(?![\d/])", texto), texto          # milhar sempre com ponto


# ================================================================ custo por categoria
class TestCustoPorCategoria:
    def test_categorias_do_responsavel_somam_o_custo_da_linha(self, custo):
        assert list(custo.categorias) == [l.nome for l in custo.linhas[:10]]
        for linha in custo.linhas[:10]:
            por_cat = custo.categorias[linha.nome]
            assert list(por_cat) == list(custos.CATEGORIAS_EEA)
            assert sum(por_cat.values()) == pytest.approx(linha.custo, abs=0.05), linha.nome

    def test_barras_empilhadas_nas_quatro_categorias(self, custo):
        from PySide6.QtWidgets import QWidget
        barras = custo.barras.barras
        assert [b.rotulo for b in barras] == [l.nome for l in custo.linhas[:10]]
        for barra, linha in zip(barras, custo.linhas):
            assert [n for _, _, n in barra.segmentos] == CATEGORIAS
            assert [c for _, c, _ in barra.segmentos] == [categorica(i) for i in range(4)]   # a cor da ficha
            assert barra.total == pytest.approx(linha.custo, abs=0.05)
            assert barra.texto == f"R$ {formatos.numero(linha.custo / 1e6, 2)} mi"
            assert all(f"{n}: {_reais(v)}" in barra.dica for v, _, n in barra.segmentos)  # o valor exato na dica
        legendas = [w.accessibleName() for w in custo.cartao_barras.findChildren(QWidget)
                    if w.accessibleName().startswith("Legenda:")]
        assert legendas == ["Legenda: " + ", ".join(CATEGORIAS)]                       # 4 cores, uma legenda

    def test_passivo_por_categoria_fecha_com_o_passivo_sem_dupla_contagem(self, custo):
        passivo, divisao = _passivo_por_categoria(custo.painel, custo.linhas)
        partes = custo.partes.partes
        assert [n for n, _, _, _ in partes] == CATEGORIAS
        for (_, valor, _, _), cat in zip(partes, custos.CATEGORIAS_EEA):
            assert valor == pytest.approx(divisao[cat], abs=0.05), cat
        assert sum(v for _, v, _, _ in partes) == pytest.approx(passivo, abs=0.05)
        assert custo.cartoes["passivo"].contexto.text() == _reais(passivo)                # fecha com o cartão
        assert sum(l.custo for l in custo.linhas) > passivo                                 # solidária: não é a soma
        # Faixa compacta, "R$ x,xx mi" à vista e o valor exato só na dica
        faixa = custo.cartao_partes
        assert faixa.rodape.text() == (f"As quatro categorias somam R$ {formatos.numero(passivo / 1e6, 2)} mi, igual "
                                       "ao passivo cobrável.")
        assert _reais(passivo) not in faixa.rodape.text() and _reais(passivo) in faixa.toolTip()
        assert not custo.partes.legenda.isVisibleTo(faixa)                                  # sem a legenda vertical
        from PySide6.QtCore import QPoint
        from PySide6.QtWidgets import QLabel
        rotulos = [w for w in faixa.legenda.findChildren(QLabel) if w.text()]
        assert len(rotulos) == len(CATEGORIAS)
        assert len({w.mapTo(faixa.legenda, QPoint(0, 0)).y() for w in rotulos}) == 1      # cabe numa linha só
        largura = faixa.legenda.width()                                                     # e nada é cortado
        assert all(w.mapTo(faixa.legenda, QPoint(w.width(), 0)).x() <= largura for w in rotulos)
        for w, (_, valor, _, _), nome in zip(rotulos, partes, CATEGORIAS):
            assert w.text() == f"{nome} <b>R$ {formatos.numero(valor / 1e6, 2)} mi</b>"
            assert w.toolTip().startswith(f"{nome}: {_reais(valor)} (")

    def test_ordem_do_maior_para_o_menor(self, custo):
        valores = [l.custo for l in custo.linhas]
        assert valores == sorted(valores, reverse=True)
        i = custo.modelo.titulos.index("CUSTO ATIVO COBRAVEL (R$)")
        assert [l[i] for l in custo.modelo.todas] == valores
        assert [l[0] for l in custo.modelo.todas] == list(range(1, len(valores) + 1))

    def test_sem_coluna_nova_na_tabela(self, custo):
        assert custo.modelo.titulos == ("ORDEM", "RESPONSAVEL", "VINCULOS", "PENDENCIAS", "CUSTO ATIVO COBRAVEL (R$)")

    def test_memoria_com_subtotal_por_categoria(self, custo, tela):
        resp = custo.linhas[0]
        itens = tela.app.acervo.memoria_por_responsavel(custo.painel, CAIO_N3, resp.nome)
        custo.mostrar_memoria(0)
        linhas = [x.strip() for x in custo.memoria.toPlainText().replace("\xa0", " ").splitlines() if x.strip()]
        assert not [x for x in linhas if ORIGEM.search(x)]                              # sem a linha de fonte
        inicio = linhas.index("Por categoria de custo")
        esperado = dict.fromkeys(custos.CATEGORIAS_EEA, 0.0)
        for item in itens:
            for c in item.componentes:
                esperado[c.categoria] += c.valor
        for j, (cat, rotulo) in enumerate(zip(custos.CATEGORIAS_EEA, CATEGORIAS)):
            assert linhas[inicio + 1 + 3 * j: inicio + 3 + 3 * j] == [rotulo, _reais(esperado[cat])]
        soma = linhas.index("Soma das categorias")
        assert linhas[soma + 1] == _reais(resp.custo)                                    # fecha com o responsável
        assert linhas.index("Total do caso") > soma                                      # o subtotal vem antes


# ================================================================ regras de nível
class TestRegrasDeNivel:
    def test_pessoa_fisica_aparece_no_n3(self, custo, tela):
        fisicas = {r.nome for r in tela.app.acervo.repo.responsaveis(3) if r.nivel_minimo == 3}
        nomes = {l.nome for l in custo.linhas}
        assert nomes & fisicas                                                          # Pf entra na soma do N3
        primeira = next(i for i, l in enumerate(custo.linhas) if l.nome in fisicas)
        custo.mostrar_memoria(primeira)
        assert custo.linhas[primeira].nome in custo.memoria.toPlainText()

    def test_n2_nao_recebe_categoria_por_responsavel(self, tela, qt):
        pa = _abrir(tela, qt, "mapa", BIA_N2, Nivel.N2)
        r = pa.responsaveis
        assert r.carregar(pa.painel) is False                                           # a matriz nega
        assert r.categorias == {} and r.passivo_categorias == {}
        assert r.partes.partes == [] and r.barras.barras == [] and r.modelo.rowCount() == 0
        ultimo = tela.app.acervo.trilha.recentes(1)[0].evento
        assert (ultimo.resultado, ultimo.usuario_id) == ("NEGADO", BIA_N2.id)


# ================================================================ casos para agir, por urgência
@pytest.fixture
def urgencia(orcamento):
    return orcamento.urgencia


def _caso(painel, codigo, classe, motivo, atraso_previsto, alem_legal, encerrado=False):
    """Um caso montado sobre um caso real da mesma classe (o custo continua calculável): `atraso_previsto` dias
    depois do prazo previsto (negativo: ainda não venceu) e `alem_legal` dias além do prazo legal da classe."""
    hoje, r = painel.hoje, painel.regras
    modelo = next(p for p in painel.pendencias if p.classe_risco == classe and p.ativa(hoje))
    sla = r.sla_dias[classe]
    identificacao = hoje - timedelta(days=sla + alem_legal) if alem_legal else hoje - timedelta(days=10)
    return replace(modelo, codigo=codigo, motivo=motivo, data_identificacao=identificacao,
                   prazo_coleta=hoje - timedelta(days=atraso_previsto),
                   data_encerramento=hoje - timedelta(days=1) if encerrado else None)


def _montados(painel):
    """Um caso em cada grupo, um empate de score (decide o código), um score maior no topo e um encerrado. Carga
    desaparecida (MP-08) de material radioativo: 3 × 3 × (1 + atraso/365), crítico a partir de 60 (com 7 anos de
    atraso, 72); área cobrável no prazo: 1: eram 1 e 2 anos de atraso (scores 18 e 27,
    críticos com a régua de antes, que punha o crítico em 10)."""
    rad, area = sinteticos.RADIOATIVO, sinteticos.AREA
    return [_caso(painel, "PD-T06", area, "MP-01", -30, 0),                  # demais
            _caso(painel, "PD-T05", area, "MP-01", -30, 10),                 # além do prazo legal, não crítico
            _caso(painel, "PD-T04", rad, "MP-08", 7 * 365, 0),               # crítico, dentro do prazo legal
            _caso(painel, "PD-T03", rad, "MP-08", 7 * 365, 100),             # crítico além (score 72, empata)
            _caso(painel, "PD-T01", rad, "MP-08", 7 * 365, 100),             # crítico além (score 72, empata)
            _caso(painel, "PD-T07", rad, "MP-08", 8 * 365, 100, encerrado=True),  # encerrado: fora
            _caso(painel, "PD-T02", rad, "MP-08", 8 * 365, 50)]              # crítico além (score 81)


def _remontar(u, qt, pendencias):
    """A lista sobre um conjunto montado de casos (as regras e a data de corte reais)."""
    real = u.painel
    u.carregar(SimpleNamespace(pendencias=tuple(pendencias), regras=real.regras, hoje=real.hoje))
    qt.processEvents()


class TestCasosParaAgir:
    def test_ordem_critico_alem_do_prazo_ativo(self, urgencia, qt):
        painel = urgencia.painel
        linhas = casos_por_urgencia(_montados(painel), painel.hoje, painel.regras)
        assert [l.caso.codigo for l in linhas] == ["PD-T02", "PD-T01", "PD-T03", "PD-T04", "PD-T05", "PD-T06"]
        assert [l.grupo for l in linhas] == [0, 0, 0, 1, 2, 3]
        assert linhas[0].score > linhas[1].score == linhas[2].score                    # score, depois código
        assert [l.faixa == "CRITICO" for l in linhas] == [True] * 4 + [False] * 2
        assert [l.dias_alem for l in linhas] == [50, 100, 100, 0, 10, 0]
        _remontar(urgencia, qt, _montados(painel))                                      # a tela segue a mesma ordem
        assert [l[0] for l in urgencia.modelo.todas] == [l.caso.codigo for l in linhas]
        # nos dados reais, o grupo nunca diminui ao longo da lista inteira, e o score não sobe dentro do grupo
        todos = casos_por_urgencia(painel.pendencias, painel.hoje, painel.regras)
        assert [l.grupo for l in todos] == sorted(l.grupo for l in todos)
        for a, b in zip(todos, todos[1:]):
            assert a.grupo < b.grupo or (a.score, b.caso.codigo) >= (b.score, a.caso.codigo)

    def test_top_n_com_acao_recomendada(self, urgencia):
        from PySide6.QtCore import Qt
        painel, u = urgencia.painel, urgencia
        hoje, r = painel.hoje, painel.regras
        assert N_CASOS_PARA_AGIR == 20 and u.total > 20
        assert len(u.linhas) == u.modelo.rowCount() == 20
        assert u.linhas == casos_por_urgencia(painel.pendencias, hoje, r)[:20]
        for linha, l in zip(u.modelo.todas, u.linhas):
            p = l.caso
            assert linha == [p.codigo, regras.categoria(p, hoje), p.classe_risco, p.uf, p.municipio,
                             regras.dias_alem_do_prazo_limite(p, hoje, r), regras.acao_recomendada(p, hoje, r),
                             regras.responsabilidade(p), round(regras.custo_estimado(p, r), 2)]
        # o texto da ação e de quem paga é o rótulo; a definição fica na dica
        m, i_acao, i_paga = u.dicas, u.TITULOS.index("ACAO RECOMENDADA"), u.TITULOS.index("RESPONSABILIDADE")
        for i, l in enumerate(u.linhas):
            assert m.data(m.index(i, i_acao)) == vocabulario.rotulo(l.acao, "acao")
            assert vocabulario.definicao(l.acao, "acao") in m.data(m.index(i, i_acao), Qt.ItemDataRole.ToolTipRole)
            assert m.data(m.index(i, i_paga)) == vocabulario.rotulo(l.quem_paga, "responsabilidade")
        # O score cru não é coluna nem texto de célula; só a dica da faixa
        assert "SCORE" not in u.TITULOS
        textos = {m.data(m.index(i, j)) for i in range(m.rowCount()) for j in range(m.columnCount())}
        assert not any(formatos.numero(l.score, 2) in textos for l in u.linhas)
        i_faixa = u.TITULOS.index("FAIXA")
        assert f"score de risco {formatos.numero(u.linhas[0].score, 2)}" in m.data(m.index(0, i_faixa),
                                                                                   Qt.ItemDataRole.ToolTipRole)
        # As 9 colunas à vista a 1500 px, cada título inteiro
        cabecalho, largura = u.tabela.horizontalHeader(), u.tabela.viewport().width()
        assert u.tabela.isVisible() and largura <= 1460
        for c in range(len(u.TITULOS)):
            assert 0 <= cabecalho.sectionViewportPosition(c)
            assert cabecalho.sectionViewportPosition(c) + cabecalho.sectionSize(c) <= largura + 1, u.TITULOS[c]
            titulo = vocabulario.titulo_coluna(u.TITULOS[c])
            assert cabecalho.fontMetrics().horizontalAdvance(titulo) <= cabecalho.sectionSize(c), titulo

    def test_pais_inteiro_sem_filtro(self, tela, qt):
        pa = _abrir(tela, qt, "orcamento")
        u = pa.orcamento.urgencia
        hoje = pa.painel.hoje
        ativos = [p for p in pa.painel.pendencias if p.ativa(hoje)]
        assert pa.painel.escopo == "NACIONAL" and "orcamento" not in pa.SEGUEM_O_FILTRO
        assert u.total == len(ativos) and len({p.uf for p in ativos}) > 1
        assert len({l.caso.uf for l in u.linhas}) > 1                                   # o topo já mistura UFs
        assert u.cartao.rodape.text().startswith(f"Mostrando 20 de {vocabulario.casos(len(ativos), 'ativos')} no país")
        antes = [l.caso.codigo for l in u.linhas]
        assert pa.estado.definir(ufs={"SP"}, situacao="TODAS")                         # filtro com "Todos"
        qt.processEvents()
        assert [l.caso.codigo for l in u.linhas] == antes and u.total == len(ativos)
        assert pa.estado.definir(situacao="ATIVAS")
        qt.processEvents()
        assert [l.caso.codigo for l in u.linhas] == antes and u.total == len(ativos)

    def test_lista_vazia_tem_mensagem(self, urgencia, qt):
        u, painel = urgencia, urgencia.painel
        encerrados = [p for p in painel.pendencias if not p.ativa(painel.hoje)]
        assert encerrados                                                               # só encerrados: lista vazia
        _remontar(u, qt, encerrados)
        assert u.total == 0 and u.linhas == [] and u.modelo.rowCount() == 0
        assert u.lista_vazia.isVisibleTo(u) and u.lista_vazia.text() == "Nenhum caso ativo na data de corte"
        assert not u.tabela.isVisibleTo(u)
        assert u.cartao.rodape.text() == "Nenhum caso ativo na data de corte."
        _remontar(u, qt, painel.pendencias)                                             # volta: a tabela no lugar
        assert u.tabela.isVisibleTo(u) and not u.lista_vazia.isVisibleTo(u) and u.modelo.rowCount() == 20

    def test_seletor_alterna_as_duas_visoes(self, orcamento, qt):
        o = orcamento
        assert [o.visoes.items[k].text() for k, _ in o.VISOES] == ["Por urgência", "Pelo orçamento público"]
        assert o.visao_atual == "urgencia"
        assert o.urgencia.isVisibleTo(o) and not o.pagina_orcamento.isVisibleTo(o)
        assert not o.controles.isVisibleTo(o)
        for tabela in (o.urgencia.tabela, o.tabela):                                    # nas duas
            assert not tabela.isSortingEnabled() and not tabela.horizontalHeader().sectionsClickable()
        o.visoes.items["orcamento"].click()                                             # o clique de verdade
        qt.processEvents()
        assert o.visao_atual == "orcamento" and o.pagina_orcamento.isVisibleTo(o)
        assert o.controles.isVisibleTo(o) and o.tabela.isVisibleTo(o)
        assert not o.urgencia.isVisibleTo(o) and o.modelo.rowCount() > 0               # a fila continua montada
        # o seletor fica na linha do orçamento e do critério (não tira altura da fila)
        assert o.visoes.geometry().center().y() == pytest.approx(o.controles.geometry().center().y(), abs=4)
        o.visoes.items["urgencia"].click()
        qt.processEvents()
        assert o.visao_atual == "urgencia" and not o.controles.isVisibleTo(o)

    def test_rodape_conta_os_grupos_sem_fonte(self, urgencia):
        u, painel = urgencia, urgencia.painel
        n = Counter(l.grupo for l in casos_por_urgencia(painel.pendencias, painel.hoje, painel.regras))
        rodape = u.cartao.rodape.text()
        assert rodape.startswith(f"Mostrando 20 de {vocabulario.casos(u.total, 'ativos')} no país: ")
        for trecho in (f"{formatos.inteiro(n[0])} críticos além do prazo legal",
                       f"{formatos.inteiro(n[1])} críticos dentro do prazo",
                       f"{formatos.inteiro(n[2])} além do prazo sem ser críticos", f"{formatos.inteiro(n[3])} demais"):
            assert trecho in rodape, trecho
        assert sum(n.values()) == u.total                                               # os grupos fecham com a base
        assert rodape.endswith("A lista completa está na Planilha analítica.")
        dica = u.cartao.toolTip()
        assert not ORIGEM.search(rodape + dica) and not hasattr(u, "base")
        assert not re.search(r"[—–]", rodape + dica)

    def test_resumo_do_topo_identifica_o_bloco(self, urgencia, qt):
        u, painel = urgencia, urgencia.painel
        scores = [l.score for l in u.linhas]
        faixa = f"score entre {formatos.numero(min(scores), 1)} e {formatos.numero(max(scores), 1)}."
        # nos dados reais o topo é todo de material radioativo, quase todo público (a frase identifica
        # o bloco, a ordem não muda). Números: 19 públicos e 1 de infraestrutura (PD-2213, MP-05),
        # e a frase é a do bloco misto.
        assert {l.caso.classe_risco for l in u.linhas} == {sinteticos.RADIOATIVO}
        assert Counter(l.quem_paga for l in u.linhas) == {regras.PUBLICO: 19, regras.INFRAESTRUTURA: 1}
        assert u.resumo.text() == ("Nos 20 primeiros casos, 20 são de material radioativo e 19 com responsabilidade "
                                   f"pública; {faixa}")
        assert u.resumo.isVisibleTo(u) and u.resumo.geometry().bottom() < u.tabela.geometry().top()   # antes das linhas
        # bloco misto: as contagens da classe e de quem paga dominantes
        _remontar(u, qt, _montados(painel))
        scores = [l.score for l in u.linhas]
        assert u.resumo.text() == ("Nos 6 primeiros casos, 4 são de material radioativo e 4 com carga a rastrear; "
                                   f"score entre {formatos.numero(min(scores), 1)} e "
                                   f"{formatos.numero(max(scores), 1)}.")
        assert resumo_do_topo([]) == ""
        _remontar(u, qt, [p for p in painel.pendencias if not p.ativa(painel.hoje)])
        assert not u.resumo.isVisibleTo(u)                                              # lista vazia: sem frase

    def test_sem_encerrados(self, tela, qt):
        pa = _abrir(tela, qt, "orcamento")
        u, painel = pa.orcamento.urgencia, pa.painel
        assert pa.estado.filtro.situacao == "TODAS"                                     # o padrão do filtro
        encerrados = {p.codigo for p in painel.pendencias if not p.ativa(painel.hoje)}
        assert encerrados
        todos = casos_por_urgencia(painel.pendencias, painel.hoje, painel.regras)
        assert len(todos) == u.total and not {l.caso.codigo for l in todos} & encerrados
        assert not {l.caso.codigo for l in u.linhas} & encerrados
