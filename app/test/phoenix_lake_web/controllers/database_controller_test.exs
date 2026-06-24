defmodule PhoenixLakeWeb.DatabaseControllerTest do
  use PhoenixLakeWeb.ConnCase

  describe "GET /v1/databases" do
    test "returns list of databases", %{conn: conn} do
      conn = get(conn, ~p"/v1/databases")
      body = json_response(conn, 200)
      assert Map.has_key?(body, "databases")
      assert is_list(body["databases"])
    end
  end

  describe "POST /v1/databases" do
    test "creates a database", %{conn: conn} do
      conn = post_json(conn, ~p"/v1/databases", %{name: "test_db", description: "test"})
      body = json_response(conn, 201)
      assert body["name"] == "test_db"

      # Cleanup
      build_conn() |> delete(~p"/v1/databases/test_db")
    end

    test "returns 400 when name is missing", %{conn: conn} do
      conn = post_json(conn, ~p"/v1/databases", %{description: "no name"})
      json_response(conn, 400)
    end
  end

  describe "GET /v1/databases/:database" do
    test "returns database details", %{conn: conn} do
      conn = get(conn, ~p"/v1/databases/landing")
      body = json_response(conn, 200)
      assert body["name"] == "landing"
      assert Map.has_key?(body, "created_at")
      assert Map.has_key?(body, "updated_at")
    end

    test "returns 404 for nonexistent database", %{conn: conn} do
      conn = get(conn, ~p"/v1/databases/does_not_exist")
      json_response(conn, 404)
    end
  end

  describe "PUT /v1/databases/:database" do
    test "updates database", %{conn: conn} do
      build_conn() |> post_json(~p"/v1/databases", %{name: "update_test"})

      conn = put_json(conn, ~p"/v1/databases/update_test", %{description: "updated"})
      body = json_response(conn, 200)
      assert body["description"] == "updated"

      # Cleanup
      build_conn() |> delete(~p"/v1/databases/update_test")
    end
  end

  describe "DELETE /v1/databases/:database" do
    test "deletes a database", %{conn: conn} do
      build_conn() |> post_json(~p"/v1/databases", %{name: "delete_test"})

      conn = delete(conn, ~p"/v1/databases/delete_test")
      body = json_response(conn, 200)
      assert body["status"] == "deleted"
    end

    test "returns 404 for nonexistent database", %{conn: conn} do
      conn = delete(conn, ~p"/v1/databases/ghost_db")
      json_response(conn, 404)
    end
  end
end
