"""Monitor de anomalias sobre a trilha (S10): "alerta precoce", não só registro.

A trilha prova o que aconteceu; o monitor lê a trilha e aponta o que merece
atenção do administrador antes que vire incidente. Função pura sobre os
registros (nada é gravado nem alterado), consultada no relatório S-08.

Regras (janela deslizante sobre os eventos; janelas e mínimo na seção [monitor] do config):
  ALTO   VARREDURA_DE_MATRICULAS    matrículas diferentes negadas na S2 dentro da janela de rajada
  ALTO   RAJADA_DE_EXPORTACOES      exportações da mesma pessoa dentro da janela de rajada
  ALTO   SESSAO_DE_RISCO_ALTO       login concedido com risco de contexto ALTO
  MEDIO  NEGACOES_EM_SERIE          logins negados da mesma matrícula dentro da janela de negações
  MEDIO  EXPORTACAO_BARRADA         tentativa de exportar o que a matriz nega
  ALTO   ACESSO_DE_EMERGENCIA       o acesso de emergência foi aberto
  MEDIO  APROVACAO_RECUSADA         código errado ao aprovar uma ação crítica de outro administrador
  MEDIO  EMERGENCIA_RECUSADA        código errado no acesso de emergência

O horário do acesso não gera alerta: não há expediente no sistema.
"""
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta

ALTO, MEDIO = "ALTO", "MEDIO"
FALHAS_DE_CREDENCIAL = {"USUARIO_INEXISTENTE", "SENHA_INCORRETA"}


@dataclass(frozen=True)
class ParametrosMonitor:
    janela_rajada: timedelta
    janela_negacoes: timedelta
    minimo_eventos: int

    @classmethod
    def de_configuracao(cls, cfg) -> "ParametrosMonitor":
        m = cfg.secao("monitor")
        return cls(timedelta(minutes=float(m["janela_rajada_minutos"])),
                   timedelta(minutes=float(m["janela_negacoes_minutos"])), int(m["minimo_eventos"]))


def _minutos(janela: timedelta) -> str:
    return f"{janela.total_seconds() / 60:g} min"


@dataclass(frozen=True)
class Alerta:
    gravidade: str
    regra: str
    momento: datetime
    descricao: str
    usuario_id: int | None = None
    matricula: str | None = None


def _rajadas(eventos, chave, janela: timedelta, minimo: int, distintos=None):
    """Para cada chave, as janelas com minimo eventos (ou minimo valores distintos de distintos).
    Devolve (chave, primeiro evento da janela, eventos da janela), sem repetir sobreposições."""
    por_chave = defaultdict(list)
    for e in eventos:
        por_chave[chave(e)].append(e)
    achados = []
    for k, lista in por_chave.items():
        lista.sort(key=lambda e: e.momento)
        i = 0
        while i < len(lista):
            janela_eventos = [e for e in lista[i:] if e.momento - lista[i].momento <= janela]
            quantidade = len({distintos(e) for e in janela_eventos}) if distintos else len(janela_eventos)
            if quantidade >= minimo:
                achados.append((k, lista[i], janela_eventos))
                i += len(janela_eventos)                 # não reporta a mesma rajada duas vezes
            else:
                i += 1
    return achados


def detectar(registros, p: ParametrosMonitor) -> list[Alerta]:
    eventos = [r.evento for r in registros]
    alertas: list[Alerta] = []

    negados_s2 = [e for e in eventos if e.evento == "ENTRADA" and e.resultado == "NEGADO"
                  and e.motivo in FALHAS_DE_CREDENCIAL and e.matricula_informada]
    for _, primeiro, janela in _rajadas(negados_s2, lambda e: "todos", p.janela_rajada, p.minimo_eventos,
                                        distintos=lambda e: e.matricula_informada):
        matriculas = sorted({e.matricula_informada for e in janela})
        alertas.append(Alerta(ALTO, "VARREDURA_DE_MATRICULAS", primeiro.momento,
                              f"{len(matriculas)} matrículas diferentes negadas em {_minutos(p.janela_rajada)}: "
                              f"{', '.join(matriculas[:6])}"))

    exportacoes = [e for e in eventos if e.evento == "EXPORTACAO" and e.resultado == "CONCEDIDO" and e.usuario_id]
    for usuario_id, primeiro, janela in _rajadas(exportacoes, lambda e: e.usuario_id, p.janela_rajada,
                                                 p.minimo_eventos):
        alertas.append(Alerta(ALTO, "RAJADA_DE_EXPORTACOES", primeiro.momento,
                              f"{len(janela)} exportações em {_minutos(p.janela_rajada)}", usuario_id=usuario_id))

    negacoes_login = [e for e in eventos if e.evento == "ENTRADA" and e.resultado == "NEGADO" and e.matricula_informada]
    for matricula, primeiro, janela in _rajadas(negacoes_login, lambda e: e.matricula_informada,
                                                p.janela_negacoes, p.minimo_eventos):
        alertas.append(Alerta(MEDIO, "NEGACOES_EM_SERIE", primeiro.momento,
                              f"{len(janela)} logins negados em {_minutos(p.janela_negacoes)}", matricula=matricula))

    for e in eventos:
        if e.evento == "ENTRADA" and e.resultado == "CONCEDIDO" and e.detalhe and "RISCO ALTO" in e.detalhe:
            alertas.append(Alerta(ALTO, "SESSAO_DE_RISCO_ALTO", e.momento, e.detalhe, e.usuario_id,
                                  e.matricula_informada))
        elif e.evento == "EXPORTACAO" and e.resultado == "NEGADO" and e.motivo != "VERIFICACAO_EXIGIDA":
            alertas.append(Alerta(MEDIO, "EXPORTACAO_BARRADA", e.momento, f"{e.motivo}: {e.detalhe or ''}".strip(),
                                  e.usuario_id))
        elif e.evento == "EMERGENCIA" and e.resultado == "CONCEDIDO":
            alertas.append(Alerta(ALTO, "ACESSO_DE_EMERGENCIA", e.momento, e.detalhe or "acesso de emergência aberto",
                                  e.usuario_id))
        elif e.evento == "EMERGENCIA" and e.resultado == "NEGADO":
            alertas.append(Alerta(MEDIO, "EMERGENCIA_RECUSADA", e.momento, "código não aceito no acesso de emergência",
                                  e.usuario_id))
        elif e.evento == "ADMIN" and e.motivo == "APROVACAO_RECUSADA":
            alertas.append(Alerta(MEDIO, "APROVACAO_RECUSADA", e.momento, e.detalhe or "aprovação recusada",
                                  e.usuario_id, e.matricula_informada))
    return sorted(alertas, key=lambda a: (a.gravidade != ALTO, -a.momento.timestamp()))
