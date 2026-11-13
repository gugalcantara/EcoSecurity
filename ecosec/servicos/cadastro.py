"""Cadastro de usuário: termo -> dados -> senha -> rosto -> matrícula.

Feito só pelo administrador, dentro da Administração. Se qualquer pessoa pudesse
se cadastrar escolhendo o nível, o cadastro contornaria todo o controle de acesso.

Ordem obrigatória:
1. TERMO primeiro: o consentimento precisa existir antes da câmera abrir
   (LGPD art. 11, I). O próprio serviço recusa abrir a coleta sem aceite.
   O aceite fica em memória e só é gravado junto com o usuário, ao concluir:
   quem desiste no meio não deixa nome nem aceite no banco (minimização,
   art. 6º, III). O momento gravado é o do aceite: a prova de que ele veio
   antes da captura continua lá.
2. As faces ficam só em memória (ColetaFacial). Treinam o modelo e são
   apagadas: inclusive se o cadastro falhar no meio (bloco finally).
3. Se algo falhar depois de o usuário existir, ele é desativado: um usuário
   ativo sem rosto no modelo só seria descoberto na primeira tentativa dele.
"""
import secrets
import threading
from collections import Counter
from dataclasses import dataclass, field, replace
from datetime import datetime

import numpy as np

from ecosec.dominio import termo, texto
from ecosec.dominio.entidades import Amostra, Consentimento, ErroDominio, UFS, Usuario
from ecosec.dominio.niveis import Nivel
from ecosec.dominio.perfis import Perfil
from ecosec.repositorios.contratos import RegistroInexistente
from ecosec.seguranca.acesso import s2_conhecimento
from ecosec.seguranca.acesso.s2_conhecimento import PoliticaSenha

# sem I, O, 0 e 1: a matrícula é lida de um crachá e digitada no login
ALFABETO_MATRICULA = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


class ErroCadastro(Exception):
    pass


# coleta facial
@dataclass(frozen=True)
class EstadoColeta:
    sessao: int
    total_sessoes: int
    aceitas: int                  # na sessão atual
    meta: int
    sessao_completa: bool
    concluida: bool
    orientacao: str | None        # o que a pessoa deve fazer agora
    recusas: dict = field(default_factory=dict)   # motivo -> quantidade, na sessão


class ColetaFacial:
    """Amostras de uma pessoa, por sessão. Só em memória; descartar() zera tudo."""

    def __init__(self, sessoes: int, por_sessao: int, diferenca_minima: float):
        self.total_sessoes, self.meta, self.diferenca_minima = sessoes, por_sessao, diferenca_minima
        self.sessao = 1
        self._faces: list[np.ndarray] = []
        self._metadados: list[tuple[int, float]] = []     # (sessão, qualidade)
        self._recusas: Counter = Counter()
        self._ultima: np.ndarray | None = None
        self._lock = threading.Lock()

    def _aceitas_na_sessao(self) -> int:
        return sum(1 for s, _ in self._metadados if s == self.sessao)

    def estado(self, orientacao: str | None = None) -> EstadoColeta:
        aceitas = self._aceitas_na_sessao()
        completa = aceitas >= self.meta
        return EstadoColeta(self.sessao, self.total_sessoes, aceitas, self.meta, completa,
                            completa and self.sessao >= self.total_sessoes, orientacao,
                            dict(self._recusas))

    def oferecer(self, r) -> EstadoColeta:
        """Recebe um ResultadoQuadro da visão; aceita a face se ela acrescenta informação."""
        with self._lock:
            if self._aceitas_na_sessao() >= self.meta:
                return self.estado("Sessão concluída")
            if r.face_normalizada is None:
                motivo = r.dica or "Imagem recusada"
                self._recusas[motivo] += 1
                return self.estado(motivo)
            face = r.face_normalizada
            if self._ultima is not None and float(np.mean(np.abs(
                    face.astype(np.int16) - self._ultima.astype(np.int16)))) < self.diferenca_minima:
                self._recusas["Mova levemente a cabeça entre as capturas"] += 1
                return self.estado("Mova levemente a cabeça entre as capturas")
            self._faces.append(face.copy())
            self._metadados.append((self.sessao, r.medidas.score if r.medidas else 0.0))
            self._ultima = face
            return self.estado("Continue movendo a cabeça devagar.")

    def avancar_sessao(self) -> None:
        with self._lock:
            if self._aceitas_na_sessao() < self.meta:
                raise ErroCadastro("A sessão atual ainda não terminou.")
            if self.sessao >= self.total_sessoes:
                raise ErroCadastro("Todas as sessões já foram feitas.")
            self.sessao += 1
            self._ultima = None
            self._recusas.clear()

    @property
    def concluida(self) -> bool:
        return self.estado().concluida

    def faces(self) -> list[np.ndarray]:
        return list(self._faces)

    def metadados(self) -> list[tuple[int, float]]:
        return list(self._metadados)

    def descartar(self) -> None:
        """Sobrescreve e solta as faces (LGPD art. 6º, III: necessidade)."""
        with self._lock:
            for face in self._faces:
                face.fill(0)
            self._faces.clear()
            self._metadados.clear()
            if self._ultima is not None:
                self._ultima = None


# serviço
@dataclass(frozen=True)
class DadosCadastro:
    """O que o formulário entrega. O perfil decide; quem ainda passa só o nível recebe o perfil
    equivalente (1 servidor, 2 diretor, 3 ministro)."""
    nome: str
    nivel: Nivel | None
    uf: str | None
    senha: str = field(repr=False)
    confirmacao: str = field(repr=False)
    perfil: Perfil | None = None

    @property
    def perfil_efetivo(self) -> Perfil | None:
        if self.perfil is not None:
            return Perfil(self.perfil)
        try:
            return Perfil.do_nivel(self.nivel) if self.nivel is not None else None
        except ValueError:
            return None


class ServicoCadastro:
    def __init__(self, usuarios, consentimentos, amostras, reconhecedor, *, custo_bcrypt: int,
                 politicas: dict, tamanho_matricula: int, sessoes: int, frames_por_sessao: int,
                 diferenca_minima: float, versao_termo: str, contato_controlador: str,
                 leitura_minima_segundos: int = 0, relogio=datetime.now, ao_alterar_modelo=None, trilha=None):
        self.usuarios, self.consentimentos, self.amostras = usuarios, consentimentos, amostras
        self.reconhecedor = reconhecedor
        self.custo = custo_bcrypt
        self.politicas = politicas
        self.tamanho_matricula = tamanho_matricula
        self.sessoes, self.frames_por_sessao, self.diferenca_minima = sessoes, frames_por_sessao, diferenca_minima
        self.versao_termo = versao_termo
        self.contato = contato_controlador
        # tempo mínimo com o termo aberto antes de o aceite ser liberado: impede
        # o "aceito" no primeiro segundo, sem leitura (consentimento informado)
        self.leitura_minima_segundos = leitura_minima_segundos
        self.relogio = relogio
        self.ao_alterar_modelo = ao_alterar_modelo
        self.trilha = trilha

    @classmethod
    def de_configuracao(cls, cfg, usuarios, consentimentos, amostras, reconhecedor, **extra):
        c = cfg.secao("cadastro")
        return cls(usuarios, consentimentos, amostras, reconhecedor,
                   custo_bcrypt=int(cfg["s2_conhecimento.custo_bcrypt"]),
                   politicas={n: PoliticaSenha.de_configuracao(cfg, n) for n in Nivel},
                   tamanho_matricula=int(c["tamanho_matricula"]), sessoes=int(c["sessoes"]),
                   frames_por_sessao=int(c["frames_por_sessao"]),
                   diferenca_minima=float(c["diferenca_minima_duplicata"]),
                   versao_termo=str(cfg["lgpd.versao_termo"]), contato_controlador=str(cfg["lgpd.contato"]),
                   leitura_minima_segundos=int(cfg["lgpd.leitura_minima_segundos"]), **extra)

    # etapa 1: termo
    def texto_termo(self, nome: str, autoriza_pesquisa: bool | None = None) -> str:
        return termo.renderizar(nome, self.contato, autoriza_pesquisa)

    def termo_html(self, nome: str, autoriza_pesquisa: bool | None = None) -> str:
        return termo.renderizar_html(nome, self.contato, autoriza_pesquisa)

    def via_do_titular_html(self, aceite: Consentimento, matricula: str | None = None) -> str:
        """A via assinada, com o momento e o hash DO ACEITE registrado (não recalculados)."""
        return termo.via_do_titular_html(aceite.titular_nome, self.contato, aceite.autoriza_pesquisa,
                                         aceite.momento, aceite.hash_termo, matricula)

    def registrar_aceite(self, nome: str, autoriza_pesquisa: bool = False) -> Consentimento:
        """Aceite em memória (sem id). Só vai ao banco em concluir.

        autoriza_pesquisa é a finalidade (b), opcional. A escolha entra no
        texto cujo hash é gravado: o hash prova o que foi lido e o que foi escolhido."""
        # padronizado antes do hash: o termo assinado traz o nome como ele fica gravado
        nome = texto.nome(nome) or ""
        if len(nome) < 3:
            raise ErroCadastro("Digite o nome completo como assinatura.")
        if self.versao_termo != termo.VERSAO:
            # o config promete uma versão e o código apresenta outra: não aceitar
            raise ErroCadastro("Versão do termo divergente da configuração.")
        autoriza_pesquisa = bool(autoriza_pesquisa)
        return Consentimento(titular_nome=nome, versao_termo=termo.VERSAO,
                             hash_termo=termo.calcular_hash(self.texto_termo(nome, autoriza_pesquisa)),
                             momento=self.relogio(), autoriza_pesquisa=autoriza_pesquisa)

    # etapa 2: dados
    def politica(self, perfil_ou_nivel) -> PoliticaSenha:
        """A política de senha da camada do perfil. Sem camada (administrador, sem perfil), a mais forte: quem está
        sem perfil pode receber a camada 3 depois, e não há troca de senha."""
        if isinstance(perfil_ou_nivel, Perfil):
            camada = perfil_ou_nivel.camada or Nivel.N3
        else:
            camada = Nivel(perfil_ou_nivel)
        return self.politicas[camada]

    def requisitos_senha(self, senha: str, perfil_ou_nivel) -> list[tuple[str, bool]]:
        """Checklist para a tela: a mesma lista que validar usa."""
        return s2_conhecimento.requisitos(senha, self.politica(perfil_ou_nivel))

    def validar(self, d: DadosCadastro) -> list[str]:
        erros = []
        if len(" ".join(d.nome.split())) < 3:
            erros.append("Informe o nome completo.")
        perfil = d.perfil_efetivo
        if perfil is None:
            return erros + ["Escolha um perfil de acesso."]
        if perfil.exige_uf and d.uf not in UFS:
            erros.append("O perfil de diretor exige a UF sob responsabilidade dele.")
        erros += [f"Senha: falta {p}." for p in s2_conhecimento.pendencias(d.senha, self.politica(perfil))]
        if d.senha != d.confirmacao:
            erros.append("A confirmação não é igual à senha.")
        return erros

    # etapa 3: rosto
    def nova_coleta(self, aceite: Consentimento | None) -> ColetaFacial:
        """Sem aceite vigente, nenhuma imagem é coletada: regra do serviço, não só da tela."""
        if aceite is None or not aceite.vigente or not aceite.hash_termo:
            raise ErroCadastro("Sem consentimento não há captura facial (LGPD art. 11, I).")
        return ColetaFacial(self.sessoes, self.frames_por_sessao, self.diferenca_minima)

    # recadastro do rosto
    def nova_coleta_recadastro(self, usuario_id: int) -> ColetaFacial:
        """Mesmo consentimento, rosto novo (por exemplo, quando o modelo deixou de reconhecer a pessoa).
        Sem consentimento vigente, nenhuma imagem é coletada."""
        usuario = self.usuarios.por_id(usuario_id)
        if usuario is None or not usuario.ativo or self.consentimentos.vigente_de(usuario_id) is None:
            raise ErroCadastro("Sem cadastro ativo com consentimento vigente não há captura facial (LGPD art. 11, I).")
        return ColetaFacial(self.sessoes, self.frames_por_sessao, self.diferenca_minima)

    def substituir_rosto(self, usuario_id: int, coleta: ColetaFacial) -> None:
        """Troca o rosto da pessoa no modelo: o antigo sai, o novo entra. As faces são descartadas sempre."""
        try:
            if not coleta.concluida:
                raise ErroCadastro("A captura facial não foi concluída.")
            self.nova_coleta_recadastro(usuario_id)            # confere de novo cadastro e consentimento
            self.reconhecedor.remover(usuario_id)
            self.reconhecedor.adicionar(coleta.faces(), usuario_id)
            self.amostras.registrar([Amostra(usuario_id, sessao, "webcam", qualidade)
                                     for sessao, qualidade in coleta.metadados()])
            if self.trilha is not None:
                self.trilha.registrar("CADASTRO", "REGISTRADO", "ROSTO_SUBSTITUIDO", usuario_id=usuario_id,
                                      detalhe="rosto recadastrado; o modelo anterior da pessoa foi eliminado")
            if self.ao_alterar_modelo:
                self.ao_alterar_modelo()
        finally:
            coleta.descartar()

    # etapa 4: conclusão
    def gerar_matricula(self) -> str:
        for _ in range(100):
            matricula = "".join(secrets.choice(ALFABETO_MATRICULA) for _ in range(self.tamanho_matricula))
            if self.usuarios.por_matricula(matricula) is None:
                return matricula
        raise ErroCadastro("Não foi possível gerar uma matrícula livre.")

    def concluir(self, d: DadosCadastro, consentimento: Consentimento, coleta: ColetaFacial) -> Usuario:
        usuario = None
        try:
            erros = self.validar(d)
            if erros:
                raise ErroCadastro(" ".join(erros))
            if not coleta.concluida:
                raise ErroCadastro("A captura facial não foi concluída.")
            if consentimento is None or not consentimento.vigente or not consentimento.hash_termo:
                raise ErroCadastro("Sem consentimento não há cadastro.")
            perfil = d.perfil_efetivo
            try:
                usuario = self.usuarios.adicionar(Usuario(
                    matricula=self.gerar_matricula(), nome=" ".join(d.nome.split()), nivel=None, perfil=perfil,
                    senha_hash=s2_conhecimento.gerar_hash(d.senha, self.custo),
                    uf=d.uf if perfil.exige_uf else None))
            except ErroDominio as erro:
                raise ErroCadastro(str(erro)) from None
            self.consentimentos.registrar(replace(consentimento, usuario_id=usuario.id))
            self.reconhecedor.adicionar(coleta.faces(), usuario.id)       # rótulo LBPH = id
            self.amostras.registrar([Amostra(usuario.id, sessao, "webcam", qualidade)
                                     for sessao, qualidade in coleta.metadados()])
            if self.trilha is not None:          # cadastro sem registro não se conclui
                self.trilha.registrar("CADASTRO", "REGISTRADO", "CADASTRO_CONCLUIDO",
                                      nivel_solicitado=perfil.camada.value if perfil.camada else None,
                                      usuario_id=usuario.id,
                                      detalhe=f"perfil {perfil.value}; termo v{consentimento.versao_termo}")
            if self.ao_alterar_modelo:
                self.ao_alterar_modelo()
            return usuario
        except Exception:
            if usuario is not None:          # existe no banco, mas o cadastro não fechou
                try:
                    self.usuarios.atualizar(replace(usuario, ativo=False))
                except RegistroInexistente:
                    pass
            raise
        finally:
            coleta.descartar()                # em qualquer saída
