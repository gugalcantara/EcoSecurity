"""Identificação 1:N: o sistema diz quem é, comparando com todos os cadastros, sem conceder nada.

Serve a seção "Identificação facial" do painel de Administração: só o administrador identifica
(identificar pessoas é gestão de acesso), com o painel já aberto pelo rosto e pelo celular. Não é a
sessão do N1
(ServicoAutenticacao.nova_sessao(1)): aquela decide ACESSO (nível, consentimento, contenção) e grava AUTENTICACAO
na trilha. Identificar não é autenticar: este serviço nunca cria IdentidadeComprovada nem toca na contenção.

Regras:
- IDENTIFICADO: N quadros seguidos com a mesma pessoa dentro do limiar (ConfirmadorQuadros) e a S4 aprovando
  com o limiar próprio, [identificacao] limiar, mais rígido que o do N1: no 1:N cada cadastro a mais é mais uma
  chance de falso positivo;
- Não reconhecido: [identificacao] quadros_nao_reconhecido quadros seguidos acima do limiar (~1 s), sem esperar
  o prazo, que é do acesso. O mais parecido sem cadastro válido (inativo ou sem consentimento vigente) também é
  "não reconhecido", na hora, e não cede o lugar ao segundo mais parecido; no top 3 ele aparece sem nome;
- o prazo ([reconhecimento] timeout_face_segundos) só decide quem nunca se firmou: rosto instável vira "não
  reconhecido"; nenhum rosto utilizável vira "sem rosto", sem registro (nada foi comparado);
- trilha: um registro por identificação (IDENTIFICACAO / REGISTRADO), com o operador no detalhe; usuario_id e
  distância só de quem foi identificado. O registro vem antes do resultado: se a trilha falhar, a exceção sobe à
  thread do vídeo e a tela não mostra nada (sem registro, sem resultado).

Recebe ResultadoQuadro (da visão), nunca a câmera: testável com quadros fabricados.
"""
import threading
import time
from dataclasses import dataclass

import numpy as np

from ecosec.dominio.motivos import Motivo
from ecosec.dominio.niveis import Nivel
from ecosec.seguranca.acesso import s4_inerencia
from ecosec.visao.reconhecimento import ConfirmadorQuadros

TOP = 3
CAMADAS = "S3,S4"
IDENTIFICADO = "IDENTIFICADO"


class ErroIdentificacao(Exception):
    """Pedido recusado: só o administrador identifica. A mensagem é para a tela."""


@dataclass(frozen=True)
class Candidato:
    nome: str | None                  # None: cadastro sem validade (inativo ou sem consentimento), mostrado sem nome
    distancia: float


@dataclass(frozen=True, eq=False)
class AndamentoIdentificacao:
    """O que a tela mostra agora. Imutável: a thread do vídeo cria, a da tela lê."""
    mensagem: str
    limiar: float
    progresso: float = 0.0            # 0..1, rumo à confirmação
    concluida: bool = False
    nome: str | None = None           # de quem foi identificado
    distancia: float | None = None    # do identificado; senão, a menor vista na tentativa
    candidatos: tuple = ()            # os TOP mais parecidos (Candidato), do mais ao menos parecido
    sem_rosto: bool = False
    segundos: float | None = None     # do primeiro rosto até a decisão

    @property
    def identificado(self) -> bool:
        return self.concluida and self.nome is not None


class ServicoIdentificacao:
    def __init__(self, usuarios, consentimentos, reconhecedor, *, limiar: float, quadros_confirmacao: int,
                 quadros_nao_reconhecido: int, timeout: float, trilha=None, monotonico=time.monotonic,
                 eh_administrador=None):
        self.usuarios, self.consentimentos, self.reconhecedor = usuarios, consentimentos, reconhecedor
        self.limiar, self.quadros_confirmacao = limiar, quadros_confirmacao
        self.quadros_nao_reconhecido, self.timeout = quadros_nao_reconhecido, timeout
        self.trilha = trilha                          # ServicoTrilha (None = sem auditoria, só em testes)
        self.monotonico = monotonico
        self.eh_administrador = eh_administrador or (lambda _usuario_id: False)

    @classmethod
    def de_configuracao(cls, cfg, usuarios, consentimentos, reconhecedor, trilha=None,
                        eh_administrador=None) -> "ServicoIdentificacao":
        return cls(usuarios, consentimentos, reconhecedor, limiar=float(cfg["identificacao.limiar"]),
                   quadros_confirmacao=int(cfg["reconhecimento.frames_confirmacao"]),
                   quadros_nao_reconhecido=int(cfg["identificacao.quadros_nao_reconhecido"]),
                   timeout=float(cfg["reconhecimento.timeout_face_segundos"]), trilha=trilha,
                   eh_administrador=eh_administrador)

    def nova_sessao(self, operador_id: int) -> "SessaoIdentificacao":
        """operador_id: quem está logado e pediu a identificação (vai para o detalhe da trilha). Só um
        administrador ativo identifica; os outros perfis são recusados também aqui, no serviço."""
        operador = self.usuarios.por_id(operador_id) if operador_id is not None else None
        if operador is None or not operador.ativo or not self.eh_administrador(operador.id):
            raise ErroIdentificacao("A identificação facial é do administrador.")
        return SessaoIdentificacao(self, operador_id)

    def valido(self, usuario_id: int | None):
        """O cadastro, se ativo e com consentimento vigente; senão None."""
        usuario = self.usuarios.por_id(usuario_id) if usuario_id is not None else None
        if usuario is None or not usuario.ativo or self.consentimentos.vigente_de(usuario.id) is None:
            return None
        return usuario

    def candidatos(self, face: np.ndarray) -> tuple:
        """A menor distância a cada pessoa do modelo (1:1 com cada uma), as TOP menores."""
        medidas = sorted((d, r) for r in self.reconhecedor.rotulos()
                         if (d := self.reconhecedor.verificar(face, r)) is not None)
        return tuple(Candidato(u.nome if (u := self.valido(r)) else None, d) for d, r in medidas[:TOP])


class SessaoIdentificacao:
    def __init__(self, servico: ServicoIdentificacao, operador_id: int):
        self.s = servico
        operador = servico.usuarios.por_id(operador_id)
        if operador is None:
            raise ValueError("A identificação parte de um usuário logado.")
        self._operador = operador.nome
        self._lock = threading.Lock()
        self._confirmador = ConfirmadorQuadros(servico.quadros_confirmacao, servico.limiar)
        self._acima = 0                               # quadros seguidos acima do limiar
        self._menor: float | None = None
        self._comparou = False
        self._inicio = self._primeiro_rosto = None
        self._ultima_face = None
        self._andamento = AndamentoIdentificacao("Olhe para a câmera.", servico.limiar)

    @property
    def andamento(self) -> AndamentoIdentificacao:
        with self._lock:
            return self._andamento

    def processar(self, r) -> AndamentoIdentificacao:
        """Um quadro da visão (ResultadoQuadro)."""
        with self._lock:
            if self._andamento.concluida:
                return self._andamento
            agora = self.s.monotonico()
            if self._inicio is None:
                self._inicio = agora                  # o prazo conta do 1º quadro, não da câmera abrindo
            if r.quantidade_faces and self._primeiro_rosto is None:
                self._primeiro_rosto = agora
            if r.quantidade_faces != 1 or r.face_normalizada is None:
                self._acima = 0
                if r.quantidade_faces > 1:
                    self._confirmador.reiniciar()     # uma pessoa por vez
                mensagem = r.dica or "Mantenha o rosto parado no centro da imagem."
            else:
                self._ultima_face = r.face_normalizada
                decidido = self._medir(r.face_normalizada, agora)
                if decidido is not None:
                    return decidido
                mensagem = "Identificando… mantenha o rosto parado."
            if agora - self._inicio > self.s.timeout:
                return self._prazo(agora)
            return self._atualizar(mensagem)

    def _medir(self, face, agora):
        resultado = self.s.reconhecedor.identificar(face)
        rotulo, distancia = resultado if resultado else (None, None)
        self._comparou = True
        if distancia is not None and (self._menor is None or distancia < self._menor):
            self._menor = distancia
        if s4_inerencia.avaliar(Nivel.N1, distancia, rotulo, {Nivel.N1: self.s.limiar}).aprovado:
            self._acima = 0
            confirmado = self._confirmador.alimentar(rotulo, distancia)
            if confirmado:
                return self._confirmado(*confirmado, agora)
            return None
        self._acima += 1
        self._confirmador.reiniciar()
        if self._acima >= self.s.quadros_nao_reconhecido:
            return self._nao_reconhecido(agora)
        return None

    def _confirmado(self, rotulo: int, distancia_media: float, agora) -> AndamentoIdentificacao:
        usuario = self.s.valido(rotulo)
        if usuario is None:
            return self._nao_reconhecido(agora)
        self._registrar(IDENTIFICADO, usuario_id=usuario.id, distancia=distancia_media,
                        detalhe=f"operador: {self._operador}; distancia: {distancia_media:.4f}")
        return self._concluir(f"Identificado: {usuario.nome}", agora, nome=usuario.nome, distancia=distancia_media)

    def _nao_reconhecido(self, agora) -> AndamentoIdentificacao:
        self._registrar(Motivo.FACE_NAO_RECONHECIDA.value, detalhe=f"operador: {self._operador}")
        return self._concluir("Não reconhecido", agora, distancia=self._menor)

    def _prazo(self, agora) -> AndamentoIdentificacao:
        if self._comparou:                            # houve rosto, mas não se firmou
            return self._nao_reconhecido(agora)
        return self._concluir("Nenhum rosto utilizável diante da câmera.", agora, sem_rosto=True, candidatos=())

    def _concluir(self, mensagem, agora, *, candidatos=None, **campos) -> AndamentoIdentificacao:
        if candidatos is None:
            candidatos = self.s.candidatos(self._ultima_face) if self._ultima_face is not None else ()
        self._ultima_face = None                      # decidido: a face não fica na memória da sessão
        segundos = agora - self._primeiro_rosto if self._primeiro_rosto is not None else None
        self._andamento = AndamentoIdentificacao(mensagem, self.s.limiar, progresso=1.0, concluida=True,
                                                 candidatos=candidatos, segundos=segundos, **campos)
        return self._andamento

    def _atualizar(self, mensagem) -> AndamentoIdentificacao:
        self._andamento = AndamentoIdentificacao(
            mensagem, self.s.limiar, progresso=self._confirmador.confirmados / self.s.quadros_confirmacao,
            distancia=self._menor)
        return self._andamento

    def _registrar(self, motivo: str, *, usuario_id=None, distancia=None, detalhe=None) -> None:
        if self.s.trilha is not None:
            self.s.trilha.registrar("IDENTIFICACAO", "REGISTRADO", motivo, camadas=CAMADAS, usuario_id=usuario_id,
                                    distancia=distancia, detalhe=detalhe)
