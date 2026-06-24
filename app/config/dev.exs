import Config

config :phoenix_lake, PhoenixLakeWeb.Endpoint,
  http: [ip: {127, 0, 0, 1}, port: 4000],
  check_origin: false,
  code_reloader: true,
  debug_errors: true,
  secret_key_base: "dev_only_secret_key_base_that_is_at_least_64_bytes_long_for_development_purposes_only",
  watchers: [
    esbuild: {Esbuild, :install_and_run, [:phoenix_lake, ~w(--sourcemap=inline --watch)]},
    tailwind: {Tailwind, :install_and_run, [:phoenix_lake, ~w(--watch)]}
  ]

config :phoenix_lake, PhoenixLakeWeb.Endpoint,
  live_reload: [
    patterns: [
      ~r"priv/static/(?!uploads/).*(js|css|png|jpeg|jpg|gif|svg)$",
      ~r"lib/phoenix_lake_web/(controllers|live|components)/.*(ex|heex)$"
    ]
  ]

config :phoenix_lake, PhoenixLake.Repo,
  username: "postgres",
  password: "postgres",
  hostname: "localhost",
  database: "phoenix_lake_dev",
  stacktrace: true,
  show_sensitive_data_on_connection_error: true,
  pool_size: 10

config :phoenix_lake, :duckdb_service,
  host: "localhost",
  port: 8080,
  timeout: 30_000,
  memory_limit: "4GB"

config :phoenix_lake, :s3,
  bucket: "phoenix-lake-dev",
  region: "us-east-1",
  endpoint: "http://localhost:9000"

config :logger, :console, format: "[$level] $message\n"
config :phoenix, :stacktrace_depth, 20
config :phoenix, :plug_init_mode, :runtime
