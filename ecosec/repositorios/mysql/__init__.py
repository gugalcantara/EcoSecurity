"""Implementação MySQL dos repositórios (mesmos contratos da versão em memória)."""
from ecosec.repositorios.mysql.conexao import BancoMySQL, ParametrosConexao, conectar_direto
from ecosec.repositorios.mysql.repositorios import (RepositorioAcervoMySQL, RepositorioAdministradoresMySQL,
                                                    RepositorioAmostrasMySQL, RepositorioConsentimentosMySQL,
                                                    RepositorioEstacoesMySQL,
                                                    RepositorioTentativasMySQL, RepositorioTrilhaMySQL,
                                                    RepositorioUsuariosMySQL)

TABELAS_ACERVO = ("atividade_geradora", "motivo_permanencia", "pendencia", "responsavel",
                  "item_acervo")
TABELAS_SEGURANCA = ("nivel", "usuario", "consentimento", "amostra", "tentativa", "log_acesso", "estacao",
                     "administrador", "codigo_recuperacao")

__all__ = ["RepositorioAcervoMySQL", "TABELAS_ACERVO", "BancoMySQL", "ParametrosConexao", "conectar_direto", "TABELAS_SEGURANCA",
           "RepositorioUsuariosMySQL", "RepositorioTentativasMySQL", "RepositorioConsentimentosMySQL",
           "RepositorioAmostrasMySQL", "RepositorioTrilhaMySQL", "RepositorioEstacoesMySQL",
           "RepositorioAdministradoresMySQL"]
