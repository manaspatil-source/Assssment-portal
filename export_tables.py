import mysql.connector
import pandas as pd

db = mysql.connector.connect(
    host="localhost",
    user="root",
    password="NewStrongPassword123!",
    database="assessment_portal"
)

tables = ["users", "attempts", "responses"]

for table in tables:

    query = f"SELECT * FROM {table}"

    df = pd.read_sql(query, db)

    df.to_csv(f"{table}.csv", index=False)

print("CSV export complete.")