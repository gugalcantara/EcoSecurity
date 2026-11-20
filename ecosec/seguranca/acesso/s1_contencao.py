"""S1 Contenção: esta matrícula ainda pode tentar?"""
from dataclasses import dataclass
from datetime import datetime, timedelta

from ecosec.dominio.camadas import CamadaSeguranca
from ecosec.dominio.entidades import RegistroTentativas
from ecosec.dominio.motivos import Motivo
from ecosec.seguranca.acesso.veredito import Veredito, aprovar, negar

CAMADA = CamadaSeguranca.S1_CONTENCAO


@dataclass(frozen=True)
class ParametrosContencao:
    tentativas_maximas: int
    bloqueio: timedelta

    @classmethod
    def de_configuracao(cls, cfg) -> "ParametrosContencao":
        return cls(int(cfg["s1_contencao.tentativas_maximas"]),
                   timedelta(minutes=cfg["s1_contencao.bloqueio_minutos"]))


def esta_bloqueado(registro: RegistroTentativas | None, agora: datetime) -> bool:
    """Nenhum registro = nunca falhou = livre."""
    return (registro is not None and registro.bloqueado_ate is not None
            and agora < registro.bloqueado_ate)


def avaliar(bloqueado: bool | None) -> Veredito:
    # `is not False`: só passa quem foi consultado e está livre. None (não
    # consultado) nega: falha segura.
    if bloqueado is not False:
        return negar(Motivo.BLOQUEADO)
    return aprovar(CAMADA)


def registrar_falha(registro: RegistroTentativas | None, matricula: str, agora: datetime,
                    parametros: ParametrosContencao) -> RegistroTentativas:
    """Novo estado após uma falha de identidade."""
    falhas = 0 if registro is None else registro.falhas
    if registro is not None and registro.bloqueado_ate is not None and agora >= registro.bloqueado_ate:
        falhas = 0                       # bloqueio cumprido: contagem recomeça
    falhas += 1
    if falhas >= parametros.tentativas_maximas:
        return RegistroTentativas(matricula, 0, agora + parametros.bloqueio)
    return RegistroTentativas(matricula, falhas, None)


def registrar_sucesso(matricula: str) -> RegistroTentativas:
    """Autenticação completa zera a contagem."""
    return RegistroTentativas(matricula)
