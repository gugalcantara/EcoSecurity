"""Segredos do sistema, no arquivo .env (fora do controle de versão).

Ficam aqui, e não no config/ecosec.toml, os valores que não podem vazar:
    CHAVE_CIFRAGEM     chave Fernet que cifra o modelo facial
    CHAVE_TOTP         chave Fernet que cifra os segredos do código do celular dos administradores
    ADMIN_SENHA_HASH   hash bcrypt da senha de INSTALAÇÃO (só abre a configuração inicial)
    ADMIN_MATRICULA    (legado) o administrador único das versões antigas; migrado para o banco

Leitura com interpolate=False: o python-dotenv expande "${VAR}" até entre
aspas simples. Uma senha ou chave que contivesse "${" seria corrompida em
silêncio na leitura.

PROTEÇÃO PELO WINDOWS (DPAPI). No Windows, cada VALOR é gravado como
"dpapi:<base64>": o Windows o cifra com uma chave presa à conta de usuário
deste computador. O programa lê normalmente; quem copiar o arquivo para outro
PC (pen drive, nuvem, vírus) leva só texto ilegível. O nome de cada chave
continua legível, para dar para saber o que o arquivo guarda.
- Protege contra cópia do arquivo, backup vazado e outra conta do Windows.
- Não protege contra quem (ou o que) roda como você, logado na sua conta.
- Reinstalar o Windows ou trocar de conta torna o arquivo ilegível também para
  nós: por isso existe o backup protegido por frase-senha
  (python -m ferramentas.proteger_segredos --backup ARQUIVO), guardado fora do PC.
Valores antigos, em texto puro, continuam sendo lidos; a mesma ferramenta, sem
argumentos, converte todos de uma vez.
"""
import base64
import json
import sys
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from dotenv import dotenv_values, set_key, unset_key

from ecosec.configuracao import RAIZ_PROJETO

CAMINHO_PADRAO = RAIZ_PROJETO / ".env"
CHAVE_CIFRAGEM = "CHAVE_CIFRAGEM"
CHAVE_TOTP = "CHAVE_TOTP"
# chave da marca d'água (S9): embaralha as posições da marca; sem ela não se lê nem se apaga a marca
CHAVE_MARCA = "CHAVE_MARCA"
ADMIN_SENHA_HASH = "ADMIN_SENHA_HASH"
ADMIN_MATRICULA = "ADMIN_MATRICULA"
# contas do MySQL, criadas por ferramentas/preparar_banco.py
DB_SEGURANCA_USUARIO, DB_SEGURANCA_SENHA = "DB_SEGURANCA_USUARIO", "DB_SEGURANCA_SENHA"
DB_ACERVO_USUARIO, DB_ACERVO_SENHA = "DB_ACERVO_USUARIO", "DB_ACERVO_SENHA"
DB_TESTE_USUARIO, DB_TESTE_SENHA = "DB_TESTE_USUARIO", "DB_TESTE_SENHA"

PREFIXO_DPAPI = "dpapi:"
# "entropia" do DPAPI: um segundo ingrediente da chave, próprio do EcoSecurity
_ENTROPIA = b"EcoSecurity/segredos/v1"
_SEM_INTERFACE = 0x1                    # CRYPTPROTECT_UI_FORBIDDEN: nunca abrir janela do Windows


class ErroSegredo(RuntimeError):
    """O .env existe, mas um valor não pôde ser aberto. A mensagem diz o que fazer."""


def dpapi_disponivel() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import win32crypt  # noqa: F401
    except ImportError:
        return False
    return True


def _proteger(valor: str) -> str:
    import win32crypt
    cifrado = win32crypt.CryptProtectData(valor.encode("utf-8"), "EcoSecurity", _ENTROPIA, None, None,
                                          _SEM_INTERFACE)
    return PREFIXO_DPAPI + base64.b64encode(cifrado).decode("ascii")


def _abrir(nome: str, valor: str) -> str:
    if not valor.startswith(PREFIXO_DPAPI):
        return valor                                    # legado: texto puro
    if not dpapi_disponivel():
        raise ErroSegredo(f"O segredo {nome} foi protegido pelo Windows e só abre no Windows.")
    import win32crypt
    try:
        _, aberto = win32crypt.CryptUnprotectData(base64.b64decode(valor[len(PREFIXO_DPAPI):]), _ENTROPIA,
                                                  None, None, _SEM_INTERFACE)
    except Exception:  # noqa: BLE001, pywintypes.error: outra conta, outro PC ou valor corrompido
        raise ErroSegredo(
            f"O segredo {nome} do .env não abre nesta conta do Windows. O arquivo foi protegido em outro "
            "computador ou em outra conta (ou o Windows foi reinstalado).\nRestaure o backup com:  "
            ".venv\\Scripts\\python.exe -m ferramentas.proteger_segredos --restaurar ARQUIVO") from None
    return aberto.decode("utf-8")


def ler(nome: str, caminho: Path = CAMINHO_PADRAO) -> str | None:
    if not Path(caminho).exists():
        return None
    valor = dotenv_values(caminho, interpolate=False).get(nome)
    return _abrir(nome, valor) if valor else None


def gravar(nome: str, valor: str, caminho: Path = CAMINHO_PADRAO) -> None:
    caminho = Path(caminho)
    caminho.touch(exist_ok=True)
    guardado = _proteger(valor) if dpapi_disponivel() else valor
    set_key(caminho, nome, guardado, quote_mode="always", encoding="utf-8")


def apagar(nome: str, caminho: Path = CAMINHO_PADRAO) -> None:
    if Path(caminho).exists() and nome in dotenv_values(caminho, interpolate=False):
        unset_key(caminho, nome, encoding="utf-8")


def nomes(caminho: Path = CAMINHO_PADRAO) -> list[str]:
    return list(dotenv_values(caminho, interpolate=False)) if Path(caminho).exists() else []


def proteger_existentes(caminho: Path = CAMINHO_PADRAO) -> int:
    """Converte os valores ainda em texto puro para DPAPI. Devolve quantos converteu."""
    if not dpapi_disponivel() or not Path(caminho).exists():
        return 0
    convertidos = 0
    for nome, valor in dotenv_values(caminho, interpolate=False).items():
        if valor and not valor.startswith(PREFIXO_DPAPI):
            gravar(nome, valor, caminho)
            convertidos += 1
    return convertidos


# ---------------------------------------------------------------- backup (o "envelope" fora do PC)
# O backup precisa abrir em outro computador, então não pode usar DPAPI: os
# segredos são cifrados com uma chave derivada de uma FRASE-SENHA (scrypt, que é
# lento de propósito, para encarecer a adivinhação) e guardados num arquivo.
_SCRYPT = {"n": 2 ** 15, "r": 8, "p": 1}
FRASE_MINIMA = 12


def _chave_da_frase(frase: str, sal: bytes, n: int, r: int, p: int) -> bytes:
    from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
    return base64.urlsafe_b64encode(Scrypt(salt=sal, length=32, n=n, r=r, p=p).derive(frase.encode("utf-8")))


def exportar_backup(frase: str, caminho: Path = CAMINHO_PADRAO) -> bytes:
    """Todos os segredos, abertos e de novo cifrados pela frase-senha. Devolve o conteúdo do arquivo."""
    import secrets
    if len(frase) < FRASE_MINIMA:
        raise ErroSegredo(f"A frase-senha do backup precisa de pelo menos {FRASE_MINIMA} caracteres.")
    valores = {nome: ler(nome, caminho) for nome in nomes(caminho)}
    sal = secrets.token_bytes(16)
    token = Fernet(_chave_da_frase(frase, sal, **_SCRYPT)).encrypt(json.dumps(valores).encode("utf-8"))
    return json.dumps({"formato": "ecosec-backup-segredos/1", "kdf": "scrypt", **_SCRYPT,
                       "sal": base64.b64encode(sal).decode("ascii"), "dados": token.decode("ascii")},
                      indent=2).encode("utf-8")


def importar_backup(conteudo: bytes, frase: str) -> dict[str, str]:
    try:
        pacote = json.loads(conteudo)
        chave = _chave_da_frase(frase, base64.b64decode(pacote["sal"]), pacote["n"], pacote["r"], pacote["p"])
        return json.loads(Fernet(chave).decrypt(pacote["dados"].encode("ascii")))
    except InvalidToken:
        raise ErroSegredo("Frase-senha incorreta (ou arquivo de backup alterado).") from None
    except (ValueError, KeyError, TypeError):
        raise ErroSegredo("Este arquivo não é um backup de segredos do EcoSecurity.") from None


# ---------------------------------------------------------------- chaves
def _garantir_fernet(nome: str, caminho: Path) -> bytes:
    existente = ler(nome, caminho)
    if existente:
        return existente.encode("ascii")
    nova = Fernet.generate_key()
    gravar(nome, nova.decode("ascii"), caminho)
    return nova


def garantir_chave_cifragem(caminho: Path = CAMINHO_PADRAO) -> bytes:
    """A chave existente nunca é trocada: com outra chave, o modelo já salvo
    (com os rostos cadastrados) ficaria ilegível."""
    return _garantir_fernet(CHAVE_CIFRAGEM, caminho)


def garantir_chave_totp(caminho: Path = CAMINHO_PADRAO) -> bytes:
    """Chave própria dos segredos TOTP (não a do modelo facial): quem obtiver uma não abre a outra.
    Também nunca é trocada: com outra, todo administrador teria de recadastrar o celular."""
    return _garantir_fernet(CHAVE_TOTP, caminho)


def garantir_chave_marca(caminho: Path = CAMINHO_PADRAO) -> bytes:
    """Como a de cifragem, nunca é trocada: com outra chave, as marcas já
    embutidas em material exportado não poderiam mais ser lidas."""
    existente = ler(CHAVE_MARCA, caminho)
    if existente:
        return existente.encode("ascii")
    import secrets
    nova = secrets.token_hex(32)
    gravar(CHAVE_MARCA, nova, caminho)
    return nova.encode("ascii")
