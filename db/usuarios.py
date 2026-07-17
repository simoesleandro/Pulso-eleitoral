"""CRUD de usuários (login/admin) — não depende de nenhum outro cluster além
de get_conn()."""
import sqlite3

import bcrypt

from db.core import get_conn


def criar_usuario(username: str, password: str, nome: str = None) -> bool:
    """Cria novo usuário com senha hasheada. Retorna False se username já existe."""
    username = username.strip().lower()
    password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    try:
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO usuarios (username, password_hash, nome, ativo) VALUES (?, ?, ?, 1)",
            (username, password_hash, nome)
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    except Exception as e:
        raise e
    finally:
        conn.close()


def verificar_usuario(username: str, password: str) -> dict | None:
    """Compara a senha informada com a hash salva via bcrypt.checkpw,
    atualiza ultimo_login se correta, e retorna dados do usuário (dict) se ativo."""
    username = username.strip().lower()
    conn = get_conn()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, username, password_hash, nome, ativo FROM usuarios WHERE username = ?",
            (username,)
        )
        row = cursor.fetchone()
        if not row:
            return None

        # Se o usuário não estiver ativo, não permite login
        if not row['ativo']:
            return None

        # Verifica senha
        hash_bytes = row['password_hash'].encode('utf-8')
        if bcrypt.checkpw(password.encode('utf-8'), hash_bytes):
            # Atualiza último login
            import datetime
            now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cursor.execute(
                "UPDATE usuarios SET ultimo_login = ? WHERE id = ?",
                (now_str, row['id'])
            )
            conn.commit()
            return {
                "id": row["id"],
                "username": row["username"],
                "nome": row["nome"],
                "ativo": row["ativo"]
            }
        return None
    except Exception as e:
        raise e
    finally:
        conn.close()


def listar_usuarios() -> list[dict]:
    """Retorna todos os usuários cadastrados sem a hash da senha."""
    conn = get_conn()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, username, nome, ativo, criado_em, ultimo_login FROM usuarios ORDER BY username ASC"
        )
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    except Exception:
        return []
    finally:
        conn.close()


def remover_usuario(user_id: int) -> bool:
    """Exclui o usuário do banco por ID. Retorna True se excluiu com sucesso."""
    conn = get_conn()
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM usuarios WHERE id = ?", (user_id,))
        conn.commit()
        return cursor.rowcount > 0
    except Exception:
        return False
    finally:
        conn.close()


def toggle_usuario(user_id: int) -> bool:
    """Inverte o status 'ativo' (0 para 1, ou 1 para 0) do usuário por ID."""
    conn = get_conn()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT ativo FROM usuarios WHERE id = ?", (user_id,))
        row = cursor.fetchone()
        if row is None:
            return False
        novo_status = 0 if row['ativo'] == 1 else 1
        cursor.execute("UPDATE usuarios SET ativo = ? WHERE id = ?", (novo_status, user_id))
        conn.commit()
        return True
    except Exception:
        return False
    finally:
        conn.close()
