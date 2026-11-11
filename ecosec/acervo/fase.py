"""Fase do processo: derivada 100% da etapa, sem campo novo no acervo nem no banco.

Antes, 395 pendências ativas apareciam como "EM PROCESSO" (a situação genérica de `ciclo.situacao` para as
etapas sem rótulo próprio), o que não informa nada. A fase agrupa as etapas de TODOS os ciclos
(`geracao.ciclo.CICLOS`) em quatro códigos, na ordem do processo:

    IDENTIFICACAO  o passivo foi registrado e a autoridade começou a agir (sem investigação nem obra)
    INVESTIGACAO   caracterização: investigação, avaliação de risco, inspeção, inventário
    REMEDIACAO     intervenção física ou contenção: plano de intervenção, remediação, monitoramento,
                   acondicionamento, transporte, armazenamento provisório
    ENCERRADA      a etapa final do ciclo (a mesma data do encerramento da pendência)

Regras (verificadas em `testes/test_fase_ciclo.py`):
  - toda etapa de todo ciclo tem fase; a fase não decresce ao longo da ordem das etapas de cada ciclo;
  - ENCERRADA é exatamente a etapa final de cada ciclo;
  - etapa desconhecida levanta `EtapaDesconhecida` (nunca um chute).

Critérios da tabela:
  - Área contaminada (CONAMA 420/2009, art. 23): avaliação preliminar e investigação confirmatória ficam na
    IDENTIFICACAO, como no inciso I da norma (a norma vence a coerência com a situação "EM
    INVESTIGACAO", que é outro atributo); investigação detalhada e avaliação de risco (diagnóstico, inciso II)
    são INVESTIGACAO; monitoramento para encerramento ainda é REMEDIACAO.
  - Plano de intervenção, acondicionamento e armazenamento são REMEDIACAO, como na categoria EEA dos
    componentes de custo de mesmo nome.
  - Notificação e declaração de fonte fora de uso são atos administrativos sem caracterização: IDENTIFICACAO.

Uso compartilhado: o mapa temático e a ficha chamam `fase(p)` / `fase_da_etapa(etapa)`.
Com data de corte (linha do tempo), `fase(p, em)` usa a etapa vigente naquela data (`etapa_em`), para o mapa de
um ano passado não mostrar a fase de hoje.

Sem Qt: `acervo/` não importa a interface.
"""
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
    """Etapa vigente na data `em` (a última com data até `em`); sem data, a `etapa_atual`. Pendência ainda não
    identificada em `em` fica na primeira etapa; sem histórico de etapas, vale a `etapa_atual`."""
    if em is None or not p.etapas:
        return p.etapa_atual
    vigente = p.etapas[0][0]
    for nome, dia in p.etapas:
        if dia > em:
            break
        vigente = nome
    return vigente


def fase(p, em: date | None = None) -> str:
    """Fase da pendência `p` hoje (pela `etapa_atual`) ou na data de corte `em` (pela etapa vigente)."""
    return fase_da_etapa(etapa_em(p, em))


def rotulo(codigo: str) -> str:
    """Rótulo de exibição, com acento ("INVESTIGAÇÃO")."""
    return ROTULO[codigo]


def fases_do_ciclo(ciclo: str) -> tuple[str, ...]:
    """Fase de cada etapa do ciclo, na ordem das etapas (para conferência e para a ata)."""
    return tuple(fase_da_etapa(e) for e in CICLOS[ciclo][0])
