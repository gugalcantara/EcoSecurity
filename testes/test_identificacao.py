"""Identificação 1:N: o sistema diz quem é, sem conceder nada.

Serviço próprio (`app.identificacao`), e não a sessão do N1: aquela decide ACESSO (nível, consentimento,
contenção) e grava AUTENTICACAO na trilha. Aqui só se identifica, e cada identificação vai para a trilha como
IDENTIFICACAO / REGISTRADO: só o ADMINISTRADOR identifica, numa seção do painel de Administração
(já aberto pelo rosto e pelo celular); não há mais item no menu nem step-up do N3.

Faces sintéticas de test_interface: todas têm a mesma estatística de textura e ficam a ~26 umas das outras no
LBPH (medido), abaixo do limiar. O rosto de ninguém precisa de outro grão de textura (~135 de todas).
"""
import dataclasses
import re
from datetime import datetime

import cv2
import numpy as np
import pytest
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QLabel

from ecosec.aplicacao import montar
from ecosec.dominio.niveis import Nivel
from ecosec.dominio.perfis import Perfil
from test_arquitetura import RAIZ, _imports
from test_interface import (SENHA_ADMIN_USUARIO, cadastrar, cadastrar_celular_pela_tela, fazer_login,  # noqa: F401
                            janela, quadro, vincular_admin)

# como o cadastro grava (texto.nome: maiúsculas, sem acento) e como as telas já mostram ("Olá, RAFAEL")
BIA = "BEATRIZ SOUZA"
NOMES = {BIA, "ANA PRADO", "RAFAEL DUARTE"}


class Relogio:
    def __init__(self):
        self.t = 500.0

    def __call__(self):
        return self.t


@pytest.fixture
def app(tmp_path):
    """O app da fixture `janela` de test_interface, sem a janela."""
    a = montar(caminho_env=tmp_path / ".env", modo="memoria")
    a.administracao.custo = a.cadastro.custo = a.autenticacao.p.custo_bcrypt = 4
    a.cadastro.frames_por_sessao = 3
    a.cadastro.leitura_minima_segundos = 0
    return a


def _tres_cadastros(app):
    """Beatriz (N2), Ana (N1) e Rafael, o administrador: um Externo com o papel (só o admin identifica)."""
    from ecosec.dominio.entidades import Administrador
    cadastros = (cadastrar(app, "Beatriz Souza", Nivel.N2, "SP", "diretor2026", 100),
                 cadastrar(app, "Ana Prado", Nivel.N1, None, "servidor2026", 300),
                 cadastrar(app, "Rafael Duarte", None, None, SENHA_ADMIN_USUARIO, 700, perfil=Perfil.EXTERNO))
    app.administracao.administradores.salvar(Administrador(cadastros[2].id, datetime.now()))
    return cadastros


def _rosto_de_ninguem():
    base = np.random.default_rng(999).integers(40, 215, (10, 10)).astype(np.uint8)
    return cv2.resize(base, (200, 200), interpolation=cv2.INTER_LINEAR)


def _alimentar(sessao, relogio, q, n, passo=0.1):
    andamento = None
    for _ in range(n):
        andamento = sessao.processar(q)
        relogio.t += passo
    return andamento


# ================================================================ serviço
def test_identificacao_1n_identifica_usuario_cadastrado(app):
    bia, _, rafael = _tres_cadastros(app)
    relogio = Relogio()
    app.identificacao.monotonico = relogio
    frames = app.cfg["reconhecimento.frames_confirmacao"]
    sessao = app.identificacao.nova_sessao(operador_id=rafael.id)
    andamento = _alimentar(sessao, relogio, quadro(100), frames - 1)
    assert not andamento.concluida and andamento.nome is None          # um quadro a menos: ainda confirmando
    a = _alimentar(sessao, relogio, quadro(100), 1)
    assert a.concluida and a.identificado and a.nome == BIA
    assert a.limiar == app.cfg["identificacao.limiar"] == 50            # limiar próprio, não o do N1 (70)
    assert a.distancia <= a.limiar
    assert a.segundos == pytest.approx(0.1 * (frames - 1))              # do 1º rosto à decisão, medido
    nomes, distancias = [c.nome for c in a.candidatos], [c.distancia for c in a.candidatos]
    assert nomes[0] == BIA and set(nomes) == NOMES and distancias == sorted(distancias)
    # o resultado não carrega imagem nenhuma do rosto (as etapas internas da visão não são mostradas)
    assert not any(isinstance(v, np.ndarray) for v in vars(a).values())
    ev = app.administracao.trilha_recente()[0].evento
    assert (ev.evento, ev.resultado, ev.motivo) == ("IDENTIFICACAO", "REGISTRADO", "IDENTIFICADO")
    assert ev.usuario_id == bia.id and ev.distancia == pytest.approx(a.distancia, abs=1e-3)
    assert ev.matricula_informada is None and ev.nivel_solicitado is None
    # no padrão de texto da trilha (texto.referencia: maiúsculas, sem "="); o tempo fica só na tela
    assert ev.detalhe == f"OPERADOR: RAFAEL DUARTE; DISTANCIA: {a.distancia:.4f}"
    # decidido, não muda mais, e a identificação fica uma vez na trilha
    assert sessao.processar(quadro(300)).nome == BIA
    assert [r.evento.evento for r in app.administracao.trilha_recente()].count("IDENTIFICACAO") == 1


@pytest.mark.parametrize("caso", ["rosto_de_ninguem", "cadastro_inativo", "sem_consentimento", "rosto_instavel",
                                  "sem_rosto"])
def test_identificacao_1n_recusa_desconhecido(app, caso):
    bia, _, rafael = _tres_cadastros(app)
    relogio = Relogio()
    app.identificacao.monotonico = relogio
    prazo = app.cfg["reconhecimento.timeout_face_segundos"]
    ninguem = dataclasses.replace(quadro(1), face_normalizada=_rosto_de_ninguem())
    if caso == "cadastro_inativo":
        assert app.administracao.definir_ativo(bia.id, False) is None          # desativar não tira o rosto
    elif caso == "sem_consentimento":
        assert app.autenticacao.consentimentos.revogar(bia.id, datetime.now())
    sessao = app.identificacao.nova_sessao(operador_id=rafael.id)
    if caso == "rosto_de_ninguem":
        # longe de todos: N quadros seguidos acima do limiar bastam (~1 s); o prazo de 15 s é do acesso
        n = app.cfg["identificacao.quadros_nao_reconhecido"]
        assert n == 15 and not _alimentar(sessao, relogio, ninguem, n - 1).concluida
        a = _alimentar(sessao, relogio, ninguem, 1)
        assert a.distancia > a.limiar == 50                                # a menor distância vista, acima do limiar
        assert {c.nome for c in a.candidatos} == NOMES
    elif caso in ("cadastro_inativo", "sem_consentimento"):
        # o rosto da Beatriz, que continua no modelo, sem cadastro válido: não reconhecido na hora, sem passar ao
        # segundo mais parecido; no top 3 ela aparece sem nome
        a = _alimentar(sessao, relogio, quadro(100), app.cfg["reconhecimento.frames_confirmacao"])
        assert a.candidatos[0].nome is None and BIA not in [c.nome for c in a.candidatos]
    elif caso == "rosto_instavel":
        # nem 5 seguidos da mesma pessoa nem 15 seguidos acima do limiar: o prazo decide, como não reconhecido
        for _ in range(10):
            _alimentar(sessao, relogio, quadro(100), 1)
            a = _alimentar(sessao, relogio, ninguem, 1)
        assert not a.concluida
        relogio.t += prazo
        a = sessao.processar(ninguem)
    else:
        vazio = dataclasses.replace(quadro(1), faces=(), recorte_cinza=None, face_normalizada=None)
        assert not _alimentar(sessao, relogio, vazio, 20).concluida
        relogio.t += prazo
        a = sessao.processar(vazio)
    if caso == "sem_rosto":
        # o prazo sem nenhum rosto utilizável: "sem rosto", e nada foi comparado, então nada vai para a trilha
        assert a.concluida and a.sem_rosto and not a.identificado and a.nome is None
        assert "IDENTIFICACAO" not in [r.evento.evento for r in app.administracao.trilha_recente()]
    else:
        assert a.concluida and not a.sem_rosto and not a.identificado and a.nome is None
        ev = app.administracao.trilha_recente()[0].evento
        assert (ev.evento, ev.resultado, ev.motivo) == ("IDENTIFICACAO", "REGISTRADO", "FACE_NAO_RECONHECIDA")
        assert ev.usuario_id is None and ev.distancia is None             # nunca a distância de quem não foi identificado
        assert ev.detalhe == "OPERADOR: RAFAEL DUARTE"


# ================================================================ seção do painel (só o administrador)
def identificacao_no_menu(janela) -> bool:
    return "paginaIdentificacao" in janela.navigationInterface.panel.items


def _abrir_identificacao(janela, usuario, senha, semente, relogio):
    """Login do administrador, painel aberto (rosto e celular) e a seção "Identificação facial"."""
    fazer_login(janela, usuario, senha, semente)
    cadastrar_celular_pela_tela(janela, semente)
    pa = janela.pagina_admin
    janela.app.identificacao.monotonico = relogio
    pa.identificacao._ligar_video = lambda: None
    pa._abrir_identificacao()
    assert pa.pilha_abas.currentWidget() is pa.identificacao and pa.identificacao.sessao is not None
    return pa


def _alimentar_vista(vista, relogio, q, n):
    imagem = QImage(640, 480, QImage.Format.Format_RGB888)
    andamento = None
    for _ in range(n):
        andamento = vista.sessao.processar(q)
        vista._ao_quadro(imagem, q, andamento)
        relogio.t += 0.1
    return andamento


def _textos(widget):
    return [w.text() for w in widget.findChildren(QLabel) if w.isVisibleTo(widget)]


def test_identificacao_mostra_a_decisao_sem_as_etapas_internas(janela):
    admin = vincular_admin(janela)
    bia = cadastrar(janela.app, "Beatriz Souza", Nivel.N2, "SP", "diretor2026", 100)
    ana = cadastrar(janela.app, "Ana Prado", Nivel.N1, None, "servidor2026", 300)
    assert not identificacao_no_menu(janela)                              # não é item de menu de ninguém
    fazer_login(janela, bia, "diretor2026", 100)
    assert not identificacao_no_menu(janela) and not janela.sessao.administrador   # o diretor nem tem o painel
    janela.encerrar_sessao("SAIDA")
    relogio = Relogio()
    pa = _abrir_identificacao(janela, admin, SENHA_ADMIN_USUARIO, 700, relogio)
    vista = pa.identificacao
    a = _alimentar_vista(vista, relogio, quadro(100), janela.app.cfg["reconhecimento.frames_confirmacao"])
    assert a.identificado
    textos = _textos(vista)
    for etapa in ("Recorte do rosto", "Face normalizada", "Padrão LBP", "padrão LBP"):     # nada do pipeline
        assert not any(etapa in t for t in textos), etapa
    assert not hasattr(vista, "img_lbp") and not hasattr(vista, "img_recorte")
    # fora do modo demonstração (fixado pela fixture): só a decisão, sem candidatos, distâncias nem tempo
    assert vista.modo_demonstracao is False
    assert vista.mensagem.text() == f"Identificado como {BIA}"
    assert not [t for t in textos for nome in NOMES - {BIA} if nome in t]  # os outros cadastros não aparecem
    assert not vista.titulo_candidatos.isVisibleTo(vista)
    for detalhe in ("distância", "limiar", "Tempo"):
        assert not [t for t in textos if detalhe in t], detalhe
    assert not [t for t in textos if re.search(r"\d+,\d+ s\b", t)]           # nenhum tempo medido
    assert not [t for t in textos for u in (admin, bia, ana) if u.matricula in t]   # matrícula nunca
    # câmera da identificação ligada conta como uso para a inatividade
    vista.trabalhador = object()
    assert janela._ocupado()
    vista.trabalhador = None
    # identificar de novo: outra sessão, decisão anterior limpa
    sessao = vista.sessao
    vista.botao_repetir.click()
    assert vista.sessao is not sessao and not vista.titulo_decisao.isVisibleTo(vista)
    # o bloqueio por inatividade tranca o painel e desliga a identificação: a senha sozinha não a reabre
    janela._inatividade._venceu()
    assert pa.pilha.currentIndex() == 3 and vista.sessao is None


@pytest.mark.parametrize("modo_demonstracao", [True])
def test_identificacao_no_modo_demonstracao_mostra_os_candidatos_e_o_tempo(janela):
    admin = vincular_admin(janela)
    bia = cadastrar(janela.app, "Beatriz Souza", Nivel.N2, "SP", "diretor2026", 100)
    ana = cadastrar(janela.app, "Ana Prado", Nivel.N1, None, "servidor2026", 300)
    relogio = Relogio()
    vista = _abrir_identificacao(janela, admin, SENHA_ADMIN_USUARIO, 700, relogio).identificacao
    assert vista.modo_demonstracao is True
    a = _alimentar_vista(vista, relogio, quadro(100), janela.app.cfg["reconhecimento.frames_confirmacao"])
    assert a.identificado
    textos = _textos(vista)
    assert vista.mensagem.text() == f"Identificado como {BIA}"
    assert vista.titulo_candidatos.isVisibleTo(vista)
    assert all(any(nome in t for t in textos) for nome in NOMES)          # os 3 cadastros mais parecidos
    assert any("0,4 s" in t for t in textos)                               # o tempo medido, sem promessa
    for etapa in ("Recorte do rosto", "Face normalizada", "Padrão LBP", "padrão LBP"):     # nada do pipeline
        assert not any(etapa in t for t in textos), etapa
    assert not [t for t in textos for u in (admin, bia, ana) if u.matricula in t]   # matrícula nunca


def test_video_congela_apos_decisao(janela):
    admin = vincular_admin(janela)
    cadastrar(janela.app, "Beatriz Souza", Nivel.N2, "SP", "diretor2026", 100)
    relogio = Relogio()
    vista = _abrir_identificacao(janela, admin, SENHA_ADMIN_USUARIO, 700, relogio).identificacao
    quadros = [QImage(640, 480, QImage.Format.Format_RGB888)
               for _ in range(janela.app.cfg["reconhecimento.frames_confirmacao"])]
    for imagem in quadros:
        vista._ao_quadro(imagem, quadro(100), vista.sessao.processar(quadro(100)))
        relogio.t += 0.1
    assert vista.sessao.andamento.identificado
    assert vista.visor._imagem is quadros[-1]                  # o quadro que gerou a decisão fica no vídeo
    assert vista.mensagem.text() == f"Identificado como {BIA}"
    atrasado = QImage(640, 480, QImage.Format.Format_RGB888)   # um quadro que ainda estava na fila do sinal
    vista._ao_quadro(atrasado, quadro(300), vista.sessao.processar(quadro(300)))
    assert vista.visor._imagem is quadros[-1]                  # congelado: não atualiza mais
    # "Identificar de novo" volta ao vivo
    vista.botao_repetir.click()
    ao_vivo = QImage(640, 480, QImage.Format.Format_RGB888)
    vista._ao_quadro(ao_vivo, quadro(100), vista.sessao.processar(quadro(100)))
    assert vista.visor._imagem is ao_vivo and not vista.sessao.andamento.concluida


def test_identificacao_nao_concede_acesso(janela):
    from ecosec.seguranca.acesso import s1_contencao
    from ecosec.servicos.autenticacao import IdentidadeComprovada
    rafael = vincular_admin(janela)
    bia = cadastrar(janela.app, "Beatriz Souza", Nivel.N2, "SP", "diretor2026", 100)
    tentativas = janela.app.autenticacao.tentativas
    tentativas.salvar(s1_contencao.registrar_falha(None, bia.matricula, datetime.now(),
                                                   janela.app.autenticacao.p.contencao))
    relogio = Relogio()
    pa = _abrir_identificacao(janela, rafael, SENHA_ADMIN_USUARIO, 700, relogio)
    assert janela.sessao.administrador
    identidade = janela.sessao.identidade
    chaves = (bia.matricula, rafael.matricula, f"{rafael.matricula}#ADM")
    contencao = {c: tentativas.obter(c) for c in chaves}
    antes = {r.hash_registro for r in janela.app.administracao.trilha_recente()}
    a = _alimentar_vista(pa.identificacao, relogio, quadro(100), janela.app.cfg["reconhecimento.frames_confirmacao"])
    assert a.identificado and a.nome == BIA
    novos = [r.evento for r in janela.app.administracao.trilha_recente() if r.hash_registro not in antes]
    assert [(e.evento, e.resultado) for e in novos] == [("IDENTIFICACAO", "REGISTRADO")]   # nenhum AUTENTICACAO
    assert novos[0].detalhe.startswith("OPERADOR: RAFAEL DUARTE;")          # quem operou, não quem foi identificado
    assert janela.sessao.identidade is identidade and identidade.usuario_id == rafael.id  # o logado não muda
    assert {c: tentativas.obter(c) for c in chaves} == contencao          # a falha da Beatriz continua lá
    assert not any(isinstance(getattr(a, f.name), IdentidadeComprovada) for f in dataclasses.fields(a))


# ================================================================ arquitetura
def test_identificacao_so_fala_com_o_servico():
    pagina = RAIZ / "interface" / "pagina_identificacao.py"
    assert pagina.exists(), "falta a página de identificação (ecosec/interface/pagina_identificacao.py)"
    proibidos = ("ecosec.visao.reconhecimento", "ecosec.seguranca", "ecosec.repositorios")
    assert not [m for m in _imports(pagina) if any(m == p or m.startswith(p + ".") for p in proibidos)]
    assert "app.identificacao" in pagina.read_text(encoding="utf-8")        # pede ao serviço
    # nenhuma tela chama o reconhecedor direto (app.reconhecedor está exposto na Aplicacao)
    assert not [a.name for a in (RAIZ / "interface").rglob("*.py") if "reconhecedor" in a.read_text(encoding="utf-8")]
