"""O perfil na persistência, nas duas implementações, e a migração do MySQL.

- contrato: memória e MySQL guardam e devolvem o perfil, o nível nulo (Externo, inclusive o administrador) e a
  exclusão lógica (excluido_em);
- o banco recusa perfil e nível incoerentes (CHECK ck_usuario_perfil_nivel), mesmo que a aplicação erre;
- a migração (ferramentas.preparar_banco.migrar_perfis) leva ao modelo de quatro perfis tanto um banco de antes
  (só níveis) quanto um da primeira versão dela (perfis Administrador, Sem perfil e Ministério Público):
  cada um pelo nível; administradores e perfis retirados viram Externo, sem camada. É idempotente. Os dois
  schemas estão congelados em `testes/dados/`.

Os privilégios não mudam: o DELETE continua recusado à aplicação (test_mysql.py::test_conta_da_aplicacao_nao_apaga_provas).
Sem o MySQL preparado, os casos "mysql" são pulados: a suíte completa roda com o banco preparado.
"""
import secrets
from datetime import datetime
from pathlib import Path

import pytest

from ecosec.dominio.entidades import Usuario
from ecosec.dominio.niveis import Nivel
from test_repositorios_contrato import repos  # noqa: F401

SCHEMA_ANTES = Path(__file__).parent / "dados" / "seguranca_01_schema_sem_perfil.sql"
SCHEMA_PERFIS_V1 = Path(__file__).parent / "dados" / "seguranca_01_schema_perfis_v1.sql"     # a primeira versão


def Perfil():  # noqa: N802
    from ecosec.dominio.perfis import Perfil as P
    return P


def novo(matricula, perfil, uf=None):
    return Usuario(matricula=matricula, nome="Ana Lima", nivel=None, perfil=Perfil()[perfil], senha_hash="$2b$x",
                   uf=uf)


# contrato
@pytest.mark.parametrize("perfil, nivel", [("EXTERNO", None), ("SERVIDOR", Nivel.N1), ("MINISTRO", Nivel.N3)])
def test_perfil_e_nivel_nulo_ida_e_volta(repos, perfil, nivel):
    usuarios, _, _ = repos
    gravado = usuarios.adicionar(novo("R7K2M94", perfil))
    lido = usuarios.por_id(gravado.id)
    assert (lido.perfil, lido.nivel) == (Perfil()[perfil], nivel)
    assert usuarios.por_matricula("R7K2M94") == lido


def test_trocar_o_perfil_e_a_uf(repos):
    import dataclasses
    usuarios, _, _ = repos
    u = usuarios.adicionar(novo("R7K2M94", "EXTERNO"))
    usuarios.atualizar(dataclasses.replace(u, perfil=Perfil().DIRETOR, nivel=Nivel.N2, uf="SP"))
    lido = usuarios.por_id(u.id)
    assert (lido.perfil, lido.nivel, lido.uf) == (Perfil().DIRETOR, Nivel.N2, "SP")


def test_exclusao_logica_ida_e_volta(repos):
    import dataclasses
    usuarios, _, _ = repos
    u = usuarios.adicionar(novo("R7K2M94", "SERVIDOR"))
    momento = datetime(2026, 11, 7, 10, 0, 0, 123456)
    usuarios.atualizar(dataclasses.replace(u, ativo=False, excluido_em=momento))
    lido = usuarios.por_id(u.id)
    assert not lido.ativo and lido.excluido_em == momento


# o banco recusa o incoerente
@pytest.mark.parametrize("perfil, nivel", [("EXTERNO", 3), ("EXTERNO", 1), ("MINISTRO", 1), ("MINISTRO", None),
                                           ("SERVIDOR", None), ("ADMINISTRADOR", None), ("MINISTERIO_PUBLICO", 3),
                                           ("XERIFE", None)])
def test_banco_recusa_perfil_e_nivel_incoerentes(banco_mysql_limpo, perfil, nivel):
    with pytest.raises(Exception) as erro:
        with banco_mysql_limpo.transacao() as c:
            c.execute("INSERT INTO usuario (matricula, nome, nivel, perfil, uf, senha_hash, ativo, criado_em) "
                      "VALUES (%s, 'ANA LIMA', %s, %s, NULL, '$2b$x', TRUE, %s)",
                      ("R7K2M94", nivel, perfil, datetime(2026, 11, 7)))
    assert "ck_usuario_perfil" in str(erro.value), str(erro.value)


# migração
def _banco_descartavel(schema, cadastros):
    """Um banco descartável com o schema de segurança e os cadastros (comandos INSERT). Apagado no fim."""
    from ecosec import segredos
    from ecosec.configuracao import carregar
    from ecosec.repositorios.contratos import ErroRepositorio
    from ecosec.repositorios.mysql import conectar_direto
    from ecosec.repositorios.mysql.scripts import PASTA_SQL, dividir
    usuario, senha = segredos.ler(segredos.DB_TESTE_USUARIO), segredos.ler(segredos.DB_TESTE_SENHA)
    if not usuario or not senha:
        pytest.skip("MySQL não preparado (rode python -m ferramentas.preparar_banco)")
    cfg = carregar()
    nome = cfg["banco.prefixo_teste"] + "migra_" + secrets.token_hex(3)
    try:
        conexao = conectar_direto(cfg["banco.host"], int(cfg["banco.porta"]), usuario, senha)
    except ErroRepositorio as erro:
        pytest.skip(f"MySQL indisponível: {erro}")
    cursor = conexao.cursor()
    cursor.execute(f"CREATE DATABASE `{nome}` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci")
    conexao.database = nome
    try:
        for arquivo in (schema, PASTA_SQL / "seguranca" / "02_referencia.sql"):
            for comando in dividir(arquivo.read_text(encoding="utf-8")):
                cursor.execute(comando)
        agora = datetime(2026, 11, 7, 10, 0)
        for sql, parametros in cadastros:
            cursor.execute(sql, parametros + (agora,))
        cursor.execute("INSERT INTO administrador (usuario_id, designado_em) "
                       "SELECT id, %s FROM usuario WHERE matricula = 'ADMIN3'", (agora,))
        conexao.commit()
        yield conexao, cursor, nome
    finally:
        cursor.execute(f"DROP DATABASE `{nome}`")
        cursor.close()
        conexao.close()


@pytest.fixture
def banco_antigo():
    """Schema de antes e quatro cadastros: N1, N2, N3 e um administrador que era N3."""
    inserir = ("INSERT INTO usuario (matricula, nome, nivel, uf, senha_hash, ativo, criado_em) "
               "VALUES (%s, 'ANA LIMA', %s, %s, '$2b$x', TRUE, %s)")
    yield from _banco_descartavel(SCHEMA_ANTES, [(inserir, ("SERVIDOR1", 1, None)), (inserir, ("DIRETOR2", 2, "SP")),
                                                 (inserir, ("MINISTRO3", 3, None)), (inserir, ("ADMIN3", 3, None))])


@pytest.fixture
def banco_perfis_v1():
    """Schema da primeira versão (como o banco do aplicativo ficou): um administrador com o perfil
    Administrador, um Ministério Público, um sem perfil e um ministro."""
    inserir = ("INSERT INTO usuario (matricula, nome, nivel, perfil, uf, senha_hash, ativo, criado_em) "
               "VALUES (%s, 'ANA LIMA', %s, %s, NULL, '$2b$x', TRUE, %s)")
    yield from _banco_descartavel(SCHEMA_PERFIS_V1, [(inserir, ("ADMIN3", None, "ADMINISTRADOR")),
                                                (inserir, ("PROMOTOR3", 3, "MINISTERIO_PUBLICO")),
                                                (inserir, ("ESPERA0", None, "SEM_PERFIL")),
                                                (inserir, ("MINISTRO3", 3, "MINISTRO"))])


def _cadastros(cursor):
    cursor.execute("SELECT matricula, perfil, nivel, uf FROM usuario ORDER BY id")
    return {m: (p, n, uf) for m, p, n, uf in cursor.fetchall()}


def test_migracao_leva_o_schema_antigo_ao_modelo_de_perfis(banco_antigo):
    from ferramentas.preparar_banco import migrar_perfis
    conexao, cursor, nome = banco_antigo
    migrar_perfis(cursor, nome)
    conexao.commit()
    assert _cadastros(cursor) == {"SERVIDOR1": ("SERVIDOR", 1, None), "DIRETOR2": ("DIRETOR", 2, "SP"),
                                  "MINISTRO3": ("MINISTRO", 3, None), "ADMIN3": ("EXTERNO", None, None)}
    migrar_perfis(cursor, nome)                                  # idempotente: rodar de novo não muda nada
    conexao.commit()
    assert _cadastros(cursor)["ADMIN3"] == ("EXTERNO", None, None)
    with pytest.raises(Exception) as erro:                        # e o CHECK novo passa a valer
        cursor.execute("UPDATE usuario SET nivel = 3 WHERE matricula = 'ADMIN3'")
    assert "ck_usuario_perfil" in str(erro.value)


def test_migracao_leva_a_primeira_versao_dos_perfis_ao_modelo_de_quatro_perfis(banco_perfis_v1):
    """Migração: os antigos Administrador, Sem perfil e Ministério Público viram Externo, sem
    camada. O papel de administrador continua na tabela administrador."""
    from ferramentas.preparar_banco import migrar_perfis
    conexao, cursor, nome = banco_perfis_v1
    migrar_perfis(cursor, nome)
    conexao.commit()
    assert _cadastros(cursor) == {"ADMIN3": ("EXTERNO", None, None), "PROMOTOR3": ("EXTERNO", None, None),
                                  "ESPERA0": ("EXTERNO", None, None), "MINISTRO3": ("MINISTRO", 3, None)}
    cursor.execute("SELECT COUNT(*) FROM administrador a JOIN usuario u ON u.id = a.usuario_id "
                   "WHERE a.ativo AND u.matricula = 'ADMIN3'")
    assert cursor.fetchone()[0] == 1                             # o papel continua
    migrar_perfis(cursor, nome)                                  # idempotente
    conexao.commit()
    with pytest.raises(Exception) as erro:                        # o CHECK novo recusa os perfis retirados
        cursor.execute("UPDATE usuario SET perfil = 'MINISTERIO_PUBLICO' WHERE matricula = 'MINISTRO3'")
    assert "ck_usuario_perfil" in str(erro.value)
