"""Serviço da trilha de auditoria (S10): registrar, consultar e verificar.

Regra de ouro: sem registro, sem acesso. Se a trilha não puder ser gravada,
um acesso que seria concedido vira negação: um acesso que não deixa rastro é
indistinguível de uma invasão.

O que nunca vai para a trilha: senha (nem errada), imagem, e a distância
facial de quem não teve identidade resolvida (um número biométrico de um
desconhecido, sem finalidade de auditoria).

Visão do administrador: o administrador não lê dado do acervo, e o
detalhe das consultas e exportações carrega pedaços dele (código do caso, número
de documento, filtros de UF e de risco; nos registros antigos, até o nome de um
responsável). A trilha gravada é imutável e continua inteira (a cadeia de hash
confere sobre ela); o que o administrador recebe é uma cópia em que o detalhe
desses eventos fica só com o código do relatório.
"""
import re
from dataclasses import replace
from datetime import datetime

from ecosec.dominio import texto
from ecosec.dominio.entidades import EventoTrilha, RegistroTrilha
from ecosec.seguranca.evidencia import s10_trilha
from ecosec.seguranca.evidencia.s10_trilha import Ancora, ConferenciaAncora, Verificacao


class ServicoTrilha:
    def __init__(self, repositorio, relogio=datetime.now):
        self.repo = repositorio
        self.relogio = relogio

    def registrar(self, evento: str, resultado: str, motivo: str, **campos) -> RegistroTrilha:
        # padrão de texto do banco ANTES do hash: o encadeado é exatamente o que fica gravado
        if campos.get("detalhe") is not None:
            campos["detalhe"] = texto.referencia(campos["detalhe"])
        fato = EventoTrilha(momento=self.relogio(), evento=evento, resultado=resultado, motivo=motivo, **campos)
        return self.repo.acrescentar(lambda anterior: s10_trilha.encadear(fato, anterior))

    def verificar(self) -> Verificacao:
        return s10_trilha.verificar(self.repo.todos())

    def ancora(self) -> Ancora | None:
        """A âncora do último registro, para guardar fora do banco (None com a trilha vazia)."""
        return s10_trilha.ancora(self.repo.todos())

    def conferir_ancora(self, ancorada: Ancora) -> ConferenciaAncora:
        return s10_trilha.conferir_ancora(self.repo.todos(), ancorada)

    def recentes(self, limite: int = 200) -> list[RegistroTrilha]:
        return self.repo.recentes(limite)

    def recentes_para_administrador(self, limite: int = 200) -> list[RegistroTrilha]:
        """Os mesmos registros, com o detalhe dos eventos do acervo mascarado (só o código do relatório fica)."""
        return [para_administrador(r) for r in self.repo.recentes(limite)]


EVENTOS_DO_ACERVO = frozenset({"CONSULTA", "EXPORTACAO"})
OMITIDO = "DETALHE DO ACERVO OMITIDO"
_CODIGO_RELATORIO = re.compile(r"A[123]-\d{2}\b")


def para_administrador(registro: RegistroTrilha) -> RegistroTrilha:
    """Cópia para a visão do administrador: nas consultas e exportações do acervo, o detalhe vira só o código do
    relatório (quando houver) e o aviso de omissão. Os outros eventos (login, administração, sessão) ficam iguais."""
    evento = registro.evento
    if evento.evento not in EVENTOS_DO_ACERVO or not evento.detalhe:
        return registro
    codigo = _CODIGO_RELATORIO.match(evento.detalhe)
    detalhe = (codigo.group(0) + "; " if codigo else "") + OMITIDO
    return replace(registro, evento=replace(evento, detalhe=detalhe))
