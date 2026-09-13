import os
from app.db.session import engine, SessionLocal
from app.models import Hospital, User, Transaction, TransactionItem, FWAResult, IntegrationEvent
print("Engine:", engine.url)
db = SessionLocal()
print("Hospitals:", db.query(Hospital).count())
print("Users:", db.query(User).count())
print("Transactions:", db.query(Transaction).count())
txs = db.query(Transaction).order_by(Transaction.created_at.desc()).limit(5).all()
for tx in txs:
    print(f"TX: {tx.transaction_id} | Hosp: {tx.hospital_id} | Created: {tx.created_at} | Status: {tx.status}")
