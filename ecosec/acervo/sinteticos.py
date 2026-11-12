"""Base do acervo de passivos perigosos: determinística (semente fixa).

Todas as execuções geram exatamente o mesmo acervo: os testes dependem disso,
e o documento pode citar números estáveis.

A forma segue os cadastros oficiais:
  - tipologia das atividades e contaminantes: Relação de Áreas Contaminadas da
    CETESB (SP) e BDNAC/IBAMA; passivos minerários: FEAM/IDE-Sisema (MG);
  - geografia REAL, lida de dados/geografia.json (ferramentas.baixar_geografia):
    a coordenada é sorteada DENTRO do polígono do município (malha do IBGE), a
    pelo menos ~200 m da divisa; o bairro e o prefixo do CEP são da própria
    cidade (ViaCEP). O logradouro é genérico, para não apontar um endereço real.
    A cidade sai pelo porte e pelo perfil econômico dela (CIDADES), com um
    gerador próprio por caso: mudar as cidades não muda classe, datas nem score.
Toda linha gerada aqui leva `sintetico = TRUE` (origem: este gerador), o que a
separa de qualquer carga externa no mesmo banco.

Texto padronizado na origem (ecosec.dominio.texto): maiúsculas, sem acento,
unidades de medida por extenso.

A distribuição por atividade segue, grosso modo, a do cadastro da CETESB
(postos de combustível são a maior parte): o único dado real usado, e só como
proporção.
"""
import hashlib
import json
import math
import random
from dataclasses import dataclass
from statistics import NormalDist
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np

from ecosec.acervo.geracao import ciclo, fluxos, saidas, series
from ecosec.dominio import texto
from ecosec.dominio.acervo import (AtividadeGeradora, Custodia, EventoRegulatorio, MotivoPermanencia, Pendencia,
                                   RelatorioCatalogo, Responsavel)

SEMENTE = 2026
QUANTIDADE = 2400                    # padrão de [geracao] quantidade (ecosec.toml)
DATA_BASE = date(2026, 10, 1)        # referência para os prazos (alguns vencem, outros não)
PRIMEIRA_IDENTIFICACAO = date(2006, 1, 1)     # início da série (antes: só estoque herdado)
MARGEM_DIVISA = 0.002                # graus (~200 m): o ponto não encosta na divisa do município
DISTANCIA_CONTINENTE = 0.5           # graus: anel municipal mais longe que isso do continente (ilha oceânica) não conta
TOLERANCIA_CONTORNO = 0.03           # graus (~3 km): o contorno do país é simplificado; a costa real vai além dele
ARQUIVO_GEOGRAFIA = Path(__file__).parent / "dados" / "geografia.json"

# Peso de cada UF no sorteio: grosso modo, o tamanho do parque industrial e minerário (todas as 27 aparecem)
PESO_UF = {"SP": 9, "MG": 6, "RJ": 5, "PR": 4, "RS": 4, "BA": 4, "GO": 3, "SC": 3, "PE": 3, "ES": 3,
           "PA": 4, "AM": 3, "MT": 3, "MS": 2, "MA": 2, "CE": 2, "AL": 1.5, "RN": 1.5, "TO": 1.5, "RO": 2,
           "AP": 1.5, "PB": 1, "SE": 1, "PI": 1, "AC": 1, "RR": 1, "DF": 1}
# Afinidade regional (multiplica o peso da atividade na UF): a origem do passivo segue a economia local.
# O garimpo de ouro com mercúrio (AG-13) só existe onde há garimpo: metalurgia em MG, ES e RJ;
# química no Norte, no Sul, no RJ e, com agrotóxico, no Centro-Oeste (2,5: com 1,5 a média do país subia junto);
# terminais no ES, PR e RS; mineração com radioatividade natural no AM e em RO.
AFINIDADE = {
    "AG-13": {uf: 1.0 for uf in ("PA", "AM", "RO", "RR", "AP", "MT", "TO", "AC")},
    "AG-07": {"MG": 3, "PA": 3, "GO": 2, "AP": 2, "MS": 2, "BA": 1.5, "SC": 1.5, "AM": 2, "RO": 2},
    "AG-11": {"MS": 3, "BA": 2.5, "ES": 2.5, "MA": 2, "SP": 1.5, "PR": 1.5},
    "AG-10": {"RJ": 3, "BA": 2.5, "AM": 2.5, "MA": 2, "SP": 2, "RN": 2, "PE": 1.5, "ES": 2, "RS": 1.5, "PR": 1.5},
    "AG-02": {"SP": 2, "BA": 2, "RS": 1.5, "AL": 2, "MT": 2.5, "GO": 2.5, "MS": 2.5, "PR": 1.5, "RJ": 1.5,
              "AM": 1.5, "PA": 1.5},
    "AG-04": {"MG": 2.5, "ES": 1.5, "RJ": 1.5},
}
AFINIDADE_EXCLUSIVA = {"AG-13"}

# Cidades de cada UF: (nome, porte, perfis), a capital primeiro; os nomes são os de
# dados/geografia.json. A cidade é sorteada DEPOIS da atividade, com peso porte × AFINIDADE_PERFIL quando a atividade
# é do perfil da cidade (porte × 1 nas demais): 295 cidades, proporcionais aos casos da UF (casos / 8, de 6
# a 30; saíram as que o sorteio deixava sem caso), as novas com porte 1, em ordem de prioridade depois das 90
# Campina Grande e Imperatriz, polos regionais, passaram a porte 2 (com 1 ficavam sem caso).
# O porte da capital está calibrado para ela ficar com cerca de 40% dos casos esperados da UF (era 45%;
# de 30% a 60%; participacao_esperada). Sem perfil biológico (não há essa atividade) nem nuclear de operador único: as
# fontes seladas ficam no perfil urbano, onde estão os hospitais.
URBANO, QUIMICO, METALURGICO, PETROLEO, MINERACAO, AGROFLORESTAL = (
    "URBANO", "QUIMICO", "SIDERURGICO E METALURGICO", "PETROLEO E PORTUARIO", "MINERACAO", "AGROFLORESTAL")
ATIVIDADES_DO_PERFIL = {
    URBANO: ("AG-01", "AG-06", "AG-08", "AG-12"),         # postos, ascarel, radioterapia e fontes, lavanderias
    QUIMICO: ("AG-02", "AG-03", "AG-05"),
    METALURGICO: ("AG-03", "AG-04", "AG-06"),
    PETROLEO: ("AG-01", "AG-10"),
    MINERACAO: ("AG-04", "AG-07", "AG-13"),
    AGROFLORESTAL: ("AG-02", "AG-09", "AG-11"),
}
AFINIDADE_PERFIL = 3.0
CIDADES = {
    "SP": (("SAO PAULO", 20.9, (URBANO,)), ("CUBATAO", 2, (QUIMICO, METALURGICO)), ("PAULINIA", 2, (PETROLEO, QUIMICO)),
           ("SAO BERNARDO DO CAMPO", 2, (METALURGICO,)), ("CAMPINAS", 2, (QUIMICO, URBANO)),
           ("SAO JOSE DOS CAMPOS", 1, (METALURGICO, PETROLEO)), ("SOROCABA", 1, (METALURGICO,)),
           ("RIBEIRAO PRETO", 1, (AGROFLORESTAL, URBANO)), ("SANTOS", 1, (PETROLEO,)),
           ("PIRACICABA", 1, (METALURGICO, AGROFLORESTAL)), ("LIMEIRA", 1, (METALURGICO,)),
           ("FRANCA", 1, (AGROFLORESTAL,)), ("SAO JOSE DO RIO PRETO", 1, (AGROFLORESTAL,)),
           ("PRESIDENTE PRUDENTE", 1, (AGROFLORESTAL,)), ("ARARAQUARA", 1, (AGROFLORESTAL,)),
           ("AMERICANA", 1, (QUIMICO,)), ("TAUBATE", 1, (METALURGICO,)), ("JACAREI", 1, (QUIMICO, AGROFLORESTAL)),
           ("SERTAOZINHO", 1, (METALURGICO, AGROFLORESTAL)), ("SANTA GERTRUDES", 1, (QUIMICO,)),
           ("OURINHOS", 1, (AGROFLORESTAL,)), ("MARILIA", 1, (AGROFLORESTAL,)), ("ARACATUBA", 1, (AGROFLORESTAL,)),
           ("SAO CARLOS", 1, (METALURGICO,)), ("BARRETOS", 1, (AGROFLORESTAL,)),
           ("LENCOIS PAULISTA", 1, (AGROFLORESTAL,)), ("ITAPEVA", 1, (AGROFLORESTAL, MINERACAO)),
           ("MOGI GUACU", 1, (AGROFLORESTAL,))),
    "RJ": (("RIO DE JANEIRO", 11.8, (URBANO, PETROLEO)), ("DUQUE DE CAXIAS", 2, (PETROLEO, QUIMICO)),
           ("VOLTA REDONDA", 2, (METALURGICO,)), ("CAMPOS DOS GOYTACAZES", 1, (PETROLEO,)),
           ("RESENDE", 1, (METALURGICO,)), ("MACAE", 1, (PETROLEO,)), ("ITAGUAI", 1, (PETROLEO, METALURGICO)),
           ("BARRA MANSA", 1, (METALURGICO,)), ("NITEROI", 1, (PETROLEO,)), ("PETROPOLIS", 1, (QUIMICO,)),
           ("NOVA FRIBURGO", 1, (METALURGICO,)), ("SAO JOAO DA BARRA", 1, (PETROLEO,)),
           ("TERESOPOLIS", 1, (AGROFLORESTAL,)), ("SEROPEDICA", 1, (QUIMICO,)), ("BELFORD ROXO", 1, (QUIMICO,)),
           ("RIO DAS OSTRAS", 1, (PETROLEO,)), ("ITAPERUNA", 1, (AGROFLORESTAL,)), ("PORTO REAL", 1, (METALURGICO,)),
           ("VALENCA", 1, (AGROFLORESTAL,)), ("CANTAGALO", 1, (MINERACAO,))),
    "MG": (("BELO HORIZONTE", 16.3, (URBANO,)), ("CONTAGEM", 2, (QUIMICO, METALURGICO)),
           ("IPATINGA", 2, (METALURGICO,)), ("ITABIRA", 1, (MINERACAO,)), ("UBERLANDIA", 1, (AGROFLORESTAL,)),
           ("JUIZ DE FORA", 1, (METALURGICO,)), ("BETIM", 1, (PETROLEO, METALURGICO)),
           ("MONTES CLAROS", 1, (AGROFLORESTAL,)), ("UBERABA", 1, (QUIMICO, AGROFLORESTAL)),
           ("GOVERNADOR VALADARES", 1, (AGROFLORESTAL,)), ("SETE LAGOAS", 1, (METALURGICO,)),
           ("DIVINOPOLIS", 1, (METALURGICO,)), ("OURO PRETO", 1, (MINERACAO,)), ("JOAO MONLEVADE", 1, (METALURGICO,)),
           ("CONGONHAS", 1, (MINERACAO,)), ("PATOS DE MINAS", 1, (AGROFLORESTAL,)), ("ITABIRITO", 1, (MINERACAO,)),
           ("VARGINHA", 1, (AGROFLORESTAL,)), ("POUSO ALEGRE", 1, (QUIMICO,)),
           ("TEOFILO OTONI", 1, (AGROFLORESTAL, MINERACAO)), ("UNAI", 1, (AGROFLORESTAL,)),
           ("TRES MARIAS", 1, (METALURGICO,)), ("ITAJUBA", 1, (METALURGICO,)), ("LAVRAS", 1, (AGROFLORESTAL,)),
           ("PIRAPORA", 1, (METALURGICO, AGROFLORESTAL))),
    "ES": (("VITORIA", 6.8, (URBANO, PETROLEO)), ("SERRA", 2, (METALURGICO,)), ("VILA VELHA", 1, (PETROLEO,)),
           ("ARACRUZ", 1, (AGROFLORESTAL,)), ("ANCHIETA", 1, (MINERACAO, PETROLEO)),
           ("CACHOEIRO DE ITAPEMIRIM", 1, (MINERACAO,)), ("LINHARES", 1, (PETROLEO, AGROFLORESTAL)),
           ("SAO MATEUS", 1, (PETROLEO, AGROFLORESTAL)), ("COLATINA", 1, (AGROFLORESTAL,)),
           ("NOVA VENECIA", 1, (MINERACAO,)), ("VIANA", 1, (QUIMICO,)), ("BARRA DE SAO FRANCISCO", 1, (MINERACAO,))),
    "PR": (("CURITIBA", 10.6, (URBANO,)), ("ARAUCARIA", 2, (PETROLEO, QUIMICO)), ("PONTA GROSSA", 1, (AGROFLORESTAL,)),
           ("LONDRINA", 1, (AGROFLORESTAL,)), ("MARINGA", 1, (AGROFLORESTAL,)), ("CASCAVEL", 1, (AGROFLORESTAL,)),
           ("PARANAGUA", 1, (PETROLEO, QUIMICO)), ("SAO JOSE DOS PINHAIS", 1, (METALURGICO,)),
           ("GUARAPUAVA", 1, (AGROFLORESTAL,)), ("TOLEDO", 1, (AGROFLORESTAL,)),
           ("TELEMACO BORBA", 1, (AGROFLORESTAL,)), ("APUCARANA", 1, (AGROFLORESTAL,)),
           ("UMUARAMA", 1, (AGROFLORESTAL,)), ("CAMPO MOURAO", 1, (AGROFLORESTAL,)), ("ARAPONGAS", 1, (QUIMICO,)),
           ("FRANCISCO BELTRAO", 1, (AGROFLORESTAL,)), ("PATO BRANCO", 1, (METALURGICO,)),
           ("RIO BRANCO DO SUL", 1, (MINERACAO,))),
    "SC": (("FLORIANOPOLIS", 6.6, (URBANO,)), ("JOINVILLE", 2, (METALURGICO,)), ("CRICIUMA", 1, (MINERACAO,)),
           ("CHAPECO", 1, (AGROFLORESTAL,)), ("BLUMENAU", 1, (QUIMICO,)), ("ITAJAI", 1, (PETROLEO,)),
           ("JARAGUA DO SUL", 1, (METALURGICO,)), ("LAGES", 1, (AGROFLORESTAL,)),
           ("SAO FRANCISCO DO SUL", 1, (PETROLEO,)), ("TUBARAO", 1, (MINERACAO,)), ("CONCORDIA", 1, (AGROFLORESTAL,)),
           ("BRUSQUE", 1, (QUIMICO,))),
    "RS": (("PORTO ALEGRE", 8.9, (URBANO, PETROLEO)), ("CANOAS", 2, (PETROLEO,)), ("TRIUNFO", 1, (QUIMICO,)),
           ("SANTA CRUZ DO SUL", 1, (AGROFLORESTAL,)), ("CAXIAS DO SUL", 1, (METALURGICO,)),
           ("RIO GRANDE", 1, (PETROLEO, QUIMICO)), ("PELOTAS", 1, (AGROFLORESTAL,)),
           ("NOVO HAMBURGO", 1, (AGROFLORESTAL,)), ("PASSO FUNDO", 1, (AGROFLORESTAL,)),
           ("SANTA MARIA", 1, (AGROFLORESTAL,)), ("GRAVATAI", 1, (METALURGICO,)),
           ("CHARQUEADAS", 1, (METALURGICO, MINERACAO)), ("ESTANCIA VELHA", 1, (AGROFLORESTAL,)),
           ("CANDIOTA", 1, (MINERACAO,)), ("BENTO GONCALVES", 1, (QUIMICO,)), ("IJUI", 1, (AGROFLORESTAL,)),
           ("URUGUAIANA", 1, (AGROFLORESTAL,))),
    "BA": (("SALVADOR", 8.3, (URBANO, PETROLEO)), ("CAMACARI", 3, (QUIMICO,)), ("CANDEIAS", 1, (PETROLEO,)),
           ("FEIRA DE SANTANA", 1, (QUIMICO,)), ("VITORIA DA CONQUISTA", 1, (AGROFLORESTAL,)),
           ("ILHEUS", 1, (AGROFLORESTAL, PETROLEO)), ("JUAZEIRO", 1, (AGROFLORESTAL,)),
           ("BARREIRAS", 1, (AGROFLORESTAL,)), ("SIMOES FILHO", 1, (METALURGICO, QUIMICO)),
           ("MUCURI", 1, (AGROFLORESTAL,)), ("TEIXEIRA DE FREITAS", 1, (AGROFLORESTAL,)), ("JACOBINA", 1, (MINERACAO,)),
           ("BRUMADO", 1, (MINERACAO,)), ("LUIS EDUARDO MAGALHAES", 1, (AGROFLORESTAL,))),
    "PE": (("RECIFE", 7.3, (URBANO,)), ("IPOJUCA", 2, (PETROLEO,)), ("JABOATAO DOS GUARARAPES", 1, (QUIMICO,)),
           ("PETROLINA", 1, (AGROFLORESTAL,)), ("CARUARU", 1, (QUIMICO,)),
           ("CABO DE SANTO AGOSTINHO", 1, (QUIMICO, PETROLEO)), ("GOIANA", 1, (METALURGICO,)),
           ("VITORIA DE SANTO ANTAO", 1, (AGROFLORESTAL,)), ("GARANHUNS", 1, (AGROFLORESTAL,)),
           ("ARARIPINA", 1, (MINERACAO,)), ("SERRA TALHADA", 1, (AGROFLORESTAL,)), ("ESCADA", 1, (AGROFLORESTAL,)),
           ("OURICURI", 1, (MINERACAO,))),
    "CE": (("FORTALEZA", 4.2, (URBANO,)), ("MARACANAU", 1, (QUIMICO,)), ("CAUCAIA", 1, (PETROLEO, METALURGICO)),
           ("SAO GONCALO DO AMARANTE", 1, (PETROLEO, METALURGICO)), ("JUAZEIRO DO NORTE", 1, (METALURGICO,)),
           ("SOBRAL", 1, (MINERACAO,)), ("CRATO", 1, (AGROFLORESTAL,)), ("HORIZONTE", 1, (QUIMICO,))),
    "RN": (("NATAL", 3.8, (URBANO,)), ("MOSSORO", 1, (PETROLEO,)), ("PARNAMIRIM", 1, (QUIMICO,)),
           ("GUAMARE", 1, (PETROLEO,)), ("MACAU", 1, (PETROLEO,)), ("ASSU", 1, (PETROLEO, AGROFLORESTAL)),
           ("CURRAIS NOVOS", 1, (MINERACAO,))),
    "PB": (("JOAO PESSOA", 3.2, (URBANO,)), ("CAMPINA GRANDE", 2, (QUIMICO,)), ("CABEDELO", 1, (PETROLEO,)),
           ("SANTA RITA", 1, (QUIMICO,)), ("PATOS", 1, (AGROFLORESTAL,)), ("CAAPORA", 1, (MINERACAO,))),
    "AL": (("MACEIO", 3, (URBANO, QUIMICO)), ("MARECHAL DEODORO", 1, (QUIMICO,)), ("ARAPIRACA", 1, (AGROFLORESTAL,)),
           ("RIO LARGO", 1, (AGROFLORESTAL,)), ("PENEDO", 1, (AGROFLORESTAL,)), ("CORURIPE", 1, (AGROFLORESTAL,)),
           ("SAO MIGUEL DOS CAMPOS", 1, (PETROLEO, AGROFLORESTAL)), ("PILAR", 1, (PETROLEO,))),
    "SE": (("ARACAJU", 3, (URBANO,)), ("LARANJEIRAS", 1, (QUIMICO, PETROLEO)),
           ("NOSSA SENHORA DO SOCORRO", 1, (QUIMICO,)), ("CARMOPOLIS", 1, (PETROLEO,)),
           ("ITABAIANA", 1, (AGROFLORESTAL,)), ("JAPARATUBA", 1, (PETROLEO,))),
    "MA": (("SAO LUIS", 3.1, (URBANO, PETROLEO)), ("ACAILANDIA", 1, (METALURGICO,)),
           ("IMPERATRIZ", 2, (AGROFLORESTAL,)), ("BALSAS", 1, (AGROFLORESTAL,)), ("CAXIAS", 1, (AGROFLORESTAL,)),
           ("BACABAL", 1, (AGROFLORESTAL,)), ("GRAJAU", 1, (MINERACAO,))),
    "PI": (("TERESINA", 2.5, (URBANO,)), ("PARNAIBA", 1, (PETROLEO,)), ("URUCUI", 1, (AGROFLORESTAL,)),
           ("PICOS", 1, (AGROFLORESTAL,)), ("FLORIANO", 1, (AGROFLORESTAL,)), ("BOM JESUS", 1, (AGROFLORESTAL,))),
    "PA": (("BELEM", 11.5, (URBANO, PETROLEO)), ("BARCARENA", 2, (METALURGICO, PETROLEO)),
           ("ITAITUBA", 2, (MINERACAO,)), ("MARABA", 1, (METALURGICO, MINERACAO)),
           ("SANTAREM", 1, (PETROLEO, AGROFLORESTAL)), ("PARAUAPEBAS", 1, (MINERACAO,)),
           ("ALTAMIRA", 1, (MINERACAO, AGROFLORESTAL)), ("PARAGOMINAS", 1, (AGROFLORESTAL, MINERACAO)),
           ("CASTANHAL", 1, (AGROFLORESTAL,)), ("REDENCAO", 1, (AGROFLORESTAL,)), ("ORIXIMINA", 1, (MINERACAO,)),
           ("NOVO PROGRESSO", 1, (MINERACAO, AGROFLORESTAL)), ("ABAETETUBA", 1, (AGROFLORESTAL,)),
           ("JACAREACANGA", 1, (MINERACAO,)), ("TAILANDIA", 1, (AGROFLORESTAL,))),
    "AM": (("MANAUS", 4.8, (URBANO, QUIMICO)), ("PRESIDENTE FIGUEIREDO", 1, (MINERACAO,)), ("COARI", 1, (PETROLEO,)),
           ("ITACOATIARA", 1, (PETROLEO,)), ("PARINTINS", 1, (AGROFLORESTAL,)), ("MANACAPURU", 1, (AGROFLORESTAL,)),
           ("HUMAITA", 1, (MINERACAO, AGROFLORESTAL)), ("TEFE", 1, (AGROFLORESTAL,)),
           ("SAO GABRIEL DA CACHOEIRA", 1, (MINERACAO,)), ("MAUES", 1, (AGROFLORESTAL,))),
    "RO": (("PORTO VELHO", 2, (URBANO, MINERACAO)), ("ARIQUEMES", 1, (MINERACAO,)), ("JI PARANA", 1, (AGROFLORESTAL,)),
           ("VILHENA", 1, (AGROFLORESTAL,)), ("CACOAL", 1, (AGROFLORESTAL,)), ("CANDEIAS DO JAMARI", 1, (MINERACAO,))),
    "AC": (("RIO BRANCO", 2.5, (URBANO,)), ("CRUZEIRO DO SUL", 1, (AGROFLORESTAL,)),
           ("SENA MADUREIRA", 1, (AGROFLORESTAL,)), ("TARAUACA", 1, (AGROFLORESTAL,)), ("FEIJO", 1, (AGROFLORESTAL,)),
           ("BRASILEIA", 1, (AGROFLORESTAL,))),
    "RR": (("BOA VISTA", 3, (URBANO,)), ("CARACARAI", 1, (MINERACAO,)), ("MUCAJAI", 1, (MINERACAO,)),
           ("RORAINOPOLIS", 1, (AGROFLORESTAL,)), ("ALTO ALEGRE", 1, (MINERACAO,)), ("CANTA", 1, (AGROFLORESTAL,))),
    "AP": (("MACAPA", 3.4, (URBANO,)), ("SANTANA", 1, (PETROLEO,)), ("LARANJAL DO JARI", 1, (AGROFLORESTAL, MINERACAO)),
           ("OIAPOQUE", 1, (MINERACAO,)), ("PEDRA BRANCA DO AMAPARI", 1, (MINERACAO,)),
           ("VITORIA DO JARI", 1, (AGROFLORESTAL,))),
    "TO": (("PALMAS", 2.7, (URBANO,)), ("ARAGUAINA", 1, (AGROFLORESTAL,)), ("GURUPI", 1, (AGROFLORESTAL,)),
           ("PORTO NACIONAL", 1, (AGROFLORESTAL,)), ("PARAISO DO TOCANTINS", 1, (AGROFLORESTAL,)),
           ("DIANOPOLIS", 1, (MINERACAO,))),
    "GO": (("GOIANIA", 6.7, (URBANO,)), ("CATALAO", 1, (MINERACAO,)), ("RIO VERDE", 1, (AGROFLORESTAL,)),
           ("ANAPOLIS", 1, (QUIMICO,)), ("JATAI", 1, (AGROFLORESTAL,)), ("ITUMBIARA", 1, (AGROFLORESTAL,)),
           ("NIQUELANDIA", 1, (MINERACAO,)), ("CRIXAS", 1, (MINERACAO,)), ("BARRO ALTO", 1, (MINERACAO, METALURGICO)),
           ("LUZIANIA", 1, (AGROFLORESTAL,)), ("MINEIROS", 1, (AGROFLORESTAL,)), ("SENADOR CANEDO", 1, (PETROLEO,))),
    "MT": (("CUIABA", 7, (URBANO,)), ("RONDONOPOLIS", 1, (AGROFLORESTAL,)), ("PEIXOTO DE AZEVEDO", 1, (MINERACAO,)),
           ("SINOP", 1, (AGROFLORESTAL,)), ("SORRISO", 1, (AGROFLORESTAL,)),
           ("LUCAS DO RIO VERDE", 1, (AGROFLORESTAL,)), ("PRIMAVERA DO LESTE", 1, (AGROFLORESTAL,)),
           ("ALTA FLORESTA", 1, (MINERACAO, AGROFLORESTAL)), ("PONTES E LACERDA", 1, (MINERACAO,)),
           ("BARRA DO GARCAS", 1, (AGROFLORESTAL,)), ("POCONE", 1, (MINERACAO,)),
           ("TANGARA DA SERRA", 1, (AGROFLORESTAL,))),
    "MS": (("CAMPO GRANDE", 3.1, (URBANO, AGROFLORESTAL)), ("TRES LAGOAS", 1, (AGROFLORESTAL,)),
           ("CORUMBA", 1, (MINERACAO,)), ("DOURADOS", 1, (AGROFLORESTAL,)), ("RIBAS DO RIO PARDO", 1, (AGROFLORESTAL,)),
           ("PONTA PORA", 1, (AGROFLORESTAL,)), ("NAVIRAI", 1, (AGROFLORESTAL,)), ("MARACAJU", 1, (AGROFLORESTAL,))),
    "DF": (("BRASILIA", 1, (URBANO,)),),
}
SEMENTE_GEOGRAFIA = "ECOSEC GEOGRAFIA 2026"          # diferente da SEMENTE do acervo, por construção
# rodovias que de fato cortam cada UF (o km é sorteado)
RODOVIAS = {
    "SP": ("SP 055", "SP 330", "SP 280", "BR 116"), "MG": ("BR 381", "BR 040", "BR 262"),
    "RJ": ("BR 116", "BR 040", "BR 101"), "PR": ("BR 277", "BR 376", "PR 423"), "RS": ("BR 386", "BR 116", "RS 118"),
    "BA": ("BA 093", "BR 324", "BA 535"), "GO": ("BR 060", "BR 153", "GO 330"), "SC": ("BR 101", "BR 470", "SC 108"),
    "PE": ("BR 232", "BR 101", "PE 060"), "ES": ("BR 101", "BR 262", "ES 010"),
    "PA": ("BR 316", "PA 150", "BR 230"), "AM": ("BR 174", "AM 010", "BR 319"), "RO": ("BR 364", "BR 425"),
    "RR": ("BR 174", "BR 401"), "AP": ("BR 156", "BR 210"), "AC": ("BR 364", "BR 317"), "TO": ("BR 153", "TO 050"),
    "MT": ("BR 163", "BR 364", "BR 070"), "MS": ("BR 163", "BR 262", "BR 267"), "DF": ("BR 040", "DF 001"),
    "MA": ("BR 135", "BR 222", "BR 010"), "CE": ("BR 116", "CE 040", "BR 222"), "AL": ("BR 101", "AL 101"),
    "RN": ("BR 304", "BR 101"), "PB": ("BR 230", "BR 101"), "SE": ("BR 101", "SE 065"), "PI": ("BR 343", "BR 316"),
}

AREA, CLASSE_I, RADIOATIVO = "AREA CONTAMINADA", "CLASSE I NBR 10004", "REJEITO RADIOATIVO CNEN"

# Catálogo da camada causal. Subclasses CNAE pela CONCLA/IBGE: só a de
# AG-08 (8640-2/11) foi conferida; as demais seguem a conferir (integrante 3).
ATIVIDADES = (
    AtividadeGeradora(
        "AG-01", "POSTOS DE COMBUSTIVEIS",
        "REVENDA VAREJISTA DE COMBUSTIVEIS COM TANQUES SUBTERRANEOS (SASC). OS PASSIVOS VEM DE VAZAMENTO DE "
        "TANQUES E LINHAS, DA AREA DE ABASTECIMENTO E DA TROCA DE OLEO",
        "4731-8/00", "BTEX E BENZENO NA AGUA SUBTERRANEA; PAH E BORRA DE TANQUE SUBTERRANEO; BENZENO NO SOLO SOB "
        "A PISTA", "MAIORIA DO CADASTRO DA CETESB"),
    AtividadeGeradora(
        "AG-02", "QUIMICA E DEFENSIVOS AGRICOLAS",
        "FABRICACAO E FORMULACAO DE PRODUTOS QUIMICOS E AGROTOXICOS, COM ESTOCAGEM DE MATERIAS-PRIMAS E DE "
        "PRODUTOS OBSOLETOS",
        "2051-7/00", "HCH E DDT NO SOLO; PESTICIDAS OBSOLETOS EM TAMBORES; SOLVENTES CLORADOS (PCE, TCE)"),
    AtividadeGeradora(
        "AG-03", "GALVANOPLASTIA",
        "TRATAMENTO E REVESTIMENTO DE METAIS EM BANHOS ELETROLITICOS (CROMO, NIQUEL, ZINCO, CIANETO)",
        "2539-0/02", "LODO GALVANICO COM CROMO HEXAVALENTE; BANHO DE CIANETO EXAURIDO; NIQUEL, ZINCO E COBRE NO "
        "SOLO"),
    AtividadeGeradora(
        "AG-04", "METALURGIA E FUNDICAO",
        "FUNDICAO DE FERRO E ACO E METALURGIA DE NAO FERROSOS, COM FORNOS, PATIOS DE ESCORIA E SUBESTACAO INTERNA",
        "2451-2/00", "ESCORIA COM CHUMBO E CADMIO; OLEO BPF E BORRA OLEOSA DE FORNOS; PCBS NO SOLO DA SUBESTACAO"),
    AtividadeGeradora(
        "AG-05", "ATERRO DE RESIDUOS PERIGOSOS",
        "TRATAMENTO E DISPOSICAO DE RESIDUOS CLASSE I EM CELULAS, LAGOAS DE CHORUME E UNIDADES DE TRATAMENTO",
        "3822-0/00", "CHORUME CLASSE I EM LAGOA; RESIDUOS EM CELULA SEM MANTA"),
    AtividadeGeradora(
        "AG-06", "TRANSFORMADORES COM ASCAREL",
        "MANUTENCAO, REFORMA E DEPOSITO DE TRANSFORMADORES E CAPACITORES COM OLEO ISOLANTE CONTAMINADO POR PCBS",
        "3313-9/01", "ASCAREL EM TRANSFORMADORES; CARCACAS CONTAMINADAS COM PCBS",
        "ASCAREL PROIBIDO DESDE 1981 (PORTARIA MIC/MME/MI 19)"),
    AtividadeGeradora(
        "AG-07", "MINERACAO COM RADIOATIVIDADE NATURAL",
        "EXTRACAO E BENEFICIAMENTO DE MINERIO COM URANIO E TORIO ASSOCIADOS (NORM), PILHAS DE ESTERIL E "
        "GALPOES DE INSUMOS",
        "0725-1/00", "REJEITO COM URANIO E TORIO (NORM); DRENAGEM ACIDA DE PILHA DE ESTERIL; PRODUTOS PERIGOSOS EM "
        "GALPAO"),
    AtividadeGeradora(
        "AG-08", "RADIOTERAPIA E FONTES SELADAS",
        "SERVICOS DE SAUDE E PESQUISA COM FONTES SELADAS (TELETERAPIA, BRAQUITERAPIA, IRRADIADORES), ALEM DE "
        "PARA-RAIOS RADIOATIVOS RECOLHIDOS",
        "8640-2/11", "FONTE SELADA DE CS-137; FONTE DE CO-60 DE TELETERAPIA; PARA-RAIOS COM AM-241",
        "SUBCLASSE CNAE CONFERIDA (SERVICOS DE RADIOTERAPIA)"),
    AtividadeGeradora(
        "AG-09", "CURTUMES", "CURTIMENTO AO CROMO E BENEFICIAMENTO DE COURO",
        "1510-6/00", "LODO DE CURTIMENTO COM CROMO; BANHO DE CALEIRO COM SULFETO"),
    AtividadeGeradora(
        "AG-10", "REFINO E TERMINAIS DE PETROLEO",
        "REFINO DE PETROLEO E TERMINAIS DE ARMAZENAMENTO E DISTRIBUICAO DE DERIVADOS",
        "1921-7/00; 4681-8/01", "HIDROCARBONETOS EM FASE LIVRE; BORRA DE FUNDO DE TANQUE"),
    AtividadeGeradora(
        "AG-11", "CELULOSE E PAPEL",
        "FABRICACAO DE CELULOSE, COM LAGOAS DE LICOR NEGRO E EFLUENTE E SEDIMENTOS COM ORGANOCLORADOS",
        "1710-9/00", "LICOR NEGRO EM LAGOA DESATIVADA; DIOXINAS E FURANOS EM SEDIMENTO"),
    AtividadeGeradora(
        "AG-12", "LAVANDERIAS E TINTURARIAS", "LAVAGEM A SECO E TINGIMENTO INDUSTRIAL COM SOLVENTES CLORADOS",
        "9601-7/01; 9601-7/02", "PERCLOROETILENO (PCE) NO AQUIFERO; RESIDUO DE DESTILACAO DE SOLVENTE"),
    AtividadeGeradora(
        "AG-13", "GARIMPO DE OURO COM MERCURIO",
        "EXTRACAO DE OURO ALUVIONAR COM AMALGAMACAO POR MERCURIO, EM BALSAS E BARRANCOS",
        "0724-3/01", "MERCURIO EM SEDIMENTO DE GARIMPO; REJEITO DE AMALGAMACAO; BALSA DE GARIMPO ABANDONADA",
        "AMAZONIA LEGAL"),
)
# Bases legais revisadas: MP-01, MP-06, MP-07 e MP-08. Revisar com quem responde pelo
# conteúdo jurídico do grupo antes de publicar.
MOTIVOS = (
    MotivoPermanencia(
        "MP-01", "GERADOR ENCERRADO OU FALIDO",
        "A EMPRESA QUE GEROU O PASSIVO DEIXOU DE EXISTIR OU ESTA EM FALENCIA. A OBRIGACAO ACOMPANHA O IMOVEL E "
        "ALCANCA SUCESSORES E ADQUIRENTES, MAS A COBRANCA PRECISA LOCALIZA-LOS",
        "LEI 6.938/1981, ART. 14, PARAGRAFO 1 (RESPONSABILIDADE OBJETIVA); STJ, SUMULA 623 (NATUREZA PROPTER REM)",
        "COBRAVEL", "IDENTIFICAR SUCESSOR OU PROPRIETARIO ATUAL E NOTIFICAR"),
    MotivoPermanencia(
        "MP-02", "DISPUTA DE RESPONSABILIDADE",
        "PROPRIETARIO, POSSUIDOR, GERADOR E ADQUIRENTE CONTESTAM A QUEM CABE A REMEDIACAO; ENQUANTO ISSO, "
        "NINGUEM EXECUTA",
        "STJ, SUMULA 623 (COBRANCA DE ATUAIS OU ANTERIORES, A ESCOLHA DO CREDOR)",
        "COBRAVEL", "ACOMPANHAMENTO PROCESSUAL; MEDIDA CAUTELAR DE CONTENCAO"),
    MotivoPermanencia(
        "MP-03", "CUSTO DA DESTINACAO",
        "O RESPONSAVEL ESTA IDENTIFICADO E SOLVENTE, MAS ADIA A DESTINACAO POR CAUSA DO CUSTO DO TRATAMENTO; O "
        "RESIDUO SEGUE ARMAZENADO NO LOCAL",
        "ABNT NBR 10004; LEI 12.305/2010", "COBRAVEL", "CRONOGRAMA DE REGULARIZACAO; AUTUACAO SE DESCUMPRIDO"),
    MotivoPermanencia(
        "MP-04", "SEM DESTINADOR LICENCIADO",
        "NAO HA INSTALACAO LICENCIADA EM DISTANCIA VIAVEL PARA AQUELE TIPO DE RESIDUO (EX.: INCINERACAO DE PCBS)",
        "LEI 12.305/2010", "INFRAESTRUTURA", "MAPEAR CAPACIDADE INSTALADA E O VAZIO DE INFRAESTRUTURA"),
    MotivoPermanencia(
        "MP-05", "SEM DESTINO FINAL NO PAIS",
        "REJEITO RADIOATIVO A ESPERA DO REPOSITORIO NACIONAL DE BAIXO E MEDIO NIVEL",
        "LEI 10.308/2001", "INFRAESTRUTURA", "PRIORIZAR NA FILA DO DEPOSITO INTERMEDIARIO"),
    MotivoPermanencia(
        "MP-06", "MATERIAL ORFAO",
        "NENHUM RESPONSAVEL IDENTIFICADO. O PODER PUBLICO AGE DE FORMA SUBSIDIARIA E COBRA DEPOIS, SE ALGUEM FOR "
        "IDENTIFICADO",
        "LEI 12.305/2010, ART. 29 (ATUACAO SUBSIDIARIA DO PODER PUBLICO)",
        "PUBLICO", "PROGRAMA PUBLICO DE REMEDIACAO, PRIORIZADO POR RISCO"),
    MotivoPermanencia(
        "MP-07", "PASSIVO DESCOBERTO DEPOIS",
        "CONTAMINACAO ENCONTRADA ANOS APOS O FIM DA ATIVIDADE (PASSIVO HISTORICO)",
        "STF, TEMA 999 (RE 654.833): REPARACAO CIVIL DE DANO AMBIENTAL E IMPRESCRITIVEL",
        "PUBLICO", "CARACTERIZACAO TECNICA E PROCESSO DE REGULARIZACAO"),
    MotivoPermanencia(
        "MP-08", "MANIFESTO SEM BAIXA",
        "MTR EMITIDO SEM CERTIFICADO DE DESTINACAO FINAL; A CARGA PODE TER SIDO DESVIADA",
        "PORTARIA MMA 280/2020 (MTR NACIONAL E CDF)",
        "FISCALIZACAO", "RASTREAR A CARGA: GERADOR, TRANSPORTADOR E DESTINADOR"),
    MotivoPermanencia(
        "MP-09", "INTERDICAO JUDICIAL OU EMBARGO",
        "AREA SOB ORDEM JUDICIAL OU EMBARGO ADMINISTRATIVO; QUALQUER INTERVENCAO DEPENDE DE AUTORIZACAO",
        "LEI 7.347/1985; DECRETO 6.514/2008, ART. 15-A",
        "COBRAVEL", "CUMPRIR A DECISAO E PEDIR AUTORIZACAO JUDICIAL PARA A COLETA"),
    MotivoPermanencia(
        "MP-10", "AGUARDANDO LICENCA DE REMEDIACAO",
        "PLANO DE INTERVENCAO PROTOCOLADO, A ESPERA DE ANALISE E LICENCA",
        "RESOLUCAO CONAMA 420/2009", "INFRAESTRUTURA", "ACOMPANHAR O PRAZO DO ORGAO AMBIENTAL; CONTENCAO PROVISORIA"),
)

TONELADAS, METROS_CUBICOS = texto.unidade("t"), texto.unidade("m³")

# atividade -> (peso no sorteio, ((substância, classe de risco), ...), motivos mais prováveis,
#               prefixos do nome do gerador). Substâncias com até 34 caracteres: os
#               relatórios cortam o texto nesse tamanho.
PERFIS = {
    "AG-01": (14, (("BTEX EM AGUA SUBTERRANEA", AREA), ("PAH E BORRA DE TANQUE SUBTERRANEO", AREA),
                   ("BENZENO EM SOLO SOB A PISTA", AREA)),
              ("MP-01", "MP-02", "MP-07", "MP-10"), ("AUTO POSTO", "POSTO DE SERVICOS", "COMERCIO DE COMBUSTIVEIS")),
    "AG-02": (5, (("ORGANOCLORADOS HCH DDT EM SOLO", CLASSE_I), ("PESTICIDAS OBSOLETOS EM TAMBORES", CLASSE_I),
                  ("SOLVENTES CLORADOS PCE TCE", AREA)),
              ("MP-03", "MP-04", "MP-08", "MP-09"), ("QUIMICA", "AGROQUIMICA", "INDUSTRIA DE DEFENSIVOS")),
    "AG-03": (5, (("LODO GALVANICO COM CROMO VI", CLASSE_I), ("BANHO DE CIANETO EXAURIDO", CLASSE_I),
                  ("METAIS PESADOS NI ZN CU", AREA)),
              ("MP-01", "MP-03", "MP-08"), ("GALVANICA", "CROMEACAO", "TRATAMENTO DE SUPERFICIES")),
    "AG-04": (4, (("ESCORIA COM CHUMBO E CADMIO", CLASSE_I), ("OLEO BPF E BORRA OLEOSA DE FORNOS", CLASSE_I),
                  ("PCBS EM SOLO DA SUBESTACAO INTERNA", AREA)),
              ("MP-01", "MP-02", "MP-03", "MP-09"), ("FUNDICAO", "METALURGICA", "SIDERURGICA")),
    "AG-05": (3, (("CHORUME CLASSE I EM LAGOA", CLASSE_I), ("RESIDUOS EM CELULA SEM MANTA", CLASSE_I)),
              ("MP-02", "MP-04", "MP-07", "MP-10"), ("CENTRAL DE TRATAMENTO DE RESIDUOS", "ATERRO INDUSTRIAL")),
    "AG-06": (3, (("ASCAREL PCBS EM TRANSFORMADORES", CLASSE_I), ("CARCACAS CONTAMINADAS COM PCBS", CLASSE_I)),
              ("MP-04", "MP-06", "MP-08"), ("ELETROMECANICA", "TRANSFORMADORES", "REFORMADORA DE TRANSFORMADORES")),
    "AG-07": (4, (("REJEITO COM URANIO E TORIO NORM", RADIOATIVO), ("DRENAGEM ACIDA DE PILHA DE ESTERIL", AREA),
                  ("PRODUTOS PERIGOSOS EM GALPAO", CLASSE_I)),
              ("MP-05", "MP-06", "MP-07"), ("MINERACAO", "BENEFICIADORA DE MINERIOS", "ARMAZENS GERAIS")),
    "AG-08": (5, (("FONTE SELADA DE CESIO 137", RADIOATIVO), ("FONTE DE COBALTO 60 DE TELETERAPIA", RADIOATIVO),
                  ("PARA RAIOS COM AMERICIO 241", RADIOATIVO)),
              ("MP-01", "MP-05", "MP-06"), ("CLINICA DE RADIOTERAPIA", "INSTITUTO DE MEDICINA NUCLEAR",
                                            "CENTRO DE ONCOLOGIA")),
    "AG-09": (3, (("LODO DE CURTIMENTO COM CROMO", CLASSE_I), ("BANHO DE CALEIRO COM SULFETO", CLASSE_I)),
              ("MP-01", "MP-03", "MP-09"), ("CURTUME", "INDUSTRIA DE COUROS")),
    "AG-10": (3, (("HIDROCARBONETOS EM FASE LIVRE", AREA), ("BORRA DE FUNDO DE TANQUE", CLASSE_I)),
              ("MP-02", "MP-07", "MP-10"), ("TERMINAL DE ARMAZENAMENTO", "DISTRIBUIDORA DE PETROLEO")),
    "AG-11": (2, (("LICOR NEGRO EM LAGOA DESATIVADA", CLASSE_I), ("DIOXINAS E FURANOS EM SEDIMENTO", AREA)),
              ("MP-02", "MP-04", "MP-10"), ("CELULOSE", "PAPEL E CELULOSE")),
    "AG-12": (3, (("PERCLOROETILENO PCE NO AQUIFERO", AREA), ("RESIDUO DE DESTILACAO DE SOLVENTE", CLASSE_I)),
              ("MP-01", "MP-03", "MP-07"), ("LAVANDERIA INDUSTRIAL", "TINTURARIA")),
    "AG-13": (14, (("MERCURIO EM SEDIMENTO DE GARIMPO", AREA), ("REJEITO DE AMALGAMACAO COM MERCURIO", CLASSE_I),
                  ("BALSA DE GARIMPO ABANDONADA", CLASSE_I)),
              ("MP-06", "MP-07", "MP-09"), ("COOPERATIVA DE GARIMPEIROS", "MINERACAO AURIFERA")),
}

# Unidade de cada classe: área contaminada em m³ de solo, rejeito radioativo em m³, Classe I em t.
# m³ de solo e m³ de rejeito têm a mesma unidade, mas não a mesma natureza: nenhum total soma classes
# diferentes, e nenhum soma m³ com t (acervo/quantidades.py).
UNIDADE_DA_CLASSE = {AREA: METROS_CUBICOS, CLASSE_I: TONELADAS, RADIOATIVO: METROS_CUBICOS}

# Quantidade por (atividade, classe): log-normal truncada. Parâmetro de simulação: ordem de
# grandeza coerente com a atividade, sem fonte estatística.
#   (atividade, classe) -> (mediana, sigma do log, mínimo, máximo), na unidade da classe
QUANTIDADE_POR_PAR = {
    ("AG-01", AREA): (250, 0.8, 15, 4_500),            # posto: m³ de solo sob tanques e pista
    ("AG-02", AREA): (1_400, 0.9, 60, 33_000),
    ("AG-03", AREA): (450, 0.8, 30, 11_000),
    ("AG-04", AREA): (1_100, 0.9, 60, 28_000),
    ("AG-07", AREA): (5_000, 1.0, 300, 110_000),       # drenagem ácida de pilha de estéril
    ("AG-10", AREA): (2_000, 0.9, 80, 45_000),
    ("AG-11", AREA): (1_400, 0.9, 60, 33_000),
    ("AG-12", AREA): (220, 0.8, 15, 5_500),
    ("AG-13", AREA): (6_500, 1.0, 300, 170_000),       # sedimento de garimpo
    ("AG-02", CLASSE_I): (18, 0.9, 0.5, 600),
    ("AG-03", CLASSE_I): (40, 0.8, 1, 800),
    ("AG-04", CLASSE_I): (150, 0.9, 5, 4_000),
    ("AG-05", CLASSE_I): (900, 0.9, 30, 20_000),       # lagoa de chorume, célula sem manta
    ("AG-06", CLASSE_I): (6, 0.8, 0.2, 200),           # ascarel: poucos transformadores
    ("AG-07", CLASSE_I): (30, 0.8, 1, 600),
    ("AG-09", CLASSE_I): (80, 0.8, 2, 2_000),
    ("AG-10", CLASSE_I): (60, 0.8, 2, 1_500),
    ("AG-11", CLASSE_I): (300, 0.9, 10, 8_000),
    ("AG-12", CLASSE_I): (5, 0.8, 0.2, 150),
    ("AG-13", CLASSE_I): (25, 0.9, 0.5, 800),
    ("AG-07", RADIOATIVO): (25, 0.8, 1, 600),          # NORM: volume de rejeito de beneficiamento
    ("AG-08", RADIOATIVO): (0.3, 0.6, 0.02, 3),        # fonte selada com a blindagem
}


def quantidade_de(atividade: str, classe: str, u: float) -> float:
    """Quantil `u` (0..1) da log-normal do par, truncada no intervalo. Recebe o sorteio pronto: consome
    exatamente um número da sequência, como o uniform de antes, e o resto do acervo não muda."""
    mediana, sigma, minimo, maximo = QUANTIDADE_POR_PAR[(atividade, classe)]
    z = NormalDist().inv_cdf(min(max(u, 1e-9), 1 - 1e-9))
    return round(min(max(mediana * math.exp(sigma * z), minimo), maximo), 2)

# nomes para compor razões sociais (o tipo da empresa vem antes)
_NOMES = ("VALE DO PARAIBA", "SERRA DOURADA", "PLANALTO SUL", "RIO CLARO", "TRES BARRAS", "ALTO TIETE",
          "HORIZONTE NOVO", "BANDEIRANTE", "PIONEIRA", "ATLANTICA", "GUARANI", "IPE AMARELO", "CERRADO",
          "MANTIQUEIRA", "IBIRAPUERA", "TAPAJOS", "ITAUNA", "SANTA BARBARA", "SAO GABRIEL", "CRUZEIRO DO SUL",
          "BOA ESPERANCA", "PRIMAVERA", "ESTRELA GUIA", "NOVO RUMO", "AGUA BRANCA", "SERRA DO MAR", "JATOBA",
          "AROEIRA", "PARANAPANEMA", "TOCANTINS")
_SUFIXOS = ("LTDA", "SA", "EIRELI", "LTDA ME")
_PRENOMES = ("JOSE", "MARIA", "ANTONIO", "FRANCISCA", "JOAO", "ANA", "CARLOS", "LUZIA", "PAULO", "RITA",
             "SEBASTIAO", "HELENA", "MANOEL", "TERESA", "RAIMUNDO", "CECILIA")
_SOBRENOMES = ("SILVA", "SANTOS", "OLIVEIRA", "SOUZA", "PEREIRA", "LIMA", "CARVALHO", "FERREIRA", "RODRIGUES",
               "ALMEIDA", "NASCIMENTO", "ARAUJO", "RIBEIRO", "BARBOSA", "MOREIRA", "TEIXEIRA")
_LOGRADOUROS = ("AVENIDA DAS INDUSTRIAS", "RUA DOS METALURGICOS", "ESTRADA DO POLO INDUSTRIAL", "RUA PROJETADA",
                "AVENIDA INDUSTRIAL", "ESTRADA VELHA", "RUA DOS QUIMICOS", "AVENIDA DO CONTORNO")
_COMPLEMENTOS = ("GALPAO {n}", "BLOCO {l}", "LOTE {n}", "QUADRA {n} LOTE {m}", "MODULO {n}", "ARMAZEM {n}")

CATALOGO = (
    # A descrição é a pergunta que o relatório responde. O título fica como no banco (caixa alta, sem
    # acento: a coluna item_acervo.titulo tem CHECK de padrão); o título de exibição está em relatorios.TITULOS
    RelatorioCatalogo("A1-01", "PANORAMA NACIONAL", 1,
                      "Quantos casos ativos há no país, quão graves são e onde se concentram."),
    RelatorioCatalogo("A1-02", "DISTRIBUICAO POR ATIVIDADE E MOTIVO", 1,
                      "De onde vêm os casos e o que impede que sejam resolvidos."),
    RelatorioCatalogo("A1-05", "MAPA DE DENSIDADE", 1,
                      "Onde estão os casos: o total de cada estado, sem nenhum ponto no mapa."),
    RelatorioCatalogo("A2-01", "FICHAS DAS PENDENCIAS", 2,
                      "Quais casos tratar primeiro, onde estão, quem responde por eles e que ação tomar."),
    RelatorioCatalogo("A2-02", "PENDENCIAS VENCIDAS POR REGIAO", 2,
                      "Quais casos passaram do prazo previsto, há quanto tempo, e o que fazer com cada grupo."),
    RelatorioCatalogo("A2-04", "RASTREIO DE MANIFESTO", 2,
                      "Cargas que saíram com manifesto e não tiveram a chegada confirmada: onde a cadeia se rompeu."),
    RelatorioCatalogo("A3-01", "CONSOLIDADO NACIONAL", 3,
                      "Situação, risco, custódia e custo do passivo nacional, com números exatos e fontes."),
    RelatorioCatalogo("A3-02", "MATRIZ DE CRITICIDADE", 3,
                      "Por que cada caso está no topo da fila: classe × tipo de providência × atraso."),
    RelatorioCatalogo("A3-03", "MAPA DE CALOR GEORREFERENCIADO", 3,
                      "Onde o risco se concentra no país e onde ficam as instalações de custódia."),
)

# Instalações de custódia (fictícias, tipadas 2.8). Símbolos no mapa do N3:
# ◇ definitivo · □ intermediário · △ NORM · ○ armazenamento inicial.
CUSTODIAS = (
    Custodia("DEPOSITO INTERMEDIARIO SUL", "INTERMEDIARIO", -50.16, -25.10, 0.81, "PR"),
    Custodia("DEPOSITO INTERMEDIARIO SUDESTE", "INTERMEDIARIO", -45.80, -21.60, 0.94, "MG"),
    Custodia("DEPOSITO INTERMEDIARIO NORDESTE", "INTERMEDIARIO", -39.60, -10.40, 0.58, "BA"),
    Custodia("DEPOSITO INTERMEDIARIO NORTE", "INTERMEDIARIO", -49.10, -2.30, 0.71, "PA"),
    Custodia("DEPOSITO DEFINITIVO SUPERFICIAL CENTRO OESTE", "DEFINITIVO", -48.90, -15.90, 1.00, "GO"),
    Custodia("ARMAZEM DE NORM DO QUADRILATERO", "NORM", -44.20, -19.40, 0.76, "MG"),
    Custodia("ARMAZENAMENTO INICIAL LITORAL SUDESTE", "INICIAL", -43.40, -22.80, 0.63, "RJ"),
)
TIPOS_CUSTODIA = ("DEFINITIVO", "INTERMEDIARIO", "NORM", "INICIAL")
SIMBOLO_CUSTODIA = {"DEFINITIVO": "◇", "INTERMEDIARIO": "□", "NORM": "△", "INICIAL": "○"}

# Catálogo de eventos: anotações dos gráficos e efeitos do gerador.
EVENTOS = (
    EventoRegulatorio(date(2009, 12, 28), "CONAMA 420", "RESOLUCAO CONAMA 420/2009: VALORES ORIENTADORES E "
                      "GERENCIAMENTO DE AREAS CONTAMINADAS", (AREA,), "ANOTACAO", "RESOLUCAO CONAMA 420/2009",
                      "CONFIRMADO"),
    EventoRegulatorio(date(2010, 8, 2), "PNRS LEI 12305", "POLITICA NACIONAL DE RESIDUOS SOLIDOS", (CLASSE_I,),
                      "ENTRADAS", "LEI 12.305/2010", "CONFIRMADO"),
    EventoRegulatorio(date(2013, 6, 5), "DECRETO SP 59263", "REGULAMENTO PAULISTA DE AREAS CONTAMINADAS (CLASSES "
                      "AP, AS, AC, AME, AR)", (AREA,), "ANOTACAO", "DECRETO ESTADUAL 59.263/2013", "CONFIRMADO"),
    EventoRegulatorio(date(2020, 3, 11), "PANDEMIA", "PANDEMIA DE COVID-19: QUEDA DA ATIVIDADE INDUSTRIAL E DAS "
                      "REMEDIACOES", (CLASSE_I, AREA), "AMBOS", None,
                      "CONFIRMADO"),
    EventoRegulatorio(date(2021, 1, 1), "MTR NACIONAL", "MANIFESTO DE TRANSPORTE DE RESIDUOS OBRIGATORIO EM TODO O "
                      "PAIS", (CLASSE_I,), "AMBOS", "PORTARIA MMA 280/2020", "CONFIRMADO"),
    EventoRegulatorio(date(2022, 4, 1), "RESOLUCAO CNEN 293", "VEDACAO DO ARMAZENAMENTO POR TEMPO INDETERMINADO DE "
                      "FONTE FORA DE USO NA INSTALACAO", (RADIOATIVO,), "AMBOS", "RESOLUCAO CNEN 293/2022",
                      "CONFIRMADO"),
)


# ---------------------------------------------------------------- geografia
@dataclass(frozen=True)
class Municipio:
    nome: str
    uf: str
    ibge: int
    aneis: tuple                 # np.ndarray (N, 2) float32 por anel: só os que ficam no continente
    areas: tuple
    cep_prefixos: tuple
    bairros: tuple


@lru_cache(maxsize=1)
def geografia() -> tuple[np.ndarray, dict[str, tuple[Municipio, ...]]]:
    """(contorno do país, municípios por UF), lidos do JSON do projeto."""
    dados = json.loads(ARQUIVO_GEOGRAFIA.read_text(encoding="utf-8"))
    pais = np.array(dados["pais"], np.float32)
    municipios = {}
    for uf, lista in dados["municipios"].items():
        itens = []
        for m in lista:
            aneis = []
            for anel in m["poligonos"]:
                pontos = np.array(anel, np.float32)
                centro = pontos.mean(axis=0)
                # Vitória inclui a Ilha da Trindade, a 1.100 km da costa: anel longe do continente não conta.
                # Perto da costa vale (Cabedelo/PB é uma península que o contorno simplificado deixa de fora).
                if cv2.pointPolygonTest(pais, (float(centro[0]), float(centro[1])), True) >= -DISTANCIA_CONTINENTE:
                    aneis.append(pontos)
            itens.append(Municipio(m["nome"], uf, m["ibge"], tuple(aneis),
                                   tuple(float(cv2.contourArea(a)) for a in aneis),
                                   tuple(m["cep_prefixos"]), tuple(m["bairros"])))
        municipios[uf] = tuple(itens)
    return pais, municipios


@lru_cache(maxsize=1)
def divisas_uf() -> dict[str, tuple]:
    """Polígonos (anéis externos) de cada UF, da malha do IBGE: as divisas do mapa interativo."""
    dados = json.loads(ARQUIVO_GEOGRAFIA.read_text(encoding="utf-8"))
    return {uf: tuple(np.array(anel, np.float32) for anel in aneis) for uf, aneis in dados.get("ufs", {}).items()}


def ponto_no_municipio(rng: random.Random, m: Municipio) -> tuple[float, float]:
    """(lon, lat) estritamente dentro do polígono do município (a MARGEM_DIVISA da divisa) e junto ao contorno
    do país (o contorno é simplificado: na costa, a cidade real pode passar dele por até TOLERANCIA_CONTORNO)."""
    pais, _ = geografia()
    anel = rng.choices(m.aneis, weights=m.areas)[0]
    (lon_min, lat_min), (lon_max, lat_max) = anel.min(axis=0), anel.max(axis=0)
    for tentativa in range(2000):
        margem = MARGEM_DIVISA if tentativa < 1500 else 0.0     # município minúsculo: aceita sem margem
        lon, lat = round(rng.uniform(lon_min, lon_max), 5), round(rng.uniform(lat_min, lat_max), 5)
        if (cv2.pointPolygonTest(anel, (lon, lat), True) >= margem
                and cv2.pointPolygonTest(pais, (lon, lat), True) >= -TOLERANCIA_CONTORNO):
            return lon, lat
    raise RuntimeError(f"Não foi possível sortear um ponto em {m.nome}/{m.uf}.")


# ---------------------------------------------------------------- composição
def _peso_na_uf(atividade: str, uf: str) -> float:
    afinidade = AFINIDADE.get(atividade, {})
    if atividade in AFINIDADE_EXCLUSIVA:
        return PERFIS[atividade][0] * afinidade.get(uf, 0.0)
    return PERFIS[atividade][0] * afinidade.get(uf, 1.0)


@lru_cache(maxsize=None)
def _pesos_cidades(uf: str, atividade: str) -> tuple[float, ...]:
    """Peso de cada cidade da UF (na ordem de CIDADES) no sorteio de um caso desta atividade."""
    return tuple(porte * (AFINIDADE_PERFIL if any(atividade in ATIVIDADES_DO_PERFIL[p] for p in perfis) else 1.0)
                 for _, porte, perfis in CIDADES[uf])


@lru_cache(maxsize=None)
def _cidades_da_uf(uf: str) -> tuple[Municipio, ...]:
    """Os municípios de CIDADES, na ordem de lá, com a geografia do JSON."""
    _, municipios = geografia()
    por_nome = {m.nome: m for m in municipios[uf]}
    faltam = [nome for nome, _, _ in CIDADES[uf] if nome not in por_nome]
    if faltam:
        raise RuntimeError(f"{faltam}/{uf} fora de {ARQUIVO_GEOGRAFIA.name}: rode ferramentas.baixar_geografia.")
    return tuple(por_nome[nome] for nome, _, _ in CIDADES[uf])


def participacao_esperada(uf: str) -> dict[str, float]:
    """Fração esperada dos casos da UF em cada cidade, pela conta dos pesos (sem sorteio): a chance de cada atividade
    na UF vezes a parte da cidade no sorteio dela. Nas UFs pequenas a contagem sorteada varia em torno disto."""
    pesos = {a: _peso_na_uf(a, uf) for a in PERFIS}
    total = sum(pesos.values())
    parte = dict.fromkeys((nome for nome, _, _ in CIDADES[uf]), 0.0)
    for atividade, peso in pesos.items():
        cidades = _pesos_cidades(uf, atividade)
        for (nome, _, _), c in zip(CIDADES[uf], cidades):
            parte[nome] += peso / total * c / sum(cidades)
    return parte


def semente_geografia(codigo: str) -> int:
    """Semente própria da geografia de cada caso: SHA-256 do código (estável entre execuções e máquinas)."""
    return int.from_bytes(hashlib.sha256(f"{SEMENTE_GEOGRAFIA}:{codigo}".encode("utf-8")).digest()[:8], "big")


def _empresa(rng, tipo: str) -> str:
    return f"{tipo} {rng.choice(_NOMES)} {rng.choice(_SUFIXOS)}"


def _pessoa(rng) -> str:
    return f"{rng.choice(_PRENOMES)} {rng.choice(_SOBRENOMES)} {rng.choice(_SOBRENOMES)}"


def _bairro(rng, m: Municipio) -> str:
    industriais = [b for b in m.bairros if any(p in b for p in ("INDUSTRIAL", "DISTRITO", "FABRIL", "PORTO"))]
    if industriais and rng.random() < 0.5:
        return rng.choice(industriais)
    return rng.choice(m.bairros) if m.bairros else "CENTRO"


def _endereco(rng, uf: str) -> tuple[str, str, str | None]:
    """(logradouro, número, complemento)."""
    sorteio = rng.random()
    if sorteio < 0.3:
        return f"RODOVIA {rng.choice(RODOVIAS[uf])} KM {rng.randint(2, 380)}", "S/N", None
    logradouro = rng.choice(_LOGRADOUROS)
    numero = "S/N" if rng.random() < 0.1 else str(rng.randint(10, 4999))
    complemento = None
    if rng.random() < 0.6:
        complemento = rng.choice(_COMPLEMENTOS).format(n=rng.randint(1, 24), m=rng.randint(1, 40),
                                                       l=rng.choice("ABCDEF"))
    return logradouro, numero, complemento


class _Rascunho:
    """Pendência em montagem: atributos sorteados primeiro, datas depois (pela linha de geração)."""
    __slots__ = ("campos", "linha", "entrada", "saida")

    def __init__(self, campos: dict, linha: str):
        self.campos, self.linha, self.entrada, self.saida = campos, linha, 0.0, None


def _ano_fracionario(d: date) -> float:
    inicio = date(d.year, 1, 1)
    return d.year + (d - inicio).days / (date(d.year + 1, 1, 1) - inicio).days


def _data(ano: float) -> date:
    inteiro = int(ano)
    inicio = date(inteiro, 1, 1)
    return inicio + timedelta(days=int((ano - inteiro) * (date(inteiro + 1, 1, 1) - inicio).days))


def _parametros_geracao() -> tuple[int, str]:
    from ecosec.configuracao import carregar
    g = carregar().secao("geracao")
    return int(g["quantidade"]), str(g["modo"])


def gerar(quantidade: int | None = None, modo: str | None = None) -> tuple[list[Pendencia], list[Responsavel]]:
    """O acervo inteiro. Sem argumentos, usa [geracao] do ecosec.toml (quantidade e modo)."""
    if quantidade is None or modo is None:
        padrao_q, padrao_m = _parametros_geracao()
        quantidade, modo = quantidade or padrao_q, modo or padrao_m
    pendencias, responsaveis = _gerar(int(quantidade), modo)
    return list(pendencias), list(responsaveis)


@lru_cache(maxsize=4)
def _gerar(quantidade: int, modo: str) -> tuple[tuple, tuple]:
    rng = random.Random(SEMENTE)
    ufs = list(PESO_UF)
    atividades = list(PERFIS)
    rascunhos, responsaveis = [], []
    for i in range(1, quantidade + 1):
        uf = rng.choices(ufs, weights=[PESO_UF[u] for u in ufs])[0]
        ag = rng.choices(atividades, weights=[_peso_na_uf(a, uf) for a in atividades])[0]
        _, substancias, motivos, tipos_gerador = PERFIS[ag]
        substancia, classe = rng.choice(substancias)
        radioativo = classe == RADIOATIVO
        # destino final no país (MP-05) só existe para rejeito radioativo (CNEN); manifesto (MP-08), para resíduo
        mp = rng.choice([m for m in motivos if (radioativo or m != "MP-05") and (classe == CLASSE_I or m != "MP-08")]
                        or [m for m in motivos if m not in ("MP-05", "MP-08")])
        codigo = f"PD-{i:04d}"
        # geografia com gerador próprio: a cidade, o ponto, o endereço, o bairro e o CEP não consomem a
        # sequência do acervo; mudar as cidades não muda classe, motivo, datas nem score
        geo = random.Random(semente_geografia(codigo))
        municipio = geo.choices(_cidades_da_uf(uf), weights=_pesos_cidades(uf, ag))[0]
        lon, lat = ponto_no_municipio(geo, municipio)
        logradouro, numero, complemento = _endereco(geo, uf)
        rascunhos.append(_Rascunho(dict(
            codigo=codigo, substancia=substancia, classe_risco=classe,
            quantidade=quantidade_de(ag, classe, rng.random()),
            unidade=UNIDADE_DA_CLASSE[classe], uf=uf, municipio=municipio.nome,
            logradouro=logradouro, numero=numero, complemento=complemento, bairro=_bairro(geo, municipio),
            cep=geo.choice(municipio.cep_prefixos) + f"{geo.randint(0, 999):03d}",
            latitude=lat, longitude=lon, atividade=ag, motivo=mp), series.linha_de(ag, classe, mp)))
        # cadeia de responsabilidade (camada causal)
        responsaveis.append(Responsavel(codigo, _empresa(rng, rng.choice(tipos_gerador)), "GERADOR_ORIGINAL",
                                        "FALIDA" if mp == "MP-01" else "ATIVA"))
        if mp == "MP-01" and rng.random() < 0.6:
            responsaveis.append(Responsavel(codigo, _empresa(rng, "PARTICIPACOES"), "SUCESSOR", "ATIVA"))
        if rng.random() < 0.7:
            pessoa_fisica = rng.random() < 0.35
            nome = _pessoa(rng) if pessoa_fisica else _empresa(rng, "EMPREENDIMENTOS IMOBILIARIOS")
            # pessoa física identificada: dado pessoal de terceiro -> só a custódia (N3) vê
            responsaveis.append(Responsavel(codigo, nome, "PROPRIETARIO_ATUAL", "ATIVA",
                                            3 if pessoa_fisica else 2))
        if mp == "MP-08":
            responsaveis.append(Responsavel(codigo, _empresa(rng, "TRANSPORTES RODOQUIMICOS"), "TRANSPORTADOR",
                                            "ATIVA"))
            responsaveis.append(Responsavel(codigo, _empresa(rng, "AMBIENTAL TRATAMENTO DE RESIDUOS"),
                                            "DESTINADOR", "SUSPENSA"))
    _datar(rascunhos, modo, random.Random(SEMENTE + 1))
    return tuple(_montar(r, random.Random(SEMENTE + 2 + n)) for n, r in enumerate(rascunhos)), tuple(responsaveis)


def _datar(rascunhos, modo: str, rng: random.Random) -> None:
    """Entradas pela forma λ de cada linha e saídas pelo risco calibrado."""
    ultima_entrada = _ano_fracionario(DATA_BASE - timedelta(days=30))
    data_base = _ano_fracionario(DATA_BASE - timedelta(days=10))       # folga para as etapas caberem antes
    anos = range(series.INICIO_SERIE, DATA_BASE.year + 1)
    parcial = ultima_entrada - DATA_BASE.year                           # fração do último ano com entradas
    por_linha: dict[str, list] = {}
    for r in rascunhos:
        por_linha.setdefault(r.linha, []).append(r)
    configuradas = saidas.configuradas()
    for nome in sorted(por_linha):
        linha, registros = series.LINHAS[nome], por_linha[nome]
        rng.shuffle(registros)
        herdados = round(len(registros) * linha.herdado)
        novos = len(registros) - herdados
        pesos = {a: series.intensidade(linha, a + 0.5) * (parcial if a == DATA_BASE.year else 1.0) for a in anos}
        soma = sum(pesos.values()) or 1.0
        esperado = {a: novos * w / soma for a, w in pesos.items()}
        if modo == "poisson":                                           # Poisson condicionado ao total: multinomial
            sorteados = rng.choices(list(esperado), weights=list(esperado.values()), k=novos) if novos else []
            contagem = {a: sorteados.count(a) for a in anos}
        else:
            contagem = fluxos.contagens_sistematicas(esperado, rng)
        fila = iter(registros)
        for _ in range(herdados):
            next(fila).entrada = rng.uniform(series.INICIO_HERDADO, series.INICIO_SERIE)
        for ano in anos:
            for _ in range(contagem[ano]):
                next(fila).entrada = rng.uniform(ano, min(ano + 1.0, ultima_entrada))
        saida = saidas.calibrar_risco_base(esperado, configuradas[nome], herdados)
        _, fluxo, _ = saidas.calibrar(esperado, saida, herdados)
        fluxo[DATA_BASE.year] *= data_base - DATA_BASE.year             # o último ano vai só até a data-base
        fluxos.sortear_saidas(registros, fluxos.contagens(fluxo, rng, modo), rng, data_base,
                              configuradas[nome].latencia)


def _montar(r: _Rascunho, rng: random.Random) -> Pendencia:
    """Datas e etapas a partir de entrada/saída; a data de encerramento é a da etapa final."""
    nome_ciclo = ciclo.ciclo_da_linha(r.linha)
    etapas_ciclo, medianas, _ = ciclo.CICLOS[nome_ciclo]
    datas = ciclo.encaixar_etapas(rng, etapas_ciclo, medianas, ciclo.SIGMA, r.entrada, r.saida,
                                  _ano_fracionario(DATA_BASE))
    etapas, anterior = [], None
    for nome, ano in datas:                                             # datas estritamente crescentes, em dias
        dia = _data(ano)
        if anterior is not None and dia <= anterior:
            dia = anterior + timedelta(days=1)
        etapas.append((nome, dia))
        anterior = dia
    encerrada = r.saida is not None
    if not encerrada:                                                   # ativa: nada na data-base ou depois
        etapas = [e for e in etapas if e[1] < DATA_BASE] or etapas[:1]
    identificacao = etapas[0][1]
    return Pendencia(**r.campos, data_identificacao=identificacao,
                     prazo_coleta=identificacao + timedelta(days=rng.randint(240, 1500)),
                     situacao=ciclo.situacao(nome_ciclo, etapas, encerrada),
                     data_encerramento=etapas[-1][1] if encerrada else None,
                     etapa_atual=etapas[-1][0], etapas=tuple(etapas))


def custodia_de(p: Pendencia) -> Custodia | None:
    """Onde o rejeito está guardado (derivado, não armazenado): fonte recolhida vai ao depósito intermediário
    mais próximo; o NORM legado fica no armazém de NORM; o resto está IN SITU (None)."""
    if p.classe_risco != RADIOATIVO:
        return None
    if p.atividade == "AG-08" and p.data_encerramento is not None:
        candidatas = [c for c in CUSTODIAS if c.tipo == "INTERMEDIARIO"]
        return min(candidatas, key=lambda c: (c.longitude - p.longitude) ** 2 + (c.latitude - p.latitude) ** 2)
    if p.atividade == "AG-07":
        return next(c for c in CUSTODIAS if c.tipo == "NORM")
    return None


def ocupacao_em(c: Custodia, ano: int, pendencias) -> float:
    """Ocupação da custódia no fim de `ano`: a da data-base, proporcional ao que já tinha entrado até lá.
    O depósito definitivo (estoque herdado de Goiânia, 1987) não muda."""
    if c.tipo == "DEFINITIVO":
        return c.ocupacao
    guardadas = [p for p in pendencias if custodia_de(p) is c]
    if not guardadas:
        return c.ocupacao
    entrada = lambda p: p.data_encerramento or p.data_identificacao            # noqa: E731
    ate = sum(entrada(p) <= date(ano, 12, 31) for p in guardadas)
    base = 0.35 * c.ocupacao                                                    # o que já estava lá antes da série
    return round(base + (c.ocupacao - base) * ate / len(guardadas), 3)
