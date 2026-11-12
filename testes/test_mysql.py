"""Camada MySQL: leitor de scripts, falha segura e integração com o banco real.

Os testes de integração só rodam depois de `python -m ferramentas.preparar_banco`;
antes disso aparecem como pulados.
"""
import pytest

from ecosec import segredos
from ecosec.aplicacao import ErroAbertura, montar
from ecosec.configuracao import carregar
from ecosec.dominio.motivos import Motivo
from ecosec.dominio.niveis import Nivel
from ecosec.repositorios.contratos import BancoIndisponivel
from ecosec.repositorios.mysql.scripts import dividir
from ecosec.servicos.autenticacao import Etapa

CFG = carregar()


# ================================================================ leitor de scripts
def test_dividir_respeita_texto_e_comentarios():
    sql = ("-- comentário; com ponto e vírgula\n"
           "CREATE TABLE t (a INT); -- fim de linha\n"
           "INSERT INTO t VALUES ('a; b -- não é comentário', 'it''s', 'x\\'y');\n"
           "SELECT `col;una` FROM t")
    assert dividir(sql) == ["CREATE TABLE t (a INT)",
                            "INSERT INTO t VALUES ('a; b -- não é comentário', 'it''s', 'x\\'y')",
                            "SELECT `col;una` FROM t"]


def test_scripts_do_projeto_sao_lidos():
    from ecosec.repositorios.mysql.scripts import PASTA_SQL, SCRIPTS
    for arquivos in SCRIPTS.values():
        for arquivo in arquivos:
            assert dividir((PASTA_SQL / arquivo).read_text(encoding="utf-8"))


# ================================================================ falha segura
class RepositorioQueCai:
    """Simula o MySQL caindo no meio da operação."""

    def __getattr__(self, _):
        def falhar(*_args, **_kw):
            raise BancoIndisponivel("serviço parado")
        return falhar


def test_banco_caindo_no_login_nega_com_erro_interno(tmp_path):
    app = montar(CFG, tmp_path / ".env", modo="memoria")
    servico = app.autenticacao
    servico.usuarios = servico.tentativas = RepositorioQueCai()
    sessao = servico.nova_sessao(2)
    andamento = sessao.informar_credenciais("QUALQUER", "senha")
    assert andamento.etapa is Etapa.CONCLUIDA
    assert andamento.decisao.motivo is Motivo.ERRO_INTERNO and not andamento.decisao.concedido


def test_banco_caindo_no_portao_admin_nega(tmp_path):
    app = montar(CFG, tmp_path / ".env", modo="memoria")
    app.administracao.custo = 4
    app.administracao.definir_senha_inicial("Admin#Forte2026", "Admin#Forte2026")
    app.administracao.tentativas = RepositorioQueCai()
    assert app.administracao.autenticar("Admin#Forte2026") is Motivo.ERRO_INTERNO


def test_sem_credenciais_do_banco_o_sistema_nao_abre(tmp_path):
    with pytest.raises(ErroAbertura, match="preparar_banco"):
        montar(CFG, tmp_path / ".env", modo="mysql")


def test_modo_invalido_e_erro():
    from ecosec.configuracao import ErroConfiguracao
    with pytest.raises(ErroConfiguracao):
        montar(CFG, modo="planilha")


# ================================================================ integração (banco real)
def _conta(chave_usuario, chave_senha, banco):
    from ecosec.repositorios.mysql import conectar_direto
    usuario, senha = segredos.ler(chave_usuario), segredos.ler(chave_senha)
    if not usuario:
        pytest.skip("MySQL não preparado (rode python -m ferramentas.preparar_banco)")
    try:
        return conectar_direto(CFG["banco.host"], int(CFG["banco.porta"]), usuario, senha, banco)
    except BancoIndisponivel as erro:
        pytest.skip(f"MySQL indisponível: {erro}")


@pytest.mark.parametrize("sql", ["DELETE FROM usuario WHERE 1 = 0", "DELETE FROM consentimento WHERE 1 = 0",
                                 "DELETE FROM amostra WHERE 1 = 0", "DROP TABLE tentativa",
                                 "UPDATE amostra SET qualidade = 0 WHERE 1 = 0",
                                 "UPDATE log_acesso SET motivo = 'X' WHERE 1 = 0",
                                 "DELETE FROM log_acesso WHERE 1 = 0"])
def test_conta_da_aplicacao_nao_apaga_provas(sql):
    import mysql.connector
    conexao = _conta(segredos.DB_SEGURANCA_USUARIO, segredos.DB_SEGURANCA_SENHA, CFG["banco.seguranca"])
    try:
        with pytest.raises(mysql.connector.errors.ProgrammingError) as erro:
            conexao.cursor().execute(sql)
        assert erro.value.errno in (1142, 1143)          # comando negado à conta
    finally:
        conexao.close()


def test_conta_do_cofre_so_le():
    import mysql.connector
    conexao = _conta(segredos.DB_ACERVO_USUARIO, segredos.DB_ACERVO_SENHA, CFG["banco.acervo"])
    try:
        cursor = conexao.cursor()
        cursor.execute("SELECT COUNT(*) FROM motivo_permanencia")
        assert cursor.fetchone()[0] == 10                  # MP-01 a MP-10
        with pytest.raises(mysql.connector.errors.ProgrammingError):
            cursor.execute("DELETE FROM pendencia WHERE 1 = 0")
    finally:
        conexao.close()


def test_tabela_nivel_concorda_com_o_dominio():
    conexao = _conta(segredos.DB_SEGURANCA_USUARIO, segredos.DB_SEGURANCA_SENHA, CFG["banco.seguranca"])
    try:
        cursor = conexao.cursor(dictionary=True)
        cursor.execute("SELECT id, titulo, modo, exportacao FROM nivel ORDER BY id")
        for linha, nivel in zip(cursor.fetchall(), Nivel, strict=True):
            assert (linha["titulo"], linha["modo"], linha["exportacao"]) == \
                   (nivel.titulo, nivel.modo.value, nivel.exportacao.value)
    finally:
        conexao.close()


def test_banco_recusa_estado_invalido_mesmo_se_a_aplicacao_errar(banco_mysql_limpo):
    """As regras de segurança moram também no banco (CHECK)."""
    from ecosec.repositorios.contratos import ErroRepositorio
    with pytest.raises(ErroRepositorio):                   # N2 sem UF
        with banco_mysql_limpo.transacao() as c:
            c.execute("INSERT INTO usuario (matricula, nome, nivel, uf, senha_hash, criado_em) "
                      "VALUES ('X', 'X', 2, NULL, '$2b$12$abc', NOW(6))")
    with pytest.raises(ErroRepositorio):                   # senha em texto puro
        with banco_mysql_limpo.transacao() as c:
            c.execute("INSERT INTO usuario (matricula, nome, nivel, uf, senha_hash, criado_em) "
                      "VALUES ('Y', 'Y', 1, NULL, 'minhasenha', NOW(6))")
