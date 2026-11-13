"""Confere um documento do acervo pelo QR code ou pelo hash da marca visível (S-07).

    python -m ferramentas.verificar_documento "ecosec://verificar/AUTO DE INFRACAO/1234/2024/3f9a0c2177b4e810"
    python -m ferramentas.verificar_documento E77FAFCFA6C68E02

  - QR (ecosec://verificar/{TIPO}/{NUMERO}/{hash16}): procura o documento no cadastro (os documentos são
    derivados das pendências) e confere se o hash dos campos bate. Diz qual pendência e qual documento é;
  - hash de 16 caracteres da marca visível (hash_consulta): procura na trilha a abertura com esse hash e
    diz quem abriu e quando: uma foto da tela leva a quem a tirou.
"""
import sys

from ecosec.acervo import documentos as docs
from ecosec.acervo import sinteticos
from ecosec.servicos.documentos import hash_documento

PREFIXO = "ecosec://verificar/"


def pelo_qr(conteudo: str):
    """(documento, pendência, confere) ou None. confere = o hash do QR bate com o dos campos atuais."""
    resto = conteudo[len(PREFIXO):] if conteudo.startswith(PREFIXO) else conteudo
    partes = resto.split("/")
    if len(partes) < 4:
        return None
    tipo, numero, hash16 = partes[0], "/".join(partes[1:-1]), partes[-1].lower()
    pendencias, responsaveis = sinteticos.gerar()
    atividades = {a.codigo: a for a in sinteticos.ATIVIDADES}
    motivos = {m.codigo: m for m in sinteticos.MOTIVOS}
    geradores = {r.pendencia_codigo: r.nome for r in responsaveis if r.vinculo == "GERADOR_ORIGINAL"}
    for p in pendencias:
        for d in docs.documentos_da_pendencia(p, sinteticos.DATA_BASE):
            if d.tipo == tipo and d.numero == numero:
                campos = docs.campos(d, p, atividades, motivos, geradores.get(p.codigo))
                return d, p, hash_documento(campos)[:16] == hash16
    return None


def pela_trilha(hash16: str, trilha) -> list:
    """Aberturas de documento registradas com esse hash de consulta."""
    alvo = f"SHA256 {hash16.upper()}"
    return [r.evento for r in trilha.recentes(100000)
            if r.evento.motivo == "ABERTURA_DOCUMENTO" and alvo in (r.evento.detalhe or "").upper()]


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    entrada = sys.argv[1].strip()
    if "/" in entrada:
        achado = pelo_qr(entrada)
        if achado is None:
            print("[FALHA] Nenhum documento do cadastro corresponde a este QR.")
            sys.exit(1)
        d, p, confere = achado
        print(f"{d.tipo} Nº {d.numero} de {d.data:%d/%m/%Y} · pendência {p.codigo} ({p.municipio}/{p.uf})")
        print("[OK] o hash do QR confere com o documento." if confere else
              "[FALHA] o hash do QR NÃO confere: o documento foi alterado ou o QR não é deste sistema.")
        sys.exit(0 if confere else 1)
    from ecosec.aplicacao import montar
    app = montar()
    registros = pela_trilha(entrada, app.acervo.trilha)
    if not registros:
        print("[FALHA] Nenhuma abertura de documento com este hash na trilha.")
        sys.exit(1)
    for r in registros:
        print(f"[OK] aberto por usuário {r.usuario_id} em {r.momento:%d/%m/%Y %H:%M:%S} · {r.detalhe}")


if __name__ == "__main__":
    main()
