import streamlit as st
import requests
from bs4 import BeautifulSoup
import re
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from urllib.parse import urlparse, urljoin
import json
from difflib import SequenceMatcher
import time

# ─── CONFIG ────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Comparador de precios",
    page_icon="🛒",
    layout="wide",
    initial_sidebar_state="expanded",
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "es-CO,es;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
}

PRESET_STORES = {
    "bellapiel.com.co": "Bella Piel",
    "lineaestetica.co": "Línea Estética",
    "medipiel.com.co": "Medipiel",
}

STORE_COLORS = [
    "#01696f", "#e07b39", "#4a6fa5", "#8e44ad",
    "#27ae60", "#c0392b", "#f39c12", "#16a085",
]

# ─── STYLES ────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

html, body, [class*="css"] { font-family: 'Inter', sans-serif; }

.store-card {
    background: #f9f8f5;
    border: 1px solid rgba(0,0,0,0.08);
    border-radius: 10px;
    padding: 1rem 1.2rem;
    margin-bottom: 0.75rem;
    position: relative;
}
.store-card-name { font-weight: 600; font-size: 0.95rem; margin-bottom: 0.2rem; }
.store-card-url { font-size: 0.78rem; color: #7a7974; word-break: break-all; }

.product-row-card {
    background: #fff;
    border: 1px solid rgba(0,0,0,0.07);
    border-radius: 8px;
    padding: 1rem;
    margin-bottom: 0.6rem;
}
.kpi-box {
    background: #f3f0ec;
    border-radius: 10px;
    padding: 1rem 1.4rem;
    text-align: center;
}
.kpi-label { font-size: 0.78rem; color: #7a7974; text-transform: uppercase; letter-spacing: 0.05em; }
.kpi-value { font-size: 1.6rem; font-weight: 700; color: #01696f; font-variant-numeric: tabular-nums; }

.price-best { color: #1a7a3a; font-weight: 700; }
.price-worst { color: #9a4a4a; }
.price-mid { color: #28251d; }

.cart-item {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    padding: 0.8rem 1rem;
    background: #f9f8f5;
    border-radius: 8px;
    margin-bottom: 0.5rem;
    border: 1px solid rgba(0,0,0,0.06);
}
.store-badge {
    display: inline-block;
    padding: 2px 10px;
    border-radius: 999px;
    font-size: 0.72rem;
    font-weight: 600;
    color: white;
    white-space: nowrap;
}
.savings-pill {
    background: #d4dfcc;
    color: #1e3f0a;
    padding: 2px 10px;
    border-radius: 999px;
    font-size: 0.75rem;
    font-weight: 600;
}
section[data-testid="stSidebar"] {
    background: #1c1b19 !important;
}
section[data-testid="stSidebar"] * {
    color: #cdccca !important;
}
</style>
""", unsafe_allow_html=True)

# ─── SESSION STATE ─────────────────────────────────────────────────────────────
if "stores" not in st.session_state:
    st.session_state.stores = [
        {"name": "Bella Piel",      "url": "https://www.bellapiel.com.co",    "color": STORE_COLORS[0], "active": True},
        {"name": "Línea Estética",  "url": "https://www.lineaestetica.co",     "color": STORE_COLORS[1], "active": True},
        {"name": "Medipiel",        "url": "https://www.medipiel.com.co",      "color": STORE_COLORS[2], "active": True},
    ]
if "products" not in st.session_state:
    st.session_state.products = [""]
if "results" not in st.session_state:
    st.session_state.results = None

# ─── HELPERS ──────────────────────────────────────────────────────────────────
def get_domain(url):
    try:
        return urlparse(url).netloc.replace("www.", "")
    except:
        return url

def clean_price(raw):
    """Extract numeric price from COP string like $148.900 or 148,900."""
    if not raw:
        return None
    raw = re.sub(r"[^\d.,]", "", raw.strip())
    if not raw:
        return None
    # Detect if dots are thousands separators (e.g. 148.900)
    dot_idx = raw.rfind(".")
    comma_idx = raw.rfind(",")
    if dot_idx > comma_idx:
        # dots as thousands: remove dots
        raw = raw.replace(".", "").replace(",", ".")
    else:
        raw = raw.replace(",", "")
    try:
        return float(raw)
    except:
        return None

def fetch_html(url, timeout=12):
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout)
        r.raise_for_status()
        return r.text
    except Exception as e:
        return None

def extract_product_from_url(url):
    """
    Given a direct product URL, extract: name, price, image.
    Handles WooCommerce and generic e-commerce patterns.
    """
    html = fetch_html(url)
    if not html:
        return {"url": url, "name": None, "price": None, "image": None, "error": "No se pudo cargar la página"}

    soup = BeautifulSoup(html, "html.parser")

    # ── Name ──────────────────────────────────────────────────────────────────
    name = None
    name_selectors = [
        "h1.product_title",
        "h1.product-title",
        "h1[itemprop='name']",
        ".product-name h1",
        "h1.entry-title",
        "h1",
    ]
    for sel in name_selectors:
        el = soup.select_one(sel)
        if el and el.get_text(strip=True):
            name = el.get_text(strip=True)
            break

    # ── Price ─────────────────────────────────────────────────────────────────
    price = None
    price_selectors = [
        "p.price ins .woocommerce-Price-amount bdi",
        "p.price .woocommerce-Price-amount bdi",
        "p.price .woocommerce-Price-amount",
        ".price ins bdi",
        ".price bdi",
        ".price .amount",
        "[itemprop='price']",
        ".product-price",
        ".precio",
        ".woocommerce-Price-amount",
        "span.price",
    ]
    for sel in price_selectors:
        el = soup.select_one(sel)
        if el:
            text = el.get_text(strip=True)
            p = clean_price(text)
            if p and p > 100:
                price = p
                break

    # If still no price, try meta
    if not price:
        meta = soup.find("meta", {"property": "product:price:amount"}) or \
               soup.find("meta", {"itemprop": "price"})
        if meta:
            price = clean_price(meta.get("content", ""))

    # ── Image ─────────────────────────────────────────────────────────────────
    image = None
    img_selectors = [
        ".woocommerce-product-gallery__image img",
        ".product-image img",
        "img.wp-post-image",
        ".product img",
    ]
    for sel in img_selectors:
        el = soup.select_one(sel)
        if el:
            src = el.get("src") or el.get("data-src") or el.get("data-lazy-src")
            if src:
                image = urljoin(url, src)
                break

    return {
        "url": url,
        "name": name,
        "price": price,
        "image": image,
        "error": None if (name or price) else "No se encontró producto en esta URL",
    }


def search_store_for_product(store_url, product_name, max_pages=2):
    """
    Search a WooCommerce store by product name.
    Returns list of {name, price, url} candidates.
    """
    results = []
    base = store_url.rstrip("/")
    for page in range(1, max_pages + 1):
        search_url = f"{base}/?s={requests.utils.quote(product_name)}&post_type=product"
        if page > 1:
            search_url += f"&paged={page}"
        html = fetch_html(search_url)
        if not html:
            break
        soup = BeautifulSoup(html, "html.parser")

        # WooCommerce product cards
        cards = (
            soup.select("li.product") or
            soup.select(".product-item") or
            soup.select(".products .product") or
            soup.select("article.product")
        )
        if not cards:
            break

        for card in cards:
            a = card.select_one("a[href]")
            href = a["href"] if a else None
            title_el = card.select_one(".woocommerce-loop-product__title, h2, h3, .product-name")
            title = title_el.get_text(strip=True) if title_el else None
            price_el = card.select_one(".woocommerce-Price-amount bdi, .price bdi, .price .amount, .price")
            raw_price = price_el.get_text(strip=True) if price_el else None
            price = clean_price(raw_price) if raw_price else None
            if title and href:
                results.append({"name": title, "price": price, "url": href})

    return results


def best_match(query, candidates, threshold=0.30):
    """Return the best matching candidate by combined similarity score."""
    if not candidates:
        return None
    query_lower = query.lower()
    query_words = set(re.findall(r"\w+", query_lower))
    best = None
    best_score = -1
    for c in candidates:
        cname = (c.get("name") or "").lower()
        cwords = set(re.findall(r"\w+", cname))
        seq = SequenceMatcher(None, query_lower, cname).ratio()
        kw = len(query_words & cwords) / max(len(query_words), 1)
        score = 0.55 * seq + 0.45 * kw
        if score > best_score:
            best_score = score
            best = c
    if best_score < threshold:
        return None
    best["_score"] = round(best_score, 3)
    return best


def format_cop(value):
    if value is None:
        return "—"
    return f"${value:,.0f}".replace(",", ".")


# ─── SIDEBAR ──────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 🛒 Comparador de precios")
    st.markdown("---")

    # ── Tiendas ──────────────────────────────────────────────────────────────
    st.markdown("### Tiendas")
    st.caption("Activa, desactiva o agrega tiendas. Pega la URL base (ej: https://www.tienda.com)")

    stores_to_remove = []
    for i, store in enumerate(st.session_state.stores):
        cols = st.columns([0.1, 0.9])
        with cols[0]:
            active = st.checkbox("", value=store["active"], key=f"active_{i}", label_visibility="collapsed")
            st.session_state.stores[i]["active"] = active
        with cols[1]:
            new_name = st.text_input("Nombre", value=store["name"], key=f"sname_{i}", label_visibility="collapsed", placeholder="Nombre tienda")
            st.session_state.stores[i]["name"] = new_name
            new_url = st.text_input("URL", value=store["url"], key=f"surl_{i}", label_visibility="collapsed", placeholder="https://...")
            st.session_state.stores[i]["url"] = new_url
            if st.button("✕ Eliminar", key=f"del_{i}", use_container_width=False):
                stores_to_remove.append(i)

    for i in reversed(stores_to_remove):
        st.session_state.stores.pop(i)

    col_add1, col_add2 = st.columns(2)
    with col_add1:
        if st.button("＋ Añadir tienda", use_container_width=True):
            n = len(st.session_state.stores)
            st.session_state.stores.append({
                "name": f"Tienda {n+1}",
                "url": "",
                "color": STORE_COLORS[n % len(STORE_COLORS)],
                "active": True,
            })
            st.rerun()

    st.markdown("---")

    # ── Modo de búsqueda ──────────────────────────────────────────────────────
    st.markdown("### Modo de búsqueda")
    search_mode = st.radio(
        "¿Cómo quieres encontrar los productos?",
        ["🔗 Pegar URL directa por producto", "🔍 Buscar por nombre"],
        label_visibility="collapsed",
    )

    st.markdown("---")
    st.markdown("### Ajustes")
    threshold = st.slider("Sensibilidad de coincidencia (búsqueda)", 0.15, 0.60, 0.28, 0.01,
                          help="Qué tan similares deben ser los nombres. Más alto = más estricto.")
    max_pages = st.number_input("Páginas de resultados", 1, 5, 2)


# ─── MAIN ─────────────────────────────────────────────────────────────────────
st.markdown("# Comparador de precios")
st.markdown("Compara precios de productos en múltiples tiendas y optimiza tu carrito de compra.")

active_stores = [s for s in st.session_state.stores if s["active"] and s["url"].strip()]

if not active_stores:
    st.warning("Activa al menos una tienda con URL en el panel lateral.")
    st.stop()

# ─── ENTRADA DE PRODUCTOS ─────────────────────────────────────────────────────
st.markdown("---")

if "🔗" in search_mode:
    # ── Modo URL directa ───────────────────────────────────────────────────
    st.markdown("## Productos por URL directa")
    st.caption(
        "Para cada producto, pega la URL del producto en cada tienda. "
        "Deja vacío si la tienda no lo vende."
    )

    # Asegurar suficientes filas
    while len(st.session_state.products) < 1:
        st.session_state.products.append("")

    # Tabla de productos × tiendas
    product_urls = []  # list of {product_label, store_name: url, ...}

    for pi in range(len(st.session_state.products)):
        with st.expander(f"Producto {pi+1}", expanded=True):
            prod_label = st.text_input(
                "Nombre / etiqueta del producto (opcional)",
                value=st.session_state.products[pi],
                key=f"prod_label_{pi}",
                placeholder="Ej: CeraVe Gel Limpiador 473ml",
            )
            st.session_state.products[pi] = prod_label

            urls_for_product = {"label": prod_label or f"Producto {pi+1}"}
            cols = st.columns(len(active_stores))
            for si, store in enumerate(active_stores):
                with cols[si]:
                    u = st.text_input(
                        store["name"],
                        key=f"url_{pi}_{si}",
                        placeholder="https://...",
                    )
                    urls_for_product[store["name"]] = u.strip()
            product_urls.append(urls_for_product)

    col_add_p, col_rm_p = st.columns([1, 1])
    with col_add_p:
        if st.button("＋ Agregar producto", use_container_width=True):
            st.session_state.products.append("")
            st.rerun()
    with col_rm_p:
        if len(st.session_state.products) > 1:
            if st.button("− Quitar último", use_container_width=True):
                st.session_state.products.pop()
                st.rerun()

    st.markdown("---")
    run_btn = st.button("🔍 Comparar precios", type="primary", use_container_width=True)

    if run_btn:
        results = []
        progress = st.progress(0, text="Iniciando…")
        total = sum(
            1 for pu in product_urls
            for sname in [s["name"] for s in active_stores]
            if pu.get(sname, "").startswith("http")
        )
        done = 0

        for pu in product_urls:
            row = {"product": pu["label"]}
            for store in active_stores:
                url = pu.get(store["name"], "")
                if url.startswith("http"):
                    progress.progress(done / max(total, 1), text=f"Leyendo {store['name']}… {pu['label']}")
                    data = extract_product_from_url(url)
                    row[store["name"]] = {
                        "price": data["price"],
                        "name": data["name"],
                        "url": url,
                        "error": data["error"],
                    }
                    done += 1
                    time.sleep(0.3)
                else:
                    row[store["name"]] = {"price": None, "name": None, "url": None, "error": None}
            results.append(row)

        progress.empty()
        st.session_state.results = {"mode": "url", "data": results, "stores": [s["name"] for s in active_stores]}

else:
    # ── Modo búsqueda por nombre ────────────────────────────────────────────
    st.markdown("## Productos a buscar")
    st.caption("Escribe uno por línea o uno por campo.")

    products_text = st.text_area(
        "Lista de productos",
        value="\n".join(p for p in st.session_state.products if p),
        height=180,
        placeholder="CeraVe gel limpiador espumoso 473ml\nCetaphil crema hidratante\nEucerin protector solar fps50",
        label_visibility="collapsed",
    )
    names = [p.strip() for p in products_text.splitlines() if p.strip()]

    st.markdown("---")
    run_btn = st.button("🔍 Buscar y comparar", type="primary", use_container_width=True)

    if run_btn:
        if not names:
            st.warning("Agrega al menos un producto.")
            st.stop()

        results = []
        progress = st.progress(0, text="Iniciando…")
        total = len(names) * len(active_stores)
        done = 0

        for name in names:
            row = {"product": name}
            for store in active_stores:
                progress.progress(done / total, text=f"Buscando '{name}' en {store['name']}…")
                candidates = search_store_for_product(store["url"], name, max_pages=max_pages)
                match = best_match(name, candidates, threshold=threshold)
                if match:
                    row[store["name"]] = {
                        "price": match.get("price"),
                        "name": match.get("name"),
                        "url": match.get("url"),
                        "error": None,
                        "_score": match.get("_score"),
                    }
                else:
                    row[store["name"]] = {"price": None, "name": None, "url": None, "error": "No encontrado"}
                done += 1
                time.sleep(0.4)

        progress.empty()
        st.session_state.results = {"mode": "search", "data": results, "stores": [s["name"] for s in active_stores]}


# ─── RESULTADOS ───────────────────────────────────────────────────────────────
if st.session_state.results:
    res = st.session_state.results
    data = res["data"]
    store_names = res["stores"]
    store_color_map = {s["name"]: s["color"] for s in st.session_state.stores}

    st.markdown("---")
    st.markdown("## Resultados")

    # ── KPIs ────────────────────────────────────────────────────────────────
    found = sum(
        1 for row in data
        for sn in store_names
        if row.get(sn, {}).get("price")
    )
    all_slots = len(data) * len(store_names)

    # Optimal cart
    cart = []
    for row in data:
        prices = {sn: row.get(sn, {}).get("price") for sn in store_names if row.get(sn, {}).get("price")}
        if prices:
            best_store = min(prices, key=prices.get)
            cart.append({
                "product": row["product"],
                "store": best_store,
                "price": prices[best_store],
                "url": row.get(best_store, {}).get("url"),
                "all_prices": prices,
            })

    total_optimal = sum(c["price"] for c in cart)
    total_cheapest_single = min(
        (sum(row.get(sn, {}).get("price", 0) or 0 for row in data) for sn in store_names),
        default=0,
    )
    savings = total_cheapest_single - total_optimal if total_cheapest_single > total_optimal else 0

    k1, k2, k3, k4 = st.columns(4)
    with k1:
        st.markdown(f'''<div class="kpi-box"><div class="kpi-label">Productos buscados</div><div class="kpi-value">{len(data)}</div></div>''', unsafe_allow_html=True)
    with k2:
        st.markdown(f'''<div class="kpi-box"><div class="kpi-label">Precios encontrados</div><div class="kpi-value">{found}/{all_slots}</div></div>''', unsafe_allow_html=True)
    with k3:
        st.markdown(f'''<div class="kpi-box"><div class="kpi-label">Total carrito óptimo</div><div class="kpi-value">{format_cop(total_optimal)}</div></div>''', unsafe_allow_html=True)
    with k4:
        st.markdown(f'''<div class="kpi-box"><div class="kpi-label">Ahorro vs 1 tienda</div><div class="kpi-value" style="color:#1a7a3a">{format_cop(savings)}</div></div>''', unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Tabla comparativa ───────────────────────────────────────────────────
    st.markdown("### Tabla comparativa de precios")

    table_rows = []
    for row in data:
        prices = {sn: row.get(sn, {}).get("price") for sn in store_names}
        valid = [p for p in prices.values() if p]
        min_p = min(valid) if valid else None
        max_p = max(valid) if valid else None
        tr = {"Producto": row["product"]}
        for sn in store_names:
            p = prices.get(sn)
            if p is None:
                tr[sn] = "—"
            elif p == min_p:
                tr[sn] = f"✅ {format_cop(p)}"
            elif p == max_p and len(valid) > 1:
                tr[sn] = f"⬆ {format_cop(p)}"
            else:
                tr[sn] = format_cop(p)
        table_rows.append(tr)

    df_table = pd.DataFrame(table_rows)
    st.dataframe(df_table, use_container_width=True, hide_index=True)

    # ── Gráfico de barras ────────────────────────────────────────────────────
    st.markdown("### Comparación visual")

    products_with_prices = [
        row for row in data
        if any(row.get(sn, {}).get("price") for sn in store_names)
    ]

    if products_with_prices:
        fig = go.Figure()
        for i, sn in enumerate(store_names):
            color = store_color_map.get(sn, STORE_COLORS[i % len(STORE_COLORS)])
            y_vals = [row.get(sn, {}).get("price") or 0 for row in products_with_prices]
            product_labels = [row["product"][:30] + ("…" if len(row["product"]) > 30 else "") for row in products_with_prices]
            fig.add_trace(go.Bar(
                name=sn,
                x=product_labels,
                y=y_vals,
                marker_color=color,
                text=[format_cop(v) if v else "" for v in y_vals],
                textposition="outside",
            ))

        fig.update_layout(
            barmode="group",
            plot_bgcolor="white",
            paper_bgcolor="white",
            font_family="Inter",
            xaxis_title=None,
            yaxis_title="Precio (COP)",
            legend_title="Tienda",
            margin=dict(t=20, b=20),
            height=420,
        )
        st.plotly_chart(fig, use_container_width=True)

    # ── Carrito óptimo ───────────────────────────────────────────────────────
    st.markdown("### 🛒 Carrito óptimo")
    st.caption("Dónde comprar cada producto para minimizar el gasto total.")

    if cart:
        for item in cart:
            color = store_color_map.get(item["store"], "#01696f")
            all_p = item["all_prices"]
            max_p = max(all_p.values()) if all_p else None
            saved = (max_p - item["price"]) if max_p and max_p != item["price"] else 0
            savings_html = f'<span class="savings-pill">Ahorra {format_cop(saved)}</span>' if saved > 0 else ""

            link_html = (
                f'<a href="{item['url']}" target="_blank" rel="noopener" style="font-size:0.78rem;color:#01696f;">Ver producto ↗</a>'
                if item.get("url") else ""
            )
            st.markdown(f'''
            <div class="cart-item">
                <span class="store-badge" style="background:{color}">{item["store"]}</span>
                <span style="flex:1;font-size:0.9rem">{item["product"]}</span>
                <strong style="font-variant-numeric:tabular-nums">{format_cop(item["price"])}</strong>
                {savings_html}
                {link_html}
            </div>
            ''', unsafe_allow_html=True)

        st.markdown(f"""
        <div style="text-align:right;margin-top:1rem;padding-top:0.8rem;border-top:1px solid #dcd9d5">
            <span style="font-size:0.85rem;color:#7a7974">Total carrito óptimo:</span>
            <strong style="font-size:1.3rem;margin-left:0.5rem;font-variant-numeric:tabular-nums">{format_cop(total_optimal)}</strong>
        </div>
        """, unsafe_allow_html=True)
    else:
        st.info("No se encontraron precios suficientes para armar el carrito óptimo.")

    # ── Distribución por tienda ──────────────────────────────────────────────
    if cart:
        st.markdown("### Distribución del carrito")
        c1, c2 = st.columns(2)

        store_counts = {}
        store_totals = {}
        for item in cart:
            store_counts[item["store"]] = store_counts.get(item["store"], 0) + 1
            store_totals[item["store"]] = store_totals.get(item["store"], 0) + item["price"]

        with c1:
            fig_pie = go.Figure(go.Pie(
                labels=list(store_counts.keys()),
                values=list(store_counts.values()),
                marker_colors=[store_color_map.get(sn, "#ccc") for sn in store_counts.keys()],
                hole=0.4,
            ))
            fig_pie.update_layout(
                title="Productos por tienda",
                paper_bgcolor="white", plot_bgcolor="white",
                font_family="Inter", height=300, margin=dict(t=40, b=10),
            )
            st.plotly_chart(fig_pie, use_container_width=True)

        with c2:
            fig_bar2 = go.Figure(go.Bar(
                x=list(store_totals.keys()),
                y=list(store_totals.values()),
                marker_color=[store_color_map.get(sn, "#ccc") for sn in store_totals.keys()],
                text=[format_cop(v) for v in store_totals.values()],
                textposition="outside",
            ))
            fig_bar2.update_layout(
                title="Gasto por tienda",
                paper_bgcolor="white", plot_bgcolor="white",
                font_family="Inter", height=300, margin=dict(t=40, b=10),
                yaxis_title="COP",
            )
            st.plotly_chart(fig_bar2, use_container_width=True)

    # ── Exportar ─────────────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("### Exportar resultados")
    col_j, col_c = st.columns(2)

    with col_j:
        st.download_button(
            "📥 Descargar JSON",
            data=json.dumps(data, ensure_ascii=False, indent=2),
            file_name="comparacion_precios.json",
            mime="application/json",
            use_container_width=True,
        )
    with col_c:
        flat_rows = []
        for row in data:
            for sn in store_names:
                entry = row.get(sn, {})
                flat_rows.append({
                    "Producto": row["product"],
                    "Tienda": sn,
                    "Precio": entry.get("price"),
                    "Nombre en tienda": entry.get("name"),
                    "URL": entry.get("url"),
                    "Error": entry.get("error"),
                })
        df_export = pd.DataFrame(flat_rows)
        st.download_button(
            "📥 Descargar CSV",
            data=df_export.to_csv(index=False, encoding="utf-8-sig"),
            file_name="comparacion_precios.csv",
            mime="text/csv",
            use_container_width=True,
        )
