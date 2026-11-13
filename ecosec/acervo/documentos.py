"""Documentos administrativos das pendências.

Os documentos nascem das etapas do ciclo de vida: não são armazenados, são
derivados de forma determinística da pendência (mesma pendência, mesmos
documentos, mesmos números). Isso mantém o banco do acervo como única fonte e
evita uma tabela que poderia divergir das etapas.

Órgãos emissores fictícios, com nomes que descrevem a função e sem sigla real.
É proibido usar nome, sigla, logotipo ou brasão de órgão real (CETESB, IBAMA,
CNEN, INEA, FEAM). O selo diz "assinado eletronicamente" e não imita marca de
autoridade certificadora.
"""
import hashlib
import html
from datetime import date, timedelta
from string import Template

from ecosec.dominio.acervo import Documento, Pendencia

ORGAO_ESTADUAL = "AGENCIA ESTADUAL DE CONTROLE AMBIENTAL"
ORGAO_NUCLEAR = "AUTORIDADE NACIONAL DE REJEITOS RADIOATIVOS"
ORGAO_MANIFESTOS = "CENTRAL NACIONAL DE MANIFESTOS DE TRANSPORTE"

TIPOS = ("LICENCA DE OPERACAO", "LAUDO DE VISTORIA", "AUTO DE INFRACAO", "TERMO DE AJUSTAMENTO DE CONDUTA",
         "MANIFESTO DE TRANSPORTE")
_PRENOMES = ("ADRIANA", "BRUNO", "CAMILA", "DANIEL", "ELIANE", "FABIO", "GISELE", "HUGO", "IRENE", "JULIO",
             "KATIA", "LEANDRO", "MARCIA", "NELSON", "OLGA", "RENATO")
_SOBRENOMES = ("ANDRADE", "BATISTA", "CAMPOS", "DUARTE", "ESTEVES", "FONSECA", "GUIMARAES", "MACEDO", "NOGUEIRA",
               "PRADO", "QUEIROZ", "RAMOS", "SALES", "TAVARES", "VASCONCELOS", "XAVIER")


def _semente(*partes) -> int:
    return int(hashlib.sha256("|".join(map(str, partes)).encode()).hexdigest()[:12], 16)


def _numero(p: Pendencia, tipo: str, quando: date) -> str:
    return f"{_semente(p.codigo, tipo) % 9000 + 1000:04d}/{quando.year}"


def _data_da_etapa(p: Pendencia, *nomes) -> date | None:
    return next((d for n, d in p.etapas if n in nomes), None)


def documentos_da_pendencia(p: Pendencia, hoje: date) -> list[Documento]:
    """Metadados dos documentos da pendência, em ordem cronológica. Nada posterior a hoje."""
    base = int(p.codigo.split("-")[1]) * 10
    fim = min(hoje, p.data_encerramento) if p.data_encerramento else hoje
    itens = []
    if p.motivo != "MP-06":                       # material órfão: não há empreendimento licenciado conhecido
        anos = 3 + _semente(p.codigo, "LO") % 8
        itens.append(("LICENCA DE OPERACAO", p.data_identificacao - timedelta(days=365 * anos),
                      "VENCIDA" if p.motivo in ("MP-01", "MP-07") else "VIGENTE"))
    vistoria = _data_da_etapa(p, "AVALIACAO PRELIMINAR", "NOTIFICACAO", "DECLARACAO DE FONTE FORA DE USO",
                              "INVENTARIO") or p.data_identificacao + timedelta(days=20)
    if vistoria <= fim:
        itens.append(("LAUDO DE VISTORIA", vistoria, "CONCLUIDO"))
    autuacao = p.prazo_coleta + timedelta(days=30)
    if (p.vencida(hoje) or p.motivo in ("MP-03", "MP-08", "MP-09")) and autuacao <= fim:
        itens.append(("AUTO DE INFRACAO", autuacao, "EM DEFESA" if p.ativa(hoje) else "JULGADO"))
    if p.motivo in ("MP-02", "MP-09"):
        tac = p.data_identificacao + timedelta(days=200 + _semente(p.codigo, "TAC") % 300)
        if tac <= fim:
            itens.append(("TERMO DE AJUSTAMENTO DE CONDUTA", tac, "EM CUMPRIMENTO" if p.ativa(hoje) else "CUMPRIDO"))
    mtr = _data_da_etapa(p, "MTR EMITIDO")
    if p.motivo == "MP-08":
        mtr = mtr or p.data_identificacao + timedelta(days=5)
    if mtr and mtr <= fim:
        itens.append(("MANIFESTO DE TRANSPORTE", mtr, "SEM BAIXA" if p.motivo == "MP-08" and p.ativa(hoje)
                      else "BAIXADO"))
    itens.sort(key=lambda i: i[1])
    return [Documento(base + TIPOS.index(tipo), tipo, _numero(p, tipo, quando), quando, situacao, p.codigo)
            for tipo, quando, situacao in itens]


def orgao(p: Pendencia, tipo: str) -> str:
    if tipo == "MANIFESTO DE TRANSPORTE":
        return ORGAO_MANIFESTOS
    return ORGAO_NUCLEAR if p.classe_risco.startswith("REJEITO RADIOATIVO") else ORGAO_ESTADUAL


def _assinante(p: Pendencia, n: int) -> tuple[str, str, str]:
    s = _semente(p.codigo, "ASSINANTE", n)
    nome = f"{_PRENOMES[s % 16]} {_SOBRENOMES[(s >> 4) % 16]} {_SOBRENOMES[(s >> 8) % 16]}"
    cargo = ("ANALISTA AMBIENTAL", "GERENTE DA AGENCIA REGIONAL")[n - 1]
    return nome, cargo, f"{s % 900000 + 100000}"


def codigo_verificador(hash_documento: str, n: int) -> str:
    """8 dígitos decimais de sha256(hash_documento + n), em grupos de 4: determinístico e verificável."""
    digitos = str(int(hashlib.sha256(f"{hash_documento}{n}".encode()).hexdigest(), 16))[:8]
    return f"{digitos[:4]} {digitos[4:]}"


def campos(doc: Documento, p: Pendencia, atividades: dict, motivos: dict, responsavel: str | None) -> dict:
    """Os campos canônicos do documento (entram no hash_documento)."""
    from ecosec.dominio.acervo import rotulo
    corpo = {
        "LICENCA DE OPERACAO": [("EMPREENDIMENTO", responsavel or "NAO IDENTIFICADO"),
                                ("ATIVIDADE", rotulo(p.atividade, atividades)),
                                ("VALIDADE", f"{doc.data + timedelta(days=4 * 365):%d/%m/%Y}"),
                                ("CONDICIONANTES", "MONITORAMENTO SEMESTRAL DE SOLO E AGUA SUBTERRANEA; "
                                                   "PLANO DE GERENCIAMENTO DE RESIDUOS")],
        "LAUDO DE VISTORIA": [("CONSTATACOES", f"{p.substancia}. {p.quantidade:g} {p.unidade}. "
                                               f"CLASSE {p.classe_risco}."),
                              ("FOTOS", "3 REGISTROS FOTOGRAFICOS ARQUIVADOS NO PROCESSO"),
                              ("CONCLUSAO", f"PASSIVO CONFIRMADO. ETAPA ATUAL: {p.etapa_atual}.")],
        "AUTO DE INFRACAO": [("AUTUADO", responsavel or "RESPONSAVEL NAO IDENTIFICADO"),
                             ("ENQUADRAMENTO", "DECRETO 6.514/2008, ARTS. 61 E 62"),
                             ("DESCRICAO DA INFRACAO", f"DESCUMPRIMENTO DO PRAZO DE COLETA DE {p.prazo_coleta:%d/%m/%Y}"),
                             ("MULTA", f"R$ {10000 + _semente(p.codigo, 'MULTA') % 490000:,.2f}".replace(",", "X")
                              .replace(".", ",").replace("X", ".") + " · PRAZO DE DEFESA: 20 DIAS")],
        "TERMO DE AJUSTAMENTO DE CONDUTA": [("COMPROMISSARIO", responsavel or "NAO IDENTIFICADO"),
                                            ("OBRIGACOES", "CONTENCAO IMEDIATA; PLANO DE INTERVENCAO EM 90 DIAS; "
                                                           "REMEDIACAO CONFORME CRONOGRAMA APROVADO"),
                                            ("MULTA DIARIA", "R$ 5.000,00 POR DIA DE DESCUMPRIMENTO")],
        "MANIFESTO DE TRANSPORTE": [("GERADOR", responsavel or "NAO IDENTIFICADO"),
                                    ("RESIDUO", f"{p.substancia} · {p.classe_risco}"),
                                    ("QUANTIDADE", f"{p.quantidade:g} {p.unidade}"),
                                    ("SITUACAO DA BAIXA", doc.situacao)],
    }[doc.tipo]
    return {"TIPO": doc.tipo, "NUMERO": doc.numero, "DATA": doc.data.isoformat(), "PENDENCIA": p.codigo,
            "ORGAO": orgao(p, doc.tipo), "LOCAL": f"{p.endereco} · {p.municipio}/{p.uf}",
            "COORDENADAS": f"{p.latitude:.5f}, {p.longitude:.5f}", "MOTIVO": rotulo(p.motivo, motivos),
            "SITUACAO": doc.situacao, "CORPO": corpo}


MODELO = Template("""<html><head><style>
  body   { font-family: 'Segoe UI'; font-size: 10pt; color: #1a1a1a; }
  .orgao { font-size: 13pt; font-weight: 600; color: #1f4e79; }
  .tit   { font-size: 16pt; font-weight: 700; text-align: center; letter-spacing: 2px; }
  table.campos { border-collapse: collapse; width: 100%; }
  table.campos td { border: 1px solid #9aa4ae; padding: 4px 6px; vertical-align: top; }
  td.rot { background: #eef2f6; font-weight: 600; width: 28%; }
  table.assin { border-collapse: collapse; width: 100%; margin-top: 18px; }
  td.ass { border: 1px dashed #9aa4ae; padding: 8px 10px; width: 40%; vertical-align: top; }
  .nome-ass { font-weight: 600; }
  .selo { font-size: 7.5pt; color: #1f4e79; }
  td.qr { text-align: center; width: 20%; vertical-align: top; }
  .mini { font-size: 7pt; color: #555555; }
  .rodape { font-size: 7.5pt; color: #555555; margin-top: 14px; }
  .hash { font-family: 'Consolas'; }
</style></head><body>
<table width="100%" style="border-bottom: 3px solid #1f4e79;"><tr>
  <td width="80"><img src="brasao:orgao" width="64" height="64"/></td>
  <td><div class="orgao">$ORGAO</div><div>$MUNICIPIO/$UF</div></td>
  <td align="right"><b>N&ordm; $NUMERO</b><br/>$DATA</td>
</tr></table>
<p class="tit">$TITULO</p>
<table class="campos">
  <tr><td class="rot">PENDENCIA</td><td>$PENDENCIA · $MOTIVO</td></tr>
  <tr><td class="rot">LOCAL</td><td>$LOCAL<br/>$COORDENADAS</td></tr>
  $LINHAS
  <tr><td class="rot">SITUACAO</td><td>$SITUACAO</td></tr>
</table>
<table class="assin"><tr>
  <td class="ass"><br/><br/><div class="nome-ass">$ASSINANTE_1_NOME</div>
    <div>$ASSINANTE_1_CARGO · MATRICULA $ASSINANTE_1_MATRICULA</div>
    <div class="selo">ASSINADO ELETRONICAMENTE EM $DATA · CODIGO VERIFICADOR $ASSINATURA_1_CODIGO</div></td>
  <td class="ass"><br/><br/><div class="nome-ass">$ASSINANTE_2_NOME</div>
    <div>$ASSINANTE_2_CARGO · MATRICULA $ASSINANTE_2_MATRICULA</div>
    <div class="selo">ASSINADO ELETRONICAMENTE EM $DATA · CODIGO VERIFICADOR $ASSINATURA_2_CODIGO</div></td>
  <td class="qr"><img src="qr:documento" width="92" height="92"/><br/><span class="mini">VERIFICACAO DO DOCUMENTO</span></td>
</tr></table>
<p class="rodape">$ORGAO · documento gerado a partir do cadastro · classificacao SECRETO · consulta registrada na
trilha de auditoria · <span class="hash">SHA-256 $HASH_CURTO…</span> · pagina 1 de 1</p>
</body></html>""")


def html_do_documento(c: dict, hash_documento: str, p: Pendencia) -> str:
    e = html.escape
    linhas = "\n  ".join(f'<tr><td class="rot">{e(rotulo)}</td><td>{e(valor)}</td></tr>' for rotulo, valor in c["CORPO"])
    a1, a2 = _assinante(p, 1), _assinante(p, 2)
    data = date.fromisoformat(c["DATA"])
    return MODELO.substitute(
        ORGAO=e(c["ORGAO"]), MUNICIPIO=e(p.municipio), UF=p.uf, NUMERO=e(c["NUMERO"]), DATA=f"{data:%d/%m/%Y}",
        TITULO=e(c["TIPO"]), PENDENCIA=e(c["PENDENCIA"]), MOTIVO=e(c["MOTIVO"]), LOCAL=e(c["LOCAL"]),
        COORDENADAS=e(c["COORDENADAS"]), LINHAS=linhas, SITUACAO=e(c["SITUACAO"]),
        ASSINANTE_1_NOME=a1[0], ASSINANTE_1_CARGO=a1[1], ASSINANTE_1_MATRICULA=a1[2],
        ASSINANTE_2_NOME=a2[0], ASSINANTE_2_CARGO=a2[1], ASSINANTE_2_MATRICULA=a2[2],
        ASSINATURA_1_CODIGO=codigo_verificador(hash_documento, 1),
        ASSINATURA_2_CODIGO=codigo_verificador(hash_documento, 2),
        HASH_CURTO=" ".join(hash_documento[i:i + 4].upper() for i in range(0, 16, 4)))
