"""Experimento da curva DET com voluntários: mede FAR e FRR e sugere os limiares de cada nível.

    .venv\\Scripts\\python.exe -m ferramentas.experimento_det coletar --sessao 1
    .venv\\Scripts\\python.exe -m ferramentas.experimento_det analisar

Quem participa: só cadastros ativos, com consentimento vigente que autoriza a finalidade (b) do termo
(estatísticas e experimentos) e com rosto no modelo. Quem não autorizou a (b) não aparece nem como alvo.

COLETA (por voluntário): a pessoa informa a matrícula e fica diante da câmera em algumas tentativas curtas. Cada
quadro aprovado pelo portão de qualidade é comparado (1:1) com o próprio cadastro, o que dá a distância genuína, e
com cada um dos outros participantes, o que dá as distâncias de impostor (o impostor de esforço zero, que só
apresenta o próprio rosto). O mesmo quadro também passa pela identificação 1:N do modelo inteiro. Repetir com a
`--sessao 2` em outra iluminação: o modelo foi treinado no cadastro, e as tentativas daqui são capturas novas.

Análise: a pontuação de cada tentativa segue o confirmador do login (N quadros seguidos dentro do limiar), e a curva,
a EER e os limiares sugeridos saem de ecosec/visao/desempenho.py. Grava a figura da curva DET em
resultados/curva_det.png e o resumo em resultados/experimento_det_analise.json. Não altera o config: trocar um
limiar é decisão que se registra em ata.

LGPD: nenhuma imagem é gravada. O arquivo guarda só distâncias, e cada participante aparece por um código (não pela
matrícula, nem pelo identificador do banco), calculado com um sal aleatório do próprio arquivo.
"""
import argparse
import hashlib
import json
import secrets
import sys
import time
from datetime import datetime
from pathlib import Path
from statistics import NormalDist

from ecosec.visao import desempenho

ARQUIVO_DADOS = "experimento_det.json"
ARQUIVO_ANALISE = "experimento_det_analise.json"
ARQUIVO_FIGURA = "curva_det.png"
MINIMO_PARTICIPANTES = 3


# ------------------------------------------------------------------ participantes
def elegiveis(usuarios, consentimentos, rotulos_modelo: set[int]) -> list:
    """Cadastros que podem participar: ativos, não excluídos, com rosto no modelo e com o consentimento vigente
    autorizando a finalidade (b)."""
    saida = []
    for u in usuarios.listar():
        if not u.ativo or u.excluido_em is not None or u.id not in rotulos_modelo:
            continue
        consentimento = consentimentos.vigente_de(u.id)
        if consentimento is not None and consentimento.autoriza_pesquisa:
            saida.append(u)
    return saida


def codigo(sal: str, usuario_id: int) -> str:
    """Código do participante no arquivo: estável entre sessões, sem a matrícula nem o identificador do banco."""
    return "P" + hashlib.sha256(f"{sal}:{usuario_id}".encode()).hexdigest()[:8].upper()


# ------------------------------------------------------------------ arquivo de dados
def ler_dados(caminho: Path) -> dict:
    if caminho.exists():
        return json.loads(caminho.read_text(encoding="utf-8"))
    return {"sal": secrets.token_hex(16), "criado_em": datetime.now().isoformat(timespec="seconds"),
            "tentativas": []}


def gravar_dados(caminho: Path, dados: dict) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    temporario = caminho.with_suffix(".tmp")
    temporario.write_text(json.dumps(dados, ensure_ascii=False, indent=1), encoding="utf-8")
    temporario.replace(caminho)


# ------------------------------------------------------------------ análise
def analisar(dados: dict, quadros: int, far_nivel_2: float = 0.01) -> dict:
    """Resumo do experimento: contagens, pontos da curva, EER, limiares sugeridos e o limiar de identificação."""
    genuinas, impostoras, falhas = [], [], 0
    ident_corretas, ident_erradas = [], []
    participantes, sessoes = set(), set()
    for t in dados["tentativas"]:
        participantes.add(t["participante"])
        sessoes.add(t["sessao"])
        qs = t["quadros"]
        pontuacao = desempenho.pontuacao_tentativa([q["genuina"] for q in qs], quadros)
        if pontuacao is None:
            falhas += 1                          # a câmera não entregou N quadros aprovados: o login recusaria
        else:
            genuinas.append(pontuacao)
        alvos = {alvo for q in qs for alvo in q["impostoras"]}
        for alvo in sorted(alvos):
            serie = [q["impostoras"][alvo] for q in qs if alvo in q["impostoras"]]
            p = desempenho.pontuacao_tentativa(serie, quadros)
            if p is not None:
                impostoras.append(p)
        for q in qs:
            ident = q.get("identificacao")
            if ident:
                (ident_corretas if ident["correta"] else ident_erradas).append(ident["distancia"])
    resumo = {"participantes": len(participantes), "sessoes": sorted(sessoes),
              "tentativas_genuinas": len(genuinas) + falhas, "falhas_captura": falhas,
              "tentativas_impostor": len(impostoras), "quadros_confirmacao": quadros, "avisos": []}
    if len(participantes) < MINIMO_PARTICIPANTES:
        resumo["avisos"].append(f"Só {len(participantes)} participante(s): o mínimo para tirar conclusões é "
                                f"{MINIMO_PARTICIPANTES}.")
    if len(sessoes) < 2:
        resumo["avisos"].append("Só uma sessão de iluminação: repita com --sessao 2 em outra luz.")
    if not genuinas and not falhas or not impostoras:
        resumo["avisos"].append("Faltam tentativas genuínas ou de impostor para traçar a curva.")
        return resumo
    pontos = desempenho.curva(genuinas, impostoras, falhas)
    resumo["eer"] = desempenho.eer(pontos).__dict__
    sugestoes = desempenho.sugerir_limiares(genuinas, impostoras, falhas, far_nivel_2)
    resumo["limiares_sugeridos"] = {str(n): s.__dict__ for n, s in sugestoes.items()}
    if len({s.limiar for s in sugestoes.values()}) == 1:
        resumo["avisos"].append("Os três limiares coincidem: nestas tentativas, genuínos e impostores não se "
                                "misturam. Mais participantes e sessões mostram a diferença entre os níveis.")
    ident = desempenho.limiar_identificacao(ident_corretas, ident_erradas, teto=sugestoes[3].limiar)
    resumo["identificacao"] = ({**ident.__dict__, "quadros_corretos": len(ident_corretas),
                                "quadros_errados": len(ident_erradas)} if ident else None)
    resumo["curva"] = [p.__dict__ for p in pontos]
    return resumo


def _num(valor: float) -> str:
    return f"{valor:.1f}".replace(".", ",")


def _pct(taxa: float) -> str:
    return f"{taxa:.1%}".replace(".", ",")


def texto_resumo(resumo: dict) -> str:
    linhas = [f"Participantes: {resumo['participantes']} · sessões: {resumo['sessoes']}",
              f"Tentativas genuínas: {resumo['tentativas_genuinas']} (falhas de captura: {resumo['falhas_captura']})"
              f" · tentativas de impostor: {resumo['tentativas_impostor']}"]
    linhas += [f"AVISO: {a}" for a in resumo["avisos"]]
    if "eer" in resumo:
        e = resumo["eer"]
        linhas.append(f"EER: {_pct(e['far'])} no limiar {_num(e['limiar'])}")
        linhas.append("Limiares sugeridos (distância máxima aceita):")
        for nivel, s in resumo["limiares_sugeridos"].items():
            linhas.append(f"  nível {nivel}: {_num(s['limiar'])}  ({s['criterio']}; FAR {_pct(s['far'])}, "
                          f"FRR {_pct(s['frr'])})")
        if resumo.get("identificacao"):
            i = resumo["identificacao"]
            linhas.append(f"Identificação 1:N: limiar {_num(i['limiar'])} (no máximo o do nível 3) recusa todas as "
                          f"identificações erradas medidas; recusa {_pct(i['frr'])} das corretas.")
        linhas.append("Para adotar: [s4_inerencia] limiar_nivel_1, limiar_nivel_2 e limiar_nivel_3, e "
                      "[identificacao] limiar no config/ecosec.toml, com registro em ata.")
    return "\n".join(linhas)


# ------------------------------------------------------------------ figura
def _probit(taxa: float, piso: float) -> float:
    return NormalDist().inv_cdf(min(max(taxa, piso), 1 - piso))


def desenhar_curva(resumo: dict, caminho: Path, fonte_regular: str = "arial.ttf") -> Path:
    """Curva DET em escala de desvio normal (Martin et al., 1997): FRR em função da FAR, com os limiares sugeridos."""
    from PIL import Image, ImageDraw, ImageFont

    def fonte(tamanho):
        try:
            return ImageFont.truetype(fonte_regular, tamanho)
        except OSError:
            return ImageFont.load_default(tamanho)

    largura, altura, margem = 900, 760, 110
    img = Image.new("RGB", (largura, altura), "white")
    d = ImageDraw.Draw(img)
    marcas = [0.001, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.4]
    piso, teto = marcas[0] / 2, 0.5               # taxas fora da escala ficam presas à borda do gráfico
    lo, hi = _probit(piso, piso), _probit(teto, piso)

    def xy(far, frr):
        far, frr = min(max(far, piso), teto), min(max(frr, piso), teto)
        x = margem + (_probit(far, piso) - lo) / (hi - lo) * (largura - 2 * margem)
        y = altura - margem - (_probit(frr, piso) - lo) / (hi - lo) * (altura - 2 * margem)
        return x, y

    for m in marcas:
        x, _ = xy(m, piso)
        _, y = xy(piso, m)
        d.line([(x, margem), (x, altura - margem)], fill=(225, 225, 225))
        d.line([(margem, y), (largura - margem, y)], fill=(225, 225, 225))
        rotulo = f"{m * 100:g}%".replace(".", ",")
        d.text((x, altura - margem + 8), rotulo, fill="black", font=fonte(15), anchor="mt")
        d.text((margem - 8, y), rotulo, fill="black", font=fonte(15), anchor="rm")
    d.rectangle([margem, margem, largura - margem, altura - margem], outline="black")
    d.text((largura / 2, altura - 45), "Taxa de falsa aceitação (FAR)", fill="black", font=fonte(18), anchor="mm")
    d.text((30, altura / 2), "FRR", fill="black", font=fonte(18), anchor="mm")
    d.text((largura / 2, 50), "Curva DET medida com os voluntários", fill="black", font=fonte(22), anchor="mm")
    pontos = [xy(p["far"], p["frr"]) for p in resumo.get("curva", [])]
    if len(pontos) > 1:
        d.line(pontos, fill=(0, 90, 170), width=3)
    cores = {"1": (0, 140, 70), "2": (210, 130, 0), "3": (190, 30, 30)}
    grupos: dict[tuple, list[str]] = {}            # níveis no mesmo ponto ganham um rótulo só
    for nivel, s in resumo.get("limiares_sugeridos", {}).items():
        grupos.setdefault((s["far"], s["frr"], s["limiar"]), []).append(nivel)
    for (far, frr, limiar), niveis in grupos.items():
        x, y = xy(far, frr)
        d.ellipse([x - 7, y - 7, x + 7, y + 7], fill=cores.get(niveis[-1], "black"))
        nomes = niveis[0] if len(niveis) == 1 else ", ".join(niveis[:-1]) + " e " + niveis[-1]
        rotulo = f"{'Nível' if len(niveis) == 1 else 'Níveis'} {nomes}: {_num(limiar)}"
        d.text((min(x + 12, largura - margem - 150), max(y - 26, margem + 4)), rotulo, fill="black", font=fonte(16))
    caminho.parent.mkdir(parents=True, exist_ok=True)
    img.save(caminho)
    return caminho


# ------------------------------------------------------------------ coleta com a câmera
def _medir_quadro(app, face, alvo_id: int, outros: dict[str, int]) -> dict | None:
    genuina = app.reconhecedor.verificar(face, alvo_id)
    if genuina is None:
        return None
    impostoras = {cod: d for cod, uid in outros.items()
                  if (d := app.reconhecedor.verificar(face, uid)) is not None}
    quadro = {"genuina": genuina, "impostoras": impostoras}
    identificado = app.reconhecedor.identificar(face)
    if identificado is not None:
        quadro["identificacao"] = {"correta": identificado[0] == alvo_id, "distancia": identificado[1]}
    return quadro


def coletar(app, dados: dict, matricula: str, sessao: int, tentativas: int, segundos: float,
            quadros_maximos: int, preparo: float = 2.0) -> int:
    """Grava as tentativas de um voluntário. Devolve quantas tiveram quadros aprovados."""
    import cv2

    participantes = elegiveis(app.cadastro.usuarios, app.cadastro.consentimentos, app.reconhecedor.rotulos())
    alvo = next((u for u in participantes if u.matricula == matricula.strip().upper()), None)
    if alvo is None:
        raise SystemExit("Matrícula fora do experimento: o cadastro precisa estar ativo, com rosto e com a "
                         "finalidade (b) do termo autorizada.")
    if len(participantes) < 2:
        raise SystemExit("É preciso ao menos mais um participante cadastrado para medir as tentativas de impostor.")
    sal = dados["sal"]
    outros = {codigo(sal, u.id): u.id for u in participantes if u.id != alvo.id}
    janela = "Experimento DET (Esc encerra)"
    com_quadros = 0
    try:
        with app.nova_camera() as camera:
            pipeline = app.novo_pipeline()
            for n in range(1, tentativas + 1):
                inicio_preparo = time.monotonic()
                while time.monotonic() - inicio_preparo < preparo:      # tempo para a pessoa se posicionar
                    quadro = camera.ler()
                    _mostrar(cv2, janela, quadro, f"Tentativa {n} de {tentativas}: prepare-se", None)
                    if cv2.waitKey(1) == 27:
                        return com_quadros
                medidos, inicio = [], time.monotonic()
                while time.monotonic() - inicio < segundos and len(medidos) < quadros_maximos:
                    quadro = camera.ler()
                    resultado = pipeline.processar(quadro)
                    if resultado.qualidade_aprovada:
                        medida = _medir_quadro(app, resultado.face_normalizada, alvo.id, outros)
                        if medida is not None:
                            medidos.append(medida)
                    _mostrar(cv2, janela, quadro, f"Olhe para a camera ({len(medidos)} quadros)",
                             resultado.face_unica)
                    if cv2.waitKey(1) == 27:
                        break
                dados["tentativas"].append({"participante": codigo(sal, alvo.id), "sessao": sessao,
                                            "momento": datetime.now().isoformat(timespec="seconds"),
                                            "quadros": medidos})
                com_quadros += bool(medidos)
    finally:
        cv2.destroyAllWindows()
    return com_quadros


def _mostrar(cv2, janela, quadro, texto, face):
    imagem = cv2.flip(quadro, 1)
    if face is not None:
        x, y, w, h = face
        x = imagem.shape[1] - x - w
        cv2.rectangle(imagem, (x, y), (x + w, y + h), (80, 200, 80), 2)
    cv2.putText(imagem, texto, (12, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
    cv2.imshow(janela, imagem)


# ------------------------------------------------------------------ linha de comando
def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Experimento da curva DET com voluntários.")
    sub = parser.add_subparsers(dest="comando", required=True)
    c = sub.add_parser("coletar", help="grava as tentativas de um voluntário diante da câmera")
    c.add_argument("--sessao", type=int, default=1, help="1 ou 2: cada sessão numa iluminação diferente")
    c.add_argument("--tentativas", type=int, default=5)
    c.add_argument("--segundos", type=float, default=4.0, help="duração de cada tentativa")
    c.add_argument("--quadros", type=int, default=20, help="máximo de quadros aprovados por tentativa")
    sub.add_parser("analisar", help="calcula a curva, a EER e os limiares sugeridos")
    args = parser.parse_args(argv)

    from ecosec.configuracao import carregar
    cfg = carregar()
    pasta = cfg.caminho("resultados")
    arquivo = pasta / ARQUIVO_DADOS
    if args.comando == "analisar":
        if not arquivo.exists():
            print(f"[FALHA] Nenhuma coleta em {arquivo}. Rode primeiro o comando coletar.")
            return 1
        resumo = analisar(ler_dados(arquivo), int(cfg["reconhecimento.frames_confirmacao"]))
        (pasta / ARQUIVO_ANALISE).write_text(json.dumps(resumo, ensure_ascii=False, indent=1), encoding="utf-8")
        print(texto_resumo(resumo))
        if "curva" in resumo:
            figura = desenhar_curva(resumo, pasta / ARQUIVO_FIGURA, cfg["acervo.fonte_regular"])
            print(f"Figura: {figura}")
        return 0

    from ecosec.aplicacao import ErroAbertura, montar
    try:
        app = montar(cfg)
    except ErroAbertura as erro:
        print(f"[FALHA] {erro}")
        return 2
    dados = ler_dados(arquivo)
    matricula = input("Matrícula do voluntário: ")
    feitas = coletar(app, dados, matricula, args.sessao, args.tentativas, args.segundos, args.quadros)
    gravar_dados(arquivo, dados)
    print(f"{feitas} tentativa(s) com quadros aprovados gravadas em {arquivo}. Próximo voluntário: rode de novo.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
