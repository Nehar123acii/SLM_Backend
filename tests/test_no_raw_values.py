import os
import tempfile
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from backend.db.models import Base
from backend.services.inventory import InventoryService


def test_no_raw_personal_values_in_sqlite():
    """
    Seeds sentinel phone, email, Aadhaar-format number and name;
    executes full ingestion/scan/persistence pipeline;
    inspects binary content of the SQLite DB file and WAL file;
    asserts no sentinel strings appear anywhere in the database files.
    """
    sentinel_phone = "9876543219"
    sentinel_email = "sentinel_alpha_user99@sentinelcorp.in"
    sentinel_aadhaar = "998877665544"
    sentinel_name = "SentinelTestPrincipalPerson"

    csv_content = (
        f"full_name,contact_phone,user_email,aadhaar_number\n"
        f"{sentinel_name},+91 {sentinel_phone},{sentinel_email},{sentinel_aadhaar}\n"
        f"Another Person,+91 9811122233,other@example.com,112233445566\n"
        f"Third Person,+91 9822233344,third@example.com,223344556677\n"
    )

    with tempfile.TemporaryDirectory() as tmp_dir:
        db_file = os.path.join(tmp_dir, "sentinel_kavach.db").replace("\\", "/")
        db_url = f"sqlite:///{db_file}"

        tmp_engine = create_engine(
            db_url,
            connect_args={"check_same_thread": False},
        )
        Base.metadata.create_all(bind=tmp_engine)
        TmpSession = sessionmaker(autocommit=False, autoflush=False, bind=tmp_engine)

        session = TmpSession()
        try:
            InventoryService.process_upload(
                db=session,
                original_filename="sentinel_upload.csv",
                file_bytes=csv_content.encode("utf-8"),
                source_type="csv",
            )
        finally:
            session.close()

        # Checkpoint WAL to flush all pages to the database file
        with tmp_engine.connect() as conn:
            conn.execute(text("PRAGMA wal_checkpoint(FULL)"))

        tmp_engine.dispose()

        # Read binary bytes of the SQLite file and WAL file
        db_bytes = b""
        if os.path.exists(db_file):
            with open(db_file, "rb") as f:
                db_bytes += f.read()

        wal_file = f"{db_file}-wal"
        if os.path.exists(wal_file):
            with open(wal_file, "rb") as f:
                db_bytes += f.read()

        # Assert no sentinel appears in binary bytes
        assert sentinel_phone.encode("utf-8") not in db_bytes, "Sentinel phone found in SQLite bytes!"
        assert sentinel_email.encode("utf-8") not in db_bytes, "Sentinel email found in SQLite bytes!"
        assert sentinel_aadhaar.encode("utf-8") not in db_bytes, "Sentinel Aadhaar found in SQLite bytes!"
        assert sentinel_name.encode("utf-8") not in db_bytes, "Sentinel name found in SQLite bytes!"
