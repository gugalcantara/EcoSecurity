"""Cadastro (termo, dados, coleta, conclusão), administração, termo e segredos."""
from datetime import datetime, timedelta

import cv2
import numpy as np
import pytest

from ecosec import segredos
from ecosec.configuracao import carregar
from ecosec.dominio import termo
from ecosec.dominio.motivos import Motivo
from ecosec.dominio.niveis import Nivel
from ecosec.dominio.perfis import Perfil
from ecosec.repositorios.memoria import (RepositorioAmostrasMemoria, RepositorioConsentimentosMemoria,
                                         RepositorioTentativasMemoria, RepositorioUsuariosMemoria)
from ecosec.servicos.administracao import ServicoAdministracao
from ecosec.servicos.cadastro import (ALFABETO_MATRICULA, ColetaFacial, DadosCadastro, ErroCadastro,
                                      ServicoCadastro)
from ecosec.visao.pipeline import ResultadoQuadro
from ecosec.visao.qualidade import MedidasQualidade
from ecosec.visao.reconhecimento import ParametrosLBPH, ReconhecedorLBPH

CFG = carregar()


def face(semente):
    base = np.random.default_rng(semente).integers(40, 215, (50, 50)).astype(np.uint8)
    return cv2.resize(base, (200, 200), interpolation=cv2.INTER_LINEAR)


def quadro_bom(semente):
    return ResultadoQuadro(faces=((0, 0, 200, 200),), fonte="HAAR", largura=640, altura=480,
                           medidas=MedidasQualidade(300, 120, 40, 2), face_normalizada=face(semente))


@pytest.fixture
def cadastro():
    usuarios, consentimentos = RepositorioUsuariosMemoria(), RepositorioConsentimentosMemoria()
    amostras = RepositorioAmostrasMemoria()
    rec = ReconhecedorLBPH(ParametrosLBPH.de_configuracao(CFG))
    servico = ServicoCadastro.de_configuracao(CFG, usuarios, consentimentos, amostras, rec)
    servico.custo = 4
    servico.sessoes, servico.frames_por_sessao = 2, 3
    return servico


def coleta_completa(servico, semente=0, aceite=None):
    coleta = servico.nova_coleta(aceite or servico.registrar_aceite("Titular Teste"))
    for s in range(servico.sessoes):
        for i in range(servico.frames_por_sessao):
            coleta.oferecer(quadro_bom(semente * 100 + s * 10 + i))
        if s < servico.sessoes - 1:
            coleta.avancar_sessao()
    return coleta


DADOS_N2 = DadosCadastro("Bia Souza", Nivel.N2, "SP", "diretor2026", "diretor2026")


# ================================================================ termo
def test_termo_inclui_o_nome_e_o_hash_muda_com_ele():
    texto = termo.renderizar("Ana  Lima ", "grupo@exemplo.edu")
    assert "eu, Ana Lima," in texto and "art. 11" in texto
    outro = termo.renderizar("Outra Pessoa", "grupo@exemplo.edu")
    assert termo.calcular_hash(texto) != termo.calcular_hash(outro)


def test_termo_traz_contato_idade_e_eliminacao():
    texto = termo.renderizar("Ana", "grupo@exemplo.edu")
    assert "grupo@exemplo.edu" in texto                    # art. 9º: contato do controlador
    assert "18 (dezoito) anos" in texto                    # art. 14: menores
    assert "eliminação do modelo facial" in texto          # art. 16 / 18, VI
    # o contato entra no hash: mudar o contato muda o texto aceito
    assert termo.calcular_hash(texto) != termo.calcular_hash(termo.renderizar("Ana", "outro@exemplo.edu"))


def test_termo_html_escapa_o_nome():
    assert "<script>" not in termo.renderizar_html("<script>x</script>", "c")


def test_aceite_fica_em_memoria_ate_concluir(cadastro):
    aceite = cadastro.registrar_aceite("Bia Souza")
    assert aceite.id is None and aceite.vigente
    assert aceite.titular_nome == "BIA SOUZA"                # padrão do banco antes do hash
    assert aceite.hash_termo == termo.calcular_hash(cadastro.texto_termo("BIA SOUZA", False))
    assert not cadastro.consentimentos._por_id                 # nada gravado ainda


def test_desistir_depois_do_aceite_nao_deixa_dado_pessoal(cadastro):
    aceite = cadastro.registrar_aceite("Bia Souza")
    coleta = cadastro.nova_coleta(aceite)
    coleta.oferecer(quadro_bom(1))
    coleta.descartar()                                      # o que a tela faz ao cancelar
    assert cadastro.usuarios.listar() == []
    assert not cadastro.consentimentos._por_id


def test_sem_aceite_o_servico_nao_abre_a_coleta(cadastro):
    with pytest.raises(ErroCadastro, match="consentimento"):
        cadastro.nova_coleta(None)


def test_aceite_exige_assinatura(cadastro):
    with pytest.raises(ErroCadastro):
        cadastro.registrar_aceite("  ")


# ================================================================ dados
def test_validacao_aceita_dados_corretos(cadastro):
    assert cadastro.validar(DADOS_N2) == []


@pytest.mark.parametrize("ajuste, trecho", [
    (dict(uf=None), "UF"),
    (dict(confirmacao="outra"), "confirmação"),
    (dict(senha="curta1", confirmacao="curta1"), "8 caracteres"),
    (dict(nome=" "), "nome"),
])
def test_validacao_recusa(cadastro, ajuste, trecho):
    from dataclasses import replace
    erros = " ".join(cadastro.validar(replace(DADOS_N2, **ajuste)))
    assert trecho in erros


def test_n3_exige_senha_forte(cadastro):
    erros = cadastro.validar(DadosCadastro("Caio", Nivel.N3, None, "diretor2026", "diretor2026"))
    assert any("maiúscula" in e for e in erros)


# ================================================================ coleta
def test_coleta_recusa_quadro_sem_face_boa_com_a_orientacao():
    coleta = ColetaFacial(1, 3, 3.0)
    vazio = ResultadoQuadro(faces=(), fonte="HAAR", largura=640, altura=480)
    estado = coleta.oferecer(vazio)
    assert estado.aceitas == 0 and estado.orientacao.startswith("Posicione")


def test_coleta_descarta_quadro_repetido():
    coleta = ColetaFacial(1, 3, 3.0)
    coleta.oferecer(quadro_bom(1))
    assert coleta.oferecer(quadro_bom(1)).aceitas == 1       # idêntico: recusado
    assert coleta.oferecer(quadro_bom(2)).aceitas == 2


def test_coleta_por_sessoes():
    coleta = ColetaFacial(2, 2, 3.0)
    coleta.oferecer(quadro_bom(1))
    with pytest.raises(ErroCadastro):
        coleta.avancar_sessao()                                 # sessão incompleta
    coleta.oferecer(quadro_bom(2))
    assert coleta.oferecer(quadro_bom(3)).sessao_completa       # já não aceita mais
    coleta.avancar_sessao()
    coleta.oferecer(quadro_bom(4)), coleta.oferecer(quadro_bom(5))
    assert coleta.concluida
    assert [s for s, _ in coleta.metadados()] == [1, 1, 2, 2]


def test_descartar_apaga_as_faces():
    coleta = ColetaFacial(1, 2, 3.0)
    coleta.oferecer(quadro_bom(1))
    guardada = coleta.faces()[0]
    coleta.descartar()
    assert coleta.faces() == [] and not guardada.any()          # sobrescrita com zeros


# ================================================================ conclusão
def test_cadastro_completo(cadastro):
    aceite = cadastro.registrar_aceite("Bia Souza")
    coleta = coleta_completa(cadastro, aceite=aceite)
    usuario = cadastro.concluir(DADOS_N2, aceite, coleta)
    assert len(usuario.matricula) == 7 and set(usuario.matricula) <= set(ALFABETO_MATRICULA)
    assert usuario.ativo and usuario.uf == "SP"
    assert "diretor2026" not in usuario.senha_hash
    gravado = cadastro.consentimentos.vigente_de(usuario.id)
    assert gravado.hash_termo == aceite.hash_termo and gravado.momento == aceite.momento
    assert cadastro.reconhecedor.rotulos() == {usuario.id}
    assert len(cadastro.amostras.por_usuario(usuario.id)) == 6
    assert coleta.faces() == []                                 # biometria descartada


def test_uf_so_fica_para_o_nivel_2(cadastro):
    dados = DadosCadastro("Caio", Nivel.N3, "SP", "Custodia#2026", "Custodia#2026")
    usuario = cadastro.concluir(dados, cadastro.registrar_aceite("Caio"), coleta_completa(cadastro))
    assert usuario.uf is None


def test_sem_captura_completa_nao_cadastra(cadastro):
    coleta = cadastro.nova_coleta(cadastro.registrar_aceite("Bia"))
    coleta.oferecer(quadro_bom(1))
    with pytest.raises(ErroCadastro, match="captura"):
        cadastro.concluir(DADOS_N2, cadastro.registrar_aceite("Bia"), coleta)
    assert coleta.faces() == [] and cadastro.usuarios.listar() == []


def test_falha_no_treino_desativa_o_usuario_e_descarta_as_faces(cadastro):
    def quebra(*_):
        raise RuntimeError("disco cheio")
    cadastro.reconhecedor.adicionar = quebra
    coleta = coleta_completa(cadastro)
    with pytest.raises(RuntimeError):
        cadastro.concluir(DADOS_N2, cadastro.registrar_aceite("Bia"), coleta)
    [usuario] = cadastro.usuarios.listar()
    assert usuario.ativo is False                               # existe, mas não entra
    assert coleta.faces() == []


def test_segunda_pessoa_entra_no_modelo_sem_retreinar(cadastro):
    a = cadastro.concluir(DADOS_N2, cadastro.registrar_aceite("Bia"), coleta_completa(cadastro, 1))
    b = cadastro.concluir(DadosCadastro("Duda", Nivel.N1, None, "senha1234", "senha1234"),
                          cadastro.registrar_aceite("Duda"), coleta_completa(cadastro, 2))
    assert cadastro.reconhecedor.rotulos() == {a.id, b.id}


# ================================================================ administração
@pytest.fixture
def admin(tmp_path, cadastro):
    env = tmp_path / ".env"
    relogio = {"agora": datetime(2026, 10, 6, 14)}
    servico = ServicoAdministracao.de_configuracao(
        CFG, cadastro.usuarios, cadastro.consentimentos, cadastro.amostras, RepositorioTentativasMemoria(),
        ler_hash=lambda: segredos.ler(segredos.ADMIN_SENHA_HASH, env),
        gravar_hash=lambda h: segredos.gravar(segredos.ADMIN_SENHA_HASH, h, env),
        rotulos_modelo=lambda: rotulos, relogio=lambda: relogio["agora"])
    rotulos = set()
    servico.rotulos = rotulos               # quem está no modelo facial (o teste controla)
    servico.custo = 4
    servico.relogio_mut = relogio
    servico.env = env
    return servico


def test_primeira_execucao_define_a_senha_uma_vez(admin):
    assert not admin.configurado
    assert admin.definir_senha_inicial("fraca", "fraca")                 # recusada: política N3
    assert admin.definir_senha_inicial("Admin#Forte2026", "Admin#Forte2026") == []
    assert admin.configurado
    assert "Admin#Forte2026" not in admin.env.read_text()                # só o hash no .env
    assert admin.definir_senha_inicial("Outra#Senha2026", "Outra#Senha2026")   # não redefine


def test_admin_autentica_e_bloqueia(admin):
    admin.definir_senha_inicial("Admin#Forte2026", "Admin#Forte2026")
    assert admin.autenticar("Admin#Forte2026") is Motivo.CONCEDIDO
    assert admin.autenticar("errada") is Motivo.SENHA_INCORRETA
    admin.autenticar("errada")
    assert admin.autenticar("errada") is Motivo.BLOQUEADO
    assert admin.autenticar("Admin#Forte2026") is Motivo.BLOQUEADO      # bloqueado: nem confere
    admin.relogio_mut["agora"] += timedelta(minutes=16)
    assert admin.autenticar("Admin#Forte2026") is Motivo.CONCEDIDO


def test_admin_sem_senha_definida_nunca_entra(admin):
    assert admin.autenticar("") is Motivo.SENHA_INCORRETA


def test_revogar_desativa_e_impede_reativar(admin, cadastro):
    u = cadastro.concluir(DADOS_N2, cadastro.registrar_aceite("Bia"), coleta_completa(cadastro))
    admin._eliminar_biometria = cadastro.reconhecedor.remover
    assert admin.revogar_consentimento(u.id) is None
    assert u.id not in cadastro.reconhecedor.rotulos()             # rosto eliminado (art. 18, VI)
    assert len(cadastro.consentimentos.de_usuario(u.id)) == 1      # o registro do aceite fica
    assert cadastro.usuarios.por_id(u.id).ativo is False
    assert "revogado" in admin.definir_ativo(u.id, True)
    assert cadastro.usuarios.por_id(u.id).ativo is False


def test_desativar_e_reativar(admin, cadastro):
    u = cadastro.concluir(DADOS_N2, cadastro.registrar_aceite("Bia"), coleta_completa(cadastro))
    assert admin.definir_ativo(u.id, False) is None
    assert admin.definir_ativo(u.id, True) is None
    [linha] = admin.listar()
    assert linha.usuario.ativo and linha.consentimento_vigente and linha.amostras == 6


# ================================================================ segredos
def test_chave_de_cifragem_nunca_e_trocada(tmp_path):
    env = tmp_path / ".env"
    primeira = segredos.garantir_chave_cifragem(env)
    assert segredos.garantir_chave_cifragem(env) == primeira


def test_segredo_com_cifrao_e_chaves_volta_intacto(tmp_path):
    env = tmp_path / ".env"
    segredos.gravar("X", "a${HOME}b$2b$", env)
    assert segredos.ler("X", env) == "a${HOME}b$2b$"


def test_relatorio_do_titular(admin, cadastro):
    u = cadastro.concluir(DADOS_N2, cadastro.registrar_aceite("Bia Souza"), coleta_completa(cadastro))
    admin._rotulos_modelo = cadastro.reconhecedor.rotulos
    relatorio = admin.dados_do_titular(u.id)
    assert u.matricula in relatorio and "BIA SOUZA" in relatorio
    assert "NENHUMA guardada" in relatorio and "PRESENTE" in relatorio
    assert "sessão 1: 3, sessão 2: 3" in relatorio
    assert "diretor2026" not in relatorio and u.senha_hash not in relatorio   # nem a senha nem o hash


def test_falha_ao_eliminar_ainda_deixa_o_acesso_bloqueado(admin, cadastro):
    u = cadastro.concluir(DADOS_N2, cadastro.registrar_aceite("Bia"), coleta_completa(cadastro))

    def quebra(_):
        raise OSError("disco cheio")
    admin._eliminar_biometria = quebra
    assert "Repita" in admin.revogar_consentimento(u.id)
    assert cadastro.usuarios.por_id(u.id).ativo is False
    assert cadastro.consentimentos.vigente_de(u.id) is None


# ---------------------------------------------------------------- termo: finalidades separadas
def test_termo_tem_resumo_e_duas_finalidades():
    texto = termo.renderizar("Ana", "c@x", None)
    assert "Quadro-resumo" in texto and "Finalidade obrigatória" in texto and "Finalidade opcional" in texto
    assert "Finalidade (b): a manifestar" in texto


def test_a_escolha_da_finalidade_b_entra_no_hash(cadastro):
    sim = cadastro.registrar_aceite("Bia Souza", autoriza_pesquisa=True)
    nao = cadastro.registrar_aceite("Bia Souza", autoriza_pesquisa=False)
    assert sim.autoriza_pesquisa and not nao.autoriza_pesquisa
    assert sim.hash_termo != nao.hash_termo                  # o hash prova o que foi escolhido
    assert "Finalidade (b): AUTORIZO." in cadastro.texto_termo("Bia Souza", True)
    assert "Finalidade (b): NÃO AUTORIZO." in cadastro.texto_termo("Bia Souza", False)


# ---------------------------------------------------------------- termo: versões e prova
# hashes do termo 2.0 calculados antes de a versão 3.0 existir: se o arquivo da
# 2.0 mudar um caractere, os consentimentos já gravados deixam de ser prováveis
HASHES_V2 = {None: "3d240f407a66ddbbe809823d940faccb65327bf65f8c70afe03bee691b4c20ec",
             True: "ad311aa18c469812a2439536e7be437590ad805cb6bbc6f221b805d3e62ee3f7",
             False: "9cbcf803c140210050dc8e220f6e40bde338298c7528be68e7ced44bd30e3173"}


@pytest.mark.parametrize("escolha", [None, True, False])
def test_termo_2_arquivado_reproduz_os_hashes_ja_gravados(escolha):
    from ecosec.dominio import termo_v2
    texto = termo_v2.renderizar("Ana Lima", "grupo@exemplo.edu", escolha)
    assert termo.calcular_hash(texto) == HASHES_V2[escolha]


def test_confere_recalcula_o_hash_da_versao_aceita():
    h3 = termo.calcular_hash(termo.renderizar("Ana Lima", "c@x", True))
    assert termo.confere(termo.VERSAO, "Ana Lima", "c@x", True, h3) is True
    assert termo.confere(termo.VERSAO, "Ana Lima", "c@x", False, h3) is False    # escolha diferente
    assert termo.confere("2.0", "Ana Lima", "grupo@exemplo.edu", True, HASHES_V2[True]) is True
    assert termo.confere("1.0", "Ana Lima", "c@x", True, h3) is None            # versão não arquivada


def test_termo_vigente_nao_usa_travessao():
    from datetime import datetime
    textos = (termo.renderizar("Ana Lima", "c@x", True), termo.renderizar_html("Ana Lima", "c@x"),
              termo.via_do_titular_html("Ana Lima", "c@x", True, datetime(2026, 10, 7, 11, 4), "ab" * 32, "K7M2PQX"))
    for texto in textos:
        # sem exceção desde a 3.4: a marcação de documento simulado saiu
        assert "DOCUMENTO SIMULADO" not in texto
        assert "—" not in texto and "–" not in texto


def test_via_do_titular_traz_assinatura_escolhas_e_registro():
    from datetime import datetime
    via = termo.via_do_titular_html("Ana  Lima", "c@x", False, datetime(2026, 10, 7, 11, 4), "f" * 64, "K7M2PQX")
    assert "<b>Ana Lima</b>" in via and "Matrícula K7M2PQX" in via
    assert "7 de outubro de 2026, às 11:04" in via and "f" * 64 in via
    assert "(X) Não autorizo" in via and "(&nbsp;&nbsp;) Autorizo<br>" in via


def test_recusar_a_finalidade_b_nao_impede_o_cadastro(cadastro):
    aceite = cadastro.registrar_aceite("Bia Souza", autoriza_pesquisa=False)
    usuario = cadastro.concluir(DADOS_N2, aceite, coleta_completa(cadastro, aceite=aceite))
    assert usuario.ativo
    assert cadastro.consentimentos.vigente_de(usuario.id).autoriza_pesquisa is False


def test_escolha_aparece_no_relatorio_do_titular(admin, cadastro):
    aceite = cadastro.registrar_aceite("Bia Souza", autoriza_pesquisa=True)
    u = cadastro.concluir(DADOS_N2, aceite, coleta_completa(cadastro, aceite=aceite))
    assert "(b) estatísticas e experimentos: AUTORIZADA" in admin.dados_do_titular(u.id)
    [linha] = admin.listar()
    assert linha.autoriza_pesquisa is True


# ---------------------------------------------------------------- primeiro administrador
def _pessoa_com_rosto(admin, cadastro, nome="Bia Souza", perfil=Perfil.EXTERNO):
    aceite = cadastro.registrar_aceite(nome)
    usuario = cadastro.concluir(DadosCadastro(nome, None, None, "Ministro#2026x", "Ministro#2026x", perfil=perfil),
                                aceite, coleta_completa(cadastro, aceite=aceite))
    admin.rotulos.add(usuario.id)
    return usuario


def test_primeiro_administrador_exige_a_senha_de_instalacao_e_vale_uma_vez(admin, cadastro):
    """O primeiro admin é o primeiro cadastro da configuração inicial,
    aberta pela senha de instalação, com perfil de administrador."""
    admin.definir_senha_inicial("Admin#Forte2026", "Admin#Forte2026")
    bia = _pessoa_com_rosto(admin, cadastro)
    assert not admin.administrador_vinculado
    assert admin.vincular_primeiro_administrador(bia.id)                  # recusado: sem a senha de instalação
    assert admin.autenticar("errada") is not Motivo.CONCEDIDO
    assert admin.vincular_primeiro_administrador(bia.id)
    assert admin.autenticar("Admin#Forte2026") is Motivo.CONCEDIDO
    assert admin.vincular_primeiro_administrador(bia.id) is None
    assert admin.eh_administrador(bia.id)
    assert bia.matricula not in admin.env.read_text()                    # o papel mora no banco, não no .env
    outra = _pessoa_com_rosto(admin, cadastro, "Caio Lima")
    assert admin.vincular_primeiro_administrador(outra.id)                # uma vez só
    assert not admin.eh_administrador(outra.id)


def test_primeiro_administrador_precisa_de_rosto_no_modelo_e_cadastro_ativo(admin, cadastro):
    admin.definir_senha_inicial("Admin#Forte2026", "Admin#Forte2026")
    assert admin.autenticar("Admin#Forte2026") is Motivo.CONCEDIDO
    bia = _pessoa_com_rosto(admin, cadastro)
    admin.rotulos.discard(bia.id)                                          # sem rosto no modelo
    assert admin.vincular_primeiro_administrador(bia.id)
    admin.rotulos.add(bia.id)
    admin.definir_ativo(bia.id, False)
    assert admin.vincular_primeiro_administrador(bia.id)
    assert not admin.administrador_vinculado


def test_so_o_perfil_de_administrador_vira_o_primeiro_admin(admin, cadastro):
    """O primeiro admin é o cadastro com perfil de administrador
    (um cadastro, um perfil); qualquer outro perfil é recusado."""
    admin.definir_senha_inicial("Admin#Forte2026", "Admin#Forte2026")
    assert admin.autenticar("Admin#Forte2026") is Motivo.CONCEDIDO
    aceite = cadastro.registrar_aceite("Bia Souza")
    bia = cadastro.concluir(DADOS_N2, aceite, coleta_completa(cadastro, aceite=aceite))
    admin.rotulos.add(bia.id)
    ministro = _pessoa_com_rosto(admin, cadastro, "Caio Lima", Perfil.MINISTRO)
    assert admin.vincular_primeiro_administrador(bia.id)
    assert admin.vincular_primeiro_administrador(ministro.id)
    assert not admin.administrador_vinculado


# ---------------------------------------------------------------- recadastro do rosto (acesso de emergência)
def test_substituir_rosto_troca_o_modelo_da_pessoa_e_descarta_as_faces(cadastro):
    import numpy as np
    bia = cadastro.concluir(DADOS_N2, cadastro.registrar_aceite("Bia"), coleta_completa(cadastro, 1))
    duda = cadastro.concluir(DadosCadastro("Duda", Nivel.N1, None, "senha1234", "senha1234"),
                             cadastro.registrar_aceite("Duda"), coleta_completa(cadastro, 2))
    assert cadastro.reconhecedor.verificar(face(100), bia.id) == 0          # amostra do rosto antigo
    coleta = cadastro.nova_coleta_recadastro(bia.id)
    for s in range(cadastro.sessoes):
        for i in range(cadastro.frames_por_sessao):
            coleta.oferecer(quadro_bom(900 + s * 10 + i))
        if s < cadastro.sessoes - 1:
            coleta.avancar_sessao()
    cadastro.substituir_rosto(bia.id, coleta)
    assert coleta.faces() == []                                             # faces descartadas
    assert cadastro.reconhecedor.rotulos() == {bia.id, duda.id}             # a outra pessoa continua
    assert cadastro.reconhecedor.verificar(face(900), bia.id) == 0          # o novo bate exatamente...
    assert cadastro.reconhecedor.verificar(face(100), bia.id) > 0           # ...e o antigo saiu do modelo
    assert len(cadastro.amostras.por_usuario(bia.id)) == 12                 # metadados novos somados


def test_recadastro_sem_consentimento_nao_coleta(cadastro, admin):
    bia = cadastro.concluir(DADOS_N2, cadastro.registrar_aceite("Bia"), coleta_completa(cadastro, 1))
    admin.revogar_consentimento(bia.id)
    with pytest.raises(ErroCadastro, match="consentimento"):
        cadastro.nova_coleta_recadastro(bia.id)
