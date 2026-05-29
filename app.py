import base64
import json
import logging
import os
import sqlite3
import uuid
from datetime import datetime
from functools import wraps
from urllib.parse import quote

from dotenv import load_dotenv
from flask import (
    Flask, abort, flash, g, jsonify, redirect, render_template,
    request, send_from_directory, session, url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

# Carrega variáveis de .env (se existir) antes de qualquer config
load_dotenv()

# ---------------------------------------------------------------------------
# Configuração
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# DB_PATH e UPLOAD_DIR podem apontar para um disco persistente via env
# (recomendado em produção / VPS para sobreviver a redeploys).
DB_PATH = os.environ.get("SEBO_DB_PATH", os.path.join(BASE_DIR, "sebo_store.db"))
UPLOAD_DIR = os.environ.get("SEBO_UPLOAD_DIR", os.path.join(BASE_DIR, "static", "uploads"))
ALLOWED_IMAGE_EXT = {"png", "jpg", "jpeg", "webp", "gif"}
MAX_IMAGE_BYTES = 5 * 1024 * 1024  # 5 MB

# Número do WhatsApp do vendedor (formato internacional, só dígitos)
WHATSAPP_NUMBER = os.environ.get("SEBO_WHATSAPP", "5592993280966")
STORE_NAME = os.environ.get("SEBO_STORE_NAME", "Sebo Store")

# OpenAI — usado para identificar livros pela capa
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

GENRES = [
    "Romance", "Ficção Científica", "Fantasia", "Suspense", "Terror",
    "Biografia", "História", "Autoajuda", "Infantil", "Juvenil",
    "Técnico", "Religião", "Poesia", "Quadrinhos", "Outro",
]

# Coleções curadas: o admin marca um livro como pertencente a uma destas.
# Cada entrada é (slug, rótulo exibido).
COLLECTIONS = [
    ("classicos",       "Nossa Coleção de Clássicos"),
    ("antes-de-morrer", "Livros para Ler Antes de Morrer"),
    ("indicacao",       "Indicações da Semana"),
]
COLLECTION_SLUGS = {slug for slug, _ in COLLECTIONS}

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SEBO_SECRET", "troque-esta-chave-em-producao")
app.config["MAX_CONTENT_LENGTH"] = MAX_IMAGE_BYTES

os.makedirs(UPLOAD_DIR, exist_ok=True)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("sebo")


# ---------------------------------------------------------------------------
# Integração OpenAI (identificação de livro pela capa)
# ---------------------------------------------------------------------------
_openai_client = None


def get_openai_client():
    """Lazy init para não quebrar a app caso a chave não esteja definida."""
    global _openai_client
    if not OPENAI_API_KEY:
        return None
    if _openai_client is None:
        from openai import OpenAI  # import local pra startup rápido
        _openai_client = OpenAI(api_key=OPENAI_API_KEY)
    return _openai_client


def _genres_list_str() -> str:
    return ", ".join(GENRES)


def ai_identify_book(image_bytes: bytes, mime_type: str) -> dict:
    """
    Tenta identificar o livro a partir da imagem da capa.
    Retorna sempre um dict com a chave 'identified' (bool) e, se True,
    title/author/genre/description.
    """
    client = get_openai_client()
    if client is None:
        return {"identified": False, "error": "OPENAI_API_KEY não configurada."}

    b64 = base64.b64encode(image_bytes).decode("ascii")
    data_url = f"data:{mime_type};base64,{b64}"

    system = (
        "Você é um especialista em catalogar livros para uma livraria/sebo brasileiro. "
        "Você recebe a foto da capa de um livro e deve identificá-lo. "
        "Responda SEMPRE em português do Brasil. "
        "Se você reconhecer o livro com confiança razoável, devolva os dados. "
        "Se a capa estiver ilegível, cortada, sem informação suficiente, ou se você "
        "não tiver certeza de qual livro é, devolva identified=false. "
        f"O campo 'genre' DEVE ser exatamente um destes valores: {_genres_list_str()}. "
        "O campo 'description' deve ser uma sinopse curta (2 a 4 frases) do livro, "
        "sem dar spoilers grandes. NÃO invente livros que você não conhece."
    )

    user_text = (
        "Identifique este livro pela capa e devolva JSON no formato:\n"
        '{"identified": true, "title": "...", "author": "...", '
        '"genre": "...", "description": "..."}\n'
        'ou {"identified": false, "reason": "motivo curto"} se não tiver certeza.'
    )

    try:
        resp = client.chat.completions.create(
            model=OPENAI_MODEL,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": [
                    {"type": "text", "text": user_text},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ]},
            ],
            max_tokens=500,
            temperature=0.2,
        )
        content = resp.choices[0].message.content or "{}"
        data = json.loads(content)
    except Exception as e:
        logger.exception("Erro chamando OpenAI (identify)")
        return {"identified": False, "error": f"Erro ao chamar a IA: {e}"}

    if not data.get("identified"):
        return {"identified": False, "reason": data.get("reason", "")}

    # Normaliza o gênero pra um dos valores conhecidos (case-insensitive)
    g_in = (data.get("genre") or "").strip()
    genre = next((g for g in GENRES if g.lower() == g_in.lower()), None) or "Outro"

    return {
        "identified": True,
        "title": (data.get("title") or "").strip(),
        "author": (data.get("author") or "").strip(),
        "genre": genre,
        "description": (data.get("description") or "").strip(),
    }


def ai_complete_book(title: str, author: str) -> dict:
    """
    Dado título e autor, devolve gênero (da lista) e descrição (sinopse).
    """
    client = get_openai_client()
    if client is None:
        return {"ok": False, "error": "OPENAI_API_KEY não configurada."}

    if not title.strip() or not author.strip():
        return {"ok": False, "error": "Informe título e autor."}

    system = (
        "Você cataloga livros para uma livraria/sebo brasileiro. "
        "Dado um título e autor, devolva o gênero e uma sinopse curta em português. "
        f"O campo 'genre' DEVE ser exatamente um destes valores: {_genres_list_str()}. "
        "A 'description' deve ter 2 a 4 frases, sem spoilers grandes. "
        "Se você não conhecer este livro, responda com seu melhor palpite a partir do título."
    )
    user = (
        f"Título: {title}\nAutor: {author}\n\n"
        'Devolva JSON: {"genre": "...", "description": "..."}'
    )

    try:
        resp = client.chat.completions.create(
            model=OPENAI_MODEL,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_tokens=400,
            temperature=0.3,
        )
        data = json.loads(resp.choices[0].message.content or "{}")
    except Exception as e:
        logger.exception("Erro chamando OpenAI (complete)")
        return {"ok": False, "error": f"Erro ao chamar a IA: {e}"}

    g_in = (data.get("genre") or "").strip()
    genre = next((g for g in GENRES if g.lower() == g_in.lower()), None) or "Outro"
    return {
        "ok": True,
        "genre": genre,
        "description": (data.get("description") or "").strip(),
    }


# ---------------------------------------------------------------------------
# Banco de dados
# ---------------------------------------------------------------------------
def get_db():
    if "db" not in g:
        # timeout faz a conexão aguardar o lock liberar em vez de falhar na hora
        conn = sqlite3.connect(DB_PATH, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        g.db = conn
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    conn = sqlite3.connect(DB_PATH, timeout=15)
    # WAL melhora concorrência de leitura/escrita (vários workers do gunicorn)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS books (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            author TEXT NOT NULL,
            genre TEXT NOT NULL,
            price REAL NOT NULL,
            description TEXT DEFAULT '',
            image_filename TEXT,
            stock INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_name TEXT,
            items_json TEXT NOT NULL,
            total REAL NOT NULL,
            status TEXT NOT NULL DEFAULT 'pendente',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS admins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL
        );
        """
    )
    # Migrações leves e idempotentes: adiciona colunas que talvez não existam
    existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(books)").fetchall()}
    if "is_featured" not in existing_cols:
        conn.execute("ALTER TABLE books ADD COLUMN is_featured INTEGER NOT NULL DEFAULT 0")
    if "collection" not in existing_cols:
        conn.execute("ALTER TABLE books ADD COLUMN collection TEXT")

    # Cria admin padrão se nenhum existir
    cur = conn.execute("SELECT COUNT(*) AS c FROM admins")
    if cur.fetchone()[0] == 0:
        conn.execute(
            "INSERT INTO admins (username, password_hash) VALUES (?, ?)",
            ("admin", generate_password_hash("admin123")),
        )
        print(">>> Admin padrão criado: usuário 'admin' / senha 'admin123'")
        print(">>> Altere a senha imediatamente em produção.")
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_IMAGE_EXT


def save_upload(file_storage):
    """Salva imagem enviada e devolve o nome do arquivo, ou None."""
    if not file_storage or not file_storage.filename:
        return None
    if not allowed_file(file_storage.filename):
        return None
    ext = file_storage.filename.rsplit(".", 1)[1].lower()
    new_name = f"{uuid.uuid4().hex}.{ext}"
    file_storage.save(os.path.join(UPLOAD_DIR, new_name))
    return new_name


def delete_upload(filename):
    if not filename:
        return
    path = os.path.join(UPLOAD_DIR, filename)
    if os.path.isfile(path):
        try:
            os.remove(path)
        except OSError:
            pass


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("admin_id"):
            flash("Faça login para acessar essa área.", "warning")
            return redirect(url_for("admin_login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def parse_price(value):
    if value is None:
        raise ValueError("Preço é obrigatório.")
    value = str(value).strip().replace(",", ".")
    try:
        price = float(value)
    except ValueError as exc:
        raise ValueError("Preço inválido.") from exc
    if price < 0:
        raise ValueError("Preço não pode ser negativo.")
    return round(price, 2)


def parse_stock(value):
    try:
        stock = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Estoque inválido.") from exc
    if stock < 0:
        raise ValueError("Estoque não pode ser negativo.")
    return stock


def format_brl(value: float) -> str:
    return f"R$ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


@app.context_processor
def inject_globals():
    return {
        "STORE_NAME": STORE_NAME,
        "GENRES": GENRES,
        "COLLECTIONS": COLLECTIONS,
        "format_brl": format_brl,
        "current_year": datetime.now().year,
        "AI_ENABLED": bool(OPENAI_API_KEY),
    }


# ---------------------------------------------------------------------------
# Rotas públicas — home, catálogo, carrinho
# ---------------------------------------------------------------------------
def _fetch(sql: str, params=()):
    return get_db().execute(sql, params).fetchall()


def section_novelties(limit=12):
    return _fetch(
        "SELECT * FROM books WHERE stock > 0 ORDER BY created_at DESC LIMIT ?",
        (limit,),
    )


def section_by_genre(genre: str, limit=12):
    return _fetch(
        "SELECT * FROM books WHERE genre = ? AND stock > 0 ORDER BY created_at DESC LIMIT ?",
        (genre, limit),
    )


def section_by_collection(slug: str, limit=12):
    return _fetch(
        "SELECT * FROM books WHERE collection = ? AND stock > 0 ORDER BY created_at DESC LIMIT ?",
        (slug, limit),
    )


def section_featured(limit=3):
    return _fetch(
        "SELECT * FROM books WHERE is_featured = 1 AND stock > 0 ORDER BY RANDOM() LIMIT ?",
        (limit,),
    )


def genres_with_books(min_books=3):
    """Retorna lista de gêneros que têm pelo menos min_books livros em estoque."""
    rows = _fetch(
        "SELECT genre, COUNT(*) AS c FROM books WHERE stock > 0 GROUP BY genre HAVING c >= ?",
        (min_books,),
    )
    return [r["genre"] for r in rows]


@app.route("/")
def index():
    """Home com hero + carrosséis temáticos + destaques rotativos."""
    sections = []  # lista ordenada: [{kind, title, slug, books}, ...]

    # 1. Novidades sempre primeiro
    novelties = section_novelties()
    if novelties:
        sections.append({"kind": "carousel", "title": "Novidades", "slug": "novidades", "books": novelties})

    # 2. Coleção de Clássicos
    classicos = section_by_collection("classicos")
    if classicos:
        sections.append({"kind": "carousel", "title": "Nossa Coleção de Clássicos", "slug": "classicos", "books": classicos})

    # 3. Carrossel automático por gênero (Fantasia primeiro se existir, depois outros)
    available_genres = genres_with_books()
    # Ordena pra "Fantasia" vir primeiro se existir (a usuária citou explicitamente)
    available_genres.sort(key=lambda g: (0 if g == "Fantasia" else 1, g))
    for g in available_genres[:3]:  # limita pra não ficar enorme
        books = section_by_genre(g)
        if books:
            sections.append({"kind": "carousel", "title": f"Livros de {g}", "slug": f"genero-{g.lower()}", "books": books})

    # 4. Indicações da Semana
    indicacoes = section_by_collection("indicacao")
    if indicacoes:
        sections.append({"kind": "carousel", "title": "Indicações da Semana", "slug": "indicacao", "books": indicacoes})

    # 5. Para Ler Antes de Morrer
    antes = section_by_collection("antes-de-morrer")
    if antes:
        sections.append({"kind": "carousel", "title": "Livros para Ler Antes de Morrer", "slug": "antes-de-morrer", "books": antes})

    # Intercala os destaques entre os carrosséis
    featured = section_featured(limit=3)
    final_sections = []
    if sections and featured:
        # Insere o bloco de destaque depois do 1º carrossel (e antes do último, se houver muitos)
        # Estratégia simples: 1 bloco de destaque entre carrosséis, posicionado no meio
        mid = max(1, len(sections) // 2)
        for i, sec in enumerate(sections):
            final_sections.append(sec)
            if i == 0 and len(sections) > 1:
                final_sections.append({"kind": "spotlight", "books": featured})
            elif i == mid and len(sections) > 3:
                # Se houver muitas seções, intercala um 2º bloco no meio. Usa os mesmos featured (gira automático no front).
                final_sections.append({"kind": "spotlight", "books": featured})
    else:
        final_sections = sections
        if featured and not sections:
            final_sections.insert(0, {"kind": "spotlight", "books": featured})

    return render_template("home.html", sections=final_sections, has_books=bool(sections))


@app.route("/catalogo")
def catalog():
    q = request.args.get("q", "").strip()
    genre = request.args.get("genero", "").strip()

    sql = "SELECT * FROM books WHERE 1=1"
    params = []
    if q:
        sql += " AND (title LIKE ? OR author LIKE ? OR description LIKE ?)"
        like = f"%{q}%"
        params.extend([like, like, like])
    if genre:
        sql += " AND genre = ?"
        params.append(genre)
    sql += " ORDER BY created_at DESC"
    books = _fetch(sql, params)
    return render_template(
        "catalog.html",
        books=books,
        q=q,
        selected_genre=genre,
    )


def get_similar_books(book_id: int, genre: str, author: str, limit: int = 6):
    """
    Recomenda livros parecidos:
      relevância 3 = mesmo gênero E mesmo autor
      relevância 2 = mesmo gênero
      relevância 1 = mesmo autor
      relevância 0 = qualquer outro
    Filtra o próprio livro e itens sem estoque. RANDOM() varia a vitrine entre visitas.
    """
    db = get_db()
    sql = """
        SELECT *,
            CASE
                WHEN genre = ? AND author = ? THEN 3
                WHEN genre = ? THEN 2
                WHEN author = ? THEN 1
                ELSE 0
            END AS relevance
        FROM books
        WHERE id != ? AND stock > 0
        ORDER BY relevance DESC, RANDOM()
        LIMIT ?
    """
    return db.execute(sql, (genre, author, genre, author, book_id, limit)).fetchall()


@app.route("/livro/<int:book_id>")
def book_detail(book_id):
    db = get_db()
    book = db.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()
    if book is None:
        abort(404)
    similar = get_similar_books(book_id, book["genre"], book["author"])
    return render_template("book_detail.html", book=book, similar=similar)


@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    """Serve as imagens enviadas. Uma rota dedicada (em vez de static/) permite
    que UPLOAD_DIR aponte para um disco/volume persistente em produção."""
    return send_from_directory(UPLOAD_DIR, filename)


@app.route("/carrinho")
def cart():
    return render_template("cart.html", whatsapp_number=WHATSAPP_NUMBER)


@app.route("/api/books")
def api_books():
    """Endpoint usado pelo carrinho para revalidar os itens (preço/estoque atual)."""
    ids = request.args.get("ids", "")
    ids = [int(x) for x in ids.split(",") if x.strip().isdigit()]
    if not ids:
        return jsonify([])
    placeholders = ",".join("?" * len(ids))
    db = get_db()
    rows = db.execute(
        f"SELECT id, title, author, price, stock, image_filename FROM books WHERE id IN ({placeholders})",
        ids,
    ).fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/checkout", methods=["POST"])
def api_checkout():
    """Salva o pedido no banco e devolve a URL do WhatsApp com a mensagem pronta."""
    data = request.get_json(silent=True) or {}
    customer_name = (data.get("customer_name") or "").strip()
    items_in = data.get("items") or []

    if not items_in:
        return jsonify({"error": "Carrinho vazio."}), 400

    db = get_db()
    ids = [int(i.get("id")) for i in items_in if str(i.get("id", "")).isdigit()]
    if not ids:
        return jsonify({"error": "Itens inválidos."}), 400

    placeholders = ",".join("?" * len(ids))
    rows = db.execute(
        f"SELECT id, title, author, price, stock FROM books WHERE id IN ({placeholders})",
        ids,
    ).fetchall()
    by_id = {r["id"]: r for r in rows}

    saved_items = []
    total = 0.0
    for item in items_in:
        try:
            book_id = int(item.get("id"))
            qty = max(1, int(item.get("qty", 1)))
        except (TypeError, ValueError):
            continue
        book = by_id.get(book_id)
        if book is None:
            continue
        subtotal = round(book["price"] * qty, 2)
        total += subtotal
        saved_items.append({
            "id": book_id,
            "title": book["title"],
            "author": book["author"],
            "price": book["price"],
            "qty": qty,
            "subtotal": subtotal,
        })

    if not saved_items:
        return jsonify({"error": "Nenhum dos livros do carrinho está disponível."}), 400

    total = round(total, 2)
    db.execute(
        "INSERT INTO orders (customer_name, items_json, total) VALUES (?, ?, ?)",
        (customer_name or None, json.dumps(saved_items, ensure_ascii=False), total),
    )
    order_id = db.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
    db.commit()

    # Monta a mensagem para o WhatsApp
    lines = [f"Olá, {STORE_NAME}! Gostaria de comprar:", ""]
    for i, it in enumerate(saved_items, start=1):
        lines.append(
            f"{i}. *{it['title']}* — {it['author']}\n"
            f"   {it['qty']}x {format_brl(it['price'])} = {format_brl(it['subtotal'])}"
        )
    lines.append("")
    lines.append(f"*Total: {format_brl(total)}*")
    lines.append(f"Pedido #{order_id}")
    if customer_name:
        lines.append(f"Nome: {customer_name}")
    message = "\n".join(lines)
    whatsapp_url = f"https://wa.me/{WHATSAPP_NUMBER}?text={quote(message)}"

    return jsonify({"order_id": order_id, "whatsapp_url": whatsapp_url})


# ---------------------------------------------------------------------------
# Admin
# ---------------------------------------------------------------------------
@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        db = get_db()
        row = db.execute("SELECT * FROM admins WHERE username = ?", (username,)).fetchone()
        if row and check_password_hash(row["password_hash"], password):
            session.clear()
            session["admin_id"] = row["id"]
            session["admin_username"] = row["username"]
            flash("Bem-vindo(a)!", "success")
            nxt = request.args.get("next") or url_for("admin_dashboard")
            return redirect(nxt)
        flash("Usuário ou senha inválidos.", "error")
    return render_template("admin/login.html")


@app.route("/admin/logout")
def admin_logout():
    session.clear()
    flash("Você saiu.", "success")
    return redirect(url_for("admin_login"))


@app.route("/admin")
@login_required
def admin_dashboard():
    db = get_db()
    total_books = db.execute("SELECT COUNT(*) AS c FROM books").fetchone()["c"]
    total_orders = db.execute("SELECT COUNT(*) AS c FROM orders").fetchone()["c"]
    pending_orders = db.execute(
        "SELECT COUNT(*) AS c FROM orders WHERE status = 'pendente'"
    ).fetchone()["c"]
    revenue = db.execute(
        "SELECT COALESCE(SUM(total), 0) AS s FROM orders WHERE status = 'concluido'"
    ).fetchone()["s"]
    recent_orders = db.execute(
        "SELECT * FROM orders ORDER BY created_at DESC LIMIT 5"
    ).fetchall()
    return render_template(
        "admin/dashboard.html",
        total_books=total_books,
        total_orders=total_orders,
        pending_orders=pending_orders,
        revenue=revenue,
        recent_orders=recent_orders,
    )


@app.route("/admin/livros")
@login_required
def admin_books():
    db = get_db()
    books = db.execute("SELECT * FROM books ORDER BY created_at DESC").fetchall()
    return render_template("admin/books.html", books=books)


@app.route("/admin/api/identify-book", methods=["POST"])
@login_required
def admin_api_identify_book():
    """Recebe a imagem da capa, devolve dados do livro identificado (ou identified=false)."""
    file = request.files.get("image")
    if not file or not file.filename:
        return jsonify({"identified": False, "error": "Envie uma imagem."}), 400
    if not allowed_file(file.filename):
        return jsonify({"identified": False, "error": "Formato de imagem inválido."}), 400

    data = file.read()
    if not data:
        return jsonify({"identified": False, "error": "Arquivo vazio."}), 400

    mime = file.mimetype or "image/jpeg"
    result = ai_identify_book(data, mime)
    status = 200 if result.get("identified") or "error" not in result else 200
    return jsonify(result), status


@app.route("/admin/api/complete-book", methods=["POST"])
@login_required
def admin_api_complete_book():
    """Recebe título e autor; devolve gênero + descrição sugeridos pela IA."""
    body = request.get_json(silent=True) or {}
    title = (body.get("title") or "").strip()
    author = (body.get("author") or "").strip()
    result = ai_complete_book(title, author)
    status = 200 if result.get("ok") else 400
    return jsonify(result), status


@app.route("/admin/livros/novo", methods=["GET", "POST"])
@login_required
def admin_book_new():
    if request.method == "POST":
        try:
            title = request.form.get("title", "").strip()
            author = request.form.get("author", "").strip()
            genre = request.form.get("genre", "").strip()
            description = request.form.get("description", "").strip()
            price = parse_price(request.form.get("price"))
            stock = parse_stock(request.form.get("stock", "1"))
            is_featured = 1 if request.form.get("is_featured") == "1" else 0
            collection = request.form.get("collection", "").strip()
            if collection and collection not in COLLECTION_SLUGS:
                collection = ""
            if not title or not author or not genre:
                raise ValueError("Título, autor e gênero são obrigatórios.")
            image_name = save_upload(request.files.get("image"))
            db = get_db()
            db.execute(
                """INSERT INTO books (title, author, genre, price, description,
                                      image_filename, stock, is_featured, collection)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (title, author, genre, price, description, image_name, stock,
                 is_featured, collection or None),
            )
            db.commit()
            flash("Livro adicionado.", "success")
            return redirect(url_for("admin_books"))
        except ValueError as e:
            flash(str(e), "error")
    return render_template("admin/book_form.html", book=None)


@app.route("/admin/livros/<int:book_id>/editar", methods=["GET", "POST"])
@login_required
def admin_book_edit(book_id):
    db = get_db()
    book = db.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()
    if book is None:
        abort(404)
    if request.method == "POST":
        try:
            title = request.form.get("title", "").strip()
            author = request.form.get("author", "").strip()
            genre = request.form.get("genre", "").strip()
            description = request.form.get("description", "").strip()
            price = parse_price(request.form.get("price"))
            stock = parse_stock(request.form.get("stock", "0"))
            is_featured = 1 if request.form.get("is_featured") == "1" else 0
            collection = request.form.get("collection", "").strip()
            if collection and collection not in COLLECTION_SLUGS:
                collection = ""
            if not title or not author or not genre:
                raise ValueError("Título, autor e gênero são obrigatórios.")

            image_name = book["image_filename"]
            new_file = request.files.get("image")
            if new_file and new_file.filename:
                uploaded = save_upload(new_file)
                if uploaded:
                    delete_upload(image_name)
                    image_name = uploaded
            if request.form.get("remove_image") == "1":
                delete_upload(image_name)
                image_name = None

            db.execute(
                """UPDATE books SET title=?, author=?, genre=?, price=?,
                          description=?, image_filename=?, stock=?,
                          is_featured=?, collection=? WHERE id=?""",
                (title, author, genre, price, description, image_name, stock,
                 is_featured, collection or None, book_id),
            )
            db.commit()
            flash("Livro atualizado.", "success")
            return redirect(url_for("admin_books"))
        except ValueError as e:
            flash(str(e), "error")
    return render_template("admin/book_form.html", book=book)


@app.route("/admin/livros/<int:book_id>/remover", methods=["POST"])
@login_required
def admin_book_delete(book_id):
    db = get_db()
    book = db.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()
    if book is None:
        abort(404)
    delete_upload(book["image_filename"])
    db.execute("DELETE FROM books WHERE id = ?", (book_id,))
    db.commit()
    flash("Livro removido.", "success")
    return redirect(url_for("admin_books"))


@app.route("/admin/pedidos")
@login_required
def admin_orders():
    status_filter = request.args.get("status", "").strip()
    db = get_db()
    sql = "SELECT * FROM orders"
    params = []
    if status_filter in ("pendente", "concluido", "cancelado"):
        sql += " WHERE status = ?"
        params.append(status_filter)
    sql += " ORDER BY created_at DESC"
    rows = db.execute(sql, params).fetchall()
    orders = []
    for r in rows:
        d = dict(r)
        try:
            d["books"] = json.loads(d["items_json"])
        except (TypeError, ValueError):
            d["books"] = []
        orders.append(d)
    return render_template("admin/orders.html", orders=orders, status_filter=status_filter)


@app.route("/admin/pedidos/<int:order_id>/status", methods=["POST"])
@login_required
def admin_order_status(order_id):
    new_status = request.form.get("status", "").strip()
    if new_status not in ("pendente", "concluido", "cancelado"):
        flash("Status inválido.", "error")
        return redirect(url_for("admin_orders"))
    db = get_db()
    db.execute("UPDATE orders SET status = ? WHERE id = ?", (new_status, order_id))
    db.commit()
    flash("Pedido atualizado.", "success")
    return redirect(url_for("admin_orders"))


@app.route("/admin/pedidos/<int:order_id>/remover", methods=["POST"])
@login_required
def admin_order_delete(order_id):
    db = get_db()
    db.execute("DELETE FROM orders WHERE id = ?", (order_id,))
    db.commit()
    flash("Pedido removido.", "success")
    return redirect(url_for("admin_orders"))


@app.route("/admin/senha", methods=["GET", "POST"])
@login_required
def admin_change_password():
    if request.method == "POST":
        current = request.form.get("current_password", "")
        new = request.form.get("new_password", "")
        confirm = request.form.get("confirm_password", "")
        db = get_db()
        admin = db.execute(
            "SELECT * FROM admins WHERE id = ?", (session["admin_id"],)
        ).fetchone()
        if not check_password_hash(admin["password_hash"], current):
            flash("Senha atual incorreta.", "error")
        elif len(new) < 6:
            flash("A nova senha deve ter pelo menos 6 caracteres.", "error")
        elif new != confirm:
            flash("Confirmação não confere.", "error")
        else:
            db.execute(
                "UPDATE admins SET password_hash = ? WHERE id = ?",
                (generate_password_hash(new), session["admin_id"]),
            )
            db.commit()
            flash("Senha alterada.", "success")
            return redirect(url_for("admin_dashboard"))
    return render_template("admin/change_password.html")


# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------
@app.errorhandler(404)
def not_found(_e):
    return render_template("404.html"), 404


@app.errorhandler(413)
def too_large(_e):
    flash("Arquivo muito grande (máx. 5 MB).", "error")
    return redirect(request.referrer or url_for("index")), 302


# ---------------------------------------------------------------------------
# Inicialização do banco
# ---------------------------------------------------------------------------
# Roda no import do módulo para que funcione tanto com `python3 app.py` (dev)
# quanto sob um servidor WSGI como o gunicorn (produção), que não executa o
# bloco `if __name__ == "__main__"`. init_db() é idempotente.
init_db()

if app.config["SECRET_KEY"] == "troque-esta-chave-em-producao":
    logger.warning(
        "SECRET_KEY usando valor padrão! Defina a variável de ambiente "
        "SEBO_SECRET com um valor aleatório longo em produção."
    )


# ---------------------------------------------------------------------------
# Entry point (desenvolvimento local)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Em produção use gunicorn: `gunicorn --bind 0.0.0.0:8000 app:app`
    debug = os.environ.get("FLASK_DEBUG", "1") == "1"
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")), debug=debug)
