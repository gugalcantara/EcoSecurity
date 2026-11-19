"""Análise da ferramenta de calibração da vivacidade (função pura, sem câmera)."""
import json
from datetime import datetime

from ferramentas.calibrar_vivacidade import (Registro, analisar, caixa_do_registro, deslocamento_maximo,
                                             nome_arquivo, parametros_gravaveis, quadros_por_segundo, relatorio)

ATUAL = {"vizinhos_olhos": 3, "queda_ear_minima": 0.30, "deslocamento_minimo": 0.25}
PG = __import__("ecosec.visao.gestos", fromlist=["x"]).ParametrosGestos.de_configuracao(
    __import__("ecosec.configuracao", fromlist=["x"]).carregar())


def _etapa(nome, aberturas, centros=None):
    centros = centros or [3.0] * len(aberturas)
    # 30 quadros/s: o detector mede a piscada em tempo
    return [Registro(nome, i / 30, True, 1, 100.0, c, ear=e) for i, (e, c) in enumerate(zip(aberturas, centros))]


def _sessao(deslize=0.4, piscadas=5, fechado=0.12):
    parado = [0.30 + 0.01 * ((i % 3) - 1) for i in range(30)]
    # cada piscada é um desafio novo: 0,5 s de olho aberto (16 quadros) antes dela
    piscar = ([0.30] * 16 + [fechado, fechado, 0.29]) * piscadas + [0.30] * 3
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
    assert r["detector"]["PISCAR"] == 0 and any("só 0 piscadas" in a for a in r["avisos"])
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
    assert "melhor sinal nesta medição: escuro" in relatorio(r)


def test_sinal_que_sobe_na_piscada_tambem_e_reconhecido():
    r = analisar(_com_sinais("brilho", 0.80, 1.10), 30.0, ATUAL)
    assert r["melhor_sinal"] == "brilho"


def test_nao_sugere_aumentar_o_deslocamento():
    """Mover mais não dá segurança (deslizar uma foto custa o mesmo): só sugere reduzir."""
    r = analisar(_sessao(deslize=1.0), 30.0, ATUAL)
    assert "deslocamento_minimo" not in r["sugerido"]


# gravação: um arquivo por medição, com os parâmetros em uso e só números
def test_cada_medicao_tem_um_arquivo_proprio():
    assert nome_arquivo(datetime(2026, 11, 19, 14, 5, 9)) == "calibracao_vivacidade_2026-11-19_140509.json"
    assert nome_arquivo(datetime(2026, 11, 19, 14, 5, 9)) != nome_arquivo(datetime(2026, 11, 19, 14, 5, 10))


def test_parametros_gravados_bastam_para_reanalisar_a_serie():
    gravados = parametros_gravaveis(PG)
    json.dumps(gravados)
    for chave in ("referencia_ms", "queda_ear_minima", "fechado_minimo_ms", "fechado_maximo_ms",
                  "janela_movimento_ms", "movimento_maximo"):
        assert chave in gravados, chave


def test_registro_guarda_so_numeros():
    r = Registro("PISCAR", 1.0, True, 1, 100.0, 0.5, ear=0.3, x=120.0, w=150.0)
    assert all(v is None or isinstance(v, (bool, int, float, str)) for v in r.__dict__.values())
    json.dumps(r.__dict__)


def test_deslocamento_pela_largura_tipica_ignora_a_caixa_que_cresce_e_encolhe():
    """Centro parado em 300 px, caixa de 100 e 130 px: na conta antiga, (x + w/2)/w, isso andava 0,7."""
    parado = [Registro("ESQUERDA", i / 30, True, x=300 - w / 2, w=w) for i, w in enumerate([100, 130] * 10)]
    assert deslocamento_maximo(parado, 1) == 0.0
    andando = [Registro("ESQUERDA", i / 30, True, x=200 + 10 * i, w=100) for i in range(5)]
    assert deslocamento_maximo(andando, 1) == 0.4


def test_gravacao_antiga_sem_caixa_usa_o_centro():
    assert caixa_do_registro(Registro("PARADO", 0.0, True, centro=3.0)) == (250, 0, 100, 100)
    assert caixa_do_registro(Registro("PARADO", 0.0, True, x=120.0, w=150.0)) == (120, 0, 150, 150)


def test_quadros_por_segundo_sem_intervalo_medido_e_zero():
    assert quadros_por_segundo([]) == 0.0
    assert quadros_por_segundo([5.0]) == 0.0
    assert quadros_por_segundo([5.0, 5.0]) == 0.0              # dois quadros no mesmo instante do relógio
    assert quadros_por_segundo([0.0, 0.05, 0.10]) == 20.0

