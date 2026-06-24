# Stage 1: Build Elixir release
FROM hexpm/elixir:1.17.2-erlang-27.0-debian-bookworm-20240612 AS builder

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY app/mix.exs app/mix.lock ./
RUN mix deps.get --only prod && mix deps.compile

COPY app/config ./config
COPY app/lib ./lib
COPY app/priv ./priv

ENV MIX_ENV=prod
RUN mix release

# Stage 2: Runtime — stateless Oban workers + Phoenix
# No DuckDB binary needed. Workers submit SQL to DuckDB service via Postgres protocol.
FROM python:3.12-slim-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install dbt-core + dbt-postgres (for connecting to DuckDB service via Postgres wire protocol)
RUN pip install --no-cache-dir dbt-core dbt-postgres

# Install Elixir runtime from builder
COPY --from=builder /app/_build/prod/rel/phoenix_lake ./app

ENV HOME=/home/app
RUN useradd -m -d /home/app app && chown -R app:app /home/app
USER app

WORKDIR /home/app

EXPOSE 4000

CMD ["app/bin/phoenix_lake", "start"]
