# Sebo Store

Catálogo para um grupo de sebos de Belém - PA. O sistema consiste em um site de catálogo para a coleção de sebos parceiros do Forra Cultural. Os clientes navegam, buscam por título/autor, filtram por gênero, montam o carrinho e finalizam o pedido pelo **WhatsApp** — a mensagem já vai pronta com a lista de livros e o total.


## Stack

- **Python + Flask** (servidor web + templates)
- **SQLite** (banco de dados — arquivo `sebo_store.db`, criado automaticamente)
- **OpenAI (gpt-4o-mini)** — identificação de livros pela capa no painel admin
- HTML/CSS/JavaScript vanilla no front

## Como rodar

```bash
# 1. (opcional) criar um ambiente virtual
python3 -m venv .venv
source .venv/bin/activate

# 2. instalar dependências
pip install -r requirements.txt

# 3. rodar o servidor de desenvolvimento
python3 app.py
```

Acesse: **http://127.0.0.1:5000**

Na primeira execução o banco é criado e um admin padrão é gerado:

- usuário: `admin`
- senha: `admin123`

**Troque a senha imediatamente** em `Admin → Senha` (ou em produção via env).

## Rotas principais

### Site público
- `/` — catálogo, com `?q=...` (busca) e `?genero=...` (filtro)
- `/livro/<id>` — detalhe de um livro
- `/carrinho` — carrinho local + finalização pelo WhatsApp
- `/api/checkout` (POST) — salva o pedido e devolve a URL do WhatsApp

### Admin (login obrigatório)
- `/admin/login`, `/admin/logout`, `/admin/senha`
- `/admin` — painel com estatísticas
- `/admin/livros` — lista, adicionar, editar, remover
- `/admin/pedidos` — pedidos com filtro por status (pendente/concluído/cancelado)

## Configuração

No topo de `app.py`:

```python
WHATSAPP_NUMBER = "5592993280966"   # número do vendedor (só dígitos, com DDI+DDD)
STORE_NAME = "Sebo Store"
GENRES = [...]                       # lista de gêneros disponíveis
```

Variáveis de ambiente (em `.env` — copie do `.env.example`):

- `OPENAI_API_KEY` — chave da API da OpenAI (obrigatória pra usar a identificação por IA)
- `OPENAI_MODEL` — modelo usado, padrão `gpt-4o-mini` (também aceita `gpt-4o`)
- `SEBO_SECRET` — chave secreta da sessão Flask (valor aleatório longo em produção)

## Identificação de livros por IA (admin)

Ao **adicionar um livro novo**, a imagem da capa é o primeiro campo. Assim que você escolhe a imagem:

1. A capa é enviada pra OpenAI (gpt-4o-mini com visão).
2. Se a IA reconhecer o livro → **preenche título, autor, gênero e descrição** automaticamente. Você só revisa e salva.
3. Se a IA **não** reconhecer → você preenche **título** e **autor** manualmente, depois clica no botão **"✨ Completar com IA"** ao lado da Descrição e a IA preenche gênero + sinopse a partir desses dois campos.

Para habilitar:

1. Pegue uma chave em https://platform.openai.com/api-keys
2. Configure billing/saldo em https://platform.openai.com/account/billing (sem isso, a API devolve `insufficient_quota`)
3. Crie um arquivo `.env` (com base no `.env.example`):

   ```bash
   cp .env.example .env
   # edite .env e coloque sua OPENAI_API_KEY
   ```

4. Reinicie o servidor.

**Custo aproximado** (gpt-4o-mini): ~US$ 0,15 a cada mil identificações por imagem; muito menor para "completar com IA" (sem imagem). Para uso típico de um sebo, o custo mensal é desprezível.

Se `OPENAI_API_KEY` não estiver definida, o formulário continua funcionando normalmente (modo manual), só sem o auto-preenchimento.

## Banco de dados

Tabelas (criadas automaticamente):

- `books` — id, title, author, genre, price, description, image_filename, stock, created_at
- `orders` — id, customer_name, items_json (lista de livros), total, status, created_at
- `admins` — id, username, password_hash

Para resetar tudo, basta apagar o arquivo `sebo_store.db` (ele será recriado no próximo start).

## Estrutura

```
sebo store/
├── app.py                     # toda a aplicação Flask
├── requirements.txt
├── Procfile                   # comando de start (gunicorn) pra produção
├── railway.json               # config de deploy do Railway
├── .python-version            # versão do Python pro builder
├── .env.example               # modelo das variáveis de ambiente
├── sebo_store.db              # criado em runtime (não versionado)
├── static/
│   ├── css/style.css
│   ├── js/cart.js             # carrinho via localStorage
│   ├── js/home.js             # destaque rotativo + carrosséis
│   └── uploads/               # imagens dos livros (não versionado)
└── templates/
    ├── base.html              # layout do site público
    ├── home.html              # página inicial (hero + carrosséis + destaque)
    ├── catalog.html           # catálogo com busca/filtro
    ├── book_detail.html       # detalhe + "você também pode gostar"
    ├── _section_carousel.html # parcial: carrossel temático
    ├── _section_spotlight.html# parcial: destaque rotativo
    ├── cart.html
    ├── 404.html
    └── admin/
        ├── base_admin.html
        ├── login.html
        ├── dashboard.html
        ├── books.html
        ├── book_form.html
        ├── orders.html
        └── change_password.html
```

## Como funciona o checkout

1. Cliente adiciona livros ao carrinho (guardado em `localStorage` no navegador).
2. Em `/carrinho` clica em **Finalizar pelo WhatsApp**.
3. O JS envia o carrinho para `POST /api/checkout`.
4. O servidor:
   - valida e busca os livros no banco (usa o preço atual, não o preço guardado no front);
   - salva o pedido na tabela `orders` com status `pendente`;
   - monta uma mensagem formatada e devolve a URL do WhatsApp (`https://wa.me/<numero>?text=<mensagem>`).
5. O navegador abre o WhatsApp do vendedor com a mensagem pré-preenchida.
6. O admin acompanha o pedido em `/admin/pedidos` e marca como concluído/cancelado.

## Variáveis de ambiente (produção)

| Variável | Para quê | Exemplo |
|---|---|---|
| `OPENAI_API_KEY` | identificação de livro por IA | `sk-...` |
| `OPENAI_MODEL` | modelo da OpenAI | `gpt-4o-mini` |
| `SEBO_SECRET` | chave da sessão Flask (use algo aleatório!) | `a9f3...` |
| `SEBO_DB_PATH` | caminho do banco (aponte pro disco persistente) | `/data/sebo_store.db` |
| `SEBO_UPLOAD_DIR` | pasta das imagens (disco persistente) | `/data/uploads` |
| `SEBO_WHATSAPP` | número do vendedor (opcional, sobrescreve o código) | `5592993280966` |
| `SEBO_STORE_NAME` | nome da loja (opcional) | `Sebo Store` |
| `FLASK_DEBUG` | `0` em produção | `0` |
| `PORT` | porta (a plataforma define) | `8000` |

Gere um `SEBO_SECRET` forte com:

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

---

# 🚀 Deploy no Railway

O projeto já vem pronto pra Railway (`Procfile`, `railway.json`, `gunicorn` no requirements).
A app usa **SQLite + uploads em disco**, então é obrigatório um **Volume** persistente.

### Passo 1 — Subir o código no GitHub

```bash
cd "sebo store"
git init
git add .
git commit -m "Sebo Store pronto pra produção"
# crie um repositório no GitHub e então:
git remote add origin https://github.com/SEU_USUARIO/sebo-store.git
git branch -M main
git push -u origin main
```

> O `.gitignore` já protege `.env`, o banco (`*.db`) e os uploads — eles **não** vão pro GitHub.

### Passo 2 — Criar o projeto no Railway

1. Entre em [railway.app](https://railway.app) e faça login com o GitHub.
2. **New Project → Deploy from GitHub repo →** selecione o repositório.
3. O Railway detecta Python automaticamente (via Nixpacks) e usa o `Procfile`.

### Passo 3 — Criar o Volume (disco persistente) ⚠️ IMPORTANTE

Sem isso, livros e imagens somem a cada deploy.

1. No serviço, aba **Variables/Settings → Volumes → New Volume**.
2. **Mount path:** `/data`
3. Salve.

### Passo 4 — Configurar as variáveis de ambiente

Na aba **Variables** do serviço, adicione:

```
OPENAI_API_KEY   = sk-...           (sua chave)
OPENAI_MODEL     = gpt-4o-mini
SEBO_SECRET      = <cole o token gerado com o comando acima>
SEBO_DB_PATH     = /data/sebo_store.db
SEBO_UPLOAD_DIR  = /data/uploads
FLASK_DEBUG      = 0
```

> `SEBO_DB_PATH` e `SEBO_UPLOAD_DIR` apontam pro Volume `/data` — é o que garante a persistência.

### Passo 5 — Gerar o domínio

1. Aba **Settings → Networking → Generate Domain**.
2. O Railway cria uma URL `https://...up.railway.app` com HTTPS já incluso.
3. Acesse `…/admin/login` (usuário `admin`, senha `admin123`) e **troque a senha imediatamente** em *Senha*.

### Passo 6 (opcional) — Domínio próprio

1. Compre um domínio (ex: [registro.br](https://registro.br) pra `.com.br`).
2. No Railway: **Settings → Networking → Custom Domain**, informe seu domínio.
3. Adicione o registro **CNAME** que o Railway mostrar no painel do seu domínio.
4. Em alguns minutos o HTTPS é emitido automaticamente.

---

## Checklist final de produção

- [ ] Volume `/data` criado e `SEBO_DB_PATH` / `SEBO_UPLOAD_DIR` apontando pra ele
- [ ] `SEBO_SECRET` aleatório definido
- [ ] `OPENAI_API_KEY` definida e com saldo na conta OpenAI
- [ ] Senha do admin trocada (não deixar `admin123`)
- [ ] `FLASK_DEBUG=0`
- [ ] Testar: cadastrar um livro com imagem, fazer um pedido, ver no `/admin/pedidos`
- [ ] Fazer um redeploy e confirmar que os dados **persistiram** (prova do volume)

## Backup

Os dados ficam todos no Volume (`/data`): o banco `sebo_store.db` e as imagens em `/data/uploads`.
Faça backups periódicos desse volume (o Railway permite baixar/snapshot via dashboard ou CLI).
