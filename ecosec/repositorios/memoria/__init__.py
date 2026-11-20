"""Repositórios em memória."""
from ecosec.repositorios.memoria.repositorios import (RepositorioAcervoMemoria, RepositorioAdministradoresMemoria,
                                                      RepositorioAmostrasMemoria,
                                                      RepositorioConsentimentosMemoria,
                                                      RepositorioTentativasMemoria,
                                                      RepositorioEstacoesMemoria, RepositorioTrilhaMemoria,
                                                      RepositorioUsuariosMemoria)

__all__ = ["RepositorioAcervoMemoria", "RepositorioUsuariosMemoria", "RepositorioTentativasMemoria",
           "RepositorioConsentimentosMemoria", "RepositorioAmostrasMemoria",
           "RepositorioTrilhaMemoria", "RepositorioEstacoesMemoria", "RepositorioAdministradoresMemoria"]
