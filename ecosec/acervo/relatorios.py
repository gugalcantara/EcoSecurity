"""Os 9 relatórios do acervo: desenhados na hora, a partir do banco.

    N1  A1-01 Panorama nacional · A1-02 Origem e motivo dos casos · A1-05 Mapa de densidade
    N2  A2-01 Fichas dos casos prioritários · A2-02 Casos com prazo vencido · A2-04 Rastreio de manifesto
    N3  A3-01 Consolidado nacional · A3-02 Matriz de risco · A3-03 Mapa de calor do risco

Cada função recebe dados já filtrados pelo serviço (o N2 só recebe a própria
UF; o N1 nem recebe a cadeia de responsáveis) e desenha marcando o que é
sensível. Defesa em profundidade: um relatório de N2 marca endereço e
coordenadas mesmo nunca sendo exibido no N1: se alguém rebaixar o nível
mínimo dele no banco por engano, a tarja ainda protege.

Quando o segredo é a posição, suprimir no lugar não basta: o retângulo da
tarja fica exatamente onde o objeto está, e a posição vaza pela própria tarja.
Por isso o que o nível não pode
localizar é OMITIDO, nem desenhado: as instalações de custódia abaixo do N3 e
os pontos das pendências no N1 (que vê só o total agregado de cada estado).

Redesenho como relatório executivo. Todos seguem a mesma grade:
    capa enxuta (título, a pergunta que o relatório responde, escopo, data de corte, base e selo de sigilo);
    sumário executivo com 3 a 5 achados em frases; poucos indicadores com nome e contexto; seções numeradas, cada
    visual respondendo a uma pergunta (escrita como subtítulo); detalhe agrupado; nota de método; rodapé com
    a data de geração, o escopo e a classificação.
Política por camada: N1 só agregados protegidos (k=3, os mesmos do resumo e do cubo; nenhum valor financeiro,
endereço, coordenada ou nome); N2 decisão e ação na UF (o que priorizar, o que venceu, quem agir, prazos);
N3 precisão (números exatos com unidade, base, comparação e fontes), agrupada em situação, risco, custódia e custo.
Todo rótulo visível vem do `vocabulario` (classes, faixas, ações, motivos, atividades, KPIs, "caso", "score").
"""
import re
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from statistics import median

import cv2
import numpy as np
from PIL import Image

from ecosec.acervo import analise, fase, ficha, formatos, quantidades, regras, sinteticos, vocabulario
from ecosec.acervo.desenho import CINZA, TINTA, Documento, Fontes, Tela
from ecosec.acervo.mapa import CENTROIDES_UF, CONTORNO_BRASIL, Mapa
from ecosec.acervo.sinteticos import AREA, CLASSE_I, RADIOATIVO
from ecosec.dominio.acervo import GRUPOS_MOTIVO, Pendencia, RelatorioCatalogo, Responsavel, grupo_do_motivo

# ================================================================ grade, tipografia e cores (iguais nos nove)
LARGURA = 1000                     # a marca d'água é lida nesta largura (servicos.acervo.identificar_marca)
ALTURA_MINIMA = 1414               # proporção A4: o relatório curto continua com cara de página
MARGEM = 56
UTIL = LARGURA - 2 * MARGEM
GOTEIRA = 24
T_TITULO, T_SECAO, T_CORPO, T_TABELA, T_NOTA = 28, 18, 13, 12, 11

COR_NIVEL = {1: (46, 163, 107), 2: (217, 154, 30), 3: (210, 56, 79)}
CLASSIFICACAO = {1: "USO INTERNO", 2: "RESERVADO", 3: "SECRETO"}

DADO = (44, 82, 130)               # a série única das contagens (azul-ardósia; o azul AZUL fica para a custódia)
AZUL = (52, 120, 180)              # instalação de custódia (o mesmo símbolo no A1-05 e no A3-03)
FUNDO_SUAVE = (246, 247, 249)
FUNDO_GRUPO = (239, 242, 246)
FILETE = (224, 227, 232)
COR_SUPRIMIDO = (236, 237, 240)
CINZA_HACHURA = (160, 163, 170)
# faixas de risco: os mesmos valores de interface/componentes/simbologia.COR_IDENTIDADE (acervo não importa a
# interface; o teste test_relatorios confere que as duas tabelas continuam iguais)
COR_CATEGORIA = {"BAIXO": (46, 163, 107), "MEDIO": (217, 154, 30), "ALTO": (227, 106, 46), "CRITICO": (210, 56, 79)}
COR_CLASSE = {AREA: (78, 121, 167), CLASSE_I: (242, 142, 43), RADIOATIVO: (225, 87, 89)}
# rampa sequencial de densidade: os mesmos valores de simbologia.RAMPA_DENSIDADE (claro = pouco, escuro = muito)
RAMPA = ((220, 228, 247), (157, 184, 230), (85, 128, 204), (36, 81, 158), (11, 44, 102))

# a régua (pesos, faixas, prazo, custo, ação) mora nas regras de negócio: relatórios e painel usam a mesma
from ecosec.acervo.regras import ACAO_GRUPO, CATEGORIAS, PESO_GRUPO, RISCO_CLASSE, categoria, criticidade, fator_atraso

# título de exibição (o do banco fica em caixa alta e sem acento: item_acervo.titulo tem CHECK de padrão)
TITULOS = {"A1-01": "Panorama nacional", "A1-02": "Origem e motivo dos casos", "A1-05": "Mapa de densidade",
           "A2-01": "Fichas dos casos prioritários", "A2-02": "Casos com prazo vencido",
           "A2-04": "Rastreio de manifesto", "A3-01": "Consolidado nacional", "A3-02": "Matriz de risco",
           "A3-03": "Mapa de calor do risco"}
DESCRICOES = {i.codigo: i.descricao for i in sinteticos.CATALOGO}
NOME_REGIAO = {"NORTE": "Norte", "NORDESTE": "Nordeste", "CENTRO OESTE": "Centro-Oeste", "SUDESTE": "Sudeste",
               "SUL": "Sul"}
FAIXAS_IDADE_ROTULO = {"<1": "menos de 1", "1-3": "1 a 3", "3-5": "3 a 5", "5-10": "5 a 10", "10-20": "10 a 20",
                       "≥20": "20 ou mais"}
VINCULOS = {"GERADOR_ORIGINAL": "Gerador original", "SUCESSOR": "Sucessor", "PROPRIETARIO_ATUAL": "Proprietário atual",
            "TRANSPORTADOR": "Transportador", "DESTINADOR": "Destinador"}


def titulo(item: RelatorioCatalogo) -> str:
    """Título de exibição em linguagem simples (o código e o nível continuam os do banco)."""
    return TITULOS.get(item.codigo, item.titulo)


def descricao(item: RelatorioCatalogo) -> str:
    return DESCRICOES.get(item.codigo, item.descricao)


@dataclass(frozen=True)
class DadosRelatorio:
    pendencias: tuple[Pendencia, ...]
    responsaveis: dict | None              # codigo -> tuple[Responsavel]; None = nível 1 (não recebe)
    atividades: dict                        # AG-xx -> AtividadeGeradora
    motivos: dict                           # MP-xx -> MotivoPermanencia
    hoje: date
    escopo: str                             # "Nacional" ou "UF SP"
    gerado_em: datetime
    nivel: int = 3                          # nível de quem consulta: decide o que nem é desenhado
    regras: "regras.ParametrosRegras | None" = None   # None = os do config/ecosec.toml
    supressao_minima: int = 3               # o k ([indice_pressao] supressao_minima): só vale no N1

    @property
    def parametros(self) -> "regras.ParametrosRegras":
        return self.regras or regras.ParametrosRegras.padrao()

    @property
    def k(self) -> int:
        """No N2 e no N3 o k não se aplica."""
        return self.supressao_minima if self.nivel <= 1 else 0


# ================================================================ números
def br(valor: float, casas: int = 1) -> str:
    """Número no formato brasileiro: 1.376,5 (milhar com ponto, decimal com vírgula)."""
    return formatos.numero(valor, casas)


def brg(valor: float) -> str:
    """Como o formato "g" (sem zeros sobrando), com vírgula decimal: 2,5 · 3 · 47,76."""
    return f"{valor:g}".replace(".", ",")


def _suprimido(valor) -> bool:
    return valor is None or (isinstance(valor, str) and valor == analise.SUPRIMIDO)


def _pct(parte, todo) -> str:
    """Percentual com uma casa (o mesmo formato do resumo); vazio se a parte saiu SUPRIMIDO (o % a revelaria)."""
    if _suprimido(parte) or _suprimido(todo):
        return ""
    return formatos.percentual(100 * parte / todo) if todo else formatos.percentual(0)


def _qtd(valor) -> str:
    """Contagem com milhar, ou SUPRIMIDO intacto."""
    return analise.SUPRIMIDO if _suprimido(valor) else formatos.inteiro(valor)


def _volume(ps, classe: str) -> float:
    """Total de UMA classe, na unidade dela: nenhum total soma m³ com t nem solo com rejeito (quantidades.py)."""
    return quantidades.total_da_classe(ps, classe)


def _cartoes_de_volume(ps, ocultas=frozenset()) -> list[tuple[str, str]]:
    """Um total por classe, cada um com a sua unidade (t de Classe I, m³ de solo, m³ de rejeito). `ocultas` =
    classes cuja linha o resumo do N1 suprime: o total delas sai SUPRIMIDO."""
    return [(quantidades.DESCRICAO[c], analise.SUPRIMIDO if c in ocultas else formatos.quantidade(_volume(ps, c), c))
            for c in quantidades.CLASSES]


def _atraso_medio(ps, hoje) -> str:
    """Atraso médio dos casos com o prazo previsto vencido, em anos com uma casa."""
    dias = [p.dias_de_atraso(hoje) for p in ps if p.vencida(hoje)]
    return formatos.anos(sum(dias) / len(dias) if dias else 0)


def _rot_faixa(f: str) -> str:
    return vocabulario.rotulo(f, "faixa")


# a faixa no meio da frase ("faixa média"), para o exemplo da nota de método do A3-02
_FAIXA_NA_FRASE = {"BAIXO": "baixa", "MEDIO": "média", "ALTO": "alta", "CRITICO": "crítica"}


def _limiar_critico() -> str:
    """O score a partir do qual o caso é crítico, lido da régua na hora (o texto não guarda o número)."""
    return brg(regras.LIMITES[-1])


def _exemplo_do_score() -> str:
    """Material radioativo sem a quem cobrar com 1 e com 8 anos de atraso, cada um na faixa que a régua dá."""
    classe, grupo = RISCO_CLASSE[RADIOATIVO], PESO_GRUPO["Depende de recurso público"]
    um, oito = (classe * grupo * (1 + anos) for anos in (1, 8))
    return (f"Exemplo: material radioativo ({classe}) sem a quem cobrar ({brg(grupo)}): com 1 ano de atraso (× 2) = "
            f"{brg(um)}, faixa {_FAIXA_NA_FRASE[regras.faixa_do_score(um)]}; com 8 anos (× 9) = {brg(oito)}, faixa "
            f"{_FAIXA_NA_FRASE[regras.faixa_do_score(oito)]}.")


def _rot_classe(c: str) -> str:
    return vocabulario.rotulo(c, "classe")


def _rot_acao(a: str) -> str:
    return vocabulario.rotulo(a, "acao")


def _rot_motivo(m: str) -> str:
    return vocabulario.rotulo(m, "motivo")


def _rot_atividade(a: str) -> str:
    return vocabulario.rotulo(a, "atividade")


def _rot_resp(r: str) -> str:
    return vocabulario.rotulo(r, "responsabilidade")


def _casos(n, adjetivo: str = "") -> str:
    return analise.SUPRIMIDO if _suprimido(n) else vocabulario.casos(n, adjetivo)


def _plural(n: int, singular: str, plural: str) -> str:
    """"1 carga", "2 cargas" (milhar com ponto)."""
    return f"{formatos.inteiro(n)} {singular if n == 1 else plural}"


def _verbo(n: int, singular: str, plural: str) -> str:
    """Concordância do verbo com a contagem: "1 caso já esgotou", "2 casos já esgotaram"."""
    return singular if n == 1 else plural


def _local(dados: DadosRelatorio) -> str:
    """"a UF SP" / "o país": o sujeito das frases do sumário."""
    return f"a {dados.escopo}" if dados.escopo.startswith("UF ") else "o país"


def _uf_do_escopo(dados: DadosRelatorio) -> str | None:
    return dados.escopo.split()[1] if dados.escopo.startswith("UF ") else None


# ================================================================ totais do N1 (os mesmos do Resumo agregado)
def _cubo(dados: DadosRelatorio) -> "analise.CuboN1":
    """O cubo protegido do corte (memorizado em analise): no N1, k e complementar; no N2 e no N3, k = 0."""
    return analise.proteger_cubo(dados.pendencias, analise.REGIAO_DA_UF, dados.hoje, dados.k, dados.parametros)


def _resumo(dados: DadosRelatorio) -> dict:
    """Todas as tabelas do Resumo agregado, com a mesma supressão do N1: k em toda contagem,
    complementar pelas margens e, na família por UF, o cubo do panorama do mesmo corte. Um relatório do N1 que
    contasse por conta própria mostraria a célula que o resumo e o mapa escondem. No N2 e no N3, k = 0."""
    tabelas = {g: analise.agregar(dados.pendencias, dados.hoje, g, dados.atividades, dados.motivos, dados.parametros)
               for g in analise.AGRUPAMENTOS}
    if not dados.k:
        return tabelas
    tabelas, _ = analise.proteger_resumo(tabelas, dados.pendencias, dados.hoje, dados.atividades, dados.motivos,
                                         dados.k, dados.parametros, _cubo(dados))
    return tabelas


def _tabela_do_resumo(dados: DadosRelatorio, agrupamento: str):
    return _resumo(dados)[agrupamento]


def _coluna(tabela, coluna: str = "PENDENCIAS") -> dict:
    """{primeira chave do grupo (UF, código da atividade...): valor ou SUPRIMIDO}, na ordem da tabela."""
    titulos, linhas = tabela
    i = list(titulos).index(coluna)
    return {l[0]: l[i] for l in linhas}


def _maior_visivel(contagens: dict):
    visiveis = [(c, v) for c, v in contagens.items() if not _suprimido(v)]
    return max(visiveis, key=lambda cv: cv[1]) if visiveis else ("-", 0)


def _sub(cubo, nome: str, linha: str = analise.NACIONAL, coluna: str = analise.TODAS):
    v = cubo.subcontagem(nome, linha, coluna)
    return analise.SUPRIMIDO if v is None else v


def _cont(cubo, linha: str, coluna: str = analise.TODAS):
    v = cubo.contagem(linha, coluna)
    return analise.SUPRIMIDO if v is None else v


# ================================================================ peças de desenho comuns
def _tela(fontes, altura=7000) -> Tela:
    return Tela(LARGURA, altura, fontes)


def _luminancia(cor) -> float:
    def canal(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (canal(v) for v in cor[:3])
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _tinta_sobre(fundo) -> tuple:
    """Texto branco ou tinta sobre um fundo cheio, o que der mais contraste."""
    lum = _luminancia(fundo)
    return (255, 255, 255) if (1.05 / (lum + 0.05)) >= ((lum + 0.05) / (_luminancia(TINTA) + 0.05)) else TINTA


def _largura_texto(t: Tela, texto: str, tamanho: int, negrito=False) -> float:
    return t.d.textlength(texto, font=t.fonte(tamanho, negrito))


def _medir(t: Tela, texto: str, tamanho: int, largura: int, negrito=False) -> int:
    return len(t._quebrar(str(texto), t.fonte(tamanho, negrito), largura)) * int(tamanho * 1.35)


def _cabe(t: Tela, texto: str, largura: int, tamanho: int, negrito=False) -> str:
    """Corta com reticências para caber na coluna (a planilha do painel traz o texto inteiro)."""
    fonte = t.fonte(tamanho, negrito)
    if t.d.textlength(texto, font=fonte) <= largura:
        return texto
    while texto and t.d.textlength(texto + "…", font=fonte) > largura:
        texto = texto[:-1]
    return texto.rstrip() + "…"


def _centro(t: Tela, x_centro: float, y: int, texto: str, tamanho: int, negrito=False, cor=TINTA, sensivel=None):
    t.texto(x_centro - _largura_texto(t, texto, tamanho, negrito) / 2, y, texto, tamanho, negrito=negrito, cor=cor,
            sensivel=sensivel)


def _direita(t: Tela, x_direita: float, y: int, texto: str, tamanho: int, negrito=False, cor=TINTA):
    t.texto(x_direita - _largura_texto(t, texto, tamanho, negrito), y, texto, tamanho, negrito=negrito, cor=cor)


def _selo(t: Tela, x: float, y: int, texto: str, cor, tamanho: int = 11) -> int:
    """Selo de fundo cheio (faixa de risco): a cor é do fundo, o texto tem contraste. Devolve a largura."""
    largura = int(_largura_texto(t, texto, tamanho, True)) + 14
    t.retangulo(x, y, x + largura, y + int(tamanho * 1.35) + 6, preenchimento=cor, raio=4)
    t.texto(x + 7, y + 3, texto, tamanho, negrito=True, cor=_tinta_sobre(cor))
    return largura


def _selo_faixa(t: Tela, x: float, y: int, faixa: str, tamanho: int = 11) -> int:
    return _selo(t, x, y, _rot_faixa(faixa), COR_CATEGORIA[faixa], tamanho)


# ---------------------------------------------------------------- texto com trechos em negrito
_TOKEN = re.compile(r"\s+|\S+")


def _rico(t: Tela, x: int, y: int, texto: str, tamanho: int, largura: int, cor=TINTA, medir=False) -> int:
    """Parágrafo com trechos **em negrito**, quebrado na largura. Desenha cada trecho contínuo de uma linha com uma
    chamada a Tela.texto (o mesmo estilo junto). Devolve a altura."""
    unidades, atual, espaco_antes = [], [], False
    for i, parte in enumerate(texto.split("**")):
        negrito = i % 2 == 1
        for tok in _TOKEN.findall(parte):
            if tok.isspace():
                if atual:
                    unidades.append((espaco_antes, atual))
                    atual = []
                espaco_antes = True
            else:
                if not atual and unidades and not espaco_antes and i > 0 and tok:
                    # colado ao trecho anterior (ex.: "**62,0%**." ): continua a mesma unidade
                    prev_espaco, prev = unidades.pop()
                    atual, espaco_antes = prev, prev_espaco
                atual.append((tok, negrito))
        if atual:
            unidades.append((espaco_antes, atual))
            atual = []
            espaco_antes = False
    linhas, linha, x_atual = [], [], 0.0
    espaco = _largura_texto(t, " ", tamanho)
    for antes, pedacos in unidades:
        w = sum(_largura_texto(t, s, tamanho, n) for s, n in pedacos)
        gap = espaco if linha and antes else 0
        if linha and x_atual + gap + w > largura:
            linhas.append(linha)
            linha, x_atual, gap = [], 0.0, 0
        linha.append((gap > 0, pedacos))
        x_atual += gap + w
    if linha:
        linhas.append(linha)
    altura_linha = int(tamanho * 1.35)
    if medir:
        return altura_linha * len(linhas)
    for n_linha, linha in enumerate(linhas):
        trechos = []                                          # [(texto, negrito)] juntando o mesmo estilo
        for com_espaco, pedacos in linha:
            for j, (s, negrito) in enumerate(pedacos):
                prefixo = " " if (com_espaco and j == 0) else ""
                if trechos and trechos[-1][1] == negrito:
                    trechos[-1][0] += prefixo + s
                else:
                    if prefixo and trechos:
                        trechos[-1][0] += prefixo
                    trechos.append([s, negrito])
        xx = x
        for s, negrito in trechos:
            t.texto(xx, y + n_linha * altura_linha, s.rstrip(), tamanho, negrito=negrito, cor=cor)
            xx += _largura_texto(t, s, tamanho, negrito)
    return altura_linha * len(linhas)


# ---------------------------------------------------------------- capa, sumário, seções, rodapé
def _capa(t: Tela, item: RelatorioCatalogo, dados: DadosRelatorio, base: str) -> int:
    cor = COR_NIVEL[item.nivel_minimo]
    t.retangulo(0, 0, LARGURA, 8, preenchimento=cor)
    t.texto(MARGEM, 30, f"ECOSECURITY  ·  ACERVO DE PASSIVOS PERIGOSOS  ·  RELATÓRIO {item.codigo}", T_NOTA,
            negrito=True, cor=CINZA)
    # selo de classificação: o grau de sigilo do documento, pelo nível mínimo que o abre
    largura_selo = 200
    x_selo = LARGURA - MARGEM - largura_selo
    t.retangulo(x_selo, 26, LARGURA - MARGEM, 84, preenchimento=cor, raio=6)
    tinta = _tinta_sobre(cor)
    t.texto(x_selo + 14, 31, CLASSIFICACAO[item.nivel_minimo], 20, negrito=True, cor=tinta)
    t.texto(x_selo + 14, 60, f"Nível {item.nivel_minimo} · classificação da informação", 10, cor=tinta)
    largura_texto = UTIL - largura_selo - 24
    y = 50
    y += t.texto(MARGEM, y, titulo(item), T_TITULO, negrito=True, largura_max=largura_texto) + 2
    y += t.texto(MARGEM, y, descricao(item), 14, cor=CINZA, largura_max=largura_texto)
    y = max(y + 18, 104)
    meta = (("ESCOPO", dados.escopo), ("DATA DE CORTE", f"{dados.hoje:%d/%m/%Y}"), ("BASE", base),
            ("GERADO EM", f"{dados.gerado_em:%d/%m/%Y %H:%M}"))
    x = MARGEM
    for rotulo, valor in meta:
        largura = max(_largura_texto(t, valor, 13, True), _largura_texto(t, rotulo, 10, True))
        if x > MARGEM and x + largura > LARGURA - MARGEM:
            x, y = MARGEM, y + 42
        t.texto(x, y, rotulo, 10, negrito=True, cor=CINZA)
        t.texto(x, y + 15, valor, 13, negrito=True)
        x += largura + 40
    y += 44
    t.linha(MARGEM, y, LARGURA - MARGEM, y, cor=TINTA, espessura=2)
    return y + 24


def _sumario(t: Tela, y: int, achados: list[str], cor) -> int:
    """O sumário executivo: de 3 a 5 achados em frases, numerados, com o número-chave em negrito."""
    achados = [a for a in achados if a][:5]
    x_texto, largura = MARGEM + 54, UTIL - 54 - 24
    alturas = [_rico(t, x_texto, 0, a, 14, largura, medir=True) for a in achados]
    altura = 18 + 30 + sum(alturas) + 10 * max(0, len(achados) - 1) + 20
    t.retangulo(MARGEM, y, LARGURA - MARGEM, y + altura, preenchimento=FUNDO_SUAVE, raio=6)
    t.retangulo(MARGEM, y, MARGEM + 5, y + altura, preenchimento=cor)
    t.texto(MARGEM + 24, y + 16, "Sumário executivo", 16, negrito=True)
    yy = y + 18 + 30
    for i, (achado, h) in enumerate(zip(achados, alturas), 1):
        t.circulo(MARGEM + 34, yy + 10, 10, (255, 255, 255), contorno=FILETE)
        _centro(t, MARGEM + 34, yy + 2, str(i), 12, negrito=True, cor=CINZA)
        _rico(t, x_texto, yy, achado, 14, largura)
        yy += h + 10
    return y + altura + 28


def _secao(t: Tela, y: int, numero, titulo_secao: str, pergunta: str | None = None) -> int:
    """Seção numerada: filete, título e a pergunta que ela responde."""
    t.linha(MARGEM, y, LARGURA - MARGEM, y, cor=FILETE)
    y += 14
    t.texto(MARGEM, y, f"{numero}.  {titulo_secao}" if numero is not None else titulo_secao, T_SECAO, negrito=True)
    y += 30
    if pergunta:
        y += t.texto(MARGEM, y, pergunta, T_CORPO, cor=CINZA, largura_max=UTIL) + 4
    return y + 10


def _subtitulo(t: Tela, x: int, y: int, texto: str, largura: int = UTIL, nota: str | None = None) -> int:
    """Título de um gráfico dentro da seção (12 negrito), com a unidade ou a base em cinza."""
    h = t.texto(x, y, texto, 13, negrito=True, largura_max=largura)
    if nota:
        h += t.texto(x, y + h, nota, T_NOTA, cor=CINZA, largura_max=largura)
    return y + h + 8


def _nota(t: Tela, y: int, titulo_nota: str, itens: list[str]) -> int:
    """Nota de método / leitura: texto pequeno, sem caixa colorida."""
    itens = [i for i in itens if i]
    y += 4
    t.texto(MARGEM, y, titulo_nota, 12, negrito=True, cor=CINZA)
    y += 20
    for item in itens:
        t.texto(MARGEM, y, "·", T_NOTA, negrito=True, cor=CINZA)
        y += t.texto(MARGEM + 12, y, item, T_NOTA, cor=CINZA, largura_max=UTIL - 12) + 3
    return y + 10


def _fechar(t: Tela, item: RelatorioCatalogo, dados: DadosRelatorio) -> Documento:
    """Rodapé (data, escopo e classificação) e a página fechada logo abaixo do conteúdo, com a altura mínima de uma
    página A4. A marcação de documento simulado saiu."""
    altura_rodape = 56
    altura = max(t.fundo + 40 + altura_rodape, ALTURA_MINIMA)
    y = altura - altura_rodape
    t.linha(MARGEM, y, LARGURA - MARGEM, y, cor=FILETE)
    t.texto(MARGEM, y + 18, f"Gerado em {dados.gerado_em:%d/%m/%Y %H:%M}  ·  {dados.escopo}  ·  Classificação: "
                            f"{CLASSIFICACAO[item.nivel_minimo].capitalize()}", T_NOTA, cor=CINZA, largura_max=UTIL)
    t.cortar(altura)
    return Documento(t.para_bgr(), tuple(t.regioes))


# ---------------------------------------------------------------- indicadores
@dataclass(frozen=True)
class Kpi:
    nome: str
    valor: str
    contexto: str = ""


def _kpis(t: Tela, y: int, itens: list[Kpi], colunas: int | None = None) -> int:
    """Linha de indicadores: nome (o que é), valor, contexto (base e comparação). Filete no topo, sem caixa."""
    n = colunas or len(itens)
    largura = (UTIL - (n - 1) * GOTEIRA) // n
    alturas_nome = [_medir(t, k.nome, 12, largura, True) for k in itens]
    h_nome = max(alturas_nome, default=0)
    alturas_ctx = [_medir(t, k.contexto, T_NOTA, largura) if k.contexto else 0 for k in itens]
    altura = 12 + h_nome + 6 + 40 + max(alturas_ctx, default=0)
    for i, k in enumerate(itens):
        x = MARGEM + (i % n) * (largura + GOTEIRA)
        t.retangulo(x, y, x + largura, y + 3, preenchimento=TINTA)
        t.texto(x, y + 12, k.nome, 12, negrito=True, largura_max=largura)
        tamanho = 30                                   # número longo num espaço estreito: diminui, não corta
        while tamanho > 14 and _largura_texto(t, k.valor, tamanho, True) > largura:
            tamanho -= 2
        t.texto(x, y + 12 + h_nome + 4 + (30 - tamanho) // 2, k.valor, tamanho, negrito=True)
        if k.contexto:
            t.texto(x, y + 12 + h_nome + 6 + 40, k.contexto, T_NOTA, cor=CINZA, largura_max=largura)
    return y + altura + 26


# ---------------------------------------------------------------- gráficos
def _valor_e_pct(valor, total) -> str:
    """"1.055  (12,1%)"; SUPRIMIDO intacto; sem o % se não houver total."""
    if _suprimido(valor):
        return analise.SUPRIMIDO
    texto = formatos.inteiro(valor) if isinstance(valor, int) else brg(valor)
    return f"{texto}  ({_pct(valor, total)})" if total else texto


def _barras(t: Tela, x: int, y: int, largura: int, itens: list, total=None, largura_rotulo: int = 220,
            cor=DADO, cores=None, extras=None, titulo_extra: str | None = None, largura_extra: int = 96,
            tamanho: int = 12, maximo=None) -> int:
    """Barras horizontais com rótulo direto (valor e %). O rótulo quebra dentro da sua coluna e a linha cresce
    junto; SUPRIMIDO sai sem barra (o comprimento revelaria o número). `extras`: uma coluna de texto à direita
    (ex.: % críticos), alinhada à direita, com o título `titulo_extra`."""
    visiveis = [v for _, v in itens if not _suprimido(v)]
    maximo = maximo if maximo is not None else max(visiveis, default=0)
    reserva = 104
    largura_barra = largura - largura_rotulo - reserva - (largura_extra if extras else 0)
    if extras and titulo_extra:
        _direita(t, x + largura, y, titulo_extra, T_NOTA, negrito=True, cor=CINZA)
        y += 20
    altura_linha = int(tamanho * 1.35)
    for i, (rotulo, valor) in enumerate(itens):
        h = t.texto(x, y, rotulo, tamanho, largura_max=largura_rotulo - 12)
        y_barra = y + (altura_linha - 12) // 2 + 1
        if _suprimido(valor):
            t.texto(x + largura_rotulo, y, analise.SUPRIMIDO, T_NOTA, negrito=True, cor=CINZA)
        else:
            w = t.barra(x + largura_rotulo, y_barra, largura_barra, valor, maximo, altura=12,
                        cor=cores[i] if cores else cor) if valor else 0
            t.texto(x + largura_rotulo + w + 8, y, _valor_e_pct(valor, total), tamanho, negrito=True)
        if extras:
            _direita(t, x + largura, y, extras[i], tamanho)
        y += max(h, altura_linha) + 8
    return y + 6


def _colunas(t: Tela, x: int, y: int, largura: int, altura: int, itens: list, total=None, cor=DADO,
             legenda_eixo: str | None = None) -> int:
    """Colunas verticais com o valor em cima e a categoria embaixo (sem eixo de valores: o rótulo direto basta)."""
    n = max(1, len(itens))
    passo = largura / n
    largura_coluna = min(64, passo * 0.6)
    visiveis = [v for _, v in itens if not _suprimido(v)]
    maximo = max(visiveis, default=0) or 1
    base = y + altura
    for i, (rotulo, valor) in enumerate(itens):
        cx = x + passo * i + passo / 2
        if _suprimido(valor):
            _centro(t, cx, base - 18, analise.SUPRIMIDO, 10, negrito=True, cor=CINZA)
        else:
            h = int((altura - 38) * valor / maximo)
            if valor:
                t.retangulo(cx - largura_coluna / 2, base - h, cx + largura_coluna / 2, base, preenchimento=cor, raio=3)
                t.retangulo(cx - largura_coluna / 2, base - 3, cx + largura_coluna / 2, base, preenchimento=cor)
            _centro(t, cx, base - h - 34, formatos.inteiro(valor), 13, negrito=True)
            if total:
                _centro(t, cx, base - h - 17, _pct(valor, total), 10, cor=CINZA)
        linhas = t._quebrar(rotulo, t.fonte(12), int(passo - 6))
        for j, linha in enumerate(linhas):
            _centro(t, cx, base + 8 + j * 16, linha, 12)
    t.linha(x, base, x + largura, base, cor=TINTA)
    y = base + 8 + 16 * max(len(t._quebrar(r, t.fonte(12), int(passo - 6))) for r, _ in itens) + 4 if itens else base
    if legenda_eixo:
        _centro(t, x + largura / 2, y, legenda_eixo, T_NOTA, cor=CINZA)
        y += 18
    return y + 8


def _empilhada(t: Tela, x: int, y: int, largura: int, partes: list, total, altura: int = 24,
               legenda: bool = True) -> int:
    """Barra 100% empilhada (composição), com 2 px de folga entre as partes e a legenda com valor e % embaixo.
    Com alguma parte SUPRIMIDA não há barra (o comprimento revelaria o número): só a legenda."""
    tem_suprimido = any(_suprimido(v) for _, v, _ in partes)
    soma = sum(v for _, v, _ in partes if not _suprimido(v)) or 1
    if not tem_suprimido:
        xx = x
        for i, (_, valor, cor) in enumerate(partes):
            if not valor:
                continue
            w = largura * valor / soma
            fim = x + largura if i == len(partes) - 1 else xx + w - 2
            if fim > xx:
                t.retangulo(xx, y, fim, y + altura, preenchimento=cor)
            xx += w
        y += altura + 10
    if not legenda:
        return y
    xx = x
    for rotulo, valor, cor in partes:
        texto_valor = _valor_e_pct(valor, total)
        w = 14 + _largura_texto(t, rotulo, 12, True) + 6 + _largura_texto(t, texto_valor, 12) + 26
        if xx > x and xx + w > x + largura:
            xx, y = x, y + 22
        t.retangulo(xx, y + 3, xx + 10, y + 13, preenchimento=cor, raio=2)
        t.texto(xx + 14, y, rotulo, 12, negrito=True)
        t.texto(xx + 14 + _largura_texto(t, rotulo, 12, True) + 6, y, texto_valor, 12)
        xx += w
    return y + 30


# ---------------------------------------------------------------- tabela
@dataclass(frozen=True)
class Grupo:
    """Linha de grupo dentro da tabela (ex.: "Crítico · 98 casos")."""
    texto: str
    faixa: str | None = None


@dataclass(frozen=True)
class Faixa:
    """Célula com o selo da faixa de risco."""
    codigo: str


def _tabela(t: Tela, y: int, colunas: list, linhas: list, total=None, tamanho: int = T_TABELA, sensivel=None,
            x0: int = MARGEM, largura: int | None = None, negrito_col0: bool = False) -> int:
    """Tabela de relatório: cabeçalho pequeno em cinza com filete escuro, linhas separadas por filete fino,
    números à direita. `colunas` = [(título, largura[, "d"|"e"])] ("d" alinha à direita; número já alinha).
    Uma linha `Grupo` ocupa a largura toda. `sensivel(i, j)` devolve o rótulo de proteção da célula ou None."""
    largura = largura or sum(c[1] for c in colunas)
    altura_linha = int(tamanho * 1.35) + 10
    alturas = []
    for c in colunas:
        alturas.append(_medir(t, c[0], T_NOTA, c[1] - 12, True))
    h_cab = max(alturas, default=14)
    primeira = next((l for l in linhas if not isinstance(l, Grupo)), None)
    x = x0
    for j, c in enumerate(colunas):
        direita = (len(c) > 2 and c[2] == "d") or (primeira is not None and j < len(primeira)
                                                     and not isinstance(primeira[j], (str, Faixa)))
        linhas_cab = t._quebrar(c[0], t.fonte(T_NOTA, True), c[1] - 12)
        for j, l in enumerate(linhas_cab):
            yy = y + h_cab - len(linhas_cab) * int(T_NOTA * 1.35) + j * int(T_NOTA * 1.35)
            if direita:
                _direita(t, x + c[1] - 8, yy, l, T_NOTA, negrito=True, cor=CINZA)
            else:
                t.texto(x + 4, yy, l, T_NOTA, negrito=True, cor=CINZA)
        x += c[1]
    y += h_cab + 6
    t.linha(x0, y, x0 + largura, y, cor=TINTA, espessura=1)
    y += 6
    i_dado = 0
    for linha in linhas + ([total] if total else []):
        e_total = total is not None and linha is total
        if isinstance(linha, Grupo):
            y += 4
            t.retangulo(x0, y, x0 + largura, y + altura_linha, preenchimento=FUNDO_GRUPO)
            xx = x0 + 6
            if linha.faixa:
                xx += _selo_faixa(t, xx, y + 4, linha.faixa, 10) + 8
            t.texto(xx, y + 5, linha.texto, tamanho, negrito=True)
            y += altura_linha + 4
            continue
        if e_total:
            t.linha(x0, y - 3, x0 + largura, y - 3, cor=TINTA)
        x = x0
        for j, (c, valor) in enumerate(zip(colunas, linha)):
            largura_col = c[1]
            if isinstance(valor, Faixa):
                _selo_faixa(t, x + 4, y + 2, valor.codigo, 10)
                x += largura_col
                continue
            texto = valor if isinstance(valor, str) else (br(valor) if isinstance(valor, float)
                                                          else formatos.inteiro(valor))
            texto = _cabe(t, texto, largura_col - 12, tamanho, e_total or (negrito_col0 and j == 0))
            direita = (not isinstance(valor, str)) or (len(c) > 2 and c[2] == "d")
            negrito = e_total or (negrito_col0 and j == 0)
            rotulo = sensivel(i_dado, j) if sensivel and not e_total else None
            xx = x + largura_col - 8 - _largura_texto(t, texto, tamanho, negrito) if direita else x + 4
            t.texto(xx, y + 4, texto, tamanho, negrito=negrito, sensivel=rotulo)
            x += largura_col
        y += altura_linha
        if not e_total:
            t.linha(x0, y, x0 + largura, y, cor=FILETE)
            i_dado += 1
    return y + 16


# ---------------------------------------------------------------- mapas
def _na_rampa(frac: float) -> tuple:
    """Cor contínua da rampa sequencial (0 = mais claro, 1 = mais escuro)."""
    paradas = np.linspace(0, 1, len(RAMPA))
    frac = min(1.0, max(0.0, frac))
    return tuple(int(round(np.interp(frac, paradas, [c[k] for c in RAMPA]))) for k in range(3))


def _legenda_rampa(t: Tela, x: int, y: int, titulo_legenda: str, menor: str, maior: str, largura: int = 220) -> int:
    t.texto(x, y, titulo_legenda, T_NOTA, negrito=True, cor=CINZA)
    y += 18
    for i in range(largura):
        t.linha(x + i, y + 2, x + i, y + 14, cor=_na_rampa(i / (largura - 1)))
    t.texto(x, y + 18, menor, 10, cor=CINZA)
    _direita(t, x + largura, y + 18, maior, 10, cor=CINZA)
    return y + 38


def _quebras(valores: list[int], classes: int = 5) -> list[int]:
    """Limites superiores das classes do coroplético (quantis dos valores visíveis, sem repetir)."""
    if not valores:
        return []
    ordem = sorted(valores)
    limites = []
    for i in range(1, classes):
        v = ordem[min(len(ordem) - 1, int(round(i * len(ordem) / classes)) - 1)]
        if not limites or v > limites[-1]:
            limites.append(v)
    if ordem[-1] > (limites[-1] if limites else -1):
        limites.append(ordem[-1])
    return limites


def _classe_de(valor: int, limites: list[int]) -> int:
    return next((i for i, lim in enumerate(limites) if valor <= lim), len(limites) - 1)


def _mapa_coropletico(t: Tela, mapa: Mapa, por_uf: dict) -> list[tuple[str, tuple]]:
    """Nível 1: cada UF pintada pelo total de casos (rampa sequencial de 5 classes). Nenhum ponto é desenhado
    (omissão, não tarja): não há posição a inferir. UF SUPRIMIDA: cinza claro hachurado, sem número. Devolve a
    legenda [(texto, cor)]."""
    visiveis = {uf: n for uf, n in por_uf.items() if not _suprimido(n)}
    limites = _quebras(list(visiveis.values()))
    rampa = RAMPA[-len(limites):] if len(limites) < len(RAMPA) else RAMPA
    cores = {uf: rampa[_classe_de(n, limites)] for uf, n in visiveis.items()}
    escondidas = {uf for uf, n in por_uf.items() if _suprimido(n)}
    cores.update({uf: COR_SUPRIMIDO for uf in escondidas})
    mapa.desenhar_ufs(t, cores, padrao=(244, 245, 247), contorno=(255, 255, 255), hachura=escondidas,
                      cor_hachura=CINZA_HACHURA)
    for uf, (lon, lat) in CENTROIDES_UF.items():          # sigla no centro (o número fica na lista ao lado)
        x, y = mapa.px(lon, lat)
        fundo = cores.get(uf, (244, 245, 247))
        _centro(t, x, y - 7, uf, 10, negrito=True, cor=_tinta_sobre(fundo))
    legenda, anterior = [], 0
    for i, lim in enumerate(limites):
        de = anterior + 1 if i else min(visiveis.values())
        legenda.append((f"{formatos.inteiro(de)} a {formatos.inteiro(lim)}" if lim != de else formatos.inteiro(lim),
                        rampa[i]))
        anterior = lim
    if escondidas:
        legenda.append(("SUPRIMIDO", COR_SUPRIMIDO))
    return legenda


ORDEM_FAIXAS_DESENHO = ("BAIXO", "MEDIO", "ALTO", "CRITICO")      # o crítico por cima


def _pontos(t: Tela, dados: DadosRelatorio, mapa: Mapa, raio: float = 4, anel=True):
    """Um ponto por caso, na cor da faixa de risco (o crítico por cima)."""
    faixa = {p.codigo: categoria(p, dados.hoje) for p in dados.pendencias}
    for f in ORDEM_FAIXAS_DESENHO:
        for p in dados.pendencias:
            if faixa[p.codigo] != f:
                continue
            x, y = mapa.px(p.longitude, p.latitude)
            if mapa.dentro(x, y):
                t.circulo(x, y, raio, COR_CATEGORIA[f], contorno=(255, 255, 255) if anel else None)


def _custodias_ordenadas():
    """As instalações de custódia da mais cheia para a mais vazia: o número de cada uma no mapa e na lista."""
    return sorted(sinteticos.CUSTODIAS, key=lambda c: (-c.ocupacao, c.nome))


def _custodias(t: Tela, mapa: Mapa):
    """Instalações de custódia (só no N3): quadrado azul numerado, com anel branco; o nome fica na lista ao lado
    (rótulo no mapa cobria o calor e colidia com os vizinhos). A região marcada é a do símbolo."""
    for i, c in enumerate(_custodias_ordenadas(), 1):
        x, y = mapa.px(c.longitude, c.latitude)
        if not mapa.dentro(x, y, 10):
            continue
        t.retangulo(x - 11, y - 11, x + 11, y + 11, preenchimento=(255, 255, 255), raio=3)
        t.retangulo(x - 9, y - 9, x + 9, y + 9, preenchimento=AZUL, raio=2)
        _centro(t, x, y - 8, str(i), 11, negrito=True, cor=(255, 255, 255))
        t.marcar(x - 11, y - 11, x + 11, y + 11, "CUSTODIA", 3)


def _marcador_custodia(t: Tela, x: int, y: int, numero: int):
    t.retangulo(x, y, x + 16, y + 16, preenchimento=AZUL, raio=2)
    _centro(t, x + 8, y + 1, str(numero), 10, negrito=True, cor=(255, 255, 255))


def _lista_custodias(t: Tela, x: int, y: int, largura: int, barras: bool = True) -> int:
    """Lista numerada das instalações (o número do mapa), com a ocupação."""
    for i, c in enumerate(_custodias_ordenadas(), 1):
        _marcador_custodia(t, x, y, i)
        t.texto(x + 24, y, _cabe(t, c.nome, largura - 24 - 56, 10), 10, sensivel=("CUSTODIA", 3))
        _direita(t, x + largura, y, formatos.percentual(100 * c.ocupacao), 11, negrito=c.ocupacao > 0.9)
        if barras:
            t.retangulo(x + 24, y + 17, x + largura - 56, y + 24, preenchimento=FUNDO_GRUPO, raio=2)
            t.retangulo(x + 24, y + 17, x + 24 + int((largura - 80) * min(c.ocupacao, 1.0)), y + 24,
                        preenchimento=COR_CATEGORIA["CRITICO"] if c.ocupacao > 0.9 else DADO, raio=2)
            y += 34
        else:
            y += 22
    return y


def _legenda(t: Tela, x: int, y: int, largura: int, itens: list, titulo_legenda: str | None = None,
             forma: str = "quadrado") -> int:
    if titulo_legenda:
        t.texto(x, y, titulo_legenda, T_NOTA, negrito=True, cor=CINZA)
        y += 18
    xx = x
    for texto, cor in itens:
        w = 18 + _largura_texto(t, texto, T_NOTA) + 18
        if xx > x and xx + w > x + largura:
            xx, y = x, y + 20
        if forma == "ponto":
            t.circulo(xx + 6, y + 8, 5, cor, contorno=(255, 255, 255))
        else:
            t.retangulo(xx, y + 2, xx + 12, y + 14, preenchimento=cor, contorno=FILETE)
            if texto == analise.SUPRIMIDO:
                for d in range(-12, 12, 4):
                    t.linha(xx + max(0, d), y + 2 + max(0, -d), xx + min(12, d + 12), y + 2 + min(12, 12 - d),
                            cor=CINZA_HACHURA)
        t.texto(xx + 18, y, texto, T_NOTA)
        xx += w
    return y + 24


# ================================================================ N1: agregados protegidos, sem localização
def a1_01(item, dados: DadosRelatorio, fontes: Fontes) -> Documento:
    t = _tela(fontes)
    ps, hoje = dados.pendencias, dados.hoje
    n = len(ps)
    cubo, resumo = _cubo(dados), _resumo(dados)
    fora = _sub(cubo, analise.FORA_DA_PREVISAO)
    alem = _sub(cubo, analise.ALEM_DO_PRAZO)
    criticas = _sub(cubo, analise.CRITICAS)
    por_faixa = _coluna(resumo["POR NIVEL DE RISCO"])
    tab_classe = resumo["POR CLASSE DE RISCO"]
    por_classe = _coluna(tab_classe)
    criticas_classe = _coluna(tab_classe, analise.CRITICAS)
    por_regiao = _coluna(resumo["POR REGIAO"])
    fora_regiao = _coluna(resumo["POR REGIAO"], analise.PERCENTUAL_FORA_DA_PREVISAO)
    crit_regiao = _coluna(resumo["POR REGIAO"], analise.CRITICAS)
    por_uf = _coluna(resumo["POR UF"])
    env = analise.envelhecimento(ps, hoje)
    idade_escondida = analise.proteger_envelhecimento(env, dados.k, cubo if dados.k else None)
    por_idade = {f: (analise.SUPRIMIDO if (analise.TODAS, f) in idade_escondida
                     else env.contagens.get((analise.TODAS, f), 0)) for f in analise.ROTULOS_FAIXAS}
    mediana = env.medianas.get(analise.TODAS)

    y = _capa(t, item, dados, _casos(n, "ativos"))
    reg_top, n_reg = _maior_visivel(por_regiao)
    uf_top, n_uf = _maior_visivel(por_uf)
    dez_mais = [por_idade[f] for f in ("10-20", "≥20")]
    achados = [
        f"O país tem **{_casos(n, 'ativos')}**; **{_qtd(criticas)} ({_pct(criticas, n)})** estão na faixa de risco "
        "crítico." if not _suprimido(criticas) else f"O país tem **{_casos(n, 'ativos')}**.",
        (f"**{_pct(fora, n)}** dos casos já passaram do prazo previsto e **{_pct(alem, n)}** estão além do prazo "
         "legal da sua classe: o atraso é a regra, não a exceção.") if not (_suprimido(fora) or _suprimido(alem))
        else "",
        f"A região **{NOME_REGIAO.get(reg_top, reg_top)}** concentra **{_pct(n_reg, n)}** dos casos; **{uf_top}** é o "
        f"estado com mais casos ({formatos.inteiro(n_uf)}, {_pct(n_uf, n)})." if n_reg else "",
        (f"Metade dos casos está em aberto há mais de **{br(mediana)} anos**"
         + (f"; **{_pct(sum(dez_mais), n)}** estão no cadastro há 10 anos ou mais." if not any(map(_suprimido, dez_mais))
            else ".")) if mediana is not None and n >= max(dados.k, 1) else "",
    ]
    y = _sumario(t, y, achados, COR_NIVEL[1])
    y = _kpis(t, y, [
        Kpi("Casos ativos", formatos.inteiro(n), f"na data de corte, {hoje:%d/%m/%Y}"),
        Kpi(vocabulario.rotulo("KPI-03b", "kpi"), _qtd(fora), f"{_pct(fora, n)} dos casos ativos" if _pct(fora, n)
            else "oculto: poucos casos"),
        Kpi(vocabulario.rotulo("KPI-03", "kpi"), _qtd(alem), f"{_pct(alem, n)} dos casos ativos" if _pct(alem, n)
            else "oculto: poucos casos"),
        Kpi("Casos de risco crítico", _qtd(criticas),
            f"{_pct(criticas, n)} dos casos ativos (score {_limiar_critico()} ou mais)" if _pct(criticas, n)
            else "oculto: poucos casos")])

    # 1. gravidade e natureza
    y = _secao(t, y, 1, "Gravidade e natureza dos casos",
               "Quão graves são os casos ativos e de que tipo eles são?")
    y = _subtitulo(t, MARGEM, y, "Casos por faixa de risco", nota="Faixa do score de risco na data de corte.")
    y = _empilhada(t, MARGEM, y, UTIL, [(_rot_faixa(f), por_faixa.get(f, 0), COR_CATEGORIA[f])
                                         for f in reversed(CATEGORIAS)], n)
    y = _subtitulo(t, MARGEM, y + 4, "Casos e quantidade por classe",
                   nota="Cada classe na sua unidade: nenhum total soma toneladas com metros cúbicos.")
    linhas = []
    for c in quantidades.CLASSES:
        v = por_classe.get(c, 0)
        oculta = _suprimido(v)
        linhas.append([_rot_classe(c), _qtd(v), _pct(v, n) or "-", _pct(criticas_classe.get(c, 0), v) or "-",
                       analise.SUPRIMIDO if oculta else formatos.quantidade(_volume(ps, c), c)])
    y = _tabela(t, y, [("Classe", 300), ("Casos", 120, "d"), ("% dos casos", 130, "d"),
                       ("% de risco crítico na classe", 170, "d"), ("Quantidade", 168, "d")], linhas,
                negrito_col0=True)

    # 2. onde estão
    y = _secao(t, y + 4, 2, "Onde estão os casos",
               "Como os casos se distribuem entre as regiões, e que estados concentram mais?")
    y = _subtitulo(t, MARGEM, y, "Comparação entre regiões",
                   nota="Casos por classe e proporções dentro de cada região. Os 27 estados estão no relatório Mapa "
                        "de densidade.")
    linhas = []
    for reg in sorted(por_regiao, key=lambda r: (-(por_regiao[r] if not _suprimido(por_regiao[r]) else -1), r)):
        total_reg = por_regiao[reg]
        linhas.append([NOME_REGIAO.get(reg, reg), _qtd(total_reg), _pct(total_reg, n) or "-"]
                      + [_qtd(_cont(cubo, analise.linha_regiao(reg), c)) for c in quantidades.CLASSES]
                      + ["-" if _suprimido(fora_regiao.get(reg)) else formatos.percentual(fora_regiao[reg]),
                         _pct(crit_regiao.get(reg), total_reg) or "-"])
    y = _tabela(t, y, [("Região", 140), ("Casos", 80, "d"), ("% do país", 84, "d"),
                       (f"{_rot_classe(CLASSE_I)} (casos)", 120, "d"), (f"{_rot_classe(AREA)} (casos)", 120, "d"),
                       (f"{_rot_classe(RADIOATIVO)} (casos)", 120, "d"), ("% com prazo previsto vencido", 112, "d"),
                       ("% de risco crítico", 112, "d")], linhas, negrito_col0=True,
                total=["Brasil", formatos.inteiro(n), "100,0%"]
                + [_qtd(_cont(cubo, analise.NACIONAL, c)) for c in quantidades.CLASSES]
                + [_pct(fora, n) or "-", _pct(criticas, n) or "-"])
    visiveis = sorted(((uf, v) for uf, v in por_uf.items() if not _suprimido(v)), key=lambda kv: (-kv[1], kv[0]))
    escondidas = sorted(uf for uf, v in por_uf.items() if _suprimido(v))
    y = _subtitulo(t, MARGEM, y, "Os 10 estados com mais casos",
                   nota="Casos ativos e % do total nacional." + (
                       f" Abaixo, os {len(escondidas)} estados com o total SUPRIMIDO (não quer dizer zero)."
                       if escondidas else ""))
    y = _barras(t, MARGEM, y, UTIL, visiveis[:10] + [(uf, por_uf[uf]) for uf in escondidas], total=n,
                largura_rotulo=80)

    # 3. há quanto tempo
    y = _secao(t, y + 4, 3, vocabulario.rotulo("KPI-04", "kpi"),
               "Os casos são recentes ou se arrastam há anos?")
    y = _subtitulo(t, MARGEM, y, "Casos ativos por tempo desde a identificação",
                   nota=(f"Idade mediana: {br(mediana)} anos." if mediana is not None else ""))
    y = _colunas(t, MARGEM + 40, y + 6, UTIL - 80, 190,
                 [(FAIXAS_IDADE_ROTULO[f], por_idade[f]) for f in analise.ROTULOS_FAIXAS], total=n,
                 legenda_eixo="anos desde a identificação")

    y = _nota(t, y + 4, "Como ler", [
        f"{vocabulario.rotulo('KPI-03b', 'kpi')}: {vocabulario.definicao('VENCIDO', 'prazo')}",
        f"{vocabulario.rotulo('KPI-03', 'kpi')}: {vocabulario.definicao('KPI-03', 'kpi')}",
        "Faixa de risco: baixo, médio, alto ou crítico, conforme o score de risco do caso na data de corte. "
        + vocabulario.definicao("CRITICO", "faixa"),
        "Nível 1: apenas totais, os mesmos do Resumo agregado; nenhum endereço, coordenada, nome ou documento de "
        "empresa e nenhum valor financeiro. " + vocabulario.definicao("SUPRESSAO", "sigilo")])
    return _fechar(t, item, dados)


def a1_02(item, dados: DadosRelatorio, fontes: Fontes) -> Documento:
    t = _tela(fontes)
    n = len(dados.pendencias)
    resumo = _resumo(dados)
    tab_ag = resumo["POR ATIVIDADE GERADORA"]
    por_ag, crit_ag = _coluna(tab_ag), _coluna(tab_ag, analise.CRITICAS)
    tab_mp = resumo["POR MOTIVO DA PERMANENCIA"]
    por_mp, fora_mp = _coluna(tab_mp), _coluna(tab_mp, analise.PERCENTUAL_FORA_DA_PREVISAO)
    por_resp = _coluna(resumo["POR RESPONSABILIDADE FINANCEIRA"])

    y = _capa(t, item, dados, _casos(n, "ativos"))
    ordem_ag = sorted(por_ag, key=lambda a: (-(por_ag[a] if not _suprimido(por_ag[a]) else -1), a))
    ag_top, n_ag = _maior_visivel(por_ag)
    mp_top, n_mp = _maior_visivel(por_mp)
    top3 = [por_ag[a] for a in ordem_ag[:3]]
    publico = por_resp.get(regras.PUBLICO, 0)
    fisc = por_resp.get(regras.FISCALIZACAO, 0)
    proporcao = {a: crit_ag[a] / por_ag[a] for a in por_ag
                 if not _suprimido(por_ag[a]) and not _suprimido(crit_ag.get(a)) and por_ag[a] >= 10}
    ag_grave = max(proporcao, key=proporcao.get) if proporcao else None
    achados = [
        f"**{_rot_atividade(ag_top)}** é a maior origem: **{_pct(n_ag, n)}** dos casos ativos "
        f"({formatos.inteiro(n_ag)})." if n_ag else "Nenhum caso ativo.",
        f"As **3 atividades** com mais casos somam **{_pct(sum(top3), n)}** do total." if len(top3) == 3 and not any(
            map(_suprimido, top3)) else "",
        f"O motivo mais comum é **{_rot_motivo(mp_top).lower()}**: {formatos.inteiro(n_mp)} casos "
        f"({_pct(n_mp, n)})." if n_mp else "",
        (f"**{_pct(publico, n)}** dos casos dependem do orçamento público (não há a quem cobrar) e "
         f"**{_pct(fisc, n)}** são cargas sem comprovante de destino.")
        if not (_suprimido(publico) or _suprimido(fisc)) and n else "",
        f"Em **{_rot_atividade(ag_grave).lower()}**, {formatos.percentual(100 * proporcao[ag_grave])} dos casos estão "
        "na faixa de risco crítico, a maior proporção entre as atividades com 10 casos ou mais." if ag_grave else "",
    ]
    y = _sumario(t, y, achados, COR_NIVEL[1])
    y = _kpis(t, y, [
        Kpi("Maior origem", _pct(n_ag, n) or "-", f"{_rot_atividade(ag_top)} · {_casos(n_ag)}" if n_ag else ""),
        Kpi("Motivo mais comum", _pct(n_mp, n) or "-", f"{_rot_motivo(mp_top)} · {_casos(n_mp)}" if n_mp else ""),
        Kpi("Dependem do orçamento público", _qtd(publico), f"{_pct(publico, n)} dos casos ativos" if _pct(publico, n)
            else ""),
        Kpi(_rot_motivo("MP-08"), _qtd(fisc), f"{_pct(fisc, n)} dos casos ativos" if _pct(fisc, n) else "")])

    y = _secao(t, y, 1, "De onde vêm os casos",
               "Que atividades econômicas originaram os casos ativos, e quais deixam os casos mais graves?")
    y = _subtitulo(t, MARGEM, y, "Casos ativos por atividade de origem",
                   nota="Barra: casos e % do total. À direita: parte dos casos da atividade na faixa de risco crítico.")
    y = _barras(t, MARGEM, y, UTIL, [(_rot_atividade(a), por_ag[a]) for a in ordem_ag], total=n, largura_rotulo=300,
                extras=[_pct(crit_ag.get(a), por_ag[a]) or "-" for a in ordem_ag], titulo_extra="% de risco crítico")

    y = _secao(t, y + 4, 2, "Por que continuam abertos",
               "O que impede a solução, agrupado pelo tipo de providência que resolve cada grupo?")
    y = _subtitulo(t, MARGEM, y, "Casos ativos por motivo da permanência",
                   nota="Os motivos agrupados por quem paga a solução. À direita: parte dos casos com o prazo previsto "
                        "vencido.")
    visiveis_mp = [v for v in por_mp.values() if not _suprimido(v)]
    maximo = max(visiveis_mp, default=0)
    grupos = sorted(GRUPOS_MOTIVO, key=lambda g: -(por_resp.get(regras.RESPONSABILIDADE_GRUPO[g], 0)
                                                   if not _suprimido(por_resp.get(regras.RESPONSABILIDADE_GRUPO[g], 0))
                                                   else -1))
    _direita(t, LARGURA - MARGEM, y, "% com prazo vencido", T_NOTA, negrito=True, cor=CINZA)
    y += 20
    for g in grupos:
        resp = regras.RESPONSABILIDADE_GRUPO[g]
        total_g = por_resp.get(resp, 0)
        t.retangulo(MARGEM, y, LARGURA - MARGEM, y + 30, preenchimento=FUNDO_GRUPO)
        t.texto(MARGEM + 8, y + 6, _rot_resp(resp), 13, negrito=True)
        texto_total = _valor_e_pct(total_g, n)
        x_total = MARGEM + 8 + _largura_texto(t, _rot_resp(resp), 13, True) + 14
        t.texto(x_total, y + 6, texto_total, 13)
        _direita(t, LARGURA - MARGEM - 8, y + 7, f"providência: {ACAO_GRUPO[g]}", T_NOTA, cor=CINZA)
        y += 38
        codigos = sorted((c for c in GRUPOS_MOTIVO[g] if c in por_mp),
                         key=lambda c: -(por_mp[c] if not _suprimido(por_mp[c]) else -1))
        y = _barras(t, MARGEM + 16, y, UTIL - 16, [(_rot_motivo(c), por_mp[c]) for c in codigos], total=n,
                    largura_rotulo=300, maximo=maximo,
                    extras=["-" if _suprimido(fora_mp.get(c)) else formatos.percentual(fora_mp[c]) for c in codigos])
    y = _nota(t, y + 4, "Como ler", [
        f"{_rot_resp(regras.COBRAVEL)}: {vocabulario.definicao(regras.COBRAVEL, 'responsabilidade')}",
        f"{_rot_resp(regras.PUBLICO)}: {vocabulario.definicao(regras.PUBLICO, 'responsabilidade')}",
        f"{_rot_resp(regras.INFRAESTRUTURA)}: {vocabulario.definicao(regras.INFRAESTRUTURA, 'responsabilidade')}",
        f"{_rot_resp(regras.FISCALIZACAO)}: {vocabulario.definicao(regras.FISCALIZACAO, 'responsabilidade')}",
        "Nível 1: apenas totais, os mesmos do Resumo agregado. " + vocabulario.definicao("SUPRESSAO", "sigilo")])
    return _fechar(t, item, dados)


def a1_05(item, dados: DadosRelatorio, fontes: Fontes) -> Documento:
    t = _tela(fontes)
    ps, hoje = dados.pendencias, dados.hoje
    n = len(ps)
    resumo = _resumo(dados)
    por_uf = _coluna(resumo["POR UF"])                   # o mesmo por UF do resumo (k = 3 no N1)
    por_regiao = _coluna(resumo["POR REGIAO"])
    uf_escopo = _uf_do_escopo(dados) if dados.nivel == 2 else None
    criticas = sum(categoria(p, hoje) == "CRITICO" for p in ps) if dados.nivel >= 2 else None

    y = _capa(t, item, dados, _casos(n, "ativos"))
    visiveis = sorted(((uf, v) for uf, v in por_uf.items() if not _suprimido(v)), key=lambda kv: (-kv[1], kv[0]))
    escondidas = [uf for uf, v in por_uf.items() if _suprimido(v)]
    if uf_escopo:
        por_mun = Counter(p.municipio for p in ps)
        ordem_mun = sorted(por_mun.items(), key=lambda kv: (-kv[1], kv[0]))
        mun_top, n_mun = ordem_mun[0] if ordem_mun else ("-", 0)
        achados = [
            f"**{_casos(n, 'ativos')}** em **{formatos.inteiro(len(por_mun))} municípios** da UF {uf_escopo}.",
            f"**{mun_top}** concentra **{_pct(n_mun, n)}** dos casos ({formatos.inteiro(n_mun)})." if n_mun else "",
            f"Os 3 municípios com mais casos somam **{_pct(sum(v for _, v in ordem_mun[:3]), n)}** do total da UF."
            if len(ordem_mun) >= 3 else "",
            f"**{_pct(criticas, n)}** dos casos ({formatos.inteiro(criticas)}) estão na faixa de risco crítico."
            if n else "",
        ]
    else:
        top5 = visiveis[:5]
        reg_top, n_reg = _maior_visivel(por_regiao)
        acima = [c for c in sinteticos.CUSTODIAS if c.ocupacao > 0.9]
        achados = [
            f"Os **5 estados** com mais casos ({', '.join(uf for uf, _ in top5)}) concentram "
            f"**{_pct(sum(v for _, v in top5), n)}** dos casos ativos." if len(top5) == 5 else "",
            f"**{NOME_REGIAO.get(reg_top, reg_top)}** é a região com mais casos: **{_pct(n_reg, n)}** "
            f"({formatos.inteiro(n_reg)})." if n_reg else "",
            f"**{visiveis[0][0]}** tem {br(visiveis[0][1] / visiveis[-1][1])} vezes mais casos que **{visiveis[-1][0]}**, "
            "o estado com menos casos visíveis." if len(visiveis) >= 2 and visiveis[-1][1] else "",
            (f"**{len(escondidas)} estados** saem como SUPRIMIDO: menos de {dados.k} casos, ou escondidos para não "
             "serem deduzidos por subtração." if escondidas else
             f"Nenhum estado precisou de supressão: todos têm {dados.k} casos ou mais.") if dados.k else
            (f"**{len(acima)} das {len(sinteticos.CUSTODIAS)} instalações de custódia** estão acima de 90% da "
             "capacidade." if dados.nivel >= 3 else ""),
        ]
    y = _sumario(t, y, achados, COR_NIVEL[1])

    pergunta = ("Em que municípios da UF estão os casos, e onde estão os mais graves?" if uf_escopo else
                "Em que estados os casos se concentram?" if dados.nivel <= 1 else
                "Onde estão os casos no país, quão graves são e onde ficam as instalações de custódia?")
    y = _secao(t, y, 1, "Distribuição geográfica", pergunta)
    largura_mapa, altura_mapa = 540, 528
    mapa = (Mapa.da_uf(uf_escopo, MARGEM, y, largura_mapa, altura_mapa) if uf_escopo
            else Mapa(MARGEM, y, largura_mapa, altura_mapa))
    if dados.nivel <= 1:
        legenda = _mapa_coropletico(t, mapa, por_uf)
    else:
        mapa.desenhar_ufs(t, {uf_escopo: (238, 243, 238)} if uf_escopo else {}, padrao=(238, 243, 238)
                          if not uf_escopo else (246, 247, 248), contorno=(150, 160, 150))
        _pontos(t, dados, mapa)
        # a área inteira do mapa é sensível: a informação está na posição, não no texto
        t.marcar(*mapa.caixa, "DISTRIBUICAO_GEOGRAFICA", 2)
        if dados.nivel >= 3:                     # abaixo do N3: omitidas, não suprimidas (ver topo)
            _custodias(t, mapa)
    t.retangulo(mapa.x0, mapa.y0, mapa.x0 + mapa.largura, mapa.y0 + mapa.altura, contorno=FILETE)
    # coluna da direita: a lista ordenada (o número exato de cada estado ou município)
    x = MARGEM + largura_mapa + 28
    largura_lista = LARGURA - MARGEM - x
    if uf_escopo:
        yy = _subtitulo(t, x, y, "Casos por município", largura_lista,
                        nota=f"Os {min(16, len(ordem_mun))} com mais casos, de {formatos.inteiro(len(ordem_mun))}.")
        yy = _barras(t, x, yy, largura_lista, ordem_mun[:16], total=n, largura_rotulo=130, tamanho=11)
    else:
        yy = _subtitulo(t, x, y, "Casos por estado", largura_lista, nota="Casos ativos e % do total.")
        ordem = visiveis + [(uf, por_uf[uf]) for uf in sorted(escondidas)]
        yy = _barras(t, x, yy, largura_lista, ordem, total=n, largura_rotulo=34, tamanho=11)
    y = mapa.y0 + mapa.altura + 14
    if dados.nivel <= 1:
        y = _legenda(t, MARGEM, y, largura_mapa, legenda, "Casos ativos por estado")
    else:
        itens = [(_rot_faixa(f), COR_CATEGORIA[f]) for f in reversed(CATEGORIAS)]
        y = _legenda(t, MARGEM, y, largura_mapa, itens, "Cada ponto é um caso, na cor da faixa de risco", "ponto")
        if dados.nivel >= 3:
            t.texto(MARGEM, y, "Instalações de custódia de material radioativo (número no mapa) e ocupação", T_NOTA,
                    negrito=True, cor=CINZA)
            y = _lista_custodias(t, MARGEM, y + 20, largura_mapa, barras=False)
    y = max(y, yy) + 8
    y = _nota(t, y, "Como ler", [
        "Só o total de cada estado: nenhum ponto é desenhado, e as instalações de custódia não aparecem (a posição "
        "é o segredo).",
        ("Cores do mapa: 5 classes de casos por estado (quantis), do mais claro (menos casos) ao mais escuro. "
         + vocabulario.definicao("SUPRIMIDO", "sigilo")) if dados.nivel <= 1 else "",
        "Contorno e divisas: malha do IBGE (qualidade mínima), projeção simples, sem pretensão cartográfica."])
    return _fechar(t, item, dados)


# ================================================================ N2: decisão e ação na UF
def _responsaveis(dados: DadosRelatorio, codigo: str) -> tuple[Responsavel, ...]:
    return tuple((dados.responsaveis or {}).get(codigo, ()))


def _anos(dias: float) -> str:
    return formatos.anos(dias)


def _campos(t: Tela, x: int, y: int, largura: int, campos: list, colunas: int = 3, medir=False) -> int:
    """Grade de campos da ficha: rótulo pequeno em cinza sobre o valor. `campos` = [(rótulo, valor, sensível ou
    None)]. A altura de cada linha é medida antes de desenhar (nada se sobrepõe)."""
    largura_col = (largura - (colunas - 1) * 20) // colunas
    y0 = y
    for i in range(0, len(campos), colunas):
        linha = campos[i:i + colunas]
        h = max(16 + _medir(t, v, T_TABELA, largura_col) for _, v, _ in linha)
        if not medir:
            for j, (rotulo, valor, sensivel) in enumerate(linha):
                xx = x + j * (largura_col + 20)
                t.texto(xx, y, rotulo, 10, negrito=True, cor=CINZA)
                t.texto(xx, y + 15, valor, T_TABELA, largura_max=largura_col, sensivel=sensivel)
        y += h + 8
    return y - y0


def _ficha(t: Tela, y: int, p: Pendencia, dados: DadosRelatorio, medir=False) -> int:
    """Ficha compacta e escaneável de um caso: cabeçalho (faixa, código, substância, score), linha de identificação e
    a grade de campos. Os mesmos atributos da ficha da tela."""
    hoje, r = dados.hoje, dados.parametros
    faixa = categoria(p, hoje)
    largura_interna = UTIL - 40
    atraso = p.dias_de_atraso(hoje)
    limite = regras.prazo_limite(p, r)
    alem = regras.dias_alem_do_prazo_limite(p, hoje, r)
    ct = ficha.contaminante(p)
    mp = dados.motivos.get(p.motivo)
    campos = [
        ("Endereço", p.endereco, ("ENDERECO", 2)),
        ("Coordenadas", f"{p.latitude:.5f}, {p.longitude:.5f}", ("COORDENADA", 2)),
        ("Atividade de origem", _rot_atividade(p.atividade), None),
        ("Prazo previsto", f"{p.prazo_coleta:%d/%m/%Y}" + (f" · vencido há {_anos(atraso)}" if atraso else " · em dia"),
         None),
        ("Prazo legal da classe", f"{limite:%d/%m/%Y}" + (f" · estourado há {_anos(alem)}" if alem else " · em dia"),
         None),
        ("Custo estimado", f"{formatos.custo_caso(regras.custo_estimado(p, r))} · quem paga: "
                           f"{_rot_resp(regras.responsabilidade(p)).lower()}", None),
        ("Fase", fase.rotulo(fase.fase(p)), None),
        ("Contaminante", f"{ct.grupo} ({ct.meio})", None),
        ("Restrição de uso", ficha.restricao(p), None),
        ("Motivo da permanência", _rot_motivo(p.motivo) + (f" · base legal: {mp.base_legal}" if mp is not None
                                                            else ""), None),
        ("Uso anterior", ficha.uso_anterior(p), None),
        ("Uso pretendido", ficha.uso_pretendido(p), None),
    ]
    responsaveis = _responsaveis(dados, p.codigo)
    h_campos = _campos(t, 0, 0, largura_interna, campos, medir=True)
    h_resp = 16 + 18 * max(1, len(responsaveis))
    altura = 14 + 26 + 22 + 12 + h_campos + h_resp + 10
    if medir:
        return altura
    t.retangulo(MARGEM, y, LARGURA - MARGEM, y + altura, contorno=FILETE, raio=6)
    t.retangulo(MARGEM, y, MARGEM + 5, y + altura, preenchimento=COR_CATEGORIA[faixa])
    x = MARGEM + 20
    w = _selo_faixa(t, x, y + 14, faixa)
    t.texto(x + w + 10, y + 12, _cabe(t, f"{p.codigo} · {p.substancia}", largura_interna - w - 150, 15, True), 15,
            negrito=True)
    _direita(t, LARGURA - MARGEM - 18, y + 14, f"score {br(criticidade(p, hoje))}", 13, negrito=True)
    t.texto(x, y + 40, f"{_rot_classe(p.classe_risco)} · {formatos.quantidade(p.quantidade, p.classe_risco)} · "
                       f"{vocabulario.rotulo(p.situacao, 'situacao_caso')} · {p.municipio}/{p.uf} · identificado "
                       f"em {p.data_identificacao:%d/%m/%Y}", 12, cor=CINZA)
    yy = y + 14 + 26 + 22 + 6
    t.linha(x, yy - 4, LARGURA - MARGEM - 18, yy - 4, cor=FILETE)
    yy += _campos(t, x, yy + 4, largura_interna, campos) + 4
    t.texto(x, yy, "Responsáveis", 10, negrito=True, cor=CINZA)
    yy += 16
    if not responsaveis:
        t.texto(x, yy, "nenhum identificado", T_TABELA, cor=CINZA)
    for resp in responsaveis:
        # nível mínimo por responsável: pessoa física só aparece para a custódia (N3)
        t.texto(x, yy, f"{VINCULOS.get(resp.vinculo, resp.vinculo)}: {resp.nome} · cadastro "
                       f"{(resp.situacao_cadastral or '-').lower()}", T_TABELA, sensivel=("RESPONSAVEL", resp.nivel_minimo))
        yy += 18
    return altura


def a2_01(item, dados: DadosRelatorio, fontes: Fontes) -> Documento:
    maximo = 6
    hoje, r = dados.hoje, dados.parametros
    ps = sorted(dados.pendencias, key=lambda p: criticidade(p, hoje), reverse=True)
    n = len(ps)
    t = _tela(fontes, 9000)
    y = _capa(t, item, dados, _casos(n, "ativos"))
    criticas = sum(categoria(p, hoje) == "CRITICO" for p in ps)
    alem = [regras.dias_alem_do_prazo_limite(p, hoje, r) for p in ps]
    acoes = Counter(regras.acao_recomendada(p, hoje, r) for p in ps)
    custo_total = sum(regras.custo_estimado(p, r) for p in ps)
    prioritarios = ps[:maximo]
    custo_prio = sum(regras.custo_estimado(p, r) for p in prioritarios)
    acao_top, n_acao = acoes.most_common(1)[0] if acoes else ("-", 0)
    n_alem, n_mp = sum(a > 0 for a in alem), acoes.get(regras.ESCALAR_MP, 0)
    local = _local(dados)
    achados = [
        f"{local[0].upper()}{local[1:]} tem **{_casos(n, 'ativos')}**; **{formatos.inteiro(criticas)} "
        f"({_pct(criticas, n)})** estão na faixa de risco crítico." if n else "Nenhum caso ativo no escopo.",
        f"**{_plural(n_alem, 'caso', 'casos')}** {_verbo(n_alem, 'já passou', 'já passaram')} do prazo legal da "
        f"classe; o maior estouro é de **{_anos(max(alem))}**." if any(alem) else "",
        f"A providência mais frequente é **{_rot_acao(acao_top).lower()}** ({_casos(n_acao)})"
        + (f"; **{_plural(n_mp, 'caso cobrável', 'casos cobráveis')}** "
           f"{_verbo(n_mp, 'já esgotou', 'já esgotaram')} a via administrativa e "
           f"{_verbo(n_mp, 'deve', 'devem')} ir ao Ministério Público." if n_mp else ".") if n else "",
        f"Custo estimado para resolver os casos ativos: **{formatos.custo(custo_total)}**; os {len(prioritarios)} "
        f"prioritários desta ficha somam **{formatos.custo(custo_prio)}**." if n else "",
    ]
    y = _sumario(t, y, achados, COR_NIVEL[2])
    y = _kpis(t, y, [
        Kpi("Casos ativos", formatos.inteiro(n), f"no escopo {dados.escopo}"),
        Kpi("Casos de risco crítico", formatos.inteiro(criticas), f"{_pct(criticas, n)} dos casos ativos"),
        Kpi(vocabulario.rotulo("KPI-03", "kpi"), formatos.inteiro(sum(a > 0 for a in alem)),
            f"{_pct(sum(a > 0 for a in alem), n)} dos casos ativos"),
        Kpi(vocabulario.rotulo("KPI-05", "kpi"), formatos.custo(custo_total), "soma dos casos ativos")])

    # 1. fila de ação
    y = _secao(t, y, 1, "Fila de ação", "Que providência cada grupo de casos exige agora, e quanto ela custa?")
    linhas = []
    for a in regras.ACOES:
        do_grupo = [p for p in ps if regras.acao_recomendada(p, hoje, r) == a]
        if not do_grupo:
            continue
        linhas.append([_rot_acao(a), len(do_grupo), sum(categoria(p, hoje) == "CRITICO" for p in do_grupo),
                       sum(regras.dias_alem_do_prazo_limite(p, hoje, r) > 0 for p in do_grupo),
                       formatos.custo(sum(regras.custo_estimado(p, r) for p in do_grupo))])
    y = _tabela(t, y, [("Ação recomendada (da mais grave à mais branda)", 380), ("Casos", 110), ("Risco crítico", 120),
                       ("Além do prazo legal", 130), ("Custo estimado", 148, "d")], linhas, negrito_col0=True,
                total=["Total", n, criticas, sum(a > 0 for a in alem), formatos.custo(custo_total)] if linhas else None)

    # 2. fichas agrupadas pela ação
    y = _secao(t, y + 4, 2, f"Os {len(prioritarios)} casos prioritários" if prioritarios else "Casos prioritários",
               "Quais casos tratar primeiro, onde estão e quem responde por eles? Ordem: score de risco, do maior "
               "para o menor, agrupados pela ação recomendada.")
    grupos: dict[str, list] = {}
    for p in prioritarios:
        grupos.setdefault(regras.acao_recomendada(p, hoje, r), []).append(p)
    for a in sorted(grupos, key=regras.ACOES.index):
        t.texto(MARGEM, y, f"{_rot_acao(a)}  ·  {_casos(len(grupos[a]))}", 14, negrito=True)
        y += 22
        y += t.texto(MARGEM, y, vocabulario.definicao(a, "acao"), 12, cor=CINZA, largura_max=UTIL) + 10
        for p in grupos[a]:
            y += _ficha(t, y, p, dados) + 14
        y += 6
    if not ps:
        t.texto(MARGEM, y, "Nenhum caso ativo neste escopo.", 15, cor=CINZA)
        y += 30

    # 3. próximos da fila
    proximos = ps[maximo:maximo + 10]
    if proximos:
        y = _secao(t, y, 3, "Próximos da fila", f"Os casos de {maximo + 1}º a {maximo + len(proximos)}º pelo score de "
                                                f"risco, para planejar a etapa seguinte.")
        linhas = [[f"{i}", p.codigo, f"{p.municipio}", _rot_classe(p.classe_risco), Faixa(categoria(p, hoje)),
                   criticidade(p, hoje), _rot_acao(regras.acao_recomendada(p, hoje, r)),
                   (f"há {_anos(regras.dias_alem_do_prazo_limite(p, hoje, r))}"
                    if regras.dias_alem_do_prazo_limite(p, hoje, r) else "em dia")]
                  for i, p in enumerate(proximos, maximo + 1)]
        y = _tabela(t, y, [("Nº", 40), ("Código", 80), ("Município", 140), ("Classe", 140), ("Faixa", 84),
                           ("Score", 70), ("Ação recomendada", 200), ("Prazo legal estourado", 134, "d")], linhas)
        if n > maximo + len(proximos):
            t.texto(MARGEM, y, f"Mais {_casos(n - maximo - len(proximos))} no escopo: a lista completa, com busca e "
                               "filtros, está no Painel analítico (aba Planilha).", 12, cor=CINZA, largura_max=UTIL)
            y += 26
    y = _nota(t, y + 4, "Como ler", [
        vocabulario.definicao("SCORE", "risco"),
        f"Prazo previsto: {vocabulario.definicao('PRAZO_COLETA', 'prazo')} Prazo legal: "
        f"{vocabulario.definicao('PRAZO_LIMITE', 'prazo')}"])
    return _fechar(t, item, dados)


FAIXAS_ATRASO = ((0, 1, "menos de 1"), (1, 3, "1 a 3"), (3, 5, "3 a 5"), (5, 10, "5 a 10"), (10, 20, "10 a 20"),
                 (20, float("inf"), "20 ou mais"))


def a2_02(item, dados: DadosRelatorio, fontes: Fontes) -> Documento:
    hoje, r = dados.hoje, dados.parametros
    n = len(dados.pendencias)
    vencidas = sorted((p for p in dados.pendencias if p.vencida(hoje)), key=lambda p: p.dias_de_atraso(hoje),
                      reverse=True)
    nv = len(vencidas)
    t = _tela(fontes, 9000)
    y = _capa(t, item, dados, _casos(n, "ativos"))
    criticas = sum(categoria(p, hoje) == "CRITICO" for p in vencidas)
    anos_atraso = [p.dias_de_atraso(hoje) / formatos.DIAS_POR_ANO for p in vencidas]
    mais_10 = sum(a >= 10 for a in anos_atraso)
    por_motivo = Counter(p.motivo for p in vencidas).most_common(1)
    acoes = Counter(regras.acao_recomendada(p, hoje, r) for p in vencidas)
    n_mp = acoes.get(regras.ESCALAR_MP, 0)
    achados = [
        f"**{formatos.inteiro(nv)} dos {formatos.inteiro(n)} casos ativos ({_pct(nv, n)})** já passaram do prazo "
        "previsto." if n else "Nenhum caso ativo no escopo.",
        f"O atraso médio é de **{_atraso_medio(vencidas, hoje)}**; **{_pct(mais_10, nv)}** estão vencidos há 10 anos "
        "ou mais." if nv else "",
        f"**{_plural(criticas, 'caso vencido', 'casos vencidos')}** "
        f"{_verbo(criticas, 'está', 'estão')} na faixa de risco crítico: "
        f"{_verbo(criticas, 'comece por ele', 'comece por eles')} (seção 3)." if criticas else "",
        f"O motivo que mais segura os vencidos é **{_rot_motivo(por_motivo[0][0]).lower()}** "
        f"({_casos(por_motivo[0][1])})." if por_motivo else "",
        f"**{_plural(n_mp, 'caso', 'casos')}** {_verbo(n_mp, 'já esgotou', 'já esgotaram')} a cobrança "
        f"administrativa e {_verbo(n_mp, 'deve', 'devem')} ir ao Ministério Público."
        if n_mp else "",
    ]
    y = _sumario(t, y, achados, COR_NIVEL[2])
    y = _kpis(t, y, [
        Kpi(vocabulario.rotulo("KPI-03b", "kpi"), formatos.inteiro(nv), f"{_pct(nv, n)} dos {_casos(n, 'ativos')}"),
        Kpi("Atraso médio", _atraso_medio(vencidas, hoje), "desde o prazo previsto, entre os vencidos"),
        Kpi("Maior atraso", _anos(vencidas[0].dias_de_atraso(hoje)) if vencidas else "-",
            vencidas[0].codigo if vencidas else ""),
        Kpi("Vencidos de risco crítico", formatos.inteiro(criticas), f"{_pct(criticas, nv)} dos vencidos" if nv
            else "")])

    y = _secao(t, y, 1, "Há quanto tempo estão vencidos", "O atraso é recente ou acumulado há anos?")
    y = _colunas(t, MARGEM + 40, y + 6, UTIL - 80, 170,
                 [(rotulo, sum(de <= a < ate for a in anos_atraso)) for de, ate, rotulo in FAIXAS_ATRASO], total=nv,
                 legenda_eixo="anos de atraso desde o prazo previsto")

    y = _secao(t, y + 4, 2, "O que fazer com cada grupo", "Que providência os vencidos exigem, quantos são e qual o "
                                                          "atraso de cada grupo?")
    linhas = []
    for a in regras.ACOES:
        grupo = [p for p in vencidas if regras.acao_recomendada(p, hoje, r) == a]
        if grupo:
            linhas.append([_rot_acao(a), len(grupo), sum(categoria(p, hoje) == "CRITICO" for p in grupo),
                           _atraso_medio(grupo, hoje), _anos(max(p.dias_de_atraso(hoje) for p in grupo)),
                           formatos.custo(sum(regras.custo_estimado(p, r) for p in grupo))])
    y = _tabela(t, y, [("Ação recomendada", 300), ("Casos", 90), ("Risco crítico", 110), ("Atraso médio", 120, "d"),
                       ("Maior atraso", 120, "d"), ("Custo estimado", 148, "d")], linhas, negrito_col0=True)

    y = _secao(t, y + 4, 3, "Lista dos vencidos por faixa de risco",
               "Quais casos cobrar primeiro? Em cada faixa, do maior para o menor atraso (até 10 por faixa).")
    por_faixa = {f: [p for p in vencidas if categoria(p, hoje) == f] for f in reversed(CATEGORIAS)}
    linhas = []
    restantes = 0
    for f, grupo in por_faixa.items():
        if not grupo:
            continue
        linhas.append(Grupo(f"{_casos(len(grupo))} vencidos", f))
        for p in grupo[:10]:
            linhas.append([p.codigo, p.municipio, p.substancia, _rot_classe(p.classe_risco),
                           _anos(p.dias_de_atraso(hoje)), _rot_motivo(p.motivo),
                           _rot_acao(regras.acao_recomendada(p, hoje, r))])
        restantes += max(0, len(grupo) - 10)
    y = _tabela(t, y, [("Código", 66), ("Município", 112), ("Substância", 168), ("Classe", 112),
                       ("Atraso", 74, "d"), ("Motivo da permanência", 176), ("Ação recomendada", 180)], linhas,
                tamanho=11)
    if restantes:
        t.texto(MARGEM, y, f"Mais {_casos(restantes)} vencidos não listados: a lista completa está no Painel "
                           "analítico (aba Planilha, filtro de prazo vencido).", 12, cor=CINZA, largura_max=UTIL)
        y += 26
    if not vencidas:
        t.texto(MARGEM, y, "Nenhum caso com o prazo previsto vencido neste escopo.", 15, cor=CINZA)
        y += 30
    y = _nota(t, y + 4, "Como ler", [
        f"Prazo previsto vencido: {vocabulario.definicao('VENCIDO', 'prazo')} O atraso é contado desde essa data.",
        "Faixa de risco: baixo, médio, alto ou crítico, conforme o score de risco na data de corte. Sem solução, "
        "o atraso cresce e a faixa sobe.",
        f"{_rot_acao(regras.ESCALAR_MP)}: {vocabulario.definicao(regras.ESCALAR_MP, 'acao')}"])
    return _fechar(t, item, dados)


def numero_manifesto(p: Pendencia) -> str:
    """Nº do MTR (Manifesto de Transporte de Resíduos, SINIR) da carga: ano de emissão, UF e sequência."""
    return f"{p.data_identificacao.year}{p.uf}{(int(p.codigo[3:]) * 7919) % 1_000_000:06d}"


def _cadeia(t: Tela, x: int, y: int, cadeia: dict, largura: int) -> int:
    """As três etapas do manifesto lado a lado; a etapa rompida (destinador, sem baixa) em destaque."""
    etapas = (("GERADOR_ORIGINAL", "1. Gerador emitiu o manifesto", "concluída"),
              ("TRANSPORTADOR", "2. Transportador retirou e levou", "declarada"),
              ("DESTINADOR", "3. Destinador recebe e dá baixa", "sem baixa"))
    seta = 26
    w = (largura - 2 * seta) // 3
    for i, (vinculo, etapa, estado) in enumerate(etapas):
        xx = x + i * (w + seta)
        rompida = vinculo == "DESTINADOR"
        t.retangulo(xx, y, xx + w, y + ALTURA_ETAPA, preenchimento=(253, 242, 243) if rompida else FUNDO_SUAVE,
                    contorno=COR_CATEGORIA["CRITICO"] if rompida else FILETE, espessura=2 if rompida else 1, raio=5)
        t.texto(xx + 10, y + 7, etapa, 11, negrito=True, cor=TINTA if rompida else CINZA)
        resp = cadeia.get(vinculo)
        nome = resp.nome if resp else "(não identificado)"
        linhas_nome = t._quebrar(nome, t.fonte(12), w - 20)
        if len(linhas_nome) > 2:
            nome = " ".join(linhas_nome[:1]) + " " + _cabe(t, " ".join(linhas_nome[1:]), w - 20, 12)
        t.texto(xx + 10, y + 26, nome, 12, largura_max=w - 20,
                sensivel=("RESPONSAVEL", resp.nivel_minimo) if resp else None)
        situacao = (resp.situacao_cadastral or "-") if resp else "-"
        alerta = situacao in ("SUSPENSA", "FALIDA")
        t.texto(xx + 10, y + 64, f"cadastro {situacao.lower()}", 11, negrito=alerta)
        t.texto(xx + 10, y + 80, f"etapa {estado}", 11, negrito=rompida)
        if i < 2:
            _centro(t, xx + w + seta / 2, y + 28, "→", 18, negrito=True, cor=CINZA)
    return y + ALTURA_ETAPA


ALTURA_ETAPA = 100


def a2_04(item, dados: DadosRelatorio, fontes: Fontes) -> Documento:
    hoje = dados.hoje
    sem_baixa = sorted((p for p in dados.pendencias if p.motivo == "MP-08"), key=lambda p: p.data_identificacao)
    mostradas = sem_baixa[:10]
    t = _tela(fontes, 9000)
    y = _capa(t, item, dados, _plural(len(sem_baixa), "carga sem baixa", "cargas sem baixa"))
    suspensos = sum(1 for p in sem_baixa for r in _responsaveis(dados, p.codigo)
                    if r.vinculo == "DESTINADOR" and r.situacao_cadastral == "SUSPENSA")
    dias = [(hoje - p.data_identificacao).days for p in sem_baixa]
    quantidades_txt = " · ".join(formatos.quantidade(_volume(sem_baixa, c), c) for c in quantidades.CLASSES
                                 if _volume(sem_baixa, c)) or "0 t"
    if sem_baixa:
        achados = [
            f"**{_plural(len(sem_baixa), 'carga', 'cargas')}** "
            + ("saiu com manifesto e não teve" if len(sem_baixa) == 1 else "saíram com manifesto e não tiveram")
            + " a chegada confirmada (sem baixa do destinador).",
            f"A mais antiga está sem baixa há **{_anos(max(dias))}** ({formatos.inteiro(max(dias))} dias); a média é "
            f"de {_anos(sum(dias) / len(dias))}." if len(dias) > 1 else
            f"A carga está sem baixa há **{_anos(max(dias))}** ({formatos.inteiro(max(dias))} dias).",
            (f"**{_plural(suspensos, 'destinador', 'destinadores')}** com cadastro suspenso "
             + ("aparece como recebedor: é o primeiro a notificar." if suspensos == 1 else
                "aparecem como recebedores: são os primeiros a notificar.")) if suspensos else "Nenhum destinador com cadastro suspenso entre as cargas.",
            f"Quantidade sem destino confirmado: **{quantidades_txt}**.",
        ]
    else:
        achados = [f"Nenhuma carga com manifesto sem baixa n{_local(dados)}.",
                   "Não há etapa rompida a rastrear neste escopo.",
                   "O relatório volta a listar as cargas assim que surgir um manifesto sem baixa."]
    y = _sumario(t, y, achados, COR_NIVEL[2])
    y = _kpis(t, y, [
        Kpi(_rot_motivo("MP-08"), formatos.inteiro(len(sem_baixa)), f"de {_casos(len(dados.pendencias), 'ativos')}"),
        Kpi("Quantidade sem destino confirmado", quantidades_txt, "por classe, sem somar unidades"),
        Kpi("Tempo médio sem baixa", _anos(sum(dias) / len(dias)) if dias else "-", "desde a emissão do manifesto"),
        Kpi("Destinadores com cadastro suspenso", formatos.inteiro(suspensos), "não podiam receber a carga")])

    y = _secao(t, y, 1, "Como funciona o rastreio", "Onde a cadeia do manifesto se rompe?")
    y += t.texto(MARGEM, y, "O Manifesto de Transporte de Resíduos (MTR, SINIR) acompanha a carga: o gerador emite, o "
                            "transportador leva e o destinador dá a baixa ao receber. Sem a baixa, ninguém confirma que "
                            "a carga chegou: a etapa 3 é a rompida em todas as cargas abaixo.", 12, cor=CINZA,
                 largura_max=UTIL) + 14

    y = _secao(t, y, 2, "Cargas a rastrear", "Quais cargas estão sem baixa, desde quando, e quem notificar? Da mais "
                                             "antiga para a mais recente.")
    for p in mostradas:
        cadeia = {r.vinculo: r for r in _responsaveis(dados, p.codigo)}
        dias_sem_baixa = (hoje - p.data_identificacao).days
        topo = y
        h_end = _medir(t, f"{p.endereco} · {p.municipio}/{p.uf}", 12, UTIL - 32 - 200)
        altura = 14 + 24 + 22 + 10 + ALTURA_ETAPA + 14 + 15 + max(h_end, 16) + 14
        t.retangulo(MARGEM, y, LARGURA - MARGEM, y + altura, contorno=FILETE, raio=6)
        x = MARGEM + 16
        w = _selo_faixa(t, x, y + 14, categoria(p, hoje))
        t.texto(x + w + 10, y + 12, f"MTR {numero_manifesto(p)}  ·  {p.codigo}", 15, negrito=True)
        alerta = f"{formatos.inteiro(dias_sem_baixa)} dias sem baixa ({_anos(dias_sem_baixa)})"
        largura_alerta = _largura_texto(t, alerta, 12, True) + 16
        t.retangulo(LARGURA - MARGEM - 16 - largura_alerta, y + 12, LARGURA - MARGEM - 16, y + 34,
                    preenchimento=TINTA, raio=4)
        t.texto(LARGURA - MARGEM - 8 - largura_alerta, y + 14, alerta, 12, negrito=True, cor=(255, 255, 255))
        t.texto(x, y + 40, f"{p.substancia} · {formatos.quantidade(p.quantidade, p.classe_risco)} · "
                           f"{_rot_classe(p.classe_risco)} · emitido em {p.data_identificacao:%d/%m/%Y}", 12,
                cor=CINZA)
        yy = _cadeia(t, x, y + 70, cadeia, UTIL - 32) + 12
        t.texto(x, yy, "Última posição conhecida (origem)", 10, negrito=True, cor=CINZA)
        t.texto(x, yy + 15, f"{p.endereco} · {p.municipio}/{p.uf}", 12, sensivel=("ENDERECO", 2),
                largura_max=UTIL - 32 - 200)
        t.texto(LARGURA - MARGEM - 16 - 180, yy, "Coordenadas", 10, negrito=True, cor=CINZA)
        t.texto(LARGURA - MARGEM - 16 - 180, yy + 15, f"{p.latitude:.5f}, {p.longitude:.5f}", 12,
                sensivel=("COORDENADA", 2))
        y = topo + altura + 14
    if len(sem_baixa) > len(mostradas):
        t.texto(MARGEM, y, f"Mais {formatos.inteiro(len(sem_baixa) - len(mostradas))} cargas sem baixa: Painel "
                           f"analítico, aba Planilha, motivo \"{_rot_motivo('MP-08')}\".", 12, cor=CINZA)
        y += 26
    if not sem_baixa:
        t.texto(MARGEM, y, "Nenhuma carga com manifesto sem baixa neste escopo.", 15, cor=CINZA)
        y += 34

    y = _secao(t, y + 4, 3, "Ação recomendada e prazos", "Quem agir, em que ordem e em quanto tempo?")
    passos = [
        ("Até 10 dias", "Notificar o destinador para apresentar o comprovante de recebimento e o transportador para "
                        "o comprovante de entrega. Destinador com cadastro suspenso primeiro."),
        ("Vencido o prazo", "Sem comprovante: autuação pela ausência de baixa (SINIR/MTR) de quem não a deu."),
        ("Em seguida", "Busca da carga a partir da última posição conhecida e da cadeia de transporte. "
         + vocabulario.definicao("AUTUAR E RASTREAR A CARGA", "acao")),
    ]
    for prazo, texto in passos:
        t.texto(MARGEM, y, prazo, 13, negrito=True)
        y += t.texto(MARGEM + 150, y, texto, 13, largura_max=UTIL - 150) + 10
    y = _nota(t, y + 6, "Como ler", [
        f"{_rot_motivo('MP-08')}: {vocabulario.definicao('MP-08', 'motivo')}",
        "Nº do MTR: ano de emissão, UF e sequência. Endereço, coordenadas e responsáveis seguem a proteção "
        "do nível de quem consulta."])
    return _fechar(t, item, dados)


# ================================================================ N3: precisão, agrupada por tema
def _custo(ps, dados: DadosRelatorio, responsabilidade: str) -> float:
    return sum(regras.custo_estimado(p, dados.parametros) for p in ps if regras.responsabilidade(p) == responsabilidade)


PARTES_DO_CUSTO = tuple((r, vocabulario.rotulo(r, "responsabilidade"))
                        for r in (regras.COBRAVEL, regras.PUBLICO, regras.INFRAESTRUTURA, regras.FISCALIZACAO))


def custos_por_responsabilidade(ps, dados: DadosRelatorio) -> tuple[float, list[tuple[str, float]]]:
    """(total, [(parte, custo)]): as quatro responsabilidades financeiras, que somam o total."""
    return (sum(regras.custo_estimado(p, dados.parametros) for p in ps),
            [(rotulo, _custo(ps, dados, resp)) for resp, rotulo in PARTES_DO_CUSTO])


def cartoes_de_custo(ps, dados: DadosRelatorio):
    """O total e as quatro partes, no formato único de custo agregado (o mesmo texto desenhado no A3-01)."""
    total, partes = custos_por_responsabilidade(ps, dados)
    return ((vocabulario.rotulo("KPI-05", "kpi"), formatos.custo(total)),
            [(rotulo, formatos.custo(valor)) for rotulo, valor in partes])


COR_RESPONSABILIDADE = {regras.COBRAVEL: (78, 121, 167), regras.PUBLICO: (225, 87, 89),
                        regras.INFRAESTRUTURA: (242, 142, 43), regras.FISCALIZACAO: (118, 183, 178)}


def a3_01(item, dados: DadosRelatorio, fontes: Fontes) -> Documento:
    t = _tela(fontes, 9000)
    ps, hoje, r = dados.pendencias, dados.hoje, dados.parametros
    n = len(ps)
    faixa = {p.codigo: categoria(p, hoje) for p in ps}
    vencidas = [p for p in ps if p.vencida(hoje)]
    alem = [p for p in ps if regras.dias_alem_do_prazo_limite(p, hoje, r) > 0]
    criticas = [p for p in ps if faixa[p.codigo] == "CRITICO"]
    mp08 = [p for p in ps if p.motivo == "MP-08"]
    por_uf = Counter(p.uf for p in ps)
    criticas_uf = Counter(p.uf for p in criticas)
    uf_top, n_uf = por_uf.most_common(1)[0] if ps else ("-", 0)
    uf_crit, n_crit = criticas_uf.most_common(1)[0] if criticas else ("-", 0)
    total_custo, partes = custos_por_responsabilidade(ps, dados)
    custo_publico = dict(partes).get(_rot_resp(regras.PUBLICO), 0.0)
    acima = [c for c in sinteticos.CUSTODIAS if c.ocupacao > 0.9]
    ano = timedelta(days=365)
    recentes = sum(hoje - ano < p.data_identificacao <= hoje for p in ps)
    anteriores = sum(hoje - 2 * ano < p.data_identificacao <= hoje - ano for p in ps)

    y = _capa(t, item, dados, _casos(n, "ativos"))
    achados = [
        f"O país tem **{_casos(n, 'ativos')}**: **{formatos.inteiro(len(criticas))} ({_pct(len(criticas), n)})** na "
        f"faixa de risco crítico e **{formatos.inteiro(len(vencidas))} ({_pct(len(vencidas), n)})** com o prazo "
        "previsto vencido.",
        f"**{uf_top}** concentra {_pct(n_uf, n)} dos casos; em casos críticos, o maior é **{uf_crit}**, com "
        f"**{formatos.inteiro(n_crit)}** ({_pct(n_crit, len(criticas))} dos críticos)." if ps else "",
        f"Custo estimado para resolver: **{formatos.custo(total_custo)}**; **{formatos.custo(custo_publico)} "
        f"({_pct(custo_publico, total_custo)})** recaem no orçamento público, porque não há a quem cobrar."
        if total_custo else "",
        f"Custódia: **{len(acima)} das {len(sinteticos.CUSTODIAS)} instalações** estão acima de 90% da capacidade; "
        f"há **{formatos.quantidade(_volume(ps, RADIOATIVO), RADIOATIVO)}** de material radioativo ainda fora dos "
        "depósitos.",
        f"Entraram **{_casos(recentes)}** nos últimos 12 meses (ainda ativos), contra {formatos.inteiro(anteriores)} "
        f"nos 12 meses anteriores ({'+' if recentes >= anteriores else ''}"
        f"{formatos.inteiro(recentes - anteriores)}).",
    ]
    y = _sumario(t, y, achados, COR_NIVEL[3])

    # 1. situação
    y = _secao(t, y, 1, "Situação", "Quantos casos estão ativos, quantos fora do prazo e quanto material envolvem?")
    y = _kpis(t, y, [
        Kpi("Casos ativos", formatos.inteiro(n), f"na data de corte, {hoje:%d/%m/%Y}"),
        Kpi(vocabulario.rotulo("KPI-03b", "kpi"), formatos.inteiro(len(vencidas)),
            f"{_pct(len(vencidas), n)} de {formatos.inteiro(n)}; atraso médio {_atraso_medio(ps, hoje)}"),
        Kpi(vocabulario.rotulo("KPI-03", "kpi"), formatos.inteiro(len(alem)), f"{_pct(len(alem), n)} de "
                                                                              f"{formatos.inteiro(n)}"),
        Kpi("Casos de risco crítico", formatos.inteiro(len(criticas)),
            f"{_pct(len(criticas), n)} de {formatos.inteiro(n)} (score {_limiar_critico()} ou mais)")])
    y = _kpis(t, y, [Kpi(f"{_rot_classe(c)}", formatos.quantidade(_volume(ps, c), c),
                         f"{_casos(sum(p.classe_risco == c for p in ps))}; unidade da classe")
                     for c in quantidades.CLASSES]
              + [Kpi(_rot_motivo("MP-08"), formatos.inteiro(len(mp08)), f"{_pct(len(mp08), n)} dos casos ativos")])
    y = _subtitulo(t, MARGEM, y, "Por região", nota="Valores exatos; a tabela completa por estado está no Anexo A.")
    linhas = []
    for reg in sorted(analise.REGIOES, key=lambda g: -sum(p.uf in analise.REGIOES[g] for p in ps)):
        doz = [p for p in ps if p.uf in analise.REGIOES[reg]]
        if not doz:
            continue
        venc = sum(p.vencida(hoje) for p in doz)
        crit = sum(faixa[p.codigo] == "CRITICO" for p in doz)
        linhas.append([NOME_REGIAO[reg], len(doz), f"{formatos.inteiro(venc)} ({_pct(venc, len(doz))})",
                       f"{formatos.inteiro(crit)} ({_pct(crit, len(doz))})", _atraso_medio(doz, hoje)]
                      + [_volume(doz, c) for c in quantidades.CLASSES])
    y = _tabela(t, y, [("Região", 110), ("Casos", 70), ("Prazo previsto vencido", 130, "d"),
                       ("Risco crítico", 120, "d"), ("Atraso médio", 96, "d"),
                       (f"{_rot_classe(CLASSE_I)} (t)", 120), (f"{_rot_classe(AREA)} (m³)", 130),
                       (f"{_rot_classe(RADIOATIVO)} (m³)", 112)], linhas, negrito_col0=True,
                total=["Brasil", n, f"{formatos.inteiro(len(vencidas))} ({_pct(len(vencidas), n)})",
                       f"{formatos.inteiro(len(criticas))} ({_pct(len(criticas), n)})", _atraso_medio(ps, hoje)]
                + [_volume(ps, c) for c in quantidades.CLASSES])
    andamento = Counter(vocabulario.rotulo(p.situacao, "situacao_caso") for p in ps).most_common()
    y = _subtitulo(t, MARGEM, y, "Andamento dos casos ativos", nota="Situação administrativa, derivada da etapa atual.")
    y = _barras(t, MARGEM, y, UTIL, andamento, total=n, largura_rotulo=200)

    # 2. risco
    y = _secao(t, y + 4, 2, "Risco", "Quão graves são os casos, de onde vêm os mais graves e que providência exigem?")
    por_faixa = Counter(faixa.values())
    y = _subtitulo(t, MARGEM, y, "Casos por faixa de risco")
    y = _empilhada(t, MARGEM, y, UTIL, [(_rot_faixa(f), por_faixa.get(f, 0), COR_CATEGORIA[f])
                                         for f in reversed(CATEGORIAS)], n)
    criticas_ag = Counter(p.atividade for p in criticas)
    por_ag = Counter(p.atividade for p in ps)
    ordem_ag = sorted(por_ag, key=lambda a: (-criticas_ag.get(a, 0), a))
    y = _subtitulo(t, MARGEM, y + 4, "Atividades de origem com mais casos críticos",
                   nota=f"As 8 primeiras de {len(ordem_ag)}; score médio = média do score de risco dos casos ativos.")
    linhas = []
    for a in ordem_ag[:8]:
        doa = [p for p in ps if p.atividade == a]
        linhas.append([_rot_atividade(a), len(doa), criticas_ag.get(a, 0),
                       _pct(sum(p.vencida(hoje) for p in doa), len(doa)),
                       sum(criticidade(p, hoje) for p in doa) / len(doa)])
    y = _tabela(t, y, [("Atividade de origem", 380), ("Casos", 110), ("Risco crítico", 130),
                       ("% prazo previsto vencido", 140, "d"), ("Score médio", 128)], linhas, negrito_col0=True)
    acoes = Counter(regras.acao_recomendada(p, hoje, r) for p in ps)
    y = _subtitulo(t, MARGEM, y, "Ação recomendada", nota="A regra de escalonamento aplicada a cada caso, da mais grave "
                                                          "à mais branda.")
    y = _barras(t, MARGEM, y, UTIL, [(_rot_acao(a), acoes.get(a, 0)) for a in regras.ACOES if acoes.get(a)], total=n,
                largura_rotulo=260)

    # 3. custódia
    y = _secao(t, y + 4, 3, "Custódia", "As instalações de custódia têm folga para receber o material radioativo que "
                                        "ainda está nos casos?")
    y = _kpis(t, y, [
        Kpi("Material radioativo fora dos depósitos", formatos.quantidade(_volume(ps, RADIOATIVO), RADIOATIVO),
            f"{_casos(sum(p.classe_risco == RADIOATIVO for p in ps), 'ativos')}"),
        Kpi("Instalações acima de 90% da capacidade", f"{len(acima)} de {len(sinteticos.CUSTODIAS)}",
            "sem folga para receber novas cargas"),
        Kpi("Ocupação média das instalações", formatos.percentual(100 * sum(c.ocupacao for c in sinteticos.CUSTODIAS)
                                                                  / len(sinteticos.CUSTODIAS)),
            "média simples das sete instalações")], colunas=3)
    y = _subtitulo(t, MARGEM, y, "Ocupação de cada instalação", nota="Linhas de referência em 70% e 90% da capacidade.")
    x_barra, largura_barra = MARGEM + 380, 340
    for c in sorted(sinteticos.CUSTODIAS, key=lambda c: -c.ocupacao):
        t.texto(MARGEM, y, c.nome, 12, sensivel=("CUSTODIA", 3))
        t.retangulo(x_barra, y + 3, x_barra + largura_barra, y + 15, preenchimento=FUNDO_GRUPO, raio=3)
        t.retangulo(x_barra, y + 3, x_barra + int(largura_barra * min(c.ocupacao, 1.0)), y + 15,
                    preenchimento=COR_CATEGORIA["CRITICO"] if c.ocupacao > 0.9 else DADO, raio=3)
        for ref in (0.7, 0.9):
            xr = x_barra + int(largura_barra * ref)
            t.linha(xr, y, xr, y + 18, cor=TINTA)
        t.texto(x_barra + largura_barra + 14, y, formatos.percentual(100 * c.ocupacao)
                + ("  acima de 90%" if c.ocupacao > 0.9 else ""), 12, negrito=c.ocupacao > 0.9)
        y += 26
    y += 10

    # 4. custo
    y = _secao(t, y + 4, 4, "Custo e responsabilidade financeira",
               "Quanto custaria resolver os casos ativos, e quem paga cada parte?")
    (rotulo_total, texto_total), cartoes = cartoes_de_custo(ps, dados)
    t.texto(MARGEM, y, rotulo_total, 12, negrito=True)
    t.texto(MARGEM, y + 18, texto_total, 30, negrito=True)
    t.texto(MARGEM + 260, y + 30, f"soma das quatro partes abaixo · {_casos(n, 'ativos')}", T_NOTA,
            cor=CINZA)
    y += 66
    cores = [COR_RESPONSABILIDADE[resp] for resp, _ in PARTES_DO_CUSTO]
    if total_custo:
        xx = MARGEM
        for i, (_, valor) in enumerate(partes):
            w = UTIL * valor / total_custo
            if w > 2:
                t.retangulo(xx, y, (LARGURA - MARGEM) if i == len(partes) - 1 else xx + w - 2, y + 24,
                            preenchimento=cores[i])
            xx += w
        y += 34
    largura_parte = (UTIL - 3 * GOTEIRA) // 4
    for i, ((rotulo, valor), (_, texto)) in enumerate(zip(partes, cartoes)):
        x = MARGEM + i * (largura_parte + GOTEIRA)
        t.retangulo(x, y + 4, x + 10, y + 14, preenchimento=cores[i], raio=2)
        t.texto(x + 16, y, rotulo, 12, negrito=True, largura_max=largura_parte - 16)
        t.texto(x + 16, y + 20, texto, 18, negrito=True)
        t.texto(x + 16, y + 46, f"{_pct(valor, total_custo)} do total", T_NOTA, cor=CINZA)
    y += 76
    fila = regras.priorizar(ps, hoje, r)
    y = _subtitulo(t, MARGEM, y, "Fila do orçamento público", nota="Casos que o Estado paga, ordenados pela maior redução "
                                                                   "de risco por real.")
    y = _kpis(t, y, [
        Kpi("Orçamento de referência", formatos.custo(fila.orcamento), "orçamento anual usado na fila"),
        Kpi("Casos que cabem no orçamento", f"{formatos.inteiro(len(fila.selecionadas))} de "
                                            f"{formatos.inteiro(fila.candidatas)}",
            f"custo {formatos.custo(fila.custo_total)}"),
        Kpi("Risco público eliminado", formatos.percentual(fila.percentual_reduzido), "soma dos scores dos casos "
                                                                                      "atendidos ÷ total público"),
        Kpi(_rot_acao(regras.ESCALAR_MP), formatos.inteiro(acoes.get(regras.ESCALAR_MP, 0)),
            "casos cobráveis com a via administrativa esgotada")])

    # anexos
    y = _secao(t, y + 4, "Anexo A", "Tabela por estado", "Ordenada pelo número de casos críticos (a ordem de atenção).")
    linhas = []
    for uf in sorted(por_uf, key=lambda u: (-criticas_uf.get(u, 0), u)):
        doz = [p for p in ps if p.uf == uf]
        venc = sum(p.vencida(hoje) for p in doz)
        linhas.append([uf, len(doz), f"{formatos.inteiro(venc)} ({_pct(venc, len(doz))})", criticas_uf.get(uf, 0)]
                      + [_volume(doz, c) for c in quantidades.CLASSES]
                      + [sum(regras.responsabilidade(p) == regras.PUBLICO for p in doz), _atraso_medio(doz, hoje)])
    y = _tabela(t, y, [("UF", 50), ("Casos", 70), ("Prazo previsto vencido", 130, "d"), ("Risco crítico", 90),
                       (f"{_rot_classe(CLASSE_I)} (t)", 116), (f"{_rot_classe(AREA)} (m³)", 124),
                       (f"{_rot_classe(RADIOATIVO)} (m³)", 110), ("Sem a quem cobrar", 96), ("Atraso médio", 102, "d")],
                linhas, tamanho=11, negrito_col0=True,
                total=["Brasil", n, f"{formatos.inteiro(len(vencidas))} ({_pct(len(vencidas), n)})", len(criticas)]
                + [_volume(ps, c) for c in quantidades.CLASSES]
                + [sum(regras.responsabilidade(p) == regras.PUBLICO for p in ps), _atraso_medio(ps, hoje)])
    y = _nota(t, y + 4, "Anexo B · Como ler", [
        f"Score e faixas: {vocabulario.definicao('SCORE', 'risco')}",
        f"Prazo legal: {vocabulario.definicao('PRAZO_LIMITE', 'prazo')}",
        "Custo: soma, caso a caso, de quantidade × custo unitário de cada etapa do tratamento. As quatro partes "
        "somam o total.",
        "Custódia: ocupação atual das instalações. Material radioativo em m³ de rejeito.",
        "Comparação de 12 meses: casos identificados no período que continuam ativos (os encerrados não entram)."])
    return _fechar(t, item, dados)


def a3_02(item, dados: DadosRelatorio, fontes: Fontes) -> Documento:
    t = _tela(fontes, 9000)
    ps, hoje, r = dados.pendencias, dados.hoje, dados.parametros
    n = len(ps)
    classes = sorted(RISCO_CLASSE, key=lambda c: -RISCO_CLASSE[c])
    grupos = sorted(GRUPOS_MOTIVO, key=lambda g: -PESO_GRUPO[g])
    score = {p.codigo: criticidade(p, hoje) for p in ps}
    faixa = {p.codigo: categoria(p, hoje) for p in ps}
    criticas = sum(f == "CRITICO" for f in faixa.values())
    celulas = {}
    for c in classes:
        for g in grupos:
            cel = [p for p in ps if p.classe_risco == c and grupo_do_motivo(p.motivo) == g]
            if cel:
                celulas[(c, g)] = cel
    pior = max(celulas, key=lambda k: sum(score[p.codigo] for p in celulas[k]) / len(celulas[k])) if celulas else None
    topo = sorted(ps, key=lambda p: score[p.codigo], reverse=True)[:15]
    media = sum(score.values()) / n if n else 0

    y = _capa(t, item, dados, _casos(n, "ativos"))
    achados = [
        f"Score de risco médio: **{br(media)}** (mediana {br(median(score.values())) if n else '0'}); "
        f"**{formatos.inteiro(criticas)} casos ({_pct(criticas, n)})** estão na faixa crítica (score {_limiar_critico()} ou mais)."
        if n else "Nenhum caso ativo.",
        f"A combinação mais grave é **{_rot_classe(pior[0]).lower()} × {_rot_resp(regras.RESPONSABILIDADE_GRUPO[pior[1]]).lower()}**: "
        f"score médio **{br(sum(score[p.codigo] for p in celulas[pior]) / len(celulas[pior]))}** em "
        f"{_casos(len(celulas[pior]))}." if pior else "",
        f"Os 15 primeiros da fila têm score de **{br(score[topo[-1].codigo])}** a **{br(score[topo[0].codigo])}**; "
        f"{formatos.inteiro(sum(p.classe_risco == RADIOATIVO for p in topo))} deles são material radioativo."
        if len(topo) == 15 else "",
        "O atraso multiplica o score: sem solução, cada ano soma 1 ao fator de atraso, e o caso sobe de faixa "
        "sozinho.",
    ]
    y = _sumario(t, y, achados, COR_NIVEL[3])
    y = _kpis(t, y, [
        Kpi("Score médio", br(media), f"mediana {br(median(score.values())) if n else '0'}; {_casos(n, 'ativos')}"),
        Kpi("Casos de risco crítico", formatos.inteiro(criticas), f"{_pct(criticas, n)} dos casos ativos"),
        Kpi("Maior score", br(score[topo[0].codigo]) if topo else "-", f"{topo[0].codigo} · {topo[0].uf}" if topo
            else ""),
        Kpi("Casos com score acima de 100", formatos.inteiro(sum(v > 100 for v in score.values())),
            "atraso de décadas em classe pesada")])

    # 1. matriz
    y = _secao(t, y, 1, "Matriz: classe × tipo de providência",
               "Onde estão os casos mais graves? Cada célula: score médio, casos e casos críticos; quanto mais escura, "
               "maior o score médio.")
    larg_rotulo, alt = 196, 84
    larg_celula = (UTIL - larg_rotulo) // len(grupos)
    h_cab = max(_medir(t, _rot_resp(regras.RESPONSABILIDADE_GRUPO[g]), 12, larg_celula - 16, True) for g in grupos)
    for j, g in enumerate(grupos):
        x = MARGEM + larg_rotulo + j * larg_celula + 8
        t.texto(x, y, _rot_resp(regras.RESPONSABILIDADE_GRUPO[g]), 12, negrito=True, largura_max=larg_celula - 16)
        t.texto(x, y + h_cab, f"peso {brg(PESO_GRUPO[g])}", T_NOTA, cor=CINZA)
    y += h_cab + 24
    medias = {k: sum(score[p.codigo] for p in v) / len(v) for k, v in celulas.items()}
    lo = np.log(min(medias.values())) if medias else 0.0
    hi = np.log(max(medias.values())) if medias else 1.0
    for c in classes:
        t.texto(MARGEM, y + 18, _rot_classe(c), 13, negrito=True, largura_max=larg_rotulo - 14)
        t.texto(MARGEM, y + 40, f"peso {RISCO_CLASSE[c]}", T_NOTA, cor=CINZA)
        for j, g in enumerate(grupos):
            x = MARGEM + larg_rotulo + j * larg_celula
            cel = celulas.get((c, g))
            if not cel:
                t.retangulo(x + 3, y, x + larg_celula - 3, y + alt - 6, preenchimento=FUNDO_SUAVE, raio=4)
                t.texto(x + 12, y + 30, "nenhum caso", 12, cor=CINZA)
                continue
            medio = medias[(c, g)]
            fundo = _na_rampa((np.log(medio) - lo) / (hi - lo) if hi > lo else 0.5)
            tinta = _tinta_sobre(fundo)
            t.retangulo(x + 3, y, x + larg_celula - 3, y + alt - 6, preenchimento=fundo, raio=4)
            t.texto(x + 14, y + 6, f"score médio {br(medio)}", 13, negrito=True, cor=tinta)
            n_crit = sum(faixa[p.codigo] == "CRITICO" for p in cel)
            t.texto(x + 14, y + 30, f"{_casos(len(cel))}", 12, cor=tinta)
            t.texto(x + 14, y + 50, f"{formatos.inteiro(n_crit)} críticos ({_pct(n_crit, len(cel))})", 12,
                    cor=tinta)
        y += alt
    y = _legenda_rampa(t, MARGEM + larg_rotulo, y + 8, "Cor da célula: score médio (escala logarítmica)",
                       br(min(medias.values())) if medias else "-", br(max(medias.values())) if medias else "-")
    for g in grupos:
        t.texto(MARGEM, y, f"{_rot_resp(regras.RESPONSABILIDADE_GRUPO[g])}:", T_NOTA, negrito=True, cor=CINZA)
        x_txt = MARGEM + _largura_texto(t, f"{_rot_resp(regras.RESPONSABILIDADE_GRUPO[g])}:", T_NOTA, True) + 6
        y += t.texto(x_txt, y, ACAO_GRUPO[g] + ".", T_NOTA, cor=CINZA, largura_max=LARGURA - MARGEM - x_txt) + 2
    y += 14

    # 2. faixa por classe
    y = _secao(t, y, 2, "Faixa de risco por classe", "Que classe tem mais casos críticos, em número e em proporção?")
    for c in classes:
        doc = [p for p in ps if p.classe_risco == c]
        t.texto(MARGEM, y + 2, _rot_classe(c), 13, negrito=True)
        t.texto(MARGEM, y + 22, _casos(len(doc)), T_NOTA, cor=CINZA)
        cont = Counter(faixa[p.codigo] for p in doc)
        y = _empilhada(t, MARGEM + 200, y, UTIL - 200, [(_rot_faixa(f), cont.get(f, 0), COR_CATEGORIA[f])
                                                         for f in reversed(CATEGORIAS)], len(doc), altura=20) + 6

    # 3. fila
    y = _secao(t, y, 3, "As 15 maiores prioridades nacionais",
               "Por que cada caso está no topo? Composição = peso da classe × peso da providência × fator de atraso.")
    linhas = [[str(i), p.codigo, f"{p.municipio}/{p.uf}", p.substancia,
               f"{RISCO_CLASSE[p.classe_risco]} × {brg(PESO_GRUPO[grupo_do_motivo(p.motivo)])} × "
               f"{br(fator_atraso(p, hoje))}", score[p.codigo], _rot_acao(regras.acao_recomendada(p, hoje, r))]
              for i, p in enumerate(topo, 1)]
    y = _tabela(t, y, [("Nº", 36), ("Código", 76), ("Local", 150), ("Substância", 200), ("Composição", 122),
                       ("Score", 70), ("Ação recomendada", 234)], linhas, tamanho=11)
    if topo:
        p = topo[0]
        y += t.texto(MARGEM, y, f"Primeiro da fila: {p.codigo}, {p.substancia} em {p.municipio}/{p.uf}, "
                                f"{_anos(p.dias_de_atraso(hoje))} de atraso; motivo: {_rot_motivo(p.motivo).lower()}; "
                                f"custo estimado {formatos.custo_caso(regras.custo_estimado(p, r))}; quem paga: "
                                f"{_rot_resp(regras.responsabilidade(p)).lower()}.", 12, largura_max=UTIL) + 10

    y = _nota(t, y + 4, "Método", [
        "Score de risco = peso da classe × peso da providência × (1 + anos de atraso no prazo previsto).",
        "Peso da classe: " + "; ".join(f"{_rot_classe(c).lower()} {RISCO_CLASSE[c]}" for c in classes) + ".",
        "Peso da providência: " + "; ".join(f"{_rot_resp(regras.RESPONSABILIDADE_GRUPO[g]).lower()} "
                                            f"{brg(PESO_GRUPO[g])}" for g in grupos)
        + ". Pesa mais o que o Estado não tem a quem cobrar, ou nem sabe onde está.",
        "Faixas: " + "; ".join(f"{_rot_faixa(f).lower()}, {vocabulario.definicao(f, 'faixa').lower().rstrip('.')}"
                               for f in CATEGORIAS) + ".",
        _exemplo_do_score()])
    return _fechar(t, item, dados)


def a3_03(item, dados: DadosRelatorio, fontes: Fontes) -> Documento:
    t = _tela(fontes)
    ps, hoje = dados.pendencias, dados.hoje
    n = len(ps)
    criticas = [p for p in ps if categoria(p, hoje) == "CRITICO"]
    criticas_uf = Counter(p.uf for p in criticas)
    por_uf = Counter(p.uf for p in ps)
    peso_uf = Counter()
    for p in ps:
        peso_uf[p.uf] += RISCO_CLASSE.get(p.classe_risco, 1)
    peso_total = sum(peso_uf.values())
    top3 = [uf for uf, _ in peso_uf.most_common(3)]
    acima = [c for c in sinteticos.CUSTODIAS if c.ocupacao > 0.9]

    y = _capa(t, item, dados, _casos(n, "ativos"))
    achados = [
        f"O risco se concentra em **{', '.join(top3)}**: juntos, **{_pct(sum(peso_uf[u] for u in top3), peso_total)}** "
        "do risco ponderado do país." if len(top3) == 3 else "",
        f"**{criticas_uf.most_common(1)[0][0]}** tem o maior número de casos críticos "
        f"(**{formatos.inteiro(criticas_uf.most_common(1)[0][1])}** de {formatos.inteiro(len(criticas))})."
        if criticas else "Nenhum caso na faixa crítica no recorte.",
        f"**{len(acima)} instalações de custódia** estão acima de 90% da capacidade: "
        + "; ".join(f"{c.nome} ({formatos.percentual(100 * c.ocupacao)})" for c in acima) + "." if acima else "",
        f"Recorte aplicado: {dados.escopo}." if "filtro" in dados.escopo else
        f"**{_casos(n, 'ativos')}** no mapa, cada um pesando pela sua classe.",
    ]
    y = _sumario(t, y, achados, COR_NIVEL[3])
    y = _secao(t, y, 1, "Onde o risco se concentra", "Em que áreas do país se acumula o risco dos casos ativos, e onde "
                                                     "ficam as instalações de custódia?")
    largura_mapa, altura_mapa = 560, 548
    mapa = Mapa(MARGEM, y, largura_mapa, altura_mapa)
    mapa.desenhar_ufs(t, {}, padrao=(244, 245, 247), contorno=(200, 204, 210))
    # densidade: soma de gaussianas centradas em cada caso, ponderadas pelo risco da classe
    calor = np.zeros((mapa.altura, mapa.largura), np.float32)
    for p in ps:
        x, yy = mapa.px(p.longitude, p.latitude)
        xi, yi = int(x - mapa.x0), int(yy - mapa.y0)
        if 0 <= xi < mapa.largura and 0 <= yi < mapa.altura:
            calor[yi, xi] += RISCO_CLASSE.get(p.classe_risco, 1)
    calor = cv2.GaussianBlur(calor, (0, 0), 24)
    if calor.max() > 0:
        # raiz quadrada: realça as densidades baixas, senão só o pico mais forte aparece
        normal = np.sqrt(calor / calor.max())
        paradas = np.linspace(0, 1, len(RAMPA))
        rgb = np.dstack([np.interp(normal, paradas, [c[i] for c in RAMPA]) for i in range(3)]).astype(np.uint8)
        territorio = np.zeros(normal.shape, np.uint8)
        contorno = np.array([[mapa.px(lon, lat)[0] - mapa.x0, mapa.px(lon, lat)[1] - mapa.y0]
                             for lon, lat in CONTORNO_BRASIL], np.int32)
        cv2.fillPoly(territorio, [contorno], 1)          # calor sobre o mar não significa nada
        alfa = (np.clip(normal * 1.6, 0, 1) * 0.9 * 255 * territorio).astype(np.uint8)
        t.colar(Image.fromarray(np.dstack([rgb, alfa]), "RGBA"), mapa.x0, mapa.y0)
    _pontos(t, dados, mapa, raio=2.5, anel=False)
    t.marcar(*mapa.caixa, "DISTRIBUICAO_GEOGRAFICA", 3)
    _custodias(t, mapa)
    t.retangulo(mapa.x0, mapa.y0, mapa.x0 + mapa.largura, mapa.y0 + mapa.altura, contorno=FILETE)
    # coluna da direita: números exatos
    x = MARGEM + largura_mapa + 28
    largura_lista = LARGURA - MARGEM - x
    yy = _subtitulo(t, x, y, "Casos críticos por estado", largura_lista,
                    nota=f"Os 12 maiores; base: {_casos(len(criticas))} críticos.")
    ordem = sorted(criticas_uf.items(), key=lambda kv: (-kv[1], kv[0]))[:12]
    yy = _barras(t, x, yy, largura_lista, ordem, total=len(criticas), largura_rotulo=34, tamanho=11)
    yy = _subtitulo(t, x, yy + 6, "Ocupação da custódia", largura_lista,
                    nota="Número = símbolo no mapa. Acima de 90%: sem folga.")
    yy = _lista_custodias(t, x, yy, largura_lista)
    y = mapa.y0 + mapa.altura + 14
    # legenda: rampa contínua e pontos
    y1 = _legenda_rampa(t, MARGEM, y, "Densidade do risco (casos ponderados pela classe)", "menor", "maior")
    y2 = _legenda(t, MARGEM + 300, y, largura_mapa - 300,
                  [(_rot_faixa(f), COR_CATEGORIA[f]) for f in reversed(CATEGORIAS)], "Cada ponto é um caso, na cor "
                  "da faixa de risco", "ponto")
    y = max(y1, y2)
    y = max(y + 6, yy) + 8
    y = _nota(t, y, "Como ler", [
        "Calor: soma de manchas suaves centradas em cada caso, ponderadas pelo risco da classe (material radioativo "
        "3, resíduo perigoso 2, área contaminada 1), em escala de raiz quadrada para mostrar também as densidades "
        "baixas. Só dentro do território.",
        "Contorno e divisas: malha do IBGE (qualidade mínima), projeção simples, sem pretensão cartográfica.",
        "Números exatos por estado e por instalação na coluna ao lado; a tabela completa está no Consolidado nacional."])
    return _fechar(t, item, dados)


DESENHOS = {"A1-01": a1_01, "A1-02": a1_02, "A1-05": a1_05, "A2-01": a2_01, "A2-02": a2_02, "A2-04": a2_04,
            "A3-01": a3_01, "A3-02": a3_02, "A3-03": a3_03}


def gerar(item: RelatorioCatalogo, dados: DadosRelatorio, fontes: Fontes) -> Documento:
    desenhar = DESENHOS.get(item.codigo)
    if desenhar is None:
        raise KeyError(f"Relatório sem desenho: {item.codigo}")
    return desenhar(item, dados, fontes)
