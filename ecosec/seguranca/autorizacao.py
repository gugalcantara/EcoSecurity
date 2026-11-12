"""Autorização em três dimensões: PAPEL × CLASSIFICAÇÃO DO DADO × OPERAÇÃO.

Antes, cada regra morava onde era usada ("N3 não exporta" no serviço do
acervo, "N1 não tem planilha" no painel...). Aqui fica a MATRIZ inteira, num
lugar só, como função pura: o serviço pergunta, a matriz responde, e o
administrador vê a mesma matriz no relatório S-09. Inspirado no modelo
"role-data-operation" e no princípio de confiança zero: nenhuma operação é
permitida por omissão: o que não está na matriz é NEGADO.

  Papel           quem é: servidor, diretor ou ministro (o perfil) ou administrador (o papel de um Externo)
  Classificação   o grau do dado (da camada aberta): USO INTERNO, RESERVADO, SECRETO
  Operação        visualizar, exportar relatório, exportar registros, exportar agregado, administrar

Efeitos:
  PERMITIDO                    pode, já
  PERMITIDO_COM_VERIFICACAO    pode, se o ROSTO foi conferido há pouco (step-up); senão, confere antes
  NEGADO                       não pode

Escopo exclusivo: cada papel lê só a classificação da própria camada. O ministro não lê
USO INTERNO nem RESERVADO; o ADMINISTRADOR não tem camada e não lê dado nenhum (só ADMINISTRAR).

O contexto entra por cima: com risco ALTO (ver contexto.py), nenhuma
exportação e nenhum dado SECRETO: a sessão vale só para consulta.
"""
from dataclasses import dataclass
from enum import Enum, IntEnum

from ecosec.dominio.niveis import Nivel
from ecosec.dominio.perfis import Perfil


class Papel(str, Enum):
    SERVIDOR = "SERVIDOR"
    DIRETOR = "DIRETOR"
    MINISTRO = "MINISTRO"
    ADMINISTRADOR = "ADMINISTRADOR"

    @property
    def camada(self) -> Nivel | None:
        """A única camada que o papel lê; o administrador não tem nenhuma."""
        return None if self is Papel.ADMINISTRADOR else Perfil(self.value).camada


class Classificacao(IntEnum):
    USO_INTERNO = 1
    RESERVADO = 2
    SECRETO = 3

    @property
    def rotulo(self) -> str:
        return self.name.replace("_", " ")

    @classmethod
    def do_nivel(cls, nivel: int) -> "Classificacao":
        return cls(int(nivel))


class Operacao(str, Enum):
    VISUALIZAR = "VISUALIZAR"
    EXPORTAR_RELATORIO = "EXPORTAR_RELATORIO"      # o PNG de um relatório (com marca d'água no N2)
    EXPORTAR_REGISTROS = "EXPORTAR_REGISTROS"      # planilha com registros individuais
    EXPORTAR_AGREGADO = "EXPORTAR_AGREGADO"        # resumo com totais por grupo
    LISTAR_DOCUMENTOS = "LISTAR_DOCUMENTOS"        # metadados (tipo, número, data, situação): S-06
    VISUALIZAR_DOCUMENTO = "VISUALIZAR_DOCUMENTO"  # o conteúdo renderizado, com marcas e trilha
    EXPORTAR_DOCUMENTO = "EXPORTAR_DOCUMENTO"      # nunca: o documento só é visto, em nenhum nível sai
    SOMAR_POR_RESPONSAVEL = "SOMAR_POR_RESPONSAVEL"  # custo do passivo somado por responsável nomeado
    PRIORIZAR = "PRIORIZAR"                        # fila do orçamento público: só a camada 3 (o ministro)
    ADMINISTRAR = "ADMINISTRAR"                    # cadastrar, revogar, ver a trilha


class Efeito(str, Enum):
    PERMITIDO = "PERMITIDO"
    PERMITIDO_COM_VERIFICACAO = "PERMITIDO_COM_VERIFICACAO"
    NEGADO = "NEGADO"


P, V, N = Efeito.PERMITIDO, Efeito.PERMITIDO_COM_VERIFICACAO, Efeito.NEGADO

# (classificação, operação) -> efeito, para quem tem o nível do dado. Quem não tem: NEGADO sempre.
MATRIZ: dict[tuple[Classificacao, Operacao], Efeito] = {
    (Classificacao.USO_INTERNO, Operacao.VISUALIZAR): P,
    (Classificacao.USO_INTERNO, Operacao.EXPORTAR_RELATORIO): P,       # só totais, sem localização
    (Classificacao.USO_INTERNO, Operacao.EXPORTAR_AGREGADO): P,
    (Classificacao.USO_INTERNO, Operacao.EXPORTAR_REGISTROS): N,       # o N1 não tem registros individuais
    (Classificacao.RESERVADO, Operacao.VISUALIZAR): P,
    (Classificacao.RESERVADO, Operacao.EXPORTAR_RELATORIO): V,         # sai com marca d'água; rosto antes
    (Classificacao.RESERVADO, Operacao.EXPORTAR_AGREGADO): P,
    (Classificacao.RESERVADO, Operacao.EXPORTAR_REGISTROS): V,         # nomes e endereços: rosto antes
    (Classificacao.SECRETO, Operacao.VISUALIZAR): P,                   # o step-up do N3 já conferiu o rosto
    (Classificacao.SECRETO, Operacao.EXPORTAR_RELATORIO): N,
    (Classificacao.SECRETO, Operacao.EXPORTAR_AGREGADO): N,
    (Classificacao.SECRETO, Operacao.EXPORTAR_REGISTROS): N,
    # documentos administrativos (S-06): o N2 lista os metadados; o conteúdo, só o N3 abre
    (Classificacao.USO_INTERNO, Operacao.LISTAR_DOCUMENTOS): N,
    (Classificacao.RESERVADO, Operacao.LISTAR_DOCUMENTOS): P,
    (Classificacao.SECRETO, Operacao.LISTAR_DOCUMENTOS): P,
    (Classificacao.USO_INTERNO, Operacao.VISUALIZAR_DOCUMENTO): N,
    (Classificacao.RESERVADO, Operacao.VISUALIZAR_DOCUMENTO): N,
    (Classificacao.SECRETO, Operacao.VISUALIZAR_DOCUMENTO): P,
    (Classificacao.USO_INTERNO, Operacao.EXPORTAR_DOCUMENTO): N,
    (Classificacao.RESERVADO, Operacao.EXPORTAR_DOCUMENTO): N,
    (Classificacao.SECRETO, Operacao.EXPORTAR_DOCUMENTO): N,
    # soma de custo atribuída a um nome é quase uma acusação: só a custódia (N3), e nunca exportada
    (Classificacao.USO_INTERNO, Operacao.SOMAR_POR_RESPONSAVEL): N,
    (Classificacao.RESERVADO, Operacao.SOMAR_POR_RESPONSAVEL): N,
    (Classificacao.SECRETO, Operacao.SOMAR_POR_RESPONSAVEL): P,
    # fila do orçamento público: decisão nacional (só a camada 3)
    (Classificacao.USO_INTERNO, Operacao.PRIORIZAR): N,
    (Classificacao.RESERVADO, Operacao.PRIORIZAR): N,
    (Classificacao.SECRETO, Operacao.PRIORIZAR): P,
}
EXPORTACOES = (Operacao.EXPORTAR_RELATORIO, Operacao.EXPORTAR_REGISTROS, Operacao.EXPORTAR_AGREGADO,
               Operacao.EXPORTAR_DOCUMENTO)


@dataclass(frozen=True)
class Autorizacao:
    efeito: Efeito
    motivo: str                       # para a trilha e para a tela

    @property
    def permitido(self) -> bool:
        return self.efeito is not Efeito.NEGADO

    @property
    def exige_verificacao(self) -> bool:
        return self.efeito is Efeito.PERMITIDO_COM_VERIFICACAO


def papel_de(perfil: Perfil, administrador: bool = False) -> Papel:
    """O papel na matriz: o perfil do cadastro, ou ADMINISTRADOR para o Externo com esse papel. Um Externo sem o
    papel não tem papel nenhum (a S5 nem deixa entrar)."""
    perfil = Perfil(perfil)
    if perfil is Perfil.EXTERNO:
        if administrador:
            return Papel.ADMINISTRADOR
        raise ValueError("Externo sem o papel de administrador não tem papel na matriz.")
    return Papel(perfil.value)


def decidir(papel: Papel, classificacao: Classificacao, operacao: Operacao, risco: str = "BAIXO") -> Autorizacao:
    if operacao is Operacao.ADMINISTRAR:
        if papel is not Papel.ADMINISTRADOR:
            return Autorizacao(N, "SO_O_ADMINISTRADOR")
        return Autorizacao(V, "ADMINISTRACAO_COM_ROSTO")
    if papel.camada is None or int(papel.camada) != int(classificacao):     # escopo exclusivo; admin sem camada
        return Autorizacao(N, "NIVEL_INSUFICIENTE")
    if risco == "ALTO" and (operacao in EXPORTACOES or classificacao is Classificacao.SECRETO):
        return Autorizacao(N, "RISCO_CONTEXTUAL_ALTO")
    efeito = MATRIZ.get((classificacao, operacao), N)        # fora da matriz: negado (confiança zero)
    # códigos curtos: a coluna log_acesso.motivo tem 40 caracteres
    negado = "SEM_REGISTROS_NO_NIVEL" if operacao is Operacao.EXPORTAR_REGISTROS and \
        classificacao is Classificacao.USO_INTERNO else "EXPORTACAO_BLOQUEADA" if operacao in EXPORTACOES \
        else "RESPONSAVEL_SO_NO_NIVEL_3" if operacao is Operacao.SOMAR_POR_RESPONSAVEL \
        else "PRIORIZACAO_SO_NO_NIVEL_3" if operacao is Operacao.PRIORIZAR \
        else "DOCUMENTO_SO_NO_NIVEL_3"
    return Autorizacao(efeito, {P: "PERMITIDO", V: "EXIGE_ROSTO_RECENTE", N: negado}[efeito])


def tabela() -> list[tuple[str, str, str, str]]:
    """A matriz por extenso, para o relatório S-09 do administrador: (papel, classificação, operação, efeito)."""
    linhas = []
    for papel in Papel:
        for classificacao in Classificacao:
            for operacao in Operacao:
                if operacao is Operacao.ADMINISTRAR and classificacao is not Classificacao.USO_INTERNO:
                    continue                                   # administrar não depende da classificação
                a = decidir(papel, classificacao, operacao)
                linhas.append((papel.value, "-" if operacao is Operacao.ADMINISTRAR else classificacao.rotulo,
                               operacao.value, a.efeito.value))
    return linhas


