"""Regras do acervo, cada uma com o seu teste:

k=3 com supressão complementar em todo agregado do N1
pessoa física e custo somado por responsável só no N3
quantidade coerente com atividade e classe
custo por componente e rota de tratamento, com memória de cálculo
latência mínima por linha antes de poder encerrar
KPI-01 por Kaplan-Meier, com censura e entrada tardia
série anual do banco sem ano final fixo
termo 3.1 com contato simulado e rodapé; a 3.0 arquivada continua conferindo
"""
import csv
from datetime import datetime

import pytest

from ecosec.acervo import analise, sinteticos
from ecosec.configuracao import carregar
from ecosec.dominio.entidades import Usuario
from ecosec.repositorios.memoria import RepositorioAcervoMemoria, RepositorioTrilhaMemoria
from ecosec.seguranca import autorizacao
from ecosec.seguranca.autorizacao import Classificacao, Efeito, Operacao, Papel
from ecosec.servicos.acervo import ErroAcervo, ServicoAcervo
from ecosec.servicos.trilha import ServicoTrilha

CFG = carregar()
HOJE = sinteticos.DATA_BASE
K = int(CFG["indice_pressao.supressao_minima"])
ANA_N1 = Usuario(matricula="ANA", nome="Ana", nivel=1, senha_hash="$2b$x", id=1)
BIA_N2 = Usuario(matricula="BIA", nome="Bia", nivel=2, uf="SP", senha_hash="$2b$x", id=2)
CAIO_N3 = Usuario(matricula="CAIO", nome="Caio", nivel=3, senha_hash="$2b$x", id=3)
RADIOATIVO = "REJEITO RADIOATIVO CNEN"


@pytest.fixture
def acervo():
    servico = ServicoAcervo.de_configuracao(CFG, RepositorioAcervoMemoria(), ServicoTrilha(RepositorioTrilhaMemoria()),
                                            b"chave-teste", relogio=lambda: datetime(2026, 10, 1, 10, 0))
    servico.data_referencia = HOJE
    return servico


# ================================================================ a regra
def test_suprimir_primaria_e_complementar_numa_tabela():
    escondidas = analise.suprimir({("A",): 1, ("B",): 5, ("C",): 7}, 3)
    assert escondidas == {("A",), ("B",)}           # A < 3; B sai junto, senão A = total - B - C


def test_suprimir_nada_quando_todas_as_celulas_passam_de_k():
    assert analise.suprimir({("A",): 3, ("B",): 9}, 3) == set()


def test_suprimir_nao_complementa_quando_ja_ha_duas_escondidas():
    assert analise.suprimir({("A",): 1, ("B",): 2, ("C",): 7}, 3) == {("A",), ("B",)}


def test_suprimir_em_duas_margens_ate_estabilizar():
    # linha SP: (SP,X)=1 é primária -> a menor visível da linha, (SP,Y)=4, sai junto;
    # coluna Y: agora só (SP,Y) escondida -> (RJ,Y) também sai; linha RJ fica com uma -> (RJ,X) sai.
    celulas = {("SP", "X"): 1, ("SP", "Y"): 4, ("SP", "Z"): 9, ("RJ", "X"): 8, ("RJ", "Y"): 5, ("RJ", "Z"): 6}
    escondidas = analise.suprimir(celulas, 3, (lambda c: (c[0],), lambda c: (c[1],)))
    for margem in (0, 1):
        for grupo in {c[margem] for c in celulas}:
            assert sum(c in escondidas for c in celulas if c[margem] == grupo) != 1


# ================================================================ o resumo do N1
def _contagem(titulos, linha):
    return linha[list(titulos).index("PENDENCIAS")]


def test_resumo_n1_nao_tem_celula_pequena_visivel_em_nenhuma_tabela(acervo):
    resumo = acervo.resumo_agregado(ANA_N1, 1)
    assert resumo.supressao_minima == K
    for agrupamento, (titulos, linhas) in resumo.tabelas.items():
        visiveis = [_contagem(titulos, l) for l in linhas if _contagem(titulos, l) != analise.SUPRIMIDO]
        assert all(n >= K for n in visiveis), agrupamento
        tapadas = [l for l in linhas if _contagem(titulos, l) == analise.SUPRIMIDO]
        assert all(set(l[list(titulos).index("PENDENCIAS"):]) == {analise.SUPRIMIDO} for l in tapadas)
        assert len(tapadas) != 1, agrupamento          # uma só sairia por subtração do total


def test_resumo_n1_por_uf_e_atividade_complementa_por_uf_e_por_atividade(acervo):
    titulos, linhas = acervo.resumo_agregado(ANA_N1, 1).tabelas["POR UF E ATIVIDADE"]
    tapada = {(l[0], l[1]) for l in linhas if _contagem(titulos, l) == analise.SUPRIMIDO}
    assert len(tapada) > 100                            # 133 células UF × atividade tinham 1 ou 2
    for margem in (0, 1):
        for grupo in {l[margem] for l in linhas}:
            assert sum(c[margem] == grupo for c in tapada) != 1


def test_linhas_suprimidas_vao_para_o_fim_em_ordem_de_chave(acervo):
    titulos, linhas = acervo.resumo_agregado(ANA_N1, 1).tabelas["POR UF E ATIVIDADE"]
    marcas = [_contagem(titulos, l) == analise.SUPRIMIDO for l in linhas]
    primeira = marcas.index(True)
    assert all(marcas[primeira:])
    chaves = [(l[0], l[1]) for l in linhas[primeira:]]
    assert chaves == sorted(chaves)


def test_resumo_do_n3_nao_suprime(acervo):
    resumo = acervo.resumo_agregado(CAIO_N3, 3)
    assert resumo.supressao_minima == 0
    assert all(analise.SUPRIMIDO not in l for _, linhas in resumo.tabelas.values() for l in linhas)


def test_exportacao_do_n1_sai_suprimida(acervo, tmp_path):
    resumo = acervo.resumo_agregado(ANA_N1, 1)
    destino = tmp_path / "resumo.csv"
    acervo.exportar_resumo(resumo, ANA_N1, "POR UF E ATIVIDADE", destino)
    linhas = list(csv.reader(destino.read_text(encoding="utf-8-sig").splitlines(), delimiter=";"))
    i = linhas[0].index("PENDENCIAS")
    contagens = [l[i] for l in linhas[1:]]
    assert analise.SUPRIMIDO in contagens
    assert all(int(n) >= K for n in contagens if n != analise.SUPRIMIDO)


def test_trilha_registra_quantas_celulas_foram_suprimidas(acervo):
    acervo.resumo_agregado(ANA_N1, 1)
    assert "CELULAS SUPRIMIDAS" in acervo.trilha.recentes(1)[0].evento.detalhe.upper()


# ================================================================ o panorama do N1
def test_panorama_filtrado_por_classe_suprime_uf_sem_deixar_numero(acervo):
    p = acervo.panorama(ANA_N1, 1, classe=RADIOATIVO)
    suprimidas = [item for item in p.pressao.values() if item.suprimida]
    assert suprimidas and len(suprimidas) != 1
    for item in suprimidas:
        # custo None: o N1 não recebe dado financeiro
        assert (item.ativas, item.criticas, item.custo, item.vencidas, item.indice, item.posto) == (0, 0, None, 0, 0.0, 0)
        assert p.por_classe[item.uf] == {}


def test_panorama_uf_por_classe_complementa_nas_duas_margens(acervo):
    p = acervo.panorama(ANA_N1, 1)
    visiveis = {uf: d for uf, d in p.por_classe.items() if not p.pressao[uf].suprimida}
    for uf, d in visiveis.items():
        assert all(n is None or n >= K for n in d.values())
        assert sum(n is None for n in d.values()) != 1, uf
    for classe in p.totais_classe:
        assert sum(d.get(classe, 0) is None for d in visiveis.values()) != 1, classe


def test_visoes_sql_do_n1_usam_o_mesmo_k_da_configuracao():
    from pathlib import Path
    sql = (Path(__file__).resolve().parent.parent / "sql" / "acervo" / "01_schema.sql").read_text(encoding="utf-8")
    trecho = sql[sql.index("CREATE OR REPLACE VIEW vw_n1_por_atividade"):sql.index("CREATE OR REPLACE VIEW vw_fluxo")]
    assert trecho.count(f"pendencias < {K}") == 4 and trecho.count(f"pendencias >= {K}") == 2


def test_visoes_sql_do_n1_suprimem_no_mysql(acervo_mysql):
    with acervo_mysql.transacao() as c:
        c.execute("SELECT uf, atividade, pendencias FROM vw_n1_por_atividade")
        visiveis = [(r["uf"], r["atividade"], r["pendencias"]) for r in c.fetchall()]
        c.execute("SELECT p.uf, a.codigo, COUNT(*) AS n FROM pendencia p JOIN atividade_geradora a ON a.id = "
                  "p.atividade_id WHERE p.data_encerramento IS NULL GROUP BY p.uf, a.codigo")
        todas = [(r["uf"], r["codigo"], r["n"]) for r in c.fetchall()]
        c.execute("SELECT MIN(pendencias) AS minimo FROM vw_n1_por_motivo")
        minimo_motivo = c.fetchone()["minimo"]
    assert visiveis and min(n for *_, n in visiveis) >= K
    assert minimo_motivo is None or minimo_motivo >= K
    vistas = {(uf, ag) for uf, ag, _ in visiveis}
    for uf in {uf for uf, _, _ in todas}:
        escondidas = [1 for u, ag, _ in todas if u == uf and (u, ag) not in vistas]
        assert len(escondidas) != 1, uf


# ================================================================ pessoa física e custo por responsável
def test_pessoa_fisica_nunca_chega_ao_n2(acervo):
    painel = acervo.painel(BIA_N2, 2)
    vistos = [r for p in painel.pendencias for r in acervo.responsaveis_da_pendencia(painel, BIA_N2, p.codigo)]
    assert vistos and all(r.nivel_minimo == 2 for r in vistos)
    assert any(r.nivel_minimo == 3 for r in acervo.repo.responsaveis(3, "SP"))      # existem, mas não descem


def test_nome_de_pessoa_no_gerador_e_sempre_nivel_3():
    """Empresário individual conta como pessoa física. O gerador só nomeia pessoa no
    proprietário atual (nível 3); razão social nunca carrega prenome + sobrenome."""
    prenomes = set(sinteticos._PRENOMES)
    _, responsaveis = sinteticos.gerar()
    for r in responsaveis:
        if r.nome.split()[0] in prenomes:
            assert r.nivel_minimo == 3, r


def test_matriz_soma_por_responsavel_so_no_n3():
    decidir = autorizacao.decidir
    for papel in Papel:
        if papel is Papel.ADMINISTRADOR:
            continue
        for classificacao in Classificacao:
            efeito = decidir(papel, classificacao, Operacao.SOMAR_POR_RESPONSAVEL).efeito
            # A camada 3 (ministro e Ministério Público); antes, "nível >= 3"
            esperado = Efeito.PERMITIDO if classificacao is Classificacao.SECRETO and papel.camada == 3 \
                else Efeito.NEGADO
            assert efeito is esperado, (papel, classificacao)
    assert decidir(Papel.DIRETOR, Classificacao.RESERVADO, Operacao.SOMAR_POR_RESPONSAVEL).motivo ==         "RESPONSAVEL_SO_NO_NIVEL_3"


def test_custo_por_responsavel_no_n2_e_recusado_e_registrado(acervo):
    painel = acervo.painel(BIA_N2, 2)
    with pytest.raises(ErroAcervo, match="não faz parte deste acesso"):      # Sem citar o N3
        acervo.custo_por_responsavel(painel, BIA_N2)
    ultimo = acervo.trilha.recentes(1)[0].evento
    assert ultimo.resultado == "NEGADO" and ultimo.motivo == "RESPONSAVEL_SO_NO_NIVEL_3"


def test_ministro_nem_abre_o_painel_do_n2(acervo):
    """Escopo exclusivo: o ministro nem abre a camada 2. A recusa fica na trilha."""
    with pytest.raises(ErroAcervo):
        acervo.painel(CAIO_N3, 2)
    ultimo = acervo.trilha.recentes(1)[0].evento
    assert (ultimo.resultado, ultimo.motivo, ultimo.usuario_id) == ("NEGADO", "NIVEL_INSUFICIENTE", CAIO_N3.id)


def test_custo_por_responsavel_no_n3_soma_so_ativas_cobraveis_e_registra(acervo):
    from ecosec.acervo import regras
    painel = acervo.painel(CAIO_N3, 3)
    linhas = acervo.custo_por_responsavel(painel, CAIO_N3)
    assert linhas and [l.custo for l in linhas] == sorted((l.custo for l in linhas), reverse=True)
    assert all(set(l.vinculos) <= set(analise.VINCULOS_COBRAVEIS) for l in linhas)
    cobraveis = [p for p in painel.pendencias
                 if p.ativa(HOJE) and regras.grupo_do_motivo(p.motivo) == "Cobrável do responsável"]
    total = sum(regras.custo_estimado(p, painel.regras) for p in cobraveis)
    assert sum(l.custo for l in linhas) >= total * 0.999        # solidária: cada corresponsável soma o caso
    assert acervo.trilha.recentes(1)[0].evento.motivo == "CUSTO_POR_RESPONSAVEL"


def test_resumo_agregado_nao_agrupa_por_nome_de_responsavel():
    assert not any("RESPONSAVEL" in g and "RESPONSABILIDADE" not in g for g in analise.AGRUPAMENTOS)


# ================================================================ volume coerente
@pytest.fixture(scope="module")
def gerado():
    return sinteticos.gerar()


def test_toda_quantidade_dentro_da_faixa_do_par_e_na_unidade_da_classe(gerado):
    for p in gerado[0]:
        mediana, sigma, minimo, maximo = sinteticos.QUANTIDADE_POR_PAR[(p.atividade, p.classe_risco)]
        assert minimo <= p.quantidade <= maximo, p.codigo
        # área contaminada em m³ de solo e rejeito em m³; só Classe I em toneladas
        esperada = sinteticos.TONELADAS if p.classe_risco == "CLASSE I NBR 10004" else sinteticos.METROS_CUBICOS
        assert p.unidade == esperada, p.codigo


def test_mediana_por_par_segue_o_parametro(gerado):
    from statistics import median
    por_par = {}
    for p in gerado[0]:
        por_par.setdefault((p.atividade, p.classe_risco), []).append(p.quantidade)
    for par, valores in por_par.items():
        if len(valores) >= 30:
            alvo = sinteticos.QUANTIDADE_POR_PAR[par][0]
            assert alvo / 1.5 <= median(valores) <= alvo * 1.5, par


def test_area_contaminada_deixou_de_ter_volume_de_dois_caminhoes(gerado):
    from statistics import median
    assert median(p.quantidade for p in gerado[0] if p.classe_risco == "AREA CONTAMINADA") >= 300


def test_mudar_o_volume_nao_mexe_em_mais_nada_do_acervo(monkeypatch, gerado):
    """O quantil consome UM sorteio, como o uniform de antes: datas, lugares e responsáveis não mudam."""
    dobrado = {par: (m * 2, s, lo, hi * 2) for par, (m, s, lo, hi) in sinteticos.QUANTIDADE_POR_PAR.items()}
    monkeypatch.setattr(sinteticos, "QUANTIDADE_POR_PAR", dobrado)
    outro, responsaveis = sinteticos._gerar.__wrapped__(len(gerado[0]), CFG["geracao.modo"])   # sem o cache
    from dataclasses import replace
    assert [p.quantidade for p in outro] != [p.quantidade for p in gerado[0]]           # regenerou de fato
    assert [replace(p, quantidade=0) for p in outro] == [replace(p, quantidade=0) for p in gerado[0]]
    assert list(responsaveis) == gerado[1]


def test_preparar_banco_aponta_volume_fora_da_faixa():
    from ferramentas.preparar_banco import incoerencias_de_volume
    certo = ("PD-1", "AG-06", "CLASSE I NBR 10004", 5.0, sinteticos.TONELADAS)
    fora = ("PD-2", "AG-06", "CLASSE I NBR 10004", 900.0, sinteticos.TONELADAS)
    unidade = ("PD-3", "AG-08", RADIOATIVO, 0.3, sinteticos.TONELADAS)
    area_em_t = ("PD-4", "AG-01", "AREA CONTAMINADA", 250.0, sinteticos.TONELADAS)
    area_certa = ("PD-5", "AG-01", "AREA CONTAMINADA", 250.0, sinteticos.METROS_CUBICOS)
    assert incoerencias_de_volume([certo, fora, unidade, area_em_t, area_certa]) == ["PD-2", "PD-3", "PD-4"]


def test_volume_do_banco_real_de_teste_e_coerente(acervo_mysql):
    from ferramentas.preparar_banco import SQL_VOLUME, incoerencias_de_volume
    with acervo_mysql.transacao() as c:
        c.execute(SQL_VOLUME)
        linhas = [(r["codigo"], r["atividade"], r["classe_risco"], r["quantidade"], r["unidade"]) for r in c.fetchall()]
    assert linhas and incoerencias_de_volume(linhas) == []


# ================================================================ custo por componente
from ecosec.acervo import custos, regras  # noqa: E402

R = regras.ParametrosRegras.de_configuracao(CFG)


def test_transicao_variaveis_da_rota_padrao_somam_o_custo_unitario_antigo():
    # a área é cobrada por m³ de solo: a referência antiga (R$ 1.200 por t) passa pelo fator documentado
    antigos = {"CLASSE I NBR 10004": 2800.0, "AREA CONTAMINADA": 1200.0 * R.custos.densidade_solo,
               RADIOATIVO: 180000.0}
    for classe, unitario in antigos.items():
        assert R.custos.rotas[R.custos.rota_padrao[classe]].unitario == pytest.approx(unitario), classe
    assert R.custos.densidade_solo == pytest.approx(1.8)


# ================================================================ regra: nenhum total soma unidades diferentes
def test_somar_recusa_unidades_ou_classes_misturadas(gerado):
    from ecosec.acervo import quantidades
    classe_i = next(p for p in gerado[0] if p.classe_risco == "CLASSE I NBR 10004")
    area = next(p for p in gerado[0] if p.classe_risco == "AREA CONTAMINADA")
    rejeito = next(p for p in gerado[0] if p.classe_risco == RADIOATIVO)
    with pytest.raises(quantidades.UnidadesMisturadas):
        quantidades.somar([classe_i, area])                   # t com m³
    with pytest.raises(quantidades.UnidadesMisturadas):
        quantidades.somar([area, rejeito])                    # m³ de solo com m³ de rejeito: classes diferentes
    assert quantidades.somar([area, area]) == round(2 * area.quantidade, 2)


def test_relatorios_e_analises_nao_somam_quantidade_por_conta_propria():
    """Toda soma de `p.quantidade` passa por acervo/quantidades.py, que recusa a mistura de unidades."""
    import ast
    from pathlib import Path
    raiz = Path(__file__).resolve().parent.parent / "ecosec"
    achados = []
    for arquivo in raiz.rglob("*.py"):
        if arquivo.name == "quantidades.py":
            continue
        for no in ast.walk(ast.parse(arquivo.read_text(encoding="utf-8"))):
            if isinstance(no, ast.Call) and getattr(no.func, "id", None) == "sum" and any(
                    isinstance(sub, ast.Attribute) and sub.attr == "quantidade" for sub in ast.walk(no)):
                achados.append(f"{arquivo.relative_to(raiz)}:{no.lineno}")
    assert achados == []


def test_resumo_tem_uma_coluna_de_quantidade_por_classe_e_unidade(acervo):
    titulos, linhas = acervo.resumo_agregado(CAIO_N3, 3).tabelas["POR UF"]
    assert {"TONELADAS CLASSE I", "M3 SOLO AREA CONTAMINADA", "M3 REJEITO RADIOATIVO"} <= set(titulos)
    assert "TONELADAS" not in titulos and "METROS CUBICOS" not in titulos       # nenhuma coluna mista
    ativas = [p for p in sinteticos.gerar()[0] if p.ativa(HOJE)]
    i = titulos.index("M3 SOLO AREA CONTAMINADA")
    esperado = sum(p.quantidade for p in ativas if p.classe_risco == "AREA CONTAMINADA")
    assert sum(l[i] for l in linhas) == pytest.approx(esperado, rel=1e-6)


def test_relatorios_mostram_cada_classe_com_a_sua_unidade():
    from ecosec.acervo import relatorios
    cartoes = dict(relatorios._cartoes_de_volume(sinteticos.gerar()[0]))
    assert cartoes["de resíduo Classe I"].endswith(" t")
    assert cartoes["de solo em áreas contaminadas"].endswith(" m³")
    assert cartoes["de rejeito radioativo (CNEN)"].endswith(" m³")


def test_memoria_de_calculo_soma_exatamente_o_custo_estimado(gerado):
    for p in gerado[0][:400]:
        memoria = regras.memoria_de_calculo(p, R)
        assert memoria and regras.custo_estimado(p, R) == round(sum(c.valor for c in memoria), 2)
        assert all(c.fonte for c in memoria)


def test_rotas_forcadas_pela_substancia(gerado):
    rota = {p.substancia: custos.rota_de(p, R.custos).nome for p in gerado[0]}
    assert rota["ASCAREL PCBS EM TRANSFORMADORES"] == "INCINERACAO"
    assert rota["REJEITO COM URANIO E TORIO NORM"] == "ARMAZENAMENTO DE NORM"
    assert rota["HIDROCARBONETOS EM FASE LIVRE"] == "REMEDIACAO COM BOMBEAMENTO"
    assert rota["BORRA DE FUNDO DE TANQUE"] == "COPROCESSAMENTO"                # sem regra: padrão da classe


def test_monitoramento_da_area_e_a_mediana_da_etapa_no_ciclo_de_vida():
    from ecosec.acervo.geracao import ciclo
    etapas, medianas, _ = ciclo.CICLOS["AREA"]
    assert R.custos.rotas["REMEDIACAO EX SITU"].anos_monitoramento == medianas[etapas.index("MONITORAMENTO")]


def test_rota_sem_fonte_e_recusada_na_carga():
    class Cfg:
        def secao(self, _):
            return {"data_base_valores": "2026-10", "rota_padrao": {"X": "R"},
                    "rotas": {"R": {"variaveis": [["A", 1.0]], "fonte": " "}}}
    with pytest.raises(ValueError, match="sem fonte"):
        custos.ParametrosCustos.de_configuracao(Cfg())


def test_rota_inexistente_e_recusada_na_carga():
    class Cfg:
        def secao(self, _):
            return {"data_base_valores": "2026-10", "rota_padrao": {"X": "NAO EXISTE"},
                    "rotas": {"R": {"variaveis": [["A", 1.0]], "fonte": "PARAMETRO"}}}
    with pytest.raises(ValueError, match="NAO EXISTE"):
        custos.ParametrosCustos.de_configuracao(Cfg())


def test_toda_substancia_gerada_tem_rota(gerado):
    for p in gerado[0]:
        assert custos.rota_de(p, R.custos).nome in R.custos.rotas


# ================================================================ latência mínima
def test_nenhuma_encerrada_antes_da_latencia_da_sua_linha(gerado):
    from ecosec.acervo.geracao import saidas, series
    latencia = {linha: s.latencia for linha, s in saidas.configuradas().items()}
    for p in gerado[0]:
        if p.data_encerramento:
            duracao = (p.data_encerramento - p.data_identificacao).days / 365.25
            assert duracao >= latencia[series.linha_de(p.atividade, p.classe_risco, p.motivo)] - 2 / 365, p.codigo


def test_nenhuma_area_contaminada_encerra_em_menos_de_dois_anos(gerado):
    curtas = [p.codigo for p in gerado[0] if p.classe_risco == "AREA CONTAMINADA" and p.data_encerramento
              and (p.data_encerramento - p.data_identificacao).days < 2 * 365]
    assert curtas == []


def test_latencia_vem_da_configuracao_de_cada_linha():
    from ecosec.acervo.geracao import saidas
    linhas = saidas.configuradas()
    assert linhas["AREA"].latencia == linhas["POSTOS"].latencia == 2.0
    assert linhas["MTR SEM BAIXA"].latencia < linhas["CLASSE I"].latencia < linhas["ATERROS"].latencia


def test_saida_sem_ninguem_elegivel_e_contada_e_nao_inventada():
    import random
    from ecosec.acervo.geracao import fluxos

    class R:
        def __init__(self, entrada):
            self.entrada, self.saida = entrada, None
    novos = [R(2020.5) for _ in range(5)]
    faltaram = fluxos.sortear_saidas(novos, {2020: 3, 2021: 2}, random.Random(1), 2026.0, latencia=2.0)
    assert faltaram == 5 and all(r.saida is None for r in novos)
    antigos = [R(2015.0) for _ in range(5)]
    assert fluxos.sortear_saidas(antigos, {2020: 3}, random.Random(1), 2026.0, latencia=2.0) == 0
    assert sum(r.saida is not None for r in antigos) == 3


def test_latencia_nao_muda_quantos_saem(gerado):
    """A calibração decide quantos saem por ano; a latência só decide quem."""
    encerradas = sum(1 for p in gerado[0] if p.data_encerramento)
    assert encerradas == 1372                           # Era 1.345


# ================================================================ KPI-01 por Kaplan-Meier
def test_kaplan_meier_conta_as_censuradas():
    # eventos em 1 e 2 anos; duas ainda ativas há 5. Mediana só das encerradas = 1,5; com censura = 2.
    curva = analise.kaplan_meier([(1, True, 0), (2, True, 0), (5, False, 0), (5, False, 0)])
    assert curva == [(1, 0.75), (2, 0.5)]
    assert analise._primeiro_abaixo(curva, 0.5) == 2


def test_kaplan_meier_com_entrada_tardia():
    # quem entrou na observação já com 3 anos não está em risco em t = 1 (truncamento à esquerda)
    curva = analise.kaplan_meier([(1, True, 0), (4, True, 3), (6, False, 0)])
    assert curva[0] == (1, pytest.approx(1 - 1 / 2))             # em risco em t=1: só os dois de entrada 0
    assert curva[1] == (4, pytest.approx(0.5 * (1 - 1 / 2)))     # em t=4: o de entrada 3 e o censurado em 6


def test_kpi01_no_acervo_e_maior_que_a_mediana_ingenua(gerado):
    from statistics import median
    for classe in ("AREA CONTAMINADA", "CLASSE I NBR 10004"):
        km = analise.tempo_ate_encerramento(gerado[0], HOJE, classe)
        ingenua = median((p.data_encerramento - p.data_identificacao).days / 365.25 for p in gerado[0]
                         if p.classe_risco == classe and p.encerrada(HOJE))
        assert km.mediana is not None and km.mediana > ingenua, classe
        assert km.eventos + km.censuradas == sum(p.classe_risco == classe for p in gerado[0])


def test_kpi01_p90_nao_atingido_vira_none(gerado):
    km = analise.tempo_ate_encerramento(gerado[0], HOJE, "AREA CONTAMINADA")
    assert km.p90 is None                                          # a curva não chega a 90% encerradas


# ================================================================ série anual sem ano fixo
def _sql_da_serie():
    from pathlib import Path
    sql = (Path(__file__).resolve().parent.parent / "sql" / "acervo" / "01_schema.sql").read_text(encoding="utf-8")
    inicio = sql.index("CREATE OR REPLACE VIEW vw_fluxo_estoque_anual")
    return sql[inicio:sql.index(";", inicio)]


def test_serie_anual_vai_ate_o_ano_corrente_sem_numero_fixo():
    import re
    trecho = _sql_da_serie()
    assert "YEAR(CURRENT_DATE)" in trecho
    assert not re.search(r"ano\s*<\s*20\d\d", trecho)


def test_serie_anual_no_mysql_termina_no_ano_corrente(acervo_mysql):
    from datetime import date
    with acervo_mysql.transacao() as c:
        c.execute("SELECT MIN(ano) AS primeiro, MAX(ano) AS ultimo FROM vw_fluxo_estoque_anual")
        linha = c.fetchone()
    assert (linha["primeiro"], linha["ultimo"]) == (2006, date.today().year)


# ================================================================ termo 3.1 e a 3.0 arquivada
# hashes da 3.0 calculados pelo código antes de a 3.1 existir (contato não preenchido com que a 3.0 sempre saiu)
HASHES_V3_0 = {None: "3f39c3262a49428cfe68f9b0539918ce45cac6c52d95806273b007ae11bf02f0",
               True: "2dbe748462dec89212c2c006d19815d16d74b46e773b0870b47edda13440943e",
               False: "08f322d782310b348b0699e7cbfc36e1db3d044ca945be1955f9046f30f059bb"}


@pytest.mark.parametrize("escolha", [None, True, False])
def test_termo_3_0_arquivado_reproduz_os_hashes(escolha):
    from ecosec.dominio import termo, termo_v3_0
    texto = termo_v3_0.renderizar("Ana Lima", termo_v3_0.CONTATO, escolha)
    assert termo.calcular_hash(texto) == HASHES_V3_0[escolha]


def test_aceite_3_0_confere_com_qualquer_contato_configurado_hoje():
    from ecosec.dominio import termo
    for contato in (CFG["lgpd.contato"], "outro@exemplo.edu"):
        assert termo.confere("3.0", "Ana Lima", contato, True, HASHES_V3_0[True]) is True


def test_termo_vigente_e_3_4_com_contato_e_sem_rodape_de_simulado():
    """A 3.4 tira o rodapé de documento simulado; a 3.3 foi arquivada em termo_v3_3.py. Os
    pedidos do TITULAR continuam indo ao administrador (Cláusula 6ª e quadro-resumo)."""
    from ecosec.dominio import termo
    assert termo.VERSAO == CFG["lgpd.versao_termo"] == "3.4"
    contato = CFG["lgpd.contato"]
    assert "preencher" not in contato and "@" in contato
    texto = termo.renderizar("Ana Lima", contato, True)
    assert contato in texto and texto.endswith("Finalidade (b): AUTORIZO.")
    assert "DOCUMENTO SIMULADO" not in texto and "simulado" not in texto
    assert "DOCUMENTO SIMULADO" not in termo.renderizar_html("Ana Lima", contato, True)
    assert "requisição ao administrador do sistema" in texto and "junto ao administrador" in texto
    assert not hasattr(termo, "RODAPE_SIMULADO") and not hasattr(termo, "MARCACAO_SIMULADO")


def test_3_1_e_3_0_tem_hashes_diferentes_para_o_mesmo_aceite():
    from ecosec.dominio import termo, termo_v3_0, termo_v3_1
    h31 = termo.calcular_hash(termo_v3_1.renderizar("Ana Lima", termo_v3_0.CONTATO, True))
    assert h31 != HASHES_V3_0[True]
    assert termo.confere("3.1", "Ana Lima", termo_v3_0.CONTATO, True, HASHES_V3_0[True]) is False


# ================================================================ tela de custo por responsável (N3)
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


def _abas(painel_analitico) -> set:
    return {chave for chave, _ in painel_analitico.SECOES if chave in painel_analitico.abas.items}


def test_n3_ve_a_tela_com_a_lista_e_a_memoria_de_calculo(tela, qt):
    from ecosec.dominio.niveis import Nivel
    tela.iniciar(CAIO_N3, Nivel.N3)
    tela.mostrar_modo("painel")
    pa = tela.painel_analitico
    assert "responsaveis" in _abas(pa)
    pa.mostrar("responsaveis")
    qt.processEvents()
    assert pa.pilha.currentWidget() is pa.responsaveis.property("cartao")
    tela_resp = pa.responsaveis
    assert tela_resp.linhas and tela_resp.modelo.rowCount() == len(tela_resp.linhas)
    tela_resp.mostrar_memoria(0)
    html = tela_resp.memoria.toPlainText()
    primeiro = tela_resp.linhas[0]
    assert primeiro.nome in html and "rota:" in html and "Total do caso" in html          # "caso"
    assert "PARAMETRO" not in html and "Fonte" not in html                # sem a fonte
    motivos = [r.evento.motivo for r in tela.app.acervo.trilha.recentes(50)]
    assert "CUSTO_POR_RESPONSAVEL" in motivos and "MEMORIA_CUSTO_RESPONSAVEL" in motivos


def test_memoria_da_tela_soma_o_custo_do_responsavel(tela, qt):
    from ecosec.dominio.niveis import Nivel
    tela.iniciar(CAIO_N3, Nivel.N3)
    tela.mostrar_modo("painel")
    pa = tela.painel_analitico
    resp = pa.responsaveis.linhas[0]
    itens = tela.app.acervo.memoria_por_responsavel(pa.painel, CAIO_N3, resp.nome)
    assert [i.codigo for i in itens] == list(resp.codigos)
    assert sum(i.total for i in itens) == pytest.approx(resp.custo)
    for i in itens:
        assert sum(c.valor for c in i.componentes) == pytest.approx(i.total)


def test_n2_nao_ve_a_tela_e_a_tentativa_fica_na_trilha(tela, qt):
    from ecosec.dominio.niveis import Nivel
    tela.iniciar(BIA_N2, Nivel.N2)
    tela.mostrar_modo("painel")
    pa = tela.painel_analitico
    if not pa.carregado:
        pa.carregar()
    assert "responsaveis" not in _abas(pa)                               # não aparece nas abas do N2
    antes = pa.pilha.currentWidget()
    pa.mostrar("responsaveis")                                            # tentativa direta (atalho, código)
    qt.processEvents()
    assert pa.pilha.currentWidget() is antes                              # a página não abre
    assert pa.responsaveis.modelo.rowCount() == 0 and not pa.responsaveis.linhas
    ultimo = tela.app.acervo.trilha.recentes(1)[0].evento
    assert (ultimo.resultado, ultimo.motivo) == ("NEGADO", "RESPONSAVEL_SO_NO_NIVEL_3")
    assert ultimo.usuario_id == BIA_N2.id


def test_memoria_por_responsavel_tambem_negada_fora_do_n3():
    from ecosec.repositorios.memoria import RepositorioAcervoMemoria, RepositorioTrilhaMemoria
    from ecosec.servicos.trilha import ServicoTrilha
    s = ServicoAcervo.de_configuracao(CFG, RepositorioAcervoMemoria(), ServicoTrilha(RepositorioTrilhaMemoria()),
                                      b"chave-teste", relogio=lambda: datetime(2026, 10, 1, 10, 0))
    s.data_referencia = HOJE
    painel = s.painel(BIA_N2, 2)
    with pytest.raises(ErroAcervo):
        s.memoria_por_responsavel(painel, BIA_N2, "QUALQUER NOME")
    assert s.trilha.recentes(1)[0].evento.motivo == "RESPONSAVEL_SO_NO_NIVEL_3"
