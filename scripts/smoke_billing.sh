#!/bin/bash
set -e
echo "=== B-2 billing smoke ==="
TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/token \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=developer&password=dev123" \
  | python -c "import json,sys;print(json.load(sys.stdin).get('access_token',''))")
ADMIN=$(curl -s -X POST http://localhost:8000/api/v1/auth/token \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=admin&password=admin123" \
  | python -c "import json,sys;print(json.load(sys.stdin).get('access_token',''))")
echo "dev_token_len=${#TOKEN}, admin_token_len=${#ADMIN}"

echo "--- GET /billing/me (developer, expect auto-Free) ---"
curl -s -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/billing/me | python -m json.tool

echo "--- POST /billing/subscribe (admin → developer to Dev plan) ---"
curl -s -X POST -H "Authorization: Bearer $ADMIN" \
  -H "Content-Type: application/json" \
  -d '{"user_id":"developer","plan_code":"dev"}' \
  http://localhost:8000/api/v1/billing/subscribe | python -m json.tool

echo "--- GET /billing/me (developer, expect Dev now) ---"
curl -s -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/billing/me | python -m json.tool

echo "--- POST /billing/subscribe by non-admin (developer attempts admin call → expect 403) ---"
curl -s -o /dev/null -w "non_admin_subscribe_http=%{http_code}\n" \
  -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"user_id":"developer","plan_code":"team"}' \
  http://localhost:8000/api/v1/billing/subscribe

echo "--- invalid plan_code ---"
curl -s -o /dev/null -w "invalid_plan_http=%{http_code}\n" \
  -X POST -H "Authorization: Bearer $ADMIN" \
  -H "Content-Type: application/json" \
  -d '{"user_id":"developer","plan_code":"premium"}' \
  http://localhost:8000/api/v1/billing/subscribe
