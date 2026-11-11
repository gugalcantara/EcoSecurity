"""Vocabulário de exibição: a fonte única dos rótulos que a pessoa lê.

Regra: o rótulo visível é o significado em linguagem simples. Os códigos (KPI-xx, AG-xx, MP-xx, "CLASSE I NBR 10004",
nomes internos de campo) continuam nos DADOS, sem mudança nenhuma (o acervo gerado é idêntico; teste de hash em
`testes/test_ficha.py`), e só aparecem na dica e no glossário. Termos técnicos consagrados ficam em inglês:
"score", não "escore".

Puro, sem Qt: `acervo/` não importa a interface, os serviços nem a segurança (`testes/test_arquitetura.py`).

REGRA DO SUBSTANTIVO
    O objeto do cadastro, nos textos visíveis, é o CASO: "caso" / "casos" ("1.055 casos ativos", "Casos além do
    prazo legal"). "Pendência" continua só no código, nos nomes internos (Pendencia, pendencias, PENDENCIAS) e nos
    títulos de coluna da exportação crua. Texto novo ou reescrito usa `SUBSTANTIVO` / `casos(n)`. O título das
    colunas na tela sai de `titulo_coluna`, que já troca PENDENCIAS por "Casos".

SITUAÇÃO
    O filtro único tem três valores internos (ATIVAS, ENCERRADAS, TODAS, em `acervo/filtro.py`) com os rótulos
    "Ativos", "Encerrados" e "Todos"; o padrão é TODAS. O campo se chama "Situação do caso". Os KPIs continuam
    definidos sobre os casos ativos.

API (o que as telas usam)
    rotulo(codigo, tipo=None)        rótulo curto de exibição ("CLASSE I NBR 10004" -> "Resíduo perigoso")
    codigo(rotulo, tipo)             o inverso, para os combos (mostram o rótulo, filtram pelo código)
    rotulo_longo(codigo, tipo=None)  rótulo longo, quando há (senão o curto)
    definicao(codigo, tipo=None)     a regra de negócio em linguagem simples
    dica(codigo, tipo=None)          definição + fórmula e unidade (KPI) + código e norma: o texto do tooltip
    termo(codigo, tipo=None)         o objeto Termo (ou None)
    titulo_coluna(titulo)            título de exibição de uma coluna da planilha ou do resumo
    casos(n, adjetivo="")            "1 caso", "1.055 casos ativos"
    glossario()                      [Secao(titulo, descricao, termos)], na ordem da aba Glossário
    buscar(texto)                    as seções do glossário só com os termos que contêm o texto (sem acento)
    Dicionários prontos: ROTULO_CLASSE, ROTULO_SITUACAO, ROTULO_KPI, ROTULO_FAIXA, ROTULO_FASE, ROTULO_ETAPA,
    ROTULO_ACAO, ROTULO_RESPONSABILIDADE, ROTULO_MOTIVO, ROTULO_ATIVIDADE, ROTULO_NIVEL.
    `tipo` é um de TIPOS. Sem tipo, o código é procurado na ordem de TIPOS (o mesmo código pode existir em mais de
    um tipo: REMEDIACAO é fase, etapa e categoria de custo). Código desconhecido: o rótulo é o próprio código
    (nunca um erro na tela); o teste `test_vocabulario.py` garante que todo código do acervo tem rótulo.

Nenhum travessão em texto visível.
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass

from ecosec.acervo import fase as _fase
from ecosec.acervo import regras as _regras
from ecosec.acervo.sinteticos import AREA, CLASSE_I, RADIOATIVO

SUBSTANTIVO, SUBSTANTIVO_PLURAL = "caso", "casos"
CAMPO_SITUACAO = "Situação do caso"
CAMPO_ANO, TODOS_OS_ANOS = "Ano", "Todos"     # O ano é a data de corte; "Todos" = a situação atual

TIPOS = ("classe", "situacao", "kpi", "faixa", "risco", "fase", "etapa", "situacao_caso", "acao", "responsabilidade",
         "motivo", "atividade", "campo", "categoria_custo", "prazo", "nivel", "sigilo")
TIPOS_COM_CODIGO = ("classe", "kpi", "motivo", "atividade", "nivel")      # o código interno aparece na dica


@dataclass(frozen=True)
class Termo:
    tipo: str                 # um de TIPOS
    codigo: str               # o valor nos dados (intocado)
    rotulo: str               # rótulo curto de exibição
    definicao: str            # regra de negócio em linguagem simples
    longo: str = ""           # rótulo longo (quando útil)
    formula: str = ""         # KPIs: a conta em linguagem simples
    unidade: str = ""         # KPIs
    referencia: str = ""      # norma ou origem (para a dica e o glossário)

    @property
    def mostrar_codigo(self) -> bool:
        """O código só aparece (dica e glossário) quando é um código de verdade dos dados ou do catálogo."""
        return self.tipo in TIPOS_COM_CODIGO

    @property
    def rotulo_longo(self) -> str:
        return self.longo or self.rotulo


@dataclass(frozen=True)
class Secao:
    titulo: str
    descricao: str
    termos: tuple


def _t(tipo, codigo, rotulo, definicao, **extra) -> Termo:
    return Termo(tipo, codigo, rotulo, definicao, **extra)


def _num(valor: float) -> str:
    return f"{valor:g}".replace(".", ",")


# ================================================================ classes
CLASSES = (
    _t("classe", AREA, "Área contaminada",
       "Terreno onde o solo, a água subterrânea ou o sedimento tem substância perigosa acima do valor de investigação "
       "e, por isso, precisa ser investigado e remediado. A quantidade é medida em m³ de solo.",
       longo="Área contaminada (CONAMA 420)", referencia="Resolução CONAMA 420/2009"),
    _t("classe", CLASSE_I, "Resíduo perigoso",
       "Resíduo que pode causar dano à saúde ou ao ambiente por ser inflamável, corrosivo, reativo, tóxico ou "
       "patogênico. A norma chama de \"Classe I\". Fica armazenado à espera de destino licenciado. A quantidade é "
       "medida em toneladas.",
       longo="Resíduo perigoso (Classe I)", referencia="ABNT NBR 10.004"),
    _t("classe", RADIOATIVO, "Material radioativo",
       "Rejeito com radioatividade acima do limite de isenção e sem uso previsto: fontes seladas fora de uso, "
       "para-raios radioativos e rejeitos de mineração com urânio e tório (NORM). Manuseio e transporte só com "
       "autorização da CNEN. A quantidade é medida em m³.",
       longo="Material radioativo (rejeito CNEN)", referencia="CNEN (Comissão Nacional de Energia Nuclear); "
                                                             "Lei 10.308/2001"),
)

# ================================================================ situação (filtro único)
SITUACOES = (
    _t("situacao", "ATIVAS", "Ativos",
       "Casos identificados até a data de corte e ainda sem solução nessa data (não chegaram à etapa final do "
       "ciclo). É sobre eles que os indicadores são calculados."),
    _t("situacao", "ENCERRADAS", "Encerrados",
       "Casos que chegaram à etapa final do ciclo (encerramento, destinação ou recolhimento) até a data de corte. "
       "Ficam no cadastro como histórico."),
    _t("situacao", "TODAS", "Todos",
       "Ativos e encerrados: todo caso identificado até a data de corte. É o padrão do filtro. Os indicadores "
       "continuam contando só os ativos."),
)


# ================================================================ risco e score
def _texto_score() -> str:
    classe = "; ".join(f"{ROTULO_CLASSE[c].lower()} {_num(p)}" for c, p in
                       sorted(_regras.RISCO_CLASSE.items(), key=lambda cp: -cp[1]))
    grupo = "; ".join(f"{g.lower()} {_num(p)}" for g, p in sorted(_regras.PESO_GRUPO.items(), key=lambda gp: -gp[1]))
    return ("Número que resume a gravidade de um caso: peso da classe × peso do motivo × (1 + anos de atraso no "
            f"prazo previsto). Pesos da classe: {classe}. Pesos do motivo: {grupo}. Sem solução, o atraso cresce e o "
            "score sobe sozinho. A faixa de risco sai do score.")


def _faixas() -> tuple:
    b, m, a = _regras.LIMITES
    definicoes = {"BAIXO": f"Score abaixo de {_num(b)}.",
                  "MEDIO": f"Score de {_num(b)} até menos de {_num(m)}.",
                  "ALTO": f"Score de {_num(m)} até menos de {_num(a)}.",
                  "CRITICO": f"Score de {_num(a)} ou mais: o caso mais grave, a tratar primeiro."}
    rotulos = {"BAIXO": "Baixo", "MEDIO": "Médio", "ALTO": "Alto", "CRITICO": "Crítico"}
    return tuple(_t("faixa", f, rotulos[f], definicoes[f], longo=f"Risco {rotulos[f].lower()}")
                 for f in _regras.CATEGORIAS)


ROTULO_CLASSE = {t.codigo: t.rotulo for t in CLASSES}
FAIXAS = _faixas()
RISCO = (
    _t("risco", "SCORE", "Score de risco", _texto_score(), longo="Score de risco (criticidade)"),
    _t("risco", "FAIXA", "Faixa de risco",
       "Baixo, médio, alto ou crítico, conforme o score de risco do caso na data de hoje. O filtro por faixa usa "
       "sempre a faixa de hoje, mesmo com outro ano escolhido."),
    _t("risco", "INDICE_PRESSAO", "Índice de pressão",
       "Posição relativa de cada UF entre as 27, de 0 (menor pressão) a 1 (maior). Combina o volume de casos ativos, "
       "a fração crítica, o custo estimado e a fração além do prazo legal, cada um como posição no ranking das UFs. "
       "Não é escala física nem valor em reais. Onde o acesso não recebe dado financeiro, o custo não entra: "
       "volume 0,375, fração crítica 0,375 e fração além do prazo legal 0,25."),
)

# ================================================================ KPIs
KPIS = (
    _t("kpi", "KPI-01", "Tempo típico até o encerramento",
       "Quanto tempo um caso costuma levar, da identificação até o encerramento. Metade dos casos encerra antes "
       "da mediana. Conta também os casos ainda abertos, para não fingir que tudo encerra rápido.",
       formula="mediana do tempo entre a identificação e o encerramento, pelo método de Kaplan-Meier (os casos "
               "ainda abertos entram até a data de corte)", unidade="anos"),
    _t("kpi", "KPI-02", "Taxa anual de encerramento",
       "Que parte dos casos abertos no começo do ano foi resolvida durante o ano. O ano corrente é parcial.",
       formula="casos encerrados no ano ÷ casos ativos em 1º de janeiro", unidade="% ao ano"),
    _t("kpi", "KPI-03", "Casos além do prazo legal",
       "Parte dos casos ativos que já passou do prazo legal da sua classe (o tempo máximo que a norma tolera "
       "desde a identificação), mesmo que o prazo previsto ainda não tenha vencido.",
       formula="casos ativos além do prazo legal ÷ casos ativos", unidade="% dos casos ativos"),
    _t("kpi", "KPI-03b", "Casos com prazo previsto vencido",
       "Parte dos casos ativos cujo prazo previsto de coleta (combinado para aquele caso) já passou.",
       formula="casos ativos com o prazo previsto vencido ÷ casos ativos", unidade="% dos casos ativos"),
    _t("kpi", "KPI-04", "Idade dos casos em aberto",
       "Há quanto tempo os casos ativos estão no cadastro: a idade mediana e a distribuição por faixa (menos de 1 "
       "ano, 1 a 3, 3 a 5, 5 a 10, 10 a 20, 20 anos ou mais).",
       formula="anos desde a identificação, dos casos ativos na data de corte", unidade="anos"),
    _t("kpi", "KPI-05", "Custo estimado para resolver",
       "Quanto custaria resolver os casos ativos, somando o custo estimado de cada um (investigação, remediação, "
       "monitoramento e disposição), em reais. Não aparece onde o acesso não recebe dado financeiro.",
       formula="soma, nos casos ativos, de quantidade × custo unitário de cada componente da rota de tratamento",
       unidade="reais (em milhões)"),
)

# ================================================================ fases e etapas
FASES = (
    _t("fase", _fase.IDENTIFICACAO, "Identificação",
       "O caso foi registrado e a autoridade começou a agir (avaliação preliminar, notificação, declaração de fonte "
       "fora de uso, investigação confirmatória), ainda sem diagnóstico nem obra.",
       referencia="Resolução CONAMA 420/2009, art. 23, inciso I"),
    _t("fase", _fase.INVESTIGACAO, "Investigação",
       "Diagnóstico do problema: investigação detalhada, avaliação de risco, inspeção ou inventário.",
       referencia="Resolução CONAMA 420/2009, art. 23, inciso II"),
    _t("fase", _fase.REMEDIACAO, "Remediação",
       "Intervenção física ou contenção: plano de intervenção, remediação, monitoramento, acondicionamento, "
       "transporte ou armazenamento provisório.", referencia="Resolução CONAMA 420/2009, art. 23, inciso III"),
    _t("fase", _fase.ENCERRADA, "Encerrada",
       "A etapa final do ciclo: área reabilitada, resíduo destinado ou material recolhido. A data é a do "
       "encerramento do caso."),
)

_ETAPAS = {
    "IDENTIFICACAO": ("Identificação", "O caso entra no cadastro."),
    "AVALIACAO PRELIMINAR": ("Avaliação preliminar", "Levantamento inicial do histórico do local e dos indícios de "
                                                     "contaminação."),
    "INVESTIGACAO CONFIRMATORIA": ("Investigação confirmatória", "Amostragem para confirmar se há contaminação "
                                                                 "acima do valor de investigação."),
    "INVESTIGACAO DETALHADA": ("Investigação detalhada", "Mede a extensão da contaminação: quanto, onde e em que "
                                                         "meio."),
    "AVALIACAO DE RISCO": ("Avaliação de risco", "Estima o risco à saúde de quem usa ou vai usar o local."),
    "PLANO DE INTERVENCAO": ("Plano de intervenção", "Projeto da remediação, apresentado ao órgão ambiental."),
    "REMEDIACAO": ("Remediação", "Obra que remove ou trata a contaminação."),
    "MONITORAMENTO": ("Monitoramento", "Acompanhamento depois da obra, até provar que a área pode ser reabilitada."),
    "ENCERRAMENTO": ("Encerramento", "Etapa final: área reabilitada para o uso declarado, ou rejeito com destino "
                                     "definitivo."),
    "NOTIFICACAO": ("Notificação", "O responsável é notificado a dar destino ao resíduo."),
    "ACONDICIONAMENTO": ("Acondicionamento", "O material é embalado de forma segura para guarda e transporte."),
    "PLANO DE GERENCIAMENTO": ("Plano de gerenciamento", "Plano de gerenciamento de resíduos, com o destino "
                                                         "previsto."),
    "MTR EMITIDO": ("Manifesto de transporte emitido", "Foi emitido o Manifesto de Transporte de Resíduos (MTR), "
                                                       "que acompanha a carga até o destino."),
    "COLETA": ("Coleta", "A carga sai do local com empresa licenciada."),
    "DESTINACAO": ("Destinação", "Etapa final: o resíduo chegou ao tratamento ou à disposição licenciada, com "
                                 "certificado."),
    "DECLARACAO DE FONTE FORA DE USO": ("Declaração de fonte fora de uso", "O dono declara à CNEN que a fonte "
                                                                           "radioativa não é mais usada."),
    "INSPECAO": ("Inspeção", "Vistoria da fonte ou do local pela autoridade nuclear."),
    "TRANSPORTE AUTORIZADO": ("Transporte autorizado", "A CNEN autorizou o transporte do material."),
    "RECOLHIMENTO": ("Recolhimento", "Etapa final: o material foi recolhido a um depósito da CNEN."),
    "INVENTARIO": ("Inventário", "Levantamento do volume e da atividade do rejeito armazenado."),
    "ARMAZENAMENTO PROVISORIO": ("Armazenamento provisório", "Rejeito guardado à espera de um destino final que "
                                                             "ainda não existe no país."),
}
_ROTULO_DA_FASE = {f.codigo: f.rotulo for f in FASES}
ETAPAS = tuple(_t("etapa", e, r, f"{d} Fase: {_ROTULO_DA_FASE[_fase.FASE_DA_ETAPA[e]].lower()}.")
               for e, (r, d) in _ETAPAS.items())

_SITUACOES_CASO = {
    "PENDENTE": ("Pendente", "Registrado, aguardando a primeira providência."),
    "EM NOTIFICACAO": ("Em notificação", "O responsável foi ou está sendo notificado."),
    "EM INVESTIGACAO": ("Em investigação", "Em investigação confirmatória, detalhada ou avaliação de risco."),
    "EM REMEDIACAO": ("Em remediação", "Obra de remediação em andamento."),
    "EM MONITORAMENTO": ("Em monitoramento", "Obra concluída; acompanhamento até a reabilitação."),
    "ARMAZENADA": ("Armazenado", "Material guardado provisoriamente, à espera de destino final."),
    "EM PROCESSO": ("Em andamento", "Etapa intermediária sem nome próprio (plano, acondicionamento, transporte). "
                                    "Veja a fase para saber em que ponto está."),
    "REABILITADA": ("Reabilitada", "Área contaminada encerrada: reabilitada para o uso declarado."),
    "DESTINADA": ("Destinado", "Resíduo perigoso encerrado: chegou ao destino licenciado."),
    "COLETADA": ("Recolhido", "Fonte radioativa encerrada: recolhida pela CNEN."),
    "ENCERRADA": ("Encerrado", "Rejeito encerrado com destino definitivo."),
}
SITUACOES_CASO = tuple(_t("situacao_caso", c, r, d) for c, (r, d) in _SITUACOES_CASO.items())

# ================================================================ ação recomendada e responsabilidade financeira
_ACOES = {
    _regras.ESCALAR_MP: ("Levar ao Ministério Público", "Cobrança administrativa esgotada: caso crítico de "
                                                        "responsável cobrável com atraso maior que o limite de "
                                                        "escalonamento. Cabe ação civil pública."),
    "AUTUAR E RASTREAR A CARGA": ("Autuar e rastrear a carga", "A carga saiu com manifesto e não chegou ao destino: "
                                                              "rastrear gerador, transportador e destinador e "
                                                              "autuar quem não deu baixa."),
    "PRIORIZAR NO ORCAMENTO PUBLICO": ("Priorizar no orçamento público", "Não há a quem cobrar e o risco é alto ou "
                                                                        "crítico: entra na fila do programa "
                                                                        "público de remediação."),
    "NOTIFICACAO URGENTE": ("Notificação urgente", "Responsável cobrável, prazo previsto vencido e risco alto ou "
                                                   "crítico."),
    "BUSCAR DESTINO TECNICO": ("Buscar destino técnico", "Falta onde tratar: abrir capacidade de tratamento ou vaga "
                                                         "no depósito."),
    "NOTIFICAR O RESPONSAVEL": ("Notificar o responsável", "Responsável cobrável com o prazo previsto vencido."),
    "ACOMPANHAR O PRAZO": ("Acompanhar o prazo", "O prazo previsto ainda não venceu, ou o risco ainda não justifica "
                                                 "gasto público: acompanhar."),
}
ACOES = tuple(_t("acao", c, r, d) for c, (r, d) in _ACOES.items())

_RESPONSABILIDADES = {
    _regras.COBRAVEL: ("Cobrável do responsável", "Existe um responsável identificado que deve pagar (gerador, "
                                                  "sucessor ou proprietário): a remediação é cobrada dele.",
                       "Lei 6.938/1981, art. 14 (responsabilidade objetiva)"),
    _regras.PUBLICO: ("Orçamento público", "Não há a quem cobrar (material órfão ou passivo descoberto depois): o "
                                           "poder público paga e cobra depois, se achar o responsável.",
                      "Lei 12.305/2010, art. 29"),
    _regras.INFRAESTRUTURA: ("Investimento em infraestrutura", "Falta instalação licenciada para tratar ou guardar "
                                                               "o material: o gasto é em capacidade, não no caso.",
                             ""),
    _regras.FISCALIZACAO: ("Fiscalização e rastreio", "A carga desapareceu: primeiro é preciso achá-la e achar o "
                                                      "responsável.", "Portaria MMA 280/2020 (MTR e CDF)"),
}
RESPONSABILIDADES = tuple(_t("responsabilidade", c, r, d, referencia=ref) for c, (r, d, ref) in
                          _RESPONSABILIDADES.items())

# ================================================================ motivos (MP-xx) e atividades (AG-xx)
_MOTIVOS = {
    "MP-01": ("Empresa responsável fechou ou faliu", "A empresa que gerou o problema deixou de existir ou está em "
                                                     "falência. A obrigação passa a sucessores e a quem compra o "
                                                     "imóvel, mas é preciso localizá-los."),
    "MP-02": ("Disputa sobre quem paga", "Proprietário, gerador e comprador discutem a quem cabe a remediação; "
                                         "enquanto isso, ninguém executa."),
    "MP-03": ("Responsável adia pelo custo", "O responsável existe e pode pagar, mas adia a destinação por causa do "
                                             "custo; o resíduo segue guardado no local."),
    "MP-04": ("Sem empresa licenciada para tratar", "Não há instalação licenciada a uma distância viável para aquele "
                                                    "tipo de resíduo."),
    "MP-05": ("Sem depósito final no país", "Rejeito radioativo à espera do repositório nacional, que ainda não "
                                            "existe."),
    "MP-06": ("Sem responsável identificado", "Material órfão: ninguém foi identificado. O poder público age e cobra "
                                              "depois, se alguém aparecer."),
    "MP-07": ("Contaminação descoberta depois", "Contaminação achada anos depois do fim da atividade (passivo "
                                                "histórico)."),
    "MP-08": ("Carga sem comprovante de destino", "O manifesto de transporte foi emitido, mas nunca veio o "
                                                  "certificado de destinação: a carga pode ter sido desviada."),
    "MP-09": ("Bloqueado por ordem judicial ou embargo", "Qualquer intervenção no local depende de autorização "
                                                         "judicial ou administrativa."),
    "MP-10": ("Aguardando licença de remediação", "O plano de intervenção foi protocolado e espera análise e licença "
                                                  "do órgão ambiental."),
}
MOTIVOS = tuple(_t("motivo", c, r, d) for c, (r, d) in _MOTIVOS.items())

_ATIVIDADES = {
    "AG-01": ("Postos de combustíveis", "Vazamento de tanques e linhas, área de abastecimento e troca de óleo."),
    "AG-02": ("Indústria química e de agrotóxicos", "Fabricação e estoque de produtos químicos e agrotóxicos, "
                                                    "inclusive obsoletos."),
    "AG-03": ("Galvanoplastia", "Revestimento de metais em banhos com cromo, níquel, zinco e cianeto."),
    "AG-04": ("Metalurgia e fundição", "Fornos, pátios de escória e subestação interna."),
    "AG-05": ("Aterro de resíduos perigosos", "Células, lagoas de chorume e unidades de tratamento de resíduo "
                                              "perigoso."),
    "AG-06": ("Transformadores com ascarel", "Manutenção e depósito de transformadores com óleo contaminado por PCB "
                                             "(ascarel, proibido desde 1981)."),
    "AG-07": ("Mineração com radioatividade natural", "Minério com urânio e tório associados (NORM), pilhas de "
                                                      "estéril e galpões de insumos."),
    "AG-08": ("Radioterapia e fontes radioativas", "Fontes seladas de saúde e pesquisa e para-raios radioativos "
                                                   "recolhidos."),
    "AG-09": ("Curtumes", "Curtimento de couro ao cromo."),
    "AG-10": ("Refino e terminais de petróleo", "Refinarias e terminais de armazenamento de derivados."),
    "AG-11": ("Celulose e papel", "Lagoas de licor negro e sedimentos com organoclorados."),
    "AG-12": ("Lavanderias e tinturarias", "Lavagem a seco e tingimento com solventes clorados."),
    "AG-13": ("Garimpo de ouro com mercúrio", "Extração de ouro com mercúrio, em balsas e barrancos."),
}
ATIVIDADES = tuple(_t("atividade", c, r, d) for c, (r, d) in _ATIVIDADES.items())

# ================================================================ campos da ficha e categorias de custo
CAMPOS = (
    _t("campo", "CODIGO", "Código do caso", "Identificador do caso no cadastro: as letras PD e um número de quatro dígitos."),
    _t("campo", "SUBSTANCIA", "Substância", "O que contamina ou o que está guardado, como registrado no caso."),
    _t("campo", "QUANTIDADE", "Quantidade", "Volume ou massa do passivo, na unidade da classe: toneladas para "
                                            "resíduo perigoso, m³ para área contaminada e material radioativo. "
                                            "Unidades diferentes nunca se somam."),
    _t("campo", "ATIVIDADE", "Atividade de origem", "A atividade econômica que gerou o passivo (posto, indústria, "
                                                    "mineração...)."),
    _t("campo", "MOTIVO", "Motivo da permanência", "Por que o caso continua sem solução. O motivo define quem paga e "
                                                   "que ação resolve."),
    _t("campo", "CONTAMINANTE", "Contaminante", "O grupo químico ou radiológico da substância (metais, "
                                                "hidrocarbonetos, PCB, radionuclídeos...)."),
    _t("campo", "MEIO", "Meio afetado", "Onde o contaminante está: solo, água subterrânea ou sedimento, na área "
                                        "contaminada; no resíduo e no material radioativo, a própria matriz "
                                        "(resíduo sólido, líquido, equipamento, fonte selada)."),
    _t("campo", "RESTRICAO", "Restrição de uso", "O que fica proibido ou controlado no local enquanto o caso não se "
                                                 "resolve (e, na área reabilitada, depois), conforme a classe, "
                                                 "a fase e o meio."),
    _t("campo", "USO_ANTERIOR", "Uso anterior", "O uso do local que gerou o passivo, derivado da atividade de "
                                                "origem."),
    _t("campo", "USO_PRETENDIDO", "Uso pretendido", "Só na área contaminada: o uso futuro que orienta a remediação "
                                                    "(agrícola, residencial ou industrial).",
       referencia="Resolução CONAMA 420/2009"),
    _t("campo", "MEMORIA", "Memória de cálculo", "De onde vem o custo estimado: cada componente da rota de "
                                                 "tratamento, como quantidade × custo unitário, agrupado nas quatro "
                                                 "categorias de custo."),
    _t("campo", "ROTA", "Rota de tratamento", "O caminho técnico previsto para resolver o caso (incineração, "
                                              "coprocessamento, remediação com bombeamento, depósito da CNEN...)."),
    _t("campo", "CUSTO_ESTIMADO", "Custo estimado", "Quanto custaria resolver o caso pela rota de tratamento, em "
                                                    "reais. Não aparece onde o acesso não recebe dado "
                                                    "financeiro."),
    _t("campo", "IDENTIFICACAO", "Identificado em", "Data em que o caso entrou no cadastro. Conta a idade do caso e "
                                                    "o prazo legal."),
    _t("campo", "ETAPA", "Etapa atual", "O último passo do ciclo já cumprido. Cada classe tem o seu ciclo de "
                                        "etapas."),
    _t("campo", "SITUACAO_CASO", "Andamento", "Situação administrativa do caso, derivada da etapa (pendente, em "
                                              "investigação, em remediação...)."),
    _t("campo", "ATRASO", "Atraso", "Dias desde o prazo previsto vencido (para de contar no encerramento)."),
)
CATEGORIAS_CUSTO = (
    _t("categoria_custo", "INVESTIGACAO", "Investigação", "Diagnóstico: amostragem, análises e avaliação de risco."),
    _t("categoria_custo", "REMEDIACAO", "Remediação", "Obra ou contenção no próprio local."),
    _t("categoria_custo", "MONITORAMENTO", "Monitoramento", "Acompanhamento depois da intervenção."),
    _t("categoria_custo", "DISPOSICAO", "Disposição", "Transporte, tratamento e destino fora do local."),
)


# ================================================================ prazos
def _texto_prazo_legal() -> str:
    try:
        sla = _regras.ParametrosRegras.padrao().sla_dias
        partes = "; ".join(f"{ROTULO_CLASSE[c].lower()}, {sla[c]} dias" for c in (RADIOATIVO, CLASSE_I, AREA)
                           if c in sla)
        valores = f" Prazos usados: {partes}."
    except Exception:  # noqa: BLE001, sem configuração, a definição sai sem os números
        valores = ""
    return ("O tempo máximo que a norma tolera, desde a identificação, para resolver um caso da sua classe. "
            "Passou dele: \"além do prazo legal\", mesmo que o prazo previsto ainda não tenha vencido." + valores)


PRAZOS = (
    _t("prazo", "PRAZO_COLETA", "Prazo previsto",
       "A data prevista para a coleta ou a solução daquele caso, que pode ter sido negociada com o responsável. "
       "Passou dela sem solução: \"prazo previsto vencido\".", longo="Prazo previsto de coleta"),
    _t("prazo", "PRAZO_LIMITE", "Prazo legal", _texto_prazo_legal(), longo="Prazo-limite legal da classe"),
    _t("prazo", "VENCIDO", "Prazo previsto vencido",
       "O prazo previsto já passou e o caso continua ativo. É o indicador \"Casos com prazo previsto vencido\"."),
    _t("prazo", "ALEM_DO_PRAZO", "Além do prazo legal",
       "O caso continua ativo depois do prazo legal da classe. É o indicador \"Casos além do prazo legal\"."),
    _t("prazo", "CORTE", "Data de corte",
       "A data em que os números são calculados: hoje ou o fim do ano escolhido. Ativo e encerrado sempre se "
       "referem a ela."),
)

# ================================================================ níveis de acesso e sigilo
NIVEIS = (
    _t("nivel", "N1", "Nível 1 · Uso interno",
       "Servidores com permissão geral. Só totais agregados que ajudam a entender o quadro: nenhum endereço, "
       "coordenada, CNPJ, nome de pessoa ou empresa, e nenhum valor em reais. Todo total passa pela supressão de "
       "grupos pequenos."),
    _t("nivel", "N2", "Nível 2 · Reservado",
       "Diretores de divisão. Os casos da própria UF, um a um, com endereço, responsáveis (empresas) e custo "
       "estimado, para priorizar e agir. Exportação com marca d'água e conferência do rosto."),
    _t("nivel", "N3", "Nível 3 · Secreto",
       "Custódia nacional. Todos os casos do país, com responsáveis (inclusive pessoas físicas), custo por "
       "responsável e documentos. Só visualização: não exporta."),
)
SIGILO = (
    _t("sigilo", "SUPRESSAO", "Supressão de grupos pequenos",
       "Nos totais agregados, todo total que junta menos de 3 casos aparece como SUPRIMIDO. Assim ninguém consegue "
       "reconhecer um caso específico (por exemplo, \"o único rejeito radioativo do estado X\")."),
    _t("sigilo", "COMPLEMENTAR", "Supressão complementar",
       "Às vezes um segundo número também é escondido, mesmo sendo grande: sem isso, daria para descobrir o "
       "número suprimido por subtração (o total menos as partes que aparecem)."),
    _t("sigilo", "SUPRIMIDO", "SUPRIMIDO",
       "Número escondido pela supressão de grupos pequenos. Não quer dizer zero."),
    _t("sigilo", "TARJA", "Tarja",
       "Faixa que cobre, no relatório, o que o seu acesso não pode ver (endereço, coordenada, responsável)."),
    _t("sigilo", "MARCA", "Marca d'água",
       "Identificação de quem abriu o documento e quando, gravada na imagem. Permite rastrear um vazamento."),
)

# ================================================================ índices
TODOS_OS_TERMOS = (*CLASSES, *SITUACOES, *KPIS, *FAIXAS, *RISCO, *FASES, *ETAPAS, *SITUACOES_CASO, *ACOES,
                   *RESPONSABILIDADES, *MOTIVOS, *ATIVIDADES, *CAMPOS, *CATEGORIAS_CUSTO, *PRAZOS, *NIVEIS, *SIGILO)
_INDICE = {(t.tipo, t.codigo): t for t in TODOS_OS_TERMOS}

ROTULO_SITUACAO = {t.codigo: t.rotulo for t in SITUACOES}
ROTULO_KPI = {t.codigo: t.rotulo for t in KPIS}
ROTULO_FAIXA = {t.codigo: t.rotulo for t in FAIXAS}
ROTULO_FASE = {t.codigo: t.rotulo for t in FASES}
ROTULO_ETAPA = {t.codigo: t.rotulo for t in ETAPAS}
ROTULO_SITUACAO_CASO = {t.codigo: t.rotulo for t in SITUACOES_CASO}
ROTULO_ACAO = {t.codigo: t.rotulo for t in ACOES}
ROTULO_RESPONSABILIDADE = {t.codigo: t.rotulo for t in RESPONSABILIDADES}
ROTULO_MOTIVO = {t.codigo: t.rotulo for t in MOTIVOS}
ROTULO_ATIVIDADE = {t.codigo: t.rotulo for t in ATIVIDADES}
ROTULO_CATEGORIA_CUSTO = {t.codigo: t.rotulo for t in CATEGORIAS_CUSTO}
ROTULO_NIVEL = {t.codigo: t.rotulo for t in NIVEIS}
# a situação dentro de uma frase de contagem ("de 2.400 casos ativos e encerrados em 25/10/2026")
ADJETIVO_SITUACAO = {"ATIVAS": "ativos", "ENCERRADAS": "encerrados", "TODAS": "ativos e encerrados"}
FRASE_SITUACAO = {s: f"casos {a}" for s, a in ADJETIVO_SITUACAO.items()}


def termo(codigo: str, tipo: str | None = None) -> Termo | None:
    if tipo is not None:
        return _INDICE.get((tipo, codigo))
    return next((_INDICE[(t, codigo)] for t in TIPOS if (t, codigo) in _INDICE), None)


def rotulo(codigo: str, tipo: str | None = None) -> str:
    """Rótulo curto de exibição; o próprio código quando não há termo (nunca um erro na tela)."""
    t = termo(codigo, tipo)
    return t.rotulo if t else codigo


def codigo(rotulo_exibido: str, tipo: str) -> str | None:
    """O código interno de um rótulo de exibição do tipo (o inverso de `rotulo`): os combos mostram o rótulo e
    filtram pelo código. None quando o rótulo não é de nenhum termo do tipo."""
    return next((t.codigo for t in TODOS_OS_TERMOS if t.tipo == tipo and t.rotulo == rotulo_exibido), None)


def rotulo_longo(codigo: str, tipo: str | None = None) -> str:
    t = termo(codigo, tipo)
    return t.rotulo_longo if t else codigo


def definicao(codigo: str, tipo: str | None = None) -> str:
    t = termo(codigo, tipo)
    return t.definicao if t else ""


def dica(codigo: str, tipo: str | None = None) -> str:
    """Texto do tooltip: definição; no KPI, a fórmula e a unidade; por fim o código interno e a norma."""
    t = termo(codigo, tipo)
    if t is None:
        return ""
    linhas = [f"{t.rotulo_longo}: {t.definicao}"]
    if t.formula:
        linhas.append(f"Cálculo: {t.formula}.")
    if t.unidade:
        linhas.append(f"Unidade: {t.unidade}.")
    rodape = [x for x in ((f"código {t.codigo}" if t.mostrar_codigo else ""), t.referencia) if x]
    if rodape:
        linhas.append(" · ".join(rodape))
    return "\n".join(linhas)


def casos(n: int | None, adjetivo: str = "") -> str:
    """"1 caso", "1.055 casos ativos" (milhar com ponto). None: SUPRIMIDO."""
    if n is None:
        return "SUPRIMIDO"
    numero = f"{n:,}".replace(",", ".")
    nome = SUBSTANTIVO if n == 1 else SUBSTANTIVO_PLURAL
    if adjetivo and n == 1 and adjetivo.endswith("s"):
        adjetivo = adjetivo[:-1]
    return f"{numero} {nome}" + (f" {adjetivo}" if adjetivo else "")


def itens_ano(inicio: int, hoje) -> list[str]:
    """A lista "Ano" do N1 e do N3: "Todos" e os anos anteriores ao corrente, do mais recente a `inicio`.
    O ano corrente não entra: o corte dele é hoje, o mesmo de "Todos"."""
    return [TODOS_OS_ANOS, *(str(a) for a in range(hoje.year - 1, inicio - 1, -1))]


def dica_ano(ano: int | None, hoje) -> str:
    """Dica da lista "Ano": o ano é a DATA DE CORTE (a situação em 31/12), não "casos do ano"; None = Todos."""
    atual = f"situação atual, em {hoje:%d/%m/%Y}"
    if ano is None:
        return f"Todos: {atual}. O ano é a data de corte: escolha um ano para ver a situação em 31/12 dele."
    return f"{ano}: situação em 31/12/{ano} (o ano é a data de corte). Todos: {atual}."


# ================================================================ títulos de coluna (só exibição; a exportação é crua)
_TITULOS = {
    "CODIGO": "Código", "SUBSTANCIA": "Substância", "CLASSE DE RISCO": "Classe", "QUANTIDADE": "Quantidade",
    "UNIDADE": "Unidade", "ATIVIDADE": "Atividade de origem", "MOTIVO": "Motivo da permanência",
    "LOGRADOURO": "Logradouro", "NUMERO": "Número", "COMPLEMENTO": "Complemento", "BAIRRO": "Bairro",
    "MUNICIPIO": "Município", "UF": "UF", "CEP": "CEP", "LATITUDE": "Latitude", "LONGITUDE": "Longitude",
    "IDENTIFICACAO": "Identificado em", "PRAZO DE COLETA": "Prazo previsto", "ATRASO DIAS": "Atraso (dias)",
    "SITUACAO": "Andamento", "ETAPA ATUAL": "Etapa atual", "ENCERRAMENTO": "Encerrado em",
    "CRITICIDADE": "Score de risco", "NIVEL DE RISCO": "Faixa de risco", "PRAZO LIMITE": "Prazo legal",
    "DIAS ALEM DO PRAZO LIMITE": "Dias além do prazo legal", "CUSTO ESTIMADO": "Custo estimado",
    "RESPONSABILIDADE": "Quem paga", "ACAO RECOMENDADA": "Ação recomendada",
    # resumo agregado
    "PENDENCIAS": "Casos", "FORA DA PREVISAO": "Prazo previsto vencido",
    "PERCENTUAL FORA DA PREVISAO": "% prazo previsto vencido", "CRITICAS": "Críticos",
    "TONELADAS CLASSE I": "Resíduo perigoso (t)", "M3 SOLO AREA CONTAMINADA": "Área contaminada (m³ de solo)",
    "M3 REJEITO RADIOATIVO": "Material radioativo (m³)",
    "ATRASO MEDIO FORA DA PREVISAO (DIAS)": "Atraso médio dos vencidos (dias)",
    "ALEM DO PRAZO LIMITE": "Além do prazo legal", "PERCENTUAL ALEM DO PRAZO LIMITE": "% além do prazo legal",
    "REGIAO": "Região", "NOME": "Nome",
    # priorização e custo por responsável (N3)
    "ORDEM": "Ordem", "FAIXA": "Faixa de risco", "SCORE": "Score de risco", "CUSTO (R$)": "Custo (R$)",
    "ACUMULADO NA FILA (R$)": "Acumulado na fila (R$)", "RESPONSAVEL": "Responsável", "VINCULOS": "Vínculos",
    "CUSTO ATIVO COBRAVEL (R$)": "Custo ativo cobrável (R$)",
}
# valores de célula que têm rótulo (a ordenação e a exportação usam o valor cru)
TIPO_DA_CELULA = {"CLASSE DE RISCO": "classe", "NIVEL DE RISCO": "faixa", "FAIXA": "faixa",
                  "RESPONSABILIDADE": "responsabilidade", "ACAO RECOMENDADA": "acao", "ETAPA ATUAL": "etapa",
                  "SITUACAO": "situacao_caso", "ATIVIDADE": "atividade", "MOTIVO": "motivo"}


def titulo_coluna(titulo: str) -> str:
    """Título de exibição de uma coluna da planilha ou do resumo (o título interno fica na exportação)."""
    return _TITULOS.get(titulo, titulo)


# coluna -> termo cuja definição vira a dica do cabeçalho
_DICA_DA_COLUNA = {
    "CLASSE DE RISCO": ("FAIXA_CLASSE", None), "CRITICIDADE": ("SCORE", "risco"), "SCORE": ("SCORE", "risco"),
    "NIVEL DE RISCO": ("FAIXA", "risco"), "FAIXA": ("FAIXA", "risco"), "PRAZO DE COLETA": ("PRAZO_COLETA", "prazo"),
    "PRAZO LIMITE": ("PRAZO_LIMITE", "prazo"), "DIAS ALEM DO PRAZO LIMITE": ("ALEM_DO_PRAZO", "prazo"),
    "ALEM DO PRAZO LIMITE": ("ALEM_DO_PRAZO", "prazo"), "FORA DA PREVISAO": ("VENCIDO", "prazo"),
    "ATRASO DIAS": ("ATRASO", "campo"), "CUSTO ESTIMADO": ("CUSTO_ESTIMADO", "campo"),
    "ATIVIDADE": ("ATIVIDADE", "campo"), "MOTIVO": ("MOTIVO", "campo"), "SITUACAO": ("SITUACAO_CASO", "campo"),
    "ETAPA ATUAL": ("ETAPA", "campo"), "QUANTIDADE": ("QUANTIDADE", "campo"),
    "IDENTIFICACAO": ("IDENTIFICACAO", "campo"),
}


def dica_coluna(titulo: str) -> str:
    """A definição do campo de uma coluna (dica do cabeçalho), ou "" quando o título já basta."""
    codigo_termo, tipo = _DICA_DA_COLUNA.get(titulo, (None, None))
    if codigo_termo == "FAIXA_CLASSE":
        return "Classe do passivo: " + "; ".join(f"{t.rotulo} ({t.referencia})" for t in CLASSES) + "."
    t = termo(codigo_termo, tipo) if codigo_termo else None
    return f"{t.rotulo_longo}: {t.definicao}" if t else ""


def celula(titulo: str, valor):
    """Valor de exibição de uma célula com rótulo (classe, faixa, quem paga, ação, etapa, andamento)."""
    tipo = TIPO_DA_CELULA.get(titulo)
    if tipo and isinstance(valor, str):
        codigo_ = valor.split(" · ")[0] if tipo in ("atividade", "motivo") else valor   # "AG-05 · NOME" -> "AG-05"
        t = termo(codigo_, tipo)
        return t.rotulo if t else valor
    return valor


# ================================================================ glossário
_SECOES = (
    ("Classes", "As três classes de passivo do cadastro. O nome técnico e a norma de origem ficam na referência.",
     CLASSES),
    ("Situação", f"O filtro \"{CAMPO_SITUACAO}\", que vale para o mapa e a planilha. Padrão: Todos.", SITUACOES),
    ("Risco e score", "Como a gravidade de um caso é medida.", (*RISCO, *FAIXAS)),
    ("Indicadores (KPIs)", "Os indicadores do painel, pelo nome do que medem. Todos contam só os casos ativos na data "
                           "de corte. O código (KPI-xx) é a referência do catálogo.", KPIS),
    ("Fases e etapas", "A fase agrupa as etapas de todos os ciclos em quatro passos, na ordem do processo.",
     (*FASES, *ETAPAS)),
    ("Andamento", "A situação administrativa registrada em cada caso, derivada da etapa.", SITUACOES_CASO),
    ("Ação recomendada", "A providência que o caso exige agora, pela regra de escalonamento.", ACOES),
    ("Responsabilidade financeira", "Quem paga a solução do caso, pelo motivo da permanência.", RESPONSABILIDADES),
    ("Motivos", "Por que o caso continua sem solução.", MOTIVOS),
    ("Atividades", "A atividade econômica que gerou o passivo.", ATIVIDADES),
    ("Campos da ficha", "Os campos que aparecem na ficha, na planilha e nos relatórios.", (*CAMPOS,
                                                                                          *CATEGORIAS_CUSTO)),
    ("Prazos", "Dois prazos diferentes: o previsto (do caso) e o legal (da norma, por classe).", PRAZOS),
    ("Níveis de acesso e sigilo", "Quem vê o quê, e como os números pequenos são protegidos.", (*NIVEIS, *SIGILO)),
)
SECOES_GLOSSARIO = tuple(titulo for titulo, _, _ in _SECOES)


def glossario(camada=None) -> list[Secao]:
    """As seções da aba Glossário, na ordem. Só definições: nenhum dado do acervo (seguro para o N1). Com
    `camada`, o termo de nível é só o da própria camada (escopo exclusivo): as outras nem são citadas."""
    secoes = []
    for titulo, descricao, termos in _SECOES:
        if camada is not None:
            termos = tuple(t for t in termos if t.tipo != "nivel" or t.codigo == f"N{int(camada)}")
        secoes.append(Secao(titulo, descricao, tuple(termos)))
    return secoes


def sem_acento(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn").lower()


def texto_de_busca(t: Termo) -> str:
    return sem_acento(" ".join((t.rotulo, t.longo, t.definicao, t.formula, t.codigo, t.referencia)))


def buscar(texto: str, camada=None) -> list[Secao]:
    """As seções com os termos cujo rótulo, definição, código ou norma contêm `texto` (sem acento, sem caixa)."""
    alvo = sem_acento(texto.strip())
    if not alvo:
        return glossario(camada)
    resultado = []
    for s in glossario(camada):
        termos = tuple(t for t in s.termos if alvo in texto_de_busca(t))
        if termos:
            resultado.append(Secao(s.titulo, s.descricao, termos))
    return resultado


# ================================================================ (analítico N2 e N3): rótulos extras
# Só exibição. Os códigos continuam nos dados e na exportação crua.
ROTULO_AGRUPAMENTO = {
    "POR UF": "Por UF", "POR REGIAO": "Por região", "POR ATIVIDADE GERADORA": "Por atividade de origem",
    "POR MOTIVO DA PERMANENCIA": "Por motivo da permanência", "POR CLASSE DE RISCO": "Por classe",
    "POR NIVEL DE RISCO": "Por faixa de risco", "POR ACAO RECOMENDADA": "Por ação recomendada",
    "POR RESPONSABILIDADE FINANCEIRA": "Por quem paga", "POR UF E ATIVIDADE": "Por UF e atividade de origem",
}
ROTULO_CRITERIO = {"MAIOR REDUCAO DE RISCO POR REAL": "Maior redução de risco por real",
                   "MAIOR RISCO PRIMEIRO": "Maior risco primeiro"}
DEFINICAO_CRITERIO = {
    "MAIOR REDUCAO DE RISCO POR REAL": "Leva primeiro o caso que tira mais score de risco por real gasto.",
    "MAIOR RISCO PRIMEIRO": "Leva primeiro o caso de maior score de risco, mesmo que seja caro.",
}
ROTULO_VINCULO = {"GERADOR_ORIGINAL": "Gerador original", "SUCESSOR": "Sucessor",
                  "PROPRIETARIO_ATUAL": "Proprietário atual", "TRANSPORTADOR": "Transportador",
                  "DESTINADOR": "Destinador"}
ROTULO_CUSTODIA = {"DEFINITIVO": "Depósito definitivo", "INTERMEDIARIO": "Depósito intermediário",
                   "NORM": "Armazém de NORM", "INICIAL": "Armazenamento inicial"}
ROTULO_SITUACAO_CADASTRAL = {"ATIVA": "ativa", "SUSPENSA": "suspensa", "BAIXADA": "baixada", "INAPTA": "inapta"}
# base legal de cada motivo, como se escreve (o catálogo do acervo guarda em maiúsculas)
BASE_LEGAL = {
    "MP-01": "Lei 6.938/1981, art. 14, § 1º (responsabilidade objetiva); STJ, Súmula 623 (natureza propter rem)",
    "MP-02": "STJ, Súmula 623 (cobrança dos atuais ou anteriores, à escolha do credor)",
    "MP-03": "ABNT NBR 10.004; Lei 12.305/2010",
    "MP-04": "Lei 12.305/2010",
    "MP-05": "Lei 10.308/2001",
    "MP-06": "Lei 12.305/2010, art. 29 (atuação subsidiária do poder público)",
    "MP-07": "STF, Tema 999 (RE 654.833): a reparação civil de dano ambiental é imprescritível",
    "MP-08": "Portaria MMA 280/2020 (MTR nacional e CDF)",
    "MP-09": "Lei 7.347/1985; Decreto 6.514/2008, art. 15-A",
    "MP-10": "Resolução CONAMA 420/2009",
}
UNIDADE_EXIBICAO = {"pendência": "caso", "pendencia": "caso", "TONELADAS": "t", "METROS CUBICOS": "m³"}
# colunas de exibição novas da planilha e da priorização (a exportação crua não tem estas colunas)
_TITULOS.update({"ENDERECO": "Endereço", "COORDENADAS": "Coordenadas",
                 "RISCO ELIMINADO ACUMULADO (%)": "Risco eliminado acumulado (%)"})

# palavras dos catálogos da ficha (maiúsculas, sem acento, no acervo) -> grafia de exibição
_SIGLAS = {"BTEX": "BTEX", "PAH": "PAH", "PCB": "PCB", "PCBS": "PCBs", "PCE": "PCE", "TCE": "TCE", "HCH": "HCH",
           "DDT": "DDT", "BPF": "BPF", "NORM": "NORM", "CNEN": "CNEN", "VI": "VI", "NI": "Ni", "ZN": "Zn",
           "CU": "Cu", "I": "I", "MTR": "MTR", "UF": "UF", "CEP": "CEP"}
_ACENTOS = {
    "acida": "ácida", "agricola": "agrícola", "agricolas": "agrícolas", "agua": "água", "amalgamacao": "amalgamação",
    "americio": "amerício", "aquifero": "aquífero", "area": "área", "aromaticos": "aromáticos", "ate": "até",
    "autorizacao": "autorização", "avaliacao": "avaliação", "cadmio": "cádmio", "captacao": "captação",
    "caracterizacao": "caracterização", "carcacas": "carcaças", "celula": "célula", "cesio": "césio",
    "clinquer": "clínquer", "combustiveis": "combustíveis", "deposito": "depósito", "destilacao": "destilação",
    "destinacao": "destinação", "diagnostico": "diagnóstico", "disposicao": "disposição", "escavacao": "escavação",
    "escoria": "escória", "estabilizacao": "estabilização", "esteril": "estéril", "fisico": "físico",
    "fundicao": "fundição", "galpao": "galpão", "galvanico": "galvânico", "hidrico": "hídrico",
    "incineracao": "incineração", "inorganicos": "inorgânicos", "inspecao": "inspeção", "intervencao": "intervenção",
    "investigacao": "investigação", "lancamento": "lançamento", "liquido": "líquido", "manutencao": "manutenção",
    "mercurio": "mercúrio", "mineracao": "mineração", "minerio": "minério", "mudanca": "mudança", "oleo": "óleo",
    "operacao": "operação", "organicos": "orgânicos", "orgao": "órgão", "petroleo": "petróleo",
    "policiclicos": "policíclicos", "protecao": "proteção", "quimica": "química", "quimico": "químico",
    "radiologica": "radiológica", "radiologico": "radiológico", "radionuclideos": "radionuclídeos",
    "reabilitacao": "reabilitação", "remediacao": "remediação", "remocao": "remoção", "residuo": "resíduo",
    "residuos": "resíduos", "restricao": "restrição", "saude": "saúde", "servico": "serviço", "servicos": "serviços",
    "so": "só", "solido": "sólido", "subestacao": "subestação", "subterranea": "subterrânea",
    "subterraneo": "subterrâneo", "torio": "tório", "uranio": "urânio", "armazem": "armazém",
    "quadrilatero": "quadrilátero", "metalurgicos": "metalúrgicos", "oratorio": "oratório", "regiao": "região",
    "acao": "ação", "situacao": "situação", "permanencia": "permanência", "pendencia": "caso",
}


def frase(texto: str) -> str:
    """Texto de catálogo do acervo (MAIÚSCULAS sem acento: "AGUA SUBTERRANEA") em grafia de frase para a tela
    ("Água subterrânea"). Siglas ficam em maiúsculas (BTEX, PCBs, CNEN, Classe I); só a primeira letra do texto
    sobe. A exportação continua com o texto cru."""
    import re
    if not texto or not isinstance(texto, str):
        return texto

    def palavra(m):
        bruto = m.group(0)
        if bruto in _SIGLAS:
            return _SIGLAS[bruto]
        minuscula = bruto.lower()
        return _ACENTOS.get(minuscula, minuscula)
    saida = re.sub(r"[A-ZÀ-Ý]+", palavra, texto)
    return saida[:1].upper() + saida[1:]


def rotulo_unidade(unidade: str) -> str:
    """Unidade de exibição ("pendência" na memória de cálculo vira "caso"; TONELADAS vira t)."""
    return UNIDADE_EXIBICAO.get(unidade, unidade)
