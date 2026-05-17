# Compound interest

A canonical Pixie example tool. Computes compound-interest growth on a starting principal with regular monthly contributions over a chosen horizon. Optionally shows balances deflated at 2.5% per year so the user can see purchasing power rather than nominal value.

Pixie launches this tool the same way it launches any other: it picks a free loopback port, runs `tools/example-compound-interest/.venv/Scripts/python.exe main.py --port <port>` (or the POSIX equivalent), polls `/healthz` until it returns 200, then proxies `/schema` and `/run` calls from the dashboard. The tool binds `127.0.0.1` only and ships no secrets.

To test manually, from this folder run `uv sync` once to provision the virtualenv, then `uv run python main.py --port 8000`. Then in another shell: `curl http://127.0.0.1:8000/healthz`, `curl http://127.0.0.1:8000/schema`, and `curl -X POST http://127.0.0.1:8000/run -H "Content-Type: application/json" -d '{"principal":10000,"annual_rate":5,"years":10,"compounding":12,"monthly_contribution":250,"inflation_adjusted":false}'`.
