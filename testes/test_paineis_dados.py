"""Dados dos quatro painéis temáticos do N1 e dos cartões de KPI (padrão SINIR+).

Segurança primeiro: no N1, nenhum número dos painéis sai com 0 < n < k nem com complemento
pequeno, e as margens não deixam deduzir uma célula escondida; o N3 recebe os números inteiros. O painel por UF lê
o mesmo cubo do panorama. A garantia hierárquica do resumo (risco registrado) vira teste que vale para
qualquer acervo, inclusive um montado à mão em que a supressão tabela a tabela deixava recompor a UF.
"""
from contextlib import contextmanager
from dataclasses import replace
from datetime import date, datetime, timedelta

import pytest

from ecosec.acervo import analise, custos, quantidades, regras, sinteticos
from ecosec.configuracao import carregar
from ecosec.dominio.entidades import Usuario
from ecosec.repositorios.memoria import RepositorioAcervoMemoria, RepositorioTrilhaMemoria
from ecosec.servicos.acervo import ErroAcervo, ServicoAcervo
from ecosec.servicos.trilha import ServicoTrilha

CFG = carregar()
HOJE = sinteticos.DATA_BASE
K = int(CFG["indice_pressao.supressao_minima"])
ANA_N1 = Usuario(matricula="ANA", nome="Ana", nivel=1, senha_hash="$2b$x", id=1)
BIA_N2 = Usuario(matricula="BIA", nome="Bia", nivel=2, senha_hash="$2b$x", id=2, uf="SP")
CAIO_N3 = Usuario(matricula="CAIO", nome="Caio", nivel=3, senha_hash="$2b$x", id=3)
CLASSES = tuple(quantidades.CLASSES)
FILTROS = (None,) + CLASSES
ANOS = range(2008, HOJE.year + 1)
TODAS = analise.TODAS


def _pequeno(n) -> bool:
    return n is not None and 0 < n < K


@pytest.fixture(scope="module")
def acervo():
    trilha = ServicoTrilha(RepositorioTrilhaMemoria())
    servico = ServicoAcervo.de_configuracao(CFG, RepositorioAcervoMemoria(), trilha, b"chave-teste",
                                            relogio=lambda: datetime(2026, 10, 1, 10, 0))
    servico.data_referencia = HOJE
    return servico


@contextmanager
def _acervo_montado(servico, pendencias):
    original = servico.repo._pendencias
    servico.repo._pendencias = list(pendencias)
    try:
        yield
    finally:
        servico.repo._pendencias = original


def _montar(servico, linhas, encerradas=()):
    """[(uf, atividade, classe, n)] ativas e [(uf, atividade, classe, anos até encerrar)] já encerradas, com
    idades variadas (para as faixas do KPI-04)."""
    base = {p.classe_risco: p for p in servico.repo.pendencias() if p.ativa(HOJE)}
    montado, i = [], 0
    for uf, atividade, classe, n in linhas:
        for _ in range(n):
            i += 1
            montado.append(replace(base[classe], codigo=f"M{i:04d}", uf=uf, atividade=atividade,
                                   data_encerramento=None, data_identificacao=HOJE - timedelta(days=97 * i % 9000)))
    for uf, atividade, classe, anos in encerradas:
        i += 1
        inicio = HOJE - timedelta(days=4000 + 31 * i)
        montado.append(replace(base[classe], codigo=f"M{i:04d}", uf=uf, atividade=atividade, data_identificacao=inicio,
                               data_encerramento=inicio + timedelta(days=round(anos * 365.25))))
    return montado


def _custo_n1_interno(servico, ano=None, classe=None, por="classe"):
    """O serviço recusa o painel de custo no N1. A proteção k=3 do custo
    (analise.proteger_custo) continua no código e é conferida aqui pelo cálculo interno, com o contexto do N1, para o
    caso de uma decisão futura reabrir algum agregado de custo a um nível com k."""
    return servico._dados_custo(servico._abrir_painel(ANA_N1, 1, "PAINEL_CUSTO", ano, classe), por)


def _atividades(servico, n):
    return sorted(a.codigo for a in servico.repo.atividades())[:n]


# contrato e trilha
def test_os_cinco_metodos_existem_registram_na_trilha_e_o_n1_so_tem_ano_e_classe(acervo):
    import inspect
    for nome in ("painel_classe", "painel_uf", "painel_custo", "kpis"):
        assert {"ano", "classe"} <= set(inspect.signature(getattr(acervo, nome)).parameters)
    assert set(inspect.signature(acervo.painel_encerramento).parameters) == {"usuario", "nivel", "classe"}
    acervo.painel_classe(ANA_N1, 1)
    acervo.painel_uf(ANA_N1, 1)
    with pytest.raises(ErroAcervo):
        acervo.painel_custo(ANA_N1, 1, por="rota")          # N1 sem dado financeiro (recusa na trilha)
    acervo.painel_custo(BIA_N2, 2, por="rota")
    acervo.painel_encerramento(ANA_N1, 1)
    acervo.kpis(ANA_N1, 1)
    motivos = {r.evento.motivo for r in acervo.trilha.recentes(10_000)}
    assert motivos >= {"PAINEL_CLASSE", "PAINEL_UF", "PAINEL_CUSTO", "PAINEL_ENCERRAMENTO", "KPIS",
                       "CUSTO_NO_NIVEL_1"}


def test_n1_nao_abre_painel_de_nivel_acima_nem_classe_inventada(acervo):
    with pytest.raises(ErroAcervo):
        acervo.painel_uf(ANA_N1, 3)                       # a matriz nega: nível acima do cadastro
    with pytest.raises(ErroAcervo):
        acervo.painel_classe(ANA_N1, 1, classe="CLASSE INVENTADA")
    with pytest.raises(ErroAcervo):
        acervo.painel_custo(ANA_N1, 1, por="responsavel")  # custo por responsável só no N3, em outra tela


def test_n2_ve_so_a_propria_uf_sem_k(acervo):
    painel = acervo.painel_uf(BIA_N2, 2)
    assert [l.uf for l in painel.linhas] == ["SP"] and painel.supressao_minima == 0
    real = sum(p.ativa(HOJE) for p in acervo.repo.pendencias("SP"))
    assert painel.linhas[0].ativas == painel.total.ativas == real


# nenhuma célula pequena no N1
def _confere_grade(escondida, real, eixos, contexto):
    """Grade com margens (TODAS): em cada linha e coluna, nunca uma só célula escondida não nula."""
    for i in range(eixos):
        grupos = {}
        for chave in real:
            grupos.setdefault(chave[:i] + chave[i + 1:], []).append(chave)
        for chaves in grupos.values():
            assert sum(escondida(c) and real[c] > 0 for c in chaves) != 1, (contexto, chaves)


def _confere_painel_classe(n1, n3, contexto):
    linhas1 = {l.classe: l for l in n1.linhas}
    linhas3 = {l.classe: l for l in n3.linhas}
    for c, l in linhas1.items():
        assert not _pequeno(l.ativas), (contexto, c)
        assert all(not _pequeno(v) for v in l.envelhecimento.values()), (contexto, c)
        assert (l.quantidade is None) == (l.ativas is None), (contexto, c)
        if l.ativas is not None:
            assert l.ativas == linhas3[c].ativas and l.quantidade == linhas3[c].quantidade
    assert not _pequeno(n1.total_ativas)
    assert all(not _pequeno(v) for v in n1.envelhecimento_total.values())
    if n1.classe is None:                                  # a grade inteira: classe × faixa, com as margens
        real, escondidas = {}, set()
        for c in list(linhas3) + [TODAS]:
            l3 = linhas3.get(c)
            l1 = linhas1.get(c)
            env3 = l3.envelhecimento if l3 else n3.envelhecimento_total
            env1 = l1.envelhecimento if l1 else n1.envelhecimento_total
            for f in n1.faixas:
                real[(c, f)] = env3[f]
                if env1[f] is None:
                    escondidas.add((c, f))
            real[(c, TODAS)] = l3.ativas if l3 else n3.total_ativas
            if (l1.ativas if l1 else n1.total_ativas) is None:
                escondidas.add((c, TODAS))
        _confere_grade(lambda x: x in escondidas, real, 2, contexto)


def _confere_painel_uf(n1, n3, contexto):
    reais = {l.uf: l for l in n3.linhas + (n3.total,)}
    for l in n1.linhas + (n1.total,):
        r = reais[l.uf]
        assert not _pequeno(l.ativas), (contexto, l.uf)
        for parte, real in ((l.alem_do_prazo, r.alem_do_prazo), (l.fora_da_previsao, r.fora_da_previsao)):
            if parte is not None:
                assert parte == real and not _pequeno(parte) and not _pequeno(r.ativas - parte), (contexto, l.uf)
        if l.ativas is not None:
            assert l.ativas == r.ativas
    escondidas = [l for l in n1.linhas if l.ativas is None and reais[l.uf].ativas]
    assert len(escondidas) != 1, contexto                  # o total nacional está na mesma tela


def _confere_painel_custo(n1, n3, contagens, contexto):
    recorte = n1.classe or TODAS
    for l in n1.linhas:
        chave = (l.grupo, TODAS) if n1.por == "classe" else (recorte, l.grupo)
        assert not _pequeno(l.pendencias), (contexto, l.grupo)
        assert (l.custo is None) == (l.pendencias is None)
        for cat, v in l.por_categoria.items():
            if v is not None:
                assert not _pequeno(contagens.get(chave + (cat,), 0)), (contexto, l.grupo, cat)
    reais = {l.grupo: l for l in n3.linhas}
    escondidos = [l for l in n1.linhas if l.custo is None and reais[l.grupo].custo]
    assert len(escondidos) != 1, contexto                  # complementar pela margem do total
    for cat in custos.CATEGORIAS_EEA:
        col = [l for l in n1.linhas if l.por_categoria[cat] is None and reais[l.grupo].por_categoria[cat]]
        assert len(col) != 1, (contexto, cat)
    partes = [g for g, v in n1.por_responsabilidade.items() if v is None and n3.por_responsabilidade[g]]
    assert len(partes) != 1, contexto


@pytest.mark.parametrize("classe", FILTROS)
def test_painel_classe_n1_sem_celula_pequena_e_n3_inteiro(acervo, classe):
    for ano in ANOS:
        n1, n3 = acervo.painel_classe(ANA_N1, 1, ano, classe), acervo.painel_classe(CAIO_N3, 3, ano, classe)
        _confere_painel_classe(n1, n3, (ano, classe))
        assert n3.supressao_minima == 0 and n3.total_ativas is not None
        assert all(l.ativas is not None and None not in l.envelhecimento.values() for l in n3.linhas)


@pytest.mark.parametrize("classe", FILTROS)
def test_painel_uf_n1_sem_celula_nem_complemento_pequeno_e_n3_inteiro(acervo, classe):
    for ano in ANOS:
        n1, n3 = acervo.painel_uf(ANA_N1, 1, ano, classe), acervo.painel_uf(CAIO_N3, 3, ano, classe)
        _confere_painel_uf(n1, n3, (ano, classe))
        assert all(l.ativas is not None and l.alem_do_prazo is not None and l.fora_da_previsao is not None
                   and not l.suprimida for l in n3.linhas)


@pytest.mark.parametrize("por", ("classe", "rota"))
def test_painel_custo_n1_sem_grupo_pequeno_e_n3_inteiro(acervo, por):
    for ano in (2008, 2012, 2018, HOJE.year):
        contagens = analise.custo_do_passivo(acervo.repo.pendencias(), min(date(ano, 12, 31), HOJE),
                                             acervo.regras).contagens
        for classe in FILTROS:
            n1 = _custo_n1_interno(acervo, ano, classe, por)
            n3 = acervo.painel_custo(CAIO_N3, 3, ano, classe, por)
            _confere_painel_custo(n1, n3, contagens, (ano, classe, por))
            assert n3.total is not None and all(l.custo is not None for l in n3.linhas)
            assert None not in n3.por_responsabilidade.values()


@pytest.mark.parametrize("classe", FILTROS)
def test_painel_encerramento_n1_tabua_sem_degrau_pequeno_e_n3_curva_exata(acervo, classe):
    n1, n3 = acervo.painel_encerramento(ANA_N1, 1, classe), acervo.painel_encerramento(CAIO_N3, 3, classe)
    assert not n1.exata and n3.exata
    for c, curva in n1.curvas.items():
        assert not curva.exata and curva.eventos is None
        assert all(iv.eventos >= K and iv.em_risco >= K for iv in curva.intervalos), (classe, c)
        assert [t for t, _ in curva.pontos] == ([0.0] + [iv.fim for iv in curva.intervalos] if curva.intervalos
                                                 else [])
    for c, curva in n3.curvas.items():
        assert curva.exata and curva.eventos is not None and not curva.intervalos
    for t in n1.taxa_anual:
        assert not _pequeno(t.saidas) and not _pequeno(t.ativas_1_jan), (classe, t)
    assert all(t.saidas is not None and t.ativas_1_jan is not None for t in n3.taxa_anual)


def test_acervo_pequeno_montado_a_mao_nenhuma_funcao_nova_mostra_celula_pequena(acervo):
    """Um acervo com várias células de 1 e 2: tudo o que sai no N1 está suprimido ou é >= k (e o complemento das
    subcontagens também); o N3, com os mesmos dados, mostra tudo."""
    ag = _atividades(acervo, 3)
    ci, area, rej = CLASSES
    linhas = [("SP", ag[0], ci, 7), ("SP", ag[1], area, 5), ("SP", ag[2], rej, 1), ("RJ", ag[0], ci, 4),
              ("RJ", ag[1], rej, 2), ("MG", ag[0], area, 6), ("MG", ag[2], ci, 2), ("PR", ag[0], ci, 1),
              ("SC", ag[1], area, 3), ("BA", ag[2], rej, 4), ("BA", ag[0], area, 2)]
    encerradas = [("SP", ag[0], ci, a) for a in (0.4, 0.8, 1.3, 1.7, 2.2, 2.9, 3.4, 5.1)] + \
                 [("RJ", ag[1], area, a) for a in (1.2, 4.5)] + [("MG", ag[2], rej, 0.7)]
    with _acervo_montado(acervo, _montar(acervo, linhas, encerradas)):
        contagens = analise.custo_do_passivo(acervo.repo.pendencias(), HOJE, acervo.regras).contagens
        for classe in FILTROS:
            _confere_painel_classe(acervo.painel_classe(ANA_N1, 1, None, classe),
                                   acervo.painel_classe(CAIO_N3, 3, None, classe), classe)
            _confere_painel_uf(acervo.painel_uf(ANA_N1, 1, None, classe), acervo.painel_uf(CAIO_N3, 3, None, classe),
                               classe)
            for por in ("classe", "rota"):
                _confere_painel_custo(_custo_n1_interno(acervo, None, classe, por),
                                      acervo.painel_custo(CAIO_N3, 3, None, classe, por), contagens, (classe, por))
            enc = acervo.painel_encerramento(ANA_N1, 1, classe)
            for curva in enc.curvas.values():
                assert all(iv.eventos >= K and iv.em_risco >= K for iv in curva.intervalos)
            assert all(not _pequeno(t.saidas) and not _pequeno(t.ativas_1_jan) for t in enc.taxa_anual)
            for kpi in acervo.kpis(ANA_N1, 1, None, classe):
                assert kpi.fonte and kpi.corte == HOJE
        uf = acervo.painel_uf(ANA_N1, 1)
        assert any(l.suprimida for l in uf.linhas)          # o caso exercita a supressão de fato
        assert {l.uf: l.ativas for l in uf.linhas}["PR"] is None


# painel por UF = panorama
@pytest.mark.parametrize("classe", FILTROS)
def test_painel_uf_coerente_com_o_panorama_em_todos_os_anos(acervo, classe):
    for ano in ANOS:
        for usuario, nivel in ((ANA_N1, 1), (CAIO_N3, 3)):
            painel = acervo.painel_uf(usuario, nivel, ano, classe)
            panorama = acervo.panorama(usuario, nivel, ano, classe)
            assert painel.corte == min(date(ano, 12, 31), HOJE)
            for l in painel.linhas:
                item = panorama.pressao[l.uf]
                assert l.suprimida == item.suprimida, (ano, classe, l.uf)
                if not l.suprimida:
                    assert l.ativas == item.ativas and l.alem_do_prazo == item.vencidas, (ano, classe, l.uf)
                else:
                    assert l.ativas is None and l.alem_do_prazo is None and l.fora_da_previsao is None
            if classe:                                      # o total da classe: o mesmo número das barras
                assert panorama.totais_classe.get(classe, 0) == (painel.total.ativas or 0) or \
                    panorama.totais_classe.get(classe) is None is painel.total.ativas


def test_kpi03b_no_n1_agregado_bate_com_o_catalogo(acervo):
    total = acervo.painel_uf(ANA_N1, 1).total
    assert (total.ativas, total.alem_do_prazo, total.fora_da_previsao) == (1028, 929, 833)


# custo por categoria EEA
def test_todo_componente_das_rotas_tem_categoria_eea():
    c = regras.ParametrosRegras.padrao().custos
    nomes = custos.componentes_das_rotas(c.rotas)
    assert nomes and nomes <= set(c.categoria_componente)
    assert set(c.categoria_componente.values()) <= set(custos.CATEGORIAS_EEA)
    assert c.categoria_componente["MONITORAMENTO"] == "MONITORAMENTO"
    assert c.categoria_componente["INVESTIGACAO DETALHADA E AVALIACAO DE RISCO"] == "INVESTIGACAO"
    assert c.categoria_componente["TRANSPORTE DE PRODUTO PERIGOSO"] == "DISPOSICAO"


def test_componente_sem_categoria_e_recusado_na_carga():
    class Cfg:
        def secao(self, _):
            return {"data_base_valores": "2026-10", "densidade_solo_t_por_m3": 1.8, "rota_padrao": {"X": "R"},
                    "rotas": {"R": {"variaveis": [["A", 1.0], ["B", 2.0]], "fonte": "PARAMETRO"}},
                    "categoria_componente": {"A": "DISPOSICAO"}}
    with pytest.raises(ValueError, match="sem categoria"):
        custos.ParametrosCustos.de_configuracao(Cfg())


def test_soma_das_categorias_de_cada_pendencia_e_o_custo_estimado(acervo):
    r = acervo.regras
    for p in acervo.repo.pendencias():
        partes = custos.por_categoria(p, r.custos)
        assert set(partes) == set(custos.CATEGORIAS_EEA)
        assert sum(partes.values()) == pytest.approx(regras.custo_estimado(p, r), abs=0.005), p.codigo
        assert all(x.categoria in custos.CATEGORIAS_EEA for x in regras.memoria_de_calculo(p, r))


@pytest.mark.parametrize("por", ("classe", "rota"))
def test_partes_do_custo_somam_o_total(acervo, por):
    for classe in FILTROS:
        painel = acervo.painel_custo(CAIO_N3, 3, None, classe, por)
        assert sum(painel.por_responsabilidade.values()) == pytest.approx(painel.total, abs=1e5)
        assert sum(painel.por_categoria.values()) == pytest.approx(painel.total, abs=1e5)
        assert sum(l.custo for l in painel.linhas) == pytest.approx(painel.total, abs=1e5)
        for l in painel.linhas:
            assert sum(l.por_categoria.values()) == pytest.approx(l.custo, abs=1e5)
    n1 = _custo_n1_interno(acervo, por=por)
    assert sum(n1.por_responsabilidade.values()) == pytest.approx(n1.total, abs=1e5)   # 4 partes visíveis nos dados
    # Era R$ 1.958,6 mi; o novo sorteio subiu o custo em 14,9% (catálogo de KPIs, KPI-05)
    assert n1.total == pytest.approx(2250.4e6, abs=0.1e6) and n1.data_base == "2026-10" and n1.fonte == "PARAMETRO"


# KPI-01: tábua de vida e Kaplan-Meier
# 10 casos: 5 encerrados cedo, 5 ainda ativos aos 4 anos. A média (e a mediana) só das encerradas diz 1,9 (1,6);
# o Kaplan-Meier, que conta as censuradas, chega a 50% só aos 3,5 anos.
CASO = [(0.5, True, 0.0), (1.5, True, 0.0), (1.6, True, 0.0), (2.5, True, 0.0), (3.5, True, 0.0)] + \
       [(4.0, False, 0.0)] * 5


def test_km_com_censura_diverge_da_media_ingenua():
    encerradas = sorted(t for t, e, _ in CASO if e)
    assert sum(encerradas) / len(encerradas) == pytest.approx(1.92)
    curva = analise.kaplan_meier(CASO)
    assert [round(s, 2) for _, s in curva] == [0.9, 0.8, 0.7, 0.6, 0.5]
    assert analise._primeiro_abaixo(curva, 0.5) == 3.5 != encerradas[len(encerradas) // 2]


def test_tabua_de_vida_junta_degraus_pequenos_e_para_sem_gente_em_risco():
    tabua = analise.tabua_de_vida(CASO, 3)
    # (0, 1] tem 1 evento: junta com (1, 2] (2 eventos); (2, 3] e (3, 4] têm 1 cada: sobram e entram no último
    # degrau; em 4 ninguém mais está em risco
    assert [(iv.inicio, iv.fim, iv.eventos) for iv in tabua] == [(0.0, 4.0, 5)]
    assert all(iv.eventos >= 3 and iv.em_risco >= 3 for iv in tabua)
    assert tabua[-1].sobrevivencia == pytest.approx(0.5)
    assert analise.quantil_da_tabua(tabua, 0.5) == 4.0 and analise.quantil_da_tabua(tabua, 0.1) is None
    dobro = [(t, e, x) for t, e, x in CASO for _ in range(2)]          # com o dobro, cada ano tem gente bastante
    assert [(iv.inicio, iv.fim) for iv in analise.tabua_de_vida(dobro, 3)] == [(0.0, 2.0), (2.0, 4.0)]
    assert analise.tabua_de_vida(CASO, 0)[0].eventos == 1               # sem k: um degrau por ano com evento


def test_tabua_com_entrada_tardia_conta_o_risco_so_depois_da_entrada():
    # três herdados entram na observação aos 5 anos: antes disso, não estão em risco
    obs = [(6.0, True, 5.0), (6.5, True, 5.0), (7.0, True, 5.0)] + [(t, True, 0.0) for t in (0.2, 0.4, 0.6)] + \
          [(9.0, False, 0.0)] * 3
    tabua = analise.tabua_de_vida(obs, 3)
    # em (0, 1]: 6 no início, 4 no último evento; os herdados (que entram aos 5) não contam
    assert tabua[0].em_risco == 4 and tabua[0].eventos == 3
    assert all(iv.em_risco >= 3 for iv in tabua)


def test_curva_n1_da_classe_e_a_mesma_com_e_sem_filtro_e_o_total_usa_cortes_comuns(acervo):
    todas = acervo.painel_encerramento(ANA_N1, 1).curvas
    for c in CLASSES:
        assert acervo.painel_encerramento(ANA_N1, 1, c).curvas[c] == todas[c]
    comuns = set.intersection(*({0.0} | {iv.fim for iv in todas[c].intervalos} for c in CLASSES))
    assert {iv.fim for iv in todas[TODAS].intervalos} <= comuns
    assert todas[TODAS].mediana == pytest.approx(8.6, abs=0.3)          # catálogo: total 8,6 anos


# KPI-02 e cartões
def test_kpi02_marca_o_ano_corrente_como_parcial_e_bate_com_o_catalogo(acervo):
    taxa = {t.ano: t for t in acervo.painel_encerramento(ANA_N1, 1).taxa_anual}
    assert taxa[HOJE.year].parcial and not any(t.parcial for a, t in taxa.items() if a != HOJE.year)
    # Eram (86, 1.032, 8,3) e (56, 1.050, 5,3); o catálogo de KPIs foi atualizado junto
    assert (taxa[2024].saidas, taxa[2024].ativas_1_jan, taxa[2024].percentual) == (89, 1008, 8.8)
    assert (taxa[2026].saidas, taxa[2026].ativas_1_jan, taxa[2026].percentual) == (60, 1025, 5.9)


def test_saldo_do_panorama_e_kpi02_tem_o_mesmo_destino_por_classe_e_ano(acervo):
    for classe in FILTROS:
        serie = acervo.panorama(ANA_N1, 1, classe=classe).serie
        taxa = {t.ano: t for t in acervo.painel_encerramento(ANA_N1, 1, classe).taxa_anual}
        assert "acumulado" not in serie                      # a diferença do acumulado revelaria a entrada
        for a in serie["anos"]:
            assert (serie["saidas"][a] is None) == (taxa[a].saidas is None), (classe, a)


def test_fluxo_escondido_numa_classe_tem_complementar_no_ano(acervo):
    n1 = {c: acervo.panorama(ANA_N1, 1, classe=c).serie for c in FILTROS}
    n3 = {c: acervo.panorama(CAIO_N3, 3, classe=c).serie for c in FILTROS}
    for a in n1[None]["anos"]:
        for medida in ("entradas", "saidas"):
            escondidas = [c for c in FILTROS if n1[c][medida][a] is None and n3[c][medida][a]]
            assert len(escondidas) != 1, (a, medida)        # total do ano menos as classes visíveis


@pytest.mark.parametrize("usuario,nivel", ((ANA_N1, 1), (CAIO_N3, 3)))
def test_kpis_com_fonte_nivel_e_corte(acervo, usuario, nivel):
    funcoes = {"analise": analise, "custos": custos}
    for classe in FILTROS:
        for ano in (2015, None):
            lista = acervo.kpis(usuario, nivel, ano, classe)
            # o N1 não recebe o KPI-05 (custo), de nível mínimo 2
            assert [k.id for k in lista] == ["KPI-01", "KPI-02", "KPI-03", "KPI-03b", "KPI-04"] + (
                ["KPI-05"] if nivel > 1 else [])
            for k in lista:
                modulo, funcao = k.fonte.split(".")
                assert hasattr(funcoes[modulo], funcao), k.fonte
                assert k.nivel_minimo == (2 if k.id == "KPI-05" else 1)
                assert k.corte == min(date(ano or HOJE.year, 12, 31), HOJE)
                assert k.nome and k.unidade and k.observacao and "—" not in k.observacao + k.nome
                if nivel == 3 and k.id != "KPI-01":
                    assert k.valor is not None, (classe, ano, k.id)
    cartoes = {k.id: k for k in acervo.kpis(usuario, nivel)}
    # Eram 90,6; 82,7; 8,6 e 7,8
    assert cartoes["KPI-03"].valor == pytest.approx(90.4) and cartoes["KPI-03b"].valor == pytest.approx(81.0)
    assert cartoes["KPI-04"].valor == pytest.approx(8.0) and cartoes["KPI-02"].valor == pytest.approx(8.3)


# garantia hierárquica do resumo
def _celulas(tabelas):
    """{(agrupamento, chave): {coluna: valor}} das tabelas da família POR UF / REGIAO / ATIVIDADE / UF E ATIVIDADE."""
    saida = {}
    for g in analise.FAMILIA_UF:
        titulos, linhas = tabelas[g]
        n = list(titulos).index("PENDENCIAS")
        for l in linhas:
            saida[(g, tuple(l[:n]))] = dict(zip(titulos[n:], l[n:]))
    return saida


def _total_conhecido(tabelas):
    """(coluna, lado) -> o N1 deduz o total do escopo? Sim se alguma tabela do resumo tem a coluna inteira visível
    (o total é a soma das linhas); o complemento de uma subcontagem pede também a contagem inteira visível."""
    def visivel(coluna):
        for titulos, linhas in tabelas.values():
            i = list(titulos).index(coluna)
            if all(l[i] != analise.SUPRIMIDO for l in linhas):
                return True
        return False
    return lambda coluna, lado: visivel(coluna) and (lado == "PARTE" or visivel("PENDENCIAS"))


def _recomposicoes(protegido, real, total, conhecido=lambda coluna, lado: True):
    """Células escondidas que saem somando ou subtraindo as visíveis de outra tabela da família (ou do total).

    Para cada equação (a UF = suas linhas de UF e atividade; a região = suas UFs; a região = suas linhas de UF e
    atividade; a atividade = sua coluna; cada tabela = o total) e cada coluna (contagem, cada subcontagem e o seu
    complemento, cada quantidade por classe): se uma só célula não nula está escondida, ela é recomposta."""
    uf, regiao, atividade, uf_atividade = analise.FAMILIA_UF
    equacoes = []
    for g in analise.FAMILIA_UF:
        equacoes.append((("TOTAL", ()), [c for c in real if c[0] == g]))
    for c in real:
        if c[0] == uf:
            equacoes.append((c, [x for x in real if x[0] == uf_atividade and x[1][0] == c[1][0]]))
        if c[0] == regiao:
            equacoes.append((c, [x for x in real if x[0] == uf and analise.REGIAO_DA_UF.get(x[1][0]) == c[1][0]]))
            equacoes.append((c, [x for x in real if x[0] == uf_atividade
                                 and analise.REGIAO_DA_UF.get(x[1][0]) == c[1][0]]))
        if c[0] == atividade:
            equacoes.append((c, [x for x in real if x[0] == uf_atividade and x[1][1] == c[1][0]]))
    colunas = ["PENDENCIAS", *analise.SUBCONTAGENS, *analise.COLUNA_DA_CLASSE.values()]
    achados = []
    for coluna in colunas:
        lados = [("PARTE", lambda v, n: v)]
        if coluna in analise.SUBCONTAGENS:
            lados.append(("RESTO", lambda v, n: n - v))
        for lado, valor in lados:
            def escondida(c):
                if c == ("TOTAL", ()):
                    return not conhecido(coluna, lado)
                return protegido[c][coluna] == analise.SUPRIMIDO

            def real_de(c):
                if c == ("TOTAL", ()):
                    return total[coluna] if lado == "PARTE" else total["PENDENCIAS"] - total[coluna]
                return valor(real[c][coluna], real[c]["PENDENCIAS"])
            for pai, filhos in equacoes:
                if not filhos:
                    continue
                ocultas = [c for c in [pai] + filhos if escondida(c) and real_de(c)]
                if len(ocultas) == 1:
                    achados.append((coluna, lado, pai, ocultas[0]))
    return achados


def _resumos(servico):
    """(protegido do N1, real do N3, total real por coluna, o N1 conhece o total?)."""
    tabelas_n1 = servico.resumo_agregado(ANA_N1, 1).tabelas
    protegido = _celulas(tabelas_n1)
    tabelas_n3 = servico.resumo_agregado(CAIO_N3, 3).tabelas
    real = _celulas(tabelas_n3)
    titulos, linhas = tabelas_n3["POR UF"]
    total = {t: sum(l[i] for l in linhas) for i, t in enumerate(titulos) if t not in ("UF",)
             and all(isinstance(l[i], (int, float)) for l in linhas)}
    return protegido, real, total, _total_conhecido(tabelas_n1)


def _acervo_da_recomposicao(servico):
    """PR com 1 pendência (primária) e SC com 3, todas de uma atividade só: a complementar da região esconde SC no
    POR UF, e a linha (SC, atividade) = 3 ficava visível no POR UF E ATIVIDADE."""
    ag = _atividades(servico, 3)
    ci = CLASSES[0]
    return _montar(servico, [("SP", ag[0], ci, 6), ("SP", ag[1], ci, 6), ("RJ", ag[0], ci, 5), ("RJ", ag[2], ci, 5),
                             ("PR", ag[0], ci, 1), ("SC", ag[1], ci, 3)])


def test_acervo_montado_a_mao_a_supressao_tabela_a_tabela_deixava_recompor_a_uf(acervo):
    """O risco registrado existe: protegendo cada tabela sozinha (o método anterior), a UF escondida sai
    somando as linhas de UF e atividade."""
    with _acervo_montado(acervo, _acervo_da_recomposicao(acervo)):
        pendencias = regras.ativas(acervo.repo.pendencias(), HOJE)
        atividades = {a.codigo: a for a in acervo.repo.atividades()}
        motivos = {m.codigo: m for m in acervo.repo.motivos()}
        cubo = analise.proteger_cubo(pendencias, analise.REGIAO_DA_UF, HOJE, K, acervo.regras)
        antigas = {}
        for g in analise.AGRUPAMENTOS:
            titulos, linhas = analise.agregar(pendencias, HOJE, g, atividades, motivos, acervo.regras)
            por_classe = analise.contagens_por_classe(pendencias, HOJE, g, atividades, motivos, acervo.regras)
            antigas[g] = (titulos, analise.suprimir_tabela(g, titulos, linhas, K, por_classe,
                                                           cubo.iniciais_do_resumo() if g == "POR UF" else None)[0])
        _, real, total, _ = _resumos(acervo)
        achados = _recomposicoes(_celulas(antigas), real, total, _total_conhecido(antigas))
        assert ("PENDENCIAS", "PARTE", ("POR UF", ("SC",)), ("POR UF", ("SC",))) in achados
        assert _celulas(antigas)[("POR UF E ATIVIDADE", ("SC", _atividades(acervo, 3)[1]))]["PENDENCIAS"] == 3


def test_acervo_montado_a_mao_o_resumo_protegido_nao_deixa_recompor(acervo):
    with _acervo_montado(acervo, _acervo_da_recomposicao(acervo)):
        protegido, real, total, conhecido = _resumos(acervo)
        assert protegido[("POR UF", ("SC",))]["PENDENCIAS"] == analise.SUPRIMIDO
        assert protegido[("POR UF E ATIVIDADE", ("SC", _atividades(acervo, 3)[1]))]["PENDENCIAS"] == analise.SUPRIMIDO
        assert _recomposicoes(protegido, real, total, conhecido) == []
        # o mapa continua com o mesmo destino da UF
        pressao = acervo.panorama(ANA_N1, 1).pressao
        assert all(pressao[uf].suprimida == (protegido[("POR UF", (uf,))]["PENDENCIAS"] == analise.SUPRIMIDO)
                   for (g, (uf, *_)) in protegido if g == "POR UF")


def test_dados_reais_o_resumo_protegido_nao_deixa_recompor(acervo):
    protegido, real, total, conhecido = _resumos(acervo)
    assert conhecido("PENDENCIAS", "PARTE")
    assert _recomposicoes(protegido, real, total, conhecido) == []


def test_acervo_pequeno_variado_o_resumo_protegido_nao_deixa_recompor(acervo):
    ag = _atividades(acervo, 4)
    ci, area, rej = CLASSES
    linhas = [("SP", ag[0], ci, 4), ("SP", ag[1], area, 2), ("SP", ag[3], rej, 3), ("RJ", ag[1], ci, 1),
              ("RJ", ag[2], area, 5), ("ES", ag[2], rej, 2), ("MG", ag[3], ci, 3), ("PR", ag[0], area, 2),
              ("RS", ag[0], ci, 4), ("SC", ag[1], rej, 1), ("BA", ag[2], ci, 6), ("PE", ag[3], area, 1),
              ("AM", ag[0], rej, 3), ("PA", ag[1], ci, 2)]
    with _acervo_montado(acervo, _montar(acervo, linhas)):
        protegido, real, total, conhecido = _resumos(acervo)
        assert _recomposicoes(protegido, real, total, conhecido) == []
        assert any(v["PENDENCIAS"] == analise.SUPRIMIDO for v in protegido.values())
