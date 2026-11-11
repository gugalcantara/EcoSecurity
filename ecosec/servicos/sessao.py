"""Sessão da aplicação: quem entrou pelo login de entrada, e o que vê.

Nada da aplicação aparece antes do login. Depois dele, a sessão diz:
- o PAPEL da pessoa: o perfil do cadastro (servidor, diretor ou ministro), ou
  administrador, o papel dado a um cadastro Externo;
- as abas de camada que ela vê: só a do próprio perfil (escopo exclusivo). O
  administrador não tem camada: não vê aba nenhuma, nem o acervo, nunca. As
  outras camadas nem são mencionadas.

Quem decide se uma aba abre é a política (ServicoAutenticacao.abrir_nivel ou o
step-up do N3), nunca a sessão: a sessão só organiza a navegação.

A saída (pelo botão) e o bloqueio por inatividade ficam registrados na trilha.
"""
import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime

from ecosec.dominio.entidades import Usuario
from ecosec.dominio.niveis import Nivel
from ecosec.servicos.autenticacao import IdentidadeComprovada

log = logging.getLogger(__name__)


class UltimaVerificacao:
    """Quando o rosto foi conferido pela última vez nesta sessão (login, step-up do N3, painel,
    ou a conferência pedida antes de exportar). Uma operação crítica só passa se isto for recente."""

    def __init__(self, momento: datetime):
        self._momento = momento
        self._lock = threading.Lock()

    @property
    def momento(self) -> datetime:
        with self._lock:
            return self._momento

    def registrar(self, momento: datetime) -> None:
        with self._lock:
            self._momento = max(self._momento, momento)


@dataclass(frozen=True)
class SessaoAplicacao:
    usuario: Usuario
    identidade: IdentidadeComprovada | None      # None só no acesso de emergência (o rosto falhou)
    administrador: bool
    inicio: datetime
    verificacao: UltimaVerificacao = field(default=None, compare=False, repr=False)
    emergencia: object | None = None             # servicos.administracao.Emergencia

    def __post_init__(self):
        if self.verificacao is None:                 # o login acabou de conferir o rosto
            object.__setattr__(self, "verificacao", UltimaVerificacao(self.inicio))

    @property
    def em_emergencia(self) -> bool:
        return self.emergencia is not None

    @property
    def risco(self) -> str:
        return self.identidade.risco.nivel if self.identidade else "ALTO"

    @property
    def papel(self) -> str:
        if self.em_emergencia:
            return "Acesso de emergência"
        return "Administrador" if self.administrador else self.usuario.perfil.rotulo

    @property
    def niveis_com_aba(self) -> tuple[Nivel, ...]:
        """Só a camada do perfil. Externo (inclusive o administrador) e emergência: nenhuma."""
        camada = self.usuario.perfil.camada
        return () if self.em_emergencia or camada is None else (camada,)


class ServicoSessao:
    def __init__(self, usuarios, administracao, trilha=None, *, inatividade_minutos: float,
                 relogio=datetime.now):
        self.usuarios, self.administracao, self.trilha = usuarios, administracao, trilha
        self.inatividade_minutos = inatividade_minutos
        self.relogio = relogio

    def abrir(self, sessao_entrada) -> SessaoAplicacao | None:
        """A partir de um login de ENTRADA concedido; None para qualquer outra coisa."""
        identidade = sessao_entrada.identidade_comprovada if sessao_entrada is not None else None
        usuario = self.usuarios.por_id(identidade.usuario_id) if identidade else None
        if usuario is None:
            return None
        return SessaoAplicacao(usuario, identidade, self.administracao.eh_administrador(usuario.id),
                               self.relogio())

    def abrir_emergencia(self, emergencia) -> SessaoAplicacao | None:
        """Sessão restrita do acesso de emergência: sem identidade comprovada (o rosto falhou), sem acervo."""
        usuario = self.usuarios.por_id(emergencia.usuario_id) if emergencia is not None else None
        if usuario is None or not emergencia.valida(self.relogio()):
            return None
        return SessaoAplicacao(usuario, None, True, self.relogio(), emergencia=emergencia)

    def encerrar(self, sessao: SessaoAplicacao | None, motivo: str = "SAIDA") -> None:
        """Melhor esforço: sair nunca pode falhar por causa do log (sair é a ação segura)."""
        self.registrar(sessao, motivo)

    def registrar(self, sessao: SessaoAplicacao | None, motivo: str) -> None:
        """Fato da sessão na trilha (SAIDA, BLOQUEIO_INATIVIDADE...). Melhor esforço."""
        if sessao is None or self.trilha is None:
            return
        try:
            self.trilha.registrar("SESSAO", "REGISTRADO", motivo, usuario_id=sessao.usuario.id,
                                  matricula_informada=sessao.usuario.matricula,
                                  detalhe="acesso de emergência" if sessao.em_emergencia else None)
        except Exception:  # noqa: BLE001
            log.exception("Falha ao registrar o fim da sessão")
