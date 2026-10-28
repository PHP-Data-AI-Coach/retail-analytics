import base64
import io
import sqlite3
import flask
import matplotlib
import numpy as np
import pandas as pd
import seaborn as sns

matplotlib.use("Agg")
import matplotlib.pyplot as plt

app = flask.Flask(__name__)
DB_FILE = "commerce_db.sqlite"

# ==========================================================
# 🗄️ ИНИЦИЈАЛИЗАЦИЈА НА БАЗАТА И ПОЧЕТНИ ПОДАТОЦИ
# ==========================================================
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Спречување на foreign key рестрикции за едноставност кај студентите
    cursor.execute("PRAGMA foreign_keys = ON;")
    
    # 1. Табела за добавувачи
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS suppliers (
            supplier_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL
        )
    """)
    
    # 2. Табела за артикли
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS items (
            item_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            price REAL NOT NULL,
            supplier_id INTEGER,
            FOREIGN KEY (supplier_id) REFERENCES suppliers(supplier_id)
        )
    """)
    
    # 3. Табела за продавници
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS stores (
            store_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL
        )
    """)
    
    # 4. Табела за продажби (Сметки)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sales (
            invoice_id INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_number TEXT NOT NULL,
            date TEXT NOT NULL,
            store_id INTEGER,
            item_id INTEGER,
            quantity INTEGER NOT NULL,
            total_price REAL NOT NULL,
            FOREIGN KEY (store_id) REFERENCES stores(store_id),
            FOREIGN KEY (item_id) REFERENCES items(item_id)
        )
    """)
    
    # Полнење на почетни шифрарници доколку се празни
    cursor.execute("SELECT COUNT(*) FROM suppliers")
    if cursor.fetchone()[0] == 0:
        cursor.executemany("INSERT INTO suppliers (name) VALUES (?)", [("ТехноДистрибуција",), ("АгроМаркет",), ("Глобал Трејд",)])
        cursor.executemany("INSERT INTO stores (name) VALUES (?)", [("Продавница Скопје",), ("Продавница Битола",), ("Продавница Охрид",)])
        
        cursor.executemany("INSERT INTO items (name, price, supplier_id) VALUES (?, ?, ?)", [
            ("Лаптоп Core i5", 35000.0, 1),
            ("Смартфон 5G", 18500.0, 3),
            ("Безжични Слушалки", 2400.0, 1),
            ("Електричен бокал", 1600.0, 2),
            ("Кафе Апарат", 5400.0, 2)
        ])
        
        # Симулација на првични историски продажби за извештајот (последните 3 дена)
        dates = ["2026-10-26", "2026-10-27", "2026-10-28"]
        import random
        inv_counter = 1001
        for d in dates:
            for s_id in [1, 2, 3]: # за сите три продавници
                for _ in range(random.randint(2, 5)): # по неколку сметки
                    i_id = random.randint(1, 5)
                    qty = random.randint(1, 3)
                    cursor.execute("SELECT price FROM items WHERE item_id = ?", (i_id,))
                    u_price = cursor.fetchone()[0]
                    t_price = u_price * qty
                    cursor.execute("""
                        INSERT INTO sales (invoice_number, date, store_id, item_id, quantity, total_price)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (f"INV-{inv_counter}", d, s_id, i_id, qty, t_price))
                    inv_counter += 1
                    
    conn.commit()
    conn.close()

# Иницијализирај ја базата при старт
init_db()

# ==========================================================
# ⚙️ РУТИ И БИЗНИС ЛОГИКА
# ==========================================================
@app.route("/")
def dashboard():
    conn = sqlite3.connect(DB_FILE)
    
    # 1. Читање на основните шифрарници за формата
    df_items = pd.read_sql_query("SELECT item_id, name, price FROM items", conn)
    df_stores = pd.read_sql_query("SELECT store_id, name FROM stores", conn)
    
    # 2. Извлекување извештај за продажба по датум за 3-те продавници
    query_report = """
        SELECT 
            s.date AS "Датум",
            st.name AS "Продавница",
            SUM(s.total_price) AS "Вкупен_Промет"
        FROM sales s
        JOIN stores st ON s.store_id = st.store_id
        GROUP BY s.date, st.name
        ORDER BY s.date DESC, st.name ASC
    """
    df_report = pd.read_sql_query(query_report, conn)
    
    # Подготовка за Pivot табела во извештајот (побарано: табела по датум за 3 продавници)
    if not df_report.empty:
        df_pivot = df_report.pivot(index="Датум", columns="Продавница", values="Вкупен_Промет").fillna(0).reset_index()
        # Пресметка на тотал по датум
        df_pivot["Вкупно деноноќно"] = df_pivot.iloc[:, 1:].sum(axis=1)
    else:
        df_pivot = pd.DataFrame(columns=["Датум", "Продавница Скопје", "Продавница Битола", "Продавница Охрид", "Вкупно деноноќно"])

    # 3. Генерирање на Seaborn График (Извештај по датум и продавница)
    encoded_chart = ""
    if not df_report.empty:
        sns.set_theme(style="darkgrid")
        fig, ax = plt.subplots(figsize=(8, 4))
        
        # Креираме линиски или столбни дијаграм за тренд
        sns.barplot(
            x="Датум", 
            y="Вкупен_Промет", 
            hue="Продавница", 
            data=df_report, 
            palette="Set2",
            ax=ax
        )
        
        ax.set_title("Преглед на промет по датум и локација на продавница", fontsize=12, fontweight="bold", pad=12)
        ax.set_xlabel("Оперативен Датум", fontsize=10)
        ax.set_ylabel("Остварен Промет (ден.)", fontsize=10)
        plt.xticks(rotation=15)
        plt.tight_layout()
        
        buf = io.BytesIO()
        plt.savefig(buf, format="png", bbox_inches="tight")
        buf.seek(0)
        encoded_chart = base64.b64encode(buf.getvalue()).decode("utf-8")
        plt.close(fig)

    # Убаво форматирање на валутите во Pivot табелата пред приказ
    df_render = df_pivot.copy()
    for col in df_render.columns:
        if col != "Датум":
            df_render[col] = df_render[col].map("{:,.2f} ден.".format)

    conn.close()
    
    return flask.render_template(
        "commerce_dashboard1.html",
        items=df_items.to_dict(orient="records"),
        stores=df_stores.to_dict(orient="records"),
        report_table=df_render.to_html(classes="table table-bordered table-striped table-hover mt-2 text-center", index=False),
        chart_stream=encoded_chart
    )

@app.route("/add_invoice", methods=["POST"])
def add_invoice():
    # Преземање на параметрите од формата (Нова Сметка)
    invoice_number = flask.request.form.get("invoice_number")
    date = flask.request.form.get("date")
    store_id = int(flask.request.form.get("store_id"))
    item_id = int(flask.request.form.get("item_id"))
    quantity = int(flask.request.form.get("quantity"))
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Земи ја цената на артиклот за пресметка на тотал
    cursor.execute("SELECT price FROM items WHERE item_id = ?", (item_id,))
    price = cursor.fetchone()[0]
    total_price = price * quantity
    
    # Запиши ја новата сметка директно во релациската база
    cursor.execute("""
        INSERT INTO sales (invoice_number, date, store_id, item_id, quantity, total_price)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (invoice_number, date, store_id, item_id, quantity, total_price))
    
    conn.commit()
    conn.close()
    
    # Насочи го корисникот назад кон ажурираниот команден пул
    return flask.redirect(flask.url_style or "/")

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5001, debug=True)
	