"""Risco do CONTEXTO do login: a verificação se adapta ao ambiente (MFA adaptativo).

A mesma matrícula, senha e rosto valem menos numa máquina que a pessoa nunca
usou, logo depois de errar a senha. Dois sinais, os dois locais (o sistema não
usa internet nem localização por ip):

  ESTACAO_NOVA         computador + usuário do Windows nunca vistos para esta matrícula
                       (o primeiro login de cada pessoa só registra a estação: não pune)
  FALHAS_RECENTES      a matrícula vem de erros seguidos (ainda não bloqueada)

  0 sinais  BAIXO   o login de sempre (matrícula, senha, rosto)
  1 sinal   MEDIO   + prova de vida (S6) já no login
  2 sinais  ALTO    + prova de vida, e a sessão fica só para consulta: sem N3 e sem
                    exportação (a matriz de autorização nega), com alerta ao administrador

O horário não é sinal de risco: o dia e a hora do acesso não pesam no risco
nem restringem nenhum nível, porque não há expediente no sistema.

Função pura: recebe o momento e os fatos, devolve o risco. Quem coleta os
fatos (estação, falhas) é o serviço de autenticação.
"""
import getpass
import hashlib
import platform
from dataclasses import dataclass
from datetime import datetime

BAIXO, MEDIO, ALTO = "BAIXO", "MEDIO", "ALTO"


@dataclass(frozen=True)
class ParametrosContexto:
    ativo: bool

    @classmethod
    def de_configuracao(cls, cfg) -> "ParametrosContexto":
        return cls(bool(cfg.secao("contexto")["ativo"]))


@dataclass(frozen=True)
class RiscoContexto:
    nivel: str
    sinais: tuple[str, ...]

    @property
    def exige_vivacidade(self) -> bool:
        return self.nivel in (MEDIO, ALTO)

    @property
    def so_consulta(self) -> bool:
        return self.nivel == ALTO

    def __str__(self) -> str:
        return f"RISCO {self.nivel}" + (f" ({', '.join(self.sinais)})" if self.sinais else "")


SEM_RISCO = RiscoContexto(BAIXO, ())


def avaliar(momento: datetime, p: ParametrosContexto, estacao_conhecida: bool | None, falhas_recentes: int) -> RiscoContexto:
    """estacao_conhecida None = primeira estação desta pessoa (só registra, não conta como sinal).
    momento não entra na avaliação: o horário nunca é sinal de risco."""
    if not p.ativo:
        return SEM_RISCO
    sinais = []
    if estacao_conhecida is False:
        sinais.append("ESTACAO_NOVA")
    if falhas_recentes > 0:
        sinais.append("FALHAS_RECENTES")
    nivel = BAIXO if not sinais else MEDIO if len(sinais) == 1 else ALTO
    return RiscoContexto(nivel, tuple(sinais))


def impressao_estacao() -> str:
    """Identifica ESTE computador e a conta do Windows, sem guardar nenhum dos dois: só o SHA-256."""
    bruto = f"{platform.node()}|{getpass.getuser()}".lower()
    return hashlib.sha256(bruto.encode("utf-8")).hexdigest()
