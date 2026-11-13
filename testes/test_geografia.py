"""Distribuição geográfica do acervo.

Critérios: 90 cidades (5 por UF no Sudeste, 4 no Sul, 3 no Norte, no
Nordeste e no Centro-Oeste; o DF tem um município só), as 27 UFs com caso, a capital de SP com casos de risco baixo,
nenhuma cidade com mais de 8% do total, a capital com 30% a 60% da UF e a origem do passivo coerente com a economia
da região. O score não muda aqui.

A regra da capital vale para a participação esperada (a dos pesos do gerador, participacao_esperada): nas UFs com
cerca de 32 casos a contagem sorteada varia uns 17 pontos para cada lado, e uma regra sobre ela passaria ou falharia
pela semente. A contagem sorteada confere a conta onde há casos bastantes (SP).

295 cidades, proporcionais aos casos da UF (casos / 8, de 6 a 30, sem as que o
sorteio deixaria sem caso; o DF tem uma), a capital calibrada para 40% esperado da UF, toda cidade da
lista com caso (1 basta). Mudar as cidades não muda nada fora da geografia: o gerador dela é próprio.
"""
import dataclasses
import hashlib
from collections import Counter

import pytest

from ecosec.acervo import regras, sinteticos
from ecosec.dominio import texto
from ferramentas import baixar_geografia

HOJE = sinteticos.DATA_BASE
REGIOES = {"NORTE": ("AC", "AM", "AP", "PA", "RO", "RR", "TO"),
           "NORDESTE": ("AL", "BA", "CE", "MA", "PB", "PE", "PI", "RN", "SE"),
           "CENTRO-OESTE": ("DF", "GO", "MS", "MT"),
           "SUDESTE": ("ES", "MG", "RJ", "SP"),
           "SUL": ("PR", "RS", "SC")}
REGIAO = {uf: regiao for regiao, ufs in REGIOES.items() for uf in ufs}
CIDADES_POR_UF = (6, 30)                          # Proporcional aos casos da UF (era 5, 4 e 3 por região)
TOTAL_CIDADES = 295
AMAZONIA_LEGAL = {"AC", "AM", "AP", "MA", "MT", "PA", "RO", "RR", "TO"}
TETO_CIDADE = 0.08
FAIXA_CAPITAL = (0.30, 0.60)
# Fora da geografia (município, endereço, bairro, CEP e coordenadas), o acervo com as 90 cidades: SHA-256 do
# repr dos outros campos de cada pendência, na ordem de sinteticos.gerar()
CAMPOS_DA_GEOGRAFIA = ("municipio", "logradouro", "numero", "complemento", "bairro", "cep", "latitude", "longitude")
HASH_FORA_DA_GEOGRAFIA = "8a3441a0276134ff75bc34438983a377e94562646af9f185623798975457daf0"

# Lista de cidades (alvo 40%), com a capital primeiro (nomes como no geografia.json)
CIDADES = {
    "SP": ("SAO PAULO", "CUBATAO", "PAULINIA", "SAO BERNARDO DO CAMPO", "CAMPINAS", "SAO JOSE DOS CAMPOS", "SOROCABA",
           "RIBEIRAO PRETO", "SANTOS", "PIRACICABA", "LIMEIRA", "FRANCA", "SAO JOSE DO RIO PRETO",
           "PRESIDENTE PRUDENTE", "ARARAQUARA", "AMERICANA", "TAUBATE", "JACAREI", "SERTAOZINHO", "SANTA GERTRUDES",
           "OURINHOS", "MARILIA", "ARACATUBA", "SAO CARLOS", "BARRETOS", "LENCOIS PAULISTA", "ITAPEVA", "MOGI GUACU"),
    "RJ": ("RIO DE JANEIRO", "DUQUE DE CAXIAS", "VOLTA REDONDA", "CAMPOS DOS GOYTACAZES", "RESENDE", "MACAE", "ITAGUAI",
           "BARRA MANSA", "NITEROI", "PETROPOLIS", "NOVA FRIBURGO", "SAO JOAO DA BARRA", "TERESOPOLIS", "SEROPEDICA",
           "BELFORD ROXO", "RIO DAS OSTRAS", "ITAPERUNA", "PORTO REAL", "VALENCA", "CANTAGALO"),
    "MG": ("BELO HORIZONTE", "CONTAGEM", "IPATINGA", "ITABIRA", "UBERLANDIA", "JUIZ DE FORA", "BETIM", "MONTES CLAROS",
           "UBERABA", "GOVERNADOR VALADARES", "SETE LAGOAS", "DIVINOPOLIS", "OURO PRETO", "JOAO MONLEVADE", "CONGONHAS",
           "PATOS DE MINAS", "ITABIRITO", "VARGINHA", "POUSO ALEGRE", "TEOFILO OTONI", "UNAI", "TRES MARIAS", "ITAJUBA",
           "LAVRAS", "PIRAPORA"),
    "ES": ("VITORIA", "SERRA", "VILA VELHA", "ARACRUZ", "ANCHIETA", "CACHOEIRO DE ITAPEMIRIM", "LINHARES", "SAO MATEUS",
           "COLATINA", "NOVA VENECIA", "VIANA", "BARRA DE SAO FRANCISCO"),
    "PR": ("CURITIBA", "ARAUCARIA", "PONTA GROSSA", "LONDRINA", "MARINGA", "CASCAVEL", "PARANAGUA",
           "SAO JOSE DOS PINHAIS", "GUARAPUAVA", "TOLEDO", "TELEMACO BORBA", "APUCARANA", "UMUARAMA", "CAMPO MOURAO",
           "ARAPONGAS", "FRANCISCO BELTRAO", "PATO BRANCO", "RIO BRANCO DO SUL"),
    "SC": ("FLORIANOPOLIS", "JOINVILLE", "CRICIUMA", "CHAPECO", "BLUMENAU", "ITAJAI", "JARAGUA DO SUL", "LAGES",
           "SAO FRANCISCO DO SUL", "TUBARAO", "CONCORDIA", "BRUSQUE"),
    "RS": ("PORTO ALEGRE", "CANOAS", "TRIUNFO", "SANTA CRUZ DO SUL", "CAXIAS DO SUL", "RIO GRANDE", "PELOTAS",
           "NOVO HAMBURGO", "PASSO FUNDO", "SANTA MARIA", "GRAVATAI", "CHARQUEADAS", "ESTANCIA VELHA", "CANDIOTA",
           "BENTO GONCALVES", "IJUI", "URUGUAIANA"),
    "BA": ("SALVADOR", "CAMACARI", "CANDEIAS", "FEIRA DE SANTANA", "VITORIA DA CONQUISTA", "ILHEUS", "JUAZEIRO",
           "BARREIRAS", "SIMOES FILHO", "MUCURI", "TEIXEIRA DE FREITAS", "JACOBINA", "BRUMADO",
           "LUIS EDUARDO MAGALHAES"),
    "PE": ("RECIFE", "IPOJUCA", "JABOATAO DOS GUARARAPES", "PETROLINA", "CARUARU", "CABO DE SANTO AGOSTINHO", "GOIANA",
           "VITORIA DE SANTO ANTAO", "GARANHUNS", "ARARIPINA", "SERRA TALHADA", "ESCADA", "OURICURI"),
    "CE": ("FORTALEZA", "MARACANAU", "CAUCAIA", "SAO GONCALO DO AMARANTE", "JUAZEIRO DO NORTE", "SOBRAL", "CRATO",
           "HORIZONTE"),
    "RN": ("NATAL", "MOSSORO", "PARNAMIRIM", "GUAMARE", "MACAU", "ASSU", "CURRAIS NOVOS"),
    "PB": ("JOAO PESSOA", "CAMPINA GRANDE", "CABEDELO", "SANTA RITA", "PATOS", "CAAPORA"),
    "AL": ("MACEIO", "MARECHAL DEODORO", "ARAPIRACA", "RIO LARGO", "PENEDO", "CORURIPE", "SAO MIGUEL DOS CAMPOS",
           "PILAR"),
    "SE": ("ARACAJU", "LARANJEIRAS", "NOSSA SENHORA DO SOCORRO", "CARMOPOLIS", "ITABAIANA", "JAPARATUBA"),
    "MA": ("SAO LUIS", "ACAILANDIA", "IMPERATRIZ", "BALSAS", "CAXIAS", "BACABAL", "GRAJAU"),
    "PI": ("TERESINA", "PARNAIBA", "URUCUI", "PICOS", "FLORIANO", "BOM JESUS"),
    "PA": ("BELEM", "BARCARENA", "ITAITUBA", "MARABA", "SANTAREM", "PARAUAPEBAS", "ALTAMIRA", "PARAGOMINAS",
           "CASTANHAL", "REDENCAO", "ORIXIMINA", "NOVO PROGRESSO", "ABAETETUBA", "JACAREACANGA", "TAILANDIA"),
    "AM": ("MANAUS", "PRESIDENTE FIGUEIREDO", "COARI", "ITACOATIARA", "PARINTINS", "MANACAPURU", "HUMAITA", "TEFE",
           "SAO GABRIEL DA CACHOEIRA", "MAUES"),
    "RO": ("PORTO VELHO", "ARIQUEMES", "JI PARANA", "VILHENA", "CACOAL", "CANDEIAS DO JAMARI"),
    "AC": ("RIO BRANCO", "CRUZEIRO DO SUL", "SENA MADUREIRA", "TARAUACA", "FEIJO", "BRASILEIA"),
    "RR": ("BOA VISTA", "CARACARAI", "MUCAJAI", "RORAINOPOLIS", "ALTO ALEGRE", "CANTA"),
    "AP": ("MACAPA", "SANTANA", "LARANJAL DO JARI", "OIAPOQUE", "PEDRA BRANCA DO AMAPARI", "VITORIA DO JARI"),
    "TO": ("PALMAS", "ARAGUAINA", "GURUPI", "PORTO NACIONAL", "PARAISO DO TOCANTINS", "DIANOPOLIS"),
    "GO": ("GOIANIA", "CATALAO", "RIO VERDE", "ANAPOLIS", "JATAI", "ITUMBIARA", "NIQUELANDIA", "CRIXAS", "BARRO ALTO",
           "LUZIANIA", "MINEIROS", "SENADOR CANEDO"),
    "MT": ("CUIABA", "RONDONOPOLIS", "PEIXOTO DE AZEVEDO", "SINOP", "SORRISO", "LUCAS DO RIO VERDE",
           "PRIMAVERA DO LESTE", "ALTA FLORESTA", "PONTES E LACERDA", "BARRA DO GARCAS", "POCONE", "TANGARA DA SERRA"),
    "MS": ("CAMPO GRANDE", "TRES LAGOAS", "CORUMBA", "DOURADOS", "RIBAS DO RIO PARDO", "PONTA PORA", "NAVIRAI",
           "MARACAJU"),
    "DF": ("BRASILIA",),
}
CAPITAL = {uf: cidades[0] for uf, cidades in CIDADES.items()}
# O hash do acervo está em test_ficha.py.


def _parte(casos, atividade: str) -> float:
    return sum(p.atividade == atividade for p in casos) / len(casos) if casos else 0.0


@pytest.fixture(scope="module")
def base():
    return sinteticos.gerar()


# onde estão os casos
def test_cada_estado_tem_pelo_menos_uma_cidade_com_caso(base):
    pendencias = base[0]
    _, municipios = sinteticos.geografia()
    assert len(sinteticos.PESO_UF) == 27 and {p.uf for p in pendencias} == set(sinteticos.PESO_UF)
    for uf in sinteticos.PESO_UF:
        assert {p.municipio for p in pendencias if p.uf == uf} <= {m.nome for m in municipios[uf]}, uf


def test_capital_sp_tem_caso_de_risco_baixo(base):
    # situação Todos, na data-base; menos de 5 ATIVOS só vai para
    casos = [p for p in base[0] if (p.uf, p.municipio) == ("SP", CAPITAL["SP"])]
    baixos = [p for p in casos if regras.categoria(p, HOJE) == "BAIXO"]
    bairros = {p.bairro for p in baixos}
    assert len(baixos) >= 5 and len(bairros) >= 3, \
        f"capital SP: {len(casos)} casos, {len(baixos)} de risco baixo, em {len(bairros)} bairros"


def test_nenhuma_cidade_tem_mais_de_8_por_cento_do_total(base):
    pendencias = base[0]
    (uf, nome), n = Counter((p.uf, p.municipio) for p in pendencias).most_common(1)[0]
    assert n / len(pendencias) <= TETO_CIDADE, f"{nome}/{uf}: {n} de {len(pendencias)}"
    # A capital com 30% a 60% da UF (o DF tem um município só)
    fora = {}
    for uf in sinteticos.PESO_UF:
        parte = sinteticos.participacao_esperada(uf)
        assert sum(parte.values()) == pytest.approx(1.0), uf
        if uf != "DF" and not FAIXA_CAPITAL[0] <= parte.get(CAPITAL[uf], 0.0) <= FAIXA_CAPITAL[1]:
            fora[uf] = round(100 * parte.get(CAPITAL[uf], 0.0))
    assert not fora, f"capital fora de 30% a 60% da UF, em %: {fora}"
    sp = [p for p in pendencias if p.uf == "SP"]                 # cerca de 300 casos: a contagem confere a conta
    sorteada = sum(p.municipio == CAPITAL["SP"] for p in sp) / len(sp)
    assert sorteada == pytest.approx(sinteticos.participacao_esperada("SP")[CAPITAL["SP"]], abs=0.10)


def test_nenhum_estado_concentra_100_por_cento_numa_cidade(base):
    por_uf: dict[str, Counter] = {}
    for p in base[0]:
        por_uf.setdefault(p.uf, Counter())[p.municipio] += 1
    assert set(por_uf["DF"]) == {CAPITAL["DF"]}                 # a exceção: o DF tem um município só
    assert not sorted(uf for uf, cidades in por_uf.items() if uf != "DF" and len(cidades) < 2)


def test_toda_cidade_da_lista_tem_caso(base):
    # Nenhuma cidade da lista fica vazia; 1 caso basta
    com_caso = {(p.uf, p.municipio) for p in base[0]}
    sem_caso = sorted(f"{nome}/{uf}" for uf, cidades in CIDADES.items() for nome in cidades
                      if (uf, nome) not in com_caso)
    assert not sem_caso, f"{len(sem_caso)} cidades da lista sem caso: {sem_caso}"
    assert len(com_caso) == TOTAL_CIDADES


def test_mudar_as_cidades_nao_muda_nada_fora_da_geografia(base):
    # o gerador da geografia é próprio: classe, datas, score e responsáveis não mudam com as cidades. O hash
    # dos responsáveis é conferido em test_ficha.py (o mesmo)
    m = hashlib.sha256()
    for p in base[0]:
        fora = tuple(getattr(p, c.name) for c in dataclasses.fields(p) if c.name not in CAMPOS_DA_GEOGRAFIA)
        m.update(repr(fora).encode("utf-8"))
        m.update(b"\n")
    assert m.hexdigest() == HASH_FORA_DA_GEOGRAFIA


# a lista de cidades
def test_distribuicao_de_cidades_por_estado_conforme_tabela():
    assert set(CIDADES) == set(sinteticos.PESO_UF) and sum(len(c) for c in CIDADES.values()) == TOTAL_CIDADES
    for uf, cidades in CIDADES.items():
        assert (len(cidades) == 1) if uf == "DF" else (CIDADES_POR_UF[0] <= len(cidades) <= CIDADES_POR_UF[1]), uf
    aprovada = {uf: set(cidades) for uf, cidades in CIDADES.items()}
    _, municipios = sinteticos.geografia()
    no_arquivo = {uf: {m.nome for m in ms} for uf, ms in municipios.items()}
    diferencas = {uf: {"faltam": sorted(aprovada[uf] - no_arquivo.get(uf, set())),
                       "sobram": sorted(no_arquivo.get(uf, set()) - aprovada[uf])}
                  for uf in aprovada if no_arquivo.get(uf) != aprovada[uf]}
    assert not diferencas, f"geografia.json fora da lista aprovada: {diferencas}"
    # o arquivo sai da ferramenta (reprodutível): a lista dela é a mesma
    assert {uf: {texto.nome(n) for n in nomes} for uf, nomes in baixar_geografia.MUNICIPIOS.items()} == aprovada


# origem do passivo × região
def test_distribuicao_por_classe_e_plausivel_por_regiao(base):
    pendencias = base[0]
    falhas = []
    garimpo = {p.uf for p in pendencias if p.atividade == "AG-13"}
    if not garimpo or not garimpo <= AMAZONIA_LEGAL:
        falhas.append(f"garimpo fora da Amazônia Legal: {sorted(garimpo - AMAZONIA_LEGAL)}")
    sem_norm = [uf for uf in ("AM", "PA", "RO") if not any(p.uf == uf and p.atividade == "AG-07" for p in pendencias)]
    if sem_norm:
        falhas.append(f"mineração com radioatividade natural ausente em {sem_norm}")
    capitais = [p for p in pendencias if p.municipio == CAPITAL[p.uf]]
    acima_do_pais = (("metalurgia em MG", [p for p in pendencias if p.uf == "MG"], "AG-04"),
                     ("química e defensivos no Centro-Oeste",
                      [p for p in pendencias if REGIAO[p.uf] == "CENTRO-OESTE"], "AG-02"),
                     ("refino e terminais no Sudeste", [p for p in pendencias if REGIAO[p.uf] == "SUDESTE"], "AG-10"),
                     ("radioterapia e fontes seladas nas capitais", capitais, "AG-08"))
    for rotulo, casos, atividade in acima_do_pais:
        local, pais = _parte(casos, atividade), _parte(pendencias, atividade)
        if local <= pais:
            falhas.append(f"{rotulo}: {100 * local:.1f}% contra {100 * pais:.1f}% no país")
    assert not falhas, "; ".join(falhas)
