"""Autenticação: conduz uma tentativa, etapa por etapa, até a decisão.

    N1:  ROSTO (1:N) ──────────────────────────────────────────▶ decisão
    N2:  CREDENCIAIS ─▶ ROSTO (1:1) ───────────────────────────▶ decisão
    N3:  CREDENCIAIS ─▶ ROSTO (1:1) ─▶ DESAFIO ─▶ [2ª pessoa: o mesmo] ─▶ decisão

Login de entrada e STEP-UP. Antes de qualquer tela, a pessoa faz o login de
entrada com os fatores do N2 (ver politica.py). O que ele prova vira uma
IdentidadeComprovada, válida enquanto a sessão da aplicação durar:
- abrir o N1 ou o N2: `abrir_nivel` reavalia as evidências do login com a
  mesma `decidir()` daquele nível. Nenhum fator novo é pedido, porque o login
  já provou matrícula, senha e rosto 1:1; a política é quem confirma;
- abrir o N3: uma sessão que começa no rosto (matrícula e senha vêm do login)
  e pede o que o login não provou: rosto de novo, vivacidade e segunda pessoa;
- painel do administrador: o mesmo começo no rosto, para conferir na hora que
  quem está diante da tela é o administrador logado.
A contenção de um step-up usa uma chave própria (MATRÍCULA#N3, MATRÍCULA#ADM):
falhar o gesto do N3 três vezes tranca o N3, não o login nem o N1/N2. Sem
isso, um detector de gesto mal calibrado trancava a pessoa fora do sistema
inteiro por causa de um único nível.

Quem decide é a política (função pura). Este serviço só COLETA evidências e,
a cada etapa, pergunta à política "até aqui, tudo certo?" (primeira_falha). A
decisão final é sempre `decidir()` sobre todas as evidências.

Recebe ResultadoQuadro (da visão), nunca a câmera: por isso é testável com
quadros fabricados.

Decisões de segurança deste serviço:
- Matrícula bloqueada nem confere a senha: senão o bloqueio viraria oráculo.
- Durante o desafio o ROSTO continua sendo conferido. Sem isso, mostra-se a
  foto da vítima para a S4 e faz-se o gesto com o próprio rosto.
- Desistir na etapa do rosto conta como falha para a S1. Sem isso, quem tem a
  senha roubada testaria rostos e cancelaria antes do prazo, para sempre.
- Métodos protegidos por Lock: o vídeo chama `processar` numa thread e a tela
  chama `informar_credenciais` em outra.
"""
import dataclasses
import functools
import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from ecosec.dominio.camadas import CamadaSeguranca as C
from ecosec.dominio.entidades import MATRICULA_MAX, Usuario
from ecosec.dominio.motivos import Motivo
from ecosec.dominio.niveis import ModoBiometrico, Nivel
from ecosec.seguranca.acesso import contexto, s1_contencao, s2_conhecimento, s6_vivacidade
from ecosec.seguranca.acesso.contexto import SEM_RISCO, ParametrosContexto, RiscoContexto
from ecosec.seguranca.acesso.politica import (Decisao, Evidencias, ParametrosAcesso, camadas_exigidas,
                                              decidir, primeira_falha)
from ecosec.seguranca.acesso.s1_contencao import ParametrosContencao
from ecosec.seguranca.acesso.s2_conhecimento import PoliticaSenha
from ecosec.seguranca.acesso.veredito import Veredito
from ecosec.visao.gestos import DetectorGesto, Gesto, ParametrosGestos
from ecosec.visao.reconhecimento import ConfirmadorQuadros

log = logging.getLogger(__name__)


def _falha_segura(metodo):
    """Qualquer exceção (banco fora do ar, modelo corrompido...) encerra a
    tentativa como negada (ERRO_INTERNO). Nunca trava, nunca concede."""
    @functools.wraps(metodo)
    def protegido(self, *args, **kwargs):
        with self._lock:
            try:
                return metodo(self, *args, **kwargs)
            except Exception:  # noqa: BLE001, de propósito: nenhuma falha concede
                log.exception("Falha durante a autenticação; tentativa negada")
                return self._erro_interno()
    return protegido


# falhas que provam identidade errada sob uma matrícula: contam para o bloqueio
FALHAS_DE_IDENTIDADE = {Motivo.USUARIO_INEXISTENTE, Motivo.SENHA_INCORRETA,
                        Motivo.CREDENCIAL_ALHEIA, Motivo.VIVACIDADE_NAO_CONFIRMADA}


class Finalidade(str, Enum):
    ENTRADA = "ENTRADA"            # login de entrada (fatores do N2, S5 com piso N1)
    NIVEL = "NIVEL"                # abrir um nível de conteúdo
    ADMIN = "ADMIN"                # conferir o rosto do administrador ao abrir o painel
    OPERACAO = "OPERACAO"          # conferir o rosto antes de uma operação crítica (exportar dados nominais)


@dataclass(frozen=True)
class IdentidadeComprovada:
    """O que o login de entrada provou. Só o serviço cria (a partir de uma
    sessão de entrada concedida); a tela apenas guarda e devolve."""
    usuario_id: int
    matricula: str
    senha_forte: bool                    # a senha cumpre a política do N3? (o N3 confere no step-up)
    evidencias: Evidencias = dataclasses.field(repr=False)
    risco: RiscoContexto = SEM_RISCO     # contexto do login: ALTO = sessão só para consulta


class Etapa(str, Enum):
    CREDENCIAIS = "CREDENCIAIS"
    ROSTO = "ROSTO"
    DESAFIO = "DESAFIO"
    CONCLUIDA = "CONCLUIDA"


@dataclass(frozen=True)
class Andamento:
    """O que a tela precisa mostrar agora. Imutável: a thread do vídeo cria, a da tela lê."""
    etapa: Etapa
    pessoa: int
    mensagem: str
    camadas: tuple                       # exigidas pelo nível, na ordem
    aprovadas: frozenset                 # camadas já aprovadas
    atual: C | None = None
    progresso: float = 0.0               # 0..1
    distancia: float | None = None
    limiar: float | None = None
    segundos_restantes: float | None = None
    desafio: s6_vivacidade.Desafio | None = None
    desafio_indice: int = 0
    desafio_total: int = 0
    decisao: Decisao | None = None
    cancelada: bool = False
    bloqueado_ate: datetime | None = None    # contenção ativa: até quando (a tela informa a hora)


@dataclass
class ParametrosAutenticacao:
    acesso: ParametrosAcesso
    contencao: ParametrosContencao
    custo_bcrypt: int
    politica_forte: PoliticaSenha
    frames_confirmacao: int
    timeout_rosto: float
    desafios: tuple
    quantidade_desafios: int
    timeout_desafio: float
    divergentes_maximos: int
    conferidos_minimos: int
    gesto_obrigatorio: str | None
    gestos: ParametrosGestos
    limiar_durante_gesto: float = 70.0

    @classmethod
    def de_configuracao(cls, cfg) -> "ParametrosAutenticacao":
        v = cfg.secao("s6_vivacidade")
        return cls(ParametrosAcesso.de_configuracao(cfg), ParametrosContencao.de_configuracao(cfg),
                   int(cfg["s2_conhecimento.custo_bcrypt"]), PoliticaSenha.de_configuracao(cfg, Nivel.N3),
                   int(cfg["reconhecimento.frames_confirmacao"]), float(cfg["reconhecimento.timeout_face_segundos"]),
                   tuple(v["desafios"]), int(v["quantidade_desafios"]), float(v["timeout_desafio_segundos"]),
                   int(v["quadros_divergentes_maximos"]), int(v["quadros_conferidos_minimos"]),
                   v["gesto_obrigatorio"] or None,
                   ParametrosGestos.de_configuracao(cfg), float(v["limiar_durante_gesto"]))


class ServicoAutenticacao:
    def __init__(self, usuarios, tentativas, consentimentos, reconhecedor, parametros: ParametrosAutenticacao,
                 *, relogio=datetime.now, monotonico=time.monotonic, gerador=None,
                 criar_detector=None, ao_concluir=None, trilha=None, estacoes=None, eh_administrador=None,
                 contexto_parametros: ParametrosContexto | None = None, estacao_atual=contexto.impressao_estacao):
        self.trilha = trilha                          # ServicoTrilha (None = sem auditoria, só em testes)
        # MFA adaptativo: sem repositório de estações ou parâmetros, o contexto não é avaliado (risco BAIXO)
        self.estacoes, self.contexto_parametros, self.estacao_atual = estacoes, contexto_parametros, estacao_atual
        self.usuarios, self.tentativas, self.consentimentos = usuarios, tentativas, consentimentos
        self.reconhecedor = reconhecedor
        self.p = parametros
        self.relogio, self.monotonico, self.gerador = relogio, monotonico, gerador
        self.criar_detector = criar_detector or (lambda gesto: DetectorGesto(gesto, parametros.gestos))
        self.ao_concluir = ao_concluir
        # o administrador é um Externo com esse papel: a S5 o deixa entrar (os outros Externos, não)
        self.eh_administrador = eh_administrador or (lambda _usuario_id: False)

    def nova_sessao(self, nivel: int, identidade: IdentidadeComprovada | None = None) -> "SessaoAutenticacao":
        """Com `identidade`, a sessão começa no rosto (step-up do N3)."""
        return SessaoAutenticacao(Nivel(nivel), self, identidade=identidade)

    def nova_entrada(self) -> "SessaoAutenticacao":
        return SessaoAutenticacao(Nivel.N2, self, finalidade=Finalidade.ENTRADA)

    def nova_verificacao_admin(self, identidade: IdentidadeComprovada) -> "SessaoAutenticacao":
        return SessaoAutenticacao(Nivel.N2, self, finalidade=Finalidade.ADMIN, identidade=identidade)

    def nova_verificacao_operacao(self, identidade: IdentidadeComprovada) -> "SessaoAutenticacao":
        """Step-up antes de uma operação crítica: o rosto é conferido de novo, NA HORA (verificação de presença)."""
        return SessaoAutenticacao(Nivel.N2, self, finalidade=Finalidade.OPERACAO, identidade=identidade)

    def avaliar_contexto(self, usuario: Usuario, falhas_recentes: int) -> RiscoContexto:
        if self.contexto_parametros is None or self.estacoes is None or usuario is None:
            return SEM_RISCO
        conhecidas = self.estacoes.conhecidas(usuario.id)
        estacao_conhecida = None if not conhecidas else self.estacao_atual() in conhecidas
        return contexto.avaliar(self.relogio(), self.contexto_parametros, estacao_conhecida, falhas_recentes)

    def desbloquear(self, identidade: IdentidadeComprovada, senha: str) -> Motivo:
        """Tela de bloqueio por inatividade: a senha do próprio logado devolve a sessão.
        Erros contam para a contenção da matrícula (adivinhar a senha na tela de
        bloqueio é ataque à conta); bloqueada, a sessão termina."""
        try:
            matricula, agora = identidade.matricula, self.relogio()
            registro = self.tentativas.obter(matricula)
            if s1_contencao.esta_bloqueado(registro, agora):
                motivo = Motivo.BLOQUEADO                  # nem confere a senha: não vira oráculo
            else:
                usuario = self.usuarios.por_id(identidade.usuario_id)
                if s2_conhecimento.conferir(senha, usuario.senha_hash if usuario else None, self.p.custo_bcrypt):
                    self.tentativas.salvar(s1_contencao.registrar_sucesso(matricula))
                    motivo = Motivo.CONCEDIDO if usuario.ativo else Motivo.USUARIO_INATIVO
                else:
                    novo = s1_contencao.registrar_falha(registro, matricula, agora, self.p.contencao)
                    self.tentativas.salvar(novo)
                    motivo = Motivo.BLOQUEADO if s1_contencao.esta_bloqueado(novo, agora) else Motivo.SENHA_INCORRETA
            if self.trilha is not None:
                self.trilha.registrar("SESSAO", "CONCEDIDO" if motivo is Motivo.CONCEDIDO else "NEGADO",
                                      "DESBLOQUEIO" if motivo is Motivo.CONCEDIDO else motivo.value,
                                      camadas="S1,S2", usuario_id=identidade.usuario_id,
                                      matricula_informada=matricula, detalhe="tela de bloqueio por inatividade")
            return motivo
        except Exception:  # noqa: BLE001, falha segura: não desbloqueia
            log.exception("Falha ao desbloquear a sessão")
            return Motivo.ERRO_INTERNO

    def abrir_nivel(self, identidade: IdentidadeComprovada, nivel: int) -> Decisao:
        """Step-up sem fator novo (N1 e N2): as evidências do login, reavaliadas
        pela política do nível pedido. Contenção, cadastro e consentimento são
        relidos agora: desativar alguém tem efeito na próxima aba que ele abrir."""
        nivel = Nivel(nivel)
        try:
            usuario = self.usuarios.por_id(identidade.usuario_id)
            ev = dataclasses.replace(
                identidade.evidencias, nivel_solicitado=nivel.value, entrada=False,
                usuario_alegado=usuario, usuario_identificado=usuario,
                bloqueado=s1_contencao.esta_bloqueado(self.tentativas.obter(identidade.matricula), self.relogio()),
                consentimento_vigente=usuario is not None and self.consentimentos.vigente_de(usuario.id) is not None)
            decisao = decidir(ev, self.p.acesso)
        except Exception:  # noqa: BLE001, nenhuma falha concede
            log.exception("Falha ao abrir o nível %s", nivel.value)
            decisao = Decisao(Motivo.ERRO_INTERNO, (), camadas_exigidas(nivel, self.p.acesso.exigir_segunda_pessoa))
        try:
            if self.trilha is not None:
                self.trilha.registrar(
                    "AUTENTICACAO", "CONCEDIDO" if decisao.concedido else "NEGADO", decisao.motivo.value,
                    camadas=decisao.fatores_avaliados, nivel_solicitado=nivel.value,
                    usuario_id=identidade.usuario_id, matricula_informada=identidade.matricula,
                    detalhe="step-up: evidências do login de entrada")
        except Exception:  # noqa: BLE001, SEM REGISTRO, SEM ACESSO
            log.exception("Trilha indisponível ao abrir o nível; acesso negado")
            decisao = Decisao(Motivo.ERRO_INTERNO, decisao.vereditos, decisao.camadas_exigidas)
        return decisao


class SessaoAutenticacao:
    def __init__(self, nivel: Nivel, servico: ServicoAutenticacao, *, finalidade: Finalidade = Finalidade.NIVEL,
                 identidade: IdentidadeComprovada | None = None):
        self.nivel, self.s, self.p = nivel, servico, servico.p
        self.finalidade, self.identidade = finalidade, identidade
        if finalidade in (Finalidade.ADMIN, Finalidade.OPERACAO) and identidade is None:
            raise ValueError("A conferência do rosto parte de um login de entrada.")
        self._risco: RiscoContexto = identidade.risco if identidade is not None else SEM_RISCO
        self._lock = threading.RLock()
        self._camadas = camadas_exigidas(nivel, self.p.acesso.exigir_segunda_pessoa)
        self._pessoas: list[Evidencias] = []
        self._matriculas: list[str | None] = []
        self._chaves: list[str | None] = []            # chave da contenção (no step-up, MATRÍCULA#N3)
        self._bloqueado_ate: datetime | None = None
        self._falhas: list[Veredito | None] = []
        self._concluiu_em: list[float] = []            # instante em que cada pessoa passou até a S6
        self._aprovadas: set = set()
        self._decisao: Decisao | None = None
        self._cancelada = False
        self._andamento: Andamento | None = None
        self._nova_pessoa()

    # ============================================================ consulta
    @property
    def andamento(self) -> Andamento:
        with self._lock:
            return self._andamento

    @property
    def concluida(self) -> bool:
        return self._etapa is Etapa.CONCLUIDA

    def _limiar(self, pessoa=None) -> float:
        nivel = Nivel.N3 if (pessoa or len(self._pessoas)) == 2 else self.nivel
        return self.p.acesso.limiares[nivel]

    @property
    def _ev(self) -> Evidencias:
        return self._pessoas[-1]

    @property
    def _pessoa(self) -> int:
        return len(self._pessoas)

    def _atualizar(self, mensagem, atual=None, **extra) -> Andamento:
        self._andamento = Andamento(self._etapa, self._pessoa, mensagem, self._camadas,
                                    frozenset(self._aprovadas), atual, decisao=self._decisao,
                                    cancelada=self._cancelada, bloqueado_ate=self._bloqueado_ate, **extra)
        return self._andamento

    # ============================================================ pessoas
    def _nova_pessoa(self):
        nivel_pessoa = 3 if self._pessoas else self.nivel.value     # a 2ª pessoa é sempre N3
        entrada = not self._pessoas and self.finalidade is not Finalidade.NIVEL
        self._pessoas.append(Evidencias(nivel_solicitado=nivel_pessoa, entrada=entrada))
        self._matriculas.append(None)
        self._chaves.append(None)
        self._falhas.append(None)
        if self.identidade is not None and self._pessoa == 1:
            self._herdar_credenciais()
        elif self.nivel.modo is ModoBiometrico.VERIFICACAO:
            self._etapa = Etapa.CREDENCIAIS
            texto = ("Segunda pessoa de nível 3: informe a sua matrícula e senha."
                     if self._pessoa == 2 else
                     "Informe a sua matrícula e senha. Ao continuar, o sistema confere primeiro se a matrícula "
                     "pode tentar entrar e depois a senha.")
            # a S1 é a primeira camada avaliada: a tela a destaca desde o início
            self._atualizar(texto, C.S7_CUSTODIA if self._pessoa == 2 else C.S1_CONTENCAO)
        else:
            self._iniciar_rosto()

    def _herdar_credenciais(self):
        """Step-up: matrícula e senha já foram provadas no login de entrada.
        A contenção e o cadastro são relidos AGORA (pode ter mudado desde o login)."""
        idt, ev = self.identidade, self._ev
        self._matriculas[-1] = idt.matricula
        sufixo = {Finalidade.ADMIN: "ADM", Finalidade.OPERACAO: "OPR"}.get(self.finalidade, f"N{self.nivel.value}")
        self._chaves[-1] = f"{idt.matricula}#{sufixo}"
        agora = self.s.relogio()
        registros = [self.s.tentativas.obter(idt.matricula), self.s.tentativas.obter(self._chaves[-1])]
        ev.bloqueado = any(s1_contencao.esta_bloqueado(r, agora) for r in registros)
        if ev.bloqueado:
            self._bloqueado_ate = max(r.bloqueado_ate for r in registros
                                      if r is not None and s1_contencao.esta_bloqueado(r, agora))
        ev.usuario_alegado = self.s.usuarios.por_id(idt.usuario_id)
        ev.administrador = ev.usuario_alegado is not None and bool(self.s.eh_administrador(ev.usuario_alegado.id))
        ev.senha_confere, ev.senha_forte = ev.usuario_alegado is not None, idt.senha_forte
        # sessão de risco ALTO: vale só para consulta, sem N3, sem painel e sem exportação (a S1 nega)
        ev.restrito_a_consulta = idt.risco.so_consulta and (
            self.nivel is Nivel.N3 or self.finalidade in (Finalidade.ADMIN, Finalidade.OPERACAO))
        falha = primeira_falha(ev, self.p.acesso, C.S2_CONHECIMENTO)
        if falha:
            self._etapa = Etapa.CREDENCIAIS              # _finalizar precisa de uma etapa definida
            self._falhar(falha)
            return
        self._aprovadas |= {C.S1_CONTENCAO, C.S2_CONHECIMENTO}
        self._iniciar_rosto()

    # ============================================================ credenciais (S1, S2)
    @_falha_segura
    def informar_credenciais(self, matricula: str, senha: str) -> Andamento:
        with self._lock:
            if self._etapa is not Etapa.CREDENCIAIS:
                return self._andamento
            if self._janela_expirou():
                return self._finalizar()
            matricula = matricula.strip().upper()
            ev = self._ev
            if not matricula or len(matricula) > MATRICULA_MAX:
                # nenhuma matrícula real tem esse formato: responde como inexistente,
                # com o mesmo tempo (bcrypt contra o hash de referência) e sem gravar
                # tentativa: não há chave válida para contar
                ev.bloqueado, ev.usuario_alegado = False, None
                ev.senha_confere = s2_conhecimento.conferir(senha, None, self.p.custo_bcrypt)
                if ev.nivel_solicitado == 3:
                    ev.senha_forte = not s2_conhecimento.pendencias(senha, self.p.politica_forte)
                return self._falhar(primeira_falha(ev, self.p.acesso, C.S2_CONHECIMENTO))
            self._matriculas[-1] = self._chaves[-1] = matricula
            registro = self.s.tentativas.obter(matricula)
            ev.bloqueado = s1_contencao.esta_bloqueado(registro, self.s.relogio())
            if ev.bloqueado:
                self._bloqueado_ate = registro.bloqueado_ate
            if not ev.bloqueado:
                usuario = self.s.usuarios.por_matricula(matricula)
                ev.usuario_alegado = usuario
                ev.administrador = usuario is not None and bool(self.s.eh_administrador(usuario.id))
                # confere sempre (mesmo sem usuário): tempo constante
                ev.senha_confere = s2_conhecimento.conferir(
                    senha, usuario.senha_hash if usuario else None, self.p.custo_bcrypt)
                # medida também no login de entrada: o step-up do N3 usa este resultado
                if ev.nivel_solicitado == 3 or self.finalidade is Finalidade.ENTRADA:
                    ev.senha_forte = not s2_conhecimento.pendencias(senha, self.p.politica_forte)
            falha = primeira_falha(ev, self.p.acesso, C.S2_CONHECIMENTO)
            if falha:
                return self._falhar(falha)
            if self._pessoa == 2 and ev.usuario_alegado.id == self._pessoas[0].usuario_alegado.id:
                return self._finalizar()        # a mesma pessoa duas vezes: S7 decide (inválida)
            if self._pessoa == 1:
                self._aprovadas |= {C.S1_CONTENCAO, C.S2_CONHECIMENTO}
                if self.finalidade is Finalidade.ENTRADA:
                    self._aplicar_contexto(ev.usuario_alegado, registro)
            self._iniciar_rosto()
            return self._andamento

    def _aplicar_contexto(self, usuario: Usuario, registro) -> None:
        """MFA adaptativo: com risco MEDIO ou ALTO, a prova de vida (S6) entra já no login."""
        self._risco = self.s.avaliar_contexto(usuario, registro.falhas if registro else 0)
        if self._risco.exige_vivacidade:
            self._ev.exigir_vivacidade = True
            self._camadas = camadas_exigidas(self.nivel, self.p.acesso.exigir_segunda_pessoa, True)

    # ============================================================ rosto (S3, S4, S5)
    def _iniciar_rosto(self):
        self._etapa = Etapa.ROSTO
        # O prazo do rosto conta a partir do 1º QUADRO, não do aceite da senha: a
        # câmera só liga agora, e o tempo de abri-la não pode consumir o prazo
        # (com ele contando daqui, uma webcam lenta negava no primeiro quadro).
        # Uma câmera que nunca entrega quadro cai no timeout de leitura (ErroCamera).
        self._inicio = None
        self._confirmador = ConfirmadorQuadros(self.p.frames_confirmacao, self._limiar())
        self._contagem = {"sem_face": 0, "multiplas": 0, "ruim": 0, "boas": 0}
        self._ultima_distancia = None
        self._atualizar("Olhe para a câmera.", self._atual_rosto(), limiar=self._limiar(),
                        segundos_restantes=self.p.timeout_rosto)

    def _atual_rosto(self):
        return C.S7_CUSTODIA if self._pessoa == 2 else C.S4_INERENCIA

    @_falha_segura
    def processar(self, r) -> Andamento:
        """Um quadro da visão (ResultadoQuadro)."""
        with self._lock:
            if self._etapa is Etapa.ROSTO:
                return self._quadro_rosto(r)
            if self._etapa is Etapa.DESAFIO:
                return self._quadro_desafio(r)
            if self._etapa is Etapa.CREDENCIAIS and self._janela_expirou():
                return self._finalizar()
            return self._andamento

    def _medir(self, face) -> tuple[int | None, float | None]:
        if self.nivel.modo is ModoBiometrico.IDENTIFICACAO:
            resultado = self.s.reconhecedor.identificar(face)
            return resultado if resultado else (None, None)
        alegado = self._ev.usuario_alegado.id
        distancia = self.s.reconhecedor.verificar(face, alegado)
        return (alegado if distancia is not None else None), distancia

    def _quadro_rosto(self, r) -> Andamento:
        if self._inicio is None:
            self._inicio = self.s.monotonico()
        decorrido = self.s.monotonico() - self._inicio
        if decorrido > self.p.timeout_rosto:
            return self._rosto_sem_confirmacao()
        restante = self.p.timeout_rosto - decorrido
        if r.quantidade_faces == 0:
            self._contagem["sem_face"] += 1
        elif r.quantidade_faces > 1:
            self._contagem["multiplas"] += 1
            self._confirmador.reiniciar()        # uma pessoa por vez: recomeça a contagem
        elif r.face_normalizada is None:
            self._contagem["ruim"] += 1
        else:
            self._contagem["boas"] += 1
            rotulo, distancia = self._medir(r.face_normalizada)
            self._ultima_distancia = distancia
            confirmado = self._confirmador.alimentar(rotulo, distancia)
            if confirmado:
                return self._rosto_confirmado(*confirmado)
        atual = C.S3_QUALIDADE if r.dica else self._atual_rosto()
        mensagem = r.dica or "Reconhecendo… mantenha o rosto parado."
        return self._atualizar(mensagem, atual, progresso=self._confirmador.confirmados / self.p.frames_confirmacao,
                               distancia=self._ultima_distancia, limiar=self._limiar(),
                               segundos_restantes=restante)

    def _rosto_confirmado(self, rotulo: int, distancia_media: float) -> Andamento:
        ev = self._ev
        ev.faces_detectadas, ev.qualidade_aprovada = 1, True
        ev.distancia, ev.identidade_medida = distancia_media, rotulo
        if self.nivel.modo is ModoBiometrico.IDENTIFICACAO:
            ev.usuario_identificado = self.s.usuarios.por_id(rotulo)
        usuario = ev.usuario(Nivel(ev.nivel_solicitado))
        ev.consentimento_vigente = (usuario is not None and
                                    self.s.consentimentos.vigente_de(usuario.id) is not None)
        falha = primeira_falha(ev, self.p.acesso, C.S5_HABILITACAO)
        if falha:
            return self._falhar(falha)
        if self._pessoa == 1:
            self._aprovadas |= {C.S3_QUALIDADE, C.S4_INERENCIA, C.S5_HABILITACAO}
        if C.S6_VIVACIDADE in self._camadas or self._pessoa == 2:
            return self._iniciar_desafio()
        return self._finalizar()

    def _rosto_sem_confirmacao(self) -> Andamento:
        """Prazo esgotado: a evidência registra o que de fato aconteceu."""
        ev, c = self._ev, self._contagem
        if c["boas"]:
            # houve rosto bom, mas não se confirmou: S4 nega (distância None = não confirmada)
            ev.faces_detectadas, ev.qualidade_aprovada = 1, True
        elif c["multiplas"] and c["multiplas"] >= max(c["sem_face"], c["ruim"]):
            ev.faces_detectadas = 2
        elif c["ruim"]:
            ev.faces_detectadas, ev.qualidade_aprovada = 1, False
        else:
            ev.faces_detectadas = 0
        nivel = Nivel(ev.nivel_solicitado)
        return self._falhar(primeira_falha(ev, self.p.acesso, C.S5_HABILITACAO)
                            or Veredito(C.S4_INERENCIA, Motivo.CREDENCIAL_ALHEIA
                                        if nivel.modo is ModoBiometrico.VERIFICACAO
                                        else Motivo.FACE_NAO_RECONHECIDA))

    # ============================================================ desafio (S6)
    # Como o gesto é amarrado à identidade (três regras):
    #  1. o rosto é conferido em todo quadro bom, com a tolerância de gesto (o rosto em
    #     movimento ou piscando se afasta do modelo); N quadros seguidos fora dela negam
    #     (uma troca de rosto fica muito além; um quadro borrado isolado, não);
    #  2. se o rosto some da imagem durante a PISCADA, ela recomeça: trocar a
    #     foto da vítima pelo próprio rosto faz a face sumir por um instante.
    #     No MOVER, sumir é normal (o detector frontal perde o rosto virado, medido
    #     em 02/11/2026: 20% a 45% dos quadros); o quadro só não conta. A troca de
    #     rosto continua barrada pelas regras 1 e 3;
    #  3. depois de cada gesto, a identidade precisa ser CONFERIDA de novo em N
    #     quadros seguidos. Contar conferências durante o gesto não basta: dois
    #     quadros da foto antes da troca já as cumpririam.
    def _iniciar_desafio(self) -> Andamento:
        self._etapa = Etapa.DESAFIO
        self._desafios = s6_vivacidade.sortear(self.p.desafios, self.p.quantidade_desafios, self.s.gerador,
                                               exigir=self.p.gesto_obrigatorio)
        self._indice_desafio = 0
        self._divergentes = 0
        return self._proximo_gesto()

    def _proximo_gesto(self) -> Andamento:
        desafio = self._desafios[self._indice_desafio]
        self._detector = self.s.criar_detector(Gesto(desafio.value))
        self._inicio = self.s.monotonico()
        self._conferindo = False             # True = gesto feito, conferindo a identidade depois dele
        self._conferidos = 0
        return self._andamento_desafio()

    def _andamento_desafio(self, progresso=0.0) -> Andamento:
        desafio = self._desafios[self._indice_desafio]
        atual = C.S7_CUSTODIA if self._pessoa == 2 else C.S6_VIVACIDADE
        restante = self.p.timeout_desafio - (self.s.monotonico() - self._inicio)
        return self._atualizar(desafio.instrucao, atual, progresso=progresso, desafio=desafio,
                               desafio_indice=self._indice_desafio + 1, desafio_total=len(self._desafios),
                               segundos_restantes=max(0.0, restante))

    def _quadro_desafio(self, r) -> Andamento:
        if self.s.monotonico() - self._inicio > self.p.timeout_desafio:
            return self._vivacidade(False)
        desafio = self._desafios[self._indice_desafio]
        atual = C.S7_CUSTODIA if self._pessoa == 2 else C.S6_VIVACIDADE
        # regra 2: rosto sumiu na piscada = possível troca -> ela recomeça (o prazo segue)
        if r.quantidade_faces == 0 and desafio is not s6_vivacidade.Desafio.PISCAR:
            return self._andamento_desafio(getattr(self._detector, "progresso", 0.0))
        if r.quantidade_faces == 0:
            self._detector = self.s.criar_detector(Gesto(desafio.value))
            self._conferindo, self._conferidos = False, 0
            return self._atualizar("Mantenha o rosto dentro do quadro e refaça o gesto.", atual,
                                   desafio=desafio, desafio_indice=self._indice_desafio + 1,
                                   desafio_total=len(self._desafios))
        # regra 1: conferência contínua, com tolerância de gesto e divergências seguidas
        conferido = False
        if r.quantidade_faces > 1:
            self._divergentes += 1
        elif r.face_normalizada is not None:
            distancia = self.s.reconhecedor.verificar(r.face_normalizada, self._ev.usuario_alegado.id)
            tolerancia = max(self._limiar(), self.p.limiar_durante_gesto)
            if distancia is None or not (distancia <= tolerancia):
                self._divergentes += 1
            else:
                self._divergentes = 0
                conferido = distancia <= self._limiar()          # a regra 3 usa o limiar do nível
        if self._divergentes > self.p.divergentes_maximos:
            return self._vivacidade(False)

        if not self._conferindo:
            if self._detector.alimentar(r):
                self._conferindo, self._conferidos = True, 0
            return self._andamento_desafio(self._detector.progresso)

        # regra 3: depois do gesto, N quadros seguidos conferidos
        self._conferidos = self._conferidos + 1 if conferido else 0
        if self._conferidos < self.p.conferidos_minimos:
            return self._atualizar("Ótimo. Agora olhe para a câmera, parado, por um instante.", atual,
                                   progresso=1.0, desafio=desafio, desafio_indice=self._indice_desafio + 1,
                                   desafio_total=len(self._desafios))
        self._indice_desafio += 1
        if self._indice_desafio == len(self._desafios):
            return self._vivacidade(True)
        return self._proximo_gesto()

    def _vivacidade(self, confirmada: bool) -> Andamento:
        ev = self._ev
        ev.vivacidade_confirmada = confirmada
        falha = primeira_falha(ev, self.p.acesso, C.S6_VIVACIDADE)
        if falha:
            return self._falhar(falha)
        self._concluiu_em.append(self.s.monotonico())
        if self._pessoa == 1:
            self._aprovadas.add(C.S6_VIVACIDADE)
            if C.S7_CUSTODIA in self._camadas:
                self._nova_pessoa()
                return self._andamento
        return self._finalizar()

    # ============================================================ desfecho
    def _janela_expirou(self) -> bool:
        if self._pessoa != 2 or not self._concluiu_em:
            return False
        return self.s.monotonico() - self._concluiu_em[0] > self.p.acesso.janela_custodia_segundos

    @_falha_segura
    def verificar_prazo(self) -> Andamento:
        """A tela chama periodicamente enquanto espera a segunda pessoa digitar."""
        with self._lock:
            if self._etapa is Etapa.CREDENCIAIS and self._janela_expirou():
                return self._finalizar()
            return self._andamento

    def _falhar(self, falha: Veredito) -> Andamento:
        self._falhas[-1] = falha
        return self._finalizar()

    def _evidencias_finais(self) -> Evidencias:
        ev = dataclasses.replace(self._pessoas[0])
        if len(self._pessoas) > 1:
            segunda = self._pessoas[1]
            ev.segundo_usuario = segunda.usuario_alegado
            ev.segundo_autenticado = len(self._concluiu_em) == 2 and self._falhas[1] is None
            if len(self._concluiu_em) == 2:
                ev.segundos_entre = self._concluiu_em[1] - self._concluiu_em[0]
            elif self._janela_expirou():
                ev.segundos_entre = self.s.monotonico() - self._concluiu_em[0]
        return ev

    def _finalizar(self) -> Andamento:
        if self._etapa is Etapa.CONCLUIDA:
            return self._andamento
        decisao = decidir(self._evidencias_finais(), self.p.acesso)
        self._decisao = decisao
        self._contabilizar_tentativas()
        self._etapa = Etapa.CONCLUIDA
        try:
            self._registrar_na_trilha(decisao)
        except Exception:  # noqa: BLE001, SEM REGISTRO, SEM ACESSO
            log.exception("Trilha indisponível: o desfecho não pôde ser registrado; acesso negado")
            self._decisao = Decisao(Motivo.ERRO_INTERNO, decisao.vereditos, self._camadas)
        if self._decisao.concedido:
            self._aprovadas = set(self._camadas)
            self._registrar_estacao()
        atual = self._decisao.camada_que_negou
        andamento = self._atualizar(self._decisao.mensagem, atual)
        if self.s.ao_concluir:
            self.s.ao_concluir(self, self._decisao)
        return andamento

    def _registrar_estacao(self) -> None:
        """Login concedido: a estação passa a ser conhecida desta pessoa. Melhor esforço."""
        if self.finalidade is not Finalidade.ENTRADA or self.s.estacoes is None:
            return
        try:
            self.s.estacoes.registrar(self._pessoas[0].usuario_alegado.id, self.s.estacao_atual(), self.s.relogio())
        except Exception:  # noqa: BLE001, não registrar a estação não pode derrubar um login válido
            log.exception("Falha ao registrar a estação")

    def _registrar_na_trilha(self, decisao: Decisao) -> None:
        if self.s.trilha is None:
            return
        primeira = self._pessoas[0]
        usuario = primeira.usuario(self.nivel)
        segundo = self._pessoas[1].usuario_alegado if len(self._pessoas) > 1 else None
        evento = {Finalidade.ENTRADA: "ENTRADA", Finalidade.ADMIN: "ADMIN",
                  Finalidade.OPERACAO: "OPERACAO"}.get(self.finalidade, "AUTENTICACAO")
        detalhes = [d for d in ("tentativa cancelada" if self._cancelada else None,
                                "step-up: matrícula e senha do login de entrada"
                                if self.identidade and self.finalidade is Finalidade.NIVEL else None,
                                "rosto do administrador conferido ao abrir o painel"
                                if self.finalidade is Finalidade.ADMIN else None,
                                "rosto conferido antes de exportar" if self.finalidade is Finalidade.OPERACAO else None,
                                str(self._risco) if self._risco.nivel != contexto.BAIXO else None) if d]
        self.s.trilha.registrar(
            evento, "CONCEDIDO" if decisao.concedido else "NEGADO", decisao.motivo.value,
            camadas=decisao.fatores_avaliados,
            nivel_solicitado=self.nivel.value if self.finalidade is Finalidade.NIVEL else None,
            usuario_id=usuario.id if usuario else None, usuario2_id=segundo.id if segundo else None,
            matricula_informada=self._matriculas[0],
            # distância só de identidade resolvida: de um desconhecido, não tem finalidade de auditoria
            distancia=primeira.distancia if usuario else None,
            detalhe="; ".join(detalhes) or None)

    def _erro_interno(self) -> Andamento:
        if self._etapa is not Etapa.CONCLUIDA:
            self._decisao = Decisao(Motivo.ERRO_INTERNO, (), self._camadas)
            self._etapa = Etapa.CONCLUIDA
            try:
                self._registrar_na_trilha(self._decisao)      # melhor esforço: o banco pode estar fora
            except Exception:  # noqa: BLE001
                log.exception("Falha ao registrar ERRO_INTERNO na trilha")
        return self._atualizar(Motivo.ERRO_INTERNO.mensagem)

    def _contabilizar_tentativas(self):
        agora = self.s.relogio()
        for chave, falha in zip(self._chaves, self._falhas):
            if chave is None:
                continue                                  # N1 não tem matrícula
            if falha is not None and falha.motivo in FALHAS_DE_IDENTIDADE:
                novo = s1_contencao.registrar_falha(self.s.tentativas.obter(chave), chave, agora, self.p.contencao)
                self.s.tentativas.salvar(novo)
                if s1_contencao.esta_bloqueado(novo, agora):    # esta falha bloqueou: a tela já diz até quando
                    self._bloqueado_ate = max(filter(None, (self._bloqueado_ate, novo.bloqueado_ate)))
            elif self._decisao.concedido:
                self.s.tentativas.salvar(s1_contencao.registrar_sucesso(chave))

    @_falha_segura
    def cancelar(self) -> Andamento:
        with self._lock:
            if self._etapa is Etapa.CONCLUIDA:
                return self._andamento
            self._cancelada = True
            # desistir depois de alegar uma identidade conta como falha (ver docstring)
            if self._etapa in (Etapa.ROSTO, Etapa.DESAFIO) and self._matriculas[-1]:
                self._falhas[-1] = Veredito(self._atual_rosto(), Motivo.CREDENCIAL_ALHEIA)
            return self._finalizar()

    @property
    def identidade_comprovada(self) -> IdentidadeComprovada | None:
        """Só de um login de ENTRADA concedido."""
        if self.finalidade is not Finalidade.ENTRADA or self._decisao is None or not self._decisao.concedido:
            return None
        ev = dataclasses.replace(self._pessoas[0])
        return IdentidadeComprovada(ev.usuario_alegado.id, self._matriculas[0], bool(ev.senha_forte), ev, self._risco)

    @property
    def credenciais_sem_rosto(self) -> Usuario | None:
        """Login de ENTRADA negado DEPOIS de a matrícula e a senha passarem (S1 e S2), no rosto ou na
        câmera (S3/S4; a falha da câmera cancela a tentativa no rosto). É o único caso em que o login
        pode oferecer o acesso de emergência: quem chegou aqui sabe a senha e foi barrado pela câmera."""
        if self.finalidade is not Finalidade.ENTRADA or self._decisao is None or self._decisao.concedido:
            return None
        if not {C.S1_CONTENCAO, C.S2_CONHECIMENTO} <= self._aprovadas:
            return None
        if self._decisao.camada_que_negou not in (C.S3_QUALIDADE, C.S4_INERENCIA):
            return None
        return self._pessoas[0].usuario_alegado

    @property
    def usuario_autenticado(self) -> Usuario | None:
        if self._decisao is None or not self._decisao.concedido:
            return None
        return self._pessoas[0].usuario(self.nivel)
