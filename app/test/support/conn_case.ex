defmodule PhoenixLakeWeb.ConnCase do
  @moduledoc """
  This module defines the test case to be used by
  tests that require setting up a connection.

  It sets up the connection, adds JSON helpers,
  and provides shared setup for API tests.
  """

  use ExUnit.CaseTemplate

  using do
    quote do
      use Phoenix.ConnTest

      import PhoenixLakeWeb.Router.Helpers

      @endpoint PhoenixLakeWeb.Endpoint

      defp json_response(conn, status) do
        assert conn.status == status
        assert conn.resp_body != ""
        Jason.decode!(conn.resp_body)
      end

      defp post_json(conn, path, body \\ %{}) do
        conn
        |> put_req_header("content-type", "application/json")
        |> post(path, Jason.encode!(body))
      end

      defp put_json(conn, path, body \\ %{}) do
        conn
        |> put_req_header("content-type", "application/json")
        |> put(path, Jason.encode!(body))
      end
    end
  end

  setup _tags do
    {:ok, conn: Phoenix.ConnTest.build_conn()}
  end
end
