"""Prepara o MySQL do EcoSecurity: bancos, tabelas, dados de referência e contas.

    .venv\\Scripts\\python.exe -m ferramentas.preparar_banco

Pede a senha do root uma vez (digitada por você, não guardada em lugar
nenhum). O root só serve para isto; a aplicação nunca o usa.

Cria três contas, cada uma com o mínimo de que precisa:

  conta          banco              pode                         não pode
  -------------  -----------------  ----------------------------  --------------------------------
  ecosec_seg     ecosec_seguranca   ler; inserir; alterar usuário  apagar usuário, consentimento,
                                    e consentimento; registrar     amostra; mexer no acervo
                                    amostras e tentativas
  ecosec_cofre   ecosec_acervo      só ler                         gravar qualquer coisa no acervo
  ecosec_teste   ecosec_teste_*     tudo (bancos descartáveis)     tocar nos bancos reais

Assim, mesmo com um defeito ou uma injeção de SQL na aplicação, o estrago fica
limitado ao que a conta pode: e ela não pode apagar provas nem alterar o cofre.

Idempotente: pode rodar de novo. Tabelas existentes são mantidas; privilégios
são refeitos do zero (REVOKE + GRANT), corrigindo qualquer excesso.
"""
import argparse
import getpass
import secrets
import re
import sys

from ecosec import segredos
from ecosec.configuracao import carregar
from ecosec.repositorios.contratos import ErroRepositorio
from ecosec.repositorios.mysql.conexao import conectar_direto
from ecosec.dominio import texto
from ecosec.repositorios.mysql.importacao import importar_acervo, inventariar_regioes, so_carga_gerada
from ecosec.repositorios.mysql.scripts import executar_scripts

HOSTS = ("localhost", "127.0.0.1")       # só conexões desta máquina

# Colunas acrescentadas depois que o banco já existia. CREATE TABLE IF NOT EXISTS
# não altera tabela existente, e o MySQL (ao contrário do MariaDB) não aceita
# "ADD COLUMN IF NOT EXISTS": então a ferramenta pergunta ao information_schema.
MIGRACOES = (
    ("seguranca", "consentimento", "autoriza_pesquisa",
     "ALTER TABLE consentimento ADD COLUMN autoriza_pesquisa BOOLEAN NOT NULL DEFAULT FALSE AFTER revogado_em"),
)
# Acervo de schema antigo: o schema mudou demais para ALTERs; como o acervo é todo gerado, ele é
# recriado (ver _recriar_acervo). Antigo = tem a coluna única `endereco` (antes de 13/10/2026) ou
# ainda não tem `data_encerramento` (antes do ciclo de vida, 17/10/2026).
COLUNA_ACERVO_ANTIGO = ("pendencia", "endereco")
COLUNA_ACERVO_CICLO = ("pendencia", "data_encerramento")

# Conferências do acervo importado
SQL_CONSISTENCIA = ("SELECT p.codigo FROM pendencia p "
                    "LEFT JOIN etapa_gerenciamento e ON e.pendencia_id = p.id AND e.final = TRUE "
                    "WHERE (p.data_encerramento IS NULL) <> (e.id IS NULL) OR p.data_encerramento <> e.data_etapa")
SQL_QUEDAS = ("SELECT ano, total, anterior FROM (SELECT ano, SUM(ativas_fim_do_ano) AS total, "
              "LAG(SUM(ativas_fim_do_ano)) OVER (ORDER BY ano) AS anterior FROM vw_fluxo_estoque_anual "
              "GROUP BY ano) serie WHERE total < anterior")

PRIVILEGIOS_SEGURANCA = {
    "nivel": "SELECT",
    "usuario": "SELECT, INSERT, UPDATE",
    "consentimento": "SELECT, INSERT, UPDATE",
    "amostra": "SELECT, INSERT",
    "tentativa": "SELECT, INSERT, UPDATE",
    "estacao": "SELECT, INSERT, UPDATE",          # MFA adaptativo: estações já usadas por cada pessoa
    # papel de administrador e códigos de recuperação: tirar o papel e usar um código marcam, não apagam
    "administrador": "SELECT, INSERT, UPDATE",
    "codigo_recuperacao": "SELECT, INSERT, UPDATE",
    # a trilha só cresce: sem UPDATE e sem DELETE, nem a própria aplicação reescreve o passado
    "log_acesso": "SELECT, INSERT",
}


def _senha_da_conta(chave_env: str) -> str:
    """Reaproveita a senha que já está no .env; senão gera uma nova, aleatória."""
    return segredos.ler(chave_env) or secrets.token_urlsafe(24)


IDENTIFICADOR = re.compile(r"[A-Za-z0-9_]{1,64}")


def _secao_banco(cfg) -> dict:
    """Nomes de banco entram em comandos executados como root (CREATE, USE, GRANT), onde
    identificadores não podem ir como parâmetro. Só letras, números e "_": um nome com
    crase ou ponto e vírgula no config viraria SQL arbitrário com privilégio máximo."""
    b = cfg.secao("banco")
    for chave in ("seguranca", "acervo", "prefixo_teste"):
        if not IDENTIFICADOR.fullmatch(str(b[chave])):
            raise SystemExit(f"[FALHA] [banco] {chave} = {b[chave]!r}: use só letras, números e _ (até 64).")
    return b


def _executar(cursor, sql, parametros=None):
    cursor.execute(sql, parametros or ())
    if cursor.with_rows:
        cursor.fetchall()


def _conta(cursor, usuario: str, senha: str):
    for host in HOSTS:
        _executar(cursor, "CREATE USER IF NOT EXISTS %s@%s IDENTIFIED BY %s", (usuario, host, senha))
        _executar(cursor, "ALTER USER %s@%s IDENTIFIED BY %s", (usuario, host, senha))
        _executar(cursor, "REVOKE ALL PRIVILEGES, GRANT OPTION FROM %s@%s", (usuario, host))


def _coluna_existe(cursor, banco: str, tabela: str, coluna: str) -> bool:
    cursor.execute("SELECT COUNT(*) FROM information_schema.columns WHERE table_schema = %s "
                   "AND table_name = %s AND column_name = %s", (banco, tabela, coluna))
    return cursor.fetchone()[0] > 0


def _recriar_acervo(raiz, cursor, nome: str, pedido: bool) -> None:
    """Apaga e recria o banco do acervo, se pedido ou se o schema for o antigo. Recusa se houver
    carga externa (`sintetico = FALSE`): só o que o gerador produziu pode ser refeito."""
    cursor.execute("SELECT COUNT(*) FROM information_schema.schemata WHERE schema_name = %s", (nome,))
    if cursor.fetchone()[0] == 0:
        return
    antigo = (_coluna_existe(cursor, nome, *COLUNA_ACERVO_ANTIGO)
              or not _coluna_existe(cursor, nome, *COLUNA_ACERVO_CICLO))
    if not (pedido or antigo):
        return
    raiz.database = nome
    if not so_carga_gerada(raiz):
        raise SystemExit("[FALHA] O acervo tem pendências de carga externa (sintetico = FALSE): nada foi apagado.")
    _executar(cursor, f"DROP DATABASE `{nome}`")
    print(f"  {nome}: recriado" + (" (schema anterior ao ciclo de vida)" if antigo else ""))


def _padronizar_seguranca(raiz, cursor, nome: str) -> None:
    """Nomes de usuário em maiúsculas, sem acento (ecosec.dominio.texto), e o CHECK que mantém o padrão.
    A trilha e o consentimento antigos não são tocados: entram em hashes (são prova)."""
    raiz.database = nome
    cursor.execute("SELECT id, nome FROM usuario")
    for usuario_id, atual in cursor.fetchall():
        if texto.nome(atual) != atual:
            cursor.execute("UPDATE usuario SET nome = %s WHERE id = %s", (texto.nome(atual), usuario_id))
            print(f"  migração: nome do usuário {usuario_id} padronizado")
    cursor.execute("SELECT COUNT(*) FROM information_schema.check_constraints WHERE constraint_schema = %s "
                   "AND constraint_name = 'ck_usuario_nome'", (nome,))
    if cursor.fetchone()[0] == 0:
        cursor.execute("ALTER TABLE usuario ADD CONSTRAINT ck_usuario_nome "
                       "CHECK (REGEXP_LIKE(nome, '^[A-Z0-9 ]+$', 'c'))")
        print("  migração: usuario.nome passa a exigir o padrão (CHECK)")
    raiz.commit()


# Perfis: um perfil por cadastro, com a camada coerente. NULL-safe (<=>): um CHECK do MySQL
# aceita quando a expressão dá NULL, e `nivel = 1` com nivel NULL daria NULL.
CHECKS_PERFIL = {
    "ck_usuario_perfil_nivel": "CHECK ((perfil = 'SERVIDOR' AND nivel <=> 1) OR (perfil = 'DIRETOR' AND nivel <=> 2) "
                               "OR (perfil = 'MINISTRO' AND nivel <=> 3) OR (perfil = 'EXTERNO' AND nivel IS NULL))",
    "ck_usuario_uf_perfil": "CHECK ((perfil = 'DIRETOR') = (uf IS NOT NULL))",
    "ck_usuario_excluido": "CHECK (excluido_em IS NULL OR NOT ativo)",
}


# perfis da primeira versão que deixaram de existir: viram EXTERNO (sem camada; o papel de administrador
# continua na tabela administrador)
PERFIS_RETIRADOS = ("ADMINISTRADOR", "SEM_PERFIL", "MINISTERIO_PUBLICO")


def _check_existe(cursor, banco: str, nome: str) -> bool:
    cursor.execute("SELECT COUNT(*) FROM information_schema.check_constraints WHERE constraint_schema = %s "
                   "AND constraint_name = %s", (banco, nome))
    return cursor.fetchone()[0] > 0


def migrar_perfis(cursor, banco: str) -> None:
    """Leva o banco de segurança ao modelo de perfis, de antes dela (só níveis) ou da sua
    primeira versão (com os perfis Administrador, Sem perfil e Ministério Público). Idempotente: cada passo confere
    antes. Cada um recebe o perfil do nível (1 servidor, 2 diretor, 3 ministro); quem tem o papel de administrador
    ativo vira EXTERNO e perde a camada (o administrador não tem acesso a dados). Os perfis retirados viram
    EXTERNO, sem camada. A UF fica só com o diretor. A trilha e os consentimentos não são tocados (são prova)."""
    cursor.execute(f"USE `{banco}`")
    if not _coluna_existe(cursor, banco, "usuario", "excluido_em"):
        cursor.execute("ALTER TABLE usuario ADD COLUMN excluido_em DATETIME(6) NULL AFTER criado_em")
        print("  migração: usuario.excluido_em acrescentada (exclusão lógica)")
    cursor.execute("SELECT is_nullable FROM information_schema.columns WHERE table_schema = %s "
                   "AND table_name = 'usuario' AND column_name = 'nivel'", (banco,))
    if cursor.fetchone()[0] != "YES":
        cursor.execute("ALTER TABLE usuario MODIFY nivel TINYINT NULL")
        print("  migração: usuario.nivel passa a aceitar NULL (administrador e sem perfil)")
    if not _coluna_existe(cursor, banco, "usuario", "perfil"):
        cursor.execute("ALTER TABLE usuario ADD COLUMN perfil VARCHAR(20) NOT NULL DEFAULT 'EXTERNO' AFTER nivel")
        cursor.execute("UPDATE usuario SET perfil = CASE nivel WHEN 1 THEN 'SERVIDOR' WHEN 2 THEN 'DIRETOR' "
                       "WHEN 3 THEN 'MINISTRO' ELSE 'EXTERNO' END")
        cursor.execute("UPDATE usuario u JOIN administrador a ON a.usuario_id = u.id AND a.ativo "
                       "SET u.perfil = 'EXTERNO', u.nivel = NULL, u.uf = NULL")
        cursor.execute("UPDATE usuario SET uf = NULL WHERE perfil <> 'DIRETOR'")
        cursor.execute("ALTER TABLE usuario ALTER COLUMN perfil DROP DEFAULT")
        print("  migração: usuario.perfil acrescentada; administradores passam a Externo, sem camada")
    # primeira versão: o CHECK antigo recusaria o EXTERNO, então sai antes de os perfis retirados mudarem
    cursor.execute("SELECT check_clause FROM information_schema.check_constraints WHERE constraint_schema = %s "
                   "AND constraint_name = 'ck_usuario_perfil_nivel'", (banco,))
    clausula = cursor.fetchone()
    if clausula is not None and any(p in clausula[0] for p in PERFIS_RETIRADOS):
        cursor.execute("ALTER TABLE usuario DROP CHECK ck_usuario_perfil_nivel")
        marcas = ", ".join(["%s"] * len(PERFIS_RETIRADOS))
        cursor.execute(f"UPDATE usuario SET perfil = 'EXTERNO', nivel = NULL, uf = NULL WHERE perfil IN ({marcas})",
                       PERFIS_RETIRADOS)
        print(f"  migração: perfis retirados (Administrador, Sem perfil, Ministério Público) passam a Externo "
              f"({cursor.rowcount} cadastros)")
    for nome, regra in CHECKS_PERFIL.items():
        if not _check_existe(cursor, banco, nome):
            cursor.execute(f"ALTER TABLE usuario ADD CONSTRAINT {nome} {regra}")
            print(f"  migração: {nome} (CHECK)")


def preparar(root_senha: str, recriar_acervo: bool = False) -> None:
    cfg = carregar()
    b = _secao_banco(cfg)
    print(f"Conectando como root em {b['host']}:{b['porta']}…")
    raiz = conectar_direto(b["host"], b["porta"], "root", root_senha)
    cursor = raiz.cursor()
    try:
        _recriar_acervo(raiz, cursor, b["acervo"], recriar_acervo)
        # ---------------------------------------------------------------- bancos e tabelas
        for qual in ("seguranca", "acervo"):
            nome = b[qual]
            _executar(cursor, f"CREATE DATABASE IF NOT EXISTS `{nome}` "
                              "CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci")
            raiz.database = nome
            print(f"  {nome}: {executar_scripts(raiz, qual)} comandos executados")
            for banco_migracao, tabela, coluna, ddl in MIGRACOES:
                if banco_migracao != qual:
                    continue
                if not _coluna_existe(cursor, nome, tabela, coluna):
                    cursor.execute(f"USE `{nome}`")
                    cursor.execute(ddl)
                    print(f"  migração: {tabela}.{coluna} acrescentada")
            if qual == "seguranca":
                migrar_perfis(cursor, nome)

        _padronizar_seguranca(raiz, cursor, b["seguranca"])

        # ---------------------------------------------------------------- acervo
        raiz.database = b["acervo"]
        pendencias, responsaveis = importar_acervo(raiz)
        print(f"  acervo: {pendencias} pendências e {responsaveis} responsáveis importados"
              if pendencias else "  acervo: já estava importado (nada alterado)")
        from ecosec.acervo.desenho import Fontes
        print(f"  acervo: {inventariar_regioes(raiz, Fontes.de_configuracao(cfg))} regiões sensíveis inventariadas")
        conferir_ciclo_de_vida(cursor)
        conferir_volume(cursor)

        # ---------------------------------------------------------------- contas
        seg_usuario, seg_senha = "ecosec_seg", _senha_da_conta(segredos.DB_SEGURANCA_SENHA)
        cofre_usuario, cofre_senha = "ecosec_cofre", _senha_da_conta(segredos.DB_ACERVO_SENHA)
        teste_usuario, teste_senha = "ecosec_teste", _senha_da_conta(segredos.DB_TESTE_SENHA)
        for usuario, senha in ((seg_usuario, seg_senha), (cofre_usuario, cofre_senha),
                               (teste_usuario, teste_senha)):
            _conta(cursor, usuario, senha)
        padrao_teste = b["prefixo_teste"].replace("_", "\\_") + "%"
        for host in HOSTS:
            for tabela, privilegios in PRIVILEGIOS_SEGURANCA.items():
                _executar(cursor, f"GRANT {privilegios} ON `{b['seguranca']}`.`{tabela}` TO %s@%s",
                          (seg_usuario, host))
            _executar(cursor, f"GRANT SELECT ON `{b['acervo']}`.* TO %s@%s", (cofre_usuario, host))
            _executar(cursor, f"GRANT ALL PRIVILEGES ON `{padrao_teste}`.* TO %s@%s", (teste_usuario, host))
        raiz.commit()
        print("  contas ecosec_seg, ecosec_cofre e ecosec_teste prontas")
    finally:
        cursor.close()
        raiz.close()

    # ---------------------------------------------------------------- .env
    for chave, valor in ((segredos.DB_SEGURANCA_USUARIO, seg_usuario), (segredos.DB_SEGURANCA_SENHA, seg_senha),
                         (segredos.DB_ACERVO_USUARIO, cofre_usuario), (segredos.DB_ACERVO_SENHA, cofre_senha),
                         (segredos.DB_TESTE_USUARIO, teste_usuario), (segredos.DB_TESTE_SENHA, teste_senha)):
        segredos.gravar(chave, valor)
    segredos.garantir_chave_cifragem()
    print("  credenciais das contas e chave de cifragem gravadas no .env")
    verificar_privilegios()


SQL_VOLUME = ("SELECT p.codigo, a.codigo AS atividade, p.classe_risco, p.quantidade, p.unidade FROM pendencia p "
              "JOIN atividade_geradora a ON a.id = p.atividade_id WHERE p.sintetico = TRUE")


def incoerencias_de_volume(linhas) -> list[str]:
    """Pendências geradas fora da faixa do par (atividade, classe) ou com unidade trocada."""
    from ecosec.acervo import sinteticos
    erradas = []
    for codigo, atividade, classe, quantidade, unidade in linhas:
        faixa = sinteticos.QUANTIDADE_POR_PAR.get((atividade, classe))
        esperada = sinteticos.UNIDADE_DA_CLASSE.get(classe)
        if faixa is None or unidade != esperada or not faixa[2] <= float(quantidade) <= faixa[3]:
            erradas.append(codigo)
    return erradas


def conferir_volume(cursor) -> bool:
    cursor.execute(SQL_VOLUME)
    erradas = incoerencias_de_volume(cursor.fetchall())
    print(f"  acervo: volume {'coerente com atividade e classe' if not erradas else 'INCOERENTE em ' + ', '.join(erradas[:5])}")
    return not erradas


def conferir_ciclo_de_vida(cursor) -> bool:
    """Encerrada <=> etapa final com a mesma data; e o estoque ativo cai em pelo menos um ano."""
    cursor.execute(SQL_CONSISTENCIA)
    incoerentes = [l[0] for l in cursor.fetchall()]
    cursor.execute(SQL_QUEDAS)
    quedas = [l[0] for l in cursor.fetchall()]
    print(f"  acervo: ciclo de vida {'coerente' if not incoerentes else 'INCOERENTE em ' + ', '.join(incoerentes[:5])}"
          f"; estoque ativo cai em {', '.join(map(str, quedas)) if quedas else 'NENHUM ano (curva monotônica!)'}")
    return not incoerentes and bool(quedas)


def verificar_privilegios() -> bool:
    """Prova, contra o banco real, que as contas não podem o que não devem.
    Cada tentativa é inofensiva (WHERE 1 = 0): o que se testa é a permissão."""
    cfg = carregar()
    b = _secao_banco(cfg)
    print("\nVerificando privilégios (cada linha DEVE ser recusada pelo banco):")
    casos = [
        (segredos.DB_SEGURANCA_USUARIO, segredos.DB_SEGURANCA_SENHA, b["seguranca"],
         "DELETE FROM usuario WHERE 1 = 0", "ecosec_seg apagar usuário"),
        (segredos.DB_SEGURANCA_USUARIO, segredos.DB_SEGURANCA_SENHA, b["seguranca"],
         "DELETE FROM consentimento WHERE 1 = 0", "ecosec_seg apagar consentimento"),
        (segredos.DB_SEGURANCA_USUARIO, segredos.DB_SEGURANCA_SENHA, b["seguranca"],
         "DROP TABLE amostra", "ecosec_seg destruir tabela"),
        (segredos.DB_SEGURANCA_USUARIO, segredos.DB_SEGURANCA_SENHA, b["seguranca"],
         "UPDATE log_acesso SET motivo = 'X' WHERE 1 = 0", "ecosec_seg reescrever a trilha"),
        (segredos.DB_SEGURANCA_USUARIO, segredos.DB_SEGURANCA_SENHA, b["seguranca"],
         "DELETE FROM log_acesso WHERE 1 = 0", "ecosec_seg apagar a trilha"),
        (segredos.DB_SEGURANCA_USUARIO, segredos.DB_SEGURANCA_SENHA, b["seguranca"],
         "DELETE FROM administrador WHERE 1 = 0", "ecosec_seg apagar um administrador"),
        (segredos.DB_SEGURANCA_USUARIO, segredos.DB_SEGURANCA_SENHA, b["seguranca"],
         "DELETE FROM codigo_recuperacao WHERE 1 = 0", "ecosec_seg apagar código de recuperação"),
        (segredos.DB_SEGURANCA_USUARIO, segredos.DB_SEGURANCA_SENHA, b["acervo"],
         "SELECT 1 FROM pendencia LIMIT 1", "ecosec_seg ler o acervo"),
        (segredos.DB_ACERVO_USUARIO, segredos.DB_ACERVO_SENHA, b["acervo"],
         "DELETE FROM pendencia WHERE 1 = 0", "ecosec_cofre alterar o acervo"),
        (segredos.DB_ACERVO_USUARIO, segredos.DB_ACERVO_SENHA, b["seguranca"],
         "SELECT 1 FROM usuario LIMIT 1", "ecosec_cofre ler usuários"),
    ]
    tudo_certo = True
    for chave_usuario, chave_senha, banco, sql, descricao in casos:
        try:
            conexao = conectar_direto(b["host"], b["porta"], segredos.ler(chave_usuario),
                                      segredos.ler(chave_senha), banco)
            try:
                cursor = conexao.cursor()
                cursor.execute(sql)
                if cursor.with_rows:
                    cursor.fetchall()
                print(f"  [FALHA] {descricao}: o banco PERMITIU")
                tudo_certo = False
            finally:
                conexao.close()
        except ErroRepositorio:
            print(f"  [ OK ] {descricao}: recusado")
        except Exception as erro:  # noqa: BLE001, erro do driver = recusa do banco
            print(f"  [ OK ] {descricao}: recusado ({getattr(erro, 'errno', '')})")
    return tudo_certo


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0].strip())
    parser.add_argument("--recriar-acervo", action="store_true",
                        help="apaga e recria o banco do acervo a partir do gerador (após mudar sinteticos.py)")
    args = parser.parse_args()
    print(__doc__.split("\n\n")[0].strip(), "\n")
    try:
        senha = getpass.getpass("Senha do root do MySQL (não aparece ao digitar): ")
        preparar(senha, recriar_acervo=args.recriar_acervo)
    except (ErroRepositorio, segredos.ErroSegredo) as erro:
        print(f"\n[FALHA] {erro}")
        sys.exit(1)
    print("\nPronto. Abra o EcoSecurity com:  .venv\\Scripts\\python.exe -m ecosec")


if __name__ == "__main__":
    main()
