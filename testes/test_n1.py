"""O painel analítico do N1 por perguntas (interface/n1_painel.py).

Estrutura (cinco seções com o nome da pergunta, faixa de indicadores com nome do vocabulário e variação anual,
cartões sem fonte, nível nem corte, tabela equivalente em todo gráfico); política da camada (nenhum "R$", CNPJ,
endereço, coordenada ou código de caso em texto visível ou dica); None do serviço = "Suprimido", nunca 0 (acervo
pequeno que força supressão); Índice de pressão do N1 sem custo e o do N3 com; agregados
novos protegidos (nenhuma célula escondida se recompõe por soma com as outras vistas do N1, prova algébrica);
filtro de classe e ano propagado a todas as seções; mapa navegável (arrasto, clique na UF ao soltar,
Ctrl + roda dá zoom e a roda sozinha rola a página, − + e Brasil). Gera as capturas "depois".
"""
import re

import pytest

from ecosec.acervo import analise, quantidades, sinteticos, vocabulario
from ecosec.dominio.entidades import Usuario
from ecosec.dominio.niveis import Nivel

ANA_N1 = Usuario(matricula="ANA", nome="Ana", nivel=1, senha_hash="$2b$x", id=1)
CAIO_N3 = Usuario(matricula="CAIO", nome="Caio", nivel=3, senha_hash="$2b$x", id=3)
AREA, CLASSE_I, RADIOATIVO = sinteticos.AREA, sinteticos.CLASSE_I, sinteticos.RADIOATIVO
HOJE = sinteticos.DATA_BASE
TODAS = analise.TODAS
SECOES =["onde", "tipo", "motivos", "resolucao", "prazo"]
PERGUNTAS = ["Onde estão os casos?", "Que tipo de passivo?", "Por que continuam abertos?", "Estão sendo resolvidos?",
             "Quanto está fora do prazo?"]
DINHEIRO = re.compile(r"R\$")
CNPJ = re.compile(r"\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}")
COORDENADA = re.compile(r"-?\d{1,2}[.,]\d{4,}")


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


def _esperar(ms: int = 60):
    from PySide6.QtTest import QTest
    QTest.qWait(ms)


def _abrir(tela):
    tela.iniciar(ANA_N1, Nivel.N1)
    tela.mostrar_modo("painel")
    _esperar(150)
    return tela.painel_analitico.panorama


def _montar_pequeno(tela):
    from test_paineis_tela import _montar_pequeno as montar
    montar(tela)


def _preparar(pn):
    """Mostra cada seção e pinta cada gráfico (os textos e os alvos de mouse saem da pintura)."""
    for chave in pn.secoes:
        pn.mostrar_secao(chave)
        _esperar(30)
        for gr in pn.secoes[chave].graficos():
            if hasattr(gr, "preparar"):
                gr.preparar()


def _visiveis(pn) -> list[str]:
    """O que a pessoa lê: rótulos, botões, combos, textos desenhados nos gráficos e as células das tabelas."""
    from PySide6.QtWidgets import QAbstractButton, QComboBox, QLabel
    textos = [w.text() for w in pn.findChildren(QLabel)]
    textos += [w.text() for w in pn.findChildren(QAbstractButton)]
    for w in pn.findChildren(QComboBox):
        textos += [w.itemText(i) for i in range(w.count())]
    for gr in pn.graficos():
        if hasattr(gr, "textos"):
            textos += gr.textos()
        titulos, linhas = gr.tabela()
        textos += list(titulos) + [str(c) for l in linhas for c in l]
    return textos


def _dicas(pn) -> list[str]:
    from PySide6.QtWidgets import QWidget
    dicas = [w.toolTip() for w in pn.findChildren(QWidget) if w.toolTip()]
    for gr in pn.graficos():
        if hasattr(gr, "dicas"):
            dicas += gr.dicas()
    return dicas


# ================================================================ estrutura
def test_cinco_secoes_com_o_nome_da_pergunta_e_cartoes_com_fonte(tela):
    from ecosec.interface.n1_painel import PainelN1
    pn = _abrir(tela)
    assert isinstance(pn, PainelN1)
    assert list(pn.secoes) == SECOES and list(pn.abas_secoes.items) == SECOES
    assert [pn.abas_secoes.items[c].text() for c in SECOES] == PERGUNTAS
    assert [pn.secoes[c].titulo.text() for c in SECOES] == PERGUNTAS
    esperado = {"onde": {"mapa", "ranking", "regioes"}, "tipo": {"atividades", "regiao_classe"},
                "motivos": {"motivos", "motivo_classe"}, "resolucao": {"estoque", "fluxos", "taxa", "curva", "idade"},
                "prazo": {"prazo_regiao", "prazo_classe", "prazo_uf", "prazo_calor"}}
    _preparar(pn)
    for chave, cartoes in esperado.items():
        secao = pn.secoes[chave]
        assert set(secao.cartoes) == cartoes, chave
        for nome, cartao in secao.cartoes.items():
            assert cartao.titulo.text() and cartao.subtitulo.text(), (chave, nome)
            assert "KPI-0" not in cartao.titulo.text() + cartao.subtitulo.text()
            assert not re.search(r"fonte|nível mínimo|corte: ", cartao.dica), nome  # sem origem
            titulos, linhas = cartao.grafico.tabela()                  # todo gráfico tem a tabela equivalente
            assert titulos and linhas, (chave, nome)
            cartao.alternar_tabela()
            assert cartao.pilha.currentWidget() is cartao.tabela and cartao.tabela.rowCount() == len(linhas)
            cartao.alternar_tabela()
            assert cartao.pilha.currentWidget() is cartao.grafico
    # nenhum gráfico de um eixo só com três barras: cada seção tem pelo menos dois gráficos
    assert all(len(pn.secoes[c].cartoes) >= 2 for c in SECOES)
    # a navegação troca a seção à vista sem recarregar
    pedidos = len(_registros(tela))
    for chave in SECOES:
        pn.mostrar_secao(chave)
        assert pn.pilha.currentWidget().widget() is pn.secoes[chave] and pn.secao_atual == chave
    assert len(_registros(tela)) == pedidos


def test_faixa_de_indicadores_com_nome_variacao_e_base(tela):
    pn = _abrir(tela)
    d = pn.dados["n1"]
    ids = [i.id for i in d.indicadores]
    assert ids == ["ATIVOS", "KPI-03", "KPI-03b", "CRITICOS", "KPI-02", "KPI-01", "KPI-04"]
    assert list(pn.cartoes) == ids
    for ind in d.indicadores:
        cartao = pn.cartoes[ind.id]
        if ind.id.startswith("KPI"):
            assert cartao.nome.text() == vocabulario.ROTULO_KPI[ind.id]
            assert ind.id in cartao.toolTip()                          # o código só na dica
        assert "KPI-0" not in cartao.nome.text() + cartao.valor.text() + cartao.variacao.text()
        assert cartao.valor.text() and cartao.base.text() == ind.base                # sem o corte
        assert not re.search(r"fonte|nível mínimo|corte: ", cartao.toolTip())
        # variação: o serviço manda as duas pontas; a tela escreve seta, sinal e o ano de comparação
        assert ind.ano_anterior == HOJE.year - (2 if ind.id == "KPI-02" else 1)
        if ind.variacao is not None:
            assert ind.variacao == pytest.approx(round(ind.valor - ind.anterior, 1))
            texto = cartao.variacao.text()
            assert texto.endswith(f"em relação a {ind.ano_anterior}")
            if ind.variacao:
                assert texto[0] in "▲▼" and ("+" if ind.variacao > 0 else "-") in texto
                unidade = "p.p." if ind.unidade.startswith("%") else ("caso" if ind.unidade == "casos" else "ano")
                assert unidade in texto
            else:                                    # sem variação, sem unidade (o KPI-04 ficou em 8,0 anos)
                assert texto == f"= estável em relação a {ind.ano_anterior}"
    assert "p.p." in pn.cartoes["KPI-03"].variacao.text()
    # os números da faixa são os mesmos do resto do painel
    assert d.indicadores[0].valor == d.nacional.ativas == pn.dados["uf"].total.ativas
    assert d.indicadores[1].valor == round(100 * d.nacional.alem_do_prazo / d.nacional.ativas, 1)
    kpis = {k.id: k for k in tela.app.acervo.kpis(ANA_N1, 1)}
    for i in d.indicadores:
        if i.id in kpis:
            assert i.valor == kpis[i.id].valor, i.id
    # a seta tem a cor pela direção boa: mais casos além do prazo é ruim; mais encerramento é bom
    from ecosec.interface import n1_graficos as g
    from ecosec.interface.n1_painel import CartaoIndicador
    sobe = next(i for i in d.indicadores if i.id == "KPI-03")
    assert CartaoIndicador.texto_variacao(sobe)[1] == ("ruim" if sobe.variacao > 0 else "bom")
    taxa = next(i for i in d.indicadores if i.id == "KPI-02")
    assert CartaoIndicador.texto_variacao(taxa)[1] == ("bom" if taxa.variacao > 0 else "ruim")
    assert g.cor_status("ruim") in pn.cartoes["KPI-03"].variacao.styleSheet() or not sobe.variacao


# ================================================================ política da camada
def test_nada_financeiro_nem_identificador_em_texto_visivel_ou_dica(tela):
    pn = _abrir(tela)
    pendencias = list(tela.app.acervo.repo.pendencias())
    municipios = {p.municipio for p in pendencias if len(p.municipio) > 6}
    logradouros = {p.logradouro for p in pendencias if len(p.logradouro) > 8}
    for chave in SECOES:
        pn.mostrar_secao(chave)
        for i in range(pn.combo_indicador.count()):
            pn.combo_indicador.setCurrentIndex(i)
            _esperar(10)
            _preparar(pn)
            textos = _visiveis(pn) + _dicas(pn) + [r.toolTip() for r in pn.mapa.ufs.values()]
            tudo = "\n".join(textos)
            for e in sinteticos.EVENTOS:           # marcos regulatórios são texto público ("Regulamento paulista...")
                tudo = tudo.replace(e.descricao, "").replace(e.rotulo, "")
            assert not DINHEIRO.search(tudo), "valor em reais no N1"
            assert "custo estimado" not in tudo.lower().replace("o custo estimado não entra", "")
            assert not CNPJ.search(tudo) and not COORDENADA.search(tudo)
            assert not re.search(r"PD-\d{4}", tudo)                    # código de caso
            assert not [m for m in municipios if m in tudo.upper()]
            assert not [l for l in logradouros if l in tudo.upper()]
        break                                                        # os combos valem para todas as seções
    visiveis = _visiveis(pn)
    assert not [t for t in visiveis if "KPI-0" in t or "NBR 10004" in t or "AG-" in t or "MP-" in t]


# ================================================================ None = Suprimido
def test_none_do_servico_aparece_suprimido_e_nunca_zero(tela):
    from ecosec.interface import n1_graficos as g
    _montar_pequeno(tela)
    pn = _abrir(tela)
    _preparar(pn)
    d, pc = pn.dados["n1"], pn.dados["classe"]
    # faixa: indicador None = Suprimido (ou "não atingido", quando o serviço diz)
    nulos = [i for i in d.indicadores if i.valor is None]
    assert nulos
    for i in nulos:
        texto = pn.cartoes[i.id].valor.text()
        assert texto == ("não atingido" if "não atingido" in i.observacao else "Suprimido"), i.id
        if texto == "Suprimido":
            assert "Não quer dizer zero" in pn.cartoes[i.id].toolTip()
    # classes: o rejeito (2 casos) some, e a classe I sai junto como complementar
    linhas = {l.classe: l for l in pc.linhas}
    assert linhas[RADIOATIVO].ativas is None
    for c, l in linhas.items():
        cartao = pn.cartoes_classe[c]
        assert (cartao.valor.text() == "Suprimido") == (l.ativas is None)
    # mapa de calor região × classe: célula None = "Suprimido" desenhado, nunca "0"
    rc = pn.regiao_classe
    for i_linha, linha in enumerate(rc.celulas):
        for celula in linha:
            if celula["valor"] is None:
                assert celula["texto"] == "Suprimido" and "Suprimido" in celula["dica"]
    assert "Suprimido" in rc.textos()
    sudeste = next(r for r in d.regioes if r.chave == "SUDESTE")
    assert sudeste.por_classe[RADIOATIVO] is None
    # ranking: a UF suprimida (MG) no fim, sem número; UFs sem casos ativos sem barra
    assert pn.panorama.pressao["MG"].suprimida
    mg = next(l for l in pn.ranking.linhas if l["chave"] == "MG")
    assert mg["valor"] is None and mg["fim"] == "" and pn.ranking.linhas[-1]["valor"] is None
    assert "Suprimido" in pn.ranking.textos() and "sem casos ativos" in pn.ranking.textos()
    # prazo por UF: MG com as duas medidas Suprimido
    uf = {l["chave"]: l for l in pn.prazo_uf.linhas}["MG"]
    assert uf["a"] is None and uf["b"] is None
    assert "Suprimido" in pn.prazo_uf.textos()
    # idade: a classe suprimida desenha Suprimido, não uma barra vazia de 0%
    assert any(t == "Suprimido" for t in pn.idade.textos())
    # nenhum gráfico escreve 0 onde o serviço mandou None: os textos "0" só vêm de células visíveis de valor 0
    for gr in pn.graficos():
        if isinstance(gr, g.MapaCalorN1):
            for linha in gr.celulas:
                for celula in linha:
                    assert not (celula["valor"] is None and celula["texto"] in ("0", "0%"))


def test_estoque_e_fluxos_do_n1_seguem_o_cubo(tela):
    """O estoque por classe e ano e os fluxos do N1 chegam ao gráfico com o destino do serviço:
    None vira vão na linha (tracinho no pé), nunca 0."""
    _montar_pequeno(tela)
    pn = _abrir(tela)
    pn.mostrar_secao("resolucao")
    pn.estoque.preparar()
    p = pn.panorama
    suprimidos = [a for a in p.serie["anos"] if p.serie["ativas"][RADIOATIVO][a] is None]
    assert suprimidos and p.totais_classe.get(RADIOATIVO) is None
    assert all(p.serie["estoque_total"][a] is not None for a in p.serie["anos"])     # o total do ano fica à vista
    for a in p.serie["anos"]:                                  # nenhuma classe sozinha escondida num ano
        assert len([c for c, d in p.serie["ativas"].items() if d[a] is None]) != 1, a
    serie = next(s for s in pn.estoque.series if s["chave"] == RADIOATIVO)
    assert all(dict(serie["pontos"])[a] is None for a in suprimidos)
    dica = pn.estoque._dica(suprimidos[0])
    assert f"{vocabulario.rotulo(RADIOATIVO)}: Suprimido" in dica


# ================================================================ índice de pressão
def test_indice_de_pressao_do_n1_sem_custo_e_do_n3_com(tela):
    acervo = tela.app.acervo
    n1, n3 = acervo.panorama(ANA_N1, 1), acervo.panorama(CAIO_N3, 3)
    assert dict(n1.pesos) == pytest.approx({"volume": 0.375, "severidade": 0.375, "atraso": 0.25})
    assert dict(n3.pesos) == pytest.approx(acervo.pesos_pressao) and "custo" in dict(n3.pesos)
    assert analise.pesos_sem_custo({"volume": 0.3, "severidade": 0.3, "custo": 0.2, "atraso": 0.2}) == {
        "volume": 0.375, "severidade": 0.375, "atraso": 0.25}
    pendencias = list(acervo.repo.pendencias())
    ufs = sorted(analise.REGIAO_DA_UF)
    hoje = acervo.hoje()
    sem = analise.indice_pressao(pendencias, ufs, hoje, acervo.regras, analise.pesos_sem_custo(acervo.pesos_pressao))
    com = analise.indice_pressao(pendencias, ufs, hoje, acervo.regras, acervo.pesos_pressao)
    for uf in ufs:
        if not n1.pressao[uf].suprimida:
            assert n1.pressao[uf].indice == sem[uf].indice, uf
        assert n3.pressao[uf].indice == com[uf].indice, uf
    assert any(sem[uf].indice != com[uf].indice for uf in ufs)            # o custo de fato saiu
    assert all(item.custo is None for item in n1.pressao.values())
    assert dict(acervo.painel_n1(ANA_N1, 1).pesos_pressao) == dict(n1.pesos)
    # a dica mostra como é calculado, com os pesos do serviço
    pn = _abrir(tela)
    pn.combo_indicador.setCurrentIndex(0)
    _esperar()
    dica = pn.mapa.toolTip()
    assert "Nível 1, sem custo" in dica and "0,375 × posição no volume" in dica and "0,25 × posição na fração além" in dica
    assert "custo estimado" not in dica and "R$" not in dica
    assert dica == pn.legenda.toolTip() == pn.secoes["onde"].cartoes["mapa"].dica


# ================================================================ agregados novos protegidos
def _equacoes_do_cubo(d, pu, panorama, classes):
    """Células (linha, coluna) que o N1 publica com origem no cubo e as equações que as ligam: cada linha soma as
    classes; a região soma as UFs; o total soma as regiões e as atividades."""
    valores, publicados, equacoes = {}, {}, []

    def pub(celula, valor):
        publicados[celula] = valor
    for r in d.regioes:
        pub((("R", r.chave), TODAS), r.ativas)
        for c in classes:
            pub((("R", r.chave), c), r.por_classe[c])
    pub((("N",), TODAS), d.nacional.ativas)
    for c in classes:
        pub((("N",), c), d.nacional.por_classe[c])
    for a in d.atividades:
        pub((("A", a.chave), TODAS), a.ativas)
        for c in classes:
            pub((("A", a.chave), c), a.por_classe[c])
    for l in pu.linhas:
        pub((("U", l.uf), TODAS), None if l.suprimida else l.ativas)
    for uf, por in panorama.por_classe.items():
        for c in classes:
            if not panorama.pressao[uf].suprimida:
                pub((("U", uf), c), por.get(c, 0))
            else:
                pub((("U", uf), c), None)
    linhas = {cel[0] for cel in publicados}
    for linha in linhas:
        equacoes.append(((linha, TODAS), [(linha, c) for c in classes]))
    for col in (*classes, TODAS):
        for r, ufs in analise.REGIOES.items():
            equacoes.append(((("R", r), col), [(("U", uf), col) for uf in ufs]))
        equacoes.append(((("N",), col), [(("R", r), col) for r in analise.REGIOES]))
        equacoes.append(((("N",), col), [(("A", a.chave), col) for a in d.atividades]))
    return publicados, equacoes


@pytest.mark.parametrize("pequeno", [False, True])
def test_agregados_novos_do_n1_nao_se_recompoem(tela, pequeno):
    """Região × classe, atividade × classe (do cubo) e motivo × classe (grade nova): nenhuma célula visível com
    0 < n < 3 e nenhuma escondida determinada pelas equações que o N1 publica (álgebra linear exata)."""
    if pequeno:
        _montar_pequeno(tela)
    acervo = tela.app.acervo
    pendencias = list(acervo.repo.pendencias())
    classes = list(quantidades.CLASSES)
    escondidas_vistas = 0
    for ano, classe in ((None, None), (2015, None), (None, RADIOATIVO), (2020, CLASSE_I)):
        d = acervo.painel_n1(ANA_N1, 1, ano, classe)
        corte = d.corte
        cls = [classe] if classe else classes
        # ---- cubo: região, atividade, UF e o total, coerentes entre as vistas
        if classe is None:
            pu = acervo.painel_uf(ANA_N1, 1, ano)
            pan = acervo.panorama(ANA_N1, 1, ano)
            publicados, equacoes = _equacoes_do_cubo(d, pu, pan, cls)
            reais = {}
            for (linha, col) in publicados:
                ps = [p for p in pendencias if p.ativa(corte) and (col == TODAS or p.classe_risco == col)]
                tipo = linha[0]
                if tipo == "N":
                    reais[(linha, col)] = len(ps)
                elif tipo == "R":
                    reais[(linha, col)] = sum(analise.REGIAO_DA_UF.get(p.uf) == linha[1] for p in ps)
                elif tipo == "A":
                    reais[(linha, col)] = sum(p.atividade == linha[1] for p in ps)
                else:
                    reais[(linha, col)] = sum(p.uf == linha[1] for p in ps)
            escondidas = {c for c, v in publicados.items() if v is None}
            escondidas_vistas += len(escondidas)
            for c, v in publicados.items():
                if v is not None:
                    assert v == reais[c] and not 0 < v < 3, (ano, c, v)
            assert not analise.celulas_recompostas(reais, escondidas, equacoes), (ano, classe)
        # ---- motivo × classe: a grade nova
        grade = analise.contagens_motivo_classe(pendencias, corte)
        for m in {m.chave for m in d.motivos}:
            for c in (*classes, TODAS):
                grade.setdefault((m, c), 0)
        publicados = {}
        for m in d.motivos:
            publicados[(m.chave, classe or TODAS)] = m.ativas
            for c in cls:
                publicados[(m.chave, c)] = m.por_classe[c]
        for c in d.classes:
            publicados[(TODAS, c.chave)] = c.ativas
        publicados[(TODAS, classe or TODAS)] = d.nacional.ativas
        for c, v in publicados.items():
            if v is not None:
                assert v == grade[c] and not 0 < v < 3, (ano, classe, c, v)
        escondidas = {c for c, v in publicados.items() if v is None}
        escondidas_vistas += len([c for c, v in publicados.items() if v is None])
        if classe is None:
            assert not analise.celulas_recompostas(grade, escondidas), (ano, classe)
        # o total de cada motivo é o mesmo do resumo por motivo no corte de hoje (mesmo destino)
        if ano is None and classe is None:
            resumo = acervo.resumo_agregado(ANA_N1, 1)
            titulos, linhas = resumo.tabelas["POR MOTIVO DA PERMANENCIA"]
            no_resumo = {l[0]: l[list(titulos).index("PENDENCIAS")] for l in linhas}
            for m in d.motivos:
                if m.chave in no_resumo:
                    assert (m.ativas is None) == (no_resumo[m.chave] == analise.SUPRIMIDO), m.chave
    if pequeno:
        assert escondidas_vistas                                    # o acervo pequeno força supressão de fato


def test_proteger_grade_n1_fecha_a_recomposicao_que_a_regra_simples_deixaria():
    """Caso montado à mão: a margem do motivo a é publicada por outra vista (conhecida) e a única outra célula da
    linha seria a complementar natural; a prova algébrica obriga a esconder mais uma na coluna."""
    g = {("A", "x"): 2, ("A", "y"): 9, ("A", TODAS): 11, ("B", "x"): 5, ("B", "y"): 6, ("B", TODAS): 11,
         ("C", "x"): 7, ("C", "y"): 4, ("C", TODAS): 11, (TODAS, "x"): 14, (TODAS, "y"): 19, (TODAS, TODAS): 33}
    conhecidas = {("A", TODAS), ("B", TODAS), ("C", TODAS), (TODAS, "x"), (TODAS, "y"), (TODAS, TODAS)}
    escondidas = analise.proteger_grade_n1(g, 3, conhecidas)
    assert ("A", "x") in escondidas and not escondidas & conhecidas
    assert not analise.celulas_recompostas(g, escondidas)
    assert not [c for c in g if c not in escondidas and 0 < g[c] < 3]
    assert analise.proteger_grade_n1(g, 0, conhecidas) == set()              # N2 e N3: sem k
    assert analise.celulas_recompostas(g, {("A", "x")}) == {("A", "x")}    # sozinha, sairia por subtração


def test_painel_n1_pela_matriz_e_pela_trilha_e_sem_reais(tela):
    acervo = tela.app.acervo
    antes = len(_registros(tela))
    d = acervo.painel_n1(ANA_N1, 1)
    registros = _registros(tela)
    assert len(registros) == antes + 1 and registros[-1].evento.motivo == "PAINEL_N1"
    assert d.supressao_minima == 3 and acervo.painel_n1(CAIO_N3, 3).supressao_minima == 0
    from dataclasses import fields

    from ecosec.servicos import acervo as servico
    assert "R$" not in repr(d)
    for tipo in (servico.PainelN1, servico.GrupoN1, servico.ContagemN1, servico.IndicadorN1):
        assert not [f.name for f in fields(tipo) if "custo" in f.name or "valor_r" in f.name], tipo
    assert "custo" not in dict(d.pesos_pressao)
    with pytest.raises(Exception):
        acervo.painel_n1(ANA_N1, 1, classe="CLASSE INEXISTENTE")


def _registros(tela):
    return tela.app.acervo.trilha.repo.todos()


# ================================================================ filtro classe e ano
def test_ano_em_lista_com_todos_por_padrao(tela):
    """O ano (data de corte) numa lista, como a classe ao lado: "Todos" primeiro e escolhido (a situação
    atual), depois os anos anteriores em ordem decrescente. O ano corrente não entra (daria o mesmo que "Todos",
    ). A lista, o chip e o clique num ano do gráfico ficam sincronizados; o slider e o rótulo do ano
    saíram."""
    from PySide6.QtCore import QPoint

    pn = _abrir(tela)
    hoje, c = pn.panorama.hoje, pn.combo_ano
    primeiro = pn.panorama.serie["anos"][0]
    assert [c.itemText(i) for i in range(c.count())] == ["Todos", *[str(a) for a in range(hoje.year - 1,
                                                                                          primeiro - 1, -1)]]
    assert c.currentIndex() == 0 and pn.estado.ano == hoje.year and pn.estado_filtro.filtro.ano is None
    assert f"situação atual, em {hoje:%d/%m/%Y}" in c.toolTip()
    classe = pn.combo_classe.mapTo(pn, QPoint(0, 0))                   # "Classe [lista] · Ano [lista]", no topo
    ano = c.mapTo(pn, QPoint(0, 0))
    assert ano.x() > classe.x() + pn.combo_classe.width() and abs(ano.y() - classe.y()) <= 4
    c.setCurrentText("2015")
    _esperar()
    assert pn.estado.ano == 2015 and pn.panorama.ano == 2015 and pn.estado_filtro.filtro.ano == 2015
    assert "31/12/2015" in c.toolTip() and any(ch.dimensao == "ano" for ch in pn.barra.chips)
    pn.estado_filtro.definir(ano=None)                                  # remover o chip: a situação atual
    _esperar()
    assert c.currentText() == "Todos" and pn.estado.ano == hoje.year and pn.panorama.ano == hoje.year
    pn.estoque.clicado.emit(2020)                                       # clique num ano do gráfico
    _esperar()
    assert c.currentText() == "2020" and pn.estado.ano == 2020
    c.setCurrentText("Todos")
    _esperar()
    assert pn.estado.ano == hoje.year and pn.estado_filtro.filtro.ano is None
    assert not hasattr(pn, "slider") and not hasattr(pn, "rotulo_ano")


def test_filtro_de_classe_e_ano_propaga_para_todas_as_secoes(tela):
    pn = _abrir(tela)
    pn.combo_classe.setCurrentText(vocabulario.rotulo(RADIOATIVO))
    pn.combo_ano.setCurrentText("2015")
    _esperar()
    assert pn.estado.classe == RADIOATIVO and pn.estado.ano == 2015
    assert pn.estado_filtro.filtro.classes == {RADIOATIVO} and pn.estado_filtro.filtro.ano == 2015
    assert {c.dimensao for c in pn.barra.chips} == {"classes", "ano"}

    def conferir(classe, ano):
        for chave in ("n1", "classe", "uf"):
            assert pn.dados[chave].classe == classe and pn.dados[chave].ano == ano, chave
        assert pn.dados["encerramento"].classe == classe and pn.panorama.classe == classe and pn.panorama.ano == ano
        so = [classe] if classe else list(sinteticos.UNIDADE_DA_CLASSE)
        nomes = {vocabulario.rotulo(c) for c in so}
        _preparar(pn)
        # onde: regiões só com a classe; ranking na cor da classe
        assert all(set(r.por_classe) == set(so) for r in pn.dados["n1"].regioes)
        assert {n for l in pn.regioes.linhas for n, *_ in l["segmentos"]} <= nomes | {"Todas as classes"}
        # tipo: só o cartão da classe; heatmap com a coluna da classe
        assert [c for c, w in pn.cartoes_classe.items() if not w.isHidden()] == (
            [classe] if classe else list(pn.cartoes_classe))
        assert {n for n, _ in pn.regiao_classe.colunas} <= nomes | {"Total"}
        # motivos, resolução e prazo
        assert {n for n, _ in pn.motivo_classe.colunas} == nomes
        assert {s["chave"] for s in pn.estoque.series} == set(so)
        assert pn.estoque.marcado == ano
        assert {n for n, _ in pn.prazo_calor.colunas} <= nomes | {"Todas"}
        assert [l["chave"] for l in pn.prazo_classe.linhas if not l.get("referencia")] == so if classe else True
        recorte = (vocabulario.rotulo(classe) if classe else "Todas as classes") + f" · {ano}"
        assert recorte in pn.secoes["onde"].cartoes["regioes"].subtitulo.text()
        assert recorte in pn.secoes["tipo"].cartoes["atividades"].subtitulo.text()
    for chave in SECOES:                                            # navegar não perde o filtro
        pn.mostrar_secao(chave)
        conferir(RADIOATIVO, 2015)
    # clique numa classe (marca do gráfico) tira o filtro dela; clique num ano escolhe o ano
    pn.motivo_classe.clicado.emit(RADIOATIVO)
    _esperar()
    assert pn.estado.classe is None and not pn.estado_filtro.filtro.classes
    conferir(None, 2015)
    pn.estoque.clicado.emit(2020)
    _esperar()
    assert pn.estado.ano == 2020 and pn.combo_ano.currentText() == "2020" and pn.estado_filtro.filtro.ano == 2020
    conferir(None, 2020)
    pn.atividades.clicado.emit(CLASSE_I)
    _esperar()
    conferir(CLASSE_I, 2020)
    # nenhuma outra dimensão entra no N1
    pn.estado_filtro.definir(ufs={"SP"}, riscos={"CRITICO"})
    assert not pn.estado_filtro.filtro.ufs and not pn.estado_filtro.filtro.riscos
    # tirar os chips volta a todas as classes e ao ano corrente
    pn.estado_filtro.limpar()
    _esperar()
    assert pn.estado.classe is None and pn.estado.ano == HOJE.year
    conferir(None, HOJE.year)


def test_mapa_e_ranking_seguem_o_mesmo_indicador_e_a_mesma_uf(tela):
    from ecosec.interface.n1_painel import INDICADORES
    pn = _abrir(tela)
    for i, indicador in enumerate(INDICADORES):
        pn.combo_indicador.setCurrentIndex(i)
        _esperar(10)
        visiveis = [l for l in pn.ranking.linhas if l["valor"] is not None]
        assert [l["valor"] for l in visiveis] == sorted((l["valor"] for l in visiveis), reverse=True)
        for l in visiveis:
            assert l["valor"] == pn._valor_uf(l["chave"])
        assert indicador.lower() in pn.secoes["onde"].cartoes["ranking"].titulo.text().lower()
        assert indicador in pn.legenda.titulo.text()
    pn.estado.definir(foco="SP")
    assert [l["chave"] for l in pn.ranking.linhas if l.get("destaque")] == ["SP"]
    pn.ranking.clicado.emit(("UF", "RJ"))
    assert "RJ" in pn.estado.selecao
    pn.regioes.clicado.emit(("REGIAO", "SUL"))
    assert pn.estado.selecao == frozenset(analise.REGIOES["SUL"])
    pn.estado.definir(foco=None, selecao=frozenset())


# ================================================================ navegação do mapa do N1
def _barras(m) -> tuple[int, int]:
    return m.horizontalScrollBar().value(), m.verticalScrollBar().value()


def _arrastar(m, inicio, delta, passos=10):
    """Aperta em `inicio`, move em passos até `inicio + delta` e solta (o arrasto real, com o botão apertado)."""
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    QTest.mousePress(m.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, inicio)
    for i in range(1, passos + 1):
        QTest.mouseMove(m.viewport(), inicio + QPoint(delta.x() * i // passos, delta.y() * i // passos))
    QTest.mouseRelease(m.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, inicio + delta)
    _esperar(30)


def _dentro_da_uf(m, uf):
    """Um pixel do mapa em que o item de cima é a UF (o centro do retângulo pode cair fora do polígono)."""
    from PySide6.QtCore import QPoint
    caixa = m.mapFromScene(m.ufs[uf].boundingRect()).boundingRect()
    return next(p for y in range(caixa.top(), caixa.bottom(), 3) for x in range(caixa.left(), caixa.right(), 3)
                if m.itemAt(p := QPoint(x, y)) is m.ufs[uf])


def _roda(m, passos, modificadores, pagina):
    """A roda pela janela, num ponto do mapa à vista (QTest.wheelEvent: o caminho da roda real; no Qt 6 a roda
    enviada direto ao mapa não é espontânea e não sobe para a página). Espera a rolagem suave da página parar."""
    from PySide6.QtCore import QPoint, QPointF
    from PySide6.QtTest import QTest
    pos = m.viewport().mapTo(m.window(), m.viewport().visibleRegion().boundingRect().center())
    QTest.wheelEvent(m.window().windowHandle(), QPointF(pos), QPoint(0, 120 * passos), stateKey=modificadores)
    anterior = None
    for _ in range(40):
        _esperar(100)
        if pagina.value() == anterior:
            break
        anterior = pagina.value()


def test_mapa_do_n1_arrasta_sem_escolher_uf(tela):
    """O mapa do N1 arrasta (sai o NoDrag), no país inteiro e aproximado; o arrasto que começa numa UF move
    o mapa e não a escolhe."""
    from PySide6.QtCore import QPoint
    from PySide6.QtWidgets import QGraphicsView
    pn = _abrir(tela)
    m = pn.mapa
    assert m.dragMode() == QGraphicsView.DragMode.ScrollHandDrag
    assert m.aumento == pytest.approx(1.0, abs=0.05)
    inicio = _dentro_da_uf(m, "MT")
    antes = _barras(m)
    _arrastar(m, inicio, QPoint(150, 0))
    assert _barras(m)[0] == antes[0] - 150 and pn.estado.selecao == frozenset()
    m.aproximar(2.0)
    antes = _barras(m)
    _arrastar(m, m.viewport().rect().center(), QPoint(-60, 40))
    assert _barras(m) == (antes[0] + 60, antes[1] - 40) and pn.estado.selecao == frozenset()


def test_clique_na_uf_do_n1_escolhe_ao_soltar(tela):
    """Apertar numa UF não escolhe nada; soltar a até 4 px do aperto escolhe (e o segundo clique tira)."""
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    pn = _abrir(tela)
    m = pn.mapa
    pos = _dentro_da_uf(m, "SP")
    QTest.mousePress(m.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, pos)
    assert pn.estado.selecao == frozenset()                                        # apertar não escolhe
    QTest.mouseRelease(m.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, pos + QPoint(2, 2))
    _esperar(30)
    assert pn.estado.selecao == frozenset({"SP"})
    QTest.mouseClick(m.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, _dentro_da_uf(m, "SP"))
    _esperar(30)
    assert pn.estado.selecao == frozenset()


def test_roda_sozinha_rola_a_pagina_e_ctrl_roda_da_zoom(tela):
    """No N1 o mapa fica no meio de uma página que rola: a roda sozinha rola a página (o mapa não a rouba);
    Ctrl + roda dá zoom no mapa (convenção de mapa embutido). O texto de ajuda diz isso."""
    from PySide6.QtCore import Qt
    pn = _abrir(tela)
    m = pn.mapa
    pagina = pn._rolagens["onde"].verticalScrollBar()
    assert pagina.maximum() > 0
    pagina.setValue(0)
    z0 = m.aumento
    _roda(m, -1, Qt.KeyboardModifier.NoModifier, pagina)
    assert m.aumento == pytest.approx(z0) and pagina.value() > 0
    rolada = pagina.value()
    _roda(m, 1, Qt.KeyboardModifier.ControlModifier, pagina)
    assert m.aumento == pytest.approx(z0 * 1.25) and pagina.value() == rolada
    _roda(m, -1, Qt.KeyboardModifier.ControlModifier, pagina)
    assert m.aumento == pytest.approx(z0)
    assert "Ctrl + roda dá zoom; arrastar move o mapa" in m.accessibleDescription()
    assert "Roda do mouse" not in m.accessibleDescription()


def test_botoes_menos_mais_e_brasil_no_mapa_do_n1(tela):
    """− + e Brasil no cabeçalho do cartão do mapa, à direita do Indicador e na mesma linha, na mesma ordem
    do N2 e do N3; + e − aproximam e afastam (1,6×), Brasil volta à vista base (o país inteiro)."""
    from PySide6.QtCore import QPoint
    from PySide6.QtWidgets import QAbstractButton
    pn = _abrir(tela)
    m = pn.mapa
    cartao = pn.secoes["onde"].cartoes["mapa"]
    botoes = {b.text(): b for b in cartao.findChildren(QAbstractButton)
              if b.isVisible() and b.text() in ("−", "+", "Brasil", "UF")}
    assert set(botoes) == {"−", "+", "Brasil"}
    combo = pn.combo_indicador.mapTo(cartao, QPoint(0, 0))
    xs = []
    for texto in ("−", "+", "Brasil"):
        b = botoes[texto].mapTo(cartao, QPoint(0, 0))
        assert b.y() < combo.y() + pn.combo_indicador.height() and combo.y() < b.y() + botoes[texto].height()
        xs.append(b.x())
    assert combo.x() + pn.combo_indicador.width() <= xs[0] < xs[1] < xs[2]
    base = (m.aumento, _barras(m))
    botoes["+"].click()
    assert m.aumento == pytest.approx(base[0] * 1.6)
    botoes["−"].click()
    assert m.aumento == pytest.approx(base[0])
    m.aproximar(3.0)
    _arrastar(m, m.viewport().rect().center(), QPoint(80, 50))
    botoes["Brasil"].click()
    _esperar(30)
    assert m.aumento == pytest.approx(base[0]) and _barras(m) == base[1]


def test_cabecalho_do_mapa_do_n1_com_controles_numa_linha_abaixo_do_titulo(tela):
    """No cartão do mapa, Indicador + − + Brasil numa linha própria abaixo do título e do subtítulo; o
    subtítulo volta a caber em até 2 linhas (com os controles ao lado do título, eram 3)."""
    from PySide6.QtCore import QPoint
    pn = _abrir(tela)
    cartao = pn.secoes["onde"].cartoes["mapa"]
    sub = cartao.subtitulo
    assert round(sub.height() / sub.fontMetrics().lineSpacing()) <= 2
    fim_do_subtitulo = sub.mapTo(cartao, QPoint(0, sub.height())).y()
    assert pn.combo_indicador.mapTo(cartao, QPoint(0, 0)).y() >= fim_do_subtitulo


# ================================================================ prazo pelo cubo (k=3, parte e complemento)
def _prazo_publicado(acervo, ano):
    """O que o N1 publica no ano, em todos os filtros de classe: ativas e as duas subcontagens do prazo (além do
    prazo legal, prazo previsto vencido) por célula (linha, coluna); linha ("N",), ("R", região) ou ("U", uf)."""
    classes = list(quantidades.CLASSES)
    ativas, partes, corte = {}, {"alem": {}, "fora": {}}, None

    def pub(destino, celula, valor):
        assert destino.get(celula, valor) == valor, celula          # a mesma célula, o mesmo destino em todo filtro
        destino[celula] = valor
    for classe in (None, *classes):
        col, cls = classe or TODAS, [classe] if classe else classes
        d, pu = acervo.painel_n1(ANA_N1, 1, ano, classe), acervo.painel_uf(ANA_N1, 1, ano, classe)
        corte = d.corte
        for linha, gr in [(("N",), d.nacional)] + [(("R", r.chave), r) for r in d.regioes]:
            pub(ativas, (linha, col), gr.ativas)
            pub(partes["alem"], (linha, col), gr.alem_do_prazo)
            pub(partes["fora"], (linha, col), gr.fora_da_previsao)
            for c in cls:
                pub(ativas, (linha, c), gr.por_classe[c])
                pub(partes["alem"], (linha, c), gr.alem_por_classe[c])
        for c in d.classes:
            pub(ativas, (("N",), c.chave), c.ativas)
            pub(partes["alem"], (("N",), c.chave), c.alem_do_prazo)
            pub(partes["fora"], (("N",), c.chave), c.fora_da_previsao)
        for l in pu.linhas:
            pub(ativas, (("U", l.uf), col), None if l.suprimida else l.ativas)
            pub(partes["alem"], (("U", l.uf), col), None if l.suprimida else l.alem_do_prazo)
            pub(partes["fora"], (("U", l.uf), col), None if l.suprimida else l.fora_da_previsao)
    return corte, ativas, partes


def _prazo_real(acervo, corte):
    """As contagens reais (sem k) das mesmas células, contadas aqui a partir dos registros."""
    from collections import Counter

    from ecosec.acervo import regras
    r = acervo.regras or regras.ParametrosRegras.padrao()
    reais = {"ativas": Counter(), "alem": Counter(), "fora": Counter()}
    for p in acervo.repo.pendencias():
        if not p.ativa(corte):
            continue
        marcas = {"ativas": 1, "alem": int(regras.dias_alem_do_prazo_limite(p, corte, r) > 0),
                  "fora": int(p.vencida(corte))}
        for linha in (("N",), ("R", analise.REGIAO_DA_UF.get(p.uf)), ("U", p.uf)):
            for col in (p.classe_risco, TODAS):
                for nome, marca in marcas.items():
                    reais[nome][(linha, col)] += marca
    return reais


def _equacoes_publicadas(familia, celulas, classes):
    """As somas que o N1 deixa ver numa família de células: a linha soma as classes, a região soma as UFs e o
    Brasil soma as regiões (só as equações com todas as células publicadas, visíveis ou suprimidas)."""
    equacoes = []

    def eq(margem, partes):
        if margem in celulas and partes and all(p in celulas for p in partes):
            equacoes.append(((familia, margem), [(familia, p) for p in partes]))
    for linha in {cel[0] for cel in celulas}:
        eq((linha, TODAS), [(linha, c) for c in classes])
    for col in (*classes, TODAS):
        for r, ufs in analise.REGIOES.items():
            eq((("R", r), col), [(("U", uf), col) for uf in ufs])
        eq((("N",), col), [(("R", r), col) for r in analise.REGIOES])
    return equacoes


@pytest.mark.parametrize("pequeno", [False, True])
def test_prazo_do_n1_sai_do_cubo_com_k3_na_parte_e_no_complemento(tela, pequeno):
    """"Quanto está fora do prazo?" publica, por Brasil, região, classe e UF, o além do prazo legal e o prazo previsto
    vencido (as dicas escrevem "X de Y casos ativos"). Cada número visível é o real, nem ele nem o complemento
    (dentro do prazo) fica entre 0 e 3, e nenhuma célula suprimida (ativas, parte ou complemento) sai por soma ou
    subtração das que o N1 publica em qualquer filtro de classe (álgebra linear exata)."""
    if pequeno:
        _montar_pequeno(tela)
    acervo = tela.app.acervo
    classes = list(quantidades.CLASSES)
    suprimidas_vistas = 0
    for ano in (None, 2015):
        corte, ativas, partes = _prazo_publicado(acervo, ano)
        reais = _prazo_real(acervo, corte)
        for cel, v in ativas.items():
            if v is not None:
                assert v == reais["ativas"][cel] and not 0 < v < 3, (ano, cel, v)
        contagens = {("ativas", c): reais["ativas"][c] for c in ativas}
        escondidas = {("ativas", c) for c, v in ativas.items() if v is None}
        equacoes = _equacoes_publicadas("ativas", ativas, classes)
        for nome, publicadas in partes.items():
            resto = f"resto_{nome}"
            for cel, v in publicadas.items():
                total = ativas[cel]
                if v is not None:
                    assert total is not None, (ano, nome, cel)          # subcontagem visível só com o total visível
                    assert v == reais[nome][cel] and not 0 < v < 3, (ano, nome, cel, v)
                    assert not 0 < total - v < 3, (ano, nome, cel, total - v)        # complemento: dentro do prazo
                contagens[(nome, cel)] = reais[nome][cel]
                contagens[(resto, cel)] = reais["ativas"][cel] - reais[nome][cel]
                if v is None:
                    escondidas |= {(nome, cel), (resto, cel)}
                    suprimidas_vistas += 1
                elif total is None:
                    escondidas.add((resto, cel))
                equacoes.append((("ativas", cel), [(nome, cel), (resto, cel)]))   # ativas = parte + complemento
            equacoes += _equacoes_publicadas(nome, publicadas, classes)
        assert not analise.celulas_recompostas(contagens, escondidas, equacoes), ano
    if pequeno:
        assert suprimidas_vistas                                    # o acervo pequeno força supressão de fato


# ================================================================ tabela equivalente com Suprimido
def _suprimidas_do_grafico(gr, titulos) -> list[tuple[int, int]]:
    """(linha, coluna) da tabela equivalente onde o modelo do gráfico tem None (o que veio suprimido do serviço)."""
    from ecosec.interface import n1_graficos as g
    if isinstance(gr, g.MapaCalorN1):
        return [(i, 1 + j) for i, linha in enumerate(gr.celulas) for j, c in enumerate(linha) if c["valor"] is None]
    if isinstance(gr, g.HalteresN1):
        return [(i, j) for i, l in enumerate(gr.linhas) for j, lado in ((1, "a"), (2, "b")) if l[lado] is None]
    if isinstance(gr, g.Barras100N1):
        return [(i, 1 + j) for i, l in enumerate(gr.linhas) for j, (_, n) in enumerate(l["partes"]) if n is None] + [
            (i, len(gr.faixas) + 1) for i, l in enumerate(gr.linhas) if l["total"] is None]
    if isinstance(gr, g.ColunasN1):
        return [(i, 1) for i, item in enumerate(gr.itens) if item["valor"] is None]
    if isinstance(gr, g.LinhasN1):
        xs = sorted({x for s in gr.series for x, _ in s["pontos"]})
        if len(xs) > 60:                                            # a curva longa não tem tabela por ponto
            return []
        return [(xs.index(x), 1 + j) for j, s in enumerate(gr.series) for x, v in s["pontos"] if v is None]
    if isinstance(gr, g.BarrasN1):
        posicoes = []
        for i, l in enumerate(gr.linhas):
            if l.get("vazio"):
                continue
            if "dicas" not in l:                                    # ranking: [UF, valor]
                posicoes += [(i, 1)] if l["valor"] is None else []
                continue
            if l["valor"] is None:                                  # composta: total e % do total
                posicoes += [(i, titulos.index("Total")), (i, titulos.index("% do total"))]
            posicoes += [(i, titulos.index(n)) for n, dica in l["dicas"].items() if f": {g.SUPRIMIDO} " in dica]
        return posicoes
    return []


def test_tabela_equivalente_escreve_suprimido_onde_o_servico_mandou_none(tela):
    """No acervo pequeno, a tabela de cada gráfico (e a que a pessoa abre no botão "Ver tabela") escreve "Suprimido"
    em toda célula que o serviço mandou None: nunca 0, 0% nem vazio."""
    from ecosec.interface import n1_graficos as g
    _montar_pequeno(tela)
    pn = _abrir(tela)
    com_supressao = set()
    for i in range(pn.combo_indicador.count()):
        pn.combo_indicador.setCurrentIndex(i)
        _esperar(10)
        _preparar(pn)
        mapa = pn.secoes["onde"].cartoes["mapa"].grafico
        for chave, secao in pn.secoes.items():
            for nome, cartao in secao.cartoes.items():
                gr = cartao.grafico
                titulos, linhas = gr.tabela()
                if gr is mapa:
                    posicoes = [(j, 1) for j, uf in enumerate(sorted(pn.panorama.pressao)) if pn._valor_uf(uf) is None]
                else:
                    posicoes = _suprimidas_do_grafico(gr, list(titulos))
                for li, cj in posicoes:
                    assert linhas[li][cj] == g.SUPRIMIDO, (pn.combo_indicador.currentText(), chave, nome, linhas[li])
                if posicoes:
                    com_supressao.add(type(gr).__name__ if gr is not mapa else "mapa")
                cartao.alternar_tabela()
                aberta = [[cartao.tabela.item(r, c).text() for c in range(cartao.tabela.columnCount())]
                          for r in range(cartao.tabela.rowCount())]
                assert aberta == [[str(c) for c in l] for l in linhas], (chave, nome)
                cartao.alternar_tabela()
    # o acervo pequeno força supressão em cada tipo de gráfico que tem célula pequena
    assert {"mapa", "BarrasN1", "MapaCalorN1", "HalteresN1", "LinhasN1", "Barras100N1"} <= com_supressao


# ================================================================ nada financeiro em outros recortes
FINANCEIRO = ("custo estimado", "orçament", "orcament", "responsabilidade financeira", "em reais")


@pytest.mark.parametrize("pequeno, classe, ano", [(False, RADIOATIVO, 2015), (True, None, None),
                                                  (True, CLASSE_I, 2020)])
def test_nada_financeiro_com_supressao_e_com_filtro(tela, pequeno, classe, ano):
    """A varredura de "R$" e de termo financeiro em todo texto visível e em toda dica do painel, também no acervo
    pequeno (as notas de supressão entram nas dicas) e com filtro de classe e ano (subtítulos e recortes mudam)."""
    if pequeno:
        _montar_pequeno(tela)
    pn = _abrir(tela)
    if classe or ano:
        pn.combo_classe.setCurrentText(vocabulario.rotulo(classe) if classe else "Todas as classes")
        pn.combo_ano.setCurrentText(str(ano) if ano else "Todos")
        _esperar()
        assert pn.estado.classe == classe and pn.estado.ano == (ano or HOJE.year)
    for i in range(pn.combo_indicador.count()):
        pn.combo_indicador.setCurrentIndex(i)
        _esperar(10)
        _preparar(pn)
        tudo = "\n".join(_visiveis(pn) + _dicas(pn) + [r.toolTip() for r in pn.mapa.ufs.values()])
        for e in sinteticos.EVENTOS:
            tudo = tudo.replace(e.descricao, "").replace(e.rotulo, "")
        assert not DINHEIRO.search(tudo), (pn.combo_indicador.currentText(), "valor em reais no N1")
        texto = tudo.lower().replace("o custo estimado não entra", "").replace(      # os avisos de que não há
            "nenhum valor em reais entra na conta", "").replace("sem valores em reais", "")  # reais não contam
        assert not [t for t in FINANCEIRO if t in texto], pn.combo_indicador.currentText()
    assert "R$" not in repr(pn.dados) and "R$" not in repr(pn.panorama)
    assert all(item.custo is None for item in pn.panorama.pressao.values())


# ================================================================ pesos fixos por nível, em todo recorte
def test_pesos_do_indice_de_pressao_fixos_no_n1_e_completos_no_n3_em_todo_recorte(tela):
    """N1: 0,375 / 0,375 / 0,25 (volume / severidade / atraso), sem custo, em qualquer classe e ano. N3: os pesos
    completos de [indice_pressao] (config/ecosec.toml), 0,30 / 0,30 / 0,20 / 0,20, com custo."""
    from ecosec.interface.n1_painel import formula_pressao
    acervo = tela.app.acervo
    sem_custo = {"volume": 0.375, "severidade": 0.375, "atraso": 0.25}
    completos = {"volume": 0.30, "severidade": 0.30, "custo": 0.20, "atraso": 0.20}
    assert dict(acervo.pesos_pressao) == pytest.approx(completos)
    for ano, classe in ((None, None), (2015, None), (None, RADIOATIVO), (2020, CLASSE_I)):
        n1, n3 = acervo.panorama(ANA_N1, 1, ano, classe), acervo.panorama(CAIO_N3, 3, ano, classe)
        assert dict(n1.pesos) == pytest.approx(sem_custo) and set(dict(n1.pesos)) == set(sem_custo), (ano, classe)
        assert dict(n3.pesos) == pytest.approx(completos) and set(dict(n3.pesos)) == set(completos), (ano, classe)
        assert sum(dict(n1.pesos).values()) == pytest.approx(1) == sum(dict(n3.pesos).values())
        assert all(item.custo is None for item in n1.pressao.values())
        assert dict(acervo.painel_n1(ANA_N1, 1, ano, classe).pesos_pressao) == pytest.approx(sem_custo)
        assert dict(acervo.painel_n1(CAIO_N3, 3, ano, classe).pesos_pressao) == pytest.approx(completos)
    f1, f3 = formula_pressao(tuple(sem_custo.items())), formula_pressao(tuple(completos.items()))
    assert "Nível 1, sem custo" in f1 and "custo estimado" not in f1
    assert "Nível 1, sem custo" not in f3 and "custo estimado" in f3 and "0,2 ×" in f3 and "0,3 ×" in f3
    # a dica do mapa do N1, já filtrado, continua com os pesos sem custo
    pn = _abrir(tela)
    pn.combo_classe.setCurrentText(vocabulario.rotulo(CLASSE_I))
    pn.combo_ano.setCurrentText("2020")
    _esperar()
    pn.combo_indicador.setCurrentIndex(0)
    _esperar()
    assert dict(pn.panorama.pesos) == pytest.approx(sem_custo) and pn.panorama.classe == CLASSE_I
    dica = pn.mapa.toolTip()
    assert "Nível 1, sem custo" in dica and "0,375 × posição no volume" in dica and "0,25 × posição na fração além" in dica
    assert "custo estimado" not in dica and "R$" not in dica


# ================================================================ capturas
def test_capturas_do_n1(tela, tmp_path):
    """Capturas "depois" para a conferência visual: cada seção (tela e inteira), com o acervo do sistema e com o
    acervo pequeno que força supressão. Gravadas na pasta temporária do teste (antes, numa pasta fixa de uma
    máquina de desenvolvimento, o que fazia o teste falhar em qualquer outra)."""
    CAPTURAS = tmp_path / "capturas_n1"
    CAPTURAS.mkdir()
    arquivos = []
    for pequeno in (False, True):
        if pequeno:
            tela.encerrar()
            _montar_pequeno(tela)
        pn = _abrir(tela)
        prefixo = "depois_pequeno_" if pequeno else "depois_"
        for chave in SECOES:
            pn.mostrar_secao(chave)
            _esperar(150)
            caminho = CAPTURAS / f"{prefixo}{chave}_tela.png"
            assert tela.grab().save(str(caminho))
            arquivos.append(caminho)
            secao = pn.secoes[chave]
            secao.resize(1420, secao.sizeHint().height())
            _esperar(60)
            caminho = CAPTURAS / f"{prefixo}{chave}_inteiro.png"
            assert secao.grab().save(str(caminho))
            arquivos.append(caminho)
    assert all(a.stat().st_size > 10_000 for a in arquivos)
