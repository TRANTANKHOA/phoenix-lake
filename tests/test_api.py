#!/usr/bin/env python3
"""Integration tests for Phoenix Lake API.

Usage:
    # Start backend first
    docker-compose up -d

    # Run all tests
    python3 tests/test_api.py

    # Run specific group
    python3 tests/test_api.py -k database
    python3 tests/test_api.py -k query
    python3 tests/test_api.py -k ingest
    python3 tests/test_api.py -k table
    python3 tests/test_api.py -k job
    python3 tests/test_api.py -k health

    # Base URL override
    BASE_URL=http://localhost:4000/v1 python3 tests/test_api.py
"""

import os
import sys
import json
import time
import tempfile
import struct
import pytest
import requests

BASE_URL = os.environ.get("BASE_URL", "http://localhost:4000/v1")
TIMEOUT = int(os.environ.get("TIMEOUT", "10"))


def api(method, path, **kwargs):
    """Make an API request and return (status_code, json)."""
    url = f"{BASE_URL}{path}"
    kwargs.setdefault("timeout", TIMEOUT)
    r = requests.request(method, url, **kwargs)
    try:
        body = r.json()
    except Exception:
        body = r.text
    return r.status_code, body


def create_dummy_parquet(num_rows=10):
    """Create a minimal Parquet file in /tmp."""
    # Use pyarrow if available, otherwise create a raw binary stub
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq

        table = pa.table({
            "id": pa.array(range(num_rows), type=pa.int64()),
            "name": pa.array([f"row_{i}" for i in range(num_rows)], type=pa.string()),
            "value": pa.array([i * 1.5 for i in range(num_rows)], type=pa.float64()),
        })
        path = tempfile.mktemp(suffix=".parquet")
        pq.write_table(table, path)
        return path
    except ImportError:
        return None


# ============================================================
# Health
# ============================================================

class TestHealth:
    def test_health_returns_200(self):
        status, body = api("GET", "/health")
        assert status == 200
        assert body["status"] == "healthy"

    def test_health_reports_services(self):
        status, body = api("GET", "/health")
        assert status == 200
        for key in ["duckdb", "postgres", "s3"]:
            assert key in body, f"Health response missing '{key}'"
            assert body[key] in ("connected", "healthy", "ok")


# ============================================================
# Databases
# ============================================================

class TestDatabases:
    def test_list_databases(self):
        status, body = api("GET", "/databases")
        assert status == 200
        assert "databases" in body
        assert isinstance(body["databases"], list)

    def test_get_database(self):
        status, body = api("GET", "/databases/landing")
        assert status == 200
        assert body["name"] == "landing"

    def test_get_nonexistent_database(self):
        status, body = api("GET", "/databases/does_not_exist")
        assert status == 404

    def test_create_database(self):
        status, body = api("POST", "/databases", json={
            "name": "test_db",
            "description": "Integration test database"
        })
        assert status == 201
        assert body["name"] == "test_db"

        # Cleanup
        api("DELETE", "/databases/test_db")

    def test_create_database_missing_name(self):
        status, body = api("POST", "/databases", json={"description": "no name"})
        assert status == 400

    def test_update_database(self):
        # Create first
        api("POST", "/databases", json={"name": "update_test"})

        status, body = api("PUT", "/databases/update_test", json={
            "description": "updated description"
        })
        assert status == 200
        assert body["description"] == "updated description"

        # Cleanup
        api("DELETE", "/databases/update_test")

    def test_delete_database(self):
        api("POST", "/databases", json={"name": "delete_test"})
        status, body = api("DELETE", "/databases/delete_test")
        assert status == 200
        assert body["status"] == "deleted"

    def test_delete_nonexistent_database(self):
        status, body = api("DELETE", "/databases/ghost_db")
        assert status == 404


# ============================================================
# Tables
# ============================================================

class TestTables:
    def test_list_tables(self):
        status, body = api("GET", "/table")
        assert status == 200
        assert "tables" in body
        assert isinstance(body["tables"], list)

    def test_list_tables_filter_by_database(self):
        status, body = api("GET", "/table?database=landing")
        assert status == 200
        for table in body["tables"]:
            assert table["database"] == "landing"

    def test_create_table(self):
        status, body = api("POST", "/table", json={
            "name": "test_users",
            "database": "landing",
            "columns": [
                {"name": "id", "type": "BIGINT", "nullable": False},
                {"name": "email", "type": "VARCHAR", "nullable": True},
            ]
        })
        assert status == 201
        assert body["name"] == "test_users"
        assert body["database"] == "landing"
        assert len(body["columns"]) == 2

        # Cleanup
        api("DELETE", "/table/landing/test_users")

    def test_get_table_with_schema(self):
        # Create first
        api("POST", "/table", json={
            "name": "schema_test",
            "database": "landing",
            "columns": [
                {"name": "id", "type": "BIGINT"},
                {"name": "name", "type": "VARCHAR"},
            ]
        })

        status, body = api("GET", "/table/landing/schema_test")
        assert status == 200
        assert body["name"] == "schema_test"
        assert "columns" in body
        assert len(body["columns"]) >= 2

        # Cleanup
        api("DELETE", "/table/landing/schema_test")

    def test_get_nonexistent_table(self):
        status, body = api("GET", "/table/landing/ghost_table")
        assert status == 404

    def test_update_table(self):
        api("POST", "/table", json={
            "name": "update_table_test",
            "database": "landing",
            "columns": [{"name": "id", "type": "BIGINT"}]
        })

        status, body = api("PUT", "/table/landing/update_table_test", json={
            "description": "updated table"
        })
        assert status == 200
        assert body["description"] == "updated table"

        # Cleanup
        api("DELETE", "/table/landing/update_table_test")

    def test_delete_table(self):
        api("POST", "/table", json={
            "name": "delete_table_test",
            "database": "landing",
            "columns": [{"name": "id", "type": "BIGINT"}]
        })

        status, body = api("DELETE", "/table/landing/delete_table_test")
        assert status == 200
        assert body["status"] == "deleted"

    def test_delete_nonexistent_table(self):
        status, body = api("DELETE", "/table/landing/ghost")
        assert status == 404

    def test_create_table_missing_columns(self):
        status, body = api("POST", "/table", json={
            "name": "bad_table",
            "database": "landing"
        })
        assert status == 400


# ============================================================
# Query
# ============================================================

class TestQuery:
    def test_sync_query(self):
        status, body = api("POST", "/query", json={
            "sql": "SELECT 1 as num, 'hello' as msg",
            "database": "landing",
            "timeout_ms": 10000
        })
        assert status == 200
        assert "columns" in body
        assert "rows" in body
        assert body["row_count"] >= 1

    def test_async_query_returns_202(self):
        status, body = api("POST", "/query", json={
            "sql": "SELECT * FROM generate_series(1, 1000000)",
            "database": "landing",
            "timeout_ms": 1  # Force timeout -> async
        })
        assert status == 202
        assert "job_id" in body

    def test_query_missing_sql(self):
        status, body = api("POST", "/query", json={"database": "landing"})
        assert status == 400

    def test_get_async_query_results(self):
        # Start async query
        status, body = api("POST", "/query", json={
            "sql": "SELECT * FROM generate_series(1, 1000000)",
            "database": "landing",
            "timeout_ms": 1
        })
        if status == 202:
            job_id = body["job_id"]
            # Poll until done (max 30s)
            for _ in range(30):
                time.sleep(1)
                s, b = api("GET", f"/query/{job_id}")
                assert s == 200
                if b.get("status") in ("succeed", "failed"):
                    break
            assert b["status"] == "succeed"
            assert "result" in b

    def test_cancel_query(self):
        # Start async query
        status, body = api("POST", "/query", json={
            "sql": "SELECT * FROM generate_series(1, 10000000)",
            "database": "landing",
            "timeout_ms": 1
        })
        if status == 202:
            job_id = body["job_id"]
            time.sleep(0.5)
            s, b = api("POST", f"/query/{job_id}/cancel")
            assert s == 200
            assert b["status"] == "cancelled"

    def test_get_nonexistent_query(self):
        status, body = api("GET", "/query/nonexistent-id")
        assert status == 404


# ============================================================
# Ingest
# ============================================================

class TestIngest:
    def test_upload_parquet(self):
        path = create_dummy_parquet(10)
        if path is None:
            pytest.skip("pyarrow not installed, skipping parquet upload test")

        with open(path, "rb") as f:
            status, body = api("POST", "/ingest", files={
                "file": ("test_data.parquet", f, "application/octet-stream")
            }, data={"table": "test_ingest_table"})
        assert status == 202
        assert "job_id" in body

        os.unlink(path)

    def test_upload_missing_file(self):
        status, body = api("POST", "/ingest", json={})
        assert status in (400, 422)

    def test_get_ingest_status(self):
        path = create_dummy_parquet(5)
        if path is None:
            pytest.skip("pyarrow not installed")

        with open(path, "rb") as f:
            s, b = api("POST", "/ingest", files={
                "file": ("test.parquet", f, "application/octet-stream")
            }, data={"table": "status_test"})

        if s == 202:
            job_id = b["job_id"]
            # Poll until done
            for _ in range(30):
                time.sleep(1)
                s2, b2 = api("GET", f"/ingest/{job_id}")
                assert s2 == 200
                if b2.get("status") in ("succeed", "failed"):
                    break

        os.unlink(path)

    def test_cancel_ingest(self):
        path = create_dummy_parquet(100000)
        if path is None:
            pytest.skip("pyarrow not installed")

        with open(path, "rb") as f:
            s, b = api("POST", "/ingest", files={
                "file": ("large.parquet", f, "application/octet-stream")
            }, data={"table": "cancel_test"})

        if s == 202:
            job_id = b["job_id"]
            time.sleep(0.5)
            s2, b2 = api("POST", f"/ingest/{job_id}/cancel")
            assert s2 == 200
            assert b2["status"] == "cancelled"

        os.unlink(path)

    def test_get_nonexistent_ingest(self):
        status, body = api("GET", "/ingest/nonexistent-id")
        assert status == 404


# ============================================================
# Jobs
# ============================================================

class TestJobs:
    def test_list_jobs(self):
        status, body = api("GET", "/job")
        assert status == 200
        assert "jobs" in body
        assert isinstance(body["jobs"], list)

    def test_list_jobs_filter_by_status(self):
        status, body = api("GET", "/job?status=failed")
        assert status == 200
        for job in body["jobs"]:
            assert job["status"] == "failed"

    def test_list_jobs_filter_by_queue(self):
        status, body = api("GET", "/job?queue=ingest")
        assert status == 200
        for job in body["jobs"]:
            assert job["queue"] == "ingest"

    def test_get_job(self):
        # Create a job first (via query)
        s, b = api("POST", "/query", json={
            "sql": "SELECT * FROM generate_series(1, 1000000)",
            "database": "landing",
            "timeout_ms": 1
        })
        if s == 202:
            job_id = b["job_id"]
            s2, b2 = api("GET", f"/job/{job_id}")
            assert s2 == 200
            assert b2["id"] == job_id
            assert b2["status"] in ("queued", "running", "succeed", "failed")

    def test_get_nonexistent_job(self):
        status, body = api("GET", "/job/nonexistent-id")
        assert status == 404

    def test_cancel_job(self):
        s, b = api("POST", "/query", json={
            "sql": "SELECT * FROM generate_series(1, 10000000)",
            "database": "landing",
            "timeout_ms": 1
        })
        if s == 202:
            job_id = b["job_id"]
            time.sleep(0.5)
            s2, b2 = api("POST", f"/job/{job_id}/cancel")
            assert s2 == 200
            assert b2["status"] == "cancelled"

    def test_retry_job(self):
        # This test assumes there's a failed job in the system
        # In practice, you'd create one via a failing query
        s, b = api("POST", "/query", json={
            "sql": "SELECT * FROM nonexistent_table_xyz",
            "database": "landing",
            "timeout_ms": 1
        })
        if s == 202:
            job_id = b["job_id"]
            # Wait for it to fail
            for _ in range(15):
                time.sleep(1)
                s2, b2 = api("GET", f"/job/{job_id}")
                if b2.get("status") == "failed":
                    break
            if b2.get("status") == "failed":
                s3, b3 = api("POST", f"/job/{job_id}/retry")
                assert s3 == 200
                assert b3["status"] == "retrying"


# ============================================================
# Error Handling
# ============================================================

class TestErrors:
    def test_invalid_json(self):
        status, body = api("POST", "/query",
            data="not json",
            headers={"Content-Type": "application/json"})
        assert status == 400

    def test_unknown_path(self):
        status, body = api("GET", "/nonexistent/path")
        assert status == 404


# ============================================================
# Run
# ============================================================

if __name__ == "__main__":
    print(f"Testing against: {BASE_URL}")
    print(f"Timeout: {TIMEOUT}s")
    print()
    pytest.main([__file__, "-v", "--tb=short", "-x"] + sys.argv[1:])
