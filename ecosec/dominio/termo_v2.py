"""Termo de consentimento, versão 2.0 (arquivada). Não editar.

Os cadastros feitos sob esta versão guardam o hash SHA-256 do texto exato que
foi apresentado. Para provar o que a pessoa leu e aceitou (o ônus da prova é
do controlador, LGPD art. 8º, §2º), o texto precisa continuar reproduzível
byte a byte: qualquer mudança aqui, até de pontuação, faz o hash deixar de
conferir. Por isso este arquivo mantém a redação original, inclusive a
pontuação que a versão 3.0 abandonou. Um teste trava os hashes de referência.

Só o necessário para reproduzir o texto (e o hash). A versão em vigor está em
`termo.py`.
"""
VERSAO = "2.0"
# 1.0 -> 1.1: contato do controlador (art. 9º), idade (art. 14), eliminação na revogação.
# 1.1 -> 2.0: resumo em camadas e consentimento separado por finalidade (art. 8º, §4º).
TITULO = "Termo de consentimento para tratamento de dado biométrico facial"

RESUMO = (
    "Vamos guardar um MODELO MATEMÁTICO do seu rosto — não a foto — para confirmar que é você ao entrar no EcoSec.",
    "As fotos tiradas no cadastro ficam só na memória do computador e são apagadas logo depois.",
    "O modelo fica cifrado, neste computador. Nada vai para a internet nem para outras empresas.",
    "Você escolhe, separadamente, se seus registros de acesso podem entrar nas estatísticas do trabalho. "
    "Dizer não, não impede o cadastro.",
    "Você pode desistir a qualquer momento: o cadastro é desativado e o modelo do seu rosto é apagado.",
    "Tudo é eliminado ao fim da avaliação do trabalho acadêmico.",
)

_ABERTURA = (
    "Eu, {nome}, declaro que li e compreendi este termo e autorizo, de forma livre, informada "
    "e inequívoca, o tratamento da minha imagem facial nas condições abaixo, com fundamento no "
    "art. 11, inciso I, da Lei nº 13.709/2018 (Lei Geral de Proteção de Dados Pessoais).")

FINALIDADE_A = ("(a) Autenticação — confirmar a minha identidade ao acessar o EcoSec. "
                "OBRIGATÓRIA: sem ela não há cadastro.")
FINALIDADE_B = ("(b) Estatísticas e experimentos — usar os registros das minhas tentativas de acesso "
                "(resultado e distância facial) e os índices de qualidade das minhas amostras, de forma "
                "agregada e sem meu nome, nas taxas de acerto e erro do trabalho acadêmico. OPCIONAL.")

SECOES = (
    ("1. Quem trata os dados",
     "O sistema EcoSec é um trabalho acadêmico da disciplina de Processamento de Imagens e Visão "
     "Computacional (UNIP, 2026/2). O tratamento é feito pelos integrantes do grupo identificados "
     "na capa do trabalho, sob orientação docente. Contato para dúvidas e para exercer os direitos "
     "deste termo: {contato}."),
    ("2. Quais dados",
     "Imagens do meu rosto capturadas pela webcam durante o cadastro e a cada autenticação; meu "
     "nome; a matrícula gerada pelo sistema; meu nível de acesso e, no nível 2, a unidade da "
     "federação sob minha responsabilidade."),
    ("3. Para quê — duas finalidades, autorizadas separadamente",
     FINALIDADE_A + " " + FINALIDADE_B + " Os dados não serão usados para nenhuma outra finalidade, "
     "nem compartilhados, vendidos ou publicados."),
    ("4. Como a imagem é tratada",
     "A imagem é convertida em tons de cinza, recortada na região do rosto e transformada em um "
     "modelo matemático (histogramas de padrões binários locais — LBPH). As imagens originais não "
     "são gravadas em disco: ficam na memória só durante o cadastro e são descartadas após o "
     "treinamento. O modelo é guardado cifrado, no próprio computador, sem envio a nuvem ou a "
     "serviço externo de reconhecimento."),
    ("5. Por quanto tempo",
     "Até o fim da avaliação do trabalho acadêmico, quando o modelo e o cadastro serão eliminados "
     "com registro em ata — ou antes, se eu revogar este consentimento: nesse caso, o modelo do meu "
     "rosto é eliminado imediatamente. Permanecem apenas o registro deste aceite e da revogação, "
     "como prova de que o tratamento foi autorizado e encerrado."),
    ("6. Meus direitos",
     "Posso, a qualquer momento, pedir confirmação e acesso aos meus dados, correção, eliminação "
     "e informação sobre o tratamento (art. 18), e revogar este consentimento (art. 8º, §5º). A "
     "revogação desativa o meu cadastro, elimina o modelo do meu rosto e não afeta a licitude do "
     "que foi feito antes dela. O pedido é feito ao administrador do sistema."),
    ("7. Riscos e salvaguardas",
     "Diferente de uma senha, um rosto não pode ser trocado se vazar. Por isso o modelo é "
     "cifrado, as imagens não são guardadas e, nos níveis 2 e 3, o rosto nunca é o único fator "
     "de acesso: há também senha e, no nível 3, prova de vivacidade e uma segunda pessoa."),
    ("8. Se eu não concordar",
     "Recusar a finalidade (a) não traz prejuízo algum: apenas não serei cadastrado e nenhuma "
     "imagem será capturada. Recusar a finalidade (b) não impede o cadastro."),
    ("9. Natureza do sistema",
     "Trata-se de protótipo acadêmico, com taxa de erro conhecida e medida. Toda negação de "
     "acesso pode ser revista por um responsável humano."),
    ("10. Idade",
     "Declaro ter 18 anos ou mais. Dados de crianças e adolescentes exigem consentimento específico "
     "de um dos pais ou responsável (art. 14) e não são tratados por este sistema."),
)


def _escolhas(autoriza_pesquisa: bool | None) -> str:
    if autoriza_pesquisa is None:
        b = "a escolher"
    else:
        b = "AUTORIZADA" if autoriza_pesquisa else "NÃO AUTORIZADA"
    return f"Escolhas registradas: finalidade (a) AUTORIZADA; finalidade (b) {b}."


def renderizar(nome: str, contato: str, autoriza_pesquisa: bool | None = None) -> str:
    """Texto exato apresentado: com o nome e as escolhas. É sobre ele que o hash é calculado."""
    nome = " ".join(nome.split())
    partes = [f"{TITULO} — versão {VERSAO}", "", "Resumo:"]
    partes += [f"- {item}" for item in RESUMO]
    partes += ["", _ABERTURA.format(nome=nome or "_" * 30)]
    for titulo, corpo in SECOES:
        partes += ["", titulo, corpo.format(contato=contato)]
    partes += ["", _escolhas(autoriza_pesquisa)]
    return "\n".join(partes)
