"""Os três níveis de acesso e o que cada um significa.

Tudo o que varia por nível mora aqui, num lugar só: quem é o público, o modo
biométrico, a política de exportação. Se a tela, a política e a trilha
consultassem tabelas próprias, cedo ou tarde uma delas divergiria: e a tela
anunciaria uma regra que a decisão não aplica.

Sem hierarquia: cada nível é uma CAMADA de dado, e cada perfil
(perfis.py) vê só a sua. O ministro não vê a camada 1 nem a 2; o diretor não vê a 1.
"""
from dataclasses import dataclass
from enum import Enum, IntEnum


class ModoBiometrico(str, Enum):
    # 1:N, "quem é você?": compara com todas as identidades cadastradas.
    IDENTIFICACAO = "1:N"
    # 1:1, "você é quem diz ser?": compara só com a identidade alegada.
    # Testa uma hipótese em vez de N, por isso a falsa aceitação (FAR) cai.
    VERIFICACAO = "1:1"


class Exportacao(str, Enum):
    LIVRE = "LIVRE"
    COM_MARCA = "COM_MARCA"      # marca d'água invisível com identidade e momento
    BLOQUEADA = "BLOQUEADA"      # apenas visualização, em sessão com tempo-limite


@dataclass(frozen=True)
class _PerfilNivel:
    titulo: str                  # titulo e publico espelham a tabela nivel: padrão de texto do banco
    publico: str
    conteudo: str
    modo: ModoBiometrico
    exportacao: Exportacao


class Nivel(IntEnum):
    N1 = 1
    N2 = 2
    N3 = 3

    @property
    def _perfil(self) -> _PerfilNivel:
        return _PERFIS[self]

    @property
    def titulo(self) -> str:
        return self._perfil.titulo

    @property
    def publico(self) -> str:
        return self._perfil.publico

    @property
    def conteudo(self) -> str:
        return self._perfil.conteudo

    @property
    def modo(self) -> ModoBiometrico:
        return self._perfil.modo

    @property
    def exportacao(self) -> Exportacao:
        return self._perfil.exportacao


_PERFIS = {
    Nivel.N1: _PerfilNivel(
        titulo="CONSULTA PUBLICA ASSISTIDA",
        publico="SERVIDORES COM ACESSO BASICO",
        conteudo="Estatísticas agregadas, sem localização; regiões sensíveis suprimidas",
        modo=ModoBiometrico.IDENTIFICACAO,
        exportacao=Exportacao.LIVRE),
    Nivel.N2: _PerfilNivel(
        titulo="CONSULTA RESTRITA",
        publico="DIRETORES DE DIVISAO",
        conteudo="Registros individuais da própria região, com cadeia de responsabilidade",
        modo=ModoBiometrico.VERIFICACAO,
        exportacao=Exportacao.COM_MARCA),
    Nivel.N3: _PerfilNivel(
        titulo="CUSTODIA",
        publico="MINISTRO DO MEIO AMBIENTE",
        conteudo="Visão consolidada nacional e matriz de criticidade",
        modo=ModoBiometrico.VERIFICACAO,
        exportacao=Exportacao.BLOQUEADA),
}
