"""SEC EDGAR Integration.

Wraps edgartools (which includes a built-in MCP server) and Arelle for
XBRL validation.

Third-party libraries:
- edgartools (MIT) - https://github.com/dgunning/edgartools
  Accepted into Anthropic's Claude for Open Source program
- Arelle (Apache 2.0) - https://github.com/Arelle/Arelle
- sec-parser (MIT) - https://github.com/alphanome-ai/sec-parser
- sec-edgar-downloader (MIT) - https://github.com/jadchaar/sec-edgar-downloader

Install with: pip install nexus-core[edgar]
"""
