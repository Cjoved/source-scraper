import mysql.connector
import os
import numpy as np
from dotenv import load_dotenv

load_dotenv()


def store_data_in_mysql(data_long, batch_size=1000):
    connection = mysql.connector.connect(
        host=os.getenv("MYSQL_HOST"),
        user=os.getenv("MYSQL_USER"),
        password=os.getenv("MYSQL_PASSWORD"),
        database=os.getenv("MYSQL_DATABASE"),
        autocommit=True
    )
    cursor = connection.cursor()
    cursor.execute("DROP TABLE IF EXISTS price_data;")
    cursor.execute("""
        CREATE TABLE price_data (
            id INT AUTO_INCREMENT PRIMARY KEY,
            geolocation VARCHAR(70),
            commodity VARCHAR(70),
            price VARCHAR(50),
            year INT,
            period VARCHAR(10),
            commodity_type VARCHAR(30)
        );
    """)
    print("Table `price_data` has been recreated.")
    insert_query = "INSERT INTO price_data (geolocation, commodity, price, commodity_type, year, period) VALUES (%s, %s, %s, %s, %s, %s);"
    data_long.replace({np.nan: None}, inplace=True)
    values = data_long.values.tolist()
    print("Inserting values to database, please wait.")
    for i in range(0, len(values), batch_size):
        batch = values[i:i + batch_size]
        cursor.executemany(insert_query, batch)
    connection.commit()
    cursor.close()
    connection.close()
    print("All data has been successfully stored in Database.")
