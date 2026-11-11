"""Experimento da curva DET: o cálculo (ecosec/visao/desempenho.py) e a ferramenta (ferramentas/experimento_det.py),
com distâncias fabricadas, sem câmera, banco nem modelo."""
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from ecosec.visao import desempenho as dp
from ferramentas import experimento_det as ex


# ------------------------------------------------------------------ pontuação da tentativa
def test_pontuacao_exige_n_quadros_seguidos():
    # com 3 quadros seguidos: a melhor janela é (40, 42, 41), aceita a partir de 42
    assert dp.pontuacao_tentativa([90, 40, 42, 41, 95], 3) == 42
    # um quadro isolado bom não basta: o pior da melhor janela manda
    assert dp.pontuacao_tentativa([10, 80, 80, 80], 3) == 80


def test_pontuacao_sem_quadros_suficientes_e_none():
    assert dp.pontuacao_tentativa([40, 41], 3) is None
    with pytest.raises(ValueError):
        dp.pontuacao_tentativa([40], 0)


# ------------------------------------------------------------------ taxas e curva
def test_taxas_seguem_a_convencao_do_lbph():
    """Aceita quando distância <= limiar: FAR conta impostores aceitos, FRR conta genuínos recusados."""
    p = dp.taxas(genuinas=[30, 50, 70], impostoras=[45, 80, 90, 100], limiar=50)
    assert p.far == pytest.approx(1 / 4)          # só o impostor de 45 passa
    assert p.frr == pytest.approx(1 / 3)          # só o genuíno de 70 é recusado


def test_falhas_de_captura_entram_na_frr_em_qualquer_limiar():
    p = dp.taxas([30, 40], [90], limiar=1000, falhas_captura=2)
    assert p.frr == pytest.approx(2 / 4) and p.far == 1.0


def test_curva_comeca_sem_aceitar_nada_e_termina_aceitando_tudo():
    pontos = dp.curva([30, 50], [60, 80])
    assert (pontos[0].far, pontos[0].frr) == (0.0, 1.0)
    assert (pontos[-1].far, pontos[-1].frr) == (1.0, 0.0)
    assert [p.limiar for p in pontos] == sorted(p.limiar for p in pontos)


def test_dados_separados_dao_eer_zero_e_limiares_ordenados():
    genuinas = [30, 35, 40, 42, 45]
    impostoras = [70, 75, 80, 90, 95, 100]
    s = dp.sugerir_limiares(genuinas, impostoras)
    assert dp.eer(dp.curva(genuinas, impostoras)).far == 0.0
    assert all(x.far == 0.0 for x in s.values())
    assert s[3].limiar <= s[2].limiar <= s[1].limiar


def test_dados_sobrepostos_nivel_mais_sensivel_nunca_aceita_mais():
    rng = np.random.default_rng(2026)
    genuinas = list(rng.normal(45, 8, 200))
    impostoras = list(rng.normal(75, 10, 600))
    s = dp.sugerir_limiares(genuinas, impostoras)
    assert s[3].limiar <= s[2].limiar <= s[1].limiar
    assert s[3].far <= s[2].far <= s[1].far
    assert s[2].far <= 0.01
    e = dp.eer(dp.curva(genuinas, impostoras))
    assert 0 < e.far < 0.2                        # sobreposição real: a EER não é zero


def test_limiar_de_identificacao_recusa_todas_as_erradas():
    p = dp.limiar_identificacao(corretas=[30, 40, 55, 60], erradas=[50, 70])
    assert p.limiar < 50 and p.far == 0.0
    assert p.frr == pytest.approx(2 / 4)          # 55 e 60 ficam acima
    assert dp.limiar_identificacao([], [50]) is None


def test_sem_identificacao_errada_o_limiar_fica_no_teto():
    """Sem erro medido, nada mostra até onde afrouxar: o limiar não passa do teto (o do nível 3)."""
    assert dp.limiar_identificacao([30, 70, 80], [], teto=55).limiar == 55
    assert dp.limiar_identificacao([30, 70, 80], []).limiar == 80


def test_analise_limita_a_identificacao_ao_nivel_3():
    resumo = ex.analisar(_dados_sinteticos(), quadros=5)
    assert resumo["identificacao"]["limiar"] <= resumo["limiares_sugeridos"]["3"]["limiar"]


# ------------------------------------------------------------------ participantes
class _Usuarios:
    def __init__(self, lista):
        self._lista = lista

    def listar(self):
        return list(self._lista)


class _Consentimentos:
    def __init__(self, por_id):
        self._por_id = por_id

    def vigente_de(self, usuario_id):
        return self._por_id.get(usuario_id)


def _u(uid, ativo=True, excluido=None):
    return SimpleNamespace(id=uid, matricula=f"MAT{uid:04d}", ativo=ativo, excluido_em=excluido)


def _c(pesquisa=True):
    return SimpleNamespace(autoriza_pesquisa=pesquisa)


def test_so_participa_quem_autorizou_a_finalidade_b():
    usuarios = _Usuarios([_u(1), _u(2), _u(3, ativo=False), _u(4, excluido="2026-11-01"), _u(5), _u(6)])
    consentimentos = _Consentimentos({1: _c(), 2: _c(pesquisa=False), 3: _c(), 4: _c(), 5: _c()})
    rotulos = {1, 2, 3, 4, 6}                     # o 5 não tem rosto no modelo; o 6 não tem consentimento
    assert [u.id for u in ex.elegiveis(usuarios, consentimentos, rotulos)] == [1]


def test_codigo_do_participante_e_estavel_e_nao_expoe_identificadores():
    a = ex.codigo("sal", 7)
    assert a == ex.codigo("sal", 7) != ex.codigo("outro sal", 7)
    assert a.startswith("P") and len(a) == 9
    int(a[1:], 16)                                # o resto é só o resumo do hash, em hexadecimal


# ------------------------------------------------------------------ análise e figura
def _dados_sinteticos(participantes=3, sessoes=(1, 2)):
    rng = np.random.default_rng(7)
    codigos = [f"P{i}" for i in range(participantes)]
    tentativas = []
    for s in sessoes:
        for c in codigos:
            for _ in range(4):
                quadros = []
                for _ in range(12):
                    outros = {o: float(rng.normal(68, 10)) for o in codigos if o != c}   # sobrepõe aos genuínos
                    quadros.append({"genuina": float(rng.normal(52, 10)), "impostoras": outros,
                                    "identificacao": {"correta": True, "distancia": float(rng.normal(42, 6))}})
                tentativas.append({"participante": c, "sessao": s, "quadros": quadros})
    return {"sal": "x", "tentativas": tentativas}


def test_analise_completa_sem_avisos():
    resumo = ex.analisar(_dados_sinteticos(), quadros=5)
    assert resumo["participantes"] == 3 and resumo["sessoes"] == [1, 2] and resumo["avisos"] == []
    assert resumo["tentativas_genuinas"] == 24 and resumo["falhas_captura"] == 0
    assert resumo["tentativas_impostor"] == 24 * 2          # cada tentativa contra os outros dois
    lim = {int(n): s["limiar"] for n, s in resumo["limiares_sugeridos"].items()}
    assert lim[3] <= lim[2] <= lim[1]
    assert "Limiares sugeridos" in ex.texto_resumo(resumo)


def test_analise_avisa_poucos_participantes_e_uma_sessao():
    resumo = ex.analisar(_dados_sinteticos(participantes=2, sessoes=(1,)), quadros=5)
    assert any("participante" in a for a in resumo["avisos"]) and any("sessão" in a for a in resumo["avisos"])


def test_analise_avisa_quando_os_tres_limiares_coincidem():
    dados = _dados_sinteticos()
    for t in dados["tentativas"]:                 # genuínos e impostores bem separados
        for q in t["quadros"]:
            q["genuina"] = 30.0
            q["impostoras"] = {k: 90.0 for k in q["impostoras"]}
    resumo = ex.analisar(dados, quadros=5)
    assert any("coincidem" in a for a in resumo["avisos"])


def test_tentativa_sem_quadros_suficientes_conta_como_falha_de_captura():
    dados = _dados_sinteticos()
    dados["tentativas"][0]["quadros"] = dados["tentativas"][0]["quadros"][:2]
    resumo = ex.analisar(dados, quadros=5)
    assert resumo["falhas_captura"] == 1 and resumo["tentativas_genuinas"] == 24


def test_figura_da_curva_e_gravada(tmp_path):
    resumo = ex.analisar(_dados_sinteticos(), quadros=5)
    caminho = ex.desenhar_curva(resumo, tmp_path / "curva_det.png")
    from PIL import Image
    with Image.open(caminho) as img:
        assert img.size == (900, 760)


def test_analisar_pela_linha_de_comando_sem_coleta_falha_com_orientacao(tmp_path, monkeypatch, capsys):
    from ecosec.configuracao import carregar
    cfg = carregar()
    monkeypatch.setattr(type(cfg), "caminho", lambda self, nome: tmp_path)
    monkeypatch.setattr("ecosec.configuracao.carregar", lambda *a, **k: cfg)
    assert ex.main(["analisar"]) == 1
    assert "Rode primeiro o comando coletar" in capsys.readouterr().out


# ------------------------------------------------------------------ coleta (câmera e modelo falsos)
class _Reconhecedor:
    """Distância fabricada: 40 para o próprio rótulo, 85 para os outros."""
    def __init__(self, dono):
        self.dono = dono

    def rotulos(self):
        return {1, 2, 3}

    def verificar(self, face, rotulo):
        return 40.0 if rotulo == self.dono else 85.0

    def identificar(self, face):
        return self.dono, 40.0


def _app_falso(dono=1):
    @contextmanager
    def camera():
        yield SimpleNamespace(ler=lambda: np.zeros((480, 640, 3), np.uint8))
    resultado = SimpleNamespace(qualidade_aprovada=True, face_normalizada=np.zeros((200, 200), np.uint8),
                                face_unica=(10, 10, 100, 100))
    return SimpleNamespace(
        reconhecedor=_Reconhecedor(dono),
        cadastro=SimpleNamespace(usuarios=_Usuarios([_u(1), _u(2), _u(3)]),
                                 consentimentos=_Consentimentos({1: _c(), 2: _c(), 3: _c()})),
        nova_camera=camera, novo_pipeline=lambda: SimpleNamespace(processar=lambda q: resultado))


@pytest.fixture
def sem_janela(monkeypatch):
    import cv2
    monkeypatch.setattr(ex, "_mostrar", lambda *a, **k: None)
    monkeypatch.setattr(cv2, "waitKey", lambda *a: -1)
    monkeypatch.setattr(cv2, "destroyAllWindows", lambda: None)


def test_coleta_grava_so_distancias_com_codigos(sem_janela):
    dados = {"sal": "s", "tentativas": []}
    feitas = ex.coletar(_app_falso(), dados, "mat0001", sessao=2, tentativas=2, segundos=5, quadros_maximos=6,
                        preparo=0)
    assert feitas == 2 and len(dados["tentativas"]) == 2
    t = dados["tentativas"][0]
    assert t["participante"] == ex.codigo("s", 1) and t["sessao"] == 2 and len(t["quadros"]) == 6
    q = t["quadros"][0]
    assert q["genuina"] == 40.0 and sorted(q["impostoras"].values()) == [85.0, 85.0]
    assert set(q["impostoras"]) == {ex.codigo("s", 2), ex.codigo("s", 3)}
    assert q["identificacao"] == {"correta": True, "distancia": 40.0}
    texto = str(dados)
    assert "MAT0001" not in texto and "'id'" not in texto      # nem matrícula nem identificador do banco


def test_coleta_recusa_matricula_fora_do_experimento(sem_janela):
    app = _app_falso()
    app.cadastro.consentimentos = _Consentimentos({2: _c(), 3: _c()})     # o 1 não autorizou a (b)
    with pytest.raises(SystemExit, match="fora do experimento"):
        ex.coletar(app, {"sal": "s", "tentativas": []}, "MAT0001", 1, 1, 1, 1, preparo=0)


def test_arquivo_de_dados_e_gravado_e_lido_de_volta(tmp_path):
    caminho = tmp_path / "experimento_det.json"
    dados = ex.ler_dados(caminho)
    assert dados["tentativas"] == [] and len(dados["sal"]) == 32
    dados["tentativas"].append({"participante": "P1", "sessao": 1, "quadros": []})
    ex.gravar_dados(caminho, dados)
    assert ex.ler_dados(caminho) == dados


# ------------------------------------------------------------------ cadastros da mesma pessoa
def test_ignorar_tira_do_experimento_o_cadastro_da_mesma_pessoa():
    usuarios = _Usuarios([_u(1), _u(2), _u(3)])
    consentimentos = _Consentimentos({1: _c(), 2: _c(), 3: _c()})
    assert [u.id for u in ex.elegiveis(usuarios, consentimentos, {1, 2, 3}, ignorar=["mat0002 "])] == [1, 3]


def test_coleta_sozinho_mede_so_as_genuinas_e_ignora_a_identificacao_do_mesmo_rosto(sem_janela):
    app = _app_falso(dono=1)
    app.reconhecedor.identificar = lambda face: (2, 38.0)        # o mais parecido é o outro cadastro dele
    dados = {"sal": "s", "tentativas": []}
    ex.coletar(app, dados, "MAT0001", 1, 1, 5, 3, preparo=0, ignorar={"MAT0002", "MAT0003"})
    q = dados["tentativas"][0]["quadros"][0]
    assert q["genuina"] == 40.0 and q["impostoras"] == {} and "identificacao" not in q


# ------------------------------------------------------------------ base pública
@pytest.mark.parametrize("nome, esperado", [
    ("yaleB11_P00A+000E+00.pgm", 1), ("yaleB11_P00A+010E-20.pgm", 2), ("yaleB11_P00A+035E+15.pgm", 3),
    ("yaleB11_P00A+060E-20.pgm", 4), ("yaleB11_P00A+130E+20.pgm", 5), ("yaleB11_P00_Ambient.pgm", None),
    ("yaleB11_P00A+000E+00.pgm.bad", None)])
def test_subconjunto_de_iluminacao_pelo_nome_do_arquivo(nome, esperado):
    assert ex.subconjunto_yale(nome) == esperado


def _base_sintetica(pessoas=4, por_subconjunto=3):
    """Uma textura própria por pessoa, com ruído leve por imagem; a imagem marcada com "escura" é recusada."""
    import cv2
    rng = np.random.default_rng(3)
    padroes = {f"yaleB{10 + p}": rng.integers(0, 256, (25, 25)).astype(np.uint8) for p in range(pessoas)}
    imagens, base = {}, {}
    for nome, padrao in padroes.items():
        lista = []
        for s in range(1, 6):
            for i in range(por_subconjunto):
                arq = Path(f"{nome}/{nome}_s{s}_{i}{'_escura' if s == 5 and i == 0 else ''}.pgm")
                img = cv2.resize(padrao, (200, 200), interpolation=cv2.INTER_NEAREST).astype(np.int16)
                imagens[arq] = np.clip(img + rng.normal(0, 6, img.shape), 0, 255).astype(np.uint8)
                lista.append((s, arq))
        base[nome] = lista
    return base, imagens


def _novo_reconhecedor():
    from ecosec.configuracao import carregar
    from ecosec.visao.reconhecimento import ParametrosLBPH, ReconhecedorLBPH
    return ReconhecedorLBPH(ParametrosLBPH.de_configuracao(carregar()))


def test_base_cadastra_o_subconjunto_1_e_mede_os_outros_num_modelo_proprio():
    pessoas, imagens = _base_sintetica()
    alvo = []
    medida = ex.medir_base(pessoas, lambda img: img, _novo_reconhecedor,
                           ler=lambda arq: None if "_escura" in arq.name else imagens[arq],
                           alvo=lambda face: alvo.append(1) or 99.0)
    assert medida["pessoas"] == 4 and medida["cadastro"] == {"imagens": 12, "aprovadas": 12}
    s5 = medida["por_subconjunto"]["5"]
    assert (s5["imagens"], s5["rejeitadas_qualidade"], len(s5["genuinas"])) == (12, 4, 8)
    assert len(s5["impostoras"]) == len(s5["genuinas"]) * 3              # contra cada uma das outras três
    s2 = medida["por_subconjunto"]["2"]
    assert np.mean(s2["genuinas"]) < np.mean(s2["impostoras"])
    assert len(medida["alvo_impostoras"]) == len(alvo) == 4 * 15 - 4      # toda imagem aprovada, cadastro incluído
    resumo = ex.analisar_base(medida)                                     # a curva: subconjuntos 2 e 3
    assert resumo["subconjuntos_curva"] == ["2", "3"] and resumo["falha_aquisicao"] == 0
    assert resumo["tentativas_genuinas"] == 24 and resumo["tentativas_impostor"] == 72 and "eer" in resumo
    assert "eer" in resumo["subconjuntos"]["5"]
    assert "subconjunto 5: 12 imagens, 4 recusadas" in ex.texto_base(resumo)
    com_extremos = ex.analisar_base(medida, subconjuntos=("2", "3", "4", "5"))
    assert com_extremos["falha_aquisicao"] == 4 / 48


def test_reconhecedor_devolve_a_menor_distancia_de_cada_rotulo_como_o_verificar():
    pessoas, imagens = _base_sintetica(pessoas=3, por_subconjunto=2)
    r = _novo_reconhecedor()
    for rotulo, (_, lista) in enumerate(sorted(pessoas.items()), start=1):
        r.adicionar([imagens[a] for s, a in lista if s == 1], rotulo)
    face = imagens[pessoas["yaleB10"][4][1]]
    todas = r.distancias(face)
    assert set(todas) == {1, 2, 3} and all(todas[k] == r.verificar(face, k) for k in todas)
    assert min(todas, key=todas.get) == r.identificar(face)[0]


def test_sistema_junta_as_genuinas_da_camera_com_os_rostos_da_base_contra_o_alvo():
    dados = _dados_sinteticos()
    alvo = dados["tentativas"][0]["participante"]
    base = {"alvo": {"sal": "x", "codigo": alvo, "impostoras": [80.0 + i % 20 for i in range(300)]}}
    resumo = ex.analisar_sistema(dados, base, quadros=5)
    assert resumo["tentativas_genuinas"] == 8 and resumo["impostores_da_base"] == 300
    assert resumo["tentativas_impostor"] == 300 + 8 * 2 and "eer" in resumo
    assert ex.analisar_sistema(dados, {"alvo": {**base["alvo"], "sal": "outro"}}, quadros=5) is None


def test_figura_com_mais_de_uma_curva(tmp_path):
    resumo = ex.analisar(_dados_sinteticos(), quadros=5)
    caminho = ex.desenhar_curva(resumo, tmp_path / "curva.png", rotulo="Base",
                                extras=(("Câmera", resumo["curva"]),))
    assert caminho.exists()


# ------------------------------------------------------------------ administrador
def test_coleta_e_base_pedem_um_administrador():
    pedidos = []

    def autorizar_ferramenta(matricula, senha, codigo, ferramenta):
        pedidos.append((matricula, senha, codigo, ferramenta))
        return (None, "Matrícula ou senha incorretas.") if senha != "certa" else (7, None)
    app = SimpleNamespace(administracao=SimpleNamespace(autorizar_ferramenta=autorizar_ferramenta))
    respostas = iter(["ADM0001", "123456"])
    assert ex.autorizar(app, "EXPERIMENTO DET COLETAR", entrada=lambda _: next(respostas),
                        ler_senha=lambda _: "certa") == 7
    assert pedidos[0] == ("ADM0001", "certa", "123456", "EXPERIMENTO DET COLETAR")
    respostas = iter(["ADM0001", "123456"])
    with pytest.raises(SystemExit, match="incorretas"):
        ex.autorizar(app, "X", entrada=lambda _: next(respostas), ler_senha=lambda _: "errada")


def test_analise_mostra_far_e_frr_nos_limiares_do_config():
    resumo = ex.analisar(_dados_sinteticos(), quadros=5, atuais={"1": 70.0, "2": 60.0, "3": 50.0})
    atuais = resumo["limiares_atuais"]
    assert [atuais[n]["limiar"] for n in "123"] == [70.0, 60.0, 50.0]
    assert atuais["1"]["far"] >= atuais["2"]["far"] >= atuais["3"]["far"]
    assert atuais["1"]["frr"] <= atuais["2"]["frr"] <= atuais["3"]["frr"]
    assert "Nos limiares do config:" in ex.texto_resumo(resumo)


def test_sistema_avisa_quando_os_rostos_da_base_ficam_todos_longe_do_cadastro():
    dados = _dados_sinteticos()
    alvo = dados["tentativas"][0]["participante"]
    base = {"alvo": {"sal": "x", "codigo": alvo, "impostoras": [500.0] * 50}}
    resumo = ex.analisar_sistema(dados, base, quadros=5)
    assert any("outra câmera" in a for a in resumo["avisos"])
