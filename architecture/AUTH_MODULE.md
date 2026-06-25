# Auth Module Design

## Overview

Two authentication paths that coexist:

1. **Interactive login** — browser-based, delegates to an identity provider
   (Google, WorkOS, Okta). Uses [Assent](https://hexdocs.pm/assent) library
   for multi-provider OAuth2/OIDC.
2. **API tokens** — programmatic access for CI, dbt runners, service accounts.
   No IdP involved.

Authorization (grants) is the same for both paths. DuckDB trusts the control
plane and never sees unauthenticated requests.

## Architecture

```
                          ┌─────────────────────────┐
                          │   Identity Provider      │
                          │   (Google / WorkOS / Okta)│
                          └────────────┬────────────┘
                                       │ OAuth2 / OIDC
                                       ▼
┌─────────────────────────────────────────────────────────────────┐
│  Phoenix Auth                                                   │
│                                                                 │
│  Path 1: Interactive (browser)                                  │
│  ├─ Assent strategy → IdP redirect → callback                   │
│  ├─ IdP provides: email, name, groups                           │
│  ├─ Phoenix finds/creates User, maps groups → role              │
│  └─ Session cookie for subsequent requests                      │
│                                                                 │
│  Path 2: API token (programmatic)                               │
│  ├─ Authorization: Bearer pk_live_...                           │
│  ├─ Hash lookup → user + grants                                 │
│  └─ No IdP, no session                                          │
│                                                                 │
│  Both paths → Authorize plug → Grant check → Controller         │
└─────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
                              Postgres
                         (users, tokens, grants)
```

## Schemas

### User

```elixir
defmodule PhoenixLake.Accounts.User do
  use Ecto.Schema

  schema "users" do
    field :email, :string
    field :name, :string
    field :role, Ecto.Enum, values: [:admin, :editor, :viewer]
    field :provider, :string              # "google", "workos", "okta", "local"
    field :provider_uid, :string          # IdP's unique user ID
    field :active, :boolean, default: true
    has_many :tokens, PhoenixLake.Accounts.Token
    has_many :grants, PhoenixLake.Accounts.Grant
    timestamps()
  end
end
```

Users can be provisioned two ways:
- **Admin creates** — local accounts (email/password or API-only)
- **IdP auto-provisions** — on first OAuth login, matching by email

### Token (API Keys)

```elixir
defmodule PhoenixLake.Accounts.Token do
  use Ecto.Schema

  schema "tokens" do
    field :key_hash, :string           # bcrypt hash
    field :key_prefix, :string         # first 8 chars (pk_live_...)
    field :name, :string               # "CI pipeline", "dbt runner"
    field :scopes, {:array, :string}, default: ["read", "write"]
    field :expires_at, :utc_datetime, virtual: true
    belongs_to :user, PhoenixLake.Accounts.User
    timestamps()
  end
end
```

**Key format:** `pk_live_<48 random chars>` — hash stored, prefix for ID only.

### Grant

Row-level access control per dataset and optionally per table.

```elixir
defmodule PhoenixLake.Accounts.Grant do
  use Ecto.Schema

  schema "grants" do
    field :database, :string           # "landing", "refining", "reporting", or "*"
    field :table, :string              # table name or "*" for all tables
    field :permission, Ecto.Enum, values: [:read, :write, :admin]
    belongs_to :user, PhoenixLake.Accounts.User
    timestamps()
  end
end
```

**Wildcard semantics:**
- `database: "*", table: "*"` → full access to all databases
- `database: "landing", table: "*"` → all tables in landing
- `database: "landing", table: "orders"` → only orders in landing

## Roles

| Role | Can do |
|------|--------|
| `admin` | Full access. Manage users, tokens, grants. |
| `editor` | Read + write data. Create/drop tables. Cannot manage users. |
| `viewer` | Read-only. Can run queries but not ingest. |

Roles are checked at the controller level. Grants are checked at the
dataset/table level for fine-grained access. When an IdP user belongs to
multiple groups, the highest role wins: admin > editor > viewer.

## Authentication Flows

### Flow 1: Interactive Login (IdP)

```
┌──────────┐     ┌─────────┐     ┌──────────┐     ┌──────────┐
│  Browser  │     │ Phoenix  │     │  Assent   │     │   IdP    │
└─────┬────┘     └────┬────┘     └─────┬────┘     └────┬─────┘
      │               │                │                │
      │ 1. GET /auth/:provider         │                │
      │──────────────>│                │                │
      │               │                │                │
      │               │ 2. authorize_url(config)       │
      │               │──────────────>│                │
      │               │                │                │
      │               │ 3. {:ok, url, session_params}  │
      │               │<──────────────│                │
      │               │                │                │
      │  4. 302 redirect to IdP        │                │
      │<──────────────│                │                │
      │               │                │                │
      │  5. User logs in at IdP        │                │
      │───────────────────────────────────────────────>│
      │               │                │                │
      │  6. 302 redirect with code     │                │
      │<───────────────────────────────────────────────│
      │               │                │                │
      │  7. GET /auth/:provider/callback?code=...      │
      │──────────────>│                │                │
      │               │                │                │
      │               │ 8. callback(config, params, session_params)
      │               │──────────────>│                │
      │               │                │  9. exchange code for token
      │               │                │──────────────>│
      │               │                │  10. token    │
      │               │                │<──────────────│
      │               │                │                │
      │               │                │  11. fetch userinfo
      │               │                │──────────────>│
      │               │                │  12. userinfo │
      │               │                │<──────────────│
      │               │                │                │
      │               │ 13. {:ok, user, token}          │
      │               │<──────────────│                │
      │               │                │                │
      │               │ 14. find_or_create_user(email, groups)
      │               │──────┐        │                │
      │               │      │        │                │
      │               │<─────┘        │                │
      │               │                │                │
      │ 15. 302 redirect to /dashboard│                │
      │  + set session cookie         │                │
      │<──────────────│                │                │
      │               │                │                │
      │  16. GET /dashboard (session)  │                │
      │──────────────>│                │                │
      │               │ 17. validate session, attach user
      │               │──────┐        │                │
      │               │<─────┘        │                │
      │  18. 200 OK                   │                │
      │<──────────────│                │                │
```

**Key steps:**
- Step 2-3: Assent generates authorization URL + stores PKCE/state in session
- Step 8-12: Assent exchanges code, fetches userinfo via provider strategy
- Step 14: Phoenix maps IdP groups → role, creates/updates User record
- Step 15: Session cookie set for subsequent requests

### Flow 2: API Token Authentication

```
┌──────────┐     ┌─────────┐     ┌──────────┐
│  Client   │     │ Phoenix  │     │ Postgres  │
└─────┬────┘     └────┬────┘     └────┬─────┘
      │               │                │
      │ 1. POST /v1/query              │
      │  Authorization: Bearer pk_live_abc123...
      │──────────────>│                │
      │               │                │
      │               │ 2. extract_token(conn)
      │               │──────┐        │
      │               │<─────┘        │
      │               │                │
      │               │ 3. hash key    │
      │               │──────┐        │
      │               │<─────┘        │
      │               │                │
      │               │ 4. SELECT * FROM tokens WHERE key_prefix = ? AND key_hash = ?
      │               │──────────────>│
      │               │                │
      │               │ 5. token row   │
      │               │<──────────────│
      │               │                │
      │               │ 6. preload user│
      │               │──────────────>│
      │               │                │
      │               │ 7. user        │
      │               │<──────────────│
      │               │                │
      │               │ 8. assign(:current_user, user)
      │               │ 9. assign(:current_token, token)
      │               │ 10. assign(:auth_method, :token)
      │               │──────┐        │
      │               │<─────┘        │
      │               │                │
      │               │ 11. Authorize plug checks grants
      │               │──────┐        │
      │               │<─────┘        │
      │               │                │
      │ 12. 200 OK (or 401/403)        │
      │<──────────────│                │
```

**Key steps:**
- Step 3: Bcrypt hash of the full key (slow — prevents timing attacks)
- Step 4: Lookup by prefix (fast) + hash (slow — but prefix narrows to 1 row)
- Step 8-10: Attach user + token to conn for downstream plugs

### Flow 3: Dataset/Table Authorization

```
┌──────────┐     ┌─────────┐     ┌──────────┐
│  Client   │     │ Phoenix  │     │ Postgres  │
└─────┬────┘     └────┬────┘     └────┬─────┘
      │               │                │
      │ 1. POST /v1/query              │
      │  {"sql": "...", "database": "landing"}
      │──────────────>│                │
      │               │                │
      │               │ 2. Auth plug validates token/session
      │               │──────┐        │
      │               │<─────┘        │
      │               │                │
      │               │ 3. Authorize plug: extract database + table
      │               │──────┐        │
      │               │      │        │
      │               │      │ database = "landing"
      │               │      │ table = nil (multi-table query)
      │               │<─────┘        │
      │               │                │
      │               │ 4. SELECT EXISTS (
      │               │      SELECT 1 FROM grants
      │               │      WHERE user_id = ?
      │               │        AND (database = 'landing' OR database = '*')
      │               │        AND (table = '*' OR table IS NULL)
      │               │        AND permission = 'read'
      │               │    )
      │               │──────────────>│
      │               │                │
      │               │ 5. true/false  │
      │               │<──────────────│
      │               │                │
      │               │ 6. if true: proceed
      │               │    if false: 403 Forbidden
      │               │──────┐        │
      │               │<─────┘        │
      │               │                │
      │ 7. 200 OK (or 403 Forbidden)   │
      │<──────────────│                │
```

**Grant check logic:**
- Admin role → always authorized (bypasses grant check)
- Editor role → needs grant for read or write
- Viewer role → needs grant for read only
- Wildcard `*` matches any value for that dimension

## IdP Configuration

### Library

Use [Assent](https://hexdeps.pm/assent) — the standard Elixir library for
multi-provider OAuth2/OIDC. Supports Google, WorkOS, Okta, and 20+ providers
out of the box.

```elixir
# mix.exs
defp deps do
  [
    {:assent, "~> 0.3"},
    {:jose, "~> 1.8"}  # JWT adapter
  ]
end
```

### Provider config

```elixir
# config/runtime.exs
config :phoenix_lake, :auth_providers,
  google: [
    strategy: Assent.Strategy.Google,
    client_id: System.get_env("GOOGLE_CLIENT_ID"),
    client_secret: System.get_env("GOOGLE_CLIENT_SECRET"),
    redirect_uri: System.get_env("GOOGLE_REDIRECT_URI")
  ],
  workos: [
    strategy: Assent.Strategy.OAuth2,
    base_url: "https://api.workos.com",
    authorize_url: "/sso/authorize",
    token_url: "/sso/token",
    user_url: "/sso/profiles",
    client_id: System.get_env("WORKOS_CLIENT_ID"),
    client_secret: System.get_env("WORKOS_API_KEY"),
    authorization_params: [connection: System.get_env("WORKOS_CONNECTION_ID")]
  ],
  okta: [
    strategy: Assent.Strategy.OIDC,
    client_id: System.get_env("OKTA_CLIENT_ID"),
    client_secret: System.get_env("OKTA_CLIENT_SECRET"),
    base_url: "https://#{System.get_env("OKTA_DOMAIN")}"
  ]
```

### Group → role mapping

```elixir
# config/runtime.exs
config :phoenix_lake, :auth_roles,
  group_mapping: %{
    "data-admins" => :admin,
    "data-engineers" => :editor,
    "data-analysts" => :viewer
  },
  default_role: :viewer
```

## Plugs

### `PhoenixLakeWeb.Plugs.Auth`

Handles both API tokens and session-based auth.

```elixir
defmodule PhoenixLakeWeb.Plugs.Auth do
  import Plug.Conn

  def init(opts), do: opts

  def call(conn, _opts) do
    cond do
      # Path 1: API token
      token = extract_bearer_token(conn) ->
        with {:ok, user, token} <- validate_token(token) do
          conn
          |> assign(:current_user, user)
          |> assign(:current_token, token)
          |> assign(:auth_method, :token)
        else
          _ -> unauthorized(conn)
        end

      # Path 2: Session cookie (from IdP login)
      user_id = get_session(conn, :user_id) ->
        with {:ok, user} <- validate_session(user_id) do
          conn
          |> assign(:current_user, user)
          |> assign(:current_token, nil)
          |> assign(:auth_method, :session)
        else
          _ -> unauthorized(conn)
        end

      # No auth
      true ->
        unauthorized(conn)
    end
  end

  defp extract_bearer_token(conn) do
    case get_req_header(conn, "authorization") do
      ["Bearer " <> key] -> key
      _ -> nil
    end
  end

  defp validate_token(key) do
    # The stored key_hash is a bcrypt digest (random salt), so it cannot be
    # matched by an equality lookup. Look up the token by its 8-char prefix,
    # then verify the full secret against the stored hash with Bcrypt.verify_pass/2.
    prefix = String.slice(key, 0, 8)

    case PhoenixLake.Repo.get_by(Token, key_prefix: prefix) do
      nil ->
        :error

      token ->
        # verify_pass is constant-time and safe against timing leaks; it also
        # returns false (not raises) when the hash/format is invalid.
        if Bcrypt.verify_pass(key, token.key_hash) and not expired?(token) do
          user = PhoenixLake.Repo.preload(token, :user).user
          if user.active, do: {:ok, user, token}, else: :error
        else
          :error
        end
    end
  end

  defp expired?(%{expires_at: nil}), do: false
  defp expired?(%{expires_at: expires_at}) do
    DateTime.compare(expires_at, DateTime.utc_now()) == :lt
  end

  defp validate_session(user_id) do
    case PhoenixLake.Repo.get_by(User, id: user_id) do
      nil -> :error
      user -> if user.active, do: {:ok, user}, else: :error
    end
  end

  defp unauthorized(conn) do
    conn
    |> put_status(:unauthorized)
    |> Phoenix.Controller.json(%{error: %{code: "unauthorized", message: "Invalid or missing credentials"}})
    |> halt()
  end
end
```

### `PhoenixLakeWeb.Plugs.Authorize`

Unchanged — checks grants regardless of auth method.

```elixir
defmodule PhoenixLakeWeb.Plugs.Authorize do
  import Plug.Conn

  def init(opts), do: opts

  def call(conn, opts) do
    user = conn.assigns.current_user
    permission = Keyword.get(opts, :permission, :read)
    database = resolve_param(opts, :database, conn)
    table = resolve_param(opts, :table, conn)

    if authorized?(user, permission, database, table) do
      conn
    else
      conn
      |> put_status(:forbidden)
      |> Phoenix.Controller.json(%{error: %{code: "forbidden", message: "Insufficient permissions"}})
      |> halt()
    end
  end

  defp resolve_param(opts, key, conn) do
    case Keyword.get(opts, key) do
      fun when is_function(fun, 1) -> fun.(conn)
      value -> value
    end
  end

  defp authorized?(%{role: :admin}, _perm, _db, _tbl), do: true
  defp authorized?(%{role: role}, :read, db, tbl) when role in [:editor, :viewer] do
    PhoenixLake.Accounts.granted?(role, :read, db, tbl)
  end
  defp authorized?(%{role: :editor}, :write, db, tbl) do
    PhoenixLake.Accounts.granted?(:editor, :write, db, tbl)
  end
  defp authorized?(_, _, _, _), do: false
end
```

## Auth Controller (Assent Integration)

```elixir
defmodule PhoenixLakeWeb.AuthController do
  use Phoenix.Controller

  @doc "Redirect to IdP"
  def redirect(conn, %{"provider" => provider}) do
    config = provider_config!(provider)

    case config[:strategy].authorize_url(config) do
      {:ok, %{url: url, session_params: session_params}} ->
        conn
        |> put_session(:oauth_provider, provider)
        |> put_session(:oauth_session_params, session_params)
        |> put_resp_header("location", url)
        |> send_resp(302, "")

      {:error, _error} ->
        conn
        |> put_status(500)
        |> json(%{error: "Failed to initiate authentication"})
    end
  end

  @doc "Handle IdP callback"
  def callback(conn, %{"provider" => provider} = params) do
    config = provider_config!(provider)
    session_params = get_session(conn, :oauth_session_params)

    conn = delete_session(conn, :oauth_session_params)

    config
    |> Keyword.put(:session_params, session_params)
    |> config[:strategy].callback(params)
    |> case do
      {:ok, %{user: idp_user}} ->
        with {:ok, user} <- PhoenixLake.Auth.find_or_create_user(provider, idp_user) do
          conn
          |> put_session(:user_id, user.id)
          |> put_resp_header("location", "/dashboard")
          |> send_resp(302, "")
        else
          {:error, reason} ->
            conn
            |> put_status(500)
            |> json(%{error: reason})
        end

      {:error, _error} ->
        conn
        |> put_status(401)
        |> json(%{error: "Authentication failed"})
    end
  end

  @doc "Log out"
  def logout(conn, _params) do
    conn
    |> configure_session(drop: true)
    |> put_resp_header("location", "/")
    |> send_resp(302, "")
  end

  defp provider_config!(provider) do
    provider = String.to_existing_atom(provider)

    Application.get_env(:phoenix_lake, :auth_providers)[provider] ||
      raise "No provider configuration for #{provider}"
  end
end
```

## Auth Context Module

```elixir
defmodule PhoenixLake.Auth do
  alias PhoenixLake.Repo
  alias PhoenixLake.Accounts.User

  @doc "Find or create user from IdP userinfo. Maps groups → role."
  def find_or_create_user(provider, idp_user) do
    email = idp_user["email"]
    name = idp_user["name"] || idp_user["nickname"]
    provider_uid = idp_user["sub"] || idp_user["id"]
    groups = extract_groups(idp_user)

    role = resolve_role(groups)

    case Repo.get_by(User, email: email) do
      nil ->
        %User{}
        |> User.changeset(%{
          email: email,
          name: name,
          provider: to_string(provider),
          provider_uid: provider_uid,
          role: role
        })
        |> Repo.insert()

      user ->
        # Update provider info, upgrade role if groups changed
        user
        |> User.changeset(%{
          name: name,
          provider_uid: provider_uid,
          role: max_role(user.role, role)
        })
        |> Repo.update()
    end
  end

  defp extract_groups(idp_user) do
    # IdP-specific group extraction
    # Google: idp_user["groups"] or fetch from Admin SDK
    # WorkOS: idp_user["raw_attributes"]["groups"]
    # Okta: idp_user["groups"]
    idp_user["groups"] ||
      get_in(idp_user, ["raw_attributes", "groups"]) ||
      []
  end

  defp resolve_role(groups) do
    mapping = Application.get_env(:phoenix_lake, :auth_roles)[:group_mapping] || %{}
    default = Application.get_env(:phoenix_lake, :auth_roles)[:default_role] || :viewer

    groups
    |> Enum.map(&Map.get(mapping, &1))
    |> Enum.reject(&is_nil/1)
    |> Enum.reduce(default, &max_role/2)
  end

  defp max_role(:admin, _), do: :admin
  defp max_role(_, :admin), do: :admin
  defp max_role(:editor, _), do: :editor
  defp max_role(_, :editor), do: :editor
  defp max_role(_, _), do: :viewer
end
```

## Router Usage

```elixir
pipeline :browser do
  plug :fetch_session
  plug PhoenixLakeWeb.Plugs.Auth
end

pipeline :api do
  plug PhoenixLakeWeb.Plugs.Auth
end

# IdP routes (browser)
scope "/auth", PhoenixLakeWeb do
  pipe_through :browser

  get "/:provider", AuthController, :redirect
  get "/:provider/callback", AuthController, :callback
  delete "/logout", AuthController, :logout
end

# API routes
scope "/v1", PhoenixLakeWeb do
  pipe_through :api

  get "/health", HealthController, :index

  get "/databases", DatabaseController, :index
  post "/databases", DatabaseController, :create
  get "/databases/:database", DatabaseController, :show
  put "/databases/:database", DatabaseController, :update
  delete "/databases/:database", DatabaseController, :delete

  get "/table", TableController, :index
  post "/table", TableController, :create
  get "/table/:database/:table", TableController, :show
  put "/table/:database/:table", TableController, :update
  delete "/table/:database/:table", TableController, :delete

  post "/query", QueryController, :create
  get "/query/:job_id", QueryController, :show
  post "/query/:job_id/cancel", QueryController, :cancel

  post "/ingest", IngestController, :create
  get "/ingest/:job_id", IngestController, :show
  post "/ingest/:job_id/cancel", IngestController, :cancel

  get "/job", JobController, :index
  get "/job/:job_id", JobController, :show
  post "/job/:job_id/cancel", JobController, :cancel
  post "/job/:job_id/retry", JobController, :retry
end
```

## Database Migrations

```elixir
defmodule PhoenixLake.Repo.Migrations.CreateAccounts do
  use Ecto.Migration

  def change do
    create table(:users) do
      add :email, :string, null: false
      add :name, :string
      add :role, :string, null: false, default: "viewer"
      add :provider, :string
      add :provider_uid, :string
      add :active, :boolean, null: false, default: true
      timestamps()
    end

    create unique_index(:users, [:email])
    create unique_index(:users, [:provider, :provider_uid])

    create table(:tokens) do
      add :user_id, references(:users, on_delete: :delete_all), null: false
      add :key_hash, :string, null: false
      add :key_prefix, :string, null: false
      add :name, :string
      add :scopes, {:array, :string}, null: false, default: ["read", "write"]
      timestamps()
    end

    create index(:tokens, [:key_prefix])
    create index(:tokens, [:user_id])

    create table(:grants) do
      add :user_id, references(:users, on_delete: :delete_all), null: false
      add :database, :string, null: false
      add :table, :string, null: false, default: "*"
      add :permission, :string, null: false
      timestamps()
    end

    create index(:grants, [:user_id])
    create unique_index(:grants, [:user_id, :database, :table, :permission])
  end
end
```

## Security Properties

| Property | Mechanism |
|----------|-----------|
| Token secrecy | Key hash stored; prefix only for identification |
| Token revocation | Delete token row; next request fails |
| Session security | Server-side session, secure cookie, SameSite=Strict |
| IdP trust | Assent validates JWT signature or uses token exchange |
| PKCE | Assent uses PKCE for OAuth2 flows (prevents code interception) |
| No token in logs | Plug strips `Authorization` header before logging |
| Rate limiting | Per-token rate limit via Oban or PlugAttack |
| Audit trail | Every query/ingest logs `user_id` + `token_id` + `auth_method` |
| Multi-tenant isolation | Grants enforced at control plane; DuckDB sees only scoped tables |

## References

- [Assent docs](https://hexdocs.pm/assent) — Multi-provider OAuth2/OIDC library
- [Assent Google strategy](https://hexdocs.pm/assent/Assent.Strategy.Google.html)
- [Assent OIDC strategy](https://hexdocs.pm/assent/Assent.Strategy.OIDC.html)
- [WorkOS SSO docs](https://workos.com/docs/sso) — SAML/OIDC middleware
- [OpenID Connect claims](https://openid.net/specs/openid-connect-core-1_0.html#rfc.section.5.1)

## Design Decisions

| # | Issue | Decision | Why |
|---|-------|----------|-----|
| D1 | `Bcrypt.hash_pwd_salt` generates new salt each call — stored hash never matches | Two-step: (1) lookup by `key_prefix` only, (2) `Bcrypt.verify_pass` against stored hash | Prefix narrows to 1 row (fast), verify is constant-time (no timing attack) |
| D2 | `expires_at` field exists but validation ignores it | Check after bcrypt: reject if `expires_at` in the past | Tokens should be revocable by time |
| D3 | WorkOS has both OAuth2 and OIDC connections | Keep `Assent.Strategy.OAuth2` | Simpler, no OIDC discovery endpoint needed, same userinfo output |
| D4 | Google doesn't return groups in userinfo | Admin SDK call at login, or Oban background sync | Admin SDK: real-time but adds latency. Sync: faster login but eventual consistency |
| D5 | No visibility into token usage | Add `last_used_at`, updated on each validation | Audit trail, stale cleanup, security monitoring |
| D6 | Concurrent OAuth logins race on user insert | `Repo.insert(on_conflict: :nothing)` + unique index on `email` | Race-safe, no duplicate rows |
