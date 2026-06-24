ExUnit.start()

Application.put_env(:phoenix_lake, PhoenixLakeWeb.Endpoint,
  http: [ip: {127, 0, 0, 1}, port: 0],
  server: false,
  secret_key_base: String.duplicate("a", 64)
)
