"""Filtro único do painel: um recorte do acervo, lido por todas as vistas.

Antes havia quatro estados de filtro independentes (mapa, planilha, gráfico de risco e panorama). Este
objeto é puro (sem Qt) e imutável: quem guarda o filtro corrente e avisa as vistas é o EstadoFiltro da
interface. Cada dimensão de conjunto vazia significa "sem restrição"; dimensões diferentes combinam em E,
valores da mesma dimensão em ou.

A semântica reproduz os predicados que já existiam (para a ligação nas telas não mudar nenhum número):
  - UF e atividade: igualdade exata (MapaVetorial.filtrar; PlanilhaAnalitica.filtrar);
  - risco: a faixa de `regras.categoria(p, hoje)`, sempre avaliada em `hoje` (o mapa calcula a faixa uma
    vez, na montagem, com painel.hoje; a planilha também, em analise.linhas). O corte por ano não muda a faixa;
  - motivo e ação recomendada: igualdade com o código do motivo e com `regras.acao_recomendada(p, hoje, r)`
    (a planilha compara os rótulos "código · nome", que correspondem 1 para 1 aos códigos);
  - situação e ano: corte = fim do ano (31/12), limitado a hoje, como MapaInterativo.definir_ano; sem ano,
    o corte é hoje. ATIVAS = `p.ativa(corte)` (os pontos do mapa); ENCERRADAS = `p.encerrada(corte)`;
    TODAS = identificadas até o corte. Sem ano e com o cadastro todo datado até hoje, isso coincide com a
    planilha (ENCERRAMENTO vazio / preenchido / qualquer);
  - busca: o termo (sem espaços nas pontas, em maiúsculas) contido em código, substância, município,
    bairro, logradouro ou CEP, como na planilha, e também na classe ("REJEITO" acha os rejeitos
    radioativos).
Dimensões só desta vista: município (par UF, município: há nomes repetidos entre
UFs), classe e etapa (`etapa_atual`).

A situação aparece como "Situação do caso" com os rótulos Ativos, Encerrados e
Todos (`acervo/vocabulario.py`), e o PADRÃO passou a ser TODAS (antes, ATIVAS). Os valores internos não mudaram.
Os chips usam os rótulos do vocabulário (classe, atividade e motivo pelo nome simples, sem o código).
"""
from dataclasses import dataclass, fields, replace
from datetime import date

from ecosec.acervo import regras as _regras
from ecosec.acervo import vocabulario as _vocabulario

SITUACOES = ("ATIVAS", "ENCERRADAS", "TODAS")             # a ordem dos combos: Ativos, Encerrados, Todos
SITUACAO_PADRAO = "TODAS"
# dimensões de conjunto, na ordem em que os chips aparecem
CONJUNTOS = ("ufs", "municipios", "classes", "atividades", "motivos", "riscos", "acoes", "etapas")
DIMENSOES = ("situacao", "ano", *CONJUNTOS, "busca")
CAMPOS_BUSCA = ("codigo", "substancia", "municipio", "bairro", "logradouro", "cep", "classe_risco")

ROTULO_DIMENSAO = {"situacao": _vocabulario.CAMPO_SITUACAO, "ano": "Ano", "ufs": "UF", "municipios": "Município",
                   "classes": "Classe", "atividades": "Atividade", "motivos": "Motivo", "riscos": "Risco",
                   "acoes": "Ação", "etapas": "Etapa", "busca": "Busca"}
ROTULO_SITUACAO = _vocabulario.ROTULO_SITUACAO        # Ativos, Encerrados, Todos
ROTULO_CLASSE = _vocabulario.ROTULO_CLASSE


def _conjunto(dimensao: str, valor) -> frozenset:
    """Aceita um valor solto, qualquer iterável ou None. No município, um par (UF, nome) solto vale um só."""
    if valor is None:
        return frozenset()
    if isinstance(valor, str):
        return frozenset({valor})
    if dimensao == "municipios" and isinstance(valor, tuple) and len(valor) == 2 and all(
            isinstance(v, str) for v in valor):
        return frozenset({valor})
    return frozenset(tuple(v) if dimensao == "municipios" else v for v in valor)


@dataclass(frozen=True)
class Filtro:
    ufs: frozenset = frozenset()
    municipios: frozenset = frozenset()      # pares (UF, MUNICIPIO)
    classes: frozenset = frozenset()
    atividades: frozenset = frozenset()      # códigos AG-xx
    motivos: frozenset = frozenset()         # códigos MP-xx
    riscos: frozenset = frozenset()          # faixas de regras.categoria (BAIXO..CRITICO)
    acoes: frozenset = frozenset()           # regras.acao_recomendada
    etapas: frozenset = frozenset()          # etapa_atual
    situacao: str = SITUACAO_PADRAO
    ano: int | None = None
    busca: str = ""

    def __post_init__(self):
        for nome in CONJUNTOS:
            object.__setattr__(self, nome, _conjunto(nome, getattr(self, nome)))
        if self.situacao not in SITUACOES:
            raise ValueError(f"situação inválida: {self.situacao!r} (use {', '.join(SITUACOES)})")
        if self.ano is not None:
            object.__setattr__(self, "ano", int(self.ano))
        object.__setattr__(self, "busca", self.busca or "")

    # ------------------------------------------------------------ predicado
    def corte(self, hoje: date) -> date:
        """Data em que a situação é avaliada: fim do ano escolhido (até hoje) ou hoje."""
        return hoje if self.ano is None else min(date(self.ano, 12, 31), hoje)

    @property
    def termo(self) -> str:
        return self.busca.strip().upper()

    def aceita(self, p, hoje: date, regras: "_regras.ParametrosRegras | None" = None) -> bool:
        if self.ufs and p.uf not in self.ufs:
            return False
        if self.municipios and (p.uf, p.municipio) not in self.municipios:
            return False
        if self.classes and p.classe_risco not in self.classes:
            return False
        if self.atividades and p.atividade not in self.atividades:
            return False
        if self.motivos and p.motivo not in self.motivos:
            return False
        if self.etapas and p.etapa_atual not in self.etapas:
            return False
        corte = self.corte(hoje)
        if self.situacao == "ATIVAS" and not p.ativa(corte):
            return False
        if self.situacao == "ENCERRADAS" and not p.encerrada(corte):
            return False
        if self.situacao == "TODAS" and p.data_identificacao > corte:
            return False
        termo = self.termo
        if termo and not any(termo in str(getattr(p, campo)) for campo in CAMPOS_BUSCA):
            return False
        if self.riscos and _regras.categoria(p, hoje) not in self.riscos:
            return False
        if self.acoes and _regras.acao_recomendada(p, hoje, regras or _regras.ParametrosRegras.padrao()) \
                not in self.acoes:
            return False
        return True

    def aplicar(self, pendencias, hoje: date, regras: "_regras.ParametrosRegras | None" = None) -> list:
        if self.acoes and regras is None:
            regras = _regras.ParametrosRegras.padrao()
        return [p for p in pendencias if self.aceita(p, hoje, regras)]

    def contar(self, pendencias, hoje: date, regras: "_regras.ParametrosRegras | None" = None
               ) -> tuple[int, int, int]:
        """(dentro, fora, total): total = todas as pendências recebidas; dentro + fora == total."""
        pendencias = list(pendencias)
        dentro = len(self.aplicar(pendencias, hoje, regras))
        return dentro, len(pendencias) - dentro, len(pendencias)

    # ------------------------------------------------------------ edição (sempre devolve outro Filtro)
    def com(self, **mudancas) -> "Filtro":
        desconhecidas = set(mudancas) - set(DIMENSOES)
        if desconhecidas:
            raise TypeError(f"dimensão desconhecida: {', '.join(sorted(desconhecidas))}")
        return replace(self, **mudancas)

    def sem(self, dimensao: str, valor=None) -> "Filtro":
        """Tira a restrição da dimensão (toda, ou só `valor` numa dimensão de conjunto)."""
        if dimensao in CONJUNTOS:
            if valor is None:
                return replace(self, **{dimensao: frozenset()})
            return replace(self, **{dimensao: getattr(self, dimensao) - _conjunto(dimensao, valor)})
        padrao = {f.name: f.default for f in fields(self)}
        if dimensao not in padrao:
            raise TypeError(f"dimensão desconhecida: {dimensao}")
        return replace(self, **{dimensao: padrao[dimensao]})

    def vazio(self) -> bool:
        """Sem nenhuma restrição além do padrão (todos os casos até hoje). O filtro vazio é `Filtro()`."""
        return not self.chips()

    # ------------------------------------------------------------ chips
    def chips(self, atividades: dict | None = None, motivos: dict | None = None) -> list[tuple]:
        """[(dimensão, valor, rótulo)], um por restrição ativa. Classe, atividade e motivo saem pelo nome simples
        do vocabulário (o código fica no glossário); os catálogos ficam para o código que o vocabulário não tem."""
        from ecosec.dominio.acervo import rotulo
        resultado = []
        if self.situacao != SITUACAO_PADRAO:
            resultado.append(("situacao", self.situacao, f"{ROTULO_DIMENSAO['situacao']}: {ROTULO_SITUACAO[self.situacao]}"))
        if self.ano is not None:
            resultado.append(("ano", self.ano, f"Ano: {self.ano}"))
        legivel = {"municipios": lambda v: f"{v[1]}/{v[0]}", "classes": lambda v: ROTULO_CLASSE.get(v, v),
                   "atividades": lambda v: _vocabulario.ROTULO_ATIVIDADE.get(v) or rotulo(v, atividades or {}),
                   "motivos": lambda v: _vocabulario.ROTULO_MOTIVO.get(v) or rotulo(v, motivos or {}),
                   "riscos": lambda v: _vocabulario.ROTULO_FAIXA.get(v, v),
                   "acoes": lambda v: _vocabulario.ROTULO_ACAO.get(v, v),
                   "etapas": lambda v: _vocabulario.ROTULO_ETAPA.get(v, v)}
        for dimensao in CONJUNTOS:
            texto = legivel.get(dimensao, str)
            for valor in sorted(getattr(self, dimensao), key=self._ordem(dimensao)):
                resultado.append((dimensao, valor, f"{ROTULO_DIMENSAO[dimensao]}: {texto(valor)}"))
        if self.termo:
            resultado.append(("busca", self.busca, f"Busca: {self.busca.strip()}"))
        return resultado

    @staticmethod
    def _ordem(dimensao: str):
        if dimensao == "riscos":
            return lambda v: (_regras.CATEGORIAS.index(v) if v in _regras.CATEGORIAS else 99, v)
        if dimensao == "acoes":
            return lambda v: (_regras.ACOES.index(v) if v in _regras.ACOES else 99, v)
        return lambda v: v
