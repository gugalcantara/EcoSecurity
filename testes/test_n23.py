"""A ficha do caso, aba "Dados técnicos" do mapa interativo (n23_ficha.FichaTecnica).

A ficha é uma sequência de blocos, do que decide para o que detalha: cabeçalho (código, substância, selos de classe e
de risco, score e andamento), Situação e prazos, Local, Origem e causa, Contaminação e uso, Custo estimado (com a
memória de cálculo recolhível) e Histórico de etapas, este como linha do tempo (n23_ficha.LinhaDoTempo).

Cobre: estado sem caso, cabeçalho, cada bloco com os rótulos do vocabulário, caso vencido e caso encerrado, a linha
do tempo (uma linha por etapa, duração até a etapa seguinte, a etapa atual marcada), a troca de caso sem acumular
linhas, as regras de nível (sem responsável nomeado nem custo por responsável; exportação só no N2, com o CSV do caso
pela tela) e o texto legível (blocos na ordem, sem travessão): os testes da ficha na tela ficam aqui.
"""
import re

import pytest

from ecosec.acervo import ficha, formatos, regras, sinteticos, vocabulario
from ecosec.dominio.entidades import Usuario
from ecosec.dominio.niveis import Nivel

BIA_N2 = Usuario(matricula="BIA", nome="Bia", nivel=2, uf="SP", senha_hash="$2b$x", id=2)
CAIO_N3 = Usuario(matricula="CAIO", nome="Caio", nivel=3, senha_hash="$2b$x", id=3)
USUARIOS = {Nivel.N2: BIA_N2, Nivel.N3: CAIO_N3}
TRAVESSOES = ("—", "–")
SIGLAS = {"BTEX", "PCB", "PCBs", "PAH", "PCE", "TCE", "HCH", "DDT", "BPF", "NORM", "CNEN", "PARAMETRO", "STF", "STJ",
          "RE", "CONAMA", "ABNT", "NBR", "MMA", "MTR", "CDF", "VI", "UF", "CEP", "SIRGAS"}


@pytest.fixture
def tela(qt, tmp_path):
    from ecosec.aplicacao import montar
    from ecosec.interface.tela_acervo import TelaAcervo
    app = montar(caminho_env=tmp_path / ".env", modo="memoria")
    t = TelaAcervo(app)
    t.resize(1500, 950)
    t.show()
    yield t
    t.encerrar()
    t.deleteLater()


def _abrir(tela, qt, nivel=Nivel.N2):
    tela.iniciar(USUARIOS[nivel], nivel)
    tela.mostrar_modo("painel")
    pa = tela.painel_analitico
    pa.mostrar("mapa")
    qt.processEvents()
    return pa


def _mostrar(pa, qt, p):
    pa.mapa.mostrar_ficha(p)
    qt.processEvents()
    return pa.mapa.ficha_tecnica


def _ativos(pa):
    """Um caso ativo de cada classe, sem encerramento marcado."""
    hoje = pa.painel.hoje
    return {c: next(p for p in pa.painel.pendencias
                    if p.classe_risco == c and p.ativa(hoje) and p.data_encerramento is None)
            for c in sinteticos.UNIDADE_DA_CLASSE}


def _encerrado(pa):
    return next(p for p in pa.painel.pendencias if p.encerrada(pa.painel.hoje))


def _vencido(pa):
    """Ativo, com a previsão vencida e já além do prazo legal."""
    hoje, r = pa.painel.hoje, pa.painel.regras
    return next(p for p in pa.painel.pendencias
                if p.ativa(hoje) and p.vencida(hoje) and regras.dias_alem_do_prazo_limite(p, hoje, r) > 0)


def _linha_do_tempo(ft):
    from ecosec.interface.n23_ficha import LinhaDoTempo
    extra = ft.blocos["historico"].extra
    assert extra.count() == 1
    linha = extra.itemAt(0).widget()
    assert isinstance(linha, LinhaDoTempo)
    return linha


def _valor(bloco, chave):
    """O QLabel do valor da linha chave de um bloco (para ler a dica)."""
    for i in range(bloco.grade.rowCount()):
        k = bloco.grade.itemAtPosition(i, 0)
        if k is not None and k.widget().text() == chave:
            return bloco.grade.itemAtPosition(i, 1).widget()
    raise KeyError(chave)


# estado sem caso
class TestEstadoInicial:
    def test_sem_caso_mostra_convite_e_esconde_selos_e_blocos(self, qt):
        from ecosec.interface.n23_ficha import FichaTecnica
        ft = FichaTecnica()
        assert ft.titulo.text() == "Clique num ponto"
        assert ft.subtitulo.text() == "A ficha do caso aparece aqui."
        assert not any(w.isVisibleTo(ft) for w in (ft.selo_classe, ft.selo_risco, ft.score))
        assert not any(b.isVisibleTo(ft) for b in ft.blocos.values())

    def test_texto_sem_caso_nao_lista_blocos(self, qt):
        from ecosec.interface.n23_ficha import ROTULO_BLOCO, FichaTecnica
        linhas = FichaTecnica().texto().split("\n")
        assert "Clique num ponto" in linhas
        assert not set(linhas) & set(ROTULO_BLOCO.values())


# cabeçalho
class TestCabecalho:
    @pytest.mark.parametrize("nivel", [Nivel.N2, Nivel.N3])
    def test_titulo_codigo_e_substancia_e_selos_do_vocabulario(self, tela, qt, nivel):
        pa = _abrir(tela, qt, nivel)
        hoje = pa.painel.hoje
        for p in _ativos(pa).values():
            ft = _mostrar(pa, qt, p)
            assert ft.titulo.text() == f"{p.codigo} · {vocabulario.frase(p.substancia)}"
            assert pa.mapa.ficha_titulo is ft.titulo
            assert ft.selo_classe.text() == vocabulario.rotulo(p.classe_risco, "classe")
            faixa = regras.categoria(p, hoje)
            assert ft.selo_risco.text() == vocabulario.rotulo_longo(faixa, "faixa") and ft.selo_risco.solido
            assert pa.mapa.selo_risco is ft.selo_risco and ft.selo_risco.isVisibleTo(pa.mapa.ficha)   # Em selo
            assert f"Score de risco <b>{formatos.numero(regras.criticidade(p, hoje), 1)}</b>" == ft.score.text()

    def test_subtitulo_ativo_andamento_e_fase(self, tela, qt):
        pa = _abrir(tela, qt)
        for p in _ativos(pa).values():
            ft = _mostrar(pa, qt, p)
            a = ficha.atributos(p, pa.painel.regras.custos)
            assert ft.subtitulo.text() == (f"Ativo · {vocabulario.rotulo(p.situacao, 'situacao_caso')} · fase "
                                           f"{vocabulario.rotulo(a.fase, 'fase').lower()}")


# blocos
class TestBlocos:
    @pytest.mark.parametrize("nivel", [Nivel.N2, Nivel.N3])
    def test_seis_blocos_na_ordem_com_titulos_do_vocabulario(self, tela, qt, nivel):
        from ecosec.interface.n23_ficha import BLOCOS, ROTULO_BLOCO
        assert list(ROTULO_BLOCO.values()) == ["Situação e prazos", "Local", "Origem e causa", "Contaminação e uso",
                                               "Custo estimado", "Histórico de etapas"]
        pa = _abrir(tela, qt, nivel)
        for p in _ativos(pa).values():
            ft = _mostrar(pa, qt, p)
            assert list(ft.blocos) == list(BLOCOS)
            assert [b.titulo.text() for b in ft.blocos.values()] == [ROTULO_BLOCO[c] for c in BLOCOS]
            assert all(b.isVisibleTo(ft) and b.linhas for b in ft.blocos.values())

    def test_situacao_etapa_prazos_acao_e_responsabilidade(self, tela, qt):
        pa = _abrir(tela, qt)
        hoje, r = pa.painel.hoje, pa.painel.regras
        for p in _ativos(pa).values():
            ft = _mostrar(pa, qt, p)
            s = dict(ft.blocos["situacao"].linhas)
            assert s["Etapa atual"] == vocabulario.rotulo(p.etapa_atual, "etapa")
            assert s[vocabulario.rotulo("IDENTIFICACAO", "campo")] == f"{p.data_identificacao:%d/%m/%Y}"
            assert s[vocabulario.rotulo("PRAZO_COLETA", "prazo")].startswith(f"{p.prazo_coleta:%d/%m/%Y}")
            assert s[vocabulario.rotulo("PRAZO_LIMITE", "prazo")].startswith(f"{regras.prazo_limite(p, r):%d/%m/%Y}")
            acao = regras.acao_recomendada(p, hoje, r)
            assert s[vocabulario.titulo_coluna("ACAO RECOMENDADA")] == vocabulario.rotulo(acao, "acao")
            resp = regras.responsabilidade(p)
            assert s[vocabulario.titulo_coluna("RESPONSABILIDADE")] == vocabulario.rotulo(resp, "responsabilidade")
            assert "Encerrado em" not in s
            assert _valor(ft.blocos["situacao"], "Etapa atual").toolTip() == vocabulario.dica(p.etapa_atual, "etapa")

    def test_situacao_vencido_mostra_dias_de_atraso_e_alem_do_prazo_legal(self, tela, qt):
        pa = _abrir(tela, qt)
        hoje, r = pa.painel.hoje, pa.painel.regras
        p = _vencido(pa)
        s = dict(_mostrar(pa, qt, p).blocos["situacao"].linhas)
        assert f"vencido há {formatos.inteiro(p.dias_de_atraso(hoje))} dias" in s[
            vocabulario.rotulo("PRAZO_COLETA", "prazo")]
        assert f"além do prazo legal há {formatos.inteiro(regras.dias_alem_do_prazo_limite(p, hoje, r))} dias" in s[
            vocabulario.rotulo("PRAZO_LIMITE", "prazo")]

    @pytest.mark.parametrize("nivel", [Nivel.N2, Nivel.N3])
    def test_local_municipio_endereco_e_coordenadas_com_virgula(self, tela, qt, nivel):
        pa = _abrir(tela, qt, nivel)
        for p in _ativos(pa).values():
            local = dict(_mostrar(pa, qt, p).blocos["local"].linhas)
            assert local["Município"] == f"{p.municipio}/{p.uf}"
            assert local["Endereço"] == p.endereco
            assert local["Coordenadas"] == f"{formatos.numero(p.latitude, 5)}; {formatos.numero(p.longitude, 5)}"
            assert "," in local["Coordenadas"]

    def test_origem_atividade_motivo_definicao_e_base_legal(self, tela, qt):
        pa = _abrir(tela, qt)
        com_base = [p for p in pa.painel.pendencias if vocabulario.BASE_LEGAL.get(p.motivo)]
        assert com_base
        for p in list(_ativos(pa).values()) + com_base[:1]:
            ft = _mostrar(pa, qt, p)
            b = ft.blocos["origem"]
            o = dict(b.linhas)
            atividade, motivo = vocabulario.rotulo("ATIVIDADE", "campo"), vocabulario.rotulo("MOTIVO", "campo")
            assert o[atividade].startswith(vocabulario.rotulo(p.atividade, "atividade"))
            assert vocabulario.definicao(p.atividade, "atividade") in o[atividade]
            assert o[motivo].startswith(vocabulario.rotulo(p.motivo, "motivo"))
            assert vocabulario.definicao(p.motivo, "motivo") in o[motivo]
            ag = pa.painel.atividades.get(p.atividade)
            if ag and ag.descricao_operacional:                  # a descrição operacional fica na dica
                assert _valor(b, atividade).toolTip() == vocabulario.frase(ag.descricao_operacional)
            if vocabulario.BASE_LEGAL.get(p.motivo):
                assert o["Base legal"] == vocabulario.BASE_LEGAL[p.motivo]

    def test_contaminacao_e_uso_pretendido_so_na_area(self, tela, qt):
        pa = _abrir(tela, qt)
        for classe, p in _ativos(pa).items():
            c = dict(_mostrar(pa, qt, p).blocos["contaminacao"].linhas)
            a = ficha.atributos(p, pa.painel.regras.custos)
            assert c["Quantidade"] == f"{formatos.numero(p.quantidade, 2)} {vocabulario.rotulo_unidade(p.unidade)}"
            assert c["Contaminante"] == vocabulario.frase(a.grupo_contaminante)
            assert c["Meio afetado"] == vocabulario.frase(a.meio)
            assert c["Restrição de uso"] == vocabulario.frase(a.restricao)     # sem "(PARAMETRO)"
            assert c["Uso anterior"] == vocabulario.frase(a.uso_anterior)
            if classe == sinteticos.AREA:
                assert c["Uso pretendido"] == vocabulario.frase(a.uso_pretendido)
            else:
                assert c["Uso pretendido"] == formatos.NAO_SE_APLICA

    def test_custo_total_rota_e_barra_que_soma_o_total(self, tela, qt):
        from ecosec.interface.n23_graficos import BarraPartes
        pa = _abrir(tela, qt)
        for p in _ativos(pa).values():
            ft = _mostrar(pa, qt, p)
            m = ficha.atributos(p, pa.painel.regras.custos).memoria
            b = ft.blocos["custo"]
            custo = dict(b.linhas)
            assert custo["Total"] == f"R$ {formatos.numero(m.total, 0)}"
            assert custo[vocabulario.rotulo("ROTA", "campo")] == vocabulario.frase(m.rota)
            assert "Base" not in custo                                  # sem data-base nem fonte
            barra = b.extra.itemAt(0).widget()
            assert isinstance(barra, BarraPartes)
            assert [n for n, *_ in barra.partes] == [vocabulario.rotulo(c.nome, "categoria_custo")
                                                    for c in m.categorias]
            assert sum(v for _, v, _, _ in barra.partes) == pytest.approx(m.total, abs=0.01)

    def test_sem_maiusculas_fora_do_local(self, tela, qt):
        # endereço e município são o registro postal, como gravados; o resto em grafia de frase
        pa = _abrir(tela, qt)
        for classe, p in list(_ativos(pa).items()) + [("encerrado", _encerrado(pa))]:
            ft = _mostrar(pa, qt, p)
            for chave in ("situacao", "origem", "contaminacao", "custo", "historico"):
                for rotulo, valor in ft.blocos[chave].linhas:
                    gritos = [w for w in re.findall(r"[A-ZÀ-Ý]{4,}", valor) if w not in SIGLAS]
                    assert not gritos, (classe, chave, rotulo, valor)


# memória de cálculo
class TestMemoriaDeCalculo:
    def test_recolhida_por_padrao_e_alterna_no_botao(self, tela, qt):
        pa = _abrir(tela, qt)
        ft = _mostrar(pa, qt, _ativos(pa)[sinteticos.AREA])
        assert not ft.memoria.isVisibleTo(ft) and ft.botao_memoria.text() == "Ver memória de cálculo"
        ft.botao_memoria.click()
        assert ft.memoria.isVisibleTo(ft) and ft.botao_memoria.text() == "Esconder memória de cálculo"
        ft.botao_memoria.click()
        assert not ft.memoria.isVisibleTo(ft) and ft.botao_memoria.text() == "Ver memória de cálculo"

    def test_categorias_e_componentes_somam_o_total(self, tela, qt):
        from ecosec.interface.componentes.simbologia import COR_IDENTIDADE
        pa = _abrir(tela, qt)
        for p in _ativos(pa).values():
            ft = _mostrar(pa, qt, p)
            m = ficha.atributos(p, pa.painel.regras.custos).memoria
            html = ft.memoria.text()
            assert sum(c.total for c in m.categorias) == pytest.approx(m.total, abs=0.01)
            for cat in m.categorias:
                assert f"{vocabulario.rotulo(cat.nome, 'categoria_custo')}</b>" in html
                assert f"R$&nbsp;{formatos.numero(cat.total, 2)}" in html
                for x in cat.componentes:
                    assert vocabulario.frase(x.nome) in html and " × R$&nbsp;" in html    # quantidade × unitário
            assert "Total (soma das categorias)</b>" in html and f"R$&nbsp;{formatos.numero(m.total, 2)}" in html
            assert not any(f"color:{cor}" in html for cor in COR_IDENTIDADE.values())      # Sem texto colorido


# histórico em linha do tempo
class TestHistorico:
    def test_uma_linha_por_etapa_com_datas_de_p_etapas_e_so_a_ultima_atual(self, tela, qt):
        pa = _abrir(tela, qt)
        for p in _ativos(pa).values():
            linha = _linha_do_tempo(_mostrar(pa, qt, p))
            assert [d for d, *_ in linha.etapas] == [d for _, d in p.etapas]
            assert [d for d, *_ in linha.etapas] == sorted(d for _, d in p.etapas)
            for (nome, _), (_, rotulo, _, _) in zip(p.etapas, linha.etapas):
                assert rotulo.startswith(vocabulario.rotulo(nome, "etapa"))
            assert [atual for *_, atual in linha.etapas] == [False] * (len(p.etapas) - 1) + [True]
            assert [r.endswith(" (atual)") for _, r, _, _ in linha.etapas] == [False] * (len(p.etapas) - 1) + [True]
            assert p.etapas[-1][0] == p.etapa_atual

    def test_duracao_de_cada_etapa_e_o_intervalo_ate_a_seguinte(self, tela, qt):
        from ecosec.interface.n23_ficha import _duracao
        pa = _abrir(tela, qt)
        hoje = pa.painel.hoje
        for p in _ativos(pa).values():
            linha = _linha_do_tempo(_mostrar(pa, qt, p))
            fins = [d for _, d in p.etapas[1:]] + [hoje]          # a etapa atual conta até hoje
            esperado = [_duracao(max(0, (fim - d).days)) for (_, d), fim in zip(p.etapas, fins)]
            assert [duracao for _, _, duracao, _ in linha.etapas] == esperado

    def test_altura_e_descricao_acessivel_acompanham_as_etapas(self, tela, qt):
        pa = _abrir(tela, qt)
        for p in _ativos(pa).values():
            ft = _mostrar(pa, qt, p)
            linha = _linha_do_tempo(ft)
            n = len(p.etapas)
            assert linha.minimumHeight() == linha.maximumHeight() == linha.LINHA * n + 6
            assert linha.accessibleName() == "Histórico de etapas"
            assert linha.accessibleDescription() == "; ".join(f"{d:%d/%m/%Y} {r}" for d, r, _, _ in linha.etapas)
            # o bloco guarda as mesmas linhas em texto, para leitura
            assert ft.blocos["historico"].linhas == [(f"{d:%d/%m/%Y}", r) for d, r, _, _ in linha.etapas]

    def test_caso_encerrado_ultima_etapa_sem_atual_e_sem_duracao(self, tela, qt):
        from ecosec.acervo import fase as fases
        pa = _abrir(tela, qt)
        p = _encerrado(pa)
        assert fases.FASE_DA_ETAPA.get(p.etapas[-1][0]) == fases.ENCERRADA
        linha = _linha_do_tempo(_mostrar(pa, qt, p))
        _, rotulo, duracao, _ = linha.etapas[-1]
        assert rotulo == vocabulario.rotulo(p.etapas[-1][0], "etapa") and duracao == ""
        assert all(duracao for _, _, duracao, _ in linha.etapas[:-1])


# duração em texto
class TestDuracao:
    @pytest.mark.parametrize("dias, texto", [(0, "0 dias"), (1, "1 dia"), (59, "59 dias"), (60, "2 meses"),
                                             (364, "12 meses"), (365, "1 ano"), (730, "2 anos"), (800, "2,2 anos")])
    def test_limites_dias_meses_e_anos(self, qt, dias, texto):
        from ecosec.interface.n23_ficha import _duracao
        assert _duracao(dias) == texto

    def test_ano_no_singular_e_virgula_decimal(self, qt):
        from ecosec.interface.n23_ficha import _duracao
        assert _duracao(366) == "1 ano"                   # anos inteiros sem decimal
        assert _duracao(400) == "1,1 anos"
        assert "." not in _duracao(3000)


# caso encerrado
class TestCasoEncerrado:
    def test_subtitulo_encerrado_e_linha_encerrado_em(self, tela, qt):
        pa = _abrir(tela, qt)
        p = _encerrado(pa)
        ft = _mostrar(pa, qt, p)
        assert ft.subtitulo.text().startswith("Encerrado · ")
        assert dict(ft.blocos["situacao"].linhas)["Encerrado em"] == f"{p.data_encerramento:%d/%m/%Y}"

    def test_encerrado_sem_alem_do_prazo_legal(self, tela, qt):
        pa = _abrir(tela, qt)
        ft = _mostrar(pa, qt, _encerrado(pa))
        assert "além do prazo legal" not in ft.blocos["situacao"].texto()


# troca de caso
class TestTrocaDeCaso:
    def test_abrir_outro_caso_nao_acumula_linhas_nem_widgets(self, tela, qt):
        pa = _abrir(tela, qt)
        a, b = _ativos(pa)[sinteticos.AREA], _encerrado(pa)
        _mostrar(pa, qt, a)
        ft = _mostrar(pa, qt, b)
        for chave, bloco in ft.blocos.items():
            if chave != "historico":                             # o histórico desenha na linha do tempo, sem grade
                assert bloco.grade.count() == 2 * len(bloco.linhas), chave
        assert ft.blocos["historico"].grade.count() == 0
        assert ft.blocos["custo"].extra.count() == 3                # barra, botão e memória
        assert len(ft.blocos["historico"].linhas) == len(b.etapas)
        assert _linha_do_tempo(ft).etapas[0][0] == b.etapas[0][1]
        assert ft.titulo.text().startswith(f"{b.codigo} · ")

    def test_memoria_volta_recolhida_ao_trocar(self, tela, qt):
        pa = _abrir(tela, qt)
        a, b = list(_ativos(pa).values())[:2]
        ft = _mostrar(pa, qt, a)
        ft.botao_memoria.click()
        assert ft.memoria.isVisibleTo(ft)
        ft = _mostrar(pa, qt, b)
        assert not ft.memoria.isVisibleTo(ft) and not ft.botao_memoria.isChecked()


# regras de nível
class TestRegrasDeNivel:
    @pytest.mark.parametrize("nivel", [Nivel.N2, Nivel.N3])
    def test_sem_responsavel_nomeado_nem_custo_por_responsavel(self, tela, qt, nivel):
        pa = _abrir(tela, qt, nivel)
        todos = tela.app.acervo.repo.responsaveis(3)
        for p in list(_ativos(pa).values()) + [_encerrado(pa)]:
            _mostrar(pa, qt, p)
            texto = pa.mapa.texto_ficha()
            nomes = {x.nome for x in todos if x.pendencia_codigo == p.codigo}
            assert not any(n in texto for n in nomes)
            assert "por responsável" not in texto.lower()
            if nivel is Nivel.N2:                                # o N2 não recebe pessoa física nem na aba própria
                fisicas = {x.nome for x in todos if x.pendencia_codigo == p.codigo and x.nivel_minimo == 3}
                assert not any(n in pa.mapa.ficha_responsaveis.text() for n in fisicas)

    @pytest.mark.parametrize("nivel", [Nivel.N2, Nivel.N3])
    def test_exportar_ficha_so_no_n2(self, tela, qt, nivel):
        pa = _abrir(tela, qt, nivel)
        _mostrar(pa, qt, _ativos(pa)[sinteticos.AREA])
        assert pa.mapa.botao_exportar_ficha.isVisibleTo(pa.mapa.ficha) == (nivel is Nivel.N2)

    def test_exportar_ficha_pela_tela_grava_o_csv_do_caso(self, tela, qt, tmp_path, monkeypatch):
        """O botão da ficha grava o CSV cru do caso aberto, com os campos novos (o conteúdo cru pelo serviço
        está em test_ficha.py, em test_exportacao_da_ficha_crua_com_os_campos_novos)."""
        import csv
        import io
        from datetime import datetime

        from ecosec.acervo import fase
        from ecosec.interface import painel_analitico
        pa = _abrir(tela, qt)
        p = _ativos(pa)[sinteticos.AREA]
        _mostrar(pa, qt, p)
        destino = tmp_path / "ficha_tela.csv"
        monkeypatch.setattr(painel_analitico, "_caminho_exportacao", lambda *_: destino)
        monkeypatch.setattr(tela, "exportar_com_verificacao", lambda operacao: operacao(datetime.now()))
        pa.mapa.exportar_ficha()
        titulos, valores = csv.reader(io.StringIO(destino.read_bytes().decode("utf-8-sig")), delimiter=";")
        linha = dict(zip(titulos, valores))
        assert linha["CODIGO"] == p.codigo and linha["FASE"] == fase.fase(p)
        assert all(t in linha for t in ficha.TITULOS_EXPORTACAO)


# texto legível
class TestTextoLegivel:
    def test_texto_so_blocos_visiveis_na_ordem(self, tela, qt):
        from ecosec.interface.n23_ficha import BLOCOS, ROTULO_BLOCO
        pa = _abrir(tela, qt)
        ft = _mostrar(pa, qt, _ativos(pa)[sinteticos.AREA])
        titulos = set(ROTULO_BLOCO.values())
        assert [x for x in ft.texto().split("\n") if x in titulos] == [ROTULO_BLOCO[c] for c in BLOCOS]
        ft.blocos["origem"].hide()
        assert [x for x in ft.texto().split("\n") if x in titulos] == [ROTULO_BLOCO[c] for c in BLOCOS
                                                                       if c != "origem"]

    def test_nenhum_travessao_visivel(self, tela, qt):
        pa = _abrir(tela, qt)
        for p in list(_ativos(pa).values()) + [_encerrado(pa), _vencido(pa)]:
            ft = _mostrar(pa, qt, p)
            visivel = ft.texto() + ft.memoria.text()
            assert not any(t in visivel for t in TRAVESSOES), p.codigo
