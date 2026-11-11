"""Acervo: geração do conteúdo protegido.

    sinteticos.py   a base do acervo (pendências, responsáveis), determinístico
    desenho.py      a "tela" que desenha um relatório e anota onde pôs cada dado sensível
    mapa.py         o mapa esquemático do Brasil (projeção lon/lat -> pixel)
    relatorios.py   os 9 relatórios do catálogo (A1-xx, A2-xx, A3-xx)

Os relatórios são desenhados NA hora, a partir do banco. Como é o próprio
sistema que desenha cada campo, ele sabe exatamente onde ficou o endereço, a
coordenada, o responsável: as regiões sensíveis saem do próprio desenho, sem
marcação manual (que esquece campos e desalinha quando o layout muda).

Processamento de imagem puro: não importa interface, serviços, repositórios
nem a camada de segurança (quem aplica a tarja é o serviço, depois).
"""
