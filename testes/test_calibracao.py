"""Análise da ferramenta de calibração da vivacidade (função pura, sem câmera)."""
from ferramentas.calibrar_vivacidade import Registro, analisar, relatorio

ATUAL = {"vizinhos_olhos": 3, "queda_ear_minima": 0.30, "deslocamento_minimo": 0.25}
PG = __import__("ecosec.visao.gestos", fromlist=["x"]).ParametrosGestos.de_configuracao(
    __import__("ecosec.configuracao", fromlist=["x"]).carregar())


def _etapa(nome, aberturas, centros=None):
    centros = centros or [3.0] * len(aberturas)
    return [Registro(nome, i, True, 1, 100.0, c, ear=e) for i, (e, c) in enumerate(zip(aberturas, centros))]


def _sessao(deslize=0.4, piscadas=5, fechado=0.12):
    parado = [0.30 + 0.01 * ((i % 3) - 1) for i in range(30)]
    piscar = ([0.30] * 6 + [fechado, fechado, 0.29]) * piscadas + [0.30] * 3
    passos = int(deslize * 10) + 1
    return (_etapa("PARADO", parado) + _etapa("PISCAR", piscar)
            + _etapa("ESQUERDA", [0.30] * passos, [3.0 + d / 10 for d in range(passos)])
            + _etapa("DIREITA", [0.30] * passos, [3.0 - d / 10 for d in range(passos)]))


def test_detector_real_reproduzido_sobre_a_gravacao():
    r = analisar(_sessao(), 30.0, ATUAL, PG)
    assert r["detector"] == {"PARADO": 0, "PISCAR": 5, "ESQUERDA": 0, "DIREITA": 0}
    assert "DETECTOR DA PISCADA" in relatorio(r) and not r["avisos"]


def test_piscadas_fracas_geram_aviso_e_sugestao_de_queda():
    r = analisar(_sessao(fechado=0.24), 30.0, ATUAL, PG)              # fecha só 20%: abaixo dos 30%
    assert r["detector"]["PISCAR"] == 0 and any("reduza" in a for a in r["avisos"])
    assert 0.15 <= r["sugerido"]["queda_ear_minima"] < 0.30


def test_sugere_deslocamento_que_a_pessoa_alcanca():
    r = analisar(_sessao(deslize=0.2), 12.0, ATUAL, PG)
    assert r["sugerido"]["deslocamento_minimo"] <= 0.2


def test_fps_baixo_e_avisado():
    assert any("quadros/s" in a for a in analisar(_sessao(), 5.0, ATUAL, PG)["avisos"])


def _com_sinais(nome_sinal, valor_aberto, valor_fechado, piscadas=5):
    """Haar sempre vê olhos (como na câmera real); só o sinal escolhido muda na piscada."""
    neutro = {"energia_crua": 500.0, "escuro": 0.3, "brilho": 0.8}

    def reg(etapa, i, valor):
        sinais = dict(neutro, **{nome_sinal: valor})
        return Registro(etapa, i, True, 1, 100.0, 3.0, **sinais)
    ruido = [valor_aberto * (1 + 0.01 * ((i % 3) - 1)) for i in range(30)]
    parado = [reg("PARADO", i, v) for i, v in enumerate(ruido)]
    piscar = []
    for k in range(piscadas):
        piscar += [reg("PISCAR", 10 * k + i, valor_aberto) for i in range(6)]
        piscar += [reg("PISCAR", 10 * k + 6, valor_fechado), reg("PISCAR", 10 * k + 7, valor_fechado)]
    return parado + piscar


def test_escolhe_o_sinal_que_separa_a_piscada():
    r = analisar(_com_sinais("escuro", 0.30, 0.10), 30.0, ATUAL)
    linha = next(s for s in r["sinais"] if s["sinal"] == "escuro")
    assert linha["piscadas_percebidas"] == 5 and linha["separacao"] > 3
    assert r["melhor_sinal"] == "escuro"
    assert "melhor sinal nesta rodada: escuro" in relatorio(r)


def test_sinal_que_sobe_na_piscada_tambem_e_reconhecido():
    r = analisar(_com_sinais("brilho", 0.80, 1.10), 30.0, ATUAL)
    assert r["melhor_sinal"] == "brilho"


def test_nao_sugere_aumentar_o_deslocamento():
    """Mover mais não dá segurança (deslizar uma foto custa o mesmo): só sugere reduzir."""
    r = analisar(_sessao(deslize=1.0), 30.0, ATUAL)
    assert "deslocamento_minimo" not in r["sugerido"]
