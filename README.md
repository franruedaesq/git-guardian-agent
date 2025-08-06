# Git Guardian Agent

An autonomous agent for CI pipelines to enforce commit standards and detect secrets. This project is currently in Phase 0: Foundation & Scaffolding.

## Agent Interface Schema

The agent communicates via a simple, file-based JSON interface.

### Input (`input.json`)

The CI runner must provide a JSON file with the following structure:

```json
{
  "commit_message": "feat(api): add new user endpoint",
  "commit_diff": "--- a/src/server.js\n+++ b/src/server.js\n@@ -1,4 +1,5 @@\n const express = require('express');\n const app = express();\n+const API_KEY = \"sk-live-12345abcdefg\"; // Example of a secret\n \n app.get('/', (req, res) => {\n   res.send('Hello World!');"
}
```

### Output (STDOUT)

The agent will print a single JSON object to standard output (`stdout`).

#### On Success:

```json
{
  "status": "PASS",
  "reason": "All checks passed."
}
```

#### On Failure:

```json
{
  "status": "FAIL",
  "reason": "Secret Detected: A pattern resembling an API Key was found in `src/server.js`."
}
```
