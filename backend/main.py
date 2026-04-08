"""
Dashboard Financeiro Pessoal — Backend FastAPI
Servidor principal com autenticação Supabase e endpoints REST.
"""

import os
from datetime import datetime

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from jose import jwt, JWTError
from pydantic import BaseModel, Field
from supabase import create_client, Client

# ── Configuração ─────────────────────────────────────────────────────────────

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
SUPABASE_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET")

if not all([SUPABASE_URL, SUPABASE_KEY, SUPABASE_JWT_SECRET]):
    raise RuntimeError("Variáveis SUPABASE_URL, SUPABASE_KEY e SUPABASE_JWT_SECRET são obrigatórias no .env")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

app = FastAPI(title="Dashboard Financeiro", version="1.0.0")

# CORS — permite o frontend se comunicar com o backend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Em produção, restrinja ao domínio do frontend
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Modelos Pydantic ─────────────────────────────────────────────────────────

class AuthRequest(BaseModel):
    email: str
    password: str = Field(min_length=6)

class TransactionCreate(BaseModel):
    tipo: str = Field(pattern=r"^(renda|gasto)$")
    valor: float = Field(gt=0)
    descricao: str = Field(min_length=1, max_length=200)
    data: str  # formato YYYY-MM-DD

class LayoutSave(BaseModel):
    layout: dict

# ── Autenticação ─────────────────────────────────────────────────────────────

def get_current_user_id(authorization: str = Header(...)) -> str:
    """Extrai e valida o user_id a partir do token JWT do Supabase."""
    token = authorization.replace("Bearer ", "") if authorization.startswith("Bearer ") else authorization
    try:
        # Detecta o algoritmo real do token
        header = jwt.get_unverified_header(token)
        alg = header.get("alg", "HS256")

        payload = jwt.decode(
            token,
            SUPABASE_JWT_SECRET,
            algorithms=[alg],
            options={"verify_aud": False},
        )

        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="Token inválido: sem sub")
        return user_id
    except JWTError as e:
        raise HTTPException(status_code=401, detail=f"Token inválido: {str(e)}")

# ── Endpoints de Autenticação ────────────────────────────────────────────────

@app.post("/register")
def register(body: AuthRequest):
    """Cria uma nova conta no Supabase Auth."""
    try:
        res = supabase.auth.sign_up({"email": body.email, "password": body.password})
        if res.user is None:
            raise HTTPException(status_code=400, detail="Erro ao criar conta. Verifique os dados.")
        return {"message": "Conta criada com sucesso! Verifique seu e-mail se necessário.", "user_id": res.user.id}
    except Exception as e:
        detail = str(e)
        raise HTTPException(status_code=400, detail=detail)

@app.post("/login")
def login(body: AuthRequest):
    """Faz login e retorna o token JWT."""
    try:
        res = supabase.auth.sign_in_with_password({"email": body.email, "password": body.password})
        if res.session is None:
            raise HTTPException(status_code=401, detail="Credenciais inválidas")
        return {
            "access_token": res.session.access_token,
            "user_id": res.user.id,
            "email": res.user.email,
        }
    except Exception as e:
        detail = str(e)
        raise HTTPException(status_code=401, detail=detail)

# ── Endpoints de Transações ──────────────────────────────────────────────────

@app.get("/transactions")
def list_transactions(user_id: str = Depends(get_current_user_id)):
    """Lista todas as transações do usuário autenticado, ordenadas por data desc."""
    res = (
        supabase.table("transactions")
        .select("*")
        .eq("user_id", user_id)
        .order("data", desc=True)
        .execute()
    )
    return res.data

@app.post("/transactions")
def create_transaction(body: TransactionCreate, user_id: str = Depends(get_current_user_id)):
    """Cria uma nova transação para o usuário autenticado."""
    # Valida formato da data
    try:
        datetime.strptime(body.data, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail="Data deve estar no formato YYYY-MM-DD")

    row = {
        "user_id": user_id,
        "tipo": body.tipo,
        "valor": body.valor,
        "descricao": body.descricao,
        "data": body.data,
    }
    res = supabase.table("transactions").insert(row).execute()
    if not res.data:
        raise HTTPException(status_code=500, detail="Erro ao salvar transação")
    return res.data[0]

# ── Endpoint de Resumo ───────────────────────────────────────────────────────

@app.get("/summary")
def get_summary(user_id: str = Depends(get_current_user_id)):
    """Retorna total de rendas, gastos e saldo do usuário."""
    res = (
        supabase.table("transactions")
        .select("tipo, valor, data")
        .eq("user_id", user_id)
        .execute()
    )
    total_renda = 0.0
    total_gasto = 0.0
    # Agrupamento mensal para gráfico de evolução
    monthly: dict[str, dict[str, float]] = {}

    for t in res.data:
        mes = t["data"][:7]  # YYYY-MM
        if mes not in monthly:
            monthly[mes] = {"renda": 0.0, "gasto": 0.0}
        if t["tipo"] == "renda":
            total_renda += t["valor"]
            monthly[mes]["renda"] += t["valor"]
        else:
            total_gasto += t["valor"]
            monthly[mes]["gasto"] += t["valor"]

    # Ordena por mês
    evolucao = [{"mes": k, **v} for k, v in sorted(monthly.items())]

    return {
        "total_renda": total_renda,
        "total_gasto": total_gasto,
        "saldo": total_renda - total_gasto,
        "evolucao": evolucao,
    }

# ── Endpoints de Layout ─────────────────────────────────────────────────────

DEFAULT_LAYOUT = {
    "tema": "light",
    "widgets": [
        {"id": "saldo", "x": 0, "y": 0, "w": 12, "h": 2},
        {"id": "grafico_pizza", "x": 0, "y": 2, "w": 6, "h": 4},
        {"id": "grafico_linha", "x": 6, "y": 2, "w": 6, "h": 4},
        {"id": "transacoes", "x": 0, "y": 6, "w": 12, "h": 4},
    ],
}

@app.get("/layout")
def get_layout(user_id: str = Depends(get_current_user_id)):
    """Retorna o layout do dashboard do usuário. Cria um padrão se não existir."""
    res = (
        supabase.table("dashboard_layouts")
        .select("*")
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    if res.data:
        return res.data[0]

    # Cria layout padrão
    row = {"user_id": user_id, "layout": DEFAULT_LAYOUT}
    insert_res = supabase.table("dashboard_layouts").insert(row).execute()
    if not insert_res.data:
        raise HTTPException(status_code=500, detail="Erro ao criar layout padrão")
    return insert_res.data[0]

@app.post("/layout")
def save_layout(body: LayoutSave, user_id: str = Depends(get_current_user_id)):
    """Salva/atualiza o layout do dashboard do usuário."""
    # Verifica se já existe
    existing = (
        supabase.table("dashboard_layouts")
        .select("id")
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    if existing.data:
        res = (
            supabase.table("dashboard_layouts")
            .update({"layout": body.layout})
            .eq("user_id", user_id)
            .execute()
        )
    else:
        res = (
            supabase.table("dashboard_layouts")
            .insert({"user_id": user_id, "layout": body.layout})
            .execute()
        )
    if not res.data:
        raise HTTPException(status_code=500, detail="Erro ao salvar layout")
    return res.data[0]

# ── Debug: Testar token (remover em produção) ───────────────────────────────

@app.get("/debug-token")
def debug_token(authorization: str = Header(...)):
    """Endpoint temporário para debugar problemas com JWT."""
    token = authorization.replace("Bearer ", "") if authorization.startswith("Bearer ") else authorization
    # Decodifica SEM verificar para ver o conteúdo
    try:
        unverified = jwt.get_unverified_claims(token)
    except Exception as e:
        return {"error": f"Token malformado: {str(e)}"}

    # Tenta verificar
    try:
        verified = jwt.decode(token, SUPABASE_JWT_SECRET, algorithms=["HS256"], options={"verify_aud": False})
        return {"status": "valid", "claims": verified}
    except JWTError as e:
        return {"status": "invalid", "reason": str(e), "unverified_claims": unverified}

# ── Health Check ─────────────────────────────────────────────────────────────

@app.api_route("/", methods=["GET", "HEAD"])
def health():
    return {"status": "ok", "service": "Dashboard Financeiro API"}

# ── Entrypoint para produção ─────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
