"""Ciclo de vida: etapas encaixadas entre a entrada e a saída da pendência.

O instante de saída é decidido primeiro (saidas.py + fluxos.py); as etapas são
encaixadas depois. Assim a data de encerramento é sempre a data da etapa final:
  - encerrada: as durações são reescaladas para terminar exatamente na saída;
  - ativa: durações naturais, cortadas na data-base, sem nunca chegar à etapa final.
"""
from math import log

# classe do ciclo -> (etapas, medianas das transições em anos, situação final)
CICLOS = {
    "AREA": (("IDENTIFICACAO", "AVALIACAO PRELIMINAR", "INVESTIGACAO CONFIRMATORIA", "INVESTIGACAO DETALHADA",
              "AVALIACAO DE RISCO", "PLANO DE INTERVENCAO", "REMEDIACAO", "MONITORAMENTO", "ENCERRAMENTO"),
             (0.5, 0.8, 1.0, 1.2, 0.8, 1.0, 2.5, 2.0), "REABILITADA"),
    "CLASSE I": (("IDENTIFICACAO", "NOTIFICACAO", "ACONDICIONAMENTO", "PLANO DE GERENCIAMENTO", "MTR EMITIDO",
                  "COLETA", "DESTINACAO"),
                 (0.3, 0.5, 0.6, 0.7, 0.3, 0.3), "DESTINADA"),
    "FONTES": (("IDENTIFICACAO", "DECLARACAO DE FONTE FORA DE USO", "INSPECAO", "ACONDICIONAMENTO",
                "TRANSPORTE AUTORIZADO", "RECOLHIMENTO"),
               (0.3, 0.4, 0.3, 0.4, 0.3), "COLETADA"),
    # rejeito sem destino final no país: nunca chega a uma etapa final dentro da série
    "ARMAZENADO": (("IDENTIFICACAO", "INVENTARIO", "ACONDICIONAMENTO", "ARMAZENAMENTO PROVISORIO", "ENCERRAMENTO"),
                   (0.5, 1.0, 1.5, 3.0), "ENCERRADA"),
}
SIGMA = 0.6
SITUACOES_FINAIS = {c[2] for c in CICLOS.values()}

# situação de uma pendência ATIVA, pela etapa corrente
SITUACAO_DA_ETAPA = {
    "IDENTIFICACAO": "PENDENTE", "AVALIACAO PRELIMINAR": "PENDENTE", "NOTIFICACAO": "EM NOTIFICACAO",
    "DECLARACAO DE FONTE FORA DE USO": "EM NOTIFICACAO", "INVESTIGACAO CONFIRMATORIA": "EM INVESTIGACAO",
    "INVESTIGACAO DETALHADA": "EM INVESTIGACAO", "AVALIACAO DE RISCO": "EM INVESTIGACAO",
    "REMEDIACAO": "EM REMEDIACAO", "MONITORAMENTO": "EM MONITORAMENTO", "ARMAZENAMENTO PROVISORIO": "ARMAZENADA",
}


def ciclo_da_linha(linha: str) -> str:
    return {"POSTOS": "AREA", "AREA": "AREA", "GARIMPO": "AREA", "FONTES SELADAS": "FONTES",
            "NORM": "ARMAZENADO"}.get(linha, "CLASSE I")


def encaixar_etapas(rng, etapas, medianas_anos, sigma, entrada: float, saida: float | None,
                    data_base: float) -> list[tuple[str, float]]:
    """Datas das etapas (anos fracionários). Encerrada: as durações são reescaladas para terminar
    exatamente na saída. Ativa: durações naturais, sem nunca chegar à etapa final, cortadas na data-base."""
    duracoes = [rng.lognormvariate(log(m), sigma) for m in medianas_anos]   # uma por transição
    datas = [(etapas[0], entrada)]
    if saida is not None:
        escala, t = (saida - entrada) / sum(duracoes), entrada
        for nome, d in zip(etapas[1:], duracoes):
            t += d * escala
            datas.append((nome, t))
        datas[-1] = (etapas[-1], saida)                     # sem resíduo de ponto flutuante
        return datas
    t = entrada
    for nome, d in zip(etapas[1:-1], duracoes):             # a etapa final fica de fora
        t += d
        if t >= data_base:
            break
        datas.append((nome, t))
    return datas


def situacao(ciclo: str, etapas: list, encerrada: bool) -> str:
    if encerrada:
        return CICLOS[ciclo][2]
    return SITUACAO_DA_ETAPA.get(etapas[-1][0], "EM PROCESSO")
