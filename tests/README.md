# Tests

We use pytest with these markers:
- `unit` - pure unit tests
- `integration` - tests requiring external services
- `slow` - tests taking >5s
- `live` - tests hitting live APIs (skipped in CI)

```bash
pytest                                      # full hermetic suite
ruff check src/ tests/                      # lint
mypy --strict src/nexus_core/               # type check
pytest -m "not integration and not live"    # fast path
pytest -m unit                              # just unit tests
```
