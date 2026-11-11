"""Veredito: a resposta de uma camada à sua pergunta.

Todas as camadas do Anel 1 devolvem o mesmo tipo. É isso que permite à
política compô-las em sequência e à tela mostrar "S1 ✓  S2 ✓  S3 ✗".
"""
from dataclasses import dataclass

from ecosec.dominio.camadas import CamadaSeguranca
from ecosec.dominio.motivos import Motivo


@dataclass(frozen=True)
class Veredito:
    camada: CamadaSeguranca
    motivo: Motivo | None = None      # None = camada aprovada

    @property
    def aprovado(self) -> bool:
        return self.motivo is None

    def __str__(self):
        if self.aprovado:
            return f"{self.camada.codigo} ✓"
        return f"{self.camada.codigo} ✗ {self.motivo.value}"


def aprovar(camada: CamadaSeguranca) -> Veredito:
    return Veredito(camada)


def negar(motivo: Motivo, camada: CamadaSeguranca | None = None) -> Veredito:
    """Nega pela camada do motivo, ou por outra quando o motivo é genérico
    (ex.: ERRO_INTERNO detectado dentro da S5)."""
    camada = camada or motivo.camada
    if camada is None:
        raise ValueError(f"{motivo.value} não pertence a uma camada; informe qual negou.")
    return Veredito(camada, motivo)
