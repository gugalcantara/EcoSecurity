"""Leitor de configuração: tipos do TOML e falha segura para parâmetro ausente."""
import pytest

from ecosec.configuracao import CAMINHO_PADRAO, ErroConfiguracao, carregar


@pytest.fixture
def toml_temporario(tmp_path):
    def criar(conteudo):
        arquivo = tmp_path / "teste.toml"
        arquivo.write_text(conteudo, encoding="utf-8")
        return arquivo
    return criar


def test_arquivo_do_projeto_carrega():
    cfg = carregar()
    assert cfg.origem == CAMINHO_PADRAO
    assert cfg["aplicacao.nome"] == "EcoSecurity"


def test_tipos_chegam_prontos_sem_conversao(toml_temporario):
    cfg = carregar(toml_temporario("[a]\ninteiro = 640\nreal = 2.0\nlista = [8, 8]\n"))
    assert cfg["a.inteiro"] == 640 and isinstance(cfg["a.inteiro"], int)
    assert cfg["a.real"] == 2.0 and isinstance(cfg["a.real"], float)
    assert cfg["a.lista"] == [8, 8]


def test_parametro_ausente_e_erro_e_nao_valor_padrao(toml_temporario):
    cfg = carregar(toml_temporario("[captura]\nlargura = 640\n"))
    with pytest.raises(ErroConfiguracao, match="captura.altura"):
        cfg["captura.altura"]


def test_secao_ausente_e_erro(toml_temporario):
    cfg = carregar(toml_temporario("[captura]\nlargura = 640\n"))
    with pytest.raises(ErroConfiguracao):
        cfg.secao("limiares")


def test_secao_devolve_copia_que_nao_altera_a_configuracao(toml_temporario):
    cfg = carregar(toml_temporario("[captura]\nlargura = 640\n"))
    copia = cfg.secao("captura")
    copia["largura"] = 1
    assert cfg["captura.largura"] == 640


def test_parametro_nao_e_secao(toml_temporario):
    cfg = carregar(toml_temporario("[captura]\nlargura = 640\n"))
    with pytest.raises(ErroConfiguracao, match="não uma seção"):
        cfg.secao("captura.largura")


def test_arquivo_inexistente(tmp_path):
    with pytest.raises(ErroConfiguracao, match="não encontrado"):
        carregar(tmp_path / "nao_existe.toml")


def test_toml_invalido(toml_temporario):
    with pytest.raises(ErroConfiguracao, match="erro de sintaxe"):
        carregar(toml_temporario("[captura\nlargura = "))


# ---------------------------------------------------------------- abertura pelo atalho
# O atalho abre com pythonw.exe: não há console, então um print some. Todo erro
# de configuração precisa virar a caixa de mensagem, ou o programa "não abre" mudo.
@pytest.fixture
def caixas(monkeypatch, qt, tmp_path):
    import ecosec.__main__ as entrada
    import ecosec.interface.janela as janela
    from ecosec import segredos
    vistas = []
    monkeypatch.setattr(janela, "mostrar_erro_abertura", lambda msg: vistas.append(msg) or 1)
    # sem isto o teste gravaria em logs/erros.log e trocaria o sys.excepthook da suíte inteira
    monkeypatch.setattr(entrada, "_configurar_log", lambda cfg: None)
    # e sem isto main() abriria com o .env REAL (e criaria nele as chaves que faltassem)
    monkeypatch.setattr(segredos, "CAMINHO_PADRAO", tmp_path / ".env")
    return vistas


def test_config_ausente_aparece_na_tela(monkeypatch, caixas, tmp_path):
    import ecosec.__main__ as entrada
    import ecosec.configuracao as configuracao
    monkeypatch.setattr(configuracao, "CAMINHO_PADRAO", tmp_path / "nao_existe.toml")
    assert entrada.main(["--memoria"]) == 1
    assert caixas and "não encontrado" in caixas[0]


def test_parametro_lido_pelas_telas_ausente_aparece_na_tela(monkeypatch, caixas):
    """modo_demonstracao só é lido ao montar a tela de autenticação, depois de montar()."""
    import copy

    import ecosec.__main__ as entrada
    from ecosec.configuracao import Configuracao
    base = carregar()
    dados = copy.deepcopy(base._dados)
    del dados["interface"]["modo_demonstracao"]
    monkeypatch.setattr(entrada, "carregar", lambda: Configuracao(dados, base.origem))
    assert entrada.main(["--memoria"]) == 1
    assert caixas and "modo_demonstracao" in caixas[0]


# ---------------------------------------------------------------- prova de vida (S6)
def test_config_gesto_obrigatorio_aceita_piscada(tmp_path):
    """O config do grupo exige a piscada, e um nome errado
    ("piscada" no lugar de PISCAR) para a ABERTURA com mensagem clara. Sem isso, o erro só
    aparecia no meio do step-up do N3, que passava a negar sempre (ERRO_INTERNO)."""
    import copy

    from ecosec.aplicacao import montar
    from ecosec.configuracao import Configuracao
    base = carregar()
    assert base["s6_vivacidade.gesto_obrigatorio"] == "PISCAR"
    assert base["s6_vivacidade.desafios"] == ["PISCAR", "MOVER_ESQUERDA", "MOVER_DIREITA"]
    for chave, errado in (("gesto_obrigatorio", "piscada"), ("desafios", ["PISCAR", "deslizar"])):
        dados = copy.deepcopy(base._dados)
        dados["s6_vivacidade"][chave] = errado
        with pytest.raises(ErroConfiguracao, match=rf"\[s6_vivacidade\] {chave}.*PISCAR"):
            montar(Configuracao(dados, base.origem), tmp_path / ".env", modo="memoria")
