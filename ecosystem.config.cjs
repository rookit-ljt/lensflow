module.exports = {
  apps: [
    {
      name: "lensflow-api",
      cwd: "./apps/api",
      script: "./.venv/bin/uvicorn",
      args: "app.main:app --host 127.0.0.1 --port 8000",
      interpreter: "none",
      autorestart: true,
      max_restarts: 10,
      env: {
        PYTHONUNBUFFERED: "1",
      },
    },
    {
      name: "lensflow-web",
      cwd: "./apps/web",
      script: "node",
      args: "./node_modules/next/dist/bin/next start -p 3001",
      interpreter: "none",
      autorestart: true,
      max_restarts: 10,
      env: {
        NODE_ENV: "production",
        PORT: "3001",
        NEXT_DIST_DIR: ".next-prod",
        NEXT_PUBLIC_API_URL: "",
      },
    },
  ],
};
