"""A interface com perfis. Cada perfil vê só o próprio escopo: as outras camadas não
aparecem (nem aba, nem cartão no Início, nem "sem acesso" ou "incluído no seu nível", nem menção em texto). O
administrador vê a Administração e nenhuma camada; a identificação 1:N fica dentro do painel; a configuração
inicial cria o primeiro administrador sem o "Você é o administrador?".

Os textos são varridos como a pessoa os lê: rótulos, botões, dicas e itens de lista, mais o texto desenhado nos
relatórios (Tela.texto) e o glossário.
"""
import re

import pytest
from PySide6.QtWidgets import QAbstractButton, QComboBox, QLabel, QWidget

from ecosec.dominio.niveis import Nivel
from test_interface import cadastrar_celular_pela_tela, destravar_admin, fazer_login, janela, no_menu
from test_perfis_servicos import SENHA_FORTE, acervo, cadastrar_perfil, usuario  # noqa: F401

SEMENTE = {"ADMINISTRADOR": 700, "SERVIDOR": 300, "DIRETOR": 100, "MINISTRO": 900}


def outras_camadas(propria: int | None) -> re.Pattern:
    """Qualquer menção a uma camada que não é a da pessoa, e as situações que o Início não mostra mais."""
    outras = "".join(str(n) for n in (1, 2, 3) if n != propria)
    return re.compile(rf"[Nn][íi]ve(?:l|is) [{outras}]|\bN[{outras}]\b|n[íi]veis abaixo|Incluído no seu nível|"
                      rf"Sem acesso|Fora do seu nível|Os níveis do sistema|n[íi]veis 2 e 3")


def identificacao_no_menu(janela) -> bool:
    """A identificação 1:N fica no painel de Administração, fora do menu."""
    return "paginaIdentificacao" in janela.navigationInterface.panel.items


def textos(raiz: QWidget) -> list[str]:
    lidos = [l.text() for l in raiz.findChildren(QLabel)] + [b.text() for b in raiz.findChildren(QAbstractButton)]
    lidos += [w.toolTip() for w in raiz.findChildren(QWidget) if w.toolTip()]
    for combo in raiz.findChildren(QComboBox):
        lidos += [combo.itemText(i) for i in range(combo.count())]
    return [t for t in lidos if t]


def mencoes(raiz: QWidget, propria: int | None) -> list[str]:
    padrao = outras_camadas(propria)
    return [t for t in textos(raiz) if padrao.search(t)]


def admin_pela_configuracao(janela):
    """Configuração inicial: senha de instalação e o primeiro cadastro, Externo, que vira o primeiro admin."""
    pa = destravar_admin(janela)
    admin = cadastrar_perfil(janela.app, "Rafael Duarte", "EXTERNO", SEMENTE["ADMINISTRADOR"])
    pa._cadastro_finalizado(admin)                       # o que o assistente faz ao concluir
    janela._aplicar_estado()
    return admin


def entrar_como(janela, perfil, uf=None):
    admin_pela_configuracao(janela)
    u = cadastrar_perfil(janela.app, f"Pessoa {perfil.title()}", perfil, SEMENTE[perfil], uf=uf)
    return u, fazer_login(janela, u, SENHA_FORTE, SEMENTE[perfil])


# configuração inicial e assistente
def test_configuracao_inicial_so_oferece_administrador_e_cria_o_primeiro_admin(janela):
    from ecosec.interface.janela import Estado
    pa = destravar_admin(janela)
    pa._novo_cadastro()
    combo = pa.assistente.combo_perfil
    assert [combo.itemText(i) for i in range(combo.count())] == ["Externo"]   # o primeiro admin é um Externo
    pa._encerrar_assistente()
    admin = cadastrar_perfil(janela.app, "Rafael Duarte", "EXTERNO", SEMENTE["ADMINISTRADOR"])
    pa._cadastro_finalizado(admin)
    assert janela.app.administracao.eh_administrador(admin.id)
    assert janela.estado is Estado.LOGIN
    janela.perguntar_senha_admin = lambda nome: pytest.fail("o vínculo no login saiu (D9)")
    assert fazer_login(janela, admin, SENHA_FORTE, SEMENTE["ADMINISTRADOR"]).administrador


def test_assistente_do_admin_oferece_os_quatro_perfis(janela):
    admin = admin_pela_configuracao(janela)
    fazer_login(janela, admin, SENHA_FORTE, SEMENTE["ADMINISTRADOR"])
    cadastrar_celular_pela_tela(janela)
    pa = janela.pagina_admin
    pa._novo_cadastro()
    combo = pa.assistente.combo_perfil
    assert [combo.itemText(i) for i in range(combo.count())] == [
        "Externo", "Servidor", "Diretor", "Ministro"]


# administrador
def test_administrador_ve_so_a_administracao(janela):
    admin = admin_pela_configuracao(janela)
    sessao = fazer_login(janela, admin, SENHA_FORTE, SEMENTE["ADMINISTRADOR"])
    assert sessao.administrador and sessao.papel == "Administrador"
    assert no_menu(janela, janela.pagina_admin)
    assert not any(no_menu(janela, p) for p in janela.paginas_nivel.values())
    assert not identificacao_no_menu(janela)             # a identificação foi para o painel
    inicio = janela.pagina_inicio
    assert inicio.cartoes == [] and inicio.cartao_admin.isVisibleTo(inicio)
    assert mencoes(inicio, None) == []


def test_administrador_nao_abre_camada_nem_pelo_atalho_da_pagina(janela):
    """Defesa em profundidade: sem item no menu, e mesmo trocando de página à força, quem nega é o serviço."""
    admin = admin_pela_configuracao(janela)
    fazer_login(janela, admin, SENHA_FORTE, SEMENTE["ADMINISTRADOR"])
    pagina = janela.paginas_nivel[Nivel.N1]
    janela.switchTo(pagina)
    assert pagina.pilha.currentIndex() == 0                              # o aviso de negado, não o acervo
    ev = janela.app.administracao.trilha_recente()[0].evento
    assert (ev.evento, ev.resultado, ev.motivo, ev.usuario_id) == ("AUTENTICACAO", "NEGADO", "NIVEL_INSUFICIENTE",
                                                                   admin.id)


def test_painel_do_admin_tem_perfil_identificacao_e_trilha_mascarada(janela):
    admin = admin_pela_configuracao(janela)
    fazer_login(janela, admin, SENHA_FORTE, SEMENTE["ADMINISTRADOR"])
    janela.app.administracao.trilha.registrar("CONSULTA", "CONCEDIDO", "MEMORIA_CUSTO_RESPONSAVEL",
                                              nivel_solicitado=3, usuario_id=admin.id,
                                              detalhe="2 pendencias; RESPONSAVEL FICTICIO LTDA")
    cadastrar_celular_pela_tela(janela)
    pa = janela.pagina_admin
    cabecalho = [pa.tabela.horizontalHeaderItem(j).text() for j in range(pa.tabela.columnCount())]
    assert "Perfil" in cabecalho and "Nível" not in cabecalho
    assert "identificacao" in pa.abas.items                             # Dentro do painel
    pa._abrir_trilha()
    t = pa.tabela_trilha
    celulas = " ".join(t.item(i, j).text() for i in range(t.rowCount()) for j in range(t.columnCount())
                       if t.item(i, j))
    assert "MEMORIA_CUSTO_RESPONSAVEL" in celulas and "RESPONSAVEL FICTICIO" not in celulas


# cada perfil, só o seu escopo
@pytest.mark.parametrize("perfil, uf, camada", [("SERVIDOR", None, Nivel.N1), ("DIRETOR", "SP", Nivel.N2),
                                                ("MINISTRO", None, Nivel.N3)])
def test_inicio_mostra_so_o_cartao_do_proprio_perfil(janela, perfil, uf, camada):
    _, sessao = entrar_como(janela, perfil, uf)
    assert sessao.niveis_com_aba == (camada,)
    inicio = janela.pagina_inicio
    assert [c.nivel for c in inicio.cartoes] == [camada]
    assert [p for n, p in janela.paginas_nivel.items() if no_menu(janela, p)] == [janela.paginas_nivel[camada]]
    assert not identificacao_no_menu(janela)
    assert mencoes(inicio, camada.value) == []


def test_tela_do_acervo_do_diretor_sem_outras_camadas(janela):
    entrar_como(janela, "DIRETOR", "SP")
    pagina = janela.paginas_nivel[Nivel.N2]
    janela.switchTo(pagina)
    assert pagina.pilha.currentIndex() == 2
    assert len(pagina.acervo.cartoes_relatorio) == 3                    # só os relatórios A2
    assert mencoes(pagina, 2) == []


def test_camadas_de_seguranca_nao_listam_os_niveis(janela):
    entrar_como(janela, "SERVIDOR")
    assert mencoes(janela.pagina_camadas, 1) == []
    assert not any(t.startswith("Níveis:") for t in textos(janela.pagina_camadas))


# textos fora das telas
CODIGOS = {Nivel.N1: ("A1-01", "A1-02", "A1-05"), Nivel.N2: ("A2-01", "A2-02", "A2-04"),
           Nivel.N3: ("A3-01", "A3-02", "A3-03")}


@pytest.mark.parametrize("perfil, uf, camada", [("SERVIDOR", None, Nivel.N1), ("DIRETOR", "SP", Nivel.N2),
                                                ("MINISTRO", None, Nivel.N3)])
def test_relatorios_nao_citam_outra_camada(acervo, monkeypatch, perfil, uf, camada):
    from ecosec.acervo.desenho import Tela
    desenhados, original = [], Tela.texto

    def escutar(self, x, y, conteudo, *args, **kwargs):
        desenhados.append(str(conteudo))
        return original(self, x, y, conteudo, *args, **kwargs)
    monkeypatch.setattr(Tela, "texto", escutar)
    u = usuario(perfil, 3, uf=uf)
    for codigo in CODIGOS[camada]:
        acervo.abrir(codigo, u, camada)
    padrao = outras_camadas(camada.value)
    assert [t for t in desenhados if padrao.search(t)] == []


@pytest.mark.parametrize("camada", list(Nivel))
def test_glossario_de_cada_camada_nao_cita_outra(camada):
    from ecosec.acervo import vocabulario
    padrao = outras_camadas(camada.value)
    secoes = vocabulario.glossario(camada)
    lidos = [t for secao in secoes for t in (secao.titulo, secao.descricao) if t]
    lidos += [t for secao in secoes for termo in secao.termos for t in (termo.rotulo, termo.definicao, termo.longo)
              if t]
    assert lidos and [t for t in lidos if padrao.search(t)] == []


def test_mensagem_de_recusa_do_n3_nao_aponta_outra_camada(acervo):
    from ecosec.servicos.acervo import ErroAcervo
    caio = usuario("MINISTRO", 3)
    resumo = acervo.resumo_agregado(caio, 3)
    with pytest.raises(ErroAcervo) as erro:
        acervo.exportar_resumo(resumo, caio, "POR UF", "x.csv")
    assert not outras_camadas(3).search(str(erro.value)), str(erro.value)
