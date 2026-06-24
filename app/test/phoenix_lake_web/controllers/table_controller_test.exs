defmodule PhoenixLakeWeb.TableControllerTest do
  use PhoenixLakeWeb.ConnCase

  @valid_table %{
    name: "test_users",
    database: "landing",
    columns: [
      %{name: "id", type: "BIGINT", nullable: false},
      %{name: "email", type: "VARCHAR", nullable: true}
    ]
  }

  defp create_table(name \\ "test_table") do
    build_conn()
    |> post_json(~p"/v1/table", %{
      name: name,
      database: "landing",
      columns: [%{name: "id", type: "BIGINT"}]
    })
  end

  defp cleanup_table(name) do
    build_conn() |> delete(~p"/v1/table/landing/#{name}")
  end

  describe "GET /v1/table" do
    test "returns list of tables", %{conn: conn} do
      conn = get(conn, ~p"/v1/table")
      body = json_response(conn, 200)
      assert Map.has_key?(body, "tables")
      assert is_list(body["tables"])
    end

    test "filters by database", %{conn: conn} do
      conn = get(conn, ~p"/v1/table?database=landing")
      body = json_response(conn, 200)

      Enum.each(body["tables"], fn table ->
        assert table["database"] == "landing"
      end)
    end

    test "respects limit parameter", %{conn: conn} do
      conn = get(conn, ~p"/v1/table?limit=1")
      body = json_response(conn, 200)
      assert length(body["tables"]) <= 1
    end
  end

  describe "POST /v1/table" do
    test "creates a table with schema", %{conn: conn} do
      conn = post_json(conn, ~p"/v1/table", @valid_table)
      body = json_response(conn, 201)
      assert body["name"] == "test_users"
      assert body["database"] == "landing"
      assert length(body["columns"]) == 2

      cleanup_table("test_users")
    end

    test "returns 400 when columns are missing", %{conn: conn} do
      conn = post_json(conn, ~p"/v1/table", %{name: "bad", database: "landing"})
      json_response(conn, 400)
    end

    test "returns 400 when database is missing", %{conn: conn} do
      conn = post_json(conn, ~p"/v1/table", %{name: "no_db", columns: [%{name: "id", type: "BIGINT"}]})
      json_response(conn, 400)
    end
  end

  describe "GET /v1/table/:database/:table" do
    test "returns table with schema", %{conn: conn} do
      create_table("schema_test")

      conn = get(conn, ~p"/v1/table/landing/schema_test")
      body = json_response(conn, 200)
      assert body["name"] == "schema_test"
      assert Map.has_key?(body, "columns")
      assert length(body["columns"]) >= 1

      cleanup_table("schema_test")
    end

    test "returns 404 for nonexistent table", %{conn: conn} do
      conn = get(conn, ~p"/v1/table/landing/ghost_table")
      json_response(conn, 404)
    end
  end

  describe "PUT /v1/table/:database/:table" do
    test "updates table description", %{conn: conn} do
      create_table("update_test")

      conn = put_json(conn, ~p"/v1/table/landing/update_test", %{description: "updated"})
      body = json_response(conn, 200)
      assert body["description"] == "updated"

      cleanup_table("update_test")
    end

    test "returns 404 for nonexistent table", %{conn: conn} do
      conn = put_json(conn, ~p"/v1/table/landing/ghost", %{description: "x"})
      json_response(conn, 404)
    end
  end

  describe "DELETE /v1/table/:database/:table" do
    test "deletes a table", %{conn: conn} do
      create_table("delete_test")

      conn = delete(conn, ~p"/v1/table/landing/delete_test")
      body = json_response(conn, 200)
      assert body["status"] == "deleted"
    end

    test "returns 404 for nonexistent table", %{conn: conn} do
      conn = delete(conn, ~p"/v1/table/landing/ghost")
      json_response(conn, 404)
    end
  end
end
