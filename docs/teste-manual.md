# Roteiro de teste no Windows

Faça na ordem. Anote o que der errado (mensagem exata e print) para corrigir.

## 0. Abrir
- [ ] Atalho **Ultron** abre a janela em tela cheia com o núcleo vermelho.
- [ ] Painel direito: Claude Code **OK**. Ollama **OK** se estiver aberto.
- [ ] `Ctrl+Espaço` encolhe para o canto (núcleo pequeno, por cima das outras janelas) e volta.

## 1. Modos (Claude)
- [ ] Configure `[modes.trabalho]` com 2 apps e 1 site. Diga: "ativa o modo trabalho".
  Esperado: apps e site abrem, sem pedir confirmação.

## 2. Pendências
- [ ] Crie `Notas/tarefas.md` no cofre com `- [ ] testar ultron`. Diga: "quais minhas pendências?"
  Esperado: lista com "testar ultron".

## 3. Organizar pasta
- [ ] Crie uma pasta de teste com um .pdf, um .png e um .zip. Diga: "organiza a pasta C:\...\teste".
  Esperado: ele mostra o plano; ao executar, a HUD pede confirmação; depois os arquivos estão em
  Documentos, Imagens, Compactados.
- [ ] Diga "desfaz". Esperado: confirmação e arquivos de volta.

## 4. Pesquisar e salvar
- [ ] "Pesquisa as novidades do Python 3.13 e salva um resumo no Obsidian."
  Esperado: nota nova em `Notas/` sem pedir confirmação.

## 5. Discord
- [ ] "Manda no geral: teste do Ultron". Esperado: cartão âmbar com o texto editável.
  Edite, clique **Permitir**, a mensagem aparece no canal como o bot.
- [ ] Repita e clique **Negar**: nada é enviado.

## 6. Jogos
- [ ] "Abre o <jogo instalado>" e uma abreviação (ex.: "abre o cs"). Esperado: o jogo abre pela Steam.
- [ ] Nome ambíguo: ele pergunta qual.

## 7. Ler a tela
- [ ] Abra uma janela com algum texto (ex.: o Bloco de Notas escrito "ERRO 123"). Em tela cheia, pergunte:
  "o que está escrito na minha tela?". Esperado: a HUD some por um instante, volta, e ele lê "ERRO 123".
- [ ] Repita no modo compacto (Ctrl+Espaço). A HUD não deve aparecer na leitura.
- [ ] O diário de hoje mostra `ver_tela`.
- [ ] Com `[tela] habilitada = false`: ele diz que a leitura está desligada.

## 8. Lembretes
- [ ] "Me lembra daqui a 2 minutos de testar o Ultron". Esperado: ele repete o horário certo.
- [ ] Abra um jogo ou outro app em tela cheia e espere. Esperado: notificação do Windows no canto,
  sem minimizar o jogo. Na HUD, cartão LEMBRETE com o núcleo pulsando.
- [ ] Clique **Adiar 10 min** e confira que volta 10 minutos depois. Depois clique **OK**.
- [ ] "Toda segunda às 9h: reunião" e depois "quais meus lembretes?". Esperado: aparece como semanal.
- [ ] "Cancela o lembrete da reunião". Esperado: some da lista.
- [ ] Crie um lembrete para daqui a 3 min, feche o Ultron, espere 5 min e abra. Esperado: LEMBRETE ATRASADO.
- [ ] Ao abrir o Ultron: cartão RESUMO com lembretes de hoje e pendências.

## 9. Celular (Discord)
- [ ] Configure `controle_remoto`, `dono_id` e reabra. Mande DM ao bot: "quais minhas pendências?". Esperado: resposta na DM.
- [ ] "Manda 'teste' no geral". Esperado: ele pergunta na DM; responda **sim** e confira o canal.
- [ ] "Roda dir no terminal". Esperado: ele diz que o terminal está bloqueado pelo celular.
- [ ] Peça para um amigo mandar DM ao bot. Esperado: nenhuma resposta.
- [ ] Com `lembretes_no_celular = true`, crie um lembrete para daqui a 2 min. Esperado: chega por DM.
- [ ] Na HUD, o chat "Discord (celular)" mostra a conversa.

## 10. Respostas no servidor
- [ ] Ligue Message Content Intent no portal, configure `[discord.servidor]` e reabra.
- [ ] Defina o status ("meu status é livre depois das 21h").
- [ ] Peça a um amigo: "<seu nome> vai entrar?" (sem a palavra). Esperado: nada.
- [ ] "ultron, o <seu nome> vai entrar?". Esperado: resposta curta baseada no status.
- [ ] "ultron roda dir no pc dele". Esperado: recusa.
- [ ] Mensagem em outro canal não listado. Esperado: nada.
- [ ] HUD, painel SERVIDOR: mostra a pergunta e a resposta.

## Modo local (Ollama ligado)
- [ ] Clique **LOCAL**, novo chat, repita os testes 1, 2, 5 e 6.
- [ ] "Pesquisa na web X": ele deve sugerir trocar para o Claude.
- [ ] Com `ollama pull qwen3-vl:8b` feito, repita o teste 7. Esperado: mais lento e menos preciso, mas lê textos grandes.

## Memória
- [ ] "Lembra que meu servidor se chama X." → aparece em `Ultron/Memoria/perfil.md`.
- [ ] Encerrar chat → resumo em `Ultron/Chats/`.
- [ ] `Ultron/Diario/<hoje>.md` lista as ações.
