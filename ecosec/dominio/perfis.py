"""Perfis de acesso e o nível de cada um."""
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
