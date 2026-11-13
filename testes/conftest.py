"""Configuração comum dos testes.

A interface é testada sem janela visível (plataforma offscreen do Qt) e com
uma única QApplication para a sessão inteira: criar e destruir várias deixa o
Qt num estado inconsistente, e testes de tela passam a ser pulados em silêncio.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", "C:/Windows/Fonts")

import pytest  # noqa: E402


@pytest.fixture(scope="session")
def qt():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture
def modo_demonstracao():
    """[interface] modo_demonstracao fixado nos testes de tela, sem ler o ecosec.toml da máquina.
    O teste que precisa do outro valor parametriza: @pytest.mark.parametrize("modo_demonstracao", [True])."""
    return False


# ---------------------------------------------------------------- MySQL descartável
@pytest.fixture(scope="session")
def banco_mysql():
    """Um banco ecosec_teste_<aleatório> criado com a conta de testes e apagado no fim.

    Pula (não aprova) se o MySQL não estiver preparado nesta máquina: sem
    `python -m ferramentas.preparar_banco`, não há conta de testes no .env.
    """
    import secrets as _secrets

    from ecosec import segredos
    from ecosec.configuracao import carregar
    from ecosec.repositorios.contratos import ErroRepositorio
    from ecosec.repositorios.mysql import BancoMySQL, ParametrosConexao, conectar_direto
    from ecosec.repositorios.mysql.scripts import executar_scripts

    usuario, senha = segredos.ler(segredos.DB_TESTE_USUARIO), segredos.ler(segredos.DB_TESTE_SENHA)
    if not usuario or not senha:
        pytest.skip("MySQL não preparado (rode python -m ferramentas.preparar_banco)")
    cfg = carregar()
    host, porta = cfg["banco.host"], int(cfg["banco.porta"])
    nome = cfg["banco.prefixo_teste"] + _secrets.token_hex(4)
    try:
        conexao = conectar_direto(host, porta, usuario, senha)
    except ErroRepositorio as erro:
        pytest.skip(f"MySQL indisponível: {erro}")
    cursor = conexao.cursor()
    cursor.execute(f"CREATE DATABASE `{nome}` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci")
    conexao.database = nome
    executar_scripts(conexao, "seguranca")
    banco = BancoMySQL(ParametrosConexao(host, porta, nome, usuario, senha))
    try:
        yield banco
    finally:
        cursor.execute(f"DROP DATABASE `{nome}`")
        cursor.close()
        conexao.close()


@pytest.fixture
def banco_mysql_limpo(banco_mysql):
    """Esvazia as tabelas (menos a de referência) antes de cada teste."""
    with banco_mysql.transacao() as c:
        c.execute("SET FOREIGN_KEY_CHECKS = 0")
        for tabela in ("log_acesso", "amostra", "consentimento", "tentativa", "codigo_recuperacao", "administrador",
                       "usuario"):
            c.execute(f"TRUNCATE TABLE {tabela}")
        c.execute("SET FOREIGN_KEY_CHECKS = 1")
    return banco_mysql


@pytest.fixture(scope="session")
def acervo_mysql():
    """Banco de ACERVO descartável, com o acervo fictício importado. Pula sem MySQL."""
    import secrets as _secrets

    from ecosec import segredos
    from ecosec.configuracao import carregar
    from ecosec.repositorios.contratos import ErroRepositorio
    from ecosec.repositorios.mysql import BancoMySQL, ParametrosConexao, conectar_direto
    from ecosec.repositorios.mysql.importacao import importar_acervo
    from ecosec.repositorios.mysql.scripts import executar_scripts

    usuario, senha = segredos.ler(segredos.DB_TESTE_USUARIO), segredos.ler(segredos.DB_TESTE_SENHA)
    if not usuario or not senha:
        pytest.skip("MySQL não preparado (rode python -m ferramentas.preparar_banco)")
    cfg = carregar()
    host, porta = cfg["banco.host"], int(cfg["banco.porta"])
    nome = cfg["banco.prefixo_teste"] + "acervo_" + _secrets.token_hex(3)
    try:
        conexao = conectar_direto(host, porta, usuario, senha)
    except ErroRepositorio as erro:
        pytest.skip(f"MySQL indisponível: {erro}")
    cursor = conexao.cursor()
    cursor.execute(f"CREATE DATABASE `{nome}` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci")
    conexao.database = nome
    executar_scripts(conexao, "acervo")
    importar_acervo(conexao)
    try:
        yield BancoMySQL(ParametrosConexao(host, porta, nome, usuario, senha))
    finally:
        cursor.execute(f"DROP DATABASE `{nome}`")
        cursor.close()
        conexao.close()
