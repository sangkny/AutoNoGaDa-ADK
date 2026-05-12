#!/bin/bash
set -e
echo "=== B-5 admin/stats smoke ==="
ADMIN=$(curl -s -X POST http://localhost:8000/api/v1/auth/token \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=admin&password=admin123" \
  | python -c "import json,sys;print(json.load(sys.stdin).get('access_token',''))")
TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/token \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=developer&password=dev123" \
  | python -c "import json,sys;print(json.load(sys.stdin).get('access_token',''))")

echo "--- admin/stats ---"
curl -s -H "Authorization: Bearer $ADMIN" http://localhost:8000/api/v1/billing/admin/stats | python -m json.tool

echo "--- usage history (developer) ---"
curl -s -H "Authorization: Bearer $TOKEN" "http://localhost:8000/api/v1/billing/usage?months=3" | python -m json.tool

echo "--- usage timeline (developer, days=7) ---"
curl -s -H "Authorization: Bearer $TOKEN" "http://localhost:8000/api/v1/billing/usage/timeline?days=7" | python -m json.tool

echo "--- non-admin /admin/stats → 403 ---"
curl -s -o /dev/null -w "non_admin_stats_http=%{http_code}\n" \
  -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/billing/admin/stats
