"""O conteúdo protegido: o cadastro consolidado de passivos perigosos pendentes.

A visão consolidada é exatamente o artefato que o sistema existe para
proteger: por isso cada nível recebe só a parte que lhe cabe.

Camada causal (exigência do professor): toda pendência registra
  - a ATIVIDADE GERADORA (AG-01 a AG-13): de onde o passivo veio;
  - o MOTIVO DA PERMANÊNCIA (MP-01 a MP-10): por que ele continua lá.
O motivo é o que converte o cadastro em instrumento de decisão: MP-01 é
cobrança, MP-06 é orçamento público, MP-05 é fila de capacidade instalada.
"""
from dataclasses import dataclass
from datetime import date

# Agrupamento dos motivos pela ação que exigem (camada causal)
GRUPOS_MOTIVO = {
    "Cobrável do responsável": ("MP-01", "MP-02", "MP-03", "MP-09"),
    "Falta de destino técnico": ("MP-04", "MP-05", "MP-10"),
    "Depende de recurso público": ("MP-06", "MP-07"),
    "Carga em local desconhecido": ("MP-08",),
}


def grupo_do_motivo(codigo: str) -> str:
    return next(g for g, codigos in GRUPOS_MOTIVO.items() if codigo in codigos)


@dataclass(frozen=True)
class RegiaoSensivel:
    """Retângulo de um relatório que só aparece íntegro para nível >= nivel_minimo.

    Quem desenha o relatório produz as regiões; quem aplica a TARJA (S8) as
    consome. O tipo mora no domínio para as duas camadas falarem a mesma língua
    sem uma depender da outra."""
    x: int
    y: int
    largura: int
    altura: int
    rotulo: str                # ENDERECO, COORDENADA, RESPONSAVEL, CUSTODIA...
    nivel_minimo: int          # 2 ou 3


@dataclass(frozen=True)
class AtividadeGeradora:
    """Catálogo das atividades. `nome` é o rótulo curto (até 40 caracteres)."""
    codigo: str
    nome: str
    descricao_operacional: str = ""
    cnae_subclasse: str = ""
    exemplos: str = ""
    observacao: str | None = None

    @property
    def descricao(self) -> str:                  # compatibilidade: nome antigo da coluna
        return self.nome

    @property
    def rotulo(self) -> str:
        return f"{self.codigo} · {self.nome}"


@dataclass(frozen=True)
class MotivoPermanencia:
    """Catálogo dos motivos. `grupo` = quem paga (COBRAVEL, PUBLICO, INFRAESTRUTURA,
    FISCALIZACAO)."""
    codigo: str
    nome: str
    descricao_operacional: str = ""
    base_legal: str | None = None
    grupo: str = ""
    acao_institucional: str | None = None

    @property
    def descricao(self) -> str:
        return self.nome

    @property
    def rotulo(self) -> str:
        return f"{self.codigo} · {self.nome}"


def rotulo(codigo: str, catalogo: dict) -> str:
    """'AG-08 · RADIOTERAPIA E FONTES SELADAS': nenhum código aparece sem o nome."""
    item = catalogo.get(codigo)
    return item.rotulo if item is not None else codigo


@dataclass(frozen=True)
class Responsavel:
    """Nomeia empresas e pessoas: só existe a partir do nível 2 (RF-21)."""
    pendencia_codigo: str
    nome: str
    vinculo: str               # GERADOR_ORIGINAL, SUCESSOR, PROPRIETARIO_ATUAL, TRANSPORTADOR, DESTINADOR
    situacao_cadastral: str
    nivel_minimo: int = 2      # 3 = só a custódia vê (ex.: pessoa física)


@dataclass(frozen=True)
class Pendencia:
    codigo: str
    substancia: str
    classe_risco: str
    quantidade: float
    unidade: str
    uf: str                    # sigla de 2 letras
    municipio: str
    logradouro: str
    numero: str                # "1500" ou "S/N"
    complemento: str | None    # "GALPAO 3", "QUADRA 7 LOTE 12"...
    bairro: str
    cep: str                   # 8 dígitos, sem hífen
    latitude: float
    longitude: float
    data_identificacao: date   # quando o passivo entrou no cadastro (histórico do risco)
    prazo_coleta: date         # previsão de coleta
    situacao: str
    atividade: str             # AG-xx  (RF-19: nunca vazio)
    motivo: str                # MP-xx
    sintetico: bool = True
    fonte: str = "BASE CONSOLIDADA ECOSECURITY (ECOSEC/ACERVO/SINTETICOS.PY)"
    # ciclo de vida: a data de encerramento é a da etapa final, nunca sorteada à parte
    data_encerramento: date | None = None
    etapa_atual: str = "IDENTIFICACAO"
    etapas: tuple = ()                 # ((nome, data), ...) em ordem; a última é a etapa_atual

    def ativa(self, em: date) -> bool:
        """Já identificada em `em` e ainda não encerrada."""
        return self.data_identificacao <= em and (self.data_encerramento is None or self.data_encerramento > em)

    def encerrada(self, em: date) -> bool:
        return self.data_encerramento is not None and self.data_encerramento <= em

    @property
    def endereco(self) -> str:
        """Endereço numa linha, para fichas e relatórios: "AVENIDA X, 1500 - GALPAO 3 - CENTRO - CEP 11500-123"."""
        partes = [f"{self.logradouro}, {self.numero}"]
        if self.complemento:
            partes.append(self.complemento)
        partes += [self.bairro, f"CEP {self.cep[:5]}-{self.cep[5:]}"]
        return " - ".join(partes)

    def dias_de_atraso(self, hoje: date) -> int:
        """Atraso até `hoje`: ou até o encerramento, se já encerrou (o atraso para de crescer)."""
        fim = min(hoje, self.data_encerramento) if self.data_encerramento else hoje
        return max(0, (fim - self.prazo_coleta).days)

    def vencida(self, hoje: date) -> bool:
        return self.prazo_coleta < hoje and not self.encerrada(hoje)


@dataclass(frozen=True)
class EventoRegulatorio:
    """Anotação dos gráficos. `verificacao` = CONFIRMADO: só fato conferido na fonte vira anotação (o serviço do
    acervo descarta qualquer outro valor que tenha ficado gravado no banco)."""
    data_evento: date
    rotulo: str
    descricao: str
    classes: tuple
    efeito: str                        # ENTRADAS, SAIDAS, AMBOS, ANOTACAO
    base_legal: str | None
    verificacao: str


@dataclass(frozen=True)
class Custodia:
    """Instalação de custódia (fictícia). `tipo`: DEFINITIVO, INTERMEDIARIO, NORM ou INICIAL."""
    nome: str
    tipo: str
    longitude: float
    latitude: float
    ocupacao: float                    # fração ocupada na data-base
    uf: str = ""

    def __iter__(self):                # compatibilidade com a tupla antiga (nome, lon, lat, ocupação)
        return iter((self.nome, self.longitude, self.latitude, self.ocupacao))

    def __getitem__(self, indice):
        return (self.nome, self.longitude, self.latitude, self.ocupacao)[indice]


@dataclass(frozen=True)
class Documento:
    """Documento administrativo de uma pendência, derivado das etapas (acervo/documentos.py).
    Metadados: o N2 lista; o conteúdo só o N3 abre (matriz, operação VISUALIZAR_DOCUMENTO)."""
    id: int
    tipo: str                          # LICENCA DE OPERACAO, LAUDO DE VISTORIA, AUTO DE INFRACAO, ...
    numero: str
    data: date
    situacao: str
    pendencia_codigo: str


@dataclass(frozen=True)
class RelatorioCatalogo:
    """Um relatório do acervo: o banco diz QUAIS existem e o nível mínimo de cada um."""
    codigo: str
    titulo: str
    nivel_minimo: int
    descricao: str = ""
    sintetico: bool = True
