# Friday — monitor universal v6.0

Atualização: envie monitor.py e README.md à raiz do repositório e substitua o conteúdo de .github/workflows/monitor.yml pelo monitor.yml deste pacote. Preserve produtos.json, historico.json, requirements.txt e os Secrets TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID. Não envie a pasta inteira. O workflow usa a branch main.

Envie /menu ao bot em conversa privada e execute Friday Monitor v6 em Actions > Run workflow (teste marcado). O teclado permite cadastrar, consultar, alterar preço, pausar, ativar, remover com confirmação, adicionar link, configurar aviso sem estoque e solicitar busca. Responda um campo por vez; Cancelar desfaz o diálogo em andamento. Os comandos antigos continuam disponíveis; /ajuda lista a sintaxe. A configuração é salva no repositório. Até 10 produtos; comece com poucos. Não publique credenciais.

Comandos consultados a cada cinco minutos (minutos 02,07,...57); busca uma vez por hora, ou sob demanda. Respostas podem atrasar. O histórico guarda o estado do diálogo e o offset do Telegram; não o apague. Repositórios públicos expõem configurações e histórico, não os Secrets. Não use este bot para informações privadas.

Coleta: Bing, DuckDuckGo e Brave via DDGS, links diretos, JSON-LD e microdata. Amazon exige preço confirmado no fallback. Magalu exige link direto /p/. HTTP 403/429 suspende novas consultas daquele domínio na execução; não contorna bloqueios. Falha não implica falta de estoque. Vendedores, impostos e frete não são automaticamente confirmados. Importação continua estimativa manual. Testes locais: python -m unittest -v test_monitor.py (instale requirements.txt antes). O arquivo test_monitor.py é opcional para instalação.
