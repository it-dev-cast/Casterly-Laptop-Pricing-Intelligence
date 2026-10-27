# Working on Casterly Laptop Pricing Intelligence

The application source is in `backend/` and `frontend/`. Database migrations are in
`backend/alembic/`. Docker setup, templates, brand assets and documentation are
included in this repository.

## Start a change

From the local repository at `D:\Casterly\Casterly-Laptop-Pricing-Intelligence`:

```powershell
git switch main
git pull --ff-only origin main
git switch -c feature/describe-your-change
```

Keep your `.env` files local. Copy `.env.example` for a fresh installation and
configure your own credentials. Private historical workbooks belong in
`references/`, or `backend/tests/fixtures/reference/` for local regression testing;
both directories exclude workbooks from Git. Existing Docker database/upload
volumes are local runtime data, not part of the repository.

## Validate and commit

Run the checks relevant to your change. For the complete suite:

```powershell
python -m pip install -r backend/requirements-dev.txt
Push-Location backend
python -m pytest tests -q
Pop-Location
npm --prefix frontend ci
npm --prefix frontend test
npm --prefix frontend run build
```

Backend tests use a temporary SQLite database by default. Only point
`CLPI_TEST_DATABASE_URL` at a disposable PostgreSQL database whose name ends in
`_test`; the test suite recreates its schema.

Review the exact files being committed, then push your branch:

```powershell
git status
git add backend frontend docs
git diff --cached --check
git diff --cached --stat
git commit -m "Describe the change"
git push -u origin feature/describe-your-change
```

Add any changed root configuration files explicitly as needed. Never commit keys,
private inventory workbooks, database backups or uploaded customer data.

## Merge source changes

Open a GitHub pull request from your feature branch into `main`. Resolve conflicts
on your branch and run the affected checks before merging. To incorporate updates
from `main` into your feature branch:

```powershell
git fetch origin
git merge origin/main
```

After GitHub merges the pull request:

```powershell
git switch main
git pull --ff-only origin main
docker compose up --build -d
```

Use normal merges or pull requests rather than overwriting shared history with a
force push. Stop the local application with `docker compose down` when needed;
omit `-v` to retain database and upload volumes.
