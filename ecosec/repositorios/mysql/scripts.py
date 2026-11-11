"""Execução dos scripts em sql/: divide o arquivo em comandos.

O driver removeu `execute(..., multi=True)`. Dividir o texto em ";" à toa
quebraria um ";" dentro de um texto ('a; b'), e remover "--" à toa apagaria
um "--" dentro de um texto. Este leitor percorre caractere a caractere,
sabendo quando está dentro de aspas.
"""

from ecosec.configuracao import RAIZ_PROJETO

PASTA_SQL = RAIZ_PROJETO / "sql"
SCRIPTS = {
    "seguranca": ("seguranca/01_schema.sql", "seguranca/02_referencia.sql"),
    "acervo": ("acervo/01_schema.sql", "acervo/02_referencia.sql"),
}


def dividir(texto: str) -> list[str]:
    comandos, atual = [], []
    aspas = None                 # None, "'" ou '"'
    i = 0
    while i < len(texto):
        ch = texto[i]
        if aspas:
            atual.append(ch)
            if ch == "\\" and i + 1 < len(texto):          # \' escapado
                atual.append(texto[i + 1])
                i += 1
            elif ch == aspas:
                if i + 1 < len(texto) and texto[i + 1] == aspas:   # '' escapado
                    atual.append(texto[i + 1])
                    i += 1
                else:
                    aspas = None
        elif ch in ("'", '"', "`"):
            aspas = ch
            atual.append(ch)
        elif texto.startswith("--", i) and (i + 2 >= len(texto) or texto[i + 2] in " \t\r\n"):
            fim = texto.find("\n", i)                      # comentário até o fim da linha
            i = len(texto) if fim < 0 else fim
            continue
        elif ch == ";":
            comando = "".join(atual).strip()
            if comando:
                comandos.append(comando)
            atual = []
        else:
            atual.append(ch)
        i += 1
    resto = "".join(atual).strip()
    if resto:
        comandos.append(resto)
    return comandos


def executar_scripts(conexao, qual: str) -> int:
    """Executa os scripts do banco `qual` na conexão (já no banco certo). Devolve nº de comandos."""
    total = 0
    cursor = conexao.cursor()
    try:
        for relativo in SCRIPTS[qual]:
            for comando in dividir((PASTA_SQL / relativo).read_text(encoding="utf-8")):
                cursor.execute(comando)
                if cursor.with_rows:
                    cursor.fetchall()
                total += 1
        conexao.commit()
    finally:
        cursor.close()
    return total
