import requests
import sqlite3
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
from bs4 import BeautifulSoup
import webbrowser
import time
import threading
from datetime import datetime
import os  # 新增：处理路径和文件夹创建

# 核心配置
BASE_URL = "https://bbs.colg.cn/forum-466-{}.html"
TARGET_DATE = datetime(2025, 12, 11)  # 筛选临界日期
DEFAULT_PAGE = 50  # 默认爬取页数

# ========== 新增：数据库路径配置 ==========
def get_db_path():
    """获取数据库文件路径（我的文档/colg搜索工具/colg_posts.db）"""
    # 获取「我的文档」路径（跨平台兼容）
    documents_path = os.path.expanduser("~/Documents")  # Windows下自动转为"我的文档"路径
    # 拼接专属文件夹路径
    colg_folder = os.path.join(documents_path, "colg搜索工具")
    # 确保文件夹存在（不存在则创建）
    if not os.path.exists(colg_folder):
        os.makedirs(colg_folder)
    # 拼接数据库文件路径
    db_path = os.path.join(colg_folder, "colg_posts.db")
    return db_path

# 初始化数据库（使用新路径）
def init_db():
    """创建/更新帖子数据表，包含标题、链接、发布时间"""
    db_path = get_db_path()  # 获取新的数据库路径
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS posts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        link TEXT NOT NULL UNIQUE,
        post_time TEXT
    )
    ''')
    conn.commit()
    conn.close()

# 增强版时间解析（兼容更多格式）
def parse_post_time(time_str):
    """将论坛时间字符串转为datetime对象，失败返回None"""
    if not time_str or time_str.strip() == "":
        return None
    # 支持的时间格式列表
    time_formats = ["%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y年%m月%d日 %H:%M", "%Y年%m月%d日"]
    for fmt in time_formats:
        try:
            return datetime.strptime(time_str.strip(), fmt)
        except:
            continue
    return None

# 爬取单页帖子数据（修改数据库路径）
def crawl_page(page_num):
    """爬取指定页码的帖子，返回爬取结果描述"""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        # 请求页面
        response = requests.get(BASE_URL.format(page_num), headers=headers, timeout=10)
        response.encoding = "utf-8"
        soup = BeautifulSoup(response.text, "html.parser")
        
        # 提取帖子列表
        post_items = soup.select("tbody[id^='normalthread_']")
        posts = []
        for item in post_items:
            # 提取标题和链接
            title_tag = item.select_one("a.s.xst")
            if not title_tag:
                continue
            title = title_tag.get_text(strip=True)
            href = title_tag.get("href", "")
            link = href if href.startswith("http") else f"https://bbs.colg.cn/{href}"
            
            # 提取发布时间
            time_tag = item.select_one("td.by em") or item.select_one("td.by")
            post_time_str = time_tag.get_text(strip=True) if time_tag else ""
            
            posts.append((title, link, post_time_str))
        
        # 保存到数据库（去重，使用新路径）
        if posts:
            db_path = get_db_path()
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            for title, link, post_time_str in posts:
                cursor.execute(
                    "INSERT OR IGNORE INTO posts (title, link, post_time) VALUES (?,?,?)",
                    (title, link, post_time_str)
                )
            conn.commit()
            conn.close()
        
        return f"第{page_num}页：成功爬取 {len(posts)} 条帖子"
    
    except Exception as e:
        return f"第{page_num}页：爬取失败 - {str(e)[:50]}"

# 批量爬取指定页数（无修改，依赖crawl_page的路径）
def crawl_all_pages(status_text, page_entry):
    """在子线程中执行批量爬取，避免界面卡死"""
    # 校验输入页数
    try:
        max_page = int(page_entry.get().strip())
        if max_page < 1:
            messagebox.showerror("输入错误", "爬取页数必须≥1！")
            return
    except ValueError:
        messagebox.showerror("输入错误", "请输入有效的正整数页数！")
        return
    
    # 开始爬取
    status_text.delete(1.0, tk.END)
    status_text.insert(tk.END, f"📌 开始爬取前 {max_page} 页数据...\n")
    status_text.update()
    
    for page in range(1, max_page + 1):
        result = crawl_page(page)
        status_text.insert(tk.END, result + "\n")
        status_text.see(tk.END)  # 自动滚动到最新行
        status_text.update()
        time.sleep(0.8)  # 降低请求频率，避免被封
    
    status_text.insert(tk.END, "\n✅ 所有页面爬取完成！")

# 搜索功能（修改数据库路径）
def search_posts(keyword, result_frame, only_after_var):
    """
    多关键词模糊搜索 + 时间筛选
    :param keyword: 搜索关键词
    :param result_frame: 结果展示容器
    :param only_after_var: 仅看2025.12.11后帖子的开关变量
    """
    # 清空原有结果
    for widget in result_frame.winfo_children():
        widget.destroy()
    
    # 校验关键词
    kw = keyword.strip()
    if not kw:
        messagebox.showwarning("提示", "请输入搜索关键词！")
        return
    
    # 拆分多关键词（空格分隔/自动双字拆分）
    keyword_list = [w.strip() for w in kw.split() if w.strip()]
    if not keyword_list:
        # 无空格时按双字拆分（如"剑魂技能"→["剑魂","技能"]）
        keyword_list = [kw[i:i+2] for i in range(0, len(kw), 2) if kw[i:i+2]]
    
    # 构建SQL查询条件（使用新数据库路径）
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    # 基础条件：标题包含所有关键词
    base_cond = " AND ".join(["title LIKE ?"] * len(keyword_list))
    params = [f"%{w}%" for w in keyword_list]
    
    # 新增：时间筛选条件
    if only_after_var.get():
        # 先查询所有符合关键词的帖子，再在内存中筛选时间（兼容无法解析的时间）
        cursor.execute(f"SELECT title, link, post_time FROM posts WHERE {base_cond} ORDER BY post_time DESC", params)
        all_results = cursor.fetchall()
        # 筛选2025.12.11之后的帖子
        filtered_results = []
        for title, link, t_str in all_results:
            t_obj = parse_post_time(t_str)
            if t_obj and t_obj >= TARGET_DATE:
                filtered_results.append((title, link, t_str))
        results = filtered_results
    else:
        # 不筛选时间，直接按时间倒序查询
        cursor.execute(f"SELECT title, link, post_time FROM posts WHERE {base_cond} ORDER BY post_time DESC", params)
        results = cursor.fetchall()
    conn.close()
    
    # 展示结果
    if not results:
        tip = "未找到匹配的帖子" if not only_after_var.get() else "未找到2025-12-11之后的匹配帖子"
        ttk.Label(result_frame, text=tip).pack(pady=10)
        return
    
    # 创建滚动结果区域
    canvas = tk.Canvas(result_frame)
    scrollbar = ttk.Scrollbar(result_frame, orient="vertical", command=canvas.yview)
    scrollable_frame = ttk.Frame(canvas)
    scrollable_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
    canvas.configure(yscrollcommand=scrollbar.set)
    
    # 逐个添加搜索结果
    for idx, (title, link, t_str) in enumerate(results, 1):
        # 确定文字颜色
        t_obj = parse_post_time(t_str)
        if t_obj:
            color = "red" if t_obj < TARGET_DATE else "blue"
        else:
            color = "black"
        
        # 可点击的标题标签
        lbl = tk.Label(
            scrollable_frame,
            text=f"{idx}. {title} 【发布时间：{t_str or '未知'}】",
            fg=color,
            cursor="hand2",
            font=("微软雅黑", 9)
        )
        lbl.pack(anchor="w", padx=10, pady=2)
        # 绑定点击跳转事件
        lbl.bind("<Button-1>", lambda e, url=link: webbrowser.open_new(url))
    
    canvas.pack(side="left", fill="both", expand=True)
    scrollbar.pack(side="right", fill="y")

# 清空数据库功能（修改数据库路径）
def clear_database(status_text):
    """清空数据库所有帖子数据"""
    if messagebox.askyesno("确认", "是否确定清空所有爬取的帖子数据？"):
        try:
            db_path = get_db_path()
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("DELETE FROM posts")
            conn.commit()
            conn.close()
            status_text.insert(tk.END, "\n🗑️ 数据库已清空！\n")
            status_text.see(tk.END)
        except Exception as e:
            messagebox.showerror("错误", f"清空失败：{str(e)}")

# 主界面创建
def create_main_gui():
    """创建完整的软件界面"""
    root = tk.Tk()
    root.title("COLG论坛帖子搜索工具1.0 by果冻勇者")
    root.geometry("950x700")
    root.resizable(True, True)
    
    # 初始化数据库
    init_db()
    
    # ========== 爬取区域 ==========
    crawl_frame = ttk.LabelFrame(root, text="📥 数据爬取")
    crawl_frame.pack(fill="x", padx=10, pady=5)
    
    # 页数输入行
    page_ctrl_frame = ttk.Frame(crawl_frame)
    page_ctrl_frame.pack(fill="x", padx=5, pady=3)
    ttk.Label(page_ctrl_frame, text="爬取页数：").pack(side="left")
    page_entry = ttk.Entry(page_ctrl_frame, width=8)
    page_entry.insert(0, DEFAULT_PAGE)
    page_entry.pack(side="left", padx=5)
    ttk.Label(page_ctrl_frame, text="页（默认50页）").pack(side="left")
    
    # 爬取/清空按钮
    btn_frame = ttk.Frame(crawl_frame)
    btn_frame.pack(fill="x", padx=5, pady=3)
    crawl_btn = ttk.Button(
        btn_frame, text="开始爬取",
        command=lambda: threading.Thread(target=crawl_all_pages, args=(status_text, page_entry), daemon=True).start()
    )
    crawl_btn.pack(side="left", padx=5)
    clear_btn = ttk.Button(
        btn_frame, text="清空数据库",
        command=lambda: clear_database(status_text)
    )
    clear_btn.pack(side="left")
    
    # 爬取状态日志
    status_text = scrolledtext.ScrolledText(crawl_frame, height=7)
    status_text.pack(fill="x", padx=5, pady=3)
    
    # ========== 搜索区域 ==========
    search_frame = ttk.LabelFrame(root, text="🔍 帖子搜索（多关键词模糊匹配 + 时间筛选）")
    search_frame.pack(fill="both", expand=True, padx=10, pady=5)
    
    # 搜索提示
    tip_label = ttk.Label(
        search_frame,
        text="使用提示：1. 输入多关键词（如'剑魂技能'）会匹配标题含所有关键词的帖子；2. 结果默认按时间倒序排列；3. 数据库存储路径：我的文档/colg搜索工具/colg_posts.db",
        font=("微软雅黑", 8),
        foreground="gray"
    )
    tip_label.pack(fill="x", padx=10, pady=2)
    
    # 颜色+筛选说明
    info_frame = ttk.Frame(search_frame)
    info_frame.pack(fill="x", padx=10, pady=2)
    ttk.Label(info_frame, text="颜色说明：").pack(side="left")
    tk.Label(info_frame, text="🔴 2025-12-11前", fg="red", font=("微软雅黑", 9)).pack(side="left", padx=8)
    tk.Label(info_frame, text="🔵 2025-12-11及之后", fg="blue", font=("微软雅黑", 9)).pack(side="left", padx=8)
    
    # 新增：仅看2025.12.11后帖子的开关
    only_after_var = tk.BooleanVar(value=False)
    filter_check = ttk.Checkbutton(
        info_frame,
        text="仅查看2025-12-11之后的帖子",
        variable=only_after_var
    )
    filter_check.pack(side="left", padx=15)
    
    # 搜索输入框
    search_var = tk.StringVar()
    search_entry = ttk.Entry(search_frame, textvariable=search_var, font=("微软雅黑", 12))
    search_entry.pack(fill="x", padx=10, pady=5)
    
    # 搜索按钮
    search_btn = ttk.Button(
        search_frame, text="执行搜索",
        command=lambda: search_posts(search_var.get(), result_frame, only_after_var)
    )
    search_btn.pack(pady=3)
    
    # 结果展示区域
    result_frame = ttk.Frame(search_frame)
    result_frame.pack(fill="both", expand=True, padx=10, pady=5)
    
    # 启动主循环
    root.mainloop()

# 程序入口
if __name__ == "__main__":
    create_main_gui()