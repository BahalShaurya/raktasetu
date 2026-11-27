#!/usr/bin/env python3
"""Stores a salted hash (never the plain text) in member.password_hash for the demo accounts.
Demo passwords: admin -> admin123 ; every other member -> rotaract@123"""
import sys, psycopg2
from werkzeug.security import generate_password_hash
host = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"
user = sys.argv[2] if len(sys.argv) > 2 else "postgres"
con = psycopg2.connect(host=host, user=user, dbname="raktasetu")
cur = con.cursor()
cur.execute("SELECT member_id, role FROM member")
for mid, role in cur.fetchall():
    cur.execute("UPDATE member SET password_hash=%s WHERE member_id=%s",
                (generate_password_hash("admin123" if role == "ADMIN" else "rotaract@123"), mid))
con.commit(); print("passwords set for demo accounts")
