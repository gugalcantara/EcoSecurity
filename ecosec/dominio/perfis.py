"""Os perfis de acesso: um por cadastro, e cada um vê só a própria camada.

O nível (niveis.py) é a classificação do dado: camada 1, 2 ou 3. O perfil é quem a pessoa é no sistema, e cada
perfil tem no máximo uma camada. Não há hierarquia: o ministro não vê a camada 1 nem a 2, o diretor não vê a 1.

Quatro perfis. Servidor, diretor e ministro são do quadro do governo, cada um com a sua camada. EXTERNO é quem não é
funcionário do governo: o cadastro só registra a matrícula, o termo e o rosto; não tem camada e não entra no
sistema. O administrador não é um perfil: é um PAPEL dado pelo administrador a um cadastro Externo (tabela
`administrador`). Por isso o administrador nunca tem camada: gere pessoas, perfis, consentimentos, a trilha e a
governança, e não lê dado do acervo em nenhuma circunstância. Só o papel de administrador deixa um Externo entrar.
"""
from enum import Enum

from ecosec.dominio.niveis import Nivel


class Perfil(str, Enum):
    EXTERNO = "EXTERNO"
    SERVIDOR = "SERVIDOR"
    DIRETOR = "DIRETOR"
    MINISTRO = "MINISTRO"

    @property
    def rotulo(self) -> str:
        return self.value.capitalize()

    @property
    def camada(self) -> Nivel | None:
        return _CAMADAS[self]

    @property
    def exige_uf(self) -> bool:
        """Só o diretor tem UF: ele vê apenas a própria região."""
        return self is Perfil.DIRETOR

    def ve(self, camada) -> bool:
        """Escopo exclusivo: este perfil vê a camada pedida? Só a própria, nunca outra."""
        return self.camada is not None and self.camada == Nivel(camada)

    @classmethod
    def do_nivel(cls, nivel) -> "Perfil":
        """O perfil equivalente ao nível de um cadastro anterior à (migração e compatibilidade)."""
        return {Nivel.N1: cls.SERVIDOR, Nivel.N2: cls.DIRETOR, Nivel.N3: cls.MINISTRO}[Nivel(nivel)]


_CAMADAS = {Perfil.EXTERNO: None, Perfil.SERVIDOR: Nivel.N1, Perfil.DIRETOR: Nivel.N2, Perfil.MINISTRO: Nivel.N3}

# perfis cuja atribuição é ação crítica (pede um segundo administrador): a camada 3. Designar um
# administrador também é crítico, pela governança (servicos/administracao.py)
CRITICOS = frozenset({Perfil.MINISTRO})
