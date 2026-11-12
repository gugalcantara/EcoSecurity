"""Desempenho do reconhecimento: FAR, FRR, EER e a curva DET a partir de distâncias medidas.

Funções puras, sem câmera, banco nem modelo: recebem números e devolvem números. A coleta com a câmera fica em
ferramentas/experimento_det.py.

Convenção do LBPH: a distância é menor para rostos mais parecidos, e o sistema aceita quando distância <= limiar.
Logo, para um limiar L:
  FAR(L) = fração das tentativas de impostor com pontuação <= L (aceitas por engano);
  FRR(L) = fração das tentativas genuínas com pontuação > L (recusadas por engano), somadas às tentativas genuínas
           em que a câmera nem chegou a entregar quadros aprovados (falhas de captura, recusadas em qualquer limiar).

Pontuação de uma tentativa: o login só confirma depois de N quadros seguidos dentro do limiar (ConfirmadorQuadros).
Uma tentativa com as distâncias d1, d2, ... é aceita no limiar L se existe uma janela de N quadros seguidos com
todas as distâncias <= L, ou seja, se L >= min sobre as janelas de (max da janela). Esse valor é a pontuação da
tentativa: usar a distância de um quadro isolado mediria um sistema que não é o implementado.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Ponto:
    limiar: float
    far: float
    frr: float


@dataclass(frozen=True)
class Sugestao:
    """Limiar sugerido para um nível e as taxas medidas nele."""
    criterio: str
    limiar: float
    far: float
    frr: float


def pontuacao_tentativa(distancias: list[float], quadros: int) -> float | None:
    """Menor limiar com que a tentativa seria confirmada (N quadros seguidos dentro dele), ou None se a tentativa
    tem menos de N quadros aprovados (nunca seria confirmada)."""
    if quadros < 1:
        raise ValueError("quadros precisa ser pelo menos 1")
    if len(distancias) < quadros:
        return None
    return min(max(distancias[i:i + quadros]) for i in range(len(distancias) - quadros + 1))


def taxas(genuinas: list[float], impostoras: list[float], limiar: float, falhas_captura: int = 0) -> Ponto:
    """FAR e FRR num limiar. `genuinas` e `impostoras` são pontuações de tentativa."""
    n_gen = len(genuinas) + falhas_captura
    if not n_gen or not impostoras:
        raise ValueError("são precisas tentativas genuínas e de impostor")
    far = sum(p <= limiar for p in impostoras) / len(impostoras)
    frr = (sum(p > limiar for p in genuinas) + falhas_captura) / n_gen
    return Ponto(float(limiar), far, frr)


def curva(genuinas: list[float], impostoras: list[float], falhas_captura: int = 0) -> list[Ponto]:
    """A curva inteira: um ponto em cada limiar em que alguma taxa muda (cada pontuação medida), mais um abaixo de
    todas (nada é aceito), em ordem crescente de limiar."""
    limiares = sorted(set(genuinas) | set(impostoras))
    if not limiares:
        raise ValueError("são precisas tentativas genuínas e de impostor")
    pontos = [taxas(genuinas, impostoras, limiares[0] - 1.0, falhas_captura)]
    pontos += [taxas(genuinas, impostoras, limiar, falhas_captura) for limiar in limiares]
    return pontos


def eer(pontos: list[Ponto]) -> Ponto:
    """Ponto de taxa de erro igual: o limiar em que FAR e FRR ficam mais próximas (empate: o menor limiar). A taxa
    devolvida é a média das duas nesse ponto; com poucas amostras elas raramente são exatamente iguais."""
    melhor = min(pontos, key=lambda p: (abs(p.far - p.frr), p.limiar))
    return Ponto(melhor.limiar, (melhor.far + melhor.frr) / 2, (melhor.far + melhor.frr) / 2)


def maior_limiar_com_far(pontos: list[Ponto], far_maxima: float) -> Ponto:
    """O maior limiar (o mais tolerante, logo a menor FRR) cuja FAR não passa de `far_maxima`."""
    candidatos = [p for p in pontos if p.far <= far_maxima]
    if not candidatos:
        raise ValueError("nenhum limiar atinge essa FAR")
    return max(candidatos, key=lambda p: p.limiar)


def sugerir_limiares(genuinas: list[float], impostoras: list[float], falhas_captura: int = 0,
                     far_nivel_2: float = 0.01) -> dict[int, Sugestao]:
    """Os três limiares da política de calibração: nível 1 no ponto de taxa de erro igual, nível 2 com a FAR até
    `far_nivel_2` (1%) e nível 3 com a menor FAR alcançável. Cada um é limitado pelo do nível anterior: um nível
    mais sensível nunca aceita mais que um menos sensível."""
    pontos = curva(genuinas, impostoras, falhas_captura)
    n1 = eer(pontos)
    n1_real = taxas(genuinas, impostoras, n1.limiar, falhas_captura)
    n2 = maior_limiar_com_far(pontos, far_nivel_2)
    n2 = n2 if n2.limiar <= n1.limiar else n1_real
    far_minima = min(p.far for p in pontos)
    n3 = maior_limiar_com_far(pontos, far_minima)
    n3 = n3 if n3.limiar <= n2.limiar else n2
    return {
        1: Sugestao("taxa de erro igual (EER)", n1.limiar, n1_real.far, n1_real.frr),
        2: Sugestao(f"FAR até {far_nivel_2:.0%}", n2.limiar, n2.far, n2.frr),
        3: Sugestao("menor FAR alcançável", n3.limiar, n3.far, n3.frr),
    }


def limiar_identificacao(corretas: list[float], erradas: list[float], teto: float | None = None) -> Ponto | None:
    """Identificação 1:N. `corretas` são as distâncias dos quadros em que o mais parecido da galeria era a própria
    pessoa; `erradas`, as dos quadros em que era outra pessoa. O limiar sugerido é o maior que ainda recusa toda
    identificação errada (abaixo da menor distância errada), limitado por `teto`: sem nenhuma identificação errada
    medida, os dados não mostram até onde é seguro afrouxar, e no 1:N cada cadastro a mais é mais uma chance de
    erro. Devolve o ponto com far = fração das erradas aceitas (0) e frr = fração das corretas recusadas, ou None
    sem quadros corretos."""
    if not corretas:
        return None
    if not erradas:
        limiar = max(corretas)
    else:
        abaixo = [d for d in corretas if d < min(erradas)]
        limiar = max(abaixo) if abaixo else min(erradas) - 1.0
    if teto is not None:
        limiar = min(limiar, teto)
    far = (sum(d <= limiar for d in erradas) / len(erradas)) if erradas else 0.0
    frr = sum(d > limiar for d in corretas) / len(corretas)
    return Ponto(float(limiar), far, frr)
