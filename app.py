from __future__ import annotations

import io
import os
import sqlite3
import uuid
from datetime import date, timedelta
from pathlib import Path
from xml.sax.saxutils import escape

import pandas as pd
import streamlit as st
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

APP_NAME = "Atelier PVC Pro"
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = Path(os.environ.get("ATELIER_DB_PATH", str(DATA_DIR / "atelier.db")))

st.set_page_config(page_title=APP_NAME, page_icon="🪟", layout="wide")

# ----------------------------- Database -------------------------------------
def get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def init_db() -> None:
    with get_connection() as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS clients (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                phone TEXT NOT NULL DEFAULT '',
                email TEXT NOT NULL DEFAULT '',
                address TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS products (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                reference TEXT NOT NULL DEFAULT '',
                category TEXT NOT NULL,
                unit TEXT NOT NULL DEFAULT 'unité',
                price REAL NOT NULL DEFAULT 0,
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS quotes (
                id TEXT PRIMARY KEY,
                number TEXT NOT NULL UNIQUE,
                client_id TEXT NOT NULL,
                quote_date TEXT NOT NULL,
                validity_days INTEGER NOT NULL DEFAULT 30,
                status TEXT NOT NULL DEFAULT 'Brouillon',
                notes TEXT NOT NULL DEFAULT '',
                subtotal REAL NOT NULL DEFAULT 0,
                discount_percent REAL NOT NULL DEFAULT 0,
                discount_amount REAL NOT NULL DEFAULT 0,
                vat_percent REAL NOT NULL DEFAULT 19,
                vat_amount REAL NOT NULL DEFAULT 0,
                total REAL NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                FOREIGN KEY(client_id) REFERENCES clients(id)
            );
            CREATE TABLE IF NOT EXISTS quote_items (
                id TEXT PRIMARY KEY,
                quote_id TEXT NOT NULL,
                product_id TEXT,
                description TEXT NOT NULL,
                quantity REAL NOT NULL,
                unit TEXT NOT NULL DEFAULT 'unité',
                unit_price REAL NOT NULL,
                line_total REAL NOT NULL,
                FOREIGN KEY(quote_id) REFERENCES quotes(id) ON DELETE CASCADE,
                FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE SET NULL
            );
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            """
        )
        defaults = {
            "company_name": "Votre atelier PVC",
            "company_address": "",
            "company_phone": "",
            "company_email": "",
            "currency": "DA",
            "default_vat": "19",
        }
        for key, value in defaults.items():
            con.execute(
                "INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)",
                (key, value),
            )


def query_all(sql: str, params: tuple = ()) -> list[sqlite3.Row]:
    with get_connection() as con:
        return con.execute(sql, params).fetchall()


def query_one(sql: str, params: tuple = ()) -> sqlite3.Row | None:
    with get_connection() as con:
        return con.execute(sql, params).fetchone()


def execute(sql: str, params: tuple = ()) -> None:
    with get_connection() as con:
        con.execute(sql, params)


def get_settings() -> dict[str, str]:
    return {row["key"]: row["value"] for row in query_all("SELECT key, value FROM settings")}


def save_setting(key: str, value: str) -> None:
    execute(
        "INSERT INTO settings(key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )


def money(value: float, currency: str | None = None) -> str:
    current_currency = currency or get_settings().get("currency", "DA")
    return f"{value:,.2f}".replace(",", " ") + f" {current_currency}"


# ----------------------------- PDF ------------------------------------------
def make_quote_pdf(quote_id: str) -> bytes:
    quote = query_one(
        """SELECT q.*, c.name AS client_name, c.phone AS client_phone,
                  c.email AS client_email, c.address AS client_address
           FROM quotes q JOIN clients c ON c.id=q.client_id WHERE q.id=?""",
        (quote_id,),
    )
    if quote is None:
        raise ValueError("Devis introuvable.")
    items = query_all("SELECT * FROM quote_items WHERE quote_id=? ORDER BY rowid", (quote_id,))
    settings = get_settings()
    currency = settings.get("currency", "DA")
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4, rightMargin=18 * mm, leftMargin=18 * mm,
        topMargin=16 * mm, bottomMargin=18 * mm,
        title=f"Devis {quote['number']}", author=settings.get("company_name", APP_NAME),
    )
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="Company", parent=styles["Title"], fontSize=18, leading=22, textColor=colors.HexColor("#15324B"), alignment=0, spaceAfter=4))
    styles.add(ParagraphStyle(name="SmallText", parent=styles["BodyText"], fontSize=8.5, leading=11))
    styles.add(ParagraphStyle(name="RightText", parent=styles["BodyText"], alignment=TA_RIGHT))
    styles.add(ParagraphStyle(name="CenterText", parent=styles["BodyText"], alignment=TA_CENTER))
    story = []
    story.append(Paragraph(escape(settings.get("company_name", APP_NAME)), styles["Company"]))
    company_lines = [settings.get("company_address", ""), settings.get("company_phone", ""), settings.get("company_email", "")]
    for line in company_lines:
        if line.strip():
            story.append(Paragraph(escape(line), styles["SmallText"]))
    story.append(Spacer(1, 8 * mm))
    story.append(Paragraph(f"DEVIS N° {escape(quote['number'])}", styles["Heading1"]))
    story.append(Paragraph(f"Date : {escape(quote['quote_date'])} &nbsp;&nbsp;&nbsp; Validité : {quote['validity_days']} jours", styles["BodyText"]))
    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph("<b>Client</b>", styles["Heading3"]))
    story.append(Paragraph(escape(quote["client_name"]), styles["BodyText"]))
    for field in ("client_address", "client_phone", "client_email"):
        if quote[field]:
            story.append(Paragraph(escape(quote[field]), styles["SmallText"]))
    story.append(Spacer(1, 7 * mm))

    table_data = [["Désignation", "Qté", "Unité", "Prix unitaire", "Total"]]
    for item in items:
        table_data.append([
            Paragraph(escape(item["description"]), styles["SmallText"]),
            f"{item['quantity']:g}", item["unit"],
            f"{item['unit_price']:,.2f} {currency}".replace(",", " "),
            f"{item['line_total']:,.2f} {currency}".replace(",", " "),
        ])
    items_table = Table(table_data, colWidths=[75 * mm, 16 * mm, 19 * mm, 31 * mm, 31 * mm], repeatRows=1)
    items_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#15324B")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#D9E1E8")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F5F8FA")]),
    ]))
    story.append(items_table)
    story.append(Spacer(1, 5 * mm))
    discount_label = f"Remise ({quote['discount_percent']:.2f} %)"
    totals_data = [
        ["Sous-total", f"{quote['subtotal']:,.2f} {currency}".replace(",", " ")],
        [discount_label, f"- {quote['discount_amount']:,.2f} {currency}".replace(",", " ")],
        [f"TVA ({quote['vat_percent']:.2f} %)", f"{quote['vat_amount']:,.2f} {currency}".replace(",", " ")],
        ["TOTAL TTC", f"{quote['total']:,.2f} {currency}".replace(",", " ")],
    ]
    totals = Table(totals_data, colWidths=[45 * mm, 45 * mm], hAlign="RIGHT")
    totals.setStyle(TableStyle([
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("LINEABOVE", (0, -1), (-1, -1), 1, colors.HexColor("#15324B")),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(totals)
    if quote["notes"].strip():
        story.append(Spacer(1, 5 * mm))
        story.append(Paragraph("<b>Notes et conditions</b>", styles["Heading3"]))
        story.append(Paragraph(escape(quote["notes"]).replace("\n", "<br/>"), styles["BodyText"]))
    story.append(Spacer(1, 12 * mm))
    story.append(Paragraph("Bon pour accord : ________________________________", styles["BodyText"]))
    story.append(Spacer(1, 10 * mm))
    story.append(Paragraph("Signature et cachet", styles["SmallText"]))
    doc.build(story)
    return buffer.getvalue()


# ----------------------------- Initialization -------------------------------
init_db()
settings = get_settings()

# Keep quote cart local to the browser session.
if "quote_cart" not in st.session_state:
    st.session_state.quote_cart = []

# ----------------------------- Navigation -----------------------------------
st.title("🪟 Atelier PVC Pro")
st.caption("Gestion des clients, du catalogue et des devis")
with st.sidebar:
    st.markdown("## Atelier PVC Pro")
    page = st.radio(
        "Navigation",
        ["Tableau de bord", "Clients", "Catalogue", "Nouveau devis", "Historique des devis", "Paramètres"],
        label_visibility="collapsed",
    )
    st.divider()
    st.caption("Version initiale — stockage SQLite")


# ----------------------------- Dashboard ------------------------------------
if page == "Tableau de bord":
    st.header("Tableau de bord")
    nb_clients = query_one("SELECT COUNT(*) AS n FROM clients")["n"]
    nb_products = query_one("SELECT COUNT(*) AS n FROM products WHERE active=1")["n"]
    nb_quotes = query_one("SELECT COUNT(*) AS n FROM quotes")["n"]
    total_quotes = query_one("SELECT COALESCE(SUM(total),0) AS total FROM quotes WHERE status!='Annulé'")["total"]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Clients", nb_clients)
    c2.metric("Articles au catalogue", nb_products)
    c3.metric("Devis créés", nb_quotes)
    c4.metric("Montant des devis", money(float(total_quotes), settings.get("currency", "DA")))
    st.subheader("Derniers devis")
    recent = query_all(
        """SELECT q.number AS 'N° devis', q.quote_date AS Date, c.name AS Client,
                  q.status AS Statut, q.total AS Total
           FROM quotes q JOIN clients c ON c.id=q.client_id
           ORDER BY q.created_at DESC LIMIT 10"""
    )
    if recent:
        df = pd.DataFrame([dict(row) for row in recent])
        df["Total"] = df["Total"].map(lambda v: money(float(v)))
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("Aucun devis pour le moment. Commence par créer un client, puis un devis.")
    st.warning("Sur Streamlit Cloud, SQLite local peut être perdu lors d'une reconstruction ou d'une réinitialisation. Configure une base de données distante avant d'y stocker des données importantes.")


# ----------------------------- Clients --------------------------------------
elif page == "Clients":
    st.header("👥 Clients")
    tab_new, tab_list = st.tabs(["Ajouter un client", "Liste des clients"])
    with tab_new:
        with st.form("add_client", clear_on_submit=True):
            name = st.text_input("Nom ou raison sociale *")
            phone = st.text_input("Téléphone")
            email = st.text_input("E-mail")
            address = st.text_area("Adresse")
            submitted = st.form_submit_button("Enregistrer le client", type="primary")
        if submitted:
            if not name.strip():
                st.error("Le nom du client est obligatoire.")
            else:
                execute(
                    "INSERT INTO clients(id,name,phone,email,address,created_at) VALUES(?,?,?,?,?,?)",
                    (str(uuid.uuid4()), name.strip(), phone.strip(), email.strip(), address.strip(), date.today().isoformat()),
                )
                st.success("Client enregistré.")
                st.rerun()
    with tab_list:
        search = st.text_input("Rechercher un client", key="client_search")
        clients = query_all(
            """SELECT name AS 'Nom', phone AS 'Téléphone', email AS 'E-mail',
                      address AS 'Adresse', created_at AS 'Créé le'
               FROM clients WHERE name LIKE ? OR phone LIKE ? OR email LIKE ?
               ORDER BY name""",
            (f"%{search}%", f"%{search}%", f"%{search}%"),
        )
        if clients:
            st.dataframe(pd.DataFrame([dict(row) for row in clients]), use_container_width=True, hide_index=True)
            csv_data = pd.DataFrame([dict(row) for row in clients]).to_csv(index=False).encode("utf-8-sig")
            st.download_button("Exporter les clients en CSV", csv_data, file_name="clients.csv", mime="text/csv")
        else:
            st.info("Aucun client correspondant.")


# ----------------------------- Catalogue ------------------------------------
elif page == "Catalogue":
    st.header("📦 Catalogue des articles")
    st.caption("Ajoute les articles que tu utilises dans les devis : fenêtres, portes, profils, vitrages, accessoires, pose, transport, etc.")
    with st.form("add_product", clear_on_submit=True):
        name = st.text_input("Désignation *")
        c1, c2, c3 = st.columns(3)
        category = c1.selectbox("Catégorie", ["Fenêtre PVC", "Porte PVC", "Profilé", "Vitrage", "Accessoire", "Quincaillerie", "Pose", "Transport", "Autre"])
        reference = c2.text_input("Référence (facultatif)")
        unit = c3.selectbox("Unité", ["unité", "m²", "mètre linéaire", "lot", "heure", "forfait"])
        price = st.number_input("Prix unitaire de vente", min_value=0.0, value=0.0, step=100.0)
        submitted = st.form_submit_button("Ajouter au catalogue", type="primary")
    if submitted:
        if not name.strip():
            st.error("La désignation est obligatoire.")
        else:
            execute(
                "INSERT INTO products(id,name,reference,category,unit,price,active,created_at) VALUES(?,?,?,?,?,?,1,?)",
                (str(uuid.uuid4()), name.strip(), reference.strip(), category, unit, float(price), date.today().isoformat()),
            )
            st.success("Article ajouté au catalogue.")
            st.rerun()
    st.subheader("Articles enregistrés")
    products = query_all("SELECT id,name AS 'Désignation',reference AS 'Référence',category AS 'Catégorie',unit AS 'Unité',price AS 'Prix unitaire' FROM products WHERE active=1 ORDER BY name")
    if products:
        df = pd.DataFrame([dict(row) for row in products])
        df["Prix unitaire"] = df["Prix unitaire"].map(lambda v: money(float(v)))
        st.dataframe(df.drop(columns=["id"]), use_container_width=True, hide_index=True)
    else:
        st.info("Le catalogue est vide. Ajoute un premier article ci-dessus.")


# ----------------------------- New quote ------------------------------------
elif page == "Nouveau devis":
    st.header("🧾 Créer un devis")
    clients = query_all("SELECT id,name FROM clients ORDER BY name")
    products = query_all("SELECT id,name,reference,unit,price FROM products WHERE active=1 ORDER BY name")
    if not clients:
        st.warning("Crée d'abord au moins un client dans la page Clients.")
    else:
        client_options = {f"{c['name']}": c["id"] for c in clients}
        client_label = st.selectbox("Client du devis", list(client_options.keys()), key="quote_client")
        client_id = client_options[client_label]
        previous_cart_client = st.session_state.get("quote_cart_client")
        if previous_cart_client and previous_cart_client != client_id and st.session_state.quote_cart:
            st.warning("Le client a changé. Vide le panier précédent avant de préparer un devis pour un autre client.")
        st.subheader("Ajouter des lignes au devis")
        if products:
            with st.expander("Ajouter un article du catalogue", expanded=True):
                product_options = {f"{p['name']} | {p['price']:.2f} {settings.get('currency','DA')}/{p['unit']}": p for p in products}
                selected_product_label = st.selectbox("Article", list(product_options.keys()))
                selected_product = product_options[selected_product_label]
                qty1 = st.number_input("Quantité de l'article", min_value=0.01, value=1.0, step=1.0, key="catalog_qty")
                if st.button("Ajouter l'article au devis", type="primary"):
                    if st.session_state.get("quote_cart_client") not in (None, client_id):
                        st.session_state.quote_cart = []
                    st.session_state.quote_cart_client = client_id
                    st.session_state.quote_cart.append({
                        "product_id": selected_product["id"],
                        "description": selected_product["name"],
                        "quantity": float(qty1),
                        "unit": selected_product["unit"],
                        "unit_price": float(selected_product["price"]),
                    })
                    st.rerun()
        with st.expander("Ajouter une ligne personnalisée"):
            with st.form("add_custom_line", clear_on_submit=True):
                custom_description = st.text_input("Désignation *")
                c1, c2, c3 = st.columns(3)
                custom_qty = c1.number_input("Quantité", min_value=0.01, value=1.0, step=1.0)
                custom_unit = c2.selectbox("Unité", ["unité", "m²", "mètre linéaire", "lot", "heure", "forfait"])
                custom_price = c3.number_input("Prix unitaire", min_value=0.0, value=0.0, step=100.0)
                add_custom = st.form_submit_button("Ajouter cette ligne")
            if add_custom:
                if not custom_description.strip():
                    st.error("La désignation est obligatoire.")
                else:
                    if st.session_state.get("quote_cart_client") not in (None, client_id):
                        st.session_state.quote_cart = []
                    st.session_state.quote_cart_client = client_id
                    st.session_state.quote_cart.append({
                        "product_id": None,
                        "description": custom_description.strip(),
                        "quantity": float(custom_qty),
                        "unit": custom_unit,
                        "unit_price": float(custom_price),
                    })
                    st.rerun()

        st.subheader("Contenu du devis")
        cart = st.session_state.quote_cart
        if cart:
            cart_view = [{
                "Ligne": i + 1,
                "Désignation": row["description"],
                "Quantité": row["quantity"],
                "Unité": row["unit"],
                "Prix unitaire": row["unit_price"],
                "Total": row["quantity"] * row["unit_price"],
            } for i, row in enumerate(cart)]
            st.dataframe(pd.DataFrame(cart_view), use_container_width=True, hide_index=True)
            col_remove, col_clear = st.columns([1, 3])
            with col_remove:
                remove_index = st.selectbox("Supprimer la ligne", list(range(1, len(cart) + 1)), key="remove_line")
                if st.button("Supprimer la ligne sélectionnée"):
                    st.session_state.quote_cart.pop(remove_index - 1)
                    if not st.session_state.quote_cart:
                        st.session_state.quote_cart_client = None
                    st.rerun()
            with col_clear:
                if st.button("Vider le devis"):
                    st.session_state.quote_cart = []
                    st.session_state.quote_cart_client = None
                    st.rerun()

            subtotal = sum(row["quantity"] * row["unit_price"] for row in cart)
            col1, col2, col3 = st.columns(3)
            discount_percent = col1.number_input("Remise (%)", min_value=0.0, max_value=100.0, value=0.0, step=1.0)
            vat_default = float(settings.get("default_vat", "19"))
            vat_percent = col2.number_input("TVA (%)", min_value=0.0, max_value=100.0, value=vat_default, step=1.0)
            validity_days = col3.number_input("Validité (jours)", min_value=1, max_value=365, value=30, step=1)
            notes = st.text_area("Notes / conditions de vente", placeholder="Délais, modalités de paiement, livraison, pose, etc.")
            discount_amount = subtotal * discount_percent / 100
            taxable = subtotal - discount_amount
            vat_amount = taxable * vat_percent / 100
            total = taxable + vat_amount
            st.markdown("#### Récapitulatif")
            t1, t2, t3 = st.columns(3)
            t1.metric("Sous-total", money(subtotal))
            t2.metric("TVA", money(vat_amount))
            t3.metric("Total TTC", money(total))
            if st.button("💾 Enregistrer le devis", type="primary", use_container_width=True):
                if st.session_state.get("quote_cart_client") not in (None, client_id):
                    st.error("Le panier appartient à un autre client. Vide-le et recommence.")
                else:
                    today = date.today()
                    count_row = query_one("SELECT COUNT(*) AS n FROM quotes WHERE quote_date=?", (today.isoformat(),))
                    number = f"DEV-{today:%Y%m%d}-{int(count_row['n']) + 1:03d}"
                    quote_id = str(uuid.uuid4())
                    try:
                        with get_connection() as con:
                            con.execute(
                                """INSERT INTO quotes(id,number,client_id,quote_date,validity_days,status,notes,subtotal,discount_percent,discount_amount,vat_percent,vat_amount,total,created_at)
                                   VALUES(?,?,?,?,?,'Envoyé',?,?,?,?,?,?,?,?)""",
                                (quote_id, number, client_id, today.isoformat(), int(validity_days), notes.strip(), subtotal, discount_percent, discount_amount, vat_percent, vat_amount, total, today.isoformat()),
                            )
                            for row in cart:
                                line_total = row["quantity"] * row["unit_price"]
                                con.execute(
                                    "INSERT INTO quote_items(id,quote_id,product_id,description,quantity,unit,unit_price,line_total) VALUES(?,?,?,?,?,?,?,?)",
                                    (str(uuid.uuid4()), quote_id, row["product_id"], row["description"], row["quantity"], row["unit"], row["unit_price"], line_total),
                                )
                        st.session_state.quote_cart = []
                        st.session_state.quote_cart_client = None
                        st.session_state.last_saved_quote = quote_id
                        st.success(f"Devis {number} enregistré.")
                        st.rerun()
                    except sqlite3.Error as err:
                        st.error(f"Erreur d'enregistrement du devis : {err}")
        else:
            st.info("Ajoute au moins une ligne pour pouvoir enregistrer le devis.")

    last_quote_id = st.session_state.get("last_saved_quote")
    if last_quote_id:
        saved = query_one("SELECT number FROM quotes WHERE id=?", (last_quote_id,))
        if saved:
            st.download_button(
                "📄 Télécharger le dernier devis en PDF",
                data=make_quote_pdf(last_quote_id),
                file_name=f"{saved['number']}.pdf",
                mime="application/pdf",
                use_container_width=True,
            )


# ----------------------------- Quote history --------------------------------
elif page == "Historique des devis":
    st.header("📚 Historique des devis")
    quotes = query_all(
        """SELECT q.id, q.number AS 'N° devis', q.quote_date AS Date, c.name AS Client,
                  q.status AS Statut, q.subtotal AS 'Sous-total', q.vat_amount AS TVA, q.total AS Total
           FROM quotes q JOIN clients c ON c.id=q.client_id ORDER BY q.created_at DESC"""
    )
    if not quotes:
        st.info("Aucun devis enregistré.")
    else:
        df = pd.DataFrame([dict(row) for row in quotes])
        display = df.drop(columns=["id"]).copy()
        for col in ("Sous-total", "TVA", "Total"):
            display[col] = display[col].map(lambda v: money(float(v)))
        st.dataframe(display, use_container_width=True, hide_index=True)
        options = {f"{q['N° devis']} — {q['Client']} — {money(float(q['Total']))}": q["id"] for q in quotes}
        selected_label = st.selectbox("Choisir un devis pour voir ou télécharger le PDF", list(options.keys()))
        selected_id = options[selected_label]
        selected = query_one("SELECT * FROM quotes WHERE id=?", (selected_id,))
        lines = query_all("SELECT description AS 'Désignation',quantity AS 'Quantité',unit AS 'Unité',unit_price AS 'Prix unitaire',line_total AS Total FROM quote_items WHERE quote_id=? ORDER BY rowid", (selected_id,))
        st.subheader("Détail du devis")
        st.write(f"**Statut actuel :** {selected['status']}")
        if lines:
            st.dataframe(pd.DataFrame([dict(line) for line in lines]), use_container_width=True, hide_index=True)
        new_status = st.selectbox("Modifier le statut", ["Brouillon", "Envoyé", "Accepté", "Refusé", "Annulé"], index=["Brouillon", "Envoyé", "Accepté", "Refusé", "Annulé"].index(selected["status"]) if selected["status"] in ["Brouillon", "Envoyé", "Accepté", "Refusé", "Annulé"] else 1)
        if st.button("Enregistrer le statut"):
            execute("UPDATE quotes SET status=? WHERE id=?", (new_status, selected_id))
            st.success("Statut du devis mis à jour.")
            st.rerun()
        st.download_button(
            "📄 Télécharger ce devis en PDF",
            data=make_quote_pdf(selected_id),
            file_name=f"{selected['number']}.pdf",
            mime="application/pdf",
            type="primary",
        )
        quote_csv = pd.DataFrame([dict(line) for line in lines]).to_csv(index=False).encode("utf-8-sig")
        st.download_button("Exporter les lignes du devis en CSV", quote_csv, file_name=f"{selected['number']}.csv", mime="text/csv")


# ----------------------------- Settings --------------------------------------
elif page == "Paramètres":
    st.header("⚙️ Paramètres de l'atelier")
    current = get_settings()
    with st.form("settings_form"):
        company_name = st.text_input("Nom de l'entreprise", value=current.get("company_name", APP_NAME))
        company_address = st.text_area("Adresse", value=current.get("company_address", ""))
        c1, c2 = st.columns(2)
        company_phone = c1.text_input("Téléphone", value=current.get("company_phone", ""))
        company_email = c2.text_input("E-mail", value=current.get("company_email", ""))
        c3, c4 = st.columns(2)
        currency = c3.selectbox("Devise", ["DA", "DZD", "EUR", "USD"], index=["DA", "DZD", "EUR", "USD"].index(current.get("currency", "DA")) if current.get("currency", "DA") in ["DA", "DZD", "EUR", "USD"] else 0)
        default_vat = c4.number_input("TVA par défaut (%)", min_value=0.0, max_value=100.0, value=float(current.get("default_vat", "19")), step=1.0)
        save = st.form_submit_button("Enregistrer les paramètres", type="primary")
    if save:
        for key, value in {
            "company_name": company_name.strip() or APP_NAME,
            "company_address": company_address.strip(),
            "company_phone": company_phone.strip(),
            "company_email": company_email.strip(),
            "currency": currency,
            "default_vat": str(default_vat),
        }.items():
            save_setting(key, value)
        st.success("Paramètres enregistrés.")
        st.rerun()
    st.divider()
    st.subheader("Base de données locale")
    st.write(f"Chemin du fichier SQLite : `{DB_PATH}`")
    st.warning("Ne place pas une vraie base de données contenant des clients dans GitHub. Sur Streamlit Cloud, configure ensuite une base PostgreSQL/Supabase pour préserver les données à long terme.")
