"""S10 Trilha: "O que aconteceu, e alguém alterou o registro?"

Cada evento é encadeado ao anterior por SHA-256:

    hash_n = SHA-256( hash_(n-1) + conteúdo_n )

Por que isso detecta adulteração:
- alterar o conteúdo de uma linha muda o hash calculado, que deixa de bater
  com o gravado -> REGISTRO_ALTERADO, na própria linha;
- alterar o conteúdo e recalcular o hash daquela linha quebra a seguinte, cujo
  hash_anterior aponta o valor antigo -> ENCADEAMENTO_ROMPIDO, na linha seguinte;
- apagar uma linha do meio também quebra a seguinte.
Em todos os casos o verificador diz onde a corrente rompeu.

Limite: quem tiver acesso administrativo ao banco pode apagar as últimas
linhas, ou recalcular toda a cauda, sem quebrar a corrente. A defesa é a
âncora: o id e o hash do último registro, numa linha de texto guardada fora do
banco (impressa em ata, ou enviada a outro computador). Conferir a âncora depois
prova que tudo até aquele registro continua igual: se ele sumiu, a cauda foi
apagada; se o hash mudou, a cauda foi recalculada. O que veio depois da âncora
só fica protegido pela âncora seguinte, por isso ela é periódica.

Por que SHA-256 aqui e bcrypt nas senhas: aqui se quer integridade, rápido e
determinístico é o certo. Para senha, rápido é o problema.

O conteúdo é serializado em JSON (lista em ordem fixa), não concatenado com um
separador: com "|" como separador, os campos ("a|b", "c") e ("a", "b|c")
produziriam o mesmo texto: e o mesmo hash.
"""
import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from ecosec.dominio.camadas import CamadaSeguranca
from ecosec.dominio.entidades import EventoTrilha, RegistroTrilha

CAMADA = CamadaSeguranca.S10_TRILHA
GENESE = "0" * 64                      # o "anterior" do primeiro registro


def _numero(valor) -> str:
    return "" if valor is None else str(int(valor))


def canonico(ev: EventoTrilha, hash_anterior: str) -> str:
    campos = [hash_anterior, ev.momento.isoformat(timespec="microseconds"), ev.evento, ev.resultado,
              ev.motivo, ev.camadas, _numero(ev.nivel_solicitado), _numero(ev.usuario_id),
              _numero(ev.usuario2_id), ev.matricula_informada or "",
              "" if ev.distancia is None else f"{ev.distancia:.4f}",     # = DECIMAL(10,4) no banco
              ev.detalhe or ""]
    return json.dumps(campos, ensure_ascii=False, separators=(",", ":"))


def calcular_hash(ev: EventoTrilha, hash_anterior: str) -> str:
    return hashlib.sha256(canonico(ev, hash_anterior).encode("utf-8")).hexdigest()


def encadear(ev: EventoTrilha, hash_anterior: str | None) -> RegistroTrilha:
    """Monta o registro a partir do último hash (None = trilha vazia)."""
    anterior = hash_anterior or GENESE
    if ev.distancia is not None:
        ev = EventoTrilha(**{**ev.__dict__, "distancia": round(float(ev.distancia), 4)})
    return RegistroTrilha(ev, anterior, calcular_hash(ev, anterior))


@dataclass(frozen=True)
class Verificacao:
    integra: bool
    registros_verificados: int
    id_rompido: int | None = None
    problema: str | None = None          # REGISTRO_ALTERADO | ENCADEAMENTO_ROMPIDO

    def __str__(self):
        if self.integra:
            return f"Trilha íntegra: {self.registros_verificados} registros conferidos."
        explicacao = {"REGISTRO_ALTERADO": "o conteúdo não corresponde ao hash gravado",
                      "ENCADEAMENTO_ROMPIDO": "o registro anterior foi alterado ou apagado"}[self.problema]
        return f"Trilha ADULTERADA no registro {self.id_rompido}: {explicacao}."


def verificar(registros: Iterable[RegistroTrilha]) -> Verificacao:
    """Percorre a trilha em ordem de id e para na primeira ruptura."""
    anterior, total = GENESE, 0
    for r in registros:
        total += 1
        if r.hash_anterior != anterior:
            return Verificacao(False, total, r.id, "ENCADEAMENTO_ROMPIDO")
        if calcular_hash(r.evento, r.hash_anterior) != r.hash_registro:
            return Verificacao(False, total, r.id, "REGISTRO_ALTERADO")
        anterior = r.hash_registro
    return Verificacao(True, total)


# ------------------------------------------------------------------ âncora fora do banco
PREFIXO_ANCORA = "ECOSEC-TRILHA"
_HEX = set("0123456789abcdef")


@dataclass(frozen=True)
class Ancora:
    """O último registro da trilha num instante: id, hash e momento. Guardada fora do banco, como uma linha."""
    id: int
    hash: str
    momento: datetime | None = None

    def texto(self) -> str:
        quando = f" {self.momento:%Y-%m-%dT%H:%M:%S}" if self.momento else ""
        return f"{PREFIXO_ANCORA} {self.id} {self.hash}{quando}"

    @classmethod
    def de_texto(cls, linha: str) -> "Ancora":
        """Lê a linha gerada por texto(). Levanta ValueError se ela não tem o formato esperado."""
        partes = linha.strip().split()
        if len(partes) not in (3, 4) or partes[0] != PREFIXO_ANCORA:
            raise ValueError(f"Linha de âncora inválida: esperado '{PREFIXO_ANCORA} <id> <hash> [momento]'.")
        try:
            ident = int(partes[1])
        except ValueError:
            raise ValueError("Linha de âncora inválida: o id não é um número.") from None
        hash_ = partes[2].lower()
        if len(hash_) != 64 or not set(hash_) <= _HEX:
            raise ValueError("Linha de âncora inválida: o hash precisa ter 64 caracteres hexadecimais.")
        momento = datetime.fromisoformat(partes[3]) if len(partes) == 4 else None
        return cls(ident, hash_, momento)


def ancora(registros: Iterable[RegistroTrilha]) -> Ancora | None:
    """A âncora do último registro, ou None com a trilha vazia."""
    ultimo = None
    for ultimo in registros:
        pass
    if ultimo is None:
        return None
    return Ancora(ultimo.id, ultimo.hash_registro, ultimo.evento.momento)


@dataclass(frozen=True)
class ConferenciaAncora:
    valida: bool
    verificacao: Verificacao
    problema: str | None = None          # TRILHA_ADULTERADA | ANCORA_AUSENTE | ANCORA_DIVERGENTE
    registros_depois: int = 0            # quantos registros vieram depois da âncora

    def __str__(self):
        if self.valida:
            return (f"Âncora confere: a trilha continua igual até o registro ancorado, e "
                    f"{self.registros_depois} registro(s) vieram depois dele.")
        if self.problema == "TRILHA_ADULTERADA":
            return str(self.verificacao)
        return {"ANCORA_AUSENTE": "Âncora NÃO confere: o registro ancorado não existe mais (registros do fim da "
                                  "trilha foram apagados).",
                "ANCORA_DIVERGENTE": "Âncora NÃO confere: o registro ancorado tem outro hash (o fim da trilha foi "
                                     "recalculado)."}[self.problema]


def conferir_ancora(registros: Iterable[RegistroTrilha], ancorada: Ancora) -> ConferenciaAncora:
    """A trilha continua íntegra e ainda contém o registro ancorado com o mesmo hash? A corrente sozinha não vê a
    cauda apagada ou recalculada; a âncora vê."""
    lista = list(registros)
    verificacao = verificar(lista)
    if not verificacao.integra:
        return ConferenciaAncora(False, verificacao, "TRILHA_ADULTERADA")
    posicao = next((i for i, r in enumerate(lista) if r.id == ancorada.id), None)
    if posicao is None:
        return ConferenciaAncora(False, verificacao, "ANCORA_AUSENTE")
    if lista[posicao].hash_registro != ancorada.hash:
        return ConferenciaAncora(False, verificacao, "ANCORA_DIVERGENTE")
    return ConferenciaAncora(True, verificacao, None, len(lista) - posicao - 1)
