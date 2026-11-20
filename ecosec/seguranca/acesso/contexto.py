"""Risco do login pelo contexto (MFA adaptativo)."""
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
    """Identifica este computador e a conta do Windows, sem guardar nenhum dos dois: só o SHA-256."""
    bruto = f"{platform.node()}|{getpass.getuser()}".lower()
    return hashlib.sha256(bruto.encode("utf-8")).hexdigest()
