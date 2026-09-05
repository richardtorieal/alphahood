module.exports = {
  apps: [
    {
      name: "alphahood-monitor",
      script: "python",
      args: "-m src.agent --monitor",
      interpreter: "none",
      env: {
        NODE_ENV: "production",
      }
    },
    {
      name: "alphahood-review",
      script: "python",
      args: "-m src.agent --review",
      cron_restart: "0 17 * * *", // Run at 5 PM daily
      autorestart: false,
      interpreter: "none"
    }
  ]
};
