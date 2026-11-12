"""Interface: as telas montam e os fluxos funcionam, sem câmera, sem janela visível.

A câmera é substituída: `_ligar_video` vira no-op e os quadros são entregues
à mão, como a thread de vídeo faria.
"""
import cv2
import numpy as np
import pytest
from PySide6.QtGui import QImage

from ecosec.aplicacao import montar
from ecosec.dominio.niveis import Nivel
from ecosec.dominio.perfis import Perfil
from ecosec.servicos.autenticacao import Etapa
from ecosec.servicos.cadastro import DadosCadastro
from ecosec.visao.pipeline import ResultadoQuadro
from ecosec.visao.qualidade import MedidasQualidade

SENHA_ADMIN = "Admin#Forte2026"


def face(semente):
    base = np.random.default_rng(semente).integers(40, 215, (50, 50)).astype(np.uint8)
    return cv2.resize(base, (200, 200), interpolation=cv2.INTER_LINEAR)


def quadro(semente, boa=True):
    return ResultadoQuadro(faces=((220, 120, 200, 200),), fonte="HAAR", largura=640, altura=480,
                           medidas=MedidasQualidade(300, 120, 40, 2),
                           face_normalizada=face(semente) if boa else None,
                           recorte_cinza=np.zeros((10, 10), np.uint8))


@pytest.fixture
def janela(qt, tmp_path):
    from ecosec.interface.estilo import aplicar_tema
    from ecosec.interface.janela import JanelaPrincipal
    app = montar(caminho_env=tmp_path / ".env", modo="memoria")
    # o risco de contexto depende do relógio real (fim de semana, noite): os testes de tela não podem
    # mudar de resultado conforme o dia. O MFA adaptativo tem testes próprios, com relógio controlado.
    app.autenticacao.contexto_parametros = None
    app.administracao.custo = app.cadastro.custo = app.autenticacao.p.custo_bcrypt = 4
    app.cadastro.frames_por_sessao = 3
    app.cadastro.leitura_minima_segundos = 0      # o teste do relógio de leitura liga o seu
    aplicar_tema("escuro")
    j = JanelaPrincipal(app)
    j.show()
    yield j
    # close() só esconde: sem destruir, as janelas se acumulam e a troca de
    # tema do teste seguinte reestiliza TODAS (cada teste ficava ~1 s mais lento)
    j.close()
    # o roteador do qfluentwidgets é global e guarda o StackedWidget de toda FluentWindow: destruída a janela, a
    # entrada ficava, e o próximo Pivot.clear() de outro arquivo estourava "already deleted" (falha 7)
    from qfluentwidgets.common.router import qrouter
    qrouter.stackHistories.pop(j.stackedWidget, None)
    qrouter.history = [item for item in qrouter.history if item.stacked is not j.stackedWidget]
    j.deleteLater()
    from PySide6.QtCore import QCoreApplication, QEvent
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def cadastrar(app, nome, nivel, uf, senha, semente, perfil=None):
    aceite = app.cadastro.registrar_aceite(nome)
    coleta = app.cadastro.nova_coleta(aceite)
    for s in range(2):
        for i in range(3):
            coleta.oferecer(quadro(semente + 10 * s + i))
        if s == 0:
            coleta.avancar_sessao()
    return app.cadastro.concluir(DadosCadastro(nome, nivel, uf, senha, senha, perfil=perfil), aceite, coleta)


def destravar_admin(j):
    pa = j.pagina_admin
    j.switchTo(pa)
    pa.def_senha.setText(SENHA_ADMIN)
    pa.def_confirmacao.setText(SENHA_ADMIN)
    pa._definir()
    pa.campo_admin.setText(SENHA_ADMIN)
    pa._entrar()
    return pa


# ---------------------------------------------------------------- administração
def test_primeira_execucao_pede_para_definir_a_senha(janela):
    assert janela.pagina_admin.pilha.currentIndex() == 0


def test_admin_entra_e_ve_o_painel(janela):
    pa = destravar_admin(janela)
    assert pa.pilha.currentIndex() == 2


def test_senha_admin_errada_nao_entra(janela):
    pa = destravar_admin(janela)
    pa.bloquear()
    pa.campo_admin.setText("errada")
    pa._entrar()
    assert pa.pilha.currentIndex() == 1


def test_sair_da_pagina_tranca_o_painel_e_descarta_o_cadastro(janela):
    pa = destravar_admin(janela)
    pa._novo_cadastro()
    assistente = pa.assistente
    assistente.coleta = janela.app.cadastro.nova_coleta(janela.app.cadastro.registrar_aceite("Bia"))
    assistente.coleta.oferecer(quadro(1))
    coleta = assistente.coleta
    janela.switchTo(janela.pagina_camadas)
    assert pa.assistente is None and pa.pilha.currentIndex() == 1
    assert coleta.faces() == []                    # biometria apagada


# ---------------------------------------------------------------- assistente
def test_preparacao_exige_os_tres_requisitos(janela):
    pa = destravar_admin(janela)
    pa._novo_cadastro()
    a = pa.assistente
    assert a.pilha.currentIndex() == 0 and not a.botao_comecar.isEnabled()
    for caixa in a.requisitos[:2]:
        caixa.setChecked(True)
    assert not a.botao_comecar.isEnabled()
    a.requisitos[2].setChecked(True)
    assert a.botao_comecar.isEnabled()


def _ate_o_termo(janela):
    pa = destravar_admin(janela)
    pa._novo_cadastro()
    a = pa.assistente
    for caixa in a.requisitos:
        caixa.setChecked(True)
    a.botao_comecar.click()
    return pa, a


def test_termo_so_libera_o_aceite_depois_de_ler_marcar_a_e_assinar(janela):
    _, a = _ate_o_termo(janela)
    assert a.pilha.currentIndex() == 1 and not a.botao_aceitar.isEnabled()
    a.campo_assinatura.setText("Beatriz Souza")
    a.check_lido.setChecked(True)
    assert not a.botao_aceitar.isEnabled() and "finalidade (a)" in a.motivo_aceite.text()
    a.check_finalidade_a.setChecked(True)
    assert a.botao_aceitar.isEnabled() and a.motivo_aceite.text() == ""
    a.campo_assinatura.setText("Beatriz")                       # sem sobrenome
    assert not a.botao_aceitar.isEnabled()


def test_termo_so_libera_o_aceite_depois_do_tempo_minimo_de_leitura(janela):
    janela.app.cadastro.leitura_minima_segundos = 30
    _, a = _ate_o_termo(janela)
    a.check_finalidade_a.setChecked(True)
    a.campo_assinatura.setText("Beatriz Souza")
    assert not a.check_lido.isEnabled() and not a.botao_aceitar.isEnabled()
    assert "30 s" in a.relogio_leitura.text() and "tempo mínimo" in a.motivo_aceite.text()
    a.check_lido.setChecked(True)                     # mesmo forçado, o aceite continua travado
    a._aceitar()
    assert a.aceite is None
    a._inicio_leitura -= 31                            # o tempo passou
    a._tique_leitura()
    assert a.check_lido.isEnabled() and a.botao_aceitar.isEnabled() and a.relogio_leitura.text() == ""


def test_termo_e_uma_folha_inteira_sem_caixa_com_rolagem_propria(janela):
    _, a = _ate_o_termo(janela)
    assert "QUADRO-RESUMO" in a.texto_termo.text() and "CLÁUSULA 11ª" in a.texto_termo.text()
    assert not hasattr(a.texto_termo, "verticalScrollBar")      # quem rola é a página
    assert "(X)" not in a.texto_termo.text()                    # nada vem marcado antes de assinar


def test_via_do_titular_so_aparece_no_fim_e_sai_assinada(janela, tmp_path):
    from PySide6.QtPdf import QPdfDocument
    from ecosec.interface.assistente_cadastro import FIM, TERMO
    _, a = _ate_o_termo(janela)
    assert not a.pilha.widget(TERMO).isAncestorOf(a.botao_pdf)  # antes de assinar, não há via
    assert a.pilha.widget(FIM).isAncestorOf(a.botao_pdf)
    a.check_lido.setChecked(True)
    a.check_finalidade_a.setChecked(True)
    a.campo_assinatura.setText("Beatriz Souza")
    a._aceitar()
    a.usuario = cadastrar(janela.app, "Beatriz Souza", Nivel.N2, "SP", "diretor2026", 400)
    caminho = tmp_path / "via.pdf"
    a.gerar_via_pdf(str(caminho))
    pdf = QPdfDocument()
    pdf.load(str(caminho))
    texto = " ".join(pdf.getAllText(p).text() for p in range(pdf.pageCount()))
    assert "BEATRIZ SOUZA" in texto and a.usuario.matricula in texto
    assert a.aceite.hash_termo in texto.replace("\n", "")       # o hash do aceite, não um recalculado


def test_finalidade_b_e_opcional_e_fica_registrada(janela):
    _, a = _ate_o_termo(janela)
    a.check_lido.setChecked(True)
    a.check_finalidade_a.setChecked(True)
    a.campo_assinatura.setText("Beatriz Souza")
    a._aceitar()                                                # (b) desmarcada
    assert a.aceite.autoriza_pesquisa is False and a.pilha.currentIndex() == 2


def test_recusar_o_termo_nao_cria_nada(janela):
    pa = destravar_admin(janela)
    pa._novo_cadastro()
    pa.assistente._recusar()
    assert janela.app.administracao.listar() == []
    assert pa.assistente is None


def _assistente_com_todos_os_perfis(janela):
    """O assistente de um administrador logado oferece os seis perfis; o da configuração inicial, só o de
    administrador. Já com o termo aceito, na etapa dos dados."""
    from ecosec.interface.assistente_cadastro import AssistenteCadastro
    a = AssistenteCadastro(janela.app, perfis=tuple(Perfil))
    for caixa in a.requisitos:
        caixa.setChecked(True)
    a.botao_comecar.click()
    a.check_lido.setChecked(True)
    a.check_finalidade_a.setChecked(True)
    a.campo_assinatura.setText("Beatriz Souza")
    a._aceitar()
    return a


def test_dados_n2_sem_uf_sao_recusados_com_erro_ao_lado_e_sem_camera(janela):
    a = _assistente_com_todos_os_perfis(janela)
    assert a.pilha.currentIndex() == 2
    a.combo_perfil.setCurrentIndex(list(Perfil).index(Perfil.DIRETOR))      # diretor, UF não escolhida
    a.campo_senha.setText("diretor2026")
    a.campo_confirmacao.setText("diretor2026")
    a._confirmar_dados()
    assert a.pilha.currentIndex() == 2 and a.coleta is None
    assert "UF" in a.erros_dados.text()             # o erro fica visível ao lado do formulário


def test_checklist_acompanha_a_politica_do_perfil(janela):
    a = _assistente_com_todos_os_perfis(janela)
    a.campo_senha.setText("diretor2026")
    a.campo_confirmacao.setText("diretor2026")
    a.combo_perfil.setCurrentIndex(list(Perfil).index(Perfil.SERVIDOR))
    assert a.checklist.tudo_cumprido               # servidor: basta letra e número
    a.combo_perfil.setCurrentIndex(list(Perfil).index(Perfil.MINISTRO))
    assert not a.checklist.tudo_cumprido           # camada 3: senha forte
    a.combo_perfil.setCurrentIndex(list(Perfil).index(Perfil.EXTERNO))
    assert not a.checklist.tudo_cumprido           # Externo: forte (pode virar administrador)


def test_cadastro_aparece_na_tabela(janela):
    cadastrar(janela.app, "Beatriz Souza", Nivel.N2, "SP", "diretor2026", 100)
    pa = destravar_admin(janela)
    assert pa.tabela.rowCount() == 1
    assert pa.tabela.item(0, 1).text() == "BEATRIZ SOUZA"


def test_camadas_listadas(janela):
    janela.switchTo(janela.pagina_camadas)
    assert janela.pagina_camadas.widget() is not None


def test_camadas_todas_implementadas_e_s7_conforme_a_configuracao(janela):
    """As dez camadas aparecem implementadas; a S7 diz que está desligada quando o config a desliga."""
    from ecosec.interface.fluent import CaptionLabel
    from ecosec.interface.pagina_camadas import DESLIGADA, IMPLEMENTADA
    estados = [r.text() for r in janela.pagina_camadas.findChildren(CaptionLabel)]
    s7_ligada = janela.app.autenticacao.p.acesso.exigir_segunda_pessoa
    assert len(estados) == 10
    assert estados.count(IMPLEMENTADA) == (10 if s7_ligada else 9)
    assert estados.count(DESLIGADA) == (0 if s7_ligada else 1)


# ---------------------------------------------------------------- trilha e modo demonstração
def test_aba_da_trilha_lista_eventos_e_verifica(janela):
    pa = destravar_admin(janela)
    pa._abrir_trilha()
    assert pa.tabela_trilha.rowCount() >= 2                     # senha definida + login do admin
    pa._verificar_trilha()
    assert "íntegra" in pa.resultado_trilha.text()


def test_aba_de_relatorios_do_sistema(janela):
    pa = destravar_admin(janela)
    pa._abrir_relatorios()
    for indice in range(pa.combo_relatorio.count()):
        pa.combo_relatorio.setCurrentIndex(indice)
        assert pa.tabela_relatorio.columnCount() > 0 and pa.explicacao_relatorio.text()


# ---------------------------------------------------------------- responsividade
def test_tabela_de_usuarios_mostra_o_perfil_e_se_adapta_a_largura(janela, qt):
    cadastrar(janela.app, "Beatriz Souza", Nivel.N2, "SP", "diretor2026", 100)
    pa = destravar_admin(janela)
    assert pa.tabela.item(0, 2).text() == "Diretor"
    janela.resize(1700, 900)
    qt.processEvents()
    assert not pa.tabela.isColumnHidden(8) and not pa.tabela.isColumnHidden(6)
    janela.resize(900, 700)
    qt.processEvents()
    assert pa.tabela.isColumnHidden(8)                       # "Criado em" sai antes de cortar o nome
    assert pa.tabela.columnWidth(1) >= 220 or pa.tabela.isColumnHidden(6)


# ---------------------------------------------------------------- login de entrada e papéis
SENHA_ADMIN_USUARIO = "Ministro#2026x"


def vincular_admin(janela):
    """Configuração inicial: o primeiro cadastro, com o perfil de administrador (sem camada), vira o
    primeiro admin pela senha de instalação já digitada para abrir a configuração."""
    destravar_admin(janela)
    admin = cadastrar(janela.app, "Rafael Duarte", None, None, SENHA_ADMIN_USUARIO, 700, perfil=Perfil.EXTERNO)
    assert janela.app.administracao.vincular_primeiro_administrador(admin.id) is None
    janela._aplicar_estado()
    return admin


SENHA_MINISTRO = "Custodia#2026"


def cadastrar_ministro(janela):
    """O ministro (camada 3) dos testes do step-up do N3: o administrador não tem camada."""
    return cadastrar(janela.app, "Caio Mendes", Nivel.N3, None, SENHA_MINISTRO, 900)


def alimentar_tela(tela, semente, n):
    imagem = QImage(640, 480, QImage.Format.Format_RGB888)
    for i in range(n):
        tela._ao_quadro(imagem, quadro(semente + i), tela.sessao.processar(quadro(semente + i)))


def fazer_login(janela, usuario, senha, semente):
    """Login de entrada completo, sem câmera (quadros fabricados do rosto cadastrado)."""
    tela = janela.pagina_entrada.autenticacao
    tela._ligar_video = lambda: None
    if tela.sessao is None:
        janela.pagina_entrada.iniciar()
    tela.campo_matricula.setText(usuario.matricula)
    tela.campo_senha.setText(senha)
    tela._enviar_credenciais()
    alimentar_tela(tela, semente, janela.app.autenticacao.p.frames_confirmacao)
    assert tela.botao_entrar.isVisible(), tela.res_texto.text()
    tela._entrar()
    return janela.sessao


def no_menu(janela, pagina):
    return not janela.navigationInterface.widget(pagina.objectName()).isHidden()


def test_configuracao_inicial_mostra_so_a_administracao(janela):
    from ecosec.interface.janela import Estado
    assert janela.estado is Estado.CONFIGURACAO
    assert no_menu(janela, janela.pagina_admin) and not no_menu(janela, janela.pagina_inicio)
    assert not any(no_menu(janela, p) for p in janela.paginas_nivel.values())


def test_depois_do_vinculo_o_sistema_abre_pelo_login_e_nada_mais_aparece(janela):
    from ecosec.interface.janela import Estado
    vincular_admin(janela)
    assert janela.estado is Estado.LOGIN and janela.stackedWidget.currentWidget() is janela.pagina_entrada
    paginas = [janela.pagina_inicio, janela.pagina_camadas, janela.pagina_admin, *janela.paginas_nivel.values()]
    assert not any(no_menu(janela, p) for p in paginas)
    assert janela.pagina_entrada.autenticacao.sessao.andamento.etapa is Etapa.CREDENCIAIS


def test_login_com_senha_errada_mostra_negacao(janela):
    vincular_admin(janela)
    bia = cadastrar(janela.app, "Beatriz Souza", Nivel.N2, "SP", "diretor2026", 100)
    tela = janela.pagina_entrada.autenticacao
    tela.campo_matricula.setText(bia.matricula)
    tela.campo_senha.setText("errada0000")
    tela._enviar_credenciais()
    assert tela.campo_senha.text() == ""                    # a senha não fica na tela
    assert tela.pilha.currentIndex() == 2 and not tela.botao_entrar.isVisible()
    assert janela.sessao is None


def test_senha_do_administrador_pode_ser_definida_pelo_teclado(janela):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    pa = janela.pagina_admin
    janela.switchTo(pa)
    pa.def_senha.setText(SENHA_ADMIN)
    pa.def_confirmacao.setText(SENHA_ADMIN)
    QTest.keyClick(pa.def_confirmacao, Qt.Key.Key_Return)
    assert janela.app.administracao.configurado


def test_tela_nao_revela_se_a_matricula_existe(janela):
    """Matrícula inexistente e senha errada: a mesma tela, palavra por palavra.
    O detalhe mostrava USUARIO_INEXISTENTE x SENHA_INCORRETA e entregava quais existem."""
    vincular_admin(janela)
    bia = cadastrar(janela.app, "Beatriz Souza", Nivel.N2, "SP", "diretor2026", 100)
    tela = janela.pagina_entrada.autenticacao
    telas = []
    for matricula in (bia.matricula, "ZZZZZZZ"):
        janela.pagina_entrada.iniciar()
        tela.campo_matricula.setText(matricula)
        tela.campo_senha.setText("errada0000")
        tela._enviar_credenciais()
        telas.append((tela.res_titulo.text(), tela.res_texto.text(), tela.res_detalhe.text()))
    assert telas[0] == telas[1]
    assert "INEXISTENTE" not in telas[1][2]


def test_o_erro_que_bloqueia_ja_avisa_ate_quando(janela):
    vincular_admin(janela)
    bia = cadastrar(janela.app, "Beatriz Souza", Nivel.N2, "SP", "diretor2026", 100)
    tela = janela.pagina_entrada.autenticacao
    for _ in range(janela.app.autenticacao.p.contencao.tentativas_maximas):
        janela.pagina_entrada.iniciar()
        tela.campo_matricula.setText(bia.matricula)
        tela.campo_senha.setText("errada0000")
        tela._enviar_credenciais()
    assert "bloqueada até as" in tela.res_texto.text()


def test_servidor_ve_so_a_aba_e_o_cartao_do_nivel_1(janela):
    """Escopo exclusivo: as outras camadas não aparecem nem como cartão "sem acesso"."""
    vincular_admin(janela)
    ana = cadastrar(janela.app, "Ana Prado", Nivel.N1, None, "servidor2026", 300)
    sessao = fazer_login(janela, ana, "servidor2026", 300)
    assert sessao.papel == "Servidor"
    assert no_menu(janela, janela.paginas_nivel[Nivel.N1])
    assert not no_menu(janela, janela.paginas_nivel[Nivel.N2]) and not no_menu(janela, janela.paginas_nivel[Nivel.N3])
    assert not no_menu(janela, janela.pagina_admin)
    assert [c.nivel for c in janela.pagina_inicio.cartoes] == [Nivel.N1]


def test_diretor_abre_o_nivel_2_direto_pelo_step_up(janela):
    vincular_admin(janela)
    bia = cadastrar(janela.app, "Beatriz Souza", Nivel.N2, "SP", "diretor2026", 100)
    fazer_login(janela, bia, "diretor2026", 100)
    assert [c.nivel for c in janela.pagina_inicio.cartoes] == [Nivel.N2]     # o N1 não vem junto
    pagina = janela.paginas_nivel[Nivel.N2]
    janela.switchTo(pagina)
    assert pagina.pilha.currentIndex() == 2                                 # sem pedir nada de novo
    assert "região SP" in pagina.acervo.subtitulo.text() and len(pagina.acervo.cartoes_relatorio) == 3
    janela.switchTo(janela.pagina_inicio)                                    # sair da aba encerra o acervo
    assert pagina.pilha.currentIndex() == 0


def test_ministro_ve_so_a_aba_do_nivel_3_e_ela_comeca_no_rosto(janela):
    """O administrador não tem camada: quem abre o N3 é o ministro, e o step-up começa no rosto."""
    vincular_admin(janela)
    caio = cadastrar_ministro(janela)
    sessao = fazer_login(janela, caio, SENHA_MINISTRO, 900)
    assert not sessao.administrador and sessao.papel == "Ministro"
    assert no_menu(janela, janela.paginas_nivel[Nivel.N3]) and not no_menu(janela, janela.pagina_admin)
    assert not no_menu(janela, janela.paginas_nivel[Nivel.N1]) and not no_menu(janela, janela.paginas_nivel[Nivel.N2])
    pagina = janela.paginas_nivel[Nivel.N3]
    pagina.autenticacao._ligar_video = lambda: None
    janela.switchTo(pagina)
    assert pagina.pilha.currentIndex() == 1
    assert pagina.autenticacao.sessao.andamento.etapa is Etapa.ROSTO         # matrícula e senha vêm do login


def test_segunda_pessoa_nao_perde_o_que_digita_a_cada_quadro(janela):
    """Regressão: o vídeo manda um Andamento por quadro; o campo não pode ser limpo a cada um."""
    import dataclasses
    p = janela.app.autenticacao.p
    p.acesso = dataclasses.replace(p.acesso, exigir_segunda_pessoa=True)     # desligada no config do projeto
    vincular_admin(janela)
    caio = cadastrar_ministro(janela)
    fazer_login(janela, caio, SENHA_MINISTRO, 900)
    pagina = janela.paginas_nivel[Nivel.N3]
    tela = pagina.autenticacao
    tela._ligar_video = lambda: None
    janela.switchTo(pagina)
    sessao = tela.sessao
    sessao.s.criar_detector = lambda _: type("G", (), {"alimentar": lambda s, r: True, "progresso": 1.0})()
    alimentar_tela(tela, 900, 20)                # rosto + 2 gestos, cada um com conferência depois
    assert sessao.andamento.pessoa == 2 and sessao.andamento.etapa is Etapa.CREDENCIAIS
    tela.campo_matricula.setText("PARCIAL")
    alimentar_tela(tela, 1, 1)
    assert tela.campo_matricula.text() == "PARCIAL"


def test_trocar_de_pagina_cancela_a_tentativa(janela):
    vincular_admin(janela)
    caio = cadastrar_ministro(janela)
    fazer_login(janela, caio, SENHA_MINISTRO, 900)
    pagina = janela.paginas_nivel[Nivel.N3]
    pagina.autenticacao._ligar_video = lambda: None
    janela.switchTo(pagina)
    sessao = pagina.autenticacao.sessao
    janela.switchTo(janela.pagina_camadas)
    assert sessao.andamento.etapa is Etapa.CONCLUIDA and sessao.andamento.cancelada




def test_encerrar_sessao_volta_ao_login_e_fica_na_trilha(janela):
    from ecosec.interface.janela import Estado
    vincular_admin(janela)
    ana = cadastrar(janela.app, "Ana Prado", Nivel.N1, None, "servidor2026", 300)
    fazer_login(janela, ana, "servidor2026", 300)
    janela.encerrar_sessao("SAIDA")
    assert janela.estado is Estado.LOGIN and janela.stackedWidget.currentWidget() is janela.pagina_entrada
    assert not no_menu(janela, janela.pagina_inicio)
    ultimo = janela.app.administracao.trilha_recente()[0].evento
    assert (ultimo.evento, ultimo.motivo, ultimo.usuario_id) == ("SESSAO", "SAIDA", ana.id)




def test_distancia_escondida_fora_do_modo_demonstracao(janela):
    tela = janela.pagina_entrada.autenticacao
    assert tela.modo_demonstracao is False
    assert tela.prog_distancia.isHidden() and tela.prog_ajuda.isHidden()


def test_nivel_3_nao_mostra_botao_de_exportar(janela):
    from ecosec.dominio.entidades import Usuario
    caio = Usuario(matricula="CAIO", nome="Caio", nivel=3, senha_hash="$2b$x", id=99)
    acervo = janela.paginas_nivel[Nivel.N3].acervo
    acervo.iniciar(caio, Nivel.N3)
    assert acervo.botao_exportar.isHidden()                 # sem texto explicando o bloqueio
    assert "sem uso" in acervo.tempo.text()                 # fecha por INATIVIDADE, não por relógio fixo
    acervo.encerrar()


PROTECAO_NA_TELA = ("marca d'água", "invisível", "exportação", "bloqueada", "tarja")


def _textos_visiveis(widget):
    from PySide6.QtWidgets import QLabel
    return [r.text() for r in widget.findChildren(QLabel) if r.isVisibleTo(widget) and r.text()]


@pytest.mark.parametrize("nivel, codigo", [(Nivel.N1, "A1-01"), (Nivel.N2, "A2-01"), (Nivel.N3, "A3-01")],
                         ids=["N1", "N2", "N3"])
def test_painel_do_acervo_sem_avisos_de_marca_nem_exportacao(janela, nivel, codigo):
    """(01/11/2026): a tela fica simples. O painel à direita diz só o que foi
    ocultado; nada sobre marca d'água (visível ou invisível) nem sobre a exportação, antes ou depois de abrir."""
    from ecosec.dominio.entidades import Usuario
    usuario = Usuario(matricula="K7QX2PM", nome="Ana", nivel=nivel.value, uf="SP" if nivel is Nivel.N2 else None,
                      senha_hash="$2b$x", id=99)
    acervo = janela.paginas_nivel[nivel].acervo
    acervo.iniciar(usuario, nivel)
    antes = _textos_visiveis(acervo.vazio) + _textos_visiveis(acervo.direita)
    acervo.abrir(codigo)
    depois = _textos_visiveis(acervo.direita)
    assert [t for t in antes + depois if any(p in t.lower() for p in PROTECAO_NA_TELA)] == []
    assert any("ocultado" in t.lower() for t in depois)              # o que foi ocultado continua
    acervo.encerrar()


def test_cartao_do_nivel_sem_a_secao_de_protecao(janela):
    """(01/11/2026): o cartão de cada nível na página inicial mostra o nível,
    para quem é, o que mostra e o botão; sai "Como o conteúdo é protegido" (tarja, marca d'água, exportação)."""
    vincular_admin(janela)
    ana = cadastrar(janela.app, "Ana Prado", Nivel.N1, None, "servidor2026", 300)
    fazer_login(janela, ana, "servidor2026", 300)
    for cartao in janela.pagina_inicio.cartoes:
        textos = _textos_visiveis(cartao)
        assert not [t for t in textos if "protegido" in t.lower() or any(p in t.lower() for p in PROTECAO_NA_TELA)]
        assert "O QUE MOSTRA" in textos


def test_tela_do_acervo_sem_a_faixa_de_regras_do_nivel(janela):
    """(01/11/2026): a faixa "O que mostra · Tarja · Marca d'água · Exportação"
    sai da tela do acervo, nos três níveis. Quem consulta não precisa saber que a marca é invisível nem que a
    exportação está bloqueada."""
    from PySide6.QtWidgets import QLabel

    from ecosec.dominio.entidades import Usuario
    for nivel in Nivel:
        usuario = Usuario(matricula="K7QX2PM", nome="Ana", nivel=nivel.value, uf="SP" if nivel is Nivel.N2 else None,
                          senha_hash="$2b$x", id=99)
        acervo = janela.paginas_nivel[nivel].acervo
        acervo.iniciar(usuario, nivel)
        textos = {r.text() for r in acervo.findChildren(QLabel) if r.isVisibleTo(acervo)}
        assert not textos & {"O QUE MOSTRA", "TARJA", "MARCA D'ÁGUA", "EXPORTAÇÃO"}, nivel
        acervo.encerrar()


def test_inicio_rola_e_o_cartao_do_nivel_nao_encolhe(janela, qt):
    """Um cartão só (o da camada do perfil); em janela baixa a página rola, e o botão mantém a altura."""
    from ecosec.interface.fluent import ScrollArea
    from ecosec.interface.pagina_acesso import ALTURA_BOTAO
    vincular_admin(janela)
    ana = cadastrar(janela.app, "Ana Prado", Nivel.N1, None, "servidor2026", 300)
    fazer_login(janela, ana, "servidor2026", 300)
    inicio = janela.pagina_inicio
    assert len(inicio.cartoes) == 1 and inicio.findChild(ScrollArea) is not None
    janela.resize(820, 520)
    qt.processEvents()
    assert inicio.cartoes[0].botao.height() == ALTURA_BOTAO


# ---------------------------------------------------------------- login único (usuário e administrador)
def test_configuracao_inicial_so_existe_antes_do_primeiro_administrador(janela):
    """A configuração inicial termina quando o primeiro cadastro, com perfil de administrador, é concluído."""
    from ecosec.interface.janela import Estado
    pa = destravar_admin(janela)
    assert janela.estado is Estado.CONFIGURACAO and pa.bloq_titulo.text() == "Configuração inicial"
    cadastrar(janela.app, "Beatriz Souza", Nivel.N2, "SP", "diretor2026", 100)
    assert janela.estado is Estado.CONFIGURACAO                  # sem administrador, ninguém entra
    admin = cadastrar(janela.app, "Rafael Duarte", None, None, SENHA_ADMIN_USUARIO, 700, perfil=Perfil.EXTERNO)
    pa._cadastro_finalizado(None)                                # (cancelado: não reavalia)
    assert janela.estado is Estado.CONFIGURACAO
    pa._cadastro_finalizado(admin)
    assert janela.estado is Estado.LOGIN and janela.stackedWidget.currentWidget() is janela.pagina_entrada


def test_cadastro_sem_perfil_de_administrador_nao_vira_o_primeiro_admin(janela):
    """O vínculo no login ("Você é o administrador?") saiu. Na configuração inicial, um cadastro que não é
    de administrador não encerra a configuração."""
    from ecosec.interface.janela import Estado
    pa = destravar_admin(janela)
    ministro = cadastrar(janela.app, "Rafael Duarte", Nivel.N3, None, SENHA_ADMIN_USUARIO, 700)
    pa._cadastro_finalizado(ministro)
    assert not janela.app.administracao.administrador_vinculado and janela.estado is Estado.CONFIGURACAO
    assert not hasattr(janela, "perguntar_senha_admin")








def conferir_rosto_no_painel(janela, semente=700):
    pa = janela.pagina_admin
    pa.tela_rosto._ligar_video = lambda: None
    janela.switchTo(pa)
    assert pa.pilha.currentIndex() == 3                                     # direto na conferência do rosto
    assert pa.tela_rosto.sessao.andamento.etapa is Etapa.ROSTO
    alimentar_tela(pa.tela_rosto, semente, janela.app.autenticacao.p.frames_confirmacao)
    pa.tela_rosto._entrar()
    return pa


def cadastrar_celular_pela_tela(janela, semente=700):
    """Rosto -> QR -> primeiro código -> códigos de recuperação -> painel. Devolve o segredo."""
    from ecosec.seguranca.acesso import totp
    pa = conferir_rosto_no_painel(janela, semente)
    assert pa.pilha.currentIndex() == 5                                     # primeiro acesso: cadastra o celular
    segredo = pa.tela_celular.novo.segredo
    assert pa.tela_celular.qr.pixmap() is not None and not pa.tela_celular.qr.pixmap().isNull()
    pa.tela_celular.campo.setText(totp.codigo(segredo, janela.app.administracao.relogio()))
    pa.tela_celular._confirmar()
    assert pa.tela_celular.pilha.currentIndex() == 1 and len(pa.tela_celular._codigos) == 8
    assert not pa.tela_celular.botao_concluir.isEnabled()                   # só depois de "guardei"
    pa.tela_celular.guardei.setChecked(True)
    pa.tela_celular.botao_concluir.click()
    assert pa.pilha.currentIndex() == 2 and pa.tela_celular._codigos == []  # códigos não ficam na tela
    return segredo


def test_painel_pede_rosto_e_celular_e_no_primeiro_acesso_cadastra_o_celular(janela):
    import datetime as _dt
    from ecosec.seguranca.acesso import totp
    admin = vincular_admin(janela)
    fazer_login(janela, admin, SENHA_ADMIN_USUARIO, 700)
    segredo = cadastrar_celular_pela_tela(janela)
    eventos = [(r.evento.evento, r.evento.motivo) for r in janela.app.administracao.trilha_recente()]
    assert ("ADMIN", "CELULAR_CADASTRADO") in eventos and ("ENTRADA", "CONCEDIDO") in eventos
    pa = janela.pagina_admin
    janela.switchTo(janela.pagina_inicio)                                   # sair tranca: volta a pedir o rosto
    assert pa.pilha.currentIndex() == 3 and pa.tela_rosto.sessao is None
    conferir_rosto_no_painel(janela)
    assert pa.pilha.currentIndex() == 4                                     # agora pede o código
    pa.tela_codigo.campo.setText("000000")
    pa.tela_codigo._confirmar()
    assert pa.pilha.currentIndex() == 4 and "Código não aceito" in pa.tela_codigo.mensagem.text()
    proximo = _dt.datetime.now() + _dt.timedelta(seconds=30)                # o código do cadastro já foi usado
    pa.tela_codigo.campo.setText(totp.codigo(segredo, proximo))
    pa.tela_codigo._confirmar()
    assert pa.pilha.currentIndex() == 2


def test_administrador_nunca_tem_aba_do_acervo_com_o_painel_aberto_ou_trancado(janela):
    """O administrador não tem camada. Antes, as abas do acervo só sumiam com o painel aberto."""
    admin = vincular_admin(janela)
    fazer_login(janela, admin, SENHA_ADMIN_USUARIO, 700)
    def nenhuma():
        return not any(no_menu(janela, p) for p in janela.paginas_nivel.values())
    assert nenhuma()
    cadastrar_celular_pela_tela(janela)
    assert nenhuma()
    janela.pagina_admin.bloquear()
    assert nenhuma()


def test_tornar_administrador_pelo_painel_na_implantacao_e_depois_com_aprovacao(janela):
    admin = vincular_admin(janela)
    # só um Externo vira administrador
    bruno = cadastrar(janela.app, "Bruno Reis", None, None, "Ministro#2026y", 710, perfil=Perfil.EXTERNO)
    caio = cadastrar(janela.app, "Caio Dias", None, None, "Ministro#2026z", 720, perfil=Perfil.EXTERNO)
    fazer_login(janela, admin, SENHA_ADMIN_USUARIO, 700)
    cadastrar_celular_pela_tela(janela)
    pa = janela.pagina_admin
    pedidos = []
    pa.pedir_aprovacao = lambda acao, alvo: pedidos.append((acao, alvo)) or ""      # implantação: confirma
    pa.tabela.selectRow([l.usuario.id for l in janela.app.administracao.listar()].index(bruno.id))
    assert pa.botao_tornar_admin.isEnabled()
    pa._tornar_admin()
    assert janela.app.administracao.eh_administrador(bruno.id) and pedidos[0][0] == "Tornar administrador"
    pa.pedir_aprovacao = lambda acao, alvo: "123456"                                 # agora precisa de outro
    pa.tabela.selectRow([l.usuario.id for l in janela.app.administracao.listar()].index(caio.id))
    pa._tornar_admin()
    assert not janela.app.administracao.eh_administrador(caio.id)          # Bruno nem cadastrou o celular


def test_relatorio_s10_e_o_botao_de_registrar_a_revisao(janela):
    admin = vincular_admin(janela)
    fazer_login(janela, admin, SENHA_ADMIN_USUARIO, 700)
    cadastrar_celular_pela_tela(janela)
    pa = janela.pagina_admin
    pa._abrir_relatorios()
    pa.combo_relatorio.setCurrentIndex(list(pa.combo_relatorio.itemData(i) for i in
                                            range(pa.combo_relatorio.count())).index("S-10"))
    assert pa.botao_revisao.isVisible() and pa.tabela_relatorio.rowCount() == 1
    pa.pedir_aprovacao = lambda acao, alvo: ""
    pa._registrar_revisao()
    assert any(r.evento.motivo == "REVISAO_ACESSOS" for r in janela.app.administracao.trilha_recente())


def test_ancora_da_trilha_pelo_painel_com_o_codigo_do_proprio_celular(janela):
    import datetime as _dt
    from ecosec.seguranca.acesso import totp
    admin = vincular_admin(janela)
    fazer_login(janela, admin, SENHA_ADMIN_USUARIO, 700)
    segredo = cadastrar_celular_pela_tela(janela)
    pa = janela.pagina_admin
    pa._abrir_trilha()
    mostradas = []
    pa.mostrar_ancora = mostradas.append
    pa.pedir_codigo_proprio = lambda acao, explicacao: None                 # desistiu: nada acontece
    pa._gerar_ancora()
    assert mostradas == []
    proximo = _dt.datetime.now() + _dt.timedelta(seconds=30)               # o código do cadastro já foi usado
    pa.pedir_codigo_proprio = lambda acao, explicacao: totp.codigo(segredo, proximo)
    pa._gerar_ancora()
    assert len(mostradas) == 1 and mostradas[0].startswith("ECOSEC-TRILHA ")
    registros = janela.app.administracao.trilha_recente()
    assert any(r.evento.motivo == "ANCORA_TRILHA" and r.evento.usuario_id == admin.id for r in registros)
    pa.pedir_linha_ancora = lambda: mostradas[0]
    pa._conferir_ancora()
    assert "confere" in pa.resultado_trilha.text()


# ---------------------------------------------------------------- acesso de emergência
def trio_de_admins(janela):
    """Rafael (configuração inicial), Bruno e Caio: os três administradores, com celular. Devolve os segredos."""
    from ecosec.dominio.entidades import Administrador
    from ecosec.seguranca.acesso import totp
    adm = janela.app.administracao
    rafael = vincular_admin(janela)
    bruno = cadastrar(janela.app, "Bruno Reis", None, None, "Ministro#2026y", 710, perfil=Perfil.EXTERNO)
    caio = cadastrar(janela.app, "Caio Dias", None, None, "Ministro#2026z", 720, perfil=Perfil.EXTERNO)
    segredos = {}
    for u in (rafael, bruno, caio):
        if not adm.eh_administrador(u.id):
            adm.administradores.salvar(Administrador(u.id, adm.relogio(), designado_por=rafael.id))
        novo = adm.novo_celular(u.id)
        adm.confirmar_celular(u.id, novo, totp.codigo(novo.segredo, adm.relogio()))
        segredos[u.id] = novo.segredo
    return rafael, bruno, caio, segredos


def login_com_rosto_falhando(janela, usuario, senha):
    tela = janela.pagina_entrada.autenticacao
    tela._ligar_video = lambda: None
    janela.pagina_entrada.iniciar()
    tela.campo_matricula.setText(usuario.matricula)
    tela.campo_senha.setText(senha)
    tela._enviar_credenciais()
    tela.cancelar()                                      # o mesmo que a câmera falhar no meio do rosto
    return tela


def test_emergencia_aparece_so_para_admin_barrado_pela_camera(janela):
    rafael, _, _, _ = trio_de_admins(janela)
    ana = cadastrar(janela.app, "Ana Prado", Nivel.N1, None, "servidor2026", 300)
    tela = login_com_rosto_falhando(janela, rafael, SENHA_ADMIN_USUARIO)
    assert tela.botao_emergencia.isVisible()
    tela = login_com_rosto_falhando(janela, ana, "servidor2026")
    assert not tela.botao_emergencia.isVisible()                            # não é administrador
    janela.pagina_entrada.iniciar()
    tela.campo_matricula.setText(rafael.matricula)
    tela.campo_senha.setText("errada0000")
    tela._enviar_credenciais()
    assert not tela.botao_emergencia.isVisible()                            # senha errada: não é a câmera


def test_quorum_abre_a_emergencia_so_com_a_administracao_restrita(janela):
    import datetime as _dt
    from ecosec.seguranca.acesso import totp
    rafael, bruno, caio, segredos = trio_de_admins(janela)
    tela = login_com_rosto_falhando(janela, rafael, SENHA_ADMIN_USUARIO)
    tela.botao_emergencia.click()
    pe = janela.pagina_entrada
    assert pe.lados.currentWidget() is pe.tela_emergencia
    depois = _dt.datetime.now() + _dt.timedelta(seconds=30)                 # os códigos do cadastro já foram usados
    for u in (caio, bruno):                                                 # em qualquer ordem
        pe.tela_emergencia.campo.setText(totp.codigo(segredos[u.id], depois))
        pe.tela_emergencia._informar()
    sessao = janela.sessao
    assert sessao is not None and sessao.em_emergencia and sessao.papel == "Acesso de emergência"
    assert janela.stackedWidget.currentWidget() is janela.pagina_admin and janela.pagina_admin.pilha.currentIndex() == 6
    assert no_menu(janela, janela.pagina_admin)
    assert not any(no_menu(janela, p) for p in (*janela.paginas_nivel.values(), janela.pagina_inicio))
    painel = janela.pagina_admin.tela_emergencia
    painel.tabela.selectRow(0)
    painel._recadastrar()
    assert janela.pagina_admin.assistente is not None and janela.pagina_admin.assistente.recadastro.id == rafael.id
    janela.bloquear_sessao()                                                # inatividade: a emergência termina
    assert janela.sessao is None and janela.pagina_admin.assistente is None


# ---------------------------------------------------------------- inatividade: bloqueia, nunca fecha no meio do uso
def logar_diretora(janela):
    vincular_admin(janela)
    bia = cadastrar(janela.app, "Beatriz Souza", Nivel.N2, "SP", "diretor2026", 100)
    fazer_login(janela, bia, "diretor2026", 100)
    return bia


def test_inatividade_bloqueia_e_a_senha_devolve_para_onde_estava(janela):
    logar_diretora(janela)
    pagina = janela.paginas_nivel[Nivel.N2]
    janela.switchTo(pagina)
    pagina.acervo.abrir("A2-01")
    janela._inatividade._venceu()                                  # 10 min sem uso
    assert janela.bloqueada and janela.stackedWidget.currentWidget() is janela.pagina_bloqueio
    assert not no_menu(janela, janela.pagina_inicio) and not no_menu(janela, pagina)   # nada visível
    assert janela.sessao is not None                                # a sessão não foi encerrada
    janela.pagina_bloqueio.desbloquear.emit("errada0000")
    assert janela.bloqueada and "incorreta" in janela.pagina_bloqueio.erro.text()
    janela.pagina_bloqueio.desbloquear.emit("diretor2026")
    assert not janela.bloqueada and janela.stackedWidget.currentWidget() is pagina
    assert pagina.pilha.currentIndex() == 2 and pagina.acervo.entrega.item.codigo == "A2-01"   # como estava
    motivos = [r.evento.motivo for r in janela.app.administracao.trilha_recente(5)]
    assert "BLOQUEIO_INATIVIDADE" in motivos and "DESBLOQUEIO" in motivos


def test_camera_ligada_conta_como_uso_e_nao_bloqueia(janela):
    logar_diretora(janela)
    janela.paginas_nivel[Nivel.N3].autenticacao.trabalhador = object()     # captura em andamento
    janela._inatividade._venceu()
    assert not janela.bloqueada and janela._inatividade.ativo              # o prazo recomeçou
    janela.paginas_nivel[Nivel.N3].autenticacao.trabalhador = None


def test_bloqueio_fecha_o_nivel_3(janela):
    vincular_admin(janela)
    caio = cadastrar_ministro(janela)
    fazer_login(janela, caio, SENHA_MINISTRO, 900)
    pagina = janela.paginas_nivel[Nivel.N3]
    pagina._liberar(janela.app.administracao.usuario(caio.id))
    assert pagina.pilha.currentIndex() == 2
    janela._inatividade._venceu()
    assert pagina.pilha.currentIndex() == 0 and pagina.acervo.usuario is None   # senha sozinha não reabre o N3


def test_senha_errada_seguida_na_tela_de_bloqueio_encerra_a_sessao(janela):
    from ecosec.interface.janela import Estado
    logar_diretora(janela)
    janela._inatividade._venceu()
    for i in range(janela.app.autenticacao.p.contencao.tentativas_maximas):
        janela.pagina_bloqueio.desbloquear.emit(f"errada{i:04d}")
    assert janela.estado is Estado.LOGIN and janela.sessao is None and not janela.bloqueada


def test_sair_pela_tela_de_bloqueio_volta_ao_login(janela):
    from ecosec.interface.janela import Estado
    logar_diretora(janela)
    janela._inatividade._venceu()
    janela.pagina_bloqueio.sair.emit()
    assert janela.estado is Estado.LOGIN and janela.stackedWidget.currentWidget() is janela.pagina_entrada


def test_nivel_3_fecha_so_por_inatividade(janela):
    from ecosec.dominio.entidades import Usuario
    caio = Usuario(matricula="CAIO", nome="Caio", nivel=3, senha_hash="$2b$x", id=99)
    acervo = janela.paginas_nivel[Nivel.N3].acervo
    acervo.iniciar(caio, Nivel.N3)
    assert acervo._prazo_n3.ativo
    acervo._prazo_n3._venceu()
    assert acervo.usuario is None


def test_uso_reinicia_o_prazo(qt):
    import time
    from ecosec.interface.atividade import PrazoInatividade, vigia
    prazo = PrazoInatividade(1)
    prazo.iniciar()
    time.sleep(0.2)
    antes = prazo.restante_ms()
    vigia().atividade.emit()
    assert prazo.restante_ms() > antes
    prazo.parar()
