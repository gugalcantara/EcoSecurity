"""Consulta ao acervo: o Anel 2 inteiro, numa ordem que não pode mudar.

    0. Autoriza pela matriz Papel × Classificação × Operação (seguranca/autorizacao.py),
       com o risco de contexto da sessão por cima. Nada é decidido fora da matriz.
    1. Filtra na origem: o N2 só recebe a própria UF; o N1 nem recebe a cadeia
       de responsáveis (RF-21): o que o nível não autoriza nem sai do banco.
    2. Desenha o relatório na hora (o desenho anota as regiões sensíveis).
    3. S8 TARJA: suprime, numa cópia, o que está acima do nível (RF-10).
    4. Marca visível: nos três níveis, a matrícula de quem consultou e o minuto da consulta, em diagonal
       (dissuade). Antes da S9: pintar depois degradaria a marca invisível.
    5. S9 RASTREIO: nos níveis 2 e 3, marca d'água invisível com quem e quando (RF-11).
    6. S10 TRILHA: registra a consulta. SEM REGISTRO, A IMAGEM NÃO É ENTREGUE.

Só depois do passo 6 a imagem sai do serviço. A interface nunca recebe o
pixel original de uma região que o nível não autoriza.

Escopo exclusivo: cada perfil consulta só a própria camada, e o administrador não consulta
nada. Todo método que entrega dado recebe quem pede e pergunta à matriz pelo papel dessa pessoa, mesmo quando
recebe um painel, um resumo ou um relatório já aberto: o objeto não carrega permissão.

Exportação (RF-14): N1 livre · N2 com marca d'água e rosto conferido há pouco
(step-up: se a última conferência passou da janela, a tela confere de novo) ·
N3 BLOQUEADA. Registra antes de gravar o arquivo: se a trilha falhar, nada sai.
CSV/XLSX não carregam marca d'água: a trilha guarda o SHA-256 do arquivo, uma
cópia vazada é ligada ao registro de quem a exportou.
"""
from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from pathlib import Path

import cv2
import numpy as np

from ecosec.acervo import analise, custos, desenho, quantidades, regras, relatorios, vocabulario
from ecosec.acervo.desenho import Fontes
from ecosec.dominio.acervo import RelatorioCatalogo
from ecosec.dominio.entidades import Usuario
from ecosec.dominio.niveis import Exportacao, Nivel
from ecosec.dominio.perfis import Perfil
from ecosec.seguranca import autorizacao
from ecosec.seguranca.autorizacao import Classificacao, Operacao
from ecosec.seguranca.conteudo import s8_tarja, s9_rastreio
from ecosec.seguranca.conteudo.s8_tarja import ParametrosTarja
from ecosec.seguranca.conteudo.s9_rastreio import Marca, ParametrosMarca

ROTULOS_LEGIVEIS = {"ENDERECO": "endereço", "COORDENADA": "coordenadas", "RESPONSAVEL": "responsável",
                    "CUSTODIA": "instalação de custódia", "DISTRIBUICAO_GEOGRAFICA": "área do mapa",
                    "NAO_REVISADO": "item inteiro"}

DETALHE_MAX = 200                      # tamanho da coluna log_acesso.detalhe

# Escopo exclusivo: a mensagem fala só do acesso de quem lê, nunca de outra camada
MENSAGENS = {
    "NIVEL_INSUFICIENTE": "Este conteúdo não faz parte do seu perfil.",
    "SEM_ACESSO": "Este cadastro não tem acesso aos dados do acervo.",
    "RISCO_CONTEXTUAL_ALTO": "Sessão só para consulta: exportações e conteúdo sigiloso estão bloqueados.",
    "SEM_REGISTROS_NO_NIVEL": "Este acesso não tem registros individuais para exportar.",
    ("EXPORTACAO_BLOQUEADA", Operacao.EXPORTAR_RELATORIO): "O conteúdo de custódia é só para visualização.",
    ("EXPORTACAO_BLOQUEADA", Operacao.EXPORTAR_REGISTROS): "Este acesso não exporta: a planilha é só para "
                                                           "visualização.",
    ("EXPORTACAO_BLOQUEADA", Operacao.EXPORTAR_AGREGADO): "Este acesso não exporta: o resumo é só para visualização.",
    ("EXPORTACAO_BLOQUEADA", Operacao.EXPORTAR_DOCUMENTO): "Documentos são só para visualização.",
    "DOCUMENTO_SO_NO_NIVEL_3": "O conteúdo dos documentos não faz parte deste acesso: a lista mostra só os metadados.",
    "RESPONSAVEL_SO_NO_NIVEL_3": "Custo por responsável não faz parte deste acesso.",
    "PRIORIZACAO_SO_NO_NIVEL_3": "A fila do orçamento público não faz parte deste acesso.",
    "CUSTO_NO_NIVEL_1": "Este acesso não recebe dado financeiro.",
}
COLUNAS_FINANCEIRAS = ("CUSTO ESTIMADO",)


def sem_custo(tabelas: dict) -> dict:
    """As tabelas do resumo sem as colunas em reais (N1 sem dado financeiro). Só tira
    colunas: as contagens e a supressão (k=3) ficam exatamente como saíram do cubo protegido."""
    saida = {}
    for grupo, (titulos, linhas) in tabelas.items():
        manter = [j for j, t in enumerate(titulos) if t not in COLUNAS_FINANCEIRAS]
        saida[grupo] = (tuple(titulos[j] for j in manter), [[l[j] for j in manter] for l in linhas])
    return saida


class ErroAcervo(Exception):
    """Pedido recusado (nível, exportação bloqueada). A mensagem é para a tela."""


class VerificacaoNecessaria(ErroAcervo):
    """A operação é permitida, mas o rosto precisa ser conferido de novo agora (step-up)."""


@dataclass(frozen=True)
class Painel:
    """Dados do painel analítico, já no escopo do nível (o N2 só recebe a própria UF)."""
    nivel: Nivel
    usuario_id: int
    escopo: str
    pendencias: tuple
    atividades: dict
    motivos: dict
    hoje: date
    exporta: bool = False              # decidido pela matriz no momento da consulta
    regras: "regras.ParametrosRegras | None" = None


@dataclass(frozen=True)
class MemoriaCusto:
    """Uma pendência na memória de cálculo de um responsável: rota de tratamento e componentes do custo."""
    codigo: str
    substancia: str
    classe: str
    rota: str
    componentes: tuple                 # custos.Componente
    total: float


@dataclass(frozen=True)
class ResumoAgregado:
    """Totais por grupo (UF, atividade, motivo...): o que o N1 pode ver e extrair. Calculado aqui,
    no serviço: o N1 nunca recebe os registros individuais que deram origem aos totais."""
    nivel: Nivel
    usuario_id: int
    escopo: str
    tabelas: dict                      # agrupamento -> (títulos, linhas)
    hoje: date
    exporta: bool = False
    supressao_minima: int = 0          # > 0: linhas com menos que isto (e as complementares) vêm SUPRIMIDO


@dataclass(frozen=True)
class Panorama:
    """Visão agregada por UF: Índice de Pressão, totais por classe, série de estoque e
    eventos. Nenhum registro individual nem coordenada: é o que o N1 pode ver (RF-20). A supressão de
    célula pequena é aplicada aqui, no serviço, e não só na dica da tela."""
    nivel: Nivel
    escopo: str
    ano: int
    classe: str | None
    pressao: dict                      # uf -> analise.PressaoUF
    por_classe: dict                   # uf -> {classe: ativas ou None = suprimida} (vazio se a UF foi suprimida)
    totais_classe: dict                # classe -> ativas no escopo
    serie: dict                        # analise.serie_estoque
    eventos: tuple
    supressao_minima: int
    hoje: date
    pesos: tuple = ()                  # ((componente, peso), ...) do Índice de pressão; no N1 sem custo


# ---------------------------------------------------------------- painéis temáticos do N1
# Contrato com a tela (etapa 3b). Em todos: None = número suprimido pelo k do N1 (primária ou complementar);
# `corte` = data a que os números se referem; `supressao_minima` = k aplicado (0 no N2 e no N3).
@dataclass(frozen=True)
class LinhaClasse:
    """Uma classe no painel por classe."""
    classe: str
    ativas: int | None                 # o mesmo destino da linha NACIONAL do cubo (panorama e resumo por classe)
    quantidade: float | None           # na unidade da classe (quantidades.total_da_classe); None se ativas é None
    unidade: str                       # "t" ou "m³" (quantidades.sigla)
    idade_mediana: float | None        # KPI-04, anos com uma casa
    envelhecimento: dict               # KPI-04: faixa (analise.ROTULOS_FAIXAS) -> ativas ou None


@dataclass(frozen=True)
class PainelClasse:
    """Painel 1 do N1: estoque ativo por classe, quantidade na unidade da classe e envelhecimento (KPI-04)."""
    nivel: Nivel
    escopo: str
    ano: int
    classe: str | None                 # filtro (None = todas)
    corte: date
    linhas: tuple                      # LinhaClasse na ordem de quantidades.CLASSES (só a do filtro, se houver)
    faixas: tuple                      # analise.ROTULOS_FAIXAS: <1, 1-3, 3-5, 5-10, 10-20, ≥20 anos
    total_ativas: int | None           # do recorte (todas as classes, ou a do filtro)
    idade_mediana_total: float | None
    envelhecimento_total: dict         # faixa -> ativas ou None, do recorte
    supressao_minima: int


@dataclass(frozen=True)
class LinhaUF:
    """Uma UF no painel por UF (ou a linha NACIONAL do recorte). Tudo lido do cubo protegido do corte."""
    uf: str
    regiao: str                        # "" na linha NACIONAL
    ativas: int | None                 # None = a UF some nesta vista (como no panorama)
    alem_do_prazo: int | None          # KPI-03: passou do prazo-limite da classe ([regras_negocio] sla_*)
    fora_da_previsao: int | None       # KPI-03b: o prazo de coleta do caso já passou
    suprimida: bool


@dataclass(frozen=True)
class PainelUF:
    """Painel 2 do N1: passivo por UF com as duas definições de vencida, como agregados
    com k=3. Coerente com o panorama: a mesma célula do cubo, o mesmo destino."""
    nivel: Nivel
    escopo: str
    ano: int
    classe: str | None
    corte: date
    linhas: tuple                      # LinhaUF, em ordem de UF
    total: LinhaUF                     # uf = analise.NACIONAL
    supressao_minima: int


@dataclass(frozen=True)
class LinhaCusto:
    """Um grupo (classe ou rota de tratamento) no painel de custo."""
    grupo: str
    pendencias: int | None
    custo: float | None                # R$ (KPI-05)
    por_categoria: dict                # categoria EEA (custos.CATEGORIAS_EEA) -> R$ ou None; soma = custo


@dataclass(frozen=True)
class PainelCusto:
    """Painel 3 do N1: custo do passivo ativo (KPI-05) por grupo e categoria EEA, e por responsabilidade
    financeira. Valores de simulação (fonte PARAMETRO), em R$ da data-base declarada em [custos]."""
    nivel: Nivel
    escopo: str
    ano: int
    classe: str | None
    por: str                           # "classe" ou "rota"
    corte: date
    data_base: str                     # "2026-10"
    fonte: str                         # "PARAMETRO" (fonte das rotas)
    linhas: tuple                      # LinhaCusto: visíveis por custo decrescente, suprimidas no fim por nome
    por_categoria: dict                # categoria EEA -> R$ ou None, do recorte
    por_responsabilidade: dict         # COBRAVEL/PUBLICO/INFRAESTRUTURA/FISCALIZACAO -> R$ ou None; soma = total
    total: float | None
    supressao_minima: int


@dataclass(frozen=True)
class PainelEncerramento:
    """Painel 4 do N1: evolução do encerramento. KPI-01 (curva S(t) por classe: tábua de vida anual no N1, curva
    exata do Kaplan-Meier no N2 e no N3) e KPI-02 por ano (o ano corrente marcado parcial)."""
    nivel: Nivel
    escopo: str
    classe: str | None
    corte: date                        # hoje: a curva usa todo o histórico
    curvas: dict                       # classe ou analise.TODAS -> analise.CurvaEncerramento
    taxa_anual: tuple                  # analise.TaxaAnual, do primeiro ano da série até o corrente
    exata: bool
    supressao_minima: int


@dataclass(frozen=True)
class KPI:
    """Um cartão de KPI do catálogo, com a dica "fonte · nível · corte"."""
    id: str                            # "KPI-01" ... "KPI-05", "KPI-03b"
    nome: str
    valor: float | None                # None = suprimido (ou não atingido, no KPI-01)
    unidade: str                       # "anos", "%", "R$"
    fonte: str                         # a função de analise/custos que calculou
    nivel_minimo: int
    corte: date
    observacao: str


@dataclass(frozen=True)
class ReferenciaNacional:
    """Totais do país para comparar com a UF no painel do N2 (analítico). É exatamente o que o N1
    pode ver: a linha NACIONAL do cubo protegido com o k do N1 (None = suprimido), sem nenhuma outra UF, sem
    registro individual e sem valor em reais. Assim o N2 não recebe do país nada além do que o N1 já recebe."""
    corte: date
    ativas: int | None
    criticas: int | None
    alem_do_prazo: int | None
    fora_da_previsao: int | None
    taxa_encerramento: float | None    # KPI-02 do último ano fechado, em % (None = suprimido)
    ano_taxa: int
    supressao_minima: int


# ---------------------------------------------------------------- painel do N1
# Contrato com a tela do N1 (interface/n1_painel.py). Tudo agregado, sem dado financeiro;
# None = suprimido pelo k (primária ou complementar), nunca 0. Tudo sai do cubo protegido do corte (as mesmas
# células do panorama, do resumo e dos painéis), exceto a grade motivo × classe, protegida por
# analise.proteger_grade_n1 com as margens que outra vista publica (cubo e resumo por motivo).
@dataclass(frozen=True)
class IndicadorN1:
    """Um indicador da faixa do N1: valor no corte, o mesmo valor um ano antes e a variação (em pontos
    percentuais quando a unidade é %). `melhor` diz a direção boa ("menor" ou "maior")."""
    id: str                            # "ATIVOS", "KPI-03", "KPI-03b", "CRITICOS", "KPI-02", "KPI-01", "KPI-04"
    nome: str                          # rótulo de exibição (vocabulário); o código fica na dica
    valor: float | None
    unidade: str                       # "casos", "%", "% ao ano", "anos"
    anterior: float | None
    ano_anterior: int | None           # o ano da comparação (None: não há ano anterior na série)
    variacao: float | None             # valor - anterior (None se um dos dois é None)
    melhor: str
    base: str                          # "de 1.055 casos ativos"
    corte: date
    fonte: str
    nivel_minimo: int
    observacao: str
    serie: tuple = ()                  # ((ano, valor ou None), ...) para a linha de tendência do cartão


@dataclass(frozen=True)
class GrupoN1:
    """Uma linha do cubo (região, classe ou o total do escopo) no recorte: ativas e as três subcontagens na coluna
    do recorte (a classe do filtro, ou todas), e as ativas e o além do prazo legal por classe."""
    chave: str
    nome: str
    ativas: int | None
    alem_do_prazo: int | None          # Casos além do prazo legal (KPI-03)
    fora_da_previsao: int | None       # Casos com prazo previsto vencido (KPI-03b)
    criticas: int | None               # Casos em risco crítico
    por_classe: dict                   # classe -> ativas ou None (só as classes do recorte)
    alem_por_classe: dict              # classe -> além do prazo legal ou None


@dataclass(frozen=True)
class ContagemN1:
    """Uma linha de contagem só (atividade de origem ou motivo da permanência): ativas na coluna do recorte e por
    classe. Sem subcontagens."""
    chave: str
    nome: str
    ativas: int | None
    por_classe: dict


@dataclass(frozen=True)
class PainelN1:
    """O painel analítico do N1: indicadores com a variação anual e os agregados das cinco perguntas
    que o panorama, o painel por classe, o por UF e o de encerramento não trazem. Nenhum valor em reais."""
    nivel: Nivel
    escopo: str
    ano: int
    classe: str | None
    corte: date
    hoje: date
    indicadores: tuple                 # IndicadorN1, na ordem da faixa
    nacional: GrupoN1                  # a linha do total do escopo
    regioes: tuple                     # GrupoN1 por região (analise.REGIOES)
    classes: tuple                     # GrupoN1 por classe (linha do total, coluna da classe)
    atividades: tuple                  # ContagemN1 por atividade de origem (cubo)
    motivos: tuple                     # ContagemN1 por motivo da permanência (grade protegida)
    pesos_pressao: tuple               # ((componente, peso), ...) do Índice de pressão do nível
    supressao_minima: int


@dataclass
class _ContextoPainel:
    """Um pedido de painel já autorizado: nível, escopo, corte, filtro e k. Interno ao serviço."""
    nivel: Nivel
    uf: str | None
    hoje: date
    ano: int
    corte: date
    classe: str | None
    pendencias: list
    ufs: list
    k: int
    parametros: object
    cubo: object = None                # o cubo do corte, calculado uma vez por pedido

    @property
    def escopo(self) -> str:
        return f"UF {self.uf}" if self.uf else "NACIONAL"


@dataclass(frozen=True)
class EntregaDocumento:
    """O documento renderizado, já com marca visível e S9, registrado na trilha antes de sair."""
    documento: object                  # dominio.acervo.Documento
    imagem: np.ndarray                 # BGR
    hash_documento: str
    hash_consulta: str
    marca_visivel: str
    momento: datetime


@dataclass(frozen=True)
class Entrega:
    """O que a tela recebe: só a imagem já tratada."""
    item: RelatorioCatalogo
    nivel: Nivel
    usuario_id: int
    imagem: np.ndarray                # BGR, já com tarja, marca visível (e S9, se N2/N3)
    suprimidas: tuple
    marcada: bool                     # S9 (a invisível)
    momento: datetime
    marca_visivel: str = ""           # o texto da marca visível desenhada na imagem

    @property
    def exportacao(self) -> Exportacao:
        return self.nivel.exportacao

    def resumo_supressao(self) -> list[str]:
        """'2 × endereço (fora do seu acesso)': para explicar na tela o que foi ocultado, sem citar outra camada."""
        contagem = defaultdict(int)
        for r in self.suprimidas:
            contagem[r.rotulo] += 1
        return [f"{n} × {ROTULOS_LEGIVEIS.get(rotulo, rotulo.lower())} (fora do seu acesso)"
                for rotulo, n in sorted(contagem.items())]


class ServicoAcervo:
    def __init__(self, repositorio, trilha, *, fontes: Fontes, tarja: ParametrosTarja, marca: ParametrosMarca,
                 chave_marca: bytes, relogio=datetime.now, data_referencia: date | None = None,
                 regras_negocio: regras.ParametrosRegras | None = None, janela_verificacao_minutos: float = 5.0,
                 pesos_pressao: dict | None = None, supressao_minima: int = 3, rasterizar_documento=None):
        self.repo, self.trilha = repositorio, trilha
        self.rasterizar_documento = rasterizar_documento     # injetado pela montagem (desenho Qt)
        self.pesos_pressao = pesos_pressao or dict(analise.PESOS_PRESSAO)
        self.supressao_minima = supressao_minima
        self.fontes, self.p_tarja, self.p_marca, self.chave = fontes, tarja, marca, chave_marca
        self.relogio = relogio
        self.data_referencia = data_referencia
        self.regras = regras_negocio
        self.janela_verificacao = timedelta(minutes=janela_verificacao_minutos)

    @classmethod
    def de_configuracao(cls, cfg, repositorio, trilha, chave_marca: bytes, **extra) -> "ServicoAcervo":
        referencia = cfg["acervo.data_referencia"]
        return cls(repositorio, trilha, fontes=Fontes.de_configuracao(cfg),
                   tarja=ParametrosTarja.de_configuracao(cfg), marca=ParametrosMarca.de_configuracao(cfg),
                   chave_marca=chave_marca, data_referencia=date.fromisoformat(referencia) if referencia else None,
                   regras_negocio=regras.ParametrosRegras.de_configuracao(cfg),
                   janela_verificacao_minutos=float(cfg["contexto.verificacao_minutos"]),
                   pesos_pressao=analise.pesos_pressao(cfg),
                   supressao_minima=int(cfg["indice_pressao.supressao_minima"]), **extra)

    def hoje(self) -> date:
        return self.data_referencia or self.relogio().date()

    # ------------------------------------------------------------ autorização (a matriz decide)
    @staticmethod
    def _decidir(usuario: Usuario, nivel: Nivel, operacao: Operacao, risco: str = "BAIXO") -> autorizacao.Autorizacao:
        """A matriz, pelo PAPEL de quem pede (o perfil do cadastro). O Externo, inclusive o administrador, não tem
        camada: negado, sempre (o administrador não lê dado do acervo em nenhuma circunstância)."""
        if usuario.perfil is Perfil.EXTERNO:
            return autorizacao.Autorizacao(autorizacao.Efeito.NEGADO, "SEM_ACESSO")
        return autorizacao.decidir(autorizacao.papel_de(usuario.perfil), Classificacao.do_nivel(nivel), operacao,
                                   risco)

    def _autorizar(self, usuario: Usuario, nivel: Nivel, operacao: Operacao, *, risco: str = "BAIXO",
                   verificado_em: datetime | None = None, evento: str = "CONSULTA", codigo: str = "") -> None:
        """Pergunta à matriz. NEGADO: registra e recusa. COM_VERIFICACAO: exige o rosto conferido
        dentro da janela (senão, VerificacaoNecessaria: a tela confere e tenta de novo)."""
        decisao = self._decidir(usuario, nivel, operacao, risco)
        if not decisao.permitido:
            self._registrar_negacao(evento, decisao.motivo, usuario, nivel, codigo)
            raise ErroAcervo(MENSAGENS.get((decisao.motivo, operacao)) or MENSAGENS.get(decisao.motivo)
                             or "Operação não permitida para o seu papel.")
        if decisao.exige_verificacao:
            recente = verificado_em is not None and self.relogio() - verificado_em <= self.janela_verificacao
            if not recente:
                self._registrar_negacao(evento, "VERIFICACAO_EXIGIDA", usuario, nivel, codigo)
                raise VerificacaoNecessaria("A exportação exige nova verificação facial.")

    def _exporta(self, usuario: Usuario, nivel: Nivel, operacao: Operacao) -> bool:
        return self._decidir(usuario, nivel, operacao).permitido

    # ------------------------------------------------------------ catálogo
    def catalogo(self, nivel: int) -> list[RelatorioCatalogo]:
        """Só os relatórios DA camada (escopo exclusivo): os das outras nem aparecem na lista."""
        return [r for r in self.repo.catalogo()
                if r.nivel_minimo == int(nivel) and r.codigo in relatorios.DESENHOS]

    # ------------------------------------------------------------ consulta
    def _escopo(self, usuario: Usuario, nivel: Nivel) -> str | None:
        """UF a que a consulta se restringe (None = nacional)."""
        if nivel is Nivel.N2 and usuario.nivel is Nivel.N2:
            if not usuario.uf:
                raise ErroAcervo("Diretor de nível 2 sem região definida: consulta recusada.")   # falha segura
            return usuario.uf
        return None

    def abrir(self, codigo: str, usuario: Usuario, nivel: int, ufs=None, categorias=None) -> Entrega:
        """`ufs` e `categorias` (de risco) filtram as pendências desenhadas: o mapa de calor filtrado do N3."""
        nivel = Nivel(nivel)
        item = next((r for r in self.catalogo(nivel) if r.codigo == codigo), None)
        if item is None:
            self._registrar_negacao("CONSULTA", "NIVEL_INSUFICIENTE", usuario, nivel, codigo)
            raise ErroAcervo(MENSAGENS["NIVEL_INSUFICIENTE"])
        self._autorizar(usuario, nivel, Operacao.VISUALIZAR, codigo=codigo)
        uf = self._escopo(usuario, nivel)
        responsaveis = None
        if nivel is not Nivel.N1:                     # N1 não recebe a cadeia (RF-21)
            responsaveis = defaultdict(list)
            for r in self.repo.responsaveis(nivel.value, uf):
                responsaveis[r.pendencia_codigo].append(r)
            responsaveis = {k: tuple(v) for k, v in responsaveis.items()}
        momento = self.relogio()
        pendencias = regras.ativas(self.repo.pendencias(uf), self.hoje())     # relatório = pendências ATIVAS
        filtros = ""
        if ufs or categorias:
            pendencias = analise.filtrar(pendencias, self.hoje(), ufs=ufs, categorias=categorias)
            filtros = (f"; filtro UF {','.join(sorted(ufs)) if ufs else 'TODAS'} "
                       f"RISCO {','.join(categorias) if categorias else 'TODOS'}")
        dados = relatorios.DadosRelatorio(
            pendencias=tuple(pendencias), responsaveis=responsaveis,
            atividades={a.codigo: a for a in self.repo.atividades()},
            motivos={m.codigo: m for m in self.repo.motivos()}, hoje=self.hoje(),
            escopo=(f"UF {uf}" if uf else "Nacional") + filtros.replace("; filtro", " · filtro"),
            gerado_em=momento, nivel=nivel.value, regras=self.regras, supressao_minima=self.supressao_minima)
        documento = relatorios.gerar(item, dados, self.fontes)
        tratado = s8_tarja.aplicar(documento.imagem, documento.regioes, nivel, self.p_tarja, regioes_revisadas=True)
        marca_visivel = f"MATRÍCULA {usuario.matricula} · {momento:%d/%m/%Y %H:%M}"
        imagem, marcada = desenho.desenhar_marca_visivel(tratado.imagem, marca_visivel), False
        if nivel is not Nivel.N1:
            imagem = s9_rastreio.marcar(imagem, Marca(usuario.id, momento), self.chave, self.p_marca)
            marcada = True
        # Sem registro, a imagem não é entregue: se a trilha falhar, a exceção sobe e nada sai
        self.trilha.registrar("CONSULTA", "CONCEDIDO", "CONSULTA_ACERVO", nivel_solicitado=nivel.value,
                              usuario_id=usuario.id,
                              detalhe=(f"{item.codigo}; {len(tratado.suprimidas)} regiões suprimidas"
                                       + ("; marca d'água" if marcada else "") + filtros)[:DETALHE_MAX])
        return Entrega(item, nivel, usuario.id, imagem, tratado.suprimidas, marcada, momento, marca_visivel)

    # ------------------------------------------------------------ painel analítico
    def painel(self, usuario: Usuario, nivel: int) -> Painel:
        """Registros individuais do escopo do nível. O N1 não tem painel: só vê agregados (RF-20)."""
        nivel = Nivel(nivel)
        if nivel is Nivel.N1:
            self._registrar_negacao("CONSULTA", "NIVEL_INSUFICIENTE", usuario, nivel, "PAINEL")
            raise ErroAcervo("O painel analítico mostra registros individuais: não faz parte deste acesso.")
        self._autorizar(usuario, nivel, Operacao.VISUALIZAR, codigo="PAINEL")
        uf = self._escopo(usuario, nivel)
        pendencias = tuple(self.repo.pendencias(uf))
        self.trilha.registrar("CONSULTA", "CONCEDIDO", "PAINEL_ANALITICO", nivel_solicitado=nivel.value,
                              usuario_id=usuario.id, detalhe=f"{len(pendencias)} registros; escopo "
                                                             f"{('UF ' + uf) if uf else 'NACIONAL'}")
        return Painel(nivel, usuario.id, f"UF {uf}" if uf else "NACIONAL", pendencias,
                      {a.codigo: a for a in self.repo.atividades()}, {m.codigo: m for m in self.repo.motivos()},
                      self.hoje(), self._exporta(usuario, nivel, Operacao.EXPORTAR_REGISTROS),
                      self.regras or regras.ParametrosRegras.padrao())

    def priorizacao(self, painel: Painel, usuario: Usuario, orcamento: float | None = None,
                    criterio: str = regras.CRITERIOS[0]) -> regras.Priorizacao:
        """Fila do orçamento público sobre os dados do painel (já autorizados e registrados). Só a camada 3 (matriz:
        PRIORIZAR): decidir onde gastar o orçamento nacional é atribuição da custódia."""
        self._dono_do_painel(painel, usuario)
        self._autorizar(usuario, painel.nivel, Operacao.PRIORIZAR, codigo="PRIORIZACAO")
        return regras.priorizar(painel.pendencias, painel.hoje, painel.regras, orcamento, criterio)

    def resumo_agregado(self, usuario: Usuario, nivel: int, filtro=None) -> ResumoAgregado:
        """Totais por grupo. No N2 e no N3, `filtro` (acervo.filtro.Filtro) recorta as pendências antes de
        agregar e os chips vão para a trilha. No N1 o filtro é RECUSADO: o k=3 protege o
        cubo inteiro, e um recorte arbitrário reabriria a dedução por diferença entre consultas."""
        nivel = Nivel(nivel)
        self._autorizar(usuario, nivel, Operacao.VISUALIZAR, codigo="RESUMO")
        if filtro is not None and nivel is Nivel.N1:
            self._registrar_negacao("CONSULTA", "FILTRO_NO_NIVEL_1", usuario, nivel, "RESUMO")
            raise ErroAcervo("Este resumo não aceita filtro.")
        uf = self._escopo(usuario, nivel)
        atividades = {a.codigo: a for a in self.repo.atividades()}
        motivos = {m.codigo: m for m in self.repo.motivos()}
        parametros = self.regras or regras.ParametrosRegras.padrao()
        if filtro is None:
            pendencias, descricao = regras.ativas(self.repo.pendencias(uf), self.hoje()), ""
        else:
            pendencias = filtro.aplicar(self.repo.pendencias(uf), self.hoje(), parametros)
            descricao = "; filtro " + (", ".join(r for _, _, r in filtro.chips(atividades, motivos)) or "nenhum")
        tabelas = {g: analise.agregar(pendencias, self.hoje(), g, atividades, motivos, parametros)
                   for g in analise.AGRUPAMENTOS}
        escondidas = 0
        if nivel is Nivel.N1:            # K em todo agregado do N1, na tela e na exportação
            # o por UF e o por classe leem o cubo do panorama do mesmo corte: a UF, a classe e a subcontagem que o
            # mapa esconde não aparecem aqui (nem o contrário); POR UF, POR REGIAO, POR ATIVIDADE e POR UF E
            # ATIVIDADE são protegidas juntas (garantia hierárquica)
            cubo = analise.proteger_cubo(pendencias, analise.REGIAO_DA_UF if uf is None else [uf], self.hoje(),
                                         self.supressao_minima, parametros)
            tabelas, escondidas = analise.proteger_resumo(tabelas, pendencias, self.hoje(), atividades, motivos,
                                                          self.supressao_minima, parametros, cubo)
            tabelas = sem_custo(tabelas)  # Nenhum valor em reais no N1 (tela e exportação)
        self.trilha.registrar("CONSULTA", "CONCEDIDO", "RESUMO_AGREGADO", nivel_solicitado=nivel.value,
                              usuario_id=usuario.id, detalhe=(f"{len(pendencias)} registros agregados; escopo "
                                                              f"{('UF ' + uf) if uf else 'NACIONAL'}; "
                                                              f"{escondidas} celulas suprimidas{descricao}"
                                                              )[:DETALHE_MAX])
        return ResumoAgregado(nivel, usuario.id, f"UF {uf}" if uf else "NACIONAL", tabelas, self.hoje(),
                              self._exporta(usuario, nivel, Operacao.EXPORTAR_AGREGADO),
                              self.supressao_minima if nivel is Nivel.N1 else 0)

    # ------------------------------------------------------------ panorama agregado (N1 e N3)
    def eventos(self) -> list:
        """Os eventos que anotam os gráficos: só os conferidos na fonte (verificacao = CONFIRMADO)."""
        return [e for e in self.repo.eventos() if e.verificacao == "CONFIRMADO"]

    def panorama(self, usuario: Usuario, nivel: int, ano: int | None = None, classe: str | None = None) -> Panorama:
        """Coroplético do N1: Índice de Pressão e totais por UF no fim de `ano`, série de estoque por classe e
        eventos. Calculado aqui: a tela nunca recebe os registros que deram origem aos totais."""
        nivel = Nivel(nivel)
        self._autorizar(usuario, nivel, Operacao.VISUALIZAR, codigo="PANORAMA")
        uf = self._escopo(usuario, nivel)
        hoje = self.hoje()
        ano = min(ano or hoje.year, hoje.year)
        corte = min(date(ano, 12, 31), hoje)
        pendencias = self.repo.pendencias(uf)
        ufs = sorted(analise.REGIAO_DA_UF) if uf is None else [uf]
        # O k só vale no N1; no N2 e no N3 o panorama sai inteiro, como o resumo
        k = self.supressao_minima if nivel is Nivel.N1 else 0
        # Um cubo por corte, protegido uma vez; toda vista (todas as classes ou uma classe) lê o mesmo
        cubo = analise.proteger_cubo(pendencias, ufs, corte, k, self.regras)
        pesos = self.pesos_da_pressao(nivel)            # No N1, sem o custo
        pressao = analise.indice_pressao(pendencias, ufs, corte, self.regras, pesos, classe, k, cubo)
        if nivel is Nivel.N1:            # O N1 não recebe valor em reais (o índice é posição)
            pressao = {u: replace(item, custo=None) for u, item in pressao.items()}
        por_classe, totais = {u: {} for u in ufs}, {}
        for (u, c), n in cubo.ativas.items():
            if c == analise.TODAS or (classe and c != classe):
                continue
            if u == analise.NACIONAL:                   # o total da classe: o mesmo destino do cubo (com complementar)
                if n:
                    totais[c] = cubo.contagem(u, c)
                continue
            if u not in pressao or pressao[u].suprimida:   # linha do resumo (região, atividade) ou UF que some
                continue
            if (u, c) in cubo.escondidas:               # célula escondida no cubo: None em toda vista
                por_classe[u][c] = None
            elif n:
                por_classe[u][c] = n
        inicio = self._inicio_da_serie(pendencias)
        # A série segue a classe do panorama (as barras e o gráfico de estoque contam o mesmo recorte);
        # o eixo dos anos é o do escopo inteiro, e "estoque_total" guarda o estoque de todas as classes por ano
        # (o "de T" da contagem do N1)
        completa = analise.serie_estoque(pendencias, inicio, hoje.year, hoje)
        serie = completa if not classe else analise.serie_estoque(
            [p for p in pendencias if p.classe_risco == classe], inicio, hoje.year, hoje)
        serie["estoque_total"] = {a: sum(d[a] for d in completa["ativas"].values()) for a in completa["anos"]}
        if k:
            # (risco registrado, fechado na etapa 3b): o estoque ativo por classe e ano também é agregado
            # do N1. Cada ano lê a linha NACIONAL do cubo do seu corte (o mesmo que o panorama daquele ano usa):
            # a classe escondida tem o mesmo destino nas barras, nos cartões e na série, com a complementar pelo
            # total do ano (que fica travado e continua à vista)
            for a in serie["anos"]:
                corte_a = min(date(a, 12, 31), hoje)
                cubo_a = cubo if corte_a == corte else analise.proteger_cubo(pendencias, ufs, corte_a, k, self.regras)
                for c in serie["ativas"]:
                    serie["ativas"][c][a] = cubo_a.contagem(analise.NACIONAL, c)
                serie["estoque_total"][a] = cubo_a.contagem(analise.NACIONAL, analise.TODAS)
            # No N1, entradas e saídas de um ano (por classe, com filtro) também são agregados:
            # com 0 < n < k, o par do ano sai SUPRIMIDO (None). Os dois juntos, porque o saldo do ano já se
            # deduz do estoque (que é grande e continua visível): o par é protegido uma vez
            # para todas as vistas, com complementar pelo ano (o total do ano menos as classes visíveis revelaria
            # a classe escondida), e o KPI-02 lê o mesmo destino.
            fluxos = analise.proteger_fluxos(pendencias, serie["anos"], k)
            for a in serie["anos"]:
                if (classe or analise.TODAS, a) in fluxos.fluxos_escondidos:
                    serie["entradas"][a] = serie["saidas"][a] = None
            serie.pop("acumulado", None)            # a diferença do cadastro acumulado é a entrada do ano
        self.trilha.registrar("CONSULTA", "CONCEDIDO", "PANORAMA_AGREGADO", nivel_solicitado=nivel.value,
                              usuario_id=usuario.id, detalhe=(f"ano {ano}; classe {classe or 'TODAS'}; escopo "
                                                              f"{('UF ' + uf) if uf else 'NACIONAL'}")[:DETALHE_MAX])
        return Panorama(nivel, f"UF {uf}" if uf else "NACIONAL", ano, classe, pressao, por_classe, totais, serie,
                        tuple(self.eventos()), k, hoje, tuple(pesos.items()))

    def pesos_da_pressao(self, nivel) -> dict:
        """Pesos do Índice de pressão no nível: o N1 não usa o custo (volume, severidade e
        atraso renormalizados, 0,375; 0,375; 0,25); o N2 e o N3, os pesos completos de [indice_pressao]."""
        if Nivel(nivel) is Nivel.N1:
            return analise.pesos_sem_custo(self.pesos_pressao)
        return dict(self.pesos_pressao)

    # ------------------------------------------------------------ painéis temáticos
    # Os quatro painéis e os cartões de KPI. N1 e N3 (no N2, a UF do diretor, sem k). O N1 só tem os filtros
    # classe e ano. Toda consulta passa pela matriz e fica na trilha; no N1, todo número é agregado e
    # passa pelo k com complementar, lendo o mesmo cubo protegido do panorama.
    def _inicio_da_serie(self, pendencias) -> int:
        inicio = min((p.data_identificacao.year for p in pendencias), default=self.hoje().year)
        return max(inicio, analise.INICIO_OBSERVACAO.year)

    def _abrir_painel(self, usuario: Usuario, nivel: int, codigo: str, ano: int | None,
                      classe: str | None) -> "_ContextoPainel":
        nivel = Nivel(nivel)
        self._autorizar(usuario, nivel, Operacao.VISUALIZAR, codigo=codigo)
        if classe is not None and classe not in quantidades.CLASSES:
            self._registrar_negacao("CONSULTA", "CLASSE_DESCONHECIDA", usuario, nivel, codigo)
            raise ErroAcervo("Classe de risco desconhecida.")
        uf = self._escopo(usuario, nivel)
        hoje = self.hoje()
        ano = min(ano or hoje.year, hoje.year)
        return _ContextoPainel(nivel, uf, hoje, ano, min(date(ano, 12, 31), hoje), classe,
                               list(self.repo.pendencias(uf)),
                               sorted(analise.REGIAO_DA_UF) if uf is None else [uf],
                               self.supressao_minima if nivel is Nivel.N1 else 0,
                               self.regras or regras.ParametrosRegras.padrao())

    def _registrar_painel(self, usuario: Usuario, ctx: "_ContextoPainel", motivo: str, extra: str = "") -> None:
        # Sem registro, nada sai: se a trilha falhar, a exceção sobe antes do retorno
        self.trilha.registrar("CONSULTA", "CONCEDIDO", motivo, nivel_solicitado=ctx.nivel.value, usuario_id=usuario.id,
                              detalhe=(f"ano {ctx.ano}; classe {ctx.classe or 'TODAS'}; escopo {ctx.escopo}"
                                       f"{extra}")[:DETALHE_MAX])

    def painel_classe(self, usuario: Usuario, nivel: int, ano: int | None = None,
                      classe: str | None = None) -> PainelClasse:
        """Estoque ativo por classe no fim de `ano`, com a quantidade na unidade da classe e o envelhecimento
        (KPI-04) em faixas. O total de cada classe segue o cubo; a complementar cai nas faixas."""
        ctx = self._abrir_painel(usuario, nivel, "PAINEL_CLASSE", ano, classe)
        painel = self._dados_classe(ctx)
        self._registrar_painel(usuario, ctx, "PAINEL_CLASSE")
        return painel

    def painel_uf(self, usuario: Usuario, nivel: int, ano: int | None = None, classe: str | None = None) -> PainelUF:
        """Ativas, além do prazo-limite (KPI-03) e fora da previsão (KPI-03b) por UF, do cubo protegido."""
        ctx = self._abrir_painel(usuario, nivel, "PAINEL_UF", ano, classe)
        painel = self._dados_uf(ctx)
        self._registrar_painel(usuario, ctx, "PAINEL_UF")
        return painel

    def painel_custo(self, usuario: Usuario, nivel: int, ano: int | None = None, classe: str | None = None,
                     por: str = "classe") -> PainelCusto:
        """Custo do passivo ativo (KPI-05) por classe ou por rota, por categoria EEA e por responsabilidade
        financeira. Custo por responsável nomeado não está aqui: só no N3 (custo_por_responsavel)."""
        if por not in ("classe", "rota"):
            raise ErroAcervo("O painel de custo agrupa por classe ou por rota.")
        if Nivel(nivel) is Nivel.N1:     # Sem dado financeiro no N1 (recusado e registrado)
            self._registrar_negacao("CONSULTA", "CUSTO_NO_NIVEL_1", usuario, Nivel.N1, "PAINEL_CUSTO")
            raise ErroAcervo(MENSAGENS["CUSTO_NO_NIVEL_1"])
        ctx = self._abrir_painel(usuario, nivel, "PAINEL_CUSTO", ano, classe)
        painel = self._dados_custo(ctx, por)
        self._registrar_painel(usuario, ctx, "PAINEL_CUSTO", f"; por {por}")
        return painel

    def painel_encerramento(self, usuario: Usuario, nivel: int, classe: str | None = None) -> PainelEncerramento:
        """KPI-01 (curva por classe; tábua de vida anual no N1) e KPI-02 por ano, com todo o histórico até hoje."""
        ctx = self._abrir_painel(usuario, nivel, "PAINEL_ENCERRAMENTO", None, classe)
        painel = self._dados_encerramento(ctx, ctx.hoje)
        self._registrar_painel(usuario, ctx, "PAINEL_ENCERRAMENTO")
        return painel

    def kpis(self, usuario: Usuario, nivel: int, ano: int | None = None, classe: str | None = None) -> list:
        """Os cartões (KPI-01, 02, 03, 03b, 04, 05) do recorte, cada um com fonte, nível mínimo e corte.
        Os números são os mesmos dos painéis (mesmas funções, mesmo k). O nome é o do vocabulário. No N1
        o KPI-05 (custo) é OMITIDO: o N1 não recebe dado financeiro."""
        ctx = self._abrir_painel(usuario, nivel, "KPIS", ano, classe)
        p_classe, p_uf = self._dados_classe(ctx), self._dados_uf(ctx)
        financeiro = ctx.nivel is not Nivel.N1
        p_custo = self._dados_custo(ctx, "classe") if financeiro else None
        p_enc = self._dados_encerramento(ctx, ctx.corte)
        nome = vocabulario.ROTULO_KPI
        coluna = classe or analise.TODAS
        curva = p_enc.curvas.get(coluna)
        fechado = ctx.ano if ctx.ano < ctx.hoje.year else ctx.ano - 1
        taxa = next((t for t in p_enc.taxa_anual if t.ano == fechado), None)
        total = p_uf.total

        def fracao(parte):
            return round(100 * parte / total.ativas, 1) if parte is not None and total.ativas else None
        k = ""                               # a supressão é explicada uma vez, no rodapé do painel
        lista = [
            KPI("KPI-01", nome["KPI-01"], curva.mediana if curva else None, "anos",
                "analise.tempo_ate_encerramento" if p_enc.exata else "analise.tabua_de_vida", 1, ctx.corte,
                "Conta também os casos que ainda não encerraram" + ("; não atingido" if curva and curva.mediana
                                                                        is None else "")),
            KPI("KPI-02", nome["KPI-02"], taxa.percentual if taxa else None, "%",
                "analise.taxa_anual_encerramento", 1, ctx.corte,
                f"{fechado}: saídas no ano sobre as ativas em 1º de janeiro"
                + (f" ({taxa.saidas} de {taxa.ativas_1_jan})" if taxa and taxa.percentual is not None else "") + k),
            KPI("KPI-03", nome["KPI-03"], fracao(total.alem_do_prazo), "%", "analise.proteger_cubo", 1,
                ctx.corte, "casos ativos que passaram do prazo legal da classe" + k),
            KPI("KPI-03b", nome["KPI-03b"], fracao(total.fora_da_previsao), "%", "analise.proteger_cubo", 1,
                ctx.corte, "casos ativos com o prazo previsto de coleta vencido"),
            KPI("KPI-04", nome["KPI-04"], p_classe.idade_mediana_total, "anos",
                "analise.envelhecimento", 1, ctx.corte, "idade mediana: anos desde a identificação, dos casos "
                                                        "ativos no corte" + k),
        ]
        if financeiro:
            lista.append(KPI("KPI-05", nome["KPI-05"], p_custo.total, "R$", "analise.custo_do_passivo", 2, ctx.corte,
                             "soma do custo estimado dos casos ativos"))
        self._registrar_painel(usuario, ctx, "KPIS", f"; {len(lista)} kpis")
        return lista

    def referencia_nacional(self, usuario: Usuario) -> ReferenciaNacional:
        """Totais do país para a comparação "UF × país" do N2. Escopo do DIRETOR: a matriz
        decide com a classificação do N2, e a proteção é a do agregado público (k=3, a linha NACIONAL do cubo
        protegido; nenhuma outra UF individualmente). Registrada na trilha com o nível 2."""
        self._autorizar(usuario, Nivel.N2, Operacao.VISUALIZAR, codigo="REFERENCIA_NACIONAL")
        hoje, k = self.hoje(), self.supressao_minima
        parametros = self.regras or regras.ParametrosRegras.padrao()
        pendencias = list(self.repo.pendencias(None))
        cubo = analise.proteger_cubo(pendencias, sorted(analise.REGIAO_DA_UF), hoje, k, parametros)
        nacional, todas = analise.NACIONAL, analise.TODAS
        anos = range(self._inicio_da_serie(pendencias), hoje.year + 1)
        taxa = analise.taxa_anual_encerramento(analise.proteger_fluxos(pendencias, anos, k), anos, hoje)
        fechado = next((t for t in reversed(taxa) if not t.parcial), None)
        referencia = ReferenciaNacional(
            hoje, cubo.contagem(nacional, todas), cubo.subcontagem(analise.CRITICAS, nacional, todas),
            cubo.subcontagem(analise.ALEM_DO_PRAZO, nacional, todas),
            cubo.subcontagem(analise.FORA_DA_PREVISAO, nacional, todas),
            fechado.percentual if fechado else None, fechado.ano if fechado else hoje.year - 1, k)
        self.trilha.registrar("CONSULTA", "CONCEDIDO", "REFERENCIA_NACIONAL", nivel_solicitado=Nivel.N2.value,
                              usuario_id=usuario.id, detalhe=f"linha NACIONAL do cubo; k={k}"[:DETALHE_MAX])
        return referencia

    # cálculos dos painéis (sem autorização nem trilha: só chamados pelos métodos públicos acima)
    def _cubo(self, ctx: "_ContextoPainel") -> analise.CuboN1:
        if ctx.cubo is None:
            ctx.cubo = analise.proteger_cubo(ctx.pendencias, ctx.ufs, ctx.corte, ctx.k, ctx.parametros)
        return ctx.cubo

    def _dados_classe(self, ctx: "_ContextoPainel") -> PainelClasse:
        cubo = self._cubo(ctx)
        env = analise.envelhecimento(ctx.pendencias, ctx.corte)
        escondidas = analise.proteger_envelhecimento(env, ctx.k, cubo)
        ativas = regras.ativas(ctx.pendencias, ctx.corte)

        def faixas(linha):
            return {f: None if (linha, f) in escondidas else env.contagens.get((linha, f), 0)
                    for f in analise.ROTULOS_FAIXAS}
        linhas = []
        for c in quantidades.CLASSES:
            if ctx.classe and c != ctx.classe:
                continue
            n = cubo.contagem(analise.NACIONAL, c)
            linhas.append(LinhaClasse(c, n, quantidades.total_da_classe(ativas, c) if n is not None else None,
                                      quantidades.sigla(c), env.medianas.get(c) if n else None, faixas(c)))
        coluna = ctx.classe or analise.TODAS
        total = cubo.contagem(analise.NACIONAL, coluna)
        return PainelClasse(ctx.nivel, ctx.escopo, ctx.ano, ctx.classe, ctx.corte, tuple(linhas),
                            analise.ROTULOS_FAIXAS, total, env.medianas.get(coluna) if total else None,
                            faixas(coluna), ctx.k)

    def _dados_uf(self, ctx: "_ContextoPainel") -> PainelUF:
        cubo, coluna = self._cubo(ctx), ctx.classe or analise.TODAS

        def linha(uf, regiao):
            return LinhaUF(uf, regiao, cubo.contagem(uf, coluna),
                           cubo.subcontagem(analise.ALEM_DO_PRAZO, uf, coluna),
                           cubo.subcontagem(analise.FORA_DA_PREVISAO, uf, coluna), (uf, coluna) in cubo.escondidas)
        return PainelUF(ctx.nivel, ctx.escopo, ctx.ano, ctx.classe, ctx.corte,
                        tuple(linha(uf, analise.REGIAO_DA_UF.get(uf, "OUTRA")) for uf in ctx.ufs),
                        linha(analise.NACIONAL, ""), ctx.k)

    def _dados_custo(self, ctx: "_ContextoPainel", por: str) -> PainelCusto:
        todas = analise.TODAS
        custo = analise.custo_do_passivo(ctx.pendencias, ctx.corte, ctx.parametros)
        grade, grade_resp = analise.proteger_custo(custo, ctx.k, self._cubo(ctx))
        recorte = ctx.classe or todas

        def valor(chave):
            return None if chave in grade else custo.valores.get(chave, 0.0)

        def grupo(nome, chave):
            n = None if chave + (todas,) in grade else custo.contagens.get(chave + (todas,), 0)
            return LinhaCusto(nome, n, valor(chave + (todas,)),
                              {cat: valor(chave + (cat,)) for cat in custos.CATEGORIAS_EEA})
        if por == "classe":
            linhas = [grupo(c, (c, todas)) for c in quantidades.CLASSES if not ctx.classe or c == ctx.classe]
        else:
            rotas = sorted({ro for (c, ro, cat), n in custo.contagens.items()
                            if c == recorte and ro != todas and cat == todas and n})
            linhas = [grupo(ro, (recorte, ro)) for ro in rotas]
            linhas = (sorted((l for l in linhas if l.custo is not None), key=lambda l: (-l.custo, l.grupo))
                      + [l for l in linhas if l.custo is None])      # as suprimidas no fim, por nome
        responsabilidades = (regras.COBRAVEL, regras.PUBLICO, regras.INFRAESTRUTURA, regras.FISCALIZACAO)
        por_resp = {g: None if (recorte, g) in grade_resp else custo.responsabilidade.get((recorte, g), 0.0)
                    for g in responsabilidades}
        fontes = ", ".join(sorted({r.fonte for r in ctx.parametros.custos.rotas.values()}))
        return PainelCusto(ctx.nivel, ctx.escopo, ctx.ano, ctx.classe, por, ctx.corte, ctx.parametros.custos.data_base,
                           fontes, tuple(linhas), {cat: valor((recorte, todas, cat)) for cat in custos.CATEGORIAS_EEA},
                           por_resp, valor((recorte, todas, todas)), ctx.k)

    def _dados_encerramento(self, ctx: "_ContextoPainel", corte: date) -> PainelEncerramento:
        curvas = analise.curvas_de_encerramento(ctx.pendencias, corte, ctx.k, ctx.classe)
        anos = range(self._inicio_da_serie(ctx.pendencias), ctx.hoje.year + 1)
        fluxos = analise.proteger_fluxos(ctx.pendencias, anos, ctx.k)
        taxa = analise.taxa_anual_encerramento(fluxos, anos, ctx.hoje, ctx.classe)
        return PainelEncerramento(ctx.nivel, ctx.escopo, ctx.classe, corte, curvas, tuple(taxa), not ctx.k, ctx.k)

    # ------------------------------------------------------------ painel do N1
    def painel_n1(self, usuario: Usuario, nivel: int, ano: int | None = None, classe: str | None = None) -> PainelN1:
        """Indicadores com variação anual, regiões, classes, atividades de origem e motivos da permanência no
        recorte (classe e ano). No N1 tudo passa pelo k=3 com complementar: o que sai do cubo lê o
        mesmo cubo protegido do panorama; a grade motivo × classe, nova, é protegida com as margens que o cubo e o
        resumo por motivo já publicam (analise.proteger_grade_n1). Sem nenhum valor em reais."""
        ctx = self._abrir_painel(usuario, nivel, "PAINEL_N1", ano, classe)
        painel = self._dados_n1(ctx)
        self._registrar_painel(usuario, ctx, "PAINEL_N1")
        return painel

    def _cubo_do_ano(self, ctx: "_ContextoPainel", ano: int) -> analise.CuboN1:
        corte = min(date(ano, 12, 31), ctx.hoje)
        return self._cubo(ctx) if corte == ctx.corte else analise.proteger_cubo(ctx.pendencias, ctx.ufs, corte, ctx.k,
                                                                                ctx.parametros)

    def _dados_n1(self, ctx: "_ContextoPainel") -> PainelN1:
        cubo, coluna = self._cubo(ctx), ctx.classe or analise.TODAS
        classes = [c for c in quantidades.CLASSES if not ctx.classe or c == ctx.classe]

        def grupo(linha: str, chave: str, nome: str) -> GrupoN1:
            return GrupoN1(chave, nome, cubo.contagem(linha, coluna),
                           cubo.subcontagem(analise.ALEM_DO_PRAZO, linha, coluna),
                           cubo.subcontagem(analise.FORA_DA_PREVISAO, linha, coluna),
                           cubo.subcontagem(analise.CRITICAS, linha, coluna),
                           {c: cubo.contagem(linha, c) for c in classes},
                           {c: cubo.subcontagem(analise.ALEM_DO_PRAZO, linha, c) for c in classes})
        regioes = tuple(grupo(analise.linha_regiao(r), r, "Centro-Oeste" if r == "CENTRO OESTE" else r.title())
                        for r in analise.REGIOES if any(uf in ctx.ufs for uf in analise.REGIOES[r]))

        def da_classe(c: str) -> GrupoN1:                # a linha do total na coluna da classe
            n, alem = cubo.contagem(analise.NACIONAL, c), cubo.subcontagem(analise.ALEM_DO_PRAZO, analise.NACIONAL, c)
            return GrupoN1(c, vocabulario.rotulo(c, "classe"), n, alem,
                           cubo.subcontagem(analise.FORA_DA_PREVISAO, analise.NACIONAL, c),
                           cubo.subcontagem(analise.CRITICAS, analise.NACIONAL, c), {c: n}, {c: alem})
        por_classe = [da_classe(c) for c in classes]
        atividades = tuple(
            ContagemN1(a.codigo, vocabulario.rotulo(a.codigo, "atividade"), cubo.contagem(analise.linha_atividade(a.codigo),
                                                                                          coluna),
                       {c: cubo.contagem(analise.linha_atividade(a.codigo), c) for c in classes})
            for a in sorted(self.repo.atividades(), key=lambda a: a.codigo))
        return PainelN1(ctx.nivel, ctx.escopo, ctx.ano, ctx.classe, ctx.corte, ctx.hoje, self._indicadores_n1(ctx),
                        grupo(analise.NACIONAL, analise.NACIONAL, "Brasil" if ctx.uf is None else ctx.escopo),
                        regioes, tuple(por_classe), atividades, self._motivos_n1(ctx, classes),
                        tuple(self.pesos_da_pressao(ctx.nivel).items()), ctx.k)

    def _motivos_n1(self, ctx: "_ContextoPainel", classes) -> tuple:
        """A grade motivo × classe do corte, com as margens como células. No N1: as margens que outra vista já
        publica entram como conhecidas (o total de cada classe e o geral, do cubo; no corte de hoje, o total de cada
        motivo, do resumo por motivo); as que outra vista esconde entram escondidas. A proteção prova que nenhuma
        escondida sai das equações da grade (analise.celulas_recompostas)."""
        todas, coluna = analise.TODAS, ctx.classe or analise.TODAS
        grade = analise.contagens_motivo_classe(ctx.pendencias, ctx.corte)
        motivos = {m.codigo: m for m in self.repo.motivos()}
        for m in motivos:
            for c in tuple(quantidades.CLASSES) + (todas,):
                grade.setdefault((m, c), 0)
        escondidas: set = set()
        if ctx.k:
            cubo = self._cubo(ctx)
            conhecidas, iniciais = set(), set()
            for c in tuple(quantidades.CLASSES) + (todas,):
                (iniciais if cubo.contagem(analise.NACIONAL, c) is None else conhecidas).add((todas, c))
            if ctx.corte == ctx.hoje:
                for m, visivel, colunas_escondidas in self._motivos_do_resumo(ctx, motivos):
                    (conhecidas if visivel else iniciais).add((m, todas))
                    iniciais |= {(m, c) for c in colunas_escondidas}
            escondidas = analise.proteger_grade_n1(grade, ctx.k, conhecidas, iniciais)

        def valor(chave):
            return None if chave in escondidas else grade.get(chave, 0)
        return tuple(ContagemN1(m, vocabulario.rotulo(m, "motivo"), valor((m, coluna)),
                                {c: valor((m, c)) for c in classes}) for m in sorted(motivos))

    def _motivos_do_resumo(self, ctx: "_ContextoPainel", motivos: dict):
        """O destino de cada motivo no resumo por motivo da permanencia do N1 (o mesmo cálculo de resumo_agregado):
        (motivo, total visível?, classes cuja quantidade o resumo esconde)."""
        atividades = {a.codigo: a for a in self.repo.atividades()}
        grupo = "POR MOTIVO DA PERMANENCIA"
        ativas = regras.ativas(ctx.pendencias, ctx.hoje)
        tabelas = {grupo: analise.agregar(ativas, ctx.hoje, grupo, atividades, motivos, ctx.parametros)}
        cubo = analise.proteger_cubo(ativas, ctx.ufs, ctx.hoje, ctx.k, ctx.parametros)
        tabelas, _ = analise.proteger_resumo(tabelas, ativas, ctx.hoje, atividades, motivos, ctx.k, ctx.parametros,
                                             cubo)
        titulos, linhas = tabelas[grupo]
        titulos = list(titulos)
        j = titulos.index("PENDENCIAS")
        colunas = {classe: titulos.index(t) for classe, t in analise.COLUNA_DA_CLASSE.items()}
        for linha in linhas:
            yield (linha[0], linha[j] != analise.SUPRIMIDO,
                   {c for c, i in colunas.items() if linha[i] == analise.SUPRIMIDO})

    def _indicadores_n1(self, ctx: "_ContextoPainel") -> tuple:
        """A faixa do N1: casos ativos, além do prazo legal, prazo previsto vencido, risco crítico, taxa anual de
        encerramento, tempo típico até o encerramento e idade dos casos em aberto. Cada um no corte e um ano antes
        (o cubo, a tábua e o envelhecimento de cada corte, com o mesmo k); a variação é a diferença dos dois."""
        from ecosec.acervo import formatos
        coluna, nome = ctx.classe or analise.TODAS, vocabulario.ROTULO_KPI
        inicio = self._inicio_da_serie(ctx.pendencias)
        anos = list(range(inicio, ctx.ano + 1))
        anterior = ctx.ano - 1 if ctx.ano - 1 >= inicio else None
        corte_anterior = date(anterior, 12, 31) if anterior else None
        k = ""                               # a supressão é explicada uma vez, no rodapé do painel
        cubos = {a: self._cubo_do_ano(ctx, a) for a in anos}

        def ativas(a):
            return cubos[a].contagem(analise.NACIONAL, coluna)

        def fracao(a, sub):
            total, parte = ativas(a), cubos[a].subcontagem(sub, analise.NACIONAL, coluna)
            return round(100 * parte / total, 1) if parte is not None and total else None

        def indicador(id_, rotulo, unidade, melhor, de_ano, fonte, observacao, base, com_serie=True):
            atual = de_ano(ctx.ano)
            antes = de_ano(anterior) if anterior else None
            variacao = (round(atual - antes, 1) if atual is not None and antes is not None else None)
            serie = tuple((a, de_ano(a)) for a in anos) if com_serie else ()
            return IndicadorN1(id_, rotulo, atual, unidade, antes, anterior, variacao, melhor, base, ctx.corte, fonte,
                               1, observacao + k, serie)
        total = ativas(ctx.ano)
        de_total = "" if total is None else f"de {formatos.inteiro(total)} casos ativos"
        lista = [
            indicador("ATIVOS", f"Casos {vocabulario.ADJETIVO_SITUACAO['ATIVAS']}", "casos", "menor", ativas,
                      "analise.proteger_cubo", "casos sem solução na data de corte",
                      "casos sem solução"),
            indicador("KPI-03", nome["KPI-03"], "%", "menor", lambda a: fracao(a, analise.ALEM_DO_PRAZO),
                      "analise.proteger_cubo", "casos ativos que passaram do prazo legal da classe", de_total),
            indicador("KPI-03b", nome["KPI-03b"], "%", "menor", lambda a: fracao(a, analise.FORA_DA_PREVISAO),
                      "analise.proteger_cubo", "casos ativos com o prazo previsto vencido", de_total),
            indicador("CRITICOS", f"Casos em {vocabulario.rotulo_longo('CRITICO', 'faixa').lower()}", "%", "menor",
                      lambda a: fracao(a, analise.CRITICAS), "analise.proteger_cubo",
                      "casos ativos na faixa crítica do score de risco", de_total),
        ]
        enc = self._dados_encerramento(ctx, ctx.corte)
        taxas = {t.ano: t for t in enc.taxa_anual}
        fechado = ctx.ano if ctx.ano < ctx.hoje.year else ctx.ano - 1
        t = taxas.get(fechado)
        base_taxa = (f"{formatos.inteiro(t.saidas)} encerrados de {formatos.inteiro(t.ativas_1_jan)} ativos em "
                     f"1º/1/{fechado}" if t and t.percentual is not None else f"ano {fechado}")
        anos_taxa = [a for a in sorted(taxas) if a <= fechado]
        atual_t = t.percentual if t else None
        antes_t = taxas[fechado - 1].percentual if fechado - 1 in taxas else None
        lista.append(IndicadorN1(
            "KPI-02", nome["KPI-02"], atual_t, "% ao ano", antes_t, fechado - 1 if fechado - 1 in taxas else None,
            round(atual_t - antes_t, 1) if atual_t is not None and antes_t is not None else None, "maior", base_taxa,
            ctx.corte, "analise.taxa_anual_encerramento", 1,
            f"último ano fechado ({fechado}): encerrados no ano ÷ ativos em 1º de janeiro{k}",
            tuple((a, taxas[a].percentual) for a in anos_taxa)))
        curva = enc.curvas.get(coluna)
        mediana = curva.mediana if curva else None
        mediana_antes = None
        if corte_anterior:
            antes = analise.curvas_de_encerramento(ctx.pendencias, corte_anterior, ctx.k, ctx.classe).get(coluna)
            mediana_antes = antes.mediana if antes else None
        lista.append(IndicadorN1(
            "KPI-01", nome["KPI-01"], mediana, "anos", mediana_antes, anterior,
            round(mediana - mediana_antes, 1) if mediana is not None and mediana_antes is not None else None, "menor",
            "", ctx.corte,                       # sem base no cartão: o método fica no Glossário
            "analise.tempo_ate_encerramento" if enc.exata else "analise.tabua_de_vida", 1,
            "mediana do tempo entre a identificação e o encerramento; conta também os casos ainda abertos"
            + ("; não atingido" if curva and mediana is None else "") + k))

        def idade(corte, cubo):
            if cubo.contagem(analise.NACIONAL, coluna) in (None, 0):
                return None
            return analise.envelhecimento(ctx.pendencias, corte).medianas.get(coluna)
        idade_atual = idade(ctx.corte, cubos[ctx.ano])
        idade_antes = idade(corte_anterior, cubos[anterior]) if anterior else None
        lista.append(IndicadorN1(
            "KPI-04", nome["KPI-04"], idade_atual, "anos", idade_antes, anterior,
            round(idade_atual - idade_antes, 1) if idade_atual is not None and idade_antes is not None else None,
            "menor", f"mediana {de_total}" if de_total else "mediana", ctx.corte, "analise.envelhecimento", 1,
            "idade mediana: anos desde a identificação, dos casos ativos no corte" + k))
        return tuple(lista)


    # ------------------------------------------------------------ ficha, documentos e custódias (N2 e N3)
    @staticmethod
    def _dono_do_painel(painel: Painel, usuario: Usuario) -> None:
        if painel.usuario_id != usuario.id:
            raise ErroAcervo("O painel é pessoal: só quem o abriu consulta os detalhes.")

    def _pendencia_do_painel(self, painel: Painel, usuario: Usuario, codigo: str):
        self._dono_do_painel(painel, usuario)
        p = next((x for x in painel.pendencias if x.codigo == codigo), None)
        if p is None:                                  # fora do escopo do painel: nada sai
            self._registrar_negacao("CONSULTA", "FORA_DO_ESCOPO", usuario, painel.nivel, codigo)
            raise ErroAcervo("Registro fora do seu escopo.")
        return p

    def responsaveis_da_pendencia(self, painel: Painel, usuario: Usuario, codigo: str) -> list:
        """A cadeia de responsabilidade de uma pendência, filtrada NA CONSULTA pelo nível (RF-21): o N2 não
        recebe pessoa física (nivel_minimo = 3)."""
        self._dono_do_painel(painel, usuario)
        self._autorizar(usuario, painel.nivel, Operacao.VISUALIZAR, codigo=codigo)
        p = self._pendencia_do_painel(painel, usuario, codigo)
        return [r for r in self.repo.responsaveis(painel.nivel.value, p.uf) if r.pendencia_codigo == codigo]

    def documentos(self, painel: Painel, usuario: Usuario, codigo: str) -> list:
        """Metadados dos documentos da pendência (tipo, número, data, situação): N2 e N3."""
        from ecosec.acervo import documentos as docs
        self._autorizar(usuario, painel.nivel, Operacao.LISTAR_DOCUMENTOS, codigo=codigo)
        return docs.documentos_da_pendencia(self._pendencia_do_painel(painel, usuario, codigo), painel.hoje)

    def abrir_documento(self, painel: Painel, usuario: Usuario, codigo: str, documento_id: int) -> EntregaDocumento:
        """Renderiza (QR, assinaturas, hash), marca (visível e S9, nessa ordem), registra e só então entrega.
        Só o N3 abre o conteúdo; nenhum nível exporta (matriz)."""
        from ecosec.acervo import documentos as docs
        from ecosec.servicos import documentos as render
        self._autorizar(usuario, painel.nivel, Operacao.VISUALIZAR_DOCUMENTO, codigo=codigo)
        if self.rasterizar_documento is None:
            raise ErroAcervo("Visualizador de documentos não configurado nesta montagem.")
        p = self._pendencia_do_painel(painel, usuario, codigo)
        doc = next((d for d in docs.documentos_da_pendencia(p, painel.hoje) if d.id == documento_id), None)
        if doc is None:
            self._registrar_negacao("CONSULTA", "DOCUMENTO_INEXISTENTE", usuario, painel.nivel, codigo)
            raise ErroAcervo("Documento não encontrado para esta pendência.")
        gerador = next((r.nome for r in self.repo.responsaveis(painel.nivel.value, p.uf)
                        if r.pendencia_codigo == codigo and r.vinculo == "GERADOR_ORIGINAL"), None)
        campos = docs.campos(doc, p, painel.atividades, painel.motivos, gerador)
        momento = self.relogio()
        html = docs.html_do_documento(campos, render.hash_documento(campos), p)
        imagem, h_doc, h_consulta, marca = render.renderizar(html, campos, usuario.id, usuario.matricula, momento,
                                                              self.chave, self.p_marca, self.rasterizar_documento)
        # SEM REGISTRO, O DOCUMENTO NÃO É ENTREGUE (S-04: tipo, número e hash da leitura)
        self.trilha.registrar("CONSULTA", "CONCEDIDO", "ABERTURA_DOCUMENTO", nivel_solicitado=painel.nivel.value,
                              usuario_id=usuario.id,
                              detalhe=f"DOC {doc.tipo} {doc.numero}; {codigo}; SHA256 {h_consulta[:16]}"[:DETALHE_MAX])
        return EntregaDocumento(doc, imagem, h_doc, h_consulta, marca, momento)

    def custo_por_responsavel(self, painel: Painel, usuario: Usuario) -> list:
        """Custo do passivo ativo e cobrável por responsável nomeado (KPI-05 por responsável). Só o N3 (matriz,
        ); a consulta fica na trilha. Não há exportação: a lista só é vista."""
        if painel.usuario_id != usuario.id:
            raise ErroAcervo("O painel é pessoal: só quem o abriu consulta os detalhes.")
        self._autorizar(usuario, painel.nivel, Operacao.SOMAR_POR_RESPONSAVEL, codigo="CUSTO_RESPONSAVEL")
        linhas = analise.custo_por_responsavel(painel.pendencias, self.repo.responsaveis(painel.nivel.value),
                                               painel.hoje, painel.regras)
        self.trilha.registrar("CONSULTA", "CONCEDIDO", "CUSTO_POR_RESPONSAVEL", nivel_solicitado=painel.nivel.value,
                              usuario_id=usuario.id, detalhe=f"{len(linhas)} responsaveis"[:DETALHE_MAX])
        return linhas

    def memoria_por_responsavel(self, painel: Painel, usuario: Usuario, nome: str) -> list:
        """De onde vem o custo de um responsável: por pendência, a rota de tratamento e os componentes
        (custos.decompor). Mesma regra da soma (só N3, matriz) e a consulta fica na trilha."""
        from ecosec.acervo import custos
        if painel.usuario_id != usuario.id:
            raise ErroAcervo("O painel é pessoal: só quem o abriu consulta os detalhes.")
        self._autorizar(usuario, painel.nivel, Operacao.SOMAR_POR_RESPONSAVEL, codigo="CUSTO_RESPONSAVEL")
        linha = next((l for l in analise.custo_por_responsavel(painel.pendencias,
                                                                 self.repo.responsaveis(painel.nivel.value),
                                                                 painel.hoje, painel.regras) if l.nome == nome), None)
        if linha is None:
            raise ErroAcervo("Responsável sem pendência ativa cobrável no seu escopo.")
        por_codigo = {p.codigo: p for p in painel.pendencias}
        itens = []
        for codigo in linha.codigos:
            p = por_codigo[codigo]
            componentes = regras.memoria_de_calculo(p, painel.regras)
            itens.append(MemoriaCusto(p.codigo, p.substancia, p.classe_risco,
                                      custos.rota_de(p, painel.regras.custos).nome, componentes,
                                      regras.custo_estimado(p, painel.regras)))
        self.trilha.registrar("CONSULTA", "CONCEDIDO", "MEMORIA_CUSTO_RESPONSAVEL",
                              nivel_solicitado=painel.nivel.value, usuario_id=usuario.id,
                              detalhe=f"{len(itens)} pendencias"[:DETALHE_MAX])     # o nome não vai à trilha
        return itens

    def _autorizar_custodia(self, painel: Painel, usuario: Usuario) -> None:
        """Localização de custódia é SECRETA: só a camada 3, pela matriz e pelo papel de quem pede."""
        self._dono_do_painel(painel, usuario)
        self._autorizar(usuario, painel.nivel, Operacao.VISUALIZAR, codigo="CUSTODIA")
        if painel.nivel is not Nivel.N3:
            raise ErroAcervo("Instalações de custódia não fazem parte deste acesso.")

    def custodias(self, painel: Painel, usuario: Usuario, ano: int | None = None) -> list[tuple]:
        """[(Custodia, ocupação no fim de `ano`)]: só para o N3 (localização de custódia é SECRETA)."""
        from ecosec.acervo import sinteticos
        self._autorizar_custodia(painel, usuario)
        ano = ano or painel.hoje.year
        return [(c, sinteticos.ocupacao_em(c, ano, painel.pendencias)) for c in sinteticos.CUSTODIAS]

    def pendencias_da_custodia(self, painel: Painel, usuario: Usuario, nome: str | None,
                               ano: int | None = None) -> list:
        """Pendências guardadas numa custódia (`nome`) ou in situ (`nome` = None), ativas ou já recolhidas
        até o fim de `ano`."""
        from ecosec.acervo import sinteticos
        self._autorizar_custodia(painel, usuario)
        corte = min(date(ano or painel.hoje.year, 12, 31), painel.hoje)
        escolhidas = []
        for p in painel.pendencias:
            c = sinteticos.custodia_de(p)
            if (c.nome if c else None) == nome and p.data_identificacao <= corte \
                    and (c is not None or p.ativa(corte)):
                escolhidas.append(p)
        return escolhidas

    # ------------------------------------------------------------ exportação
    def exportar_resumo(self, resumo: ResumoAgregado, usuario: Usuario, agrupamento: str, destino: Path, *,
                        risco: str = "BAIXO", verificado_em: datetime | None = None) -> str:
        """CSV ou XLSX (pela extensão) de uma tabela do resumo."""
        if resumo.usuario_id != usuario.id:
            raise ErroAcervo("A exportação é pessoal: só quem abriu o resumo pode exportá-lo.")
        self._autorizar(usuario, resumo.nivel, Operacao.EXPORTAR_AGREGADO, risco=risco, verificado_em=verificado_em,
                        evento="EXPORTACAO", codigo="RESUMO")
        tabelas = sem_custo(resumo.tabelas) if resumo.nivel is Nivel.N1 else resumo.tabelas   # defesa em profundidade
        titulos, linhas = tabelas[agrupamento]
        return self._gravar_tabela(usuario, resumo.nivel, resumo.escopo, titulos, linhas, Path(destino),
                                   "EXPORTACAO_RESUMO", agrupamento, aba="RESUMO")

    def exportar_planilha(self, painel: Painel, usuario: Usuario, codigos, destino: Path, filtros: str = "", *,
                          risco: str = "BAIXO", verificado_em: datetime | None = None) -> str:
        """Grava CSV ou XLSX (pela extensão) das pendências `codigos` do painel. Devolve o SHA-256."""
        if painel.usuario_id != usuario.id:
            raise ErroAcervo("A exportação é pessoal: só quem abriu o painel pode exportá-lo.")
        self._autorizar(usuario, painel.nivel, Operacao.EXPORTAR_REGISTROS, risco=risco, verificado_em=verificado_em,
                        evento="EXPORTACAO", codigo="PLANILHA")
        pedidas = set(codigos)
        escolhidas = [p for p in painel.pendencias if p.codigo in pedidas]
        if len(escolhidas) != len(pedidas):          # código fora do escopo do painel: não sai nada
            self._registrar_negacao("EXPORTACAO", "FORA_DO_ESCOPO", usuario, painel.nivel, "PLANILHA")
            raise ErroAcervo("A seleção tem registros fora do seu escopo: nada foi exportado.")
        dados = analise.linhas(escolhidas, painel.hoje, painel.regras, painel.atividades, painel.motivos)
        return self._gravar_tabela(usuario, painel.nivel, painel.escopo, analise.TITULOS,
                                   [[getattr(l, c) for c in analise.COLUNAS] for l in dados], Path(destino),
                                   "EXPORTACAO_PLANILHA", filtros, aba="PASSIVOS")

    def exportar_ficha(self, painel: Painel, usuario: Usuario, codigo: str, destino: Path, *,
                       risco: str = "BAIXO", verificado_em: datetime | None = None) -> str:
        """A ficha de uma pendência: a linha da planilha mais os atributos derivados (fase,
        contaminante e meio, restrição, usos anterior e pretendido) e o custo por categoria EEA com a memória de
        cálculo. Números crus. Mesmo caminho e mesmas regras da planilha: matriz (EXPORTAR_REGISTROS, o N3 não
        exporta), step-up e trilha antes de gravar. Nenhum responsável sai na ficha exportada."""
        from ecosec.acervo import ficha
        if painel.usuario_id != usuario.id:
            raise ErroAcervo("A exportação é pessoal: só quem abriu o painel pode exportá-lo.")
        self._autorizar(usuario, painel.nivel, Operacao.EXPORTAR_REGISTROS, risco=risco, verificado_em=verificado_em,
                        evento="EXPORTACAO", codigo="FICHA")
        p = next((x for x in painel.pendencias if x.codigo == codigo), None)
        if p is None:                                 # fora do escopo do painel: não sai nada
            self._registrar_negacao("EXPORTACAO", "FORA_DO_ESCOPO", usuario, painel.nivel, "FICHA")
            raise ErroAcervo("Registro fora do seu escopo: nada foi exportado.")
        base = analise.linhas([p], painel.hoje, painel.regras, painel.atividades, painel.motivos)[0]
        linha = [getattr(base, c) for c in analise.COLUNAS] + ficha.linha_exportacao(
            ficha.atributos(p, painel.regras.custos))
        return self._gravar_tabela(usuario, painel.nivel, painel.escopo, analise.TITULOS + ficha.TITULOS_EXPORTACAO,
                                   [linha], Path(destino), "EXPORTACAO_FICHA", f"FICHA {codigo}", aba="FICHA")

    def exportar(self, entrega: Entrega, usuario: Usuario, destino: Path, *, risco: str = "BAIXO",
                 verificado_em: datetime | None = None) -> Path:
        if entrega.usuario_id != usuario.id:
            raise ErroAcervo("A exportação é pessoal: só quem abriu o relatório pode exportá-lo.")
        self._autorizar(usuario, entrega.nivel, Operacao.EXPORTAR_RELATORIO, risco=risco,
                        verificado_em=verificado_em, evento="EXPORTACAO", codigo=entrega.item.codigo)
        ok, png = cv2.imencode(".png", entrega.imagem)       # PNG: sem perda, a marca chega intacta
        if not ok:
            raise ErroAcervo("Falha ao gerar o arquivo.")
        destino = Path(destino)
        # registra antes de gravar: se a trilha falhar, o arquivo não sai
        self.trilha.registrar("EXPORTACAO", "CONCEDIDO", "EXPORTACAO_" + entrega.exportacao.value,
                              nivel_solicitado=entrega.nivel.value, usuario_id=usuario.id,
                              detalhe=f"{entrega.item.codigo}; arquivo {destino.name}")
        destino.write_bytes(png.tobytes())                    # aceita acentos no caminho (cv2.imwrite não)
        return destino

    def _gravar_tabela(self, usuario, nivel, escopo, titulos, linhas, destino: Path, motivo: str, filtros: str,
                       aba: str) -> str:
        formato = destino.suffix.lower().lstrip(".")
        if formato not in ("csv", "xlsx"):
            raise ErroAcervo("Formato de planilha não suportado: use .csv ou .xlsx.")
        momento = self.relogio()
        rastreio = {"EXPORTADO POR": f"{usuario.nome} (MATRICULA {usuario.matricula})",
                    "MOMENTO": f"{momento:%Y-%m-%d %H:%M:%S}", "NIVEL": str(nivel.value), "ESCOPO": escopo,
                    "FILTROS": filtros or "NENHUM", "REGISTROS": str(len(linhas))}
        conteudo = (analise.tabela_csv(titulos, linhas) if formato == "csv"
                    else analise.tabela_xlsx(titulos, linhas, rastreio, aba))
        resumo = analise.sha256(conteudo)
        # registra antes de gravar: se a trilha falhar, o arquivo não sai
        self.trilha.registrar("EXPORTACAO", "CONCEDIDO", motivo, nivel_solicitado=nivel.value, usuario_id=usuario.id,
                              detalhe=(f"{formato.upper()}; {len(linhas)} linhas; sha256 {resumo[:32]}"
                                       + (f"; {filtros}" if filtros else ""))[:DETALHE_MAX])
        destino.write_bytes(conteudo)
        return resumo

    # ------------------------------------------------------------ auditoria
    def identificar_marca(self, imagem: np.ndarray) -> Marca | None:
        """De quem veio uma cópia vazada? None = sem marca legível (nunca um palpite).

        A marca DCT vive na grade de blocos 8x8 do tamanho original, e uma cópia
        reduzida perde essa grade. Todo relatório é desenhado com a mesma largura:
        se a leitura direta falhar, a cópia volta a essa largura e é lida de novo.
        O CRC da marca continua impedindo que uma leitura ruim acuse alguém."""
        marca = s9_rastreio.extrair(imagem, self.chave, self.p_marca)
        altura, largura = imagem.shape[:2]
        if marca is None and largura != relatorios.LARGURA:
            tamanho = (relatorios.LARGURA, round(altura * relatorios.LARGURA / largura))
            marca = s9_rastreio.extrair(cv2.resize(imagem, tamanho, interpolation=cv2.INTER_CUBIC),
                                        self.chave, self.p_marca)
        return marca

    def _registrar_negacao(self, evento, motivo, usuario, nivel, codigo):
        try:
            self.trilha.registrar(evento, "NEGADO", motivo, nivel_solicitado=int(nivel), usuario_id=usuario.id,
                                  detalhe=codigo)
        except Exception:  # noqa: BLE001, a negação vale mesmo sem registro
            pass
