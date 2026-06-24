import Config

config :phoenix_lake, PhoenixLakeWeb.Endpoint,
  url: [host: "example.com", port: 80],
  cache_static_manifest: "priv/static/cache_manifest.json"

config :phoenix_lake, PhoenixLake.Repo,
  username: "phoenix_lake",
  password: "REPLACE_WITH_REAL_PASSWORD",
  hostname: "db.example.com",
  database: "phoenix_lake_prod",
  stacktrace: false,
  ssl: true,
  pool_size: 10

config :phoenix_lake, :duckdb_service,
  host: "duckdb.internal",
  port: 8080,
  timeout: 60_000,
  memory_limit: "8GB"

config :phoenix_lake, :s3,
  bucket: "phoenix-lake-prod",
  region: "us-east-1"

config :logger, level: :info
