"""Entidades do controle de acesso.

Imutáveis (frozen): para mudar um usuário, cria-se uma cópia com
dataclasses.replace(). Assim nenhuma camada altera em silêncio um objeto que
outra camada ainda está avaliando.

As invariantes ficam aqui, não no formulário: um diretor de nível 2 sem região
veria todas as UFs se algum filtro falhasse. Um objeto Usuario nesse estado
simplesmente não pode existir.
"""
from dataclasses import dataclass, field
from datetime import datetime

from ecosec.dominio import texto
from ecosec.dominio.niveis import Nivel
from ecosec.dominio.perfis import Perfil

# mesmo tamanho da coluna no banco: a regra mora no domínio, e o banco a repete
MATRICULA_MAX = 20

UFS = frozenset("AC AL AP AM BA CE DF ES GO MA MT MS MG PA PB PR PE PI RJ RN RS RO RR SC SP SE TO".split())


class ErroDominio(ValueError):
    """Tentativa de criar um objeto que viola uma regra do domínio."""


@dataclass(frozen=True)
class Usuario:
    """Um cadastro tem um perfil (perfis.py). O `nivel` é a camada desse perfil: None para o Externo (inclusive o
    administrador, que é um papel de um Externo). Quem cria pelo nível recebe o perfil equivalente."""
    matricula: str
    nome: str
    nivel: Nivel | None
    # repr=False: o hash nunca aparece em print, log ou mensagem de erro
    senha_hash: str = field(repr=False)
    uf: str | None = None
    ativo: bool = True
    id: int | None = None          # atribuído pelo repositório; é o rótulo no LBPH
    criado_em: datetime | None = None
    perfil: Perfil | None = None
    excluido_em: datetime | None = None   # exclusão lógica: irreversível; a trilha e a prova ficam

    def __post_init__(self):
        nivel = Nivel(self.nivel) if self.nivel is not None else None
        if self.perfil is None:
            perfil = Perfil.do_nivel(nivel) if nivel is not None else Perfil.EXTERNO
        else:
            perfil = Perfil(self.perfil)
            if nivel is None:
                nivel = perfil.camada
            elif nivel != perfil.camada:
                raise ErroDominio(f"Perfil {perfil.rotulo} não combina com o nível {nivel.value}.")
        object.__setattr__(self, "nivel", nivel)
        object.__setattr__(self, "perfil", perfil)
        # padrão de texto do banco: maiúsculas, sem acento ("José da Silva" -> "JOSE DA SILVA")
        if self.nome:
            object.__setattr__(self, "nome", texto.nome(self.nome))
        if not self.matricula or not self.matricula.strip():
            raise ErroDominio("Matrícula vazia.")
        if len(self.matricula.strip()) > MATRICULA_MAX:
            raise ErroDominio(f"Matrícula com mais de {MATRICULA_MAX} caracteres.")
        if not self.nome or not self.nome.strip():
            raise ErroDominio("Nome vazio.")
        if not self.senha_hash:
            raise ErroDominio("Usuário sem hash de senha.")
        if self.uf is not None and self.uf not in UFS:
            raise ErroDominio(f"UF inválida: {self.uf!r}.")
        if perfil.exige_uf and self.uf is None:
            raise ErroDominio("Usuário de nível 2 precisa de UF: ele só vê a própria região.")
        if not perfil.exige_uf and self.uf is not None:
            raise ErroDominio(f"Só o diretor tem UF; o perfil {perfil.rotulo} não tem região.")
        if self.excluido_em is not None and self.ativo:
            raise ErroDominio("Cadastro excluído não fica ativo.")


@dataclass(frozen=True)
class Amostra:
    """METADADO de uma amostra facial. A imagem em si nunca é guardada: ela
    treina o modelo e é descartada. A sessão é a base da divisão treino/teste
    dos experimentos (por sessão, não por quadro)."""
    usuario_id: int
    sessao: int
    origem: str                     # "webcam"
    qualidade: float
    id: int | None = None
    criada_em: datetime | None = None


@dataclass(frozen=True)
class EventoTrilha:
    """Um fato a registrar na trilha de auditoria (S10)."""
    momento: datetime
    evento: str                      # AUTENTICACAO, CADASTRO, ADMIN, CONSULTA, EXPORTACAO...
    resultado: str                   # CONCEDIDO, NEGADO ou REGISTRADO
    motivo: str
    camadas: str = ""                # camadas avaliadas: "S1,S2,S3"
    nivel_solicitado: int | None = None
    usuario_id: int | None = None
    usuario2_id: int | None = None   # segunda pessoa da regra dos dois
    matricula_informada: str | None = None
    distancia: float | None = None
    detalhe: str | None = None


@dataclass(frozen=True)
class RegistroTrilha:
    """Evento já encadeado: guarda o hash do anterior e o próprio."""
    evento: EventoTrilha
    hash_anterior: str
    hash_registro: str
    id: int | None = None


@dataclass(frozen=True)
class RegistroTentativas:
    """Estado da S1 Contenção para uma matrícula.

    Indexado pela matrícula digitada, exista ela ou não: se só matrículas reais
    fossem bloqueadas, o bloqueio revelaria quais matrículas existem.
    """
    matricula: str
    falhas: int = 0
    bloqueado_ate: datetime | None = None


@dataclass(frozen=True)
class Administrador:
    """O PAPEL de administrador de um cadastro. Não é outra pessoa nem outro login.

    Uma pessoa tem um cadastro (um rosto, uma matrícula) e pode ter mais de um
    papel: "ministro (N3)" pelo nível e "administrador" por esta linha. Duas
    identidades para o mesmo rosto confundiriam o reconhecimento 1:N, guardariam
    a biometria duas vezes e deixariam o rosto num cadastro ao revogar o outro.

    O segredo do celular (TOTP) chega aqui já cifrado: o repositório guarda um
    texto opaco, e só o serviço, com a chave do .env, o abre.
    """
    usuario_id: int
    designado_em: datetime
    designado_por: int | None = None          # None: configuração inicial (senha de instalação) ou migração
    aprovado_por: int | None = None           # segundo administrador; None na fase de implantação
    segredo_totp: str | None = field(default=None, repr=False)   # None = celular ainda não cadastrado
    ultimo_passo: int | None = None           # último código aceito (anti-repetição)
    ativo: bool = True
    removido_em: datetime | None = None

    def __post_init__(self):
        if self.aprovado_por is not None and self.aprovado_por == self.designado_por:
            raise ErroDominio("Ninguém aprova o próprio pedido.")

    @property
    def celular_cadastrado(self) -> bool:
        return self.segredo_totp is not None


@dataclass(frozen=True)
class CodigoRecuperacao:
    """Código de uso único para quem perdeu o celular. Só o SHA-256 é guardado."""
    usuario_id: int
    hash_codigo: str
    criado_em: datetime
    usado_em: datetime | None = None
    id: int | None = None


@dataclass(frozen=True)
class Consentimento:
    """Aceite do termo de uso da imagem facial (LGPD art. 11, I).

    Guarda o HASH do texto apresentado, não só a versão: provar o consentimento
    é ônus de quem trata o dado (art. 8º, §2º), e "aceitou a v1.0" não provaria
    nada se o texto da v1.0 mudasse depois. A revogação é marcada, nunca
    apagada: a baixa também é evidência.
    """
    titular_nome: str
    versao_termo: str
    hash_termo: str
    momento: datetime
    usuario_id: int | None = None
    revogado_em: datetime | None = None
    id: int | None = None
    # finalidade (b): estatísticas e experimentos. A (a), autenticação, é implícita
    # Sem ela não existe consentimento nem cadastro.
    autoriza_pesquisa: bool = False

    @property
    def vigente(self) -> bool:
        return self.revogado_em is None
