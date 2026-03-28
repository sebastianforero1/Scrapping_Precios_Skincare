"""
Comparador de Precios — Streamlit App
bellapiel.com.co | lineaestetica.co | medipiel.com.co
"""

import streamlit as st
import requests
from bs4 import BeautifulSoup
import json
import re
import time
from urllib.parse import urljoin, quote_plus
from difflib import SequenceMatcher
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px

# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Comparador de Precios — Cosméticos",
    page_icon="🛒",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─────────────────────────────────────────────────────────────────────────────
# Estilos
# ─────────────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

html, body, [class*="css"] { font-family: 'Inter', sans-serif; }

/* Tarjetas de métricas */
.metric-card {
    background: #f8f9fa;
    border: 1px solid #e9ecef;
    border-radius: 12px;
    padding: 1.25rem 1.5rem;
    margin-bottom: 0.75rem;
}
.metric-card .label { font-size: 0.75rem; color: #6c757d; text-transform: uppercase; letter-spacing: 0.05em; font-weight: 600; margin-bottom: 0.25rem; }
.metric-card .value { font-size: 1.5rem; font-weight: 700; color: #212529; }
.metric-card .sub { font-size: 0.8rem; color: #6c757d; margin-top: 0.15rem; }

/* Badge de tienda */
.store-badge {
    display: inline-block;
    padding: 0.2rem 0.65rem;
    border-radius: 999px;
    font-size: 0.7rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.04em;
}
.badge-bp  { background: #e8f5e9; color: #2e7d32; }
.badge-le  { background: #e3f2fd; color: #1565c0; }
.badge-mp  { background: #fce4ec; color: #b71c1c; }

/* Tag de ahorro */
.savings-tag {
    background: #fff3e0;
    color: #e65100;
    font-size: 0.72rem;
    font-weight: 600;
    padding: 0.15rem 0.5rem;
    border-radius: 6px;
    display: inline-block;
}

/* Fila de producto en carrito */
.cart-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 0.85rem 0;
    border-bottom: 1px solid #f0f0f0;
    gap: 1rem;
}
.cart-row:last-child { border-bottom: none; }
.cart-row .name { font-weight: 500; flex: 1; }
.cart-row .price { font-weight: 700; font-size: 1.05rem; color: #212529; white-space: nowrap; }

/* Total */
.total-bar {
    background: #01696f;
    color: white;
    border-radius: 10px;
    padding: 1rem 1.5rem;
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-top: 1rem;
}
.total-bar .label { font-size: 0.9rem; font-weight: 500; opacity: 0.9; }
.total-bar .amount { font-size: 1.5rem; font-weight: 700; }

/* Ocultar footer de streamlit */
footer { visibility: hidden; }
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# Configuración de tiendas
# ─────────────────────────────────────────────────────────────────────────────
STORES = {
    "Bella Piel": {
        "base_url": "https://www.bellapiel.com.co",
        "search_url": "https://www.bellapiel.com.co/?s={query}&post_type=product",
        "badge_class": "badge-bp",
        "color": "#2e7d32",
    },
    "Línea Estética": {
        "base_url": "https://www.lineaestetica.co",
        "search_url": "https://www.lineaestetica.co/?s={query}&post_type=product",
        "badge_class": "badge-le",
        "color": "#1565c0",
    },
    "Medipiel": {
        "base_url": "https://www.medipiel.com.co",
        "search_url": "https://www.medipiel.com.co/?s={query}&post_type=product",
        "badge_class": "badge-mp",
        "color": "#b71c1c",
    },
}

STORE_COLORS = {s: STORES[s]["color"] for s in STORES}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "es-CO,es;q=0.9",
}

PRICE_SELECTORS = [
    "span.price ins .woocommerce-Price-amount bdi",
    "span.price ins .woocommerce-Price-amount",
    "span.price .woocommerce-Price-amount bdi",
    "span.price .woocommerce-Price-amount",
    ".price .woocommerce-Price-amount",
    ".woocommerce-Price-amount",
    "bdi",
]
TITLE_SELECTORS = [
    "h2.woocommerce-loop-product__title",
    ".woocommerce-loop-product__title",
    ".product-title", "h2.entry-title", "h3.product-title", "h2",
]
LINK_SELECTORS = [
    "a.woocommerce-LoopProduct-link",
    "a.woocommerce-loop-product__link",
    ".product-item a",
    "a[href*='/producto/']",
    "a[href*='/product/']",
    "a",
]
PRODUCT_CONTAINERS = "li.product, div.product-item, article.product, .products > .type-product"

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────
def clean_price(raw: str):
    if not raw:
        return None
    cleaned = re.sub(r"[^\d,.]", "", raw.strip())
    if not cleaned:
        return None
    if "," in cleaned and "." in cleaned:
        cleaned = cleaned.replace(".", "").replace(",", ".")
    elif "." in cleaned:
        parts = cleaned.split(".")
        if len(parts[-1]) == 3:
            cleaned = cleaned.replace(".", "")
    elif "," in cleaned:
        cleaned = cleaned.replace(",", ".")
    try:
        val = float(cleaned)
        if 5_000 <= val <= 2_000_000:
            return val
        return None
    except ValueError:
        return None

def similarity(a, b):
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()

def format_cop(amount):
    return f"$ {amount:,.0f}".replace(",", ".")

def get_page(url):
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "html.parser")
    except:
        return None

def parse_products(soup, store_base):
    products = []
    containers = soup.select(PRODUCT_CONTAINERS)
    for item in containers:
        title = ""
        for sel in TITLE_SELECTORS:
            el = item.select_one(sel)
            if el:
                title = el.get_text(strip=True)
                break
        price_val = None
        for sel in PRICE_SELECTORS:
            for el in item.select(sel):
                val = clean_price(el.get_text(strip=True))
                if val:
                    price_val = val
                    break
            if price_val:
                break
        url = ""
        for sel in LINK_SELECTORS:
            el = item.select_one(sel)
            if el and el.get("href"):
                href = el["href"]
                url = href if href.startswith("http") else urljoin(store_base, href)
                break
        if title:
            products.append({"title": title, "price": price_val, "url": url})
    return products

def search_store(store_name, store_cfg, query, max_pages=3):
    all_products = []
    for page in range(1, max_pages + 1):
        url = store_cfg["search_url"].format(query=quote_plus(query))
        if page > 1:
            url += f"&paged={page}"
        soup = get_page(url)
        if not soup:
            break
        items = parse_products(soup, store_cfg["base_url"])
        if not items:
            break
        all_products.extend(items)
        if not soup.select_one("a.next.page-numbers, .next.page-numbers a, li.next a"):
            break
    return all_products

def find_best_match(query, candidates, threshold=0.28):
    if not candidates:
        return None
    query_words = set(query.lower().split())
    best, best_score = None, threshold
    for c in candidates:
        base_sim = similarity(query, c["title"])
        title_words = set(c["title"].lower().split())
        keyword_overlap = len(query_words & title_words) / max(len(query_words), 1)
        combined = base_sim * 0.6 + keyword_overlap * 0.4
        if combined > best_score:
            best_score = combined
            best = {**c, "match_score": round(combined, 2)}
    return best

def optimize_cart(comparison):
    cart = {}
    for product, stores in comparison.items():
        available = {s: d for s, d in stores.items() if d and d.get("price")}
        if not available:
            cart[product] = None
            continue
        best_store = min(available, key=lambda s: available[s]["price"])
        prices = [d["price"] for d in available.values()]
        cart[product] = {
            "store": best_store,
            "price": available[best_store]["price"],
            "title_found": available[best_store]["title"],
            "url": available[best_store].get("url", ""),
            "savings_vs_max": round(max(prices) - available[best_store]["price"], 0),
            "all_prices": {s: d["price"] for s, d in available.items()},
        }
    return cart

# ─────────────────────────────────────────────────────────────────────────────
# Sidebar
# ─────────────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 🛒 Comparador de Precios")
    st.caption("bellapiel.com.co · lineaestetica.co · medipiel.com.co")
    st.divider()

    st.markdown("### Productos a buscar")
    default_products = [
        "CeraVe gel limpiador espumoso 473ml",
        "Cetaphil crema hidratante",
        "Eucerin protector solar fps50",
        "La Roche Posay Effaclar serum",
        "Bioderma Sensibio H2O",
    ]
    products_text = st.text_area(
        "Un producto por línea:",
        value="\n".join(default_products),
        height=180,
        label_visibility="collapsed",
    )

    st.markdown("### Opciones")
    threshold = st.slider(
        "Umbral de coincidencia",
        min_value=0.10, max_value=0.70, value=0.28, step=0.02,
        help="Qué tan similar debe ser el nombre encontrado al buscado. Bájalo si no encuentra resultados.",
    )
    max_pages = st.select_slider(
        "Páginas de resultados por tienda",
        options=[1, 2, 3], value=2,
    )

    st.divider()
    run_button = st.button("🔍 Buscar y Comparar", type="primary", use_container_width=True)

    st.divider()
    st.markdown("""
    <small style="color:#999">
    Las tres tiendas usan WooCommerce.<br>
    Los precios son en COP (pesos colombianos).<br><br>
    <b>Tip:</b> Usa nombres de marca y presentación para mejores resultados.
    </small>
    """, unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# Main content
# ─────────────────────────────────────────────────────────────────────────────
st.title("Comparador de Precios · Dermocosméticos")
st.markdown("Busca productos en las tres tiendas y construye el carrito más económico.")

if not run_button:
    # Estado inicial — instrucciones
    col1, col2, col3 = st.columns(3)
    with col1:
        st.info("**1. Agrega tus productos**\nEscribe uno por línea en el panel izquierdo.", icon="📝")
    with col2:
        st.info("**2. Haz clic en Buscar**\nEl script busca simultáneamente en las 3 tiendas.", icon="🔍")
    with col3:
        st.info("**3. Revisa el carrito óptimo**\nVe dónde comprar cada producto más barato.", icon="💡")
    st.stop()

# ─────────────────────────────────────────────────────────────────────────────
# Ejecutar búsqueda
# ─────────────────────────────────────────────────────────────────────────────
queries = [q.strip() for q in products_text.strip().splitlines() if q.strip()]
if not queries:
    st.error("Agrega al menos un producto en el panel izquierdo.")
    st.stop()

comparison = {q: {} for q in queries}

progress_bar = st.progress(0, text="Iniciando búsqueda...")
total_steps = len(STORES) * len(queries)
step = 0

for store_name, store_cfg in STORES.items():
    for query in queries:
        step += 1
        progress_bar.progress(step / total_steps, text=f"Buscando **{query[:40]}** en **{store_name}**...")
        results = search_store(store_name, store_cfg, query, max_pages=max_pages)
        match = find_best_match(query, results, threshold=threshold)
        comparison[query][store_name] = match
        time.sleep(0.3)

progress_bar.empty()

# ─────────────────────────────────────────────────────────────────────────────
# Tabla comparativa
# ─────────────────────────────────────────────────────────────────────────────
st.markdown("---")
st.subheader("📊 Tabla comparativa de precios")

store_names = list(STORES.keys())
table_data = []
for query in queries:
    row = {"Producto": query}
    for s in store_names:
        d = comparison[query].get(s)
        row[s] = d["price"] if d and d.get("price") else None
    table_data.append(row)

df = pd.DataFrame(table_data)
df_display = df.copy()
for s in store_names:
    df_display[s] = df_display[s].apply(lambda x: format_cop(x) if x else "—")

# Colorear mínimos
def highlight_min(row):
    prices = {s: row[s] for s in store_names if row[s] != "—"}
    styles = [""] * len(row)
    if not prices:
        return styles
    min_price = min(prices.values())
    for i, col in enumerate(row.index):
        if col in prices and prices[col] == min_price:
            styles[i] = "background-color: #e8f5e9; font-weight: 600; color: #2e7d32;"
    return styles

st.dataframe(
    df_display.style.apply(highlight_min, axis=1),
    use_container_width=True,
    hide_index=True,
)

# ─────────────────────────────────────────────────────────────────────────────
# Gráfico de barras comparativo
# ─────────────────────────────────────────────────────────────────────────────
st.subheader("📈 Comparación visual")

# Preparar datos para Plotly
chart_data = []
for q in queries:
    for s in store_names:
        d = comparison[q].get(s)
        if d and d.get("price"):
            chart_data.append({"Producto": q[:35] + ("..." if len(q) > 35 else ""), "Tienda": s, "Precio": d["price"]})

if chart_data:
    df_chart = pd.DataFrame(chart_data)
    fig = px.bar(
        df_chart,
        x="Precio",
        y="Producto",
        color="Tienda",
        barmode="group",
        orientation="h",
        color_discrete_map=STORE_COLORS,
        text="Precio",
        height=max(300, 120 * len(queries)),
    )
    fig.update_traces(
        texttemplate="$ %{x:,.0f}",
        textposition="outside",
        textfont_size=11,
    )
    fig.update_layout(
        plot_bgcolor="white",
        paper_bgcolor="white",
        font=dict(family="Inter", size=12),
        legend=dict(orientation="h", y=1.05, x=0),
        margin=dict(l=0, r=120, t=40, b=20),
        xaxis=dict(showgrid=True, gridcolor="#f0f0f0", tickformat=",.0f", tickprefix="$ "),
        yaxis=dict(autorange="reversed"),
    )
    st.plotly_chart(fig, use_container_width=True)

# ─────────────────────────────────────────────────────────────────────────────
# Carrito óptimo
# ─────────────────────────────────────────────────────────────────────────────
st.markdown("---")
st.subheader("🛒 Carrito óptimo")

cart = optimize_cart(comparison)
total_optimal = sum(rec["price"] for rec in cart.values() if rec)
not_found = [p for p, rec in cart.items() if rec is None]

# KPIs
kpi1, kpi2, kpi3 = st.columns(3)
with kpi1:
    found_count = sum(1 for rec in cart.values() if rec)
    st.metric("Productos encontrados", f"{found_count} / {len(queries)}")
with kpi2:
    st.metric("Total carrito óptimo", format_cop(total_optimal))
with kpi3:
    total_savings = sum(rec["savings_vs_max"] for rec in cart.values() if rec)
    st.metric("Ahorro total vs. precio máximo", format_cop(total_savings), delta=f"-{format_cop(total_savings)}")

st.markdown("")

# Desglose por producto
cart_html = ""
for product, rec in cart.items():
    if rec is None:
        cart_html += f"""
        <div class="cart-row">
            <span class="name" style="color:#999">{product}</span>
            <span style="color:#999; font-size:0.85rem;">No encontrado</span>
        </div>"""
    else:
        badge_class = STORES[rec["store"]]["badge_class"]
        savings_html = f'<span class="savings-tag">Ahorro {format_cop(rec["savings_vs_max"])}</span>' if rec["savings_vs_max"] > 0 else ""
        link_html = f'<a href="{rec["url"]}" target="_blank" style="font-size:0.75rem; color:#01696f; text-decoration:none; margin-left:0.5rem;">→ ver producto</a>' if rec.get("url") else ""
        cart_html += f"""
        <div class="cart-row">
            <div class="name">
                {product}<br>
                <span style="font-size:0.75rem; color:#999;">{rec['title_found'][:60]}</span>
            </div>
            <div style="display:flex; align-items:center; gap:0.75rem; flex-wrap:wrap; justify-content:flex-end;">
                <span class="store-badge {badge_class}">{rec['store']}</span>
                {savings_html}
                <span class="price">{format_cop(rec['price'])}</span>
                {link_html}
            </div>
        </div>"""

cart_html += f"""
<div class="total-bar">
    <span class="label">Total carrito óptimo</span>
    <span class="amount">{format_cop(total_optimal)}</span>
</div>"""

st.markdown(f'<div style="background:white; border:1px solid #e9ecef; border-radius:12px; padding:1rem 1.5rem;">{cart_html}</div>', unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# Distribución por tienda (pie)
# ─────────────────────────────────────────────────────────────────────────────
store_counts = {}
store_totals = {}
for rec in cart.values():
    if rec:
        s = rec["store"]
        store_counts[s] = store_counts.get(s, 0) + 1
        store_totals[s] = store_totals.get(s, 0) + rec["price"]

if store_counts:
    st.markdown("---")
    col_pie, col_bar = st.columns(2)

    with col_pie:
        st.markdown("**Cantidad de productos por tienda**")
        fig_pie = go.Figure(go.Pie(
            labels=list(store_counts.keys()),
            values=list(store_counts.values()),
            hole=0.5,
            marker_colors=[STORE_COLORS[s] for s in store_counts],
            textinfo="label+value",
        ))
        fig_pie.update_layout(
            showlegend=False,
            margin=dict(l=20, r=20, t=20, b=20),
            paper_bgcolor="white",
            font=dict(family="Inter"),
            height=260,
        )
        st.plotly_chart(fig_pie, use_container_width=True)

    with col_bar:
        st.markdown("**Gasto por tienda**")
        fig_bar2 = go.Figure(go.Bar(
            x=list(store_totals.keys()),
            y=list(store_totals.values()),
            marker_color=[STORE_COLORS[s] for s in store_totals],
            text=[format_cop(v) for v in store_totals.values()],
            textposition="outside",
        ))
        fig_bar2.update_layout(
            plot_bgcolor="white",
            paper_bgcolor="white",
            font=dict(family="Inter", size=12),
            margin=dict(l=20, r=20, t=20, b=20),
            yaxis=dict(showgrid=True, gridcolor="#f0f0f0", tickformat=",.0f"),
            height=260,
        )
        st.plotly_chart(fig_bar2, use_container_width=True)

# ─────────────────────────────────────────────────────────────────────────────
# Exportar resultados
# ─────────────────────────────────────────────────────────────────────────────
st.markdown("---")
st.subheader("💾 Exportar resultados")

col_json, col_csv = st.columns(2)

with col_json:
    export_data = {
        "comparison": {
            product: {
                store: {
                    "price": d["price"] if d else None,
                    "title_found": d.get("title") if d else None,
                    "url": d.get("url") if d else None,
                    "match_score": d.get("match_score") if d else None,
                } for store, d in stores.items()
            } for product, stores in comparison.items()
        },
        "optimal_cart": {product: rec for product, rec in cart.items()},
    }
    st.download_button(
        "⬇ Descargar JSON completo",
        data=json.dumps(export_data, ensure_ascii=False, indent=2),
        file_name="comparacion_precios.json",
        mime="application/json",
        use_container_width=True,
    )

with col_csv:
    rows_csv = []
    for product, rec in cart.items():
        if rec:
            rows_csv.append({
                "Producto buscado": product,
                "Mejor tienda": rec["store"],
                "Precio óptimo (COP)": rec["price"],
                "Título encontrado": rec["title_found"],
                "Ahorro vs máximo": rec["savings_vs_max"],
                "URL": rec.get("url", ""),
            })
    df_csv = pd.DataFrame(rows_csv)
    st.download_button(
        "⬇ Descargar CSV carrito",
        data=df_csv.to_csv(index=False, encoding="utf-8-sig"),
        file_name="carrito_optimo.csv",
        mime="text/csv",
        use_container_width=True,
    )

# Alertas de productos no encontrados
if not_found:
    st.markdown("---")
    st.warning(f"**{len(not_found)} producto(s) no encontrado(s):**\n" + "\n".join(f"- {p}" for p in not_found) +
               "\n\nSugerencia: intenta con nombres más cortos o sin la presentación (ml/g).")
