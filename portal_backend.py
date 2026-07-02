import pandas as pd
from flask import Flask, render_template, request, session, send_file, redirect, send_from_directory, jsonify
import mysql.connector
from dotenv import load_dotenv
import os
from datetime import datetime
import zipfile
import io
import subprocess
import sys
load_dotenv()
app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY")


def get_db():
    return mysql.connector.connect(
        host=os.getenv("DB_HOST"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        database=os.getenv("DB_NAME")
    )


def export_tables_to_csv(db):
    tables = ["users", "attempts", "responses"]

    for table in tables:
        df = pd.read_sql(f"SELECT * FROM {table}", db)
        df.to_csv(f"{table}.csv", index=False)


@app.route("/")
def home():
    return render_template("login.html")


@app.route("/login", methods=["POST"])
def login():

    email = request.form["email"]
    password = request.form["password"]

    db = get_db()
    cursor = db.cursor(dictionary=True)

    cursor.execute("""
        SELECT *
        FROM users
        WHERE email = %s AND password = %s
    """, (email, password))

    user = cursor.fetchone()

    if not user:
        cursor.close()
        db.close()
        return "Invalid email or password"

    if user["has_completed"]:
        cursor.close()
        db.close()
        return "This assessment has already been completed for this email."

    cursor.execute("""
        SELECT *
        FROM attempts
        WHERE user_email = %s
          AND status = 'in_progress'
        ORDER BY started_at DESC
        LIMIT 1
    """, (email,))

    existing_attempt = cursor.fetchone()

    if existing_attempt:

        if not existing_attempt["actually_started"]:

            cursor.execute("""
                DELETE FROM attempts
                WHERE attempt_id = %s
            """, (existing_attempt["attempt_id"],))

            db.commit()

        else:

            session["user_email"] = email

            cursor.close()
            db.close()

            return render_template(
                "continue.html",
                current_page=existing_attempt["current_page"]
            )

    cursor.execute("""
        INSERT INTO attempts (user_email)
        VALUES (%s)
    """, (email,))

    cursor.execute("""
        UPDATE users
        SET has_started = TRUE
        WHERE email = %s
    """, (email,))

    db.commit()

    session["user_email"] = email

    export_tables_to_csv(db)

    cursor.close()
    db.close()

    return render_template("assessment.html")

@app.route("/save_answer", methods=["POST"])
def save_answer():

    user_email = session["user_email"]

    question_id = request.form["question_id"]
    question_text = request.form["question_text"]
    user_answer = request.form["user_answer"]
    correct_answer = request.form["correct_answer"]
    is_correct = request.form["is_correct"]
    

    db = get_db()
    cursor = db.cursor()

    cursor.execute("""
        INSERT INTO responses (
            user_email,
            question_id,
            question_text,
            user_answer,
            correct_answer,
            is_correct
        )
        VALUES (%s,%s,%s,%s,%s,%s)
    """, (
        user_email,
        question_id,
        question_text,
        user_answer,
        correct_answer,
        is_correct
    ))

    db.commit()
    export_tables_to_csv(db)

    cursor.close()
    db.close()

    return "Answer saved"


@app.route("/complete_attempt", methods=["POST"])
def complete_attempt():

    user_email = session["user_email"]

    total_score = request.form["total_score"]
    total_time = request.form["total_time"]
    section1_time = request.form.get("section1_time", 0)
    section2_time = request.form.get("section2_time", 0)
    section3_time = request.form.get("section3_time", 0)

    db = get_db()
    cursor = db.cursor()

    cursor.execute("""
        UPDATE attempts
        SET
          completed_at = NOW(),
          total_score = %s,
          total_time_seconds = %s,
          section1_time = %s,
          section2_time = %s,
          section3_time = %s,
          status = 'completed'
        WHERE user_email = %s
         AND status = 'in_progress'
    """, (
    total_score,
    total_time,
    section1_time,
    section2_time,
    section3_time,
    user_email
))

    cursor.execute("""
        UPDATE users
        SET has_completed = TRUE
        WHERE email = %s
    """, (user_email,))

    db.commit()
    export_tables_to_csv(db)

    cursor.close()
    db.close()

    return "Attempt completed"


@app.route("/save_progress", methods=["POST"])
def save_progress():

    user_email = session["user_email"]
    current_page = request.form["current_page"]

    db = get_db()
    cursor = db.cursor()

    cursor.execute("""
        UPDATE attempts
        SET current_page = %s
        WHERE user_email = %s
          AND status = 'in_progress'
    """, (current_page, user_email))

    db.commit()
    export_tables_to_csv(db)

    cursor.close()
    db.close()

    return "Progress saved"


@app.route("/continue_test", methods=["POST"])
def continue_test():

    user_email = session["user_email"]

    db = get_db()
    cursor = db.cursor(dictionary=True)

    cursor.execute("""
        SELECT current_page, warning_count
        FROM attempts
        WHERE user_email = %s
          AND status = 'in_progress'
        ORDER BY started_at DESC
        LIMIT 1
    """, (user_email,))

    attempt = cursor.fetchone()

    cursor.close()
    db.close()

    if attempt:
        return render_template(
            "assessment.html",
            resume_page=attempt["current_page"],
            warning_count=attempt["warning_count"]
        )

    return render_template("assessment.html")
@app.route("/record_warning", methods=["POST"])
def record_warning():

    user_email = session["user_email"]
    auto_submitted = request.form.get("auto_submitted", "0")

    db = get_db()
    cursor = db.cursor()

    cursor.execute("""
        UPDATE attempts
        SET
            warning_count = warning_count + 1,
            auto_submitted = %s
        WHERE user_email = %s
          AND status = 'in_progress'
    """, (
        auto_submitted,
        user_email
    ))

    db.commit()
    export_tables_to_csv(db)

    cursor.close()
    db.close()

    return "Warning recorded"
@app.route("/record_exit_violation", methods=["POST"])
def record_exit_violation():

    user_email = session.get("user_email")

    if not user_email:
        return "No active session"

    db = get_db()
    cursor = db.cursor(dictionary=True)

    cursor.execute("""
        SELECT warning_count
        FROM attempts
        WHERE user_email = %s
          AND status = 'in_progress'
        ORDER BY started_at DESC
        LIMIT 1
    """, (user_email,))

    attempt = cursor.fetchone()

    if not attempt:
        cursor.close()
        db.close()
        return "No active attempt"

    new_warning_count = attempt["warning_count"] + 1

    if new_warning_count >= 2:
        cursor.execute("""
            UPDATE attempts
            SET
                warning_count = %s,
                auto_submitted = TRUE,
                status = 'completed',
                completed_at = NOW()
            WHERE user_email = %s
              AND status = 'in_progress'
        """, (new_warning_count, user_email))

        cursor.execute("""
            UPDATE users
            SET has_completed = TRUE
            WHERE email = %s
        """, (user_email,))

    else:
        cursor.execute("""
            UPDATE attempts
            SET warning_count = %s
            WHERE user_email = %s
              AND status = 'in_progress'
        """, (new_warning_count, user_email))

    db.commit()
    export_tables_to_csv(db)

    cursor.close()
    db.close()

    return "Exit violation recorded"
@app.route("/upload_recording", methods=["POST"])
def upload_recording():

    user_email = session.get("user_email")

    if not user_email:
        return "No active session"

    recording_type = request.form.get("type")

    file = request.files.get("video")

    if not file:
        return "No file uploaded"

    os.makedirs("recordings", exist_ok=True)

    safe_email = user_email.replace("@", "_").replace(".", "_")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    filename = f"{recording_type}_{safe_email}_{timestamp}.webm"

    save_path = os.path.join("recordings", filename)

    file.save(save_path)

    return "Recording uploaded"
@app.route("/upload_recording_chunk", methods=["POST"])
def upload_recording_chunk():

    user_email = session.get("user_email")

    if not user_email:
        return "No active session", 401

    recording_type = request.form.get("type")
    chunk_index = request.form.get("chunk_index")

    file = request.files.get("video")

    if not file:
        return "No file uploaded", 400

    os.makedirs("recordings", exist_ok=True)

    safe_email = user_email.replace("@", "_").replace(".", "_")
    timestamp = datetime.now().strftime("%Y%m%d")

    filename = f"{recording_type}_{safe_email}_{timestamp}_chunk_{chunk_index}.webm"
    save_path = os.path.join("recordings", filename)

    file.save(save_path)

    return "Chunk uploaded", 200

@app.route("/run_python", methods=["POST"])
def run_python():

    code = request.form.get("code", "")
    question_id = request.form.get("question_id", "")

    banned_words = [
        "import os",
        "import sys",
        "subprocess",
        "open(",
        "__import__",
        "eval(",
        "exec(",
        "globals(",
        "locals("
    ]

    for word in banned_words:
        if word in code:
            return jsonify({
                "success": False,
                "output": f"Blocked: {word} is not allowed."
            })

    q7_code = """
numbers = [
    42, 17, 89, 23, 89, 56, 31, 72, 72, 10,
    64, 38, 95, 44, 95, 81, 27, 60, 13, 76,
    58, 33, 91, 47, 68, 91, 29, 84, 52, 39
]
"""

    q8_code = """
import pandas as pd

sales_rows = []

products = ["Laptop", "Tablet", "Phone", "Monitor", "Keyboard"]
regions = ["North", "South", "East", "West"]
months = ["Jan", "Feb", "Mar", "Apr", "May"]

for i in range(160):
    product = products[i % len(products)]
    region = regions[(i * 2 + 1) % len(regions)]
    month = months[(i * 3 + 2) % len(months)]
    revenue = 1000 + ((i * 137) % 9000)

    sales_rows.append({
        "Product": product,
        "Region": region,
        "Month": month,
        "Revenue": revenue
    })

df = pd.DataFrame(sales_rows)

df.loc[len(df)] = {"Product": "Tablet", "Region": "West", "Month": "Apr", "Revenue": 20000}
df.loc[len(df)] = {"Product": "Phone", "Region": "East", "Month": "Mar", "Revenue": 19000}
"""

    q9_code = """
import pandas as pd

students = [
    "Aarav", "Diya", "Kabir", "Meera", "Rohan",
    "Ananya", "Ishaan", "Kavya", "Vivaan", "Tara",
    "Arjun", "Nisha", "Dev", "Sara", "Yash",
    "Priya", "Manav", "Aditi", "Reyansh", "Kiara",
    "Om", "Ira", "Neil", "Riya", "Ved"
]

subjects = ["Mathematics", "Physics", "Chemistry", "English"]

rows = []

for i, student in enumerate(students):
    for j, subject in enumerate(subjects):
        score = 55 + ((i * 7 + j * 11) % 41)
        rows.append({
            "Student": student,
            "Subject": subject,
            "Score": score
        })

df = pd.DataFrame(rows)

df.loc[(df["Student"] == "Manav") & (df["Subject"] == "Mathematics"), "Score"] = 100
df.loc[(df["Student"] == "Kavya") & (df["Subject"] == "Physics"), "Score"] = 99
df.loc[(df["Student"] == "Aditi") & (df["Subject"] == "Chemistry"), "Score"] = 98
"""

    if question_id == "q7":
        setup_code = q7_code
    elif question_id == "q8":
        setup_code = q8_code
    else:
        setup_code = q9_code

    full_code = setup_code + "\n\n" + code

    try:

        result = subprocess.run(
            [sys.executable, "-c", full_code],
            capture_output=True,
            text=True,
            timeout=3
        )

        output = result.stdout

        if result.stderr:
            output += "\n" + result.stderr

        return jsonify({
            "success": True,
            "output": output if output.strip() else "Code ran successfully, but printed no output."
        })

    except subprocess.TimeoutExpired:

        return jsonify({
            "success": False,
            "output": "Execution timed out after 3 seconds."
        })

    except Exception as e:

        return jsonify({
            "success": False,
            "output": str(e)
        })
@app.route("/mark_started", methods=["POST"])
def mark_started():

    user_email = session["user_email"]

    db = get_db()
    cursor = db.cursor()

    cursor.execute("""
        UPDATE attempts
        SET actually_started = TRUE
        WHERE user_email = %s
          AND status = 'in_progress'
    """, (user_email,))

    db.commit()
    export_tables_to_csv(db)

    cursor.close()
    db.close()

    return "Assessment marked as started"
def require_admin():
    return session.get("is_admin") == True
@app.route("/admin", methods=["GET", "POST"])
def admin():

    if request.method == "POST":
        password = request.form.get("password")

        if password == os.getenv("ADMIN_PASSWORD"):
            session["is_admin"] = True
            return render_template("admin.html")

        return "Invalid admin password"

    if session.get("is_admin"):
        return render_template("admin.html")

    return render_template("admin_login.html")


@app.route("/download/<table_name>")
def download_table(table_name):
    if not require_admin():
        return redirect("/admin")
    allowed_tables = ["users", "attempts", "responses"]

    if table_name not in allowed_tables:
        return "Invalid table name"

    db = get_db()
    export_tables_to_csv(db)
    db.close()

    filename = f"{table_name}.csv"

    return send_file(
        filename,
        as_attachment=True,
        download_name=filename
    )


@app.route("/upload_users", methods=["POST"])
def upload_users():
    if not require_admin():
        return redirect("/admin")

    file = request.files.get("users_file")

    if not file:
        return "No file uploaded"

    filename = file.filename.lower()

    if filename.endswith(".csv"):
        df = pd.read_csv(file)
    elif filename.endswith(".xlsx"):
        df = pd.read_excel(file)
    else:
        return "Please upload a CSV or Excel file"

    if "email" not in df.columns or "password" not in df.columns:
        return "File must contain email and password columns"

    db = get_db()
    cursor = db.cursor()

    for _, row in df.iterrows():
        email = str(row["email"]).strip()
        password = str(row["password"]).strip()

        if not email or not password:
            continue

        cursor.execute("""
            INSERT INTO users (email, password)
            VALUES (%s, %s)
            ON DUPLICATE KEY UPDATE password = VALUES(password)
        """, (email, password))

    db.commit()
    export_tables_to_csv(db)

    cursor.close()
    db.close()

    return redirect("/admin")
@app.route("/admin/recordings")
def admin_recordings():
    if not require_admin():
        return redirect("/admin")

    os.makedirs("recordings", exist_ok=True)

    files = sorted(os.listdir("recordings"))

    groups = {}

    for filename in files:
        if "_chunk_" in filename:
            prefix = filename.split("_chunk_")[0]
        else:
            prefix = filename.rsplit(".", 1)[0]

        if prefix not in groups:
            groups[prefix] = []

        groups[prefix].append(filename)

    for prefix in groups:
        groups[prefix] = sorted(groups[prefix])

    return render_template("recordings.html", groups=groups)

@app.route("/download_recording/<filename>")
def download_recording(filename):
    if not require_admin():
        return redirect("/admin")

    return send_from_directory(
        "recordings",
        filename,
        as_attachment=True
    )
@app.route("/download_recording_zip/<recording_prefix>")
def download_recording_zip(recording_prefix):

    if not require_admin():
        return redirect("/admin")

    recordings_dir = "recordings"

    memory_file = io.BytesIO()

    with zipfile.ZipFile(memory_file, "w", zipfile.ZIP_DEFLATED) as zf:

        for filename in os.listdir(recordings_dir):

            if filename.startswith(recording_prefix):

                file_path = os.path.join(recordings_dir, filename)

                zf.write(file_path, arcname=filename)

    memory_file.seek(0)

    return send_file(
        memory_file,
        as_attachment=True,
        download_name=f"{recording_prefix}.zip",
        mimetype="application/zip"
    )
if __name__ == "__main__":
    app.run(debug=True)
