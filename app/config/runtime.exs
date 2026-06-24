import Config

if config_env() == :prod do
  database_url =
    System.get_env("DATABASE_URL") ||
      raise """
      environment variable DATABASE_URL is missing.
      For example: ecto://USER:PASS@HOST/DATABASE
      """

  config :phoenix_lake, PhoenixLake.Repo,
    url: database_url,
    pool_size: String.to_integer(System.get_env("POOL_SIZE") || "10")

  secret_key_base =
    System.get_env("SECRET_KEY_BASE") ||
      raise """
      environment variable SECRET_KEY_BASE is missing.
      You can generate one by calling: mix phx.gen.secret
      """

  host = System.get_env("PHX_HOST") || "example.com"
  port = String.to_integer(System.get_env("PORT") || "4000")

  config :phoenix_lake, PhoenixLakeWeb.Endpoint,
    url: [host: host, port: 443, scheme: "https"],
    http: [
      ip: {0, 0, 0, 0, 0, 0, 0, 0},
      port: port
    ],
    secret_key_base: secret_key_base

  duckdb_host = System.get_env("DUCKDB_HOST") || "localhost"
  duckdb_port = String.to_integer(System.get_env("DUCKDB_PORT") || "8080")
  duckdb_memory = System.get_env("DUCKDB_MEMORY_LIMIT") || "4GB"

  config :phoenix_lake, :duckdb_service,
    host: duckdb_host,
    port: duckdb_port,
    timeout: 60_000,
    memory_limit: duckdb_memory

  s3_bucket = System.get_env("S3_BUCKET") || "phoenix-lake"
  s3_region = System.get_env("S3_REGION") || "us-east-1"

  config :phoenix_lake, :s3,
    bucket: s3_bucket,
    region: s3_region
end
