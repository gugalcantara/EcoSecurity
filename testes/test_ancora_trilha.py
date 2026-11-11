"""Âncora da trilha (S10): o último hash guardado fora do banco detecta a cauda apagada ou recalculada, que a
corrente sozinha não vê."""
from datetime import datetime, timedelta

import pytest

from ecosec.dominio.entidades import EventoTrilha, RegistroTrilha
from ecosec.repositorios.memoria import RepositorioTrilhaMemoria
from ecosec.seguranca.evidencia import s10_trilha
from ecosec.seguranca.evidencia.s10_trilha import Ancora
from ecosec.servicos.trilha import ServicoTrilha
from ferramentas import verificar_trilha

T0 = datetime(2026, 11, 11, 14, 0, 0)


def evento(i, **extra):
    base = dict(momento=T0 + timedelta(seconds=i), evento="AUTENTICACAO", resultado="NEGADO",
                motivo="SENHA_INCORRETA", camadas="S1,S2", nivel_solicitado=2, matricula_informada=f"M{i}")
    return EventoTrilha(**{**base, **extra})


def cadeia(eventos):
    registros, anterior = [], None
    for i, ev in enumerate(eventos, 1):
        r = s10_trilha.encadear(ev, anterior)
        registros.append(RegistroTrilha(r.evento, r.hash_anterior, r.hash_registro, i))
        anterior = r.hash_registro
    return registros


def dez():
    return cadeia([evento(i) for i in range(1, 11)])


# ------------------------------------------------------------------ a linha de texto
def test_ancora_do_ultimo_registro_e_ida_e_volta_pelo_texto():
    registros = dez()
    a = s10_trilha.ancora(registros)
    assert (a.id, a.hash, a.momento) == (10, registros[-1].hash_registro, registros[-1].evento.momento)
    linha = a.texto()
    assert linha.startswith("ECOSEC-TRILHA 10 ") and "—" not in linha and "–" not in linha
    assert Ancora.de_texto(linha) == a
    assert Ancora.de_texto(f"  {linha.upper().replace('ECOSEC-TRILHA', 'ECOSEC-TRILHA')}  ").hash == a.hash


def test_trilha_vazia_nao_tem_ancora():
    assert s10_trilha.ancora([]) is None


@pytest.mark.parametrize("linha", ["", "ECOSEC-TRILHA", "OUTRA 10 " + "a" * 64, "ECOSEC-TRILHA dez " + "a" * 64,
                                   "ECOSEC-TRILHA 10 abc", "ECOSEC-TRILHA 10 " + "g" * 64])
def test_linha_invalida_e_recusada(linha):
    with pytest.raises(ValueError):
        Ancora.de_texto(linha)


# ------------------------------------------------------------------ conferência
def test_ancora_confere_e_conta_os_registros_depois_dela():
    registros = dez()
    a = s10_trilha.ancora(registros[:7])
    c = s10_trilha.conferir_ancora(registros, a)
    assert c.valida and c.registros_depois == 3
    assert "confere" in str(c)


def test_cauda_apagada_que_a_corrente_nao_ve_e_pega_pela_ancora():
    registros = dez()
    a = s10_trilha.ancora(registros)                      # âncora no registro 10
    apagada = registros[:7]                              # o root apaga 8, 9 e 10
    assert s10_trilha.verificar(apagada).integra          # a corrente sozinha não percebe
    c = s10_trilha.conferir_ancora(apagada, a)
    assert (c.valida, c.problema) == (False, "ANCORA_AUSENTE")
    assert "apagados" in str(c)


def test_cauda_recalculada_que_a_corrente_nao_ve_e_pega_pela_ancora():
    original = dez()
    a = s10_trilha.ancora(original[:9])                   # âncora no registro 9
    eventos = [r.evento for r in original]
    eventos[7] = evento(8, resultado="CONCEDIDO")          # o root troca o 8 e recalcula a cauda inteira
    recalculada = cadeia(eventos)
    assert s10_trilha.verificar(recalculada).integra
    c = s10_trilha.conferir_ancora(recalculada, a)
    assert (c.valida, c.problema) == (False, "ANCORA_DIVERGENTE")
    assert "recalculado" in str(c)


def test_adulteracao_no_meio_aparece_antes_da_ancora():
    registros = dez()
    a = s10_trilha.ancora(registros)
    r = registros[3]
    registros[3] = RegistroTrilha(EventoTrilha(**{**r.evento.__dict__, "resultado": "CONCEDIDO"}),
                                  r.hash_anterior, r.hash_registro, r.id)
    c = s10_trilha.conferir_ancora(registros, a)
    assert (c.valida, c.problema) == (False, "TRILHA_ADULTERADA")
    assert "registro 4" in str(c)


def test_servico_gera_e_confere_a_ancora():
    trilha = ServicoTrilha(RepositorioTrilhaMemoria(), relogio=lambda: T0)
    assert trilha.ancora() is None
    for _ in range(3):
        trilha.registrar("AUTENTICACAO", "NEGADO", "SENHA_INCORRETA")
    a = trilha.ancora()
    trilha.registrar("AUTENTICACAO", "CONCEDIDO", "OK")
    c = trilha.conferir_ancora(a)
    assert a.id == 3 and c.valida and c.registros_depois == 1


# ------------------------------------------------------------------ a ferramenta, com o sistema em memória
@pytest.fixture
def app(tmp_path):
    from ecosec.aplicacao import montar
    app = montar(caminho_env=tmp_path / ".env", modo="memoria")
    for _ in range(4):
        app.administracao.trilha.registrar("AUTENTICACAO", "NEGADO", "SENHA_INCORRETA")
    return app


def test_ferramenta_confere_a_linha_e_o_arquivo_de_ancoras(app, tmp_path, capsys):
    linha = app.administracao.ancora_trilha().texto()        # no uso real, a linha vem do painel administrativo
    assert verificar_trilha.main(["--conferir", linha], app=app) == 0
    arquivo = tmp_path / "ancoras.txt"
    arquivo.write_text("anotação: âncora do dia 11\n" + linha + "\n", encoding="utf-8")
    assert verificar_trilha.main(["--conferir-arquivo", str(arquivo)], app=app) == 0
    assert "[ OK ] registro 4" in capsys.readouterr().out


def test_ferramenta_nao_gera_ancora_que_fica_so_no_painel(app):
    with pytest.raises(SystemExit):
        verificar_trilha.main(["--ancorar"], app=app)


def test_ferramenta_acusa_a_cauda_apagada(app, capsys):
    linha = app.administracao.ancora_trilha().texto()
    repo = app.administracao.trilha.repo
    del repo._registros[-2:]                              # o que o root faria direto no banco
    assert verificar_trilha.main([], app=app) == 0       # a corrente continua "íntegra"
    assert verificar_trilha.main(["--conferir", linha], app=app) == 1
    assert "[ADULTERADA]" in capsys.readouterr().out


def test_ferramenta_recusa_linha_invalida_e_arquivo_sem_ancora(app, tmp_path, capsys):
    assert verificar_trilha.main(["--conferir", "qualquer coisa"], app=app) == 3
    vazio = tmp_path / "vazio.txt"
    vazio.write_text("nada aqui\n", encoding="utf-8")
    assert verificar_trilha.main(["--conferir-arquivo", str(vazio)], app=app) == 3
