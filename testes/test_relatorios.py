"""(relatórios): os nove relatórios redesenhados como relatório executivo.

O desenho é imagem: os testes escutam a Tela (cada texto desenhado, com a caixa que ocupa) e conferem a política
de cada camada, a grade comum (sumário executivo, rodapé com fonte e data de corte), o vocabulário e a segurança
(supressão, tarja, marca d'água), além de nada sair da página nem se sobrepor.
"""
import re
from datetime import datetime

import pytest

from ecosec.acervo import analise, relatorios, sinteticos
from ecosec.acervo.desenho import Fontes, Tela
from ecosec.configuracao import carregar
from ecosec.dominio.entidades import Usuario
from ecosec.repositorios.memoria import RepositorioAcervoMemoria, RepositorioTrilhaMemoria
from ecosec.servicos.acervo import ErroAcervo, ServicoAcervo
from ecosec.servicos.trilha import ServicoTrilha

CFG = carregar()
ANA_N1 = Usuario(matricula="ANA", nome="Ana", nivel=1, senha_hash="$2b$x", id=1)
BIA_N2 = Usuario(matricula="BIA", nome="Bia", nivel=2, uf="SP", senha_hash="$2b$x", id=2)
CAIO_N3 = Usuario(matricula="CAIO", nome="Caio", nivel=3, senha_hash="$2b$x", id=3)
USUARIO = {1: ANA_N1, 2: BIA_N2, 3: CAIO_N3}
CODIGOS = [i.codigo for i in sinteticos.CATALOGO]
NIVEL = {i.codigo: i.nivel_minimo for i in sinteticos.CATALOGO}
DINHEIRO = re.compile(r"R\$")
CNPJ = re.compile(r"\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}")
COORDENADA = re.compile(r"-?\d{1,2}[.,]\d{4,}")


@pytest.fixture(scope="module")
def acervo():
    servico = ServicoAcervo.de_configuracao(CFG, RepositorioAcervoMemoria(), ServicoTrilha(RepositorioTrilhaMemoria()),
                                            b"chave-teste", relogio=lambda: datetime(2026, 10, 25, 10, 0))
    servico.data_referencia = sinteticos.DATA_BASE
    return servico


def _escutar(monkeypatch):
    """Registra (texto, x0, y0, x1, y1) de cada Tela.texto."""
    desenhados = []
    original = Tela.texto

    def escutar(self, x, y, conteudo, tamanho=15, negrito=False, cor=None, sensivel=None, largura_max=None):
        kwargs = {"negrito": negrito, "sensivel": sensivel, "largura_max": largura_max}
        if cor is not None:
            kwargs["cor"] = cor
        altura = original(self, x, y, conteudo, tamanho, **kwargs)
        fonte = self.fonte(tamanho, negrito)
        linhas = self._quebrar(str(conteudo), fonte, largura_max) if largura_max else [str(conteudo)]
        largura = max((self.d.textlength(l, font=fonte) for l in linhas), default=0)
        desenhados.append((str(conteudo), float(x), float(y), float(x) + largura, float(y) + altura))
        return altura
    monkeypatch.setattr(Tela, "texto", escutar)
    return desenhados


@pytest.fixture(scope="module")
def desenhos(acervo):
    """{código: (entrega, [(texto, x0, y0, x1, y1)])}: cada relatório aberto pelo serviço com o usuário do nível."""
    resultado = {}
    with pytest.MonkeyPatch.context() as mp:
        for codigo in CODIGOS:
            textos = _escutar(mp)
            entrega = acervo.abrir(codigo, USUARIO[NIVEL[codigo]], NIVEL[codigo])
            resultado[codigo] = (entrega, list(textos))
            mp.undo()
    return resultado


def _so_textos(desenhos, codigo):
    return [t for t, *_ in desenhos[codigo][1]]


# ================================================================ política do N1
@pytest.mark.parametrize("codigo", [c for c in CODIGOS if NIVEL[c] == 1])
def test_n1_sem_dinheiro_cnpj_nem_coordenada(desenhos, codigo):
    textos = _so_textos(desenhos, codigo)
    assert textos
    assert not [t for t in textos if DINHEIRO.search(t)], "valor em reais no N1"
    assert not [t for t in textos if "custo estimado" in t.lower()]
    assert not [t for t in textos if CNPJ.search(t)], "CNPJ no N1"
    assert not [t for t in textos if COORDENADA.search(t)], "coordenada no N1"
    assert not desenhos[codigo][0].suprimidas            # nada a tarjar: o N1 nem recebe o que é sensível


def test_n1_nao_desenha_nome_nem_endereco(desenhos, acervo):
    """Nenhum nome de responsável, logradouro ou município de caso aparece num relatório do N1."""
    nomes = {r.nome for r in acervo.repo.responsaveis(3)}
    logradouros = {p.logradouro for p in acervo.repo.pendencias()}
    for codigo in (c for c in CODIGOS if NIVEL[c] == 1):
        texto = "\n".join(_so_textos(desenhos, codigo))
        assert not [n for n in nomes if n in texto]
        assert not [l for l in logradouros if l in texto]


# ================================================================ grade comum e vocabulário
@pytest.mark.parametrize("codigo", CODIGOS)
def test_todo_relatorio_tem_sumario_e_rodape_sem_fonte(desenhos, codigo):
    """O rodapé diz quando foi gerado, o escopo e a classificação; sem a linha de fonte,
    sem o código do relatório, sem dizer que os custos são simulados e sem a marcação de documento simulado."""
    textos = _so_textos(desenhos, codigo)
    assert "Sumário executivo" in textos
    assert not [t for t in textos if t.startswith(("Fonte:", "Data de corte:")) or "simulad" in t.lower()]
    assert any(t.startswith("Gerado em ") and "Classificação: " in t for t in textos)
    assert relatorios.CLASSIFICACAO[NIVEL[codigo]] in textos            # selo de classificação
    assert relatorios.titulo(sinteticos.CATALOGO[CODIGOS.index(codigo)]) in textos


@pytest.mark.parametrize("codigo", CODIGOS)
def test_vocabulario_sem_escore_codigo_nem_travessao(desenhos, codigo):
    textos = _so_textos(desenhos, codigo)
    assert not [t for t in textos if "escore" in t.lower() or "criticidade" in t.lower()]
    assert not [t for t in textos if "KPI-0" in t]
    assert not [t for t in textos if re.match(r"^(AG|MP)-\d\d", t)]          # código cru como rótulo
    assert not [t for t in textos if "CLASSE I NBR" in t or "pendência" in t.lower()]
    assert not [t for t in textos if "—" in t or "–" in t]


def test_titulo_de_exibicao_em_linguagem_simples():
    for item in sinteticos.CATALOGO:
        titulo = relatorios.titulo(item)
        assert titulo != titulo.upper() and "criticidade" not in titulo.lower()
        assert re.fullmatch(r"[A-Z0-9 ]+", item.titulo)              # o do banco segue o CHECK de item_acervo
        assert not re.search(r"\b(MP|AG|KPI)-\d", relatorios.descricao(item))


def test_cores_iguais_as_da_simbologia():
    """acervo/ não importa a interface; as tabelas de cor duplicadas têm de continuar iguais."""
    from ecosec.interface.componentes import simbologia

    def rgb(h):
        return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))
    assert relatorios.COR_CATEGORIA == {f: rgb(c) for f, c in simbologia.COR_IDENTIDADE.items()}
    assert relatorios.RAMPA == tuple(rgb(c) for c in simbologia.RAMPA_DENSIDADE)
    assert relatorios.COR_CLASSE == {c: rgb(h) for c, h in simbologia.COR_IDENTIDADE_CLASSE.items()}


# ================================================================ layout
@pytest.mark.parametrize("codigo", CODIGOS)
def test_nada_fora_da_pagina(desenhos, codigo):
    entrega, caixas = desenhos[codigo]
    altura, largura = entrega.imagem.shape[:2]
    assert largura == relatorios.LARGURA and altura >= relatorios.ALTURA_MINIMA
    fora = [(t, x0, x1, y1) for t, x0, _, x1, y1 in caixas
            if x0 < relatorios.MARGEM - 2 or x1 > largura - relatorios.MARGEM + 2 or y1 > altura]
    assert not fora, fora[:5]


@pytest.mark.parametrize("codigo", CODIGOS)
def test_nenhum_texto_sobreposto(desenhos, codigo):
    caixas = [c for c in desenhos[codigo][1] if c[0].strip()]
    sobrepostos = []
    for i, (t1, a0, b0, a1, b1) in enumerate(caixas):
        for t2, c0, d0, c1, d1 in caixas[i + 1:]:
            if min(a1, c1) - max(a0, c0) > 2 and min(b1, d1) - max(b0, d0) > 3:
                sobrepostos.append((t1, t2))
    assert not sobrepostos, sobrepostos[:5]


# ================================================================ segurança preservada
@pytest.mark.parametrize("codigo", [c for c in CODIGOS if NIVEL[c] >= 2])
def test_n2_e_n3_saem_com_marca_de_quem_consultou(desenhos, acervo, codigo):
    entrega = desenhos[codigo][0]
    assert entrega.marcada and acervo.identificar_marca(entrega.imagem).usuario_id == USUARIO[NIVEL[codigo]].id


def test_regioes_sensiveis_marcadas_na_origem():
    """Na visão completa (N3, nacional), cada relatório anota o que a tarja pode esconder."""
    pendencias, responsaveis = sinteticos.gerar()
    por_codigo = {}
    for r in responsaveis:
        por_codigo.setdefault(r.pendencia_codigo, []).append(r)
    ativas = tuple(p for p in pendencias if p.ativa(sinteticos.DATA_BASE))
    dados = relatorios.DadosRelatorio(ativas, {k: tuple(v) for k, v in por_codigo.items()},
                                      {a.codigo: a for a in sinteticos.ATIVIDADES},
                                      {m.codigo: m for m in sinteticos.MOTIVOS}, sinteticos.DATA_BASE, "Nacional",
                                      datetime(2026, 10, 25, 10, 0), nivel=3)
    fontes = Fontes.de_configuracao(CFG)
    itens = {i.codigo: i for i in sinteticos.CATALOGO}

    def rotulos(codigo):
        return {r.rotulo for r in relatorios.gerar(itens[codigo], dados, fontes).regioes}
    assert {"ENDERECO", "COORDENADA", "RESPONSAVEL"} <= rotulos("A2-01")
    assert {"ENDERECO", "COORDENADA", "RESPONSAVEL"} <= rotulos("A2-04")
    assert {"CUSTODIA"} <= rotulos("A3-01")
    assert {"DISTRIBUICAO_GEOGRAFICA", "CUSTODIA"} <= rotulos("A3-03")
    assert {"DISTRIBUICAO_GEOGRAFICA", "CUSTODIA"} <= rotulos("A1-05")


def test_custodia_omitida_abaixo_do_n3(acervo):
    """Fora do N3 a instalação não aparece: nem marcador, nem nome, nem região: o A1-05 é só do N1 (antes
    era aberto também no N2), e o N2 nem abre o A1-05 nem o A3-03."""
    with pytest.raises(ErroAcervo):
        acervo.abrir("A1-05", BIA_N2, 2)
    with pytest.MonkeyPatch.context() as mp:
        textos = _escutar(mp)
        entrega = acervo.abrir("A1-05", ANA_N1, 1)
    nomes = {c.nome for c in sinteticos.CUSTODIAS}
    assert not [t for t, *_ in textos if t in nomes]
    assert "CUSTODIA" not in {r.rotulo for r in entrega.suprimidas}


def test_n1_com_grupo_pequeno_mostra_suprimido_sem_numero(acervo):
    """k=3 no relatório do N1: o estado com 2 casos sai SUPRIMIDO, sem número nem percentual, e a UF fica
    hachurada no mapa (sem cor da rampa)."""
    from dataclasses import replace
    from datetime import timedelta
    base = next(p for p in acervo.repo.pendencias() if p.ativa(sinteticos.DATA_BASE))
    montado = [replace(base, codigo=f"{uf}{i:02d}", uf=uf, data_encerramento=None,
                       data_identificacao=sinteticos.DATA_BASE - timedelta(days=30))
               for uf, n in (("SP", 10), ("RJ", 10), ("MG", 2)) for i in range(n)]
    dados = relatorios.DadosRelatorio(tuple(montado), None, {a.codigo: a for a in sinteticos.ATIVIDADES},
                                      {m.codigo: m for m in sinteticos.MOTIVOS}, sinteticos.DATA_BASE, "Nacional",
                                      datetime(2026, 10, 25, 10, 0), nivel=1)
    itens = {i.codigo: i for i in sinteticos.CATALOGO}
    for codigo in ("A1-01", "A1-05"):
        with pytest.MonkeyPatch.context() as mp:
            textos = _escutar(mp)
            relatorios.gerar(itens[codigo], dados, Fontes.de_configuracao(CFG))
        so = [t for t, *_ in textos]
        assert analise.SUPRIMIDO in so
        assert not any(t.startswith("2  (") or "9,1%" in t for t in so)
