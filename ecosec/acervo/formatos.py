"""Formatador único de exibição, por tipo de coluna: o mesmo número sai igual no resumo, na
planilha e nos relatórios.

    inteiro      1.055                    (milhar com ponto)
    dias         4.026                    (inteiro com milhar; o título diz a unidade)
    percentual   83,0%                    (uma casa e o sinal)
    custo        R$ 1.958,6 mi            (custo somado de um grupo: uma casa, em milhões)
    custo_caso   R$ 365.800               (custo de uma pendência: reais com milhar)
    quantidade   106.165,8 t · 3.066,7 m³ (uma casa e a unidade da classe da coluna)
    anos         10,9 anos                (atraso em anos com uma casa)

Só exibição: a exportação (CSV e XLSX) continua com os números crus. "SUPRIMIDO" passa intacto. Unidade que não
se aplica à linha (a coluna de toneladas na linha da área contaminada) sai "não se aplica", nunca com travessão.
"""
from datetime import date

from ecosec.acervo import analise, quantidades

NAO_SE_APLICA = "não se aplica"
DIAS_POR_ANO = 365.25


def numero(valor: float, casas: int = 1) -> str:
    """Formato brasileiro: 1.376,5 (milhar com ponto, decimal com vírgula)."""
    return f"{valor:,.{casas}f}".replace(",", "§").replace(".", ",").replace("§", ".")


def inteiro(valor) -> str:
    return numero(round(valor), 0)


def percentual(valor: float) -> str:
    return f"{numero(valor, 1)}%"


def custo(valor: float) -> str:
    """Custo agregado em milhões, uma casa. Um grupo pequeno, mas não nulo, não sai como zero."""
    if 0 < abs(valor) < 50_000:
        return "< R$ 0,1 mi"
    return f"R$ {numero(valor / 1e6, 1)} mi"


def custo_caso(valor: float) -> str:
    return f"R$ {numero(valor, 0)}"


def quantidade(valor: float, classe: str) -> str:
    return f"{numero(valor, 1)} {quantidades.sigla(classe)}"


def anos(dias: float) -> str:
    return f"{numero(dias / DIAS_POR_ANO, 1)} anos"


# tipo de cada coluna
CLASSE_DA_COLUNA = {titulo: classe for classe, titulo in analise.COLUNA_DA_CLASSE.items()}
TIPO_DA_COLUNA = {
    "PENDENCIAS": "inteiro", analise.FORA_DA_PREVISAO: "inteiro", analise.CRITICAS: "inteiro",
    analise.ALEM_DO_PRAZO: "inteiro",
    analise.PERCENTUAL_FORA_DA_PREVISAO: "percentual", analise.PERCENTUAL_ALEM_DO_PRAZO: "percentual",
    analise.ATRASO_FORA_DA_PREVISAO: "dias", "CUSTO ESTIMADO": "custo",
    # planilha (uma linha = uma pendência)
    "ATRASO DIAS": "dias", "DIAS ALEM DO PRAZO LIMITE": "dias",
    "LATITUDE": "coordenada", "LONGITUDE": "coordenada", "CRITICIDADE": "score",
}
TIPO_NA_PLANILHA = {"CUSTO ESTIMADO": "custo_caso"}       # o mesmo título, um caso só: reais com milhar


def exibir(titulo: str, valor, planilha: bool = False) -> str:
    """Texto de uma célula pelo tipo da coluna titulo."""
    if isinstance(valor, str):
        return valor                                   # SUPRIMIDO, nomes, códigos: intactos
    if isinstance(valor, date):
        return f"{valor:%d/%m/%Y}"
    if valor is None:
        return ""
    tipo = (TIPO_NA_PLANILHA.get(titulo) if planilha else None) or TIPO_DA_COLUNA.get(titulo)
    if titulo in CLASSE_DA_COLUNA:
        return quantidade(valor, CLASSE_DA_COLUNA[titulo])
    if tipo in ("inteiro", "dias"):
        return inteiro(valor)
    if tipo == "percentual":
        return percentual(valor)
    if tipo == "custo":
        return custo(valor)
    if tipo == "custo_caso":
        return custo_caso(valor)
    if tipo == "coordenada":
        return numero(valor, 5)
    if tipo == "score":
        return numero(valor, 2)
    if isinstance(valor, int):
        return inteiro(valor)
    return numero(valor, 1) if planilha else numero(valor, 2)


def celula(titulos, valor_de, j: int, planilha: bool = False) -> str:
    """Texto da coluna j de uma linha; `valor_de(k)` lê a coluna k da mesma linha (para o contexto)."""
    titulo, valor = titulos[j], valor_de(j)
    if valor == analise.SUPRIMIDO:
        return valor
    classe = CLASSE_DA_COLUNA.get(titulo)
    if classe and "CLASSE DE RISCO" in titulos and valor_de(list(titulos).index("CLASSE DE RISCO")) != classe:
        return NAO_SE_APLICA                           # tonelada na linha da área contaminada: não é zero
    if titulo == "QUANTIDADE" and "UNIDADE" in titulos and isinstance(valor, (int, float)):
        unidade = valor_de(list(titulos).index("UNIDADE"))
        return f"{numero(valor, 2)} {quantidades.SIGLA.get(unidade, unidade)}"
    return exibir(titulo, valor, planilha)
