# Reach Frontend

React dashboard for the Reach assignment. The app provides authentication,
tenant-aware job monitoring and submission, API key management, workspace limit
visibility, and profile details against the FastAPI backend.

## Tech Stack

- **Vite** for a fast local dev server and simple production builds.
- **React 19 + TypeScript** for typed component code and explicit API contracts.
- **TanStack Query** for server-state caching, mutation handling, pagination, and
  query invalidation after job/API-key updates.
- **Tailwind CSS v4** for utility-first styling through the Vite plugin.
- **shadcn/ui + Radix UI** for accessible, copy-owned UI primitives rather than a
  heavy component framework.
- **lucide-react** for consistent iconography across dashboard navigation,
  actions, and status indicators.
- **Geist variable font** for a compact operational dashboard look.

## Prerequisites

- Node.js 24 is used by the Docker image. A recent Node version with Corepack
  enabled is recommended for local development.
- pnpm. The Docker image prepares `pnpm@10.15.1`; locally you can use Corepack:

```bash
corepack enable
corepack prepare pnpm@10.15.1 --activate
```

## Setup

Install frontend dependencies from this directory:

```bash
cd frontend
pnpm install
```

The frontend calls the backend from `VITE_API_BASE_URL`. If the variable is not
set, it defaults to `http://127.0.0.1:8000`.

For local development against a backend on the default port, no frontend env file
is required. To point at a different backend, create `frontend/.env.local`:

```bash
VITE_API_BASE_URL=http://127.0.0.1:8000
```

The API client removes trailing slashes and then calls backend routes under
`/api/v1`. The jobs stream uses the same origin and converts `http`/`https` to
`ws`/`wss` for the WebSocket endpoint.

## Run Locally

Start the backend first. From the repository root, the simplest path is:

```bash
docker compose up server worker lease-reaper postgres
```

Then start the frontend from `frontend/`:

```bash
pnpm dev
```

Vite serves the app at:

```text
http://localhost:5173
```

Useful scripts:

```bash
pnpm dev        # start the Vite development server
pnpm build      # run TypeScript project build and create a production bundle
pnpm preview    # preview the production bundle locally
pnpm lint       # run ESLint
pnpm typecheck  # run TypeScript without emitting files
pnpm format     # format TypeScript/TSX files with Prettier
```

## Run With Docker Compose

From the repository root:

```bash
docker compose up frontend server worker lease-reaper postgres
```

Compose builds the frontend container, installs pnpm dependencies, mounts the
local `frontend/` directory into the container, and exposes Vite on
`FRONTEND_PORT` or `5173` by default.

The Compose file also sets:

```text
VITE_API_BASE_URL=http://127.0.0.1:${SERVER_PORT:-8000}
```

If you change the frontend port, make sure the backend CORS origins include the
matching frontend URL. The provided Compose configuration handles this through
`FRONTEND_PORT`.

## Code Structure

```text
src/
  main.tsx                    React root, QueryClientProvider, theme provider
  App.tsx                     Authenticated vs unauthenticated app switch
  index.css                   Tailwind, shadcn tokens, font import, theme vars
  components/
    theme-provider.tsx        App theme wrapper
    ui/                       Local shadcn/Radix UI primitives
  features/
    auth/                     Login/signup screens, forms, auth query hook
    dashboard/                Main dashboard shell and dashboard data hooks
      api-keys/               API key list, create, revoke, reveal dialog
      jobs/                   Job submit form, table, status badge, details
      components/             Dashboard-specific reusable display components
  lib/
    api-client.ts             API origin, error normalization, auth headers
    auth-api.ts               Auth endpoints and local token persistence
    jobs-api.ts               Job endpoints, metrics, and WebSocket URL
    api-keys-api.ts           API key endpoints
    query-client.ts           TanStack Query defaults
    utils.ts                  Shared class-name merging helper
```

The app keeps shared infrastructure in `src/lib`, reusable UI primitives in
`src/components/ui`, and product behavior in `src/features`. Feature folders own
their screen components, local subcomponents, and query hooks so dashboard and
auth code can evolve independently.

## Data Flow

1. `main.tsx` creates the React tree and provides TanStack Query.
2. `App.tsx` calls `useAuth()` and renders either `AuthScreen` or
   `DashboardScreen`.
3. Auth tokens are stored in `localStorage` under `reach.authToken.v1`.
4. API modules in `src/lib` wrap `fetch`, normalize FastAPI error responses, and
   attach bearer tokens where needed.
5. Dashboard queries fetch jobs, metrics, job events, and API keys. Mutations
   invalidate the relevant query keys after successful changes.
6. `useJobStatusStream()` opens the jobs WebSocket stream and invalidates job
   queries when job events arrive, keeping the table and metrics fresh.

## UI Conventions

- Add shadcn components with:

```bash
npx shadcn@latest add button
```

- Components are copied into `src/components/ui`, which keeps the app in control
  of styling and behavior.
- Use the `@/` import alias for source imports. It is configured in
  `vite.config.ts` and mirrors `components.json`.
- Use the `cn()` helper from `src/lib/utils.ts` when combining conditional
  Tailwind classes.
