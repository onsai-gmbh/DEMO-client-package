import sentry_sdk
from src.server import app

sentry_sdk.init(
    dsn="https://86dc552825f0a6c75b44975b71e52553@o153517.ingest.sentry.io/4506359039000576",
    integrations=[
    ],
    traces_sample_rate=1.0,
    environment="local",
)


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0")

