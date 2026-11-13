"""Renderização de documento com as marcas, numa ordem que não pode mudar.

  1. campos canônicos -> hash_documento (o mesmo para qualquer leitor: identifica o DOCUMENTO);
  2. QR offline (OpenCV) com ecosec://verificar/{TIPO}/{NUMERO}/{hash_documento[:16]}. O esquema
     ecosec:// não aponta para serviço externo: quem confere é ferramentas.verificar_documento;
  3. HTML renderizado, com o QR e o brasão como recursos;
  4. marca visível diagonal repetida com matrícula, instante e hash_consulta (identifica a leitura);
  5. conversão para numpy em BGR (a S9 usa cv2.COLOR_BGR2YCrCb);
  6. S9 (marca invisível DCT) por último: qualquer pintura posterior degradaria os coeficientes;
  7. (no serviço) registro na trilha e só então a entrega.

Os passos 3 a 5 são desenho e moram na interface (ecosec/interface/rasterizar_documento.py):
este módulo recebe a função rasterizar por injeção e não importa PySide6. O que vai no
documento (campos, hash, QR, texto da marca) e a S9 continuam decididos aqui.
"""
import hashlib
import json
from datetime import datetime
from typing import Callable

import cv2
import numpy as np

from ecosec.seguranca.conteudo import s9_rastreio

# (html, matriz do QR, nome do órgão, texto da marca visível) -> imagem BGR sem a S9
Rasterizador = Callable[[str, np.ndarray, str, str], np.ndarray]


def hash_documento(campos: dict) -> str:
    return hashlib.sha256(json.dumps(campos, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def hash_consulta(h_doc: str, matricula: str, instante: datetime) -> str:
    return hashlib.sha256(f"{h_doc}|{matricula}|{instante.isoformat()}".encode()).hexdigest()


def url_verificacao(campos: dict, h_doc: str) -> str:
    return f"ecosec://verificar/{campos['TIPO']}/{campos['NUMERO']}/{h_doc[:16]}"


def qr_modulos(conteudo: str) -> np.ndarray:
    """Matriz do QR code (0 = módulo escuro, 255 = claro), offline, com o codificador do próprio OpenCV."""
    return cv2.QRCodeEncoder.create().encode(conteudo)


def texto_marca(matricula: str, instante: datetime, h_consulta: str) -> str:
    return f"COPIA NAO CONTROLADA · {matricula} · {instante:%d/%m/%Y %H:%M} · {h_consulta[:16].upper()}"


def renderizar(html: str, campos: dict, usuario_id: int, matricula: str, instante: datetime, chave_s9: bytes,
               parametros_s9, rasterizar: Rasterizador) -> tuple[np.ndarray, str, str, str]:
    """Passos 1 a 6. Devolve (imagem BGR já marcada, hash_documento, hash_consulta, texto da marca visível)."""
    h_doc = hash_documento(campos)
    h_consulta = hash_consulta(h_doc, matricula, instante)
    marca = texto_marca(matricula, instante, h_consulta)
    imagem = rasterizar(html, qr_modulos(url_verificacao(campos, h_doc)), campos["ORGAO"], marca)
    marcado = s9_rastreio.marcar(imagem, s9_rastreio.Marca(usuario_id, instante), chave_s9, parametros_s9)
    return marcado, h_doc, h_consulta, marca
