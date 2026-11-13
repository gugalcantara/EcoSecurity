"""A ficha da pendência.

Critérios: toda etapa de todo ciclo tem fase (não decresce); o acervo
antigo sai idêntico, sem campo novo; a soma das categorias é o custo; a ficha tem "Fase:", "Contaminante:",
"Restrição de uso:", "Uso anterior:" e "Uso pretendido:", com a memória de cálculo por categoria, no N2 e no N3;
custo por responsável e pessoa física continuam só no N3; a exportação da ficha sai crua, com os campos novos.

Os testes da ficha NA tela (campos novos e memória, responsáveis fora do N2, exportação pela tela) estão em
test_n23.py; a recusa do custo por responsável no N2 está em test_regras_acervo.py. Aqui ficam o acervo
(com o hash), os catálogos e a exportação pelo serviço.
"""
import csv
import dataclasses
import hashlib
import io
import random
from datetime import datetime

import pytest

from ecosec.acervo import custos, fase, ficha, formatos, regras, sinteticos
from ecosec.acervo.geracao.ciclo import CICLOS
from ecosec.configuracao import carregar
from ecosec.dominio.acervo import Pendencia
from ecosec.dominio.entidades import Usuario
from ecosec.repositorios.memoria import RepositorioAcervoMemoria, RepositorioTrilhaMemoria
from ecosec.servicos.acervo import ErroAcervo, ServicoAcervo, VerificacaoNecessaria
from ecosec.servicos.trilha import ServicoTrilha

CFG = carregar()
HOJE = sinteticos.DATA_BASE
AGORA = datetime(2026, 10, 1, 10, 0)
BIA_N2 = Usuario(matricula="BIA", nome="Bia", nivel=2, uf="SP", senha_hash="$2b$x", id=2)
CAIO_N3 = Usuario(matricula="CAIO", nome="Caio", nivel=3, senha_hash="$2b$x", id=3)
TRAVESSOES = ("—", "–")
ROTULOS_FICHA = ("Fase:", "Contaminante:", "Meio afetado:", "Restrição de uso:", "Uso anterior:", "Uso pretendido:")

# Instantâneo do acervo: SHA-256 do repr de dataclasses.astuple de cada pendência e de cada responsável, na ordem
# de sinteticos.gerar(). Qualquer mudança no gerador ou na geografia muda o hash: confira e atualize.
HASH_PENDENCIAS = "d0d8863250e5cf6bdbcd11b4abae46d74bcc8373f2905b421f38173bf45c6772"
HASH_RESPONSAVEIS = "87bf928691315247589d3dc490f245086a257b6b6ab2bcccd91a8480f91cbf78"
CAMPOS_PENDENCIA = ("codigo", "substancia", "classe_risco", "quantidade", "unidade", "uf", "municipio", "logradouro",
                    "numero", "complemento", "bairro", "cep", "latitude", "longitude", "data_identificacao",
                    "prazo_coleta", "situacao", "atividade", "motivo", "sintetico", "fonte", "data_encerramento",
                    "etapa_atual", "etapas")


def _hash(itens) -> str:
    m = hashlib.sha256()
    for x in itens:
        m.update(repr(dataclasses.astuple(x)).encode("utf-8"))
        m.update(b"\n")
    return m.hexdigest()


@pytest.fixture(scope="module")
def base():
    return sinteticos.gerar()


@pytest.fixture(scope="module")
def r():
    return regras.ParametrosRegras.padrao()


@pytest.fixture
def acervo():
    trilha = ServicoTrilha(RepositorioTrilhaMemoria())
    servico = ServicoAcervo.de_configuracao(CFG, RepositorioAcervoMemoria(), trilha, b"chave-teste",
                                            relogio=lambda: AGORA)
    servico.data_referencia = HOJE
    return servico


def _substancias() -> dict:
    """substância -> classe, como o gerador sorteia (sinteticos.PERFIS)."""
    pares = [(s, c) for _, substancias, _, _ in sinteticos.PERFIS.values() for s, c in substancias]
    assert len({s for s, _ in pares}) == len(pares)            # cada substância numa só classe
    return dict(pares)


# acervo antigo idêntico
def test_acervo_identico_ao_de_antes_do_bloco_5(base):
    pendencias, responsaveis = base
    assert len(pendencias) == 2400
    assert _hash(pendencias) == HASH_PENDENCIAS
    assert _hash(responsaveis) == HASH_RESPONSAVEIS


def test_nenhum_campo_novo_na_pendencia():
    assert tuple(f.name for f in dataclasses.fields(Pendencia)) == CAMPOS_PENDENCIA


def test_derivar_a_ficha_nao_muda_o_acervo_nem_o_gerador_global(base, r):
    estado = random.getstate()
    for p in base[0]:
        ficha.atributos(p, r.custos)
    assert random.getstate() == estado                          # nada sorteado no gerador global
    novas, responsaveis = sinteticos._gerar.__wrapped__(2400, "estratificado")   # geração nova, sem cache
    assert _hash(novas) == HASH_PENDENCIAS and _hash(responsaveis) == HASH_RESPONSAVEIS


# fase
def test_toda_etapa_de_todo_ciclo_tem_fase_e_a_fase_nao_decresce():
    for nome, (etapas, _, _) in CICLOS.items():
        ordem = [fase.FASES.index(fase.fase_da_etapa(e)) for e in etapas]
        assert ordem == sorted(ordem), nome
        assert fase.fase_da_etapa(etapas[-1]) == fase.ENCERRADA


# contaminante e meio
def test_catalogo_de_contaminantes_cobre_exatamente_as_substancias_do_gerador():
    substancias = _substancias()
    assert len(substancias) == 33
    assert not set(substancias) - set(ficha.CONTAMINANTE), "substância do gerador sem contaminante"
    assert not set(ficha.CONTAMINANTE) - set(substancias), "entrada sobrando no catálogo de contaminantes"


def test_contaminante_e_meio_coerentes_com_a_classe():
    for substancia, classe in _substancias().items():
        grupo, meio = ficha.CONTAMINANTE[substancia]
        assert grupo in ficha.GRUPOS, substancia
        assert meio in ficha.MEIOS_DA_CLASSE[classe], (substancia, classe, meio)
        assert (grupo in ficha.GRUPOS_RADIOATIVOS) == (classe == sinteticos.RADIOATIVO), substancia
    assert set(ficha.GRUPOS) == {g for g, _ in ficha.CONTAMINANTE.values()}      # nenhum grupo sem uso


def test_substancia_fora_do_catalogo_nao_e_adivinhada(base):
    p = dataclasses.replace(base[0][0], substancia="SUBSTANCIA INVENTADA")
    with pytest.raises(ficha.SemCatalogo):
        ficha.contaminante(p)


# restrição de uso
def test_tabela_de_restricao_completa_para_classe_fase_e_meio():
    classes = tuple(ficha.MEIOS_DA_CLASSE)
    assert set(ficha.RESTRICAO_BASE) == {(c, f) for c in classes for f in fase.FASES}
    for classe, meios in ficha.MEIOS_DA_CLASSE.items():
        for f in fase.FASES:
            for meio in meios:
                texto = ficha.restricao_de(classe, f, meio)
                assert texto and texto == texto.upper() and not any(t in texto for t in TRAVESSOES)
                assert texto.startswith(ficha.RESTRICAO_BASE[(classe, f)])


def test_restricao_segue_a_fase_e_o_meio():
    assert "CAPTACAO DE AGUA SUBTERRANEA" in ficha.restricao_de(sinteticos.AREA, fase.REMEDIACAO, ficha.AGUA)
    assert "ESCAVACAO" in ficha.restricao_de(sinteticos.AREA, fase.IDENTIFICACAO, ficha.SOLO)
    assert ficha.restricao_de(sinteticos.AREA, fase.ENCERRADA, ficha.SOLO) == "USO LIMITADO AO DECLARADO NA REABILITACAO"
    assert ficha.restricao_de(sinteticos.CLASSE_I, fase.ENCERRADA, ficha.EQUIPAMENTO).startswith("SEM RESTRICAO")
    assert "CNEN" in ficha.restricao_de(sinteticos.RADIOATIVO, fase.INVESTIGACAO, ficha.FONTE)


# uso anterior
def test_toda_atividade_tem_uso_anterior_e_nada_sobra():
    codigos = {a.codigo for a in sinteticos.ATIVIDADES}
    assert len(codigos) == 13 and set(ficha.USO_ANTERIOR) == codigos
    assert {a.codigo for a in RepositorioAcervoMemoria().atividades()} == codigos      # o catálogo do repositório
    assert all(v and v == v.upper() for v in ficha.USO_ANTERIOR.values())


def test_atividade_fora_do_catalogo_nao_e_adivinhada(base):
    with pytest.raises(ficha.SemCatalogo):
        ficha.uso_anterior(dataclasses.replace(base[0][0], atividade="AG-99"))


# uso pretendido
def test_uso_pretendido_so_na_area_contaminada(base):
    for p in base[0]:
        uso = ficha.uso_pretendido(p)
        if p.classe_risco == sinteticos.AREA:
            assert uso in ficha.USOS_PRETENDIDOS
        else:
            assert uso == formatos.NAO_SE_APLICA == "não se aplica"


def test_uso_pretendido_deterministico_e_so_do_codigo(base):
    areas = [p for p in base[0] if p.classe_risco == sinteticos.AREA]
    primeira = [ficha.uso_pretendido(p) for p in areas]
    random.seed(12345)                                           # mexer no gerador global não muda nada
    assert [ficha.uso_pretendido(p) for p in reversed(areas)][::-1] == primeira
    p = areas[0]
    outro = dataclasses.replace(p, uf="AC", quantidade=1.0, atividade="AG-13", substancia=areas[-1].substancia)
    assert ficha.uso_pretendido(outro) == ficha.uso_pretendido(p)
    assert ficha.semente_uso_pretendido(p.codigo) == ficha.semente_uso_pretendido(p.codigo)
    assert ficha.semente_uso_pretendido(p.codigo) != sinteticos.SEMENTE
    assert len(set(primeira)) == 3                               # os três cenários aparecem


# todas as pendências e
def test_toda_pendencia_tem_todos_os_atributos(base, r):
    for p in base[0]:
        a = ficha.atributos(p, r.custos)
        assert a.fase in fase.FASES and a.grupo_contaminante and a.meio and a.restricao and a.uso_anterior
        assert a.uso_pretendido in (*ficha.USOS_PRETENDIDOS, formatos.NAO_SE_APLICA)


def test_soma_das_categorias_e_o_custo_de_cada_pendencia(base, r):
    for p in base[0]:
        m = ficha.memoria(p, r.custos)
        assert tuple(c.nome for c in m.categorias) == custos.CATEGORIAS_EEA
        assert abs(sum(c.total for c in m.categorias) - regras.custo_estimado(p, r)) <= 0.01, p.codigo
        assert m.total == regras.custo_estimado(p, r)
        for cat in m.categorias:
            assert all(x.categoria == cat.nome for x in cat.componentes)
            assert abs(sum(x.valor for x in cat.componentes) - cat.total) <= 0.01
            assert {cat.nome: cat.total for cat in m.categorias} == custos.por_categoria(p, r.custos)
        assert m.data_base == r.custos.data_base == "2026-10" and m.fonte == ficha.PARAMETRO


# exportação (serviço)
def _csv(caminho) -> dict:
    linhas = list(csv.reader(io.StringIO(caminho.read_bytes().decode("utf-8-sig")), delimiter=";"))
    assert len(linhas) == 2
    return dict(zip(linhas[0], linhas[1]))


def test_exportacao_da_ficha_crua_com_os_campos_novos(acervo, tmp_path, r):
    painel = acervo.painel(BIA_N2, 2)
    p = next(x for x in painel.pendencias if x.classe_risco == sinteticos.AREA)
    destino = tmp_path / "ficha.csv"
    resumo = acervo.exportar_ficha(painel, BIA_N2, p.codigo, destino, verificado_em=AGORA)
    assert hashlib.sha256(destino.read_bytes()).hexdigest() == resumo
    linha = _csv(destino)
    for titulo in ficha.TITULOS_EXPORTACAO:
        assert titulo in linha
    a = ficha.atributos(p, r.custos)
    assert linha["FASE"] == a.fase and linha["GRUPO DO CONTAMINANTE"] == a.grupo_contaminante
    assert linha["RESTRICAO DE USO"] == a.restricao and linha["FONTE DA RESTRICAO"] == "PARAMETRO"
    assert linha["USO ANTERIOR"] == a.uso_anterior and linha["USO PRETENDIDO"] in ficha.USOS_PRETENDIDOS
    soma = sum(float(linha[f"CUSTO {c}"]) for c in custos.CATEGORIAS_EEA)
    assert soma == pytest.approx(float(linha["CUSTO ESTIMADO"]), abs=0.01)
    texto = destino.read_bytes().decode("utf-8-sig")
    assert "R$" not in texto and not any(t in texto for t in TRAVESSOES)          # crua, sem formatação
    assert linha["CUSTO INVESTIGACAO"] == repr(a.memoria.categorias[0].total)     # ponto decimal, sem milhar
    assert linha["DATA BASE DOS VALORES"] == "2026-10" and "INVESTIGACAO|" in linha["MEMORIA DE CALCULO"]
    nomes = {x.nome for x in acervo.repo.responsaveis(3) if x.pendencia_codigo == p.codigo}
    assert not any(nome in texto for nome in nomes)                                # nenhum responsável na ficha
    evento = acervo.trilha.recentes(1)[0].evento
    assert evento.evento == "EXPORTACAO" and evento.motivo == "EXPORTACAO_FICHA" and p.codigo in evento.detalhe


def test_ficha_fora_da_classe_area_exporta_nao_se_aplica(acervo, tmp_path):
    painel = acervo.painel(BIA_N2, 2)
    p = next(x for x in painel.pendencias if x.classe_risco == sinteticos.CLASSE_I)
    acervo.exportar_ficha(painel, BIA_N2, p.codigo, tmp_path / "f.csv", verificado_em=AGORA)
    linha = _csv(tmp_path / "f.csv")
    assert linha["USO PRETENDIDO"] == linha["FONTE DO USO PRETENDIDO"] == "não se aplica"


def test_exportacao_da_ficha_segue_as_regras_da_planilha(acervo, tmp_path):
    painel = acervo.painel(BIA_N2, 2)
    p = painel.pendencias[0]
    with pytest.raises(VerificacaoNecessaria):                   # step-up: rosto conferido há pouco
        acervo.exportar_ficha(painel, BIA_N2, p.codigo, tmp_path / "a.csv")
    fora = next(x for x in sinteticos.gerar()[0] if x.uf != "SP")
    with pytest.raises(ErroAcervo):
        acervo.exportar_ficha(painel, BIA_N2, fora.codigo, tmp_path / "b.csv", verificado_em=AGORA)
    assert acervo.trilha.recentes(1)[0].evento.motivo == "FORA_DO_ESCOPO"
    n3 = acervo.painel(CAIO_N3, 3)
    with pytest.raises(ErroAcervo):
        acervo.exportar_ficha(n3, CAIO_N3, p.codigo, tmp_path / "c.csv", verificado_em=AGORA)
    assert acervo.trilha.recentes(1)[0].evento.motivo == "EXPORTACAO_BLOQUEADA"
    assert not any((tmp_path / n).exists() for n in ("a.csv", "b.csv", "c.csv"))
