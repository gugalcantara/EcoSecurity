"""Testes de casos avulsos."""
import pytest


def test_acervo_mostra_o_motivo_da_recusa_e_esconde_falha_interna():
    from ecosec.interface.tela_acervo import _mensagem
    from ecosec.servicos.acervo import ErroAcervo
    assert _mensagem(ErroAcervo("O nível 3 não exporta.")) == "O nível 3 não exporta."
    interna = _mensagem(RuntimeError("1146 (42S02): Table 'ecosec_acervo.pendencia' doesn't exist"))
    assert "pendencia" not in interna and "Falha interna" in interna       # nada do banco na tela


@pytest.mark.parametrize("nome", ["x`; DROP DATABASE mysql; --", "banco.outro", "", "a" * 65, "nome com espaço"])
def test_preparar_banco_recusa_nome_de_banco_inseguro(nome):
    from ferramentas.preparar_banco import _secao_banco

    class Cfg:
        def secao(self, _):
            return {"seguranca": nome, "acervo": "ecosec_acervo", "prefixo_teste": "ecosec_teste_"}
    with pytest.raises(SystemExit):
        _secao_banco(Cfg())


@pytest.mark.parametrize("lado", [16, 48, 256])
def test_logo_sai_em_todos_os_tamanhos_com_as_cores_escolhidas(qt, lado):
    """Cadeado com argola menta, corpo branco e símbolo de radiação escuro (identidade visual do sistema)."""
    from PySide6.QtGui import QColor
    from ecosec.interface.logo import ARGOLA, CORPO, imagem_logo
    imagem = imagem_logo(lado)
    corpo = [imagem.pixelColor(x, y) for x in range(int(lado * 0.27), int(lado * 0.73))
             for y in range(int(lado * 0.46), int(lado * 0.84))]
    assert any(c.name() == QColor(CORPO).name() for c in corpo)                 # corpo branco
    assert any(c.lightness() < 90 for c in corpo)                                # símbolo escuro dentro do corpo
    argola = [imagem.pixelColor(x, y) for x in range(lado) for y in range(int(lado * 0.12), int(lado * 0.44))]
    menta = QColor(ARGOLA)
    assert any(abs(c.green() - menta.green()) < 60 and c.green() > c.red() + 40 for c in argola)   # argola visível


def test_a_digital_saiu_da_aplicacao():
    """O sistema não coleta digitais: nenhuma tela usa o ícone de digital."""
    from pathlib import Path
    raiz = Path(__file__).resolve().parent.parent
    usos = [str(a) for pasta in ("ecosec", "ferramentas") for a in (raiz / pasta).rglob("*.py")
            if "FINGERPRINT" in a.read_text(encoding="utf-8")]
    assert not usos, usos


def test_falha_inesperada_na_administracao_nao_mostra_o_texto_interno():
    from ecosec.repositorios.contratos import BancoIndisponivel, ErroRepositorio
    from ecosec.servicos.falhas import GENERICA, mensagem_para_tela
    assert mensagem_para_tela(BancoIndisponivel("Confira o serviço MySQL84.")) == "Confira o serviço MySQL84."
    assert mensagem_para_tela(ErroRepositorio("Erro do banco (1146): Table 'trilha' doesn't exist")) == GENERICA
    assert mensagem_para_tela(RuntimeError("detalhe interno")) == GENERICA


def test_negacao_sem_trilha_fica_no_registro_de_erros(caplog):
    """A negação vale mesmo se a trilha não grava; o evento não pode sumir sem rastro."""
    from types import SimpleNamespace

    from ecosec.servicos.acervo import ServicoAcervo

    class TrilhaFora:
        def registrar(self, *args, **kwargs):
            raise RuntimeError("banco fora do ar")

    falso = SimpleNamespace(trilha=TrilhaFora())
    with caplog.at_level("ERROR", logger="ecosec.servicos.acervo"):
        ServicoAcervo._registrar_negacao(falso, "EXPORTACAO", "EXPORTACAO_BLOQUEADA", SimpleNamespace(id=7), 3, "A3-01")
    assert "EXPORTACAO_BLOQUEADA" in caplog.text and "A3-01" in caplog.text

