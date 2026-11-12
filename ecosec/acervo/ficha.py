"""Atributos da ficha da pendência, todos DERIVADOS.

Nenhum campo novo no acervo nem no banco: `sinteticos.gerar()` continua produzindo exatamente as mesmas
pendências (o teste guarda o hash de antes). Cada atributo vem de uma fonte só:

    Fase              acervo/fase.py (etapa atual; CONAMA 420/2009, art. 23)
    Contaminante      CONTAMINANTE: catálogo por substância (as 33 do gerador), com o grupo do contaminante e o
    e meio            meio afetado, coerente com a classe. Sem concentração nem excedência: exigiriam transcrever
                      os valores orientadores da CONAMA 420, o que está fora do escopo
    Restrição de uso  regra determinística fase × meio × classe (RESTRICAO_BASE + COMPLEMENTO_MEIO): PARAMETRO
    Uso anterior      USO_ANTERIOR: catálogo por código de ATIVIDADE (AG-01 a AG-13). A atividade pode vir do banco;
                      a coluna nova é derivada aqui pelo código, sem mudar o esquema do MySQL
    Uso pretendido    só na classe área contaminada, sorteado num gerador separado (semente própria, derivada do
                      código da pendência): não consome nenhum número da sequência do acervo. PARAMETRO. Nas outras
                      classes, "não se aplica"
    Memória de        custos.decompor agrupado nas quatro categorias EEA ([custos.categoria_componente]); a soma das
    cálculo           categorias é o custo da pendência (tolerância de centavo)

Regra do ciclo: "ciclo" aqui é a CLASSE da pendência. A linha de geração do garimpo (AG-13) faz o resíduo Classe I
percorrer as etapas do ciclo da área, mas um rejeito de amalgamação não é terreno: não tem uso pretendido e a
restrição é a de resíduo (padrão mais conservador, anotado para).

Sem Qt: `acervo/` não importa a interface. Textos na convenção do acervo (maiúsculas, sem acento); a fase usa o
rótulo de `fase.rotulo`.
"""
from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass

from ecosec.acervo import custos, fase as _fase
from ecosec.acervo.formatos import NAO_SE_APLICA
from ecosec.acervo.sinteticos import AREA, CLASSE_I, RADIOATIVO

PARAMETRO = "PARAMETRO"

# ---------------------------------------------------------------- contaminante e meio
GRUPOS = (
    "METAIS", "INORGANICOS (CIANETO E SULFETO)", "HIDROCARBONETOS AROMATICOS (BTEX)",
    "HIDROCARBONETOS POLICICLICOS AROMATICOS (PAH)", "HIDROCARBONETOS DE PETROLEO", "SOLVENTES HALOGENADOS",
    "PESTICIDAS", "PESTICIDAS ORGANOCLORADOS", "BIFENILAS POLICLORADAS (PCB)", "DIOXINAS E FURANOS",
    "DRENAGEM ACIDA (METAIS E ACIDEZ)", "ORGANICOS DE PROCESSO (LICOR NEGRO)", "MISTURA DE RESIDUOS PERIGOSOS",
    "RADIONUCLIDEOS NATURAIS (NORM)", "RADIONUCLIDEOS ARTIFICIAIS",
)
GRUPOS_RADIOATIVOS = ("RADIONUCLIDEOS NATURAIS (NORM)", "RADIONUCLIDEOS ARTIFICIAIS")

SOLO, AGUA, SOLO_E_AGUA, SEDIMENTO = "SOLO", "AGUA SUBTERRANEA", "SOLO E AGUA SUBTERRANEA", "SEDIMENTO"
SOLIDO, PASTOSO, LIQUIDO, EQUIPAMENTO = "RESIDUO SOLIDO", "RESIDUO PASTOSO", "RESIDUO LIQUIDO", "EQUIPAMENTO CONTAMINADO"
FONTE, REJEITO = "FONTE SELADA", "REJEITO SOLIDO"
# meio afetado admitido por classe: a área contamina um meio natural; o resíduo e o rejeito são a matriz que contém
# o contaminante (nenhum meio natural é atribuído a um passivo acondicionado: padrão conservador)
MEIOS_DA_CLASSE = {AREA: (SOLO, AGUA, SOLO_E_AGUA, SEDIMENTO),
                   CLASSE_I: (SOLIDO, PASTOSO, LIQUIDO, EQUIPAMENTO),
                   RADIOATIVO: (FONTE, REJEITO)}

# substância (exatamente como em sinteticos.PERFIS) -> (grupo do contaminante, meio afetado)
CONTAMINANTE = {
    # AG-01 postos
    "BTEX EM AGUA SUBTERRANEA": ("HIDROCARBONETOS AROMATICOS (BTEX)", AGUA),
    "PAH E BORRA DE TANQUE SUBTERRANEO": ("HIDROCARBONETOS POLICICLICOS AROMATICOS (PAH)", SOLO),
    "BENZENO EM SOLO SOB A PISTA": ("HIDROCARBONETOS AROMATICOS (BTEX)", SOLO),
    # AG-02 química e defensivos
    "ORGANOCLORADOS HCH DDT EM SOLO": ("PESTICIDAS ORGANOCLORADOS", SOLIDO),      # solo escavado, já resíduo
    "PESTICIDAS OBSOLETOS EM TAMBORES": ("PESTICIDAS", SOLIDO),
    "SOLVENTES CLORADOS PCE TCE": ("SOLVENTES HALOGENADOS", SOLO_E_AGUA),
    # AG-03 galvanoplastia
    "LODO GALVANICO COM CROMO VI": ("METAIS", PASTOSO),
    "BANHO DE CIANETO EXAURIDO": ("INORGANICOS (CIANETO E SULFETO)", LIQUIDO),
    "METAIS PESADOS NI ZN CU": ("METAIS", SOLO),
    # AG-04 metalurgia
    "ESCORIA COM CHUMBO E CADMIO": ("METAIS", SOLIDO),
    "OLEO BPF E BORRA OLEOSA DE FORNOS": ("HIDROCARBONETOS DE PETROLEO", PASTOSO),
    "PCBS EM SOLO DA SUBESTACAO INTERNA": ("BIFENILAS POLICLORADAS (PCB)", SOLO),
    # AG-05 aterro de resíduos perigosos
    "CHORUME CLASSE I EM LAGOA": ("MISTURA DE RESIDUOS PERIGOSOS", LIQUIDO),
    "RESIDUOS EM CELULA SEM MANTA": ("MISTURA DE RESIDUOS PERIGOSOS", SOLIDO),
    # AG-06 transformadores com ascarel
    "ASCAREL PCBS EM TRANSFORMADORES": ("BIFENILAS POLICLORADAS (PCB)", EQUIPAMENTO),
    "CARCACAS CONTAMINADAS COM PCBS": ("BIFENILAS POLICLORADAS (PCB)", EQUIPAMENTO),
    # AG-07 mineração com radioatividade natural
    "REJEITO COM URANIO E TORIO NORM": ("RADIONUCLIDEOS NATURAIS (NORM)", REJEITO),
    "DRENAGEM ACIDA DE PILHA DE ESTERIL": ("DRENAGEM ACIDA (METAIS E ACIDEZ)", SOLO_E_AGUA),
    "PRODUTOS PERIGOSOS EM GALPAO": ("MISTURA DE RESIDUOS PERIGOSOS", SOLIDO),
    # AG-08 radioterapia e fontes seladas
    "FONTE SELADA DE CESIO 137": ("RADIONUCLIDEOS ARTIFICIAIS", FONTE),
    "FONTE DE COBALTO 60 DE TELETERAPIA": ("RADIONUCLIDEOS ARTIFICIAIS", FONTE),
    "PARA RAIOS COM AMERICIO 241": ("RADIONUCLIDEOS ARTIFICIAIS", FONTE),
    # AG-09 curtumes
    "LODO DE CURTIMENTO COM CROMO": ("METAIS", PASTOSO),
    "BANHO DE CALEIRO COM SULFETO": ("INORGANICOS (CIANETO E SULFETO)", LIQUIDO),
    # AG-10 refino e terminais
    "HIDROCARBONETOS EM FASE LIVRE": ("HIDROCARBONETOS DE PETROLEO", SOLO_E_AGUA),
    "BORRA DE FUNDO DE TANQUE": ("HIDROCARBONETOS DE PETROLEO", PASTOSO),
    # AG-11 celulose e papel
    "LICOR NEGRO EM LAGOA DESATIVADA": ("ORGANICOS DE PROCESSO (LICOR NEGRO)", LIQUIDO),
    "DIOXINAS E FURANOS EM SEDIMENTO": ("DIOXINAS E FURANOS", SEDIMENTO),
    # AG-12 lavanderias e tinturarias
    "PERCLOROETILENO PCE NO AQUIFERO": ("SOLVENTES HALOGENADOS", AGUA),
    "RESIDUO DE DESTILACAO DE SOLVENTE": ("SOLVENTES HALOGENADOS", PASTOSO),
    # AG-13 garimpo de ouro com mercúrio
    "MERCURIO EM SEDIMENTO DE GARIMPO": ("METAIS", SEDIMENTO),
    "REJEITO DE AMALGAMACAO COM MERCURIO": ("METAIS", SOLIDO),
    "BALSA DE GARIMPO ABANDONADA": ("METAIS", EQUIPAMENTO),
}


class SemCatalogo(KeyError):
    """Substância ou atividade fora do catálogo: o atributo não é adivinhado."""


@dataclass(frozen=True)
class Contaminante:
    grupo: str
    meio: str


def contaminante(p) -> Contaminante:
    try:
        grupo, meio = CONTAMINANTE[p.substancia]
    except KeyError:
        raise SemCatalogo(f"Substância sem contaminante no catálogo: {p.substancia!r}") from None
    return Contaminante(grupo, meio)


# ---------------------------------------------------------------- restrição de uso (PARAMETRO)
I, N, R, E = _fase.IDENTIFICACAO, _fase.INVESTIGACAO, _fase.REMEDIACAO, _fase.ENCERRADA
_AREA_DIAGNOSTICO = "ACESSO CONTROLADO E MUDANCA DE USO SUSPENSA ATE O DIAGNOSTICO"
_RESIDUO_GUARDA = "LOCAL DE GUARDA ISOLADO; MANUSEIO E REMOCAO SO COM PLANO APROVADO"
_RADIO_CONTROLE = "AREA SOB CONTROLE RADIOLOGICO; ACESSO SO DE PESSOA AUTORIZADA PELA CNEN"
# (classe, fase) -> restrição base
RESTRICAO_BASE = {
    (AREA, I): _AREA_DIAGNOSTICO,
    (AREA, N): _AREA_DIAGNOSTICO,
    (AREA, R): "ACESSO RESTRITO A OBRA E MUDANCA DE USO SUSPENSA ATE A REABILITACAO",
    (AREA, E): "USO LIMITADO AO DECLARADO NA REABILITACAO",
    (CLASSE_I, I): _RESIDUO_GUARDA,
    (CLASSE_I, N): _RESIDUO_GUARDA,
    (CLASSE_I, R): "MANUSEIO E TRANSPORTE SO POR EMPRESA LICENCIADA",
    (CLASSE_I, E): "SEM RESTRICAO NO LOCAL (RESIDUO DESTINADO)",
    (RADIOATIVO, I): _RADIO_CONTROLE,
    (RADIOATIVO, N): _RADIO_CONTROLE,
    (RADIOATIVO, R): "AREA SOB CONTROLE RADIOLOGICO; TRANSPORTE SO COM AUTORIZACAO DA CNEN",
    (RADIOATIVO, E): "SEM RESTRICAO NO LOCAL (MATERIAL RECOLHIDO)",
}
# meio -> complemento enquanto a pendência está ativa (fase antes de ENCERRADA)
COMPLEMENTO_MEIO = {
    SOLO: "PROIBIDOS ESCAVACAO E CULTIVO",
    AGUA: "PROIBIDA A CAPTACAO DE AGUA SUBTERRANEA",
    SOLO_E_AGUA: "PROIBIDOS ESCAVACAO, CULTIVO E CAPTACAO DE AGUA SUBTERRANEA",
    SEDIMENTO: "PROIBIDAS DRAGAGEM E PESCA NO LOCAL",
    EQUIPAMENTO: "EQUIPAMENTO FORA DE OPERACAO",
    LIQUIDO: "PROIBIDO O LANCAMENTO EM CORPO HIDRICO OU REDE",
}
# meio -> complemento depois do encerramento (só a água subterrânea da área reabilitada continua controlada)
COMPLEMENTO_ENCERRADA = {
    AGUA: "CAPTACAO DE AGUA SUBTERRANEA SO COM AUTORIZACAO DO ORGAO AMBIENTAL",
    SOLO_E_AGUA: "CAPTACAO DE AGUA SUBTERRANEA SO COM AUTORIZACAO DO ORGAO AMBIENTAL",
}


def restricao_de(classe: str, fase_codigo: str, meio: str) -> str:
    """A regra pura (para a tabela e os testes): base da (classe, fase) mais o complemento do meio."""
    base = RESTRICAO_BASE[(classe, fase_codigo)]
    complemento = (COMPLEMENTO_ENCERRADA if fase_codigo == E else COMPLEMENTO_MEIO).get(meio)
    return f"{base}; {complemento}" if complemento else base


def restricao(p) -> str:
    return restricao_de(p.classe_risco, _fase.fase(p), contaminante(p).meio)


# ---------------------------------------------------------------- uso anterior
# código da atividade -> uso anterior do local (o uso que gerou o passivo)
USO_ANTERIOR = {
    "AG-01": "COMERCIAL (POSTO DE COMBUSTIVEIS)",
    "AG-02": "INDUSTRIAL (QUIMICA E DEFENSIVOS AGRICOLAS)",
    "AG-03": "INDUSTRIAL (GALVANOPLASTIA)",
    "AG-04": "INDUSTRIAL (METALURGIA E FUNDICAO)",
    "AG-05": "DISPOSICAO DE RESIDUOS (ATERRO DE RESIDUOS PERIGOSOS)",
    "AG-06": "INDUSTRIAL (MANUTENCAO E DEPOSITO DE TRANSFORMADORES)",
    "AG-07": "MINERACAO (MINERIO COM URANIO E TORIO ASSOCIADOS)",
    "AG-08": "SERVICO DE SAUDE E PESQUISA (FONTES SELADAS)",
    "AG-09": "INDUSTRIAL (CURTUME)",
    "AG-10": "INDUSTRIAL (REFINO E TERMINAL DE PETROLEO)",
    "AG-11": "INDUSTRIAL (CELULOSE E PAPEL)",
    "AG-12": "SERVICOS (LAVANDERIA E TINTURARIA)",
    "AG-13": "MINERACAO (GARIMPO DE OURO)",
}


def uso_anterior(p) -> str:
    try:
        return USO_ANTERIOR[p.atividade]
    except KeyError:
        raise SemCatalogo(f"Atividade sem uso anterior no catálogo: {p.atividade!r}") from None


# ---------------------------------------------------------------- uso pretendido (PARAMETRO)
# Cenários de uso da CONAMA 420/2009 (agrícola, residencial, industrial). Pesos: PARAMETRO de simulação, sem fonte.
USOS_PRETENDIDOS = ("AGRICOLA", "RESIDENCIAL", "INDUSTRIAL")
PESO_USO_PRETENDIDO = {"AGRICOLA": 0.20, "RESIDENCIAL": 0.35, "INDUSTRIAL": 0.45}
SEMENTE_USO_PRETENDIDO = "ECOSEC USO PRETENDIDO 2026"     # diferente da SEMENTE do acervo, por construção


def semente_uso_pretendido(codigo: str) -> int:
    """Semente própria de cada pendência: SHA-256 do código (estável entre execuções e máquinas)."""
    return int.from_bytes(hashlib.sha256(f"{SEMENTE_USO_PRETENDIDO}:{codigo}".encode("utf-8")).digest()[:8], "big")


def uso_pretendido(p) -> str:
    """Só na área contaminada; nas outras classes, "não se aplica". O sorteio usa um `random.Random` local com a
    semente do código: não toca no gerador global nem na sequência do acervo."""
    if p.classe_risco != AREA:
        return NAO_SE_APLICA
    rng = random.Random(semente_uso_pretendido(p.codigo))
    return rng.choices(USOS_PRETENDIDOS, weights=[PESO_USO_PRETENDIDO[u] for u in USOS_PRETENDIDOS])[0]


# ---------------------------------------------------------------- memória de cálculo por categoria
@dataclass(frozen=True)
class CategoriaCusto:
    nome: str                          # uma de custos.CATEGORIAS_EEA
    total: float
    componentes: tuple                 # custos.Componente, na ordem de decompor()


ROTULO_CATEGORIA = {"INVESTIGACAO": "INVESTIGAÇÃO", "REMEDIACAO": "REMEDIAÇÃO", "MONITORAMENTO": "MONITORAMENTO",
                    "DISPOSICAO": "DISPOSIÇÃO"}                      # exibição (a exportação usa o código)


@dataclass(frozen=True)
class MemoriaCategorizada:
    rota: str
    categorias: tuple                  # CategoriaCusto nas quatro categorias EEA, na ordem de CATEGORIAS_EEA
    total: float                       # = custos.custo(p)
    data_base: str                     # "2026-10"
    fonte: str                         # fonte da rota ("PARAMETRO" enquanto não houver fonte primária)


def memoria(p, c: custos.ParametrosCustos) -> MemoriaCategorizada:
    """Custo da pendência decomposto nas quatro categorias EEA; a soma das categorias é o custo."""
    componentes = custos.decompor(p, c)
    categorias = tuple(CategoriaCusto(nome, round(sum(x.valor for x in componentes if x.categoria == nome), 2),
                                      tuple(x for x in componentes if x.categoria == nome))
                       for nome in custos.CATEGORIAS_EEA)
    rota = custos.rota_de(p, c)
    return MemoriaCategorizada(rota.nome, categorias, custos.custo(p, c), c.data_base, rota.fonte)


# ---------------------------------------------------------------- a ficha
@dataclass(frozen=True)
class AtributosFicha:
    fase: str                          # código (IDENTIFICACAO, ...); a tela mostra fase.rotulo
    grupo_contaminante: str
    meio: str
    restricao: str                     # PARAMETRO
    uso_anterior: str
    uso_pretendido: str                # PARAMETRO na área; "não se aplica" nas outras classes
    memoria: MemoriaCategorizada


def atributos(p, c: custos.ParametrosCustos) -> AtributosFicha:
    ct = contaminante(p)
    return AtributosFicha(_fase.fase(p), ct.grupo, ct.meio, restricao(p), uso_anterior(p), uso_pretendido(p),
                          memoria(p, c))


# Exportação (crua): colunas que a ficha acrescenta à linha da planilha. Valores sem formatação de exibição.
TITULOS_EXPORTACAO = ("FASE", "GRUPO DO CONTAMINANTE", "MEIO AFETADO", "RESTRICAO DE USO", "FONTE DA RESTRICAO",
                      "USO ANTERIOR", "USO PRETENDIDO", "FONTE DO USO PRETENDIDO", "ROTA",
                      *(f"CUSTO {nome}" for nome in custos.CATEGORIAS_EEA), "DATA BASE DOS VALORES",
                      "FONTE DOS VALORES", "MEMORIA DE CALCULO")


def linha_exportacao(a: AtributosFicha) -> list:
    """Os valores de TITULOS_EXPORTACAO: códigos, textos e números crus (ponto decimal, sem milhar, sem R$).
    Memoria de calculo: um componente por item, "CATEGORIA|COMPONENTE|quantidade|unidade|unitario|valor",
    separados por " / "."""
    m = a.memoria
    itens = " / ".join(f"{cat.nome}|{x.nome}|{x.quantidade!r}|{x.unidade}|{x.unitario!r}|{x.valor!r}"
                       for cat in m.categorias for x in cat.componentes)
    return [a.fase, a.grupo_contaminante, a.meio, a.restricao, PARAMETRO, a.uso_anterior, a.uso_pretendido,
            PARAMETRO if a.uso_pretendido != NAO_SE_APLICA else NAO_SE_APLICA, m.rota,
            *(cat.total for cat in m.categorias), m.data_base, m.fonte, itens]
