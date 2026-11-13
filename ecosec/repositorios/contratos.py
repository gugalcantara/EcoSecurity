"""Contratos dos repositórios: o que se guarda e se consulta, sem dizer como.

Protocol (tipagem estrutural): qualquer classe com estes métodos cumpre o
contrato, sem precisar herdar de nada. O serviço de autenticação recebe "algo
que cumpra RepositorioUsuarios": hoje a versão em memória, depois a MySQL.

Regras comuns a todas as implementações:
- devolvem entidades do domínio (imutáveis), nunca linhas cruas do banco;
- consulta sem resultado devolve None, não levanta exceção;
- violação de regra de armazenamento (matrícula repetida, id inexistente)
  levanta ErroRepositorio: o chamador decide o que dizer ao usuário.
"""
from collections.abc import Callable
from datetime import datetime
from typing import Protocol

from ecosec.dominio.entidades import (Administrador, Amostra, CodigoRecuperacao, Consentimento, RegistroTentativas,
                                     RegistroTrilha, Usuario)


class ErroRepositorio(Exception):
    """Operação recusada pelo armazenamento."""


class MatriculaDuplicada(ErroRepositorio):
    pass


class RegistroInexistente(ErroRepositorio):
    pass


class BancoIndisponivel(ErroRepositorio):
    """Servidor fora do ar, credencial errada, schema ausente. Quem recebe NEGA."""


class PermissaoNegada(ErroRepositorio):
    """A conta da aplicação tentou algo que o banco não lhe concede. É defeito
    (ou ataque): nunca deve acontecer no fluxo normal."""


class RepositorioUsuarios(Protocol):
    def adicionar(self, usuario: Usuario) -> Usuario:
        """Grava e devolve o usuário com id e criado_em preenchidos."""
        ...

    def por_id(self, usuario_id: int) -> Usuario | None: ...

    def por_matricula(self, matricula: str) -> Usuario | None: ...

    def listar(self) -> list[Usuario]: ...

    def atualizar(self, usuario: Usuario) -> None:
        """Substitui o registro de mesmo id. A matrícula não muda."""
        ...


class RepositorioTentativas(Protocol):
    """Estado da S1 Contenção, por matrícula digitada."""

    def obter(self, matricula: str) -> RegistroTentativas | None: ...

    def salvar(self, registro: RegistroTentativas) -> None: ...

    def bloqueadas(self, agora: datetime) -> list[RegistroTentativas]:
        """Matrículas com bloqueio ainda vigente em agora (relatório S-03)."""
        ...


class RepositorioConsentimentos(Protocol):
    def registrar(self, consentimento: Consentimento) -> Consentimento:
        """Grava o aceite (ainda sem usuário: o termo vem antes da captura)."""
        ...

    def vincular(self, consentimento_id: int, usuario_id: int) -> None:
        """Associa o aceite ao usuário criado ao fim do cadastro."""
        ...

    def vigente_de(self, usuario_id: int) -> Consentimento | None: ...

    def de_usuario(self, usuario_id: int) -> list[Consentimento]:
        """Histórico completo (vigentes e revogados), do mais antigo ao mais novo."""
        ...

    def revogar(self, usuario_id: int, momento: datetime) -> bool:
        """Marca a revogação (nunca apaga). True se havia um vigente."""
        ...


class RepositorioAmostras(Protocol):
    """Metadados das amostras faciais (sessão, qualidade). Nunca a imagem."""

    def registrar(self, amostras: list[Amostra]) -> None: ...

    def por_usuario(self, usuario_id: int) -> list[Amostra]: ...


class RepositorioTrilha(Protocol):
    """Trilha de auditoria (S10). Só cresce: não há alterar nem apagar no contrato.

    O encadeamento é calculado pela camada de segurança; o repositório garante a
    atomicidade: lê o último hash e grava o novo sem que outra gravação entre
    no meio. Por isso recebe uma função `montar(hash_anterior)` e a executa
    dentro da trava. (hash_anterior = None quando a trilha está vazia.)
    """

    def acrescentar(self, montar: Callable[[str | None], RegistroTrilha]) -> RegistroTrilha: ...

    def todos(self) -> list[RegistroTrilha]:
        """Em ordem de gravação (id crescente)."""
        ...

    def recentes(self, limite: int) -> list[RegistroTrilha]:
        """Os últimos limite, do mais novo para o mais antigo."""
        ...


class RepositorioAdministradores(Protocol):
    """O papel de administrador de cada cadastro, e os códigos de recuperação.

    Não há apagar: tirar o papel é marcar `ativo = False` e removido_em, e um
    código usado fica marcado com usado_em. A história fica (e a trilha a conta).
    """

    def listar(self) -> list[Administrador]:
        """Todos, ativos e removidos, em ordem de designação."""
        ...

    def obter(self, usuario_id: int) -> Administrador | None: ...

    def salvar(self, administrador: Administrador) -> None:
        """Grava ou substitui o registro do mesmo usuario_id."""
        ...

    def registrar_passo(self, usuario_id: int, passo: int) -> bool:
        """Grava o último código aceito só se for maior que o atual (atômico). False = já usado."""
        ...

    def trocar_codigos(self, usuario_id: int, hashes: list[str], momento: datetime) -> None:
        """Inutiliza os códigos ainda não usados da pessoa e grava os novos."""
        ...

    def codigos_validos(self, usuario_id: int) -> list[CodigoRecuperacao]: ...

    def usar_codigo(self, codigo_id: int, momento: datetime) -> bool:
        """Marca como usado só se ainda não estava (atômico). False = alguém usou antes."""
        ...


class RepositorioEstacoes(Protocol):
    """Estações (computador + conta do Windows, só o SHA-256) em que cada pessoa já entrou.
    Alimenta o sinal ESTACAO_NOVA do risco de contexto."""

    def conhecidas(self, usuario_id: int) -> set[str]: ...

    def registrar(self, usuario_id: int, impressao: str, momento: datetime) -> None: ...


class RepositorioAcervo(Protocol):
    """O cofre: só leitura. No MySQL, a conta usada nem tem permissão de escrita.

    responsaveis recebe o NÍVEL de quem consulta e devolve só os responsáveis
    com nivel_minimo <= nível. O filtro acontece NA CONSULTA: o que o
    nível não autoriza nem sai do banco.
    """

    def catalogo(self) -> list: ...

    def atividades(self) -> list: ...

    def motivos(self) -> list: ...

    def eventos(self) -> list:
        """Eventos regulatórios (anotações dos gráficos)."""
        ...

    def pendencias(self, uf: str | None = None) -> list:
        """uf=None: nacional. Ordenadas por código."""
        ...

    def responsaveis(self, nivel: int, uf: str | None = None) -> list: ...
