"""Núcleo do filtro único (Filtro puro, EstadoFiltro e BarraFiltros).

A equivalência com os predicados de hoje é o que garante que a ligação nas telas (etapa seguinte) não muda
nenhum número: o mesmo recorte no Filtro dá exatamente os pontos do mapa e as linhas da planilha.
"""
import random
from dataclasses import replace
from datetime import date

import pytest

from ecosec.acervo import regras, sinteticos, vocabulario
from ecosec.acervo.filtro import Filtro
from ecosec.dominio.entidades import Usuario
from ecosec.dominio.niveis import Nivel

HOJE = sinteticos.DATA_BASE
CAIO_N3 = Usuario(matricula="CAIO", nome="Caio", nivel=3, senha_hash="$2b$x", id=3)


@pytest.fixture(scope="module")
def acervo():
    return sinteticos.gerar()[0]


@pytest.fixture(scope="module")
def r():
    return regras.ParametrosRegras.padrao()


def _codigos(ps):
    return {p.codigo for p in ps}


# aceita, por dimensão
def test_filtro_vazio_aceita_todos_e_ativas_so_as_ativas(acervo, r):
    # o padrão é TODAS
    assert Filtro().vazio() and Filtro().situacao == "TODAS"
    assert len(Filtro().aplicar(acervo, HOJE, r)) == len(acervo)
    assert _codigos(Filtro(situacao="ATIVAS").aplicar(acervo, HOJE, r)) == {p.codigo for p in acervo if p.ativa(HOJE)}


@pytest.mark.parametrize("dimensao, atributo", [("ufs", "uf"), ("classes", "classe_risco"),
                                                ("atividades", "atividade"), ("motivos", "motivo"),
                                                ("etapas", "etapa_atual")])
def test_aceita_por_dimensao_de_igualdade(acervo, r, dimensao, atributo):
    valores = sorted({getattr(p, atributo) for p in acervo})
    escolha = valores[: max(1, len(valores) // 3)]
    obtido = Filtro(situacao="TODAS", **{dimensao: escolha}).aplicar(acervo, HOJE, r)
    esperado = [p for p in acervo if getattr(p, atributo) in escolha]
    assert obtido == esperado and 0 < len(obtido) < len(acervo)


def test_aceita_municipio_pelo_par_uf_municipio(acervo, r):
    p0 = acervo[0]
    f = Filtro(situacao="TODAS", municipios={(p0.uf, p0.municipio)})
    assert f.aplicar(acervo, HOJE, r) == [p for p in acervo if (p.uf, p.municipio) == (p0.uf, p0.municipio)]
    assert Filtro(municipios=(p0.uf, p0.municipio)).municipios == {(p0.uf, p0.municipio)}   # par solto


def test_aceita_risco_e_acao_avaliados_em_hoje(acervo, r):
    for faixa in regras.CATEGORIAS:
        assert _codigos(Filtro(riscos={faixa}, situacao="ATIVAS").aplicar(acervo, HOJE, r)) == {
            p.codigo for p in acervo if p.ativa(HOJE) and regras.categoria(p, HOJE) == faixa}
    acao = regras.ACOES[1]
    obtido = Filtro(acoes={acao}, situacao="TODAS").aplicar(acervo, HOJE, r)
    assert obtido and all(regras.acao_recomendada(p, HOJE, r) == acao for p in obtido)
    # com corte no ano, a faixa continua sendo a de hoje (como os pontos do mapa)
    em_2015 = Filtro(riscos={"CRITICO"}, ano=2015, situacao="ATIVAS").aplicar(acervo, HOJE, r)
    assert all(p.ativa(date(2015, 12, 31)) and regras.categoria(p, HOJE) == "CRITICO" for p in em_2015)


def test_situacao_e_ano_com_pendencia_montada_a_mao(acervo):
    p = replace(acervo[0], data_identificacao=date(2010, 3, 1), data_encerramento=date(2015, 6, 1))
    assert Filtro(ano=2014, situacao="ATIVAS").aceita(p, HOJE) and not Filtro(ano=2015, situacao="ATIVAS").aceita(p, HOJE)
    assert Filtro(ano=2015).aceita(p, HOJE)                       # padrão TODAS: identificada até o corte
    assert Filtro(ano=2015, situacao="ENCERRADAS").aceita(p, HOJE)
    assert not Filtro(ano=2014, situacao="ENCERRADAS").aceita(p, HOJE)
    assert not Filtro(ano=2009, situacao="TODAS").aceita(p, HOJE)
    assert Filtro(ano=2009 + 20, situacao="TODAS").aceita(p, HOJE)
    assert not Filtro(situacao="ATIVAS").aceita(p, HOJE) and Filtro(situacao="ENCERRADAS").aceita(p, HOJE)
    assert Filtro(ano=2030).corte(HOJE) == HOJE and Filtro(ano=2012).corte(HOJE) == date(2012, 12, 31)
    with pytest.raises(ValueError):
        Filtro(situacao="QUALQUER")


def test_busca_olha_os_campos_da_planilha_e_a_classe(acervo, r):
    radioativos = {p.codigo for p in acervo if p.classe_risco == sinteticos.RADIOATIVO}
    achados = _codigos(Filtro(busca="  rejeito ", situacao="TODAS").aplicar(acervo, HOJE, r))
    assert radioativos and radioativos <= achados
    p = acervo[5]
    for termo in (p.codigo, p.municipio, p.cep, p.bairro.lower()):
        assert p.codigo in _codigos(Filtro(busca=termo, situacao="TODAS").aplicar(acervo, HOJE, r))
    assert Filtro(busca="   ").vazio()


# chips, sem, com, contar
def test_chips_rotulos_legiveis_e_ordem():
    f = Filtro(ufs={"SP", "RJ"}, classes={sinteticos.RADIOATIVO}, riscos={"CRITICO", "BAIXO"},
               municipios={("SP", "CAMPINAS")}, situacao="ENCERRADAS", ano=2015, busca=" ab ")
    rotulos = [c[2] for c in f.chips()]
    # Rótulos do vocabulário; a situação padrão (Todos) não vira chip
    assert rotulos == ["Situação do caso: Encerrados", "Ano: 2015", "UF: RJ", "UF: SP",
                       "Município: CAMPINAS/SP", "Classe: Material radioativo", "Risco: Baixo", "Risco: Crítico",
                       "Busca: ab"]
    assert not Filtro(situacao="TODAS").chips()
    assert ("ufs", "SP", "UF: SP") in f.chips()
    assert not any("—" in t or "–" in t for t in rotulos)
    atividades = {a.codigo: a for a in sinteticos.ATIVIDADES}
    assert Filtro(atividades={"AG-08"}).chips(atividades)[0][2] == "Atividade: Radioterapia e fontes radioativas"


def test_sem_com_e_vazio():
    f = Filtro().com(ufs={"SP", "RJ"}, riscos="CRITICO", ano=2015)
    assert f.riscos == {"CRITICO"} and isinstance(f.ufs, frozenset) and not f.vazio()
    assert f.sem("ufs", "RJ").ufs == {"SP"} and f.sem("ufs", "RJ").riscos == {"CRITICO"}
    assert f.sem("ufs").ufs == frozenset() and f.sem("ano").ano is None
    assert f.sem("ufs").sem("riscos").sem("ano") == Filtro() and Filtro().vazio()
    assert Filtro(situacao="ENCERRADAS").sem("situacao").situacao == "TODAS"
    assert f.com() == f and hash(f) == hash(Filtro(ufs=["RJ", "SP"], riscos=("CRITICO",), ano=2015))
    with pytest.raises(TypeError):
        f.com(cor="azul")
    with pytest.raises(TypeError):
        f.sem("cor")


def test_contar_dentro_mais_fora_igual_total(acervo, r):
    for f in (Filtro(), Filtro(ufs={"SP"}), Filtro(riscos={"CRITICO"}, situacao="TODAS"), Filtro(ano=2012)):
        dentro, fora, total = f.contar(acervo, HOJE, r)
        assert dentro + fora == total == len(acervo) and dentro == len(f.aplicar(acervo, HOJE, r))


# equivalência com o mapa e a planilha de hoje
@pytest.fixture(scope="module")
def painel_n3(qt, tmp_path_factory):
    from ecosec.aplicacao import montar
    from ecosec.interface.tela_acervo import TelaAcervo
    app = montar(caminho_env=tmp_path_factory.mktemp("r4filtro") / ".env", modo="memoria")
    t = TelaAcervo(app)
    t.resize(1400, 900)
    t.show()
    t.iniciar(CAIO_N3, Nivel.N3)
    t.mostrar_modo("painel")
    qt.processEvents()
    yield t.painel_analitico
    t.encerrar()
    t.deleteLater()


def _no_mapa(pa, uf=None, risco=None, atividade=None) -> set:
    from ecosec.interface.painel_analitico import TODAS_ATIVIDADES, TODAS_UFS, TODOS_RISCOS
    m = pa.mapa
    # O filtro é único; o que a planilha deixou nas dimensões que o mapa não tem sai antes (o ano fica)
    pa.estado.definir(motivos=(), acoes=(), etapas=(), situacao="ATIVAS", busca="")
    m.combo_uf.setCurrentText(uf or TODAS_UFS)
    # Os combos mostram o rótulo do vocabulário e filtram pelo código
    m.combo_risco.setCurrentText(vocabulario.rotulo(risco, "faixa") if risco else TODOS_RISCOS)
    m.combo_atividade.setCurrentText(vocabulario.rotulo(atividade, "atividade") if atividade else TODAS_ATIVIDADES)
    m.aplicar_filtros()
    return {pt.pendencia.codigo for pt in m.mapa.pontos if pt.filtrado and pt.no_ano}


def _na_planilha(pa, uf=None, risco=None, atividade=None, motivo=None, acao=None, situacao=0, busca="") -> set:
    from ecosec.interface.painel_analitico import (TODAS_ACOES, TODAS_ATIVIDADES, TODAS_UFS, TODOS_MOTIVOS,
                                                   TODOS_RISCOS)
    pl, painel = pa.planilha, pa.painel
    for combo, valor in ((pl.combo_uf, uf or TODAS_UFS),
                         (pl.combo_risco, vocabulario.rotulo(risco, "faixa") if risco else TODOS_RISCOS),
                         (pl.combo_atividade, vocabulario.rotulo(atividade, "atividade") if atividade else TODAS_ATIVIDADES),
                         (pl.combo_motivo, vocabulario.rotulo(motivo, "motivo") if motivo else TODOS_MOTIVOS),
                         (pl.combo_acao, vocabulario.rotulo(acao, "acao") if acao else TODAS_ACOES)):
        combo.blockSignals(True)
        combo.setCurrentText(valor)
        combo.blockSignals(False)
        assert combo.currentText() == valor
    pl.combo_situacao.blockSignals(True)
    pl.combo_situacao.setCurrentIndex(situacao)
    pl.combo_situacao.blockSignals(False)
    pl.busca.blockSignals(True)
    pl.busca.setText(busca)
    pl.busca.blockSignals(False)
    pl.filtrar()
    return {l.CODIGO for l in pl.modelo.todas}


def _pelo_filtro(pa, **dimensoes) -> set:
    """O recorte pelo Filtro. Estes testes comparam com o mapa nas ATIVAS: sem situação
    explícita, ATIVAS (o padrão do Filtro é TODAS)."""
    dimensoes.setdefault("situacao", "ATIVAS")
    painel = pa.painel
    return _codigos(Filtro(**dimensoes).aplicar(painel.pendencias, painel.hoje, painel.regras))


def _como_conjunto(uf, risco, atividade) -> dict:
    return {k: {v} for k, v in (("ufs", uf), ("riscos", risco), ("atividades", atividade)) if v}


def test_cadastro_datado_ate_hoje(painel_n3):
    """Premissa da equivalência de situação: ninguém identificado ou encerrado depois de hoje."""
    hoje = painel_n3.painel.hoje
    assert all(p.data_identificacao <= hoje and (p.data_encerramento or hoje) <= hoje
               for p in painel_n3.painel.pendencias)


@pytest.mark.parametrize("uf, risco, atividade", [
    (None, None, None), ("SP", None, None), (None, "CRITICO", None), (None, "BAIXO", None),
    (None, None, "AG-01"), (None, None, "AG-08"), ("SP", "CRITICO", None), ("MG", None, "AG-07"),
    (None, "ALTO", "AG-01"), ("RJ", "MEDIO", "AG-04")])
def test_mesmo_recorte_que_o_mapa_e_a_planilha(painel_n3, uf, risco, atividade):
    filtro = _pelo_filtro(painel_n3, **_como_conjunto(uf, risco, atividade))
    assert filtro == _no_mapa(painel_n3, uf, risco, atividade)
    assert filtro == _na_planilha(painel_n3, uf, risco, atividade)


def test_risco_critico_bate_e_nao_e_trivial(painel_n3):
    criticas = _pelo_filtro(painel_n3, riscos={"CRITICO"})
    assert 0 < len(criticas) < len(painel_n3.painel.pendencias)
    assert criticas == _no_mapa(painel_n3, risco="CRITICO") == _na_planilha(painel_n3, risco="CRITICO")


def test_vinte_combinacoes_aleatorias(painel_n3):
    painel = painel_n3.painel
    rng = random.Random(4)
    ufs = sorted({p.uf for p in painel.pendencias})
    atividades, motivos = sorted(painel.atividades), sorted(painel.motivos)
    acoes = sorted({regras.acao_recomendada(p, painel.hoje, painel.regras) for p in painel.pendencias})
    talvez = lambda valores: rng.choice([None, rng.choice(valores)])  # noqa: E731
    for _ in range(20):
        uf, risco, atividade = talvez(ufs), talvez(list(regras.CATEGORIAS)), talvez(atividades)
        assert _pelo_filtro(painel_n3, **_como_conjunto(uf, risco, atividade)) == \
            _no_mapa(painel_n3, uf, risco, atividade)
        motivo, acao, situacao = talvez(motivos), talvez(acoes), rng.randrange(3)
        extras = {k: {v} for k, v in (("motivos", motivo), ("acoes", acao)) if v}
        assert _pelo_filtro(painel_n3, **_como_conjunto(uf, risco, atividade), **extras,
                            situacao=("ATIVAS", "ENCERRADAS", "TODAS")[situacao]) == \
            _na_planilha(painel_n3, uf, risco, atividade, motivo, acao, situacao)


def test_busca_igual_a_planilha_e_mais_a_classe(painel_n3):
    p = painel_n3.painel.pendencias[7]
    for termo in (p.municipio, p.codigo[:6], f" {p.bairro.lower()} "):
        assert _pelo_filtro(painel_n3, busca=termo, situacao="TODAS") == _na_planilha(painel_n3, situacao=2,
                                                                                         busca=termo)
    hoje_planilha = _na_planilha(painel_n3, busca="REJEITO")
    pelo_filtro = _pelo_filtro(painel_n3, busca="REJEITO")
    radioativas = {q.codigo for q in painel_n3.painel.pendencias
                   if q.classe_risco == sinteticos.RADIOATIVO and q.ativa(painel_n3.painel.hoje)}
    # a planilha usa o Filtro, então também acha pela classe
    assert hoje_planilha == pelo_filtro and radioativas <= pelo_filtro


def test_ano_igual_a_linha_do_tempo_do_mapa(painel_n3):
    try:
        for ano, risco in ((2012, None), (2018, "CRITICO")):
            painel_n3.mapa.definir_ano(ano)
            assert _pelo_filtro(painel_n3, ano=ano, **_como_conjunto(None, risco, None)) == \
                _no_mapa(painel_n3, risco=risco)
    finally:
        painel_n3.mapa.definir_ano(painel_n3.painel.hoje.year)


# EstadoFiltro
def test_estado_so_emite_quando_muda(qt):
    from ecosec.interface.estado_filtro import EstadoFiltro
    estado, recebidos = EstadoFiltro(), []
    estado.mudou.connect(recebidos.append)
    assert estado.definir(ufs={"SP"})
    assert not estado.definir(ufs=["SP"])                       # mesmo filtro: sem eco
    assert estado.definir(riscos={"CRITICO", "ALTO"})
    assert estado.remover("riscos", "ALTO") and estado.filtro.riscos == {"CRITICO"}
    assert not estado.remover("motivos")
    assert estado.limpar() and estado.filtro == Filtro() and not estado.limpar()
    assert recebidos == [Filtro(ufs={"SP"}), Filtro(ufs={"SP"}, riscos={"CRITICO", "ALTO"}),
                         Filtro(ufs={"SP"}, riscos={"CRITICO"}), Filtro()]
    assert not estado.substituir(Filtro()) and estado.substituir(Filtro(ano=2015))


# BarraFiltros
def test_barra_chips_remover_contagem_e_limpar(qt):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from ecosec.interface.componentes.barra_filtros import BarraFiltros
    from ecosec.interface.estado_filtro import EstadoFiltro
    estado = EstadoFiltro()
    barra = BarraFiltros(estado)
    barra.resize(700, 80)
    barra.show()
    qt.processEvents()
    assert not barra.chips and barra.rotulo_vazio.isVisible() and barra.rotulo_vazio.text() == "Sem filtro"
    assert not barra.botao_limpar.isEnabled()
    estado.definir(ufs={"SP", "RJ"}, riscos={"CRITICO"}, classes={sinteticos.AREA})
    qt.processEvents()
    assert [c.rotulo for c in barra.chips] == ["UF: RJ", "UF: SP", "Classe: Área contaminada", "Risco: Crítico"]
    assert barra.botao_limpar.isEnabled() and not barra.rotulo_vazio.isVisible()
    assert all(c.accessibleName() and c.botao.accessibleName() for c in barra.chips)
    assert barra.botao_limpar.accessibleName() and barra.contagem.accessibleName()
    chip_rj = next(c for c in barra.chips if c.valor == "RJ")
    QTest.mouseClick(chip_rj.botao, Qt.MouseButton.LeftButton)
    qt.processEvents()
    assert estado.filtro == Filtro(ufs={"SP"}, riscos={"CRITICO"}, classes={sinteticos.AREA})
    assert [c.rotulo for c in barra.chips] == ["UF: SP", "Classe: Área contaminada", "Risco: Crítico"]
    barra.definir_contagem(1200, 1200, 2400)
    assert barra.contagem.text() == "1.200 dentro · 1.200 fora (de 2.400)"
    QTest.mouseClick(barra.botao_limpar, Qt.MouseButton.LeftButton)
    qt.processEvents()
    assert estado.filtro == Filtro() and not barra.chips and not barra.botao_limpar.isEnabled()
    assert barra.rotulo_vazio.isVisible()
    barra.close()


def test_barra_quebra_linha_com_muitos_chips(qt):
    from ecosec.interface.componentes.barra_filtros import BarraFiltros
    from ecosec.interface.estado_filtro import EstadoFiltro
    estado = EstadoFiltro(Filtro(ufs=set(sinteticos.PESO_UF)))
    barra = BarraFiltros(estado)
    barra.resize(600, 400)
    barra.show()
    qt.processEvents()
    assert len(barra.chips) == len(sinteticos.PESO_UF)
    assert len({c.y() for c in barra.chips}) > 1                 # mais de uma linha de chips
    barra.close()
