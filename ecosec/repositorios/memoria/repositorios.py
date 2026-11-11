"""Repositórios em memória: cumprem os contratos com dicionários.

Servem ao desenvolvimento (interface e regras antes do banco) e aos testes.
Os dados somem ao fechar o programa; é o comportamento esperado aqui.

O Lock existe porque a captura de vídeo roda em outra thread: duas threads
gravando no mesmo dicionário ao mesmo tempo poderiam gerar ids repetidos.
"""
import dataclasses
import itertools
import threading
from datetime import datetime

from ecosec.dominio.entidades import (MATRICULA_MAX, Administrador, Amostra, CodigoRecuperacao, Consentimento,
                                     RegistroTentativas, RegistroTrilha, Usuario)
from ecosec.repositorios.contratos import ErroRepositorio, MatriculaDuplicada, RegistroInexistente


def _normalizar(matricula: str) -> str:
    return matricula.strip().upper()


class RepositorioUsuariosMemoria:
    def __init__(self, relogio=datetime.now):
        self._por_id: dict[int, Usuario] = {}
        self._ids = itertools.count(1)
        self._lock = threading.Lock()
        self._relogio = relogio

    def adicionar(self, usuario: Usuario) -> Usuario:
        with self._lock:
            if self._buscar_matricula(usuario.matricula):
                raise MatriculaDuplicada(f"Matrícula {usuario.matricula} já cadastrada.")
            gravado = dataclasses.replace(usuario, id=next(self._ids),
                                          matricula=_normalizar(usuario.matricula),
                                          criado_em=self._relogio())
            self._por_id[gravado.id] = gravado
            return gravado

    def por_id(self, usuario_id: int) -> Usuario | None:
        return self._por_id.get(usuario_id)

    def por_matricula(self, matricula: str) -> Usuario | None:
        return self._buscar_matricula(matricula)

    def listar(self) -> list[Usuario]:
        return sorted(self._por_id.values(), key=lambda u: u.id)

    def atualizar(self, usuario: Usuario) -> None:
        with self._lock:
            atual = self._por_id.get(usuario.id)
            if atual is None:
                raise RegistroInexistente(f"Usuário {usuario.id} não existe.")
            # matrícula e data de criação são fixas: preserva as originais
            self._por_id[usuario.id] = dataclasses.replace(
                usuario, matricula=atual.matricula, criado_em=atual.criado_em)

    def _buscar_matricula(self, matricula: str) -> Usuario | None:
        alvo = _normalizar(matricula)
        return next((u for u in self._por_id.values() if u.matricula == alvo), None)


class RepositorioTentativasMemoria:
    def __init__(self):
        self._registros: dict[str, RegistroTentativas] = {}
        self._lock = threading.Lock()

    def obter(self, matricula: str) -> RegistroTentativas | None:
        return self._registros.get(_normalizar(matricula))

    def salvar(self, registro: RegistroTentativas) -> None:
        if len(_normalizar(registro.matricula)) > MATRICULA_MAX:
            raise ErroRepositorio("Matrícula maior que a coluna do banco.")   # como o MySQL
        with self._lock:
            chave = _normalizar(registro.matricula)
            self._registros[chave] = dataclasses.replace(registro, matricula=chave)

    def bloqueadas(self, agora: datetime) -> list[RegistroTentativas]:
        return sorted((r for r in self._registros.values() if r.bloqueado_ate and r.bloqueado_ate > agora),
                      key=lambda r: r.bloqueado_ate)


class RepositorioConsentimentosMemoria:
    def __init__(self):
        self._por_id: dict[int, Consentimento] = {}
        self._ids = itertools.count(1)
        self._lock = threading.Lock()

    def registrar(self, consentimento: Consentimento) -> Consentimento:
        with self._lock:
            gravado = dataclasses.replace(consentimento, id=next(self._ids))
            self._por_id[gravado.id] = gravado
            return gravado

    def vincular(self, consentimento_id: int, usuario_id: int) -> None:
        with self._lock:
            atual = self._por_id.get(consentimento_id)
            if atual is None:
                raise RegistroInexistente(f"Consentimento {consentimento_id} não existe.")
            self._por_id[consentimento_id] = dataclasses.replace(atual, usuario_id=usuario_id)

    def vigente_de(self, usuario_id: int) -> Consentimento | None:
        vigentes = [c for c in self._por_id.values() if c.usuario_id == usuario_id and c.vigente]
        return max(vigentes, key=lambda c: c.momento, default=None)

    def de_usuario(self, usuario_id: int) -> list[Consentimento]:
        return sorted((c for c in self._por_id.values() if c.usuario_id == usuario_id),
                      key=lambda c: (c.momento, c.id))

    def revogar(self, usuario_id: int, momento: datetime) -> bool:
        with self._lock:
            alvos = [c for c in self._por_id.values() if c.usuario_id == usuario_id and c.vigente]
            for c in alvos:
                self._por_id[c.id] = dataclasses.replace(c, revogado_em=momento)
            return bool(alvos)


class RepositorioAmostrasMemoria:
    def __init__(self, relogio=datetime.now):
        self._amostras: list[Amostra] = []
        self._ids = itertools.count(1)
        self._lock = threading.Lock()
        self._relogio = relogio

    def registrar(self, amostras: list[Amostra]) -> None:
        with self._lock:
            agora = self._relogio()
            self._amostras += [dataclasses.replace(a, id=next(self._ids), criada_em=agora)
                               for a in amostras]

    def por_usuario(self, usuario_id: int) -> list[Amostra]:
        return [a for a in self._amostras if a.usuario_id == usuario_id]


class RepositorioAdministradoresMemoria:
    def __init__(self):
        self._por_usuario: dict[int, Administrador] = {}
        self._codigos: dict[int, CodigoRecuperacao] = {}
        self._ids = itertools.count(1)
        self._lock = threading.Lock()

    def listar(self) -> list[Administrador]:
        return sorted(self._por_usuario.values(), key=lambda a: (a.designado_em, a.usuario_id))

    def obter(self, usuario_id: int) -> Administrador | None:
        return self._por_usuario.get(usuario_id)

    def salvar(self, administrador: Administrador) -> None:
        with self._lock:
            self._por_usuario[administrador.usuario_id] = administrador

    def registrar_passo(self, usuario_id: int, passo: int) -> bool:
        with self._lock:
            atual = self._por_usuario.get(usuario_id)
            if atual is None or (atual.ultimo_passo is not None and passo <= atual.ultimo_passo):
                return False
            self._por_usuario[usuario_id] = dataclasses.replace(atual, ultimo_passo=passo)
            return True

    def trocar_codigos(self, usuario_id: int, hashes: list[str], momento: datetime) -> None:
        with self._lock:
            for c in list(self._codigos.values()):
                if c.usuario_id == usuario_id and c.usado_em is None:
                    self._codigos[c.id] = dataclasses.replace(c, usado_em=momento)
            for h in hashes:
                novo = CodigoRecuperacao(usuario_id, h, momento, id=next(self._ids))
                self._codigos[novo.id] = novo

    def codigos_validos(self, usuario_id: int) -> list[CodigoRecuperacao]:
        return [c for c in self._codigos.values() if c.usuario_id == usuario_id and c.usado_em is None]

    def usar_codigo(self, codigo_id: int, momento: datetime) -> bool:
        with self._lock:
            c = self._codigos.get(codigo_id)
            if c is None or c.usado_em is not None:
                return False
            self._codigos[codigo_id] = dataclasses.replace(c, usado_em=momento)
            return True


class RepositorioEstacoesMemoria:
    def __init__(self):
        self._dados: dict[int, dict[str, list[datetime]]] = {}
        self._lock = threading.Lock()

    def conhecidas(self, usuario_id: int) -> set[str]:
        with self._lock:
            return set(self._dados.get(usuario_id, {}))

    def registrar(self, usuario_id: int, impressao: str, momento: datetime) -> None:
        with self._lock:
            uso = self._dados.setdefault(usuario_id, {}).setdefault(impressao, [momento, momento])
            uso[1] = momento


class RepositorioTrilhaMemoria:
    def __init__(self):
        self._registros: list[RegistroTrilha] = []
        self._lock = threading.Lock()

    def acrescentar(self, montar) -> RegistroTrilha:
        with self._lock:                                   # ler o último + gravar, sem intervalo
            anterior = self._registros[-1].hash_registro if self._registros else None
            registro = dataclasses.replace(montar(anterior), id=len(self._registros) + 1)
            self._registros.append(registro)
            return registro

    def todos(self) -> list[RegistroTrilha]:
        return list(self._registros)

    def recentes(self, limite: int) -> list[RegistroTrilha]:
        return list(reversed(self._registros[-limite:]))


class RepositorioAcervoMemoria:
    """O acervo em memória (mesmos dados que a importação grava no MySQL)."""

    def __init__(self):
        from ecosec.acervo import sinteticos          # gerador determinístico
        self._pendencias, self._responsaveis = sinteticos.gerar()
        self._catalogo = list(sinteticos.CATALOGO)
        self._atividades, self._motivos = list(sinteticos.ATIVIDADES), list(sinteticos.MOTIVOS)

    def catalogo(self):
        return list(self._catalogo)

    def atividades(self):
        return list(self._atividades)

    def motivos(self):
        return list(self._motivos)

    def eventos(self):
        from ecosec.acervo import sinteticos
        return list(sinteticos.EVENTOS)

    def pendencias(self, uf=None):
        return [p for p in self._pendencias if uf is None or p.uf == uf]

    def responsaveis(self, nivel, uf=None):
        codigos = {p.codigo for p in self.pendencias(uf)}
        return [r for r in self._responsaveis if r.nivel_minimo <= nivel and r.pendencia_codigo in codigos]
