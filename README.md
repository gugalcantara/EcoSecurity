# EcoSecurity

Controle de acesso multinível por reconhecimento facial, protegendo um cadastro de passivos
perigosos pendentes de coleta. APS de Processamento de Imagens e Visão Computacional · UNIP, 2026/2.

Windows · Python 3.11 · PySide6 (Fluent Widgets) · OpenCV contrib (Haar, KCF, LBPH, FacemarkLBF) · MySQL 8.4

## Sumário

1. [Situação atual](#situação-atual)
2. [Guia rápido: do zero até o primeiro login](#guia-rápido-do-zero-até-o-primeiro-login)
3. [Uso do dia a dia](#uso-do-dia-a-dia)
4. [Administradores e segredos](#administradores-e-segredos)
5. [Configurações que você pode querer mudar](#configurações-que-você-pode-querer-mudar)
6. [Solução de problemas](#solução-de-problemas)
7. [Comandos](#comandos)
8. [Arquitetura e camadas de segurança](#arquitetura-e-camadas-de-segurança)
9. [Privacidade e dados pessoais (LGPD)](#privacidade-e-dados-pessoais-lgpd)

## Situação atual

**Pronto e testado:** as 10 camadas de segurança (S1 a S10), login único com reconhecimento facial, um perfil por
cadastro com escopo exclusivo (cada perfil vê só a própria camada; o administrador, um Externo com esse papel, não
vê dado do acervo), bloqueio de tela por inatividade, cadastro com termo de consentimento 3.4 (via assinada em
PDF; os aceites 3.3, 3.2, 3.1, 3.0 e 2.0 continuam conferindo),
acervo com 9 relatórios desenhados do banco (tarja, marca visível com a matrícula e o horário da consulta e, nos
níveis 2 e 3, marca d'água invisível), trilha de auditoria encadeada por SHA-256,
relatórios do sistema S-01 a S-07 e persistência em MySQL com contas de privilégio mínimo.

**Provisório (de propósito):**

- A **piscada** voltou ao Nível 3: o N3 pede dois gestos sorteados, sempre com uma piscada (só deslizar, uma
  foto impressa passava). Desde 02/11/2026 ela é medida nos pixels da região dos olhos (`sinal_piscada = "regiao"`):
  numa webcam fraca, com gabarito, reconheceu 10 de 10 piscadas sem nenhuma falsa, enquanto o contorno do olho (EAR)
  reconheceu 0. O limiar (`limiar_regiao = 0.85`) é provisório; calibrar de novo se a câmera, a luz ou a pessoa mudarem.
- A **regra dos dois** (segunda pessoa no N3) está desligada, a pedido do grupo.
- Os **limiares** do reconhecimento facial são estimativas, até os experimentos (curva DET).

**Próximos passos:** experimentos com voluntários (curva DET) e inspeção de acondicionamento
(ORB + SSIM).

## Guia rápido: do zero até o primeiro login

### 1. Pré-requisitos

- **Windows 10 ou 11** com **webcam**.
- **Python 3.11** (não 3.12: o OpenCV usado é validado na 3.11):

```powershell
winget install Python.Python.3.11
```

- **MySQL 8.4 LTS** (passo 4). Para só conhecer o sistema, dá para pular o banco (modo memória, no passo 4).

> Coloque o projeto numa pasta **fora do OneDrive** (por exemplo `C:\Users\<você>\Dev Hub\EcoSec`): a pasta guarda
> o modelo facial cifrado e o `.env` com segredos, que não devem ir para a nuvem.

### 2. Ambiente Python

Na pasta do projeto, num PowerShell:

```powershell
py -3.11 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m ferramentas.baixar_modelo_landmarks
.venv\Scripts\python.exe -m ferramentas.verificar_ambiente
```

- `baixar_modelo_landmarks` baixa o modelo de 68 pontos do rosto (~54 MB) e confere o SHA-256.
- `verificar_ambiente` deve terminar com **"Ambiente válido"**. Se apontar algo, veja
  [Solução de problemas](#solução-de-problemas).

Use **sempre** o `python.exe` do `.venv`. O OpenCV precisa ser o `opencv-contrib-python`: o pacote comum não tem
`cv2.face` (LBPH e landmarks), e os dois juntos conflitam em silêncio.

### 3. (Opcional) Atalho com ícone

```powershell
.venv\Scripts\python.exe -m ferramentas.criar_atalho
```

Cria **EcoSecurity** no Menu Iniciar: abre sem a janela preta do console e aparece com o ícone próprio na barra de
tarefas (pode fixar). Acrescente `--area-de-trabalho` para criar também na Área de Trabalho.

### 4. Banco de dados (uma vez por máquina)

1. Instale o MySQL: `winget install Oracle.MySQL`. No **MySQL Configurator**, escolha *Development Computer*,
   porta 3306, **não** abra a porta no firewall e defina uma senha de `root` que **só você** guarda.
2. Prepare bancos, tabelas e contas:

```powershell
.venv\Scripts\python.exe -m ferramentas.preparar_banco
```

A ferramenta pede a senha do `root` uma vez (sem guardar), cria `ecosec_seguranca` e `ecosec_acervo`, importa o
acervo e cria três contas com o **mínimo** de privilégio, provando contra o banco real que elas não podem
o que não devem:

| Conta | Banco | Pode | Não pode |
|---|---|---|---|
| `ecosec_seg` | `ecosec_seguranca` | ler; inserir; alterar usuário e consentimento | **apagar** usuário, consentimento ou amostra; ler o acervo |
| `ecosec_cofre` | `ecosec_acervo` | **só ler** | gravar qualquer coisa; ler usuários |
| `ecosec_teste` | `ecosec_teste_*` | tudo (bancos descartáveis de teste) | tocar nos bancos reais |

As senhas dessas contas são geradas aleatoriamente e vão para o `.env`. O EcoSecurity **nunca** usa o `root`.
Rodar de novo é seguro: a ferramenta só cria o que falta e aplica migrações pendentes.

**Sem banco:** troque `[persistencia] modo` para `"memoria"` em `config/ecosec.toml` (ou abra com
`python -m ecosec --memoria`). Os cadastros somem ao fechar o programa.

### 5. Primeira execução

```powershell
.venv\Scripts\python.exe -m ecosec
```

Numa instalação nova, o sistema abre em **Configuração inicial** (só o menu "Administração"):

1. **Defina a senha de instalação.** Segue a política de senha forte do nível 3; só o hash bcrypt vai para o `.env`.
   Ela serve só para a configuração inicial e para indicar o primeiro administrador.
2. **Novo cadastro**, o seu, com o perfil **Externo** (na configuração inicial é o único oferecido): termo de
   consentimento (leitura mínima, autorizações, assinatura) → nome, perfil e senha → captura do rosto em duas
   sessões → **matrícula** gerada. Ao concluir, você já é o primeiro administrador. Salve a **via do titular (PDF)**:
   ela traz a sua matrícula.
3. O sistema passa a abrir pelo **login**. Entre com a matrícula, a senha do seu cadastro e o rosto.
4. Abra a **Administração**: o rosto é conferido de novo e, no primeiro acesso, o sistema mostra um **QR** para o
   aplicativo autenticador do celular (Google Authenticator ou Microsoft Authenticator). Digite o primeiro código e
   **guarde os 8 códigos de recuperação**, que aparecem uma única vez.
5. Cadastre as outras pessoas, cada uma com o seu perfil, e designe pelo menos mais um administrador: cadastre a
   pessoa como **Externo** e use **Tornar administrador** (só um Externo vira administrador). Com menos de 2 administradores você
   faz isso sozinho (fase de implantação); a partir do segundo, cada ação crítica pede o código do celular de outro
   administrador. Cada novo admin cadastra o próprio celular no primeiro acesso ao painel.
6. O administrador **não vê nenhum dado do acervo**. Para demonstrar o Nível 3, use o cadastro de outra pessoa com
   o perfil de ministro (um cadastro, um perfil).
7. Proteja os segredos e faça o backup (veja [Administradores e segredos](#administradores-e-segredos)).

## Uso do dia a dia

**Um login só, para todos.** Matrícula, senha e rosto (os fatores do nível 2). Antes do login, nada do sistema fica
visível. Cada cadastro tem **um perfil**, e cada perfil vê **só a própria camada**: as outras
camadas não aparecem nem são mencionadas.

| Perfil | Abas no menu | O que vê |
|---|---|---|
| Servidor | Nível 1 | Estatísticas agregadas, sem localização; regiões sensíveis suprimidas |
| Diretor (com UF) | Nível 2 | Registros da própria UF, com responsáveis, e a comparação com o país (totais protegidos) |
| Ministro | Nível 3 | Visão nacional da custódia, matriz de criticidade, custo por responsável e a fila do orçamento público |
| Externo | (não entra) | Quem não é do quadro do governo: só registra a matrícula, o termo e o rosto |
| Externo com o papel de **Administrador** | Administração | Nenhum dado do acervo, nunca. Cadastra pessoas e atribui perfis, exclui cadastros, gere consentimentos, administradores e a trilha (com o detalhe do acervo mascarado), e faz a identificação facial |

- **Início:** quem você é, como funciona o acesso e o cartão do seu nível (o que mostra e como abre). O do
  administrador mostra só a Administração.
- **Abrir um nível (step-up):** N1 e N2 abrem direto, porque o login já provou matrícula, senha e rosto. O N3 pede
  de novo o rosto e os gestos na câmera, e fecha após 5 minutos sem uso. Cada abertura fica na trilha.
- **Painel analítico:** o botão *Painel analítico* troca os relatórios por seções interativas, conforme o nível:
  - **Panorama por UF** (N1 e N3): coroplético com o *Índice de Pressão* (posição relativa da UF entre as 27) na
    dica; legenda de quintis (passar o mouse realça, clicar seleciona); barras por classe que seguem o mapa; linha
    do tempo com marcadores de evento; estoque ativo por classe ou saldo anual (entradas × saídas). Só totais;
  - **Resumo agregado** (todos): totais por UF, região, atividade, motivo, ação recomendada ou quem paga.
    Exportação livre no N1;
  - **Mapa interativo** (N2 na própria UF, N3 nacional): camadas Pontos, Densidade e Municípios (N2) ou com
    opacidade própria (N3); custódias por tipo (◇ □ △ ○) com filtro; legenda que muda com o zoom; zoom animado; a
    ficha abre num painel lateral com *Dados técnicos*, *Responsáveis* e *Documentos*. No N2, *Exportar ficha* tem
    um cadeado que mostra se vai pedir o rosto. No N3, linha do tempo (pontos = ativas no ano) e árvore
    custódia → pendência → documento; o documento abre só para leitura, com QR, assinaturas, hash e marca d'água;
  - **Evolução** (N3): estoque ativo por classe com os eventos anotados e colunas da faixa de risco por ano ou mês;
  - **Priorização** (N3): com um orçamento público, quais pendências resolver primeiro e quanto risco sai;
  - **Planilha analítica** (N2 e N3): ordenável, paginada, com filtros por situação (ativas, encerradas ou todas),
    UF, risco, atividade, motivo e ação; atividade e motivo aparecem como "código · nome".
- **Pendências ativas × encerradas:** o cadastro guarda o histórico (desde 2006, mais o estoque herdado). Uma
  pendência encerra quando chega à etapa final do ciclo de vida (reabilitada, destinada ou coletada); relatórios,
  resumo, índice e fila do orçamento contam só as ativas, e a curva do estoque pode cair.
- **Exportar dados nominais (N2) pede o rosto de novo** se a última conferência passou de 5 minutos (step-up). O
  N3 não exporta; toda exportação grava o SHA-256 do arquivo na trilha.
- **Contexto do login (MFA adaptativo):** numa estação nova ou logo depois de erros, o login pede também a prova de
  vida. Com os dois sinais, a sessão vale **só para consulta** (sem N3 e sem exportação). O horário **não** conta:
  não há expediente, e nenhum nível é restrito por dia ou hora.
- **Administração:** ao abrir, o rosto do administrador é conferido de novo, na hora, e o código do celular é
  pedido. Ações críticas pedem o código de outro administrador (veja
  [Administradores e segredos](#administradores-e-segredos)).
- **Identificação facial** (só o administrador, uma seção do painel de Administração, que já conferiu o rosto e o
  celular): o sistema compara o rosto com **todos** os cadastros (1:N) e diz quem é, mostrando os 3 cadastros mais
  parecidos com a distância e o tempo até a decisão (as etapas internas da visão não são exibidas);
  o quadro da decisão fica congelado até *Identificar de novo*. Não dá acesso a nada nem mostra matrícula; cada
  identificação fica na trilha, com quem a pediu.
- **Esqueci minha matrícula:** está na via do termo (PDF) entregue no cadastro; senão, o administrador consulta no
  painel. O nome não substitui a matrícula (nomes se repetem e são públicos).
- **Bloqueio por inatividade:** após 10 minutos **sem uso** (mouse, rolagem, teclado; câmera ligada conta como uso),
  a tela é bloqueada. A sua senha devolve você para onde estava. O N3 e a Administração pedem o rosto de novo.
- **Encerrar sessão:** botão no Início ou no menu (embaixo). Volta ao login.
- **Erros seguidos:** 3 erros na mesma matrícula bloqueiam por 15 minutos, e a tela informa até que horas. Falhar o
  gesto do N3 bloqueia só o N3, não o login.

## Administradores e segredos

**Uma pessoa, um cadastro, um perfil.** Cada administrador entra pelo login de todos, com a **própria** matrícula,
senha e rosto; ser administrador é um **papel dado a um cadastro Externo** (sem camada), guardado no banco (tabela
`administrador`). Só um Externo vira administrador, e o administrador não recebe perfil com camada (tira-se o papel
antes). Não existe
senha de administrador compartilhada, então a trilha sempre diz qual admin fez cada coisa.

**Perfis e exclusão.** *Atribuir perfil* dá ou troca o perfil de um cadastro (o diretor pede a UF). Ministro,
Ministro é ação crítica; servidor, diretor e Externo, o admin faz sozinho.
Ninguém altera o próprio perfil. *Excluir* é lógico e irreversível: desativa o cadastro, revoga o consentimento e
elimina o rosto; a trilha e o termo aceito ficam, como prova (a aplicação não tem DELETE no banco). A exclusão
física fica para o fim do trabalho, pelo root, com registro em ata.

**Abrir o painel** pede três provas: o login, o rosto conferido na hora e o **código do celular** (TOTP, RFC 6238:
muda a cada 30 segundos e funciona sem internet, só precisa do relógio certo). Perdeu o celular? Um dos códigos de
recuperação abre o painel uma vez.

**Ações críticas pedem um segundo administrador:** tornar admin, tirar o papel (inclusive desativando o cadastro de
um admin), atribuir o perfil de ministro, excluir um cadastro, refazer o celular
de alguém, revogar consentimento (elimina o rosto) e registrar a revisão de acessos. Quem
pede liga ou manda mensagem para outro admin, lê o resumo e digita o código que o celular **dele** mostra agora.
Ninguém aprova o próprio pedido, e o sistema não deixa ficar com menos de 2 administradores. Com menos de 2 (fase de
implantação), o admin age sozinho e a trilha marca isso.

**Revisão de acessos:** o relatório **S-10** (Relatórios do sistema) mostra o perfil de cada pessoa, quem é admin,
quem designou e quem aprovou, se o celular está cadastrado, o último login e a versão do termo aceita. Depois de o grupo
conferir, **Registrar revisão** grava isso na trilha (pede outro admin). Sugestão: mensal, com registro em ata.

**Acesso de emergência.** Se um administrador acertou matrícula e senha mas o **rosto ou a câmera falhou**, o
resultado do login mostra o botão **Acesso de emergência**. Ele abre com os códigos de **2 dos 3 administradores**
(celular ou recuperação), em qualquer ordem, em até 5 minutos. Lá dentro, por 30 minutos e sem nada do acervo, só se
conserta o acesso: recadastrar o rosto de um admin, refazer o celular de um admin ou designar um novo. Três códigos
errados travam a emergência por 15 minutos, e a mensagem nunca diz qual código falhou. Depois, registrem em ata o
motivo e revisem a trilha do período.

**Segredos protegidos pelo Windows (DPAPI).** Os valores do `.env` são gravados cifrados pelo Windows, presos à sua
conta neste computador: quem copiar o arquivo leva texto ilegível. Para converter um `.env` antigo e guardar o
backup (que abre em outro computador, com uma frase-senha):

```powershell
.venv\Scripts\python.exe -m ferramentas.proteger_segredos
.venv\Scripts\python.exe -m ferramentas.proteger_segredos --backup E:\ecosec_segredos.bak
```

Guarde o backup **fora** do computador e a frase-senha em outro lugar. Reinstalou o Windows ou trocou de máquina?
`--restaurar ARQUIVO`. O DPAPI não protege contra quem já está logado na sua conta do Windows.

## Configurações que você pode querer mudar

Todos os parâmetros ficam em [`config/ecosec.toml`](config/ecosec.toml), comentados; segredos ficam no `.env`.

| Chave | Padrão | Para quê |
|---|---|---|
| `[aplicacao] tema` | `"escuro"` | `"claro"` ou `"escuro"` (também há o botão no menu) |
| `[persistencia] modo` | `"mysql"` | `"memoria"` para usar sem banco |
| `[captura] indice_camera` | `0` | Outra webcam (1, 2...) |
| `[interface] modo_demonstracao` | `false` | `true` mostra a distância LBPH ao lado do limiar (didático; ligar só na apresentação) |
| `[identificacao] limiar` | `50.0` | Distância máxima para a página de identificação dizer quem é. Provisório: calibrar com rostos reais; mudar só com registro em ata |
| `[s7_custodia] exigir_segunda_pessoa` | `false` | `true` religa a regra dos dois no N3 |
| `[s6_vivacidade] desafios` e `gesto_obrigatorio` | piscada obrigatória + deslizar | Só deslizar: `desafios = ["MOVER_ESQUERDA", "MOVER_DIREITA"]` e `gesto_obrigatorio = ""` (uma foto impressa volta a passar). Nome de gesto errado impede a abertura |
| `[s6_vivacidade] deslocamento_minimo` / `giro_minimo` / `direcao_livre` | `0.15` / `0.15` / `true` | Gesto de mover: vale deslizar o rosto OU virar a cabeça, para qualquer lado (a instrução só orienta). Com a câmera real, aceitou 7 de 8 gestos (o 8º sem rosto na imagem) e nenhum parado |
| `[s6_vivacidade] sinal_piscada` / `limiar_regiao` | `"regiao"` / `0.85` | Como a piscada é medida: `"regiao"` (padrão) olha os pixels da região dos olhos, localizada pelos pontos do rosto, e funciona em webcam fraca; `"ear"` é o modo anterior, pelo contorno do olho. Baixe `limiar_regiao` se as piscadas não passarem; suba se algo "piscar" sozinho. Calibre com `calibrar_vivacidade` e registre em ata |
| `[s6_vivacidade] queda_ear_minima` | `0.40` | Quanto a abertura do olho precisa cair para contar como olho fechado. Calibrado com a câmera real (01/11/2026); calibrar de novo com `calibrar_vivacidade` se a câmera, a luz ou a pessoa mudarem; mudar só com registro em ata |
| `[sessao] inatividade_minutos` | `10` | Minutos sem uso até bloquear a tela |
| `[sessao] inatividade_n3_minutos` | `5` | Minutos sem uso até fechar o Nível 3 |
| `[lgpd] leitura_minima_segundos` | `5` | Tempo com o termo aberto antes de liberar o aceite |
| `[lgpd] contato` | `controlador@ecosecurity.sim.br` | Endereço **simulado**, sem caixa postal real (emulação acadêmica); o termo 3.1 manda os pedidos do titular ao administrador. Mudou? Suba a versão do termo e arquive a anterior, ou os hashes gravados deixam de conferir |
| `[contexto] ativo` | `true` | MFA adaptativo por estação nova e erros recentes (horário nunca conta) |
| `[contexto] verificacao_minutos` | `5` | Validade da última conferência do rosto para exportar dados nominais |
| `[regras_negocio]` | ver arquivo | Prazo-limite por classe, escalonamento ao MP e orçamento da fila |
| `[custos]` | rotas `PARAMETRO` | Custo de remediação por componente (fixos, por unidade, monitoramento) e rota de tratamento por classe e substância; área por m³ de solo (`densidade_solo_t_por_m3` documenta a conversão da referência antiga). No N3, "Custo por responsável" mostra a memória de cálculo. Calculado na hora: não precisa recriar o acervo |
| `[geracao]` | 2400, estratificado | Tamanho do acervo gerado e calibração das saídas por linha (metas, âncoras e `latencia`, o tempo mínimo antes de poder encerrar; "A CONFIRMAR" = parâmetro de simulação até 2026-11-01). Mudou? `preparar_banco --recriar-acervo` |
| `[indice_pressao]` | 0,3/0,3/0,2/0,2; 3 | Pesos do Índice de Pressão (somam 1) e o k da supressão de célula pequena, que vale em todo agregado do N1 (panorama, resumo, exportação; as visões SQL usam o mesmo 3) |
| `[documentos] bloquear_captura` | `false` | `true`: a janela do documento sai preta em capturas de tela (desligado para apresentações) |
| `[interface] animacoes` | `true` | `false` desliga zoom e painéis animados |
| `[administracao] minimo_administradores` | `2` | A partir deste número de admins, ação crítica exige um segundo; abaixo dele é a fase de implantação |
| `[administracao] codigos_recuperacao` | `8` | Códigos de uso único entregues a cada admin ao cadastrar o celular |
| `[administracao] quorum_emergencia` | `2` | Quantos admins diferentes abrem o acesso de emergência |
| `[administracao] janela_emergencia_minutos` / `duracao_emergencia_minutos` | `5` / `30` | Prazo para juntar os códigos do quórum / duração da sessão de emergência |

## Solução de problemas

| Sintoma | Causa provável | O que fazer |
|---|---|---|
| "Não foi possível abrir com segurança" / banco indisponível | Serviço do MySQL parado | Abra *Serviços* do Windows e inicie **MySQL84**, ou rode `preparar_banco` de novo |
| "Câmera indisponível" | Outro programa usando a webcam | Feche Teams, navegador ou outro app de vídeo; confira com `verificar_ambiente` |
| Rosto não reconhecido | Luz atrás do rosto, mais de uma pessoa, rosto longe | Luz à frente, uma pessoa por vez, rosto no oval; os limiares ainda são provisórios |
| "Matrícula bloqueada" | 3 erros seguidos | Aguarde até a hora informada na tela (15 min) |
| N3 nega na prova de vida | Gesto não detectado | Piscada: olhe para a câmera, parado, espere um instante (o sistema mede o olho aberto) e pisque uma vez, normalmente. Mover: **vire ou deslize** o rosto para o lado e volte, até a barra da tela encher (qualquer lado vale; o rosto sumir por um instante ao virar não atrapalha). Se a piscada falha sempre, rode `calibrar_vivacidade`: ele mostra quantas piscadas o detector reconheceu |
| "[s6_vivacidade] ... valor inválido" ao abrir | Nome de gesto escrito errado no config | Use `PISCAR`, `MOVER_ESQUERDA` ou `MOVER_DIREITA` |
| "Modelo de landmarks não encontrado / não confere" | Modelo ausente ou corrompido | `python -m ferramentas.baixar_modelo_landmarks` |
| Janela preta do console junto | Aberto pelo terminal | Use o atalho (`criar_atalho`) |
| "Faltam tabelas" ao abrir depois de atualizar | As tabelas `administrador` e `codigo_recuperacao` ainda não existem | Rode `preparar_banco` de novo (o administrador antigo do `.env` passa para o banco sozinho, na primeira abertura) |
| Erro com a coluna `perfil` ao abrir, depois da troca de níveis por perfis | O banco ainda tem o modelo de níveis (ou os perfis da primeira versão) | Rode `preparar_banco`: cada cadastro recebe o perfil do nível; administradores, "sem perfil" e Ministério Público passam a Externo, sem camada (o papel de administrador continua) |
| Código do celular nunca é aceito | Relógio do celular ou do PC fora da hora | Ative a hora automática nos dois; o código tolera 30 segundos de diferença |
| Admin perdeu o celular | | Entra com um código de recuperação e pede a outro admin **Refazer celular**; ou pelo acesso de emergência |
| Ninguém consegue abrir o painel (rostos ou câmera falhando) | | Acesso de emergência, com os códigos de 2 administradores |
| "O segredo ... não abre nesta conta do Windows" | `.env` protegido em outro PC ou conta (ou Windows reinstalado) | `proteger_segredos --restaurar ARQUIVO` com o backup |

## Comandos

Todos com `.venv\Scripts\python.exe -m ...`:

| Comando | O que faz |
|---|---|
| `ecosec` | A aplicação (`--memoria` para abrir sem banco) |
| `pytest` | A suíte de testes inteira, a partir da raiz e sem argumentos (os de MySQL usam bancos descartáveis `ecosec_teste_*`) |
| `ferramentas.verificar_ambiente` | Confere Python, OpenCV contrib, LBPH, KCF, modelo de landmarks, PySide6 e o FPS da webcam |
| `ferramentas.preparar_banco` | Cria ou repara bancos, tabelas e contas; aplica migrações (inclusive a dos perfis); importa o acervo; prova os privilégios (`--recriar-acervo` apaga e reimporta o acervo, depois de mudar o gerador) |
| `ferramentas.baixar_geografia` | (Só para refazer os dados geográficos.) Baixa uma vez os polígonos municipais do IBGE e os bairros e prefixos de CEP do ViaCEP para `ecosec/acervo/dados/geografia.json`; o sistema não usa internet |
| `ferramentas.povoar_usuarios_teste` | Usuários de teste (servidor, diretor, ministro, um externo e um administrador; bcrypt + termo vigente) num banco **descartável** `ecosec_teste_usuarios`; `--apagar` remove |
| `ferramentas.baixar_modelo_landmarks` | Baixa o modelo de 68 pontos do rosto (~54 MB) e confere o SHA-256 |
| `ferramentas.criar_atalho` | Atalho com ícone no Menu Iniciar (`--area-de-trabalho` para a Área de Trabalho também) |
| `ferramentas.verificar_trilha` | Confere a cadeia de hash da trilha no banco real e aponta o registro adulterado. `--conferir "LINHA"` ou `--conferir-arquivo ARQ` prova que a trilha continua igual até cada registro ancorado, o que pega a cauda apagada ou recalculada pelo root. A âncora (id e hash do último registro) é gerada no painel administrativo, na aba da trilha, com o código do celular do administrador, e fica registrada na trilha. Guarde a linha **fora do computador** (celular, e-mail ou impressa) e ancore periodicamente, por exemplo ao fim de cada dia de uso ou na revisão de acessos |
| `ferramentas.experimento_det coletar --sessao 1` e `analisar` | Experimento da curva DET com voluntários (pelo menos 3, cadastrados e com a finalidade (b) do termo autorizada). `coletar` pede a matrícula de um voluntário e faz 5 tentativas curtas diante da câmera; rode uma vez por voluntário e repita com `--sessao 2` em outra luz. `analisar` calcula FAR, FRR e EER, sugere os limiares dos três níveis e da identificação e grava `resultados/curva_det.png`. Só grava distâncias, nunca imagens; não muda o config (adotar os limiares é com registro em ata) |
| `ferramentas.calibrar_series` | Confere as séries do acervo: metas de saída, âncoras, encerramentos e se o estoque cai (código 1 se falhar) |
| `ferramentas.verificar_documento "ecosec://..."` | Confere um documento pelo QR; com o hash da marca visível, diz quem abriu e quando (trilha) |
| `ferramentas.gerar_referencia` | Regrava `sql/acervo/02_referencia.sql` a partir do catálogo e dos eventos do código |
| `ferramentas.extrair_marca ARQ.png` | Rastreia um arquivo vazado: quem exportou e quando (marca d'água S9) |
| `ferramentas.proteger_segredos` | Protege os valores do `.env` com o DPAPI do Windows; `--backup ARQ` grava o backup por frase-senha; `--restaurar ARQ` devolve os segredos a esta máquina |

## Arquitetura e camadas de segurança

```
interface  →  servicos  →  seguranca / visao / acervo  →  dominio
                  └──────→  repositorios (contratos: memória ou MySQL)
```

As dependências só apontam para dentro. O `dominio` não importa nada; a `interface` não decide nada.

| Pacote | Conteúdo |
|---|---|
| `dominio/` | Níveis (camadas de dado), perfis (externo, servidor, diretor e ministro; um por cadastro), camadas S1 a S10, motivos de negação, entidades, termo de consentimento (3.3, e a 3.2, a 3.1, a 3.0 e a 2.0 arquivadas) |
| `visao/` | Aquisição (thread + fila 1) · pré-processamento (CLAHE) · segmentação (Haar + KCF) · qualidade · LBPH 1:N e 1:1 · gestos (mover: deslizar ou virar; piscada pela região dos olhos, localizada por landmarks) |
| `seguranca/acesso/` | Uma camada por módulo (S1 a S7), a política que as compõe (função pura) e o risco de contexto |
| `seguranca/autorizacao.py` | Matriz papel × classificação × operação: decide toda operação sobre o acervo (relatório S-09). Escopo exclusivo: cada papel lê só a própria camada; o administrador, nenhuma |
| `seguranca/evidencia/monitor.py` | Alertas de anomalia sobre a trilha (relatório S-08) |
| `acervo/regras.py` | Regras de negócio: criticidade, prazo-limite, custo, quem paga, ação recomendada e fila do orçamento |
| `acervo/geracao/` | Séries do acervo: entradas por linha, risco de saída calibrado, contagens anuais e etapas do ciclo de vida |
| `acervo/documentos.py`, `servicos/documentos.py` | Documentos derivados das etapas e o pipeline de renderização (QR, assinaturas, hash, marca visível e S9 por último) |
| `interface/componentes/` | Componentes do painel: zoom animado, painel deslizante, botão com cadeado, linha do tempo, camadas, legenda e gráfico de estoque |
| `seguranca/conteudo/` | S8 Tarja (supressão na origem) e S9 Rastreio (marca d'água LSB e DCT) |
| `seguranca/evidencia/` | S10 Trilha encadeada por SHA-256 |
| `acervo/` | Base do acervo (gerada com semente fixa) e os 9 relatórios, desenhados na hora com as regiões sensíveis anotadas |
| `servicos/` | Cadastro, autenticação (login de entrada e step-up), sessão, administração, acervo, trilha e relatórios do sistema |
| `repositorios/` | Contratos + implementação em memória + implementação MySQL (mesmo comportamento nas duas) |
| `interface/` | PySide6 + Fluent Widgets: login, início, uma página por nível, bloqueio, administração, cadastro |
| `aplicacao.py` | Raiz de composição: o único lugar que conhece as peças concretas |
| `ferramentas/` | Os comandos de instalação, diagnóstico e auditoria acima |

| Anel | Código | Camada | Pergunta | Situação |
|---|---|---|---|---|
| Acesso | S1 | Contenção | Esta matrícula ainda pode tentar? | ✅ |
| | S2 | Conhecimento | Sabe o segredo? | ✅ |
| | S3 | Qualidade | A imagem permite decidir? | ✅ |
| | S4 | Inerência | É quem diz ser? | ✅ (limiares provisórios) |
| | S5 | Habilitação | Tem direito? | ✅ |
| | S6 | Vivacidade | É uma pessoa viva, não uma foto? | ✅ piscada (obrigatória) + deslizar · limiar da piscada calibrado com a câmera real |
| | S7 | Custódia | Outra pessoa confirma? | ✅ implementada · desligada no config |
| Conteúdo | S8 | Tarja | O que pode ver? | ✅ |
| | S9 | Rastreio | Se vazar, de quem veio? | ✅ |
| Evidência | S10 | Trilha | O que aconteceu, e alguém alterou o registro? | ✅ |

## Privacidade e dados pessoais (LGPD)

- **Rosto:** as imagens do cadastro ficam **só na memória** e são apagadas depois do treinamento. O que fica é o
  modelo matemático (LBPH), **cifrado** em `modelo/lbph.enc`.
- **Senhas:** só o hash bcrypt.
- **Celular dos administradores:** o segredo TOTP fica cifrado no banco (chave própria, `CHAVE_TOTP`), e dos códigos de
  recuperação só o SHA-256. Os segredos do `.env` ficam protegidos pelo Windows (DPAPI).
- **Consentimento:** guardado com o hash SHA-256 do texto exato aceito. Versões antigas do termo ficam arquivadas
  sem alteração, para o hash continuar conferindo.
- **Nada vai para a internet**, e nada disso entra no git (`.gitignore`: `.env`, `modelo/`, capturas, resultados).
- **Revogação:** pelo painel; desativa o cadastro e elimina o rosto do modelo.
- **Exclusão:** lógica e irreversível (revoga, desativa, elimina o rosto e marca o cadastro como excluído). A
  trilha e o termo aceito ficam, como prova do tratamento e do seu fim.
- **Ao fim do trabalho:** descarte dos dados biométricos, com registro em ata.
