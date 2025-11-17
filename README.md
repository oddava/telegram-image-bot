# Telegram Image Bot

A scalable Telegram bot for image processing with background removal, built with modern Python stack and microservices architecture.

## Features

- **Image Processing**: Background removal using AI-powered algorithms
- **Multi-language Support**: English, Russian, Uzbek (i18n with Babel)
- **User Management**: Quota-based system with free and premium tiers
- **Monitoring**: Prometheus metrics and Grafana dashboards
- **Scalable Architecture**: Docker Compose with separate bot and processor services
- **Object Storage**: MinIO for image storage
- **Task Queue**: Celery with Redis for asynchronous processing
- **Database**: PostgreSQL with SQLAlchemy ORM and Alembic migrations

## Architecture

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Telegram Bot  │    │   Image Processor│    │   Monitoring    │
│   (aiogram)     │    │   (Celery)      │    │ (Prometheus)    │
└─────────────────┘    └─────────────────┘    └─────────────────┘
         │                       │                       │
         └───────────────────────┼───────────────────────┘
                                 │
         ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
         │   PostgreSQL    │    │     Redis       │    │     MinIO       │
         │   (Database)    │    │   (Task Queue)  │    │ (Object Storage)│
         └─────────────────┘    └─────────────────┘    └─────────────────┘
```

## Quick Start

### Prerequisites

- Docker and Docker Compose
- Python 3.11+ (for local development)
- Telegram Bot Token

### Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/oddava/telegram-image-bot
   cd telegram-image-bot
   ```

2. **Configure environment**
   ```bash
   cp .env.example .env
   # Edit .env with your configuration
   ```

3. **Start the services**
   ```bash
   make compose-up
   ```

4. **Run database migrations**
   ```bash
   make migrate
   ```

The bot will be available at your configured webhook URL, and monitoring services at:
- Grafana: `http://localhost:3000` (admin/admin)
- Prometheus: `http://localhost:9090`
- MinIO Console: `http://localhost:9001`

## Configuration

### Environment Variables

Key configuration options in `.env`:

```bash
# Bot Configuration
BOT_TOKEN=your_telegram_bot_token
BOT_WEBHOOK_URL=https://your-domain.com
BOT_SECRET_TOKEN=your_webhook_secret

# Database
DATABASE_URL=postgresql+asyncpg://user:password@postgres:5432/imagebot

# Redis & Celery
REDIS_URL=redis://redis:6379/0
CELERY_BROKER_URL=redis://redis:6379/1

# MinIO Storage
MINIO_ENDPOINT=minio:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
MINIO_BUCKET_NAME=image-bot-storage

# Processing
MAX_FILE_SIZE_MB=20
SUPPORTED_FORMATS=jpg,jpeg,png,webp,tiff
DEFAULT_QUOTA_FREE=10
DEFAULT_QUOTA_PREMIUM=1000
```

## Development

### Local Development

1. **Install dependencies**
   ```bash
   uv sync
   ```

2. **Start services**
   ```bash
   docker compose up postgres redis minio -d
   ```

3. **Run bot in polling mode**
   ```bash
   python -m bot.main
   ```

4. **Run processor worker**
   ```bash
   python -m processor.worker
   ```

### Project Structure

```
telegram-image-bot/
├── bot/                    # Telegram bot application
│   ├── handlers/          # Command and callback handlers
│   ├── middlewares/       # Bot middlewares (i18n, metrics, etc.)
│   ├── services/          # Bot services
│   └── locales/           # Translation files
├── processor/             # Image processing workers
│   └── tasks/            # Celery tasks
├── shared/               # Shared utilities
│   ├── core/            # Core utilities
│   ├── config.py        # Configuration management
│   ├── database.py      # Database setup
│   └── models.py        # SQLAlchemy models
├── configs/             # Configuration files
│   ├── grafana/        # Grafana dashboards
│   └── prometheus/     # Prometheus config
├── migrations/          # Database migrations
└── docker-compose.yml   # Service orchestration
```

## Available Commands

### Docker Compose
```bash
make compose-up      # Start all services
make compose-down    # Stop all services
make compose-logs    # View logs
make compose-ps      # Show running containers
```

### Database Migrations
```bash
make mm "migration_name"  # Create new migration
make migrate              # Run migrations
make downgrade <revision> # Rollback migration
```

### Internationalization
```bash
make babel-extract   # Extract translatable strings
make babel-update     # Update translation files
make babel-compile   # Compile translations
```

## Monitoring

The bot includes comprehensive monitoring:

- **Prometheus**: Metrics collection at `/metrics`
- **Grafana**: Pre-configured dashboards for:
  - Bot performance and usage
  - System resources
  - Task queue status
- **Health Checks**: `/health` endpoint for service status

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Submit a pull request