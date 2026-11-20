"""Mensagem de tela para uma falha inesperada, sem o detalhe interno."""
import logging

from ecosec.repositorios.contratos import BancoIndisponivel, PermissaoNegada

log = logging.getLogger(__name__)

GENERICA = "Falha interna. O detalhe ficou registrado em logs/erros.log."


def mensagem_para_tela(erro: Exception) -> str:
    """As falhas do banco já traduzidas (serviço parado, contas recusadas) dizem o que fazer e não trazem nada
    interno; qualquer outra vira a frase genérica, e o texto original, com tabelas ou trechos de SQL, vai só para
    o registro de erros."""
    if isinstance(erro, (BancoIndisponivel, PermissaoNegada)):
        return str(erro)
    log.error("Falha inesperada no painel administrativo", exc_info=erro)
    return GENERICA
