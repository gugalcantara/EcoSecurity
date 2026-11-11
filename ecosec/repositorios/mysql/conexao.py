"""Conexão com o MySQL: pool de conexões e tradução de erros.

Pool: a câmera consulta o banco numa thread (consentimento, usuário) enquanto
a tela consulta em outra. Uma conexão MySQL não pode ser usada por duas
threads ao mesmo tempo; o pool entrega uma conexão por operação.

Transação por operação: `with banco.transacao() as c:` faz COMMIT se o bloco
termina bem e rollback se levanta exceção: nunca fica meio gravado.

Tradução de erros: o resto do sistema não conhece o mysql.connector. Erros do
driver viram os erros do contrato (BancoIndisponivel, PermissaoNegada...).

FOUND_ROWS: por padrão o MySQL informa em `rowcount` as linhas alteradas; um
UPDATE que grava o mesmo valor devolveria 0 e pareceria "registro inexistente".
Com FOUND_ROWS ele informa as linhas encontradas.
"""
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field

import mysql.connector
from mysql.connector import errorcode, errors
from mysql.connector.constants import ClientFlag
from mysql.connector.pooling import MySQLConnectionPool

from ecosec.repositorios.contratos import BancoIndisponivel, ErroRepositorio, PermissaoNegada


@dataclass(frozen=True)
class ParametrosConexao:
    host: str
    porta: int
    banco: str
    usuario: str
    senha: str = field(repr=False)          # nunca aparece em log ou mensagem


def traduzir(erro: Exception) -> ErroRepositorio:
    numero = getattr(erro, "errno", None)
    if numero in (errorcode.ER_TABLEACCESS_DENIED_ERROR, errorcode.ER_COLUMNACCESS_DENIED_ERROR,
                  errorcode.ER_DBACCESS_DENIED_ERROR, errorcode.ER_SPECIFIC_ACCESS_DENIED_ERROR):
        return PermissaoNegada(f"O banco recusou a operação à conta da aplicação ({numero}).")
    if numero == errorcode.ER_ACCESS_DENIED_ERROR:
        return BancoIndisponivel("Usuário ou senha do banco recusados. Rode "
                                 "`python -m ferramentas.preparar_banco` para refazer as contas.")
    if numero == errorcode.ER_BAD_DB_ERROR or numero == errorcode.ER_NO_SUCH_TABLE:
        return BancoIndisponivel("O banco ou suas tabelas não existem. Rode "
                                 "`python -m ferramentas.preparar_banco`.")
    if isinstance(erro, (errors.InterfaceError, errors.OperationalError, errors.PoolError)):
        return BancoIndisponivel("Não foi possível falar com o MySQL. Confira se o serviço "
                                 "MySQL84 está em execução.")
    return ErroRepositorio(f"Erro do banco ({numero}): {getattr(erro, 'msg', erro)}")


class BancoMySQL:
    def __init__(self, p: ParametrosConexao, tamanho_pool: int = 5):
        self.p = p
        self._tamanho = tamanho_pool
        self._pool: MySQLConnectionPool | None = None
        self._lock = threading.Lock()

    def _obter_pool(self) -> MySQLConnectionPool:
        with self._lock:                         # criado na 1ª necessidade, uma vez só
            if self._pool is None:
                self._pool = MySQLConnectionPool(
                    pool_name=f"ecosec_{self.p.banco}_{id(self)}", pool_size=self._tamanho,
                    host=self.p.host, port=self.p.porta, database=self.p.banco,
                    user=self.p.usuario, password=self.p.senha, charset="utf8mb4",
                    collation="utf8mb4_0900_ai_ci", autocommit=False, connection_timeout=5,
                    client_flags=[ClientFlag.FOUND_ROWS])
            return self._pool

    @contextmanager
    def transacao(self):
        try:
            conexao = self._obter_pool().get_connection()
        except errors.Error as erro:
            raise traduzir(erro) from None
        cursor = conexao.cursor(dictionary=True)
        try:
            yield cursor
            conexao.commit()
        except errors.Error as erro:
            conexao.rollback()
            raise traduzir(erro) from erro
        except BaseException:
            conexao.rollback()
            raise
        finally:
            cursor.close()
            conexao.close()                      # devolve ao pool

    def verificar(self, tabelas: tuple[str, ...]) -> None:
        """Na abertura: o servidor responde e as tabelas existem? Senão, BancoIndisponivel."""
        with self.transacao() as c:
            c.execute("SELECT table_name AS t FROM information_schema.tables WHERE table_schema = %s",
                      (self.p.banco,))
            existentes = {linha["t"] for linha in c.fetchall()}
        faltando = set(tabelas) - existentes
        if faltando:
            raise BancoIndisponivel(f"Tabelas ausentes em {self.p.banco}: {', '.join(sorted(faltando))}. "
                                    "Rode `python -m ferramentas.preparar_banco`.")


def conectar_direto(host: str, porta: int, usuario: str, senha: str, banco: str | None = None):
    """Conexão avulsa (sem pool): usada pela ferramenta de preparação e pelos testes."""
    try:
        return mysql.connector.connect(host=host, port=porta, user=usuario, password=senha,
                                       database=banco, charset="utf8mb4",
                                       collation="utf8mb4_0900_ai_ci", connection_timeout=5,
                                       client_flags=[ClientFlag.FOUND_ROWS])
    except errors.Error as erro:
        raise traduzir(erro) from None
