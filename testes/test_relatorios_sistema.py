"""Relatórios do sistema S-01 a S-07."""
from datetime import timedelta

import pytest

from ecosec.aplicacao import montar
from ecosec.servicos.relatorios_sistema import RELATORIOS


@pytest.fixture
def app(tmp_path):
    a = montar(caminho_env=tmp_path / ".env", modo="memoria")
    a.administracao.custo = a.autenticacao.p.custo_bcrypt = 4
    return a


def test_todos_os_relatorios_geram(app):
    for codigo in RELATORIOS:
        tabela = app.relatorios_sistema.gerar(codigo)
        assert tabela.codigo == codigo and tabela.colunas
        assert all(len(linha) == len(tabela.colunas) for linha in tabela.linhas)


def test_s01_e_s02_vem_da_trilha(app):
    for _ in range(2):
        app.autenticacao.nova_sessao(2).informar_credenciais("NAOEXISTE", "x")
    s01, s02 = app.relatorios_sistema.gerar("S-01"), app.relatorios_sistema.gerar("S-02")
    assert len(s01.linhas) == 2 and all(l[3] == "NEGADO" for l in s01.linhas)
    assert all("USUARIO_INEXISTENTE" in l for l in s02.linhas)


def test_s03_lista_bloqueios_vigentes(app):
    for _ in range(3):
        app.autenticacao.nova_sessao(2).informar_credenciais("ALVO", "x")
    [linha] = app.relatorios_sistema.gerar("S-03").linhas
    assert linha[0] == "ALVO"


def test_s04_aponta_trilha_integra(app):
    app.administracao.definir_senha_inicial("Admin#Forte2026", "Admin#Forte2026")
    [linha] = app.relatorios_sistema.gerar("S-04").linhas
    assert linha[0] == "ÍNTEGRA" and linha[1] == 1


def test_s07_lista_exportacoes_e_bloqueios(app, tmp_path):
    from ecosec.dominio.entidades import Usuario
    caio = Usuario(matricula="CAIO", nome="Caio", nivel=3, senha_hash="$2b$x", id=7)
    entrega = app.acervo.abrir("A3-01", caio, 3)
    with pytest.raises(Exception):
        app.acervo.exportar(entrega, caio, tmp_path / "x.png")
    [linha] = app.relatorios_sistema.gerar("S-07").linhas
    assert linha[2] == "NEGADO" and linha[3] == "EXPORTACAO_BLOQUEADA"
