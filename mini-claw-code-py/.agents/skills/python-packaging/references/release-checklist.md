# Python Release Checklist

1. Confirm the current version in `pyproject.toml`.
2. Update release notes or changelog entries if the repository uses them.
3. Build distributions with `uv build`.
4. Inspect the generated artifacts before publishing.
5. Publish only after the user confirms the target registry and credentials.
