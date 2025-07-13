#!/bin/bash

# Fix permissions on the home directory if needed
if [ -d /home/agent ]; then
    sudo chown -R agent:agent /home/agent
fi

# Execute the original command
exec "$@"