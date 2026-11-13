"""S2 Conhecimento: "Sabe o segredo?"

bcrypt, e não SHA-256: o SHA-256 é rápido (bilhões por
segundo numa GPU), o que serve à integridade da trilha (S10), mas é um
desastre para senha: um vazamento seria quebrado por força bruta em horas.
O bcrypt é lento (custo 12 ≈ 0,25 s) e embute um sal aleatório:
duas pessoas com a mesma senha têm hashes diferentes.

Cuidados da verificação:
1. Tempo constante para matrícula inexistente. Sem isso, "matrícula não
   existe" responderia em 1 ms e "senha errada" em 250 ms: o cronômetro
   revelaria quais matrículas existem. Comparamos contra um hash de referência.
2. Limite de 72 bytes. O bcrypt só lê 72 bytes; o bcrypt 5 recusa o excesso em
   vez de truncar. Recusamos no cadastro e negamos no login.
3. Normalização Unicode (NFC). "ç" pode ser 1 ou 2 códigos conforme o teclado;
   sem normalizar, a mesma senha digitada em outra máquina não conferiria.
"""
import unicodedata
from dataclasses import dataclass
from functools import lru_cache

import bcrypt

from ecosec.dominio.camadas import CamadaSeguranca
from ecosec.dominio.motivos import Motivo
from ecosec.dominio.niveis import Nivel
from ecosec.seguranca.acesso.veredito import Veredito, aprovar, negar

CAMADA = CamadaSeguranca.S2_CONHECIMENTO
LIMITE_BYTES = 72

# exigência -> (descrição para a tela, teste)
EXIGENCIAS = {
    "letra": ("uma letra", lambda s: any(c.isalpha() for c in s)),
    "maiuscula": ("uma letra maiúscula", lambda s: any(c.isupper() for c in s)),
    "minuscula": ("uma letra minúscula", lambda s: any(c.islower() for c in s)),
    "digito": ("um número", lambda s: any(c.isdigit() for c in s)),
    "simbolo": ("um símbolo (ex.: # @ ! %)",
                lambda s: any(not c.isalnum() and not c.isspace() for c in s)),
}


@dataclass(frozen=True)
class PoliticaSenha:
    minimo_caracteres: int
    exigir: tuple[str, ...]

    def __post_init__(self):
        desconhecidas = set(self.exigir) - EXIGENCIAS.keys()
        if desconhecidas:
            raise ValueError(f"Exigência de senha desconhecida: {sorted(desconhecidas)}")

    @classmethod
    def de_configuracao(cls, cfg, nivel: Nivel) -> "PoliticaSenha":
        secao = cfg.secao(f"s2_conhecimento.nivel_{Nivel(nivel).value}")
        return cls(int(secao["minimo_caracteres"]), tuple(secao["exigir"]))


def _bytes(senha: str) -> bytes:
    return unicodedata.normalize("NFC", senha).encode("utf-8")


def requisitos(senha: str, politica: PoliticaSenha) -> list[tuple[str, bool]]:
    """Checklist (descrição, cumprido): a mesma lista que a tela mostra e que
    a validação usa. Assim a tela nunca marca ✓ num item que o cadastro recusa."""
    lista = [(f"ao menos {politica.minimo_caracteres} caracteres",
              len(senha) >= politica.minimo_caracteres)]
    lista += [(EXIGENCIAS[e][0], EXIGENCIAS[e][1](senha)) for e in politica.exigir]
    lista.append((f"no máximo {LIMITE_BYTES} bytes", len(_bytes(senha)) <= LIMITE_BYTES))
    return lista


def pendencias(senha: str, politica: PoliticaSenha) -> list[str]:
    return [descricao for descricao, cumprido in requisitos(senha, politica) if not cumprido]


def gerar_hash(senha: str, custo: int) -> str:
    dados = _bytes(senha)
    if len(dados) > LIMITE_BYTES:
        raise ValueError(f"Senha acima de {LIMITE_BYTES} bytes.")
    return bcrypt.hashpw(dados, bcrypt.gensalt(rounds=custo)).decode("ascii")


@lru_cache(maxsize=4)
def _hash_de_referencia(custo: int) -> bytes:
    """Hash de uma senha que ninguém conhece, com o mesmo custo dos reais."""
    return bcrypt.hashpw(b"ecosec-hash-de-referencia-para-tempo-constante", bcrypt.gensalt(rounds=custo))


def conferir(senha: str, senha_hash: str | None, custo: int) -> bool:
    """True só se o hash existe e a senha confere. Gasta o mesmo tempo em todos os casos."""
    dados = _bytes(senha)
    alvo = senha_hash.encode("ascii") if senha_hash else _hash_de_referencia(custo)
    if len(dados) > LIMITE_BYTES:
        dados = b""                      # ainda executa o bcrypt: mesmo tempo, resultado falso
        senha_hash = None
    try:
        confere = bcrypt.checkpw(dados, alvo)
    except ValueError:                   # hash corrompido no banco: nega
        return False
    return confere and senha_hash is not None


def avaliar(nivel_solicitado: Nivel, usuario_existe: bool | None, senha_confere: bool | None,
            senha_forte: bool | None) -> Veredito:
    # A força vem antes de tudo. Ela depende só do texto digitado e de uma
    # política pública: não revela nada. Na ordem inversa (conferir, depois
    # medir a força), "o nível 3 exige senha forte" só apareceria para quem
    # acertou a senha: a mensagem confirmaria ao atacante que ela estava certa.
    # O nível 3 reconfere a força no login: protege contra senha cadastrada
    # antes de a política endurecer.
    if nivel_solicitado is Nivel.N3 and senha_forte is not True:
        return negar(Motivo.SENHA_FRACA)
    if usuario_existe is not True:
        return negar(Motivo.USUARIO_INEXISTENTE)
    if senha_confere is not True:
        return negar(Motivo.SENHA_INCORRETA)
    return aprovar(CAMADA)
