defmodule PhoenixLakeWeb.HealthControllerTest do
  use PhoenixLakeWeb.ConnCase

  describe "GET /v1/health" do
    test "returns 200 with status healthy", %{conn: conn} do
      conn = get(conn, ~p"/v1/health")
      body = json_response(conn, 200)
      assert body["status"] == "healthy"
    end

    test "reports service connectivity", %{conn: conn} do
      conn = get(conn, ~p"/v1/health")
      body = json_response(conn, 200)
      assert Map.has_key?(body, "duckdb")
      assert Map.has_key?(body, "postgres")
      assert Map.has_key?(body, "s3")
    end
  end
end
