#!/bin/bash

# Discord Finance Bot - Development Setup Script
# This script helps set up the development environment

echo "🚀 Setting up Discord Finance Bot development environment..."

# Check if Python is installed
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 is not installed. Please install Python 3.8+ first."
    exit 1
fi

# Create virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv venv
else
    echo "✅ Virtual environment already exists"
fi

# Activate virtual environment
echo "🔄 Activating virtual environment..."
source venv/bin/activate

# Upgrade pip
echo "⬆ Upgrading pip..."
pip install --upgrade pip

# Install requirements
if [ -f "requirements.txt" ]; then
    echo "📋 Installing dependencies..."
    pip install -r requirements.txt
else
    echo "⚠️ requirements.txt not found. Installing basic dependencies..."
    pip install discord.py python-dotenv
fi

# Copy configuration files if they don't exist
echo "⚙ Setting up configuration files..."

if [ ! -f ".env" ]; then
    if [ -f ".env.example" ]; then
        cp .env.example .env
        echo "✅ Created .env from template"
    else
        echo "⚠️ .env.example not found. Creating basic .env file..."
        cat > .env << EOF
# Discord Bot Configuration
DISCORD_TOKEN=your_discord_token_here
REMINDER_CHANNEL_ID=0
DAILY_REMINDER_TIME=09:00
EOF
    fi
else
    echo "✅ .env already exists"
fi

if [ ! -f "src/config/config_settings.py" ]; then
    if [ -f "src/config/config_settings.example.py" ]; then
        cp src/config/config_settings.example.py src/config/config_settings.py
        echo "✅ Created config_settings.py from template"
    else
        echo "⚠️ config_settings.example.py not found"
    fi
else
    echo "✅ config_settings.py already exists"
fi

# Create necessary directories
echo "📁 Creating directories..."
mkdir -p data/uploads
mkdir -p data/sessions
mkdir -p src/config

# Install pre-commit hooks
echo "🔧 Installing pre-commit hooks..."
if command -v pre-commit &> /dev/null; then
    pre-commit install
    echo "✅ Pre-commit hooks installed"
else
    echo "⚠️ pre-commit not found. Run 'pip install pre-commit && pre-commit install' manually"
fi

echo ""
echo "🎉 Setup complete!"
echo ""
echo "📝 Next steps:"
echo "   1. Edit .env file with your Discord bot token"
echo "   2. Edit src/config/config_settings.py to add user IDs for mentions"
echo "   3. Run the bot: cd src && python bot.py"
echo ""
echo "💡 Don't forget to:"
echo "   - Set up your Discord bot in the Developer Portal"
echo "   - Invite the bot to your server with proper permissions"
echo "   - Enable Message Content Intent in the bot settings"
echo ""
