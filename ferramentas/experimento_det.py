"""Experimento da curva DET: mede FAR e FRR e sugere os limiares de cada nível.

    .venv\\Scripts\\python.exe -m ferramentas.experimento_det coletar --sessao 1 [--ignorar MATRICULA ...]
    .venv\\Scripts\\python.exe -m ferramentas.experimento_det base --pasta <CroppedYale> --alvo MATRICULA
    .venv\\Scripts\\python.exe -m ferramentas.experimento_det analisar

Administrador: `coletar` e `base` leem o modelo facial e os consentimentos, então pedem antes a matrícula, a senha e
o código do celular de um administrador ativo. O início e o fim ficam na trilha de auditoria, sem nenhuma distância.
`analisar` só lê o arquivo de distâncias e não pede login.

Quem participa: só cadastros ativos, com consentimento vigente que autoriza a finalidade (b) do termo
(estatísticas e experimentos) e com rosto no modelo. Quem não autorizou a (b) não aparece nem como alvo.
`--ignorar` tira do experimento os cadastros que são da mesma pessoa (por exemplo, um cadastro de demonstração com o
rosto do próprio voluntário): eles contariam a pessoa "se passando por ela mesma" como impostor.

Coleta com a câmera (por voluntário): a pessoa informa a matrícula e fica diante da câmera em algumas tentativas
curtas. Cada quadro aprovado pelo portão de qualidade é comparado (1:1) com o próprio cadastro, o que dá a distância
genuína, e com cada um dos outros participantes, o que dá as distâncias de impostor (o impostor de esforço zero, que
só apresenta o próprio rosto). O mesmo quadro também passa pela identificação 1:N do modelo inteiro. Repetir com a
`--sessao 2` em outra iluminação: o modelo foi treinado no cadastro, e as tentativas daqui são capturas novas.

Base pública (Extended Yale B, versão recortada): as imagens já são o recorte da face, então a segmentação de Haar
dá lugar ao próprio recorte, e o resto é o mesmo do sistema: portão de qualidade, redimensionamento, CLAHE,
suavização e LBPH com os parâmetros do config. As imagens são separadas pelos subconjuntos de iluminação da base
(o ângulo entre a luz e o eixo da câmera): o subconjunto 1, o de luz quase frontal, vira o cadastro de cada pessoa
num modelo próprio, só em memória, e os subconjuntos 2 a 5 viram as tentativas. Cada imagem é uma tentativa de um
quadro: genuína contra a própria pessoa e de impostor contra cada uma das outras. A curva usa os subconjuntos 2 e
3 (luz até 50 graus do eixo, a variação de um ambiente interno); os subconjuntos 4 e 5, de luz lateral extrema,
mostram o portão de qualidade em ação e têm a EER relatada à parte. A imagem recusada pela qualidade é uma falha
de aquisição, relatada separadamente da FRR (ISO/IEC 19795-1). Com `--alvo`, cada imagem aprovada
também é comparada ao cadastro real dessa matrícula no modelo do sistema, o que mede a FAR contra ele (uma foto
parada repete a mesma distância em todos os quadros, então um quadro basta). O modelo do sistema não é alterado.

Análise: a pontuação de cada tentativa da câmera segue o confirmador do login (N quadros seguidos dentro do limiar),
e a curva, a EER e os limiares sugeridos saem de ecosec/visao/desempenho.py, em três recortes: a câmera (cada
voluntário contra os outros cadastros), a base pública e o sistema (as tentativas genuínas da câmera contra os rostos
da base comparados ao cadastro do alvo). Cada recorte também traz a FAR e a FRR nos limiares do config. A figura, em
resultados/curva_det.png, mostra a curva da câmera, com os limiares sugeridos, e a da base pública; a do sistema
fica só no texto, porque rostos de outra câmera ficam longe do cadastro e deixam essa curva otimista. O resumo vai
para resultados/experimento_det_analise.json. Não altera o config: trocar um limiar é decisão que se registra em
ata.

LGPD: nenhuma imagem é gravada. Os arquivos guardam só distâncias, e cada participante aparece por um código (não
pela matrícula, nem pelo identificador do banco), calculado com um sal aleatório do próprio arquivo. As imagens da
base pública ficam numa pasta fora do repositório.
"""
import argparse
import getpass
import hashlib
import json
import math
import re
import secrets
import sys
import time
from datetime import datetime
from pathlib import Path
from statistics import NormalDist

from ecosec.visao import desempenho

ARQUIVO_DADOS = "experimento_det.json"
ARQUIVO_BASE = "experimento_det_base.json"
ARQUIVO_ANALISE = "experimento_det_analise.json"
ARQUIVO_FIGURA = "curva_det.png"
MINIMO_PARTICIPANTES = 3

# Extended Yale B: yaleB11_P00A+010E-20.pgm (azimute e elevação da luz, em graus)
_NOME_YALE = re.compile(r"_P00A([+-]\d{3})E([+-]\d{2})\.pgm$", re.IGNORECASE)
# limites dos subconjuntos de iluminação da base (ângulo entre a luz e o eixo da câmera)
_LIMITES_SUBCONJUNTOS = (12, 25, 50, 77)
# a curva usa a iluminação moderada (até 50 graus), a de um ambiente interno; os subconjuntos 4 e 5, de luz lateral
# extrema, ficam como teste do portão de qualidade
SUBCONJUNTOS_CURVA = ("2", "3")


# ------------------------------------------------------------------ participantes
def elegiveis(usuarios, consentimentos, rotulos_modelo: set[int], ignorar=frozenset()) -> list:
    """Cadastros que podem participar: ativos, não excluídos, com rosto no modelo e com o consentimento vigente
    autorizando a finalidade (b). As matrículas de `ignorar` ficam de fora."""
    ignorar = {m.strip().upper() for m in ignorar}
    saida = []
    for u in usuarios.listar():
        if not u.ativo or u.excluido_em is not None or u.id not in rotulos_modelo or u.matricula in ignorar:
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
def _avaliar(genuinas: list[float], impostoras: list[float], falhas: int, ident_corretas: list[float],
             ident_erradas: list[float], far_nivel_2: float, avisos: list[str], atuais: dict | None = None) -> dict:
    """Curva, EER, limiares sugeridos e limiar de identificação de um conjunto de pontuações. `atuais` são os
    limiares do config ({"1": 70.0, ...}): a saída também traz a FAR e a FRR medidas em cada um."""
    saida: dict = {}
    if not genuinas and not falhas or not impostoras:
        avisos.append("Faltam tentativas genuínas ou de impostor para traçar a curva.")
        return saida
    if atuais:
        saida["limiares_atuais"] = {n: desempenho.taxas(genuinas, impostoras, limiar, falhas).__dict__
                                    for n, limiar in atuais.items()}
    pontos = desempenho.curva(genuinas, impostoras, falhas)
    saida["eer"] = desempenho.eer(pontos).__dict__
    sugestoes = desempenho.sugerir_limiares(genuinas, impostoras, falhas, far_nivel_2)
    saida["limiares_sugeridos"] = {str(n): s.__dict__ for n, s in sugestoes.items()}
    if len({s.limiar for s in sugestoes.values()}) == 1:
        avisos.append("Os três limiares coincidem: nestas tentativas, genuínos e impostores não se "
                      "misturam. Mais participantes e sessões mostram a diferença entre os níveis.")
    ident = desempenho.limiar_identificacao(ident_corretas, ident_erradas, teto=sugestoes[3].limiar)
    saida["identificacao"] = ({**ident.__dict__, "quadros_corretos": len(ident_corretas),
                               "quadros_errados": len(ident_erradas)} if ident else None)
    saida["curva"] = [p.__dict__ for p in pontos]
    return saida


def _pontuacoes_camera(dados: dict, quadros: int, participante: str | None = None) -> dict:
    """As pontuações das tentativas da câmera (todas, ou só as de um participante)."""
    genuinas, impostoras, falhas = [], [], 0
    ident_corretas, ident_erradas = [], []
    participantes, sessoes = set(), set()
    for t in dados["tentativas"]:
        if participante is not None and t["participante"] != participante:
            continue
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
    return {"genuinas": genuinas, "impostoras": impostoras, "falhas": falhas, "ident_corretas": ident_corretas,
            "ident_erradas": ident_erradas, "participantes": participantes, "sessoes": sessoes}


def analisar(dados: dict, quadros: int, far_nivel_2: float = 0.01, atuais: dict | None = None) -> dict:
    """Resumo da coleta com a câmera: contagens, pontos da curva, EER, limiares sugeridos e o limiar de
    identificação."""
    p = _pontuacoes_camera(dados, quadros)
    resumo = {"participantes": len(p["participantes"]), "sessoes": sorted(p["sessoes"]),
              "tentativas_genuinas": len(p["genuinas"]) + p["falhas"], "falhas_captura": p["falhas"],
              "tentativas_impostor": len(p["impostoras"]), "quadros_confirmacao": quadros, "avisos": []}
    if len(p["participantes"]) < MINIMO_PARTICIPANTES:
        resumo["avisos"].append(f"Só {len(p['participantes'])} participante(s): o mínimo para tirar conclusões é "
                                f"{MINIMO_PARTICIPANTES}.")
    if len(p["sessoes"]) < 2:
        resumo["avisos"].append("Só uma sessão de iluminação: repita com --sessao 2 em outra luz.")
    resumo.update(_avaliar(p["genuinas"], p["impostoras"], p["falhas"], p["ident_corretas"], p["ident_erradas"],
                           far_nivel_2, resumo["avisos"], atuais))
    return resumo


def analisar_base(base: dict, far_nivel_2: float = 0.01, subconjuntos=SUBCONJUNTOS_CURVA,
                  atuais: dict | None = None) -> dict:
    """Resumo da base pública: cada imagem é uma tentativa de um quadro. A curva usa os subconjuntos de iluminação
    moderada (`subconjuntos`), e a imagem recusada pelo portão de qualidade conta como falha de aquisição, relatada
    à parte, como na ISO/IEC 19795-1: ela nem chega a ser comparada. Cada subconjunto também tem a sua EER."""
    por = base["por_subconjunto"]
    escolhidos = [s for s in subconjuntos if s in por]
    juntar = lambda chave: [d for s in escolhidos for d in por[s][chave]]       # noqa: E731
    imagens = sum(por[s]["imagens"] for s in escolhidos)
    recusadas = sum(por[s]["rejeitadas_qualidade"] for s in escolhidos)
    tabela = {}
    for s, info in por.items():
        linha = {"imagens": info["imagens"], "rejeitadas_qualidade": info["rejeitadas_qualidade"]}
        if info["genuinas"] and info["impostoras"]:
            linha["eer"] = desempenho.eer(desempenho.curva(info["genuinas"], info["impostoras"])).__dict__
        tabela[s] = linha
    resumo = {"pessoas": base["pessoas"], "cadastro": base["cadastro"], "subconjuntos_curva": escolhidos,
              "subconjuntos": tabela, "falha_aquisicao": (recusadas / imagens) if imagens else None,
              "tentativas_genuinas": len(juntar("genuinas")), "tentativas_impostor": len(juntar("impostoras")),
              "quadros_confirmacao": 1, "avisos": []}
    resumo.update(_avaliar(juntar("genuinas"), juntar("impostoras"), 0, juntar("ident_corretas"),
                           juntar("ident_erradas"), far_nivel_2, resumo["avisos"], atuais))
    return resumo


def analisar_sistema(dados: dict, base: dict, quadros: int, far_nivel_2: float = 0.01,
                     atuais: dict | None = None) -> dict | None:
    """O sistema real: as tentativas genuínas do alvo com a câmera contra os rostos da base comparados ao cadastro
    dele (somados aos impostores da própria câmera, se houver). None se falta uma das partes."""
    alvo = base.get("alvo")
    if not alvo or not dados or not dados.get("tentativas") or dados.get("sal") != alvo.get("sal"):
        return None
    p = _pontuacoes_camera(dados, quadros, participante=alvo["codigo"])
    if not p["genuinas"] and not p["falhas"]:
        return None
    impostoras = p["impostoras"] + alvo["impostoras"]
    resumo = {"sessoes": sorted(p["sessoes"]), "tentativas_genuinas": len(p["genuinas"]) + p["falhas"],
              "falhas_captura": p["falhas"], "tentativas_impostor": len(impostoras),
              "impostores_da_base": len(alvo["impostoras"]), "quadros_confirmacao": quadros, "avisos": []}
    if len(p["sessoes"]) < 2:
        resumo["avisos"].append("Só uma sessão de iluminação: repita com --sessao 2 em outra luz.")
    if alvo["impostoras"] and p["genuinas"] and min(alvo["impostoras"]) > max(p["genuinas"]):
        resumo["avisos"].append(
            f"Nenhum rosto da base chegou perto do cadastro (a menor distância foi {_num(min(alvo['impostoras']))}, "
            f"acima de todas as genuínas): as imagens vêm de outra câmera e de outra iluminação, então esta curva é "
            f"otimista e não mede o impostor diante desta câmera. Para isso vale a curva da câmera.")
    resumo.update(_avaliar(p["genuinas"], impostoras, p["falhas"], p["ident_corretas"], p["ident_erradas"],
                           far_nivel_2, resumo["avisos"], atuais))
    return resumo


def _num(valor: float) -> str:
    return f"{valor:.1f}".replace(".", ",")


def _pct(taxa: float) -> str:
    return f"{taxa:.1%}".replace(".", ",")


def _texto_taxas(resumo: dict) -> list[str]:
    linhas = [f"AVISO: {a}" for a in resumo["avisos"]]
    if "eer" in resumo:
        e = resumo["eer"]
        linhas.append(f"EER: {_pct(e['far'])} no limiar {_num(e['limiar'])}")
        linhas.append("Limiares sugeridos (distância máxima aceita):")
        for nivel, s in resumo["limiares_sugeridos"].items():
            linhas.append(f"  nível {nivel}: {_num(s['limiar'])}  ({s['criterio']}; FAR {_pct(s['far'])}, "
                          f"FRR {_pct(s['frr'])})")
        if resumo.get("limiares_atuais"):
            linhas.append("Nos limiares do config:")
            for nivel, t in resumo["limiares_atuais"].items():
                linhas.append(f"  nível {nivel} ({_num(t['limiar'])}): FAR {_pct(t['far'])}, FRR {_pct(t['frr'])}")
        if resumo.get("identificacao"):
            i = resumo["identificacao"]
            linhas.append(f"Identificação 1:N: limiar {_num(i['limiar'])} (no máximo o do nível 3) recusa todas as "
                          f"identificações erradas medidas; recusa {_pct(i['frr'])} das corretas.")
    return linhas


def texto_resumo(resumo: dict) -> str:
    linhas = [f"Participantes: {resumo['participantes']} · sessões: {resumo['sessoes']}",
              f"Tentativas genuínas: {resumo['tentativas_genuinas']} (falhas de captura: {resumo['falhas_captura']})"
              f" · tentativas de impostor: {resumo['tentativas_impostor']}"]
    linhas += _texto_taxas(resumo)
    if "eer" in resumo:
        linhas.append("Para adotar: [s4_inerencia] limiar_nivel_1, limiar_nivel_2 e limiar_nivel_3, e "
                      "[identificacao] limiar no config/ecosec.toml, com registro em ata.")
    return "\n".join(linhas)


def texto_base(resumo: dict) -> str:
    c = resumo["cadastro"]
    linhas = [f"Pessoas: {resumo['pessoas']} · cadastro (subconjunto 1): {c['aprovadas']} de {c['imagens']} imagens "
              f"aprovadas pelo portão de qualidade"]
    for s, info in resumo["subconjuntos"].items():
        eer = f", EER {_pct(info['eer']['far'])} no limiar {_num(info['eer']['limiar'])}" if "eer" in info else ""
        linhas.append(f"  subconjunto {s}: {info['imagens']} imagens, {info['rejeitadas_qualidade']} recusadas pelo "
                      f"portão de qualidade{eer}")
    falha = resumo["falha_aquisicao"]
    linhas.append(f"Curva com os subconjuntos {' e '.join(resumo['subconjuntos_curva'])}: tentativas genuínas "
                  f"{resumo['tentativas_genuinas']} · de impostor {resumo['tentativas_impostor']} · falha de "
                  f"aquisição {_pct(falha) if falha is not None else '-'}")
    return "\n".join(linhas + _texto_taxas(resumo))


def texto_sistema(resumo: dict) -> str:
    linhas = [f"Sessões: {resumo['sessoes']} · tentativas genuínas com a câmera: {resumo['tentativas_genuinas']} "
              f"(falhas de captura: {resumo['falhas_captura']})",
              f"Tentativas de impostor: {resumo['tentativas_impostor']} (rostos da base contra o cadastro: "
              f"{resumo['impostores_da_base']})"]
    return "\n".join(linhas + _texto_taxas(resumo))


# ------------------------------------------------------------------ figura
def _probit(taxa: float, piso: float) -> float:
    return NormalDist().inv_cdf(min(max(taxa, piso), 1 - piso))


def desenhar_curva(resumo: dict, caminho: Path, fonte_regular: str = "arial.ttf", titulo: str = "Curva DET",
                   rotulo: str | None = None, extras: tuple = ()) -> Path:
    """Curva DET em escala de desvio normal (Martin et al., 1997): FRR em função da FAR, com os limiares sugeridos
    de `resumo`. `extras` são outras curvas, como (rótulo, pontos), desenhadas junto, com legenda."""
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
        texto = f"{m * 100:g}%".replace(".", ",")
        d.text((x, altura - margem + 8), texto, fill="black", font=fonte(15), anchor="mt")
        d.text((margem - 8, y), texto, fill="black", font=fonte(15), anchor="rm")
    d.rectangle([margem, margem, largura - margem, altura - margem], outline="black")
    d.text((largura / 2, altura - 45), "Taxa de falsa aceitação (FAR)", fill="black", font=fonte(18), anchor="mm")
    d.text((30, altura / 2), "FRR", fill="black", font=fonte(18), anchor="mm")
    d.text((largura / 2, 50), titulo, fill="black", font=fonte(22), anchor="mm")
    cores_linhas = [(0, 90, 170), (230, 120, 0), (120, 60, 160)]
    curvas = [(rotulo, resumo.get("curva", []))] + list(extras)
    legenda_y = margem + 12
    for i, (nome, pontos_curva) in enumerate(curvas):
        pontos = [xy(p["far"], p["frr"]) for p in pontos_curva]
        cor = cores_linhas[i % len(cores_linhas)]
        if len(pontos) > 1:
            d.line(pontos, fill=cor, width=3)
        if nome and len(curvas) > 1:
            d.line([(largura - margem - 260, legenda_y), (largura - margem - 230, legenda_y)], fill=cor, width=3)
            d.text((largura - margem - 222, legenda_y), nome, fill="black", font=fonte(15), anchor="lm")
            legenda_y += 22
    cores = {"1": (0, 140, 70), "2": (210, 130, 0), "3": (190, 30, 30)}
    grupos: dict[tuple, list[str]] = {}            # níveis no mesmo ponto ganham um rótulo só
    for nivel, s in resumo.get("limiares_sugeridos", {}).items():
        grupos.setdefault((s["far"], s["frr"], s["limiar"]), []).append(nivel)
    for (far, frr, limiar), niveis in grupos.items():
        x, y = xy(far, frr)
        d.ellipse([x - 7, y - 7, x + 7, y + 7], fill=cores.get(niveis[-1], "black"))
        nomes = niveis[0] if len(niveis) == 1 else ", ".join(niveis[:-1]) + " e " + niveis[-1]
        texto = f"{'Nível' if len(niveis) == 1 else 'Níveis'} {nomes}: {_num(limiar)}"
        d.text((min(x + 12, largura - margem - 150), max(y - 26, margem + 4)), texto, fill="black", font=fonte(16))
    caminho.parent.mkdir(parents=True, exist_ok=True)
    img.save(caminho)
    return caminho


# ------------------------------------------------------------------ coleta com a câmera
def _medir_quadro(app, face, alvo_id: int, outros: dict[str, int], ignorados: set[int]) -> dict | None:
    genuina = app.reconhecedor.verificar(face, alvo_id)
    if genuina is None:
        return None
    impostoras = {cod: d for cod, uid in outros.items()
                  if (d := app.reconhecedor.verificar(face, uid)) is not None}
    quadro = {"genuina": genuina, "impostoras": impostoras}
    identificado = app.reconhecedor.identificar(face)
    if identificado is not None and identificado[0] not in ignorados:      # cadastro da mesma pessoa: não é erro
        quadro["identificacao"] = {"correta": identificado[0] == alvo_id, "distancia": identificado[1]}
    return quadro


def coletar(app, dados: dict, matricula: str, sessao: int, tentativas: int, segundos: float,
            quadros_maximos: int, preparo: float = 2.0, ignorar=frozenset()) -> int:
    """Grava as tentativas de um voluntário. Devolve quantas tiveram quadros aprovados."""
    import cv2

    usuarios = app.cadastro.usuarios
    participantes = elegiveis(usuarios, app.cadastro.consentimentos, app.reconhecedor.rotulos(), ignorar)
    alvo = next((u for u in participantes if u.matricula == matricula.strip().upper()), None)
    if alvo is None:
        raise SystemExit("Matrícula fora do experimento: o cadastro precisa estar ativo, com rosto e com a "
                         "finalidade (b) do termo autorizada.")
    ignorar = {m.strip().upper() for m in ignorar}
    ignorados = {u.id for u in usuarios.listar() if u.matricula in ignorar}
    sal = dados["sal"]
    outros = {codigo(sal, u.id): u.id for u in participantes if u.id != alvo.id}
    if not outros:
        print("Só este participante no experimento: a coleta mede as tentativas genuínas, e os impostores vêm da "
              "base pública (comando base).")
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
                        medida = _medir_quadro(app, resultado.face_normalizada, alvo.id, outros, ignorados)
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


# ------------------------------------------------------------------ base pública (Extended Yale B recortada)
def subconjunto_yale(nome: str) -> int | None:
    """O subconjunto de iluminação (1 a 5) pelo nome do arquivo, ou None se não é uma imagem de tentativa (a imagem
    ambiente e os arquivos de outro formato)."""
    m = _NOME_YALE.search(nome)
    if not m:
        return None
    azimute, elevacao = math.radians(int(m.group(1))), math.radians(int(m.group(2)))
    angulo = math.degrees(math.acos(max(-1.0, min(1.0, math.cos(azimute) * math.cos(elevacao)))))
    return 1 + sum(angulo > limite for limite in _LIMITES_SUBCONJUNTOS)


def ler_base(pasta: Path) -> dict[str, list[tuple[int, Path]]]:
    """{pessoa: [(subconjunto, arquivo)]}: uma subpasta por pessoa, como na distribuição da base."""
    pessoas = {}
    for sub in sorted(p for p in pasta.iterdir() if p.is_dir()):
        imagens = [(s, arq) for arq in sorted(sub.iterdir()) if (s := subconjunto_yale(arq.name)) is not None]
        if imagens:
            pessoas[sub.name] = imagens
    return pessoas


def ler_cinza(arquivo: Path):
    """A imagem em tons de cinza (lida pelos bytes, para aceitar caminhos com acento no Windows)."""
    import cv2
    import numpy as np
    return cv2.imdecode(np.fromfile(str(arquivo), dtype=np.uint8), cv2.IMREAD_GRAYSCALE)


def preparador_do_sistema(cfg):
    """O mesmo tratamento do sistema depois da segmentação: portão de qualidade sobre o recorte original e, se
    aprovado, a normalização (200x200, CLAHE e suavização). Devolve a face normalizada ou None."""
    from ecosec.visao.preprocessamento import ParametrosPreprocessamento, Preprocessador
    from ecosec.visao.qualidade import ParametrosQualidade, avaliar, medir
    preprocessador = Preprocessador(ParametrosPreprocessamento.de_configuracao(cfg))
    p_qual = ParametrosQualidade.de_configuracao(cfg)

    def preparar(recorte):
        if recorte is None or recorte.size == 0 or avaliar(medir(recorte), p_qual):
            return None
        return preprocessador.normalizar(recorte)
    return preparar


def medir_base(pessoas: dict[str, list[tuple[int, Path]]], preparar, novo_reconhecedor, ler=ler_cinza,
               alvo=None) -> dict:
    """Distâncias da base: o subconjunto 1 de cada pessoa vira o cadastro num modelo próprio, e cada imagem dos
    subconjuntos 2 a 5 é uma tentativa. `alvo(face)` devolve a distância ao cadastro real do alvo (ou None)."""
    cadastro = {"imagens": 0, "aprovadas": 0}
    por: dict[str, dict] = {}
    faces_cadastro, tentativas, alvo_impostoras = {}, [], []
    for rotulo, (_, imagens) in enumerate(sorted(pessoas.items()), start=1):
        for s, arquivo in imagens:
            face = preparar(ler(arquivo))
            if s == 1:
                cadastro["imagens"] += 1
                if face is not None:
                    cadastro["aprovadas"] += 1
                    faces_cadastro.setdefault(rotulo, []).append(face)
            else:
                tentativas.append((str(s), rotulo, face))
            if face is not None and alvo is not None:
                distancia = alvo(face)
                if distancia is not None:
                    alvo_impostoras.append(distancia)
    reconhecedor = novo_reconhecedor()
    for rotulo, faces in faces_cadastro.items():
        reconhecedor.adicionar(faces, rotulo)
    for s, rotulo, face in tentativas:
        if rotulo not in faces_cadastro:
            continue                             # pessoa sem nenhuma imagem de cadastro aprovada: fica de fora
        info = por.setdefault(s, {"imagens": 0, "rejeitadas_qualidade": 0, "genuinas": [], "impostoras": [],
                                  "ident_corretas": [], "ident_erradas": []})
        info["imagens"] += 1
        if face is None:
            info["rejeitadas_qualidade"] += 1    # recusada no portão de qualidade: nem chega a ser comparada
            continue
        distancias = reconhecedor.distancias(face)
        info["genuinas"].append(distancias[rotulo])
        info["impostoras"] += [d for r, d in distancias.items() if r != rotulo]
        mais_proximo = min(distancias, key=distancias.get)
        (info["ident_corretas"] if mais_proximo == rotulo else info["ident_erradas"]).append(distancias[mais_proximo])
    return {"pessoas": len(faces_cadastro), "cadastro": cadastro, "por_subconjunto": dict(sorted(por.items())),
            "alvo_impostoras": alvo_impostoras}


# ------------------------------------------------------------------ administrador
def autorizar(app, ferramenta: str, entrada=input, ler_senha=getpass.getpass) -> int:
    """Matrícula, senha e código do celular de um administrador. Sai com erro se o serviço recusar."""
    print("Esta ferramenta lê o modelo facial e os consentimentos: entre com um administrador.")
    matricula = entrada("Matrícula do administrador: ")
    senha = ler_senha("Senha: ")
    codigo_celular = entrada("Código do celular: ")
    usuario_id, recusa = app.administracao.autorizar_ferramenta(matricula, senha, codigo_celular, ferramenta)
    if recusa:
        raise SystemExit(f"[FALHA] {recusa}")
    return usuario_id


# ------------------------------------------------------------------ linha de comando
def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Experimento da curva DET.")
    sub = parser.add_subparsers(dest="comando", required=True)
    c = sub.add_parser("coletar", help="grava as tentativas de um voluntário diante da câmera")
    c.add_argument("--sessao", type=int, default=1, help="1 ou 2: cada sessão numa iluminação diferente")
    c.add_argument("--tentativas", type=int, default=5)
    c.add_argument("--segundos", type=float, default=4.0, help="duração de cada tentativa")
    c.add_argument("--quadros", type=int, default=20, help="máximo de quadros aprovados por tentativa")
    c.add_argument("--ignorar", nargs="*", default=[], metavar="MATRICULA",
                   help="cadastros da mesma pessoa, que não podem contar como impostores")
    b = sub.add_parser("base", help="mede a base pública de rostos (Extended Yale B recortada)")
    b.add_argument("--pasta", type=Path, required=True, help="a pasta com uma subpasta por pessoa")
    b.add_argument("--alvo", metavar="MATRICULA", help="compara cada rosto da base ao cadastro real desta matrícula")
    sub.add_parser("analisar", help="calcula a curva, a EER e os limiares sugeridos")
    args = parser.parse_args(argv)

    from ecosec.configuracao import carregar
    cfg = carregar()
    pasta = cfg.caminho("resultados")
    arquivo, arquivo_base = pasta / ARQUIVO_DADOS, pasta / ARQUIVO_BASE
    if args.comando == "analisar":
        return _analisar(cfg, pasta, arquivo, arquivo_base)
    if args.comando == "base" and not args.pasta.is_dir():
        print(f"[FALHA] Pasta da base não encontrada: {args.pasta}")
        return 1

    from ecosec.aplicacao import ErroAbertura, montar
    try:
        app = montar(cfg)
    except ErroAbertura as erro:
        print(f"[FALHA] {erro}")
        return 2
    ferramenta = f"EXPERIMENTO DET {args.comando.upper()}"
    administrador = autorizar(app, ferramenta)
    dados = ler_dados(arquivo)
    if args.comando == "coletar":
        matricula = input("Matrícula do voluntário: ")
        feitas = coletar(app, dados, matricula, args.sessao, args.tentativas, args.segundos, args.quadros,
                         ignorar=args.ignorar)
        gravar_dados(arquivo, dados)
        app.administracao.registrar_fim_ferramenta(administrador, ferramenta,
                                                   f"sessão {args.sessao}, {feitas} tentativa(s) gravadas")
        print(f"{feitas} tentativa(s) com quadros aprovados gravadas em {arquivo}. Próximo voluntário: rode de novo.")
        return 0

    alvo_info, medir_alvo = None, None
    if args.alvo:
        participantes = elegiveis(app.cadastro.usuarios, app.cadastro.consentimentos, app.reconhecedor.rotulos())
        alvo = next((u for u in participantes if u.matricula == args.alvo.strip().upper()), None)
        if alvo is None:
            raise SystemExit("Matrícula fora do experimento: o cadastro precisa estar ativo, com rosto e com a "
                             "finalidade (b) do termo autorizada.")
        gravar_dados(arquivo, dados)                              # o sal precisa existir para o código do alvo
        alvo_info = {"sal": dados["sal"], "codigo": codigo(dados["sal"], alvo.id)}
        medir_alvo = lambda face: app.reconhecedor.verificar(face, alvo.id)    # noqa: E731
    from ecosec.visao.reconhecimento import ParametrosLBPH, ReconhecedorLBPH
    pessoas = ler_base(args.pasta)
    print(f"{len(pessoas)} pessoas na base. Medindo (pode levar alguns minutos)...")
    base = medir_base(pessoas, preparador_do_sistema(cfg), lambda: ReconhecedorLBPH(ParametrosLBPH.de_configuracao(cfg)),
                      alvo=medir_alvo)
    alvo_impostoras = base.pop("alvo_impostoras")
    if alvo_info is not None:
        base["alvo"] = {**alvo_info, "impostoras": alvo_impostoras}
    base["medido_em"] = datetime.now().isoformat(timespec="seconds")
    gravar_dados(arquivo_base, base)
    app.administracao.registrar_fim_ferramenta(administrador, ferramenta, f"{base['pessoas']} pessoas da base")
    print(texto_base(analisar_base(base)))
    print(f"Distâncias gravadas em {arquivo_base}. Rode o comando analisar para a figura.")
    return 0


def _analisar(cfg, pasta: Path, arquivo: Path, arquivo_base: Path) -> int:
    if not arquivo.exists() and not arquivo_base.exists():
        print(f"[FALHA] Nenhuma coleta em {pasta}. Rode primeiro o comando coletar ou o comando base.")
        return 1
    quadros = int(cfg["reconhecimento.frames_confirmacao"])
    atuais = {str(n): float(cfg[f"s4_inerencia.limiar_nivel_{n}"]) for n in (1, 2, 3)}
    dados = ler_dados(arquivo) if arquivo.exists() else None
    base = json.loads(arquivo_base.read_text(encoding="utf-8")) if arquivo_base.exists() else None
    resumo = {}
    if dados and dados["tentativas"]:
        resumo["camera"] = analisar(dados, quadros, atuais=atuais)
        print("=== Câmera do equipamento (cada voluntário contra os outros cadastros) ===")
        print(texto_resumo(resumo["camera"]))
    if base:
        resumo["base"] = analisar_base(base, atuais=atuais)
        print("\n=== Base pública (Extended Yale B) ===")
        print(texto_base(resumo["base"]))
        sistema = analisar_sistema(dados, base, quadros, atuais=atuais)
        if sistema is not None:
            resumo["sistema"] = sistema
            print("\n=== Sistema (câmera do voluntário contra os rostos da base) ===")
            print(texto_sistema(sistema))
    (pasta / ARQUIVO_ANALISE).write_text(json.dumps(resumo, ensure_ascii=False, indent=1), encoding="utf-8")
    # a figura: a curva da câmera (a condição real do sistema), com os limiares sugeridos, e a da base pública. A do
    # "sistema" fica só no texto: com os rostos de outra câmera, ela é otimista
    nomes = {"camera": "Câmera do equipamento", "base": "Base pública (Extended Yale B)"}
    principal = next((resumo[k] for k in nomes if "curva" in resumo.get(k, {})), None)
    if principal is not None:
        chave = next(k for k in nomes if resumo.get(k) is principal)
        extras = tuple((nomes[k], resumo[k]["curva"]) for k in nomes if k != chave and "curva" in resumo.get(k, {}))
        figura = desenhar_curva(principal, pasta / ARQUIVO_FIGURA, cfg["acervo.fonte_regular"], rotulo=nomes[chave],
                                extras=extras)
        print(f"\nFigura: {figura}")
    print("\nPara adotar: [s4_inerencia] limiar_nivel_1, limiar_nivel_2 e limiar_nivel_3, e [identificacao] limiar "
          "no config/ecosec.toml, com registro em ata.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
