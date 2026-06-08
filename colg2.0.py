import sqlite3
import tkinter as tk
from tkinter import ttk, messagebox
import time
import threading
from datetime import datetime
import os
import random
import webbrowser
import sys

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service

# ===================== 配置 =====================
DB_PATH = os.path.join(os.path.expanduser("~/Documents"), "colg搜索工具", "colg_posts.db")
BASE_URL = "https://bbs.colg.cn/forum-466-{}.html"
CRAWL_PAGE_COUNT = 20
# ==================================================

def get_exe_root():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS posts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT,
        link TEXT UNIQUE,
        post_time TEXT
    )''')
    conn.commit()
    conn.close()

def random_delay():
    time.sleep(random.uniform(1.5, 2.5))

# ===================== 后台隐身Chrome抓取 =====================
def start_crawl(progress_var, percent_label, start_btn):
    start_btn.config(state=tk.DISABLED)
    progress_var.set(0)
    percent_label.config(text="0%")
    total = 0
    repeat = 0

    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("DELETE FROM posts")
        conn.commit()
        conn.close()

        # ===================== Chrome 隐身模式 =====================
        chrome_options = Options()

        # 核心：后台无头 + 完全看不见
        chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--window-size=1920,1080")

        # 防崩溃
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-extensions")

        # 防反爬关键
        chrome_options.add_experimental_option('excludeSwitches', ['enable-logging', 'enable-automation'])
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        chrome_options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")

        # 自动驱动，无需手动放 chromedriver
        driver = webdriver.Chrome(options=chrome_options)

        # ===================== 开始爬取 =====================
        for page in range(1, CRAWL_PAGE_COUNT + 1):
            driver.get(BASE_URL.format(page))
            WebDriverWait(driver, 20).until(
                EC.presence_of_all_elements_located((By.CSS_SELECTOR, "tbody[id^='normalthread_'] tr"))
            )
            time.sleep(1.5)

            items = driver.find_elements(By.CSS_SELECTOR, "tbody[id^='normalthread_'] tr")
            posts = []
            for item in items:
                try:
                    a = item.find_element(By.CSS_SELECTOR, "a.s.xst")
                    t_elem = item.find_element(By.CSS_SELECTOR, "td.by em span")
                    title = a.text.strip()
                    link = a.get_attribute("href")
                    post_time = t_elem.text.strip() if t_elem else ""
                    if title and link:
                        posts.append((title, link, post_time))
                except Exception:
                    continue

            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            for p in posts:
                try:
                    c.execute("INSERT INTO posts (title, link, post_time) VALUES (?,?,?)", p)
                    total += 1
                except sqlite3.IntegrityError:
                    repeat += 1
            conn.commit()
            conn.close()

            progress = (page / CRAWL_PAGE_COUNT) * 100
            progress_var.set(progress)
            percent_label.config(text=f"{int(progress)}%")
            random_delay()

        driver.quit()
        messagebox.showinfo("完成", f"抓取完毕\n新增：{total}\n去重：{repeat}")

    except Exception as e:
        messagebox.showerror("错误", str(e))
    finally:
        start_btn.config(state=tk.NORMAL)

# ===================== 搜索 =====================
def parse_post_time(s):
    fmts = ["%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y年%m月%d日 %H:%M", "%Y年%m月%d日"]
    for f in fmts:
        try:
            return datetime.strptime(s.strip(), f)
        except:
            continue
    return None

def do_search(keyword, frame, enable_date, year_val, month_val, day_val):
    for w in frame.winfo_children():
        w.destroy()

    if not os.path.exists(DB_PATH):
        ttk.Label(frame, text="请先读取帖子数据").pack()
        return

    kw = keyword.strip()
    if not kw:
        messagebox.showwarning("提示", "请输入关键词")
        return

    filter_date = None
    if enable_date.get():
        try:
            filter_date = datetime(int(year_val.get()), int(month_val.get()), int(day_val.get()))
        except:
            messagebox.showerror("错误", "日期格式错误")
            return

    words = [x.strip() for x in kw.split()]
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    cond = " AND ".join(["title LIKE ?"] * len(words))
    params = [f"%{w}%" for w in words]
    c.execute(f"SELECT title, link, post_time FROM posts WHERE {cond} ORDER BY post_time DESC", params)
    rows = c.fetchall()
    conn.close()

    if filter_date:
        rows = [r for r in rows if parse_post_time(r[2]) and parse_post_time(r[2]) >= filter_date]

    if not rows:
        ttk.Label(frame, text="无匹配结果").pack()
        return

    canvas = tk.Canvas(frame)
    scroll = ttk.Scrollbar(frame, orient="vertical", command=canvas.yview)
    content = tk.Frame(canvas)
    content.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.create_window((0, 0), window=content, anchor="nw")
    canvas.configure(yscrollcommand=scroll.set)

    canvas.pack(side="left", fill="both", expand=True)
    scroll.pack(side="right", fill="y")

    for idx, (title, link, t_str) in enumerate(rows, 1):
        lbl = tk.Label(content, text=f"{idx}. {title} [{t_str}]", cursor="hand2", fg="#0066cc")
        lbl.pack(anchor="w", padx=10, pady=3)
        lbl.bind("<Button-1>", lambda e, u=link: webbrowser.open(u))

# ===================== 界面 =====================
def main():
    root = tk.Tk()
    root.title("COLG 果冻勇者colg论坛补丁搜索工具2.2")
    root.geometry("950x650")
    init_db()

    top_frame = tk.Frame(root)
    top_frame.pack(fill="x", padx=10, pady=10)

    progress_var = tk.DoubleVar()
    percent_label = ttk.Label(top_frame, text="0%")
    
    start_btn = ttk.Button(top_frame, text="读取帖子数据",
        command=lambda: threading.Thread(target=start_crawl, args=(progress_var, percent_label, start_btn), daemon=True).start())
    start_btn.pack(side="left", padx=5)

    ttk.Progressbar(top_frame, variable=progress_var, length=400).pack(side="left", padx=10)
    percent_label.pack(side="left")

    # 搜索栏
    search_bar = tk.Frame(root)
    search_bar.pack(fill="x", padx=10, pady=5)

    date_enable = tk.BooleanVar()
    ttk.Checkbutton(search_bar, text="只显示此日期之后：", variable=date_enable).grid(row=0, column=0, padx=5)

    yv = tk.StringVar(value="2026")
    mv = tk.StringVar(value="4")
    dv = tk.StringVar(value="23")

    ttk.Combobox(search_bar, textvariable=yv, width=5, values=[str(x) for x in range(2023,2030)]).grid(row=0,column=1)
    ttk.Label(search_bar, text="年").grid(row=0,column=2)
    ttk.Combobox(search_bar, textvariable=mv, width=3, values=[f"{i}" for i in range(1,13)]).grid(row=0,column=3)
    ttk.Label(search_bar, text="月").grid(row=0,column=4)
    ttk.Combobox(search_bar, textvariable=dv, width=3, values=[f"{i}" for i in range(1,32)]).grid(row=0,column=5)
    ttk.Label(search_bar, text="日").grid(row=0,column=6)

    search_var = tk.StringVar()
    search_entry = ttk.Entry(search_bar, textvariable=search_var, font=("",12))
    search_entry.grid(row=1, column=0, columnspan=7, sticky="ew", pady=3)
    ttk.Button(search_bar, text="搜索", 
        command=lambda: do_search(search_var.get(), result_frame, date_enable, yv, mv, dv)).grid(row=1, column=7)
    search_bar.grid_columnconfigure(0, weight=1)

    result_frame = tk.Frame(root)
    result_frame.pack(fill="both", expand=True, padx=10, pady=5)

    root.mainloop()

if __name__ == "__main__":
    main()