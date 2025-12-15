#!/bin/bash
# Setup script for Render deployment
pip install -r requirements.txt
python init_db.py || true

