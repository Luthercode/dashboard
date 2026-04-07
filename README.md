# 💰 Dashboard Financeiro Pessoal

Dashboard web moderno para controle financeiro pessoal com autenticação, gráficos interativos e layout personalizável. Funciona em celulares e desktops como PWA instalável.

---

## 📁 Estrutura do Projeto

```
dashboard/
├── backend/
│   ├── main.py              # Servidor FastAPI (endpoints REST)
│   ├── requirements.txt     # Dependências Python
│   ├── .env                 # Variáveis de ambiente (NÃO versionar)
│   └── .env.example         # Modelo de variáveis
├── frontend/
│   ├── index.html           # Tela de login/cadastro
│   ├── dashboard.html       # Dashboard principal
│   ├── config.js            # URL da API
│   ├── manifest.json        # Manifesto PWA
│   ├── sw.js                # Service Worker
│   └── icons/               # Ícones PWA
├── database/
│   └── schema.sql           # SQL para criar tabelas no Supabase
├── .gitignore
└── README.md
```

---

## 🚀 Como Rodar — Passo a Passo

### 1. Configurar o Supabase

1. Acesse [supabase.com](https://supabase.com) e crie um projeto gratuito.
2. Vá em **Settings → API** e copie:
   - `Project URL` → será o `SUPABASE_URL`
   - `anon public` key → será o `SUPABASE_KEY`
   - `JWT Secret` (em Settings → API → JWT Settings) → será o `SUPABASE_JWT_SECRET`

3. Vá em **SQL Editor** e cole o conteúdo do arquivo `database/schema.sql`. Execute.

4. Em **Authentication → Settings**, confirme que "Enable email signup" está ativado.

### 2. Configurar o Backend

```bash
cd backend

# Crie um ambiente virtual
python -m venv venv

# Ative o ambiente
# Windows:
venv\Scripts\activate
# Linux/Mac:
source venv/bin/activate

# Instale dependências
pip install -r requirements.txt
```

Edite o arquivo `backend/.env` com seus dados do Supabase:

```env
SUPABASE_URL=https://xxxxx.supabase.co
SUPABASE_KEY=eyJhbGciOiJI...
SUPABASE_JWT_SECRET=seu-jwt-secret-aqui
```

### 3. Rodar o Backend

```bash
cd backend
uvicorn main:app --reload --port 8000
```

O servidor estará em `http://localhost:8000`. Verifique acessando `http://localhost:8000/` — deve retornar `{"status": "ok"}`.

### 4. Configurar o Frontend

Edite `frontend/config.js` se necessário (padrão aponta para `http://localhost:8000`):

```js
const APP_CONFIG = {
    API_URL: 'http://localhost:8000',
};
```

### 5. Rodar o Frontend

Abra o `frontend/index.html` no navegador, ou use um servidor estático:

```bash
# Opção 1: Python
cd frontend
python -m http.server 3000

# Opção 2: Node.js (npx)
cd frontend
npx serve -l 3000
```

Acesse `http://localhost:3000`.

---

## 🔧 Funcionalidades

| Funcionalidade | Descrição |
|---|---|
| **Cadastro/Login** | Autenticação via Supabase Auth (e-mail + senha) |
| **Transações** | Adicionar rendas e gastos com data e descrição |
| **Saldo** | Visualização em tempo real do saldo total |
| **Gráfico Pizza** | Proporção renda vs gasto (Chart.js) |
| **Gráfico Linha** | Evolução mensal de rendas e gastos |
| **Tema** | Claro / Escuro com troca instantânea |
| **Layout** | Reordenação de widgets via drag & drop |
| **PWA** | Instalável como app no celular |
| **Responsivo** | Mobile-first com Bootstrap 5 |
| **Segurança** | JWT + RLS no Supabase = dados isolados por usuário |

---

## 🔒 Segurança

- **Autenticação JWT**: Cada requisição ao backend é validada via token.
- **Row Level Security (RLS)**: Mesmo acessando o banco diretamente, cada usuário só vê seus próprios dados.
- **Validação de entrada**: Pydantic valida tipo, valor, data e descrição no backend.
- **CORS configurável**: Em produção, restrinja `allow_origins` no CORS.

---

## ⚠️ Erros Comuns e Soluções

### "Variáveis SUPABASE_URL, SUPABASE_KEY e SUPABASE_JWT_SECRET são obrigatórias"
→ Edite o arquivo `backend/.env` com os dados corretos do seu projeto Supabase.

### "Token inválido ou expirado"
→ Faça logout e login novamente. Tokens expiram após um tempo.

### CORS error no navegador
→ Verifique se o backend está rodando na porta correta (8000).
→ Se o frontend está em outra origem, confirme que o CORS está configurado.

### "relation 'transactions' does not exist"
→ Execute o SQL do arquivo `database/schema.sql` no SQL Editor do Supabase.

### Erro ao criar conta: "User already registered"
→ O e-mail já está cadastrado. Use outro ou faça login.

### Gráficos não aparecem
→ Verifique se há transações cadastradas. Sem dados, os gráficos ficam vazios.

### PWA não instala
→ O service worker requer HTTPS ou localhost. Não funciona em `file://`.
→ Os ícones devem ser arquivos PNG reais (os SVG incluídos são placeholders).

---

## 📱 PWA (App Instalável)

Para que o app seja instalável no celular:

1. Sirva o frontend via HTTPS (ex: Vercel, Netlify, ou localhost para testes).
2. Converta os ícones SVG em `frontend/icons/` para PNG (192x192 e 512x512).
3. Abra no Chrome mobile → menu → "Instalar app" ou "Adicionar à tela inicial".

---

## 🏗 Deploy em Produção

1. **Backend**: Deploy no Railway, Render, Fly.io ou qualquer servidor Python.
2. **Frontend**: Deploy no Vercel, Netlify ou GitHub Pages (arquivos estáticos).
3. Atualize `frontend/config.js` com a URL pública do backend.
4. No backend, restrinja CORS para o domínio do frontend.

---

## Tecnologias

- **Backend**: Python 3.10+, FastAPI, Supabase Python SDK
- **Frontend**: HTML5, CSS3, JavaScript ES6+, Bootstrap 5, Chart.js
- **Banco**: PostgreSQL (via Supabase)
- **Auth**: Supabase Auth (JWT)
- **PWA**: Service Worker + Web App Manifest
