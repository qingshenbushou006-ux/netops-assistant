"""
数据库模块 - SQLite 资产管理
"""
import sqlite3
import os
from datetime import datetime
from pathlib import Path

SERIAL_COLUMNS = {
    "serial_port": "TEXT DEFAULT ''",
    "baud_rate": "INTEGER DEFAULT 9600",
    "data_bits": "INTEGER DEFAULT 8",
    "parity": "TEXT DEFAULT 'N'",
    "stop_bits": "INTEGER DEFAULT 1",
    "flow_control": "TEXT DEFAULT 'none'",
    "telnet_port": "INTEGER DEFAULT 23",
}

DB_DIR = Path(__file__).parent.parent / "database"
DB_PATH = DB_DIR / "assets.db"
DEFAULT_GROUPS = [
    ("核心设备", None, 0),
    ("汇聚设备", None, 1),
    ("接入设备", None, 2),
    ("防火墙", None, 3),
    ("路由器", None, 4),
    ("服务器", None, 5),
    ("其他", None, 99),
]


def get_connection():
    """获取数据库连接"""
    DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _sync_default_groups(conn):
    cursor = conn.execute("SELECT COUNT(*) FROM device_groups")
    if cursor.fetchone()[0] == 0:
        conn.executemany(
            "INSERT INTO device_groups (name, parent_id, sort_order) VALUES (?, ?, ?)",
            DEFAULT_GROUPS,
        )
        conn.commit()
        return

    rows = conn.execute(
        "SELECT id, name, sort_order, parent_id FROM device_groups WHERE parent_id IS NULL"
    ).fetchall()
    rows_by_sort = {row[2]: row for row in rows}
    existing_names = {row[1] for row in rows}

    for expected_name, expected_parent_id, sort_order in DEFAULT_GROUPS:
        row = rows_by_sort.get(sort_order)
        if row:
            group_id, current_name, _, current_parent_id = row
            if current_name != expected_name or current_parent_id != expected_parent_id:
                conflict = conn.execute(
                    "SELECT id FROM device_groups WHERE name=? AND id<>?",
                    (expected_name, group_id),
                ).fetchone()
                if conflict is None:
                    conn.execute(
                        "UPDATE device_groups SET name=?, parent_id=? WHERE id=?",
                        (expected_name, expected_parent_id, group_id),
                    )
            continue

        if expected_name not in existing_names:
            conn.execute(
                "INSERT INTO device_groups (name, parent_id, sort_order) VALUES (?, ?, ?)",
                (expected_name, expected_parent_id, sort_order),
            )

    conn.commit()


def init_db():
    """初始化数据库表"""
    conn = get_connection()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS device_groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                parent_id INTEGER,
                icon TEXT DEFAULT 'folder',
                sort_order INTEGER DEFAULT 0,
                FOREIGN KEY (parent_id) REFERENCES device_groups(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS assets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                ip TEXT NOT NULL DEFAULT '',
                port INTEGER DEFAULT 22,
                protocol TEXT DEFAULT 'ssh',
                vendor TEXT DEFAULT '',
                model TEXT DEFAULT '',
                username TEXT DEFAULT '',
                password TEXT DEFAULT '',
                enable_password TEXT DEFAULT '',
                serial_port TEXT DEFAULT '',
                baud_rate INTEGER DEFAULT 9600,
                data_bits INTEGER DEFAULT 8,
                parity TEXT DEFAULT 'N',
                stop_bits INTEGER DEFAULT 1,
                flow_control TEXT DEFAULT 'none',
                group_id INTEGER,
                location TEXT DEFAULT '',
                tags TEXT DEFAULT '',
                notes TEXT DEFAULT '',
                status TEXT DEFAULT 'unknown',
                last_online TEXT,
                created_at TEXT DEFAULT (datetime('now','localtime')),
                updated_at TEXT DEFAULT (datetime('now','localtime')),
                deleted_at TEXT DEFAULT NULL,
                FOREIGN KEY (group_id) REFERENCES device_groups(id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS command_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                asset_id INTEGER,
                command TEXT,
                output TEXT,
                executed_at TEXT DEFAULT (datetime('now','localtime')),
                FOREIGN KEY (asset_id) REFERENCES assets(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS config_backups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                asset_id INTEGER NOT NULL,
                config_text TEXT NOT NULL,
                config_hash TEXT,
                backup_type TEXT DEFAULT 'manual',
                created_at TEXT DEFAULT (datetime('now','localtime')),
                FOREIGN KEY (asset_id) REFERENCES assets(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS backup_schedules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                asset_ids TEXT NOT NULL,
                cron_expr TEXT DEFAULT '0 2 * * *',
                enabled INTEGER DEFAULT 1,
                last_run TEXT,
                next_run TEXT,
                created_at TEXT DEFAULT (datetime('now','localtime'))
            );

            CREATE TABLE IF NOT EXISTS topology_links (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                src_asset_id INTEGER NOT NULL,
                src_interface TEXT DEFAULT '',
                dst_asset_id INTEGER NOT NULL,
                dst_interface TEXT DEFAULT '',
                link_type TEXT DEFAULT 'ethernet',
                bandwidth TEXT DEFAULT '',
                discovered_at TEXT DEFAULT (datetime('now','localtime')),
                FOREIGN KEY (src_asset_id) REFERENCES assets(id) ON DELETE CASCADE,
                FOREIGN KEY (dst_asset_id) REFERENCES assets(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS command_templates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                command TEXT NOT NULL,
                vendor TEXT DEFAULT '',
                category TEXT DEFAULT '',
                description TEXT DEFAULT '',
                sort_order INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now','localtime'))
            );

            CREATE TABLE IF NOT EXISTS topology_node_positions (
                asset_id INTEGER PRIMARY KEY,
                x REAL NOT NULL,
                y REAL NOT NULL,
                FOREIGN KEY (asset_id) REFERENCES assets(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS topology_edge_control_points (
                link_id INTEGER PRIMARY KEY,
                cx REAL NOT NULL,
                cy REAL NOT NULL,
                FOREIGN KEY (link_id) REFERENCES topology_links(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS serial_quick_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT DEFAULT '',
                config TEXT NOT NULL,
                is_favorite INTEGER DEFAULT 0,
                last_used TEXT DEFAULT (datetime('now','localtime'))
            );
        """)
        conn.commit()

        existing_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(assets)").fetchall()
        }
        for column, definition in SERIAL_COLUMNS.items():
            if column not in existing_columns:
                conn.execute(f"ALTER TABLE assets ADD COLUMN {column} {definition}")
        if "deleted_at" not in existing_columns:
            conn.execute("ALTER TABLE assets ADD COLUMN deleted_at TEXT DEFAULT NULL")
        # 创建软删除资产索引
        conn.execute("CREATE INDEX IF NOT EXISTS idx_assets_deleted_at ON assets(deleted_at)")
        # 拓扑链路索引（src/dst 查询 + 去重 EXISTS 检查）
        conn.execute("CREATE INDEX IF NOT EXISTS idx_topology_links_src ON topology_links(src_asset_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_topology_links_dst ON topology_links(dst_asset_id)")
        # 拓扑链路去重索引（规范化无向边，保证 A->B 与 B->A 只存一条）
        # CREATE UNIQUE INDEX 无 IF NOT EXISTS，先清理历史重复边再建，避免旧库报错
        conn.execute("""
            DELETE FROM topology_links
            WHERE id NOT IN (
                SELECT MIN(id) FROM topology_links
                GROUP BY MIN(src_asset_id, dst_asset_id), MAX(src_asset_id, dst_asset_id)
            )
        """)
        try:
            conn.execute("CREATE UNIQUE INDEX idx_topology_links_edge ON topology_links(MIN(src_asset_id, dst_asset_id), MAX(src_asset_id, dst_asset_id))")
        except Exception:
            pass  # 已存在则忽略
        conn.commit()

        _sync_default_groups(conn)
    finally:
        conn.close()


# ---- 资产 CRUD ----

def add_asset(name, ip="", port=22, protocol="ssh", vendor="", model="",
              username="", password="", enable_password="",
              serial_port="", baud_rate=9600, data_bits=8,
              parity="N", stop_bits=1, flow_control="none",
              group_id=None, location="", tags="", notes=""):
    conn = get_connection()
    conn.execute("""
        INSERT INTO assets (name, ip, port, protocol, vendor, model,
                           username, password, enable_password,
                           serial_port, baud_rate, data_bits, parity, stop_bits, flow_control,
                           group_id, location, tags, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (name, ip, port, protocol, vendor, model,
          username, password, enable_password,
          serial_port, baud_rate, data_bits, parity, stop_bits, flow_control,
          group_id, location, tags, notes))
    conn.commit()
    asset_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()
    return asset_id


def update_asset(asset_id, **kwargs):
    if asset_id < 0:
        return
    conn = get_connection()
    allowed = {"name", "ip", "port", "protocol", "vendor", "model",
               "username", "password", "enable_password",
               "serial_port", "baud_rate", "data_bits", "parity", "stop_bits", "flow_control",
               "group_id", "location", "tags", "notes", "status"}
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if not fields:
        conn.close()
        return
    fields["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    set_clause = ", ".join(f"{k}=?" for k in fields)
    values = list(fields.values()) + [asset_id]
    conn.execute(f"UPDATE assets SET {set_clause} WHERE id=?", values)
    conn.commit()
    conn.close()


def delete_asset(asset_id):
    """软删除资产（移入回收站，可恢复）"""
    conn = get_connection()
    conn.execute(
        "UPDATE assets SET deleted_at=datetime('now','localtime') WHERE id=?",
        (asset_id,),
    )
    conn.commit()
    conn.close()


def restore_asset(asset_id):
    """从回收站恢复资产"""
    conn = get_connection()
    conn.execute(
        "UPDATE assets SET deleted_at=NULL WHERE id=?",
        (asset_id,),
    )
    conn.commit()
    conn.close()


def purge_asset(asset_id):
    """彻底删除资产（不可恢复）"""
    conn = get_connection()
    conn.execute("DELETE FROM assets WHERE id=?", (asset_id,))
    conn.commit()
    conn.close()


def get_deleted_assets():
    """获取回收站中的资产"""
    conn = get_connection()
    rows = conn.execute("""
        SELECT a.*, g.name as group_name
        FROM assets a
        LEFT JOIN device_groups g ON a.group_id = g.id
        WHERE a.deleted_at IS NOT NULL
        ORDER BY a.deleted_at DESC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_all_assets(include_deleted=False):
    conn = get_connection()
    if include_deleted:
        where_clause = ""
    else:
        where_clause = "WHERE a.deleted_at IS NULL"
    rows = conn.execute(f"""
        SELECT a.*, g.name as group_name
        FROM assets a
        LEFT JOIN device_groups g ON a.group_id = g.id
        {where_clause}
        ORDER BY g.sort_order, a.name
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_asset_by_id(asset_id):
    conn = get_connection()
    row = conn.execute("""
        SELECT a.*, g.name as group_name
        FROM assets a
        LEFT JOIN device_groups g ON a.group_id = g.id
        WHERE a.id=?
    """, (asset_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def _fuzzy_match_score(keyword, value):
    """子序列模糊匹配评分：值包含全部字符（按顺序）返回匹配长度，否则 -1"""
    if not keyword or not value:
        return -1
    kw = keyword.lower()
    val = value.lower()
    if kw in val:
        return 1000 - val.index(kw)  # 越靠前分数越高
    # 子序列匹配
    i = 0
    for ch in val:
        if i < len(kw) and ch == kw[i]:
            i += 1
    if i == len(kw):
        return 500 - len(val)  # 越短分数越高
    return -1


def search_assets(keyword):
    """模糊搜索资产：支持 LIKE 包含和子序列匹配"""
    if not keyword:
        return get_all_assets()
    conn = get_connection()
    like = f"%{keyword}%"
    rows = conn.execute("""
        SELECT a.*, g.name as group_name
        FROM assets a
        LEFT JOIN device_groups g ON a.group_id = g.id
        WHERE a.deleted_at IS NULL AND (
              a.name LIKE ? OR a.ip LIKE ? OR a.vendor LIKE ?
              OR a.tags LIKE ? OR a.location LIKE ?
              OR a.protocol LIKE ? OR a.serial_port LIKE ? OR a.model LIKE ?
              OR a.notes LIKE ? OR COALESCE(g.name, '') LIKE ?
        )
        ORDER BY a.name
    """, (like, like, like, like, like, like, like, like, like, like)).fetchall()
    conn.close()

    # 子序列匹配补集
    seen_ids = {r["id"] for r in rows}
    all_assets = get_all_assets()
    fuzzy_results = []
    for asset in all_assets:
        if asset["id"] in seen_ids:
            continue
        candidates = [
            asset.get("name", ""),
            asset.get("ip", ""),
            asset.get("vendor", ""),
            asset.get("model", ""),
            asset.get("tags", ""),
            asset.get("location", ""),
            asset.get("notes", ""),
            asset.get("group_name") or "",
        ]
        best_score = -1
        for c in candidates:
            s = _fuzzy_match_score(keyword, c)
            if s > best_score:
                best_score = s
        if best_score > 0:
            fuzzy_results.append((best_score, asset))
    fuzzy_results.sort(key=lambda x: -x[0])
    return [dict(r) for r in rows] + [a for _, a in fuzzy_results]


# ---- 分组 CRUD ----

def get_all_groups():
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM device_groups ORDER BY sort_order, name"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def add_group(name, parent_id=None, sort_order=0):
    conn = get_connection()
    conn.execute(
        "INSERT INTO device_groups (name, parent_id, sort_order) VALUES (?, ?, ?)",
        (name, parent_id, sort_order),
    )
    conn.commit()
    group_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()
    return group_id


def update_group(group_id, **kwargs):
    conn = get_connection()
    allowed = {"name", "parent_id", "icon", "sort_order"}
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if not fields:
        conn.close()
        return
    set_clause = ", ".join(f"{k}=?" for k in fields)
    values = list(fields.values()) + [group_id]
    conn.execute(f"UPDATE device_groups SET {set_clause} WHERE id=?", values)
    conn.commit()
    conn.close()


def delete_group(group_id):
    conn = get_connection()
    conn.execute("DELETE FROM device_groups WHERE id=?", (group_id,))
    conn.commit()
    conn.close()


# ---- 日志 ----

def log_command(asset_id, command, output=""):
    if asset_id < 0:
        return
    conn = get_connection()
    conn.execute(
        "INSERT INTO command_logs (asset_id, command, output) VALUES (?, ?, ?)",
        (asset_id, command, output),
    )
    conn.commit()
    conn.close()


def get_asset_logs(asset_id, limit=100):
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM command_logs WHERE asset_id=? ORDER BY executed_at DESC LIMIT ?",
        (asset_id, limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ---- 备份管理 ----

def add_config_backup(asset_id, config_text, backup_type="manual"):
    import hashlib
    config_hash = hashlib.md5(config_text.encode()).hexdigest()
    conn = get_connection()
    conn.execute(
        "INSERT INTO config_backups (asset_id, config_text, config_hash, backup_type) VALUES (?, ?, ?, ?)",
        (asset_id, config_text, config_hash, backup_type),
    )
    conn.commit()
    backup_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()
    return backup_id


def get_asset_backups(asset_id, limit=50):
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM config_backups WHERE asset_id=? ORDER BY created_at DESC LIMIT ?",
        (asset_id, limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_backup_by_id(backup_id):
    conn = get_connection()
    row = conn.execute("SELECT * FROM config_backups WHERE id=?", (backup_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def delete_backup(backup_id):
    conn = get_connection()
    conn.execute("DELETE FROM config_backups WHERE id=?", (backup_id,))
    conn.commit()
    conn.close()


def get_latest_backup(asset_id):
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM config_backups WHERE asset_id=? ORDER BY created_at DESC LIMIT 1",
        (asset_id,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


# ---- 备份计划 ----

def add_backup_schedule(name, asset_ids, cron_expr="0 2 * * *"):
    import json
    if isinstance(asset_ids, list):
        asset_ids = json.dumps(asset_ids)
    conn = get_connection()
    conn.execute(
        "INSERT INTO backup_schedules (name, asset_ids, cron_expr) VALUES (?, ?, ?)",
        (name, asset_ids, cron_expr),
    )
    conn.commit()
    schedule_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()
    return schedule_id


def get_all_schedules():
    conn = get_connection()
    rows = conn.execute("SELECT * FROM backup_schedules ORDER BY name").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_schedule(schedule_id, **kwargs):
    conn = get_connection()
    allowed = {"name", "asset_ids", "cron_expr", "enabled", "last_run", "next_run"}
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if not fields:
        conn.close()
        return
    set_clause = ", ".join(f"{k}=?" for k in fields)
    values = list(fields.values()) + [schedule_id]
    conn.execute(f"UPDATE backup_schedules SET {set_clause} WHERE id=?", values)
    conn.commit()
    conn.close()


def delete_schedule(schedule_id):
    conn = get_connection()
    conn.execute("DELETE FROM backup_schedules WHERE id=?", (schedule_id,))
    conn.commit()
    conn.close()


# ---- 拓扑链路 ----

def add_topology_link(src_asset_id, dst_asset_id, src_interface="", dst_interface="",
                      link_type="ethernet", bandwidth=""):
    """添加拓扑连线（自动去重：A->B 和 B->A 视为同一条）"""
    # 去重检查：两个方向都检查
    conn = get_connection()
    existing = conn.execute("""
        SELECT id FROM topology_links
        WHERE (src_asset_id=? AND dst_asset_id=?)
           OR (src_asset_id=? AND dst_asset_id=?)
        LIMIT 1
    """, (src_asset_id, dst_asset_id, dst_asset_id, src_asset_id)).fetchone()
    if existing:
        conn.close()
        return existing[0]  # 已存在，返回已有 ID

    conn.execute(
        "INSERT INTO topology_links (src_asset_id, dst_asset_id, src_interface, dst_interface, link_type, bandwidth) VALUES (?, ?, ?, ?, ?, ?)",
        (src_asset_id, dst_asset_id, src_interface, dst_interface, link_type, bandwidth),
    )
    conn.commit()
    link_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()
    return link_id


def get_all_topology_links(location=None):
    conn = get_connection()
    params = []
    where_clause = ""
    if location and location != "全部站点":
        where_clause = "WHERE sa.deleted_at IS NULL AND da.deleted_at IS NULL AND COALESCE(sa.location, '') = ? AND COALESCE(da.location, '') = ?"
        params = [location, location]
    else:
        where_clause = "WHERE sa.deleted_at IS NULL AND da.deleted_at IS NULL"

    rows = conn.execute(f"""
        SELECT tl.*,
               sa.name as src_name, sa.ip as src_ip, sa.location as src_location,
               da.name as dst_name, da.ip as dst_ip, da.location as dst_location
        FROM topology_links tl
        JOIN assets sa ON tl.src_asset_id = sa.id
        JOIN assets da ON tl.dst_asset_id = da.id
        {where_clause}
        ORDER BY tl.discovered_at DESC
    """, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_topology_link(link_id, **kwargs):
    conn = get_connection()
    allowed = {"src_interface", "dst_interface", "link_type", "bandwidth"}
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if not fields:
        conn.close()
        return
    set_clause = ", ".join(f"{k}=?" for k in fields)
    values = list(fields.values()) + [link_id]
    conn.execute(f"UPDATE topology_links SET {set_clause} WHERE id=?", values)
    conn.commit()
    conn.close()


def delete_topology_link(link_id):
    conn = get_connection()
    conn.execute("DELETE FROM topology_links WHERE id=?", (link_id,))
    conn.commit()
    conn.close()


# ---- 拓扑节点位置 ----

def save_node_position(asset_id, x, y):
    conn = get_connection()
    conn.execute(
        "INSERT OR REPLACE INTO topology_node_positions (asset_id, x, y) VALUES (?, ?, ?)",
        (asset_id, x, y),
    )
    conn.commit()
    conn.close()


def get_node_positions():
    conn = get_connection()
    rows = conn.execute("SELECT asset_id, x, y FROM topology_node_positions").fetchall()
    conn.close()
    return {row["asset_id"]: (row["x"], row["y"]) for row in rows}


def clear_node_positions():
    conn = get_connection()
    conn.execute("DELETE FROM topology_node_positions")
    conn.commit()
    conn.close()


# ---- 拓扑边控制点 ----

def save_edge_control_point(link_id, cx, cy):
    conn = get_connection()
    conn.execute(
        "INSERT OR REPLACE INTO topology_edge_control_points (link_id, cx, cy) VALUES (?, ?, ?)",
        (link_id, cx, cy),
    )
    conn.commit()
    conn.close()


def get_edge_control_points():
    conn = get_connection()
    rows = conn.execute("SELECT link_id, cx, cy FROM topology_edge_control_points").fetchall()
    conn.close()
    return {row["link_id"]: (row["cx"], row["cy"]) for row in rows}


def clear_edge_control_points():
    conn = get_connection()
    conn.execute("DELETE FROM topology_edge_control_points")
    conn.commit()
    conn.close()


def get_asset_neighbors(asset_id):
    conn = get_connection()
    rows = conn.execute("""
        SELECT tl.*,
               CASE WHEN tl.src_asset_id = ? THEN da.name ELSE sa.name END as neighbor_name,
               CASE WHEN tl.src_asset_id = ? THEN da.ip ELSE sa.ip END as neighbor_ip,
               CASE WHEN tl.src_asset_id = ? THEN da.id ELSE sa.id END as neighbor_id,
               CASE WHEN tl.src_asset_id = ? THEN tl.dst_interface ELSE tl.src_interface END as neighbor_interface
        FROM topology_links tl
        JOIN assets sa ON tl.src_asset_id = sa.id
        JOIN assets da ON tl.dst_asset_id = da.id
        WHERE tl.src_asset_id = ? OR tl.dst_asset_id = ?
    """, (asset_id, asset_id, asset_id, asset_id, asset_id, asset_id)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ---- 命令模板 ----

def add_command_template(name, command, vendor="", category="", description="", sort_order=0):
    conn = get_connection()
    conn.execute(
        "INSERT INTO command_templates (name, command, vendor, category, description, sort_order) VALUES (?, ?, ?, ?, ?, ?)",
        (name, command, vendor, category, description, sort_order),
    )
    conn.commit()
    template_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()
    return template_id


def get_all_command_templates(vendor=None, category=None):
    conn = get_connection()
    query = "SELECT * FROM command_templates"
    params = []
    conditions = []
    if vendor:
        conditions.append("vendor = ?")
        params.append(vendor)
    if category:
        conditions.append("category = ?")
        params.append(category)
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY sort_order, category, name"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_command_template(template_id, **kwargs):
    conn = get_connection()
    allowed = {"name", "command", "vendor", "category", "description", "sort_order"}
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if not fields:
        conn.close()
        return
    set_clause = ", ".join(f"{k}=?" for k in fields)
    values = list(fields.values()) + [template_id]
    conn.execute(f"UPDATE command_templates SET {set_clause} WHERE id=?", values)
    conn.commit()
    conn.close()


def delete_command_template(template_id):
    conn = get_connection()
    conn.execute("DELETE FROM command_templates WHERE id=?", (template_id,))
    conn.commit()
    conn.close()


# ---- 串口快速会话 ----

def add_quick_session(name, config, is_favorite=False):
    """保存串口快速会话（自动去重：同端口+同参数则更新 last_used）"""
    import json
    config_str = json.dumps(config, ensure_ascii=False)
    conn = get_connection()
    # 检查是否已有相同配置
    existing = conn.execute(
        "SELECT id FROM serial_quick_sessions WHERE config=?",
        (config_str,),
    ).fetchone()
    if existing:
        conn.execute(
            "UPDATE serial_quick_sessions SET last_used=datetime('now','localtime'), name=? WHERE id=?",
            (name, existing["id"]),
        )
        conn.commit()
        session_id = existing["id"]
    else:
        conn.execute(
            "INSERT INTO serial_quick_sessions (name, config, is_favorite) VALUES (?, ?, ?)",
            (name, config_str, 1 if is_favorite else 0),
        )
        conn.commit()
        session_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()
    return session_id


def get_quick_sessions(favorites_only=False):
    """获取串口快速会话列表，收藏排最前，然后按 last_used DESC"""
    conn = get_connection()
    if favorites_only:
        rows = conn.execute(
            "SELECT * FROM serial_quick_sessions WHERE is_favorite=1 ORDER BY last_used DESC"
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM serial_quick_sessions ORDER BY is_favorite DESC, last_used DESC"
        ).fetchall()
    conn.close()
    result = []
    for r in rows:
        d = dict(r)
        import json
        d["config"] = json.loads(d["config"])
        result.append(d)
    return result


def update_quick_session_favorite(session_id, is_favorite):
    """更新快速会话收藏状态"""
    conn = get_connection()
    conn.execute(
        "UPDATE serial_quick_sessions SET is_favorite=? WHERE id=?",
        (1 if is_favorite else 0, session_id),
    )
    conn.commit()
    conn.close()


def delete_quick_session(session_id):
    """删除快速会话"""
    conn = get_connection()
    conn.execute("DELETE FROM serial_quick_sessions WHERE id=?", (session_id,))
    conn.commit()
    conn.close()


def _seed_default_templates(conn):
    """填充默认命令模板（如果表为空）"""
    cursor = conn.execute("SELECT COUNT(*) FROM command_templates")
    if cursor.fetchone()[0] > 0:
        return

    templates = [
        # Cisco 基础
        ("Cisco - 查看运行配置", "show running-config", "cisco", "基础", "显示当前运行配置"),
        ("Cisco - 查看接口状态", "show ip interface brief", "cisco", "基础", "显示接口IP和状态"),
        ("Cisco - 查看路由表", "show ip route", "cisco", "基础", "显示IP路由表"),
        ("Cisco - 查看ARP表", "show arp", "cisco", "基础", "显示ARP缓存"),
        ("Cisco - 查看MAC地址表", "show mac address-table", "cisco", "基础", "显示MAC地址表"),
        ("Cisco - 查看CDP邻居", "show cdp neighbors", "cisco", "发现", "显示CDP邻居设备"),
        ("Cisco - 查看LLDP邻居", "show lldp neighbors", "cisco", "发现", "显示LLDP邻居设备"),
        ("Cisco - 查看版本", "show version", "cisco", "基础", "显示设备版本信息"),
        ("Cisco - 查看CPU使用", "show processes cpu", "cisco", "监控", "显示CPU使用率"),
        ("Cisco - 查看内存使用", "show memory statistics", "cisco", "监控", "显示内存使用情况"),
        ("Cisco - 查看日志", "show logging", "cisco", "监控", "显示系统日志"),
        ("Cisco - 保存配置", "write memory", "cisco", "配置", "保存当前配置到NVRAM"),
        ("Cisco - 查看VLAN", "show vlan brief", "cisco", "基础", "显示VLAN信息"),
        ("Cisco - 查看STP", "show spanning-tree", "cisco", "基础", "显示生成树状态"),
        ("Cisco - Ping测试", "ping", "cisco", "测试", "Ping连通性测试"),

        # Huawei 基础
        ("Huawei - 查看运行配置", "display current-configuration", "huawei", "基础", "显示当前运行配置"),
        ("Huawei - 查看接口状态", "display ip interface brief", "huawei", "基础", "显示接口IP和状态"),
        ("Huawei - 查看路由表", "display ip routing-table", "huawei", "基础", "显示IP路由表"),
        ("Huawei - 查看ARP表", "display arp all", "huawei", "基础", "显示ARP缓存"),
        ("Huawei - 查看MAC地址表", "display mac-address", "huawei", "基础", "显示MAC地址表"),
        ("Huawei - 查看LLDP邻居", "display lldp neighbor brief", "huawei", "发现", "显示LLDP邻居设备"),
        ("Huawei - 查看版本", "display version", "huawei", "基础", "显示设备版本信息"),
        ("Huawei - 查看CPU使用", "display cpu-usage", "huawei", "监控", "显示CPU使用率"),
        ("Huawei - 查看内存使用", "display memory-usage", "huawei", "监控", "显示内存使用情况"),
        ("Huawei - 查看日志", "display logbuffer", "huawei", "监控", "显示系统日志"),
        ("Huawei - 保存配置", "save", "huawei", "配置", "保存当前配置"),
        ("Huawei - 查看VLAN", "display vlan", "huawei", "基础", "显示VLAN信息"),
        ("Huawei - 查看接口统计", "display interface", "huawei", "监控", "显示接口详细统计"),

        # H3C 基础
        ("H3C - 查看运行配置", "display current-configuration", "h3c", "基础", "显示当前运行配置"),
        ("H3C - 查看接口状态", "display ip interface brief", "h3c", "基础", "显示接口IP和状态"),
        ("H3C - 查看路由表", "display ip routing-table", "h3c", "基础", "显示IP路由表"),
        ("H3C - 查看ARP表", "display arp all", "h3c", "基础", "显示ARP缓存"),
        ("H3C - 查看MAC地址表", "display mac-address", "h3c", "基础", "显示MAC地址表"),
        ("H3C - 查看版本", "display version", "h3c", "基础", "显示设备版本信息"),
        ("H3C - 查看CPU使用", "display cpu-usage", "h3c", "监控", "显示CPU使用率"),
        ("H3C - 查看内存使用", "display memory", "h3c", "监控", "显示内存使用情况"),
        ("H3C - 查看日志", "display logbuffer", "h3c", "监控", "显示系统日志"),
        ("H3C - 保存配置", "save", "h3c", "配置", "保存当前配置"),

        # Linux 基础
        ("Linux - 查看IP地址", "ip addr show", "linux", "基础", "显示网络接口地址"),
        ("Linux - 查看路由", "ip route show", "linux", "基础", "显示路由表"),
        ("Linux - 查看进程", "ps aux", "linux", "监控", "显示所有进程"),
        ("Linux - 查看磁盘", "df -h", "linux", "监控", "显示磁盘使用"),
        ("Linux - 查看内存", "free -h", "linux", "监控", "显示内存使用"),
        ("Linux - 查看系统信息", "uname -a", "linux", "基础", "显示系统内核信息"),
        ("Linux - 查看网络连接", "ss -tlnp", "linux", "监控", "显示监听端口"),
        ("Linux - 查看防火墙", "iptables -L -n", "linux", "安全", "显示防火墙规则"),

        # 通用诊断
        ("通用 - Ping", "ping 8.8.8.8", "通用", "测试", "测试外网连通性"),
        ("通用 - Traceroute", "traceroute 8.8.8.8", "通用", "测试", "路由追踪"),
        ("通用 - DNS查询", "nslookup baidu.com", "通用", "测试", "DNS解析测试"),
    ]

    conn.executemany(
        "INSERT INTO command_templates (name, command, vendor, category, description) VALUES (?, ?, ?, ?, ?)",
        templates,
    )
    conn.commit()


# 初始化
init_db()
_seed_conn = get_connection()
try:
    _seed_default_templates(_seed_conn)
finally:
    _seed_conn.close()
