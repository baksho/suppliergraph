#!/usr/bin/env sh
# UNVERIFIED: creates a repository through GraphDB's REST API. Parameter names follow GraphDB 10 docs as
# remembered when this was written; check them against your server's Workbench ("Setup > Repositories").
set -eu
HOST="${GRAPHDB_URL:-http://localhost:7200}"
curl -fsS -X POST "$HOST/rest/repositories" -H 'Content-Type: application/json' -d '{
  "id": "suppliergraph", "title": "SupplierGraph", "type": "graphdb",
  "params": { "ruleset": { "value": "empty" }, "enableContextIndex": { "value": "true" } }
}'
echo "created; load data with: SG_STORE=remote sg build-kg"
