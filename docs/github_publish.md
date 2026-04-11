# GitHub Publish

## Safe-to-publish files

- source code in `src/`
- tests in `tests/`
- public configs such as `config/app.toml.example`
- public docs in `docs/`
- `.env.example`

## Files that should stay local

- `.env`
- any VPS-specific service file that contains secrets
- private notes with tokens, chat IDs, or server IPs

## Before first push

1. Check `.gitignore` and confirm `.env` is ignored.
2. Make sure `config/app.toml` does not contain secrets you do not want in GitHub.
3. Keep real Telegram credentials only in `.env`.
4. Run:
   - `python -m unittest discover -s tests -v`
   - `PYTHONPATH=src python -m density_screener.cli doctor`

## Suggested first publish flow

1. Create an empty GitHub repository.
2. Add the remote:
   - `git remote add origin <your-repo-url>`
3. Stage files:
   - `git add .`
4. Create the first commit:
   - `git commit -m "Initial density screener"`
5. Push:
   - `git push -u origin main`

## After push

- rotate the Telegram bot token if it was ever pasted into chat or stored in a tracked file
- set VPS-specific values in `.env`
- re-run `doctor` and `test-telegram` on the server
