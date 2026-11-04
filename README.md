# Ultron

Assistente pessoal para Windows com HUD "Núcleo", dois cérebros (Claude pela sua assinatura,
via Claude Code, ou um modelo local no Ollama), memória num cofre do Obsidian e ferramentas para
abrir apps e jogos da Steam, organizar pastas e mandar mensagem no Discord.

## O que ele faz

| Peça | Detalhe |
|---|---|
| Cérebro Claude | Roda o Claude Code oficial (`claude -p`) com a sua assinatura. O Ultron nunca toca no seu login. |
| Cérebro local | Ollama, modelo padrão `qwen3:8b`. Sem terminal e sem web: só as ferramentas do Ultron. |
| Memória | Cofre Obsidian em `%USERPROFILE%\Ultron\UltronVault`. Perfil, conclusões, diário, resumos de chats. |
| Ferramentas | apps, modos, jogos Steam, pastas, Obsidian, Discord (bot oficial), ler a tela. |
| Lembretes | "Me lembra às 18h de treinar", "toda segunda às 9h: reunião". Na hora: notificação do Windows (não tira o foco do jogo) e cartão na HUD com OK / Adiar 10 min. Perdidos com o PC desligado aparecem ao abrir. |
| Resumo ao abrir | Lembretes de hoje, pendências abertas e conclusões novas. Montado dos arquivos, sem gastar a cota do Claude. |
| Ler a tela | "O que é esse erro na tela?": o Ultron se esconde, tira print do monitor principal e analisa. O print não é salvo. No Claude a imagem vai para a Anthropic; no modo local não sai do PC. Desligue em `[tela] habilitada`. |
| Segurança | Ler e abrir é livre. Mover arquivos, mandar no Discord, rodar comandos e editar arquivos pedem confirmação na HUD. Nada é apagado: vai para `%USERPROFILE%\Ultron\Lixeira`. Sem resposta em 2 minutos = negado. |

## Instalação

1. **Python 3.12+**: `winget install Python.Python.3.12`
2. **Claude Code**: instale seguindo https://code.claude.com/docs/en/setup e rode `claude` uma vez no
   terminal para fazer login com sua conta Pro/Max.
3. **Ollama** (opcional, modo local): instale de https://ollama.com e rode `ollama pull qwen3:8b`.
   Com 8 GB de VRAM, alternativas: `llama3.1:8b` ou `qwen3.5:9b` (troque em `[ollama] model`).
   Para ler a tela no modo local: `ollama pull qwen3-vl:8b` (ou `qwen2.5vl:7b`, em `[ollama] vision_model`).
   Em 8 GB só cabe um modelo por vez: ler a tela no modo local troca de modelo e leva alguns segundos.
4. **Ultron**:
   ```powershell
   git clone https://github.com/suporteskoupa-coder/assistente-ia-windows "$HOME\ultron-app"
   cd "$HOME\ultron-app"
   powershell -ExecutionPolicy Bypass -File scripts\instalar.ps1
   ```
   Isso cria o ambiente Python, a configuração em `%USERPROFILE%\Ultron\ultron.toml` e o atalho
   **Ultron** na área de trabalho.

Para atualizar depois: `git pull` e rode o instalador de novo.

> O código e os dados ficam em pastas separadas: código em `ultron-app`, dados (cofre, configuração,
> banco) em `%USERPROFILE%\Ultron`. **Não** clone o código dentro de `%USERPROFILE%\Ultron`:
> no Windows, `ultron` e `Ultron` são a mesma pasta. Nunca rode `git clean` na pasta de dados.

## Configuração (`%USERPROFILE%\Ultron\ultron.toml`)

- `[apps]`: apelido = caminho do `.exe` ou comando. Ex.: `obs = "C:/Program Files/obs-studio/bin/64bit/obs64.exe"`.
- `[modes.<nome>]`: `apps` (apelidos acima) e `urls`.
- `[discord.channels]`: apelido = ID do canal.
- `[claude] allowed_bash`: comandos de terminal liberados sem confirmação, no formato do Claude Code
  (ex.: `"git status"`). Comece vazio.
- `[ultron] hotkey`: atalho que alterna tela cheia / modo compacto (padrão `ctrl+space`).

## Bot do Discord

1. Abra https://discord.com/developers/applications → **New Application** → aba **Bot** → **Reset Token** e copie.
2. Guarde o token no Windows (não no arquivo):  `setx ULTRON_DISCORD_TOKEN "SEU_TOKEN"`  e reabra o Ultron.
3. Aba **OAuth2 → URL Generator**: marque `bot`, depois as permissões **View Channels** e **Send Messages**.
   Abra a URL gerada e adicione o bot ao seu servidor.
4. No Discord: Configurações → Avançado → **Modo desenvolvedor**. Clique com o botão direito no canal →
   **Copiar ID** e coloque em `[discord.channels]`, ex.: `geral = "1234567890"`.

## Falar com o Ultron pelo celular (opcional)

Você manda DM para o bot no Discord e o Ultron responde por lá. O PC precisa estar ligado e o Ultron aberto.

1. Ative a **verificação em duas etapas** da sua conta do Discord. Quem entrar na sua conta controla o Ultron.
2. Com o Modo desenvolvedor ligado, clique no seu nome → **Copiar ID do usuário**.
3. No `ultron.toml`:
   ```toml
   [discord]
   controle_remoto = true
   dono_id = "SEU_ID"
   lembretes_no_celular = true   # opcional
   ```
4. Reabra o Ultron e mande uma DM para o bot (por exemplo, "quais minhas pendências?").

Travas: só o seu ID é atendido (outros recebem silêncio), terminal e edição de arquivos ficam sempre bloqueados
pelo celular, e ações como mandar mensagem em canal ou mover arquivos pedem **sim** ou **não** na DM.
A conversa aparece na HUD no chat "Discord (celular)".

## Ultron respondendo por você no servidor (opcional)

Quando alguém escreve a palavra de ativação ("ultron, o <seu nome> vai entrar?"), ele responde por você.

1. No portal do Discord, aba **Bot**, ligue **Message Content Intent**.
2. No `ultron.toml`, em `[discord.servidor]`: `ativo = true`, `canais = ["ID_DO_CANAL"]`, `seu_nome = "Seu Nome"`
   e escolha `notas` (`publica` = só `Notas/Publico`, `todas` = todas as suas notas exceto a pasta `Ultron/`).
3. Defina seu status: diga ao Ultron "meu status é jogando até 23h" ou mande DM ao bot: `status: jogando até 23h`.

O que ele sabe: seu status, horários ocupados de hoje (sem o texto dos lembretes) e suas notas.
O que ele não tem: ferramentas, controle do PC, diário, conclusões. Senhas, e-mails, CPF, cartões e telefones
são trocados por `[removido]`, mas o filtro só reconhece formatos: assuntos pessoais escritos nas notas podem sair.
Quem responde: com `cerebro = "seguir"` (padrão), o botão CLAUDE/LOCAL da HUD manda. No Claude não gasta
ferramentas, mas usa a cota; no local não gasta cota, mas disputa a placa de vídeo com o jogo. Se o Claude falhar
(ex.: limite da assinatura), ele tenta o local. Mensagens sem a palavra de ativação não gastam nada. Limite: 5 por minuto e 50 por dia (configurável).
As respostas aparecem na HUD (painel SERVIDOR) e no diário.

**Escalada (opcional, `escalada = true`):** com cada amigo, o Ultron fica mais vilão conforme a pessoa conversa
com ele (níveis 0 a 5, um nível a cada `escalada_passo` conversas). Limites fixos: o desprezo é pela humanidade,
nunca ofensa pessoal; ninguém é assediado de verdade. Quem escrever "ultron volta ao normal" zera o próprio nível.
Você, o criador, nunca entra na escalada. O nível de cada pessoa fica em `Ultron/Pessoas/<ID>.md` (linha "Interações").

## A HUD

O centro é a "mente" do Ultron, desenhada ao vivo:
- **ULTRON · CLAUDE**: massa dourada e caótica, com tentáculos de energia que estalam.
- **JARVIS · LOCAL**: esfera ciano ordenada, com malha geodésica. Trocar de modo faz um absorver o outro.
- Reage ao que ele está fazendo (pensando, ferramenta, respondendo, lendo a tela, confirmação, lembrete)
  e ao PC: CPU, RAM, placa de vídeo NVIDIA (`nvidia-smi`) e jogo da Steam aberto.
- Com jogo aberto, a animação cai para 15 quadros por segundo e fica discreta; parada, 30; minimizada, pausa.
- Sons de interface opcionais no botão ♪ da barra do topo.

## Personalidade e jeito de falar

- `Ultron/Personalidade.md` no cofre: quem ele é. Edite à vontade.
- `Ultron/Exemplos.md`: banco de exemplos de fala (vem com ~120). A cada mensagem ele usa os 3 mais
  parecidos como referência de tom. Apague o que não soar como o Ultron e edite o que estiver quase bom.
- O 👍 ao lado de uma resposta na HUD guarda aquela resposta no banco.

## Uso

- Abra pelo atalho **Ultron**. `Ctrl+Espaço` alterna entre tela cheia e o núcleo compacto no canto.
- Escolha **CLAUDE** ou **LOCAL** antes de criar um chat. "Continuar no outro cérebro" cria um chat novo
  com o resumo do atual.
- "Encerrar chat" salva um resumo em `Ultron/Chats` no cofre.
- Abra a pasta `%USERPROFILE%\Ultron\UltronVault` como cofre no Obsidian para ver e editar a memória.
  Apagar uma linha de `conclusoes.md` faz o Ultron esquecer aquela conclusão.
- Todo dia às 4h (se o PC estiver ligado e o Ultron aberto), o Claude revisa as conclusões a partir do diário.

## Problemas comuns

| Sintoma | Causa provável |
|---|---|
| "Claude Code não encontrado" | `claude` não está no PATH. Abra um terminal novo e rode `claude --version`. |
| "Ollama não está rodando" | Abra o app do Ollama. |
| "Modelo ... não está baixado" | `ollama pull <modelo>` |
| Discord "respondeu 403" | O bot não está no servidor ou não tem permissão no canal. |
| Janela não abre / tela branca | Instale o Microsoft Edge WebView2 Runtime. |
| Erro "porta 8765" | Já existe um Ultron aberto, ou troque `[ultron] port`. |

Para ver mensagens de erro, rode `.\.venv\Scripts\python.exe -m ultron` num terminal.

## Desenvolvimento

```bash
pip install -e ".[dev]" playwright
pytest
```
