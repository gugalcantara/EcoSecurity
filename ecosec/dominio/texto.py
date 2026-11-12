"""Padronização de texto dos registros: maiúsculas, sem acento nem cedilha.

Duas regras, conforme o campo:
  - nome(): nomes e descrições (substância, município, bairro, razão social,
    título...). Só letras A-Z, dígitos e espaço; qualquer outro caractere vira
    espaço, e espaços repetidos viram um só. "Césio-137 (fonte)" -> "CESIO 137 FONTE".
  - referencia(): códigos e referências técnicas (base legal, CNAE, detalhe da
    trilha, fonte). Mesmas maiúsculas sem acento, mas mantém a pontuação que dá
    sentido ao texto: ". , ; : - / ( ) # %". "Lei 6.938/81, art. 14, §1º" ->
    "LEI 6.938/81, ART. 14, PARAGRAFO 1".

Ficam fora (o valor exato é o dado): hashes, senhas bcrypt, chaves e e-mails.
E não se reescreve o que já é prova: a trilha encadeada e o nome no
consentimento entram em hashes; registros antigos ficam como foram gravados.
"""
import re
import unicodedata

_FORA_NOME = re.compile(r"[^A-Z0-9 ]+")
_FORA_REFERENCIA = re.compile(r"[^A-Z0-9 .,;:\-/()#%]+")
_ESPACOS = re.compile(r"\s+")

# o banco repete as regras (CHECK com REGEXP_LIKE ... 'c', sensível à caixa)
PADRAO_NOME = "^[A-Z0-9 ]*$"

UNIDADES = {"T": "TONELADAS", "KG": "QUILOGRAMAS", "G": "GRAMAS", "L": "LITROS", "ML": "MILILITROS",
            "M2": "METROS QUADRADOS", "M3": "METROS CUBICOS", "HA": "HECTARES", "UN": "UNIDADES"}
# antes de decompor: o NFKD transformaria "º" em "O" ("§1º" -> "1O")
_TROCAS = str.maketrans({"º": "", "ª": "", "°": "", "§": " PARAGRAFO "})


def sem_acento(texto: str) -> str:
    """"ÁÇÕ" -> "ACO". Decompõe (NFKD) e descarta as marcas combinantes ("m³" -> "m3")."""
    decomposto = unicodedata.normalize("NFKD", texto.translate(_TROCAS))
    return "".join(c for c in decomposto if not unicodedata.combining(c))


def _limpar(texto: str | None, fora: re.Pattern) -> str | None:
    if texto is None:
        return None
    limpo = fora.sub(" ", sem_acento(str(texto)).upper())
    return _ESPACOS.sub(" ", limpo).strip()


def nome(texto: str | None) -> str | None:
    return _limpar(texto, _FORA_NOME)


def referencia(texto: str | None) -> str | None:
    return _limpar(texto, _FORA_REFERENCIA)


def unidade(sigla: str) -> str:
    """Sigla da unidade de medida por extenso ("t" -> "TONELADAS"). Já por extenso: só normaliza."""
    chave = sem_acento(sigla).upper().replace(" ", "") if sigla else ""
    if chave in UNIDADES:
        return UNIDADES[chave]
    por_extenso = nome(sigla)
    if por_extenso in UNIDADES.values():
        return por_extenso
    raise ValueError(f"Unidade de medida desconhecida: {sigla!r}")
