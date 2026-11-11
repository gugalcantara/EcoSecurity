"""Anel 1: cada camada (S1 a S7) testada isoladamente."""
import math
import random
import time
from datetime import datetime, timedelta

import pytest

from ecosec.configuracao import carregar
from ecosec.dominio.camadas import CamadaSeguranca as C
from ecosec.dominio.entidades import RegistroTentativas, Usuario
from ecosec.dominio.motivos import Motivo
from ecosec.dominio.niveis import Nivel
from ecosec.seguranca.acesso import (s1_contencao, s2_conhecimento, s3_qualidade, s4_inerencia,
                                     s5_habilitacao, s6_vivacidade, s7_custodia)

CUSTO_TESTE = 4   # mínimo do bcrypt: os testes não precisam ser lentos
AGORA = datetime(2026, 10, 6, 14, 0)


def usuario(id_=1, nivel=Nivel.N3, ativo=True, **extra):
    uf = extra.pop("uf", "SP" if Nivel(nivel) is Nivel.N2 else None)
    return Usuario(matricula=f"MAT{id_}", nome=f"Pessoa {id_}", nivel=nivel,
                   senha_hash="$2b$x", uf=uf, ativo=ativo, id=id_)


# ================================================================ S1 Contenção
PARAMS_S1 = s1_contencao.ParametrosContencao(tentativas_maximas=3, bloqueio=timedelta(minutes=15))


def test_s1_livre_quando_consultado_e_nao_bloqueado():
    assert s1_contencao.avaliar(False).aprovado


@pytest.mark.parametrize("bloqueado", [True, None])
def test_s1_nega_bloqueado_e_nao_consultado(bloqueado):
    assert s1_contencao.avaliar(bloqueado).motivo is Motivo.BLOQUEADO


def test_s1_bloqueia_na_terceira_falha():
    registro = None
    for _ in range(2):
        registro = s1_contencao.registrar_falha(registro, "X", AGORA, PARAMS_S1)
        assert not s1_contencao.esta_bloqueado(registro, AGORA)
    registro = s1_contencao.registrar_falha(registro, "X", AGORA, PARAMS_S1)
    assert s1_contencao.esta_bloqueado(registro, AGORA)
    assert s1_contencao.esta_bloqueado(registro, AGORA + timedelta(minutes=14, seconds=59))


def test_s1_bloqueio_expira_e_contagem_recomeca():
    registro = RegistroTentativas("X", 0, AGORA + timedelta(minutes=15))
    depois = AGORA + timedelta(minutes=15)
    assert not s1_contencao.esta_bloqueado(registro, depois)
    novo = s1_contencao.registrar_falha(registro, "X", depois, PARAMS_S1)
    assert novo.falhas == 1 and novo.bloqueado_ate is None


def test_s1_sucesso_zera_contagem():
    assert s1_contencao.registrar_sucesso("X") == RegistroTentativas("X")


def test_s1_sem_registro_esta_livre():
    assert not s1_contencao.esta_bloqueado(None, AGORA)


# ================================================================ S2 Conhecimento
def test_s2_hash_confere_e_nao_e_a_senha():
    h = s2_conhecimento.gerar_hash("Senha#Forte2026", CUSTO_TESTE)
    assert "Senha#Forte2026" not in h and h.startswith("$2b$04$")
    assert s2_conhecimento.conferir("Senha#Forte2026", h, CUSTO_TESTE)
    assert not s2_conhecimento.conferir("Senha#Forte2027", h, CUSTO_TESTE)


def test_s2_mesma_senha_gera_hashes_diferentes():
    # sal aleatório: vazamento não revela quem compartilha a mesma senha
    assert (s2_conhecimento.gerar_hash("abc12345", CUSTO_TESTE)
            != s2_conhecimento.gerar_hash("abc12345", CUSTO_TESTE))


def test_s2_matricula_inexistente_nunca_confere():
    assert not s2_conhecimento.conferir("qualquer", None, CUSTO_TESTE)


def test_s2_nem_a_senha_do_hash_ficticio_abre_matricula_inexistente():
    # quem ler o código-fonte conhece a senha do hash fictício; ela não pode servir de chave
    assert not s2_conhecimento.conferir("ecosec-hash-de-referencia-para-tempo-constante", None, CUSTO_TESTE)


def test_s2_tempo_parecido_com_e_sem_usuario():
    # custo 10 para o tempo do bcrypt dominar o ruído do sistema
    h = s2_conhecimento.gerar_hash("abc12345", 10)
    s2_conhecimento.conferir("x", None, 10)          # aquece o hash fictício

    def medir(hash_):
        inicio = time.perf_counter()
        s2_conhecimento.conferir("errada", hash_, 10)
        return time.perf_counter() - inicio
    com, sem = medir(h), medir(None)
    assert 0.5 < com / sem < 2.0, (com, sem)


def test_s2_normaliza_unicode():
    composta, decomposta = "ação#2026", "ação#2026"   # "ação" de dois jeitos
    h = s2_conhecimento.gerar_hash(composta, CUSTO_TESTE)
    assert s2_conhecimento.conferir(decomposta, h, CUSTO_TESTE)


def test_s2_acima_de_72_bytes_recusada_no_cadastro_e_negada_no_login():
    longa = "a1" * 40   # 80 bytes
    with pytest.raises(ValueError):
        s2_conhecimento.gerar_hash(longa, CUSTO_TESTE)
    h = s2_conhecimento.gerar_hash(longa[:72], CUSTO_TESTE)
    # o bcrypt antigo truncaria e aceitaria a versão longa; aqui nega
    assert not s2_conhecimento.conferir(longa, h, CUSTO_TESTE)


def test_s2_hash_corrompido_nega_sem_excecao():
    assert not s2_conhecimento.conferir("abc", "lixo-no-banco", CUSTO_TESTE)


def test_s2_checklist_da_senha_forte():
    politica = s2_conhecimento.PoliticaSenha(12, ("maiuscula", "minuscula", "digito", "simbolo"))
    assert s2_conhecimento.pendencias("Unip#Aps2026", politica) == []
    faltando = s2_conhecimento.pendencias("unipaps", politica)
    assert "uma letra maiúscula" in faltando and "um símbolo (ex.: # @ ! %)" in faltando
    assert "ao menos 12 caracteres" in faltando


def test_s2_politica_le_o_config():
    cfg = carregar()
    assert s2_conhecimento.PoliticaSenha.de_configuracao(cfg, Nivel.N3).minimo_caracteres == 12


def test_s2_exigencia_desconhecida_e_erro_de_configuracao():
    with pytest.raises(ValueError):
        s2_conhecimento.PoliticaSenha(8, ("emoji",))


@pytest.mark.parametrize("existe, confere, forte, nivel, esperado", [
    (False, True, True, Nivel.N2, Motivo.USUARIO_INEXISTENTE),
    (True, False, True, Nivel.N2, Motivo.SENHA_INCORRETA),
    (True, None, True, Nivel.N2, Motivo.SENHA_INCORRETA),
    (True, True, False, Nivel.N3, Motivo.SENHA_FRACA),
    (True, True, None, Nivel.N3, Motivo.SENHA_FRACA),
    (True, True, None, Nivel.N2, None),          # N2 não exige senha forte
    (True, True, True, Nivel.N3, None),
    # senha fraca no N3 responde igual esteja ela certa ou errada, exista o
    # usuário ou não: a mensagem não pode confirmar que a senha confere
    (True, False, False, Nivel.N3, Motivo.SENHA_FRACA),
    (False, False, False, Nivel.N3, Motivo.SENHA_FRACA),
])
def test_s2_avaliar(existe, confere, forte, nivel, esperado):
    assert s2_conhecimento.avaliar(nivel, existe, confere, forte).motivo is esperado


# ================================================================ S3 Qualidade
@pytest.mark.parametrize("faces, qualidade, esperado", [
    (None, True, Motivo.FACE_AUSENTE),
    (0, True, Motivo.FACE_AUSENTE),
    (2, True, Motivo.MULTIPLAS_FACES),
    (1, False, Motivo.QUALIDADE_INSUFICIENTE),
    (1, None, Motivo.QUALIDADE_INSUFICIENTE),
    (1, True, None),
])
def test_s3_avaliar(faces, qualidade, esperado):
    assert s3_qualidade.avaliar(faces, qualidade).motivo is esperado


# ================================================================ S4 Inerência
LIMIARES = {Nivel.N1: 70.0, Nivel.N2: 60.0, Nivel.N3: 50.0}


def test_s4_distancia_menor_e_melhor():
    # o teste que impede inverter o sinal: perto aceita, longe nega
    assert s4_inerencia.avaliar(Nivel.N1, 10.0, 7, LIMIARES).aprovado
    assert not s4_inerencia.avaliar(Nivel.N1, 90.0, 7, LIMIARES).aprovado


def test_s4_limiar_e_inclusivo():
    assert s4_inerencia.avaliar(Nivel.N1, 70.0, 7, LIMIARES).aprovado
    assert not s4_inerencia.avaliar(Nivel.N1, 70.0001, 7, LIMIARES).aprovado


def test_s4_nan_nega():
    assert s4_inerencia.avaliar(Nivel.N1, math.nan, 7, LIMIARES).motivo is Motivo.FACE_NAO_RECONHECIDA


def test_s4_cada_nivel_usa_o_proprio_limiar():
    # 55 passa no N2 (60) e não passa no N3 (50)
    assert s4_inerencia.avaliar(Nivel.N2, 55.0, 7, LIMIARES, identidade_alegada=7).aprovado
    assert not s4_inerencia.avaliar(Nivel.N3, 55.0, 7, LIMIARES, identidade_alegada=7).aprovado


def test_s4_verificacao_nega_como_credencial_alheia():
    veredito = s4_inerencia.avaliar(Nivel.N2, 99.0, 7, LIMIARES, identidade_alegada=7)
    assert veredito.motivo is Motivo.CREDENCIAL_ALHEIA


def test_s4_verificacao_exige_distancia_medida_contra_o_alegado():
    # distância ótima, mas medida contra o usuário 8: quem digitou a senha foi o 7
    veredito = s4_inerencia.avaliar(Nivel.N2, 5.0, 8, LIMIARES, identidade_alegada=7)
    assert not veredito.aprovado


@pytest.mark.parametrize("distancia, medida", [(None, 7), (10.0, None)])
def test_s4_evidencia_ausente_nega(distancia, medida):
    assert not s4_inerencia.avaliar(Nivel.N1, distancia, medida, LIMIARES).aprovado


def test_s4_limiar_ausente_nega():
    assert not s4_inerencia.avaliar(Nivel.N1, 1.0, 7, {}).aprovado


# ================================================================ S5 Habilitação
@pytest.mark.parametrize("u, consentimento, solicitado, esperado", [
    (None, True, Nivel.N1, Motivo.ERRO_INTERNO),
    (usuario(ativo=False), True, Nivel.N1, Motivo.USUARIO_INATIVO),
    (usuario(), False, Nivel.N1, Motivo.CONSENTIMENTO_AUSENTE),
    (usuario(), None, Nivel.N1, Motivo.CONSENTIMENTO_AUSENTE),
    (usuario(nivel=Nivel.N1), True, Nivel.N2, Motivo.NIVEL_INSUFICIENTE),
    (usuario(nivel=Nivel.N3), True, Nivel.N1, Motivo.NIVEL_INSUFICIENTE),   # escopo exclusivo
    (usuario(nivel=Nivel.N3), True, Nivel.N3, None),
])
def test_s5_avaliar(u, consentimento, solicitado, esperado):
    veredito = s5_habilitacao.avaliar(u, consentimento, solicitado)
    assert veredito.motivo is esperado
    assert veredito.camada is C.S5_HABILITACAO


# ================================================================ S6 Vivacidade
def test_s6_sorteio_respeita_lista_e_quantidade():
    sequencia = s6_vivacidade.sortear(["PISCAR", "MOVER_DIREITA"], 5)
    assert len(sequencia) == 5
    assert set(sequencia) <= {s6_vivacidade.Desafio.PISCAR, s6_vivacidade.Desafio.MOVER_DIREITA}


def test_s6_sorteio_varia():
    gerador = random.Random(0)   # determinístico só no teste
    sorteios = {tuple(s6_vivacidade.sortear(["PISCAR", "MOVER_ESQUERDA", "MOVER_DIREITA"], 2, gerador))
                for _ in range(100)}
    assert len(sorteios) == 9    # todas as 3x3 combinações aparecem


def test_s6_piscada_garantida_em_toda_sequencia():
    gerador = random.Random(1)
    for _ in range(200):
        sequencia = s6_vivacidade.sortear(["PISCAR", "MOVER_ESQUERDA", "MOVER_DIREITA"], 2, gerador,
                                          exigir="PISCAR")
        assert s6_vivacidade.Desafio.PISCAR in sequencia


def test_s6_posicao_da_piscada_continua_imprevisivel():
    gerador = random.Random(2)
    posicoes = {s6_vivacidade.sortear(["MOVER_ESQUERDA", "MOVER_DIREITA", "PISCAR"], 2, gerador,
                                      exigir="PISCAR").index(s6_vivacidade.Desafio.PISCAR) for _ in range(200)}
    assert posicoes == {0, 1}


def test_s6_configuracao_vazia_e_erro():
    with pytest.raises(ValueError):
        s6_vivacidade.sortear([], 1)


def test_s6_todo_desafio_tem_instrucao():
    assert all(d.instrucao for d in s6_vivacidade.Desafio)


@pytest.mark.parametrize("confirmada, aprovado", [(True, True), (False, False), (None, False)])
def test_s6_avaliar(confirmada, aprovado):
    assert s6_vivacidade.avaliar(confirmada).aprovado is aprovado


# ================================================================ S7 Custódia
@pytest.mark.parametrize("segundo, autenticado, segundos, esperado", [
    (None, True, 10, Motivo.SEGUNDA_PESSOA_AUSENTE),
    (usuario(2), False, 10, Motivo.SEGUNDA_PESSOA_AUSENTE),
    (usuario(1), True, 10, Motivo.SEGUNDA_PESSOA_INVALIDA),             # a mesma pessoa
    (usuario(2, nivel=Nivel.N2), True, 10, Motivo.SEGUNDA_PESSOA_INVALIDA),
    (usuario(2, ativo=False), True, 10, Motivo.SEGUNDA_PESSOA_INVALIDA),
    (usuario(2), True, 121, Motivo.JANELA_EXPIRADA),
    (usuario(2), True, -1, Motivo.JANELA_EXPIRADA),
    (usuario(2), True, math.nan, Motivo.JANELA_EXPIRADA),
    (usuario(2), True, None, Motivo.JANELA_EXPIRADA),
    (usuario(2), True, 120, None),
])
def test_s7_avaliar(segundo, autenticado, segundos, esperado):
    veredito = s7_custodia.avaliar(usuario(1), segundo, autenticado, segundos, 120)
    assert veredito.motivo is esperado
