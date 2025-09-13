#!/bin/bash

# Setup script for host-based temporary file directory
# This script should be run on the server where Docker containers are deployed

echo "🔧 Setting up host-based temporary file directory..."

# Create the temp_uploads directory on host machine
echo "📁 Creating temp_uploads directory..."
mkdir -p ./temp_uploads

# Set proper permissions (777 to ensure Docker containers can write)
echo "🔐 Setting permissions..."
chmod 777 ./temp_uploads

# Create a test file to verify permissions
echo "✅ Testing write permissions..."
echo "test" > ./temp_uploads/test_file.txt
if [ -f "./temp_uploads/test_file.txt" ]; then
    echo "✅ Write permissions confirmed"
    rm ./temp_uploads/test_file.txt
else
    echo "❌ Write permission test failed"
    exit 1
fi

echo "📋 Directory info:"
ls -la ./temp_uploads

echo ""
echo "🚀 Setup complete! Now run:"
echo "   docker-compose down"
echo "   docker-compose up -d --build"
echo ""
echo "📁 Host directory: $(pwd)/temp_uploads"
echo "🐳 Container path: /app/temp_uploads"
echo ""
