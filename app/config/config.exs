import Config

config :phoenix_lake,
  generators: [timestamp_type: :utc_datetime]

config :phoenix_lake, PhoenixLakeWeb.Endpoint,
  url: [host: "localhost"],
  adapter: Phoenix.Endpoint.Cowboy2Adapter,
  render_errors: [
    formats: [html: PhoenixLakeWeb.ErrorHTML, json: PhoenixLakeWeb.ErrorJSON],
    layout: false
  ],
  pubsub_server: PhoenixLake.PubSub,
  live_view: [signing_salt: "kHt3xRfj"]

config :phoenix_lake, :generators,
  context_app: :phoenix_lake

config :logger, :console,
  format: "$time $metadata[$level] $message\n",
  metadata: [:request_id]

config :phoenix, :json_library, Jason

config :oban, repo: PhoenixLake.Repo

import_config "#{config_env()}.exs"
