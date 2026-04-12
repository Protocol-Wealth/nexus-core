# Contributing to Nexus Core

Thank you for your interest in contributing to Nexus Core. This document outlines our process for welcoming new contributors.

## Developer Certificate of Origin

All commits to this repository must be signed off under the [Developer Certificate of Origin (DCO)](https://developercertificate.org/) version 1.1.

By signing off your commits, you certify that:

1. The contribution was created in whole or in part by you and you have the right to submit it under the open source license indicated in the file; or
2. The contribution is based upon previous work that, to the best of your knowledge, is covered under an appropriate open source license and you have the right under that license to submit that work with modifications; or
3. The contribution was provided directly to you by some other person who certified (1), (2), or (3) and you have not modified it.
4. You understand and agree that this project and the contribution are public and that a record of the contribution (including all personal information you submit with it, including your sign-off) is maintained indefinitely.

Sign off your commits using the `-s` flag:

```bash
git commit -s -m "feat: add Monte Carlo retirement simulation"
```

This appends a `Signed-off-by: Your Name <your.email@example.com>` line to the commit message.

## How to Contribute

### Reporting Bugs

Open an issue describing:
- What you expected to happen
- What actually happened
- Steps to reproduce
- Your Python version, OS, and nexus-core version

### Suggesting Features

Open an issue with the `enhancement` label. Describe:
- The problem you're trying to solve
- Why existing functionality doesn't address it
- Your proposed solution (if you have one)

### Submitting Pull Requests

1. **Fork** the repository
2. **Create a branch** from `main`: `git checkout -b feat/your-feature`
3. **Write tests** for your changes (we use pytest)
4. **Run the test suite** locally: `pytest tests/`
5. **Run the linter**: `ruff check src/ tests/`
6. **Sign off your commits**: `git commit -s -m "feat: your feature"`
7. **Push** to your fork and open a PR

### PR Guidelines

- One logical change per PR
- Include tests for new functionality
- Update documentation if you change behavior
- Follow existing code style (`ruff format`)
- Keep PRs focused — small PRs merge faster than large ones

## Development Setup

```bash
# Clone your fork
git clone https://github.com/YOUR_USERNAME/nexus-core.git
cd nexus-core

# Install dev dependencies
pip install -e ".[all,dev]"

# Run tests
pytest tests/

# Run linter
ruff check src/ tests/
ruff format --check src/ tests/

# Type check
mypy src/
```

## Code Style

- **Line length:** 100 chars
- **Formatting:** `ruff format` (Black-compatible)
- **Linting:** `ruff check`
- **Type hints:** Required for all public APIs
- **Docstrings:** Google style, required for all public functions

## Testing

We use pytest with these markers:
- `unit` — pure unit tests (default)
- `integration` — tests requiring external services
- `slow` — tests taking >5s
- `live` — tests hitting live APIs (skipped in CI)

Run only unit tests: `pytest -m "not integration and not live and not slow"`

## Attribution

When adding third-party code or ideas:
1. Add full copyright notice and license to [NOTICE](NOTICE)
2. Add full license text to [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md)
3. Add provenance details to [docs/attribution.md](docs/attribution.md)
4. Update [README.md](README.md) "Built on" section if appropriate

## Upstream Contributions

If you find a bug or improvement in one of our dependencies (PyPortfolioOpt, edgartools, etc.), we encourage you to contribute upstream first, then pin the new version here.

## License

By contributing, you agree that your contributions will be licensed under the [Apache License 2.0](LICENSE).

## Code of Conduct

Please read our [Code of Conduct](CODE_OF_CONDUCT.md) before contributing.

## Getting Help

- **Questions:** [GitHub Discussions](https://github.com/Protocol-Wealth/nexus-core/discussions)
- **Bugs:** [GitHub Issues](https://github.com/Protocol-Wealth/nexus-core/issues)
- **Security issues:** email security@protocolwealthllc.com (see [SECURITY.md](SECURITY.md))
