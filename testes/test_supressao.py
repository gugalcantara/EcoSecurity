"""Supressão k=3 do N1 sem vazamento entre filtros e tabelas.

panorama do N1: a célula (UF, classe) escondida na visão "todas as classes" não pode sair na visão
           filtrada pela classe, nem por subtração (antes: 38 casos de 2008 a 2026). Um cubo por corte.
/  resumo do N1: a quantidade de uma célula (grupo, classe) pequena e as subcontagens pequenas (ou com
           complemento pequeno) dentro de linhas visíveis saem SUPRIMIDO (2026-10-24).
/  o k só vale no N1: o panorama do N3 sai inteiro.
"""
from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from ecosec.acervo import analise, sinteticos
from ecosec.configuracao import carregar
from ecosec.dominio.entidades import Usuario
from ecosec.repositorios.memoria import RepositorioAcervoMemoria, RepositorioTrilhaMemoria
from ecosec.servicos.acervo import ServicoAcervo
from ecosec.servicos.trilha import ServicoTrilha

CFG = carregar()
HOJE = sinteticos.DATA_BASE
K = int(CFG["indice_pressao.supressao_minima"])
ANA_N1 = Usuario(matricula="ANA", nome="Ana", nivel=1, senha_hash="$2b$x", id=1)
CAIO_N3 = Usuario(matricula="CAIO", nome="Caio", nivel=3, senha_hash="$2b$x", id=3)
CLASSES = (sinteticos.AREA, sinteticos.CLASSE_I, sinteticos.RADIOATIVO)
ANOS = range(2008, HOJE.year + 1)
SUBCONTAGENS = tuple(analise.SUBCONTAGENS)            # FORA DA PREVISAO, CRITICAS, ALEM DO PRAZO LIMITE


@pytest.fixture(scope="module")
def acervo():
    servico = ServicoAcervo.de_configuracao(CFG, RepositorioAcervoMemoria(), ServicoTrilha(RepositorioTrilhaMemoria()),
                                            b"chave-teste", relogio=lambda: datetime(2026, 10, 1, 10, 0))
    servico.data_referencia = HOJE
    return servico


@pytest.fixture(scope="module")
def vistas(acervo):
    """{ano: (todas N1, {classe: filtrada N1}, todas N3, {classe: filtrada N3})}: o N3 dá os números reais."""
    return {ano: (acervo.panorama(ANA_N1, 1, ano), {c: acervo.panorama(ANA_N1, 1, ano, c) for c in CLASSES},
                  acervo.panorama(CAIO_N3, 3, ano), {c: acervo.panorama(CAIO_N3, 3, ano, c) for c in CLASSES})
            for ano in ANOS}


def _celula_escondida_em_todas(todas, uf, classe) -> bool:
    return todas.pressao[uf].suprimida or todas.por_classe[uf].get(classe, 0) is None


# ================================================================ o panorama do N1
def test_nenhuma_celula_escondida_em_todas_sai_na_vista_da_classe(vistas):
    """Busca de vazamento, para todo ano e toda classe: nem revelada pelo
    filtro, nem deduzida por subtração (total da UF − classes visíveis − reveladas)."""
    vazamentos = []
    for ano, (todas, filtradas, _, _) in vistas.items():
        for uf, item in todas.pressao.items():
            if item.suprimida:
                reveladas = [c for c in CLASSES if not filtradas[c].pressao[uf].suprimida
                             and filtradas[c].pressao[uf].ativas]
                vazamentos += [(ano, uf, c, "revelada") for c in reveladas]
                continue
            celulas = todas.por_classe[uf]
            escondidas = [c for c, n in celulas.items() if n is None]
            reveladas = {c: filtradas[c].pressao[uf].ativas for c in escondidas
                         if not filtradas[c].pressao[uf].suprimida}
            vazamentos += [(ano, uf, c, "revelada") for c in reveladas]
            if len(escondidas) - len(reveladas) == 1:
                vazamentos.append((ano, uf, set(escondidas) - set(reveladas), "por subtração"))
    assert vazamentos == []


def test_a_mesma_celula_tem_o_mesmo_destino_em_todas_e_na_vista_da_classe(vistas):
    for ano, (todas, filtradas, _, reais) in vistas.items():
        for uf in todas.pressao:
            for c in CLASSES:
                escondida = _celula_escondida_em_todas(todas, uf, c)
                assert filtradas[c].pressao[uf].suprimida == escondida, (ano, uf, c)
                if not escondida:
                    n = reais[c].pressao[uf].ativas
                    assert todas.por_classe[uf].get(c, 0) == n == filtradas[c].pressao[uf].ativas, (ano, uf, c)


def test_nenhuma_celula_do_cubo_sai_por_subtracao_de_margem(vistas):
    """Com os números reais (N3): em cada linha (as classes e o total da UF) e em cada coluna (o total nacional
    da classe aparece), nunca uma só célula não nula escondida. Vale para a contagem e para as críticas."""
    for ano, (todas, filtradas, real, reais) in vistas.items():
        def valores(uf):
            """[(escondida?, real, críticas escondidas?, críticas reais)] das classes e do total da UF."""
            linha = [(filtradas[c].pressao[uf].suprimida, reais[c].pressao[uf].ativas,
                      filtradas[c].pressao[uf].suprimida or filtradas[c].pressao[uf].criticas is None,
                      reais[c].pressao[uf].criticas) for c in CLASSES]
            t = todas.pressao[uf]
            return linha + [(t.suprimida, real.pressao[uf].ativas, t.suprimida or t.criticas is None,
                             real.pressao[uf].criticas)]
        grade = {uf: valores(uf) for uf in todas.pressao}
        for uf, linha in grade.items():
            assert sum(e and n > 0 for e, n, _, _ in linha) != 1, (ano, uf)
            assert sum(e and n > 0 for _, _, e, n in linha) != 1, (ano, uf, "criticas")
            assert sum(e and n - c > 0 for (_, n, e, c) in linha) != 1, (ano, uf, "nao criticas")
        for j in range(len(CLASSES) + 1):
            coluna = [linha[j] for linha in grade.values()]
            assert sum(e and n > 0 for e, n, _, _ in coluna) != 1, (ano, j)
            assert sum(e and n > 0 for _, _, e, n in coluna) != 1, (ano, j, "criticas")


def test_subcontagem_visivel_do_panorama_n1_nao_e_pequena(vistas):
    for ano, (todas, filtradas, _, _) in vistas.items():
        for vista in (todas, *filtradas.values()):
            for item in vista.pressao.values():
                if item.suprimida or not item.ativas:
                    continue
                assert item.ativas >= K, (ano, vista.classe, item.uf)
                for sub in (item.criticas, item.vencidas):
                    assert sub is None or not (0 < sub < K or 0 < item.ativas - sub < K), (ano, vista.classe, item.uf)


def test_panorama_do_n3_nao_suprime_nem_com_a_classe_radioativo(vistas):
    for ano, (_, _, real, reais) in vistas.items():
        for vista in (real, *reais.values()):
            assert vista.supressao_minima == 0
            assert not any(item.suprimida for item in vista.pressao.values()), (ano, vista.classe)
            assert all(item.criticas is not None and item.vencidas is not None for item in vista.pressao.values())
            assert all(n is not None for d in vista.por_classe.values() for n in d.values())
    radioativo = vistas[HOJE.year][3][sinteticos.RADIOATIVO]
    # Eram AM, RN e TO
    assert {uf for uf, item in radioativo.pressao.items() if 0 < item.ativas < K} >= {"AC", "AM", "CE", "PB"}


# ================================================================ o resumo do N1
def _celulas(titulos, linhas, coluna):
    i = list(titulos).index(coluna)
    return {tuple(l[:list(titulos).index("PENDENCIAS")]): l[i] for l in linhas}


def test_resumo_n1_quantidade_de_rejeito_de_uma_so_pendencia_sai_suprimida(acervo):
    base = {p.classe_risco: p for p in acervo.repo.pendencias() if p.ativa(HOJE)}
    montado = []
    for uf, area, rejeito in (("SP", 9, 1), ("RJ", 4, 5), ("MG", 6, 6)):
        for i, classe in enumerate([sinteticos.AREA] * area + [sinteticos.RADIOATIVO] * rejeito):
            montado.append(replace(base[classe], codigo=f"{uf}{i}", uf=uf, data_encerramento=None,
                                   data_identificacao=HOJE - timedelta(days=30)))
    original = acervo.repo._pendencias
    acervo.repo._pendencias = montado
    try:
        titulos, linhas = acervo.resumo_agregado(ANA_N1, 1).tabelas["POR UF"]
    finally:
        acervo.repo._pendencias = original
    rejeito = _celulas(titulos, linhas, "M3 REJEITO RADIOATIVO")
    assert rejeito[("SP",)] == analise.SUPRIMIDO                       # 1 pendência de rejeito numa UF de 10
    # complementar na coluna (o total nacional aparece em por classe de risco): a menor das outras, RJ
    assert rejeito[("RJ",)] == analise.SUPRIMIDO
    assert isinstance(rejeito[("MG",)], float) and rejeito[("MG",)] > 0
    assert all(n != analise.SUPRIMIDO for n in _celulas(titulos, linhas, "PENDENCIAS").values())


def test_resumo_n1_real_nao_mostra_rejeito_de_ac_am_ce_pb(acervo):
    # Eram RN, AM e TO (o teste se chamava ..._de_rn_am_to)
    titulos, linhas = acervo.resumo_agregado(ANA_N1, 1).tabelas["POR UF"]
    rejeito = _celulas(titulos, linhas, "M3 REJEITO RADIOATIVO")
    assert all(rejeito[(uf,)] == analise.SUPRIMIDO for uf in ("AC", "AM", "CE", "PB"))


def test_resumo_n1_nenhuma_subcontagem_visivel_pequena_nem_o_complemento(acervo):
    for agrupamento, (titulos, linhas) in acervo.resumo_agregado(ANA_N1, 1).tabelas.items():
        totais = _celulas(titulos, linhas, "PENDENCIAS")
        for coluna in SUBCONTAGENS:
            celulas = _celulas(titulos, linhas, coluna)
            for chave, v in celulas.items():
                if v == analise.SUPRIMIDO:
                    continue
                assert not (0 < v < K or 0 < totais[chave] - v < K), (agrupamento, chave, coluna)
            if len(celulas) > 1:                                     # uma só escondida sairia do total nacional
                assert sum(v == analise.SUPRIMIDO for v in celulas.values()) != 1, (agrupamento, coluna)
        for coluna, derivadas in analise.SUBCONTAGENS.items():
            parte = _celulas(titulos, linhas, coluna)
            for derivada in derivadas:
                assert all(v == analise.SUPRIMIDO for c, v in _celulas(titulos, linhas, derivada).items()
                           if parte[c] == analise.SUPRIMIDO), (agrupamento, derivada)


def test_resumo_n1_quantidade_por_classe_segue_a_contagem_da_celula(acervo):
    pendencias = [p for p in acervo.repo.pendencias() if p.ativa(HOJE)]
    atividades = {a.codigo: a for a in acervo.repo.atividades()}
    motivos = {m.codigo: m for m in acervo.repo.motivos()}
    for agrupamento, (titulos, linhas) in acervo.resumo_agregado(ANA_N1, 1).tabelas.items():
        contagens = analise.contagens_por_classe(pendencias, HOJE, agrupamento, atividades, motivos, acervo.regras)
        for classe, coluna in analise.COLUNA_DA_CLASSE.items():
            celulas = _celulas(titulos, linhas, coluna)
            for chave, v in celulas.items():
                n = contagens.get(chave, {}).get(classe, 0)
                assert v == analise.SUPRIMIDO or not 0 < n < K, (agrupamento, chave, coluna)
            escondidas = [c for c, v in celulas.items() if v == analise.SUPRIMIDO and contagens[c].get(classe, 0)]
            assert len(escondidas) != 1, (agrupamento, coluna)


def test_resumo_por_uf_e_panorama_do_ano_corrente_escondem_as_mesmas_celulas(acervo, vistas):
    todas, filtradas, _, _ = vistas[HOJE.year]
    titulos, linhas = acervo.resumo_agregado(ANA_N1, 1).tabelas["POR UF"]
    contagem, criticas = _celulas(titulos, linhas, "PENDENCIAS"), _celulas(titulos, linhas, "CRITICAS")
    for uf, item in todas.pressao.items():
        if (uf,) not in contagem:
            continue
        assert (contagem[(uf,)] == analise.SUPRIMIDO) == item.suprimida, uf
        assert (criticas[(uf,)] == analise.SUPRIMIDO) == (item.suprimida or item.criticas is None), uf
        for classe, coluna in analise.COLUNA_DA_CLASSE.items():
            if filtradas[classe].pressao[uf].suprimida:
                assert _celulas(titulos, linhas, coluna)[(uf,)] == analise.SUPRIMIDO, (uf, classe)


def test_resumo_do_n3_continua_sem_suprimido(acervo):
    resumo = acervo.resumo_agregado(CAIO_N3, 3)
    assert resumo.supressao_minima == 0
    assert all(analise.SUPRIMIDO not in l for _, linhas in resumo.tabelas.values() for l in linhas)


# ================================================================ a regra
def test_suprimir_subcontagem_esconde_parte_e_complemento_pequenos_com_complementar():
    totais = {("A",): 10, ("B",): 10, ("C",): 10, ("D",): 10}
    parte = {("A",): 2, ("B",): 5, ("C",): 6, ("D",): 9}          # A: v pequeno; D: n − v = 1
    escondidas = analise.suprimir_subcontagem(totais, parte, 3)
    assert {("A",), ("D",)} <= escondidas and len(escondidas) >= 2


def test_zero_escondido_nao_conta_como_protecao():
    # (A) = 0 já escondida não protege (B) = 1: a soma das escondidas da coluna seria o próprio B
    escondidas = analise.suprimir({("A",): 0, ("B",): 1, ("C",): 5, ("D",): 7}, 3, iniciais={("A",)})
    assert ("C",) in escondidas


def test_zero_escondido_sozinho_tambem_ganha_complementar():
    # a parte de a é 0 e foi escondida porque o complemento dela protege outra linha: sozinha na coluna, sairia
    escondidas = analise.suprimir({("A",): 0, ("B",): 4, ("C",): 6}, 3, iniciais={("A",)})
    assert ("B",) in escondidas


# ================================================================ fluxos anuais da série no N1
@pytest.mark.parametrize("classe", [None, *sinteticos.UNIDADE_DA_CLASSE])
def test_fluxo_anual_do_n1_nao_mostra_entrada_ou_saida_pequena(acervo, classe):
    serie = acervo.panorama(ANA_N1, 1, classe=classe).serie
    for a in serie["anos"]:
        e, s = serie["entradas"][a], serie["saidas"][a]
        assert (e is None) == (s is None), a                    # o par do ano sai junto
        if e is not None:
            assert not (0 < e < K) and not (0 < s < K), (classe, a, e, s)


def test_rejeito_tinha_fluxo_pequeno_e_ele_sai_suprimido_so_no_n1(acervo):
    rejeito = "REJEITO RADIOATIVO CNEN"
    n1 = acervo.panorama(ANA_N1, 1, classe=rejeito).serie
    n3 = acervo.panorama(CAIO_N3, 3, classe=rejeito).serie
    suprimidos = [a for a in n1["anos"] if n1["entradas"][a] is None]
    assert suprimidos                                           # o caso existe nos dados (2006 a 2012)
    for a in suprimidos:
        assert 0 < n3["entradas"][a] < K or 0 < n3["saidas"][a] < K
    assert all(v is not None for v in n3["entradas"].values())  # N3 sem k


def test_relatorio_recebe_o_k_da_configuracao(acervo, monkeypatch):
    from ecosec.acervo import relatorios
    vistos = []
    original = relatorios.gerar
    monkeypatch.setattr(relatorios, "gerar", lambda item, dados, fontes: vistos.append(dados.k) or original(
        item, dados, fontes))
    acervo.supressao_minima = 5
    acervo.abrir("A1-01", ANA_N1, 1)
    assert vistos == [5]
