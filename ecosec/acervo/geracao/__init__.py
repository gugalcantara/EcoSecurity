"""Geração temporal do acervo.

  series.py   intensidade de ENTRADAS λ_c(t) de cada linha de geração;
  saidas.py   risco de saída h_c(t) por pendência ativa, calibrado por metas de forma e âncora de nível;
  fluxos.py   contagens anuais (arredondamento sistemático) e sorteio de quem entra e quem sai;
  ciclo.py    etapas do ciclo de vida encaixadas entre a entrada e a saída.

A data de encerramento de uma pendência é a data da sua etapa final: nunca é sorteada à parte.
"""
