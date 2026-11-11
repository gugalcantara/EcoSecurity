"""Correções da revisão de código (07/10/2026)."""
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
    """Cadeado com argola menta, corpo branco e símbolo de radiação escuro (escolha do grupo, 08/10/2026)."""
    from PySide6.QtGui import QColor
    from ecosec.interface.logo import ARGOLA, CORPO, SIMBOLO, imagem_logo
    imagem = imagem_logo(lado)
    corpo = [imagem.pixelColor(x, y) for x in range(int(lado * 0.27), int(lado * 0.73))
             for y in range(int(lado * 0.46), int(lado * 0.84))]
    assert any(c.name() == QColor(CORPO).name() for c in corpo)                 # corpo branco
    assert any(c.lightness() < 90 for c in corpo)                                # símbolo escuro DENTRO do corpo
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
