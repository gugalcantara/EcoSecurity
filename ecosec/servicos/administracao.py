"""Administração do sistema: os administradores, o celular de cada um e as ações que precisam de aprovação.

Ser administrador é um papel dado a um cadastro com o perfil Externo, que não tem acesso ao acervo. Cada
administrador entra pelo mesmo login dos outros usuários, com a própria matrícula, e o painel só abre depois
de conferir o rosto de novo e o código do celular (TOTP). Assim a trilha sempre mostra quem fez cada ação.

As ações críticas (tornar ou tirar um administrador, refazer o celular de alguém, atribuir o perfil de
ministro, revogar um consentimento, excluir um cadastro e registrar a revisão de acessos) precisam do código
do celular de outro administrador, e ninguém aprova o próprio pedido. Com menos de dois administradores
ativos não há quem aprove: o administrador age sozinho e a trilha marca a ação como implantação. Depois de
ter dois, nenhuma ação voluntária reduz esse número.

Outras regras:
- a senha de instalação só abre a configuração inicial, enquanto não existe administrador;
- o acesso de emergência abre com os códigos de recuperação de dois administradores, dura no máximo
  30 minutos e só serve para restaurar o acesso;
- a âncora da trilha é gerada pelo painel, com o código do próprio celular, e a geração fica registrada;
- as ferramentas de terminal que leem o modelo facial pedem matrícula, senha e código de um administrador;
- excluir e revogar não apagam nada: desativam o cadastro, marcam a revogação e eliminam o rosto do modelo,
  nessa ordem, e quem revogou não volta a ser ativado sem um novo termo.
"""
import hmac
import logging
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from enum import Enum

from cryptography.fernet import Fernet, InvalidToken

from ecosec.dominio.entidades import UFS, Administrador, Usuario
from ecosec.dominio.motivos import Motivo
from ecosec.dominio.niveis import Nivel
from ecosec.dominio.perfis import CRITICOS, Perfil
from ecosec.seguranca.acesso import s1_contencao, s2_conhecimento, totp
from ecosec.seguranca.acesso.s1_contencao import ParametrosContencao
from ecosec.seguranca.acesso.s2_conhecimento import PoliticaSenha
from ecosec.seguranca.evidencia.s10_trilha import Ancora

log = logging.getLogger(__name__)

# "#" não existe no alfabeto das matrículas: nunca colide com um usuário real
MATRICULA_ADMIN = "#ADMIN"                      # senha de instalação
CHAVE_EMERGENCIA = "#EMERGENCIA"                # contenção global do acesso de emergência
SUFIXO_CODIGO, SUFIXO_APROVACAO = "#COD", "#APR"
SUFIXO_FERRAMENTA = "#FER"                      # contenção própria das ferramentas de terminal


class AcaoCritica(str, Enum):
    TORNAR_ADMINISTRADOR = "TORNAR_ADMINISTRADOR"
    REMOVER_ADMINISTRADOR = "REMOVER_ADMINISTRADOR"
    REFAZER_CELULAR = "REFAZER_CELULAR"
    REVOGAR_CONSENTIMENTO = "REVOGAR_CONSENTIMENTO"
    REVISAO_ACESSOS = "REVISAO_ACESSOS"
    ATRIBUIR_PERFIL = "ATRIBUIR_PERFIL"
    EXCLUIR_USUARIO = "EXCLUIR_USUARIO"

    @property
    def descricao(self) -> str:
        return _DESCRICOES[self]


_DESCRICOES = {
    AcaoCritica.TORNAR_ADMINISTRADOR: "Tornar administrador",
    AcaoCritica.REMOVER_ADMINISTRADOR: "Tirar o papel de administrador",
    AcaoCritica.REFAZER_CELULAR: "Refazer o celular de um administrador",
    AcaoCritica.REVOGAR_CONSENTIMENTO: "Revogar o consentimento e eliminar o rosto",
    AcaoCritica.REVISAO_ACESSOS: "Registrar a revisão de acessos",
    AcaoCritica.ATRIBUIR_PERFIL: "Atribuir perfil",
    AcaoCritica.EXCLUIR_USUARIO: "Excluir o cadastro (revoga o consentimento e elimina o rosto)",
}
# o que se pode fazer dentro do acesso de emergência: só consertar o acesso
ACOES_DE_EMERGENCIA = {AcaoCritica.TORNAR_ADMINISTRADOR, AcaoCritica.REFAZER_CELULAR}


@dataclass(frozen=True)
class ParametrosGovernanca:
    minimo_administradores: int = 2
    codigos_recuperacao: int = 8
    quorum_emergencia: int = 2
    janela_emergencia: timedelta = timedelta(minutes=5)
    duracao_emergencia: timedelta = timedelta(minutes=30)

    @classmethod
    def de_configuracao(cls, cfg) -> "ParametrosGovernanca":
        a = cfg.secao("administracao")
        return cls(int(a["minimo_administradores"]), int(a["codigos_recuperacao"]), int(a["quorum_emergencia"]),
                   timedelta(minutes=float(a["janela_emergencia_minutos"])),
                   timedelta(minutes=float(a["duracao_emergencia_minutos"])))


@dataclass(frozen=True)
class LinhaUsuario:
    usuario: Usuario
    consentimento_vigente: bool
    amostras: int
    no_modelo: bool          # o rosto está no modelo facial? (diagnóstico de divergência)
    autoriza_pesquisa: bool = False   # finalidade (b) do termo vigente
    administrador: bool = False
    celular: bool = False             # administrador com o celular cadastrado


@dataclass(frozen=True)
class NovoCelular:
    """Segredo ainda não gravado: só vale depois que a pessoa digita o primeiro código."""
    segredo: str = field(repr=False)
    uri: str = field(repr=False)


@dataclass(frozen=True)
class Emergencia:
    """O acesso de emergência concedido: quem pediu, quem confirmou e até quando vale."""
    usuario_id: int
    confirmado_por: tuple[int, ...]
    inicio: datetime
    fim: datetime

    def valida(self, agora: datetime) -> bool:
        return self.inicio <= agora < self.fim


@dataclass(frozen=True)
class PassoEmergencia:
    aceitos: int
    quorum: int
    mensagem: str
    concedida: Emergencia | None = None
    bloqueado_ate: datetime | None = None


class ServicoAdministracao:
    def __init__(self, usuarios, consentimentos, amostras, tentativas, *, contencao: ParametrosContencao,
                 custo_bcrypt: int, politica: PoliticaSenha, ler_hash, gravar_hash, administradores=None,
                 cifra_totp: Fernet | None = None, governanca: ParametrosGovernanca | None = None,
                 relogio=datetime.now, rotulos_modelo=lambda: set(), eliminar_biometria=lambda _id: None,
                 trilha=None):
        from ecosec.repositorios.memoria import RepositorioAdministradoresMemoria
        self.usuarios, self.consentimentos, self.amostras = usuarios, consentimentos, amostras
        self.tentativas = tentativas
        self.administradores = administradores if administradores is not None else RepositorioAdministradoresMemoria()
        # sem chave informada (testes), uma chave efêmera: o segredo vive só na memória do processo
        self._cifra = cifra_totp or Fernet(Fernet.generate_key())
        self.governanca = governanca or ParametrosGovernanca()
        self.contencao, self.custo, self.politica = contencao, custo_bcrypt, politica
        self._ler_hash, self._gravar_hash = ler_hash, gravar_hash
        self.relogio = relogio
        self._rotulos_modelo = rotulos_modelo
        self._eliminar_biometria = eliminar_biometria
        self.trilha = trilha
        self._instalacao_aberta = False      # a senha de instalação foi conferida neste processo

    @classmethod
    def de_configuracao(cls, cfg, usuarios, consentimentos, amostras, tentativas, **extra):
        return cls(usuarios, consentimentos, amostras, tentativas,
                   contencao=ParametrosContencao.de_configuracao(cfg),
                   custo_bcrypt=int(cfg["s2_conhecimento.custo_bcrypt"]),
                   politica=PoliticaSenha.de_configuracao(cfg, Nivel.N3),
                   governanca=ParametrosGovernanca.de_configuracao(cfg), **extra)

    # trilha
    def _registrar(self, resultado: str, motivo: str, evento: str = "ADMIN", **campos) -> None:
        """Ações de proteção (desativar, revogar, negar) acontecem mesmo se a trilha
        falhar: bloquear um acesso nunca deve depender do log. A falha é anotada."""
        if self.trilha is None:
            return
        try:
            self.trilha.registrar(evento, resultado, motivo, **campos)
        except Exception:  # noqa: BLE001
            log.exception("Falha ao registrar %s na trilha", motivo)

    def _registrar_obrigatorio(self, resultado: str, motivo: str, evento: str = "ADMIN", **campos) -> None:
        """O que concede ou eleva (papel, código aceito, emergência) só acontece com registro:
        se a trilha falhar, a exceção sobe e a ação não é feita (sem registro, sem acesso)."""
        if self.trilha is not None:
            self.trilha.registrar(evento, resultado, motivo, **campos)

    def verificar_trilha(self):
        return self.trilha.verificar()

    def ancora_trilha(self):
        return self.trilha.ancora()

    def conferir_ancora_trilha(self, ancorada):
        return self.trilha.conferir_ancora(ancorada)

    def gerar_ancora(self, usuario_id: int | None, codigo: str) -> tuple[object | None, str | None]:
        """A âncora pelo painel: o administrador logado confirma com o código do próprio celular. A geração é
        registrada na trilha antes de calcular a âncora, de modo que a linha guardada fora do banco aponta para o
        registro que diz quem a gerou. Trilha adulterada não é ancorada. Devolve (âncora, None) ou (None, recusa)."""
        try:
            recusa = self._conferir_proprio_codigo(usuario_id, codigo, "ANCORA_TRILHA")
            if recusa:
                return None, recusa
            verificacao = self.trilha.verificar()
            if not verificacao.integra:
                self._registrar("NEGADO", "ANCORA_TRILHA", usuario_id=usuario_id, detalhe=str(verificacao))
                return None, f"A trilha não está íntegra, então a âncora não foi gerada. {verificacao}"
            self._registrar_obrigatorio("REGISTRADO", "ANCORA_TRILHA", usuario_id=usuario_id,
                                        detalhe=f"âncora gerada pelo painel ({verificacao.registros_verificados} registros conferidos)")
            return self.trilha.ancora(), None
        except Exception:  # noqa: BLE001, banco ou trilha fora do ar: sem registro, sem âncora
            log.exception("Falha ao gerar a âncora da trilha")
            return None, "Falha interna: a âncora não foi gerada. Procure o registro de erros."

    def conferir_ancora_painel(self, usuario_id: int | None, linha: str) -> tuple[object | None, str | None]:
        """Confere uma linha de âncora guardada fora do banco. Só lê a trilha, por isso dispensa o código do
        celular, mas o resultado fica registrado. Devolve (conferência, None) ou (None, recusa)."""
        if not self.eh_administrador(usuario_id) or self._usuario_ativo(usuario_id) is None:
            return None, "Só um administrador pode fazer isso."
        try:
            ancorada = Ancora.de_texto(linha)
        except ValueError as erro:
            return None, str(erro)
        try:
            conferencia = self.trilha.conferir_ancora(ancorada)
        except Exception:  # noqa: BLE001
            log.exception("Falha ao conferir a âncora da trilha")
            return None, "Falha interna: a âncora não foi conferida. Procure o registro de erros."
        self._registrar("REGISTRADO" if conferencia.valida else "NEGADO", "CONFERENCIA_ANCORA",
                        usuario_id=usuario_id, detalhe=f"registro {ancorada.id}: " + (
                        "confere" if conferencia.valida else conferencia.problema))
        return conferencia, None

    def autorizar_ferramenta(self, matricula: str, senha: str, codigo: str, ferramenta: str) -> tuple[int | None,
                                                                                                    str | None]:
        """Ferramenta de terminal que lê o modelo facial e os consentimentos (o experimento da curva DET). No
        terminal não há administrador logado, então ela pede a matrícula, a senha e o código do celular de um
        administrador ativo. A contenção é própria (#FER), e o início fica na trilha: sem o registro, a ferramenta
        não roda. Devolve (id do administrador, None) ou (None, recusa)."""
        try:
            informada = (matricula or "").strip().upper()[:20]
            chave = (informada or "?") + SUFIXO_FERRAMENTA
            bloqueio = self._bloqueado_ate(chave)
            if bloqueio is not None:
                return None, f"Bloqueado por erros seguidos até as {bloqueio:%H:%M}."
            usuario = self.usuarios.por_matricula(informada) if informada else None
            confere = s2_conhecimento.conferir(senha or "", usuario.senha_hash if usuario else None, self.custo)
            if not confere or usuario is None or self._admin_ativo(usuario.id) is None \
                    or self._usuario_ativo(usuario.id) is None:
                bloqueio = self._contar_falha(chave)
                self._registrar("NEGADO", "FERRAMENTA_RECUSADA", matricula_informada=informada or None,
                                detalhe=ferramenta)
                return None, ("Matrícula ou senha incorretas, ou o cadastro não é de um administrador ativo."
                              + (f" Bloqueado por erros seguidos até as {bloqueio:%H:%M}." if bloqueio else ""))
            recusa = self._conferir_proprio_codigo(usuario.id, codigo, ferramenta)
            if recusa:
                return None, recusa
            self._zerar(chave)
            self._registrar_obrigatorio("REGISTRADO", "FERRAMENTA_INICIO", usuario_id=usuario.id,
                                        matricula_informada=usuario.matricula, detalhe=ferramenta)
            return usuario.id, None
        except Exception:  # noqa: BLE001, banco ou trilha fora do ar: a ferramenta não roda
            log.exception("Falha ao autorizar a ferramenta %s", ferramenta)
            return None, "Falha interna: a ferramenta não foi liberada. Procure o registro de erros."

    def registrar_fim_ferramenta(self, usuario_id: int, ferramenta: str, resumo: str) -> None:
        """O fim da ferramenta, com um resumo sem dado biométrico (por exemplo, quantas tentativas foram gravadas)."""
        self._registrar("REGISTRADO", "FERRAMENTA_FIM", usuario_id=usuario_id, detalhe=f"{ferramenta}: {resumo}")

    def _conferir_proprio_codigo(self, usuario_id: int | None, codigo: str, acao: str) -> str | None:
        """Ação sensível de quem já está no painel: basta o código do próprio celular (ou um de recuperação).
        Usa a mesma contenção da abertura do painel. Devolve a recusa, ou None se o código confere."""
        adm, usuario = self._admin_ativo(usuario_id), self._usuario_ativo(usuario_id)
        if adm is None or usuario is None:
            return "Só um administrador pode fazer isso."
        chave = usuario.matricula + SUFIXO_CODIGO
        bloqueio = self._bloqueado_ate(chave)
        if bloqueio is not None:
            return f"Código do celular bloqueado por erros seguidos até as {bloqueio:%H:%M}."
        achados = self._quem_tem_o_codigo(codigo or "", [adm])
        if achados and self._consumir(achados[0]):
            self._zerar(chave)
            return None
        bloqueio = self._contar_falha(chave)
        self._registrar("NEGADO", Motivo.CODIGO_INCORRETO.value, usuario_id=usuario_id,
                        matricula_informada=usuario.matricula, detalhe=acao)
        return (f"Código não aceito. Código do celular bloqueado até as {bloqueio:%H:%M}." if bloqueio
                else "Código não aceito. Digite o código atual do aplicativo.")

    def trilha_recente(self, limite: int = 300):
        return self.trilha.recentes(limite)

    def trilha_visivel(self, limite: int = 300):
        """A trilha como o ADMINISTRADOR a vê: o detalhe das consultas e exportações do acervo mascarado."""
        return self.trilha.recentes_para_administrador(limite)

    # contenção (S1) das chaves próprias
    def _bloqueado_ate(self, chave: str) -> datetime | None:
        registro = self.tentativas.obter(chave)
        return registro.bloqueado_ate if s1_contencao.esta_bloqueado(registro, self.relogio()) else None

    def _contar_falha(self, chave: str) -> datetime | None:
        agora = self.relogio()
        novo = s1_contencao.registrar_falha(self.tentativas.obter(chave), chave, agora, self.contencao)
        self.tentativas.salvar(novo)
        return novo.bloqueado_ate if s1_contencao.esta_bloqueado(novo, agora) else None

    def _zerar(self, chave: str) -> None:
        self.tentativas.salvar(s1_contencao.registrar_sucesso(chave))

    # senha de instalação (configuração inicial)
    @property
    def configurado(self) -> bool:
        return bool(self._ler_hash())

    def requisitos_senha(self, senha: str) -> list[tuple[str, bool]]:
        return s2_conhecimento.requisitos(senha, self.politica)

    def definir_senha_inicial(self, senha: str, confirmacao: str) -> list[str]:
        """Só na primeira execução. Devolve os erros (vazio = definida)."""
        if self.configurado:
            return ["A senha de instalação já foi definida."]
        erros = [f"Falta {p}." for p in s2_conhecimento.pendencias(senha, self.politica)]
        if senha != confirmacao:
            erros.append("A confirmação não é igual à senha.")
        if not erros:
            self._gravar_hash(s2_conhecimento.gerar_hash(senha, self.custo))
            self._registrar("REGISTRADO", "ADMIN_SENHA_DEFINIDA")
        return erros

    def autenticar(self, senha: str) -> Motivo:
        """Senha de INSTALAÇÃO: abre o painel só na configuração inicial (a tela decide quando)."""
        try:
            motivo = self._autenticar(senha)
            if self.trilha is not None:
                # entrada de administrador sem registro não acontece: se a trilha
                # falhar aqui, a exceção cai no except abaixo e nega
                self.trilha.registrar("ADMIN", "CONCEDIDO" if motivo is Motivo.CONCEDIDO else "NEGADO",
                                      "ADMIN_AUTENTICADO" if motivo is Motivo.CONCEDIDO else motivo.value,
                                      matricula_informada=MATRICULA_ADMIN)
            return motivo
        except Exception:  # noqa: BLE001, banco ou trilha fora do ar: nega (falha segura)
            return Motivo.ERRO_INTERNO

    def _autenticar(self, senha: str) -> Motivo:
        agora = self.relogio()
        registro = self.tentativas.obter(MATRICULA_ADMIN)
        if s1_contencao.esta_bloqueado(registro, agora):
            return Motivo.BLOQUEADO                # nem confere a senha: não vira oráculo
        if s2_conhecimento.conferir(senha, self._ler_hash(), self.custo):
            self.tentativas.salvar(s1_contencao.registrar_sucesso(MATRICULA_ADMIN))
            self._instalacao_aberta = True
            return Motivo.CONCEDIDO
        novo = s1_contencao.registrar_falha(registro, MATRICULA_ADMIN, agora, self.contencao)
        self.tentativas.salvar(novo)
        return Motivo.BLOQUEADO if s1_contencao.esta_bloqueado(novo, agora) else Motivo.SENHA_INCORRETA

    # quem é administrador
    def _usuario_ativo(self, usuario_id: int | None) -> Usuario | None:
        usuario = self.usuarios.por_id(usuario_id) if usuario_id is not None else None
        return usuario if usuario is not None and usuario.ativo else None

    def administradores_ativos(self) -> list[Administrador]:
        """Governança ativa, cadastro ativo e perfil Externo: um cadastro desativado não administra, e quem tem
        camada nunca administra."""
        ativos = []
        for a in self.administradores.listar():
            usuario = self._usuario_ativo(a.usuario_id) if a.ativo else None
            if usuario is not None and usuario.perfil is Perfil.EXTERNO:
                ativos.append(a)
        return ativos

    def _admin_ativo(self, usuario_id: int | None) -> Administrador | None:
        return next((a for a in self.administradores_ativos() if a.usuario_id == usuario_id), None)

    def eh_administrador(self, usuario_id: int | None) -> bool:
        return self._admin_ativo(usuario_id) is not None

    @property
    def administrador_vinculado(self) -> bool:
        """Já existe ao menos um administrador (a configuração inicial terminou)."""
        return bool(self.administradores_ativos())

    @property
    def exige_aprovacao(self) -> bool:
        """Fora da fase de implantação: ação crítica precisa de um segundo administrador."""
        return len(self.administradores_ativos()) >= self.governanca.minimo_administradores

    def _habilitado(self, u: Usuario, no_modelo) -> bool:
        """Ativo, não excluído, com rosto no modelo e consentimento vigente."""
        return (u.ativo and u.excluido_em is None and u.id in no_modelo
                and self.consentimentos.vigente_de(u.id) is not None)

    def candidatos_a_administrador(self) -> list[Usuario]:
        """Quem pode receber o papel de administrador: um cadastro EXTERNO, ativo, com consentimento vigente e
        rosto no modelo, que ainda não é administrador. Quem tem camada (servidor, diretor, ministro) não vira admin."""
        no_modelo = self._rotulos_modelo()
        return [u for u in self.usuarios.listar() if u.perfil is Perfil.EXTERNO and self._habilitado(u, no_modelo)
                and not self.eh_administrador(u.id)]

    def vincular_primeiro_administrador(self, usuario_id: int) -> str | None:
        """Configuração inicial: o primeiro cadastro, Externo, feito depois da senha de instalação, vira o
        primeiro administrador. Uma única vez; sem pergunta no login."""
        if self.administrador_vinculado:
            return "O sistema já tem administrador; novos administradores são designados no painel."
        if not self._instalacao_aberta:
            return "Abra a configuração inicial com a senha de instalação."
        usuario = self._usuario_ativo(usuario_id)
        if (usuario is None or usuario.perfil is not Perfil.EXTERNO
                or not self._habilitado(usuario, self._rotulos_modelo())):
            return "O primeiro administrador precisa ser um cadastro Externo, ativo, com consentimento e com rosto."
        self._registrar_obrigatorio("REGISTRADO", "ADMIN_VINCULADO", usuario_id=usuario.id,
                                    matricula_informada=usuario.matricula,
                                    detalhe="primeiro administrador, pela configuração inicial")
        self.administradores.salvar(Administrador(usuario.id, self.relogio()))
        return None

    def migrar_administrador_legado(self, matricula: str | None) -> bool:
        """Versões antigas guardavam um administrador no .env (ADMIN_MATRICULA). Na primeira abertura
        desta versão, ele passa para o banco. Só acontece com a tabela vazia. True = migrou."""
        if not matricula or self.administradores.listar():
            return False
        usuario = self.usuarios.por_matricula(matricula)
        if usuario is None:
            return False
        self._definir_perfil(usuario, Perfil.EXTERNO)                # o administrador não tem camada
        self.administradores.salvar(Administrador(usuario.id, self.relogio()))
        self._registrar("REGISTRADO", "ADMIN_MIGRADO", usuario_id=usuario.id, matricula_informada=usuario.matricula,
                        detalhe="administrador da versão anterior (.env) passou para o banco")
        return True

    # celular (TOTP) e códigos de recuperação
    def _abrir(self, cifrado: str) -> str | None:
        try:
            return self._cifra.decrypt(cifrado.encode("ascii")).decode("ascii")
        except (InvalidToken, ValueError):
            log.error("Segredo de celular que não decifra com a CHAVE_TOTP atual")
            return None

    def celular_cadastrado(self, usuario_id: int) -> bool:
        adm = self._admin_ativo(usuario_id)
        return adm is not None and adm.celular_cadastrado

    def novo_celular(self, usuario_id: int) -> NovoCelular | None:
        """Começa o cadastro do celular de um admin que ainda não tem. Nada é gravado aqui."""
        adm, usuario = self._admin_ativo(usuario_id), self._usuario_ativo(usuario_id)
        if adm is None or adm.celular_cadastrado:
            return None
        segredo = totp.gerar_segredo()
        return NovoCelular(segredo, totp.uri_provisionamento(segredo, usuario.matricula))

    def confirmar_celular(self, usuario_id: int, novo: NovoCelular, codigo: str) -> list[str] | None:
        """O primeiro código prova que o aplicativo foi configurado certo. Grava o segredo (cifrado) e
        devolve os códigos de recuperação, que a tela mostra uma vez. None = código não confere."""
        adm = self._admin_ativo(usuario_id)
        if adm is None or adm.celular_cadastrado or novo is None:
            return None
        passo = totp.conferir(novo.segredo, codigo, self.relogio())
        if passo is None:
            return None
        self._registrar_obrigatorio("REGISTRADO", "CELULAR_CADASTRADO", usuario_id=usuario_id)
        self.administradores.salvar(replace(adm, segredo_totp=self._cifra.encrypt(novo.segredo.encode()).decode(),
                                            ultimo_passo=passo))
        codigos = totp.gerar_codigos_recuperacao(self.governanca.codigos_recuperacao)
        self.administradores.trocar_codigos(usuario_id, [totp.hash_recuperacao(c) for c in codigos], self.relogio())
        return codigos

    def codigos_restantes(self, usuario_id: int) -> int:
        return len(self.administradores.codigos_validos(usuario_id))

    def _quem_tem_o_codigo(self, codigo: str, candidatos: list[Administrador]) -> list[tuple]:
        """(administrador, tipo, referência) de cada candidato com quem o código confere."""
        agora, achados = self.relogio(), []
        if totp.eh_formato_recuperacao(codigo):
            alvo = totp.hash_recuperacao(codigo)
            for a in candidatos:
                achados += [(a, "RECUPERACAO", c.id) for c in self.administradores.codigos_validos(a.usuario_id)
                            if hmac.compare_digest(c.hash_codigo, alvo)]
            return achados
        for a in candidatos:
            segredo = self._abrir(a.segredo_totp) if a.segredo_totp else None
            passo = totp.conferir(segredo, codigo, agora, a.ultimo_passo) if segredo else None
            if passo is not None:
                achados.append((a, "CELULAR", passo))
        return achados

    def _consumir(self, achado) -> bool:
        """Gasta o código (o passo do celular avança; o de recuperação fica marcado). Atômico no banco."""
        adm, tipo, referencia = achado
        if tipo == "CELULAR":
            return self.administradores.registrar_passo(adm.usuario_id, referencia)
        return self.administradores.usar_codigo(referencia, self.relogio())

    def conferir_codigo_celular(self, usuario_id: int, codigo: str) -> tuple[Motivo, datetime | None]:
        """Abrir o painel: o código do celular (ou um de recuperação) da própria pessoa.
        Devolve (motivo, bloqueado_até). Erros seguidos trancam só este passo, com os limites de [s1_contencao]."""
        try:
            adm, usuario = self._admin_ativo(usuario_id), self._usuario_ativo(usuario_id)
            if adm is None or usuario is None:
                return Motivo.USUARIO_INATIVO, None
            chave = usuario.matricula + SUFIXO_CODIGO
            bloqueio = self._bloqueado_ate(chave)
            if bloqueio is not None:
                return Motivo.BLOQUEADO, bloqueio            # nem confere: não vira oráculo
            achados = self._quem_tem_o_codigo(codigo, [adm])
            if achados and self._consumir(achados[0]):
                tipo = achados[0][1]
                self._registrar_obrigatorio("CONCEDIDO", "CODIGO_CELULAR", usuario_id=usuario_id,
                                            matricula_informada=usuario.matricula,
                                            detalhe="código de recuperação usado" if tipo == "RECUPERACAO" else None)
                self._zerar(chave)
                return Motivo.CONCEDIDO, None
            bloqueio = self._contar_falha(chave)
            self._registrar("NEGADO", Motivo.CODIGO_INCORRETO.value, usuario_id=usuario_id,
                            matricula_informada=usuario.matricula)
            return (Motivo.BLOQUEADO if bloqueio else Motivo.CODIGO_INCORRETO), bloqueio
        except Exception:  # noqa: BLE001, banco ou trilha fora do ar: nega
            log.exception("Falha ao conferir o código do celular")
            return Motivo.ERRO_INTERNO, None

    # aprovação por um segundo administrador
    def _autorizar(self, acao: AcaoCritica, solicitante_id: int | None, codigo: str | None,
                   alvo: Usuario | None = None, emergencia: Emergencia | None = None) -> tuple[int | None, str | None, str]:
        """(aprovador, recusa, como). como: APROVADA, IMPLANTACAO ou EMERGENCIA."""
        solicitante = self._usuario_ativo(solicitante_id)
        if solicitante is None or not self.eh_administrador(solicitante_id):
            return None, "Só um administrador pode fazer isso.", ""
        if emergencia is not None:
            if (not emergencia.valida(self.relogio()) or emergencia.usuario_id != solicitante_id
                    or acao not in ACOES_DE_EMERGENCIA):
                return None, "O acesso de emergência não permite esta ação (ou já expirou).", ""
            return None, None, "EMERGENCIA"
        if not self.exige_aprovacao:
            return None, None, "IMPLANTACAO"
        candidatos = [a for a in self.administradores_ativos()
                      if a.usuario_id != solicitante_id and (a.celular_cadastrado
                                                             or self.administradores.codigos_validos(a.usuario_id))]
        if not candidatos:
            return None, "Nenhum outro administrador está apto a aprovar no momento.", ""
        chave = solicitante.matricula + SUFIXO_APROVACAO
        bloqueio = self._bloqueado_ate(chave)
        if bloqueio is not None:
            return None, f"Aprovações bloqueadas por erros seguidos até as {bloqueio:%H:%M}.", ""
        achados = self._quem_tem_o_codigo(codigo or "", candidatos)
        if len(achados) > 1:      # dois admins com o mesmo código neste instante (1 em 1 milhão): pede outro
            return None, "Código não aceito. Aguarde o próximo código e tente de novo.", ""
        if achados and self._consumir(achados[0]):
            self._zerar(chave)
            return achados[0][0].usuario_id, None, "APROVADA"
        bloqueio = self._contar_falha(chave)
        self._registrar("NEGADO", "APROVACAO_RECUSADA", usuario_id=solicitante_id,
                        matricula_informada=alvo.matricula if alvo else None, detalhe=acao.descricao)
        return None, (f"Código não aceito. Aprovações bloqueadas até as {bloqueio:%H:%M}." if bloqueio
                      else "Código não aceito. Peça ao outro administrador o código atual."), ""

    def _registrar_acao(self, acao: AcaoCritica, solicitante_id: int, aprovador: int | None, como: str,
                        alvo: Usuario | None, obrigatorio: bool, extra: str = "") -> None:
        detalhe = acao.descricao + extra + {
            "IMPLANTACAO": "; fase de implantação (menos de 2 administradores)",
            "EMERGENCIA": "; ACESSO DE EMERGÊNCIA",
            "DIRETA": "; sem aprovação (perfil sem camada 3)"}.get(como, "; aprovada por outro administrador")
        registrar = self._registrar_obrigatorio if obrigatorio else self._registrar
        registrar("REGISTRADO", acao.value, usuario_id=solicitante_id, usuario2_id=aprovador,
                  matricula_informada=alvo.matricula if alvo else None, detalhe=detalhe)

    def tornar_administrador(self, solicitante_id: int, alvo_id: int, codigo: str | None = None,
                             emergencia: Emergencia | None = None) -> str | None:
        alvo = next((u for u in self.candidatos_a_administrador() if u.id == alvo_id), None)
        if alvo is None:
            return "Só um cadastro Externo, ativo, com consentimento e rosto, e que ainda não é administrador."
        if alvo_id == solicitante_id:
            return "Ninguém altera o próprio perfil."
        aprovador, recusa, como = self._autorizar(AcaoCritica.TORNAR_ADMINISTRADOR, solicitante_id, codigo, alvo,
                                                  emergencia)
        if recusa:
            return recusa
        self._registrar_acao(AcaoCritica.TORNAR_ADMINISTRADOR, solicitante_id, aprovador, como, alvo, True)
        # quem já foi admin e volta começa do zero: celular novo
        self.administradores.salvar(Administrador(alvo.id, self.relogio(), designado_por=solicitante_id,
                                                  aprovado_por=aprovador))
        self.administradores.trocar_codigos(alvo.id, [], self.relogio())
        return None

    def _sobram_administradores(self, saindo: int) -> bool:
        restantes = [a for a in self.administradores_ativos() if a.usuario_id != saindo]
        return len(restantes) >= self.governanca.minimo_administradores

    def remover_administrador(self, solicitante_id: int, alvo_id: int, codigo: str | None = None) -> str | None:
        adm, alvo = self._admin_ativo(alvo_id), self.usuarios.por_id(alvo_id)
        if adm is None:
            return "Este cadastro não é administrador."
        if not self._sobram_administradores(alvo_id):
            return (f"O sistema não pode ficar com menos de {self.governanca.minimo_administradores} "
                    "administradores. Designe outro antes de tirar este.")
        aprovador, recusa, como = self._autorizar(AcaoCritica.REMOVER_ADMINISTRADOR, solicitante_id, codigo, alvo)
        if recusa:
            return recusa
        self._encerrar_administracao(adm)                            # continua Externo, sem o papel
        self._registrar_acao(AcaoCritica.REMOVER_ADMINISTRADOR, solicitante_id, aprovador, como, alvo, False)
        return None

    def _encerrar_administracao(self, adm: Administrador) -> None:
        self.administradores.salvar(replace(adm, ativo=False, removido_em=self.relogio()))
        self.administradores.trocar_codigos(adm.usuario_id, [], self.relogio())

    def _definir_perfil(self, usuario: Usuario, perfil: Perfil, uf: str | None = None) -> Usuario:
        novo = replace(usuario, perfil=perfil, nivel=perfil.camada, uf=uf if perfil.exige_uf else None)
        self.usuarios.atualizar(novo)
        return novo

    # perfis e exclusão
    def atribuir_perfil(self, solicitante_id: int, alvo_id: int, perfil: Perfil, uf: str | None = None,
                        codigo: str | None = None) -> str | None:
        """Atribui ou troca o perfil de um cadastro. Crítico (segundo admin) quando dá a camada 3 (ministro);
        servidor, diretor e Externo, sozinho. O administrador não recebe camada: tira-se o papel antes.
        Devolve a recusa, ou None se feito."""
        perfil = Perfil(perfil)
        alvo = self.usuarios.por_id(alvo_id)
        if alvo is None:
            return "Usuário não encontrado."
        if alvo.excluido_em is not None:
            return "Cadastro excluído: não recebe perfil."
        if alvo_id == solicitante_id:
            return "Ninguém altera o próprio perfil."
        if self._admin_ativo(alvo_id) is not None:
            return ("O cadastro é de um administrador, que não tem acesso a dados: tire o papel de administrador "
                    "antes de trocar o perfil.")
        if perfil.exige_uf and uf not in UFS:
            return "O perfil de diretor exige a UF sob responsabilidade dele."
        if perfil in CRITICOS:
            aprovador, recusa, como = self._autorizar(AcaoCritica.ATRIBUIR_PERFIL, solicitante_id, codigo, alvo)
            if recusa:
                return recusa
        elif not self.eh_administrador(solicitante_id) or self._usuario_ativo(solicitante_id) is None:
            return "Só um administrador pode fazer isso."
        else:
            aprovador, como = None, "DIRETA"
        self._definir_perfil(alvo, perfil, uf)
        self._registrar_acao(AcaoCritica.ATRIBUIR_PERFIL, solicitante_id, aprovador, como, alvo, True,
                             f": {perfil.rotulo}" + (f" (UF {uf})" if perfil.exige_uf else ""))
        return None

    def excluir_usuario(self, solicitante_id: int, alvo_id: int, codigo: str | None = None) -> str | None:
        """Exclusão lógica e irreversível, ação crítica: 1º desativa e marca excluído (sem papel de admin),
        2º revoga o consentimento, 3º elimina o rosto do modelo. Nada é apagado: trilha e consentimentos são a
        prova do tratamento e do seu fim."""
        alvo = self.usuarios.por_id(alvo_id)
        if alvo is None:
            return "Usuário não encontrado."
        if alvo.excluido_em is not None:
            return "Este cadastro já foi excluído."
        if alvo_id == solicitante_id:
            return "Ninguém exclui o próprio cadastro."
        adm = self._admin_ativo(alvo_id)
        if adm is not None and not self._sobram_administradores(alvo_id):
            return (f"Este cadastro é de um administrador, e o sistema não pode ficar com menos de "
                    f"{self.governanca.minimo_administradores}. Designe outro antes.")
        aprovador, recusa, como = self._autorizar(AcaoCritica.EXCLUIR_USUARIO, solicitante_id, codigo, alvo)
        if recusa:
            return recusa
        self.usuarios.atualizar(replace(alvo, ativo=False, excluido_em=self.relogio()))     # 1º
        if adm is not None:
            self._encerrar_administracao(adm)
        self.consentimentos.revogar(alvo_id, self.relogio())                               # 2º
        self._registrar_acao(AcaoCritica.EXCLUIR_USUARIO, solicitante_id, aprovador, como, alvo, False)
        try:
            self._eliminar_biometria(alvo_id)                                               # 3º
        except Exception as erro:  # noqa: BLE001, o acesso já está bloqueado pelos passos 1 e 2
            self._registrar("REGISTRADO", "USUARIO_EXCLUIDO", usuario_id=alvo_id,
                            detalhe="FALHA ao eliminar a biometria")
            return (f"Cadastro excluído, mas o modelo facial não pôde ser atualizado ({erro}). "
                    "Peça a revogação de novo para concluir a eliminação.")
        self._registrar("REGISTRADO", "USUARIO_EXCLUIDO", usuario_id=alvo_id, detalhe="biometria eliminada do modelo")
        return None

    def refazer_celular(self, solicitante_id: int, alvo_id: int, codigo: str | None = None,
                        emergencia: Emergencia | None = None) -> str | None:
        """Apaga o celular e os códigos de recuperação do alvo; ele cadastra um novo ao abrir o painel."""
        adm, alvo = self._admin_ativo(alvo_id), self.usuarios.por_id(alvo_id)
        if adm is None:
            return "Este cadastro não é administrador."
        aprovador, recusa, como = self._autorizar(AcaoCritica.REFAZER_CELULAR, solicitante_id, codigo, alvo,
                                                  emergencia)
        if recusa:
            return recusa
        self.administradores.salvar(replace(adm, segredo_totp=None, ultimo_passo=None))
        self.administradores.trocar_codigos(alvo_id, [], self.relogio())
        self._registrar_acao(AcaoCritica.REFAZER_CELULAR, solicitante_id, aprovador, como, alvo, False)
        return None

    def registrar_revisao(self, solicitante_id: int, codigo: str | None = None) -> str | None:
        """A revisão de acessos foi feita (relatório S-10, conferido pelos administradores): fica na trilha, com os dois."""
        aprovador, recusa, como = self._autorizar(AcaoCritica.REVISAO_ACESSOS, solicitante_id, codigo)
        if recusa:
            return recusa
        self._registrar_acao(AcaoCritica.REVISAO_ACESSOS, solicitante_id, aprovador, como, None, True)
        return None

    def autorizar_recadastro_rosto(self, emergencia: Emergencia, alvo_id: int) -> str | None:
        """Dentro do acesso de emergência: recadastrar o rosto de um administrador (o cadastro faz a coleta)."""
        if emergencia is None or not emergencia.valida(self.relogio()):
            return "O acesso de emergência expirou."
        if not self.eh_administrador(emergencia.usuario_id) or not self.eh_administrador(alvo_id):
            return "Só o rosto de um administrador é recadastrado pelo acesso de emergência."
        alvo = self.usuarios.por_id(alvo_id)
        # autorizado agora; o fato (rosto trocado) é gravado pelo cadastro quando a captura terminar
        self._registrar_obrigatorio("REGISTRADO", "RECADASTRO_AUTORIZADO", usuario_id=emergencia.usuario_id,
                                    matricula_informada=alvo.matricula, detalhe="ACESSO DE EMERGÊNCIA")
        return None

    # acesso de emergência
    def pode_oferecer_emergencia(self, usuario_id: int | None) -> bool:
        """Só para admin, e só se o quórum for possível (admins com celular ou código de recuperação)."""
        if not self.eh_administrador(usuario_id):
            return False
        com_credencial = [a for a in self.administradores_ativos()
                          if a.celular_cadastrado or self.administradores.codigos_validos(a.usuario_id)]
        return len(com_credencial) >= self.governanca.quorum_emergencia

    def nova_emergencia(self, usuario_id: int) -> "SessaoEmergencia | None":
        return SessaoEmergencia(self, usuario_id) if self.pode_oferecer_emergencia(usuario_id) else None

    # usuários
    def listar(self, excluidos: bool = False) -> list[LinhaUsuario]:
        """Os cadastros, sem os excluídos, salvo quando pedidos."""
        no_modelo = self._rotulos_modelo()
        admins = {a.usuario_id: a for a in self.administradores_ativos()}
        linhas = []
        for u in self.usuarios.listar():
            if u.excluido_em is not None and not excluidos:
                continue
            vigente = self.consentimentos.vigente_de(u.id)
            adm = admins.get(u.id)
            linhas.append(LinhaUsuario(u, vigente is not None, len(self.amostras.por_usuario(u.id)),
                                       u.id in no_modelo, bool(vigente and vigente.autoriza_pesquisa),
                                       adm is not None, bool(adm and adm.celular_cadastrado)))
        return linhas

    def usuario(self, usuario_id: int) -> Usuario | None:
        return self.usuarios.por_id(usuario_id)

    def definir_ativo(self, usuario_id: int, ativo: bool, solicitante_id: int | None = None,
                      codigo: str | None = None) -> str | None:
        """Devolve uma mensagem de recusa, ou None se feito.

        Desativar o cadastro de um ADMINISTRADOR tira dele o papel: exige o segundo admin e respeita o
        mínimo de administradores. Sem isso, um admin desativaria o outro sozinho e voltaria à fase de
        implantação, onde age sem aprovação."""
        usuario = self.usuarios.por_id(usuario_id)
        if usuario is None:
            return "Usuário não encontrado."
        if ativo and usuario.excluido_em is not None:
            self._registrar("NEGADO", "REATIVACAO_DE_EXCLUIDO", usuario_id=usuario_id)
            return "Não é possível reativar: o cadastro foi excluído."
        if ativo and self.consentimentos.vigente_de(usuario_id) is None:
            self._registrar("NEGADO", "REATIVACAO_SEM_CONSENTIMENTO", usuario_id=usuario_id)
            return "Não é possível reativar: o consentimento foi revogado. É preciso um novo cadastro."
        adm = self._admin_ativo(usuario_id)
        if not ativo and adm is not None:
            if not self._sobram_administradores(usuario_id):
                return (f"Este cadastro é de um administrador, e o sistema não pode ficar com menos de "
                        f"{self.governanca.minimo_administradores}. Designe outro antes.")
            aprovador, recusa, como = self._autorizar(AcaoCritica.REMOVER_ADMINISTRADOR, solicitante_id, codigo,
                                                      usuario)
            if recusa:
                return recusa
            self.administradores.salvar(replace(adm, ativo=False, removido_em=self.relogio()))
            self._registrar_acao(AcaoCritica.REMOVER_ADMINISTRADOR, solicitante_id, aprovador, como, usuario, False)
        self.usuarios.atualizar(replace(usuario, ativo=ativo))
        self._registrar("REGISTRADO", "USUARIO_REATIVADO" if ativo else "USUARIO_DESATIVADO", usuario_id=usuario_id)
        return None

    def revogar_consentimento(self, usuario_id: int, solicitante_id: int | None = None,
                              codigo: str | None = None) -> str | None:
        """Ação crítica (elimina o rosto): com administradores no sistema, exige o segundo admin.
        Na configuração inicial (nenhum admin ainda), o painel aberto pela senha de instalação revoga."""
        usuario = self.usuarios.por_id(usuario_id)
        if usuario is None:
            return "Usuário não encontrado."
        adm = self._admin_ativo(usuario_id)
        if adm is not None and not self._sobram_administradores(usuario_id):
            return (f"Este cadastro é de um administrador, e o sistema não pode ficar com menos de "
                    f"{self.governanca.minimo_administradores}. Designe outro antes.")
        aprovador, como = None, "CONFIGURACAO"
        if self.administrador_vinculado:
            aprovador, recusa, como = self._autorizar(AcaoCritica.REVOGAR_CONSENTIMENTO, solicitante_id, codigo,
                                                      usuario)
            if recusa:
                return recusa
        self.usuarios.atualizar(replace(usuario, ativo=False))             # 1º desativa
        if adm is not None:                                                # sem cadastro ativo, sem papel
            self.administradores.salvar(replace(adm, ativo=False, removido_em=self.relogio()))
        havia = self.consentimentos.revogar(usuario_id, self.relogio())     # 2º revoga
        if como != "CONFIGURACAO":
            self._registrar_acao(AcaoCritica.REVOGAR_CONSENTIMENTO, solicitante_id, aprovador, como, usuario, False)
        try:
            self._eliminar_biometria(usuario_id)                             # 3º elimina o rosto
        except Exception as erro:  # noqa: BLE001, o acesso já está bloqueado pelos passos 1 e 2
            self._registrar("REGISTRADO", "CONSENTIMENTO_REVOGADO", usuario_id=usuario_id,
                            detalhe="FALHA ao eliminar a biometria")
            return (f"Consentimento revogado e cadastro desativado, mas o modelo facial não pôde ser "
                    f"atualizado ({erro}). Repita a revogação para concluir a eliminação.")
        self._registrar("REGISTRADO", "CONSENTIMENTO_REVOGADO", usuario_id=usuario_id,
                        detalhe="biometria eliminada do modelo")
        if not havia:
            return "Não havia consentimento vigente; o cadastro foi desativado e o rosto, eliminado."
        return None

    def dados_do_titular(self, usuario_id: int) -> str:
        """Relatório em linguagem clara do que o sistema guarda sobre a pessoa (art. 18, I e II)."""
        u = self.usuarios.por_id(usuario_id)
        if u is None:
            return "Usuário não encontrado."
        amostras = self.amostras.por_usuario(usuario_id)
        por_sessao = {}
        for a in amostras:
            por_sessao[a.sessao] = por_sessao.get(a.sessao, 0) + 1
        adm = self.administradores.obter(usuario_id)
        if adm is None:
            papel = "   Papel de administrador: não"
        else:
            papel = (f"   Papel de administrador: {'SIM' if adm.ativo else 'retirado'} "
                     f"(desde {adm.designado_em:%d/%m/%Y %H:%M}"
                     + (f"; retirado em {adm.removido_em:%d/%m/%Y %H:%M}" if adm.removido_em else "") + ")\n"
                     "   Celular do administrador: "
                     + ("cadastrado; o segredo fica cifrado e ninguém consegue lê-lo" if adm.celular_cadastrado
                        else "não cadastrado"))
        linhas = [
            "RELATÓRIO DO TITULAR · EcoSecurity (LGPD, art. 18, I e II)",
            f"Emitido em {self.relogio():%d/%m/%Y %H:%M}",
            "",
            "1. Cadastro",
            f"   Nome: {u.nome}",
            f"   Matrícula: {u.matricula}",
            f"   Perfil de acesso: {u.perfil.rotulo}" + (f" (UF {u.uf})" if u.uf else ""),
            "   Situação: " + (f"excluído em {u.excluido_em:%d/%m/%Y %H:%M}" if u.excluido_em
                                else "ativo" if u.ativo else "inativo"),
            f"   Criado em: {u.criado_em:%d/%m/%Y %H:%M}" if u.criado_em else "   Criado em: não registrado",
            "   Senha: guardada apenas como hash bcrypt (irreversível); ninguém consegue lê-la.",
            papel,
            "",
            "2. Dado biométrico",
            "   Imagens do rosto: NENHUMA guardada (descartadas após o treinamento).",
            "   Modelo matemático do rosto (LBPH, cifrado): "
            + ("PRESENTE" if usuario_id in self._rotulos_modelo() else "AUSENTE (eliminado ou nunca gravado)"),
            f"   Metadados das amostras: {len(amostras)} ("
            + (", ".join(f"sessão {s}: {n}" for s, n in sorted(por_sessao.items())) or "nenhum")
            + "). Só o número da sessão e o índice de qualidade; nenhuma imagem.",
            "",
            "3. Consentimentos",
        ]
        historico = self.consentimentos.de_usuario(usuario_id)
        for c in historico:
            situacao = f"REVOGADO em {c.revogado_em:%d/%m/%Y %H:%M}" if c.revogado_em else "VIGENTE"
            pesquisa = "AUTORIZADA" if c.autoriza_pesquisa else "NÃO autorizada"
            linhas += [f"   Termo versão {c.versao_termo}, aceito em {c.momento:%d/%m/%Y %H:%M}: {situacao}",
                       f"   Finalidade (a) autenticação: autorizada · (b) estatísticas e experimentos: {pesquisa}",
                       f"   Hash SHA-256 do texto aceito: {c.hash_termo}"]
        if not historico:
            linhas.append("   Nenhum registrado.")
        linhas += ["", "4. Compartilhamento",
                   "   Nenhum. Os dados ficam neste computador; não há envio a nuvem ou a terceiros."]
        return "\n".join(linhas)


class SessaoEmergencia:
    """Junta os códigos do quórum, em qualquer ordem. Uma por tentativa; a tela a descarta ao sair.

    Cada código é conferido contra todos os administradores ativos (inclusive quem pediu: o código
    dele prova que ele tem o celular). Precisa de quorum administradores DIFERENTES dentro de
    janela minutos contados do primeiro aceito. Erro: contenção global, mensagem genérica."""

    def __init__(self, servico: ServicoAdministracao, usuario_id: int):
        self.s, self.usuario_id = servico, usuario_id
        self._aceitos: dict[int, str] = {}           # admin -> tipo do código (celular ou recuperação)
        self._primeiro: datetime | None = None
        self.concedida: Emergencia | None = None

    @property
    def quorum(self) -> int:
        return self.s.governanca.quorum_emergencia

    def _passo(self, mensagem: str, bloqueio: datetime | None = None) -> PassoEmergencia:
        return PassoEmergencia(len(self._aceitos), self.quorum, mensagem, self.concedida, bloqueio)

    def informar(self, codigo: str) -> PassoEmergencia:
        s = self.s
        try:
            if self.concedida is not None:
                return self._passo("Acesso de emergência já concedido.")
            agora = s.relogio()
            bloqueio = s._bloqueado_ate(CHAVE_EMERGENCIA)
            if bloqueio is not None:
                return self._passo(f"Tentativas seguidas demais. Tente de novo a partir das {bloqueio:%H:%M}.",
                                   bloqueio)
            if self._primeiro is not None and agora - self._primeiro > s.governanca.janela_emergencia:
                self._aceitos.clear()
                self._primeiro = None
                minutos = int(s.governanca.janela_emergencia.total_seconds() // 60)
                return self._passo(f"O prazo de {minutos} minutos acabou. Recomece com os códigos atuais.")
            candidatos = [a for a in s.administradores_ativos() if a.usuario_id not in self._aceitos]
            achados = s._quem_tem_o_codigo(codigo or "", candidatos)
            if len(achados) == 1 and s._consumir(achados[0]):
                adm, tipo, _ = achados[0]
                self._aceitos[adm.usuario_id] = tipo
                self._primeiro = self._primeiro or agora
                if len(self._aceitos) < self.quorum:
                    return self._passo("Código aceito. Falta o código de outro administrador.")
                return self._conceder(agora)
            if len(achados) > 1:
                return self._passo("Código não aceito. Aguarde o próximo código e tente de novo.")
            bloqueio = s._contar_falha(CHAVE_EMERGENCIA)
            s._registrar("NEGADO", "EMERGENCIA_CODIGO_RECUSADO", evento="EMERGENCIA", usuario_id=self.usuario_id)
            # genérica de propósito: nunca diz qual código falhou nem se ele já foi usado
            return self._passo("Código não aceito." + (f" Tente de novo a partir das {bloqueio:%H:%M}."
                                                         if bloqueio else ""), bloqueio)
        except Exception:  # noqa: BLE001, banco ou trilha fora do ar: nega
            log.exception("Falha no acesso de emergência")
            return self._passo(Motivo.ERRO_INTERNO.mensagem)

    def _conceder(self, agora: datetime) -> PassoEmergencia:
        s = self.s
        outros = [i for i in self._aceitos if i != self.usuario_id]
        matriculas = ", ".join(s.usuarios.por_id(i).matricula for i in self._aceitos)
        tipos = ", ".join(sorted(set(self._aceitos.values())))
        s._registrar_obrigatorio("CONCEDIDO", "EMERGENCIA_ABERTA", evento="EMERGENCIA", usuario_id=self.usuario_id,
                                 usuario2_id=outros[0] if outros else None,
                                 detalhe=f"quórum: {matriculas} ({tipos.lower()})")
        s._zerar(CHAVE_EMERGENCIA)
        self.concedida = Emergencia(self.usuario_id, tuple(self._aceitos), agora,
                                    agora + s.governanca.duracao_emergencia)
        minutos = int(s.governanca.duracao_emergencia.total_seconds() // 60)
        return self._passo(f"Acesso de emergência aberto por {minutos} minutos. Só para consertar o acesso.")
