#!/bin/bash

# Build the Docker image
IMAGE_NAME="claude-flow"

echo "Building Claude Flow Docker image..."
docker build -t $IMAGE_NAME .

if [ $? -eq 0 ]; then
    echo "Build successful!"
    echo "You can now run ./start.sh to begin"
else
    echo "Build failed!"
    exit 1
fi