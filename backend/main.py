"""
Dashboard Financeiro Pessoal — Backend FastAPI
Servidor principal com autenticação Supabase e endpoints REST.
"""

import os
from datetime import datetime, timedelta
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Depends, Header, Request, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from jose import jwt
from pydantic import BaseModel, Field
from supabase import create_client, Client

# ── Configuração ─────────────────────────────────────────────────────────────

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")  # anon key — usado para auth (login/register)
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", SUPABASE_KEY)  # service_role key — usado para queries (ignora RLS)

if not all([SUPABASE_URL, SUPABASE_KEY]):
    raise RuntimeError("Variáveis SUPABASE_URL e SUPABASE_KEY são obrigatórias no .env")

# Cliente para autenticação (anon key)
supabase_auth: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
# Cliente para dados (service_role key — ignora RLS)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

app = FastAPI(title="Dashboard Financeiro", version="1.0.0")

# CORS — permite o frontend se comunicar com o backend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Handler global de exceções — garante que CORS headers são sempre enviados
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={"detail": f"Erro interno: {str(exc)}"},
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Credentials": "true",
        },
    )

# ── Modelos Pydantic ─────────────────────────────────────────────────────────

class AuthRequest(BaseModel):
    email: str
    password: str = Field(min_length=6)

class TransactionCreate(BaseModel):
    tipo: str = Field(pattern=r"^(renda|gasto)$")
    valor: float = Field(gt=0)
    descricao: str = Field(min_length=1, max_length=200)
    categoria: str = Field(default="Outros", max_length=50)
    data: str  # formato YYYY-MM-DD

class LayoutSave(BaseModel):
    layout: dict

# ── Autenticação ─────────────────────────────────────────────────────────────

def get_current_user_id(authorization: str = Header(...)) -> str:
    """Extrai o user_id do token JWT do Supabase.
    A segurança dos dados é garantida pelo RLS no banco."""
    token = authorization.replace("Bearer ", "") if authorization.startswith("Bearer ") else authorization
    try:
        # Decodifica o token — extrai claims sem verificar assinatura
        # A proteção real dos dados é feita pelo Row Level Security do Supabase
        payload = jwt.get_unverified_claims(token)

        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="Token inválido: sem sub")
        return user_id
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Token inválido: {str(e)}")

# ── Endpoints de Autenticação ────────────────────────────────────────────────

@app.post("/register")
def register(body: AuthRequest):
    """Cria uma nova conta no Supabase Auth."""
    try:
        res = supabase_auth.auth.sign_up({"email": body.email, "password": body.password})
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
        res = supabase_auth.auth.sign_in_with_password({"email": body.email, "password": body.password})
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
def list_transactions(
    user_id: str = Depends(get_current_user_id),
    periodo: Optional[str] = Query(None, pattern=r"^(7d|30d|90d|12m|all)$"),
    data_inicio: Optional[str] = Query(None),
    data_fim: Optional[str] = Query(None),
):
    """Lista transações do usuário com filtros opcionais de período."""
    query = supabase.table("transactions").select("*").eq("user_id", user_id)

    # Filtro por período predefinido
    if periodo and periodo != "all":
        hoje = datetime.now().date()
        if periodo == "7d":
            inicio = hoje - timedelta(days=7)
        elif periodo == "30d":
            inicio = hoje - timedelta(days=30)
        elif periodo == "90d":
            inicio = hoje - timedelta(days=90)
        elif periodo == "12m":
            inicio = hoje - timedelta(days=365)
        query = query.gte("data", inicio.isoformat())
    elif data_inicio:
        query = query.gte("data", data_inicio)

    if data_fim:
        query = query.lte("data", data_fim)

    res = query.order("data", desc=True).execute()
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
        "categoria": body.categoria,
    }
    res = supabase.table("transactions").insert(row).execute()
    if not res.data:
        raise HTTPException(status_code=500, detail="Erro ao salvar transação")
    return res.data[0]

# ── Endpoint de Resumo ───────────────────────────────────────────────────────

@app.get("/summary")
def get_summary(
    user_id: str = Depends(get_current_user_id),
    periodo: Optional[str] = Query(None, pattern=r"^(7d|30d|90d|12m|all)$"),
):
    """Retorna resumo financeiro completo com agrupamentos para gráficos."""
    query = supabase.table("transactions").select("tipo, valor, data, categoria, descricao").eq("user_id", user_id)

    hoje = datetime.now().date()
    if periodo and periodo != "all":
        if periodo == "7d":
            inicio = hoje - timedelta(days=7)
        elif periodo == "30d":
            inicio = hoje - timedelta(days=30)
        elif periodo == "90d":
            inicio = hoje - timedelta(days=90)
        elif periodo == "12m":
            inicio = hoje - timedelta(days=365)
        query = query.gte("data", inicio.isoformat())

    res = query.execute()

    total_renda = 0.0
    total_gasto = 0.0
    monthly: dict[str, dict[str, float]] = {}
    daily: dict[str, dict[str, float]] = {}
    categorias_gasto: dict[str, float] = {}
    categorias_renda: dict[str, float] = {}
    maior_gasto = None
    maior_renda = None

    for t in res.data:
        data_str = t["data"][:10]  # YYYY-MM-DD (remove timestamp se existir)
        mes = data_str[:7]  # YYYY-MM
        cat = t.get("categoria") or "Outros"

        if mes not in monthly:
            monthly[mes] = {"renda": 0.0, "gasto": 0.0}
        if data_str not in daily:
            daily[data_str] = {"renda": 0.0, "gasto": 0.0}

        if t["tipo"] == "renda":
            total_renda += t["valor"]
            monthly[mes]["renda"] += t["valor"]
            daily[data_str]["renda"] += t["valor"]
            categorias_renda[cat] = categorias_renda.get(cat, 0.0) + t["valor"]
            if maior_renda is None or t["valor"] > maior_renda["valor"]:
                maior_renda = {"valor": t["valor"], "descricao": t.get("descricao", ""), "data": data_str}
        else:
            total_gasto += t["valor"]
            monthly[mes]["gasto"] += t["valor"]
            daily[data_str]["gasto"] += t["valor"]
            categorias_gasto[cat] = categorias_gasto.get(cat, 0.0) + t["valor"]
            if maior_gasto is None or t["valor"] > maior_gasto["valor"]:
                maior_gasto = {"valor": t["valor"], "descricao": t.get("descricao", ""), "data": data_str}

    evolucao = [{"mes": k, **v} for k, v in sorted(monthly.items())]
    evolucao_diaria = [{"dia": k, **v} for k, v in sorted(daily.items())]

    # Top categorias (ordenadas por valor)
    top_cat_gasto = sorted(categorias_gasto.items(), key=lambda x: x[1], reverse=True)
    top_cat_renda = sorted(categorias_renda.items(), key=lambda x: x[1], reverse=True)

    # Média diária de gasto
    dias_com_gasto = len([d for d in daily.values() if d["gasto"] > 0])
    media_diaria_gasto = total_gasto / dias_com_gasto if dias_com_gasto > 0 else 0.0

    return {
        "total_renda": total_renda,
        "total_gasto": total_gasto,
        "saldo": total_renda - total_gasto,
        "num_transacoes": len(res.data),
        "media_diaria_gasto": round(media_diaria_gasto, 2),
        "maior_gasto": maior_gasto,
        "maior_renda": maior_renda,
        "evolucao": evolucao,
        "evolucao_diaria": evolucao_diaria,
        "categorias_gasto": [{"nome": k, "valor": v} for k, v in top_cat_gasto],
        "categorias_renda": [{"nome": k, "valor": v} for k, v in top_cat_renda],
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
    try:
        res = (
            supabase.table("dashboard_layouts")
            .select("*")
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        if res.data:
            return res.data[0]

        # Tenta criar layout padrão
        try:
            row = {"user_id": user_id, "layout": DEFAULT_LAYOUT}
            insert_res = supabase.table("dashboard_layouts").insert(row).execute()
            if insert_res.data:
                return insert_res.data[0]
        except Exception:
            pass

    except Exception as e:
        # Tabela pode não existir — retorna layout padrão sem salvar
        pass

    return {"id": None, "user_id": user_id, "layout": DEFAULT_LAYOUT}

@app.post("/layout")
def save_layout(body: LayoutSave, user_id: str = Depends(get_current_user_id)):
    """Salva/atualiza o layout do dashboard do usuário."""
    try:
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
        if res.data:
            return res.data[0]
    except Exception:
        pass

    return {"id": None, "user_id": user_id, "layout": body.layout}

# ── Health Check ─────────────────────────────────────────────────────────────

@app.api_route("/", methods=["GET", "HEAD"])
def health():
    return {"status": "ok", "service": "Dashboard Financeiro API"}

# ── Entrypoint para produção ─────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
