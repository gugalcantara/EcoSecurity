"""Acervo: dados fictícios, relatórios por nível, tarja/marca/trilha e exportação."""
import re
from datetime import date, datetime

import cv2
import numpy as np
import pytest

from ecosec.acervo import sinteticos
from ecosec.configuracao import carregar
from ecosec.dominio.entidades import Usuario
from ecosec.repositorios.memoria import RepositorioAcervoMemoria, RepositorioTrilhaMemoria
from ecosec.seguranca.autorizacao import Operacao
from ecosec.servicos.acervo import MENSAGENS, ErroAcervo, ServicoAcervo
from ecosec.servicos.trilha import ServicoTrilha

CFG = carregar()
ANA_N1 = Usuario(matricula="ANA", nome="Ana", nivel=1, senha_hash="$2b$x", id=1)
BIA_N2 = Usuario(matricula="BIA", nome="Bia", nivel=2, uf="PR", senha_hash="$2b$x", id=2)
CAIO_N3 = Usuario(matricula="CAIO", nome="Caio", nivel=3, senha_hash="$2b$x", id=3)


class Espiao(RepositorioAcervoMemoria):
    """Registra o que o serviço pediu ao repositório."""

    def __init__(self):
        super().__init__()
        self.pedidos = []

    def pendencias(self, uf=None):
        self.pedidos.append(("pendencias", uf))
        return super().pendencias(uf)

    def responsaveis(self, nivel, uf=None):
        self.pedidos.append(("responsaveis", nivel, uf))
        return super().responsaveis(nivel, uf)


@pytest.fixture
def acervo():
    trilha = ServicoTrilha(RepositorioTrilhaMemoria())
    servico = ServicoAcervo.de_configuracao(CFG, Espiao(), trilha, b"chave-teste",
                                            relogio=lambda: datetime(2026, 10, 7, 10, 30))
    servico.data_referencia = date(2026, 10, 7)
    return servico


def eventos(servico):
    return [(r.evento.evento, r.evento.resultado, r.evento.motivo) for r in reversed(servico.trilha.recentes(50))]


# dados fictícios
def test_gerador_e_deterministico():
    assert sinteticos.gerar() == sinteticos.gerar()


def test_toda_pendencia_tem_atividade_e_motivo():
    pendencias, _ = sinteticos.gerar()
    assert all(p.atividade.startswith("AG-") and p.motivo.startswith("MP-") for p in pendencias)
    assert all(p.sintetico for p in pendencias)


def test_ha_casos_de_todos_os_tipos_para_os_relatorios():
    pendencias, responsaveis = sinteticos.gerar()
    hoje = date(2026, 10, 7)
    assert any(p.vencida(hoje) for p in pendencias) and any(not p.vencida(hoje) for p in pendencias)
    assert any(p.motivo == "MP-08" for p in pendencias)
    assert any(r.nivel_minimo == 3 for r in responsaveis)   # há quem só a custódia veja


# catálogo e escopo
def test_catalogo_por_nivel(acervo):
    """Escopo exclusivo. Antes o N2 listava 6 (A1 e A2) e o N3, 9."""
    assert [r.codigo for r in acervo.catalogo(1)] == ["A1-01", "A1-02", "A1-05"]
    assert [r.codigo for r in acervo.catalogo(2)] == ["A2-01", "A2-02", "A2-04"]
    assert [r.codigo for r in acervo.catalogo(3)] == ["A3-01", "A3-02", "A3-03"]


def test_nivel_1_nunca_recebe_a_cadeia_de_responsaveis(acervo):
    acervo.abrir("A1-05", ANA_N1, 1)
    assert not any(p[0] == "responsaveis" for p in acervo.repo.pedidos)


def test_nivel_2_so_recebe_a_propria_regiao(acervo):
    acervo.abrir("A2-01", BIA_N2, 2)
    assert ("pendencias", "PR") in acervo.repo.pedidos
    assert ("responsaveis", 2, "PR") in acervo.repo.pedidos


def test_responsavel_de_nivel_3_nem_sai_do_repositorio_no_nivel_2():
    repo = RepositorioAcervoMemoria()
    assert all(r.nivel_minimo <= 2 for r in repo.responsaveis(2))
    assert any(r.nivel_minimo == 3 for r in repo.responsaveis(3))


def test_nivel_1_pedindo_relatorio_de_nivel_2_e_negado_e_registrado(acervo):
    with pytest.raises(ErroAcervo):
        acervo.abrir("A2-01", ANA_N1, 1)
    assert ("CONSULTA", "NEGADO", "NIVEL_INSUFICIENTE") in eventos(acervo)


def test_usuario_nao_pode_pedir_nivel_acima_do_seu(acervo):
    with pytest.raises(ErroAcervo):
        acervo.abrir("A3-02", BIA_N2, 3)


# mapas: omissão no N1
def _rotulos(entrega):
    return sorted({r.rotulo for r in entrega.suprimidas})


def test_mapa_de_densidade_e_so_do_n1_e_nao_tem_o_que_suprimir(acervo):
    """No N1 os pontos são omitidos (só a bolha agregada por estado): nada a suprimir: antes o mesmo A1-05
    abria nos três níveis; agora é só da camada 1 (o N2 e o N3 têm o mapa interativo do painel)."""
    assert _rotulos(acervo.abrir("A1-05", ANA_N1, 1)) == []
    for u in (BIA_N2, CAIO_N3):
        with pytest.raises(ErroAcervo):
            acervo.abrir("A1-05", u, u.nivel)


def _pixels_azuis(imagem):
    """Azul dos depósitos só na área do mapa (x < 660): as barras do gráfico ao lado usam o mesmo azul."""
    mapa = imagem[:, 50:660]
    b, g, r = (mapa[..., i].astype(int) for i in range(3))
    return int(((b > 150) & (r < 80) & (g > 90) & (g < 140)).sum())


def test_custodia_nem_e_desenhada_abaixo_do_nivel_3(acervo, monkeypatch):
    """Uma tarja no lugar da instalação revelaria onde ela está, então a instalação é omitida. O mapa de
    densidade é só do N1, cujo coroplético já tem azul (os pixels não servem de prova); a prova é que nenhuma
    instalação é desenhada nele.
    O A3-03 (N3) é o controle: lá as instalações e os quadrados azuis existem."""
    from ecosec.acervo.desenho import Tela
    desenhados, original = [], Tela.texto

    def registrar(self, x, y, conteudo, *args, **kwargs):
        desenhados.append(str(conteudo))
        return original(self, x, y, conteudo, *args, **kwargs)
    monkeypatch.setattr(Tela, "texto", registrar)
    nomes = {c.nome for c in sinteticos.CUSTODIAS}
    acervo.abrir("A1-05", ANA_N1, 1)
    assert not any(nome in texto for texto in desenhados for nome in nomes)      # no N1, nenhuma instalação
    desenhados.clear()
    n3 = acervo.abrir("A3-03", CAIO_N3, 3)
    assert any(nome in texto for texto in desenhados for nome in nomes) and _pixels_azuis(n3.imagem) > 200


def _pontos_vermelhos(imagem):
    """O vermelho dos pontos de pendência, só na área do mapa (x < 650)."""
    mapa = imagem[:, 50:650]
    b, g, r = (mapa[..., i].astype(int) for i in range(3))
    return int(((r > 180) & (g < 80) & (b < 90)).sum())


def test_mapa_no_nivel_1_nao_desenha_nenhum_ponto(acervo):
    """Omissão, não tarja: no N1 nenhum ponto de pendência é desenhado, nem existe pixel a esconder."""
    assert _pontos_vermelhos(acervo.abrir("A1-05", ANA_N1, 1).imagem) == 0
    assert _pontos_vermelhos(acervo.abrir("A3-03", CAIO_N3, 3).imagem) > 500       # no N3 os pontos existem


def test_endereco_no_nivel_2_e_visivel_e_responsavel_n3_nem_aparece(acervo):
    entrega = acervo.abrir("A2-01", BIA_N2, 2)
    assert "ENDERECO" not in _rotulos(entrega)               # N2 vê endereço da própria região
    assert "RESPONSAVEL" not in _rotulos(entrega)            # os de N3 nem foram desenhados (filtro na origem)


def test_a2_01_traz_os_atributos_da_ficha_da_tela(acervo, monkeypatch):
    """A ficha do relatório tem os mesmos atributos da ficha da tela."""
    from ecosec.acervo.desenho import Tela
    desenhados, original = [], Tela.texto

    def registrar(self, x, y, conteudo, *args, **kwargs):
        desenhados.append(conteudo)
        return original(self, x, y, conteudo, *args, **kwargs)
    monkeypatch.setattr(Tela, "texto", registrar)
    acervo.abrir("A2-01", BIA_N2, 2)
    texto = "\n".join(desenhados)
    # A ficha virou grade com o rótulo SOBRE o valor; o rótulo é um texto próprio, sem ":"
    for rotulo in ("Fase", "Contaminante", "Restrição de uso", "Uso anterior", "Uso pretendido"):
        assert rotulo in desenhados, rotulo
    assert "PARAMETRO" not in texto and "simulado)" not in texto     # sem "(valor simulado)"
    assert "—" not in texto and "–" not in texto and "DOCUMENTO SIMULADO" not in texto


# marca d'água
def test_niveis_2_e_3_recebem_marca_com_quem_e_quando(acervo):
    entrega = acervo.abrir("A2-02", BIA_N2, 2)
    marca = acervo.identificar_marca(entrega.imagem)
    assert entrega.marcada and marca.usuario_id == BIA_N2.id
    # a marca guarda UTC; convertida para o fuso local, é o momento da consulta
    assert marca.momento.astimezone().replace(tzinfo=None) == datetime(2026, 10, 7, 10, 30)


@pytest.mark.parametrize("fator", [0.5, 0.75])
def test_copia_reduzida_ainda_identifica_quem_vazou(acervo, fator):
    """Quem vaza costuma reduzir a imagem. A marca DCT vive na grade 8x8 do
    tamanho original: o serviço devolve a cópia à largura dos relatórios e lê."""
    imagem = acervo.abrir("A2-01", BIA_N2, 2).imagem             # O A1-05 é só do N1
    reduzida = cv2.resize(imagem, None, fx=fator, fy=fator, interpolation=cv2.INTER_AREA)
    assert acervo.identificar_marca(reduzida).usuario_id == BIA_N2.id


def test_nivel_1_nao_e_marcado(acervo):
    entrega = acervo.abrir("A1-01", ANA_N1, 1)
    assert not entrega.marcada and acervo.identificar_marca(entrega.imagem) is None


# marca VISÍVEL
CINZA_DA_MARCA = 120


def _sem_marca_visivel(acervo, monkeypatch, codigo, usuario, nivel):
    """O mesmo relatório, no mesmo minuto, sem a marca visível: a referência para medir só ela."""
    from ecosec.acervo import desenho
    with monkeypatch.context() as m:
        m.setattr(desenho, "desenhar_marca_visivel", lambda imagem, texto: imagem, raising=False)
        return acervo.abrir(codigo, usuario, nivel).imagem


def _alterados_por_terco(imagem, referencia):
    """Pixels que a marca mudou (mais de 8 níveis somados), em cada terço da altura da página."""
    mudou = np.abs(imagem.astype(int) - referencia.astype(int)).sum(axis=2) > 8
    terco = mudou.shape[0] // 3
    return [int(mudou[i * terco:(i + 1) * terco].sum()) for i in range(3)]


@pytest.mark.parametrize("codigo, usuario, verificado_em", [
    ("A1-01", ANA_N1, None),                                      # N1: matrícula de quem consultou
    ("A2-04", BIA_N2, datetime(2026, 10, 7, 10, 29)),             # N2: rosto conferido há 1 minuto
], ids=["N1", "N2"])
def test_relatorio_exportado_tem_marca_dagua_visivel_com_matricula_e_data(acervo, monkeypatch, tmp_path, codigo,
                                                                          usuario, verificado_em):
    """Matrícula de quem consultou e a hora da CONSULTA (o mesmo minuto da S9), em diagonal pela página
    inteira; o arquivo exportado é a imagem da tela."""
    referencia = _sem_marca_visivel(acervo, monkeypatch, codigo, usuario, usuario.nivel)
    entrega = acervo.abrir(codigo, usuario, usuario.nivel)
    assert entrega.marca_visivel == f"MATRÍCULA {usuario.matricula} · 07/10/2026 10:30"
    destino = acervo.exportar(entrega, usuario, tmp_path / f"{codigo}.png", verificado_em=verificado_em)
    arquivo = cv2.imdecode(np.frombuffer(destino.read_bytes(), np.uint8), cv2.IMREAD_COLOR)
    assert np.array_equal(arquivo, entrega.imagem)                                    # tela = arquivo
    assert all(n > 2000 for n in _alterados_por_terco(arquivo, referencia)), _alterados_por_terco(arquivo, referencia)


def test_marca_dagua_nao_cobre_conteudo_sensivel(acervo, monkeypatch):
    """A diagonal cruza tabelas e mapa: não pode esconder. Cada pixel anda no máximo 30% do caminho até o
    cinza da marca, então o texto escuro continua escuro e nada fica ilegível. N1: sem S9, só a marca muda."""
    referencia = _sem_marca_visivel(acervo, monkeypatch, "A1-05", ANA_N1, 1)
    imagem = acervo.abrir("A1-05", ANA_N1, 1).imagem
    antes, depois = referencia.astype(float), imagem.astype(float)
    assert np.abs(depois - antes).max() > 0, "nenhuma marca visível"
    caminho = CINZA_DA_MARCA - antes                                   # até onde o pixel iria com opacidade 100%
    andou = np.divide(depois - antes, caminho, out=np.zeros_like(antes), where=np.abs(caminho) > 10)
    assert andou.min() >= -0.02 and andou.max() <= 0.30                # sempre em direção ao cinza, no máximo 30%
    escuro = antes.max(axis=2) < 80                                    # texto e traço escuros do relatório
    assert depois[escuro].max() < 100                                  # continuam escuros (80 + 30% de 40 = 92)


def test_marca_dagua_invisivel_continua_funcionando(acervo, tmp_path):
    """A marca visível entra antes da S9, e o arquivo exportado no N2 continua dizendo
    quem consultou e em que minuto."""
    entrega = acervo.abrir("A2-04", BIA_N2, 2)
    destino = acervo.exportar(entrega, BIA_N2, tmp_path / "s9.png", verificado_em=datetime(2026, 10, 7, 10, 29))
    marca = acervo.identificar_marca(cv2.imdecode(np.frombuffer(destino.read_bytes(), np.uint8), cv2.IMREAD_COLOR))
    assert entrega.marcada and marca.usuario_id == BIA_N2.id
    assert marca.momento.astimezone().replace(tzinfo=None) == datetime(2026, 10, 7, 10, 30)


# trilha
def test_consulta_vai_para_a_trilha(acervo):
    acervo.abrir("A1-02", ANA_N1, 1)
    assert eventos(acervo)[-1] == ("CONSULTA", "CONCEDIDO", "CONSULTA_ACERVO")


def test_sem_registro_a_imagem_nao_e_entregue(acervo):
    class Quebrada:
        def registrar(self, *_a, **_k):
            raise OSError("trilha fora do ar")
    acervo.trilha = Quebrada()
    with pytest.raises(OSError):
        acervo.abrir("A1-01", ANA_N1, 1)


# exportação
def test_nivel_1_exporta_livre(acervo, tmp_path):
    destino = acervo.exportar(acervo.abrir("A1-01", ANA_N1, 1), ANA_N1, tmp_path / "relatório.png")
    assert destino.exists()                                  # nome com acento: cv2.imwrite falharia aqui


def test_nivel_2_exporta_com_marca_recuperavel_do_arquivo(acervo, tmp_path):
    # N2: o rosto foi conferido há 1 minuto (step-up dentro da janela)
    destino = acervo.exportar(acervo.abrir("A2-04", BIA_N2, 2), BIA_N2, tmp_path / "rastreio.png",
                              verificado_em=datetime(2026, 10, 7, 10, 29))
    imagem = cv2.imdecode(np.frombuffer(destino.read_bytes(), np.uint8), cv2.IMREAD_COLOR)
    assert acervo.identificar_marca(imagem).usuario_id == BIA_N2.id
    assert ("EXPORTACAO", "CONCEDIDO", "EXPORTACAO_COM_MARCA") in eventos(acervo)


def test_nivel_3_nao_exporta(acervo, tmp_path):
    bloqueio = MENSAGENS[("EXPORTACAO_BLOQUEADA", Operacao.EXPORTAR_RELATORIO)]
    with pytest.raises(ErroAcervo, match=re.escape(bloqueio)):
        acervo.exportar(acervo.abrir("A3-01", CAIO_N3, 3), CAIO_N3, tmp_path / "x.png")
    assert not (tmp_path / "x.png").exists()
    assert ("EXPORTACAO", "NEGADO", "EXPORTACAO_BLOQUEADA") in eventos(acervo)


def test_so_quem_abriu_exporta(acervo, tmp_path):
    entrega = acervo.abrir("A1-01", ANA_N1, 1)
    with pytest.raises(ErroAcervo, match="pessoal"):
        acervo.exportar(entrega, BIA_N2, tmp_path / "x.png")


def test_todos_os_relatorios_abrem_no_nivel_deles(acervo):
    for item in sinteticos.CATALOGO:
        usuario = {1: ANA_N1, 2: BIA_N2, 3: CAIO_N3}[item.nivel_minimo]
        entrega = acervo.abrir(item.codigo, usuario, item.nivel_minimo)
        assert entrega.imagem.ndim == 3 and entrega.imagem.shape[1] == 1000


# MySQL: mesmo comportamento da memória
def test_acervo_mysql_igual_ao_da_memoria(acervo_mysql):
    from ecosec.repositorios.mysql import RepositorioAcervoMySQL
    mysql, memoria = RepositorioAcervoMySQL(acervo_mysql), RepositorioAcervoMemoria()
    assert [r.codigo for r in mysql.catalogo()] == [r.codigo for r in memoria.catalogo()]
    assert mysql.pendencias() == memoria.pendencias()
    assert mysql.pendencias("PR") == memoria.pendencias("PR")
    assert sorted(mysql.responsaveis(2), key=str) == sorted(memoria.responsaveis(2), key=str)
    assert all(r.nivel_minimo <= 2 for r in mysql.responsaveis(2))       # filtro na consulta SQL


def test_importacao_nao_duplica(acervo_mysql):
    from ecosec.repositorios.mysql import conectar_direto
    from ecosec.repositorios.mysql.importacao import importar_acervo
    p = acervo_mysql.p
    conexao = conectar_direto(p.host, p.porta, p.usuario, p.senha, p.banco)
    try:
        assert importar_acervo(conexao) == (0, 0)
    finally:
        conexao.close()



def test_desenhar_dado_sensivel_ja_marca_a_regiao():
    """O desenho anota a região no mesmo gesto: sem isso, a tarja não teria o que esconder."""
    from ecosec.acervo import relatorios
    from ecosec.acervo.desenho import Fontes
    pendencias, responsaveis = sinteticos.gerar()
    por_codigo = {}
    for r in responsaveis:
        por_codigo.setdefault(r.pendencia_codigo, []).append(r)
    dados = relatorios.DadosRelatorio(tuple(pendencias), {k: tuple(v) for k, v in por_codigo.items()},
                                      {a.codigo: a for a in sinteticos.ATIVIDADES},
                                      {m.codigo: m for m in sinteticos.MOTIVOS}, date(2026, 10, 7), "Nacional",
                                      datetime(2026, 10, 7, 10, 0), nivel=3)
    item = next(i for i in sinteticos.CATALOGO if i.codigo == "A2-01")
    rotulos = {r.rotulo for r in relatorios.gerar(item, dados, Fontes.de_configuracao(CFG)).regioes}
    assert {"ENDERECO", "COORDENADA", "RESPONSAVEL"} <= rotulos
