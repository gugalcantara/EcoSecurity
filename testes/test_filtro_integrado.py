"""O filtro único ligado em todas as telas.

N2 e N3: um só EstadoFiltro (PainelAnalitico.estado) para mapa, planilha, gráfico de risco, árvore de custódia,
resumo e cabeçalho; os combos são vistas do estado e a BarraFiltros acima das abas mostra os chips e a contagem.
N1: só classe e ano (as dimensões que o cubo protege), ligados ao EstadoN1 nos dois sentidos; o resumo do N1
não aceita filtro no serviço.
"""
import random
from datetime import date

import pytest

from ecosec.acervo import sinteticos, vocabulario
from ecosec.acervo.filtro import Filtro
from ecosec.dominio.entidades import Usuario
from ecosec.dominio.niveis import Nivel

ANA_N1 = Usuario(matricula="ANA", nome="Ana", nivel=1, senha_hash="$2b$x", id=1)
BIA_N2 = Usuario(matricula="BIA", nome="Bia", nivel=2, uf="SP", senha_hash="$2b$x", id=2)
CAIO_N3 = Usuario(matricula="CAIO", nome="Caio", nivel=3, senha_hash="$2b$x", id=3)
BASE_N3, BASE_N2_SP = 1028, 116                   # ativas na data de referência
# O padrão do filtro é TODOS (ativos e encerrados identificados até hoje)
TODOS_N3, TODOS_N2_SP = 2400, 309                  # Eram 1.055, 128 e 304
RADIOATIVO, AREA = vocabulario.rotulo(sinteticos.RADIOATIVO), vocabulario.rotulo(sinteticos.AREA)   # no combo


@pytest.fixture
def tela(qt, tmp_path):
    from ecosec.aplicacao import montar
    from ecosec.interface.tela_acervo import TelaAcervo
    app = montar(caminho_env=tmp_path / ".env", modo="memoria")
    t = TelaAcervo(app)
    t.resize(1400, 900)
    t.show()
    yield t
    t.encerrar()
    t.deleteLater()


def _abrir(tela, qt, usuario=CAIO_N3, nivel=Nivel.N3, aba="mapa"):
    tela.iniciar(usuario, nivel)
    tela.mostrar_modo("painel")
    pa = tela.painel_analitico
    pa.mostrar(aba)
    qt.processEvents()
    # Este teste conta pontos desenhados (isVisible) na escala país; sem a agregação por zoom, que
    # esconde os pontos dentro dos agregados (a agregação tem os próprios testes)
    pa.mapa.caixa_agrupar.setChecked(False)
    return pa


def _pontos(pa) -> set:
    """Pontos plenos do mapa (visíveis e não atenuados)."""
    return {pt.pendencia.codigo for pt in pa.mapa.mapa.pontos if pt.isVisible() and not pt.atenuado}


def _linhas(pa) -> set:
    return {l.CODIGO for l in pa.planilha.modelo.todas}


def _dentro(pa) -> int:
    return int(pa.barra.contagem.text().split(" ")[0].replace(".", ""))


def _esperado(pa, filtro=None) -> set:
    painel = pa.painel
    return {p.codigo for p in (filtro or pa.estado.filtro).aplicar(painel.pendencias, painel.hoje, painel.regras)}


def _legenda_no_brasil(pa) -> int:
    m = pa.mapa.mapa
    m.ir_para_brasil()
    m._recalcular_legenda()
    # Com a situação Todos, os encerrados têm linha própria na legenda (fora das faixas)
    return sum(int(v) for r, v in m.linhas_legenda if r.startswith("● ") or r == "○ ENCERRADAS")


def _chip(barra, dimensao):
    return next(c for c in barra.chips if c.dimensao == dimensao)


# ================================================================ mapa == planilha == legenda == barra
def test_n3_classe_radioativo_mapa_planilha_legenda_e_barra(tela, qt):
    pa = _abrir(tela, qt)
    pa.mapa.combo_classe.setCurrentText(RADIOATIVO)
    assert pa.estado.filtro.classes == {sinteticos.RADIOATIVO}
    esperado = _esperado(pa)
    assert 0 < len(esperado) < TODOS_N3
    assert _pontos(pa) == _linhas(pa) == esperado
    assert _legenda_no_brasil(pa) == len(esperado) == _dentro(pa)
    assert pa.planilha.combo_classe.currentText() == RADIOATIVO                     # o outro combo acompanha
    assert [c.dimensao for c in pa.barra.chips] == ["classes"]
    # o "fora" da barra é o mesmo do mapa: o universo é a situação e o corte do filtro (aqui, todos até hoje)
    texto = pa.barra.contagem.text()
    fora_barra = int(texto.split(" · ")[1].split(" ")[0].replace(".", ""))
    assert fora_barra == pa.mapa.mapa.contagens["fora"]
    assert f"(de {pa.mapa.mapa.contagens['total']:,} casos ativos e encerrados em ".replace(",", ".") in texto


def test_motivo_na_planilha_e_risco_no_mapa_se_refletem(tela, qt):
    pa = _abrir(tela, qt)
    pl, m, painel = pa.planilha, pa.mapa, pa.painel
    motivo = "MP-01"
    pl.combo_motivo.setCurrentText(vocabulario.rotulo(motivo, "motivo"))
    assert pa.estado.filtro.motivos == {motivo}
    assert _pontos(pa) == _linhas(pa) == _esperado(pa, Filtro(motivos={motivo}))
    m.combo_risco.setCurrentText("Crítico")
    esperado = _esperado(pa, Filtro(motivos={motivo}, riscos={"CRITICO"}))
    assert esperado and _linhas(pa) == _pontos(pa) == esperado
    assert pl.combo_risco.currentText() == m.combo_risco.currentText() == "Crítico"
    pl.combo_atividade.setCurrentText(vocabulario.rotulo("AG-08", "atividade"))
    assert m.combo_atividade.currentText() == pl.combo_atividade.currentText()
    pl.combo_uf.setCurrentText("SP")
    assert m.combo_uf.currentText() == "SP" and _pontos(pa) == _linhas(pa) == _esperado(pa)


# ================================================================ chips, limpar, abas
def test_remover_chip_volta_a_base_e_limpar_zera(tela, qt):
    pa = _abrir(tela, qt)
    pa.mapa.combo_classe.setCurrentText(AREA)
    assert len(_pontos(pa)) < TODOS_N3
    _chip(pa.barra, "classes").botao.click()
    assert len(_pontos(pa)) == TODOS_N3 == len(_linhas(pa)) == _dentro(pa)
    assert pa.mapa.combo_classe.currentIndex() == 0 and pa.planilha.combo_classe.currentIndex() == 0
    # vários filtros, depois Limpar (na barra e na planilha)
    pa.planilha.combo_situacao.setCurrentIndex(0)                       # Ativos (o padrão é Todos)
    pa.planilha.busca.setText("SAO")
    pa.mapa.combo_uf.setCurrentText("SP")
    pa.planilha.combo_etapa.setCurrentIndex(1)
    assert len(pa.barra.chips) == 4
    pa.barra.botao_limpar.click()
    assert pa.estado.filtro == Filtro() and not pa.barra.chips and not pa.barra.botao_limpar.isEnabled()
    assert pa.planilha.busca.text() == "" and pa.planilha.combo_situacao.currentIndex() == 2
    assert all(c.currentIndex() == 0 for c in (pa.mapa.combo_uf, pa.planilha.combo_uf, pa.planilha.combo_etapa))
    assert len(_pontos(pa)) == TODOS_N3
    pa.planilha.combo_risco.setCurrentText("Alto")
    assert not hasattr(pa.planilha, "botao_limpar")                     # Um só "Limpar filtros", na barra
    pa.barra.botao_limpar.click()
    assert pa.estado.filtro == Filtro()


def test_n2_remover_chip_volta_a_base_da_uf(tela, qt):
    pa = _abrir(tela, qt, BIA_N2, Nivel.N2)
    assert len(_pontos(pa)) == TODOS_N2_SP == len(_linhas(pa)) == _dentro(pa)
    pa.planilha.combo_risco.setCurrentText("Crítico")
    assert _pontos(pa) == _linhas(pa) == _esperado(pa) and len(_pontos(pa)) < TODOS_N2_SP
    _chip(pa.barra, "riscos").botao.click()
    assert len(_pontos(pa)) == TODOS_N2_SP == len(_linhas(pa))


def test_trocar_de_aba_preserva_o_filtro(tela, qt):
    pa = _abrir(tela, qt)
    pa.mapa.combo_risco.setCurrentText("Alto")
    pa.planilha.combo_motivo.setCurrentIndex(2)
    filtro = pa.estado.filtro
    for aba in ("planilha", "agregado", "mapa"):                        # a Evolução saiu do N3
        pa.mostrar(aba)
        qt.processEvents()
        assert pa.estado.filtro == filtro, aba
        assert pa.barra.isVisible() and len(pa.barra.chips) == 2, aba
    assert _pontos(pa) == _linhas(pa) == _esperado(pa)


# ================================================================ ano, gráfico, árvore, resumo
def test_ano_n3_planilha_e_mapa_seguem(tela, qt):
    """O ano do N3 é uma lista ("Todos" = situação atual); era o slider da linha do tempo."""
    pa = _abrir(tela, qt)
    pa.mapa.combo_ano.setCurrentText("2015")
    assert pa.estado.filtro.ano == 2015 and any(c.dimensao == "ano" for c in pa.barra.chips)
    corte = date(2015, 12, 31)
    todos = {p.codigo for p in pa.painel.pendencias if p.data_identificacao <= corte}
    assert pa.planilha.combo_situacao.currentIndex() == 2                  # padrão Todos
    assert _linhas(pa) == todos == _pontos(pa) and _dentro(pa) == len(todos)
    pa.planilha.combo_situacao.setCurrentIndex(0)                          # Ativos
    ativas = {p.codigo for p in pa.painel.pendencias if p.ativa(corte)}
    assert _linhas(pa) == ativas == _pontos(pa) and _dentro(pa) == len(ativas)
    assert pa.titulo.text().startswith(f"Casos ativos em 31/12/2015: {len(ativas):,}".replace(",", "."))
    _chip(pa.barra, "ano").botao.click()                                   # remover o chip volta a hoje
    assert pa.mapa.combo_ano.currentText() == "Todos" and len(_pontos(pa)) == BASE_N3
    assert pa.titulo.text().startswith(f"Casos ativos em {pa.painel.hoje:%d/%m/%Y}: {BASE_N3:,}".replace(",", "."))


def test_arvore_com_uf_sp_so_tem_sp_no_in_situ(tela, qt):
    from ecosec.interface.arvore_custodia import PAPEL
    pa = _abrir(tela, qt)
    pa.mapa.combo_uf.setCurrentText("SP")
    arvore = pa.mapa.arvore
    raizes = [arvore.topLevelItem(i) for i in range(arvore.topLevelItemCount())]
    in_situ = next(r for r in raizes if r.data(0, PAPEL)[0] == "IN_SITU")
    in_situ.setExpanded(True)
    ufs = [in_situ.child(i).data(0, PAPEL)[1] for i in range(in_situ.childCount())]
    assert ufs == ["SP"]
    # sem filtro, volta a ter várias UFs
    _chip(pa.barra, "ufs").botao.click()
    raizes = [arvore.topLevelItem(i) for i in range(arvore.topLevelItemCount())]
    in_situ = next(r for r in raizes if r.data(0, PAPEL)[0] == "IN_SITU")
    in_situ.setExpanded(True)
    assert in_situ.childCount() > 5


def test_resumo_do_n3_segue_o_filtro(tela, qt):
    pa = _abrir(tela, qt, aba="agregado")
    titulos, linhas = pa.agregado.resumo.tabelas["POR CLASSE DE RISCO"]
    assert len(linhas) == 3
    pa.planilha.combo_classe.setCurrentText(RADIOATIVO)
    pa._recarregar_resumo()                                    # sem esperar o debounce
    titulos, linhas = pa.agregado.resumo.tabelas["POR CLASSE DE RISCO"]
    assert [l[0] for l in linhas] == [sinteticos.RADIOATIVO]
    # Com a situação Todos, o resumo conta os ATIVOS do recorte (como os indicadores)
    ativas = sum(p.ativa(pa.painel.hoje) and p.classe_risco == sinteticos.RADIOATIVO for p in pa.painel.pendencias)
    assert linhas[0][titulos.index("PENDENCIAS")] == ativas < _dentro(pa)
    pa.planilha.combo_situacao.setCurrentIndex(0)                         # Ativos: o resumo e a barra coincidem
    pa._recarregar_resumo()
    titulos, linhas = pa.agregado.resumo.tabelas["POR CLASSE DE RISCO"]
    assert linhas[0][titulos.index("PENDENCIAS")] == _dentro(pa)
    registro = tela.app.acervo.trilha.recentes(1)[0].evento
    assert registro.motivo == "RESUMO_AGREGADO" and "CLASSE: MATERIAL RADIOATIVO" in registro.detalhe.upper()
    pa.planilha.combo_situacao.setCurrentIndex(2)
    # pelo debounce também
    _chip(pa.barra, "classes").botao.click()
    from PySide6.QtTest import QTest
    assert pa._espera_resumo.isActive()
    decorrido = 0
    while pa._espera_resumo.isActive() and decorrido < 4000:          # sonda, sem depender de um tempo fixo
        QTest.qWait(25)
        decorrido += 25
    assert not pa._espera_resumo.isActive()
    assert len(pa.agregado.resumo.tabelas["POR CLASSE DE RISCO"][1]) == 3


def test_resumo_do_n1_recusa_filtro_e_continua_igual(tela, qt):
    from ecosec.servicos.acervo import ErroAcervo
    acervo = tela.app.acervo
    antes = acervo.resumo_agregado(ANA_N1, 1).tabelas
    with pytest.raises(ErroAcervo):
        acervo.resumo_agregado(ANA_N1, 1, filtro=Filtro(classes={sinteticos.RADIOATIVO}))
    with pytest.raises(ErroAcervo):
        acervo.resumo_agregado(ANA_N1, 1, filtro=Filtro())                 # nem o filtro vazio
    assert acervo.resumo_agregado(ANA_N1, 1).tabelas == antes
    pa = _abrir(tela, qt, ANA_N1, Nivel.N1, aba="agregado")
    assert pa.agregado.aviso_filtro.isVisible()
    assert pa.agregado.aviso_filtro.text() == ("Totais sem filtro; números muito pequenos ficam ocultos para "
                                               "proteger poucos casos.")
    assert pa.agregado.resumo.tabelas == antes
    assert not pa.barra.isVisible()                            # no N1 a barra do painel some (só a do panorama)


def test_n3_encerradas_aparecem_como_ponto_vazado(tela, qt):
    pa = _abrir(tela, qt)
    pa.planilha.combo_situacao.setCurrentIndex(1)
    assert pa.estado.filtro.situacao == "ENCERRADAS"
    visiveis = [pt for pt in pa.mapa.mapa.pontos if pt.isVisible() and not pt.atenuado]
    assert visiveis and all(pt.vazado for pt in visiveis)
    assert {pt.pendencia.codigo for pt in visiveis} == _linhas(pa) == _esperado(pa)
    assert len(visiveis) == _dentro(pa)
    # ativas e encerradas: as ativas cheias, as encerradas vazadas
    pa.planilha.combo_situacao.setCurrentIndex(2)
    visiveis = [pt for pt in pa.mapa.mapa.pontos if pt.isVisible()]
    assert len(visiveis) == len(pa.painel.pendencias) == len(_linhas(pa))
    assert sum(not pt.vazado for pt in visiveis) == BASE_N3
    # atenuar: os de fora ficam por baixo, sem contar
    pa.planilha.combo_situacao.setCurrentIndex(0)
    pa.mapa.combo_uf.setCurrentText("RJ")
    pa.mapa.caixa_atenuar.setChecked(True)
    assert pa.mapa.mapa.modo_recorte == "atenuar"
    assert any(pt.atenuado for pt in pa.mapa.mapa.pontos) and _pontos(pa) == _esperado(pa)


def test_ficha_fecha_quando_o_recorte_exclui_a_pendencia(tela, qt):
    pa = _abrir(tela, qt)
    p = next(pt.pendencia for pt in pa.mapa.mapa.pontos if pt.isVisible() and pt.pendencia.uf == "BA")
    pa.mapa.mostrar_ficha(p)
    assert pa.mapa.ficha.aberto
    pa.mapa.combo_uf.setCurrentText("BA")
    assert pa.mapa.ficha.aberto                                 # continua no recorte
    pa.mapa.combo_uf.setCurrentText("SP")
    assert not pa.mapa.ficha.aberto


def test_vinte_combinacoes_aleatorias_mapa_planilha_barra(tela, qt):
    from ecosec.interface.painel_analitico import SITUACOES_PLANILHA
    pa = _abrir(tela, qt)
    painel = pa.painel
    rng = random.Random(2026)
    ufs = sorted({p.uf for p in painel.pendencias})
    classes = (sinteticos.AREA, sinteticos.CLASSE_I, sinteticos.RADIOATIVO)
    atividades, motivos = sorted(painel.atividades), sorted(painel.motivos)
    etapas = sorted({p.etapa_atual for p in painel.pendencias})
    talvez = lambda valores: rng.choice([(), (rng.choice(valores),)])  # noqa: E731
    nao_vazios = 0
    for _ in range(20):
        filtro = Filtro(ufs=talvez(ufs), classes=talvez(classes), atividades=talvez(atividades),
                        motivos=talvez(motivos), etapas=talvez(etapas),
                        situacao=rng.choice(("ATIVAS", "ENCERRADAS", "TODAS")))
        pa.estado.substituir(filtro)
        esperado = _esperado(pa)
        nao_vazios += bool(esperado)
        assert _pontos(pa) == _linhas(pa) == esperado, filtro
        assert _dentro(pa) == len(esperado), filtro
        assert pa.planilha.combo_situacao.currentText() == SITUACOES_PLANILHA[
            ("ATIVAS", "ENCERRADAS", "TODAS").index(filtro.situacao)]
        if filtro.ufs:
            assert pa.mapa.combo_uf.currentText() == pa.planilha.combo_uf.currentText() == next(iter(filtro.ufs))
        if filtro.classes:
            assert pa.mapa.combo_classe.currentText() == vocabulario.rotulo(next(iter(filtro.classes)))
    assert nao_vazios >= 5


# ================================================================ N1: só classe e ano
def test_n1_chip_de_classe_e_combo_do_panorama_nos_dois_sentidos(tela, qt):
    pa = _abrir(tela, qt, ANA_N1, Nivel.N1, aba="panorama")
    pn = pa.panorama
    assert pn.barra.isVisible() and not pn.barra.chips
    total = pn.barra.contagem.text()
    assert total.endswith(")") and "casos ativos no recorte (de" in total
    # combo -> chip
    pn.combo_classe.setCurrentText(AREA)
    assert pn.estado.classe == sinteticos.AREA and pn.estado_filtro.filtro.classes == {sinteticos.AREA}
    assert [c.dimensao for c in pn.barra.chips] == ["classes"]
    n_area = sum(v for v in pn.panorama.totais_classe.values() if isinstance(v, int))
    assert pn.barra.contagem.text().startswith(f"{n_area:,}".replace(",", ".") + " casos ativos no recorte")
    # remover o chip -> todas as classes
    _chip(pn.barra, "classes").botao.click()
    assert pn.estado.classe is None and pn.combo_classe.currentIndex() == 0 and pn.panorama.classe is None
    # chip (estado do filtro) -> combo
    pn.estado_filtro.definir(classes={sinteticos.RADIOATIVO})
    assert pn.combo_classe.currentText() == RADIOATIVO and pn.panorama.classe == sinteticos.RADIOATIVO
    # ano: lista -> chip; remover o chip -> hoje ("Todos")
    pn.combo_ano.setCurrentText("2015")
    assert pn.estado_filtro.filtro.ano == 2015 and pn.panorama.ano == 2015
    _chip(pn.barra, "ano").botao.click()
    assert pn.estado.ano == pn.panorama.hoje.year and pn.combo_ano.currentText() == "Todos"
    # nenhuma outra dimensão entra no N1
    pn.estado_filtro.definir(ufs={"SP"}, riscos={"CRITICO"})
    assert not pn.estado_filtro.filtro.ufs and not pn.estado_filtro.filtro.riscos
    assert {c.dimensao for c in pn.barra.chips} <= {"classes", "ano"}
