defmodule PhoenixLakeWeb.IngestControllerTest do
  use PhoenixLakeWeb.ConnCase

  @parquet_path "/tmp/test_ingest.parquet"

  defp create_parquet do
    File.write!(@parquet_path, "test parquet placeholder")
    @parquet_path
  end

  defp cleanup_parquet, do: File.rm(@parquet_path)

  defp upload_file(conn, path, table) do
    upload = %Plug.Upload{
      path: path,
      filename: Path.basename(path),
      content_type: "application/octet-stream"
    }

    conn
    |> Plug.Conn.put_req_header("content-type", "multipart/form-data")
    |> post(~p"/v1/ingest", %{"file" => upload, "table" => table})
  end

  describe "POST /v1/ingest" do
    test "uploads a file and returns 202", %{conn: conn} do
      path = create_parquet()
      conn = upload_file(conn, path, "test_ingest_table")
      body = json_response(conn, 202)
      assert Map.has_key?(body, "job_id")
      assert body["status"] == "queued"
      assert body["table"] == "test_ingest_table"

      cleanup_parquet()
    end

    test "returns 400 when file is missing", %{conn: conn} do
      conn = post(conn, ~p"/v1/ingest", %{"table" => "some_table"})
      json_response(conn, 400)
    end
  end

  describe "GET /v1/ingest/:job_id" do
    test "returns ingestion status", %{conn: conn} do
      path = create_parquet()
      conn = upload_file(conn, path, "status_test")
      %{"job_id" => job_id} = json_response(conn, 202)

      conn = build_conn()
      conn = get(conn, ~p"/v1/ingest/#{job_id}")
      body = json_response(conn, 200)
      assert body["status"] in ["queued", "running", "succeed", "failed"]
      assert body["job_id"] == job_id

      cleanup_parquet()
    end

    test "returns 404 for nonexistent job", %{conn: conn} do
      conn = get(conn, ~p"/v1/ingest/nonexistent-id")
      json_response(conn, 404)
    end
  end

  describe "POST /v1/ingest/:job_id/cancel" do
    test "cancels an ingestion job", %{conn: conn} do
      path = create_parquet()
      conn = upload_file(conn, path, "cancel_test")
      %{"job_id" => job_id} = json_response(conn, 202)

      conn = build_conn()
      conn = post(conn, ~p"/v1/ingest/#{job_id}/cancel")
      body = json_response(conn, 200)
      assert body["status"] == "cancelled"

      cleanup_parquet()
    end

    test "returns 404 for nonexistent job", %{conn: conn} do
      conn = post(conn, ~p"/v1/ingest/nonexistent-id/cancel")
      json_response(conn, 404)
    end
  end
end
