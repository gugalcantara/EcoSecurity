"""Importa o acervo gerado para o banco do acervo (ecosec_acervo).

Roda com uma conta que PODE escrever (root, na ferramenta de preparação; a
conta de testes, nos testes): nunca com a da aplicação, que só lê o cofre.

Só importa se o acervo estiver VAZIO: rodar de novo não duplica nada. O
catálogo de relatórios entra com INSERT IGNORE (acrescenta os que faltarem).
"""
from datetime import datetime

from ecosec.acervo import sinteticos


def _sql(valor) -> str:
    if valor is None:
        return "NULL"
    return "'" + str(valor).replace("\\", "\\\\").replace("'", "''") + "'"


def sql_referencia() -> str:
    """Texto de sql/acervo/02_referencia.sql, GERADO a partir de sinteticos.py (catálogo AG/MP e eventos):
    o banco e o código não divergem. Gravado por `python -m ferramentas.gerar_referencia`."""
    linhas = ["-- GERADO por ferramentas/gerar_referencia.py a partir de ecosec/acervo/sinteticos.py: NÃO EDITE À MÃO.",
              "-- Catálogo da camada causal e eventos regulatórios, no padrão de",
              "-- texto do banco. Idempotente: linhas existentes são ATUALIZADAS.",
              "-- Subclasses CNAE: só 8640-2/11 (AG-08) conferida; as demais A CONFERIR (integrante 3).", "",
              "INSERT INTO atividade_geradora (codigo, nome, descricao_operacional, cnae_subclasse, exemplos, "
              "observacao) VALUES"]
    linhas.append(",\n".join(
        f"({_sql(a.codigo)}, {_sql(a.nome)},\n {_sql(a.descricao_operacional)},\n {_sql(a.cnae_subclasse)}, "
        f"{_sql(a.exemplos)}, {_sql(a.observacao)})" for a in sinteticos.ATIVIDADES))
    linhas += ["AS novo ON DUPLICATE KEY UPDATE nome = novo.nome, descricao_operacional = novo.descricao_operacional,",
               "    cnae_subclasse = novo.cnae_subclasse, exemplos = novo.exemplos, observacao = novo.observacao;", "",
               "INSERT INTO motivo_permanencia (codigo, nome, descricao_operacional, base_legal, grupo, "
               "acao_institucional) VALUES"]
    linhas.append(",\n".join(
        f"({_sql(m.codigo)}, {_sql(m.nome)},\n {_sql(m.descricao_operacional)},\n {_sql(m.base_legal)}, "
        f"{_sql(m.grupo)}, {_sql(m.acao_institucional)})" for m in sinteticos.MOTIVOS))
    linhas += ["AS novo ON DUPLICATE KEY UPDATE nome = novo.nome, descricao_operacional = novo.descricao_operacional,",
               "    base_legal = novo.base_legal, grupo = novo.grupo, acao_institucional = novo.acao_institucional;", "",
               "INSERT INTO evento_regulatorio (data_evento, rotulo, descricao, classes, efeito, base_legal, "
               "verificacao) VALUES"]
    linhas.append(",\n".join(
        f"({_sql(e.data_evento.isoformat())}, {_sql(e.rotulo)},\n {_sql(e.descricao)},\n {_sql(','.join(e.classes))}, "
        f"{_sql(e.efeito)}, {_sql(e.base_legal)}, {_sql(e.verificacao)})" for e in sinteticos.EVENTOS))
    linhas += ["AS novo ON DUPLICATE KEY UPDATE descricao = novo.descricao, classes = novo.classes, "
               "efeito = novo.efeito,", "    base_legal = novo.base_legal, verificacao = novo.verificacao;", ""]
    return "\n".join(linhas)


def so_carga_gerada(conexao) -> bool:
    """True se o acervo não tem pendência de carga externa (`sintetico = FALSE`): ou nem tem a tabela."""
    cursor = conexao.cursor()
    try:
        cursor.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = DATABASE() "
                       "AND table_name = 'pendencia'")
        if cursor.fetchone()[0] == 0:
            return True
        cursor.execute("SELECT COUNT(*) FROM pendencia WHERE sintetico = FALSE")
        return cursor.fetchone()[0] == 0
    finally:
        cursor.close()


def importar_acervo(conexao) -> tuple[int, int]:
    """Devolve (pendências importadas, responsáveis importados); (0, 0) se já havia dados."""
    cursor = conexao.cursor()
    try:
        for item in sinteticos.CATALOGO:
            cursor.execute("INSERT IGNORE INTO item_acervo (codigo, titulo, tipo, nivel_minimo, regioes_revisadas, "
                           "sintetico) VALUES (%s, %s, 'RELATORIO', %s, TRUE, TRUE)",
                           (item.codigo, item.titulo, item.nivel_minimo))
        cursor.execute("SELECT COUNT(*) FROM pendencia")
        if cursor.fetchone()[0] > 0:
            conexao.commit()
            return 0, 0
        cursor.execute("SELECT codigo, id FROM atividade_geradora")
        atividades = dict(cursor.fetchall())
        cursor.execute("SELECT codigo, id FROM motivo_permanencia")
        motivos = dict(cursor.fetchall())
        pendencias, responsaveis = sinteticos.gerar()
        ids = {}
        for p in pendencias:
            cursor.execute(
                "INSERT INTO pendencia (codigo, substancia, classe_risco, quantidade, unidade, logradouro, numero, "
                "complemento, bairro, municipio, uf, cep, latitude, longitude, data_identificacao, prazo_coleta, "
                "situacao, data_encerramento, etapa_atual, atividade_id, motivo_id, sintetico, fonte) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (p.codigo, p.substancia, p.classe_risco, p.quantidade, p.unidade, p.logradouro, p.numero,
                 p.complemento, p.bairro, p.municipio, p.uf, p.cep, p.latitude, p.longitude, p.data_identificacao,
                 p.prazo_coleta, p.situacao, p.data_encerramento, p.etapa_atual, atividades[p.atividade],
                 motivos[p.motivo], p.sintetico, p.fonte))
            ids[p.codigo] = cursor.lastrowid
        cursor.executemany(
            "INSERT INTO etapa_gerenciamento (pendencia_id, ordem, nome, data_etapa, final) VALUES (%s, %s, %s, %s, %s)",
            [(ids[p.codigo], ordem, nome, dia, p.data_encerramento is not None and ordem == len(p.etapas))
             for p in pendencias for ordem, (nome, dia) in enumerate(p.etapas, 1)])
        cursor.executemany(
            "INSERT INTO responsavel (pendencia_id, nome, vinculo, situacao_cadastral, nivel_minimo) "
            "VALUES (%s, %s, %s, %s, %s)",
            [(ids[r.pendencia_codigo], r.nome, r.vinculo, r.situacao_cadastral, r.nivel_minimo) for r in responsaveis])
        conexao.commit()
        return len(pendencias), len(responsaveis)
    finally:
        cursor.close()


def inventariar_regioes(conexao, fontes) -> int:
    """Grava em regiao_sensivel as regiões que cada relatório anota na visão completa (nível 3,
    nacional, na data-base do gerador). É o inventário auditável do que a S8 pode suprimir;
    a aplicação continua anotando na hora, a cada consulta. Refeito do zero a cada chamada."""
    from collections import defaultdict

    from ecosec.acervo import relatorios

    pendencias, responsaveis = sinteticos.gerar()
    por_codigo = defaultdict(list)
    for r in responsaveis:
        por_codigo[r.pendencia_codigo].append(r)
    pendencias = [p for p in pendencias if p.ativa(sinteticos.DATA_BASE)]      # relatório = pendências ATIVAS
    dados = relatorios.DadosRelatorio(
        tuple(pendencias), {k: tuple(v) for k, v in por_codigo.items()},
        {a.codigo: a for a in sinteticos.ATIVIDADES}, {m.codigo: m for m in sinteticos.MOTIVOS},
        sinteticos.DATA_BASE, "Nacional", datetime.combine(sinteticos.DATA_BASE, datetime.min.time()), nivel=3)
    cursor = conexao.cursor()
    try:
        cursor.execute("DELETE FROM regiao_sensivel")
        cursor.execute("SELECT codigo, id FROM item_acervo WHERE tipo = 'RELATORIO'")
        itens = dict(cursor.fetchall())
        linhas = []
        for item in sinteticos.CATALOGO:
            if item.codigo not in itens:
                continue
            for r in relatorios.gerar(item, dados, fontes).regioes:
                linhas.append((itens[item.codigo], int(r.x), int(r.y), int(r.largura), int(r.altura), r.rotulo,
                               int(r.nivel_minimo)))
        cursor.executemany("INSERT INTO regiao_sensivel (item_id, x, y, largura, altura, rotulo, nivel_minimo) "
                           "VALUES (%s, %s, %s, %s, %s, %s, %s)", linhas)
        conexao.commit()
        return len(linhas)
    finally:
        cursor.close()
