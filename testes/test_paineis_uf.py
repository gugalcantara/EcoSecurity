"""Os "Painéis da UF" do N2 como painel de decisão (n23_paineis_uf.PaineisUF).

Critérios de aceite: priorização (o que atacar primeiro), comparação contra referência (fim do ano
anterior e Brasil), próximo passo por item, números com unidade e rótulo simples e custo mantido
(o dado financeiro sai só do N1).

Cobre: "O que fazer agora" (a ação mais urgente com casos, o caso mais atrasado e a distância do Brasil; frase sem
dado não aparece e as seguintes sobem), o veredito UF × Brasil no sentido de cada indicador (na taxa de
encerramento maior é melhor; nos outros três, menor é melhor), cada um com um caso melhor e um pior em dados
montados, os cartões com comparação, a lista vazia com a mensagem de cada situação, o desempate da lista, a ação
recomendada inteira na tabela, nada em caixa alta entre parênteses (sem "PARAMETRO" nem simulação), nenhum código
nem travessão visível e a recarga sem acumular.

Também cobre os números que fecham com o serviço (seções, cartões, barras, lista, custo,
referência nacional, evolução, rodapés e o duplo clique que abre a ficha) e o sigilo do N2 (nenhum responsável,
nenhuma outra UF, a consulta ao país na trilha).
"""
import dataclasses
import re
from types import SimpleNamespace

import pytest

from ecosec.acervo import analise, formatos, regras, vocabulario
from ecosec.dominio.entidades import Usuario
from ecosec.dominio.niveis import Nivel
from ecosec.interface import n23_paineis_uf
from ecosec.interface.n23_paineis_uf import Comparacao

BIA_N2 = Usuario(matricula="BIA", nome="Bia", nivel=2, uf="SP", senha_hash="$2b$x", id=2)
CORTE = re.compile(r"corte \d{2}/\d{2}/\d{4}")
TRAVESSOES = ("—", "–")
TITULOS = ["ACAO RECOMENDADA", "PENDENCIAS", analise.CRITICAS]
INDICADORES = ("criticos", "alem", "vencidos", "taxa")          # a ordem de PaineisUF.comparacoes


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


@pytest.fixture
def pa(tela, qt):
    tela.iniciar(BIA_N2, Nivel.N2)
    tela.mostrar_modo("painel")
    p = tela.painel_analitico
    p.mostrar("paineis_uf")
    qt.processEvents()
    return p


def _textos_visiveis(pu, todos: bool = False) -> list[str]:
    """Texto que a pessoa lê: os rótulos visíveis e a tabela "Casos para agir já". Com todos (a varredura de
    sigilo), também os rótulos escondidos, os botões, os itens de combo e as outras tabelas."""
    from PySide6.QtCore import QAbstractListModel, Qt
    from PySide6.QtWidgets import QAbstractButton, QAbstractItemView, QComboBox, QLabel
    textos = [l.text() for l in pu.findChildren(QLabel) if todos or l.isVisibleTo(pu)]
    t = pu.tabela_casos
    if todos or t.isVisibleTo(pu):
        textos += [t.horizontalHeaderItem(j).text() for j in range(t.columnCount())]
        textos += [t.item(i, j).text() for i in range(t.rowCount()) for j in range(t.columnCount())]
    if todos:
        textos += [b.text() for b in pu.findChildren(QAbstractButton)]
        for combo in pu.findChildren(QComboBox):
            textos += [combo.itemText(i) for i in range(combo.count())]
        for vista in pu.findChildren(QAbstractItemView):
            m = vista.model()
            if vista is t or m is None:
                continue
            colunas = 1 if isinstance(m, QAbstractListModel) else m.columnCount()   # lista: columnCount é privado
            textos += [str(m.headerData(j, Qt.Orientation.Horizontal)) for j in range(colunas)]
            textos += [str(m.data(m.index(i, j))) for i in range(m.rowCount()) for j in range(colunas)]
    return textos


def _remontar_lista(pu, qt, pendencias):
    """A lista "Casos para agir já" sobre um conjunto montado de casos (as regras e a data de corte reais)."""
    real = pu.painel
    pu.painel = SimpleNamespace(pendencias=pendencias, regras=real.regras, hoje=real.hoje)
    pu._casos_ja(real.hoje)
    qt.processEvents()


# O que fazer agora
def test_proximo_passo_aponta_a_acao_mais_urgente_com_casos(pa):
    pu = pa.paineis_uf
    titulos, linhas = pu._tabela("POR ACAO RECOMENDADA")
    i_n = titulos.index("PENDENCIAS")
    assert [l[0] for l in linhas] == [a for a in regras.ACOES if a in {l[0] for l in linhas}]   # ordem de urgência
    primeira = next(l for l in linhas if l[i_n])
    assert pu.frases_agora[0].startswith(f"Comece por <b>{vocabulario.rotulo(primeira[0], 'acao')}</b>")
    assert vocabulario.casos(primeira[i_n]) in pu.frases_agora[0]
    assert pu.texto_agora.text().startswith("1. Comece por")


def test_proximo_passo_cita_o_caso_mais_atrasado_da_lista(pa):
    pu = pa.paineis_uf
    p = pu._casos[0]
    alem = regras.dias_alem_do_prazo_limite(p, pa.painel.hoje, pa.painel.regras)
    assert f"<b>{p.codigo}</b>" in pu.frases_agora[1]
    assert f"{formatos.numero(alem / formatos.DIAS_POR_ANO, 1)} anos além do prazo legal" in pu.frases_agora[1]
    acao = regras.acao_recomendada(p, pa.painel.hoje, pa.painel.regras)
    assert vocabulario.rotulo(acao, "acao").lower() in pu.frases_agora[1]
    assert len(pu.frases_agora) == 3


def test_proximo_passo_sem_acao_com_casos_comeca_pelo_caso(pa):
    pu = pa.paineis_uf
    zeradas = [[a, 0, 0] for a in regras.ACOES]
    pu._proximo_passo(zeradas, TITULOS, pu._candidatos, pu.comparacoes, "29/10/2026")
    assert pu.frases_agora[0].startswith("Caso mais atrasado:")
    assert "Comece por" not in pu.texto_agora.text()
    assert pu.texto_agora.text().startswith("1. Caso mais atrasado:")


def test_proximo_passo_sem_acao_e_sem_caso_atrasado_comeca_pela_distancia_do_pais(pa):
    pu = pa.paineis_uf
    zeradas = [[a, 0, 0] for a in regras.ACOES]
    pu._proximo_passo(zeradas, TITULOS, [], pu.comparacoes, "29/10/2026")
    assert len(pu.frases_agora) == 1
    # SP está pior que o Brasil em casos críticos
    assert pu.texto_agora.text() == ("1. Maior distância do Brasil: <b>Casos críticos</b>, 6,5 p.p. pior "
                                     "(UF 19,0%, Brasil 12,5%).")


def test_proximo_passo_com_acao_e_sem_caso_atrasado_pula_a_frase_do_caso(pa):
    """Frase sem dado não aparece e as seguintes sobem, na mesma ordem: ação, depois a distância do Brasil."""
    pu = pa.paineis_uf
    titulos, linhas = pu._tabela("POR ACAO RECOMENDADA")
    pu._proximo_passo(linhas, titulos, [], pu.comparacoes, "29/10/2026")
    # A distância do Brasil é a de casos críticos ("Maior"); antes, "A UF está melhor"
    assert [f.split(" ")[0] for f in pu.frases_agora] == ["Comece", "Maior"]
    assert "Caso mais atrasado" not in pu.texto_agora.text()


def test_proximo_passo_sem_nada_mostra_aviso_e_nenhuma_frase_vazia(pa):
    pu = pa.paineis_uf
    pu._proximo_passo([], TITULOS, [], [], "29/10/2026")
    assert pu.frases_agora == []
    assert pu.texto_agora.text() == "Sem casos ativos e sem comparação com o Brasil: nada a priorizar."


# UF × Brasil: melhor ou pior, no sentido certo
def _comparar(pu, indicador=None, sentido=None):
    """UF montada: 100 ativos, 50 críticos, 60 além do prazo legal, 70 com prazo previsto vencido e taxa de
    encerramento de 10%. Brasil igual em tudo, exceto indicador, deslocado 5 p.p. (2,5 p.p. na taxa) no sentido
    pedido."""
    real = pu.dados["referencia"]
    br = {"criticos": 500, "alem": 600, "vencidos": 700, "taxa": 10.0}
    if indicador:
        uf_menor = (sentido == "melhor") != (indicador == "taxa")     # a UF fica abaixo do Brasil?
        passo = 2.5 if indicador == "taxa" else 50
        br[indicador] += passo if uf_menor else -passo
    pu.dados["referencia"] = dataclasses.replace(real, ativas=1000, criticas=br["criticos"],
                                                 alem_do_prazo=br["alem"], fora_da_previsao=br["vencidos"],
                                                 taxa_encerramento=br["taxa"])
    pu.dados["kpis"] = {**pu.dados["kpis"], "KPI-02": SimpleNamespace(valor=10.0)}
    pu._comparacao(100, 50, 60, 70, "SP")


@pytest.mark.parametrize("sentido", ["melhor", "pior"])
@pytest.mark.parametrize("indicador", INDICADORES)
def test_comparacao_diz_melhor_ou_pior_no_sentido_de_cada_indicador(pa, indicador, sentido):
    pu = pa.paineis_uf
    _comparar(pu, indicador, sentido)
    i = INDICADORES.index(indicador)
    alvo = pu.comparacoes[i]
    assert alvo.maior_e_melhor is (indicador == "taxa")
    assert alvo.veredito == sentido
    distancia = "2,5" if indicador == "taxa" else "5,0"
    assert f"<b>{distancia} p.p. {sentido}</b>" in alvo.frase()
    assert alvo.frase() in pu.texto_comparacao.text()
    assert [c.veredito for j, c in enumerate(pu.comparacoes) if j != i] == ["igual"] * 3
    assert f"{sentido} em 1 e igual em 3 dos 4 indicadores" in pu.texto_comparacao.text()
    # o próximo passo usa o mesmo veredito: o pior indicador, ou a menor folga quando nenhum é pior
    pu._proximo_passo([], TITULOS, [], pu.comparacoes, "29/10/2026")
    if sentido == "pior":
        assert pu.frases_agora == [f"Maior distância do Brasil: <b>{alvo.rotulo}</b>, {distancia} p.p. pior "
                                   f"(UF {formatos.percentual(alvo.valor)}, Brasil "
                                   f"{formatos.percentual(alvo.referencia)})."]
    else:
        assert pu.frases_agora[0].startswith("A UF está melhor ou igual ao Brasil nos 4 indicadores")


def test_comparacao_com_a_frase_no_formato_combinado():
    cp = Comparacao("Taxa anual de encerramento (2025)", 5.2, 7.8, maior_e_melhor=True)
    assert cp.frase() == "Taxa anual de encerramento (2025): 5,2% (Brasil 7,8%, <b>2,6 p.p. pior</b>)"
    assert not any(t in cp.frase() for t in TRAVESSOES)


def test_comparacao_igual_na_casa_decimal_e_sem_dado():
    assert Comparacao("Casos críticos", 57.81, 57.84, False).veredito == "igual"
    assert Comparacao("Casos críticos", 57.8, 57.9, False).veredito == "melhor"
    sem = Comparacao("Casos críticos", 57.8, None, False)
    assert sem.veredito is None and sem.frase() == "Casos críticos: 57,8% (Brasil sem dado, sem comparação)"


def test_dados_reais_de_sp_pior_que_o_brasil_so_em_criticos(pa):
    # Com a régua nova, SP tem 19,0% de casos críticos e o Brasil 12,5%. Antes, SP era
    # melhor nos 4 (57,8% contra 61,0% de críticos) e o teste se chamava ..._melhor_que_o_brasil_nos_quatro
    pu = pa.paineis_uf
    assert [c.veredito for c in pu.comparacoes] == ["pior", "melhor", "melhor", "melhor"]
    assert "<b>UF SP × Brasil:</b> melhor em 3 e pior em 1 dos 4 indicadores." in pu.texto_comparacao.text()


# cartões com referência
def test_cartoes_comparam_com_o_ano_anterior_e_com_o_pais(pa):
    pu = pa.paineis_uf
    hoje = pa.painel.hoje
    estoque = pu.dados["panorama"].serie["estoque_total"]
    ativos = sum(p.ativa(hoje) for p in pa.painel.pendencias)
    diferenca = ativos - estoque[hoje.year - 1]
    sinal = "+" if diferenca > 0 else ""
    assert pu.cartoes["ativos"].contexto.text().startswith(
        f"{sinal}{formatos.inteiro(diferenca)} desde o fim de {hoje.year - 1} ({formatos.inteiro(estoque[hoje.year - 1])})")
    ref = pu.dados["referencia"]
    for chave, parte in (("criticos", ref.criticas), ("alem", ref.alem_do_prazo), ("vencidos", ref.fora_da_previsao)):
        assert pu.cartoes[chave].contexto.text().endswith(f"Brasil {formatos.percentual(100 * parte / ref.ativas)}"), chave
    assert pu.cartoes["custo"].valor.text().startswith("R$")            # O custo fica no N2


# lista vazia e ordem
def test_lista_vazia_sem_casos_ativos(pa, qt):
    pu = pa.paineis_uf
    _remontar_lista(pu, qt, [p for p in pa.painel.pendencias if not p.ativa(pa.painel.hoje)])
    assert pu.lista_vazia.text() == "Nenhum caso ativo nesta UF"
    assert pu.lista_vazia.isVisibleTo(pu) and not pu.tabela_casos.isVisibleTo(pu)
    assert pu._casos == [] and "Mostrando" not in pu.casos.rodape.text()


def test_lista_vazia_com_criticos_mas_nenhum_alem_do_prazo(pa, qt, monkeypatch):
    pu = pa.paineis_uf
    monkeypatch.setattr(regras, "dias_alem_do_prazo_limite", lambda p, hoje, r: 0)
    _remontar_lista(pu, qt, list(pa.painel.pendencias))
    assert pu.lista_vazia.text() == "Nenhum caso crítico além do prazo legal"
    assert pu.lista_vazia.isVisibleTo(pu) and not pu.tabela_casos.isVisibleTo(pu)


def test_lista_vazia_com_ativos_mas_nenhum_critico(pa, qt, monkeypatch):
    pu = pa.paineis_uf
    monkeypatch.setattr(regras, "categoria", lambda p, hoje: "ALTO")
    _remontar_lista(pu, qt, list(pa.painel.pendencias))
    assert pu.lista_vazia.text() == "Nenhum caso crítico nesta UF"


def test_lista_volta_a_aparecer_depois_de_vazia(pa, qt):
    pu = pa.paineis_uf
    pendencias = list(pa.painel.pendencias)
    _remontar_lista(pu, qt, [])
    _remontar_lista(pu, qt, pendencias)
    assert pu.tabela_casos.isVisibleTo(pu) and not pu.lista_vazia.isVisibleTo(pu)
    assert pu.tabela_casos.rowCount() == n23_paineis_uf.MAX_CASOS


def test_lista_desempata_pelo_codigo(pa, qt, monkeypatch):
    pu = pa.paineis_uf
    monkeypatch.setattr(regras, "dias_alem_do_prazo_limite", lambda p, hoje, r: 1000)     # todos empatados
    _remontar_lista(pu, qt, list(pa.painel.pendencias))
    codigos = [p.codigo for p in pu._casos]
    assert codigos == sorted(codigos) and len(codigos) == n23_paineis_uf.MAX_CASOS


# legibilidade
def test_acao_recomendada_inteira_e_municipio_estreito(pa, qt):
    pu = pa.paineis_uf
    t = pu.tabela_casos
    acoes = {t.item(i, 3).text() for i in range(t.rowCount())}
    assert {"Priorizar no orçamento público", "Levar ao Ministério Público"} <= acoes
    assert t.sizeHintForColumn(3) <= t.columnWidth(3)                   # nenhuma ação cortada
    assert all(not t.item(i, 1).text().endswith("/SP") for i in range(t.rowCount()))
    assert t.item(0, 3).toolTip().startswith(t.item(0, 3).text() + "\n")      # a dica tem o texto inteiro
    # um município longo fica estreito (com a dica inteira) e a ação continua inteira
    hoje = pa.painel.hoje
    pendencias = [dataclasses.replace(p, municipio="SAO BERNARDO DO CAMPO") if p is pu._casos[0] else p
                  for p in pa.painel.pendencias]
    _remontar_lista(pu, qt, pendencias)
    assert t.columnWidth(1) <= n23_paineis_uf.LARGURA_MUNICIPIO
    assert t.item(0, 1).toolTip() == f"SAO BERNARDO DO CAMPO/{pu._casos[0].uf}"
    assert t.sizeHintForColumn(3) <= t.columnWidth(3)
    assert regras.categoria(pu._casos[0], hoje) == "CRITICO"


def test_nada_em_caixa_alta_entre_parenteses_e_sem_simulacao(pa):
    pu = pa.paineis_uf
    textos = _textos_visiveis(pu)
    caixa_alta = [t for t in textos for dentro in re.findall(r"\(([^()]*)\)", t)
                  if re.search(r"[A-Z]{3,}", dentro) and not re.search(r"[a-zà-ú]", dentro)]
    assert not caixa_alta, caixa_alta
    assert not [t for t in textos if "PARAMETRO" in t]
    # sem a menção a valores simulados, também nas dicas
    assert pu.cartoes["custo"].contexto.text() == "para resolver os casos ativos"
    for dica in (pu.cartoes["custo"].toolTip(), pu.custo.toolTip()):
        assert "PARAMETRO" not in dica and "simula" not in dica


def test_textos_sem_travessao_sem_codigo_e_com_unidade(pa):
    pu = pa.paineis_uf
    textos = _textos_visiveis(pu)
    assert not [t for t in textos if any(x in t for x in TRAVESSOES)]
    assert not [t for t in textos if re.search(r"KPI-0|\bk=\d|escore|pend[êe]ncia", t)]
    assert pu.comparacao.toolTip() == ("Os totais do Brasil escondem números muito pequenos, para proteger poucos "
                                       "casos.")                          # sem "k=3"
    assert "serviço do acervo" not in pu.cabecalho.text() and "trilha" not in pu.cabecalho.text()
    assert all("p.p." in c.frase() for c in pu.comparacoes)
    assert "p.p. = pontos percentuais" in pu.comparacao.rodape.text()
    for chave in ("criticos", "alem", "vencidos"):
        assert pu.cartoes[chave].valor.text().endswith("%") or chave == "criticos"
        assert "%" in pu.cartoes[chave].contexto.text()


# recarga
def test_carregar_duas_vezes_nao_acumula_linhas_nem_widgets(pa, qt):
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QLabel, QWidget
    pu = pa.paineis_uf
    antes = (len(pu.findChildren(QWidget)), len(pu.findChildren(QLabel)), pu.tabela_casos.rowCount(),
             list(pu.frases_agora), pu.texto_comparacao.text())
    pu.carregar(pa.painel)
    qt.processEvents()
    # a legenda do custo (BarraPartes) troca as linhas com deleteLater; fora do laço de eventos a remoção fica
    # pendente, e processEvents não a executa (o mesmo recurso de test_interface.py)
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    depois = (len(pu.findChildren(QWidget)), len(pu.findChildren(QLabel)), pu.tabela_casos.rowCount(),
              list(pu.frases_agora), pu.texto_comparacao.text())
    assert antes == depois


# números que fecham com o serviço
def test_secoes_e_numeros_que_fecham_com_o_servico(tela, pa, qt):
    pu = pa.paineis_uf
    servico = tela.app.acervo
    assert list(pu.paineis) == ["prioridade", "casos", "evolucao", "comparacao", "custo"]
    hoje = pa.painel.hoje
    ativos = [p for p in pa.painel.pendencias if p.ativa(hoje)]
    assert {p.uf for p in pa.painel.pendencias} == {"SP"}
    # cartões e barras de ação: somam os casos ativos da UF, igual ao resumo do serviço
    titulos, linhas = servico.resumo_agregado(BIA_N2, 2).tabelas["POR ACAO RECOMENDADA"]
    assert pu.cartoes["ativos"].valor.text() == formatos.inteiro(len(ativos))
    assert sum(b.total for b in pu.barras_acao.barras) == len(ativos) == sum(l[titulos.index("PENDENCIAS")]
                                                                           for l in linhas)
    criticos = sum(b.segmentos[0][0] for b in pu.barras_acao.barras)
    assert criticos == sum(regras.categoria(p, hoje) == "CRITICO" for p in ativos)
    assert [b.rotulo for b in pu.barras_acao.barras] == [vocabulario.rotulo(l[0], "acao") for l in linhas]
    # casos para agir já: críticos além do prazo legal, do mais atrasado para o menos
    r = pa.painel.regras
    alem = [regras.dias_alem_do_prazo_limite(p, hoje, r) for p in pu._casos]
    assert pu._casos and alem == sorted(alem, reverse=True) and all(a > 0 for a in alem)
    assert all(regras.categoria(p, hoje) == "CRITICO" and p.ativa(hoje) for p in pu._casos)
    # custo: as categorias e as barras por ação somam o total do painel de custo do serviço
    custo = servico.painel_custo(BIA_N2, 2)
    assert sum(v for _, v, _, _ in pu.partes_custo.partes) == pytest.approx(custo.total, abs=0.05)
    assert sum(b.total for b in pu.barras_custo.barras) == pytest.approx(custo.total, abs=1.0)
    assert pu.cartoes["custo"].valor.text() == formatos.custo(custo.total)
    # UF × país: o país é a linha NACIONAL protegida (k do N1), igual à referência do serviço
    ref = servico.referencia_nacional(BIA_N2)
    assert ref.supressao_minima == 3 and ref.ativas == sum(p.ativa(hoje) for p in servico.repo.pendencias())
    linha = pu.halteres.linhas[0]
    assert linha.referencia == pytest.approx(100 * ref.criticas / ref.ativas)
    assert linha.valor == pytest.approx(100 * criticos / len(ativos))
    # evolução: o último ano do estoque é o estoque ativo de hoje
    serie = pu.linha_estoque.series[0].valores
    assert serie[hoje.year] == len(ativos)
    # rodapés: o que as barras somam, sem data de corte nem fonte
    for chave in ("prioridade", "custo"):
        rodape = pu.paineis[chave].rodape.text()
        assert "somam" in rodape and not CORTE.search(rodape) and "fonte" not in rodape, chave
    # duplo clique na lista abre a ficha no mapa
    pu._caso_escolhido(0, 0)
    qt.processEvents()
    assert pa.pilha.currentWidget() is pa.mapa.property("cartao") and pa.mapa._p_atual is pu._casos[0]


# sigilo do N2
def test_n2_sem_pessoa_fisica_sem_custo_por_responsavel_e_pais_sem_outras_ufs(tela, pa):
    servico = tela.app.acervo
    assert "responsaveis" not in pa.abas.items and "orcamento" not in pa.abas.items
    nomes = {r.nome for r in servico.repo.responsaveis(3)}
    textos = " ".join(_textos_visiveis(pa.paineis_uf, todos=True))
    assert not any(n in textos for n in nomes)
    outras = sorted(set(analise.REGIAO_DA_UF) - {"SP"})
    assert not any(re.search(rf"\b{uf}\b", textos) for uf in outras)           # nenhuma outra UF aparece
    motivos = [r.evento.motivo for r in servico.trilha.recentes(80)]
    assert "REFERENCIA_NACIONAL" in motivos                                   # a consulta ao país fica na trilha
    # o país vem só como uma linha NACIONAL: o objeto não carrega UF nenhuma
    ref = servico.referencia_nacional(BIA_N2)
    assert not any(isinstance(v, dict) for v in vars(ref).values())
