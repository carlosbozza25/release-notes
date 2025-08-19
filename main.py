# app.py
# Sistema de cadastro de atualizações de sistema (Produtos, Releases e Itens)
# Stack: Flask + SQLAlchemy + SQLite + Bootstrap 5 (CDN)
# Execução: python app.py  (acessar http://127.0.0.1:5000)

from __future__ import annotations
from datetime import date
import re

from flask import (
    Flask,
    request,
    redirect,
    url_for,
    flash,
    render_template_string,
)
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func, UniqueConstraint

# -----------------------
# Configuração da aplicação
# -----------------------
app = Flask(__name__)
import os

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///releases.db")
# Render/Heroku usam prefixo postgres://; o SQLAlchemy espera postgresql+psycopg2://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg://", 1)
elif DATABASE_URL.startswith("postgresql://") and "+psycopg" not in DATABASE_URL and "+psycopg2" not in DATABASE_URL:
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URL
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret")


db = SQLAlchemy(app)


# -----------------------
# Modelos de dados
# -----------------------
class Product(db.Model):
    __tablename__ = "product"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    code = db.Column(db.String(60), nullable=False)
    description = db.Column(db.Text, nullable=True)
    active = db.Column(db.Boolean, nullable=False, default=True)

    __table_args__ = (
        UniqueConstraint("name", name="uq_product_name"),
        UniqueConstraint("code", name="uq_product_code"),
    )

    items = db.relationship("ReleaseItem", back_populates="product", cascade="all, delete")

    def __repr__(self):
        return f"<Product {self.code}:{self.name}>"


class Release(db.Model):
    __tablename__ = "release"
    id = db.Column(db.Integer, primary_key=True)
    # Data planejada da atualização
    release_date = db.Column(db.Date, nullable=False, index=True)
    title = db.Column(db.String(180), nullable=False)
    notes = db.Column(db.Text, nullable=True)

    items = db.relationship("ReleaseItem", back_populates="release", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Release {self.id} {self.release_date.isoformat()}: {self.title[:30]}>"


class ReleaseItem(db.Model):
    __tablename__ = "release_item"
    id = db.Column(db.Integer, primary_key=True)
    release_id = db.Column(db.Integer, db.ForeignKey("release.id", ondelete="CASCADE"), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey("product.id", ondelete="SET NULL"))

    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    clickup_url = db.Column(db.String(300), nullable=True)

    # Status do item: Planejado, Em andamento, Entregue, Cancelado
    status = db.Column(db.String(20), nullable=False, default="Planejado")

    release = db.relationship("Release", back_populates="items")
    product = db.relationship("Product", back_populates="items")

    mrs = db.relationship("MergeRequest", back_populates="item", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<ReleaseItem {self.id} {self.title[:20]}>"


class MergeRequest(db.Model):
    __tablename__ = "merge_request"
    id = db.Column(db.Integer, primary_key=True)
    item_id = db.Column(db.Integer, db.ForeignKey("release_item.id", ondelete="CASCADE"), nullable=False, index=True)
    url = db.Column(db.String(300), nullable=False)
    repo = db.Column(db.String(120), nullable=True)
    iid = db.Column(db.String(60), nullable=True)  # ex.: !123

    item = db.relationship("ReleaseItem", back_populates="mrs")

    def __repr__(self):
        return f"<MR {self.url}>"


# -----------------------
# Helpers
# -----------------------
DATE_BR_RE = re.compile(r"^(\d{2})/(\d{2})/(\d{4})$")


def parse_date_br(value: str) -> date:
    """Converte dd/mm/yyyy -> date, lança ValueError em caso de formato inválido."""
    if not value:
        raise ValueError("Data é obrigatória.")
    m = DATE_BR_RE.match(value.strip())
    if not m:
        raise ValueError("Use o formato dd/mm/aaaa.")
    d, mth, y = map(int, m.groups())
    return date(y, mth, d)


def to_date_br(d: date | None) -> str:
    return d.strftime("%d/%m/%Y") if d else ""


def norm_url(u: str | None) -> str | None:
    if not u:
        return None
    u = u.strip()
    if not u:
        return None
    if not (u.startswith("http://") or u.startswith("https://")):
        u = "https://" + u
    return u[:300]


# -----------------------
# Layout base (Jinja via render_template_string)
# -----------------------
BASE_HTML = r"""
{% set brand = 'Atualizações de Sistema' %}
<!doctype html>
<html lang="pt-br" data-bs-theme="dark">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{{ page_title or brand }}</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
    <link href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.min.css" rel="stylesheet">
    <style>
      .container-narrow { max-width: 1080px; }
      .form-help { font-size: .85rem; opacity:.8 }
      a.truncate { max-width: 520px; display:inline-block; white-space:nowrap; overflow:hidden; text-overflow:ellipsis }
      .badge-status { font-weight:600 }
      .theme-toggle { cursor:pointer }

      /* ====== UX upgrades ====== */
      .page-heading{letter-spacing:.2px}
      .note-callout{border-left:4px solid var(--bs-border-color); background:var(--bs-body-bg);}

      /* multi-line clamp */
      .clamp-1{display:-webkit-box;-webkit-line-clamp:1;-webkit-box-orient:vertical;overflow:hidden}
      .clamp-2{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}

      /* Chips (para MRs/links) */
      .chip{display:inline-flex;align-items:center;gap:.4rem;padding:.25rem .55rem;border-radius:9999px;border:1px solid var(--bs-border-color);background:var(--bs-body-bg);font-size:.875rem;position:relative;z-index:2}
      .chip:hover{text-decoration:none;transform:translateY(-1px)}
      /* garante que a stretched-link não bloqueie links internos (MR/ClickUp) */
      .item-card .stretched-link::after{z-index:1}
      .item-card .btn{position:relative;z-index:2}

      /* Cards dos itens */
      .item-card{border:1px solid var(--bs-border-color); border-radius:14px; box-shadow:0 1px 2px rgba(0,0,0,.03)}
      .item-card:hover{box-shadow:0 4px 16px rgba(0,0,0,.08);}

      /* Etiqueta de produto (usa badges do Bootstrap) */
      .product-pill{font-weight:600; letter-spacing:.02em}
    </style>
  </head>
  <body>
    <nav class="navbar navbar-expand-lg bg-body-tertiary border-bottom">
      <div class="container container-narrow">
        <a class="navbar-brand" href="{{ url_for('home') }}">{{ brand }}</a>
        <button class="navbar-toggler" type="button" data-bs-toggle="collapse" data-bs-target="#navbarsExample">
          <span class="navbar-toggler-icon"></span>
        </button>
        <div class="collapse navbar-collapse" id="navbarsExample">
          <ul class="navbar-nav me-auto mb-2 mb-lg-0">
            <li class="nav-item"><a class="nav-link" href="{{ url_for('list_products') }}">Produtos</a></li>
            <li class="nav-item"><a class="nav-link" href="{{ url_for('list_releases') }}">Atualizações</a></li>
          </ul>
          <div class="d-flex align-items-center gap-3">
            <span class="form-text">Tema:</span>
            <button id="toggleTheme" class="btn btn-sm btn-outline-secondary theme-toggle">alternar</button>
          </div>
        </div>
      </div>
    </nav>

    <main class="container container-narrow py-4">
      {% with messages = get_flashed_messages(with_categories=true) %}
        {% if messages %}
          {% for category, message in messages %}
            <div class="alert alert-{{ 'warning' if category == 'error' else category }} alert-dismissible fade show" role="alert">
              {{ message }}
              <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
            </div>
          {% endfor %}
        {% endif %}
      {% endwith %}

      {{ content|safe }}
    </main>

    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"></script>
    <script>
      // Dark/Light toggle usando data-bs-theme
      const btn = document.getElementById('toggleTheme');
      function getTheme(){ return localStorage.getItem('theme') || 'dark' }
      function setTheme(t){ document.documentElement.setAttribute('data-bs-theme', t); localStorage.setItem('theme', t) }
      setTheme(getTheme());
      btn?.addEventListener('click', ()=>{ setTheme(getTheme()==='dark'?'light':'dark') });
    </script>
  </body>
</html>
"""

def render_page(content: str, page_title: str = None, **ctx):
    return render_template_string(BASE_HTML, content=content, page_title=page_title, **ctx)


# -----------------------
# Rotas - Home / Dashboard
# -----------------------
@app.route("/")
def home():
    # Próximas e últimas 5 atualizações
    today = date.today()
    upcoming = (
        Release.query.filter(Release.release_date >= today)
        .order_by(Release.release_date.asc())
        .limit(5)
        .all()
    )
    recent = (
        Release.query.filter(Release.release_date < today)
        .order_by(Release.release_date.desc())
        .limit(5)
        .all()
    )

    content = render_template_string(
        r"""
        <div class="d-flex justify-content-between align-items-center mb-3">
          <h1 class="h4 m-0">Visão geral</h1>
          <a href="{{ url_for('new_release') }}" class="btn btn-primary">Nova atualização</a>
        </div>

        <div class="row g-4">
          <div class="col-md-6">
            <div class="card h-100">
              <div class="card-header">Próximas (5)</div>
              <ul class="list-group list-group-flush">
              {% for r in upcoming %}
                <li class="list-group-item d-flex justify-content-between align-items-center">
                  <div>
                    <div class="fw-semibold">{{ r.title }}</div>
                    <small class="text-secondary">{{ to_date_br(r.release_date) }} • {{ r.items|length }} itens</small>
                  </div>
                  <a class="btn btn-sm btn-outline-primary" href="{{ url_for('view_release', release_id=r.id) }}">abrir</a>
                </li>
              {% else %}
                <li class="list-group-item"><em>Nada planejado</em></li>
              {% endfor %}
              </ul>
            </div>
          </div>

          <div class="col-md-6">
            <div class="card h-100">
              <div class="card-header">Últimas (5)</div>
              <ul class="list-group list-group-flush">
              {% for r in recent %}
                <li class="list-group-item d-flex justify-content-between align-items-center">
                  <div>
                    <div class="fw-semibold">{{ r.title }}</div>
                    <small class="text-secondary">{{ to_date_br(r.release_date) }} • {{ r.items|length }} itens</small>
                  </div>
                  <a class="btn btn-sm btn-outline-secondary" href="{{ url_for('view_release', release_id=r.id) }}">ver</a>
                </li>
              {% else %}
                <li class="list-group-item"><em>Sem histórico</em></li>
              {% endfor %}
              </ul>
            </div>
          </div>
        </div>
        """,
        upcoming=upcoming,
        recent=recent,
        to_date_br=to_date_br,
    )
    return render_page(content, page_title="Visão geral")


# -----------------------
# Rotas - Produtos (CRUD)
# -----------------------
@app.route("/products")
def list_products():
    q = request.args.get("q", "").strip()
    query = Product.query
    if q:
        like = f"%{q}%"
        query = query.filter((Product.name.ilike(like)) | (Product.code.ilike(like)))
    products = query.order_by(Product.active.desc(), Product.name.asc()).all()

    content = render_template_string(
        r"""
        <div class="d-flex justify-content-between align-items-center mb-3">
          <h1 class="h4 m-0">Produtos</h1>
          <a class="btn btn-primary" href="{{ url_for('new_product') }}">Novo produto</a>
        </div>

        <form class="row g-2 mb-3" method="get">
          <div class="col-sm-8 col-md-10"><input class="form-control" name="q" placeholder="Buscar por nome ou código" value="{{ request.args.get('q','') }}"/></div>
          <div class="col-sm-4 col-md-2 d-grid"><button class="btn btn-outline-secondary">Buscar</button></div>
        </form>

        <div class="table-responsive">
          <table class="table align-middle">
            <thead><tr><th>Nome</th><th>Código</th><th>Ativo</th><th></th></tr></thead>
            <tbody>
            {% for p in products %}
              <tr>
                <td class="fw-semibold">{{ p.name }}</td>
                <td>{{ p.code }}</td>
                <td>
                  {% if p.active %}<span class="badge text-bg-success">ativo</span>
                  {% else %}<span class="badge text-bg-secondary">inativo</span>{% endif %}
                </td>
                <td class="text-end">
                  <a class="btn btn-sm btn-outline-secondary" href="{{ url_for('edit_product', product_id=p.id) }}">editar</a>
                  <a class="btn btn-sm btn-outline-danger" href="" data-bs-toggle="modal" data-bs-target="#del{{p.id}}">excluir</a>

                  <div class="modal fade" id="del{{p.id}}" tabindex="-1">
                    <div class="modal-dialog modal-dialog-centered">
                      <div class="modal-content">
                        <div class="modal-header"><h5 class="modal-title">Excluir produto</h5>
                          <button type="button" class="btn-close" data-bs-dismiss="modal"></button></div>
                        <div class="modal-body">Tem certeza que deseja excluir <strong>{{p.name}}</strong>? Esta ação não pode ser desfeita.</div>
                        <div class="modal-footer">
                          <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancelar</button>
                          <a class="btn btn-danger" href="{{ url_for('delete_product', product_id=p.id) }}" onclick="return confirm('Confirmar exclusão?')">Excluir</a>
                        </div>
                      </div>
                    </div>
                  </div>
                </td>
              </tr>
            {% else %}
              <tr><td colspan="4"><em>Nenhum produto encontrado.</em></td></tr>
            {% endfor %}
            </tbody>
          </table>
        </div>
        """,
        products=products,
    )
    return render_page(content, page_title="Produtos")


@app.route("/products/new", methods=["GET", "POST"])
def new_product():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        code = request.form.get("code", "").strip()
        description = request.form.get("description", "").strip() or None
        active = True if request.form.get("active") == "on" else False

        if not name:
            flash("Nome é obrigatório.", "error")
        elif not code:
            flash("Código é obrigatório.", "error")
        else:
            # Validar unicidade
            if Product.query.filter(func.lower(Product.name) == name.lower()).first():
                flash("Já existe um produto com este nome.", "error")
            elif Product.query.filter(func.lower(Product.code) == code.lower()).first():
                flash("Já existe um produto com este código.", "error")
            else:
                p = Product(name=name, code=code, description=description, active=active)
                db.session.add(p)
                db.session.commit()
                flash("Produto criado com sucesso.", "success")
                return redirect(url_for("list_products"))

    content = render_template_string(
        r"""
        <h1 class="h4 mb-3">Novo produto</h1>
        <form method="post" class="vstack gap-3">
          <div>
            <label class="form-label">Nome *</label>
            <input name="name" class="form-control" required>
          </div>
          <div>
            <label class="form-label">Código *</label>
            <input name="code" class="form-control" required>
          </div>
          <div>
            <label class="form-label">Descrição</label>
            <textarea name="description" class="form-control" rows="3"></textarea>
          </div>
          <div class="form-check">
            <input class="form-check-input" type="checkbox" name="active" id="pactive" checked>
            <label class="form-check-label" for="pactive">Ativo</label>
          </div>
          <div class="d-flex gap-2">
            <button class="btn btn-primary">Salvar</button>
            <a class="btn btn-secondary" href="{{ url_for('list_products') }}">Cancelar</a>
          </div>
        </form>
        """,
    )
    return render_page(content, page_title="Novo produto")


@app.route("/products/<int:product_id>/edit", methods=["GET", "POST"])
def edit_product(product_id: int):
    p = Product.query.get_or_404(product_id)
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        code = request.form.get("code", "").strip()
        description = request.form.get("description", "").strip() or None
        active = True if request.form.get("active") == "on" else False

        if not name:
            flash("Nome é obrigatório.", "error")
        elif not code:
            flash("Código é obrigatório.", "error")
        else:
            # Verifica unicidade ignorando o próprio ID
            if Product.query.filter(func.lower(Product.name) == name.lower(), Product.id != p.id).first():
                flash("Já existe um produto com este nome.", "error")
            elif Product.query.filter(func.lower(Product.code) == code.lower(), Product.id != p.id).first():
                flash("Já existe um produto com este código.", "error")
            else:
                p.name = name
                p.code = code
                p.description = description
                p.active = active
                db.session.commit()
                flash("Produto atualizado.", "success")
                return redirect(url_for("list_products"))

    content = render_template_string(
        r"""
        <h1 class="h4 mb-3">Editar produto</h1>
        <form method="post" class="vstack gap-3">
          <div>
            <label class="form-label">Nome *</label>
            <input name="name" class="form-control" value="{{ p.name }}" required>
          </div>
          <div>
            <label class="form-label">Código *</label>
            <input name="code" class="form-control" value="{{ p.code }}" required>
          </div>
          <div>
            <label class="form-label">Descrição</label>
            <textarea name="description" class="form-control" rows="3">{{ p.description or '' }}</textarea>
          </div>
          <div class="form-check">
            <input class="form-check-input" type="checkbox" name="active" id="pactive" {% if p.active %}checked{% endif %}>
            <label class="form-check-label" for="pactive">Ativo</label>
          </div>
          <div class="d-flex gap-2">
            <button class="btn btn-primary">Salvar</button>
            <a class="btn btn-secondary" href="{{ url_for('list_products') }}">Cancelar</a>
          </div>
        </form>
        """,
        p=p,
    )
    return render_page(content, page_title="Editar produto")


@app.route("/products/<int:product_id>/delete")
def delete_product(product_id: int):
    p = Product.query.get_or_404(product_id)
    db.session.delete(p)
    db.session.commit()
    flash("Produto excluído.", "success")
    return redirect(url_for("list_products"))


# -----------------------
# Rotas - Releases (CRUD)
# -----------------------
@app.route("/releases")
def list_releases():
    # Filtros: período e produto
    start = request.args.get("start")
    end = request.args.get("end")
    raw_pid = request.args.get("product_id", "")
    try:
        selected_pid = int(raw_pid) if raw_pid != "" else None
    except ValueError:
        selected_pid = None

    query = Release.query
    if start:
        try:
            d1 = parse_date_br(start)
            query = query.filter(Release.release_date >= d1)
        except ValueError:
            flash("Data inicial inválida.", "error")
    if end:
        try:
            d2 = parse_date_br(end)
            query = query.filter(Release.release_date <= d2)
        except ValueError:
            flash("Data final inválida.", "error")

    releases = query.order_by(Release.release_date.desc()).all()
    products = Product.query.order_by(Product.name.asc()).all()

    # Contagem por release (itens filtrados por produto, se houver)
    def count_items(rel: Release) -> int:
        if selected_pid is None:
            return len(rel.items)
        return sum(1 for it in rel.items if it.product_id == selected_pid)

    content = render_template_string(
        r"""
        <div class="d-flex justify-content-between align-items-center mb-3">
          <h1 class="h4 m-0">Atualizações</h1>
          <a class="btn btn-primary" href="{{ url_for('new_release') }}">Nova atualização</a>
        </div>

        <form class="row gy-2 gx-2 align-items-end mb-3" method="get">
          <div class="col-sm-3">
            <label class="form-label">Início</label>
            <input class="form-control" name="start" placeholder="dd/mm/aaaa" value="{{ request.args.get('start','') }}">
          </div>
          <div class="col-sm-3">
            <label class="form-label">Fim</label>
            <input class="form-control" name="end" placeholder="dd/mm/aaaa" value="{{ request.args.get('end','') }}">
          </div>
          <div class="col-sm-4">
            <label class="form-label">Produto</label>
            <select name="product_id" class="form-select">
              <option value=""  {% if selected_pid is none %}selected{% endif %}>Todos</option>
              {% for p in products %}
                <option value="{{p.id}}" {% if selected_pid == p.id %}selected{% endif %}>{{p.name}}</option>
              {% endfor %}
            </select>
          </div>
          <div class="col-sm-2 d-grid">
            <button class="btn btn-outline-secondary">Filtrar</button>
          </div>
        </form>

        <div class="list-group">
        {% for r in releases %}
          <a class="list-group-item list-group-item-action d-flex justify-content-between align-items-center" href="{{ url_for('view_release', release_id=r.id) }}">
            <div>
              <div class="fw-semibold">{{ r.title }}</div>
              <small class="text-secondary">{{ to_date_br(r.release_date) }} • {{ counts[r.id] }} itens</small>
            </div>
            <span class="btn btn-sm btn-outline-secondary">abrir</span>
          </a>
        {% else %}
          <div class="list-group-item"><em>Nenhuma atualização encontrada.</em></div>
        {% endfor %}
        </div>
        """,
        releases=releases,
        products=products,
        counts={rel.id: count_items(rel) for rel in releases},
        to_date_br=to_date_br,
        selected_pid=selected_pid,
    )
    return render_page(content, page_title="Atualizações")


@app.route("/releases/new", methods=["GET", "POST"])
def new_release():
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        date_str = request.form.get("release_date", "").strip()
        notes = request.form.get("notes", "").strip() or None

        if not title:
            flash("Título é obrigatório.", "error")
        else:
            try:
                d = parse_date_br(date_str)
            except ValueError as e:
                flash(str(e), "error")
            else:
                r = Release(title=title, release_date=d, notes=notes)
                db.session.add(r)
                db.session.commit()
                flash("Atualização criada.", "success")
                return redirect(url_for("view_release", release_id=r.id))

    content = render_template_string(
        r"""
        <h1 class="h4 mb-3">Nova atualização</h1>
        <form method="post" class="vstack gap-3">
          <div>
            <label class="form-label">Título *</label>
            <input name="title" class="form-control" placeholder="Ex.: Sprint 32 – Entregas de maio" required>
          </div>
          <div>
            <label class="form-label">Data (dd/mm/aaaa) *</label>
            <input name="release_date" class="form-control" placeholder="dd/mm/aaaa" required>
            <div class="form-help">Data planejada da atualização.</div>
          </div>
          <div>
            <label class="form-label">Notas</label>
            <textarea name="notes" class="form-control" rows="3" placeholder="Contexto geral, janela de deploy, riscos, etc."></textarea>
          </div>
          <div class="d-flex gap-2">
            <button class="btn btn-primary">Criar</button>
            <a class="btn btn-secondary" href="{{ url_for('list_releases') }}">Cancelar</a>
          </div>
        </form>
        """,
    )
    return render_page(content, page_title="Nova atualização")


@app.route("/releases/<int:release_id>")
def view_release(release_id: int):
    r = Release.query.get_or_404(release_id)

    # Produtos cadastrados (para dropdown)
    all_products = Product.query.order_by(Product.name.asc()).all()
    products = {p.id: p for p in all_products}

    # --- Filtro por produto (server-side) ---
    raw = request.args.get("product_id", "")
    try:
        selected_pid = int(raw) if raw != "" else None
    except ValueError:
        selected_pid = None

    items_all = list(r.items)
    if selected_pid is None:
        items_filtered = items_all
    elif selected_pid == 0:
        items_filtered = [it for it in items_all if it.product_id is None]
    else:
        items_filtered = [it for it in items_all if it.product_id == selected_pid]

    total_items = len(items_all)
    shown_items = len(items_filtered)

    # Cores determinísticas por produto
    palette = ["primary", "success", "info", "warning", "danger", "secondary"]
    color_map = {None: "secondary"}
    for p in all_products:
        color_map[p.id] = palette[p.id % len(palette)]

    content = render_template_string(
        r"""
        <style>
          /* específicos desta página */
          .toolbar-sticky{position:sticky; top:0; z-index:1030; background:var(--bs-body-bg); padding:.5rem .75rem; border-bottom:1px solid var(--bs-border-color); border-radius:.75rem}
          .status-toggle .btn{border-radius:9999px}
          .search-input{max-width:380px}
          .grid{ }
          @media (min-width: 0){      .grid{display:grid; grid-template-columns:1fr; gap:.75rem} }
          @media (min-width: 768px){  .grid{grid-template-columns:1fr 1fr} }
          @media (min-width: 1200px){ .grid{grid-template-columns:1fr 1fr 1fr} }
          .release-item.d-none{display:none !important}
        </style>

        <div class="d-flex justify-content-between align-items-center mb-3">
          <div>
            <h1 class="h4 m-0 page-heading">{{ r.title }}</h1>
            <div class="text-secondary">{{ to_date_br(r.release_date) }}</div>
          </div>
          <div class="d-flex gap-2">
            <a class="btn btn-outline-secondary" href="{{ url_for('edit_release', release_id=r.id) }}"><i class="bi bi-pencil-square me-1"></i>Editar</a>
            <a class="btn btn-outline-danger" href="{{ url_for('delete_release', release_id=r.id) }}" onclick="return confirm('Excluir esta atualização?')"><i class="bi bi-trash3 me-1"></i>Excluir</a>
            <a class="btn btn-primary" href="{{ url_for('new_item', release_id=r.id) }}"><i class="bi bi-plus-lg me-1"></i>Novo item</a>
          </div>
        </div>

        {% if r.notes %}
          <div class="alert note-callout">{{ r.notes }}</div>
        {% endif %}

        <!-- Toolbar sticky com filtros -->
        <div class="toolbar-sticky mb-3">
          <form class="row gy-2 gx-2 align-items-center" method="get" id="filterForm">
            <div class="col-12 col-md-4">
              <label class="form-label mb-1">Produto</label>
              <select name="product_id" class="form-select" onchange="this.form.submit()">
                <option value=""  {% if selected_pid is none %}selected{% endif %}>Todos</option>
                <option value="0" {% if selected_pid == 0 %}selected{% endif %}>Sem produto</option>
                {% for p in all_products %}
                  <option value="{{ p.id }}" {% if selected_pid == p.id %}selected{% endif %}>{{ p.name }}</option>
                {% endfor %}
              </select>
            </div>

            <div class="col-12 col-md-4">
              <label class="form-label mb-1">Buscar</label>
              <input id="q" class="form-control search-input" placeholder="Filtrar por título ou produto…">
            </div>

            <div class="col-12 col-md-4">
              <label class="form-label mb-1">Status</label>
              <div class="btn-group status-toggle w-100" role="group" aria-label="Filtro de status">
                <button type="button" class="btn btn-outline-secondary status-btn active" data-status="__all">Todos</button>
                <button type="button" class="btn btn-outline-secondary status-btn" data-status="Planejado">Planejado</button>
                <button type="button" class="btn btn-outline-secondary status-btn" data-status="Em andamento">Em andamento</button>
                <button type="button" class="btn btn-outline-secondary status-btn" data-status="Entregue">Entregue</button>
                <button type="button" class="btn btn-outline-secondary status-btn" data-status="Cancelado">Cancelado</button>
              </div>
            </div>
          </form>
          <div class="text-secondary small mt-2">Mostrando <strong id="shownCount">{{ shown_items }}</strong> de <strong id="totalCount">{{ total_items }}</strong> itens</div>
        </div>

        <!-- Grid responsivo de cards -->
        <div id="grid" class="grid">
          {% for it in items_filtered %}
            <div class="release-item"
                 data-title="{{ it.title|lower }}"
                 data-product="{{ (products[it.product_id].name|lower) if it.product_id else 'sem produto' }}"
                 data-status="{{ it.status }}">
              <div class="card item-card h-100">
                <div class="card-body py-3 position-relative">
                  <div class="d-flex justify-content-between align-items-center mb-1">
                    <div>
                      {% if it.product_id %}
                        <span class="badge rounded-pill text-bg-{{ color_map[it.product_id] }} product-pill">
                          <i class="bi bi-box-seam me-1"></i>{{ products[it.product_id].name }}
                        </span>
                      {% else %}
                        <span class="badge rounded-pill text-bg-secondary product-pill">
                          <i class="bi bi-box-seam me-1"></i>Sem produto
                        </span>
                      {% endif %}
                    </div>

                    <div class="d-flex align-items-center gap-2">
                      {% set badge = {'Planejado':'primary', 'Em andamento':'warning', 'Entregue':'success', 'Cancelado':'secondary'}[it.status] %}
                      <span class="badge text-bg-{{ badge }} badge-status">{{ it.status }}</span>
                      <a class="btn btn-sm btn-outline-secondary" href="{{ url_for('edit_item', item_id=it.id) }}" title="Editar item">
                        <i class="bi bi-pencil"></i>
                      </a>
                    </div>
                  </div>

                  <!-- Título clicável para editar -->
                  <a href="{{ url_for('edit_item', item_id=it.id) }}" class="stretched-link text-decoration-none text-reset">
                    <div class="fw-semibold clamp-2" title="{{ it.title }}">{{ it.title }}</div>
                  </a>

                  <div class="d-flex flex-wrap gap-2 mt-2">
                    {% for mr in it.mrs %}
                      <a class="chip" href="{{ mr.url }}" target="_blank"><i class="bi bi-git"></i>{{ mr.iid or 'MR' }}</a>
                    {% endfor %}
                    {% if it.clickup_url %}
                      <a class="chip" href="{{ it.clickup_url }}" target="_blank"><i class="bi bi-link-45deg"></i>ClickUp</a>
                    {% endif %}
                  </div>
                </div>
              </div>
            </div>
          {% else %}
            <div id="emptyServer" class="text-secondary"><em>Nenhum item para o filtro selecionado.</em></div>
          {% endfor %}
        </div>

        <div id="emptyClient" class="text-secondary mt-2" style="display:none"><em>Nenhum item após os filtros atuais.</em></div>

        <script>
          (function(){
            const q = document.getElementById('q');
            const buttons = Array.from(document.querySelectorAll('.status-btn'));
            const items = Array.from(document.querySelectorAll('.release-item'));
            const shownEl = document.getElementById('shownCount');
            const totalEl = document.getElementById('totalCount');
            const emptyServer = document.getElementById('emptyServer');
            const emptyClient = document.getElementById('emptyClient');

            // conjunto de status ativos; "__all" significa sem filtro
            let activeStatuses = new Set(["__all"]);

            function applyFilters(){
              const term = (q?.value || "").trim().toLowerCase();
              let shown = 0;

              items.forEach(el=>{
                const title = el.dataset.title || "";
                const product = el.dataset.product || "";
                const status = el.dataset.status || "";

                const matchesText = !term || title.includes(term) || product.includes(term);
                const matchesStatus = activeStatuses.has("__all") || activeStatuses.has(status);

                const visible = matchesText && matchesStatus;
                el.classList.toggle('d-none', !visible);
                if(visible) shown++;
              });

              // atualiza contadores e estados vazios
              if (shownEl) shownEl.textContent = shown;
              if (totalEl) totalEl.textContent = {{ total_items }};
              if (emptyServer) emptyServer.style.display = (items.length === 0) ? "" : "none";
              if (emptyClient) emptyClient.style.display = (shown === 0 && items.length > 0) ? "" : "none";
            }

            // eventos
            q?.addEventListener('input', applyFilters);

            buttons.forEach(btn=>{
              btn.addEventListener('click', ()=>{
                const st = btn.dataset.status;
                // alterna seleção
                if (st === "__all"){
                  activeStatuses = new Set(["__all"]);
                  buttons.forEach(b=>b.classList.toggle('active', b.dataset.status==="__all"));
                } else {
                  // ao ativar um status, desmarca "__all"
                  if (activeStatuses.has("__all")) activeStatuses.delete("__all");
                  btn.classList.toggle('active');
                  const isActive = btn.classList.contains('active');
                  if (isActive) activeStatuses.add(st); else activeStatuses.delete(st);
                  // se nenhum status ativo, volta para "__all"
                  if (activeStatuses.size === 0) {
                    activeStatuses.add("__all");
                    buttons.forEach(b=>b.classList.toggle('active', b.dataset.status==="__all"));
                  } else {
                    // garante que "__all" esteja desmarcado
                    buttons.find(b=>b.dataset.status==="__all")?.classList.remove('active');
                  }
                }
                applyFilters();
              });
            });

            // primeira aplicação (garante contadores corretos após load)
            applyFilters();
          })();
        </script>
        """,
        r=r,
        to_date_br=to_date_br,
        all_products=all_products,
        products=products,
        items_filtered=items_filtered,
        shown_items=shown_items,
        total_items=total_items,
        color_map=color_map,
        selected_pid=selected_pid,
    )
    return render_page(content, page_title=f"Atualização – {to_date_br(r.release_date)}")


@app.route("/releases/<int:release_id>/edit", methods=["GET", "POST"])
def edit_release(release_id: int):
    r = Release.query.get_or_404(release_id)
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        date_str = request.form.get("release_date", "").strip()
        notes = request.form.get("notes", "").strip() or None

        if not title:
            flash("Título é obrigatório.", "error")
        else:
            try:
                d = parse_date_br(date_str)
            except ValueError as e:
                flash(str(e), "error")
            else:
                r.title = title
                r.release_date = d
                r.notes = notes
                db.session.commit()
                flash("Atualização alterada.", "success")
                return redirect(url_for("view_release", release_id=r.id))

    content = render_template_string(
        r"""
        <h1 class="h4 mb-3">Editar atualização</h1>
        <form method="post" class="vstack gap-3">
          <div>
            <label class="form-label">Título *</label>
            <input name="title" class="form-control" value="{{ r.title }}" required>
          </div>
          <div>
            <label class="form-label">Data (dd/mm/aaaa) *</label>
            <input name="release_date" class="form-control" value="{{ to_date_br(r.release_date) }}" required>
          </div>
          <div>
            <label class="form-label">Notas</label>
            <textarea name="notes" class="form-control" rows="3">{{ r.notes or '' }}</textarea>
          </div>
          <div class="d-flex gap-2">
            <button class="btn btn-primary">Salvar</button>
            <a class="btn btn-secondary" href="{{ url_for('view_release', release_id=r.id) }}">Cancelar</a>
          </div>
        </form>
        """,
        r=r,
        to_date_br=to_date_br,
    )
    return render_page(content, page_title="Editar atualização")


@app.route("/releases/<int:release_id>/delete")
def delete_release(release_id: int):
    r = Release.query.get_or_404(release_id)
    db.session.delete(r)
    db.session.commit()
    flash("Atualização excluída.", "success")
    return redirect(url_for("list_releases"))


# -----------------------
# Rotas - Itens de Release (CRUD)
# -----------------------
@app.route("/releases/<int:release_id>/items/new", methods=["GET", "POST"])
def new_item(release_id: int):
    r = Release.query.get_or_404(release_id)
    products = Product.query.filter_by(active=True).order_by(Product.name.asc()).all()

    if request.method == "POST":
        product_id = request.form.get("product_id", type=int)
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip() or None
        clickup_url = norm_url(request.form.get("clickup_url"))
        status = request.form.get("status", "Planejado")
        mr_lines = request.form.get("mr_urls", "").splitlines()

        if not title:
            flash("Título do item é obrigatório.", "error")
        else:
            it = ReleaseItem(
                release_id=r.id,
                product_id=product_id if product_id else None,
                title=title,
                description=description,
                clickup_url=clickup_url,
                status=status,
            )
            db.session.add(it)
            db.session.flush()  # obtém it.id antes do commit

            # Cria MRs (uma por linha não vazia)
            for raw in mr_lines:
                u = norm_url(raw)
                if not u:
                    continue
                # tenta inferir repo/iid simples a partir da URL do GitLab
                repo = None
                iid = None
                m = re.search(r"gitlab\.com/([^/]+/[^/]+)/-?/merge_requests/(\d+)", u)
                if m:
                    repo, iid = m.group(1), m.group(2)
                    iid = f"!{iid}"
                db.session.add(MergeRequest(item_id=it.id, url=u, repo=repo, iid=iid))

            db.session.commit()
            flash("Item criado.", "success")
            return redirect(url_for("view_release", release_id=r.id))

    content = render_template_string(
        r"""
        <h1 class="h4 mb-3">Novo item – {{ r.title }}</h1>
        <form method="post" class="vstack gap-3">
          <div>
            <label class="form-label">Produto</label>
            <select name="product_id" class="form-select">
              <option value="">Selecione…</option>
              {% for p in products %}<option value="{{p.id}}">{{p.name}}</option>{% endfor %}
            </select>
          </div>
          <div>
            <label class="form-label">Título *</label>
            <input name="title" class="form-control" placeholder="Ex.: Ajuste de faturamento ao salvar guia" required>
          </div>
          <div>
            <label class="form-label">Descrição</label>
            <textarea name="description" class="form-control" rows="3" placeholder="Detalhes técnicos, passos de deploy, etc."></textarea>
          </div>
          <div>
            <label class="form-label">Status</label>
            <select class="form-select" name="status">
              {% for s in ['Planejado','Em andamento','Entregue','Cancelado'] %}
                <option value="{{s}}">{{s}}</option>
              {% endfor %}
            </select>
          </div>
          <div>
            <label class="form-label">Link do Card (ClickUp)</label>
            <input name="clickup_url" class="form-control" placeholder="https://app.clickup.com/...">
          </div>
          <div>
            <label class="form-label">MRs (um por linha)</label>
            <textarea name="mr_urls" class="form-control" rows="4" placeholder="https://gitlab.com/grupo/projeto/-/merge_requests/123
https://gitlab.com/outro/proj/-/merge_requests/45"></textarea>
            <div class="form-help">Cole as URLs dos Merge Requests do GitLab (um por linha). O sistema tenta inferir o repositório e o número (!iid).</div>
          </div>
          <div class="d-flex gap-2">
            <button class="btn btn-primary">Salvar item</button>
            <a class="btn btn-secondary" href="{{ url_for('view_release', release_id=r.id) }}">Cancelar</a>
          </div>
        </form>
        """,
        r=r,
        products=products,
    )
    return render_page(content, page_title="Novo item")


@app.route("/items/<int:item_id>/edit", methods=["GET", "POST"])
def edit_item(item_id: int):
    it = ReleaseItem.query.get_or_404(item_id)
    r = it.release
    products = Product.query.filter_by(active=True).order_by(Product.name.asc()).all()

    if request.method == "POST":
        product_id = request.form.get("product_id", type=int)
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip() or None
        clickup_url = norm_url(request.form.get("clickup_url"))
        status = request.form.get("status", "Planejado")
        mr_lines = request.form.get("mr_urls", "").splitlines()

        if not title:
            flash("Título do item é obrigatório.", "error")
        else:
            it.product_id = product_id if product_id else None
            it.title = title
            it.description = description
            it.clickup_url = clickup_url
            it.status = status

            # Substitui o conjunto de MRs pelo fornecido
            MergeRequest.query.filter_by(item_id=it.id).delete()
            for raw in mr_lines:
                u = norm_url(raw)
                if not u:
                    continue
                repo = None
                iid = None
                m = re.search(r"gitlab\.com/([^/]+/[^/]+)/-?/merge_requests/(\d+)", u)
                if m:
                    repo, iid = m.group(1), m.group(2)
                    iid = f"!{iid}"
                db.session.add(MergeRequest(item_id=it.id, url=u, repo=repo, iid=iid))

            db.session.commit()
            flash("Item atualizado.", "success")
            return redirect(url_for("view_release", release_id=r.id))

    # Converte MRs existentes para textarea (uma por linha)
    mr_text = "\n".join(mr.url for mr in it.mrs)

    content = render_template_string(
        r"""
        <h1 class="h4 mb-3">Editar item – {{ r.title }}</h1>
        <form method="post" class="vstack gap-3">
          <div>
            <label class="form-label">Produto</label>
            <select name="product_id" class="form-select">
              <option value="">Selecione…</option>
              {% for p in products %}<option value="{{p.id}}" {% if it.product_id==p.id %}selected{% endif %}>{{p.name}}</option>{% endfor %}
            </select>
          </div>
          <div>
            <label class="form-label">Título *</label>
            <input name="title" class="form-control" value="{{ it.title }}" required>
          </div>
          <div>
            <label class="form-label">Descrição</label>
            <textarea name="description" class="form-control" rows="3">{{ it.description or '' }}</textarea>
          </div>
          <div>
            <label class="form-label">Status</label>
            <select class="form-select" name="status">
              {% for s in ['Planejado','Em andamento','Entregue','Cancelado'] %}
                <option value="{{s}}" {% if it.status==s %}selected{% endif %}>{{s}}</option>
              {% endfor %}
            </select>
          </div>
          <div>
            <label class="form-label">Link do Card (ClickUp)</label>
            <input name="clickup_url" class="form-control" value="{{ it.clickup_url or '' }}">
          </div>
          <div>
            <label class="form-label">MRs (um por linha)</label>
            <textarea name="mr_urls" class="form-control" rows="4">{{ mr_text }}</textarea>
          </div>
          <div class="d-flex gap-2">
            <button class="btn btn-primary">Salvar mudanças</button>
            <a class="btn btn-secondary" href="{{ url_for('view_release', release_id=r.id) }}">Cancelar</a>
          </div>
        </form>
        """,
        r=r,
        it=it,
        products=products,
        mr_text=mr_text,
    )
    return render_page(content, page_title="Editar item")


@app.route("/items/<int:item_id>/delete")
def delete_item(item_id: int):
    it = ReleaseItem.query.get_or_404(item_id)
    release_id = it.release_id
    db.session.delete(it)
    db.session.commit()
    flash("Item excluído.", "success")
    return redirect(url_for("view_release", release_id=release_id))


# -----------------------
# Inicialização do banco
# -----------------------
with app.app_context():
    db.create_all()


# -----------------------
# Execução
# -----------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)

