# Persistent SQLite on Oracle Cloud Always Free

Render Free provides a public demo while its instance is running. Local SQLite data can disappear on spin-down, restart, or redeploy. Render Free cannot attach a persistent disk. [Render Free limitations](https://render.com/docs/free).

1. In your OCI home region, provision an **Always Free-eligible** VM and boot volume within your tenancy's included limits. An Ampere A1 Flex VM is an option when capacity is available. Verify the console's estimate before creating a resource. Idle instances can be reclaimed. [OCI Always Free resources](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm).
2. On the VM, install Docker Engine, the Compose plugin, Git, and a TLS reverse proxy such as Caddy. Clone the public repository. Copy `.env.example` to `.env`, set file permissions to `600`, and enter the two provider keys there. Keep `DATABASE_URL=sqlite:////data/app.db` and set `ALLOWED_ORIGINS` to the deployed frontend origin.
3. Run `docker compose up -d --build backend`. The named Docker volume stores SQLite on the VM disk across container recreation. Keep the boot volume or use a separately mounted Always Free-eligible block volume for Docker data if you need to recreate the VM. Back up the database using SQLite's backup API so the WAL is included in the snapshot.
4. Point a DNS name at the VM and proxy HTTPS to `127.0.0.1:8000`. Limit public OCI ingress to HTTP/HTTPS, restrict SSH to your own IP, and keep TCP port 8000 private. Verify the backend's HTTPS `/health` endpoint.
5. Set the frontend's `VITE_API_URL` to the OCI HTTPS endpoint and redeploy the static site. Send a message, run `docker compose down` followed by `docker compose up -d backend`, then fetch that session's history over HTTPS. Verify frontend CORS, inference, cache, and failover again.

Plan for a fresh database if the Render instance has already spun down. If an existing SQLite backup is available, restore it to the destination volume while the backend is stopped, then start the backend and verify the history endpoint.
