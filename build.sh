#!/usr/bin/env bash
# Build script for Render

# Install dependencies
pip install -r requirements.txt

# Initialize database with scraped data
python scraper_module/scraper.py

echo "Build complete!"
