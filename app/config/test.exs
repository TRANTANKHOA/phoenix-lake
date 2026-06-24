import Config

config :phoenix_lake, PhoenixLakeWeb.Endpoint,
  http: [ip: {127, 0, 0, 1}, port: 4002],
  secret_key_base: "test_secret_key_base_that_is_at_least_64_bytes_long_for_test_purposes_only",
  server: false

config :phoenix_lake, PhoenixLake.Repo,
  username: "postgres",
  password: "postgres",
  hostname: "localhost",
  database: "phoenix_lake_test#{System.get_env("MIX_TEST_PARTITION")}",
  pool: Ecto.Adapters.SQL.Sandbox,
  pool_size: System.schedulers_online() * 2

config :phoenix_lake, :duckdb_service,
  host: "localhost",
  port: 8081,
  timeout: 5_000,
  memory_limit: "1GB"

config :logger, level: :warning
config :phoenix, :plug_init_mode, :runtime
