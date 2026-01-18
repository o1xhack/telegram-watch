# Acceptance (MVP)

1) Setup & login
- Fresh Mac env can:
  - create venv
  - pip install -e .
  - start `python -m tgwatch doctor --config config.toml` (pass)

2) Capture
- In target group, when tracked user posts:
  - text message -> stored
  - reply message -> stored with reply snapshot
  - photo message -> media downloaded and stored path recorded

3) Report
- `python -m tgwatch once --config config.toml --since 2h`:
  - creates a new reports/.../index.html
  - HTML renders with images (relative paths valid)

4) Control commands
- In control chat:
  - /help responds
  - /last <tracked_user_id> 5 responds with 5 items

5) Open-source hygiene
- Repo includes .gitignore that excludes config.toml, data/, reports/, *.session
- README includes privacy & ToS warning and "user is responsible"
