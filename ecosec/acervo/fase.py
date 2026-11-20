"""Fase do processo de cada caso, calculada a partir da etapa atual."""
from __future__ import annotations

from datetime import date

from ecosec.acervo.geracao.ciclo import CICLOS

IDENTIFICACAO, INVESTIGACAO, REMEDIACAO, ENCERRADA = "IDENTIFICACAO", "INVESTIGACAO", "REMEDIACAO", "ENCERRADA"
FASES = (IDENTIFICACAO, INVESTIGACAO, REMEDIACAO, ENCERRADA)            # em ordem
ROTULO = {IDENTIFICACAO: "IDENTIFICAÇÃO", INVESTIGACAO: "INVESTIGAÇÃO", REMEDIACAO: "REMEDIAÇÃO",
          ENCERRADA: "ENCERRADA"}

# etapa -> fase. Etapas de mesmo nome em ciclos diferentes (IDENTIFICACAO, ACONDICIONAMENTO, ENCERRAMENTO) têm a
# mesma fase em todos eles.
FASE_DA_ETAPA = {
    # comum a todos os ciclos
    "IDENTIFICACAO": IDENTIFICACAO,
    # AREA (área contaminada, postos, garimpo)
    "AVALIACAO PRELIMINAR": IDENTIFICACAO,
    "INVESTIGACAO CONFIRMATORIA": IDENTIFICACAO,  # CONAMA 420, art. 23, I
    "INVESTIGACAO DETALHADA": INVESTIGACAO,
    "AVALIACAO DE RISCO": INVESTIGACAO,
    "PLANO DE INTERVENCAO": REMEDIACAO,
    "REMEDIACAO": REMEDIACAO,
    "MONITORAMENTO": REMEDIACAO,
    "ENCERRAMENTO": ENCERRADA,                    # final do ciclo AREA e do ARMAZENADO
    # CLASSE I
    "NOTIFICACAO": IDENTIFICACAO,
    "ACONDICIONAMENTO": REMEDIACAO,               # também em FONTES e ARMAZENADO
    "PLANO DE GERENCIAMENTO": REMEDIACAO,
    "MTR EMITIDO": REMEDIACAO,
    "COLETA": REMEDIACAO,
    "DESTINACAO": ENCERRADA,
    # FONTES (fontes seladas)
    "DECLARACAO DE FONTE FORA DE USO": IDENTIFICACAO,
    "INSPECAO": INVESTIGACAO,
    "TRANSPORTE AUTORIZADO": REMEDIACAO,
    "RECOLHIMENTO": ENCERRADA,
    # ARMAZENADO (NORM e rejeito sem destino final)
    "INVENTARIO": INVESTIGACAO,
    "ARMAZENAMENTO PROVISORIO": REMEDIACAO,
}


class EtapaDesconhecida(ValueError):
    """Etapa fora da tabela: a fase não é adivinhada."""


def fase_da_etapa(etapa: str) -> str:
    """Código da fase (IDENTIFICACAO, INVESTIGACAO, REMEDIACAO ou ENCERRADA) de uma etapa de qualquer ciclo."""
    try:
        return FASE_DA_ETAPA[etapa]
    except (KeyError, TypeError):
        conhecidas = ", ".join(sorted(FASE_DA_ETAPA))
        raise EtapaDesconhecida(f"Etapa sem fase definida: {etapa!r}. Etapas conhecidas: {conhecidas}.") from None


def etapa_em(p, em: date | None = None) -> str:
    """Etapa vigente na data em (a última com data até em); sem data, a etapa_atual. Pendência ainda não
    identificada em em fica na primeira etapa; sem histórico de etapas, vale a etapa_atual."""
    if em is None or not p.etapas:
        return p.etapa_atual
    vigente = p.etapas[0][0]
    for nome, dia in p.etapas:
        if dia > em:
            break
        vigente = nome
    return vigente


def fase(p, em: date | None = None) -> str:
    """Fase da pendência p hoje (pela etapa_atual) ou na data de corte em (pela etapa vigente)."""
    return fase_da_etapa(etapa_em(p, em))


def rotulo(codigo: str) -> str:
    """Rótulo de exibição, com acento ("INVESTIGAÇÃO")."""
    return ROTULO[codigo]


def fases_do_ciclo(ciclo: str) -> tuple[str, ...]:
    """Fase de cada etapa do ciclo, na ordem das etapas."""
    return tuple(fase_da_etapa(e) for e in CICLOS[ciclo][0])
