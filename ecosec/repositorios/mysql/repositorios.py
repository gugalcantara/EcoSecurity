"""Repositórios MySQL: cumprem OS mesmos contratos da versão em memória.

As duas implementações precisam se comportar igual em toda regra (matrícula
duplicada, revogação, normalização): os serviços não sabem qual estão usando.

Todo SQL usa parâmetros (%s), nunca concatenação de texto. Com concatenação, uma
matrícula digitada como  ' OR '1'='1  viraria parte do comando (injeção de
SQL). Com parâmetros, o driver envia o valor separado do comando, e ele é
sempre tratado como dado.
"""
from datetime import datetime

from mysql.connector import errorcode

from ecosec.dominio.entidades import (Administrador, Amostra, CodigoRecuperacao, Consentimento, EventoTrilha,
                                     RegistroTentativas, RegistroTrilha, Usuario)
from ecosec.dominio.niveis import Nivel
from ecosec.dominio.perfis import Perfil
from ecosec.repositorios.contratos import (BancoIndisponivel, ErroRepositorio, MatriculaDuplicada,
                                          RegistroInexistente)
from ecosec.repositorios.mysql.conexao import BancoMySQL


def _normalizar(matricula: str) -> str:
    return matricula.strip().upper()


def _usuario(linha: dict | None) -> Usuario | None:
    if linha is None:
        return None
    nivel = Nivel(linha["nivel"]) if linha["nivel"] is not None else None
    return Usuario(matricula=linha["matricula"], nome=linha["nome"], nivel=nivel, perfil=Perfil(linha["perfil"]),
                   senha_hash=linha["senha_hash"], uf=linha["uf"], ativo=bool(linha["ativo"]),
                   id=linha["id"], criado_em=linha["criado_em"], excluido_em=linha["excluido_em"])


def _nivel(u: Usuario) -> int | None:
    return int(u.nivel) if u.nivel is not None else None


class RepositorioUsuariosMySQL:
    _CAMPOS = "id, matricula, nome, nivel, perfil, uf, senha_hash, ativo, criado_em, excluido_em"

    def __init__(self, banco: BancoMySQL, relogio=datetime.now):
        self.banco, self.relogio = banco, relogio

    def adicionar(self, u: Usuario) -> Usuario:
        matricula, criado_em = _normalizar(u.matricula), self.relogio()
        try:
            with self.banco.transacao() as c:
                c.execute("INSERT INTO usuario (matricula, nome, nivel, perfil, uf, senha_hash, ativo, criado_em, "
                          "excluido_em) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                          (matricula, u.nome, _nivel(u), u.perfil.value, u.uf, u.senha_hash, u.ativo, criado_em,
                           u.excluido_em))
                novo_id = c.lastrowid
        except ErroRepositorio as erro:
            if getattr(erro.__cause__, "errno", None) == errorcode.ER_DUP_ENTRY:
                raise MatriculaDuplicada(f"Matrícula {matricula} já cadastrada.") from None
            raise
        return self.por_id(novo_id)

    def por_id(self, usuario_id: int) -> Usuario | None:
        with self.banco.transacao() as c:
            c.execute(f"SELECT {self._CAMPOS} FROM usuario WHERE id = %s", (usuario_id,))
            return _usuario(c.fetchone())

    def por_matricula(self, matricula: str) -> Usuario | None:
        with self.banco.transacao() as c:
            c.execute(f"SELECT {self._CAMPOS} FROM usuario WHERE matricula = %s", (_normalizar(matricula),))
            return _usuario(c.fetchone())

    def listar(self) -> list[Usuario]:
        with self.banco.transacao() as c:
            c.execute(f"SELECT {self._CAMPOS} FROM usuario ORDER BY id")
            return [_usuario(linha) for linha in c.fetchall()]

    def atualizar(self, u: Usuario) -> None:
        # matrícula e criação ficam de fora do SET: são fixas, como no contrato
        with self.banco.transacao() as c:
            c.execute("UPDATE usuario SET nome = %s, nivel = %s, perfil = %s, uf = %s, senha_hash = %s, ativo = %s, "
                      "excluido_em = %s WHERE id = %s",
                      (u.nome, _nivel(u), u.perfil.value, u.uf, u.senha_hash, u.ativo, u.excluido_em, u.id))
            if c.rowcount == 0:
                raise RegistroInexistente(f"Usuário {u.id} não existe.")


class RepositorioTentativasMySQL:
    def __init__(self, banco: BancoMySQL):
        self.banco = banco

    def obter(self, matricula: str) -> RegistroTentativas | None:
        with self.banco.transacao() as c:
            c.execute("SELECT matricula, falhas, bloqueado_ate FROM tentativa WHERE matricula = %s",
                      (_normalizar(matricula),))
            linha = c.fetchone()
        return RegistroTentativas(linha["matricula"], linha["falhas"], linha["bloqueado_ate"]) if linha else None

    def salvar(self, r: RegistroTentativas) -> None:
        with self.banco.transacao() as c:
            c.execute("INSERT INTO tentativa (matricula, falhas, bloqueado_ate) VALUES (%s, %s, %s) AS novo "
                      "ON DUPLICATE KEY UPDATE falhas = novo.falhas, bloqueado_ate = novo.bloqueado_ate",
                      (_normalizar(r.matricula), r.falhas, r.bloqueado_ate))

    def bloqueadas(self, agora: datetime) -> list[RegistroTentativas]:
        with self.banco.transacao() as c:
            c.execute("SELECT matricula, falhas, bloqueado_ate FROM tentativa WHERE bloqueado_ate > %s "
                      "ORDER BY bloqueado_ate", (agora,))
            return [RegistroTentativas(l["matricula"], l["falhas"], l["bloqueado_ate"]) for l in c.fetchall()]


class RepositorioEstacoesMySQL:
    def __init__(self, banco: BancoMySQL):
        self.banco = banco

    def conhecidas(self, usuario_id: int) -> set[str]:
        with self.banco.transacao() as c:
            c.execute("SELECT impressao FROM estacao WHERE usuario_id = %s", (usuario_id,))
            return {l["impressao"] for l in c.fetchall()}

    def registrar(self, usuario_id: int, impressao: str, momento: datetime) -> None:
        with self.banco.transacao() as c:
            c.execute("INSERT INTO estacao (usuario_id, impressao, primeiro_uso, ultimo_uso) VALUES (%s, %s, %s, %s) "
                      "AS novo ON DUPLICATE KEY UPDATE ultimo_uso = novo.ultimo_uso",
                      (usuario_id, impressao, momento, momento))


def _administrador(l: dict | None) -> Administrador | None:
    if l is None:
        return None
    return Administrador(usuario_id=l["usuario_id"], designado_em=l["designado_em"], designado_por=l["designado_por"],
                         aprovado_por=l["aprovado_por"], segredo_totp=l["segredo_totp"],
                         ultimo_passo=l["ultimo_passo"], ativo=bool(l["ativo"]), removido_em=l["removido_em"])


class RepositorioAdministradoresMySQL:
    _CAMPOS = ("usuario_id, designado_em, designado_por, aprovado_por, segredo_totp, ultimo_passo, ativo, "
               "removido_em")

    def __init__(self, banco: BancoMySQL):
        self.banco = banco

    def listar(self) -> list[Administrador]:
        with self.banco.transacao() as c:
            c.execute(f"SELECT {self._CAMPOS} FROM administrador ORDER BY designado_em, usuario_id")
            return [_administrador(l) for l in c.fetchall()]

    def obter(self, usuario_id: int) -> Administrador | None:
        with self.banco.transacao() as c:
            c.execute(f"SELECT {self._CAMPOS} FROM administrador WHERE usuario_id = %s", (usuario_id,))
            return _administrador(c.fetchone())

    def salvar(self, a: Administrador) -> None:
        with self.banco.transacao() as c:
            c.execute(f"INSERT INTO administrador ({self._CAMPOS}) VALUES (%s, %s, %s, %s, %s, %s, %s, %s) AS novo "
                      "ON DUPLICATE KEY UPDATE designado_em = novo.designado_em, designado_por = novo.designado_por, "
                      "aprovado_por = novo.aprovado_por, segredo_totp = novo.segredo_totp, "
                      "ultimo_passo = novo.ultimo_passo, ativo = novo.ativo, removido_em = novo.removido_em",
                      (a.usuario_id, a.designado_em, a.designado_por, a.aprovado_por, a.segredo_totp, a.ultimo_passo,
                       a.ativo, a.removido_em))

    def registrar_passo(self, usuario_id: int, passo: int) -> bool:
        # a condição no WHERE faz a comparação e a gravação numa operação só: dois
        # computadores aceitando o mesmo código ao mesmo tempo, só um consegue
        with self.banco.transacao() as c:
            c.execute("UPDATE administrador SET ultimo_passo = %s WHERE usuario_id = %s "
                      "AND (ultimo_passo IS NULL OR ultimo_passo < %s)", (passo, usuario_id, passo))
            return c.rowcount > 0

    def trocar_codigos(self, usuario_id: int, hashes: list[str], momento: datetime) -> None:
        with self.banco.transacao() as c:                     # todos ou nenhum
            c.execute("UPDATE codigo_recuperacao SET usado_em = %s WHERE usuario_id = %s AND usado_em IS NULL",
                      (momento, usuario_id))
            if hashes:
                c.executemany("INSERT INTO codigo_recuperacao (usuario_id, hash_codigo, criado_em) VALUES (%s, %s, %s)",
                              [(usuario_id, h, momento) for h in hashes])

    def codigos_validos(self, usuario_id: int) -> list[CodigoRecuperacao]:
        with self.banco.transacao() as c:
            c.execute("SELECT id, usuario_id, hash_codigo, criado_em, usado_em FROM codigo_recuperacao "
                      "WHERE usuario_id = %s AND usado_em IS NULL ORDER BY id", (usuario_id,))
            return [CodigoRecuperacao(l["usuario_id"], l["hash_codigo"], l["criado_em"], l["usado_em"], l["id"])
                    for l in c.fetchall()]

    def usar_codigo(self, codigo_id: int, momento: datetime) -> bool:
        with self.banco.transacao() as c:
            c.execute("UPDATE codigo_recuperacao SET usado_em = %s WHERE id = %s AND usado_em IS NULL",
                      (momento, codigo_id))
            return c.rowcount > 0


def _consentimento(linha: dict | None) -> Consentimento | None:
    if linha is None:
        return None
    return Consentimento(titular_nome=linha["titular_nome"], versao_termo=linha["versao_termo"],
                         hash_termo=linha["hash_termo"], momento=linha["momento"],
                         usuario_id=linha["usuario_id"], revogado_em=linha["revogado_em"], id=linha["id"],
                         autoriza_pesquisa=bool(linha["autoriza_pesquisa"]))


class RepositorioConsentimentosMySQL:
    _CAMPOS = "id, usuario_id, titular_nome, versao_termo, hash_termo, momento, revogado_em, autoriza_pesquisa"

    def __init__(self, banco: BancoMySQL):
        self.banco = banco

    def registrar(self, t: Consentimento) -> Consentimento:
        with self.banco.transacao() as c:
            c.execute("INSERT INTO consentimento (usuario_id, titular_nome, versao_termo, hash_termo, momento, "
                      "autoriza_pesquisa) VALUES (%s, %s, %s, %s, %s, %s)",
                      (t.usuario_id, t.titular_nome, t.versao_termo, t.hash_termo, t.momento, t.autoriza_pesquisa))
            novo_id = c.lastrowid
        with self.banco.transacao() as c:
            c.execute(f"SELECT {self._CAMPOS} FROM consentimento WHERE id = %s", (novo_id,))
            return _consentimento(c.fetchone())

    def vincular(self, consentimento_id: int, usuario_id: int) -> None:
        with self.banco.transacao() as c:
            c.execute("UPDATE consentimento SET usuario_id = %s WHERE id = %s", (usuario_id, consentimento_id))
            if c.rowcount == 0:
                raise RegistroInexistente(f"Consentimento {consentimento_id} não existe.")

    def vigente_de(self, usuario_id: int) -> Consentimento | None:
        with self.banco.transacao() as c:
            c.execute(f"SELECT {self._CAMPOS} FROM consentimento WHERE usuario_id = %s AND revogado_em IS NULL "
                      "ORDER BY momento DESC LIMIT 1", (usuario_id,))
            return _consentimento(c.fetchone())

    def de_usuario(self, usuario_id: int) -> list[Consentimento]:
        with self.banco.transacao() as c:
            c.execute(f"SELECT {self._CAMPOS} FROM consentimento WHERE usuario_id = %s ORDER BY momento, id",
                      (usuario_id,))
            return [_consentimento(linha) for linha in c.fetchall()]

    def revogar(self, usuario_id: int, momento: datetime) -> bool:
        with self.banco.transacao() as c:
            c.execute("UPDATE consentimento SET revogado_em = %s WHERE usuario_id = %s AND revogado_em IS NULL",
                      (momento, usuario_id))
            return c.rowcount > 0


class RepositorioAmostrasMySQL:
    def __init__(self, banco: BancoMySQL, relogio=datetime.now):
        self.banco, self.relogio = banco, relogio

    def registrar(self, amostras: list[Amostra]) -> None:
        if not amostras:
            return
        agora = self.relogio()
        with self.banco.transacao() as c:          # todas ou nenhuma
            c.executemany("INSERT INTO amostra (usuario_id, sessao, origem, qualidade, criada_em) "
                          "VALUES (%s, %s, %s, %s, %s)",
                          [(a.usuario_id, a.sessao, a.origem, round(a.qualidade, 4), agora) for a in amostras])

    def por_usuario(self, usuario_id: int) -> list[Amostra]:
        with self.banco.transacao() as c:
            c.execute("SELECT id, usuario_id, sessao, origem, qualidade, criada_em FROM amostra "
                      "WHERE usuario_id = %s ORDER BY id", (usuario_id,))
            return [Amostra(l["usuario_id"], l["sessao"], l["origem"], float(l["qualidade"]),
                            id=l["id"], criada_em=l["criada_em"]) for l in c.fetchall()]


def _registro_trilha(l: dict) -> RegistroTrilha:
    return RegistroTrilha(
        EventoTrilha(momento=l["momento"], evento=l["evento"], resultado=l["resultado"], motivo=l["motivo"],
                     camadas=l["camadas"], nivel_solicitado=l["nivel_solicitado"], usuario_id=l["usuario_id"],
                     usuario2_id=l["usuario2_id"], matricula_informada=l["matricula_informada"],
                     distancia=None if l["distancia"] is None else float(l["distancia"]), detalhe=l["detalhe"]),
        l["hash_anterior"], l["hash_registro"], l["id"])


class RepositorioTrilhaMySQL:
    """Trava com GET_LOCK: não exige UPDATE (que a conta da aplicação não tem
    na trilha) e serializa as gravações entre processos e threads.

    O commit acontece ANTES de soltar a trava. Na ordem inversa, outra gravação
    poderia ler o último hash ainda antigo e a corrente se bifurcaria.
    """
    _CAMPOS = ("id, momento, evento, nivel_solicitado, usuario_id, usuario2_id, matricula_informada, "
               "resultado, motivo, camadas, distancia, detalhe, hash_anterior, hash_registro")

    def __init__(self, banco: BancoMySQL, espera_trava: int = 5):
        self.banco, self.espera = banco, espera_trava
        self._trava = f"ecosec_trilha_{banco.p.banco}"           # uma por banco (testes x real)

    def acrescentar(self, montar) -> RegistroTrilha:
        with self.banco.transacao() as c:
            c.execute("SELECT GET_LOCK(%s, %s) AS ok", (self._trava, self.espera))
            if not c.fetchone()["ok"]:
                raise BancoIndisponivel("A trilha está ocupada; tente de novo.")
            try:
                c.execute("SELECT hash_registro FROM log_acesso ORDER BY id DESC LIMIT 1")
                ultimo = c.fetchone()
                r = montar(ultimo["hash_registro"] if ultimo else None)
                ev = r.evento
                c.execute("INSERT INTO log_acesso (momento, evento, nivel_solicitado, usuario_id, usuario2_id, "
                          "matricula_informada, resultado, motivo, camadas, distancia, detalhe, hash_anterior, "
                          "hash_registro) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                          (ev.momento, ev.evento, ev.nivel_solicitado, ev.usuario_id, ev.usuario2_id,
                           ev.matricula_informada, ev.resultado, ev.motivo, ev.camadas, ev.distancia, ev.detalhe,
                           r.hash_anterior, r.hash_registro))
                novo_id = c.lastrowid
                c.execute("COMMIT")                              # grava ANTES de soltar a trava
            finally:
                c.execute("SELECT RELEASE_LOCK(%s)", (self._trava,))
                c.fetchall()
        return RegistroTrilha(r.evento, r.hash_anterior, r.hash_registro, novo_id)

    def todos(self) -> list[RegistroTrilha]:
        with self.banco.transacao() as c:
            c.execute(f"SELECT {self._CAMPOS} FROM log_acesso ORDER BY id")
            return [_registro_trilha(l) for l in c.fetchall()]

    def recentes(self, limite: int) -> list[RegistroTrilha]:
        with self.banco.transacao() as c:
            c.execute(f"SELECT {self._CAMPOS} FROM log_acesso ORDER BY id DESC LIMIT %s", (int(limite),))
            return [_registro_trilha(l) for l in c.fetchall()]


class RepositorioAcervoMySQL:
    """Lê o banco do acervo com a conta ecosec_cofre, que SÓ tem SELECT."""

    def __init__(self, banco: BancoMySQL):
        self.banco = banco

    def catalogo(self):
        from ecosec.dominio.acervo import RelatorioCatalogo
        with self.banco.transacao() as c:
            c.execute("SELECT codigo, titulo, nivel_minimo, sintetico FROM item_acervo "
                      "WHERE tipo = 'RELATORIO' ORDER BY codigo")
            linhas = c.fetchall()
        from ecosec.acervo.sinteticos import CATALOGO   # descrições; o banco manda no que existe e no nível
        descricoes = {r.codigo: r.descricao for r in CATALOGO}
        return [RelatorioCatalogo(l["codigo"], l["titulo"], l["nivel_minimo"], descricoes.get(l["codigo"], ""),
                                  bool(l["sintetico"])) for l in linhas]

    def atividades(self):
        from ecosec.dominio.acervo import AtividadeGeradora
        with self.banco.transacao() as c:
            c.execute("SELECT codigo, nome, descricao_operacional, cnae_subclasse, exemplos, observacao "
                      "FROM atividade_geradora ORDER BY codigo")
            return [AtividadeGeradora(**l) for l in c.fetchall()]

    def motivos(self):
        from ecosec.dominio.acervo import MotivoPermanencia
        with self.banco.transacao() as c:
            c.execute("SELECT codigo, nome, descricao_operacional, base_legal, grupo, acao_institucional "
                      "FROM motivo_permanencia ORDER BY codigo")
            return [MotivoPermanencia(**l) for l in c.fetchall()]

    def eventos(self):
        from ecosec.dominio.acervo import EventoRegulatorio
        with self.banco.transacao() as c:
            c.execute("SELECT data_evento, rotulo, descricao, classes, efeito, base_legal, verificacao "
                      "FROM evento_regulatorio ORDER BY data_evento")
            return [EventoRegulatorio(**{**l, "classes": tuple(sorted(l["classes"]))
                                         if isinstance(l["classes"], set) else tuple(l["classes"].split(","))})
                    for l in c.fetchall()]

    _PENDENCIA = ("SELECT p.codigo, p.substancia, p.classe_risco, p.quantidade, p.unidade, p.uf, p.municipio, "
                  "p.logradouro, p.numero, p.complemento, p.bairro, p.cep, p.latitude, p.longitude, "
                  "p.data_identificacao, p.prazo_coleta, p.situacao, p.data_encerramento, p.etapa_atual, "
                  "a.codigo AS atividade, "
                  "m.codigo AS motivo, p.sintetico, p.fonte FROM pendencia p "
                  "JOIN atividade_geradora a ON a.id = p.atividade_id "
                  "JOIN motivo_permanencia m ON m.id = p.motivo_id")

    def pendencias(self, uf=None):
        from collections import defaultdict

        from ecosec.dominio.acervo import Pendencia
        filtro, parametros = ("", ()) if uf is None else (" WHERE p.uf = %s", (uf,))
        with self.banco.transacao() as c:
            c.execute(self._PENDENCIA + filtro + " ORDER BY p.codigo", parametros)
            linhas = c.fetchall()
            c.execute("SELECT p.codigo, e.nome, e.data_etapa FROM etapa_gerenciamento e "
                      "JOIN pendencia p ON p.id = e.pendencia_id" + filtro + " ORDER BY p.codigo, e.ordem", parametros)
            etapas = defaultdict(list)
            for l in c.fetchall():
                etapas[l["codigo"]].append((l["nome"], l["data_etapa"]))
        return [Pendencia(**{**l, "quantidade": float(l["quantidade"]), "latitude": float(l["latitude"]),
                             "longitude": float(l["longitude"]), "sintetico": bool(l["sintetico"]),
                             "etapas": tuple(etapas.get(l["codigo"], ()))})
                for l in linhas]

    def responsaveis(self, nivel, uf=None):
        from ecosec.dominio.acervo import Responsavel
        sql = ("SELECT p.codigo AS pendencia_codigo, r.nome, r.vinculo, r.situacao_cadastral, r.nivel_minimo "
               "FROM responsavel r JOIN pendencia p ON p.id = r.pendencia_id "
               "WHERE r.nivel_minimo <= %s")          # RF-21: o filtro do nível está NA CONSULTA
        parametros = [int(nivel)]
        if uf is not None:
            sql += " AND p.uf = %s"
            parametros.append(uf)
        with self.banco.transacao() as c:
            c.execute(sql + " ORDER BY p.codigo, r.id", tuple(parametros))
            return [Responsavel(**l) for l in c.fetchall()]
