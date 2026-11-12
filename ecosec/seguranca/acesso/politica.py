"""Política de acesso: compõe as camadas S1 a S7 conforme o nível.

É uma função pura: recebe as evidências já coletadas e devolve a decisão. Não
abre câmera, não consulta banco, não desenha tela. Por isso pode ser testada
em milissegundos, cobrindo combinações que seriam impossíveis de montar ao
vivo diante da webcam.

Três princípios:
1. Falha segura: evidência ausente (None) nega. Não existe caminho em que a
   falta de informação conceda acesso.
2. Ordem fixa S1 -> S7, parando na primeira negação. Não se abre a câmera
   para quem errou a senha, nem se pede o gesto a quem o rosto não confere.
3. Exceção não concede: qualquer erro inesperado vira ERRO_INTERNO.

A mesma composição serve à avaliação progressiva (`primeira_falha`): o serviço
de autenticação pergunta "até a S2, tudo certo?" antes de ligar a câmera.

LOGIN DE ENTRADA (`Evidencias.entrada`): antes de qualquer tela, a pessoa
prova quem é com os fatores do NÍVEL 2 (matrícula, senha, rosto 1:1 com o
limiar do N2). A única diferença está na S5: na entrada, basta ter um perfil com
camada ou o papel de administrador (um Externo sem esse papel não entra). Não há uma política paralela para o
login: é a mesma função, com o mesmo rigor. E é ela mesma que decide, depois,
se as evidências do login bastam para abrir o N1 ou o N2 (step-up).
"""
from collections.abc import Iterator, Mapping
from dataclasses import dataclass

from ecosec.configuracao import Configuracao
from ecosec.dominio.camadas import Anel, CamadaSeguranca as C, camadas_do_anel
from ecosec.dominio.entidades import Usuario
from ecosec.dominio.motivos import Motivo
from ecosec.dominio.niveis import ModoBiometrico, Nivel
from ecosec.seguranca.acesso import (s1_contencao, s2_conhecimento, s3_qualidade, s4_inerencia,
                                     s5_habilitacao, s6_vivacidade, s7_custodia)
from ecosec.seguranca.acesso.veredito import Veredito, negar


@dataclass(frozen=True)
class ParametrosAcesso:
    limiares: Mapping[Nivel, float]
    exigir_segunda_pessoa: bool
    janela_custodia_segundos: float

    @classmethod
    def de_configuracao(cls, cfg: Configuracao) -> "ParametrosAcesso":
        return cls(
            limiares={n: float(cfg[f"s4_inerencia.limiar_nivel_{n.value}"]) for n in Nivel},
            exigir_segunda_pessoa=bool(cfg["s7_custodia.exigir_segunda_pessoa"]),
            janela_custodia_segundos=float(cfg["s7_custodia.janela_segundos"]),
        )


@dataclass
class Evidencias:
    """Tudo o que foi coletado numa tentativa. None = não avaliado (e nega)."""
    nivel_solicitado: int
    entrada: bool = False                # login de entrada: a S5 exige uma camada ou o papel de administrador
    administrador: bool = False          # o cadastro tem o papel de administrador (o único Externo que entra)
    exigir_vivacidade: bool = False      # contexto de risco (MFA adaptativo): a S6 entra mesmo onde o nível não pede
    restrito_a_consulta: bool = False    # contexto de risco ALTO: a S1 nega N3, painel e operação crítica
    # S1
    bloqueado: bool | None = None
    # S2: usuário encontrado pela matrícula digitada (N2/N3)
    usuario_alegado: Usuario | None = None
    senha_confere: bool | None = None
    senha_forte: bool | None = None
    # S3
    faces_detectadas: int | None = None
    qualidade_aprovada: bool | None = None
    # S4
    distancia: float | None = None
    identidade_medida: int | None = None
    # S5: no N1 o usuário vem do reconhecimento; no N2/N3 é o alegado
    usuario_identificado: Usuario | None = None
    consentimento_vigente: bool | None = None
    # S6
    vivacidade_confirmada: bool | None = None
    # S7
    segundo_usuario: Usuario | None = None
    segundo_autenticado: bool | None = None
    segundos_entre: float | None = None

    def usuario(self, nivel: Nivel) -> Usuario | None:
        """De quem é esta tentativa, conforme o modo do nível."""
        if nivel.modo is ModoBiometrico.VERIFICACAO:
            return self.usuario_alegado
        return self.usuario_identificado


@dataclass(frozen=True)
class Decisao:
    motivo: Motivo
    vereditos: tuple[Veredito, ...]
    camadas_exigidas: tuple[C, ...]

    @property
    def concedido(self) -> bool:
        return self.motivo.concede

    @property
    def mensagem(self) -> str:
        return self.motivo.mensagem

    @property
    def camada_que_negou(self) -> C | None:
        if self.concedido or not self.vereditos or self.vereditos[-1].aprovado:
            return None
        return self.vereditos[-1].camada

    @property
    def fatores_avaliados(self) -> str:
        """Formato gravado na trilha: 'S2,S3,S4', só as camadas que chegaram a ser avaliadas."""
        return ",".join(v.camada.codigo for v in self.vereditos)

    def __str__(self):
        return "  ".join(str(v) for v in self.vereditos) + f"  →  {self.motivo.value}"


def camadas_exigidas(nivel: Nivel, exigir_segunda_pessoa: bool = True, exigir_vivacidade: bool = False) -> tuple[C, ...]:
    """Camadas do Anel 1 que o nível exige, na ordem de avaliação.

    Com a regra dos dois desligada, a S7 sai da lista: não vira uma camada
    "aprovada" que não foi avaliada. A auditoria leria "duas pessoas
    conferiram" onde houve uma só. Com `exigir_vivacidade` (contexto de risco),
    a S6 entra mesmo onde o nível não a pede, no seu lugar na ordem.
    """
    camadas = tuple(c for c in camadas_do_anel(Anel.ACESSO)
                    if c.atua_no(nivel) or (exigir_vivacidade and c is C.S6_VIVACIDADE))
    if not exigir_segunda_pessoa:
        camadas = tuple(c for c in camadas if c is not C.S7_CUSTODIA)
    return camadas


def _avaliar_camada(camada: C, ev: Evidencias, nivel: Nivel, p: ParametrosAcesso) -> Veredito:
    if camada is C.S1_CONTENCAO:
        if ev.restrito_a_consulta:          # antes da câmera: a sessão de risco ALTO não tenta o que não pode
            return negar(Motivo.RISCO_CONTEXTUAL)
        return s1_contencao.avaliar(ev.bloqueado)
    if camada is C.S2_CONHECIMENTO:
        return s2_conhecimento.avaliar(nivel, ev.usuario_alegado is not None,
                                       ev.senha_confere, ev.senha_forte)
    if camada is C.S3_QUALIDADE:
        return s3_qualidade.avaliar(ev.faces_detectadas, ev.qualidade_aprovada)
    if camada is C.S4_INERENCIA:
        alegado = ev.usuario_alegado.id if ev.usuario_alegado else None
        return s4_inerencia.avaliar(nivel, ev.distancia, ev.identidade_medida, p.limiares, alegado)
    if camada is C.S5_HABILITACAO:
        return s5_habilitacao.avaliar(ev.usuario(nivel), ev.consentimento_vigente, nivel, entrada=ev.entrada,
                                      administrador=ev.administrador)
    if camada is C.S6_VIVACIDADE:
        return s6_vivacidade.avaliar(ev.vivacidade_confirmada)
    if camada is C.S7_CUSTODIA:
        return s7_custodia.avaliar(ev.usuario(nivel), ev.segundo_usuario, ev.segundo_autenticado,
                                   ev.segundos_entre, p.janela_custodia_segundos)
    raise ValueError(f"Camada fora do Anel 1: {camada}")


def _percorrer(ev: Evidencias, nivel: Nivel, p: ParametrosAcesso, ate: C | None) -> Iterator[Veredito]:
    for camada in camadas_exigidas(nivel, p.exigir_segunda_pessoa, ev.exigir_vivacidade):
        veredito = _avaliar_camada(camada, ev, nivel, p)
        yield veredito
        if not veredito.aprovado or camada is ate:
            return


def decidir(ev: Evidencias, parametros: ParametrosAcesso) -> Decisao:
    """Decisão final: todas as camadas exigidas pelo nível."""
    try:
        nivel = Nivel(ev.nivel_solicitado)
    except ValueError:
        return Decisao(Motivo.NIVEL_INVALIDO, (), ())
    exigidas = camadas_exigidas(nivel, parametros.exigir_segunda_pessoa, ev.exigir_vivacidade)
    vereditos = []
    try:
        for veredito in _percorrer(ev, nivel, parametros, ate=None):
            vereditos.append(veredito)
    except Exception:  # noqa: BLE001, de propósito: nenhuma exceção pode conceder
        return Decisao(Motivo.ERRO_INTERNO, tuple(vereditos), exigidas)
    ultimo = vereditos[-1] if vereditos else None
    if ultimo is None or not ultimo.aprovado:
        return Decisao(ultimo.motivo if ultimo else Motivo.ERRO_INTERNO, tuple(vereditos), exigidas)
    return Decisao(Motivo.CONCEDIDO, tuple(vereditos), exigidas)


def primeira_falha(ev: Evidencias, parametros: ParametrosAcesso, ate: C) -> Veredito | None:
    """Avaliação progressiva: a primeira camada que nega até `ate` (inclusive),
    ou None se todas passaram. Se `ate` não vale para o nível, avalia todas."""
    try:
        nivel = Nivel(ev.nivel_solicitado)
    except ValueError:
        return Veredito(ate, Motivo.NIVEL_INVALIDO)
    try:
        for veredito in _percorrer(ev, nivel, parametros, ate):
            if not veredito.aprovado:
                return veredito
    except Exception:  # noqa: BLE001, de propósito: nenhuma exceção pode aprovar
        return Veredito(ate, Motivo.ERRO_INTERNO)
    return None
