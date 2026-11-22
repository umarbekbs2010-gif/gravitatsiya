import csv
import datetime
import json
import os
import sqlite3
from dataclasses import dataclass
from typing import Dict, List, Optional

DB_FILE = "academy_erp.db"
EXPORT_DIR = "exports"


@dataclass
class FinanceSummary:
    total_income: int
    total_expense: int
    net_balance: int
    unpaid_students: int


class DatabaseManager:
    def __init__(self, db_path: str = DB_FILE):
        self.db_path = db_path
        self.init_database()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_database(self) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS courses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT UNIQUE NOT NULL,
                    monthly_fee INTEGER NOT NULL,
                    duration_months INTEGER NOT NULL DEFAULT 6
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS students (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    code TEXT UNIQUE NOT NULL,
                    full_name TEXT NOT NULL,
                    phone TEXT NOT NULL,
                    parent_phone TEXT DEFAULT '',
                    course_id INTEGER,
                    status TEXT NOT NULL DEFAULT 'Faol',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (course_id) REFERENCES courses (id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS attendance (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    student_id INTEGER NOT NULL,
                    att_date TEXT NOT NULL,
                    state TEXT NOT NULL,
                    note TEXT DEFAULT '',
                    FOREIGN KEY (student_id) REFERENCES students (id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS payments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    student_id INTEGER NOT NULL,
                    amount INTEGER NOT NULL,
                    method TEXT NOT NULL,
                    period_label TEXT NOT NULL,
                    paid_at TEXT NOT NULL,
                    FOREIGN KEY (student_id) REFERENCES students (id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS grades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    student_id INTEGER NOT NULL,
                    exam_title TEXT NOT NULL,
                    score REAL NOT NULL,
                    graded_at TEXT NOT NULL,
                    FOREIGN KEY (student_id) REFERENCES students (id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS expenses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    category TEXT NOT NULL,
                    amount INTEGER NOT NULL,
                    description TEXT DEFAULT '',
                    spent_at TEXT NOT NULL
                )
                """
            )
            self._seed_defaults(conn)

    def _seed_defaults(self, conn: sqlite3.Connection) -> None:
        existing_courses = conn.execute("SELECT COUNT(*) AS cnt FROM courses").fetchone()["cnt"]
        if existing_courses == 0:
            default_courses = [
                ("Python Backend", 550000, 6),
                ("Frontend Dasturlash", 500000, 6),
                ("Ingliz tili (IELTS)", 450000, 5),
                ("Matematika & DTM", 400000, 9),
            ]
            conn.executemany(
                "INSERT INTO courses (title, monthly_fee, duration_months) VALUES (?, ?, ?)",
                default_courses,
            )


def format_sum(amount: int) -> str:
    return f"{int(amount):,}".replace(",", " ") + " so'm"


def today_str() -> str:
    return datetime.date.today().isoformat()


def now_str() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class AcademyERP:
    def __init__(self, db: DatabaseManager):
        self.db = db

    # --- KURSLAR ---
    def add_course(self, title: str, monthly_fee: int, duration_months: int = 6) -> bool:
        if not title.strip() or monthly_fee <= 0 or duration_months <= 0:
            return False
        try:
            with self.db.connect() as conn:
                conn.execute(
                    "INSERT INTO courses (title, monthly_fee, duration_months) VALUES (?, ?, ?)",
                    (title.strip(), monthly_fee, duration_months),
                )
            return True
        except sqlite3.IntegrityError:
            return False

    def list_courses(self) -> List[sqlite3.Row]:
        with self.db.connect() as conn:
            return conn.execute("SELECT * FROM courses ORDER BY id").fetchall()

    # --- O'QUVCHILAR ---
    def _next_student_code(self, conn: sqlite3.Connection) -> str:
        row = conn.execute("SELECT MAX(id) AS max_id FROM students").fetchone()
        next_num = (row["max_id"] or 0) + 1
        return f"STD-{next_num:04d}"

    def register_student(
        self,
        full_name: str,
        phone: str,
        parent_phone: str,
        course_id: Optional[int],
    ) -> Optional[str]:
        if not full_name.strip() or not phone.strip():
            return None
        with self.db.connect() as conn:
            code = self._next_student_code(conn)
            conn.execute(
                """
                INSERT INTO students (code, full_name, phone, parent_phone, course_id, status, created_at)
                VALUES (?, ?, ?, ?, ?, 'Faol', ?)
                """,
                (code, full_name.strip(), phone.strip(), parent_phone.strip(), course_id, now_str()),
            )
            return code

    def list_students(self, search: str = "", status: str = "") -> List[sqlite3.Row]:
        query = """
            SELECT s.*, c.title AS course_title, c.monthly_fee
            FROM students s
            LEFT JOIN courses c ON s.course_id = c.id
            WHERE 1=1
        """
        params: List[object] = []
        if search.strip():
            like = f"%{search.strip().lower()}%"
            query += " AND (LOWER(s.full_name) LIKE ? OR LOWER(s.code) LIKE ? OR LOWER(s.phone) LIKE ?)"
            params.extend([like, like, like])
        if status.strip():
            query += " AND s.status = ?"
            params.append(status.strip())
        query += " ORDER BY s.id DESC"

        with self.db.connect() as conn:
            return conn.execute(query, params).fetchall()

    def set_student_status(self, code: str, new_status: str) -> bool:
        if new_status not in ("Faol", "Muzlatilgan", "Yakunlagan"):
            return False
        with self.db.connect() as conn:
            cur = conn.execute("UPDATE students SET status = ? WHERE code = ?", (new_status, code.strip()))
            return cur.rowcount > 0

    # --- DAVOMAT ---
    def mark_attendance(self, student_code: str, state: str, note: str = "", att_date: Optional[str] = None) -> bool:
        valid_states = {"Keldi", "Kelmadi", "Kechikdi", "Sababli"}
        if state not in valid_states:
            return False
        with self.db.connect() as conn:
            st = conn.execute("SELECT id FROM students WHERE code = ?", (student_code.strip(),)).fetchone()
            if not st:
                return False
            conn.execute(
                "INSERT INTO attendance (student_id, att_date, state, note) VALUES (?, ?, ?, ?)",
                (st["id"], att_date or today_str(), state, note.strip()),
            )
            return True

    def attendance_report(self, att_date: Optional[str] = None) -> List[sqlite3.Row]:
        target_date = att_date or today_str()
        with self.db.connect() as conn:
            return conn.execute(
                """
                SELECT a.att_date, s.code, s.full_name, a.state, a.note
                FROM attendance a
                JOIN students s ON a.student_id = s.id
                WHERE a.att_date = ?
                ORDER BY a.id DESC
                """,
                (target_date,),
            ).fetchall()

    # --- TO'LOVLAR ---
    def record_payment(self, student_code: str, amount: int, method: str, period_label: str) -> bool:
        if amount <= 0:
            return False
        with self.db.connect() as conn:
            st = conn.execute("SELECT id FROM students WHERE code = ?", (student_code.strip(),)).fetchone()
            if not st:
                return False
            conn.execute(
                """
                INSERT INTO payments (student_id, amount, method, period_label, paid_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (st["id"], amount, method.strip() or "Naqd", period_label.strip() or today_str()[:7], now_str()),
            )
            return True

    def list_payments(self) -> List[sqlite3.Row]:
        with self.db.connect() as conn:
            return conn.execute(
                """
                SELECT p.*, s.code, s.full_name
                FROM payments p
                JOIN students s ON p.student_id = s.id
                ORDER BY p.id DESC
                """
            ).fetchall()

    # --- BAHOLAR ---
    def add_grade(self, student_code: str, exam_title: str, score: float) -> bool:
        if not exam_title.strip() or score < 0 or score > 100:
            return False
        with self.db.connect() as conn:
            st = conn.execute("SELECT id FROM students WHERE code = ?", (student_code.strip(),)).fetchone()
            if not st:
                return False
            conn.execute(
                "INSERT INTO grades (student_id, exam_title, score, graded_at) VALUES (?, ?, ?, ?)",
                (st["id"], exam_title.strip(), score, now_str()),
            )
            return True

    def student_gpa(self, student_code: str) -> Optional[Dict[str, object]]:
        with self.db.connect() as conn:
            st = conn.execute("SELECT id, full_name FROM students WHERE code = ?", (student_code.strip(),)).fetchone()
            if not st:
                return None
            rows = conn.execute("SELECT exam_title, score, graded_at FROM grades WHERE student_id = ?", (st["id"],)).fetchall()
            avg_score = round(sum(r["score"] for r in rows) / len(rows), 2) if rows else 0.0
            return {
                "code": student_code.strip(),
                "full_name": st["full_name"],
                "exams": [dict(r) for r in rows],
                "average": avg_score,
            }

    # --- XARAJATLAR VA MOLIYA ---
    def add_expense(self, category: str, amount: int, description: str = "") -> bool:
        if not category.strip() or amount <= 0:
            return False
        with self.db.connect() as conn:
            conn.execute(
                "INSERT INTO expenses (category, amount, description, spent_at) VALUES (?, ?, ?, ?)",
                (category.strip(), amount, description.strip(), now_str()),
            )
            return True

    def finance_summary(self) -> FinanceSummary:
        with self.db.connect() as conn:
            inc = conn.execute("SELECT COALESCE(SUM(amount), 0) AS s FROM payments").fetchone()["s"]
            exp = conn.execute("SELECT COALESCE(SUM(amount), 0) AS s FROM expenses").fetchone()["s"]
            active_cnt = conn.execute("SELECT COUNT(*) AS c FROM students WHERE status = 'Faol'").fetchone()["c"]
            paid_students = conn.execute("SELECT COUNT(DISTINCT student_id) AS c FROM payments").fetchone()["c"]
            unpaid = max(0, active_cnt - paid_students)
            return FinanceSummary(
                total_income=inc,
                total_expense=exp,
                net_balance=inc - exp,
                unpaid_students=unpaid,
            )

    # --- EKSPORT (CSV & JSON) ---
    def export_students_csv(self) -> str:
        os.makedirs(EXPORT_DIR, exist_ok=True)
        path = os.path.join(EXPORT_DIR, f"students_{today_str()}.csv")
        rows = self.list_students()
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(["Kod", "F.I.Sh.", "Telefon", "Ota-ona tel", "Kurs", "Oylik to'lov", "Holat", "Sana"])
            for r in rows:
                writer.writerow([
                    r["code"],
                    r["full_name"],
                    r["phone"],
                    r["parent_phone"],
                    r["course_title"] or "-",
                    r["monthly_fee"] or 0,
                    r["status"],
                    r["created_at"],
                ])
        return path

    def export_backup_json(self) -> str:
        os.makedirs(EXPORT_DIR, exist_ok=True)
        path = os.path.join(EXPORT_DIR, f"backup_{today_str()}.json")
        with self.db.connect() as conn:
            payload = {
                "exported_at": now_str(),
                "courses": [dict(r) for r in conn.execute("SELECT * FROM courses").fetchall()],
                "students": [dict(r) for r in conn.execute("SELECT * FROM students").fetchall()],
                "payments": [dict(r) for r in conn.execute("SELECT * FROM payments").fetchall()],
                "grades": [dict(r) for r in conn.execute("SELECT * FROM grades").fetchall()],
                "expenses": [dict(r) for r in conn.execute("SELECT * FROM expenses").fetchall()],
            }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        return path


def cli_menu(erp: AcademyERP) -> None:
    while True:
        print("\n================ AKADEMIYA ERP TIZIMI ================")
        print("1. O'quvchini ro'yxatga olish")
        print("2. O'quvchilar ro'yxati va qidiruv")
        print("3. Davomat belgilash va hisobot")
        print("4. To'lov qabul qilish va to'lovlar tarixi")
        print("5. Imtihon bahosi qo'shish va o'rtacha ball")
        print("6. Kurslar va xarajatlar / Moliya hisoboti")
        print("7. CSV va JSON zaxira eksport qilish")
        print("0. Chiqish")
        choice = input("Tanlang: ").strip()

        if choice == "1":
            courses = erp.list_courses()
            print("\nMavjud kurslar:")
            for c in courses:
                print(f"  ID: {c['id']} | {c['title']} ({format_sum(c['monthly_fee'])}/oy)")
            name = input("F.I.Sh.: ").strip()
            phone = input("Telefon: ").strip()
            parent = input("Ota-ona telefoni: ").strip()
            cid_raw = input("Kurs ID (ixtiyoriy): ").strip()
            cid = int(cid_raw) if cid_raw.isdigit() else None
            code = erp.register_student(name, phone, parent, cid)
            print(f"Saqlandi! O'quvchi kodi: {code}" if code else "Ma'lumotlar noto'g'ri.")

        elif choice == "2":
            q = input("Qidiruv (ism, kod, tel): ").strip()
            rows = erp.list_students(search=q)
            print(f"\nTopildi: {len(rows)} nafar")
            for r in rows:
                print(f"  {r['code']} | {r['full_name']} | {r['phone']} | {r['course_title'] or '-'} | {r['status']}")

        elif choice == "3":
            sub = input("1) Davomat yozish  2) Bugungi hisobot: ").strip()
            if sub == "1":
                code = input("O'quvchi kodi (masalan STD-0001): ").strip()
                print("Holat: Keldi / Kelmadi / Kechikdi / Sababli")
                state = input("Holat: ").strip()
                note = input("Izoh: ").strip()
                print("Davomat yozildi." if erp.mark_attendance(code, state, note) else "Xatolik (kod yoki holat noto'g'ri).")
            else:
                for r in erp.attendance_report():
                    print(f"  {r['att_date']} | {r['code']} | {r['full_name']} -> {r['state']} ({r['note']})")

        elif choice == "4":
            sub = input("1) To'lov kiritish  2) To'lovlar tarixi: ").strip()
            if sub == "1":
                code = input("O'quvchi kodi: ").strip()
                try:
                    amt = int(input("Summa (so'm): ").strip())
                except ValueError:
                    print("Summa raqam bo'lishi kerak.")
                    continue
                method = input("Usul (Naqd/Karta/Click): ").strip() or "Naqd"
                period = input("Davr (masalan 2026-11): ").strip() or today_str()[:7]
                print("To'lov qayd etildi." if erp.record_payment(code, amt, method, period) else "O'quvchi topilmadi yoki summa noto'g'ri.")
            else:
                for p in erp.list_payments():
                    print(f"  #{p['id']} | {p['code']} ({p['full_name']}) | {format_sum(p['amount'])} | {p['method']} | {p['period_label']}")

        elif choice == "5":
            sub = input("1) Baho qo'shish  2) O'rtacha ball ko'rish: ").strip()
            code = input("O'quvchi kodi: ").strip()
            if sub == "1":
                title = input("Imtihon/test nomi: ").strip()
                try:
                    score = float(input("Ball (0-100): ").strip())
                except ValueError:
                    print("Ball raqam bo'lishi kerak.")
                    continue
                print("Baho saqlandi." if erp.add_grade(code, title, score) else "Xatolik.")
            else:
                info = erp.student_gpa(code)
                if not info:
                    print("O'quvchi topilmadi.")
                else:
                    print(f"  {info['full_name']} ({info['code']}) — O'rtacha ball: {info['average']}")
                    for ex in info["exams"]:
                        print(f"    * {ex['exam_title']}: {ex['score']} ({ex['graded_at']})")

        elif choice == "6":
            sub = input("1) Yangi kurs  2) Xarajat qo'shish  3) Moliya hisoboti: ").strip()
            if sub == "1":
                title = input("Kurs nomi: ").strip()
                try:
                    fee = int(input("Oylik to'lov: ").strip())
                    dur = int(input("Davomiyligi (oy) [6]: ").strip() or "6")
                except ValueError:
                    print("Raqam noto'g'ri.")
                    continue
                print("Kurs qo'shildi." if erp.add_course(title, fee, dur) else "Xatolik (balki nomi takrorlangan).")
            elif sub == "2":
                cat = input("Xarajat turi (Ijara, Maosh, Internet...): ").strip()
                try:
                    amt = int(input("Summa: ").strip())
                except ValueError:
                    print("Summa noto'g'ri.")
                    continue
                desc = input("Izoh: ").strip()
                print("Xarajat yozildi." if erp.add_expense(cat, amt, desc) else "Xatolik.")
            else:
                fin = erp.finance_summary()
                print(f"  Jami kirim:    {format_sum(fin.total_income)}")
                print(f"  Jami xarajat:  {format_sum(fin.total_expense)}")
                print(f"  Sof qoldiq:    {format_sum(fin.net_balance)}")
                print(f"  To'lov qilmagan faol o'quvchilar: {fin.unpaid_students}")

        elif choice == "7":
            csv_path = erp.export_students_csv()
            json_path = erp.export_backup_json()
            print(f"CSV saqlandi:  {csv_path}")
            print(f"JSON saqlandi: {json_path}")

        elif choice == "0":
            print("Dastur yakunlandi.")
            break
        else:
            print("Noto'g'ri tanlov.")


if __name__ == "__main__":
    db_manager = DatabaseManager()
    erp_service = AcademyERP(db_manager)
    cli_menu(erp_service)