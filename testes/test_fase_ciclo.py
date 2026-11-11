"""Fase do processo derivada 100% da etapa.

O que se confere:
- toda etapa de todo ciclo de `CICLOS` tem uma das quatro fases; a tabela não tem etapa a mais;
- ao longo da ordem das etapas de cada ciclo, a fase nunca volta;
- ENCERRADA é exatamente a etapa final de cada ciclo;
- etapa desconhecida falha com erro claro (sem chute);
- no acervo gerado, toda pendência tem fase, as 395 "EM PROCESSO" ganham fase específica e a fase no corte
  bate com a situação no corte (encerrada no corte se e somente se ENCERRADA).
"""
import ast
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

import pytest

from ecosec.acervo import fase
from ecosec.acervo.geracao.ciclo import CICLOS


@pytest.fixture(scope="module")
def acervo():
    from ecosec.acervo import sinteticos
    pendencias, _ = sinteticos.gerar()
    return pendencias, sinteticos.DATA_BASE


def test_toda_etapa_de_todo_ciclo_tem_fase_e_a_tabela_nao_sobra():
    etapas = {e for etapas, _, _ in CICLOS.values() for e in etapas}
    for etapa in etapas:
        assert fase.fase_da_etapa(etapa) in fase.FASES, etapa
    assert set(fase.FASE_DA_ETAPA) == etapas                       # nenhuma etapa inventada na tabela
    assert fase.FASES == ("IDENTIFICACAO", "INVESTIGACAO", "REMEDIACAO", "ENCERRADA")


@pytest.mark.parametrize("ciclo", sorted(CICLOS))
def test_fase_nao_decresce_e_encerrada_so_na_etapa_final(ciclo):
    etapas = CICLOS[ciclo][0]
    ordem = [fase.FASES.index(f) for f in fase.fases_do_ciclo(ciclo)]
    assert ordem == sorted(ordem), (ciclo, list(zip(etapas, ordem)))
    assert fase.fase_da_etapa(etapas[0]) == fase.IDENTIFICACAO
    assert fase.fase_da_etapa(etapas[-1]) == fase.ENCERRADA
    assert all(fase.fase_da_etapa(e) != fase.ENCERRADA for e in etapas[:-1])


@pytest.mark.parametrize("etapa", ["EM PROCESSO", "REMEDIACAO EM CURSO", "", None, "identificacao"])
def test_etapa_desconhecida_falha_sem_chute(etapa):
    with pytest.raises(fase.EtapaDesconhecida) as erro:
        fase.fase_da_etapa(etapa)
    assert repr(etapa) in str(erro.value) and "Etapas conhecidas" in str(erro.value)
    assert isinstance(erro.value, ValueError)


def test_rotulos_com_acento_e_codigos_sem():
    assert [fase.rotulo(f) for f in fase.FASES] == ["IDENTIFICAÇÃO", "INVESTIGAÇÃO", "REMEDIAÇÃO", "ENCERRADA"]
    assert all(f.isascii() for f in fase.FASES)


def test_distribuicao_no_acervo_gerado_sem_em_processo_generico(acervo):
    pendencias, hoje = acervo
    ativas = [p for p in pendencias if p.data_encerramento is None]
    por_fase = Counter(fase.fase(p) for p in ativas)
    assert sum(por_fase.values()) == len(ativas) == 1028                        # Era 1.055
    assert set(por_fase) == {fase.IDENTIFICACAO, fase.INVESTIGACAO, fase.REMEDIACAO}     # as três fases ativas
    assert all(fase.fase(p) == fase.ENCERRADA for p in pendencias if p.data_encerramento is not None)
    em_processo = [p for p in ativas if p.situacao == "EM PROCESSO"]
    assert len(em_processo) == 397
    fases_em_processo = Counter(fase.fase(p) for p in em_processo)
    assert set(fases_em_processo) <= set(fase.FASES) - {fase.ENCERRADA}
    assert "EM PROCESSO" not in fase.FASES and "EM PROCESSO" not in fase.ROTULO.values()
    # derivada 100% da etapa: mesma etapa, mesma fase
    assert all(fase.fase(p) == fase.fase_da_etapa(p.etapa_atual) for p in pendencias)


def test_fase_no_corte_pela_etapa_vigente_e_coerente_com_a_situacao(acervo):
    pendencias, hoje = acervo
    for corte in (date(2010, 6, 30), date(2016, 1, 1), date(2022, 12, 31), hoje):
        existentes = [p for p in pendencias if p.data_identificacao <= corte]
        for p in existentes:
            f = fase.fase(p, corte)
            assert (f == fase.ENCERRADA) == p.encerrada(corte), (p.codigo, corte, f)
    # uma encerrada com histórico: no meio do processo, a fase é a da etapa daquela data
    p = next(p for p in pendencias if p.data_encerramento is not None and len(p.etapas) >= 4)
    nome, dia = p.etapas[2]
    assert fase.etapa_em(p, dia) == nome and fase.fase(p, dia) == fase.fase_da_etapa(nome)
    assert fase.etapa_em(p, p.etapas[0][1] - timedelta(days=1)) == p.etapas[0][0]
    assert fase.fase(p, None) == fase.fase(p) == fase.ENCERRADA


def test_acervo_fase_nao_importa_qt():
    arvore = ast.parse(Path(fase.__file__).read_text(encoding="utf-8"))
    modulos = {n.module for n in ast.walk(arvore) if isinstance(n, ast.ImportFrom)} | {
        a.name for n in ast.walk(arvore) if isinstance(n, ast.Import) for a in n.names}
    assert not any(m and (m.startswith("PySide6") or m.startswith("ecosec.interface")) for m in modulos)


def test_area_segue_os_incisos_do_art_23_da_conama_420():
    """No ciclo da área, a fase segue a CONAMA 420/2009, art. 23 (a norma vence a coerência com a
    situação "EM INVESTIGACAO", que é outro atributo). I identificação: avaliação preliminar e investigação
    confirmatória; II diagnóstico: investigação detalhada e avaliação de risco."""
    assert fase.fase_da_etapa("AVALIACAO PRELIMINAR") == fase.IDENTIFICACAO
    assert fase.fase_da_etapa("INVESTIGACAO CONFIRMATORIA") == fase.IDENTIFICACAO
    assert fase.fase_da_etapa("INVESTIGACAO DETALHADA") == fase.INVESTIGACAO
    assert fase.fase_da_etapa("AVALIACAO DE RISCO") == fase.INVESTIGACAO
