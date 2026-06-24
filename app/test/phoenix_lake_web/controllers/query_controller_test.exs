defmodule PhoenixLakeWeb.QueryControllerTest do
  use PhoenixLakeWeb.ConnCase

  @sync_query %{sql: "SELECT 1 as num, 'hello' as msg", database: "landing", timeout_ms: 10_000}
  @async_query %{sql: "SELECT * FROM generate_series(1, 1000000)", database: "landing", timeout_ms: 1}

  describe "POST /v1/query (sync)" do
    test "returns query results when completed within timeout", %{conn: conn} do
      conn = post_json(conn, ~p"/v1/query", @sync_query)
      body = json_response(conn, 200)
      assert Map.has_key?(body, "columns")
      assert Map.has_key?(body, "rows")
      assert body["row_count"] >= 1
      assert Map.has_key?(body, "duration_ms")
    end

    test "returns 400 when sql is missing", %{conn: conn} do
      conn = post_json(conn, ~p"/v1/query", %{database: "landing"})
      json_response(conn, 400)
    end

    test "returns 400 with empty body", %{conn: conn} do
      conn = post_json(conn, ~p"/v1/query", %{})
      json_response(conn, 400)
    end
  end

  describe "POST /v1/query (async)" do
    test "returns 202 with job_id when timeout exceeded", %{conn: conn} do
      conn = post_json(conn, ~p"/v1/query", @async_query)
      body = json_response(conn, 202)
      assert Map.has_key?(body, "job_id")
      assert Map.has_key?(body, "status")
      assert body["status"] == "queued"
    end
  end

  describe "GET /v1/query/:job_id" do
    test "returns job status for pending query", %{conn: conn} do
      # Enqueue async query
      conn = post_json(conn, ~p"/v1/query", @async_query)
      %{"job_id" => job_id} = json_response(conn, 202)

      # Poll status
      conn = build_conn()
      conn = get(conn, ~p"/v1/query/#{job_id}")
      body = json_response(conn, 200)
      assert body["status"] in ["queued", "running", "succeed", "failed"]
      assert body["job_id"] == job_id
    end

    test "returns 404 for nonexistent job", %{conn: conn} do
      conn = get(conn, ~p"/v1/query/nonexistent-id")
      json_response(conn, 404)
    end
  end

  describe "POST /v1/query/:job_id/cancel" do
    test "cancels a running query", %{conn: conn} do
      conn = post_json(conn, ~p"/v1/query", @async_query)
      %{"job_id" => job_id} = json_response(conn, 202)

      conn = build_conn()
      conn = post(conn, ~p"/v1/query/#{job_id}/cancel")
      body = json_response(conn, 200)
      assert body["status"] == "cancelled"
      assert body["job_id"] == job_id
    end

    test "returns 404 for nonexistent job", %{conn: conn} do
      conn = post(conn, ~p"/v1/query/nonexistent-id/cancel")
      json_response(conn, 404)
    end
  end
end
