"""Baixa uma vez a geografia do acervo e grava em ecosec/acervo/dados/geografia.json.

    .venv\\Scripts\\python.exe -m ferramentas.baixar_geografia

O sistema não depende de internet: o gerador do acervo lê só o JSON, que fica no
projeto. Esta ferramenta existe para o arquivo ser reprodutível e conferível.

Fontes oficiais:
  - IBGE, API de localidades (código de cada município) e API de malhas
    (polígono do município, qualidade intermediária; contorno do país e das
    UFs, mínima: as divisas do mapa interativo);
  - ViaCEP: prefixos de CEP (5 dígitos) e bairros reais de cada município. O
    logradouro do acervo continua genérico ("AVENIDA DAS INDUSTRIAS"): o CEP e o
    bairro dão verossimilhança sem apontar um endereço que exista.
"""
import gzip
import json
import sys
import time
import urllib.parse
import urllib.request

from ecosec.configuracao import RAIZ_PROJETO
from ecosec.dominio import texto

DESTINO = RAIZ_PROJETO / "ecosec" / "acervo" / "dados" / "geografia.json"
IBGE = "https://servicodados.ibge.gov.br/api"
CASAS = 4                               # ~11 m: sobra precisão para um mapa nacional

# A capital e os polos industriais, minerários e agrícolas de cada UF (nomes oficiais do IBGE), a capital primeiro.
# 295 cidades, de 6 a 30 por UF, proporcionais aos casos dela (eram 90: 5, 4 e 3 por região);
# o DF tem um município só. O perfil e o porte de cada cidade ficam no gerador (ecosec/acervo/sinteticos.py, CIDADES).
MUNICIPIOS = {
    "SP": ("São Paulo", "Cubatão", "Paulínia", "São Bernardo do Campo", "Campinas", "São José dos Campos", "Sorocaba",
           "Ribeirão Preto", "Santos", "Piracicaba", "Limeira", "Franca", "São José do Rio Preto",
           "Presidente Prudente", "Araraquara", "Americana", "Taubaté", "Jacareí", "Sertãozinho", "Santa Gertrudes",
           "Ourinhos", "Marília", "Araçatuba", "São Carlos", "Barretos", "Lençóis Paulista", "Itapeva", "Mogi Guaçu"),
    "MG": ("Belo Horizonte", "Contagem", "Ipatinga", "Itabira", "Uberlândia", "Juiz de Fora", "Betim", "Montes Claros",
           "Uberaba", "Governador Valadares", "Sete Lagoas", "Divinópolis", "Ouro Preto", "João Monlevade", "Congonhas",
           "Patos de Minas", "Itabirito", "Varginha", "Pouso Alegre", "Teófilo Otoni", "Unaí", "Três Marias", "Itajubá",
           "Lavras", "Pirapora"),
    "RJ": ("Rio de Janeiro", "Duque de Caxias", "Volta Redonda", "Campos dos Goytacazes", "Resende", "Macaé", "Itaguaí",
           "Barra Mansa", "Niterói", "Petrópolis", "Nova Friburgo", "São João da Barra", "Teresópolis", "Seropédica",
           "Belford Roxo", "Rio das Ostras", "Itaperuna", "Porto Real", "Valença", "Cantagalo"),
    "PR": ("Curitiba", "Araucária", "Ponta Grossa", "Londrina", "Maringá", "Cascavel", "Paranaguá",
           "São José dos Pinhais", "Guarapuava", "Toledo", "Telêmaco Borba", "Apucarana", "Umuarama", "Campo Mourão",
           "Arapongas", "Francisco Beltrão", "Pato Branco", "Rio Branco do Sul"),
    "RS": ("Porto Alegre", "Canoas", "Triunfo", "Santa Cruz do Sul", "Caxias do Sul", "Rio Grande", "Pelotas",
           "Novo Hamburgo", "Passo Fundo", "Santa Maria", "Gravataí", "Charqueadas", "Estância Velha", "Candiota",
           "Bento Gonçalves", "Ijuí", "Uruguaiana"),
    "BA": ("Salvador", "Camaçari", "Candeias", "Feira de Santana", "Vitória da Conquista", "Ilhéus", "Juazeiro",
           "Barreiras", "Simões Filho", "Mucuri", "Teixeira de Freitas", "Jacobina", "Brumado",
           "Luís Eduardo Magalhães"),
    "GO": ("Goiânia", "Catalão", "Rio Verde", "Anápolis", "Jataí", "Itumbiara", "Niquelândia", "Crixás", "Barro Alto",
           "Luziânia", "Mineiros", "Senador Canedo"),
    "SC": ("Florianópolis", "Joinville", "Criciúma", "Chapecó", "Blumenau", "Itajaí", "Jaraguá do Sul", "Lages",
           "São Francisco do Sul", "Tubarão", "Concórdia", "Brusque"),
    "PE": ("Recife", "Ipojuca", "Jaboatão dos Guararapes", "Petrolina", "Caruaru", "Cabo de Santo Agostinho", "Goiana",
           "Vitória de Santo Antão", "Garanhuns", "Araripina", "Serra Talhada", "Escada", "Ouricuri"),
    "ES": ("Vitória", "Serra", "Vila Velha", "Aracruz", "Anchieta", "Cachoeiro de Itapemirim", "Linhares", "São Mateus",
           "Colatina", "Nova Venécia", "Viana", "Barra de São Francisco"),
    # Norte: garimpo com mercúrio, mineração, polo industrial de Manaus, alumina em Barcarena
    "PA": ("Belém", "Barcarena", "Itaituba", "Marabá", "Santarém", "Parauapebas", "Altamira", "Paragominas",
           "Castanhal", "Redenção", "Oriximiná", "Novo Progresso", "Abaetetuba", "Jacareacanga", "Tailândia"),
    "AM": ("Manaus", "Presidente Figueiredo", "Coari", "Itacoatiara", "Parintins", "Manacapuru", "Humaitá", "Tefé",
           "São Gabriel da Cachoeira", "Maués"),
    "RO": ("Porto Velho", "Ariquemes", "Ji-Paraná", "Vilhena", "Cacoal", "Candeias do Jamari"),
    "RR": ("Boa Vista", "Caracaraí", "Mucajaí", "Rorainópolis", "Alto Alegre", "Cantá"),
    "AP": ("Macapá", "Santana", "Laranjal do Jari", "Oiapoque", "Pedra Branca do Amapari", "Vitória do Jari"),
    "AC": ("Rio Branco", "Cruzeiro do Sul", "Sena Madureira", "Tarauacá", "Feijó", "Brasiléia"),
    "TO": ("Palmas", "Araguaína", "Gurupi", "Porto Nacional", "Paraíso do Tocantins", "Dianópolis"),
    # Centro-Oeste
    "MT": ("Cuiabá", "Rondonópolis", "Peixoto de Azevedo", "Sinop", "Sorriso", "Lucas do Rio Verde",
           "Primavera do Leste", "Alta Floresta", "Pontes e Lacerda", "Barra do Garças", "Poconé", "Tangará da Serra"),
    "MS": ("Campo Grande", "Três Lagoas", "Corumbá", "Dourados", "Ribas do Rio Pardo", "Ponta Porã", "Naviraí",
           "Maracaju"),
    "DF": ("Brasília",),
    # Nordeste
    "MA": ("São Luís", "Açailândia", "Imperatriz", "Balsas", "Caxias", "Bacabal", "Grajaú"),
    "CE": ("Fortaleza", "Maracanaú", "Caucaia", "São Gonçalo do Amarante", "Juazeiro do Norte", "Sobral", "Crato",
           "Horizonte"),
    "AL": ("Maceió", "Marechal Deodoro", "Arapiraca", "Rio Largo", "Penedo", "Coruripe", "São Miguel dos Campos",
           "Pilar"),
    "RN": ("Natal", "Mossoró", "Parnamirim", "Guamaré", "Macau", "Assú", "Currais Novos"),
    "PB": ("João Pessoa", "Campina Grande", "Cabedelo", "Santa Rita", "Patos", "Caaporã"),
    "SE": ("Aracaju", "Laranjeiras", "Nossa Senhora do Socorro", "Carmópolis", "Itabaiana", "Japaratuba"),
    "PI": ("Teresina", "Parnaíba", "Uruçuí", "Picos", "Floriano", "Bom Jesus"),
}
TERMOS_VIACEP = ("Avenida", "Rua")       # duas buscas já trazem dezenas de CEPs e bairros reais
PARALELO = 6                              # consultas simultâneas (o ViaCEP chega a levar 15 s por resposta)


def _baixar(url: str):
    pedido = urllib.request.Request(url, headers={"Accept-Encoding": "gzip", "User-Agent": "EcoSecurity/0.1"})
    for tentativa in range(3):
        try:
            with urllib.request.urlopen(pedido, timeout=30) as resposta:
                dados = resposta.read()
                if resposta.headers.get("Content-Encoding") == "gzip" or dados[:2] == b"\x1f\x8b":
                    dados = gzip.decompress(dados)
                return json.loads(dados.decode("utf-8"))
        except Exception:                                          # noqa: BLE001, rede instável: tenta de novo
            if tentativa == 2:
                raise
            time.sleep(2)


def _aneis(geometria: dict) -> list[list[list[float]]]:
    """Anéis EXTERNOS do (Multi)Polygon, arredondados. Os buracos não interessam aqui."""
    poligonos = geometria["coordinates"] if geometria["type"] == "MultiPolygon" else [geometria["coordinates"]]
    return [[[round(lon, CASAS), round(lat, CASAS)] for lon, lat in poligono[0]] for poligono in poligonos]


def _viacep(uf: str, cidade: str) -> tuple[list[str], list[str]]:
    prefixos, bairros = set(), set()
    for termo in TERMOS_VIACEP:
        url = f"https://viacep.com.br/ws/{uf}/{urllib.parse.quote(cidade)}/{termo}/json/"
        try:
            registros = _baixar(url)
        except Exception:                                          # noqa: BLE001
            continue
        if not isinstance(registros, list):
            continue
        for r in registros:
            cep = r.get("cep", "").replace("-", "")
            if len(cep) == 8 and cep.isdigit():
                prefixos.add(cep[:5])
            if r.get("bairro"):
                bairros.add(texto.nome(r["bairro"]))
    return sorted(prefixos), sorted(b for b in bairros if b)


def _municipio(uf: str, nome_oficial: str, codigo: int):
    malha = _baixar(f"{IBGE}/v3/malhas/municipios/{codigo}?formato=application/vnd.geo%2Bjson&qualidade=intermediaria")
    prefixos, bairros = _viacep(uf, nome_oficial)
    if not prefixos:
        return None, f"{nome_oficial}/{uf}: ViaCEP sem CEP de logradouro (município de CEP único?)"
    print(f"  {uf} {nome_oficial}: {len(prefixos)} prefixos de CEP, {len(bairros)} bairros", flush=True)
    return {"nome": texto.nome(nome_oficial), "ibge": codigo, "poligonos": _aneis(malha["features"][0]["geometry"]),
            "cep_prefixos": prefixos, "bairros": bairros}, None


def main() -> int:
    """INCREMENTAL: municípios que já estão no arquivo são reaproveitados (polígono, CEP e bairros);
    só os novos são baixados, em paralelo. `--tudo` refaz o arquivo inteiro."""
    from concurrent.futures import ThreadPoolExecutor
    anterior = {}
    if DESTINO.exists() and "--tudo" not in sys.argv:
        dados = json.loads(DESTINO.read_text(encoding="utf-8"))
        anterior = {(uf, m["nome"]): m for uf, lista in dados["municipios"].items() for m in lista}
    saida = {"fontes": {"poligonos": "IBGE API de malhas v3 (municipios: intermediaria; pais e UFs: minima)",
                        "cep_e_bairros": "ViaCEP (prefixo de 5 digitos e bairros reais por municipio)"},
             "pais": [], "ufs": {}, "municipios": {}}
    pais = _baixar(f"{IBGE}/v3/malhas/paises/BR?formato=application/vnd.geo%2Bjson&qualidade=minima")
    saida["pais"] = max(_aneis(pais["features"][0]["geometry"]), key=len)   # o continente; ilhas ficam de fora
    for uf in MUNICIPIOS:
        malha_uf = _baixar(f"{IBGE}/v3/malhas/estados/{uf}?formato=application/vnd.geo%2Bjson&qualidade=minima")
        saida["ufs"][uf] = _aneis(malha_uf["features"][0]["geometry"])
    falhas, pedidos = [], []
    for uf, nomes in MUNICIPIOS.items():
        saida["municipios"][uf] = []
        oficiais = None
        for nome_oficial in nomes:
            chave = (uf, texto.nome(nome_oficial))
            if chave in anterior:
                saida["municipios"][uf].append(anterior[chave])
                continue
            if oficiais is None:
                oficiais = {texto.nome(m["nome"]): m["id"]
                            for m in _baixar(f"{IBGE}/v1/localidades/estados/{uf}/municipios")}
            codigo = oficiais.get(texto.nome(nome_oficial))
            if codigo is None:
                falhas.append(f"{nome_oficial}/{uf}: não está na lista do IBGE")
                continue
            pedidos.append((uf, nome_oficial, codigo))
    print(f"{sum(len(v) for v in saida['municipios'].values())} municípios reaproveitados; {len(pedidos)} a baixar",
          flush=True)
    with ThreadPoolExecutor(PARALELO) as executor:
        for (uf, _, _), (municipio, falha) in zip(pedidos, executor.map(lambda p: _municipio(*p), pedidos)):
            if municipio:
                saida["municipios"][uf].append(municipio)
            else:
                falhas.append(falha)
    DESTINO.parent.mkdir(parents=True, exist_ok=True)
    DESTINO.write_text(json.dumps(saida, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    total = sum(len(v) for v in saida["municipios"].values())
    print(f"\n{total} municípios gravados em {DESTINO} ({DESTINO.stat().st_size / 1024:.0f} KB)")
    for falha in falhas:
        print(f"  [AVISO] {falha}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
