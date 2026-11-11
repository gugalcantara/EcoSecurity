"""As dez camadas de segurança do EcoSecurity, em três anéis.

Cada camada responde a uma pergunta. O código (S1...S10) atravessa o sistema
inteiro: nome dos módulos, faixa de etapas na tela, campo de fatores na trilha
de auditoria e seções do documento.

A numeração do Anel 1 é também a ORDEM de avaliação: S1 antes de S2, S2 antes
de S3... Por isso não abrimos a câmera (S3, S4) para quem já errou a senha (S2).
"""
from dataclasses import dataclass
from enum import Enum

from ecosec.dominio.niveis import Nivel


class Anel(str, Enum):
    ACESSO = "Acesso"          # quem pode entrar
    CONTEUDO = "Conteúdo"      # o que pode ver, e o que acontece se vazar
    EVIDENCIA = "Evidência"    # o que aconteceu


@dataclass(frozen=True)
class _Ficha:
    codigo: str
    nome: str
    pergunta: str
    anel: Anel
    niveis: frozenset


def _ficha(codigo, nome, pergunta, anel, *niveis):
    return _Ficha(codigo, nome, pergunta, anel, frozenset(Nivel(n) for n in niveis))


class CamadaSeguranca(Enum):
    S1_CONTENCAO = _ficha("S1", "Contenção", "Esta matrícula ainda pode tentar?", Anel.ACESSO, 2, 3)
    S2_CONHECIMENTO = _ficha("S2", "Conhecimento", "Sabe o segredo?", Anel.ACESSO, 2, 3)
    S3_QUALIDADE = _ficha("S3", "Qualidade", "A imagem permite decidir?", Anel.ACESSO, 1, 2, 3)
    S4_INERENCIA = _ficha("S4", "Inerência", "É quem diz ser?", Anel.ACESSO, 1, 2, 3)
    S5_HABILITACAO = _ficha("S5", "Habilitação", "Tem direito?", Anel.ACESSO, 1, 2, 3)
    S6_VIVACIDADE = _ficha("S6", "Vivacidade", "É uma pessoa viva, não uma foto?", Anel.ACESSO, 3)
    S7_CUSTODIA = _ficha("S7", "Custódia", "Outra pessoa confirma?", Anel.ACESSO, 3)
    S8_TARJA = _ficha("S8", "Tarja", "O que pode ver?", Anel.CONTEUDO, 1, 2, 3)
    S9_RASTREIO = _ficha("S9", "Rastreio", "Se vazar, de quem veio?", Anel.CONTEUDO, 2, 3)
    S10_TRILHA = _ficha("S10", "Trilha", "O que aconteceu, e alguém alterou o registro?",
                        Anel.EVIDENCIA, 1, 2, 3)

    @property
    def codigo(self) -> str:
        return self.value.codigo

    @property
    def nome(self) -> str:
        return self.value.nome

    @property
    def pergunta(self) -> str:
        return self.value.pergunta

    @property
    def anel(self) -> Anel:
        return self.value.anel

    @property
    def niveis(self) -> frozenset:
        return self.value.niveis

    def atua_no(self, nivel: Nivel) -> bool:
        return nivel in self.niveis

    def __str__(self):
        return f"{self.codigo} {self.nome}"


def camadas_do_anel(anel: Anel) -> tuple:
    return tuple(c for c in CamadaSeguranca if c.anel is anel)
