# Tests

We use pytest with these markers:
- `unit` - pure unit tests
- `integration` - tests requiring external services
- `slow` - tests taking >5s
- `live` - tests hitting live APIs (skipped in CI)

```bash
pytest                                      # All tests
pytest -m "not integration and not live"    # Fast path
pytest -m unit                              # Just unit tests
```
